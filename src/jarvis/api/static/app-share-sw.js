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
const TYPES = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf' };
const BY_EXT = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.pdf': 'application/pdf' };
const WHY = {
  kind: 'JARVIS takes photos (JPEG, PNG or WebP), PDFs and text only.',
  big: 'It is over 10 MB, the most JARVIS takes.',
  empty: 'It is empty.',
  full: 'The tray holds 5 items at most. Discard one there, then share this again.',
  long: 'The text is longer than 2,000 characters.',
  unread: 'That share could not be read. Please try again.',
};

self.addEventListener('install', () => { self.skipWaiting(); });

self.addEventListener('fetch', (event) => {
  const req = event.request;
  let url = null;
  try { url = new URL(req.url); } catch (_) { return; }
  if (req.method !== 'POST' || url.origin !== self.location.origin || url.pathname !== '/app/share/in') return;
  event.respondWith(take(req));
});

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

function fileItem(f, refused) {
  const name = cleanName(f.name);
  const kind = kindOf(f.type, name);
  if (!kind) { refused.push({ name, why: WHY.kind }); return null; }
  if (f.size > MAX_BYTES) { refused.push({ name, why: WHY.big }); return null; }
  if (!f.size) { refused.push({ name, why: WHY.empty }); return null; }
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

/** Drops the items past 24 hours; how many are left. */
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

async function take(req) {
  const refused = [];
  let form = null;
  try { form = await req.formData(); } catch (_) { refused.push({ name: '', why: WHY.unread }); }
  const cache = await caches.open(CACHE);
  let held = await sweep(cache);
  const incoming = [];
  if (form) {
    const files = form.getAll('files').filter((f) => f && typeof f === 'object' && typeof f.size === 'number');
    files.forEach((f) => incoming.push(fileItem(f, refused)));
    incoming.push(textItem(form, files.length > 0, refused));
  }
  for (const it of incoming) {
    if (!it) continue;
    if (held >= MAX_ITEMS) { refused.push({ name: it.name, why: WHY.full }); continue; }
    await cache.put(new Request(ITEM + newId()), it.response);
    held += 1;
  }
  const note = JSON.stringify({ at: Date.now(), refused: refused.slice(0, 10) });
  await cache.put(new Request(NOTICE), new Response(note, { headers: { 'Content-Type': 'application/json' } }));
  return Response.redirect(new URL(LANDING, self.location.origin).href, 303);
}
