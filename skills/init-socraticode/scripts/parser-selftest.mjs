#!/usr/bin/env node
// >>> usage
// parser-selftest.mjs — pins mcp-driver.mjs's status PARSERS to fixtures.
//
// The driver decides "is the index done?" entirely by reading codebase_status
// text, so a server-side wording change silently turns completion detection
// into a 2h hang (#85, gotchas H/J). This selftest is the tripwire: run it
// after any server upgrade, or whenever a driver run behaves oddly.
//
// RUN AUTOMATICALLY since #107: tests/structural/test_socraticode_graph_yield.py
// shells out to this file (skipping loudly when node is absent), so the
// pre-commit structural suite pulls the tripwire. It used to be a manual check
// nothing ran, which is not a tripwire. Still run it by hand after a server
// upgrade — the fixtures are the thing that goes stale, and only a human
// comparing them to the new server's output can notice.
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
  parseGraphCounts, graphYield, graphQueryEmpty, healthProblems,
  GRAPH_YIELD_MIN_EDGES_PER_NODE, GRAPH_YIELD_MIN_NODES,
  GRAPH_UNRESOLVED_WARN_PCT,
  parseContextArtifacts, parseIndexedAt,
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

console.log('— graph YIELD: READY is a status, not a result (#107) —');
// Verbatim from CannObserv/usa-wa's codebase_graph_status, the run that filed
// #107: a uv workspace with the standard src layout, where the resolver cannot
// follow packages/<dashed-name>/src/<underscored_module>/ and gives up.
const GRAPH_LOW = `Code Graph Status

Status: READY
Files (nodes): 374
Dependencies (edges): 3
Symbols: 3767
Call edges: 23237
Unresolved: 81.8%`;
const GRAPH_OK = `Code Graph Status

Status: READY
Files (nodes): 374
Dependencies (edges): 1512
Symbols: 3767
Call edges: 23237
Unresolved: 12.4%`;
const GRAPH_TINY = `Code Graph Status

Status: READY
Files (nodes): 6
Dependencies (edges): 0`;

eq('the #107 graph parses', parseGraphCounts(GRAPH_LOW),
  { nodes: 374, edges: 3, symbols: 3767, callEdges: 23237, unresolvedPct: 81.8 });
// The whole point: both of these are READY.
eq('READY does not distinguish them', [graphReady(GRAPH_LOW), graphReady(GRAPH_OK)], [true, true]);
eq('…yield does: the #107 graph is LOW', graphYield(GRAPH_LOW).verdict, 'low');
eq('…and a resolving graph is OK', graphYield(GRAPH_OK).verdict, 'ok');
// `unknown` must never be silently folded into `low`: writing the degraded
// policy asserts a repo's graph is broken, and a repo too small to judge, or a
// status string we could not read, is not evidence of that.
eq('a 6-file repo is UNKNOWN, not LOW', graphYield(GRAPH_TINY).verdict, 'unknown');
eq('an unparseable status is UNKNOWN, not LOW',
  graphYield('Code Graph Status\n\nStatus: BUILDING').verdict, 'unknown');
eq('the threshold is edges/node, and it is stated once',
  graphYield(GRAPH_LOW).edgesPerNode < GRAPH_YIELD_MIN_EDGES_PER_NODE, true);
// The corroborating signal, never the verdict — call-graph unresolution is
// legitimately high in dynamic code.
eq('unresolved% is parsed for corroboration',
  graphYield(GRAPH_LOW).unresolvedPct > GRAPH_UNRESOLVED_WARN_PCT, true);
eq('a small graph is not judged by node count alone', GRAPH_YIELD_MIN_NODES, 20);
// `Call edges` is a different statistic and is three orders of magnitude larger
// on exactly the broken graph this gate exists to catch. If a relabelled build
// let it satisfy the dependency-edge matcher, the verdict would flip from `low`
// to a confident `ok` — the worst possible direction for this gate.
eq('"Call edges" must not be mistaken for dependency edges',
  parseGraphCounts('Status: READY\nFiles (nodes): 374\nCall edges: 23237').edges, null);
eq('…and a graph missing its dependency line is UNKNOWN, never ok',
  graphYield('Status: READY\nFiles (nodes): 374\nCall edges: 23237').verdict, 'unknown');
// The failure SHAPE is what makes this invisible: an ordinary sentence, no
// error, which an agent reads as a fact about the code.
eq('empty graph query is prose, not an exception',
  graphQueryEmpty('No dependency information found for this file.'), true);
eq('a real graph answer is not empty',
  graphQueryEmpty('Dependencies of src/app.py:\n  imports: src/db.py'), false);
eq('a stopped container is a health problem',
  healthProblems('Docker: ✓ running\nQdrant: ✗ container not running\nOllama: ✓').length, 1);
eq('an all-green health report has no problems',
  healthProblems('Docker: ✓ running\nQdrant: ✓ healthy\nOllama: ✓ nomic-embed-text present'), []);

console.log('— artifact shapes (gotcha H) —');
eq('partial 2/7', parseArtifacts(PARTIAL_ARTIFACTS), { done: 2, total: 7 });
eq('no line → 0/0', parseArtifacts('Project: /repo\nStatus: green'), { done: 0, total: 0 });
// Both of these parse to 0/0, which is why the MANIFEST is the denominator for
// the declared≠indexed check (#214) and this line never is.
eq('"N configured, not yet indexed" → 0/0 as well',
  parseArtifacts('Context artifacts: 7 configured, not yet indexed'), { done: 0, total: 0 });

// codebase_context, verbatim from a live 13-artifact reply (trimmed to two).
// This is the only per-artifact index status the server offers — the status
// line above counts, it never names.
const CONTEXT_LISTING = `Context Artifacts for: /repo
Config: .socraticodecontextartifacts.json (2 artifacts)

━━━ database-schema ━━━
  Path: ./docs/schema.sql
  Description: PostgreSQL schema.
  Status: ✓ indexed (42 chunks, 2026-08-09T04:46:34.264Z)

━━━ reference-docs ━━━
  Path: ./docs/
  Description: The docs tree.
  Status: ○ not yet indexed

Use codebase_context_search to search across artifacts.`;
eq('per-artifact status is parsed, and the name comes with it',
  parseContextArtifacts(CONTEXT_LISTING).map((a) => [a.name, a.indexed]),
  [['database-schema', true], ['reference-docs', false]]);
// Asymmetric on purpose: an unrecognised status must fall to NOT indexed, or
// the silent-green hole this check closes reopens on the next server reword.
eq('an unknown status is not indexed',
  parseContextArtifacts('━━━ x ━━━\n  Status: ✗ fetch failed')[0].indexed, false);
eq('no artifacts configured → nothing to compare',
  parseContextArtifacts('No context artifacts configured for: /repo'), []);
// The freshness half of the same reply (#225). `indexed` is a PRESENCE check;
// the index time beside it, and the source path above it, are what say whether
// an indexed artifact still matches the file it was built from.
eq('the index time is read off the status line',
  parseContextArtifacts(CONTEXT_LISTING).map((a) => a.lastIndexed),
  ['2026-08-09T04:46:34.264Z', null]);
eq('…and the source path comes with it',
  parseContextArtifacts(CONTEXT_LISTING).map((a) => a.path),
  ['./docs/schema.sql', './docs/']);
// A build that stops printing the timestamp must leave freshness UNJUDGED.
// Reading a missing time as "indexed just now" would rebuild the silent green;
// reading it as stale would make the line noise the cohort learns to skip.
eq('a status with no timestamp yields no index time',
  parseIndexedAt('✓ indexed'), null);
eq('a bare date is not an index time',
  parseIndexedAt('✓ indexed (42 chunks, 2026-08-09)'), null);

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
