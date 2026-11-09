// src/jarvis/api/static/console-voice-capture.js — slice 9 D4 (docs/plans/phase1-slice9-voice.md):
// the microphone, one capture pipeline for everything that listens. No build step; CSP 'self'.
//   window.JarvisAudio  open() → Promise (getUserMedia with echo cancellation, noise suppression and
//                       auto gain; call it from a user gesture or the owner's "Hey Jarvis" switch),
//                       subscribe(fn) → unsubscribe; fn gets Int16Array(1280) frames at 16 kHz (80 ms,
//                       read-only: every subscriber sees the same array), level() → 0..1 RMS now,
//                       close(), resume(), isOpen(), suspended(), SAMPLE_RATE, FRAME,
//                       onEnd(fn) → unsubscribe: fn({reason: 'ended'}) when the microphone stops by
//                       itself (unplugged, switched off, permission taken back), after it closed.
//                       Overlapping open() / close() calls are safe: each open() builds its own
//                       stream and context, and one that close() (or a newer open) made stale stops
//                       its own tracks and rejects with .code 'closed'; only the newest is shared.
//                       lock(by) / unlock(by) → bool / locked() / onLock(fn): the hard microphone lock
//                       (R5 D11, docs/plans/r5-voice.md). While locked open() rejects with .code
//                       'mic_off' and prime() does nothing. lock() closes the microphone, aborts every
//                       recogniser made by recognizer() and persists localStorage['jarvis_mic_off_v1'],
//                       so a reload stays locked and other tabs follow (storage event). unlock() is
//                       true only inside a real click, tap or key press (user activation) and never
//                       opens the microphone. Fires jarvis:mic-lock {locked, by}.
//                       recognizer() is the only place SpeechRecognition is built (throws 'mic_off' or
//                       'unsupported'). setInput(id | null) / inputId(): the next open() asks for that
//                       device; if it is gone, one retry on the default input fires jarvis:audio-route
//                       {input, reason: 'input_missing'}. trackLabel(): the open track's name.
//                       The wake-word module consumes the same frames:
//                       JarvisWake.start({subscribe: JarvisAudio.subscribe, sampleRate: 16000}, onWake).
//   window.JarvisWav    encode(frames | Int16Array, rate = 16000) → ArrayBuffer (RIFF/WAVE PCM16 mono).
//   window.JarvisVad    create(opts) → {push(frame) → event | null, frames(), ms()}: an energy VAD.
//                       Events: {type: 'start'} once speech begins; {type: 'end', frames} after
//                       ~1.2 s of trailing silence; {type: 'timeout'} after 6 s with no speech;
//                       {type: 'max', frames} at 30 s. Options (R5 D4): endSilenceMs, noSpeechMs, maxMs,
//                       seed (frames that already count as speech: an interruption's first words),
//                       strictAfterMs / strictRatio / strictFrames (standing by: after that long
//                       without speech a start needs a firmer, longer sound). `frames` keeps ~320 ms before the speech
//                       began and ~400 ms after it ended.
// Audio never leaves this file: frames go to subscribers in this page only, and nothing is stored.
(() => {
  'use strict';
  const SAMPLE_RATE = 16000;
  const FRAME = 1280;
  const FRAME_MS = (FRAME / SAMPLE_RATE) * 1000; // 80
  const WORKLET_URL = '/static/voice-capture-worklet.js';

  const RESUME_WAIT_MS = 2000; // a resume() the browser never settles must not hang its caller

  // ================================================================================== capture
  // `live` is the one open microphone: {ctx, stream, source, node, analyser, probe}. A build in
  // progress keeps its pieces in its own object and only becomes `live` if no close() came while it
  // awaited (`gen` counts closes). `primed` is an AudioContext made inside a tap, for the next build.
  let live = null, primed = null, pending = null, gen = 0;
  const subs = new Set(), endSubs = new Set(), lockSubs = new Set();
  let inputId = null;                    // the chosen microphone (null: the system default)

  function fail(code, cause) {
    const e = new Error(code); e.code = code; e.cause = cause; return e;
  }
  /** Why the microphone could not open, in one word the console turns into help text. */
  function reason(err) {
    const n = err && err.name;
    if (n === 'NotAllowedError' || n === 'SecurityError' || n === 'PermissionDeniedError') return 'blocked';
    if (n === 'NotFoundError' || n === 'OverconstrainedError' || n === 'DevicesNotFoundError') return 'no_mic';
    if (n === 'NotReadableError' || n === 'TrackStartError' || n === 'AbortError') return 'busy';
    return 'failed';
  }
  const AC = () => window.AudioContext || window.webkitAudioContext || null;
  function supported() {
    const C = AC();
    return !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function' &&
      C && 'audioWorklet' in C.prototype && typeof window.AudioWorkletNode === 'function');
  }
  function deliver(frame) {
    if (!(frame instanceof Int16Array) || frame.length !== FRAME) return;
    subs.forEach(fn => { try { fn(frame); } catch (_) { /* one listener must not silence the rest */ } });
  }
  const quietly = (p) => { if (p && typeof p.catch === 'function') p.catch(() => {}); };
  function closeContext(c) { if (c && c.state !== 'closed') { try { quietly(c.close()); } catch (_) {} } }
  /** Undo one build: only what that build made (its node, source, tracks and context). */
  function release(own) {
    if (own.node) { try { own.node.port.onmessage = null; own.node.disconnect(); } catch (_) {} }
    if (own.source) { try { own.source.disconnect(); } catch (_) {} }
    if (own.stream) own.stream.getTracks().forEach(t => { try { t.stop(); } catch (_) {} });
    closeContext(own.ctx);
  }

  // ================================================================================== mic lock (D11)
  const LOCK_KEY = 'jarvis_mic_off_v1';
  const LOCK_BY = ['button', 'shortcut', 'voice', 'panel', 'storage', 'boot'];
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  function readLock() { try { return localStorage.getItem(LOCK_KEY) === '1'; } catch (_) { return false; } }
  function writeLock(on) {
    try { if (on) localStorage.setItem(LOCK_KEY, '1'); else localStorage.removeItem(LOCK_KEY); } catch (_) { /* read back below */ }
    return readLock() === on;               // false: the browser blocked storage, so "off" will not survive a reload
  }
  let locked = readLock();               // read at load: this script is first, so nothing opens before it
  const recs = new Set();                // recognisers made by recognizer(), aborted on lock
  const who = (by) => (LOCK_BY.includes(by) ? by : 'button');
  function announce(by, persisted) {
    const d = { locked, by };
    if (persisted === false) d.persisted = false;   // only when storage failed: the frozen {locked, by} shape stays otherwise
    lockSubs.forEach(fn => { try { fn(d); } catch (_) {} });
    emit('jarvis:mic-lock', d);
  }
  function applyLock(on, by, persist) {
    if (locked === on) return;
    locked = on;
    const kept = persist ? writeLock(on) : true;
    if (on) {
      close();
      recs.forEach(r => { try { r.abort(); } catch (_) {} });
      recs.clear();
    }
    announce(by, kept);
  }
  const lock = (by) => applyLock(true, who(by), true);
  /** True only for a real gesture; it never opens the microphone. */
  function unlock(by) {
    const ua = navigator.userActivation;
    if (!(ua && ua.isActive)) return false;
    applyLock(false, who(by), true);
    return true;
  }
  function onLock(fn) {
    if (typeof fn !== 'function') return () => {};
    lockSubs.add(fn);
    return () => { lockSubs.delete(fn); };
  }
  /** The only SpeechRecognition constructor in the console. */
  function recognizer() {
    if (locked) throw fail('mic_off');
    const R = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!R) throw fail('unsupported');
    const rec = new R();
    recs.add(rec);
    if (typeof rec.addEventListener === 'function') rec.addEventListener('end', () => recs.delete(rec));
    else if (recs.size > 20) recs.delete(recs.values().next().value);
    return rec;
  }
  // Another tab's change only counts when the browser itself raised the event for this origin's localStorage:
  // a script's own StorageEvent (isTrusted false) must never switch the microphone on (SM1).
  window.addEventListener('storage', (e) => {
    if (!e.isTrusted || e.storageArea !== localStorage) return;
    if (e.key === LOCK_KEY || e.key === null) applyLock(readLock(), 'storage', false);
  });
  if (locked) {
    const boot = () => announce('boot');
    if (document.readyState === 'complete') boot(); else document.addEventListener('DOMContentLoaded', boot, { once: true });
  }

  function requestStream(id) {
    const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
    if (id) audio.deviceId = { exact: id };
    return navigator.mediaDevices.getUserMedia({ audio });
  }
  async function build(c, my) {
    const own = { ctx: c, stream: null, source: null, node: null, analyser: null, probe: null };
    const stale = () => my !== gen;
    try {
      try {
        own.stream = await requestStream(inputId);
      } catch (err) {
        if (inputId && err && err.name === 'OverconstrainedError') {   // the chosen microphone is gone
          emit('jarvis:audio-route', { input: { id: inputId, label: '' }, reason: 'input_missing' });
          if (stale() || locked) throw fail('closed');   // the microphone was switched off meanwhile: no second request
          try { own.stream = await requestStream(null); } catch (err2) { throw fail(reason(err2), err2); }
        } else throw fail(reason(err), err);
      }
      if (stale()) throw fail('closed');
      try { await c.audioWorklet.addModule(WORKLET_URL); } catch (err) { throw fail('failed', err); }
      if (stale()) throw fail('closed');
      const tracks = own.stream.getAudioTracks();
      if (!tracks.length || tracks.some(t => t.readyState === 'ended')) throw fail('no_mic');
      own.source = c.createMediaStreamSource(own.stream);
      own.node = new window.AudioWorkletNode(c, 'jarvis-capture', {
        numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit', channelInterpretation: 'speakers',
      });
      own.node.port.onmessage = (e) => { if (live === own) deliver(e.data); };
      own.analyser = c.createAnalyser(); own.analyser.fftSize = 1024; own.analyser.smoothingTimeConstant = 0.2;
      own.probe = new Float32Array(own.analyser.fftSize);
      own.source.connect(own.node); own.source.connect(own.analyser);
      tracks.forEach(t => t.addEventListener('ended', () => ended(own)));
      live = own;
    } catch (err) {
      release(own);
      throw err;
    }
  }
  /** The microphone stopped by itself (unplugged, switched off, permission revoked). */
  function ended(own) {
    if (live !== own) return;
    close();
    endSubs.forEach(fn => { try { fn({ reason: 'ended' }); } catch (_) {} });
  }

  /** Make the AudioContext now (inside a tap) without asking for the microphone yet; a context
   *  already made (open, or on its way) is resumed instead, while the tap still counts. */
  function prime() {
    if (locked || !supported()) return;
    const have = live ? live.ctx : pending && pending.gen === gen ? pending.ctx : primed;
    if (have) { if (have.state === 'suspended') { try { quietly(have.resume()); } catch (_) {} } return; }
    try { primed = new (AC())(); } catch (_) { primed = null; return; }
    try { quietly(primed.resume()); } catch (_) {}
  }
  /** Opens the microphone (once; later calls share it). The AudioContext is made before the first
   *  await, so a tap's user activation still counts when the browser asks to start audio. */
  function open() {
    if (locked) return Promise.reject(fail('mic_off'));
    if (live) return Promise.resolve();
    if (pending && pending.gen === gen) return pending.promise;
    if (!supported()) return Promise.reject(fail('unsupported'));
    prime();
    const c = primed;
    primed = null;
    if (!c) return Promise.reject(fail('unsupported'));
    const my = gen;
    const p = build(c, my).finally(() => { if (pending && pending.promise === p) pending = null; });
    pending = { gen: my, promise: p, ctx: c };
    return p;
  }
  /** Closes the microphone. A build still on its way notices (gen) and undoes itself. */
  function close() {
    gen++;
    pending = null;
    const own = live;
    live = null;
    if (own) release(own);
    if (primed) { closeContext(primed); primed = null; }
  }
  /** After a page load without a gesture the context may start suspended (autoplay rules). Settles
   *  within RESUME_WAIT_MS even if the browser keeps the promise pending. */
  function resume() {
    const c = live ? live.ctx : primed;
    if (!c || c.state !== 'suspended') return Promise.resolve();
    let p;
    try { p = Promise.resolve(c.resume()).catch(() => {}); } catch (_) { return Promise.resolve(); }
    return Promise.race([p, new Promise(r => setTimeout(r, RESUME_WAIT_MS))]);
  }
  function onEnd(fn) {
    if (typeof fn !== 'function') return () => {};
    endSubs.add(fn);
    return () => { endSubs.delete(fn); };
  }
  function subscribe(fn) {
    if (typeof fn !== 'function') return () => {};
    subs.add(fn);
    let on = true;
    return () => { if (on) { on = false; subs.delete(fn); } };
  }
  /** RMS of the last ~20 ms of microphone audio, 0..1 (0 while closed). Real data only. */
  function level() {
    if (!live) return 0;
    const { analyser, probe } = live;
    analyser.getFloatTimeDomainData(probe);
    let sum = 0;
    for (let i = 0; i < probe.length; i++) sum += probe[i] * probe[i];
    return Math.min(1, Math.sqrt(sum / probe.length));
  }
  /** A new listening turn starts on a clean frame boundary. */
  function flush() { if (live) { try { live.node.port.postMessage('flush'); } catch (_) {} } }

  function setInput(id) {
    inputId = typeof id === 'string' && id.length > 0 && id.length <= 400 ? id : null;
  }
  function trackLabel() {
    const t = live && live.stream ? live.stream.getAudioTracks()[0] : null;
    return t && typeof t.label === 'string' ? t.label : '';
  }

  window.JarvisAudio = Object.freeze({
    SAMPLE_RATE, FRAME,
    supported, prime, open, close, resume, subscribe, level, flush, onEnd,
    lock, unlock, onLock, recognizer, setInput, trackLabel,
    locked: () => locked,
    inputId: () => inputId,
    isOpen: () => !!live,
    suspended: () => !!(live && live.ctx.state === 'suspended'),
  });

  // ================================================================================== WAV
  /** RIFF/WAVE, PCM 16-bit little-endian, mono: the only format POST /v1/voice/transcribe takes. */
  function encode(frames, rate = SAMPLE_RATE) {
    const list = frames instanceof Int16Array ? [frames] : Array.from(frames || []).filter(f => f instanceof Int16Array);
    const samples = list.reduce((n, f) => n + f.length, 0);
    const bytes = samples * 2;
    const buf = new ArrayBuffer(44 + bytes), v = new DataView(buf);
    const ascii = (at, s) => { for (let i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i)); };
    ascii(0, 'RIFF'); v.setUint32(4, 36 + bytes, true); ascii(8, 'WAVE');
    ascii(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    ascii(36, 'data'); v.setUint32(40, bytes, true);
    let at = 44;
    list.forEach(f => { for (let i = 0; i < f.length; i++, at += 2) v.setInt16(at, f[i], true); });
    return buf;
  }
  window.JarvisWav = Object.freeze({ encode });

  // ================================================================================== VAD
  // Energy only, on 80 ms frames: cheap, deterministic, and the same on every browser. The noise
  // floor adapts while nobody speaks; speech must beat it by ~10 dB (and an absolute floor) for two
  // frames in a row to start, and fall back under a lower threshold for `endSilenceMs` to end.
  const VAD_DEFAULTS = { endSilenceMs: 1200, noSpeechMs: 6000, maxMs: 30000, prerollMs: 320, tailMs: 400,
    floor: 0.012, ratio: 3.2, endRatio: 2.0, startFrames: 2,
    strictAfterMs: 0, strictRatio: 4.0, strictFrames: 4, seed: null };
  function rms(frame) {
    let sum = 0;
    for (let i = 0; i < frame.length; i++) { const x = frame[i] / 32768; sum += x * x; }
    return Math.sqrt(sum / (frame.length || 1));
  }
  function create(opts) {
    const o = Object.assign({}, VAD_DEFAULTS, opts || {});
    const n = (ms) => Math.max(1, Math.round(ms / FRAME_MS));
    const END = n(o.endSilenceMs), NONE = n(o.noSpeechMs), MAX = n(o.maxMs), PRE = n(o.prerollMs), TAIL = n(o.tailMs);
    let count = 0, noise = null, loud = 0, quiet = 0, started = false, done = false, lastSpeech = -1;
    const pre = [], kept = [];
    // seed: frames heard before this VAD was made (an interruption): the turn starts with them.
    const seed = Array.isArray(o.seed) ? o.seed.filter(f => f instanceof Int16Array) : [];
    if (seed.length) { started = true; kept.push(...seed); lastSpeech = kept.length - 1; }
    function result(type) {
      done = true;
      if (type === 'timeout') return { type };
      const keep = Math.min(kept.length, (lastSpeech < 0 ? kept.length : lastSpeech + 1) + TAIL);
      return { type, frames: kept.slice(0, keep) };
    }
    function push(frame) {
      if (done || !(frame instanceof Int16Array)) return null;
      count++;
      const e = rms(frame);
      if (noise === null) noise = Math.min(e, o.floor);
      // strict mode (standing by): after strictAfterMs without speech a turn needs a firmer start
      const strict = !started && o.strictAfterMs > 0 && count * FRAME_MS >= o.strictAfterMs;
      const startAt = Math.max(o.floor, noise * (strict ? o.strictRatio : o.ratio)), need = strict ? o.strictFrames : o.startFrames;
      const endAt = Math.max(o.floor * 0.75, noise * o.endRatio);
      if (!started) {
        pre.push(frame); if (pre.length > PRE + Math.max(o.startFrames, o.strictFrames)) pre.shift();
        if (e >= startAt) loud++; else { loud = 0; noise = noise * 0.9 + Math.min(e, startAt) * 0.1; }
        if (loud >= need) {
          started = true; kept.push(...pre); pre.length = 0; lastSpeech = kept.length - 1; quiet = 0;
          return { type: 'start' };
        }
        if (count >= NONE) return result('timeout');
        return null;
      }
      kept.push(frame);
      if (e >= endAt) { quiet = 0; lastSpeech = kept.length - 1; } else quiet++;
      if (quiet >= END) return result('end');
      if (count >= MAX) return result('max');
      return null;
    }
    return {
      push,
      started: () => started,
      /** What was kept so far (a tap that ends listening early sends this). */
      frames: () => (started ? kept.slice() : []),
      ms: () => count * FRAME_MS,
    };
  }
  window.JarvisVad = Object.freeze({ create, rms, FRAME_MS });
})();
