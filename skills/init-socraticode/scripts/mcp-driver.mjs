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
//   J — completion is NOT keyed on a parsed "100%". The server prints its
//       progress percentage only while indexing is in flight, so the line is
//       gone by the time the run is done and `pct === 100` was only ever
//       observable by winning a race with the poll interval (#85).
//   G — we OWN the child and kill it by child.pid on exit. We never pkill by
//       cmdline, so there is no self-match footgun.
//   H — status strings are parsed loosely (regex, both artifact shapes).
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
// resolveServerLaunch(), which follows the plugin's own launch chain.
//
// Usage:
//   node mcp-driver.mjs index  <projectPath>   # full fresh index, blocks til done
//   node mcp-driver.mjs status <projectPath>   # print status once and exit
//   node mcp-driver.mjs verify <projectPath>   # sample search + list, exit 0/1
//
// Env:
//   SOCRATICODE_ENTRY   explicit path to socraticode dist/index.js (skips resolution)
//   POLL_INTERVAL_MS    status poll cadence (default 15000)
//   INDEX_TIMEOUT_MS    overall ceiling (default 7200000 = 2h; first index is slow)

import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve as resolvePath, join as joinPath } from 'node:path';
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

// Newest-first directory listing — used to prefer the latest plugin version and
// the most recently populated npx cache entry.
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

// The plugin's own mcp.json is authoritative: it records the exact command,
// args, and PATH the session uses to start this server. Reusing it verbatim is
// the only resolution that cannot drift from what the plugin actually runs.
function launchFromPluginConfig() {
  const claudeDir = process.env.CLAUDE_CONFIG_DIR || joinPath(homedir(), '.claude');
  const cacheDir = joinPath(claudeDir, 'plugins', 'cache', 'socraticode', 'socraticode');
  for (const versionDir of subdirsNewestFirst(cacheDir)) {
    const cfgPath = joinPath(versionDir, 'mcp.json');
    if (!existsSync(cfgPath)) continue;
    try {
      const server = JSON.parse(readFileSync(cfgPath, 'utf8'))?.mcpServers?.socraticode;
      if (server?.command && Array.isArray(server.args)) {
        return {
          command: server.command,
          args: server.args,
          env: server.env && typeof server.env === 'object' ? server.env : {},
          source: `plugin mcp.json (${cfgPath})`,
        };
      }
    } catch { /* malformed config — keep looking */ }
  }
  return null;
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

function resolveServerLaunch() {
  if (process.env.SOCRATICODE_ENTRY) {
    const p = resolvePath(process.env.SOCRATICODE_ENTRY);
    if (!existsSync(p)) die(`SOCRATICODE_ENTRY does not exist: ${p}`);
    return nodeLaunch(p, 'SOCRATICODE_ENTRY');
  }

  // 1) The plugin's recorded launch command — the documented install path.
  const fromPlugin = launchFromPluginConfig();
  if (fromPlugin) return fromPlugin;

  // 2) require.resolve from this module's context (works if socraticode is a dep).
  try {
    const req = createRequire(import.meta.url);
    return nodeLaunch(req.resolve('socraticode'), 'require.resolve');
  } catch { /* fall through */ }

  // 3) resolve the package root, then read its package.json "main"/"bin".
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

  // 4) npx cache, populated by any prior plugin run.
  const fromNpx = launchFromNpxCache();
  if (fromNpx) return fromNpx;

  // 5) Last resort: let npx fetch it, exactly as the plugin does. Costs a
  //    network round-trip on a cold cache but never fails to resolve.
  if (spawnSync('npx', ['--version'], { encoding: 'utf8' }).status === 0) {
    return { command: 'npx', args: ['-y', 'socraticode'], env: {}, source: 'npx -y (fallback)' };
  }

  die(
    'Could not resolve the socraticode server.\n' +
    '  Set SOCRATICODE_ENTRY=/abs/path/to/socraticode/dist/index.js, or\n' +
    '  install it first:  claude plugin install socraticode@socraticode\n' +
    '  (locate a plugin-run server with: find ~/.npm/_npx -path "*socraticode/dist/index.js")'
  );
}

// ── minimal JSON-RPC 2.0 stdio client ───────────────────────────────────────
class RpcClient {
  constructor(launch) {
    // We own this child. On our exit we kill it by child.pid — never pkill.
    // launch.env carries the plugin's PATH when we resolved from its mcp.json;
    // merging over process.env keeps that authoritative without dropping ours.
    this.child = spawn(launch.command, launch.args, {
      stdio: ['pipe', 'pipe', 'inherit'],
      env: { ...process.env, ...launch.env },
    });
    this.nextId = 1;
    this.pending = new Map();
    this.buf = '';
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
    await this.request('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'init-socraticode-driver', version: '1.0.0' },
    });
    this.notify('notifications/initialized', {});
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
function lastOperationCompleted(text) {
  return /Last operation:[^\n]*[-—–]\s*completed/i.test(text);
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

function graphReady(text) {
  return /READY/i.test(text);
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

// ── high-level flows ─────────────────────────────────────────────────────────
function die(msg) { console.error(`ERROR: ${msg}`); process.exit(1); }

async function withClient(fn) {
  const launch = resolveServerLaunch();
  console.error(`[driver] server launch (${launch.source}): ${launch.command} ${launch.args.join(' ')}`);
  const client = new RpcClient(launch);
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
function cmdResolve() {
  const launch = resolveServerLaunch();
  process.stdout.write(JSON.stringify({
    source: launch.source,
    command: launch.command,
    args: launch.args,
    env: launch.env,
  }, null, 2) + '\n');
}

// Phase 4 gate: validate the manifest before paying for an index.
function cmdValidateManifest(projectPath) {
  const m = validateManifest(projectPath);
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

async function cmdStatus(projectPath) {
  await withClient(async (client) => {
    const text = await client.callTool('codebase_status', { projectPath });
    process.stdout.write(text + '\n');
  });
}

async function cmdIndex(projectPath) {
  // Authoritative expected artifact count (null when there's no manifest). This
  // is what makes "artifacts N/N" real — the status line alone can't tell
  // "0 configured" from "not reported yet".
  const expectedArtifacts = expectedArtifactCount(projectPath);
  if (expectedArtifacts != null) {
    console.error(`[driver] manifest declares ${expectedArtifacts} context artifact(s)`);
  }

  await withClient(async (client) => {
    console.error(`[driver] starting index of ${projectPath} (returns immediately; work runs in-server)`);
    await client.callTool('codebase_index', { projectPath });

    const started = Date.now();
    let contextKicked = false;
    let contextKickFails = 0;
    const MAX_CONTEXT_KICKS = 3;
    // Some terminal-looking states show transiently while a run spins up (file
    // discovery hasn't counted anything yet; a resume hasn't taken the lock
    // yet). Require them to persist across this many consecutive polls before
    // treating them as real.
    const CONFIRM_POLLS = 3;
    let incompletePolls = 0;
    let zeroWorkPolls = 0;
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

      // Nothing to embed. Transient at startup, so confirm across polls.
      if (/\b0\s*\/\s*0\b[^\n]*(chunks?|files)/i.test(status)) {
        if (++zeroWorkPolls >= CONFIRM_POLLS) {
          die('codebase_status reports 0/0 — nothing to embed (empty repo, or everything is excluded by .socraticodeignore / .gitignore).');
        }
      } else {
        zeroWorkPolls = 0;
      }

      // ── the three completion signals ──────────────────────────────────────
      const settled = indexSettled(status);
      const pct = parseEmbedPercent(status);   // display only — see parser note
      const art = parseArtifacts(status);

      let graph = '';
      try { graph = await client.callTool('codebase_graph_status', { projectPath }); } catch { /* older server */ }
      // codebase_status renders the graph as "Code graph: N files, M edges" and
      // never the literal READY, so graph_status is the only real source here;
      // the status fallback stays as drift insurance, not a working path.
      const gReady = graphReady(graph) || graphReady(status);

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
          await client.callTool('codebase_context_index', { projectPath });
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
  });
}

async function cmdVerify(projectPath) {
  await withClient(async (client) => {
    const list = await client.callTool('codebase_list_projects', {});
    const graph = await client.callTool('codebase_graph_status', { projectPath }).catch(() => '');
    const search = await client.callTool('codebase_search', { projectPath, query: 'configuration and settings' });
    const okGraph = graphReady(graph);
    const okSearch = /\S/.test(search);
    console.error(`[driver] list_projects: ${/\S/.test(list) ? 'ok' : 'empty'}`);
    console.error(`[driver] graph_status: ${okGraph ? 'READY' : 'not-ready'}`);
    console.error(`[driver] sample search hits: ${okSearch ? 'yes' : 'none'}`);
    if (!(okGraph && okSearch)) die('verification failed — see lines above');
    console.error('[driver] verify OK');
  });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ── entry ────────────────────────────────────────────────────────────────────
const USAGE = `mcp-driver.mjs — fenced fallback that drives the SocratiCode stdio MCP server directly.

Usage: node mcp-driver.mjs <command> [projectPath]

Commands:
  index    run a full fresh index; block until embeddings 100%, graph READY,
           and context artifacts complete
  status   print codebase_status once and exit
  verify   sample codebase_search + graph_status + list_projects; exit 0/1
  resolve  print the resolved server launch command as JSON and exit — does not
           start the server (no Docker, no network); use it to debug resolution
  validate-manifest
           check .socraticodecontextartifacts.json (shape, unique names, every
           path resolves) and exit 0/1; no server, no network. Run before index.

projectPath defaults to the current working directory.

Env:
  SOCRATICODE_ENTRY   explicit path to the socraticode server entry (skips resolution)
  POLL_INTERVAL_MS    status poll cadence (default 15000)
  INDEX_TIMEOUT_MS    overall ceiling (default 7200000 = 2h)`;

// Only dispatch when run as a script. Importing the module (to exercise the
// PARSERS against captured status strings) must not spawn a server or exit.
const RUN_AS_SCRIPT = process.argv[1] && resolvePath(process.argv[1]) === fileURLToPath(import.meta.url);

if (RUN_AS_SCRIPT) {
  const [cmd, projectPathArg] = process.argv.slice(2);
  const projectPath = projectPathArg ? resolvePath(projectPathArg) : process.cwd();

  switch (cmd) {
    case 'index': await cmdIndex(projectPath); break;
    case 'status': await cmdStatus(projectPath); break;
    case 'verify': await cmdVerify(projectPath); break;
    case 'resolve': cmdResolve(); break;
    case 'validate-manifest': cmdValidateManifest(projectPath); break;
    case '--help': case '-h': console.log(USAGE); break;
    default:
      console.error(USAGE);
      process.exit(2);
  }
}

export {
  validateManifest, MANIFEST_NAME,
  parseEmbedPercent, parseArtifacts, graphReady,
  indexingInProgress, lastOperationCompleted, lastOperationFailed,
  parseLastOpError, indexIncomplete, anotherProcessIndexing, indexSettled,
  expectedArtifactCount, resolveServerLaunch,
};
