#!/usr/bin/env node
// >>> usage
// parser-selftest.mjs — pins mcp-driver.mjs's status PARSERS to fixtures.
//
// The driver decides "is the index done?" entirely by reading codebase_status
// text, so a server-side wording change silently turns completion detection
// into a 2h hang (#85, gotchas H/J). This selftest is the tripwire: run it
// after any server upgrade, or whenever a driver run behaves oddly.
//
// THIS IS A MANUAL CHECK. Nothing runs it automatically — the repo's
// pre-commit hook runs the Python structural suite, which does not shell out
// to node. Treat it as part of the "upgraded socraticode" checklist, not as
// something CI will catch for you.
//
// Fixtures are synthesized line-for-line from the server's own formatter
// (src/tools/query-tools.ts, socraticode 1.6.1). If the server changes its
// strings, update BOTH the fixtures here and the PARSERS in mcp-driver.mjs.
//
// Usage:
//   node parser-selftest.mjs      # run all assertions; exit 0 all-pass, 1 on failure
//   node parser-selftest.mjs --help
//
// No flags, no network, no server: pure string parsing.
// <<< usage
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  parseEmbedPercent, parseArtifacts, graphReady, indexingInProgress,
  lastOperationFailed, parseLastOpError, indexIncomplete,
  anotherProcessIndexing, indexSettled, validateManifest, MANIFEST_NAME,
  indexStarted, indexAlreadyRunning, runningOperationIsFullIndex,
  contextIndexComplete, indexedZeroChunks,
  searchHasHits, listHasProjects,
} from './mcp-driver.mjs';

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  const self = readFileSync(fileURLToPath(import.meta.url), 'utf8');
  const block = self.split('// >>> usage')[1].split('// <<< usage')[0];
  console.log(block.split('\n').slice(1, -1).map((l) => l.replace(/^\/\/ ?/, '')).join('\n'));
  process.exit(0);
}

let fails = 0;
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`FAIL ${label}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`); }
  else console.log(`ok   ${label}`);
};

const IN_PROGRESS = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 300

⚠ Full index in progress
  Phase: embedding chunks
  Progress: 300/6019 chunks embedded (5%)
  Elapsed: 120s

Keep calling codebase_status to check progress until it reaches 100%.

File watcher: active (auto-updating on changes)

Code graph: pending — will be auto-built after indexing completes

Context artifacts: 7 configured, not yet indexed
  Run codebase_context_index or search with codebase_context_search to auto-index.`;

// The exact state the #85 reporter was stuck in: green, done, no percentage.
const COMPLETED = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 950

Last operation: Full index — completed
  Files: 120, Chunks: 950
  35s ago (took 812.4s)

File watcher: active (auto-updating on changes)

Code graph: 120 files, 430 edges
  Last built: 10s ago (cached in memory)

Context artifacts: 7 artifacts indexed (131 chunks)`;

const FAILED = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 12

Last operation: Full index — FAILED
  Error: Ollama embedding request timed out
  12s ago (ran for 300.0s)

File watcher: inactive

Code graph: not built`;

const INCOMPLETE = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 400

⚠ INDEX IS INCOMPLETE — a previous indexing run was interrupted before finishing.
  Files indexed: 40 of 120 discovered
  Chunks stored: 400 (partial)

  Run codebase_index to resume and complete the index.

File watcher: inactive

Code graph: not built`;

const OTHER_PROCESS = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 400

⚠ ANOTHER PROCESS (PID 4242) IS ACTIVELY INDEXING this project.
  Files indexed so far: 40 of 120 discovered
  Chunks stored: 400 (partial)

File watcher: inactive`;

// First poll of a RE-index: the server child is fresh (no last-operation record
// yet) but Qdrant still holds the previous run's chunks and the graph is on disk.
const REINDEX_FIRST_POLL = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 950

File watcher: active (auto-updating on changes)

Code graph: 120 files, 430 edges
  Last built: 86400s ago

Context artifacts: 7 artifacts indexed (131 chunks)`;

const PARTIAL_ARTIFACTS = `Context artifacts: 2/7 indexed (40 chunks)
  Some artifacts are not yet indexed. Run codebase_context_index to index all.`;

// A first index during infrastructure setup: the server reports 0/0 files for
// however long the Qdrant/Ollama image pulls take (gotcha D). Nothing here may
// read as "no work to do" or as complete.
const INFRA_PHASE = `Project: /repo

⚠ Full index in progress
  Phase: preparing infrastructure
  Progress: 0/0 files
  Elapsed: 40s

Code graph: pending — will be auto-built after indexing completes`;

// The file watcher auto-starts on the first status call and records its own
// completions in the same process. This must not satisfy a full-index gate.
const WATCHER_INCREMENTAL = `Project: /repo
Collection: socraticode_abc
Status: green
Indexed chunks: 950

Last operation: Incremental update — completed
  Files: 2, Chunks: 11
  3s ago (took 0.4s)

File watcher: active (auto-updating on changes)

Code graph: 120 files, 430 edges
  Last built: 10s ago`;

console.log('— in-progress —');
eq('inProgress', indexingInProgress(IN_PROGRESS), true);
eq('pct parsed', parseEmbedPercent(IN_PROGRESS), 5);
eq('not settled', indexSettled(IN_PROGRESS), false);
eq('artifacts "N configured, not yet indexed" → 0/0', parseArtifacts(IN_PROGRESS), { done: 0, total: 0 });

console.log('— completed (the #85 hang state) —');
eq('settled', indexSettled(COMPLETED), true);
eq('pct is null once done (old gate could never fire)', parseEmbedPercent(COMPLETED), null);
eq('artifacts 7/7', parseArtifacts(COMPLETED), { done: 7, total: 7 });
eq('graphReady(status) is FALSE — status never says READY', graphReady(COMPLETED), false);
eq('graphReady(graph_status) is TRUE', graphReady('Code Graph Status\nStatus: READY\nFiles: 120'), true);
eq('not failed', lastOperationFailed(COMPLETED), false);

console.log('— failure states —');
eq('failed detected', lastOperationFailed(FAILED), true);
eq('error message extracted', parseLastOpError(FAILED), 'Ollama embedding request timed out');
eq('failed is not settled', indexSettled(FAILED), false);
eq('incomplete detected', indexIncomplete(INCOMPLETE), true);
eq('incomplete is not in progress', indexingInProgress(INCOMPLETE), false);
eq('other pid detected', anotherProcessIndexing(OTHER_PROCESS), '4242');
eq('other-process not flagged incomplete-and-idle', indexIncomplete(OTHER_PROCESS), false);

console.log('— re-index false-positive guard —');
eq('durable chunks+graph must NOT read as settled', indexSettled(REINDEX_FIRST_POLL), false);

console.log('— infrastructure phase must not read as terminal (gotcha D: image pulls report 0/0 files) —');
eq('infra phase is in progress', indexingInProgress(INFRA_PHASE), true);
eq('infra phase is not settled', indexSettled(INFRA_PHASE), false);
eq('"0/0 files" carries no completed-chunk count', indexedZeroChunks(INFRA_PHASE), false);
eq('a settled run with an empty collection does read as zero-chunk',
  indexedZeroChunks('Status: green\nIndexed chunks: 0\n\nLast operation: Full index — completed'), true);
eq('…and 950 chunks does not', indexedZeroChunks(COMPLETED), false);

console.log('— only a full-index completion settles; a watcher incremental must not (gotcha J) —');
eq('incremental completion is not settled', indexSettled(WATCHER_INCREMENTAL), false);
eq('full-index completion still settles', indexSettled(COMPLETED), true);

console.log('— the READY token comes only from graph_status, never from status text —');
// Documents WHY the status-text fallback was removed rather than kept as
// "drift insurance": the token is absent from a healthy status (asserted
// above), while an unrelated path substring satisfies it.
eq('status text of a healthy index yields no READY token', graphReady(COMPLETED), false);
eq('…yet a path containing "already" would have matched — the false positive that retired the fallback',
  graphReady('Project: /srv/already-migrated/api\nCode graph: 120 files, 430 edges'), true);

console.log('— tool replies that report failure by returning a string (gotcha M) —');
eq('index start confirmed', indexStarted('Indexing started in the background for: /repo\n\nIMPORTANT: …'), true);
eq('infra failure is not a start', indexStarted('Infrastructure setup failed:\n\nDocker daemon unreachable'), false);
eq('docker-unavailable is not a start', indexStarted('Docker is not available. Start Docker and retry.'), false);
eq('already-running is not a start…', indexStarted('⚠ Indexing is already in progress for: /repo'), false);
eq('…but is recognized as already running',
  indexAlreadyRunning('⚠ Indexing is already in progress for: /repo\nCannot run codebase_index — please wait'), true);
// Which run is underway decides whether waiting on it can ever finish: only a
// full index produces the completion the driver gates on.
eq('guard naming a full index → wait on it',
  runningOperationIsFullIndex('⚠ Indexing is already in progress for: /repo\n\nOperation: Full index\nPhase: embedding chunks'), true);
eq('guard naming an incremental → re-issue the index once it clears',
  runningOperationIsFullIndex('⚠ Indexing is already in progress for: /repo\n\nOperation: Incremental update\nPhase: scanning'), false);
eq('context index success confirmed', contextIndexComplete('Context Artifacts — Indexing Complete\n\n✓ agent-guidelines'), true);
eq('"No artifacts defined" is not success',
  contextIndexComplete('No artifacts defined in .socraticodecontextartifacts.json at /repo'), false);

console.log('— verification must be ABLE to fail: empty results are prose, not errors (gotchas K/L) —');
eq('real hits pass',
  searchHasHits('Search results for "config" (2 matches):\n\n--- src/app.py (lines 10-20) [python] score: 0.7123 ---\ncode here'), true);
eq('"No results found" fails',
  searchHasHits('No results found for "config" in project /repo.\nMake sure the project has been indexed first using codebase_index.'), false);
eq('"below score threshold" fails',
  searchHasHits('No results above score threshold 0.10 for "config" in project /repo.\n2 results were below the threshold.'), false);
eq('a populated project list passes', listHasProjects('Indexed projects (1):\n  - /repo\n    Collection: socraticode_abc'), true);
eq('the empty-list sentence fails', listHasProjects('No projects have been indexed yet. Use codebase_index to index a project.'), false);

console.log('— artifact shapes (gotcha H) —');
eq('partial 2/7', parseArtifacts(PARTIAL_ARTIFACTS), { done: 2, total: 7 });
eq('no line → 0/0', parseArtifacts('Project: /repo\nStatus: green'), { done: 0, total: 0 });

console.log('— manifest validation —');
const tmp = mkdtempSync(join(tmpdir(), 'socraticode-selftest-'));
const write = (obj) => {
  writeFileSync(join(tmp, 'AGENTS.md'), '# real file\n');
  writeFileSync(join(tmp, MANIFEST_NAME), typeof obj === 'string' ? obj : JSON.stringify(obj));
  return validateManifest(tmp);
};
try {
  const ok = write({ artifacts: [{ name: 'agent-guidelines', path: './AGENTS.md', description: 'conventions' }] });
  eq('well-formed manifest passes', [ok.errors.length, ok.count], [0, 1]);

  // The #85 shape: a bare top-level array. The server rejects it and
  // codebase_status then omits the artifact line, so anything that treats this
  // as "0 configured" reports green with no context search at all.
  const legacy = write([{ name: 'agent-guidelines', path: './AGENTS.md', description: 'conventions' }]);
  eq('legacy top-level array is rejected', legacy.errors.length > 0, true);
  eq('…with a migration hint', /wrap it/.test(legacy.errors[0]), true);

  const missingPath = write({ artifacts: [{ name: 'x', path: './nope.md', description: 'd' }] });
  eq('non-resolving path is an error', missingPath.errors.length, 1);

  const dupe = write({ artifacts: [
    { name: 'x', path: './AGENTS.md', description: 'd' },
    { name: 'X', path: './AGENTS.md', description: 'd' },
  ] });
  eq('duplicate name is case-insensitive', /duplicates/.test(dupe.errors.join()), true);

  const plural = write({ artifacts: [{ name: 'x', paths: ['./AGENTS.md'], description: 'd' }] });
  eq('plural "paths" key is caught', /there is no plural field/.test(plural.errors.join()), true);

  const glob = write({ artifacts: [{ name: 'x', path: './docs/**/*.md', description: 'd' }] });
  eq('glob path is caught', /looks like a glob/.test(glob.errors.join()), true);

  rmSync(join(tmp, MANIFEST_NAME));
  eq('absent manifest is not an error', validateManifest(tmp).present, false);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

console.log(fails ? `\n${fails} FAILED` : '\nall passed');
process.exit(fails ? 1 : 0);
