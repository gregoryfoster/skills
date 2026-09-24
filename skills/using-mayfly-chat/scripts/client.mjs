#!/usr/bin/env node
// Mayfly Chat client, vendored for the using-mayfly-chat skill (Node 18+, nothing to install).
//
// Upstream: https://github.com/josharian/mayfly — srv/static/client.mjs and create.mjs, fetched
// 2026-09-24 from https://mayfly.chat/static/ (upstream HEAD 06dd34e, 2026-09-11, MIT). The wire
// format, sealing, rendering and the read/post reply contract are upstream's, unchanged, in the
// sections marked "upstream". What differs, and the gregoryfoster/skills#302 finding behind each:
//   1. The channel URL is never an argument. It is read from the mode-600 file named by
//      MAYFLY_URL_FILE, and an argument shaped like a channel URL is refused before any request.
//      argv (/proc/<pid>/cmdline) is world-readable for the life of every call; a file is not.
//   2. `post` takes --body PATH and never reads stdin. A body-less post blocked on inherited
//      stdin for the whole tool budget, and an EOF would have posted an empty message that
//      cannot be deleted.
//   3. An ambiguous post outcome is resolved by one read-back from the old cursor. A post with
//      --last N commits at exactly N+1 or not at all, so one read answers it: posted:true with
//      recovered:"read-back" if N+1 is this message; posted:false on stdout with the missed page
//      if the head shows it is not; posted:null only if the read-back itself failed.
//   4. `listen`: short polls that skip this agent's own messages, back off on 503 or transport
//      failure, drain `more`, and return on the first peer message (exit 3 at the deadline).
//   5. `create ORIGIN` writes the new channel's URL straight into MAYFLY_URL_FILE (mode 600,
//      must not exist) and prints only the channel id, so the URL never crosses stdout.
//   6. `delete`: the post-leak remedy; upstream's CLIs have none.
//   7. A non-JSON error body (an HTML 503 page) is truncated to 200 characters.
// Exit 0 success; 1 conflict (stdout, posted:false) or error (stderr, JSON); 2 usage; 3 listen deadline.
import { createCipheriv, createDecipheriv, createHash, hkdfSync, randomBytes } from 'node:crypto';
import { existsSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { setTimeout as sleep } from 'node:timers/promises';

// ---- upstream: encoding, validation, key derivation, sealing, rendering ----------------------

const utf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }); // strict; a BOM is text
const b64 = bytes => Buffer.from(bytes).toString('base64url');
function unb64(text) {
  if (!/^[A-Za-z0-9_-]*={0,2}$/.test(text)) throw new Error('invalid base64url');
  return Buffer.from(text, 'base64url');
}

// Python's str.strip() whitespace: Unicode White_Space plus the C0 separators.
const ws = '[\\p{White_Space}\\x1c-\\x1f]';
const blank = new RegExp(`^${ws}*$`, 'u'), untrimmed = new RegExp(`^${ws}|${ws}$`, 'u');
const validText = s => typeof s === 'string' && !/\p{Cs}/u.test(s); // no lone surrogates
const validFrom = s => validText(s) && s !== '' && !untrimmed.test(s) && !/\p{Cc}/u.test(s);

function keys(address) {
  // Match the URL as written: no userinfo, query, backslash, space, or control byte anywhere,
  // and no ./.. repair of the path. Host/port syntax is then left to the URL parser.
  const raw = /^https?:\/\/([^\s\\/?#@\x00-\x1f]+)(\/[^\s\\?#\x00-\x1f]*)(?:#(.*))?$/i.exec(address); // scheme case-insensitive, as in Python
  if (!raw) throw new Error('expected HTTP(S) /c/ID#key with matching ID');
  let url;
  try { url = new URL(address); } catch { throw new Error('invalid URL (scheme, host or port)'); }
  const key = unb64(raw[3] ?? '');
  if (key.length !== 32) throw new Error('URL requires a 32-byte key fragment');
  const derive = (info, n) => Buffer.from(hkdfSync('sha256', key, Buffer.alloc(0), info, n));
  const ident = b64(derive('mayfly id', 16));
  const auth = b64(derive('mayfly auth', 32));
  const enc = derive('mayfly enc', 32);
  if (raw[2] !== `/c/${ident}`) {
    throw new Error('expected HTTP(S) /c/ID#key with matching ID');
  }
  return { url, ident, auth, enc };
}

function seal(enc, ident, seq, message) {
  const plain = Buffer.from(JSON.stringify(message));
  const padded = Buffer.alloc(Math.ceil(plain.length / 256) * 256, 0x20);
  padded.set(plain);
  const nonce = randomBytes(12);
  const c = createCipheriv('aes-256-gcm', enc, nonce).setAAD(Buffer.from(`${ident}:${seq}`));
  const ct = Buffer.concat([c.update(padded), c.final(), c.getAuthTag()]);
  return { nonce: b64(nonce), ct: b64(ct) };
}

function render(enc, ident, event) {
  for (const field of ['seq', 'ts', 'src']) {
    if (!Object.hasOwn(event, field)) throw new Error(`event missing ${field}`);
  }
  const row = { id: event.seq, ts: event.ts, src: event.src, from: '', text: '(undecryptable message)' };
  try {
    const nonce = unb64(event.nonce);
    if (nonce.length !== 12) return row;
    const ct = unb64(event.ct); // Too short for a tag: setAuthTag throws, row stays undecryptable.
    const d = createDecipheriv('aes-256-gcm', enc, nonce).setAAD(Buffer.from(`${ident}:${event.seq}`));
    d.setAuthTag(ct.subarray(ct.length - 16));
    const plain = Buffer.concat([d.update(ct.subarray(0, ct.length - 16)), d.final()]);
    row.text = '(invalid message)';
    const inner = JSON.parse(utf8.decode(plain));
    if (inner !== null && typeof inner === 'object' && !Array.isArray(inner)
        && validFrom(inner.from) && validText(inner.text)) {
      row.from = inner.from;
      row.text = inner.text;
    }
  } catch {} // Undecryptable or unbelievable events keep their row; later rows still print.
  return row;
}

// upstream create.mjs: an origin is scheme, host and optional port, nothing else.
function origin(raw) {
  const authority = raw.slice(raw.indexOf('//') + 2).replace(/\/$/, '');
  if (!raw || /[\\\x00-\x1f\x7f]/.test(raw) || raw.includes('?') || raw.includes('#') || authority.endsWith(':') ||
      !/^https?:\/\/[^/?#\\\x00-\x1f]+\/?$/i.test(raw)) {
    throw new Error('expected an HTTP(S) origin with no path, query, or fragment');
  }
  let url;
  try { url = new URL(raw); } catch { throw new Error('invalid URL (scheme, host, or port)'); }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('expected an HTTP(S) origin with no path, query, or fragment');
  }
  return url;
}

function request(target, method, headers, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    const req = (target.protocol === 'https:' ? https : http).request(target, { method, headers, agent: false }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, raw: Buffer.concat(chunks) }));
      res.on('error', reject);
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error('timed out')));
    req.on('error', reject);
    req.end(body); // http.request never follows redirects.
  });
}

// ---- derivative: the URL file, the body file, and the command surface ----------------------

const URL_FILE_VAR = 'MAYFLY_URL_FILE';
const REFUSAL = 'refusing a channel URL on the command line: write it to a mode-600 file and set MAYFLY_URL_FILE';

// An origin (create's one legitimate URL argument) has no /c/ path and no fragment.
const looksLikeChannelUrl = s => /:\/\//.test(s) && (/\/c\//.test(s) || s.includes('#'));

function urlFilePath() {
  const path = process.env[URL_FILE_VAR];
  if (!path) throw new Error(`${URL_FILE_VAR} is not set; it must name a mode-600 file holding the channel URL`);
  return path;
}

function readUrlFile() {
  const path = urlFilePath();
  let st;
  try { st = statSync(path); } catch { throw new Error(`${URL_FILE_VAR}=${path}: no such file`); }
  if (!st.isFile()) throw new Error(`${URL_FILE_VAR}=${path}: not a regular file`);
  if (process.platform !== 'win32' && (st.mode & 0o077) !== 0) {
    throw new Error(`${URL_FILE_VAR}=${path}: mode must be 600, found ${(st.mode & 0o777).toString(8)}; chmod 600 it`);
  }
  const text = utf8.decode(readFileSync(path)).trim();
  if (!text) throw new Error(`${URL_FILE_VAR}=${path}: empty`);
  return text;
}

function readBody(path) {
  if (path === '-' || path === '/dev/stdin') throw new Error('--body must be a regular file; stdin is never read');
  let st;
  try { st = statSync(path); } catch { throw new Error(`--body ${path}: no such file`); }
  if (!st.isFile()) throw new Error(`--body ${path}: not a regular file`);
  const text = utf8.decode(readFileSync(path));
  if (blank.test(text)) throw new Error('message must be nonblank');
  return text;
}

const usage = `usage: node client.mjs COMMAND [options]      (Node 18+, nothing to install)
  read   --last N [--wait S]                       one page; re-read with the returned last while "more" is true
  post   --from NAME --last N --body PATH [--wait S]
  listen --last N --me NAME [--slot S] [--max S]   short polls; returns on the first message not from NAME
  create ORIGIN                                    mint a channel; writes its URL into MAYFLY_URL_FILE
  delete                                           destroy the channel (the post-leak remedy; no undo)
The channel URL is never an argument: MAYFLY_URL_FILE names a mode-600 file that holds it, which
create writes (it must not already exist) and every other command reads. --last starts at -1; read
all pages before posting. --slot is 1-300 seconds (default 60); --max is the listen deadline in
seconds (default 1800). One JSON object per run: stdout on success or conflict, stderr on error.
Exit 0 success; 1 conflict (posted:false) or error; 2 usage; 3 listen deadline with no peer message.`;

function parseArgs(argv) {
  const opts = { wait: '0', slot: '60', max: '1800' }, positional = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') return null;
    if (looksLikeChannelUrl(arg)) throw new Error(REFUSAL);
    const m = /^--(last|wait|from|body|me|slot|max)(?:=([^]*))?$/.exec(arg);
    if (m) {
      const value = m[2] ?? argv[++i];
      if (value === undefined) throw new Error(`--${m[1]} requires a value`);
      if (looksLikeChannelUrl(value)) throw new Error(REFUSAL);
      opts[m[1]] = value;
    } else if (arg.startsWith('-')) {
      throw new Error(`unrecognized argument: ${arg}`);
    } else {
      positional.push(arg);
    }
  }
  const [command, ...extra] = positional;
  const commands = ['read', 'post', 'listen', 'create', 'delete'];
  if (!commands.includes(command)) throw new Error(`command must be one of ${commands.join('|')}`);
  if (command === 'create') {
    if (extra.length !== 1) throw new Error('create takes exactly one ORIGIN, such as https://mayfly.chat');
    return { command, origin: extra[0] };
  }
  if (extra.length) throw new Error(`${command} takes no positional arguments`);
  if (command === 'delete') return { command };
  if (opts.last === undefined) throw new Error('the following arguments are required: --last');
  for (const name of ['last', 'wait']) {
    if (!/^[+-]?\d+$/.test(opts[name])) throw new Error(`--${name}: invalid int value: ${JSON.stringify(opts[name])}`);
    opts[name] = String(BigInt(opts[name])); // Exact decimal; the server, not the client, decides the range.
  }
  if (command === 'read') return { command, last: opts.last, wait: opts.wait };
  if (command === 'post') {
    if (!validFrom(opts.from)) throw new Error('post requires --from: nonempty, trimmed, no control characters');
    if (!opts.body) throw new Error('post requires --body PATH (stdin is never read)');
    return { command, name: opts.from, last: opts.last, wait: opts.wait, body: opts.body };
  }
  if (!validFrom(opts.me)) throw new Error('listen requires --me NAME: your own --from, so your posts are skipped');
  const slot = Number(opts.slot), max = Number(opts.max);
  if (!Number.isInteger(slot) || slot < 1 || slot > 300) throw new Error('--slot must be an integer from 1 to 300 seconds');
  if (!Number.isInteger(max) || max < 1) throw new Error('--max must be a positive integer of seconds');
  return { command, last: opts.last, me: opts.me, slot, max };
}

// ---- derivative: one request, one reply, and the commands built on them --------------------

class ReplyError extends Error {
  constructor(reply, status) {
    super(`HTTP ${status}`);
    this.reply = { ...reply, http_status: status };
    this.status = status;
  }
}

function parseReply(raw, status) {
  try {
    const reply = JSON.parse(utf8.decode(raw));
    if (reply === null || typeof reply !== 'object' || Array.isArray(reply)) throw new Error('expected a JSON object');
    return reply;
  } catch {
    const text = raw.toString('utf8');
    return { error: text.length > 200 ? `${text.slice(0, 200)}…` : text, http_status: status };
  }
}

const timeoutFor = wait => Math.max(60, Math.min(Number(wait) + 60, 86460)) * 1000;

async function exchange(chan, method, pathAndQuery, body, timeoutMs) {
  const headers = { Authorization: `Bearer ${chan.auth}`, 'Content-Type': 'application/json' };
  const { status, raw } = await request(new URL(pathAndQuery, chan.url), method, headers, body, timeoutMs);
  return { status, reply: parseReply(raw, status) };
}

function renderPage(chan, reply) {
  const { events, ...rest } = reply;
  if (!Array.isArray(events)) throw new Error('reply has no events list');
  return { ...rest, messages: events.map(event => render(chan.enc, chan.ident, event)) };
}

async function doRead(chan, last, wait) {
  const { status, reply } = await exchange(chan, 'GET', `/c/${chan.ident}/events?since=${last}&wait=${wait}`, undefined, timeoutFor(wait));
  if (status !== 200) throw new ReplyError(reply, status);
  return renderPage(chan, reply);
}

// A post with last=N commits at exactly N+1 or not at all: one read from N settles it.
async function readBack(chan, name, last, text, original) {
  const ambiguous = {
    ...original,
    posted: null,
    hint: 'Post may have succeeded. Read from old --last before resubmitting; no retry.',
  };
  let page;
  try {
    page = await doRead(chan, last, '0');
  } catch (error) {
    ambiguous.readback = error instanceof ReplyError ? error.reply : { error: error.message };
    return { page: ambiguous, exit: 1, stream: 'stderr' };
  }
  const next = page.messages.find(m => String(m.id) === String(BigInt(last) + 1n));
  const base = { ...page, recovered: 'read-back', original_error: original.error };
  if (next && next.from === name && next.text === text) {
    return { page: { ...base, posted: true, id: next.id }, exit: 0, stream: 'stdout' };
  }
  return {
    page: {
      ...base,
      posted: false,
      hint: 'Read-back from the old cursor shows nothing of yours at N+1: nothing was appended. Drain pages, reconsider, then post with the final last. No retry.',
    },
    exit: 1,
    stream: 'stdout',
  };
}

async function doPost(chan, name, last, text, wait) {
  const sealed = JSON.stringify(seal(chan.enc, chan.ident, BigInt(last) + 1n, { from: name, text }));
  let status, reply;
  try {
    ({ status, reply } = await exchange(chan, 'POST', `/c/${chan.ident}/events?last=${last}&wait=${wait}`, sealed, timeoutFor(wait)));
  } catch (error) {
    return readBack(chan, name, last, text, { error: error.message }); // transport failed after the request went out
  }
  if (status === 409) {
    const page = renderPage(chan, reply);
    page.posted = false;
    page.hint = 'Read all returned/remaining pages; reconsider, then post with final last. No retry.';
    return { page, exit: 1, stream: 'stdout' };
  }
  if (status === 200 && reply.posted === true) {
    return { page: renderPage(chan, reply), exit: 0, stream: 'stdout' };
  }
  reply.http_status = status;
  if (status === 503 && reply.error === 'restarting' && reply.posted === false) {
    return { page: reply, exit: 1, stream: 'stderr' }; // definite refusal: nothing was written
  }
  return readBack(chan, name, last, text, reply); // any other reply after the request went out
}

async function doListen(chan, last, me, slot, max) {
  const deadline = Date.now() + max * 1000;
  let cursor = last, backoff = 10;
  for (;;) {
    const remaining = Math.ceil((deadline - Date.now()) / 1000);
    if (remaining <= 0) {
      return {
        page: { last: cursor, messages: [], timeout: true, hint: `No peer message within ${max}s; the cursor is ${cursor}.` },
        exit: 3,
        stream: 'stdout',
      };
    }
    let messages, head;
    try {
      head = await doRead(chan, cursor, String(Math.min(slot, remaining)));
      messages = [...head.messages];
      while (head.more) { // drain before judging, so a peer message on a later page is not missed
        head = await doRead(chan, head.last, '0');
        messages.push(...head.messages);
      }
    } catch (error) {
      if (error instanceof ReplyError && [400, 401, 404, 413].includes(error.status)) throw error;
      await sleep(Math.min(backoff, Math.max(remaining, 1)) * 1000); // 503 or transport: reads are idempotent
      backoff = Math.min(backoff * 2, 60);
      continue;
    }
    backoff = 10;
    const peer = messages.filter(m => m.from !== me).length;
    if (peer > 0) return { page: { last: head.last, more: false, messages, peer }, exit: 0, stream: 'stdout' };
    cursor = head.last;
  }
}

async function doCreate(originRaw) {
  const path = urlFilePath();
  if (existsSync(path)) throw new Error(`${URL_FILE_VAR}=${path}: already exists; one channel per file, choose a new path`);
  const url = origin(originRaw);
  const key = randomBytes(32);
  const derive = (info, n) => Buffer.from(hkdfSync('sha256', key, Buffer.alloc(0), info, n));
  const id = b64(derive('mayfly id', 16));
  const auth = b64(derive('mayfly auth', 32));
  const body = JSON.stringify({ id, auth_hash: b64(createHash('sha256').update(auth).digest()) });
  const { status, raw } = await request(new URL('/new', url), 'POST', { 'Content-Type': 'application/json' }, body, 60000);
  if (status === 503) throw new Error('HTTP 503: server temporarily unavailable; try again shortly');
  if (status !== 303) throw new ReplyError(parseReply(raw, status), status);
  writeFileSync(path, `${url.origin}/c/${id}#${b64(key)}\n`, { flag: 'wx', mode: 0o600 });
  return { page: { created: true, id, file: path }, exit: 0, stream: 'stdout' };
}

async function doDelete(chan) {
  const { status, raw } = await request(new URL(`/c/${chan.ident}`, chan.url), 'DELETE', { Authorization: `Bearer ${chan.auth}` }, undefined, 60000);
  if (status !== 204) throw new ReplyError(parseReply(raw, status), status);
  return { page: { deleted: true, id: chan.ident }, exit: 0, stream: 'stdout' };
}

async function main() {
  let args;
  try { args = parseArgs(process.argv.slice(2)); } catch (error) {
    process.stderr.write(`${usage.split('\n')[0]}\nerror: ${error.message}\n`);
    return 2;
  }
  if (args === null) {
    process.stdout.write(`${usage}\n`);
    return 0;
  }
  try {
    let result;
    if (args.command === 'create') {
      result = await doCreate(args.origin);
    } else {
      const chan = keys(readUrlFile());
      switch (args.command) {
        case 'read': result = { page: await doRead(chan, args.last, args.wait), exit: 0, stream: 'stdout' }; break;
        case 'post': result = await doPost(chan, args.name, args.last, readBody(args.body), args.wait); break;
        case 'listen': result = await doListen(chan, args.last, args.me, args.slot, args.max); break;
        default: result = await doDelete(chan);
      }
    }
    (result.stream === 'stdout' ? process.stdout : process.stderr).write(`${JSON.stringify(result.page)}\n`);
    return result.exit;
  } catch (error) {
    const reply = error instanceof ReplyError ? error.reply : { error: error.message };
    process.stderr.write(`${JSON.stringify(reply)}\n`);
    return 1;
  }
}

process.exitCode = await main();
