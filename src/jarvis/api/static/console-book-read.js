// src/jarvis/api/static/console-book-read.js -- R6.4 D1 (docs/plans/r6-4-book-look.md): the full book's own page
// (/book/read, book-read.html), an ES module.
// I0 (the seams) wrote the hand-off: the owner's book token from THIS tab's sessionStorage (the Book panel's "Read the
// full book" puts it there, as for the show), the page's transport window.JarvisBook (the show's shape: api, raw,
// failure, token, captionMs; console-book-voice.js and builder B's player use it), the page's state on
// #bookRead[data-state] (loading | ready | closed), the 60-second beat, Short tour (the show, same token) and Close (the
// session ends, the token is cleared, back to the console). Without a token the page asks nothing and says how to open
// the book; a refused session (401/403/404/410) forgets the token. Builder A adds the reader on top (contents, page,
// search, continue, keyboard) and keeps this contract: window.JarvisBookRead = {state, release, chapters, ready, close}
// and the document event 'jarvis:book-read' ({release}) once the page is ready.
// No build step; CSP script-src 'self'; server text only through textContent; ASCII source; <= 400 lines.
// Builder A (R6.4 D3, D4): once ready, the reader starts (console-book-read-app.js: contents, the page, search, continue,
// keys, the phone's sheet and Play bar); Close asks first, as the show's End does (the console's .bdialog: "Close the
// book?" / Keep reading / Close); JarvisBookRead also gives open(pageId) and page() (the page read: the address's #id).
import { currentPage, openPage, startReader } from './console-book-read-app.js';

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'jarvis_book_token', SESSION_KEY = 'jarvis_book_session', HEADER = 'X-Jarvis-Book';
const BEAT_MS = 60 * 1000, WORD_MS = 330, TAIL_MS = 800, GONE = new Set([401, 403, 404, 410]), OWN = /^\/(?![/\\])/;
const RID = /^[0-9a-f]{7}$/, LABEL = /^R\d{1,3}(?:\.\d{1,2})?$/;
const WORDS = Object.freeze({
  none: 'Open the full book from the Book panel in the console: Open for me, then Read the full book.',
  gone: 'The book session ended. Open the book again from the Book panel in the console.',
  down: 'The full book can\u2019t be reached right now. Try again in a moment.',
});
const ss = {
  get(k) { try { return sessionStorage.getItem(k) || ''; } catch (_) { return ''; } },
  del(k) { try { sessionStorage.removeItem(k); } catch (_) {} },
};
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const captionMs = (text) => (String(text || '').split(/\s+/).filter(Boolean).length * WORD_MS) + TAIL_MS;

// ---- transport: same-origin, X-Requested-With, the console's bearer in token mode, the book token on book routes ----
async function raw(path, opts = {}) {
  if (typeof path !== 'string' || !OWN.test(path)) throw new Error('Not a JARVIS path.');
  const headers = Object.assign({ 'X-Requested-With': 'JARVIS' }, opts.headers || {});
  const bearer = ss.get('jarvis_token'), token = ss.get(TOKEN_KEY);
  if (bearer) headers.Authorization = 'Bearer ' + bearer;
  if (token && path.startsWith('/v1/book/')) headers[HEADER] = token;
  let body = opts.body;
  if (body !== undefined && !(body instanceof ArrayBuffer) && !(body instanceof Blob)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  return fetch(path, { method: opts.method || (body !== undefined ? 'POST' : 'GET'), headers, body, credentials: 'same-origin', cache: 'no-store', signal: opts.signal });
}
async function failure(r) {
  let d = null;
  try { d = obj(await r.json()); } catch (_) {}
  const e = new Error(d && typeof d.detail === 'string' ? d.detail.slice(0, 300) : 'That did not work. Please try again.');
  e.status = r.status; e.code = d && typeof d.error === 'string' ? d.error : ''; e.body = d || {};
  return e;
}
async function api(path, opts) {
  const r = await raw(path, opts);
  if (!r.ok) throw await failure(r);
  return r.status === 204 ? null : r.json();
}

// ---- the page's state ------------------------------------------------------------------------------------------------
const S = { state: 'loading', release: '', label: '', chapters: [], beat: 0 };
function set(state, words) {
  S.state = state;
  const app = $('bookRead');
  if (app) { app.dataset.state = state; app.setAttribute('aria-busy', String(state === 'loading')); }
  const gate = $('brGate');
  if (gate) gate.hidden = state !== 'closed';
  const said = $('brGateText');
  if (said && words) said.textContent = words;
}
function forget() { ss.del(TOKEN_KEY); ss.del(SESSION_KEY); clearInterval(S.beat); }
function refused(e) {
  if (e && GONE.has(e.status)) { forget(); set('closed', WORDS.gone); return; }
  set('closed', WORDS.down);
}
async function beat() {
  if (document.hidden || S.state !== 'ready') return;
  try { await api('/v1/book/show/beat', { method: 'POST' }); } catch (e) { if (e && GONE.has(e.status)) refused(e); }
}
async function boot() {
  if (!ss.get(TOKEN_KEY)) { set('closed', WORDS.none); return false; }
  try {
    const got = obj(await api('/v1/book/chapters')) || {};
    S.release = RID.test(got.release || '') ? got.release : '';
    S.label = LABEL.test(got.label || '') ? got.label : ''; // I1: the release chip's "R6.4"
    S.chapters = Array.isArray(got.chapters) ? got.chapters.filter(obj) : [];
  } catch (e) { refused(e); return false; }
  const chip = $('brRelease');
  if (chip) chip.textContent = S.release;
  set('ready');
  S.beat = setInterval(beat, BEAT_MS);
  document.dispatchEvent(new CustomEvent('jarvis:book-read', { detail: { release: S.release } }));
  return true;
}

/** Close: the session ends (its conversation, if the show had one, is deleted), the token goes, back to the console. */
async function close() {
  const had = ss.get(TOKEN_KEY);
  clearInterval(S.beat);
  if (had) { try { await api('/v1/book/close', { method: 'POST' }); } catch (_) { /* it ends by itself when idle */ } }
  forget();
  window.location.assign('/');
}
/** Short tour: the show in this tab, with the same session (the token stays where it is). */
function tour() {
  if (!ss.get(TOKEN_KEY)) return;
  clearInterval(S.beat);
  window.location.assign('/book/show');
}

/** Close asks first (the console's confirm dialog, as the show's End): Keep reading is the safe default. */
function confirmClose() {
  let d = $('brConfirm');
  if (!d) {
    d = document.createElement('dialog');
    d.id = 'brConfirm'; d.className = 'bdialog'; d.setAttribute('role', 'alertdialog');
    d.setAttribute('aria-labelledby', 'brConfirmTitle'); d.setAttribute('aria-describedby', 'brConfirmText');
    const h = document.createElement('h2'), p = document.createElement('p'), row = document.createElement('div');
    h.id = 'brConfirmTitle'; h.textContent = 'Close the book?';
    p.id = 'brConfirmText'; p.textContent = 'The book session ends here. Your place is kept in this browser, so Continue picks up where you left off.';
    row.className = 'actions';
    [['brKeep', 'Keep reading', 'btn lift', 'keep'], ['brCloseNow', 'Close', 'btn lift primary', 'close']].forEach(([id, words, cls, value]) => {
      const b = document.createElement('button');
      b.id = id; b.type = 'button'; b.className = cls; b.textContent = words;
      b.addEventListener('click', () => d.close(value));
      row.append(b);
    });
    d.append(h, p, row);
    d.addEventListener('close', () => { if (d.returnValue === 'close') close(); else if (closeBtn) closeBtn.focus(); });
    $('bookRead').append(d);
  }
  if (d.open) return;
  d.returnValue = '';
  try { d.showModal(); } catch (_) { d.setAttribute('open', ''); }
  $('brKeep').focus();
}
/** A refused session (the reader's own calls): back to the closed page, the token forgotten. */
function gone(e) { refused(e); return true; }

const ready = boot();
const closeBtn = $('brClose'), tourBtn = $('brTour');
if (closeBtn) closeBtn.addEventListener('click', confirmClose);
if (tourBtn) tourBtn.addEventListener('click', tour);
ready.then((ok) => (ok ? startReader({ api, release: S.release, label: S.label, chapters: S.chapters.slice(), gone }) : false)).catch(() => {
  const note = $('brNote');
  if (note) note.textContent = WORDS.down;
});
window.JarvisBook = Object.freeze({ api, raw, failure, captionMs, token: () => ss.get(TOKEN_KEY), mode: () => '' });
window.JarvisBookRead = Object.freeze({
  state: () => S.state, release: () => S.release, chapters: () => S.chapters.slice(), ready: () => ready, close,
  open: (pageId) => openPage(pageId), page: () => currentPage(),
});
export { api, close, ready };
