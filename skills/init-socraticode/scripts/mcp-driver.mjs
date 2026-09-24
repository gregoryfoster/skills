#!/usr/bin/env node
// mcp-driver.mjs — FENCED FALLBACK for gotcha A.
//
// The native path is preferred: restart Claude Code, run the ToolSearch
// prefetch, and call codebase_index / codebase_status as normal MCP tools.
// Use THIS driver only when a session reports the SocratiCode MCP server
// "Connected" but never injects the codebase_* tools into the toolset (so the
// tools cannot be called the normal way).
//
// It drives the plugin's stdio MCP server directly over newline-delimited
// JSON-RPC 2.0: initialize -> notifications/initialized -> tools/call.
//
// Design guarantees (see the issue's gotchas):
//   B — indexing runs INSIDE the server process, so we keep it alive and poll.
//   C — "100% embedded" is NOT done; we gate on the index run having completed
//       AND graph READY AND context artifacts N/N before returning success.
//   G — we OWN the child and kill it by child.pid on exit. We never pkill by
//       cmdline, so there is no self-match footgun.
//   H — status strings are parsed loosely (regex, both artifact shapes).
//   J — completion is NOT keyed on a parsed "100%". The server prints its
//       progress percentage only while indexing is in flight, so the line is
//       gone by the time the run is done and `pct === 100` was only ever
//       observable by winning a race with the poll interval (#85).
//   M — tools report failure by RETURNING a string, not throwing. Every reply
//       the driver acts on is classified explicitly; awaiting is not checking.
//
// Wire contract exercised end-to-end against socraticode 1.6.x (the build the
// plugin runs via `npx -y socraticode`) during the #85 field report. Confirmed
// live: `query` is codebase_search's argument name, protocolVersion
// '2024-11-05' is accepted, and every tool takes its target as `projectPath`.
// If the server's tool names or status strings change, update the PARSERS and
// TOOL NAMES sections below.
//
// Server entry resolution is NOT one path (#85/3b). The plugin launches the
// server as `npx -y socraticode`, so on a plugin-only host the package lives in
// the npx cache — reachable by neither require.resolve() nor `npm root`. See
// resolveServerLaunch(), which follows the plugin's own launch chain, and
// prefers a deliberately pinned pre-install over it when one exists (#295) —
// that plugin command installs at every launch, which is the single most
// expensive thing this skill does.
//
// Commands and environment variables are documented in one place — the USAGE
// constant at the bottom of this file. Run `node mcp-driver.mjs --help`.
// (This header used to carry a second copy; it had already drifted a commit
// after the interface changed.)

import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import {
  resolve as resolvePath, join as joinPath, isAbsolute as isAbsolutePath, dirname as dirnamePath,
} from 'node:path';
import { fileURLToPath } from 'node:url';

const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS || 15000);
const INDEX_TIMEOUT_MS = Number(process.env.INDEX_TIMEOUT_MS || 7200000);

// ── server launch resolution (never hard-code dist/index.js) ────────────────
// Returns { command, args, env, source } rather than a bare path: the plugin
// launches the server through npx with its own node binary and PATH, and only a
// command+args pair can express that (#85/3b).

function nodeLaunch(entry, source) {
  return { command: process.execPath, args: [entry], env: {}, source };
}

// Most-recently-modified-first directory listing. A heuristic, not an ordering
// by version — used only where no authoritative record exists (the npx cache),
// and as the fallback scan when installed_plugins.json can't be read.
function subdirsNewestFirst(dir) {
  let names;
  try { names = readdirSync(dir); } catch { return []; }
  return names
    .map((n) => joinPath(dir, n))
    .map((p) => { try { return { p, mtime: statSync(p).mtimeMs }; } catch { return null; } })
    .filter(Boolean)
    .sort((a, b) => b.mtime - a.mtime)
    .map((e) => e.p);
}

// The plugin's own mcp.json records the exact command, args, and PATH the
// session uses to start this server — the right thing to reuse when nothing has
// been pinned deliberately.
//
// It is authoritative over the COMMAND, and #85 read that as authority over the
// version too. It is not: the command it records is `npx -y --prefer-online
// socraticode@latest`, so reusing it verbatim reproduces a spec that resolves
// at launch. Driver and session then agree only because both float and both
// launched in the same window, which is also why `graphVerdict` has to take the
// running server's version rather than the one on disk (#297). A pin ahead of
// this is what turns that coincidence into a decision; `pinDriftFinding` is
// what keeps the resulting gap measured rather than silent (#295).
//
// The chain that finds it is `pluginServerFromVersionDir` below; this function
// is the loop over candidate version directories around it.

// Claude Code expands `${VAR}` and `${VAR:-default}` in a server definition's
// command, args and env before launching it. A definition this driver reads
// straight off disk has NOT been through that, so it has to expand them here or
// it spawns a command literally named `${SOCRATICODE_COMMAND:-npx}` (#309).
//
// An unset variable with no default is left verbatim rather than emptied. That
// matches Claude Code, which loads the config and reports a missing-variable
// warning, and it keeps a misconfiguration visible: an empty command fails with
// nothing to grep for, where the literal `${VAR}` names itself in the error.
const VAR_PATTERN = /\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}/g;

//
// `${VAR:-d}` is spelled like shell `:-` but does NOT behave like it. Measured
// against Claude Code 2.1.71 with a throwaway plugin whose manifest referenced
// a file containing both forms: unset took the default, a set value won, and a
// value set to the EMPTY STRING produced an empty argv element rather than the
// default. So it is `-` semantics — absent means undefined, not falsy — and
// only `undefined` may fall through here. Treating empty as absent would hand
// the session one command and this driver another, on the exact host someone
// pinned to stop that happening.
function expandVars(value, extra = {}) {
  if (typeof value === 'string') {
    return value.replace(VAR_PATTERN, (whole, name, fallback) => {
      const v = extra[name] ?? process.env[name];
      if (v !== undefined) return v;
      return fallback !== undefined ? fallback : whole;
    });
  }
  if (Array.isArray(value)) return value.map((v) => expandVars(v, extra));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, expandVars(v, extra)]));
  }
  return value;
}

// Where one plugin version directory declares its MCP servers.
//
// Claude Code reads `.claude-plugin/plugin.json` and follows its `mcpServers`
// field, which the plugin reference types `string | array | object` — a path,
// several paths, or an inline definition. Following that field is the whole
// point: this driver used to read `mcp.json` while Claude Code read the dotted
// `.mcp.json` named by that manifest. The two files are byte-identical in every
// release so far, so the bug was invisible — and SocratiCode#180 is accepted
// precisely to make them differ, giving Claude Code an overridable launcher
// while Codex and Cursor keep the literal one (#309).
//
// Guessing either filename would then resolve the wrong host's launcher, or,
// once the definition moves inline, resolve nothing at all and fall through to
// the npx cache — a worse answer than the stale one, arrived at silently.
function pluginServerFromVersionDir(versionDir) {
  const manifest = joinPath(versionDir, '.claude-plugin', 'plugin.json');
  let declared;
  // The PLUGIN's version, carried alongside for the report (#305). It names the
  // plugin, not the server: a definition that launches `socraticode@latest`
  // runs whatever that resolved to when the session started.
  let pluginVersion = null;
  try {
    const parsed = JSON.parse(readFileSync(manifest, 'utf8'));
    declared = parsed?.mcpServers;
    if (typeof parsed?.version === 'string' && parsed.version.trim()) pluginVersion = parsed.version.trim();
  } catch { /* no manifest, or unreadable — the filename fallback below */ }

  const fromFile = (rel, why) => {
    const path = resolvePath(versionDir, rel);
    try {
      const server = JSON.parse(readFileSync(path, 'utf8'))?.mcpServers?.socraticode;
      return server ? { server, source: `plugin ${why} (${path})`, pluginVersion } : null;
    } catch { return null; }
  };

  if (typeof declared === 'string') {
    const hit = fromFile(declared, `${declared} via plugin.json`);
    if (hit) return hit;
  } else if (Array.isArray(declared)) {
    // First file that defines the server wins. Claude Code merges several
    // sources and its rules may prefer the last; no shipped plugin uses the
    // array form, so this is unobservable today and stated rather than guessed.
    for (const rel of declared) {
      if (typeof rel !== 'string') continue;
      const hit = fromFile(rel, `${rel} via plugin.json`);
      if (hit) return hit;
    }
  } else if (declared && typeof declared === 'object' && declared.socraticode) {
    return { server: declared.socraticode, source: `plugin.json inline (${manifest})`, pluginVersion };
  }

  // No usable manifest. The dotted name first: it is the one Claude Code's own
  // manifest has always pointed at, so it is the better guess of the two.
  for (const name of ['.mcp.json', 'mcp.json']) {
    const hit = fromFile(name, name);
    if (hit) return hit;
  }
  return null;
}

// Does an installed_plugins.json entry load in a session at `project`? Claude
// Code's own rule, read from the 2.1.278 binary: a `user` or `managed` entry
// applies everywhere; a `project` or `local` one only where its projectPath is
// the project, or names the same repository — so a worktree of it matches.
// Each install APPENDS an entry, and the loader takes the first applicable one
// in registry order whose install is present; there is no scope precedence to
// apply beyond that order (#305 CR 28).
//
// It matters because #305 made the entry decide severity: sessionServer()
// reads the version the session's server runs from it, and a project entry
// for some other checkout, taken first-found, judged this project's graph
// against a server its session never loads.
//
// "The same repository" is the shared git dir, not the main checkout: a bare
// repository's worktrees have no main checkout, so mainCheckoutOf() is null
// for every one of them, while the binary's canonical root for them is the
// bare dir — an entry recorded at one worktree applied at another for Claude
// Code and not here (#305 CR 50). --git-common-dir is that dir for a bare
// repo's worktrees, and <main>/.git for an ordinary repo's, so comparing it
// agrees with the binary for both.
function registryEntryApplies(entry, project) {
  if (entry?.scope === 'user' || entry?.scope === 'managed') return true;
  if (typeof entry?.projectPath !== 'string' || !entry.projectPath) return false;
  const here = realOrSelf(resolvePath(project));
  if (realOrSelf(resolvePath(entry.projectPath)) === here) return true;
  const repo = gitCommonDir(here);
  if (repo === null) return false;
  const theirs = gitCommonDir(resolvePath(entry.projectPath));
  return theirs !== null && realOrSelf(theirs) === realOrSelf(repo);
}

// `project` is the checkout whose session is in question: the project being
// checked where there is one, else the cwd, which is the session's own when
// the health hook runs this.
function launchFromPluginConfig({ project = process.cwd() } = {}) {
  const claudeDir = process.env.CLAUDE_CONFIG_DIR || joinPath(homedir(), '.claude');

  // installed_plugins.json records the install path of the version actually
  // enabled. Prefer it over scanning the cache: with two versions cached, an
  // mtime scan can pick the one the session ISN'T running, which is precisely
  // the drift reading the plugin's own config exists to avoid.
  //
  // Only the entries that load at `project` count. When the registry lists
  // the plugin and none of them does, the session there has no plugin, and a
  // cache scan would find the other project's version and report it as this
  // one's — so that is an answer, not a reason to scan. The same holds when
  // entries apply and none of their installs loads: Claude Code's loader
  // takes an applying entry or nothing, and never scans the cache (#305 CR
  // 49). The scan is for a host with no registry record at all.
  const installed = [];
  let listed = false;
  try {
    const registry = JSON.parse(readFileSync(joinPath(claudeDir, 'plugins', 'installed_plugins.json'), 'utf8'));
    for (const entry of registry?.plugins?.['socraticode@socraticode'] ?? []) {
      listed = true;
      if (entry?.installPath && registryEntryApplies(entry, project)) installed.push(entry.installPath);
    }
  } catch { /* no registry, or unreadable — fall back to the cache scan */ }

  const cacheDir = joinPath(claudeDir, 'plugins', 'cache', 'socraticode', 'socraticode');
  for (const versionDir of listed ? installed : subdirsNewestFirst(cacheDir)) {
    const hit = pluginServerFromVersionDir(versionDir);
    if (!hit) continue;
    // Expanded before validation, so a definition whose command is entirely a
    // variable still has to produce a real command and an args array.
    // `${CLAUDE_PLUGIN_ROOT}` is the variable Claude Code's own inline example
    // uses, and it is the natural way for a plugin to name a bundled engine.
    // The host sets it to the plugin directory; we know that directory, so we
    // supply it rather than leaving the literal to fail at spawn. A value
    // already in the environment wins, since that is the host's own answer.
    const server = expandVars(hit.server, { CLAUDE_PLUGIN_ROOT: versionDir });
    if (server?.command && Array.isArray(server.args)) {
      return {
        // Which variable the package spec is read from, off the UNEXPANDED
        // definition — `SOCRATICODE_SPEC` since upstream 0c33776, null for a
        // build that hardcodes it. That is the difference between "set the
        // variable" and "update the plugin first" as a remedy (#327).
        specVariable: specVariableOf(hit.server),
        command: server.command,
        args: server.args,
        env: server.env && typeof server.env === 'object' ? server.env : {},
        source: hit.source,
        // Marks the one launch that IS the session's own definition, so the
        // builder check can tell "this check ran what the session runs" from
        // "this check ran something else" without parsing `source` (#305).
        plugin: true,
        pluginVersion: hit.pluginVersion ?? null,
      };
    }
  }
  return null;
}

// The variable a definition's `socraticode[@…]` argument is spelled with, as
// `${NAME}` or `${NAME:-socraticode@…}`, or null when the spec is a literal.
function specVariableOf(server) {
  for (const a of Array.isArray(server?.args) ? server.args : []) {
    const m = typeof a === 'string' && /^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-socraticode(?:@[^}]*)?)?\}$/.exec(a);
    if (m) return m[1];
  }
  return null;
}

// A deliberately pre-installed, pinned server — the one launch path that
// installs nothing (#295).
//
// The measured reason this exists ahead of the plugin's own command: that
// command is `npx -y --prefer-online socraticode@latest`, and `--prefer-online`
// revalidates against the registry on EVERY launch. On broker a cold one
// reached 1.2 G at the cgroup and carried all 126 MemoryHigh throttle events,
// against 75 MB for the same workload from a pre-installed entry. The health
// hook runs this driver from SessionStart once per UTC day, concurrently with
// the plugin's own launch of the identical command, so on any day the package
// moved that is two simultaneous installs — unattended.
//
// Absent, it resolves nothing and the chain below is unchanged, so this is
// inert on every host that has not pre-installed. `npm install --prefix <dir>
// socraticode@<version>` is the layout it expects.
function pinDir() {
  return process.env.SOCRATICODE_PIN_DIR || joinPath(homedir(), '.socraticode', 'pin');
}

// The pin's own version, read from the package it installed — never inferred
// from the directory name, which records nothing and can be renamed.
function pinVersion(dir) {
  try {
    const v = JSON.parse(readFileSync(joinPath(dir, 'node_modules', 'socraticode', 'package.json'), 'utf8'))?.version;
    return typeof v === 'string' && v.trim() ? v.trim() : null;
  } catch { return null; }
}

function launchFromPin() {
  const dir = pinDir();
  const entry = joinPath(dir, 'node_modules', 'socraticode', 'dist', 'index.js');
  if (!existsSync(entry)) return null;
  const v = pinVersion(dir);
  return { ...nodeLaunch(entry, `pinned install ${v ? `v${v} ` : ''}(${dir})`), pinned: true, pinVersion: v };
}

// Does the plugin's recorded command still resolve at LAUNCH time? A pin can
// only diverge from something that moves: against a plugin whose mcp.json names
// an exact version there is nothing to report, and saying so anyway would be a
// daily finding about a host that is already consistent.
//
// Returns the floating spec, or null when the plugin is absent or pinned.
// `p` defaults to a fresh read; a caller that already holds the plugin's
// definition passes it, so one run reads the config tree once.
function pluginSpecFloats(p = launchFromPluginConfig()) {
  const spec = npxSpec(p);
  if (!spec) return null;
  const tag = spec.includes('@') ? spec.slice(spec.indexOf('@') + 1) : '';
  // A bare name and `@latest` both float; only a literal x.y.z is fixed. A
  // range is deliberately counted as floating — it resolves at launch too.
  return /^\d+\.\d+\.\d+$/.test(tag) ? null : spec;
}

// The `socraticode[@…]` argument of an npx-style launch, or null for any other.
// Only an npx-style launch resolves late. A recorded interpreter-and-path is as
// fixed as a pin is, whatever version it happens to be.
function npxSpec(p) {
  if (!p || !/(^|[\\/])npx(\.\w+)?$/.test(p.command)) return null;
  return p.args.find((a) => typeof a === 'string' && /^socraticode(@|$)/.test(a)) || null;
}

// The version a plugin definition FIXES, or null when it fixes none (#305).
//
// Two shapes fix one, and both are read rather than inferred. An npx launch of
// a literal `socraticode@x.y.z` names it. An interpreter-and-path launch runs
// whatever package that path sits in, so the version is that package's own
// package.json — the same rule pinVersion() applies to the pin, walked up from
// each absolute argument because the path may name `dist/index.js` or a `bin`
// shim. A floating spec fixes nothing, and neither does a path whose package
// cannot be read: null, never the plugin's own version, which names the plugin
// and not what its definition launches.
function pluginLaunchVersion(p) {
  if (!p) return null;
  const spec = npxSpec(p);
  if (spec) {
    const tag = spec.includes('@') ? spec.slice(spec.indexOf('@') + 1) : '';
    return /^\d+\.\d+\.\d+$/.test(tag) ? tag : null;
  }
  if (/(^|[\\/])npx(\.\w+)?$/.test(p.command)) return null;
  for (const arg of [p.command, ...p.args]) {
    if (typeof arg !== 'string' || !isAbsolutePath(arg)) continue;
    // Bounded: a package's entry sits a few levels below its package.json, and
    // an unbounded walk from `/usr/bin/node` would read every ancestor for
    // nothing.
    let dir = arg;
    for (let depth = 0; depth < 6; depth += 1) {
      const up = dirnamePath(dir);
      if (up === dir) break;
      dir = up;
      try {
        const pkg = JSON.parse(readFileSync(joinPath(dir, 'package.json'), 'utf8'));
        if (pkg?.name === 'socraticode' && typeof pkg.version === 'string' && pkg.version.trim()) {
          return pkg.version.trim();
        }
      } catch { /* no package.json here — keep walking */ }
    }
  }
  return null;
}

// ── which server answers the SESSION's queries (#305) ───────────────────────
// The graph is persisted, and whichever server rebuilds it stamps its own
// version on it. Under Claude Code that is the plugin's session server — the
// one every native `codebase_*` call and every `codebase_graph_build` goes to —
// and it need not be the server this driver launched. On CannObserv/power-map
// the check compared a graph the session's server had built at v1.13.1 against
// the driver's own v1.14.0 launch, called it stale, and prescribed
// codebase_graph_build; the rebuild ran through the session's server, re-stamped
// v1.13.1 in 5.8s, and the finding came back byte-identical.
//
// So the builder is judged against the session's server wherever this driver
// can KNOW its version, and the answer says how it knows:
//
//   - the plugin's definition fixes a version (pluginLaunchVersion) — read
//     from the definition, or, when this driver ran that same definition, from
//     the handshake, which is the better witness of the two;
//   - the definition floats (`npx … socraticode@latest`) — the session
//     resolved it when it started, which this driver cannot see, so the
//     version is null and the basis says why. #305 read the plugin cache's
//     directory name as the session's server version; that directory names the
//     PLUGIN, and the 1.13.1 plugin it named launches `socraticode@latest`.
//   - no plugin definition at all — nothing records which server that is.
//
// Pure over its inputs, so every branch is a fixture without a server.
// → { version: string|null, basis: string, plugin: { version, launches }|null }
function sessionServer({ launch, plugin, checkVersion }) {
  if (!plugin) {
    return { version: null, basis: 'no Claude Code plugin definition was found', plugin: null };
  }
  const described = {
    version: plugin.pluginVersion ?? null,
    launches: npxSpec(plugin) ?? [plugin.command, ...plugin.args].join(' '),
  };
  const fixed = pluginLaunchVersion(plugin);
  // `launch.plugin` says the check launched A plugin definition, not which:
  // the check resolves its own from the entry applying at its project, and a
  // caller that read the two at different projects had this branch report the
  // check's handshake as the session's, beside a definition launching another
  // version (#305 CR 42). The source names the file the definition was read
  // from, so equal sources are one definition.
  if (fixed && launch?.plugin === true && launch.source === plugin.source) {
    return {
      version: checkVersion || fixed,
      basis: 'the plugin\'s own definition, which this check launched too',
      plugin: described,
    };
  }
  if (fixed) {
    return { version: fixed, basis: `the plugin's definition fixes it: ${described.launches}`, plugin: described };
  }
  const floating = pluginSpecFloats(plugin);
  if (floating) {
    return {
      version: null,
      basis: `the plugin launches '${floating}', which the session resolved when it started`,
      plugin: described,
    };
  }
  return {
    version: null,
    basis: `the plugin's definition (${described.launches}) names no version this check can read`,
    plugin: described,
  };
}

// What that floating spec resolves to right now. Bounded to the same budget
// preflight's Node gate uses, and a failure is a stated unknown rather than an
// assumption in either direction.
//
// Last line only: deleting newlines from a multi-line reply CONCATENATES it, so
// `1.13.1\n1.13.2` would read as a plausible 1.13.11 — the same trap preflight
// documents at its own registry read.
function registryLatest() {
  // `timeout` is the bound that matters, and it is not belt-and-braces with the
  // npm flags below. spawnSync BLOCKS the event loop, and health-check's
  // ceiling is a setTimeout — a blocked loop cannot fire it, so for however
  // long this call runs, HEALTH_TIMEOUT_MS is deaf. npm's own flags are a
  // request npm has to honour; this one is the kernel killing the child.
  const out = spawnSync(
    'npm',
    ['view', 'socraticode', 'version', '--silent', '--fetch-timeout=5000', '--fetch-retries=1'],
    { encoding: 'utf8', timeout: 8000 }
  );
  if (out.status !== 0 || !out.stdout) return null;
  const v = out.stdout.trim().split('\n').pop().trim();
  return /^\d+\.\d+\.\d+/.test(v) ? v : null;
}

// The finding a pin's measured state earns, as one pure decision — separated
// from the two impure readings that feed it (the filesystem's pin and the
// registry's answer) so `parser-selftest.mjs` can pin every branch to a fixture
// without a server, a network or a clock.
//
// Always returns a finding, never null: this is only reached when a pin and a
// floating plugin both exist, and at that point "nothing printed" and "the
// check never ran" would be the same report. Two spellings of not-measured is
// the defect #297 removed.
function pinDriftFinding({ running, floatingSpec, resolves, pinPath, specVariable = null }) {
  const note = (message) => ({ severity: SEVERITY.note, message });
  // The other half of the fix, offered only where the installed plugin reads
  // the variable — on a build that hardcodes its spec it would do nothing, and
  // a remedy that changes nothing is what #326 had to take back (#327).
  const pinSession = specVariable && running
    ? `, or pin the session to the driver: ${specVariable}=socraticode@${running} in the repo's settings env block`
    : '';
  if (!running) {
    return note(`pinned launch, but no server version was recorded, so drift against '${floatingSpec}' was NOT measured`);
  }
  if (!resolves) {
    return note(`pinned at ${running}; the registry did not answer, so drift against '${floatingSpec}' was NOT measured`);
  }
  if (versionGap(running, resolves) === 'feature') {
    return {
      severity: SEVERITY.defect,
      message:
        `pinned server ${running}, but the session's plugin launches '${floatingSpec}', which resolves to `
        + `${resolves} — two different feature releases writing one store; re-pin deliberately with `
        + `npm install --prefix ${pinPath} socraticode@${resolves}${pinSession}`,
    };
  }
  return note(`pinned at ${running}; the plugin's '${floatingSpec}' resolves to ${resolves} — same feature release`);
}

// 'same' | 'patch' | 'feature'. The split carries the finding's severity, and
// it is the whole reason this check does not simply test inequality: a pin is
// MEANT to lag, so "one patch behind" is the intended steady state and has to
// stay silent or the daily hook cries wolf about working as designed. A minor
// or major gap is different in kind — that is where two writers against one
// shared store can hold different ideas of its format, the failure row S is
// about.
function versionGap(a, b) {
  const pa = String(a).split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split('.').map((n) => parseInt(n, 10) || 0);
  if (pa[0] !== pb[0] || pa[1] !== pb[1]) return 'feature';
  if (pa[2] !== pb[2]) return 'patch';
  return 'same';
}

// `npx -y socraticode` unpacks into ~/.npm/_npx/<hash>/node_modules/. Neither
// require.resolve() nor `npm root` sees it, so a plugin-only host resolves here.
function launchFromNpxCache() {
  const npmCache = process.env.npm_config_cache || joinPath(homedir(), '.npm');
  for (const hashDir of subdirsNewestFirst(joinPath(npmCache, '_npx'))) {
    const entry = joinPath(hashDir, 'node_modules', 'socraticode', 'dist', 'index.js');
    if (existsSync(entry)) return nodeLaunch(entry, 'npx cache');
  }
  return null;
}

// `project` is the checkout being measured, handed on to the plugin read: the
// definition this check launches has to be the one the session AT THE PROJECT
// loads, not the one applying at the cwd, or `health-check /abs/B` run from A
// judges B's graph with A's server (#305 CR 42). Omitted, it is the cwd.
function resolveServerLaunch({ project } = {}) {
  if (process.env.SOCRATICODE_ENTRY) {
    const p = resolvePath(process.env.SOCRATICODE_ENTRY);
    if (!existsSync(p)) die(`SOCRATICODE_ENTRY does not exist: ${p}`);
    return nodeLaunch(p, 'SOCRATICODE_ENTRY');
  }

  // 1) A pinned pre-install, when one exists. Ahead of the plugin's recorded
  //    command on purpose, reversing the #85 ordering: that command was made
  //    authoritative so the driver could not drift from the session, but the
  //    command it records is `socraticode@latest`, so reading it faithfully
  //    reproduces a spec whose resolution is time-dependent — the authority was
  //    over the command, never over the version. What the pin changes is WHICH
  //    kind of divergence you get: today both float and agree by coincidence of
  //    timing; pinned, the driver is deterministic and the session still
  //    floats. health-check measures that gap rather than leaving it silent.
  const fromPin = launchFromPin();
  if (fromPin) return fromPin;

  // 2) The plugin's recorded launch command — the documented install path.
  const fromPlugin = launchFromPluginConfig({ project });
  if (fromPlugin) return fromPlugin;

  // 3) require.resolve from this module's context (works if socraticode is a dep).
  try {
    const req = createRequire(import.meta.url);
    return nodeLaunch(req.resolve('socraticode'), 'require.resolve');
  } catch { /* fall through */ }

  // 4) resolve the package root, then read its package.json "main"/"bin".
  for (const args of [['root', '-g'], ['root']]) {
    const out = spawnSync('npm', args, { encoding: 'utf8' });
    if (out.status === 0 && out.stdout) {
      const base = out.stdout.trim();
      const req = createRequire(resolvePath(base, 'x'));
      try { return nodeLaunch(req.resolve('socraticode'), `npm ${args.join(' ')}`); } catch { /* keep trying */ }
      const guess = resolvePath(base, 'socraticode', 'dist', 'index.js');
      if (existsSync(guess)) return nodeLaunch(guess, `npm ${args.join(' ')}`);
    }
  }

  // 5) npx cache, populated by any prior plugin run.
  const fromNpx = launchFromNpxCache();
  if (fromNpx) return fromNpx;

  // 6) Last resort: let npx fetch it, exactly as the plugin does. Costs a
  //    network round-trip on a cold cache but never fails to resolve.
  if (spawnSync('npx', ['--version'], { encoding: 'utf8' }).status === 0) {
    return { command: 'npx', args: ['-y', 'socraticode'], env: {}, source: 'npx -y (fallback)' };
  }

  die(
    'Could not resolve the socraticode server.\n' +
    `  Pre-install a pinned one:  npm install --prefix ${pinDir()} socraticode@<version>, or\n` +
    '  set SOCRATICODE_ENTRY=/abs/path/to/socraticode/dist/index.js, or\n' +
    '  install the plugin:  claude plugin install socraticode@socraticode\n' +
    '  (locate a plugin-run server with: find ~/.npm/_npx -path "*socraticode/dist/index.js")'
  );
}

// ── minimal JSON-RPC 2.0 stdio client ───────────────────────────────────────
class RpcClient {
  constructor(launch, overrides = {}) {
    // We own this child. On our exit we kill it by child.pid — never pkill.
    // launch.env carries the plugin's PATH when we resolved from its mcp.json;
    // merging over process.env keeps that authoritative without dropping ours.
    // `overrides` land last: they are the driver's terms for its own server
    // (see withClient), and neither the shell nor the plugin may loosen them.
    this.child = spawn(launch.command, launch.args, {
      stdio: ['pipe', 'pipe', 'inherit'],
      env: { ...process.env, ...launch.env, ...overrides },
    });
    // Kept so a caller can report WHICH launch answered, not just what it
    // said: with a pin in play the driver and the session can be different
    // builds, and a report that records the version without the path it came
    // from cannot be re-read later to settle which one that was (#295).
    this.launch = launch;
    this.nextId = 1;
    this.pending = new Map();
    this.buf = '';
    // Filled by handshake(); null until then, and null forever against a server
    // that declares no serverInfo (#297).
    this.serverInfo = null;
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (chunk) => this.onData(chunk));
    // Swallow stdin EPIPE: if the server dies mid-index (gotcha B), a late write
    // must not crash us with an unhandled stream error — send() surfaces a clean
    // error instead (see the exitCode guard there).
    this.child.stdin.on('error', () => {});
    this.child.on('exit', (code) => {
      for (const { reject } of this.pending.values()) {
        reject(new Error(`server process exited (code ${code}) with requests in flight`));
      }
      this.pending.clear();
    });
    const cleanup = () => this.kill();
    process.on('exit', cleanup);
    process.on('SIGINT', () => { this.kill(); process.exit(130); });
    process.on('SIGTERM', () => { this.kill(); process.exit(143); });
  }

  onData(chunk) {
    this.buf += chunk;
    let nl;
    while ((nl = this.buf.indexOf('\n')) >= 0) {
      const line = this.buf.slice(0, nl).trim();
      this.buf = this.buf.slice(nl + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; } // ignore non-JSON log lines
      if (msg.id != null && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    }
  }

  send(obj) {
    if (this.child.exitCode != null) {
      throw new Error(`server process has exited (code ${this.child.exitCode}) — cannot send ${obj.method}`);
    }
    this.child.stdin.write(JSON.stringify(obj) + '\n');
  }

  request(method, params) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.send({ jsonrpc: '2.0', id, method, params });
    });
  }

  notify(method, params) { this.send({ jsonrpc: '2.0', method, params }); }

  async handshake() {
    const res = await this.request('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'init-socraticode-driver', version: '1.0.0' },
    });
    // The initialize result was discarded until #297, and with it the one fact
    // that says what this driver is actually talking to: `serverInfo.version`.
    // Verified against a live server, which answers
    // `{ name: 'socraticode', version: '1.14.0' }`.
    //
    // Without it, "is this graph older than the server" could only ever be
    // taken on the server's own word — the `— STALE` token it appends to
    // `Built by:` — so a stamp the server declines to annotate reads as
    // current. That is the #297 failure arriving one build later: in
    // CannObserv/cannabis.observer-wordpress#803 a graph cut by v1.10.0
    // reported READY throughout, three rounds of diagnosis concluded a PSR-4
    // `composer.json` declaration "would not help", and PSR-4 resolution had
    // shipped in v1.11.0 — a version the graph predated. Nothing anywhere
    // said so.
    //
    // Read loosely, like every parser here: a server that sends no serverInfo,
    // or names no version, leaves this null and the comparison simply does not
    // happen. An absent fact must not become a manufactured one.
    this.serverInfo = (res && typeof res === 'object' && res.serverInfo) || null;
    this.notify('notifications/initialized', {});
  }

  // The running server's version, or null when it declared none. A getter
  // rather than a field so the "declared nothing" case has exactly one
  // spelling at every call site.
  get serverVersion() {
    const v = this.serverInfo && this.serverInfo.version;
    return typeof v === 'string' && v.trim() ? v.trim() : null;
  }

  async callTool(name, args) {
    const res = await this.request('tools/call', { name, arguments: args });
    // Flatten the content array to plain text for loose parsing.
    if (res && Array.isArray(res.content)) {
      return res.content.map((c) => (c && c.text != null ? c.text : '')).join('\n');
    }
    return typeof res === 'string' ? res : JSON.stringify(res);
  }

  kill() {
    if (this.child && this.child.pid && this.child.exitCode == null) {
      try { this.child.kill('SIGTERM'); } catch { /* already gone */ }
    }
  }
}

// ── PARSERS (loose — tolerate string-shape drift; gotcha H) ─────────────────
// Dashes vary by server build (hyphen / en / em), so every "Last operation"
// matcher accepts all three rather than pinning the one seen today.

function parseEmbedPercent(text) {
  // "Progress: 6019/6019 chunks embedded (100%)"  → 100
  // PROGRESS DISPLAY ONLY — never a completion signal. The server emits this
  // line exclusively inside its "indexing in progress" branch, so it vanishes
  // the moment the run finishes and this returns null forever after. Gating
  // completion on `=== 100` made success a race against the poll interval
  // (gotcha J); use indexSettled() instead.
  const pct = text.match(/embedded\s*\((\d+)%\)/i);
  if (pct) return Number(pct[1]);
  const frac = text.match(/(\d+)\s*\/\s*(\d+)\s*chunks?\s*embedded/i);
  if (frac && Number(frac[2]) > 0) return Math.floor((Number(frac[1]) / Number(frac[2])) * 100);
  return null;
}

// "⚠ Full index in progress" / "⚠ Incremental update in progress"
function indexingInProgress(text) {
  return /(full index|incremental update) in progress/i.test(text);
}

// "Last operation: Full index — completed"
//
// Pinned to "Full index" rather than any completed operation. codebase_index
// always records a full index (indexProject() sets type: "full-index"
// unconditionally, even re-indexing an existing project), while the file
// watcher — which auto-starts on the first status call — records "Incremental
// update" completions in this same process. Accepting either would let a
// watcher's incremental satisfy our gate in the window before the full index
// takes its lock.
function lastOperationCompleted(text) {
  return /Last operation:\s*Full index\s*[-—–]\s*completed/i.test(text);
}

// "Last operation: Full index — FAILED" followed by "  Error: <msg>"
function lastOperationFailed(text) {
  return /Last operation:[^\n]*[-—–]\s*FAILED/i.test(text);
}

function parseLastOpError(text) {
  const m = text.match(/Last operation:[^\n]*FAILED[^\n]*\n\s*Error:\s*([^\n]*)/i);
  return m ? m[1].trim() : null;
}

// "⚠ INDEX IS INCOMPLETE — a previous indexing run was interrupted…"
function indexIncomplete(text) {
  return /INDEX IS INCOMPLETE/i.test(text);
}

// "⚠ ANOTHER PROCESS (PID 12345) IS ACTIVELY INDEXING this project."
function anotherProcessIndexing(text) {
  const m = text.match(/ANOTHER PROCESS \(PID\s*(\d+)\)/i);
  return m ? m[1] : null;
}

// Embeddings (and the server-side graph build that follows them) are done when
// the in-progress block is gone AND the server reports a completed run.
//
// `Last operation` is in-process state and this server child is OURS, so a
// completed record can only describe the run we just started — there is no
// cross-run staleness to guard against. Deliberately NOT keyed on
// "Indexed chunks: N": that count comes from Qdrant and survives across runs,
// so it reads as already-done on the first poll of a re-index.
function indexSettled(text) {
  return !indexingInProgress(text) && lastOperationCompleted(text);
}

// ── tool-reply predicates ───────────────────────────────────────────────────
// Several server tools report failure by RETURNING a string rather than
// throwing (gotcha M), so every reply the driver acts on is classified here —
// named and exported so parser-selftest.mjs pins the shipped expression rather
// than a copy of it.

// codebase_index, success: "Indexing started in the background for: <path>"
function indexStarted(text) {
  return /Indexing started in the background/i.test(text);
}

// codebase_index, concurrency guard: "⚠ Indexing is already in progress for: …"
// Not a failure — some run is underway, so the caller polls rather than aborts.
function indexAlreadyRunning(text) {
  return /Indexing is already in progress/i.test(text);
}

// …but WHICH run matters. The guard's reply names it — "Operation: Full index"
// or "Operation: Incremental update". Waiting on an incremental would be waiting
// for a full-index completion that was never requested, i.e. a silent hang to
// INDEX_TIMEOUT_MS, so the caller re-issues the index once the incremental clears.
function runningOperationIsFullIndex(text) {
  return /Operation:\s*Full index/i.test(text);
}

// codebase_context_index, success: "Context Artifacts — Indexing Complete"
function contextIndexComplete(text) {
  return /Context Artifacts\s*[-—–]\s*Indexing Complete/i.test(text);
}

// "Indexed chunks: 0" — the collection exists but holds nothing. Meaningful
// only once the run has settled (see the call site).
function indexedZeroChunks(text) {
  return /Indexed chunks:\s*0\b/.test(text);
}

// codebase_search: an empty result set is an ordinary sentence, not an error,
// so require a result row — "--- src/app.py (lines 10-20) [python] score: …"
function searchHasHits(text) {
  return !/^No results (found|above score threshold)/m.test(text)
    && /^--- .+ \(lines \d+-\d+\)/m.test(text);
}

// codebase_list_projects: "No projects have been indexed yet. …"
function listHasProjects(text) {
  return /\S/.test(text) && !/^No projects have been indexed/m.test(text);
}

function parseArtifacts(text) {
  // Two known shapes:
  //   "Context artifacts: 2/7 indexed"          → {done:2, total:7}
  //   "Context artifacts: 7 artifacts indexed (131 chunks)" → {done:7, total:7}
  const line = (text.match(/Context artifacts:[^\n]*/i) || [''])[0];
  const frac = line.match(/(\d+)\s*\/\s*(\d+)/);
  if (frac) return { done: Number(frac[1]), total: Number(frac[2]) };
  const n = line.match(/(\d+)\s*artifacts?\s*indexed/i);
  if (n) return { done: Number(n[1]), total: Number(n[1]) };
  // No artifacts configured / no line present → treat as satisfied (0 expected).
  return { done: 0, total: 0 };
}

// codebase_context lists one block per manifest entry, and its Status line is
// the ONLY per-artifact index state there is — the status line's `M/N indexed`
// gives a count and never a name:
//
//   ━━━ reference-docs ━━━
//     Path: ./docs/
//     Description: …
//     Status: ○ not yet indexed
//
// Measured against a live 13-artifact reply (cannabis_observer/code/cli), one
// of whose artifacts was sitting unindexed behind a green status at the time.
//
// The `Path:` line and the timestamp inside `Status:` are read for the same
// reason (#225): they are the only per-artifact FRESHNESS data the server
// offers, and `indexed` alone is a presence check. `Context artifacts: 14/14`
// says nothing about whether any of the fourteen still matches its source.
//
// → [{ name, path, status, indexed, lastIndexed }]
function parseContextArtifacts(text) {
  const out = [];
  for (const line of String(text).split('\n')) {
    const head = line.match(/^\s*━+\s*(.+?)\s*━+\s*$/);
    if (head) {
      out.push({ name: head[1], path: null, status: '', indexed: false, lastIndexed: null });
      continue;
    }
    if (!out.length) continue;
    const current = out[out.length - 1];
    const path = line.match(/^\s*Path:\s*(.+?)\s*$/);
    if (path) { current.path = path[1]; continue; }
    const status = line.match(/^\s*Status:\s*(.+?)\s*$/);
    if (status) {
      current.status = status[1];
      current.indexed = artifactIndexed(status[1]);
      current.lastIndexed = parseIndexedAt(status[1]);
    }
  }
  return out;
}

// "✓ indexed (42 chunks, 2026-08-09T04:46:34.264Z)" → "2026-08-09T04:46:34.264Z"
//
// Loose like every parser here, and NULL rather than a guess when the shape
// drifts: a build that stops printing the timestamp must leave freshness
// unjudged. Calling every artifact stale would train the cohort to ignore the
// line; calling every one fresh would rebuild the silence the check exists to
// break. The caller reports which ones it could not judge instead.
function parseIndexedAt(status) {
  const m = String(status).match(/(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)/);
  return m && !Number.isNaN(Date.parse(m[1])) ? m[1] : null;
}

// ── artifact freshness (#225) ───────────────────────────────────────────────
// The newest mtime at or under `target`, in epoch ms — or null when it cannot
// be read.
//
// For a directory artifact this is the only honest comparison, and the reason
// is not obvious: a directory's OWN mtime moves when an entry is added or
// removed directly inside it, and never when a file two levels down is edited.
// `design-specs`, `implementation-plans` and `alembic-migrations` all point at
// directories, so a plan written today under docs/plans/2026/ leaves the count
// unchanged, the artifact "indexed", and the directory's mtime untouched — the
// CannObserv/power-map#454 shape one level down.
const FRESHNESS_WALK_BUDGET = 20000;

// PARITY, not preference: the server's own exclusions, transcribed.
//
// `dist/services/context-artifacts.js` (socraticode 1.13.2) builds a directory
// artifact by globbing `**/*` with `dot: false` and
// `ignore: ["**/node_modules/**", "**/.git/**"]`, then running every surviving
// file through `createIgnoreFilter`/`shouldIgnore` (`dist/services/ignore.js`).
// Since SocratiCode#117 those two glob ignores are NO LONGER the filter — the
// server's own comment calls them a subtree-pruning optimisation over two of
// the chain's default patterns, "kept for what they cost the walk rather than
// what they match". Mirroring only them, as this walk did through 1.12.x,
// under-prunes by the whole list below.
//
// Transcribed verbatim from that file's DEFAULT_IGNORE_PATTERNS, in its order,
// against 1.13.2. Kept as the server's literal strings rather than a
// hand-classified list so the next reader can diff the two by eye; the three
// buckets below are derived from them at load.
const SERVER_DEFAULT_IGNORE_PATTERNS = [
  'node_modules', '.git', '.svn', '.hg',
  'dist', 'build', 'out', '.next', '.nuxt',
  '__pycache__', '*.pyc', '.venv', '/venv', '/env', '.tox',
  'target', '_build', 'deps', 'bin/Debug', 'bin/Release', 'obj',
  '.gradle', '.idea', '.vscode', '.vs',
  '*.min.js', '*.min.css', '*.map', '*.lock',
  'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
  'Cargo.lock', 'Gemfile.lock', 'poetry.lock',
  '*.log', '*.tmp', '*.swp', '*.swo',
  '.DS_Store', 'Thumbs.db',
  'coverage', '.nyc_output', '.cache', '.parcel-cache', '.turbo',
  'vendor', '.dart_tool',
];

// The defaults use exactly four gitignore forms, and only these are
// implemented — deliberately, because anything more would be inventing
// semantics the list does not exercise:
//   `name`      bare, no slash: matches that basename at ANY depth
//   `*.ext`     matches that suffix at ANY depth
//   `/name`     leading slash: anchored, root's own child only
//   `a/b`       embedded slash: anchored to the artifact root, as gitignore
// Pruning the directory covers everything beneath it, so an anchored path
// pattern needs no separate prefix test.
//
// Seventeen of the 48 are dot-named (`.git`, `.venv`, `.idea`, `.DS_Store`…)
// and so are unreachable here: the walk's `dot: false` rule fires first and
// skips them by name. They stay in the list anyway — it is a transcription,
// and one that has been edited to remove "redundant" entries can no longer be
// diffed against the server's array, which is the only thing keeping it
// honest. The overlap is the server's too: `dot: false` and the chain's
// defaults both cover them there.
const IGNORE_BASENAMES = new Set();
const IGNORE_SUFFIXES = [];
const IGNORE_ANCHORED = new Set();
for (const pattern of SERVER_DEFAULT_IGNORE_PATTERNS) {
  if (pattern.startsWith('/')) IGNORE_ANCHORED.add(pattern.slice(1));
  else if (pattern.includes('/')) IGNORE_ANCHORED.add(pattern);
  else if (pattern.startsWith('*.')) IGNORE_SUFFIXES.push(pattern.slice(1));
  else IGNORE_BASENAMES.add(pattern);
}

// THE RESIDUAL, named rather than left to be rediscovered. The server's chain
// has three layers and this mirrors one:
//   1. DEFAULT_IGNORE_PATTERNS — above.
//   2. `.gitignore` (root + nested) and `.socraticodeignore`, ROOTED AT THE
//      ARTIFACT DIRECTORY, not the project. A repo-root `.socraticodeignore`
//      does not reach a subtree artifact at all; only ignore files INSIDE the
//      artifact path do. Measured on 1.13.2, not inferred.
//   3. Virtualenv directories found by marker (`pyvenv.cfg`, `conda-meta/`).
// Layers 2 and 3 need a gitignore engine and a marker scan; this driver has no
// dependencies and is not the place for either. That trade errs in the UNSAFE
// direction — under-pruning invents findings, over-pruning only misses them —
// so it is worth stating plainly rather than leaving to be rediscovered: a file
// excluded by an artifact-local ignore file, or living in a virtualenv nested
// inside an artifact, is still counted here and can still report a false
// `stale`. That is the #235 shape, now confined to a case far rarer than the
// build output layer 1 covers, and it is the one `stale` a reader should
// dismiss rather than act on.
function serverIgnoresEntry(name, relativePath) {
  if (IGNORE_BASENAMES.has(name)) return true;
  if (IGNORE_ANCHORED.has(relativePath)) return true;
  return IGNORE_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

function newestMtimeMs(target) {
  let newest = null;
  let budget = FRESHNESS_WALK_BUDGET;
  const visit = (p, isDirectory, relativePath) => {
    let st;
    try { st = statSync(p); } catch { return; }
    if (newest === null || st.mtimeMs > newest) newest = st.mtimeMs;
    if (!isDirectory) return;
    let entries;
    try { entries = readdirSync(p, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      // Budget exhausted: stop and answer with the newest seen so far. That
      // UNDER-reports staleness, degrading toward the presence-only check this
      // replaces, which is the safe direction — a walk that gave up must not
      // manufacture a finding.
      if (budget-- <= 0) return;
      // PARITY with dist/services/context-artifacts.js: anything counted here
      // that the server never embeds moves the freshness clock for content the
      // artifact cannot contain — a `.pytest_cache/` rewritten by every test
      // run reported a byte-identical artifact stale, with a named remedy that
      // changes nothing (#235).
      //
      // `dot: false` excludes dot-named entries at every depth — files too
      // (`.coverage`) — but NOT the artifact root: glob filters paths under
      // cwd, never cwd itself, so a dot-rooted artifact still embeds its plain
      // contents, and `visit(target, …)` below this closure stays unconditional
      // to match. The ignore chain is rooted the same way, so `relativePath`
      // is measured from the artifact root and starts empty there.
      //
      // `__pycache__` used to be the one entry deliberately EXEMPT from this
      // prune: it is not a dotfile, the glob's ignore list never named it, and
      // through 1.12.x it really was embedded — #229 measured 32 of an
      // artifact's 86 chunks as compiled bytecode. SocratiCode#117 put the
      // full ignore chain behind the walk and `__pycache__`/`*.pyc` are in its
      // defaults, so on 1.13.x the server embeds neither. Keeping the old
      // exemption re-opened #235 through the single hole cut for it: a
      // bytecode rewrite (a Python version bump, an edited migration) reports
      // `stale`, and re-indexing cannot clear it, because the re-indexed
      // content does not contain the file whose mtime moved (#270).
      //
      // Known residual: creating or deleting a pruned entry still bumps its
      // parent directory's own mtime, which stays counted because it is the
      // only trace a deleted embedded file leaves. See serverIgnoresEntry for
      // the two chain layers this does not mirror. Pinned, both directions, in
      // tests/structural/test_context_artifact_parity.py.
      if (e.name.startsWith('.')) continue;
      const childRelative = relativePath ? `${relativePath}/${e.name}` : e.name;
      if (serverIgnoresEntry(e.name, childRelative)) continue;
      // Dirent flags come from lstat, so a symlink to a directory is a symlink
      // here and is never descended: no cycles, and no wandering out of the
      // artifact through a link into a tree nobody declared.
      if (e.isDirectory()) visit(joinPath(p, e.name), true, childRelative);
      else if (e.isFile()) visit(joinPath(p, e.name), false, childRelative);
    }
  };
  let root;
  try { root = statSync(target); } catch { return null; }
  visit(target, root.isDirectory(), '');
  return newest;
}

// ── content confirmation (#326) ──────────────────────────────────────────────
// mtime is a prefilter, not a verdict. A checkout, a local merge, `git stash
// pop`, a rebase or a bare `touch` rewrites a file with IDENTICAL bytes and a
// new mtime — and the server's repair is keyed on content, so codebase_update
// answers `0 files changed`, re-embeds nothing, and the finding it was named
// to clear comes back the next day. Measured on CannObserv/wslcb-licensing-
// tracker: two artifacts called stale at 18:49 by a merge, their last content
// change at 18:32:14, indexed 30 and 42 seconds later (#326).
//
// So a newer mtime is confirmed against the key the server itself uses before
// it is reported: the artifact's contentHash, recomputed here the way
// dist/services/context-artifacts.js readArtifactContent computes it (1.14.0),
// and compared with the one stored on the project's socraticode_metadata
// point. Equal means the index already holds these bytes, whatever the clock
// says.
//
// Transcribed rather than imported, like the walk above and for the same
// reason. The transcription is exact only where this walk can be: a directory
// holding an ignore file or a virtualenv marker is one the server filters with
// the two chain layers this driver does not mirror (see serverIgnoresEntry),
// and a symlink is one glob resolves by rules this walk does not follow. There
// it REFUSES to hash rather than hashing something close — a near-miss hash
// never matches, and would turn every touched file into a confirmed defect.
// Pinned against the installed server in test_context_artifact_parity.py.
const BINARY_SNIFF_BYTES = 8192; // constants.js DETECT_HEAD_BYTES

function contentDigest(text) {
  return createHash('sha256').update(text).digest('hex').slice(0, 16);
}

// { hash } or { hash: null, reason }. Never throws: an artifact this cannot
// hash is one whose freshness stays unconfirmed, not a failed health check.
function artifactContentHash(target) {
  let root;
  try { root = statSync(target); } catch (e) { return { hash: null, reason: `cannot stat it (${e.code || e.message})` }; }
  if (root.isFile()) {
    // The server reads a single-file artifact verbatim as utf-8, no binary
    // sniff and no ignore chain: a declared path is an explicit instruction.
    try { return { hash: contentDigest(readFileSync(target, 'utf8')) }; } catch (e) {
      return { hash: null, reason: `cannot read it (${e.code || e.message})` };
    }
  }
  if (!root.isDirectory()) return { hash: null, reason: 'it is neither a file nor a directory' };

  const files = [];
  let budget = FRESHNESS_WALK_BUDGET;
  let refusal = null;
  const walk = (dir, relativePath) => {
    // The ignore files the server's chain reads, rooted at the artifact: a
    // `.gitignore` in any directory it walks, `.socraticodeignore` at the root
    // only. Dot-named, so the entry loop below would never see them.
    const markers = relativePath ? ['.gitignore'] : ['.gitignore', '.socraticodeignore'];
    for (const m of markers) {
      if (existsSync(joinPath(dir, m))) {
        refusal = `${relativePath ? `${relativePath}/` : ''}${m} filters it by rules this driver does not mirror`;
        return;
      }
    }
    // A subdirectory holding pyvenv.cfg or conda-meta/ is a virtualenv the
    // server excludes whatever it is called (ignore.js isEnvironmentDirectory).
    if (relativePath && (existsSync(joinPath(dir, 'pyvenv.cfg')) || existsSync(joinPath(dir, 'conda-meta')))) {
      refusal = `${relativePath}/ is a virtualenv the server excludes by marker`;
      return;
    }
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch (e) {
      refusal = `cannot list ${relativePath || 'its root'} (${e.code || e.message})`;
      return;
    }
    for (const e of entries) {
      if (refusal) return;
      if (budget-- <= 0) { refusal = `it holds more than ${FRESHNESS_WALK_BUDGET} entries`; return; }
      if (e.name.startsWith('.')) continue;
      const childRelative = relativePath ? `${relativePath}/${e.name}` : e.name;
      if (serverIgnoresEntry(e.name, childRelative)) continue;
      if (e.isDirectory()) walk(joinPath(dir, e.name), childRelative);
      else if (e.isFile()) files.push(childRelative);
      else { refusal = `${childRelative} is a symlink or special file`; return; }
    }
  };
  walk(target, '');
  if (refusal) return { hash: null, reason: refusal };

  // Everything below is readArtifactContent's own loop: glob's paths sorted by
  // code unit, a NUL in the first 8 KiB skips the file as binary, an unreadable
  // one is skipped, and the rest are joined under a `# ── path ──` header.
  files.sort();
  const parts = [];
  for (const rel of files) {
    let buf;
    try { buf = readFileSync(joinPath(target, rel)); } catch { continue; }
    if (buf.subarray(0, BINARY_SNIFF_BYTES).includes(0)) continue;
    parts.push(`# ── ${rel} ──\n${buf.toString('utf8')}`);
  }
  // The server refuses such an artifact outright, so it holds no hash to match.
  if (!parts.length) return { hash: null, reason: 'it holds no readable text file' };
  return { hash: contentDigest(parts.join('\n\n')) };
}

// Where the server's Qdrant client connects (qdrant.js getClient): QDRANT_URL
// when set, in either mode, with 6333/443 filled in when it names no port;
// otherwise host and port, over https when an API key is set.
function qdrantBase(env) {
  if (env.QDRANT_URL) {
    const u = new URL(env.QDRANT_URL);
    if (!u.port) u.port = u.protocol === 'https:' ? '443' : '6333';
    return `${u.origin}${u.pathname.replace(/\/+$/, '')}`;
  }
  return `${env.QDRANT_API_KEY ? 'https' : 'http'}://${env.QDRANT_HOST || 'localhost'}:${env.QDRANT_PORT || 16333}`;
}

// qdrant.js metadataPointId: the first 32 hex of sha256(collection), as a UUID.
function metadataPointId(collection) {
  const h = createHash('sha256').update(collection).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}

const QDRANT_READ_TIMEOUT_MS = 10000;

// The contentHash the server stored per artifact, read off the project's
// context point in socraticode_metadata: { hashes: Map(name -> hash) } or
// { hashes: null, error }. No MCP tool returns it — codebase_context prints
// the index time and nothing else — so this is one read-only REST call to the
// store the server just answered from, with the environment it was launched
// with. Never throws.
async function indexedArtifactHashes(projectPath, env) {
  const prefix = env.QDRANT_COLLECTION_PREFIX || '';
  const collection = `${prefix}context_${effectiveProjectId(projectPath, env).value}`;
  const metadata = `${prefix}socraticode_metadata`;
  let base;
  try { base = qdrantBase(env); } catch (e) { return { hashes: null, error: `QDRANT_URL does not parse (${e.message})` }; }
  let res;
  try {
    res = await fetch(`${base}/collections/${metadata}/points`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(env.QDRANT_API_KEY ? { 'api-key': env.QDRANT_API_KEY } : {}) },
      body: JSON.stringify({ ids: [metadataPointId(collection)], with_payload: true }),
      signal: AbortSignal.timeout(QDRANT_READ_TIMEOUT_MS),
    });
  } catch (e) {
    return { hashes: null, error: `cannot reach Qdrant at ${base} (${e.cause?.code || e.message})` };
  }
  if (!res.ok) return { hashes: null, error: `Qdrant at ${base} answered HTTP ${res.status} for ${metadata}` };
  let point;
  try { point = (await res.json())?.result?.[0]; } catch (e) {
    return { hashes: null, error: `Qdrant at ${base} answered unparseable JSON (${e.message})` };
  }
  if (!point) return { hashes: null, error: `${metadata} holds no point for ${collection}` };
  let states = point.payload?.artifacts;
  try { if (typeof states === 'string') states = JSON.parse(states); } catch { states = null; }
  if (!Array.isArray(states)) return { hashes: null, error: `the ${collection} metadata point carries no artifact list` };
  return {
    hashes: new Map(states
      .filter((s) => s && typeof s.name === 'string' && typeof s.contentHash === 'string')
      .map((s) => [s.name, s.contentHash])),
  };
}

// Asymmetric on purpose: only a positively-indexed status counts as indexed,
// and anything unrecognised falls to NOT indexed. Reading an unknown rendering
// as success would rebuild the silent-green hole this check exists to close —
// and the error rendering is the one shape we have never seen from this tool,
// only from codebase_context_index's report.
function artifactIndexed(status) {
  if (/✗|✘|✖|error|fail/i.test(status)) return false;
  if (/not\s+yet|pending|queued|missing|stale/i.test(status)) return false;
  return /✓|\bindexed\b/i.test(status);
}

// Anchored to the status line, not a bare substring. `/READY/i` also matches
// the "ready" inside "already", so any future wording along the lines of
// "graph already built" would have read as READY. Harmless while nothing said
// that — but #207 gave this a second job, deciding whether an absent
// `Built by:` line means an old server or simply no graph, so a false READY
// now also puts a false claim about the server into a health finding.
function graphReady(text) {
  return /^[ \t]*Status\s*:\s*READY\b/im.test(text);
}

// ── graph YIELD (#107) ──────────────────────────────────────────────────────
// READY is a *status*, not a result. On CannObserv/usa-wa — a uv workspace with
// the standard src layout (packages/<dashed-name>/src/<underscored_module>/) —
// codebase_graph_status reported READY with 3 dependency edges across 374 files
// and 81.8% unresolved, because the resolver cannot follow the three-way
// dashed-dir / src/ / underscored-module mismatch. Nothing noticed: the skill
// gated on READY, the policy it writes then sent every agent to
// codebase_graph_query first, and an empty answer there reads as "no
// dependents" rather than "the tool failed".
//
// codebase_graph_status, healthy shape:
//   Status: READY
//   Files (nodes): 374
//   Dependencies (edges): 3
//   Symbols: 3767
//   Call edges: 23237
//   Unresolved: 81.8%
//
// Loose like every parser here (gotcha H): labels are matched individually and a
// missing one yields null rather than throwing, so a server-side relabel
// degrades this to `unknown` instead of to a false verdict.
function parseGraphCounts(text) {
  const num = (re) => {
    const m = text.match(re);
    return m ? Number(m[1].replace(/,/g, '')) : null;
  };
  // Anchored to line starts. Unanchored, the `Edges` fallback matches inside
  // `Call edges: 23237` — a different statistic, three orders of magnitude
  // larger on the very graph this gate exists to catch — and any build that
  // relabelled the dependency line would silently read as a healthy graph.
  // Failing to parse must degrade to `unknown`, never to a false `ok`.
  return {
    nodes: num(/^[ \t]*(?:Files\s*\(nodes\)|Nodes|Files)\s*:\s*([\d,]+)/im),
    edges: num(/^[ \t]*(?:Dependencies\s*\(edges\)|Dependency edges|Edges)\s*:\s*([\d,]+)/im),
    symbols: num(/^[ \t]*Symbols\s*:\s*([\d,]+)/im),
    callEdges: num(/^[ \t]*Call edges\s*:\s*([\d,]+)/im),
    unresolvedPct: num(/^[ \t]*Unresolved\s*:\s*([\d.,]+)\s*%/im),
  };
}

// The gate's threshold, in one place so the driver, the tests and the docs
// cannot disagree about it.
//
// EDGES PER NODE < 0.1 — the issue's own first suggestion (`edges < nodes / 10`)
// and the only candidate that measures the thing the policy actually depends on:
// can the graph answer "what imports this file". It is scale-free, so it reads
// the same on a 40-file service and a 4,000-file monorepo. usa-wa sits at
// 3/374 = 0.008, twelve times below the line; a Python repo where most modules
// import one sibling sits near or above 1.0, so the threshold leaves a full
// order of magnitude of headroom before a genuinely flat repo trips it.
//
// Rejected: "Average dependencies per file rounds to 0.0" is the same metric at
// a threshold of 0.05, but read off a *printed, rounded* string — exactly the
// server-formatting dependency gotcha H exists to avoid. Rejected as a gate:
// `Unresolved %`, the share of captured symbol edges matching no project
// symbol, which counts edges into builtins and external libraries by
// construction; it is reported beside the verdict, never as it (#308).
//
// MIN_NODES — below 20 files, 0.1 edges/node is under two edges and noise
// dominates; a repo that small is also one where grep is fine. Verdict
// `unknown` there, never `low`.
const GRAPH_YIELD_MIN_EDGES_PER_NODE = 0.1;
const GRAPH_YIELD_MIN_NODES = 20;
const GRAPH_UNRESOLVED_WARN_PCT = 50;

// → { verdict: 'ok' | 'low' | 'unknown', reason, edgesPerNode, ...counts }
//
// Three verdicts, not two. `unknown` (unparseable, or too few files to judge) is
// deliberately NOT folded into `low`: writing the degraded policy tells a repo
// its graph is broken, and asserting that from a string we could not read would
// be the same class of error as the one this gate exists to catch.
function graphYield(text) {
  const counts = parseGraphCounts(text);
  const { nodes, edges } = counts;
  const edgesPerNode = nodes && nodes > 0 && edges != null ? edges / nodes : null;
  const out = { ...counts, edgesPerNode, verdict: 'unknown', reason: '' };

  if (nodes == null || edges == null) {
    out.reason = 'could not parse node/edge counts from codebase_graph_status';
    return out;
  }
  if (nodes < GRAPH_YIELD_MIN_NODES) {
    out.reason = `only ${nodes} file(s) in the graph — too few to judge yield (min ${GRAPH_YIELD_MIN_NODES})`;
    return out;
  }
  if (edgesPerNode < GRAPH_YIELD_MIN_EDGES_PER_NODE) {
    out.verdict = 'low';
    out.reason = `${edges} edge(s) across ${nodes} files = ${edgesPerNode.toFixed(3)} edges/file, `
      + `below the ${GRAPH_YIELD_MIN_EDGES_PER_NODE} floor`
      + (counts.unresolvedPct != null ? ` (unresolved ${counts.unresolvedPct}%)` : '');
    return out;
  }
  out.verdict = 'ok';
  out.reason = `${edges} edge(s) across ${nodes} files = ${edgesPerNode.toFixed(3)} edges/file`;
  return out;
}

// ── the server's own import-resolution advisory (#207) ───────────────────────
// SocratiCode 1.13.0 (upstream #112, shipped 2026-09-07) states the yield
// itself, below a 2%-of-captured ratio with a 20-captured-import floor:
//
//   Import resolution: 37 of 2959 captured imports resolved to project files (1.2%)
//     Most imports did not resolve, so codebase_graph_query, ...
//
// This is the better signal and it is why the gate below prefers it: it is
// resolved-over-captured, so it does not move with repo size and does not read
// as broken on a repo that is merely orphan-heavy — the two failure modes of
// our own edges/file heuristic.
//
// Anchored to the line start and to the server's own noun phrase. A partial
// match returns null rather than a zero: an advisory we could not read must not
// become `resolved: 0`, which would assert a collapse the server never stated.
function parseImportResolution(text) {
  const m = text.match(
    /^[ \t]*Import resolution\s*:\s*([\d,]+)\s+of\s+([\d,]+)\s+captured imports resolved[^(\n]*\(\s*([\d.]+)\s*%\s*\)/im,
  );
  if (!m) return null;
  const n = (s) => Number(s.replace(/,/g, ''));
  const resolved = n(m[1]);
  const captured = n(m[2]);
  if (!Number.isFinite(resolved) || !Number.isFinite(captured)) return null;
  return { resolved, captured, pct: Number(m[3]) };
}

// ── release ordering, for the staleness comparison (#297) ───────────────────
// The leading dotted-numeric run of a version string, `v` optional. A
// prerelease identifier (`1.14.0-rc.2`) contributes its numbers and nothing
// else: ordering prereleases against their release is semver's problem, not
// this gate's, and treating `1.14.0-rc.2` as equal to `1.14.0` errs toward
// saying nothing, which is the direction this whole file errs in.
function versionParts(s) {
  if (typeof s !== 'string') return null;
  const m = s.trim().match(/^v?(\d+(?:\.\d+)*)/);
  return m ? m[1].split('.').map(Number) : null;
}

// → -1 | 0 | 1, or NULL when either side cannot be read as a release.
//
// Null, never 0. "Could not compare" rendered as "same version" is precisely
// the certificate this exists to withhold — the assert-from-a-string-we-could-
// not-read error `graphYield` and `parseImportResolution` both refuse to make.
function compareVersions(a, b) {
  const x = versionParts(a);
  const y = versionParts(b);
  if (!x || !y) return null;
  for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
    const d = (x[i] ?? 0) - (y[i] ?? 0);
    if (d !== 0) return d < 0 ? -1 : 1;
  }
  return 0;
}

// ── which build produced the graph being served (#207, #297, upstream #120) ──
// 1.13.0 stamps the builder version beside the build time, in three shapes:
//
//   Built by: v1.13.1
//   Built by: v1.12.0 — STALE, this server is v1.13.1
//   Built by: unknown (persisted before the builder version was recorded)
//
// Parsed here because the advisory above is only meaningful when the graph was
// cut by a builder that records `importCount` — see the gate for why absence is
// otherwise unreadable. Keyed on the STALE token rather than on the em-dash,
// which is punctuation and will drift.
//
// `absent` (no line at all) is a server older than 1.13.0, and is deliberately
// distinct from `unknown` (a 1.13+ server serving a graph older than itself):
// the first says the signal was never available, the second says a rebuild
// would produce it.
//
// `serverVersion` — the running server's own `serverInfo.version`, captured at
// the handshake — makes the staleness OURS to decide rather than the server's
// to volunteer (#297). Until it was threaded through, `stale` meant exactly
// "the server appended STALE", so every way of not saying it — a reformat, a
// build that stamps without comparing, the 1.10/1.11 pair in the issue that
// stamped nothing at all — landed on `current` and certified a graph older than
// the resolvers answering queries about it. The token is still believed when
// present; what is new is that its ABSENCE is now checked rather than trusted.
//
// Optional, and null-tolerant, because the two other callers of this parser
// hold no client: parser-selftest.mjs and the structural suite both exercise it
// as pure text. With no version to compare against, the behaviour is exactly
// what it was before #297.
//
// A builder NEWER than the running server (a downgrade, or a plugin cache
// behind `socraticode@latest`) stays `current` on purpose: the artifact is then
// at least as good as anything the running resolvers would cut, no action
// repairs it, and a daily finding for it would be the accusation-on-a-healthy-
// repo failure #216 and #220 spent two issues removing.
function parseGraphBuilder(text, serverVersion = null) {
  const running = typeof serverVersion === 'string' && serverVersion.trim()
    ? serverVersion.trim().replace(/^v/, '')
    : null;
  const m = text.match(/^[ \t]*Built by\s*:\s*(\S.*)$/im);
  if (!m) return { state: 'absent', builtBy: null, serverVersion: running };
  const rest = m[1].trim();
  // The server names itself on the STALE line ("— STALE, this server is v1.13.1").
  // Second-best after the handshake, which says what we are actually talking to,
  // but it keeps the finding able to print both versions when this parser is
  // called without a client — which is how every test and the selftest call it.
  const declared = (rest.match(/this server is\s+v?(\d+(?:\.\d+)*[^\s,)]*)/i) || [])[1] || null;
  const against = running || declared;
  if (/^unknown\b/i.test(rest)) {
    return { state: 'unknown', builtBy: null, serverVersion: against };
  }
  // The first delimited token, with an OPTIONAL `v`. Optional because a hard
  // `^v` turns a cosmetic reformat into a false daily "run codebase_graph_build"
  // against a current graph — the accusation-on-a-healthy-repo failure #216 and
  // #220 removed from `unresolvedPct`, re-entering through a different door.
  // Token-then-validate rather than one clever regex: the STALE line continues
  // `— STALE, this server is v…`, and a pattern that has to stop before that
  // prose is where the `v` got load-bearing in the first place.
  const token = rest.split(/[\s,]/)[0];
  const builtBy = /^v?\d+\.\d+/.test(token) ? token.replace(/^v/, '') : null;
  if (!builtBy) return { state: 'unknown', builtBy: null, serverVersion: against };
  const older = compareVersions(builtBy, against) === -1;
  return {
    state: /\bSTALE\b/.test(rest) || older ? 'stale' : 'current',
    builtBy,
    serverVersion: against,
  };
}

// The release that shipped BOTH the import-resolution advisory and the builder
// stamp (upstream #112 / #120). A graph cut before it records no `importCount`,
// so the running server has nothing to compute the ratio from and its silence
// proves nothing.
const ADVISORY_SINCE = '1.13.0';

// Can the server's SILENCE be read as "measured and found nothing"? (#207)
//
// Keyed on what the graph CARRIES, not on whether the server called it stale.
// Those were the same question only while `stale` meant "the server volunteered
// the STALE token" — once #297 made staleness ours to compute, keying trust on
// it flipped every graph a release behind its server onto the local edges/file
// floor, and an orphan-heavy repo the server had just certified would trip that
// floor and get variant B written into its AGENTS.md. That is #207's own
// failure, re-entering through the door #297 opened; the two facts have to be
// asked separately, and they are:
//
//   - THIS decides which measure rules.
//   - `builderFinding` reports the staleness, independently, on every verdict.
//
// A graph whose builder is a release behind is still a graph the RUNNING server
// read `importCount` out of, so its advisory — or its silence — is a real
// ruling about resolution. That the resolvers have since moved on is a separate
// defect with a separate repair, and it is reported as one.
//
// `>= 0`, not `!== -1`: an unreadable version compares to `null`, and `null !==
// -1` would hand the server's authority to a stamp we could not read. Not
// reachable today — `builtBy` is only set when it matched a dotted release —
// but "trust by default on an unparseable string" is the one default this file
// never takes.
function builderCarriesAdvisory(builder) {
  if (builder.builtBy == null) return false;
  const c = compareVersions(builder.builtBy, ADVISORY_SINCE);
  return c === 0 || c === 1;
}

// ── the composed gate (#207) ─────────────────────────────────────────────────
// Which of the two yield measures decides, and when.
//
// The naive reading of #207 — "gate on the advisory when present, fall back to
// our arithmetic when it is not" — treats advisory-absence as one case. It is
// three, and they do not want the same answer:
//
//   1. the server is older than 1.13.0 and never emits the line;
//   2. the server is current but the GRAPH predates `importCount`, so there is
//      nothing to compute the ratio from;
//   3. the server measured and found the resolution fine.
//
// Only `Built by:` separates them, which is why this reads both. In case 3 the
// server has ruled, and our edges/file floor must NOT overrule it: the two
// thresholds do not nest — ours is edges-per-file, the server's is
// resolved-over-captured — so a legitimately orphan-heavy repo can clear the
// server's bar and trip ours. Letting it write the degraded policy there is the
// same false accusation #216 and #220 spent two issues removing from
// `unresolvedPct`, but with a much larger blast radius: it rewrites AGENTS.md
// to route every dependency question to grep.
//
// This is not hypothetical. cannobserv served a graph at 37 edges across 621
// files for 8.8 days; our gate called it LOW throughout. It was not broken, it
// was STALE — rebuilt on 1.13.1 the same repo yields 2156 edges across 627
// files. Case 2, misread as a defect.
//
// The residual ambiguity, stated because it is the one thing this cannot
// resolve: the server suppresses the advisory below 20 captured imports, so in
// case 3 "silent" still means "fine OR too little signal to say". The counts
// are only printed when the advisory fires, so we cannot tell. That is why a
// local `low` under a current builder becomes a NOTE rather than being
// discarded — the disagreement is recorded without acting on it.
//
// → { verdict, source: 'server'|'local', reason, disagreement, local, advisory, builder }
function graphVerdict(text, serverVersion = null) {
  const local = graphYield(text);
  const advisory = parseImportResolution(text);
  const builder = parseGraphBuilder(text, serverVersion);
  const out = { local, advisory, builder, disagreement: null };

  if (advisory) {
    // An advisory measures what the builder that CUT this graph managed to
    // resolve. On a stale graph that is a verdict on an older resolver, and a
    // rebuild may clear it — so the finding must not send the caller straight
    // to variant B, which rewrites AGENTS.md to route every dependency question
    // to grep. That is the same mistake as trusting our floor over the server,
    // arriving from the advisory side instead (#207).
    const predatesServer = builder.state === 'stale' || builder.state === 'unknown';
    return {
      ...out,
      verdict: 'low',
      source: 'server',
      reason: `server states import resolution collapsed — ${advisory.resolved} of `
        + `${advisory.captured} captured imports resolved (${advisory.pct}%)`
        + (predatesServer
          ? ', but this graph predates the running resolvers — run codebase_graph_build '
            + 'and re-measure before installing variant B'
          : ''),
    };
  }

  if (builderCarriesAdvisory(builder)) {
    // The server certifies RESOLUTION; it does not certify that we could read
    // the status it printed. When the counts did not parse, that IS the
    // parser-drift tripwire firing (gotcha H, #85) — the one `parseGraphCounts`
    // anchors its patterns for and `parser-selftest.mjs` exists to pull. A
    // relabelled `Dependencies (edges):` line would otherwise arrive here as a
    // confident `ok`, silently disarming the alarm, which is the same
    // assert-from-a-string-we-could-not-read error `graphYield` refuses to make.
    if (local.nodes == null || local.edges == null) {
      return {
        ...out,
        verdict: 'unknown',
        source: 'local',
        reason: `${local.reason} — the server reported no advisory over the v${builder.builtBy} `
          + 'graph, but an unreadable status is not a certificate of health',
      };
    }
    // The server measured this graph and said nothing, so it is the authority.
    if (local.verdict === 'low') {
      out.disagreement = `local edges/file reads LOW (${local.reason}) but the server, `
        + `reading the import counts the v${builder.builtBy} builder recorded, reported no `
        + 'import-resolution problem — expected on an orphan-heavy repo; the server\'s '
        + 'ratio is the better measure';
    }
    // Worded as an absence of reported trouble, never as a positive
    // certificate. The server suppresses its advisory below 20 captured
    // imports, so on a small repo — exactly where `local.verdict` is already
    // `unknown` for too-few-files — its silence proves nothing, and "the
    // builder found no problem" would claim more than it said (#207).
    //
    // The staleness clause is not a hedge (#297): the ruling is real and it
    // stands, but it is a ruling about what an OLDER builder managed to
    // resolve, and the finding beside it says to rebuild. Saying only "ok"
    // here is how a graph two minor versions behind kept its clean bill of
    // health while the resolver fix it needed sat in the running server.
    return {
      ...out,
      verdict: 'ok',
      source: 'server',
      reason: 'the server reported no import-resolution problem over the '
        + `v${builder.builtBy} graph`
        + (builder.state === 'stale' ? ', which the running server did not build' : '')
        + (local.verdict === 'unknown' ? `, though ${local.reason}` : ''),
    };
  }

  // Cases 1 and 2: the advisory's silence carries no information, so fall back
  // to our own arithmetic and say out loud that that is what happened.
  //
  // `absent` has TWO causes and must not be reported as one. A pre-1.13.0
  // server never prints the line — but neither does a status with no graph in
  // it to stamp: "No code graph found", or a build still in progress. Blaming
  // the server version there states a falsehood about the user's install, on
  // the most current server there is, and it fires on every un-indexed repo —
  // which is the first status a new user ever sees. Reading a fact out of an
  // absent line whose absence has several causes is the very error this gate
  // was written to remove, so it does not get to live inside it (#207).
  //
  // The second arm is no longer "the server called it stale" (#297). What puts
  // a stamped graph here is a builder older than ADVISORY_SINCE — one that
  // recorded no import counts, so there is nothing for the running server to
  // compute a ratio from. Merely being a release behind does NOT: that graph
  // carries counts, the server read them, and its ruling is above.
  const why = builder.state === 'absent'
    ? (graphReady(text)
      ? 'server predates the import-resolution advisory'
      : 'no built graph here to carry an advisory or a builder stamp')
    : builder.builtBy
      ? `graph was cut by v${builder.builtBy}, which predates the import-resolution advisory`
      : 'graph predates the builder-version stamp';
  return {
    ...out,
    verdict: local.verdict,
    source: 'local',
    reason: `${local.reason} (${why}, so no server advisory to read)`,
  };
}

// A stale or unstamped builder is its own defect, independent of yield (#207).
//
// It names an action that repairs it — `codebase_graph_build` — which is the
// #220 test for `defect` rather than `note`. Reported even when the verdict is
// `ok`, because "ok" from a graph an older resolver cut is a weaker claim than
// "ok" from the current one, and because it is the standing explanation for a
// yield finding the caller would otherwise read as a code problem.
//
// BOTH versions are printed when both are known (#297). The whole point of the
// issue is that a stale artifact reporting READY should be self-evident, and
// "older than the running server" without the two numbers still leaves the
// reader to go and find them — which, in the case that prompted the issue, is
// what nobody did for months. A consuming repo had to write the hazard into its
// own AGENTS.md as a working rule because the tooling would not say it; this
// line is the tooling saying it.
function builderFinding(builder) {
  const server = builder.serverVersion ? ` (v${builder.serverVersion})` : '';
  if (builder.state === 'stale') {
    return `graph was built by v${builder.builtBy}, older than the running server${server} — `
      + 'any resolver fix since then is absent from it; run codebase_graph_build';
  }
  if (builder.state === 'unknown') {
    return 'graph was persisted before the builder version was recorded, so its edges '
      + `may predate the current resolvers${server ? ` running here${server}` : ''}; `
      + 'run codebase_graph_build';
  }
  return null;
}

// The builder finding health-check and verify report: judged against the
// server answering the SESSION's queries where that is known, and severed from
// a remedy that cannot work where it is not (#305).
//
// `builderFinding` above compares the graph with the server THIS DRIVER
// launched, and names codebase_graph_build. That remedy runs through the
// session's server, so it clears the finding only when the session's server is
// at least as new as ours. Three cases, three answers:
//
//   1. The session's version is known and the graph is OLDER than it — a real
//      #297 defect, repaired by codebase_graph_build. Judged against the
//      session even where our own server would call the graph current (a pin
//      behind the session): the session is what answers queries about it.
//   2. The session's version is known and the graph is NOT older than it, but
//      is older than ours — the graph is exactly what the session's server
//      would cut, so a rebuild re-stamps the same version and nothing moves. A
//      NOTE, costing no exit code, naming the remedy that does move it: update
//      the plugin, restart Claude Code so its MCP server reloads, then rebuild.
//      Before #305 this was a daily defect whenever the plugin lagged, and the
//      hook stopped being silent-when-clean over a state no rebuild changes.
//   3. The session's version is unknown and the graph is older than ours — a
//      DEFECT that says it could not tell which. Demoting it would regress #297
//      on today's common host, whose plugin floats: there a graph cut long ago
//      is exactly this shape. The remedy is the sequence #305 ran, completed:
//      rebuild, and if the stamp does not move, restart so the session's
//      server reloads — a floating definition resolves anew — and rebuild.
//
// An unstamped graph stays a defect everywhere: any server that rebuilds it
// stamps it, the session's included.
//
// → { severity, message, against: 'session'|'check' } | null
function graphBuilderFinding(builder, session) {
  if (builder.state === 'absent') return null;
  if (builder.state === 'unknown') {
    return { severity: SEVERITY.defect, message: builderFinding(builder), against: 'check' };
  }
  const built = builder.builtBy;
  const ours = builder.serverVersion ? ` (v${builder.serverVersion})` : '';
  const theirs = session?.version ?? null;
  const vsSession = theirs ? compareVersions(built, theirs) : null;
  if (vsSession === -1) {
    return {
      severity: SEVERITY.defect,
      against: 'session',
      message: `graph was built by v${built}, older than the server answering this session's queries `
        + `(v${theirs}; ${session.basis}) — any resolver fix since then is absent from it; `
        + 'run codebase_graph_build',
    };
  }
  if (builder.state !== 'stale') return null;
  if (vsSession === 0 || vsSession === 1) {
    return {
      severity: SEVERITY.note,
      against: 'session',
      message: `graph was built by v${built}, ${vsSession === 0 ? 'the version of' : 'newer than'} the `
        + `server answering this session's queries (v${theirs}; ${session.basis}); only this `
        + `check's own server${ours} is newer, so codebase_graph_build through the session would `
        + `re-stamp v${theirs} — update the plugin, restart Claude Code so its MCP server reloads, `
        + 'then run codebase_graph_build',
    };
  }
  return {
    severity: SEVERITY.defect,
    against: 'check',
    message: `graph was built by v${built}, older than this check's own server${ours}, and which `
      + `server answers the session's queries could not be determined (${session?.basis ?? 'not measured'}) `
      + '— run codebase_graph_build from the session; if the rebuild still stamps '
      + `v${built}, that server is behind this one: restart Claude Code so its MCP server reloads, `
      + 'then rebuild',
  };
}

// The unresolvedPct finding, worded from the verdict (#216, #308).
//
// The line itself is unconditional — it is reported whenever the figure clears
// the threshold, on healthy graphs too, because the statistic is worth having
// either way and the alternative (moving it inside the verdict branches) hides
// it from every repo that is fine. Only the gloss moves.
//
// The denominator is the server's own, not a paraphrase of it (#308). Since
// v1.14.0 `codebase_graph_status` explains the figure itself: the share of
// CAPTURED SYMBOL EDGES — calls, imports, re-exports, type or value references
// — that matched no project symbol. This gloss used to say "call edges", which
// undercounts what is being counted, and on a non-`ok` verdict it said
// "corroborates a resolver problem", which is the reading v1.14.0 added its
// paragraph to prevent: edges into runtime builtins and external libraries
// land in the share by construction, so it "is not a resolver failure rate".
// A cohort repo cited the 70% figure as the CAUSE of a codebase_impact
// under-report in its own docs, and it was the server's paragraph, not this
// line, that showed the causal claim was nobody's but the reader's.
//
// So neither branch offers it as evidence. Beside `ok` it says why it runs
// high on healthy code, so it is not read as a failure rate (#216: standing
// alone, the corroboration wording had one repo distrusting a provably exact
// import graph for weeks). Beside `low` or `unknown` the verdict already
// stands on the yield arithmetic and the server's advisory, and the figure is
// reported next to it — a second witness it cannot be would read, on a healthy
// repo with a lot of external surface, as one against the resolver.
//
// It is pushed at SEVERITY.note on EVERY verdict, not only on `ok` (#220). The
// figure is never independently actionable — no re-index lowers it, because the
// unmatched edges point at symbols that are not in the repo. Beside `low` or
// `unknown` the yield finding is already a defect and already sets the exit
// code, so the severity here changes nothing there; beside `ok` it is the
// difference between a silent healthy repo and a daily accusation.
//
// Exported, and rendered from one place, because the generated doc quotes it
// verbatim; tests/structural/test_socraticode_graph_yield.py asserts the two
// agree, so a reword cannot leave the doc behind. The returned string carries
// no severity prefix — renderFinding() adds it — so the doc quotes the message
// and not the envelope.
const UNRESOLVED_COUNTS = 'share of captured symbol edges (calls, imports, re-exports, type or '
  + 'value references) matching no project symbol';
const UNRESOLVED_BY_CONSTRUCTION = 'edges into builtins and external libraries count by construction';
function unresolvedFinding(unresolvedPct, verdict) {
  const gloss = verdict === 'ok'
    ? `${UNRESOLVED_COUNTS}; ${UNRESOLVED_BY_CONSTRUCTION}, so it runs high on healthy code — `
      + 'verdict is ok, so this is a statistic, not a defect'
    : `${UNRESOLVED_COUNTS} — reported beside the verdict, not as evidence for it, since `
      + UNRESOLVED_BY_CONSTRUCTION;
  return `graph unresolved ${unresolvedPct}% (> ${GRAPH_UNRESOLVED_WARN_PCT}%) — ${gloss}`;
}

// ── finding severity (#220) ─────────────────────────────────────────────────
// health-check keeps ONE `findings` array and gates its exit code on a
// per-finding severity rather than on emptiness.
//
//   defect — a state a named action repairs. Sets `healthy: false` and
//            `exitCode: 1`, which is what socraticode-health.sh keys its whole
//            session injection on.
//   note   — a measurement no action changes. Reported, in the JSON and on
//            stderr, and free.
//
// Why the severity rides in the finding STRING rather than in a new key or a
// new element type: `findings` stays `string[]`, so `jq -r '.findings[]'` and
// every substring match a consumer already wrote keep working. Two shapes were
// weighed and rejected at #230's scoring gate, and are recorded here rather
// than deleted because #207 revisits this seam when
// giancarloerra/SocratiCode#112 ships an upstream resolution advisory:
//
//   - A second `observations` array. Cleaner in the abstract, but a JSON
//     contract change every consumer of the driver's output has to learn.
//   - Suppressing the neutral line on an `ok` verdict (#216's original part 2).
//     Discards a figure an operator may want, and leaves a staleness finding
//     (#225) with nowhere to sit that does not fail the check.
//
// A severity field admits an "acknowledged" level later without a second
// contract change, which is the shape #207 needs.
const SEVERITY = { defect: 'defect', note: 'note' };
const NOTE_PREFIX = 'note: ';

function renderFinding(f) {
  return f.severity === SEVERITY.note ? `${NOTE_PREFIX}${f.message}` : f.message;
}

// codebase_graph_query on a file with no resolved edges: an ordinary sentence,
// not an error. This is the confirmatory probe's failure shape — and the exact
// string an agent misreads as "nothing depends on this file".
function graphQueryEmpty(text) {
  return /No dependency information found/i.test(text);
}

// codebase_health: green when nothing is reported down. Matched by the negative
// because the healthy rendering varies by build while the failure vocabulary
// (✗ / not running / unavailable / missing) is what the tool exists to say.
function healthProblems(text) {
  const problems = [];
  for (const line of String(text).split('\n')) {
    if (/(✗|✘|\bnot running\b|\bunavailable\b|\bmissing\b|\bnot installed\b|\bfailed\b)/i.test(line)
        && line.trim()) {
      problems.push(line.trim());
    }
  }
  return problems;
}

// ── manifest validation ─────────────────────────────────────────────────────
const MANIFEST_NAME = '.socraticodecontextartifacts.json';

// Mirrors the server's own manifest checks (services/context-artifacts.ts) plus
// path resolution, so a bad manifest is caught BEFORE a multi-hour index rather
// than after. Returns { present, errors, count }.
//
// Why this has to be strict: the server throws on a bad manifest, but
// codebase_status swallows that throw ("non-critical") and simply omits the
// `Context artifacts:` line. An invalid manifest is therefore indistinguishable
// from "no artifacts configured" in every status reading — it reports a
// contented `artifacts 0/0` while context search is completely absent (#85).
function validateManifest(projectPath) {
  const manifestPath = joinPath(projectPath, MANIFEST_NAME);
  const result = { path: manifestPath, present: false, errors: [], count: 0 };
  if (!existsSync(manifestPath)) return result;
  result.present = true;

  let parsed;
  try {
    parsed = JSON.parse(readFileSync(manifestPath, 'utf8'));
  } catch (e) {
    result.errors.push(`not valid JSON: ${e.message}`);
    return result;
  }

  // The legacy top-level array. The server requires an object and rejects this
  // outright; it is the single most likely shape to inherit from an older repo.
  if (Array.isArray(parsed)) {
    result.errors.push(
      'top level is a JSON array, but the server requires an object — wrap it:\n' +
      '      {"artifacts": [ …the existing array… ]}'
    );
    return result;
  }
  if (parsed === null || typeof parsed !== 'object') {
    result.errors.push('top level must be a JSON object');
    return result;
  }

  const artifacts = parsed.artifacts;
  if (artifacts === undefined) {
    result.errors.push('no "artifacts" key — the manifest declares nothing to index');
    return result;
  }
  if (!Array.isArray(artifacts)) {
    result.errors.push('"artifacts" must be an array');
    return result;
  }
  result.count = artifacts.length;
  if (artifacts.length === 0) {
    result.errors.push('"artifacts" is empty — delete the manifest or declare entries');
    return result;
  }

  const seen = new Map();
  artifacts.forEach((a, i) => {
    if (!a || typeof a !== 'object' || Array.isArray(a)) {
      result.errors.push(`artifacts[${i}] must be an object`);
      return;
    }
    for (const field of ['name', 'path', 'description']) {
      if (typeof a[field] !== 'string' || !a[field].trim()) {
        result.errors.push(`artifacts[${i}].${field} must be a non-empty string`);
      }
    }
    if (a.paths !== undefined) {
      result.errors.push(`artifacts[${i}] has a "paths" key — there is no plural field; one artifact = one "path" string`);
    }
    if (typeof a.name === 'string' && a.name.trim()) {
      const key = a.name.trim().toLowerCase();
      if (seen.has(key)) {
        result.errors.push(`artifacts[${i}].name "${a.name}" duplicates artifacts[${seen.get(key)}] — names are compared case-insensitively`);
      } else {
        seen.set(key, i);
      }
    }
    if (typeof a.path === 'string' && a.path.trim()) {
      if (/[*?]/.test(a.path)) {
        result.errors.push(`artifacts[${i}].path "${a.path}" looks like a glob — the server stat()s the value verbatim; point at a literal file or directory`);
      } else if (!existsSync(resolvePath(projectPath, a.path))) {
        // Not merely cosmetic: the server skips a non-resolving path silently,
        // so artifacts N/N never reaches parity and the driver blocks to the
        // full timeout waiting for a count that cannot arrive.
        result.errors.push(`artifacts[${i}].path does not resolve: ${a.path}`);
      }
    }
  });

  return result;
}

// Authoritative expected artifact count from the repo's manifest. The status
// line can't distinguish "no artifacts configured" (0 expected) from "artifacts
// not reported yet" (line absent) — both parse to 0/0 — so we read the manifest
// instead. Returns the declared count, or null when there is no manifest.
// A manifest that EXISTS but is invalid aborts: degrading to "0 expected" is
// what let a rejected manifest pass as green.
function expectedArtifactCount(projectPath) {
  const m = validateManifest(projectPath);
  if (!m.present) return null;
  if (m.errors.length) {
    die(
      `${MANIFEST_NAME} is invalid — the server will reject it, and codebase_status omits the\n` +
      'artifact line entirely when it does, so this would otherwise pass as a green "artifacts 0/0"\n' +
      'with no context search at all:\n' +
      m.errors.map((e) => `  - ${e}`).join('\n')
    );
  }
  return m.count;
}

// ── linked projects: configured ≠ resolved (#281) ───────────────────────────
// socraticode's loadLinkedProjects() (config.js, 1.13.3) reads two sources —
// `.socraticode.json`'s `linkedProjects` array and the comma-separated
// SOCRATICODE_LINKED_PROJECTS — resolves each entry against the project root,
// and DROPS any path that does not exist. Silently, and upstream documents that
// as intended. It is a soft failure: you search less, you are not told a wrong
// answer. But nothing anywhere said which links resolved, so a cohort that
// believes it has cross-repo search and one that has it looked identical.
//
// The same resolution, reported rather than dropped. Transcribed, not imported:
// the server package is not a dependency of this driver, and on a plugin-only
// host it lives in the npx cache where nothing can import it (#85/3b). What is
// mirrored, so a count here is a count there:
//
//   - an entry is a string that is non-empty once trimmed, resolved with
//     path.resolve(root, entry), so relative entries are relative to the root;
//   - entries are de-duplicated by resolved path across BOTH sources, as the
//     upstream Set does;
//   - an entry resolving to the root itself is dropped and is not counted: it
//     names the collection every search already reads, so dropping it costs
//     nothing and reporting it would be noise;
//   - a `.socraticode.json` that cannot be read or does not parse is ignored
//     whole — upstream's loader returns null on any throw — so that is
//     reported too, since it drops every link the file declares at once.
//
// The env source is THIS process's environment. Through the hook that is the
// session's, which is where installs before #287 wrote the variable
// (`.claude/settings.local.json`'s env block, one host's absolute paths) and
// what the plugin's server inherits — the same route SOCRATICODE_PROBE_FILE
// already takes. The skill now writes relative entries into the committed
// `.socraticode.json` instead.
const SOCRATICODE_CONFIG_NAME = '.socraticode.json';
const LINKED_ENV = 'SOCRATICODE_LINKED_PROJECTS';

function linkedProjects(projectPath, env = process.env) {
  const root = resolvePath(projectPath);
  const report = { configured: 0, resolved: [], missing: [], configError: null };
  const seen = new Set();
  const consider = (entry, source) => {
    const trimmed = entry.trim();
    if (!trimmed) return;
    const abs = resolvePath(root, trimmed);
    if (abs === root || seen.has(abs)) return;
    seen.add(abs);
    report.configured += 1;
    (existsSync(abs) ? report.resolved : report.missing).push({ path: trimmed, source });
  };

  const cfgPath = joinPath(root, SOCRATICODE_CONFIG_NAME);
  if (existsSync(cfgPath)) {
    let cfg = null;
    try {
      cfg = JSON.parse(readFileSync(cfgPath, 'utf8'));
    } catch (e) {
      // One message for both throws, as upstream has one catch for both: a
      // file that is a directory, or unreadable, is not a JSON problem, and
      // calling it one sends the reader to fix syntax that is not there.
      report.configError = `${SOCRATICODE_CONFIG_NAME} cannot be read as JSON (${e.message}), `
        + 'so the server ignores the whole file, linkedProjects included';
    }
    const declared = cfg && typeof cfg === 'object' ? cfg.linkedProjects : undefined;
    if (Array.isArray(declared)) {
      for (const p of declared) if (typeof p === 'string') consider(p, SOCRATICODE_CONFIG_NAME);
    } else if (declared !== undefined) {
      // Upstream reads the key only when it is an array; a bare string — the
      // likeliest slip — is ignored as silently as a missing path.
      report.configError = `${SOCRATICODE_CONFIG_NAME}'s linkedProjects is not an array, `
        + 'so the server ignores it';
    }
  }
  const fromEnv = (env[LINKED_ENV] || '').trim();
  if (fromEnv) for (const p of fromEnv.split(',')) consider(p, LINKED_ENV);
  return report;
}

// One defect for the whole of it, or null. Worded for the one tool it touches:
// linked collections are consulted by codebase_search ONLY — the upstream
// resolver has exactly one caller — and only when the call passes
// includeLinked: true, which defaults to false. Saying "search is degraded"
// without that qualifier would send a reader hunting in tools it never reached.
function linkedProjectsFinding(linked) {
  const parts = [];
  if (linked.configError) parts.push(linked.configError);
  if (linked.missing.length) {
    const named = linked.missing.map((m) => `${m.path} (${m.source})`).join(', ');
    parts.push(
      `linkedProjects — ${linked.resolved.length} of ${linked.configured} resolved (missing: ${named}); `
      + 'codebase_search with includeLinked: true skips the missing ones and says nothing. '
      + 'Check out the missing paths, or drop them from where they are declared'
    );
  }
  return parts.length ? parts.join('; ') : null;
}

// ── the store a launched server would address (#287) ────────────────────────
// SocratiCode names a project's collections by its projectId, which config.js
// (1.13.3) resolves from SOCRATICODE_PROJECT_ID, then `.socraticode.json`'s
// `projectId`, then sha256(<absolute path>)[:12]. Against a per-host Qdrant the
// hash is harmless. Against a SHARED store it is not per-host at all: exe.dev
// VMs check a repo out at the same path, so broker's VM and notifier's clone of
// broker both resolve to `d4eab3ecb321` — two hosts writing one collection set
// under a lock that is host-local (os.tmpdir()/socraticode-locks), and nothing
// reports it.
//
// A launch is already a write. At startup the server's auto-resume runs an
// incremental update of the project at its cwd whenever that project's
// collection exists, and every status or query call starts the file watcher on
// the same condition. So the guard stands before EVERY command that launches a
// server, not before `index` alone: `status` under the wrong id writes too.
//
// The mode is the other half. A project's settings `env` block reaches the
// server only through a Claude Code session in a trusted folder; a process that
// lacks it launches a managed server — a local Docker stack, started through
// the socket if the host has one — while the settings say external.
//
// Transcribed rather than imported, like linkedProjects() above and for the
// same reason: nothing here can import the server package.
const PROJECT_ID_PATTERN = /^[a-zA-Z0-9_-]+$/;
const LOCAL_SETTINGS = '.claude/settings.local.json';
const PROJECT_SETTINGS = [LOCAL_SETTINGS, '.claude/settings.json'];
const PATH_HASH = 'path hash';

function readJsonOrNull(path) {
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return null; }
}

// Why a file that exists could not be used, or null — absent included. The
// null above is upstream's loader and right for the id it mirrors; it is wrong
// for a finding, where "absent" and "does not parse" need opposite remedies:
// write the file, or fix it without rewriting it (#287 round 2, CR 34).
function unreadable(path) {
  if (!existsSync(path)) return null;
  try { JSON.parse(readFileSync(path, 'utf8')); return null; } catch (e) { return e.message; }
}

// config.js coreProjectId: the fallback id, from the resolved (not real) path.
function pathHash(folder) {
  return createHash('sha256').update(resolvePath(folder)).digest('hex').slice(0, 12);
}

// A folder's own declared projectId, trimmed, or null — readProjectIdFromConfigFile
// minus its throw, so an invalid id comes back to be reported rather than
// ending the run.
function declaredProjectId(folder) {
  const cfg = readJsonOrNull(joinPath(folder, SOCRATICODE_CONFIG_NAME));
  const id = cfg && typeof cfg === 'object' ? cfg.projectId : undefined;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

// The variables that decide which store a server reaches, which collections
// in it, and how it embeds — every one an untrusted folder's dropped env block
// can take with it. The prefix and the id override choose the collections
// themselves: left behind, either sends every write to another set in the
// same store, so they are store variables as much as the URL is (#287 round
// 2, CR 28).
const STORE_KEYS = [
  'QDRANT_MODE', 'QDRANT_URL', 'QDRANT_HOST', 'QDRANT_PORT', 'QDRANT_API_KEY',
  'QDRANT_COLLECTION_PREFIX', 'SOCRATICODE_PROJECT_ID',
  'OLLAMA_MODE', 'OLLAMA_URL', 'EMBEDDING_PROVIDER', 'EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS',
];

// Each store variable a project's settings files declare, local over shared,
// with the file that declared it. Only the project's files: theirs is the block
// an untrusted folder drops, where user settings apply everywhere regardless.
function declaredStoreEnv(root) {
  const out = {};
  for (const rel of [...PROJECT_SETTINGS].reverse()) {
    const env = readJsonOrNull(joinPath(root, rel))?.env;
    if (!env || typeof env !== 'object') continue;
    for (const key of STORE_KEYS) {
      const v = env[key];
      if (typeof v === 'string' || typeof v === 'number') out[key] = { value: String(v), in: rel };
    }
  }
  return out;
}

// config.js projectIdFromPath, including the branch suffix it appends to the
// hash — and only to the hash — under SOCRATICODE_BRANCH_AWARE=true.
function effectiveProjectId(root, env) {
  const fromEnv = (env.SOCRATICODE_PROJECT_ID || '').trim();
  if (fromEnv) return { value: fromEnv, source: 'SOCRATICODE_PROJECT_ID' };
  const fromFile = declaredProjectId(root);
  if (fromFile) return { value: fromFile, source: SOCRATICODE_CONFIG_NAME };
  let value = pathHash(root);
  if (env.SOCRATICODE_BRANCH_AWARE === 'true') {
    const branch = gitIn(root, ['rev-parse', '--abbrev-ref', 'HEAD']);
    const safe = branch && branch !== 'HEAD'
      ? branch.replace(/[^a-zA-Z0-9_-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')
      : '';
    if (safe) value = `${value}__${safe}`;
  }
  return { value, source: PATH_HASH };
}

// The checkout a process here runs in, when that is ANOTHER worktree of the
// project's repository; else null. A session carries the env block of the
// checkout it was started in, while the hook — and a relative projectPath —
// measure the main checkout (#180). From a worktree session the two differ,
// and the main checkout's git-ignored settings.local.json, the key's home, is
// not a file that session ever read (#287 round 2, CR 30). A process in an
// unrelated repository, or in none, is still held to the project's block.
function otherWorktree(root, cwd) {
  const top = gitIn(cwd, ['rev-parse', '--show-toplevel']);
  if (top === null || realOrSelf(top) === realOrSelf(root)) return null;
  const mine = gitCommonDir(cwd);
  const theirs = gitCommonDir(root);
  return mine && theirs && realOrSelf(mine) === realOrSelf(theirs) ? realOrSelf(top) : null;
}

// What a server lacking `unset` runs, named for what is actually missing: the
// mode moves the store; OLLAMA_MODE moves only the embedder, and only when the
// embedder is Ollama. "Falls back to a local Docker stack instead of reaching
// the store" was said of both, and of the second it is false (#287 round 2,
// CR 29).
function runsWithout(unset, env) {
  if (unset.includes('QDRANT_MODE')) {
    return 'runs a managed store — a local Qdrant in Docker — instead of reaching the external one';
  }
  if (unset.includes('OLLAMA_MODE') && (env.EMBEDDING_PROVIDER || 'ollama') === 'ollama') {
    return 'embeds through Ollama in auto mode — a container, unless a native Ollama answers on '
      + "localhost:11434 — not through the store's";
  }
  return 'runs without them';
}

// Every finding is a defect except absolute linked entries: those still
// resolve on this host, and only portability suffers. A defect blocks a
// launch (guardStore) unless it is marked `blocking: false` — the sibling
// defects, which break includeLinked search but send no write to the wrong
// collections, so they must not stop this project being indexed or measured.
const blocks = (f) => f.severity === SEVERITY.defect && f.blocking !== false;

function storeConfig(projectPath, env = process.env, cwd = process.cwd()) {
  const root = resolvePath(projectPath);
  const store = env.QDRANT_MODE === 'external' ? 'external' : 'managed';
  const declaredEnv = declaredStoreEnv(root);
  const worktree = otherWorktree(root, cwd);
  // The block this process could have been handed: its own checkout's.
  const carriedBlock = worktree ? declaredStoreEnv(worktree) : declaredEnv;
  const declared = declaredEnv.QDRANT_MODE
    ? { mode: declaredEnv.QDRANT_MODE.value, in: declaredEnv.QDRANT_MODE.in }
    : null;
  const hash = pathHash(root);
  const projectId = effectiveProjectId(root, env);
  const findings = [];
  const defect = (message) => findings.push({ severity: SEVERITY.defect, message });
  const siblingDefect = (message) => findings.push({ severity: SEVERITY.defect, message, blocking: false });
  const note = (message) => findings.push({ severity: SEVERITY.note, message });

  // A settings file that does not parse was read above as declaring nothing,
  // which printed "OK: managed store" for one that declared external. Claude
  // Code applies none of such a file, so the block it may hold reaches no
  // session — the untrusted-folder fallback by another road — and the store a
  // launch would address cannot be known. A defect, then: it blocks (#287
  // round 2, CR 34).
  for (const dir of worktree ? [root, worktree] : [root]) {
    for (const rel of PROJECT_SETTINGS) {
      const why = unreadable(joinPath(dir, rel));
      if (why) {
        defect(
          `${dir === root ? rel : joinPath(dir, rel)} does not parse (${why}) — Claude Code applies none of it, `
          + 'so any env block it declares reaches no session, and the store a server here would address '
          + 'cannot be checked. Fix its JSON'
        );
      }
    }
  }

  // Every store variable the block declares, not QDRANT_MODE alone (#287 CR
  // 2): with the mode carried and OLLAMA_MODE not, the launched server runs
  // Ollama in auto mode and starts a container. Names only — one is the key.
  //
  // Unset and different are two failures, told apart (#287 round 2, CR 29):
  // the first is a dropped block, the second a process started before the
  // file changed — in a folder already trusted, where no prompt appears.
  //
  // Keyed on the store the repo is CONFIGURED for OR the one this process
  // reaches (#287 round 2, CR 40). With the mode from user settings or a shell
  // export and OLLAMA_* in the project block, a check keyed on the declared
  // mode alone never ran, while the server embedded through a container.
  const external = store === 'external' || declared?.mode === 'external';
  if (external) {
    const unset = [];
    const different = [];
    for (const k of Object.keys(carriedBlock)) {
      const carried = env[k] ?? '';
      if (carried === '') unset.push(k);
      else if (carried !== carriedBlock[k].value) different.push(k);
    }
    const named = (keys) => keys
      .map((k) => `${k} (${worktree ? joinPath(worktree, carriedBlock[k].in) : carriedBlock[k].in})`)
      .join(', ');
    // Declared in the main checkout's local file and nowhere this worktree
    // reads: no restart or trust prompt brings it, and saying so sent the
    // operator after a trust problem that did not exist.
    const stranded = worktree
      ? Object.keys(declaredEnv).filter((k) => declaredEnv[k].in === LOCAL_SETTINGS
        && !(k in carriedBlock) && (env[k] ?? '') === '')
      : [];
    if (stranded.length) {
      const them = stranded.length > 1 ? 'them' : 'it';
      defect(
        `${stranded.join(', ')} ${stranded.length > 1 ? 'are' : 'is'} declared only in `
        + `${joinPath(root, LOCAL_SETTINGS)}, which belongs to that checkout — this process runs in ${worktree}, `
        + `another worktree whose settings do not declare ${them}, so a server launched from here runs without ${them}. `
        + `Hold ${them} in user settings, which every checkout reads, or copy the file into this worktree`
      );
    }
    if (unset.length) {
      defect(
        'the project settings declare store variables this process\'s environment does not carry: '
        + `${named(unset)} — a server launched from here ${runsWithout(unset, env)}. `
        + "Claude Code applies a project's env block only in a trusted folder, and only to sessions "
        + "started after it was written: run from such a session, or export the block's variables"
      );
    }
    if (different.length) {
      defect(
        'this process\'s environment carries other values than the project settings declare for: '
        + `${named(different)} — a server launched from here runs those instead. A session started `
        + 'before the settings changed keeps the old values: restart it, or re-export them'
      );
    }
  }

  if (projectId.source !== PATH_HASH && !PROJECT_ID_PATTERN.test(projectId.value)) {
    defect(
      `projectId "${projectId.value}" (${projectId.source}) is outside [a-zA-Z0-9_-] — `
      + 'the server throws on every call rather than sanitize it'
    );
  }

  // Keyed on the store the repo is CONFIGURED for, not only the one this
  // process would reach: with the mode defect above, fixing trust alone would
  // otherwise walk the operator straight into this one on the next run.
  const configError = unreadable(joinPath(root, SOCRATICODE_CONFIG_NAME));
  if (external && projectId.source === PATH_HASH) {
    const collection = `${env.QDRANT_COLLECTION_PREFIX || ''}codebase_${projectId.value}`;
    // A file that does not parse is ignored whole upstream, projectId and all.
    // "Write .socraticode.json" there invited an overwrite that would drop
    // every other key it holds, linkedProjects first (#287 round 2, CR 34).
    defect(configError
      ? `${SOCRATICODE_CONFIG_NAME} does not parse (${configError}), so the server ignores all of it — its `
        + `projectId included — and names this project's collections by its path hash (${collection}), `
        + `an id every host checking the repo out at ${root} shares. Fix its JSON rather than rewriting it, `
        + 'which would drop the keys it already holds'
      : `this project uses an external store but declares no projectId, so its collections are named by its path hash `
        + `(${collection}) — an id every host checking the repo out at ${root} shares, under a host-local lock. `
        + `Write .socraticode.json with {"projectId": "<repo name>"} before any server here reaches the store`);
  } else if (external && projectId.value === hash) {
    // Named by where it came from (#287 round 2, CR 44): through the
    // environment it is the documented one-session cleanup of the old set,
    // and "Use the repo name" told a checkout that already declares one to
    // write it again.
    defect(projectId.source === 'SOCRATICODE_PROJECT_ID'
      ? `projectId "${hash}" (SOCRATICODE_PROJECT_ID) is this checkout's own path hash, which reaches the `
        + 'collections written before .socraticode.json had a projectId — the one-session cleanup in '
        + "external-store.md. Nothing launched here should write under it: unset it once the removals are done"
      : `projectId "${hash}" (${projectId.source}) is this checkout's own path hash — the id every host with `
        + 'this layout resolves to without one, so declaring it names nothing. Use the repo name');
  }

  // Each sibling as upstream's resolveLinkedCollections() reads it: its own
  // declared id, else its path hash. A sibling on this project's id is one
  // collection set written by two repos, and the link is dropped as a
  // duplicate of this one. Two siblings on one id collapse the same way, and a
  // sibling whose declared id is invalid makes upstream THROW — failing every
  // includeLinked search, not only its own (#287 CR 12).
  const linked = linkedProjects(root, env);
  const siblingIds = new Map();
  for (const entry of linked.resolved) {
    const sibling = resolvePath(root, entry.path);
    const declaredId = declaredProjectId(sibling);
    if (declaredId && !PROJECT_ID_PATTERN.test(declaredId)) {
      siblingDefect(
        `linked project ${entry.path} (${entry.source}) declares projectId "${declaredId}", outside `
        + '[a-zA-Z0-9_-] — upstream throws on it, so every codebase_search with includeLinked: true fails. '
        + "Fix the projectId in that sibling's .socraticode.json, a host step outside this repo"
      );
      continue;
    }
    const id = declaredId ?? pathHash(sibling);
    if (id === projectId.value) {
      defect(
        `projectId "${projectId.value}" is also linked project ${entry.path}'s (${entry.source}) — `
        + 'the two repos write one collection set, and codebase_search drops the link as a duplicate of this one. '
        + "Give this project its own projectId, or correct the sibling's .socraticode.json if it is the stub that is wrong"
      );
    } else if (siblingIds.has(id)) {
      siblingDefect(
        `linked projects ${siblingIds.get(id)} and ${entry.path} both resolve to projectId "${id}" — `
        + 'one collection, searched once, so the repo that did not write it is never searched. '
        + "Correct the one whose .socraticode.json names the other's id, a host step outside this repo"
      );
    } else {
      siblingIds.set(id, entry.path);
    }
  }
  for (const entry of [...linked.resolved, ...linked.missing]) {
    if (entry.source === SOCRATICODE_CONFIG_NAME && isAbsolutePath(entry.path)) {
      note(
        `linkedProjects entry ${entry.path} is absolute, which names one host's layout in a committed file — `
        + 'write it relative to the repo root (../<sibling>)'
      );
    }
  }

  return { store, declared, projectId, pathHash: hash, findings };
}

// Before any command that launches a server. Dies naming every defect: the
// launch itself is the write this exists to prevent, so there is nothing to
// measure first.
function guardStore(projectPath) {
  const config = storeConfig(projectPath);
  const defects = config.findings.filter(blocks);
  if (defects.length) {
    die(
      'refusing to launch a server — it would address the wrong store, or the wrong collections in it:\n'
      + defects.map((f) => `  - ${f.message}`).join('\n')
      + '\n  Check with: node mcp-driver.mjs validate-store <projectPath>'
    );
  }
  return config;
}

// ── projectPath resolution (#226, generalizing #180) ────────────────────────
// SocratiCode indexes by ABSOLUTE project path. A relative argument — `.` most
// of all — therefore names whatever directory the caller happens to be standing
// in, and from a git worktree or a subdirectory that is a project the server
// never saw. The failure is not an error: every check answers confidently about
// the wrong path and reports a healthy index as broken.
//
// socraticode-health.sh already resolves this for its own invocation (#180).
// The doc beside it went on handing readers `health-check .`, and consumers
// copied that line into their own docs/ — so the resolution moves into the
// driver, where it fixes the copies that already exist, and the doc shows the
// explicit spelling, which stops the next one.
//
// An ABSOLUTE argument is taken verbatim. It is an explicit statement of which
// project to measure, it is what the hook passes, and it is the only spelling
// that can name a worktree on purpose.

function gitIn(dir, args) {
  const out = spawnSync('git', ['-C', dir, ...args], { encoding: 'utf8' });
  return out.status === 0 && out.stdout ? out.stdout.trim() : null;
}

const realOrSelf = (p) => { try { return realpathSync(p); } catch { return p; } };

// The checkout SocratiCode indexes, for any directory inside a repo — or null
// when there is no repo, no git, or no checkout to be sure of.
//
// The COMMON git dir, not this checkout's private one: `--git-dir` in a
// worktree yields .git/worktrees/<name>, while `--git-common-dir` yields the
// shared .git for a worktree and a primary checkout alike, and its parent is
// the directory that was indexed.
//
// Then RESOLVE, THEN VERIFY — the hook's discipline, for the same reason. The
// parent of the common dir is the checkout for an ordinary repo and for every
// worktree of it, and is NOT for a bare repo's worktree or a --separate-git-dir
// clone. Confirming that git calls the candidate a working-tree root keeps a
// layout we guessed wrong about from being measured; the caller's own path is
// the safer answer there.
// The shared git dir of `dir`'s repository, absolute, or null outside one.
// --path-format=absolute needs git >= 2.31; without it --git-common-dir is
// relative to the queried directory in a primary checkout (plain `.git`) and
// absolute in a worktree, so the fallback resolves it against that directory.
function gitCommonDir(dir) {
  const absolute = gitIn(dir, ['rev-parse', '--path-format=absolute', '--git-common-dir']);
  if (absolute !== null) return absolute;
  const relative = gitIn(dir, ['rev-parse', '--git-common-dir']);
  return relative === null ? null : resolvePath(dir, relative);
}

function mainCheckoutOf(dir) {
  const commonDir = gitCommonDir(dir);
  if (commonDir === null) return null;
  const candidate = resolvePath(commonDir, '..');
  const top = gitIn(candidate, ['rev-parse', '--show-toplevel']);
  if (top === null) return null;
  return realOrSelf(top) === realOrSelf(candidate) ? realOrSelf(top) : null;
}

function resolveProjectPath(arg) {
  if (arg && isAbsolutePath(arg)) return resolvePath(arg);
  const literal = arg ? resolvePath(arg) : process.cwd();
  const main = mainCheckoutOf(literal);
  if (main === null || main === realOrSelf(literal)) return literal;
  // Announced, never silent: a driver that answers about a path the caller did
  // not name, with nothing in the output saying so, is the same disease facing
  // the other way.
  console.error(
    `[driver] measuring ${main}, not ${literal} — SocratiCode indexes by absolute project path, `
    + 'and a relative argument from a git worktree or a subdirectory names a project that was '
    + 'never indexed (#180). Pass an absolute path to measure a different one.'
  );
  return main;
}

// ── high-level flows ─────────────────────────────────────────────────────────
function die(msg) { console.error(`ERROR: ${msg}`); process.exit(1); }

// The driver's server does what it is asked and nothing else (#287 CR 1).
// Upstream's startup auto-resume runs an incremental update of the project at
// the server's cwd whenever that project's collection exists, and the cwd is
// the caller's — through the health hook, the session's, which may be a
// worktree. With a shared projectId that wrote a worktree's files into the
// store once a day, from a hook whose contract is "reports; never re-indexes".
// Upstream reads SOCRATICODE_AUTO_RESUME=off before any Docker or Qdrant
// access. `readOnly` also stops the watcher that status and query calls start
// on their own, so `status`, `verify` and `health-check` write no index
// content; `index` keeps it, since a completed index starting its watcher is
// upstream's normal sequence. Not "nothing" (#287 round 2, CR 35): upstream's
// readiness paths still act — on a managed store codebase_status starts a
// stopped Qdrant container, codebase_graph_status creates a project's empty
// symbol-graph metadata collection when a graph lacks one, and verify's sample
// search pulls a missing embedding model, onto the store's Ollama when it is
// external.
async function withClient(fn, { readOnly = false, project } = {}) {
  const launch = resolveServerLaunch({ project });
  console.error(`[driver] server launch (${launch.source}): ${launch.command} ${launch.args.join(' ')}`);
  const client = new RpcClient(launch, {
    SOCRATICODE_AUTO_RESUME: 'off',
    ...(readOnly ? { SOCRATICODE_WATCHER: 'manual' } : {}),
  });
  try {
    await client.handshake();
    return await fn(client);
  } finally {
    client.kill();
  }
}

// Print how the server would be launched, without launching it. The cheap probe
// for #85/3b: it answers "can this host find the server at all" with no Docker,
// no Qdrant, and no network.
function cmdResolve(projectPath) {
  const launch = resolveServerLaunch({ project: projectPath });
  process.stdout.write(JSON.stringify({
    source: launch.source,
    command: launch.command,
    args: launch.args,
    env: launch.env,
  }, null, 2) + '\n');
}

// Phase 4 gate: validate the manifest before paying for an index.
// Machine-readable verdict on stdout, prose on stderr (AGENTS.md script
// convention), so this can gate a shell pipeline as well as a human.
function cmdValidateManifest(projectPath) {
  const m = validateManifest(projectPath);
  process.stdout.write(JSON.stringify({
    manifest: m.path,
    present: m.present,
    count: m.count,
    valid: m.present && m.errors.length === 0,
    errors: m.errors,
  }, null, 2) + '\n');

  if (!m.present) {
    console.error(`[driver] no ${MANIFEST_NAME} at ${projectPath} — 0 context artifacts expected`);
    return;
  }
  if (m.errors.length) {
    console.error(`[driver] ${m.path} — INVALID:`);
    for (const e of m.errors) console.error(`  - ${e}`);
    process.exit(1);
  }
  console.error(`[driver] ${m.path} — OK: ${m.count} artifact(s), every path resolves`);
}

// Phase 5 gate: the store and the id a server launched here would use, checked
// before one is — the native path's codebase_index has no guard of its own.
// Same convention as validate-manifest: verdict on stdout, prose on stderr.
function cmdValidateStore(projectPath) {
  const s = storeConfig(projectPath);
  const defects = s.findings.filter(blocks);
  const reported = s.findings.filter((f) => f.severity === SEVERITY.defect && !blocks(f));
  const notes = s.findings.filter((f) => f.severity === SEVERITY.note);
  process.stdout.write(JSON.stringify({
    config: joinPath(projectPath, SOCRATICODE_CONFIG_NAME),
    store: s.store,
    declared: s.declared,
    projectId: s.projectId,
    pathHash: s.pathHash,
    valid: defects.length === 0,
    // The findings `valid` answers to. A sibling's defect sat in `findings`
    // beside `valid: true`, rendered exactly like one that blocks, with
    // nothing to tell them apart (#287 round 2, CR 45).
    blocking: defects.map(renderFinding),
    findings: s.findings.map(renderFinding),
  }, null, 2) + '\n');

  if (defects.length) {
    console.error('[driver] store config — INVALID:');
    for (const f of defects) console.error(`  - ${f.message}`);
  } else {
    console.error(`[driver] store config — OK: ${s.store} store, projectId "${s.projectId.value}" (${s.projectId.source})`);
  }
  if (reported.length) {
    console.error('[driver] linked projects — defects, but not ones that block a launch:');
    for (const f of reported) console.error(`  - ${f.message}`);
  }
  for (const f of notes) console.error(`  - ${renderFinding(f)}`);
  // exitCode, not exit(): the verdict above is the contract, and stdout on a
  // pipe is asynchronous.
  if (defects.length) process.exitCode = 1;
}

async function cmdStatus(projectPath) {
  guardStore(projectPath);
  await withClient(async (client) => {
    const text = await client.callTool('codebase_status', { projectPath });
    process.stdout.write(text + '\n');
  }, { readOnly: true, project: projectPath });
}

async function cmdIndex(projectPath) {
  guardStore(projectPath);
  // Authoritative expected artifact count (null when there's no manifest). This
  // is what makes "artifacts N/N" real — the status line alone can't tell
  // "0 configured" from "not reported yet".
  const expectedArtifacts = expectedArtifactCount(projectPath);
  if (expectedArtifacts != null) {
    console.error(`[driver] manifest declares ${expectedArtifacts} context artifact(s)`);
  }

  await withClient(async (client) => {
    console.error(`[driver] starting index of ${projectPath} (returns immediately; work runs in-server)`);
    // The server does NOT throw when it can't start: infra failure and "Docker
    // not available" come back as ordinary strings. Ignoring the response meant
    // polling a status that would never move until INDEX_TIMEOUT_MS.
    //
    // Three outcomes, not two: "already in progress" is the concurrency guard,
    // meaning the work we want is underway (started by the watcher, or by a
    // concurrent run). That is a reason to poll, not to abort — the loop below
    // already knows how to wait for someone else's run.
    const startResponse = await client.callTool('codebase_index', { projectPath });
    // Set when the guard fired for an INCREMENTAL update: that run won't produce
    // the full-index completion we gate on, so the real index is issued below,
    // once the incremental clears.
    let awaitingIncremental = false;
    if (indexAlreadyRunning(startResponse)) {
      if (runningOperationIsFullIndex(startResponse)) {
        console.error('[driver] a full index is already in progress for this project — waiting on it rather than starting a second.');
      } else {
        awaitingIncremental = true;
        console.error('[driver] an incremental update is in progress — will start the full index once it clears.');
      }
    } else if (!indexStarted(startResponse)) {
      die(`codebase_index did not start indexing. The server replied:\n${startResponse}`);
    }

    const started = Date.now();
    let contextKicked = false;
    let contextKickFails = 0;
    const MAX_CONTEXT_KICKS = 3;
    // The persisted-incomplete state shows transiently while a resume spins up:
    // index-tools clears its infra progress just before indexProject() acquires
    // the project lock and sets its own, and in that gap a previous run's
    // "in-progress" metadata renders with nothing apparently running. Require
    // the state to persist across this many consecutive polls before believing it.
    const CONFIRM_POLLS = 3;
    let incompletePolls = 0;
    let announcedOtherProcess = false;

    for (;;) {
      if (Date.now() - started > INDEX_TIMEOUT_MS) {
        die(`index did not complete within ${Math.round(INDEX_TIMEOUT_MS / 60000)} min`);
      }
      await sleep(POLL_INTERVAL_MS);

      const status = await client.callTool('codebase_status', { projectPath });

      // ── fail fast on states that would otherwise burn the full timeout ─────
      if (lastOperationFailed(status)) {
        die(`indexing FAILED — ${parseLastOpError(status) || 'run codebase_status for details'}`);
      }

      const inProgress = indexingInProgress(status);

      // We were waiting out someone else's incremental update, not our index.
      // Now that it has cleared, ask for the run we actually came for. Skip the
      // rest of this poll — nothing of ours has started yet.
      if (awaitingIncremental && !inProgress) {
        const retry = await client.callTool('codebase_index', { projectPath });
        if (indexStarted(retry)) {
          awaitingIncremental = false;
          console.error('[driver] incremental finished; full index started.');
        } else if (!indexAlreadyRunning(retry)) {
          die(`codebase_index did not start indexing. The server replied:\n${retry}`);
        }
        continue;
      }

      // Another process holds the index lock. Ours won't advance, but the index
      // it produces is the one we want — report once and keep waiting.
      const otherPid = anotherProcessIndexing(status);
      if (otherPid && !announcedOtherProcess) {
        announcedOtherProcess = true;
        console.error(`[driver] NOTE: PID ${otherPid} is already indexing this project; waiting for that run to finish.`);
      }

      // Persisted-incomplete with nothing running: our codebase_index call did
      // not take, so polling would never converge.
      if (indexIncomplete(status) && !inProgress && !otherPid) {
        if (++incompletePolls >= CONFIRM_POLLS) {
          die(
            'index is persisted-incomplete and no run is active — a previous run was interrupted and codebase_index did not resume it.\n' +
            '  Re-run this command, or codebase_stop first if a stale lock is held.'
          );
        }
      } else {
        incompletePolls = 0;
      }

      // ── the three completion signals ──────────────────────────────────────
      const settled = indexSettled(status);
      const pct = parseEmbedPercent(status);   // display only — see parser note
      const art = parseArtifacts(status);

      // Nothing to embed — only meaningful once the run is OVER. A progress line
      // of "0/0 files" does NOT mean "no work": the server reports exactly that
      // for the whole infrastructure phase of a first index, while it pulls the
      // Qdrant and Ollama images (gotcha D). Reading it as terminal aborts a
      // healthy cold-host run within a poll or two, so key on the finished
      // state instead.
      if (settled && indexedZeroChunks(status)) {
        die('index completed with 0 chunks — nothing was embedded (empty repo, or everything is excluded by .socraticodeignore / .gitignore).');
      }

      // graph_status is the ONLY source of the READY token — codebase_status
      // renders the graph as "Code graph: N files, M edges". Matching against
      // the status text as a fallback could never succeed, but could falsely
      // succeed: status opens with "Project: <path>", so any path containing
      // "ready" or "already" would satisfy it.
      //
      // Hence no tolerance for a server without this tool: with the fallback
      // gone, gReady could never be satisfied and the run would burn the full
      // timeout. Fail with the reason instead of pretending to degrade.
      let graph;
      try {
        graph = await client.callTool('codebase_graph_status', { projectPath });
      } catch (e) {
        die(`codebase_graph_status is unavailable (${e.message}). This driver requires it — it is the only source of the graph READY signal.`);
      }
      const gReady = graphReady(graph);

      // Expected count: manifest is authoritative; otherwise trust the status line.
      const wantArtifacts = expectedArtifacts != null ? expectedArtifacts : art.total;

      console.error(
        `[driver] embeddings=${pct != null ? pct + '%' : settled ? 'done' : 'working'} ` +
        `graph=${gReady ? 'READY' : 'building'} ` +
        `artifacts=${art.done}/${wantArtifacts}`
      );

      // Once the index run is over, nudge context indexing if artifacts lag
      // (gotcha C). Keyed on `settled`, NOT on a parsed 100% — that percentage
      // is gone by the time the run completes, which is why artifacts never
      // started for the #85 reporter. Retry on transient failure (leave
      // contextKicked false) rather than spinning to the timeout; give up
      // loudly after MAX_CONTEXT_KICKS.
      if (settled && !contextKicked && wantArtifacts > 0 && art.done < wantArtifacts) {
        try {
          const kickResponse = await client.callTool('codebase_context_index', { projectPath });
          // Positive confirmation only. Failures come back as ordinary strings
          // ("No artifacts defined in …"), so latching on "it didn't throw"
          // disables the retry below and blocks to the timeout.
          if (!contextIndexComplete(kickResponse)) {
            throw new Error(kickResponse.split('\n')[0] || 'unrecognized response');
          }
          contextKicked = true;
          console.error('[driver] kicked codebase_context_index');
        } catch (e) {
          if (++contextKickFails >= MAX_CONTEXT_KICKS) {
            die(`codebase_context_index failed ${contextKickFails}× — context indexing did not start (${e.message})`);
          }
          console.error(`[driver] codebase_context_index attempt ${contextKickFails} failed; retrying next poll`);
        }
      }

      const artifactsDone = wantArtifacts === 0 || art.done >= wantArtifacts;
      if (settled && gReady && artifactsDone) {
        console.error('[driver] DONE — index run completed, graph READY, artifacts complete.');
        return;
      }
    }
  }, { project: projectPath });
}

// Yield gate + infra triage, for Phase 6 and for the once-per-day SessionStart
// hook (scripts/socraticode-health.sh). Machine-readable verdict on stdout,
// prose on stderr — the AGENTS.md script convention — so a shell hook can act
// on it without parsing English.
//
// Exit 0 when there is no DEFECT to report, 1 when there is (#220 — see the
// SEVERITY block above; a note is reported and costs nothing). NOT 1 for a
// low-yield graph alone... it is: a low-yield graph IS the finding, and the
// hook's whole job is to surface it. What a `low` verdict must never do is fail
// the *install* (Phase 6 keeps going and switches the policy to variant B),
// which is why this is a separate command from `verify`.
async function cmdHealthCheck(projectPath, probePath) {
  const findings = [];
  // Every push names its severity at the call site, so the decision is made
  // where the evidence is rather than by a rule applied afterwards.
  const defect = (message) => findings.push({ severity: SEVERITY.defect, message });
  const note = (message) => findings.push({ severity: SEVERITY.note, message });
  // `server: null` up front, not only on the measured path: the store guard
  // below can skip every server call, and a key that is sometimes absent and
  // sometimes null gives two spellings of 'not measured' in one contract —
  // `report.server === null` and `'server' in report` would disagree (#297).
  // `pinDrift` for the same reason, and it has THREE ways of not being
  // measured: no pin, a pin against a plugin that names an exact version, and
  // a launch the store guard stopped. Null says all three the same way, and
  // `launch.pinned` is what tells them apart (#295). `sessionServer` likewise:
  // null when no server was launched, an object with a null `version` and a
  // `basis` saying why when one was and the session's could not be read (#305).
  const report = {
    projectPath, healthy: true, server: null, sessionServer: null, pinDrift: null, findings: [],
  };

  // ── the store a launch would address (#287) ──────────────────────────────
  // Before the server, not after it: the launch is the write. With a defect
  // here the server checks are skipped, and a note says so — a report with no
  // infrastructure findings otherwise reads as clean infrastructure.
  const store = storeConfig(projectPath);
  report.store = {
    store: store.store,
    declared: store.declared,
    projectId: store.projectId,
    pathHash: store.pathHash,
  };
  findings.push(...store.findings);
  const launchBlocked = store.findings.some(blocks);
  if (launchBlocked) {
    report.serverChecks = 'skipped';
    note(
      'the server checks did not run — a server launched here would address the wrong store or collections, '
      + 'so nothing past the configuration was measured'
    );
  }

  if (!launchBlocked) await withClient(async (client) => {
    const call = async (tool, args) => {
      try {
        return { text: await client.callTool(tool, args), error: null };
      } catch (e) {
        return { text: '', error: e.message };
      }
    };

    // Recorded on every run, defect or not (#297). The graph's `Built by:` line
    // is only half of "is this artifact older than what is answering queries
    // about it"; this is the other half, and a JSON report that carries one
    // without the other cannot be re-read later to settle the question — which
    // is exactly what nobody could do in the case the issue records.
    if (client.serverInfo) {
      report.server = { name: client.serverInfo.name ?? null, version: client.serverVersion };
    }
    // Which launch answered, recorded on every run for the same reason the
    // version is: with a pin in play these are two different questions (#295).
    report.launch = {
      source: client.launch.source,
      pinned: client.launch.pinned === true,
      pinVersion: client.launch.pinVersion ?? null,
    };
    // `server` above is the server THIS CHECK launched. The graph is rebuilt by
    // the one answering the session's queries, which under Claude Code is the
    // plugin's, and the two need not agree (#305). Recorded beside it, with how
    // its version was known or why it was not, so the JSON says which server
    // the builder was judged against.
    const session = sessionServer({
      launch: client.launch, plugin: launchFromPluginConfig({ project: projectPath }), checkVersion: client.serverVersion,
    });
    report.sessionServer = session;

    const health = await call('codebase_health', {});
    if (health.error) {
      defect(`codebase_health failed: ${health.error}`);
    } else {
      const problems = healthProblems(health.text);
      report.health = { problems };
      for (const p of problems) defect(`infrastructure: ${p}`);
    }

    const status = await call('codebase_status', { projectPath });
    if (status.error) {
      defect(`codebase_status failed: ${status.error}`);
    } else {
      // The signal #107 found reported nowhere: an "Incremental update — FAILED
      // (fetch failed)" recorded ~21h earlier, while every green light was lit.
      // cmdIndex already dies on this during its own run; nothing surfaced a
      // failure that had already happened.
      const failed = lastOperationFailed(status.text);
      report.lastOperation = {
        failed,
        error: failed ? parseLastOpError(status.text) : null,
      };
      if (failed) {
        defect(`last operation FAILED: ${report.lastOperation.error || 'see codebase_status'}`);
      }
      if (indexIncomplete(status.text)) defect('index is marked INCOMPLETE — a previous run was interrupted');
    }

    // ── declared ≠ indexed (#214) ────────────────────────────────────────────
    // The last silent-degradation path we know of, and #107's shape one level
    // up. A COMPLETED operation can still leave an artifact unindexed: the
    // field case (CannObserv/power-map#454) settled at "Context artifacts: 2/3
    // indexed" with the operation completed, the index not INCOMPLETE and every
    // container green, and stayed there — a 2.5M docs tree unreachable via
    // codebase_context_search with nothing reporting it. Every check above this
    // one reads that install as healthy.
    //
    // The manifest is the denominator, never the status line: parseArtifacts
    // reports 0/0 both for "N configured, not yet indexed" and for a status
    // that omits the line entirely, so the server's own count cannot tell
    // "nothing declared" from "nothing indexed yet".
    const manifest = validateManifest(projectPath);
    if (manifest.present && manifest.errors.length) {
      // NOT expectedArtifactCount(), which die()s — and die() is process.exit(),
      // which this command must not call: its contract is JSON on stdout, and
      // node's stdout is async on a pipe (see the exitCode note below). An
      // invalid manifest is also exactly the #85 silent-green case — the server
      // rejects it, codebase_status then omits the artifact line, and every
      // reading reports a contented 0/0 — so it is a finding in its own right.
      report.manifest = { path: manifest.path, errors: manifest.errors };
      defect(
        `${MANIFEST_NAME} is invalid, so the server ignores it and context search is absent entirely: ${manifest.errors[0]}`
      );
    } else if (manifest.present && manifest.count > 0) {
      const declared = manifest.count;
      // UNCONDITIONAL, and it did not used to be. #214 short-circuited this
      // call whenever the status line's numerator already matched the declared
      // count: only a shortfall needs a NAME, so a matching count meant there
      // was nothing left to ask. Sound for a presence check — and presence was
      // never the whole question. `14/14 indexed` says nothing about whether
      // any of the fourteen still matches its source, and the per-artifact
      // `lastIndexed` that answers that exists ONLY in this reply. Three of
      // observo's fourteen were stale at the moment the check reported 14/14.
      //
      // The cost is what the short-circuit was saving: one MCP round-trip, per
      // repo, per day. That is the whole price of the difference between "the
      // docs are indexed" and "the docs are current".
      //
      // NOT an early `return`: this block runs inside the withClient callback,
      // so returning here would skip every graph check below it.
      const ctx = await call('codebase_context', { projectPath });
      if (ctx.error) {
        // Degrade, do not disable: the count alone beats silence. Record the
        // failure either way — a codebase_context that keeps failing is a
        // leading indicator of the very gap this check exists to catch, and
        // leaving no trace of it in the JSON would be this change's own
        // silent degradation.
        //
        // The status line's TOTAL cannot be believed (0/0 means both "none
        // declared" and "none indexed yet"), but its numerator can, and this
        // is the one place that matters. Verified rather than assumed: on
        // cannabis_observer/code/cli, sitting at 12 of 13 with `Status:
        // green`, codebase_status reported `Context artifacts: 12/13 indexed`
        // — the count is honest, it just cannot say which one, and with
        // codebase_context down there is nothing that can.
        //
        // Freshness is simply unavailable here. No reply, no per-artifact
        // index times, and no claim in either direction (#225).
        const done = status.error ? null : parseArtifacts(status.text).done;
        report.artifacts = {
          declared,
          indexed: done,
          unindexed: null,
          error: ctx.error,
        };
        if (done != null && done < declared) {
          defect(
            `context artifacts ${done}/${declared} indexed — codebase_context failed (${ctx.error}), so the missing artifact cannot be named`
          );
        }
      } else {
        const listed = parseContextArtifacts(ctx.text);
        const unindexed = listed.filter((a) => !a.indexed);
        const indexed = listed.length - unindexed.length;

        // ── indexed ≠ fresh (#225) ────────────────────────────────────────
        // Only the artifacts that ARE indexed: an unindexed one has no index
        // time to compare against, and the parity finding below already names
        // it. Double-counting would make the stale count useless as a number.
        const candidates = [];
        const unjudged = [];
        for (const a of listed) {
          if (!a.indexed) continue;
          const indexedAt = a.lastIndexed ? Date.parse(a.lastIndexed) : NaN;
          if (!a.path || Number.isNaN(indexedAt)) { unjudged.push(a.name); continue; }
          const newest = newestMtimeMs(resolvePath(projectPath, a.path));
          if (newest === null) { unjudged.push(a.name); continue; }
          if (newest > indexedAt) {
            candidates.push({
              name: a.name,
              path: a.path,
              sourceMtime: new Date(newest).toISOString(),
              lastIndexed: a.lastIndexed,
            });
          }
        }

        // ── newer ≠ changed (#326) ────────────────────────────────────────
        // A newer mtime only nominates. Each candidate is confirmed against
        // the contentHash the server stored for it — the key its own repair
        // uses — so a checkout that rewrote identical bytes is `touched`, not
        // stale, and the finding stays one that codebase_update can clear.
        // The store is read only when something was nominated: on a fresh
        // tree this costs nothing. Its environment is the one the server was
        // launched with, plugin env block included, so both address one store.
        const stale = [];
        const touched = [];
        const unverified = [];
        if (candidates.length) {
          const stored = await indexedArtifactHashes(projectPath, { ...process.env, ...client.launch.env });
          for (const c of candidates) {
            const local = artifactContentHash(resolvePath(projectPath, c.path));
            const indexedHash = stored.hashes?.get(c.name) ?? null;
            if (local.hash && indexedHash) {
              (local.hash === indexedHash ? touched : stale).push({ ...c, contentHash: local.hash, indexedHash });
            } else {
              unverified.push({
                ...c,
                reason: local.hash
                  ? stored.error || 'the index records no content hash for it'
                  : `its content cannot be hashed here: ${local.reason}`,
              });
            }
          }
        }

        report.artifacts = {
          declared,
          indexed,
          unindexed: unindexed.map((a) => ({ name: a.name, status: a.status })),
          stale,
          touched,
          unverified,
          // Named, not swallowed. A server build that stops printing the
          // timestamp would otherwise silently switch freshness off, which is
          // this check's own version of the failure it exists to report.
          unjudged,
        };
        if (indexed < declared) {
          // Naming it is the whole value: 2/3 sends the reader back to
          // codebase_status, whereas the name decides between re-indexing one
          // path and debugging the manifest.
          const named = unindexed.length
            ? unindexed.map((a) => `${a.name}: ${a.status || 'not indexed'}`).join('; ')
            : `codebase_context listed only ${listed.length} of them`;
          defect(`context artifacts ${indexed}/${declared} indexed — ${named}`);
        }
        if (stale.length) {
          // A DEFECT, not a note, and the severity is the interesting call
          // (#220 made it one). An unindexed artifact is ABSENT from search:
          // the caller gets nothing back and knows to look elsewhere.
          //
          // #225 filed the stale case here as worse in kind, on the reading
          // that codebase_context_search answers confidently from superseded
          // chunks. Read against the 1.13.1 and 1.14.0 dists, it does not: the
          // search handler calls ensureArtifactsIndexed before searching
          // (tools/context-tools.js), so the FIRST search re-embeds the
          // artifact inline and then answers from current chunks. Old chunks
          // reach an answer only when that staleness check itself errors.
          //
          // The severity stands on what survives that correction. Nothing
          // SURFACES the gap: codebase_context — what this check and any
          // listing read — does not re-index, so a listing sits at N/N while
          // artifacts are behind. And the repair is billed, unannounced, to
          // whichever search next touches the artifact. It is repaired by one
          // named call, which is the line between the two severities: a note
          // is a measurement no action changes.
          //
          // Its own finding rather than a qualifier on the parity line,
          // because the parity line only exists on a shortfall and staleness
          // has to be reportable at 14/14 — which is the whole case.
          //
          // The named call is codebase_update, NOT codebase_context_index
          // (#317). Both clear the finding; only one of them is affordable.
          // codebase_context_index -> indexAllArtifacts re-embeds every
          // artifact unconditionally — no content-hash skip — and awaits the
          // whole run while emitting no MCP progress notifications, so the
          // only bound on it from a session is Claude Code's 1800s tool idle
          // timeout. Measured on CannObserv/watcher: ~1500 chunks against a
          // shared CPU embedder ran 77 minutes, the session aborted at 30, and
          // the server finished 47 minutes later — a remedy that "failed"
          // while succeeding, for three stale artifacts. codebase_update ends
          // in ensureArtifactsIndexed, which compares each artifact's
          // contentHash and configurationSignature and re-embeds only what
          // moved; on a watcher-following repo that is seconds. Staleness here
          // is edits made while no watcher ran, which is exactly the delta the
          // incremental path exists to carry.
          defect(
            `context artifacts ${indexed}/${declared} indexed, ${stale.length} stale — `
            + `${stale.map((s) => s.name).join(', ')}; run codebase_update `
            + `(incremental; NOT codebase_context_index, which re-embeds every artifact)`
          );
        }
        if (unverified.length) {
          // A NOTE, and the other half of #326. Nominated by mtime, confirmed
          // by nothing: calling it a defect is how a touched file became a
          // daily finding whose remedy re-embeds nothing. But it is not
          // silence either — the edit may be real, and the call that settles
          // it is cheap and a no-op when it is not.
          note(
            `context artifacts with source newer than the index, content unverified — `
            + `${unverified.map((u) => `${u.name} (${u.reason})`).join('; ')}; `
            + 'codebase_update re-embeds any whose content moved and changes nothing for the rest'
          );
        }
      }
    }

    const graph = await call('codebase_graph_status', { projectPath });
    if (graph.error) {
      defect(`codebase_graph_status failed: ${graph.error}`);
    } else {
      // The running server's version, not a cached path's: this host resolves
      // the plugin's mcp.json to `npx socraticode@latest`, so the version on
      // disk under plugins/cache and the version that actually answered can
      // differ by a release (#297).
      const v = graphVerdict(graph.text, client.serverVersion);
      const y = v.local;
      report.graph = {
        ready: graphReady(graph.text),
        ...y,
        // The composed gate's answer, kept beside the local arithmetic rather
        // than replacing it: a caller reading this JSON has to be able to see
        // WHICH measure ruled, and what the other one said (#207).
        verdict: v.verdict,
        source: v.source,
        reason: v.reason,
        // Both halves of the local reading, not just its verdict: when the
        // server ruled, `reason` above is the server's, and without this the
        // JSON no longer records what our own arithmetic actually measured
        // (`disagreement` carries it only in the `low` case) (#207).
        localVerdict: y.verdict,
        localReason: y.reason,
        builder: v.builder,
        importResolution: v.advisory,
      };
      if (!report.graph.ready) defect('graph is not READY');
      // Which versions the builder was compared against, named rather than
      // implied: `builder.serverVersion` is this check's own server, and
      // `ruledBy` says which of the two decided (#305). The session's rules
      // wherever both it and the stamp are readable — the same condition
      // graphBuilderFinding branches on.
      const stamped = graphBuilderFinding(v.builder, session);
      report.graph.builderCheck = {
        builtBy: v.builder.builtBy,
        checkServer: v.builder.serverVersion,
        sessionServer: session.version,
        ruledBy: compareVersions(v.builder.builtBy, session.version) === null
          ? 'checkServer' : 'sessionServer',
      };
      // Pushed with the severity the function decided, like pinDriftFinding
      // below: which severity a builder gap earns IS the #305 decision, so it
      // lives where the fixtures reach it.
      if (stamped) findings.push({ severity: stamped.severity, message: stamped.message });
      if (v.disagreement) note(v.disagreement);
      if (v.verdict === 'low') {
        defect(`graph yield LOW — ${v.reason}; install the degraded Code Exploration Policy (variant B)`);
        // Confirmatory probe, as #107 asks: one graph query against a file the
        // caller knows has first-party imports. Its value is the *shape* of the
        // failure — an ordinary sentence, no error — which is what makes the
        // defect invisible to a caller that only catches exceptions.
        if (probePath) {
          const probe = await call('codebase_graph_query', { projectPath, filePath: probePath });
          report.probe = {
            filePath: probePath,
            empty: probe.error ? null : graphQueryEmpty(probe.text),
            error: probe.error,
            reply: probe.error ? null : probe.text.slice(0, 400),
          };
          if (report.probe.empty) {
            defect(`probe confirms: codebase_graph_query on ${probePath} returned "No dependency information found" — empty, not an error`);
          }
        }
      } else if (v.verdict === 'unknown') {
        defect(`graph yield UNKNOWN — ${v.reason}`);
      }
      // Worded from the COMPOSED verdict, not the local one: the gloss turns on
      // whether a yield finding is on the list for this to sit beside, and
      // since #207 that is what `graphVerdict` decides. Reading `y.verdict`
      // here would word the figure for a failing graph on exactly the repo the
      // server just certified — the accusation #216 removed.
      if (y.unresolvedPct != null && y.unresolvedPct > GRAPH_UNRESOLVED_WARN_PCT) {
        note(unresolvedFinding(y.unresolvedPct, v.verdict));
      }
    }
  }, { readOnly: true, project: projectPath });

  // ── pinned driver vs floating session (#295) ─────────────────────────────
  // Both halves must hold: this run launched from the pin, AND the plugin's
  // recorded command still resolves at launch time. Pinning the driver does not
  // pin the session — that takes SOCRATICODE_SPEC, on a plugin build that reads
  // it (#327) — so a driver pinned alone buys no install at launch and a
  // deterministic driver at the price of a divergence that did not exist while
  // both floated and agreed by coincidence of timing. Leaving that unmeasured
  // would trade a measured memory spike for an unmeasured correctness risk, so
  // it is measured here. With the variable set to the pin's version the
  // plugin's spec is fixed, and there is nothing left to measure.
  //
  // After the server checks, like the linked-project block below, so the
  // infrastructure findings lead the list. No server call: the pin's version is
  // the filesystem's and the floating one is the registry's.
  const plugin = report.launch?.pinned ? launchFromPluginConfig({ project: projectPath }) : null;
  const floatingSpec = plugin ? pluginSpecFloats(plugin) : null;
  if (floatingSpec) {
    const running = report.server?.version || report.launch.pinVersion;
    const resolves = registryLatest();
    report.pinDrift = { pinned: running ?? null, floatingSpec, resolves };
    // The one push here that does not name its severity at the call site, and
    // the exception is the point: which severity this earns IS the decision,
    // so it lives in a pure function the selftest can pin to fixtures without
    // a server, a network or a clock. Naming it here would put the rule in the
    // one place no fixture can reach.
    findings.push(pinDriftFinding({
      running, floatingSpec, resolves, pinPath: pinDir(), specVariable: plugin.specVariable,
    }));
  }

  // ── configured ≠ resolved (#281) ──────────────────────────────────────────
  // No server call: the resolution is the filesystem's, and is read the way
  // the server reads it. After the server checks rather than before, so the
  // infrastructure findings lead the list — and a defect, not a note, because
  // a named action repairs it: check the checkout out, or drop the entry.
  const linked = linkedProjects(projectPath);
  report.linkedProjects = linked;
  const linkedFinding = linkedProjectsFinding(linked);
  if (linkedFinding) defect(linkedFinding);

  // One array, both severities, in encounter order — the shape the JSON has
  // always had. `renderFinding` is what makes the severity legible: a note
  // carries its marker into the string, so nothing has to be cross-referenced
  // against a second array or a parallel key (#220).
  const defects = findings.filter((f) => f.severity === SEVERITY.defect);
  const notes = findings.filter((f) => f.severity === SEVERITY.note);
  report.findings = findings.map(renderFinding);
  report.healthy = defects.length === 0;
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');

  if (defects.length) {
    console.error('[driver] SocratiCode health findings:');
    for (const f of defects) console.error(`  - ${f.message}`);
  } else {
    console.error('[driver] SocratiCode health: nothing to report');
  }
  // Notes print on both paths, and always with their marker. socraticode-
  // health.sh greps stderr for `  - ` lines and injects them into the session
  // under a heading that says "findings", so an unmarked statistic there is
  // #220 rebuilt one layer down. When notes are all there is, the exit code is
  // 0, the hook prints nothing at all, and the figure survives only in the log
  // and in the JSON — which is where an operator who wants it can find it.
  if (notes.length) {
    console.error('[driver] notes — reported, not defects; these do not set the exit code:');
    for (const f of notes) console.error(`  - ${renderFinding(f)}`);
  }
  if (defects.length) {
    // exitCode, not exit(): node's stdout is ASYNC on a pipe, and process.exit()
    // abandons whatever has not drained — measured at 64 KiB through a pipe
    // against 200 KiB written. The hook redirects to a file (synchronous, so it
    // was safe there), but this command's contract is JSON on stdout, which
    // means someone will pipe it to jq, and the truncation would only ever bite
    // in the findings case — the one that matters. Setting the code lets the
    // process leave normally once the write has flushed.
    process.exitCode = 1;
  }
}

async function cmdVerify(projectPath) {
  const { store } = guardStore(projectPath);
  await withClient(async (client) => {
    // An external store is confirmed from the server's side (#287 round 2,
    // CR 38): Phase 6 accepts "native tools, or verify" for a check that
    // `codebase_health` reports `Qdrant mode: external`, and verify never made
    // it. The store guard confirmed this process carries the block; this
    // confirms the server read it as one.
    let qdrantMode = null;
    let healthError = null;
    if (store === 'external') {
      try {
        const health = await client.callTool('codebase_health', {});
        qdrantMode = (health.match(/^[ \t]*Qdrant mode\s*:\s*(\S+)/im) || [])[1] ?? null;
      } catch (e) {
        healthError = e.message;
      }
    }
    const list = await client.callTool('codebase_list_projects', {});
    // Keep the error rather than flattening it to '': "not-ready" would
    // misreport a failed call as a still-building graph.
    let graph = '';
    let graphError = null;
    try {
      graph = await client.callTool('codebase_graph_status', { projectPath });
    } catch (e) {
      graphError = e.message;
    }
    // minScore 0: this asserts that the index ANSWERS — retrieval, not
    // relevance. At the server's 0.10 default a small or unusual repo can
    // legitimately score nothing for a fixed sample query, which would fail
    // verification on a perfectly healthy index.
    const search = await client.callTool('codebase_search', {
      projectPath, query: 'configuration and settings', minScore: 0,
    });
    // A green index whose LAST recorded operation failed is not a verified
    // index — the delta that failed is missing from it. #107 found exactly this
    // going unreported for 21 hours behind three green lights, so verification
    // reads status too, and fails on it rather than mentioning it in passing.
    let statusText = '';
    let statusError = null;
    try {
      statusText = await client.callTool('codebase_status', { projectPath });
    } catch (e) {
      statusError = e.message;
    }
    const lastOpFailed = !statusError && lastOperationFailed(statusText);

    const okGraph = graphReady(graph);
    // "Returns hits" has to mean hits. The server answers an empty search with
    // an ordinary sentence ("No results found for …"), so a non-empty-string
    // test passes in exactly the states verification exists to catch — a
    // rejected manifest (gotcha K) or a post-reboot dead Qdrant (gotcha L).
    const okSearch = searchHasHits(search);
    const okList = listHasProjects(list);
    console.error(`[driver] list_projects: ${okList ? 'ok' : 'empty'}`);
    console.error(`[driver] graph_status: ${okGraph ? 'READY' : graphError ? `ERROR — ${graphError}` : 'not-ready'}`);
    console.error(`[driver] sample search hits: ${okSearch ? 'yes' : 'none'}`);
    if (statusError) {
      console.error(`[driver] last operation: UNREADABLE — ${statusError}`);
    } else {
      console.error(`[driver] last operation: ${lastOpFailed ? `FAILED — ${parseLastOpError(statusText) || 'see codebase_status'}` : 'no failure recorded'}`);
    }
    // Yield is reported here but deliberately does NOT gate. A low-yield graph
    // is an upstream resolver defect this skill cannot repair; failing the
    // install would leave the repo with no policy at all, when the right answer
    // is a policy that routes around the broken tool. Phase 6 reads this line
    // and writes variant B (#107).
    if (okGraph) {
      const v = graphVerdict(graph, client.serverVersion);
      console.error(`[driver] graph yield: ${v.verdict.toUpperCase()} (per ${v.source}) — ${v.reason}`);
      // Judged against the session's server where it is known, exactly as
      // health-check judges it (#305) — a fresh install told to rebuild by a
      // remedy that re-stamps the same version would conclude the tool is
      // broken, which is the reading #305 records.
      const stamped = graphBuilderFinding(v.builder, sessionServer({
        launch: client.launch, plugin: launchFromPluginConfig({ project: projectPath }), checkVersion: client.serverVersion,
      }));
      // Printed here too, and before the policy line: a fresh install reading
      // STALE knows to rebuild rather than to accept variant B for a graph that
      // only needs recutting (#207).
      if (stamped) console.error(`[driver] graph builder: ${renderFinding(stamped)}`);
      if (v.disagreement) console.error(`[driver] note: ${v.disagreement}`);
      if (v.verdict === 'low') {
        console.error('[driver] → write the DEGRADED Code Exploration Policy (variant B): route imports/dependents/blast-radius to grep, and warn that empty graph output is tool failure, not absence.');
      }
    }
    if (store === 'external') {
      console.error(`[driver] qdrant mode: ${qdrantMode === 'external' ? 'external'
        : healthError ? `UNREADABLE — ${healthError}` : `${qdrantMode ?? 'not reported'}, not external`}`);
      if (qdrantMode !== 'external') {
        die('verification failed — the server does not report Qdrant mode: external, so it is not reaching the store');
      }
    }
    if (!(okGraph && okSearch && okList)) die('verification failed — see lines above');
    if (lastOpFailed) die('verification failed — the last recorded operation FAILED; re-index before declaring this green');
    console.error('[driver] verify OK');
  }, { readOnly: true, project: projectPath });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ── entry ────────────────────────────────────────────────────────────────────
const USAGE = `mcp-driver.mjs — fenced fallback that drives the SocratiCode stdio MCP server directly.

Usage: node mcp-driver.mjs <command> [projectPath]

Commands:
  index    run a full fresh index; block until the run reports complete, the
           graph is READY, and context artifacts are all indexed
  status   print codebase_status once and exit
  verify   sample codebase_search + graph_status + list_projects + a check that
           the last recorded operation did not FAIL, and on an external store
           that codebase_health reports Qdrant mode: external; exit 0/1.
           Reports graph yield without gating on it.
  health-check
           infra triage on a cadence: codebase_health + codebase_status +
           codebase_graph_status, with the graph measured by YIELD rather than
           by READY — the server's own import-resolution advisory where it
           states one (1.13.0+), our edges/file floor where it is silent — and
           with the BUILD THAT CUT the graph compared against a server's own
           version, so a stored graph older than the resolvers answering
           queries about it is its own named defect rather than a silent READY
           (#297). The server it is judged against is the one answering the
           session's queries wherever the plugin's definition fixes that
           version, and this check's own launch where the definition floats
           or there is none — the finding then says it could not tell which
           (#305). A graph matching the session's
           server but older than this check's is a note, not a defect: a
           rebuild through the session re-stamps the same version, so the
           remedy is update the plugin, restart Claude Code, then rebuild.
           JSON "server" is this check's own launch, "sessionServer" the
           session's and how it was known, "graph.builderCheck" which ruled.
           JSON verdict on stdout, findings on stderr.
           Also reports linked projects that are configured and do not
           resolve (.socraticode.json's linkedProjects and
           SOCRATICODE_LINKED_PROJECTS), which the server drops silently.
           Each finding carries a SEVERITY: a defect is a state a named action
           repairs and sets exit 1; a note is a measurement no action changes,
           is prefixed "note: " in both the JSON and on stderr, and costs
           nothing. Exit 0 when there is no defect — so a repo whose only
           finding is a note stays silent through socraticode-health.sh.
  resolve  print the resolved server launch command as JSON and exit — does not
           start the server (no Docker, no network); use it to debug resolution.
           Every command launches the plugin definition applying at projectPath
  validate-manifest
           check .socraticodecontextartifacts.json (shape, unique names, every
           path resolves) and exit 0/1; no server, no network. Run before index.
  validate-store
           check the store and projectId a server launched here would use, and
           exit 0/1; no server, no network. JSON verdict on stdout: "valid",
           and "blocking" — the findings that decide it. A blocking defect: an
           external store with no projectId (or with this checkout's own path
           hash as one); a projectId outside [a-zA-Z0-9_-], or one a linked
           project also resolves to; a store variable the project settings
           declare that this environment does not carry, or carries with
           another value (from a worktree, one only the main checkout's
           settings.local.json holds); a project settings file that does not
           parse. index, status and verify refuse to launch a server on any of
           them, and health-check reports them and skips its server checks — a
           launch is itself a write. A linked project's invalid projectId, or
           two linked projects on one id, is reported and blocks nothing.

projectPath defaults to the current working directory.

  A RELATIVE projectPath (including the default) is resolved to the checkout
  SocratiCode indexes — the parent of git's --git-common-dir — so a literal "."
  from a worktree or a subdirectory does not ask about a project that was never
  indexed and get told a healthy index is broken (#180/#226). The substitution
  is printed on stderr whenever it changes the path.

  An ABSOLUTE projectPath is used verbatim. That is the escape hatch: it is the
  only spelling that can name a worktree on purpose, and it is what
  socraticode-health.sh passes after resolving the checkout itself.

Flags:
  --probe <relpath>   health-check only: on a LOW yield verdict, run one
                      codebase_graph_query against this file as a confirmatory
                      probe. Give it a file you know has first-party imports.

Env:
  SOCRATICODE_ENTRY   explicit path to the socraticode server entry (skips resolution)
  SOCRATICODE_PIN_DIR prefix holding a pre-installed, pinned server, preferred over
                      the plugin's floating 'npx ... @latest' command and inert
                      when absent (default ~/.socraticode/pin; populate with
                      'npm install --prefix <dir> socraticode@<version>')
  CLAUDE_CONFIG_DIR   Claude config dir searched for the plugin's mcp.json and
                      installed_plugins.json (default ~/.claude) — both to
                      launch and, in health-check and verify, to read which
                      server version the session runs (#305)
  npm_config_cache    npm cache dir whose _npx/ subtree is searched (default ~/.npm)
  POLL_INTERVAL_MS    status poll cadence (default 15000)
  INDEX_TIMEOUT_MS    overall ceiling (default 7200000 = 2h)
  HEALTH_TIMEOUT_MS   hard ceiling for health-check (default 120000 = 2min).
                      That default is for a DIRECT run — the install-time yield
                      measurement, or hand triage of an install already
                      suspected broken — where the wait can include a cold
                      Docker start and an answer is worth two minutes.
                      socraticode-health.sh exports 60000 instead, because a
                      SessionStart hook must not hang a session on a server
                      that will never answer. So through the hook the effective
                      ceiling is 60000, and this default never applies.

Exit codes:
  0  clean — the command ran and found nothing to report
  1  the command ran and found a defect (health-check, verify,
     validate-store, validate-manifest), or refused to launch a server into
     the wrong store or collections (index, status, verify; see
     validate-store)
  2  usage
  3  the command DID NOT COMPLETE — it threw, or health-check hit its
     timeout. Nothing was measured, so this is not a clean result and it is
     not a finding either (#254). A consumer must not read a non-zero code as
     "defects found": a driver older than this one exits 1 here too, which is
     why socraticode-health.sh branches on whether any finding was printed
     rather than on the code.`;

// Only dispatch when run as a script. Importing the module (to exercise the
// PARSERS against captured status strings) must not spawn a server or exit.
//
// Realpaths on BOTH sides (#177). `path.resolve` does not follow symlinks;
// `import.meta.url` is already the realpath, because Node resolves the ESM main
// through symlinks unless --preserve-symlinks-main is passed. So through a
// symlink the two disagreed, the guard was false, and the process exited 0
// having printed NOTHING. That is the normal invocation path — `skills/<name>`
// IS a symlink into `skills-vendor/` under the managing-skills pattern, so both
// documented routes to this driver named the silent one, and the health hook's
// silent-when-clean contract made a driver that could never speak
// indistinguishable from a healthy install.
//
// Comparing realpaths does not weaken the guard: a module IMPORTED by
// parser-selftest.mjs still has a different realpath from the runner's argv[1],
// so it still does not dispatch.
const _realOrNull = (p) => {
  // A path that does not resolve is not this file. realpathSync throws ENOENT
  // on a missing argv[1] (`node -e` with trailing args), and a throw from the
  // module's top level would replace a silent no-op with a crash — no better.
  try {
    return realpathSync(p);
  } catch {
    return null;
  }
};
const RUN_AS_SCRIPT = (() => {
  if (!process.argv[1]) return false;
  const invoked = _realOrNull(resolvePath(process.argv[1]));
  return invoked !== null && invoked === _realOrNull(fileURLToPath(import.meta.url));
})();

// A run that DID NOT COMPLETE gets its own code (#254). 0 is clean, 1 is
// "defects found" (#220) and 2 is usage, so an error thrown out of the dispatch
// had nowhere to land: node exits 1 for an unhandled rejection too, which makes
// a crashed health-check indistinguishable from one that measured the repo and
// found something. Consumers that key on the exit code — socraticode-health.sh
// is one — cannot rely on this alone, since a vendored driver predating it
// still exits 1; they need their own crash branch. It is here so the state is
// legible to anything reading the code rather than the stderr.
const EXIT_INCOMPLETE = 3;

function _reportIncomplete(err) {
  const msg = (err && err.message) ? err.message : String(err);
  console.error(`[driver] DID NOT COMPLETE: ${msg}`);
  if (err && err.stack) console.error(err.stack);
  console.error(
    '[driver] nothing was measured — this is not a clean result. ' +
    'Re-run by hand to see the failure, or check that the server launches ' +
    '(node mcp-driver.mjs resolve).'
  );
}

// The dispatch lives in a function so the caller below can wrap it in one
// try/catch. As a bare top-level `await` inside `if (RUN_AS_SCRIPT)` it had no
// catch anywhere, and every throw left as an unhandled rejection (#254).
async function runCli() {
  const argv = process.argv.slice(2);
  const probeIdx = argv.indexOf('--probe');
  let probePath = null;
  if (probeIdx !== -1) {
    probePath = argv[probeIdx + 1] || null;
    if (!probePath) die('--probe needs a file path');
    argv.splice(probeIdx, 2);
  }
  const [cmd, projectPathArg] = argv;
  const projectPath = resolveProjectPath(projectPathArg);

  switch (cmd) {
    case 'index': await cmdIndex(projectPath); break;
    case 'status': await cmdStatus(projectPath); break;
    case 'verify': await cmdVerify(projectPath); break;
    case 'health-check': {
      // Hard ceiling: a server that never answers must cost a bounded wait.
      // Implemented here in node rather than with timeout(1), which is not on
      // a stock macOS.
      //
      // 120000 is the DIRECT-invocation budget (#177 made that a documented
      // path: SKILL.md Phase 6 and references/socraticode-doc.md both tell a
      // reader to run this by hand). The SessionStart hook does not use it —
      // socraticode-health.sh exports 60000, because 60s is a hook's budget,
      // not a health check's. The two numbers disagree on purpose; both usage
      // blocks say so, and tests/structural/test_health_timeout_contract.py
      // keeps them saying it.
      const ms = Number(process.env.HEALTH_TIMEOUT_MS || 120000);
      const bomb = setTimeout(() => {
        console.error(`[driver] health-check exceeded ${ms}ms — giving up`);
        // EXIT_INCOMPLETE, not 1: giving up on a server that never answered
        // measured nothing, and 1 would report it as defects found (#254).
        process.exit(EXIT_INCOMPLETE);
      }, ms);
      bomb.unref();
      await cmdHealthCheck(projectPath, probePath);
      clearTimeout(bomb);
      break;
    }
    case 'resolve': cmdResolve(projectPath); break;
    case 'validate-manifest': cmdValidateManifest(projectPath); break;
    case 'validate-store': cmdValidateStore(projectPath); break;
    case '--help': case '-h': console.log(USAGE); break;
    default:
      console.error(USAGE);
      process.exit(2);
  }
}

if (RUN_AS_SCRIPT) {
  // A rejection that never reaches the awaited chain — a stray server-side
  // error, say — otherwise takes node's default path and exits 1, which is the
  // ambiguity EXIT_INCOMPLETE exists to remove, by another route.
  process.on('unhandledRejection', (err) => {
    _reportIncomplete(err);
    // exitCode, not exit(), matching the catch below — console.error is ASYNC
    // on a pipe, and on this path the message IS the whole output, so exiting
    // under it can truncate the one thing that says what failed. Node's own
    // default for an unhandled rejection is a hard exit; the loop here is
    // already unwound, so letting it drain costs nothing and keeps the two
    // crash paths saying the same thing the same way (#254 CR round 1).
    process.exitCode = EXIT_INCOMPLETE;
  });
  try {
    await runCli();
  } catch (err) {
    _reportIncomplete(err);
    // exitCode, not exit(): console.error is ASYNC on a pipe, and the message
    // naming what failed is the entire value of this branch — abandoning it
    // half-written reproduces the silence it replaces.
    process.exitCode = EXIT_INCOMPLETE;
  }
}

export {
  validateManifest, MANIFEST_NAME,
  parseEmbedPercent, parseArtifacts, graphReady,
  // declared ≠ indexed (#214), indexed ≠ fresh (#225)
  parseContextArtifacts, artifactIndexed, parseIndexedAt, newestMtimeMs,
  // newer ≠ changed: the server's content key, recomputed and read back (#326)
  artifactContentHash, indexedArtifactHashes, metadataPointId, qdrantBase,
  // the transcribed half of the artifact-walk parity claim, and the matcher
  // over it — exported so the four pattern forms can be asserted directly
  // rather than only through a tmp_path tree per case (#270)
  SERVER_DEFAULT_IGNORE_PATTERNS, serverIgnoresEntry,
  // graph yield (#107)
  parseGraphCounts, graphYield, graphQueryEmpty, healthProblems,
  unresolvedFinding,
  // the server's advisory, the builder stamp, and the gate that composes them
  // with the local arithmetic (#207)
  parseImportResolution, parseGraphBuilder, graphVerdict, builderFinding,
  // the builder judged against the server answering the session, and how
  // that server's version is known (#305)
  graphBuilderFinding, sessionServer, pluginLaunchVersion,
  // the ordering behind "older than the running server" — exported so the
  // refuse-to-guess cases can be asserted directly, not only through a
  // builder stamp that happens to exercise them (#297)
  compareVersions,
  // finding severity (#220)
  SEVERITY, NOTE_PREFIX, renderFinding,
  // configured ≠ resolved linked projects (#281)
  linkedProjects, linkedProjectsFinding,
  // the store and id a launch would address (#287)
  storeConfig, pathHash,
  GRAPH_YIELD_MIN_EDGES_PER_NODE, GRAPH_YIELD_MIN_NODES,
  GRAPH_UNRESOLVED_WARN_PCT,
  indexingInProgress, lastOperationCompleted, lastOperationFailed,
  parseLastOpError, indexIncomplete, anotherProcessIndexing, indexSettled,
  expectedArtifactCount, resolveServerLaunch,
  // which registry entry the session at a project loads (#305 CR 28)
  launchFromPluginConfig, registryEntryApplies,
  // the pin, and the drift it trades the install spike for (#295) — the
  // resolution half as well as the decision half, so a reordering fails a
  // fixture rather than only a hand-run
  pinVersion, launchFromPin, pluginSpecFloats, versionGap, pinDriftFinding,
  // the session's own pin, and whether the installed plugin reads one (#327)
  specVariableOf,
  // following plugin.json rather than guessing a launcher filename (#309)
  pluginServerFromVersionDir, expandVars,
  // tool-reply predicates (gotcha M)
  indexStarted, indexAlreadyRunning, runningOperationIsFullIndex,
  contextIndexComplete, indexedZeroChunks,
  searchHasHits, listHasProjects,
};
