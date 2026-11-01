// static/console-wakeword.js — "Hey Jarvis", detected entirely on this device (slice 9, D12).
//
// A JavaScript port of openWakeWord's streaming inference (openwakeword 0.6.0: utils.py
// AudioFeatures._streaming_features/_streaming_melspectrogram and model.py Model.predict;
// Copyright 2022 David Scripka; Apache-2.0, /static/wakeword/LICENSE-openwakeword-code.txt),
// running the openWakeWord v0.5.1 models (CC BY-NC-SA 4.0: personal, non-commercial use only;
// /static/wakeword/LICENSE.txt) on onnxruntime-web 1.30.0 (MIT), single-threaded WebAssembly on
// the page's main thread. Upstream: github.com/dscripka/openWakeWord.
// Changes from upstream: rewritten in JavaScript for onnxruntime-web; the 16-frame embedding
// history is seeded with fixed-seed mulberry32 noise instead of numpy random noise (same range);
// audio is consumed in whole 1280-sample frames; a wake needs 2 consecutive frames at or above
// the threshold, then a 2 s cooldown and a full reset (openWakeWord's own reset()).
//
// Privacy: audio frames never leave this tab. The only requests this file makes are the
// same-origin static files named below, once, when the owner switches the wake word on.
//
//   window.JarvisWake = { supported(), load(), start(source, onWake), pause(), resume(), stop(),
//                         state, threshold }
//   source = { subscribe(fn(Int16Array(1280) at 16 kHz)) -> unsubscribe, sampleRate: 16000 }
//   onWake({ score }) is called at most once per 2 s cooldown.
//   load() rejects with an Error whose .code is 'load_failed' or 'unsupported' (state 'error');
//   start() throws .code 'not_loaded' before a successful load(), 'bad_source' / 'bad_callback'
//   for a wrong argument. state turns 'error' if inference fails or cannot keep up.
(() => {
  'use strict';

  const ORT_BASE = '/static/vendor/ort-1.30.0/';
  const MODEL_BASE = '/static/wakeword/oww-0.5.1/';
  const MEL_MODEL = 'melspectrogram.onnx';
  const EMBEDDING_MODEL = 'embedding_model.onnx';
  const WAKE_MODEL = 'hey_jarvis_v0.1.onnx';

  // openWakeWord's fixed geometry.
  const SAMPLE_RATE = 16000;
  const FRAME = 1280; // 80 ms: one model step
  const MEL_CONTEXT = 160 * 3; // samples of history each melspectrogram step re-reads
  const MEL_BINS = 32;
  const MEL_WINDOW = 76; // melspectrogram frames per embedding
  const MEL_STRIDE = 8; // between embeddings (used when seeding the history)
  const EMB_DIM = 96;
  const EMB_FRAMES = 16; // embeddings the hey_jarvis model reads (1.28 s)
  const WARMUP_FRAMES = 5; // openWakeWord reports 0 for the first 5 frames after a reset
  const INIT_NOISE_SEED = 0x4a415256; // tests/fixtures/wakeword/make_reference.py uses the same
  const INIT_NOISE_SAMPLES = SAMPLE_RATE * 4;
  const INIT_NOISE_LOW = -1000;
  const INIT_NOISE_SPAN = 2000;

  // Detection.
  const DEFAULT_THRESHOLD = 0.5; // openWakeWord's recommended default for its models
  const PATIENCE_FRAMES = 2; // consecutive frames at or above the threshold
  const COOLDOWN_MS = 2000;
  const MAX_BACKLOG = 12; // frames (~1 s) waiting for inference before we drop them and resync
  const OVERLOAD_LIMIT = 3; // drops within OVERLOAD_WINDOW_MS: this device cannot keep up
  const OVERLOAD_WINDOW_MS = 30000;

  // The smallest module using a WebAssembly SIMD instruction (onnxruntime-web's own probe):
  // its only binary needs SIMD.
  const SIMD_PROBE = [0, 97, 115, 109, 1, 0, 0, 0, 1, 4, 1, 96, 0, 0, 3, 2, 1, 0, 10, 30, 1, 28, 0,
    65, 0, 253, 15, 253, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 253, 186, 1, 26, 11];

  const ERROR_TEXT = {
    unsupported: 'This browser cannot run the wake word.',
    load_failed: 'The wake word could not be loaded.',
    not_loaded: 'Load the wake word first.',
    bad_source: 'The audio source must give 16 kHz frames.',
    bad_callback: 'onWake must be a function.',
    inference_failed: 'The wake word stopped working.',
    too_slow: 'This device cannot run the wake word in real time.',
  };

  // A test page may set window.__jarvisWakeTest = {} before this file runs; nothing else does.
  const hooks = window.__jarvisWakeTest && typeof window.__jarvisWakeTest === 'object'
    ? window.__jarvisWakeTest
    : null;

  let state = 'idle';
  let threshold = DEFAULT_THRESHOLD;
  let ort = null;
  let sessions = null; // { mel, emb, wake } once loaded
  let loading = null;
  let initFeatures = null; // the last 16 embeddings of the seed noise
  let noiseHead = [];

  // Listening.
  let unsubscribe = null;
  let onWakeCallback = null;
  let queue = [];
  let pending = null; // a partial frame from a source that does not send exactly 1280 samples
  let pumping = false;
  let idleWaiters = [];
  let generation = 0; // bumped whenever in-flight results must be discarded
  let consecutive = 0;
  let lastWakeAt = -Infinity;
  let overloads = [];
  let processed = 0;
  let dropped = 0;
  let lastError = null;

  // The streaming pipeline (openWakeWord's AudioFeatures buffers, trimmed to what is read).
  const raw = new Float32Array(FRAME + MEL_CONTEXT); // newest samples, oldest first
  let rawLength = 0;
  const mel = new Float32Array(MEL_WINDOW * MEL_BINS); // newest 76 melspectrogram frames
  const features = new Float32Array(EMB_FRAMES * EMB_DIM); // newest 16 embeddings
  let predictions = 0;
  let needsReset = true;

  const clock = () => (hooks && typeof hooks.now === 'function' ? hooks.now() : performance.now());

  function wakeError(code, cause) {
    const err = new Error(ERROR_TEXT[code] || ERROR_TEXT.load_failed);
    err.code = code;
    if (cause !== undefined) err.cause = cause;
    return err;
  }

  function report(err) {
    if (typeof window.reportError === 'function') window.reportError(err);
  }

  function supported() {
    try {
      return typeof WebAssembly === 'object'
        && typeof WebAssembly.instantiate === 'function'
        && WebAssembly.validate(new Uint8Array(SIMD_PROBE))
        && typeof window.AudioWorkletNode === 'function';
    } catch (_) {
      return false;
    }
  }

  // ---- loading --------------------------------------------------------------------------------
  async function fetchModel(name) {
    const r = await fetch(MODEL_BASE + name, { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + name);
    return new Uint8Array(await r.arrayBuffer());
  }

  function mulberry32(seed) {
    let a = seed | 0;
    return () => {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function tensor(data, dims) {
    return new ort.Tensor('float32', data, dims);
  }

  async function run(session, data, dims) {
    const out = await session.run({ [session.inputNames[0]]: tensor(data, dims) });
    return out[session.outputNames[0]].data;
  }

  // openWakeWord starts every stream with embeddings of 4 s of low random noise in its history
  // (AudioFeatures.__init__/reset), computed the same way as a whole clip: one melspectrogram,
  // 76-frame windows every 8 frames, one embedding batch.
  async function seedHistory(ready) {
    const next = mulberry32(INIT_NOISE_SEED);
    const noise = new Float32Array(INIT_NOISE_SAMPLES);
    for (let i = 0; i < noise.length; i++) {
      noise[i] = Math.floor(next() * INIT_NOISE_SPAN) + INIT_NOISE_LOW;
    }
    noiseHead = Array.from(noise.subarray(0, 8));
    const spec = await run(ready.mel, noise, [1, noise.length]);
    const frames = spec.length / MEL_BINS;
    const starts = [];
    for (let s = 0; s + MEL_WINDOW <= frames; s += MEL_STRIDE) starts.push(s);
    const windowSize = MEL_WINDOW * MEL_BINS;
    const batch = new Float32Array(starts.length * windowSize);
    starts.forEach((s, b) => {
      for (let i = 0; i < windowSize; i++) batch[b * windowSize + i] = spec[s * MEL_BINS + i] / 10 + 2;
    });
    const emb = await run(ready.emb, batch, [starts.length, MEL_WINDOW, MEL_BINS, 1]);
    return Float32Array.from(emb.subarray(emb.length - EMB_FRAMES * EMB_DIM));
  }

  async function loadOnce() {
    let mod;
    try {
      mod = await import(ORT_BASE + 'ort.wasm.min.mjs');
    } catch (err) {
      throw wakeError('load_failed', err);
    }
    const o = mod.InferenceSession ? mod : mod.default;
    o.env.wasm.numThreads = 1;
    o.env.wasm.proxy = false;
    o.env.wasm.wasmPaths = ORT_BASE;
    const bytes = await Promise.all([MEL_MODEL, EMBEDDING_MODEL, WAKE_MODEL].map(fetchModel));
    const options = { executionProviders: ['wasm'], graphOptimizationLevel: 'all' };
    const created = [];
    try {
      for (const b of bytes) created.push(await o.InferenceSession.create(b, options)); // in turn
      ort = o;
      const ready = { mel: created[0], emb: created[1], wake: created[2] };
      initFeatures = await seedHistory(ready);
      sessions = ready; // only now: load() and start() treat a set `sessions` as fully loaded
      needsReset = true;
    } catch (err) {
      created.forEach((s) => s.release().catch(report));
      throw err;
    }
  }

  function load() {
    if (sessions) return Promise.resolve();
    if (loading) return loading;
    if (!supported()) {
      state = 'error';
      return Promise.reject(wakeError('unsupported'));
    }
    state = 'loading';
    loading = loadOnce().then(
      () => {
        loading = null;
        if (state === 'loading') state = 'idle';
      },
      (err) => {
        loading = null;
        state = 'error';
        throw err && err.code === 'load_failed' ? err : wakeError('load_failed', err);
      },
    );
    return loading;
  }

  // ---- the streaming pipeline -----------------------------------------------------------------
  // Drop the oldest values of `buf` and append `values` at its end.
  function shiftIn(buf, values) {
    const n = Math.min(values.length, buf.length);
    buf.copyWithin(0, n);
    buf.set(values.subarray(values.length - n), buf.length - n);
  }

  function resetPipeline() {
    rawLength = 0;
    mel.fill(1); // AudioFeatures.melspectrogram_buffer = np.ones((76, 32))
    features.set(initFeatures);
    predictions = 0;
    consecutive = 0;
    needsReset = false;
  }

  // One 80 ms frame → openWakeWord's score for it (Model.predict on a 1280-sample frame).
  async function step(frame) {
    // raw_data_buffer: the melspectrogram re-reads the 480 samples before this frame
    const keep = Math.min(rawLength, MEL_CONTEXT);
    raw.copyWithin(0, rawLength - keep, rawLength);
    raw.set(frame, keep);
    rawLength = keep + frame.length;

    const spec = await run(sessions.mel, raw.slice(0, rawLength), [1, rawLength]);
    const rows = new Float32Array(spec.length);
    for (let i = 0; i < spec.length; i++) rows[i] = spec[i] / 10 + 2; // openWakeWord's transform
    shiftIn(mel, rows);

    const emb = await run(sessions.emb, mel.slice(), [1, MEL_WINDOW, MEL_BINS, 1]);
    shiftIn(features, emb);

    const out = await run(sessions.wake, features.slice(), [1, EMB_FRAMES, EMB_DIM]);
    const score = predictions < WARMUP_FRAMES || !Number.isFinite(out[0]) ? 0 : out[0];
    predictions += 1;
    return score;
  }

  // ---- listening ------------------------------------------------------------------------------
  function settleIdle() {
    if (pumping || queue.length) return;
    const waiters = idleWaiters;
    idleWaiters = [];
    waiters.forEach((resolve) => resolve());
  }

  function discardInFlight() {
    queue = [];
    pending = null;
    generation += 1;
    needsReset = true;
    consecutive = 0;
  }

  function detach() {
    const off = unsubscribe;
    unsubscribe = null;
    onWakeCallback = null;
    discardInFlight();
    if (off) {
      try {
        off();
      } catch (err) {
        report(err);
      }
    }
  }

  function fail(code, cause) {
    lastError = wakeError(code, cause);
    detach();
    state = 'error';
    settleIdle();
  }

  function overload() {
    dropped += queue.length;
    discardInFlight();
    const now = clock();
    overloads = overloads.filter((t) => now - t < OVERLOAD_WINDOW_MS).concat(now);
    if (overloads.length >= OVERLOAD_LIMIT) fail('too_slow');
  }

  function decide(score) {
    consecutive = score >= threshold ? consecutive + 1 : 0;
    if (consecutive < PATIENCE_FRAMES) return;
    const now = clock();
    if (now - lastWakeAt < COOLDOWN_MS) return;
    lastWakeAt = now;
    needsReset = true; // Model.reset(): fresh buffers and 5 warm-up frames before the next wake
    consecutive = 0;
    try {
      onWakeCallback({ score });
    } catch (err) {
      report(err); // the console's error; keep listening
    }
  }

  async function pump() {
    pumping = true;
    try {
      while (queue.length && state === 'listening') {
        const frame = queue.shift();
        if (needsReset) resetPipeline();
        const gen = generation;
        const score = await step(frame);
        if (gen !== generation || state !== 'listening') continue;
        processed += 1;
        decide(score);
      }
    } catch (err) {
      fail('inference_failed', err);
    } finally {
      pumping = false;
      settleIdle();
    }
  }

  function enqueue(frame) {
    if (queue.length >= MAX_BACKLOG) {
      overload();
      if (state !== 'listening') return;
    }
    queue.push(frame);
    if (!pumping) pump();
  }

  function onFrame(frame) {
    if (state !== 'listening' || !(frame instanceof Int16Array)) return;
    let data = frame;
    if (pending) {
      data = new Int16Array(pending.length + frame.length);
      data.set(pending);
      data.set(frame, pending.length);
      pending = null;
    }
    let at = 0;
    for (; at + FRAME <= data.length; at += FRAME) enqueue(data.slice(at, at + FRAME)); // copies
    if (at < data.length && state === 'listening') pending = data.slice(at);
  }

  function start(source, onWake) {
    if (!sessions) throw wakeError('not_loaded');
    if (!source || typeof source.subscribe !== 'function' || source.sampleRate !== SAMPLE_RATE) {
      throw wakeError('bad_source');
    }
    if (typeof onWake !== 'function') throw wakeError('bad_callback');
    detach();
    onWakeCallback = onWake;
    lastWakeAt = -Infinity;
    overloads = [];
    lastError = null;
    state = 'listening';
    const off = source.subscribe(onFrame);
    unsubscribe = typeof off === 'function' ? off : null;
  }

  function pause() {
    if (state !== 'listening') return;
    state = 'paused';
    discardInFlight();
  }

  function resume() {
    if (state !== 'paused') return;
    discardInFlight(); // the gap breaks the stream: start again from fresh buffers
    state = 'listening';
  }

  function stop() {
    if (state === 'loading') return;
    detach();
    state = 'idle';
    settleIdle();
  }

  if (hooks) {
    // Test-only: drive the pipeline frame by frame and compare with Python openWakeWord.
    hooks.process = async (frame) => {
      if (needsReset) resetPipeline();
      return step(Int16Array.from(frame));
    };
    hooks.reset = () => {
      needsReset = true;
    };
    hooks.idle = () => (pumping || queue.length
      ? new Promise((resolve) => idleWaiters.push(resolve))
      : Promise.resolve());
    hooks.stats = () => ({
      processed,
      dropped,
      lastError: lastError ? lastError.code : null,
      noiseHead: noiseHead.slice(),
    });
  }

  window.JarvisWake = Object.freeze({
    supported,
    load,
    start,
    pause,
    resume,
    stop,
    get state() {
      return state;
    },
    get threshold() {
      return threshold;
    },
    set threshold(value) {
      if (typeof value === 'number' && value > 0 && value < 1) threshold = value;
    },
  });
})();
