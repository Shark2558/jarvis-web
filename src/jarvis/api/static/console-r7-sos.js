// src/jarvis/api/static/console-r7-sos.js -- R7 Part D (docs/plans/r7-mobile.md D19, D20, D21): the SOS sheet and
// Integrations -> Emergency SOS. Loaded by console-r7.js (an ES module); window.JarvisMobile (mk, api, part) and the
// console's existing classes (.bdialog, .integ, .btn, .minput, .sacts, .snote, .inote); textContent only; ASCII source.
// * The sheet: a 2-second HOLD, then a 5-second countdown with a full-width Cancel (a cancelled countdown sends
//   NOTHING: no request at all); the place is asked for when the sheet opens (10 s at most) and travels only in the
//   POST body. The answer is shown per contact, honestly ("sent", "sent, the map pin failed", "NOT sent", "SMS
//   only"), and the SMS screen (every number, the message filled in) and the 112 button are ALWAYS offered, after a
//   refusal or a failure too, and with no internet (from the numbers the sheet read when it opened).
// * A failed SOS always leaves the SMS screen and 112: the numbers the sheet loaded are kept and used when an answer
//   has none; a send that gets no answer in 20 seconds says so ("it may have gone") and offers both; every error
//   answer's plain words are shown (never "[object Object]"). One press id per hold: a repeated request is one send.
// * While the app is locked only a real SOS is offered (no test, no "I'm safe"), the answer names no contact and the
//   numbers live only inside the SMS link.
// * The card: his name for the message, up to 5 contacts (label, phone for the SMS screen), a one-time join link per
//   contact (he sends it himself; it works once, 24 hours), Remove, the last SOS, what is left this hour.
// * Voice: "open SOS" (sos.open, R7_PHRASES) only OPENS the sheet; it never holds, counts down or sends.
// * It asks the server NOTHING before sign-in: the sheet then shows 112 only; the card waits for jarvis:ready.
// API: GET /v1/sos, GET /v1/sos/sheet, PUT /v1/sos/label, POST /v1/sos/contacts, DELETE /v1/sos/contacts/{id},
//   POST /v1/sos/contacts/{id}/link, POST /v1/sos/send {kind, location?} (see api/sos.py).
// Published: window.JarvisMobile.parts.sos = {open(), close(), isOpen()} (Part A's do=sos calls open()).
const M = window.JarvisMobile;
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const NOT_A_SERVICE = 'This is not an emergency service: in danger, call 112. Set up Android\u2019s own Emergency SOS too (press the power button five times, Android 12 and newer).';
const VOICE = ['open sos', 'emergency sos', 'open emergency sos', 'open the sos screen', 'show the sos screen'];
const STATUS = { sent: 'sent on Telegram', sent_no_pin: 'sent on Telegram, but the map pin failed', failed: 'NOT sent: Telegram did not take it', not_joined: 'not on Telegram: use the SMS screen' };
const TITLE = { real: 'SOS', test: 'Test SOS', safe: '\u201cI\u2019m safe\u201d' };
const ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-';
const SEND_MS = 20000;
const LINK_MS = 10 * 60 * 1000;
const WARN = 'Your contacts couldn\u2019t be loaded just now, Sir. If you need help, call 112 or use your phone\u2019s own SMS.';
const CID = /^c_[0-9a-f]{10}$/;
const PHONE = /^\+?[0-9]{6,15}$/;
const LINK = /^https:\/\/t\.me\/[A-Za-z0-9_]{4,64}\?start=sos-[A-Za-z0-9_-]{22,60}$/;
const S = { sheet: null, phase: 'idle', kind: 'real', hold: 0, tick: 0, left: 0, place: null, card: null, view: null, busy: false, pointer: null, key: false, press: '', linkTimer: 0, lastLink: null };
const UI = {};

const mk = (tag, cls, text) => (M ? M.mk(tag, cls, text) : document.createElement(tag));
const api = (path, opts) => M.api(path, opts);
const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
const int = (v, lo, hi) => (Number.isInteger(v) && v >= lo && v <= hi ? v : null);
function button(label, cls, onClick) {
  const b = mk('button', cls || 'btn', label);
  b.type = 'button';
  if (onClick) b.addEventListener('click', onClick);
  return b;
}
function link(label, href, cls) {
  const a = mk('a', cls || 'btn sos-link', label);
  a.href = href;
  return a;
}
// Only the server's own plain sentences reach the owner (they end with "Call 112"); a status text such as "Bad
// Gateway" or a code-like word never does.
const WORDED = ['sos_off', 'invalid', 'busy', 'device_locked', 'failed'];
const NOT_SENT = 'NOT sent through JARVIS. Use the SMS screen or call 112.';
const worded = (e) => {
  const m = e && WORDED.includes(e.code) ? txt(e.message, 300) : '';
  return m && m.indexOf('[object') < 0 ? m : '';
};
const errWords = (e, fallback) => {
  if (e && e.name === 'TypeError') return OFFLINE;
  return worded(e) || fallback;
};
/** The failed press, in words: the server's own sentence alone, or the fixed line (no sentence twice). */
const notSent = (e) => {
  if (e && e.name === 'TypeError') return 'NOT sent through JARVIS: ' + OFFLINE + ' Use the SMS screen or call 112.';
  return worded(e) || NOT_SENT;
};
function newPress() {
  const a = new Uint8Array(18);
  if (window.crypto && typeof window.crypto.getRandomValues === 'function') window.crypto.getRandomValues(a);
  else for (let i = 0; i < a.length; i += 1) a[i] = Math.floor(Math.random() * 256);
  return Array.from(a, (b) => ALPHA[b & 63]).join('');
}
const lockedNow = () => !!(S.sheet && S.sheet.locked === true);

// ---- the sheet --------------------------------------------------------------------------------------------------
function buildSheet() {
  if (UI.dlg) return UI.dlg;
  const d = mk('dialog', 'bdialog sos-sheet');
  d.id = 'sosSheet';
  d.setAttribute('aria-labelledby', 'sosTitle');
  const h = mk('h2', '', 'Emergency SOS'); h.id = 'sosTitle';
  UI.say = mk('p', 'strong sos-say'); UI.say.setAttribute('role', 'status'); UI.say.setAttribute('aria-live', 'assertive');
  UI.warn = mk('p', 'strong sos-warn'); UI.warn.setAttribute('role', 'alert'); UI.warn.hidden = true;
  UI.place = mk('p', 'sos-place');
  UI.hold = button('Hold for SOS', 'btn danger sos-hold');
  UI.test = button('Hold to send a test', 'btn sos-test');
  UI.safe = button('I\u2019m safe', 'btn sos-safe');
  UI.cancel = button('Cancel', 'btn primary sos-cancel', () => cancel());
  UI.cancel.hidden = true;
  UI.result = mk('div', 'sos-result');
  UI.links = mk('div', 'sacts sos-links');
  const close = button('Close', 'btn sos-close', () => closeSheet());
  const note = mk('p', 'fine', NOT_A_SERVICE);
  const acts = mk('div', 'sacts sos-acts');
  acts.append(UI.hold, UI.test, UI.safe);
  d.append(h, UI.say, UI.warn, UI.place, acts, UI.cancel, UI.result, UI.links, note, close);
  holdable(UI.hold, 'real');
  holdable(UI.test, 'test');
  holdable(UI.safe, 'safe');
  d.addEventListener('cancel', (e) => { e.preventDefault(); closeSheet(); });
  document.body.append(d);
  UI.dlg = d;
  return d;
}
function holdable(btn, kind) {
  btn.addEventListener('pointerdown', (e) => {
    // only the primary button of one pointer starts a hold (left click, one finger); a right click, a second finger or
    // a key held at the same time never does
    if (e.button !== 0 || e.isPrimary === false || S.pointer !== null || S.key) return;
    e.preventDefault();
    if (!begin(kind)) return;
    S.pointer = e.pointerId;
    // the finger or the mouse stays this button's until it lets go (a line of text changing above it must not
    // count as letting go)
    try { btn.setPointerCapture(e.pointerId); } catch (_) { /* an old browser: the plain hold */ }
  });
  const up = (e) => { if (e.pointerId !== S.pointer) return; S.pointer = null; letGo(); };
  ['pointerup', 'pointerleave', 'pointercancel'].forEach((n) => btn.addEventListener(n, up));
  btn.addEventListener('keydown', (e) => {
    if ((e.key !== ' ' && e.key !== 'Enter') || e.repeat) return;
    e.preventDefault();
    if (S.pointer === null && begin(kind)) S.key = true;
  });
  btn.addEventListener('keyup', (e) => { if ((e.key === ' ' || e.key === 'Enter') && S.key) { S.key = false; letGo(); } });
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
}
// a window that loses focus or goes to the background ends a hold (the finger may be gone: nothing is then sent)
window.addEventListener('blur', () => letGo());
document.addEventListener('visibilitychange', () => { if (document.hidden) letGo(); });
const holdS = () => int(S.sheet && S.sheet.hold_s, 1, 10) || 2;
const countS = () => int(S.sheet && S.sheet.countdown_s, 3, 30) || 5;
function say(text) { if (UI.say) UI.say.textContent = text; }
function idle(text) {
  S.phase = 'idle'; S.pointer = null; S.key = false;
  const can = signedIn();
  [UI.hold, UI.test, UI.safe].forEach((b) => { b.hidden = false; b.disabled = !can; });
  if (lockedNow()) { UI.test.hidden = true; UI.safe.hidden = true; } // locked: a real SOS only
  UI.cancel.hidden = true;
  say(text || (can ? 'Hold the red button for ' + holdS() + ' seconds. You can still cancel after that.' : 'Sign in to send an SOS through JARVIS. In danger, call 112 now.'));
}
function begin(kind) {
  if (S.phase !== 'idle' || !signedIn()) return false;
  S.phase = 'holding'; S.kind = kind; S.press = newPress(); // one id for this hold: a repeat is one send
  say('Keep holding\u2026');
  S.hold = setTimeout(() => countdown(kind), holdS() * 1000);
  return true;
}
function letGo() {
  if (S.phase !== 'holding') return;
  clearTimeout(S.hold);
  idle('Let go too early: nothing was sent. Hold for ' + holdS() + ' seconds.');
}
function countdown(kind) {
  S.phase = 'counting';
  S.left = countS();
  [UI.hold, UI.test, UI.safe].forEach((b) => { b.hidden = true; });
  UI.cancel.hidden = false;
  UI.cancel.focus({ preventScroll: true });
  if (!S.sheet || S.sheet.unreadable === true) loadSheet(false); // read the contacts again before the press goes
  const show = () => say('Sending ' + TITLE[kind] + ' in ' + S.left + '\u2026 Press Cancel to stop.');
  show();
  S.tick = setInterval(() => {
    S.left -= 1;
    if (S.left > 0) { show(); return; }
    clearInterval(S.tick);
    send(kind);
  }, 1000);
}
function cancel() {
  if (S.phase !== 'counting' && S.phase !== 'holding') return;
  clearTimeout(S.hold); clearInterval(S.tick);
  idle('Cancelled. Nothing was sent.');
  UI.hold.focus({ preventScroll: true }); // the Cancel button that had focus is hidden now
}
function where() {
  S.place = null;
  if (!UI.place) return;
  if (!navigator.geolocation || typeof navigator.geolocation.getCurrentPosition !== 'function') { UI.place.textContent = 'Location: not available on this device.'; return; }
  UI.place.textContent = 'Location: finding it\u2026';
  navigator.geolocation.getCurrentPosition((pos) => {
    const c = pos && pos.coords;
    if (!c || !Number.isFinite(c.latitude) || !Number.isFinite(c.longitude)) { UI.place.textContent = 'Location: not available.'; return; }
    const lat = Math.round(c.latitude * 1e6), lon = Math.round(c.longitude * 1e6);
    if (Math.abs(lat) > 90e6 || Math.abs(lon) > 180e6) { UI.place.textContent = 'Location: not available.'; return; }
    const acc = Math.min(100000, Math.max(0, Math.round(c.accuracy || 0)));
    S.place = { lat_e6: lat, lon_e6: lon, accuracy_m: acc, taken: Number(pos.timestamp) || Date.now() };
    UI.place.textContent = 'Location: ready (within about ' + (acc >= 1000 ? Math.round(acc / 1000) + ' km' : acc + ' m') + ').';
  }, () => { UI.place.textContent = 'Location: not available. The message will say so.'; }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
}
function placeBody() {
  const p = S.place;
  if (!p) return null;
  const age = Math.min(86400, Math.max(0, Math.round((Date.now() - p.taken) / 1000)));
  return { lat_e6: p.lat_e6, lon_e6: p.lon_e6, accuracy_m: p.accuracy_m, age_s: age };
}
const sendMs = () => int(M && M.sosTimeoutMs, 200, 60000) || SEND_MS;
function late() {
  const e = new Error('JARVIS did not answer in time, so it is not known whether the SOS went. It may have.');
  e.timeout = true;
  return e;
}
async function send(kind) {
  S.phase = 'sending';
  UI.cancel.hidden = true;
  say('Sending\u2026');
  const body = { kind, press_id: S.press, location: kind === 'safe' ? null : placeBody() };
  let res = null, err = null, timer = 0;
  try {
    res = await Promise.race([
      api('/v1/sos/send', { method: 'POST', body }),
      new Promise((_, no) => { timer = setTimeout(() => no(late()), sendMs()); }),
    ]);
  } catch (e) { err = e; } finally { clearTimeout(timer); }
  shown(kind, res, err);
}
function numbers(res) {
  const own = res && res.sms && Array.isArray(res.sms.numbers) ? res.sms.numbers : [];
  const kept = S.sheet && Array.isArray(S.sheet.numbers) ? S.sheet.numbers : [];
  // an answer with no numbers (the store was down) never wins over the numbers the sheet loaded
  return (own.length ? own : kept).filter((n) => typeof n === 'string' && PHONE.test(n)).slice(0, 5);
}
function smsText(res) {
  const t = res && res.sms ? txt(res.sms.text, 600) : '';
  return t || txt(S.sheet && S.sheet.text, 600);
}
function offer(res) {
  const nums = numbers(res);
  const acts = [];
  if (nums.length) acts.push(link('Open SMS to ' + (nums.length === 1 ? '1 contact' : nums.length + ' contacts'), 'sms:' + nums.join(',') + '?body=' + encodeURIComponent(smsText(res)), 'btn primary sos-link'));
  if (nums.length && !lockedNow()) acts.push(link('Call your first contact', 'tel:' + nums[0]));
  acts.push(link('Call 112', 'tel:112', 'btn danger sos-link'));
  UI.links.replaceChildren(...acts);
}
function shown(kind, res, err) {
  S.phase = 'done';
  const rows = [];
  if (err && err.timeout === true) {
    rows.push(mk('p', 'strong', 'UNKNOWN: ' + errWords(err, 'JARVIS did not answer.') + ' Use the SMS screen and call 112 now.'));
  } else if (err || !res || typeof res !== 'object') {
    rows.push(mk('p', 'strong', notSent(err)));
  } else {
    rows.push(mk('p', 'strong', txt(res.words, 300) || (res.sent === true ? 'Sent.' : 'NOT sent. Use the SMS screen or call 112.')));
    (Array.isArray(res.results) ? res.results : []).slice(0, 5).forEach((r) => {
      const label = txt(r && r.label, 40), st = STATUS[r && r.status];
      if (label && st) rows.push(mk('p', 'sos-row', label + ': ' + st));
    });
    if (res.told === false) rows.push(mk('p', 'sos-row', 'I couldn\u2019t confirm that your other devices were alerted, Sir.'));
  }
  UI.result.replaceChildren(...rows);
  offer(res);
  idle(kind === 'real' && res && res.sent === true ? 'When you are safe, press \u201cI\u2019m safe\u201d to tell the same people.' : '');
  if (S.card) refreshCard();
}
async function loadSheet(first) {
  try { S.sheet = await api('/v1/sos/sheet'); } catch (e) {
    if (first && S.phase === 'idle') say(errWords(e, 'Couldn\u2019t load your SOS set-up.') + ' You can still hold the button, or call 112.');
    return; // the numbers an earlier read kept stay
  }
  const sh = S.sheet || {};
  UI.warn.textContent = sh.unreadable === true ? (txt(sh.warning, 300) || WARN) : '';
  UI.warn.hidden = !UI.warn.textContent;
  if (sh.enabled === false) say('Emergency SOS is switched off on this server. In danger, call 112 now.');
  if (S.phase !== 'done') offer(null);
  if (S.phase === 'idle' && sh.enabled !== false) idle();
}
async function openSheet() {
  const d = buildSheet();
  clearTimeout(S.hold); clearInterval(S.tick);
  forgetLink();
  UI.result.replaceChildren(); UI.links.replaceChildren(link('Call 112', 'tel:112', 'btn danger sos-link'));
  UI.warn.hidden = true;
  idle();
  if (typeof d.showModal === 'function' && !d.open) d.showModal(); else d.setAttribute('open', '');
  if (!signedIn()) { UI.place.textContent = ''; return; }
  where();
  await loadSheet(true);
}
function closeSheet() {
  clearTimeout(S.hold); clearInterval(S.tick);
  forgetLink();
  if (S.phase === 'counting' || S.phase === 'holding') S.phase = 'idle';
  S.place = null;
  if (UI.dlg && UI.dlg.open) UI.dlg.close();
}

// ---- Integrations -> Emergency SOS ------------------------------------------------------------------------------
function cardNote(kind, text) {
  if (!UI.cnote) return;
  UI.cnote.className = 'inote' + (kind === 'bad' ? ' bad' : '');
  UI.cnote.textContent = text || '';
  UI.cnote.hidden = !text;
}
function buildCard() {
  if (S.card) return true;
  const host = document.getElementById('integrations');
  if (!host || !host.parentNode) return false;
  const card = mk('section', 'integ sos-card'); card.id = 'sosCard'; card.dataset.state = 'loading';
  card.setAttribute('aria-labelledby', 'sosHead');
  const head = mk('div', 'ihead');
  const title = mk('b', '', 'Emergency SOS'); title.id = 'sosHead';
  UI.cstate = mk('span', 'istate', 'Checking\u2026');
  head.append(title, UI.cstate);
  UI.cbody = mk('div', 'ibody');
  UI.cnote = mk('div', 'inote'); UI.cnote.setAttribute('role', 'status'); UI.cnote.hidden = true;
  card.append(head, UI.cbody, UI.cnote);
  const tg = document.getElementById('telegramSet');
  const after = tg && tg.parentNode === host.parentNode ? tg : host;
  host.parentNode.insertBefore(card, after.nextSibling);
  S.card = card;
  return true;
}
function field(label, input) {
  const l = mk('label', 'sos-field');
  l.append(mk('span', 'snote', label), input);
  return l;
}
function input(value, max, kind) {
  const i = mk('input', 'minput sos-input');
  i.type = kind || 'text'; i.maxLength = max; i.value = value || ''; i.autocomplete = 'off';
  return i;
}
async function change(work, done) {
  if (S.busy) return;
  S.busy = true;
  try { const r = await work(); cardNote('ok', done(r)); await refreshCard(); } catch (e) { cardNote('bad', errWords(e, 'That didn\u2019t work.')); } finally { S.busy = false; }
}
function contactRow(c, telegram) {
  const id = CID.test(c.id) ? c.id : '';
  const label = txt(c.label, 40);
  if (!id || !label) return null;
  const day = c.joined === true ? M.when(c.joined_at, false) : '';
  const when = day ? ' on ' + day : '';
  const who = c.joined === true && typeof c.tg_hint === 'string' && c.tg_hint ? ' (Telegram account ' + txt(c.tg_hint, 8) + ')' : '';
  const how = c.joined === true ? 'Joined on Telegram' + when + who : c.pending === true ? 'Join link sent: waiting for them to press Start' : 'Not on Telegram yet';
  const phone = typeof c.phone_hint === 'string' && c.phone_hint ? ' \u00b7 SMS ' + txt(c.phone_hint, 8) : '';
  const row = mk('div', 'sos-contact');
  const words = mk('div', 'btxt'); words.append(mk('b', '', label), mk('small', '', how + phone));
  const acts = mk('div', 'sacts');
  if (telegram && c.joined !== true) acts.append(button('Join link', 'btn sos-small', () => makeLink(id, label)));
  acts.append(button('Remove', 'btn sos-small', () => change(() => api('/v1/sos/contacts/' + id, { method: 'DELETE' }), () => label + ' was removed.')));
  row.append(words, acts);
  return row;
}
function makeLink(id, label) {
  change(async () => api('/v1/sos/contacts/' + id + '/link', { method: 'POST', body: {} }), (r) => {
    const url = r && typeof r.link === 'string' && LINK.test(r.link) ? r.link : '';
    if (!url) return 'The link could not be made.';
    S.lastLink = { label, url };
    clearTimeout(S.linkTimer);
    S.linkTimer = setTimeout(forgetLink, LINK_MS); // the one-time link does not stay on the page
    return 'Send this link to ' + label + ' yourself. It works once, for 24 hours.';
  });
}
function forgetLink() {
  S.lastLink = null; clearTimeout(S.linkTimer);
  const box = document.querySelector('.sos-linkbox');
  if (box) box.remove();
}
function linkBox() {
  if (!S.lastLink) return null;
  const box = mk('div', 'sos-linkbox');
  const shown = input(S.lastLink.url, 120); shown.readOnly = true; shown.setAttribute('aria-label', 'Join link for ' + S.lastLink.label);
  const copy = button('Copy link', 'btn sos-small', async () => {
    try { const who = S.lastLink.label; await navigator.clipboard.writeText(S.lastLink.url); forgetLink(); cardNote('ok', 'Copied. Send it to ' + who + ' yourself.'); } catch (_) { shown.select(); }
  });
  box.append(shown, copy);
  return box;
}
function lastLine(v) {
  const l = v.last;
  if (!l || typeof l.at !== 'string') return 'No SOS has been sent.';
  const when = M.when(l.at, true);
  const n = int(l.reached, 0, 5) || 0;
  return 'Last: ' + (TITLE[l.kind] || 'SOS') + (when ? ' at ' + when : '') + (l.outcome === 'refused' ? ', over the limit, not sent.' : ', reached ' + n + '.');
}
function renderCard(v) {
  const parts = [];
  const off = v.enabled === false || v.sealed === false;
  S.card.dataset.state = off ? 'off' : v.locked ? 'locked' : 'ready';
  const count = Array.isArray(v.contacts) ? v.contacts.length : 0;
  UI.cstate.textContent = off ? 'Off' : v.locked ? 'Locked' : count ? count + (count === 1 ? ' contact' : ' contacts') : 'Not set up';
  parts.push(mk('p', '', 'Hold the SOS button for ' + holdS() + ' seconds: your contacts get a message and a map pin on Telegram, and your phone\u2019s SMS screen opens filled in.'));
  if (off) parts.push(mk('p', 'warn', txt(v.note, 200) || 'Emergency SOS is switched off on this server.'));
  else if (v.locked) parts.push(mk('p', '', 'Unlock JARVIS to change your SOS set-up. The SOS button still works.'));
  else {
    const name = input(txt(v.label, 40), 40);
    const save = button('Save name', 'btn sos-small', () => change(() => api('/v1/sos/label', { method: 'PUT', body: { label: name.value } }), () => 'Saved.'));
    parts.push(field(v.label_set === true ? 'Your name in the message' : 'Your name in the message (not set yet)', name), save);
    (v.contacts || []).forEach((c) => { const r = contactRow(c || {}, v.telegram === true); if (r) parts.push(r); });
    const box = linkBox(); if (box) parts.push(box);
    const most = int(v.max, 1, 5) || 5;
    if (count < most) {
      const label = input('', 40), phone = input('', 20, 'tel');
      const add = button('Add contact', 'btn sos-small', () => change(() => api('/v1/sos/contacts', { method: 'POST', body: { label: label.value, phone: phone.value || null } }), (r) => txt(r && r.contact && r.contact.label, 40) + ' was added.'));
      parts.push(field('Contact\u2019s name', label), field('Their phone number, for the SMS screen (optional)', phone), add);
    } else parts.push(mk('p', 'fine', 'You have ' + most + ' contacts, the most there can be.'));
    if (v.telegram !== true) parts.push(mk('p', 'fine', 'Telegram is not switched on, so contacts can\u2019t join there yet. The SMS screen works without it.'));
    parts.push(mk('p', 'fine', lastLine(v)));
  }
  parts.push(button('Open SOS', 'btn danger sos-open', () => openSheet()), mk('p', 'fine', txt(v.note, 300) || NOT_A_SERVICE));
  UI.cbody.replaceChildren(...parts);
}
async function refreshCard() {
  if (!signedIn() || !buildCard()) return;
  try { S.view = await api('/v1/sos'); renderCard(S.view || {}); } catch (e) {
    UI.cstate.textContent = 'Error';
    if (e && e.status !== 401) cardNote('bad', errWords(e, 'Couldn\u2019t check your SOS set-up.'));
  }
}
const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));

// ---- joins: the panel, sign-in, voice, the launch word -------------------------------------------------------------
document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id !== 'integrations') return; if (d.open) refreshCard(); else forgetLink(); });
document.addEventListener('jarvis:ready', () => { if (integOpen()) refreshCard(); });
if (signedIn() && integOpen()) refreshCard();
function voice() {
  const V = window.JarvisVoiceCommands;
  if (!V || typeof V.register !== 'function') return false;
  try {
    V.register('sos.open', { match: (norm) => (VOICE.includes(norm) ? {} : null), run: () => { openSheet(); return { say: 'The SOS screen is open, Sir. Hold the red button to send.' }; } });
  } catch (_) { /* registered already */ }
  return true;
}
if (!voice()) window.addEventListener('load', voice, { once: true });
if (M) M.part('sos', { open: openSheet, close: closeSheet, isOpen: () => !!(UI.dlg && UI.dlg.open) });
