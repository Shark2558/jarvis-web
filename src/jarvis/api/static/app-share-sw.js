// src/jarvis/api/static/app-share-sw.js -- R7 Part A (docs/plans/r7-mobile.md D15): the share tray's worker, served
// as /app/share/sw.js with scope /app/share/ only. Its scope holds no page, so it controls no page and can never
// serve a stale console (R3's rule). It takes ONE request, the share sheet's POST to /app/share/in, and keeps what
// was shared in this browser's own Cache Storage ('jarvis-share-v1'); then it answers 303 to /?do=shared, where the
// console's tray (console-r7-share.js) offers what to do with each item. It never sends anything anywhere: no
// fetch, no upload, no message to the server. Nothing reaches JARVIS before the owner presses a button in the tray.
//   kept: at most 5 items, each at most 10 MB: a JPEG, PNG, WebP or PDF, or one line of text (title, text, link;
//   at most 2,000 characters). Items older than 24 hours are dropped. Anything else is refused in plain words,
//   in a notice the tray shows once. A shared name is someone else's text: it is only ever shown as text.
'use strict';

const CACHE = 'jarvis-share-v1';
const ITEM = '/app/share/item/';
const NOTICE = '/app/share/notice';
const LANDING = '/?do=shared';
const MAX_ITEMS = 5;
const MAX_BYTES = 10 * 1024 * 1024;
const KEEP_MS = 24 * 60 * 60 * 1000;
const TEXT_MAX = 2000;
const MAX_BODY = 60 * 1024 * 1024; // the whole post: five files of 10 MB, their text and the form's own bytes
const MAX_FILES = 10;
const HOME = '/';
const TYPES = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf' };
const BY_EXT = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.pdf': 'application/pdf' };
const WHY = {
  kind: 'JARVIS takes photos (JPEG, PNG or WebP), PDFs and text only.',
  big: 'It is over 10 MB, the most JARVIS takes.',
  empty: 'It is empty.',
  full: 'The tray holds 5 items at most. Discard one there, then share this again.',
  long: 'The text is longer than 2,000 characters.',
  unread: 'That share could not be read. Please try again.',
  room: 'No room left on this phone for that item, Sir.',
  mismatch: 'The file is not what its name says it is.',
  body: 'That share is too big for JARVIS to take.',
  many: 'Too many files at once. JARVIS takes 5 at most.',
  origin: 'That did not come from your phone\u2019s share sheet, so JARVIS kept nothing.',
};
// What each kind starts with (the sender's word for its type is only a claim).
const SNIFF = {
  'image/jpeg': (b) => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff,
  'image/png': (b) => [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((v, i) => b[i] === v),
  'image/webp': (b) => [0x52, 0x49, 0x46, 0x46].every((v, i) => b[i] === v) && [0x57, 0x45, 0x42, 0x50].every((v, i) => b[8 + i] === v),
  'application/pdf': (b) => [0x25, 0x50, 0x44, 0x46, 0x2d].every((v, i) => b[i] === v),
};

self.addEventListener('install', () => { self.skipWaiting(); });
// A new worker also clears what is past 24 hours (a local cache job; nothing is asked of any server).
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.open(CACHE).then(sweep).catch(() => {}));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  let url = null;
  try { url = new URL(req.url); } catch (_) { return; }
  if (req.method !== 'POST' || url.origin !== self.location.origin || url.pathname !== '/app/share/in') return;
  event.respondWith(take(req));
});

/** A post another site (or another origin) sent: a real share-sheet launch is 'none' (or absent), a page of ours 'same-origin'. */
function foreign(req) {
  const site = req.headers.get('Sec-Fetch-Site'), origin = req.headers.get('Origin');
  if (site === 'cross-site' || site === 'same-site') return true;
  return !!origin && origin !== 'null' && origin !== self.location.origin;
}

/** True when the post is over the whole-body cap: by its length, or (no length given) by counting it, stopping at the cap. */
async function overCap(req) {
  const len = req.headers.get('Content-Length');
  if (len !== null && len !== '') { const n = Number(len); return !Number.isFinite(n) || n > MAX_BODY; }
  try {
    const body = req.clone().body;
    if (!body) return false;
    const reader = body.getReader();
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return false;
      total += value.length;
      if (total > MAX_BODY) { reader.cancel().catch(() => {}); return true; }
    }
  } catch (_) { return true; }
}

/** A shared file's name, shown as text only: no folders, no control characters, at most 120 characters. */
function cleanName(raw) {
  const base = String(raw || '').split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069]/g, '');
  return base.trim().slice(0, 120) || 'shared';
}
const extOf = (name) => { const i = name.lastIndexOf('.'); return i > 0 ? name.slice(i).toLowerCase() : ''; };

/** The kind JARVIS keeps (by the type the sender gave, else by the name), or '' to refuse. */
function kindOf(type, name) {
  const t = String(type || '').split(';')[0].trim().toLowerCase();
  if (TYPES[t]) return t;
  if (t && t !== 'application/octet-stream') return '';
  return BY_EXT[extOf(name)] || '';
}

/** The name with the extension its kind needs (R11.1's picture path reads names). */
function named(name, kind) {
  const want = TYPES[kind];
  const ext = extOf(name);
  return BY_EXT[ext] === kind ? name : name + want;
}

function meta(kind, name, type, size) {
  return {
    'Content-Type': type,
    'X-Jarvis-Kind': kind,
    'X-Jarvis-Name': encodeURIComponent(name),
    'X-Jarvis-Size': String(size),
    'X-Jarvis-At': String(Date.now()),
  };
}

async function fileItem(f, refused) {
  const name = cleanName(f.name);
  const kind = kindOf(f.type, name);
  if (!kind) { refused.push({ name, why: WHY.kind }); return null; }
  if (f.size > MAX_BYTES) { refused.push({ name, why: WHY.big }); return null; }
  if (!f.size) { refused.push({ name, why: WHY.empty }); return null; }
  const head = new Uint8Array(await f.slice(0, 12).arrayBuffer());
  if (!SNIFF[kind](head)) { refused.push({ name, why: WHY.mismatch }); return null; }
  const shown = named(name, kind);
  return { name: shown, response: new Response(f, { headers: meta('file', shown, kind, f.size) }) };
}

/** One line from the share's title, text and link; a title alone beside files is only their caption. */
function textItem(form, withFiles, refused) {
  const part = (k) => { const v = form.get(k); return typeof v === 'string' ? v.replace(/\s+/g, ' ').trim() : ''; };
  const [title, text, link] = [part('title'), part('text'), part('url')];
  if (!text && !link && (withFiles || !title)) return null;
  const line = [title, text, link].filter(Boolean).join(' ');
  if (line.length > TEXT_MAX) { refused.push({ name: 'Shared text', why: WHY.long }); return null; }
  const body = new Blob([line], { type: 'text/plain;charset=utf-8' });
  return { name: 'Shared text', response: new Response(body, { headers: meta('text', 'Shared text', 'text/plain;charset=utf-8', body.size) }) };
}

const isItem = (req) => new URL(req.url).pathname.startsWith(ITEM);
const newId = () => (self.crypto && self.crypto.randomUUID ? self.crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

/** The items past 24 hours are dropped; how many are left. */
async function sweep(cache) {
  let left = 0;
  for (const req of (await cache.keys()).filter(isItem)) {
    const res = await cache.match(req);
    const at = res ? Number(res.headers.get('X-Jarvis-At')) : NaN;
    if (Date.now() - at >= 0 && Date.now() - at < KEEP_MS) left += 1;
    else await cache.delete(req);
  }
  return left;
}

/** The files and the text line of a form, as items (the files beyond MAX_FILES are one refusal). */
async function itemsOf(form, refused) {
  const all = form.getAll('files').filter((f) => f && typeof f === 'object' && typeof f.size === 'number');
  if (all.length > MAX_FILES) refused.push({ name: '', why: WHY.many });
  const out = [];
  for (const f of all.slice(0, MAX_FILES)) out.push(await fileItem(f, refused));
  out.push(textItem(form, all.length > 0, refused));
  return out.filter(Boolean);
}

/** Puts what fits; every Cache Storage call may fail (no room): then that item is refused, never the answer. */
async function keepAll(cache, incoming, refused) {
  for (const it of incoming) {
    let held = 0;
    try { held = await sweep(cache); } catch (_) { held = 0; }
    if (held >= MAX_ITEMS) { refused.push({ name: it.name, why: WHY.full }); continue; }
    try { await cache.put(new Request(ITEM + newId()), it.response); } catch (_) { refused.push({ name: it.name, why: WHY.room }); }
  }
}

async function finish(refused, to) {
  try {
    const cache = await caches.open(CACHE);
    const note = JSON.stringify({ at: Date.now(), refused: refused.slice(0, 10) });
    await cache.put(new Request(NOTICE), new Response(note, { headers: { 'Content-Type': 'application/json' } }));
  } catch (_) { /* no room for the notice either: the redirect still happens */ }
  return Response.redirect(new URL(to, self.location.origin).href, 303);
}

async function take(req) {
  if (foreign(req)) return finish([{ name: '', why: WHY.origin }], HOME);
  const refused = [];
  let form = null;
  if (await overCap(req)) refused.push({ name: '', why: WHY.body });
  else {
    try { form = await req.formData(); } catch (_) { refused.push({ name: '', why: WHY.unread }); }
  }
  let incoming = [];
  if (form) incoming = await itemsOf(form, refused);
  let cache = null;
  try { cache = await caches.open(CACHE); } catch (_) { cache = null; }
  if (cache) await keepAll(cache, incoming, refused);
  else incoming.forEach((it) => refused.push({ name: it.name, why: WHY.room }));
  return finish(refused, LANDING);
}
