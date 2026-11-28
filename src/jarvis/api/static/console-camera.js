// src/jarvis/api/static/console-camera.js -- R7 Part B (docs/plans/r7-mobile.md D11, D12): the camera's ONE door and
// its hard off switch. The only file that asks for a camera (getUserMedia; tests/test_r7_b_console.py pins it beside
// the microphone's file). It mirrors R5's microphone lock (console-voice-capture.js):
//   JarvisCamera.locked() / lock(by) -> stops every track, persists localStorage['jarvis_cam_off_v1'], other tabs follow
//                unlock(by) -> true only inside a real tap, click or key press (navigator.userActivation); never starts it
//   start({facing}) -> Promise<{video, frame(), stop()}>   only inside a tap, never while locked (code 'camera_off')
//   frame()      the picture now, drawn into ONE canvas kept in memory (null when no camera is live); the engine reads it
//                and nothing keeps it: stop() empties the canvas
//   photo()      a photo he picks (the system's own picker: gallery or camera app), only inside a tap; Promise<File|null>
//   stop(why), live(), facing() / useFacing('environment'|'user'), onChange(fn) -> unsubscribe ({locked, live, by})
//   keepWhile(win) -> release()   R8 I1: while that small window on top is open and visible, a hidden tab keeps it on
// While any track is live a "Camera on" chip with Stop stays on screen (beside the dot Android itself draws). The camera
// stops by itself when the page is hidden (another app, the screen locks, the tab is left), and when nothing has used a
// frame for 10 minutes. "Jarvis, cameras off" (R5's local router, so it works with the AI off) locks THIS device's
// camera and says so; it never touches the home burglar camera (disarming stays a card with his passkey, R3 D8), and no
// voice command can switch a camera on. ASCII source; textContent only.
// R8 (docs/plans/r8-vision.md 4.5, D11, ADR-54; builder B): the off switches he sets in Camera, Cameras
// (GET /v1/camera/spots: every camera, this device's own camera by its id, its room) are read when a look starts and
// every RECHECK_MS while it runs, and at once by recheck(view) after a change on this device: a switch that reads off
// stops the look and refuses a start in plain words (code 'switched_off'); the device's own lock above stays as it was.
//   spot() / useSpot(id)  this device's camera id in Camera, Cameras ('' when it has none)
//   recheck(view?)        the switches now (the view a change just answered, or a fresh read) -> Promise<words | ''>
//   allOff(by)            "cameras off": locks THIS device at once, then POST /v1/camera/off (every other device stops
//                         within RECHECK_MS); -> Promise<{server, armed}>. The burglar alarm is never changed.
//   blocked()             the words of the switch that stops it now, or ''
// While a look runs on a registered camera, its health (frames used a second, a frame's grab in ms; never a picture)
// goes to POST /v1/camera/health after FIRST_HEALTH_MS and every HEALTH_MS (Vitals: last seen, frame rate). Nothing is
// asked of the server before sign-in.
const M = window.JarvisMobile;
const KEY = 'jarvis_cam_off_v1';
const IDLE_MS = 10 * 60 * 1000;
const IDLE_CHECK_MS = 30 * 1000;
const LOCK_BY = ['button', 'voice', 'panel', 'storage', 'boot', 'chip'];
const FACING = ['environment', 'user'];
// R7_PHRASES["camera.off"] (src/jarvis/voice/commands.py, I0 seam 13); tests/test_r7_b_console.py keeps them equal
const OFF_PHRASES = Object.freeze(/*CAMERA-OFF-BEGIN*/[
  'cameras off', 'camera off', 'stop the camera', 'stop the cameras', 'turn off the camera', 'turn the camera off',
  'turn off the cameras', 'switch off the camera', 'switch the camera off', 'switch off the cameras',
  'close the camera', 'shut the camera', 'shut off the camera', 'kill the camera', 'disable the camera',
  'lock the camera', 'put the camera off', 'no more camera', 'stop looking', 'stop watching me',
]/*CAMERA-OFF-END*/);
const err = (code, text) => { const e = new Error(text); e.code = code; return e; };
const OFF_TEXT = 'The camera is switched off on this device. Tap Allow in Camera, Cameras, to switch it on.';
const TAP_TEXT = 'The camera starts only from a tap.';
const NONE_TEXT = 'This browser has no camera JARVIS can use.';
const SPOT_KEY = 'jarvis_cam_spot_v1';
const SPOT_ID = /^[a-z0-9_]{1,24}$/;
const RECHECK_MS = 60 * 1000; // jarvis.camera.spots.RECHECK_S
const READ_MS = 2500; // a switch read waits this long; then the last one read counts
const FIRST_HEALTH_MS = 15 * 1000;
const HEALTH_MS = 5 * 60 * 1000;
const ALL_OFF_TEXT = 'Every camera is switched off. Tap Allow in Camera, Cameras, to switch them on.';
const SPOT_OFF_TEXT = 'This camera is switched off in Camera, Cameras. Tap Allow there to switch it on.';
// CAMERAS_OFF_REPLY (src/jarvis/voice/commands.py); tests/test_r8_b_spots.py keeps them equal. {h}: the honorific
const OFF_SAY = Object.freeze(/*CAMERAS-OFF-SAY-BEGIN*/{
  local: 'The camera on this device is off, {h}.',
  all: 'Every camera is off, {h}: this device now, your other devices within a minute.',
  armed: 'The burglar alarm is still armed and its camera keeps watching; Disarm is in Home.',
}/*CAMERAS-OFF-SAY-END*/);

function readLock() { try { return localStorage.getItem(KEY) === '1'; } catch (_) { return false; } }
function writeLock(on) {
  try { if (on) localStorage.setItem(KEY, '1'); else localStorage.removeItem(KEY); } catch (_) { /* read back below */ }
  return readLock() === on;
}
const S = { locked: readLock(), streams: new Set(), facing: 'environment', used: 0, idle: 0, wake: null, waking: false, gen: 0, tapAt: 0,
  blocked: '', recheck: 0, health: 0, frames: 0, grabMs: 0, since: 0 };
const subs = new Set();
const video = document.createElement('video');
video.muted = true;
video.playsInline = true;
video.setAttribute('playsinline', '');
video.setAttribute('aria-label', 'The live picture, on this device only');
const canvas = document.createElement('canvas');

// A tap counts only when it was a real click (or the key press a browser turns into one) on the camera's own buttons: the
// Camera panel or the chip. A script that runs just after some other tap has no activation of its own to use.
const OWN = '#p-camera, .cam-chip';
const TAP_MS = 5000;
document.addEventListener('click', (e) => {
  const t = e && e.target;
  S.tapAt = e && e.isTrusted && t && typeof t.closest === 'function' && t.closest(OWN) ? Date.now() : 0;
}, true);
const activated = () => {
  const ua = navigator.userActivation;
  return !!(ua && ua.isActive) && S.tapAt > 0 && Date.now() - S.tapAt < TAP_MS;
};
const who = (by) => (LOCK_BY.includes(by) ? by : 'button');
function tracks() { return [...S.streams].flatMap((s) => s.getTracks()); }
function live() { return tracks().some((t) => t.readyState === 'live'); }

// ---- the chip: "Camera on" with Stop, whenever a track is live -------------------------------------------------------
const chip = document.createElement('button');
chip.type = 'button';
chip.className = 'status alert cam-chip';
chip.hidden = true;
chip.setAttribute('aria-label', 'Camera on. Stop the camera');
chip.append(document.createElement('i'), document.createTextNode('Camera on \u00b7 Stop'));
chip.firstChild.setAttribute('aria-hidden', 'true');
chip.addEventListener('click', () => stop('chip'));
function placeChip() { if (!chip.parentNode && document.body) document.body.append(chip); }

function emit(by) {
  const on = live();
  chip.hidden = !on;
  if (on) placeChip();
  const d = Object.freeze({ locked: S.locked, live: on, by: by || '' });
  subs.forEach((fn) => { try { fn(d); } catch (_) {} });
  try { document.dispatchEvent(new CustomEvent('jarvis:camera', { detail: d })); } catch (_) {}
}

function release() {
  const w = S.wake;
  S.wake = null;
  if (w && typeof w.release === 'function') w.release().catch(() => {});
}
function keepAwake() { // the screen stays on while a live look runs (D13)
  const wl = navigator.wakeLock;
  if (!wl || typeof wl.request !== 'function' || S.wake || S.waking) return;
  S.waking = true;
  const held = (w) => { S.waking = false; if (live() && !S.wake) S.wake = w; else w.release().catch(() => {}); };
  wl.request('screen').then(held, () => { S.waking = false; });
}

/** Stop every track and throw the last picture away. */
function stop(why) {
  S.gen += 1;
  const had = tracks().length > 0;
  tracks().forEach((t) => { try { t.stop(); } catch (_) {} });
  S.streams.clear();
  try { video.pause(); } catch (_) {}
  video.srcObject = null;
  canvas.width = 0;
  canvas.height = 0;
  clearInterval(S.idle);
  S.idle = 0;
  clearInterval(S.recheck);
  clearTimeout(S.health);
  S.recheck = 0;
  S.health = 0;
  release();
  if (had) emit(why || 'stop');
}

function applyLock(on, by, persist) {
  const kept = persist ? writeLock(on) : true;
  const changed = S.locked !== on;
  S.locked = on;
  if (on) stop('lock');
  if (changed || !kept) emit(by);
  return kept;
}
const lock = (by) => applyLock(true, who(by), true);
/** True only for a real tap, click or key press; it never starts the camera. */
function unlock(by) {
  if (!activated()) return false;
  applyLock(false, who(by), true);
  return true;
}

// ---- R8: the off switches on the server, this device's camera id, its health ------------------------------------------
function spot() { try { const v = localStorage.getItem(SPOT_KEY) || ''; return SPOT_ID.test(v) ? v : ''; } catch (_) { return ''; } }
function useSpot(id) {
  try { if (!id) localStorage.removeItem(SPOT_KEY); else if (SPOT_ID.test(id)) localStorage.setItem(SPOT_KEY, id); else return false; } catch (_) { return false; }
  return spot() === (id || '');
}
const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
function server(path, opts) {
  const c = window.JarvisConsole;
  if (!c || typeof c.api !== 'function') return Promise.reject(new Error('offline'));
  return Promise.race([c.api(path, opts), new Promise((_, no) => setTimeout(() => no(new Error('slow')), READ_MS))]);
}
/** The words that stop this device now ('' when it may look), or null when the answer says nothing either way. */
function judge(v) {
  if (!v || typeof v !== 'object') return null;
  if (v.all_off === true) return ALL_OFF_TEXT;
  const id = spot();
  return id && v.allowed && typeof v.allowed === 'object' && v.allowed[id] === false ? SPOT_OFF_TEXT : '';
}
function applySwitches(v) {
  const words = judge(v);
  if (words === null) return S.blocked;
  S.blocked = words;
  if (words && live()) stop('switch');
  return words;
}
async function readSwitches() {
  if (!signedIn()) return S.blocked;
  try { return applySwitches(await server('/v1/camera/spots')); } catch (_) { return S.blocked; }
}
function recheck(view) { return view && typeof view === 'object' ? Promise.resolve(applySwitches(view)) : readSwitches(); }
function switched() { const e = err('switched_off', S.blocked || ALL_OFF_TEXT); e.status = 409; return e; }
function postHealth() {
  S.health = setTimeout(postHealth, HEALTH_MS);
  const id = spot(), secs = (Date.now() - S.since) / 1000;
  if (!id || !signedIn() || !live() || secs <= 0) return;
  const fps = Math.min(120, Math.round((S.frames / secs) * 10) / 10), ms = S.frames ? Math.min(60000, Math.round(S.grabMs / S.frames)) : 0;
  S.frames = 0; S.grabMs = 0; S.since = Date.now();
  server('/v1/camera/health', { method: 'POST', body: { camera: id, fps, ms } }).catch(() => {});
}
function watchServer() {
  clearInterval(S.recheck); clearTimeout(S.health);
  S.recheck = setInterval(readSwitches, RECHECK_MS);
  S.frames = 0; S.grabMs = 0; S.since = Date.now();
  S.health = setTimeout(postHealth, FIRST_HEALTH_MS);
}
/** "Cameras off": this device locks at once (it works with the AI off); then every other camera, through the server. */
async function allOff(by) {
  lock(by === 'voice' ? 'voice' : 'panel');
  if (!signedIn()) return { server: false, armed: null };
  try {
    const r = await server('/v1/camera/off', { method: 'POST', body: { by: by === 'voice' ? 'voice' : 'button' } });
    return { server: !!(r && r.all_off === true), armed: r && typeof r.alarm_armed === 'boolean' ? r.alarm_armed : null };
  } catch (_) { return { server: false, armed: null }; }
}

function touch() { S.used = Date.now(); }
function watchIdle() {
  clearInterval(S.idle);
  S.idle = setInterval(() => { if (Date.now() - S.used > IDLE_MS) stop('idle'); }, IDLE_CHECK_MS);
}

async function start(opts) {
  if (S.locked) throw err('camera_off', OFF_TEXT);
  if (!activated()) throw err('needs_tap', TAP_TEXT);
  const md = navigator.mediaDevices;
  if (!md || typeof md.getUserMedia !== 'function') throw err('unsupported', NONE_TEXT);
  if (S.blocked && (await readSwitches())) throw switched(); // a switch read off before: read again, never ask
  const facing = FACING.includes(opts && opts.facing) ? opts.facing : S.facing;
  S.facing = facing;
  stop('restart');
  const my = S.gen;
  const reading = readSwitches(); // R8: the switches, read while the browser asks
  const stream = await md.getUserMedia({ audio: false, video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } } });
  const off = await reading;
  if (S.locked || my !== S.gen || off) { // switched off (or stopped) while the browser asked: nothing stays live
    stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
    if (off && !S.locked) throw switched();
    throw err(S.locked ? 'camera_off' : 'stopped', S.locked ? OFF_TEXT : 'The camera was stopped.');
  }
  S.streams.add(stream);
  stream.getTracks().forEach((t) => t.addEventListener('ended', () => { if (!live()) stop('ended'); }));
  video.srcObject = stream;
  touch();
  watchIdle();
  watchServer();
  keepAwake();
  emit('start'); // the chip shows from the moment a track exists, before play() answers
  try { await video.play(); } catch (_) { /* a muted inline video plays; the frames still arrive */ }
  if (my !== S.gen) throw err('stopped', 'The camera was stopped.'); // stopped while play() was starting
  return Object.freeze({ video, frame, stop: () => stop('panel') });
}

/** The picture now, in the one canvas (in memory; the engine reads it, nothing keeps it). */
function frame() {
  if (!live()) return null;
  const w = video.videoWidth || 0, h = video.videoHeight || 0;
  if (!w || !h) return null;
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  const t0 = Date.now();
  ctx.drawImage(video, 0, 0, w, h);
  S.frames += 1;
  S.grabMs += Date.now() - t0;
  touch();
  return canvas;
}

/** A photo he picks with the system's own picker (only inside a tap). */
function photo() {
  if (!activated()) return Promise.reject(err('needs_tap', TAP_TEXT));
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    let done = false;
    const finish = (f) => { if (!done) { done = true; resolve(f || null); } };
    input.addEventListener('change', () => finish(input.files && input.files[0]));
    input.addEventListener('cancel', () => finish(null));
    input.click();
  });
}

function onChange(fn) {
  if (typeof fn !== 'function') return () => {};
  subs.add(fn);
  return () => { subs.delete(fn); };
}

// ---- stops by itself: hidden page, screen locked, page left --------------------------------------------------------
// R8 I1 (D10; C's Desk pane): keepWhile(win) -> release(). While the small window on top (Document Picture-in-Picture:
// a Window of this page's own) is open and visible, hiding THIS tab doesn't stop the camera; closing that window, or it
// being hidden too (the screen locked), does. Leaving the page or the page being frozen always stops it.
const keepers = new Set();
function kept() {
  for (const w of keepers) { try { if (w.closed) keepers.delete(w); } catch (_) { keepers.delete(w); } }
  return [...keepers].some((w) => { try { return !w.document.hidden; } catch (_) { return false; } });
}
function keepWhile(win) {
  let ok = false;
  try { ok = !!win && win !== window && typeof win.closed === 'boolean' && !win.closed && !!win.document; } catch (_) { ok = false; }
  if (!ok) return () => {};
  keepers.add(win);
  const release = () => { keepers.delete(win); if (document.hidden && !kept()) stop('hidden'); };
  try { win.addEventListener('pagehide', release, { once: true }); } catch (_) {}
  try { win.document.addEventListener('visibilitychange', () => { if (win.document.hidden && document.hidden && !kept()) stop('hidden'); }); } catch (_) {}
  return release;
}
document.addEventListener('visibilitychange', () => { if (document.hidden && !kept()) stop('hidden'); });
window.addEventListener('pagehide', () => stop('hidden'));
document.addEventListener('freeze', () => stop('hidden'));
// another tab's switch counts only when the browser raised the event for this origin's storage (a script's own
// StorageEvent, isTrusted false, must never switch the camera on)
window.addEventListener('storage', (e) => {
  if (!e.isTrusted || e.storageArea !== localStorage) return;
  if (e.key === KEY || e.key === null) applyLock(readLock(), 'storage', false);
});

// ---- "Jarvis, cameras off": a local voice command (R5's router); nothing turns a camera on by voice ---------------
function honorific() {
  try { return (window.JarvisChat && window.JarvisChat.honorific && window.JarvisChat.honorific()) || 'Sir'; } catch (_) { return 'Sir'; }
}
function openHome() { try { if (window.JarvisDeck && typeof window.JarvisDeck.open === 'function') window.JarvisDeck.open('home'); } catch (_) {} }
let registered = false;
function registerVoice() {
  const C = window.JarvisVoiceCommands;
  if (registered || !C || typeof C.register !== 'function') return registered;
  const said = new Set(OFF_PHRASES.map((p) => C.normalise(p)));
  try {
    C.register('camera.off', {
      match: (norm) => (said.has(norm) ? {} : null),
      run: async () => { // this device locks first (allOff), whatever the server then says
        const r = await allOff('voice');
        let say = (r.server ? OFF_SAY.all : OFF_SAY.local).replace('{h}', honorific());
        if (r.server && r.armed === true) { say += ' ' + OFF_SAY.armed; openHome(); }
        return { say };
      },
    });
    registered = true;
  } catch (_) { registered = true; /* already registered by another copy of this page's module */ }
  return registered;
}
if (!registerVoice()) {
  document.addEventListener('DOMContentLoaded', registerVoice, { once: true });
  window.addEventListener('load', registerVoice, { once: true });
}
if (S.locked) emit('boot');

const api = Object.freeze({
  locked: () => S.locked, live, lock, unlock, start, stop: (why) => stop(why || 'panel'), frame, photo, onChange,
  facing: () => S.facing, useFacing: (f) => { if (FACING.includes(f)) S.facing = f; return S.facing; },
  phrases: () => OFF_PHRASES,
  spot, useSpot, recheck, allOff, blocked: () => S.blocked, keepWhile,
});
window.JarvisCamera = api;
if (M) M.part('camera', api);
