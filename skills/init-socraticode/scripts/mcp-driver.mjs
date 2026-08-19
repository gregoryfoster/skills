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
// resolveServerLaunch(), which follows the plugin's own launch chain.
//
// Commands and environment variables are documented in one place — the USAGE
// constant at the bottom of this file. Run `node mcp-driver.mjs --help`.
// (This header used to carry a second copy; it had already drifted a commit
// after the interface changed.)

import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
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

// The plugin's own mcp.json is authoritative: it records the exact command,
// args, and PATH the session uses to start this server. Reusing it verbatim is
// the only resolution that cannot drift from what the plugin actually runs.
function launchFromPluginConfig() {
  const claudeDir = process.env.CLAUDE_CONFIG_DIR || joinPath(homedir(), '.claude');

  // installed_plugins.json records the install path of the version actually
  // enabled. Prefer it over scanning the cache: with two versions cached, an
  // mtime scan can pick the one the session ISN'T running, which is precisely
  // the drift reading the plugin's own config exists to avoid.
  const installed = [];
  try {
    const registry = JSON.parse(readFileSync(joinPath(claudeDir, 'plugins', 'installed_plugins.json'), 'utf8'));
    for (const entry of registry?.plugins?.['socraticode@socraticode'] ?? []) {
      if (entry?.installPath) installed.push(entry.installPath);
    }
  } catch { /* no registry, or unreadable — fall back to the cache scan */ }

  const cacheDir = joinPath(claudeDir, 'plugins', 'cache', 'socraticode', 'socraticode');
  for (const versionDir of [...installed, ...subdirsNewestFirst(cacheDir)]) {
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

function graphReady(text) {
  return /READY/i.test(text);
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
// `Unresolved %`, which is a call-graph statistic and is legitimately high in
// dynamic code; it is reported as corroboration, never as the verdict.
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
  });
}

// Yield gate + infra triage, for Phase 6 and for the once-per-day SessionStart
// hook (scripts/socraticode-health.sh). Machine-readable verdict on stdout,
// prose on stderr — the AGENTS.md script convention — so a shell hook can act
// on it without parsing English.
//
// Exit 0 when there is nothing to report, 1 when there is. NOT 1 for a low-yield
// graph alone... it is: a low-yield graph IS the finding, and the hook's whole
// job is to surface it. What a `low` verdict must never do is fail the *install*
// (Phase 6 keeps going and switches the policy to variant B), which is why this
// is a separate command from `verify`.
async function cmdHealthCheck(projectPath, probePath) {
  const findings = [];
  const report = { projectPath, healthy: true, findings: [] };

  await withClient(async (client) => {
    const call = async (tool, args) => {
      try {
        return { text: await client.callTool(tool, args), error: null };
      } catch (e) {
        return { text: '', error: e.message };
      }
    };

    const health = await call('codebase_health', {});
    if (health.error) {
      findings.push(`codebase_health failed: ${health.error}`);
    } else {
      const problems = healthProblems(health.text);
      report.health = { problems };
      for (const p of problems) findings.push(`infrastructure: ${p}`);
    }

    const status = await call('codebase_status', { projectPath });
    if (status.error) {
      findings.push(`codebase_status failed: ${status.error}`);
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
        findings.push(`last operation FAILED: ${report.lastOperation.error || 'see codebase_status'}`);
      }
      if (indexIncomplete(status.text)) findings.push('index is marked INCOMPLETE — a previous run was interrupted');
    }

    const graph = await call('codebase_graph_status', { projectPath });
    if (graph.error) {
      findings.push(`codebase_graph_status failed: ${graph.error}`);
    } else {
      const y = graphYield(graph.text);
      report.graph = { ready: graphReady(graph.text), ...y };
      if (!report.graph.ready) findings.push('graph is not READY');
      if (y.verdict === 'low') {
        findings.push(`graph yield LOW — ${y.reason}; install the degraded Code Exploration Policy (variant B)`);
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
            findings.push(`probe confirms: codebase_graph_query on ${probePath} returned "No dependency information found" — empty, not an error`);
          }
        }
      } else if (y.verdict === 'unknown') {
        findings.push(`graph yield UNKNOWN — ${y.reason}`);
      }
      if (y.unresolvedPct != null && y.unresolvedPct > GRAPH_UNRESOLVED_WARN_PCT) {
        findings.push(`graph unresolved ${y.unresolvedPct}% (> ${GRAPH_UNRESOLVED_WARN_PCT}%) — corroborates a resolver problem`);
      }
    }
  });

  report.findings = findings;
  report.healthy = findings.length === 0;
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  if (findings.length) {
    console.error('[driver] SocratiCode health findings:');
    for (const f of findings) console.error(`  - ${f}`);
    // exitCode, not exit(): node's stdout is ASYNC on a pipe, and process.exit()
    // abandons whatever has not drained — measured at 64 KiB through a pipe
    // against 200 KiB written. The hook redirects to a file (synchronous, so it
    // was safe there), but this command's contract is JSON on stdout, which
    // means someone will pipe it to jq, and the truncation would only ever bite
    // in the findings case — the one that matters. Setting the code lets the
    // process leave normally once the write has flushed.
    process.exitCode = 1;
    return;
  }
  console.error('[driver] SocratiCode health: nothing to report');
}

async function cmdVerify(projectPath) {
  await withClient(async (client) => {
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
      const y = graphYield(graph);
      console.error(`[driver] graph yield: ${y.verdict.toUpperCase()} — ${y.reason}`);
      if (y.verdict === 'low') {
        console.error('[driver] → write the DEGRADED Code Exploration Policy (variant B): route imports/dependents/blast-radius to grep, and warn that empty graph output is tool failure, not absence.');
      }
    }
    if (!(okGraph && okSearch && okList)) die('verification failed — see lines above');
    if (lastOpFailed) die('verification failed — the last recorded operation FAILED; re-index before declaring this green');
    console.error('[driver] verify OK');
  });
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
           the last recorded operation did not FAIL; exit 0/1. Reports graph
           yield without gating on it.
  health-check
           infra triage on a cadence: codebase_health + codebase_status +
           codebase_graph_status, with the graph measured by EDGE YIELD rather
           than by READY. JSON verdict on stdout, findings on stderr; exit 0
           when there is nothing to report, 1 when there is.
  resolve  print the resolved server launch command as JSON and exit — does not
           start the server (no Docker, no network); use it to debug resolution
  validate-manifest
           check .socraticodecontextartifacts.json (shape, unique names, every
           path resolves) and exit 0/1; no server, no network. Run before index.

projectPath defaults to the current working directory.

Flags:
  --probe <relpath>   health-check only: on a LOW yield verdict, run one
                      codebase_graph_query against this file as a confirmatory
                      probe. Give it a file you know has first-party imports.

Env:
  SOCRATICODE_ENTRY   explicit path to the socraticode server entry (skips resolution)
  CLAUDE_CONFIG_DIR   Claude config dir searched for the plugin's mcp.json and
                      installed_plugins.json (default ~/.claude)
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
                      ceiling is 60000, and this default never applies.`;

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

if (RUN_AS_SCRIPT) {
  const argv = process.argv.slice(2);
  const probeIdx = argv.indexOf('--probe');
  let probePath = null;
  if (probeIdx !== -1) {
    probePath = argv[probeIdx + 1] || null;
    if (!probePath) die('--probe needs a file path');
    argv.splice(probeIdx, 2);
  }
  const [cmd, projectPathArg] = argv;
  const projectPath = projectPathArg ? resolvePath(projectPathArg) : process.cwd();

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
        process.exit(1);
      }, ms);
      bomb.unref();
      await cmdHealthCheck(projectPath, probePath);
      clearTimeout(bomb);
      break;
    }
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
  // graph yield (#107)
  parseGraphCounts, graphYield, graphQueryEmpty, healthProblems,
  GRAPH_YIELD_MIN_EDGES_PER_NODE, GRAPH_YIELD_MIN_NODES,
  GRAPH_UNRESOLVED_WARN_PCT,
  indexingInProgress, lastOperationCompleted, lastOperationFailed,
  parseLastOpError, indexIncomplete, anotherProcessIndexing, indexSettled,
  expectedArtifactCount, resolveServerLaunch,
  // tool-reply predicates (gotcha M)
  indexStarted, indexAlreadyRunning, runningOperationIsFullIndex,
  contextIndexComplete, indexedZeroChunks,
  searchHasHits, listHasProjects,
};
