// src/jarvis/api/static/console-r7-share.js -- R7 Part A (docs/plans/r7-mobile.md D12, D15): the share tray. What
// was shared into JARVIS from another app waits in THIS browser (app-share-sw.js keeps it in Cache Storage) until
// the owner presses a button here, per item:
//   a photo   Look at it here (the Camera panel: JarvisMobile.parts.panel.look(file), on this device only)
//             Ask the AI about it (about Rs 0.30)   offered only when the brain answering now sees pictures;
//                                                   otherwise it reads "The brain answering now can't see pictures."
//             Add to my vault   Attach to my message   Discard
//   a PDF     Add to my vault   Attach to my message   Discard
//   text      Put it in my message (the composer; nothing is sent until Send)   Discard
// Ask, Vault and Attach go through I0's ONE picture door (JarvisMobile.parts.send: it redraws a photo, a WebP too,
// as a JPEG of at most 1,568 px first and counts "Pictures sent from this device today"); this file builds no Ask,
// Vault, Attach or counter of its own. Refusals the worker wrote (a sixth item, over 10 MB, a kind JARVIS does not
// take) are shown once, in plain words. Items older than 24 hours are dropped.
// Signed out it asks the server NOTHING and keeps every item: the tray opens, and the worker is registered
// (GET /app/status, then /app/share/sw.js), only after jarvis:ready. It opens by itself when items are waiting,
// and on ?do=shared (console-r7-links.js calls open()). Loaded by console-r7.js (an ES module); built with
// window.JarvisMobile and the console's existing classes (.sheet, .integ, .btn, .bnote, .bfine); textContent only;
// ASCII source.
const M = window.JarvisMobile;
const CACHE = 'jarvis-share-v1';
const ITEM = '/app/share/item/';
const NOTICE = '/app/share/notice';
const SCOPE = '/app/share/';
const KEEP_MS = 24 * 60 * 60 * 1000;
const ASK_TEXT = 'What can you tell me about this picture?';
const WORDS = {
  title: 'Shared with JARVIS',
  lead: 'These wait on this phone until you choose. Nothing has been sent.',
  none: 'Nothing shared is waiting.',
  look: 'Look at it here', ask: 'Ask the AI about it (about \u20b90.30)', vault: 'Add to my vault',
  attach: 'Attach to my message', put: 'Put it in my message', discard: 'Discard', close: 'Close',
  noLook: 'The Camera screen can\u2019t look at a shared picture yet.',
  notReady: 'JARVIS is still starting. Try again in a moment.',
  notSent: 'It wasn\u2019t sent. Try again in a moment.',
  gone: 'That item is no longer on this phone.',
  vaulted: 'Added to your vault for you to check.',
};
const KIND_WORD = { 'image/jpeg': 'Photo', 'image/png': 'Photo', 'image/webp': 'Photo', 'application/pdf': 'PDF' };

const mk = (tag, cls, text) => M.mk(tag, cls, text);
const $ = (id) => document.getElementById(id);
const signedIn = () => { const c = window.JarvisConsole; return !!(c && typeof c.ready === 'function' && c.ready()); };
const door = () => (M && M.parts && M.parts.send && typeof M.parts.send.attach === 'function' ? M.parts.send : null);
const say = (e, fallback) => (e && typeof e.message === 'string' && e.message.length <= 300 ? e.message : fallback);
function sizeText(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function decodeName(raw) { try { return decodeURIComponent(raw || '').slice(0, 120) || 'shared'; } catch (_) { return 'shared'; } }

// ---- this browser's tray (never the server) ----------------------------------------------------------------------
async function tray() { return 'caches' in window ? caches.open(CACHE) : null; }

/** The items waiting, oldest first; past 24 hours they are dropped. */
async function items() {
  const cache = await tray();
  if (!cache) return [];
  const out = [];
  for (const req of await cache.keys()) {
    const path = new URL(req.url).pathname;
    if (!path.startsWith(ITEM)) continue;
    const res = await cache.match(req);
    const at = res ? Number(res.headers.get('X-Jarvis-At')) : NaN;
    if (!(Date.now() - at >= 0 && Date.now() - at < KEEP_MS)) { await cache.delete(req); continue; }
    const text = res.headers.get('X-Jarvis-Kind') === 'text';
    const type = text ? 'text/plain' : String(res.headers.get('Content-Type') || '').split(';')[0];
    out.push({ req, at, text, type, name: decodeName(res.headers.get('X-Jarvis-Name')), size: Number(res.headers.get('X-Jarvis-Size')) || 0 });
  }
  return out.sort((a, b) => a.at - b.at);
}
/** What the worker refused at the last share, shown once. */
async function takeNotice() {
  const cache = await tray();
  const res = cache ? await cache.match(NOTICE) : null;
  if (!res) return [];
  await cache.delete(NOTICE);
  let j = null;
  try { j = await res.json(); } catch (_) { return []; }
  return Array.isArray(j && j.refused) ? j.refused.slice(0, 10) : [];
}
async function fileOf(it) {
  const cache = await tray(), res = cache ? await cache.match(it.req) : null;
  if (!res) throw new Error(WORDS.gone);
  const blob = await res.blob();
  return new File([blob], it.name, { type: it.type });
}
async function drop(it) { const cache = await tray(); if (cache) await cache.delete(it.req); }

// ---- the sheet ---------------------------------------------------------------------------------------------------
let sheet = null, list = null, note = null, sent = null, wanted = false;
function build() {
  if (sheet) return sheet;
  sheet = mk('dialog', 'sheet r7s');
  sheet.id = 'shareTray';
  sheet.setAttribute('aria-labelledby', 'shareTrayTitle');
  const inner = mk('div', 'sheet-in');
  const h = mk('h2', '', WORDS.title); h.id = 'shareTrayTitle';
  const lead = mk('p', 'bfine r7s-lead', WORDS.lead);
  note = mk('div', 'bnote r7s-note'); note.id = 'shareTrayNote'; note.setAttribute('role', 'status');
  list = mk('div', 'r7s-list'); list.id = 'shareTrayList'; list.setAttribute('role', 'list');
  sent = mk('p', 'bfine r7s-sent'); sent.id = 'shareTraySent';
  const close = mk('button', 'btn lift sheet-close', WORDS.close); close.type = 'button'; close.id = 'shareTrayClose';
  close.addEventListener('click', () => sheet.close());
  inner.append(h, lead, note, list, sent, close);
  sheet.append(inner);
  document.body.append(sheet);
  return sheet;
}
function tell(lines, bad) {
  if (!note) return;
  note.textContent = lines.filter(Boolean).join(' ');
  note.classList.toggle('bad', !!bad);
}
function countLine() { const d = door(); if (sent) sent.textContent = d && typeof d.line === 'function' ? d.line() : ''; }

function button(label, run, why) {
  const b = mk('button', why ? 'btn lift r7s-wide' : 'btn lift', label);
  b.type = 'button';
  if (why) { b.disabled = true; b.title = why; } else b.addEventListener('click', run);
  return b;
}
/** One press at a time per item: its buttons wait while it runs; whatever it says goes in the note. */
function pressing(card, job) {
  return async () => {
    const all = [...card.querySelectorAll('button')];
    all.forEach((b) => { b.disabled = true; });
    try { await job(); } catch (e) { tell([say(e, WORDS.notSent)], true); all.forEach((b) => { if (!b.title) b.disabled = false; }); }
  };
}
function card(it) {
  const c = mk('div', 'integ r7s-item');
  c.setAttribute('role', 'listitem');
  const head = mk('div', 'ihead');
  head.append(mk('b', 'r7s-name', it.name), mk('span', 'istate', `${it.text ? 'Text' : KIND_WORD[it.type] || 'File'} \u00b7 ${sizeText(it.size)}`));
  const acts = mk('div', 'actions r7s-acts');
  const picture = /^image\//.test(it.type);
  if (it.text) acts.append(button(WORDS.put, pressing(c, () => put(it))));
  if (picture) acts.append(button(WORDS.look, pressing(c, () => look(it))));
  if (picture) {
    const d = door(), can = d && typeof d.canAsk === 'function' ? d.canAsk() : { ok: false, why: WORDS.notReady };
    acts.append(can.ok ? button(WORDS.ask, pressing(c, () => ask(it))) : button(can.why, null, can.why));
  }
  if (!it.text) acts.append(button(WORDS.vault, pressing(c, () => vault(it))), button(WORDS.attach, pressing(c, () => attach(it))));
  acts.append(button(WORDS.discard, pressing(c, async () => { await drop(it); await render(); })));
  c.append(head, acts);
  return c;
}
async function render() {
  build();
  const all = await items();
  list.replaceChildren(...all.map(card));
  if (!all.length) list.append(mk('p', 'bfine', WORDS.none));
  countLine();
  return all.length;
}

// ---- the presses (the only places anything leaves this phone) ---------------------------------------------------
const need = () => { const d = door(); if (!d) throw new Error(WORDS.notReady); return d; };
const done = async (it) => { await drop(it); sheet.close(); };
async function look(it) {
  const P = M.parts.panel, D = window.JarvisDeck;
  if (!P || typeof P.look !== 'function') throw new Error(WORDS.noLook);
  const file = await fileOf(it);
  sheet.close();
  if (D) D.open('camera', { focus: true });
  await P.look(file); // on this device: the vision engine sees it, the server never does
}
async function ask(it) {
  const d = need(), file = await fileOf(it);
  if (!(await d.ask(file, ASK_TEXT))) throw new Error(WORDS.notSent);
  await done(it);
}
async function vault(it) {
  const d = need(), file = await fileOf(it);
  await d.vault(file); // the usual proposal for him to confirm; the door opens the Vault panel
  await done(it);
  tell([WORDS.vaulted], false);
}
async function attach(it) {
  const d = need(), file = await fileOf(it);
  if (!(await d.attach([file]))) throw new Error(WORDS.notSent);
  await done(it);
  const D = window.JarvisDeck; if (D) D.open('chat', { focus: false });
  const input = $('input'); if (input) input.focus();
}
async function put(it) {
  const input = $('input'), file = await fileOf(it);
  if (!input) throw new Error(WORDS.notReady);
  const words = (await file.text()).slice(0, 2000);
  input.value = input.value.trim() ? `${input.value.trimEnd()} ${words}` : words;
  input.dispatchEvent(new Event('input', { bubbles: true })); // the composer grows and Send wakes up
  await done(it);
  const D = window.JarvisDeck; if (D) D.open('chat', { focus: false });
  input.focus();
}

// ---- opening, and the worker -------------------------------------------------------------------------------------
let opening = null;
/** Opens the tray (one opening at a time: the launch word and "items are waiting" may both ask). */
function open() {
  if (!signedIn()) { wanted = true; return Promise.resolve(0); } // signed out: nothing shown, nothing asked
  wanted = false;
  if (!opening) opening = show().finally(() => { opening = null; });
  return opening;
}
async function show() {
  build();
  const refused = await takeNotice();
  const n = await render();
  tell(refused.map((r) => (r.name ? `Not kept: ${r.name}. ${r.why}` : String(r.why || ''))), refused.length > 0);
  if (!sheet.open) sheet.showModal();
  const first = list.querySelector('button:not(:disabled)') || $('shareTrayClose');
  if (first) first.focus();
  return n;
}
async function worker() {
  if (!('serviceWorker' in navigator)) return;
  let share = false;
  try { share = (await M.api('/app/status')).share === true; } catch (_) { return; }
  try {
    if (share) { await navigator.serviceWorker.register('/app/share/sw.js', { scope: SCOPE }); return; }
    const reg = await navigator.serviceWorker.getRegistration(SCOPE);
    if (reg && new URL(reg.scope).pathname === SCOPE) await reg.unregister();
  } catch (_) {}
}
async function ready() {
  worker();
  const waiting = (await items()).length;
  if (wanted || waiting) open();
}

document.addEventListener('jarvis:ready', () => { ready(); });
document.addEventListener('jarvis:pictures-sent', countLine);
if (signedIn()) ready();

if (M) M.part('share', Object.freeze({ open, items: async () => (await items()).map(({ name, type, size, text }) => ({ name, type, size, text })) }));
