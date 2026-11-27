// src/jarvis/api/static/console-calls-api.js -- R18 E (docs/plans/r18-calls.md sections 4-6; BUILD-BRIEF.md
// "Console <-> cloud"): the Calls screens' ONE place for the server's paths and shapes, and the small builders every
// Calls file shares. Every field the server sends is checked here, once: a field of the wrong type becomes '' / null /
// [] (never a guess), text loses its invisible characters (window.JarvisText, which keeps the joiners Indic scripts
// need), money stays in rupees and a phone number is never shown whole (only its last 4 digits). Nothing here writes
// HTML: textContent only. Transport is the console's own api() (auth, X-Requested-With; 401 -> the gate).
// ASCII source.
const BASE = '/v1/calls'; // I0-SEAMS.md: every JARVIS route is /v1 (the brief's /api/calls/...)
export const PATHS = Object.freeze({
  status: BASE + '/status', // the desk, the phone, today's count, this month's rupees, the call that is on
  cards: BASE + '/cards', // POST (make; the ready cards, Laundry among them, come with the status); /{id}/approve, /cancel
  records: BASE + '/records', // ?limit=N; /{id} (GET, DELETE); /{id}/keep (PUT {keep}); /{id}/audio; /{id}/booking/undo
  settings: BASE + '/settings', // GET; PUT {changed fields} (?confirm=1 when it raises a cap or switches on)
  languages: BASE + '/languages', // GET; /check (POST {confirm: false} -> the estimate, {confirm: true} -> runs)
  live: (id) => BASE + '/' + encodeURIComponent(id) + '/live', // the live WebSocket (owner session)
});
export const ID = /^[A-Za-z0-9_-]{1,64}$/;
export const LANG = /^[a-z]{2,3}-IN$/;
export const LANG_NAMES = Object.freeze({
  'en-IN': 'English', 'hi-IN': 'Hindi', 'bn-IN': 'Bengali', 'mr-IN': 'Marathi', 'te-IN': 'Telugu', 'ta-IN': 'Tamil',
  'gu-IN': 'Gujarati', 'kn-IN': 'Kannada', 'ml-IN': 'Malayalam', 'ur-IN': 'Urdu', 'or-IN': 'Odia', 'pa-IN': 'Punjabi',
  'as-IN': 'Assamese', 'ne-IN': 'Nepali', 'kok-IN': 'Konkani', 'mai-IN': 'Maithili', 'brx-IN': 'Bodo', 'doi-IN': 'Dogri',
  'mni-IN': 'Manipuri', 'sat-IN': 'Santali', 'sa-IN': 'Sanskrit', 'ks-IN': 'Kashmiri', 'sd-IN': 'Sindhi',
});
export const MAX_INDIAN = 3; // a card allows English + up to 3 Indian languages (plan 5.3)
export const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const DIDNT = 'That didn\u2019t work. Please try again.';

// ---- checks ------------------------------------------------------------------------------------------------------
export const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
export const arr = (v) => (Array.isArray(v) ? v : []);
export const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
export const int = (v, lo, hi) => (Number.isInteger(v) && v >= lo && v <= hi ? v : null);
export function txt(v, max = 300) {
  if (typeof v !== 'string') return '';
  const T = window.JarvisText;
  return (T ? T.strip(v) : v).trim().slice(0, max);
}
export const id = (v) => (typeof v === 'string' && ID.test(v) ? v : '');
export const lang = (v) => (typeof v === 'string' && LANG.test(v) ? v : '');
export const langName = (code, given) => txt(given, 40) || LANG_NAMES[code] || code;
export const last4 = (v) => (typeof v === 'string' && /^\d{4}$/.test(v) ? v : '');

// ---- words -------------------------------------------------------------------------------------------------------
/** "+91 90000 00001" (or the server's last 4 digits) -> "\u2022\u2022\u2022\u2022\u2022\u2022 0001": only the last 4 digits. */
export function masked(digits4) {
  const d = last4(digits4);
  return d ? '\u2022\u2022\u2022\u2022\u2022\u2022 ' + d : 'A number';
}
export function lastFourOf(typed) {
  const d = String(typed || '').replace(/\D/g, '');
  return d.length >= 4 ? d.slice(-4) : '';
}
export function rupees(v) { // the deck's own words ("\u2248 \u20b912.40"); \u20b90.00 for nothing spent
  const D = window.JarvisDeck;
  if (D && typeof D.rupees === 'function') return D.rupees(v);
  return typeof v === 'number' && v > 0 ? '\u2248 \u20b9' + v.toFixed(2) : '\u20b90.00';
}
export function wholeRupees(n) {
  const D = window.JarvisDeck;
  if (D && typeof D.wholeRupees === 'function' && Number.isInteger(n)) return D.wholeRupees(n);
  return Number.isInteger(n) ? '\u20b9' + n : '';
}
export function perMinute(v) { // "\u20b90 a minute", "\u2248 \u20b90.43 a minute"
  if (v === null) return '';
  return (v <= 0 ? '\u20b90' : rupees(v)) + ' a minute';
}
export function duration(seconds) { // 102 -> "1:42"; 3700 -> "1:01:40"
  const s = Math.max(0, Math.round(num(seconds) || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, r = String(s % 60).padStart(2, '0');
  return h ? h + ':' + String(m).padStart(2, '0') + ':' + r : m + ':' + r;
}
const WHEN_TIME = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
const TIME = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
/** "12 Nov, 14:05", or "14:05" for today; '' for anything that is not a date. */
export function when(iso) {
  if (!(typeof iso === 'string' && iso.length <= 40)) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return d.toDateString() === new Date().toDateString() ? TIME.format(d) : WHEN_TIME.format(d);
}
export function isToday(iso) {
  const d = typeof iso === 'string' ? new Date(iso) : null;
  return !!d && !isNaN(d) && d.toDateString() === new Date().toDateString();
}

// ---- transport ---------------------------------------------------------------------------------------------------
export const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
export function api(path, opts) {
  const C = window.JarvisConsole;
  if (!C || typeof C.api !== 'function') return Promise.reject(new Error('The console is still starting.'));
  return C.api(path, opts);
}
/** The bytes of a recording (the console's own byte transport); throws plain words. */
export async function bytes(path) {
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function') throw new Error('The console is still starting.');
  const r = await chat.raw(path);
  if (!r.ok) { const e = new Error(r.status === 404 ? 'This recording is no longer kept.' : DIDNT); e.status = r.status; throw e; }
  return r.arrayBuffer();
}
/** Plain words for whatever went wrong: the server's own short sentence, never a code or a stack. */
export function failed(e) {
  if (navigator.onLine === false || (e && e.name === 'TypeError' && typeof e.status !== 'number')) return OFFLINE;
  const m = txt(e && e.message, 300);
  if (e && e.status === 501) return 'Calls are not set up on this JARVIS yet.';
  if (e && e.status === 503 && e.code === 'calls_off') return 'Calls are switched off on this JARVIS.';
  if (e && typeof e.status === 'number' && e.status >= 500) return 'JARVIS couldn\u2019t do that just now. Try again in a moment.';
  return m && !/^[a-z0-9_.-]+$/i.test(m) && !m.startsWith('[object') ? m : DIDNT;
}

// ---- builders (existing classes only) ----------------------------------------------------------------------------
export function mk(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null && text !== '') n.textContent = text;
  return n;
}
export function button(text, cls, fn) {
  const b = mk('button', 'btn lift' + (cls ? ' ' + cls : ''), text);
  b.type = 'button';
  if (fn) b.addEventListener('click', (e) => fn(b, e));
  return b;
}
export function say(el, text, kind) {
  el.className = el.className.replace(/\s*\b(ok|bad|warn)\b/g, '') + (kind ? ' ' + kind : '');
  el.textContent = text || '';
}
let seq = 0;
export const uid = (prefix) => prefix + '-' + (++seq);
/** A label above its control (the Helpers form look). */
export function field(label, control, help) {
  const w = mk('div', 'hp-field cl-field');
  control.id = control.id || uid('clf');
  const l = mk('label', 'bl', label);
  l.htmlFor = control.id;
  w.append(l);
  if (help) {
    const h = mk('small', 'mhelp', help);
    h.id = uid('clh');
    control.setAttribute('aria-describedby', h.id);
    w.append(h);
  }
  w.append(control);
  return w;
}
export function input(type, max, cls) {
  const i = mk(type === 'textarea' ? 'textarea' : 'input', cls || (type === 'textarea' ? 'mta' : 'minput'));
  if (type !== 'textarea') i.type = type;
  if (max) i.maxLength = max;
  i.autocomplete = 'off';
  i.spellcheck = type === 'textarea';
  return i;
}
/** On / Off switch: a button with aria-pressed and the word beside the track (state never in colour alone). */
export function toggle(labelledBy, describedBy, on, fn) {
  const b = mk('button', 'bsw');
  b.type = 'button';
  const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
  const st = mk('span', 'st'); st.setAttribute('aria-hidden', 'true');
  b.append(track, st);
  if (labelledBy) b.setAttribute('aria-labelledby', labelledBy);
  if (describedBy) b.setAttribute('aria-describedby', describedBy);
  const set = (v) => { b.setAttribute('aria-pressed', v ? 'true' : 'false'); st.textContent = v ? 'On' : 'Off'; };
  set(!!on);
  b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') fn(b.getAttribute('aria-pressed') !== 'true', set); });
  return { el: b, set };
}
/** One option row: the label and its small line on the left, the control on the right (Brief / Memory settings). */
export function option(label, small, control) {
  const row = mk('div', 'bopt');
  const t = mk('div', 'btxt');
  const l = mk('span', 'bl', label); l.id = uid('clo');
  t.append(l);
  let sid = '';
  if (small) { const s = mk('small', '', small); s.id = sid = uid('cls'); t.append(s); }
  const c = typeof control === 'function' ? control(l.id, sid) : control;
  row.append(t, c);
  return row;
}
/** A segmented choice (the Appearance menu's .seg): radio inputs, keyboard arrows for free. */
export function choice(name, labelledBy, options, current, fn) {
  const seg = mk('div', 'seg' + (options.length === 2 ? ' two' : ''));
  seg.setAttribute('role', 'radiogroup');
  if (labelledBy) seg.setAttribute('aria-labelledby', labelledBy);
  const n = uid(name);
  options.forEach(([value, words]) => {
    const w = mk('span', 'seg-wrap'), inp = mk('input', 'opt-in'), lab = mk('label', 'seg-opt', words);
    inp.type = 'radio'; inp.name = n; inp.id = n + '-' + value; inp.value = value; inp.checked = value === current;
    lab.htmlFor = inp.id;
    inp.addEventListener('change', () => { if (inp.checked) fn(value); });
    w.append(inp, lab);
    seg.append(w);
  });
  return seg;
}
/** The status chip of the Vitals board: a WORD, the colour only repeats it. */
export function chip(words, status) {
  const c = mk('span', 'vt-chip', words);
  c.dataset.status = status || 'unknown';
  return c;
}
