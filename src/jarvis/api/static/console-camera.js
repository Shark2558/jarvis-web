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
// While any track is live a "Camera on" chip with Stop stays on screen (beside the dot Android itself draws). The camera
// stops by itself when the page is hidden (another app, the screen locks, the tab is left), and when nothing has used a
// frame for 10 minutes. "Jarvis, cameras off" (R5's local router, so it works with the AI off) locks THIS device's
// camera and says so; it never touches the home burglar camera (disarming stays a card with his passkey, R3 D8), and no
// voice command can switch a camera on. Nothing here talks to the server. ASCII source; textContent only.
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

function readLock() { try { return localStorage.getItem(KEY) === '1'; } catch (_) { return false; } }
function writeLock(on) {
  try { if (on) localStorage.setItem(KEY, '1'); else localStorage.removeItem(KEY); } catch (_) { /* read back below */ }
  return readLock() === on;
}
const S = { locked: readLock(), streams: new Set(), facing: 'environment', used: 0, idle: 0, wake: null, gen: 0 };
const subs = new Set();
const video = document.createElement('video');
video.muted = true;
video.playsInline = true;
video.setAttribute('playsinline', '');
video.setAttribute('aria-label', 'The live picture, on this device only');
const canvas = document.createElement('canvas');

const activated = () => { const ua = navigator.userActivation; return !!(ua && ua.isActive); };
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
  if (!wl || typeof wl.request !== 'function' || S.wake) return;
  wl.request('screen').then((w) => { if (live()) S.wake = w; else w.release().catch(() => {}); }, () => {});
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
  const facing = FACING.includes(opts && opts.facing) ? opts.facing : S.facing;
  S.facing = facing;
  stop('restart');
  const my = S.gen;
  const stream = await md.getUserMedia({ audio: false, video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } } });
  if (S.locked || my !== S.gen) { // switched off (or stopped) while the browser asked: nothing stays live
    stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
    throw err(S.locked ? 'camera_off' : 'stopped', S.locked ? OFF_TEXT : 'The camera was stopped.');
  }
  S.streams.add(stream);
  stream.getTracks().forEach((t) => t.addEventListener('ended', () => { if (!live()) stop('ended'); }));
  video.srcObject = stream;
  try { await video.play(); } catch (_) { /* a muted inline video plays; the frames still arrive */ }
  touch();
  watchIdle();
  keepAwake();
  emit('start');
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
  ctx.drawImage(video, 0, 0, w, h);
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
document.addEventListener('visibilitychange', () => { if (document.hidden) stop('hidden'); });
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
let registered = false;
function registerVoice() {
  const C = window.JarvisVoiceCommands;
  if (registered || !C || typeof C.register !== 'function') return registered;
  const said = new Set(OFF_PHRASES.map((p) => C.normalise(p)));
  try {
    C.register('camera.off', {
      match: (norm) => (said.has(norm) ? {} : null),
      run: () => { lock('voice'); return { say: 'The camera on this device is off, ' + honorific() + '.' }; },
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
});
window.JarvisCamera = api;
if (M) M.part('camera', api);
