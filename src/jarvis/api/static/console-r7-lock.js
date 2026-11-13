// src/jarvis/api/static/console-r7-lock.js -- R7 Part C (docs/plans/r7-mobile.md D21): the app lock on the page.
// 1. The installed app opens /?source=app: this tab remembers it (sessionStorage, so the Google sign-in round trip keeps
//    it) and, once signed in, tells the server once (POST /v1/session/app; a mark only ever switches the lock ON).
// 2. "I'm here": at most once a minute, and only after a real tap or key press (isTrusted), the app's page sends
//    POST /v1/session/here. Background polls never count as being here; this call is the only thing the page adds.
// 3. The unlock cover: console.js fires jarvis:device-locked (and sets html[data-locked="device"]) when any request
//    answers 423 device_locked. The cover hides the console and offers "Unlock with passkey": POST /v1/session/unlock {}
//    -> {unlocked: false, target}, a device_unlock passkey check bound to THIS session, then the page reloads.
// 4. Privacy -> "This device": the lock's switch (GET/PUT /v1/session/lock; off takes the passkey, on takes nothing).
// Loaded by console-r7.js (an ES module); existing classes only (.gate, .gate-card, .cta, .core, .pv-*); textContent
// only; ASCII only. It asks the server NOTHING before sign-in (jarvis:ready), except the unlock the owner presses.
const M = window.JarvisMobile;
const $ = (id) => document.getElementById(id);
const FLAG = 'jarvis_app_v1';
const HERE_MS = 60 * 1000;
const SS = /^ss_[A-Za-z0-9_-]{24}$/;
const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
const S = { signedIn: false, app: false, marked: false, lastHere: 0, cover: null, busy: false, lock: undefined };

const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const mk = (tag, cls, text) => (M ? M.mk(tag, cls, text) : document.createElement(tag));
const api = (path, opts) => M.api(path, opts);
const store = {
  get() { try { return sessionStorage.getItem(FLAG); } catch (_) { return null; } },
  set() { try { sessionStorage.setItem(FLAG, '1'); } catch (_) {} },
};
const locked = () => document.documentElement.dataset.locked === 'device';
function detailOf(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const m = e && typeof e.message === 'string' ? e.message.trim().slice(0, 300) : '';
  return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
}
function passkey() {
  const P = window.JarvisPasskey;
  return P && typeof P.supported === 'function' && P.supported() && typeof P.prove === 'function' ? P : null;
}

// ---- 1. this tab is the installed app's --------------------------------------------------------------------------------
try { if (new URLSearchParams(location.search).get('source') === 'app') store.set(); } catch (_) {}
S.app = store.get() === '1';

async function markApp() {
  if (!S.app || S.marked || !M) return;
  S.marked = true;
  try { await api('/v1/session/app', { method: 'POST' }); } catch (_) { S.marked = false; }
}

// ---- 2. I'm here ------------------------------------------------------------------------------------------------------
function here(e) {
  if (!e.isTrusted || !S.app || !S.signedIn || locked() || !M) return;
  const now = Date.now();
  if (now - S.lastHere < HERE_MS) return;
  S.lastHere = now;
  api('/v1/session/here', { method: 'POST' }).catch(() => {});
}
document.addEventListener('pointerdown', here, { capture: true, passive: true });
document.addEventListener('keydown', here, { capture: true, passive: true });

// ---- 3. the unlock cover ----------------------------------------------------------------------------------------------
function ring() {
  const r = mk('span', 'core lg'); r.setAttribute('aria-hidden', 'true');
  const svg = document.querySelector('#orb svg');
  if (svg) r.append(svg.cloneNode(true));
  return r;
}
function showCover() {
  if (S.cover && S.cover.isConnected) { S.cover.hidden = false; return; }
  const wrap = mk('div', 'gate show r7lock'); wrap.id = 'r7Lock';
  const box = mk('div', 'gate-card card hud'); box.id = 'r7LockBox';
  box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'r7LockTitle');
  const h = mk('h2', '', 'JARVIS'); h.id = 'r7LockTitle';
  const p = mk('p', '', 'JARVIS is locked on this device, Sir. Unlock it with your passkey.'); p.id = 'r7LockText';
  const go = mk('button', 'cta lift', 'Unlock with passkey'); go.type = 'button'; go.id = 'r7Unlock';
  const msg = mk('p', 'fine', ''); msg.id = 'r7LockNote'; msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite');
  const out = mk('button', 'btn lift', 'Sign out instead'); out.type = 'button'; out.id = 'r7SignOut';
  box.append(ring(), h, p, go, msg, out);
  wrap.append(box);
  document.body.append(wrap);
  S.cover = wrap;
  go.addEventListener('click', () => unlock(go, msg));
  out.addEventListener('click', () => signOut(out));
  go.focus();
}
async function unlock(btn, msg) {
  if (S.busy || !M) return;
  S.busy = true; btn.disabled = true; msg.textContent = 'Checking\u2026';
  try {
    let r = obj(await api('/v1/session/unlock', { body: {} }));
    if (r && r.unlocked === false) {
      const P = passkey(), target = typeof r.target === 'string' && SS.test(r.target) ? r.target : '';
      if (!P) throw new Error('This browser can\'t use passkeys here. Sign out, then sign in again.');
      if (!target) throw new Error('JARVIS couldn\'t start the unlock. Please try again.');
      let proof;
      try { proof = await P.prove('device_unlock', target); } catch (e) { throw new Error(P.message ? P.message(e) : 'The passkey check didn\'t work.'); }
      r = obj(await api('/v1/session/unlock', { body: { proof } }));
    }
    if (r && r.unlocked === true) { msg.textContent = 'Unlocked.'; delete document.documentElement.dataset.locked; location.reload(); return; }
    msg.textContent = 'JARVIS is still locked. Please try again.';
  } catch (e) {
    msg.textContent = e && e.status === 429 ? 'Too many tries. Wait a minute, then try again.' : (detailOf(e) || 'The unlock didn\'t work. Please try again.');
  } finally { S.busy = false; btn.disabled = false; }
}
async function signOut(btn) {
  btn.disabled = true;
  try { await api('/auth/logout', { method: 'POST' }); } catch (_) {}
  location.replace('/');
}
document.addEventListener('jarvis:device-locked', showCover);
if (locked()) showCover();

// ---- 4. Privacy -> This device: the switch ----------------------------------------------------------------------------
const WHAT = 'In the JARVIS phone app, JARVIS locks itself after 5 minutes away and opens again with your passkey. ' +
  'It is never on in an ordinary browser, and it waits until you have added a passkey from the phone app, so it can never lock you out.';
function lockNormal(raw) {
  const d = obj(raw);
  if (!d || typeof d.on !== 'boolean') return null;
  const minutes = Number.isInteger(d.minutes) && d.minutes > 0 ? d.minutes : 5;
  return { on: d.on, armed: d.armed === true, waiting: d.waiting === true, app: d.app === true, minutes };
}
function lockCard() {
  const body = document.querySelector('#p-privacy .pbody');
  if (!body) return null;
  let sec = $('r7LockSet');
  if (sec && sec.parentNode === body) return sec;
  sec = mk('section', 'pv-sec'); sec.id = 'r7LockSet';
  sec.append(mk('h3', 'pv-h', 'This device'));
  body.append(sec);
  return sec;
}
function renderLock(words) {
  const sec = lockCard();
  if (!sec) return;
  const d = S.lock;
  const el = mk('div', 'pv-card'); el.id = 'r7LockCard';
  const head = mk('div', 'pv-head');
  head.append(mk('h4', 'pv-label', `Lock JARVIS on this device after ${d ? d.minutes : 5} minutes away`));
  const state = !d ? 'Couldn\'t check' : !d.on ? 'Off' : d.armed ? 'On' : 'Waits for a passkey';
  const count = mk('span', 'pv-count', state); count.id = 'r7LockState';
  head.append(count);
  el.append(head, mk('p', 'pv-what', WHAT));
  if (d && d.on && !d.armed) el.append(mk('p', 'pv-note', 'It turns on by itself once you add a passkey from the phone app (Approvals, then Permissions, in the app).'));
  const msg = mk('p', 'pv-note', words || ''); msg.id = 'r7LockNote'; msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite');
  el.append(msg);
  if (d) {
    const acts = mk('div', 'pv-acts');
    const b = mk('button', 'btn bact', d.on ? 'Turn off' : 'Turn on'); b.type = 'button'; b.id = 'r7LockSwitch';
    b.addEventListener('click', () => flip(!d.on, b));
    acts.append(b);
    el.append(acts);
  }
  sec.replaceChildren(sec.firstChild, el);
}
async function loadLock() {
  if (!S.signedIn || !M || locked()) return;
  try { S.lock = lockNormal(await api('/v1/session/lock')); } catch (e) { if (e && (e.status === 401 || e.status === 423)) return; S.lock = null; }
  renderLock('');
}
async function flip(on, btn) {
  if (S.busy) return;
  S.busy = true; btn.disabled = true;
  let words = '';
  try {
    let r = obj(await api('/v1/session/lock', { method: 'PUT', body: { on } }));
    if (r && r.needs === 'passkey') {
      const P = passkey(), target = typeof r.target === 'string' && SS.test(r.target) ? r.target : '';
      if (!P || !target) throw new Error('Switching the lock off takes your passkey, and this browser can\'t use one.');
      let proof;
      try { proof = await P.prove('device_unlock', target); } catch (e) { throw new Error(P.message ? P.message(e) : 'The passkey check didn\'t work.'); }
      r = obj(await api('/v1/session/lock', { method: 'PUT', body: { on, proof } }));
    }
    S.lock = lockNormal(r) || S.lock;
    words = on ? 'The lock is on.' : 'The lock is off.';
  } catch (e) {
    if (e && e.status === 401) return;
    words = detailOf(e) || 'Couldn\'t change the lock. Please try again.';
  } finally { S.busy = false; btn.disabled = false; }
  renderLock(words);
}
const privacyOpen = () => { const p = $('p-privacy'); return !!p && !p.hidden; };
document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'privacy' && d.open) setTimeout(loadLock, 0); });

// ---- signed in --------------------------------------------------------------------------------------------------------
function signedIn() {
  S.signedIn = true; S.marked = false; // a sign-in again (after a 401) is a new session: mark it too
  markApp();
  if (privacyOpen()) setTimeout(loadLock, 0);
}
document.addEventListener('jarvis:ready', signedIn);
if (window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready()) signedIn();
if (M) M.part('lock', Object.freeze({ app: () => S.app, cover: showCover }));
