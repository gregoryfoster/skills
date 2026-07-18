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
//   C — "100% embedded" is NOT done; we gate on embeddings 100% AND graph READY
//       AND context artifacts N/N before returning success.
//   G — we OWN the child and kill it by child.pid on exit. We never pkill by
//       cmdline, so there is no self-match footgun.
//   H — status strings are parsed loosely (regex, both artifact shapes).
//
// Wire contract verified against: socraticode (npx -y socraticode) as of
// 2026-07. If the server's tool names or status strings change, update the
// PARSERS and TOOL NAMES sections below.
//
// VALIDATE ON FIRST USE — these assumptions have NOT been exercised end-to-end
// against a live server; confirm them the first time you actually run this:
//   - codebase_search's argument name is `query` (check the server's tools/list)
//   - initialize protocolVersion '2024-11-05' is accepted by the installed server
//   - every tool takes its target as `projectPath`
//   - require.resolve('socraticode') resolves the stdio server entry (else set
//     SOCRATICODE_ENTRY)
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
import { existsSync, readFileSync } from 'node:fs';
import { resolve as resolvePath, join as joinPath } from 'node:path';

const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS || 15000);
const INDEX_TIMEOUT_MS = Number(process.env.INDEX_TIMEOUT_MS || 7200000);

// ── entrypoint resolution (never hard-code dist/index.js) ───────────────────
function resolveServerEntry() {
  if (process.env.SOCRATICODE_ENTRY) {
    const p = resolvePath(process.env.SOCRATICODE_ENTRY);
    if (!existsSync(p)) die(`SOCRATICODE_ENTRY does not exist: ${p}`);
    return p;
  }
  // 1) require.resolve from this module's context (works if socraticode is a dep).
  try {
    const req = createRequire(import.meta.url);
    return req.resolve('socraticode');
  } catch { /* fall through */ }
  // 2) resolve the package root, then read its package.json "main"/"bin".
  for (const args of [['root', '-g'], ['root']]) {
    const out = spawnSync('npm', args, { encoding: 'utf8' });
    if (out.status === 0 && out.stdout) {
      const base = out.stdout.trim();
      const req = createRequire(resolvePath(base, 'x'));
      try { return req.resolve('socraticode'); } catch { /* keep trying */ }
      const guess = resolvePath(base, 'socraticode', 'dist', 'index.js');
      if (existsSync(guess)) return guess;
    }
  }
  die(
    'Could not resolve the socraticode server entrypoint.\n' +
    '  Set SOCRATICODE_ENTRY=/abs/path/to/socraticode/dist/index.js, or\n' +
    '  install it first:  npm i -g socraticode   (or `npx -y socraticode` once to populate the npx cache)'
  );
}

// ── minimal JSON-RPC 2.0 stdio client ───────────────────────────────────────
class RpcClient {
  constructor(entry) {
    // We own this child. On our exit we kill it by child.pid — never pkill.
    this.child = spawn(process.execPath, [entry], { stdio: ['pipe', 'pipe', 'inherit'] });
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
function parseEmbedPercent(text) {
  // "Progress: 6019/6019 chunks embedded (100%)"  → 100
  const pct = text.match(/embedded\s*\((\d+)%\)/i);
  if (pct) return Number(pct[1]);
  const frac = text.match(/(\d+)\s*\/\s*(\d+)\s*chunks?\s*embedded/i);
  if (frac && Number(frac[2]) > 0) return Math.floor((Number(frac[1]) / Number(frac[2])) * 100);
  return null;
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

// Authoritative expected artifact count from the repo's manifest. The status
// line can't distinguish "no artifacts configured" (0 expected) from "artifacts
// not reported yet" (line absent) — both parse to 0/0 — so we read the manifest
// instead. Returns the declared count, or null when there is no manifest.
function expectedArtifactCount(projectPath) {
  const manifest = joinPath(projectPath, '.socraticodecontextartifacts.json');
  if (!existsSync(manifest)) return null;
  try {
    const parsed = JSON.parse(readFileSync(manifest, 'utf8'));
    return Array.isArray(parsed.artifacts) ? parsed.artifacts.length : null;
  } catch {
    return null; // malformed manifest → fall back to trusting the status line
  }
}

// ── high-level flows ─────────────────────────────────────────────────────────
function die(msg) { console.error(`ERROR: ${msg}`); process.exit(1); }

async function withClient(fn) {
  const entry = resolveServerEntry();
  console.error(`[driver] server entry: ${entry}`);
  const client = new RpcClient(entry);
  try {
    await client.handshake();
    return await fn(client);
  } finally {
    client.kill();
  }
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
    let nullPolls = 0;
    for (;;) {
      if (Date.now() - started > INDEX_TIMEOUT_MS) {
        die(`index did not complete within ${Math.round(INDEX_TIMEOUT_MS / 60000)} min`);
      }
      await sleep(POLL_INTERVAL_MS);

      const status = await client.callTool('codebase_status', { projectPath });
      const pct = parseEmbedPercent(status);
      const art = parseArtifacts(status);

      // Early terminal: 0/0 chunks means there is nothing to embed — abort with a
      // clear message instead of hanging until the 2h timeout.
      if (/\b0\s*\/\s*0\b[^\n]*chunks?/i.test(status)) {
        die('codebase_status reports 0/0 chunks — nothing to embed (empty repo or no indexable files).');
      }
      // Status string couldn't be parsed for a percentage: warn once after a few
      // polls so a server string change surfaces as a hint, not a silent 2h hang.
      if (pct == null) {
        if (++nullPolls === 3) {
          console.error('[driver] WARNING: cannot parse an embedding % from codebase_status — the server string may have changed; check the PARSERS section of this file. Still polling.');
        }
      } else {
        nullPolls = 0;
      }

      let graph = '';
      try { graph = await client.callTool('codebase_graph_status', { projectPath }); } catch { /* older server */ }
      const gReady = graphReady(graph) || graphReady(status);

      // Expected count: manifest is authoritative; otherwise trust the status line.
      const wantArtifacts = expectedArtifacts != null ? expectedArtifacts : art.total;

      console.error(
        `[driver] embeddings=${pct == null ? '?' : pct + '%'} ` +
        `graph=${gReady ? 'READY' : 'building'} ` +
        `artifacts=${art.done}/${wantArtifacts}`
      );

      // Once embeddings are done, nudge context indexing if artifacts lag (gotcha C).
      // Retry on transient failure (leave contextKicked false) rather than
      // spinning to the timeout; give up loudly after MAX_CONTEXT_KICKS.
      if (pct === 100 && !contextKicked && wantArtifacts > 0 && art.done < wantArtifacts) {
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
      if (pct === 100 && gReady && artifactsDone) {
        console.error('[driver] DONE — embeddings 100%, graph READY, artifacts complete.');
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

projectPath defaults to the current working directory.

Env:
  SOCRATICODE_ENTRY   explicit path to the socraticode server entry (skips resolution)
  POLL_INTERVAL_MS    status poll cadence (default 15000)
  INDEX_TIMEOUT_MS    overall ceiling (default 7200000 = 2h)`;

const [cmd, projectPathArg] = process.argv.slice(2);
const projectPath = projectPathArg ? resolvePath(projectPathArg) : process.cwd();

switch (cmd) {
  case 'index': await cmdIndex(projectPath); break;
  case 'status': await cmdStatus(projectPath); break;
  case 'verify': await cmdVerify(projectPath); break;
  case '--help': case '-h': console.log(USAGE); break;
  default:
    console.error(USAGE);
    process.exit(2);
}
