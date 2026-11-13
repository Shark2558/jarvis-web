// src/jarvis/api/static/console-r7-links.js -- R7 Part A (docs/plans/r7-mobile.md D8, D9): a launch address opens a
// screen and NEVER acts. Loaded by console-r7.js (an ES module); ASCII source; textContent only; it never asks the
// server anything (it only reads the address, this tab's sessionStorage and the 'jarvis-launch' channel).
//   ?do=talk     the Conversation panel with the mic button focused and "Tap to talk" in the voice line. It NEVER
//                starts the microphone: no press(), no click(), no unlock; the owner's own tap on the mic button is
//                R5's press(), which is also the only thing that can switch a locked mic back on.
//   ?do=look     the Camera panel; the camera itself starts only on a tap on that screen (Part B)
//   ?do=sos      the SOS sheet (Part D: JarvisMobile.parts.sos.open()); sending still needs the hold
//   ?do=shared   the share tray (console-r7-share.js: JarvisMobile.parts.share.open())
//   ?open=<p>    the panel <p>, one of the dock's own panels (PANELS)
// Only these: each key at most once, its value exactly from WORDS or PANELS; anything else is ignored. `do` wins
// over `open`. Both keys are taken out of the address at once (history.replaceState), so a reload never repeats a
// launch; every other word stays (source=app, Google's reauth). The server already dropped both when the browser
// marked the visit cross-site (api/console.py). A launch read while signed out waits in this tab's sessionStorage
// (at most 10 minutes, so it survives the Google sign-in round trip) and opens its screen after jarvis:ready.
// A tapped alert (console-sw.js) hands its target to the JARVIS window already open over the BroadcastChannel
// 'jarvis-launch' ({type: 'launch', open, do}); a window that is not on screen keeps it until it is (15 s).
const M = window.JarvisMobile;
const WORDS = Object.freeze(['talk', 'look', 'sos', 'shared']);
const PANELS = Object.freeze(['chat', 'brief', 'approvals', 'activity', 'history', 'memory', 'integrations', 'vault',
  'things', 'notes', 'privacy', 'home', 'faces', 'vitals', 'connectors', 'people', 'book', 'voice', 'media',
  'construct', 'helpers', 'camera']);
const KEYS = ['do', 'open'];
const KEEP = 'jarvis_r7_launch_v1';
const KEEP_MS = 10 * 60 * 1000;
const UNSEEN_MS = 15000;
const PART_WAIT_MS = 5000;
const TALK_LINE = 'Tap to talk';
const NONE = Object.freeze({ do: '', open: '' });

const pick = (value, list) => (typeof value === 'string' && list.includes(value) ? value : '');
const launch = (d, o) => Object.freeze({ do: pick(d, WORDS), open: pick(o, PANELS) });
const empty = (l) => !l.do && !l.open;

/** The launch an address asks for: each key at most once and only allow-listed values. */
function read(search) {
  let q;
  try { q = new URLSearchParams(search); } catch (_) { return NONE; }
  const one = (k) => { const all = q.getAll(k); return all.length === 1 ? all[0] : ''; };
  return launch(one('do'), one('open'));
}

/** The address without `do` and `open` (null when it carries neither). */
function cleaned(href) {
  const u = new URL(href);
  if (!KEYS.some((k) => u.searchParams.has(k))) return null;
  KEYS.forEach((k) => u.searchParams.delete(k));
  const rest = u.searchParams.toString();
  return u.pathname + (rest ? '?' + rest : '') + u.hash;
}

const signedIn = () => { const c = window.JarvisConsole; return !!(c && typeof c.ready === 'function' && c.ready()); };
function keep(l) {
  try { sessionStorage.setItem(KEEP, JSON.stringify({ do: l.do, open: l.open, at: Date.now() })); } catch (_) {}
}
let lastKept = NONE;
/** The kept launch, read and left in place (the share tray asks whether a launch is on its way). */
function peekKept() {
  try {
    const o = JSON.parse(sessionStorage.getItem(KEEP) || 'null');
    return o && typeof o === 'object' && Date.now() - o.at >= 0 && Date.now() - o.at < KEEP_MS ? launch(o.do, o.open) : NONE;
  } catch (_) { return NONE; }
}
function kept() {
  let o = null;
  try { o = JSON.parse(sessionStorage.getItem(KEEP) || 'null'); sessionStorage.removeItem(KEEP); } catch (_) { return NONE; }
  if (!o || typeof o !== 'object' || !(Date.now() - o.at >= 0 && Date.now() - o.at < KEEP_MS)) return NONE;
  lastKept = launch(o.do, o.open);
  return lastKept;
}

// ---- the screens (each only opens something) --------------------------------------------------------------------
function talk() {
  const D = window.JarvisDeck, mic = document.getElementById('micBtn'), loop = window.JarvisVoiceLoop;
  if (D) D.open('chat', { focus: false });
  if (mic && !mic.hidden) {
    mic.focus();
    if (loop && typeof loop.say === 'function') loop.say(TALK_LINE);
    return;
  }
  const input = document.getElementById('input'); // this browser can't listen: the keyboard is ready instead
  if (input) input.focus();
}
async function partOpen(name) {
  const until = Date.now() + PART_WAIT_MS;
  for (;;) {
    const p = M && M.parts ? M.parts[name] : null;
    if (p && typeof p.open === 'function') { p.open({ via: 'launch' }); return true; }
    if (Date.now() > until) return false;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}
function act(l) {
  const D = window.JarvisDeck;
  if (l.do === 'talk') talk();
  else if (l.do === 'look') { if (D) D.open('camera', { focus: true }); }
  else if (l.do === 'sos') partOpen('sos');
  else if (l.do === 'shared') partOpen('share');
  else if (l.open && D) D.open(l.open, { focus: true });
}
/** Now if signed in; otherwise it waits (this tab only) for the next jarvis:ready. */
function whenIn(l) {
  if (empty(l)) return;
  if (signedIn()) act(l); else keep(l);
}

// ---- an alert tapped while this window was open -----------------------------------------------------------------
function fromAlert(data) {
  if (!data || typeof data !== 'object' || data.type !== 'launch') return;
  const l = launch(data.do, data.open);
  if (empty(l)) return;
  if (document.visibilityState === 'visible') { whenIn(l); return; }
  const shown = () => {
    if (document.visibilityState !== 'visible') return;
    document.removeEventListener('visibilitychange', shown);
    clearTimeout(timer); whenIn(l);
  };
  const timer = setTimeout(() => document.removeEventListener('visibilitychange', shown), UNSEEN_MS);
  document.addEventListener('visibilitychange', shown);
}

// ---- start: read the address once, then take the words out of it -----------------------------------------------
const first = read(location.search);
const clean = cleaned(location.href);
if (clean !== null) {
  try { history.replaceState(history.state, '', clean); } catch (_) {}
}
document.addEventListener('jarvis:ready', () => { const l = kept(); if (!empty(l)) act(l); });
if (!empty(first)) whenIn(first);
else if (signedIn()) { const l = kept(); if (!empty(l)) act(l); }
try { new BroadcastChannel('jarvis-launch').onmessage = (e) => fromAlert(e.data); } catch (_) {}

/** True when this page was launched with a screen to open (now, or kept across sign-in). */
const asked = () => !empty(first) || !empty(lastKept) || !empty(peekKept());
if (M) M.part('links', Object.freeze({ read, asked, words: () => WORDS, panels: () => PANELS }));
