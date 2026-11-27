// src/jarvis/api/static/console-voiceprint.js - R5.2 row 84 (docs/plans/r5-2-voice.md 3.5, D6): the speaker check.
// A small speaker-embedding model runs in this browser (the vendored onnxruntime-web, single-threaded WebAssembly, the
// wake word's settings); the owner's voice print is made here, kept here and never leaves the device. No build step;
// CSP script-src 'self'.
//   window.JarvisVoicePrint
//     state()        'unsupported' | 'no_model' | 'none' | 'off' | 'loading' | 'ready' | 'error'
//     active()       true only when this device has a print, its switch is on and the model is loaded
//     verify(frames) -> Promise<'owner' | 'other' | 'short' | 'skip'>  for the console's 80 ms frames; 'skip' (no print,
//                    switched off, no model, a failure, too slow) means "do what JARVIS did before the speaker check"
//     measure(frames)-> Promise<{verdict, score, voicedMs}>
//     recordReading({onProgress}) -> {stop(), done: Promise<result>}   1 minute of reading, from a tap (it opens the mic)
//     offerSessionClip(pcm)   the voice session (V3) hands each clip's 16 kHz PCM here, on the laptop: only its
//                    embedding is kept, in memory, until the owner chooses useSession(); the audio is not kept
//     sessionCount(), useSession() -> Promise<result>
//     setOn(bool), isOn(), forget() -> Promise, info() -> {saved, made, count, quality, source} (never the numbers)
//     CHECK_MS       how long a check clip listens before it is judged (the barge-in hook reads it)
//   result = {ok: true, count, quality: 'good' | 'weak'} | {ok: false, reason}
// Fires jarvis:voiceprint {state} on every change.
// What it is for: barge-in by his voice only (console-voice-barge.js asks verify() before letting a voice stop JARVIS).
// What it is never for: it approves nothing. Not a tool call, a card, a passkey, an unlock or a Telegram approval;
// "spoken by the owner" is a display label at most (slice 9 D11 stands; tests/test_r52_v5_never_approves.py).
// Privacy: the print is encrypted (AES-GCM) with a key made in this browser that cannot be exported
// (extractable: false), both kept in this origin's IndexedDB: a copy of the stored record is not the numbers. Nothing
// here sends a request except the GET of the model file; no audio, embedding or print is logged, stored elsewhere or
// uploaded. The switch is per device (localStorage); forget() deletes the print and its key.
(() => {
  'use strict';
  const M = window.JarvisVoicePrintMath;
  const ORT_BASE = '/static/vendor/ort-1.30.0/';
  const MODEL_BASE = '/static/vendor/speaker/';   // + release + '/' + file (src/jarvis/api/speaker_assets.py)
  // The model slot: static/vendor/speaker/spk-1/MANIFEST.json "slot" names the model, its licence and where it comes
  // from. No file is shipped until its SHA-256 is pinned there and here; until then sha256 is null, state() is
  // 'no_model', nothing is fetched and barge-in works as it did before (tests/test_r52_v5_console.py).
  const SLOT = { id: 'wespeaker-voxceleb-campplus', release: 'spk-1', file: 'wespeaker-voxceleb-campplus.onnx',
    sha256: null, window: 'hamming', threshold: 0.45 };
  const OFF_KEY = 'jarvis_voiceprint_off_v1';
  const DB_NAME = 'jarvis-voiceprint', DB_STORE = 'v', AAD_PREFIX = 'jarvis-voiceprint-v1:';
  const CHECK_MS = 1200;                  // a barge-in check clip lasts 1.2 s, the 320 ms before the gate opened included
  const CHECK_TIMEOUT_MS = 2500;          // a check slower than this is 'skip': JARVIS is never stuck half-ducked
  const MAX_CHECK_S = 4;                  // only the last 4 s of a clip are judged
  // A test page may set window.__jarvisVoicePrintTest = {model: {...}, readMs, enrolMin} before this file runs;
  // nothing else does.
  const hooks = window.__jarvisVoicePrintTest && typeof window.__jarvisVoicePrintTest === 'object' ? window.__jarvisVoicePrintTest : null;
  const tuned = (k, v) => (hooks && Number.isInteger(hooks[k]) && hooks[k] > 0 ? hooks[k] : v);
  const READ_MS = tuned('readMs', 60000); // the reading: one minute
  const ENROL_MIN = tuned('enrolMin', 8); // pieces of 3 s with enough voice before a print is made
  const SESSION_MAX = 200;                // embeddings kept from a voice session
  const WEAK_MARGIN = 0.1;                // a print whose pieces agree less than threshold + this is 'weak'
  const MODEL = Object.freeze(Object.assign({}, SLOT, slotOverride(hooks && hooks.model)));
  const AAD = new TextEncoder().encode(AAD_PREFIX + MODEL.id);

  function slotOverride(o) {
    if (!o || typeof o !== 'object') return {};
    const out = {};
    ['id', 'release', 'file', 'sha256', 'window'].forEach((k) => { if (typeof o[k] === 'string') out[k] = o[k]; });
    if (typeof o.threshold === 'number' && o.threshold > 0 && o.threshold < 1) out.threshold = o.threshold;
    return out;
  }
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (text) => emit('jarvis:event', { kind: 'info', text, at: Date.now(), live: true });
  const fail = (code) => { const e = new Error(code); e.code = code; return e; };

  // ---- what this browser can do ----------------------------------------------------------------------------------
  function supported() {
    try {
      if (!M || typeof indexedDB === 'undefined' || !(window.crypto && crypto.subtle) || typeof WebAssembly !== 'object') return false;
      const W = window.JarvisWake;                                   // the wake word's probe: WebAssembly SIMD + AudioWorklet
      return W && typeof W.supported === 'function' ? W.supported() : true;
    } catch (_) { return false; }
  }

  // ---- the model -------------------------------------------------------------------------------------------------
  let ortLoad = null, model = null, modelLoad = null, modelState = MODEL.sha256 ? 'unknown' : 'absent';
  function runtime() {
    if (!ortLoad) {
      ortLoad = import(ORT_BASE + 'ort.wasm.min.mjs').then((mod) => {
        const o = mod.InferenceSession ? mod : mod.default;
        o.env.wasm.numThreads = 1; o.env.wasm.proxy = false; o.env.wasm.wasmPaths = ORT_BASE;
        return o;
      }, (e) => { ortLoad = null; throw e; });
    }
    return ortLoad;
  }
  async function sha256hex(bytes) {
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return Array.from(h, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  async function loadModelOnce() {
    if (!MODEL.sha256) throw fail('no_model');
    const r = await fetch(MODEL_BASE + MODEL.release + '/' + MODEL.file, { credentials: 'same-origin' });
    if (r.status === 404) throw fail('no_model');
    if (!r.ok) throw fail('load_failed');
    const bytes = new Uint8Array(await r.arrayBuffer());
    if ((await sha256hex(bytes)) !== MODEL.sha256) throw fail('no_model');   // other bytes than the pinned ones
    const o = await runtime();
    const s = await o.InferenceSession.create(bytes, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
    return { o, s };
  }
  function loadModel() {
    if (model) return Promise.resolve(model);
    if (!modelLoad) {
      modelState = MODEL.sha256 ? 'loading' : 'absent'; changed();
      modelLoad = loadModelOnce().then((m) => { model = m; modelState = 'ready'; changed(); return m; }, (e) => {
        modelLoad = null; modelState = e && e.code === 'no_model' ? 'absent' : 'failed'; changed();
        throw e;
      });
    }
    return modelLoad;
  }
  let queue = Promise.resolve();
  /** One clip's unit embedding (null when it is too short to say anything); one inference at a time. */
  function embed(pcm) {
    const job = queue.then(async () => {
      const f = M.features(pcm, MODEL);
      if (!f) return null;
      const { o, s } = await loadModel();
      const out = await s.run({ [s.inputNames[0]]: new o.Tensor('float32', f.data, f.dims) });
      return M.unit(out[s.outputNames[0]].data);
    });
    queue = job.catch(() => null);
    return job;
  }

  // ---- the encrypted store (this origin's IndexedDB) ---------------------------------------------------------------
  function open() {
    return new Promise((res, rej) => {
      const q = indexedDB.open(DB_NAME, 1);
      q.onupgradeneeded = () => q.result.createObjectStore(DB_STORE);
      q.onsuccess = () => res(q.result);
      q.onerror = () => rej(q.error);
      q.onblocked = () => rej(fail('blocked'));
    });
  }
  async function idb(mode, act) {
    const db = await open();
    try {
      return await new Promise((res, rej) => {
        const tx = db.transaction(DB_STORE, mode), st = tx.objectStore(DB_STORE), q = act(st);
        tx.oncomplete = () => res(q ? q.result : undefined);
        tx.onerror = tx.onabort = () => rej(tx.error);
      });
    } finally { db.close(); }
  }
  const get = (k) => idb('readonly', (st) => st.get(k));
  const put = (k, v) => idb('readwrite', (st) => st.put(v, k));
  async function deviceKey(create) {
    const k = await get('key');
    if (k || !create) return k || null;
    const made = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    await put('key', made);
    return made;
  }
  async function save(record) {
    const key = await deviceKey(true), iv = crypto.getRandomValues(new Uint8Array(12));
    const plain = new TextEncoder().encode(JSON.stringify(record));
    const data = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: AAD }, key, plain);
    await put('print', { v: 1, iv, data });
  }
  async function readPrint() {
    const rec = await get('print');
    if (!rec || !(rec.iv instanceof Uint8Array) || !(rec.data instanceof ArrayBuffer)) return null;
    const key = await deviceKey(false);
    if (!key) return null;
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.iv, additionalData: AAD }, key, rec.data);
    return parsePrint(JSON.parse(new TextDecoder().decode(plain)));
  }
  /** A stored print, field by field; anything of the wrong type (or another model's print) is no print. */
  function parsePrint(p) {
    if (!p || p.v !== 1 || p.model !== MODEL.id || !Number.isInteger(p.dims)) return null;
    const vector = M.decodeVector(p.vector, p.dims);
    if (!vector) return null;
    const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    return { vector, count: Number.isInteger(p.count) ? p.count : 0, selfMean: num(p.selfMean), selfMin: num(p.selfMin),
      made: typeof p.made === 'string' ? p.made.slice(0, 10) : '', source: p.source === 'session' ? 'session' : 'reading' };
  }
  const quality = (p) => (p.selfMean >= MODEL.threshold + WEAK_MARGIN && p.selfMin >= MODEL.threshold ? 'good' : 'weak');

  // ---- state -----------------------------------------------------------------------------------------------------
  const S = { ok: supported(), print: null, read: false, failed: false };
  const store = { get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }, set(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (_) {} } };
  const isOn = () => store.get(OFF_KEY) !== '1';
  function state() {
    if (!S.ok) return 'unsupported';
    if (modelState === 'absent') return 'no_model';
    if (!S.read) return 'loading';
    if (S.failed) return 'error';
    if (!S.print) return 'none';
    if (!isOn()) return 'off';
    if (modelState === 'failed') return 'error';
    return modelState === 'ready' ? 'ready' : 'loading';
  }
  const active = () => state() === 'ready';
  let last = null;
  function changed() { const st = state(); if (st !== last) { last = st; emit('jarvis:voiceprint', { state: st }); } }
  function prepare() { if (S.print && isOn() && modelState !== 'absent') loadModel().catch(() => {}); }

  // ---- checking a clip -------------------------------------------------------------------------------------------
  async function measure(frames) {
    if (!active()) return { verdict: 'skip', score: 0, voicedMs: 0 };
    const all = M.join(frames), pcm = all.subarray(Math.max(0, all.length - MAX_CHECK_S * M.RATE));
    const voiced = M.voicedMs(pcm);
    if (voiced < M.MIN_VOICED_MS) return { verdict: 'short', score: 0, voicedMs: voiced };
    const e = await embed(pcm), p = S.print;
    if (!e || !p || e.length !== p.vector.length) return { verdict: 'skip', score: 0, voicedMs: voiced };
    const score = M.cosine(e, p.vector);
    return { verdict: M.verdict(score, voiced, MODEL.threshold), score, voicedMs: voiced };
  }
  function verify(frames) {
    let timer = 0;
    const late = new Promise((res) => { timer = setTimeout(() => res('skip'), CHECK_TIMEOUT_MS); });
    const judged = measure(frames).then((r) => r.verdict, () => 'skip');
    return Promise.race([judged, late]).finally(() => clearTimeout(timer));
  }

  // ---- enrolment -------------------------------------------------------------------------------------------------
  async function finish(embeddings, source) {
    const p = M.buildPrint(embeddings.filter(Boolean));
    if (!p || p.count < ENROL_MIN) return { ok: false, reason: 'too_little' };
    const record = { v: 1, model: MODEL.id, dims: p.vector.length, vector: M.encodeVector(p.vector), count: p.count,
      selfMean: p.selfMean, selfMin: p.selfMin, made: new Date().toISOString().slice(0, 10), source };
    try { await save(record); } catch (_) { return { ok: false, reason: 'store_failed' }; }
    S.print = parsePrint(record); S.failed = false;
    store.set(OFF_KEY, null);                                       // a new print is on for this device
    log('Voice print saved on this device.');
    changed(); prepare();
    return { ok: true, count: p.count, quality: quality(S.print) };
  }
  async function embedPieces(pcm) {
    const out = [];
    for (const piece of M.segments(pcm)) out.push(await embed(piece));
    return out;
  }
  /** One minute of reading aloud on this device. Call it from a tap: it opens the microphone. */
  function recordReading(opts) {
    const A = window.JarvisAudio, o = opts || {};
    const chunks = [];
    let off = null, stopAt = 0, settle = null, t0 = 0, voiced = 0, stopped = false;
    const done = new Promise((res) => { settle = res; });
    function stop() {
      if (stopped) return;
      stopped = true; clearTimeout(stopAt);
      if (off) { off(); off = null; }
      const pcm = M.join(chunks);
      chunks.length = 0;
      embedPieces(pcm).then((e) => finish(e, 'reading'), () => ({ ok: false, reason: 'model' })).then(settle);
    }
    const abort = (reason) => { stopped = true; clearTimeout(stopAt); if (off) { off(); off = null; } chunks.length = 0; settle({ ok: false, reason }); };
    (async () => {
      if (!S.ok) return abort('unsupported');
      if (!A || A.locked()) return abort('mic_off');
      try { await loadModel(); } catch (_) { return abort('model'); }
      try { await A.open(); } catch (e) { return abort(e && e.code === 'mic_off' ? 'mic_off' : 'mic'); }
      if (stopped) return undefined;
      t0 = performance.now();
      off = A.subscribe((frame) => {
        if (stopped) return;
        if (A.locked()) { abort('mic_off'); return; }
        chunks.push(frame.slice());
        if (M.voicedMs(frame) > 0) voiced += M.FRAME_MS;
        if (typeof o.onProgress === 'function') { try { o.onProgress({ ms: performance.now() - t0, voicedMs: voiced, of: READ_MS }); } catch (_) {} }
      });
      stopAt = setTimeout(stop, READ_MS);
      return undefined;
    })();
    return { stop, done };
  }
  const session = [];
  /** A voice-session clip (Int16Array, 16 kHz mono): its pieces' embeddings are kept in memory, the audio is not. */
  function offerSessionClip(pcm) {
    if (!(pcm instanceof Int16Array) || !S.ok || modelState === 'absent' || session.length >= SESSION_MAX) return false;
    embedPieces(pcm).then((list) => {
      list.filter(Boolean).forEach((e) => { if (session.length < SESSION_MAX) session.push(e); });
      emit('jarvis:voiceprint', { state: state(), session: session.length });
    }, () => {});
    return true;
  }
  function useSession() {
    const list = session.splice(0, session.length);
    return finish(list, 'session');
  }

  // ---- the switch and forgetting ---------------------------------------------------------------------------------
  function setOn(on) {
    store.set(OFF_KEY, on ? null : '1');
    if (on) prepare();
    changed();
  }
  function forget() {
    return new Promise((res) => {
      let q = null;
      try { q = indexedDB.deleteDatabase(DB_NAME); } catch (_) { q = null; }
      const done = (ok) => { if (ok) { S.print = null; S.failed = false; store.set(OFF_KEY, null); log('Voice print forgotten on this device.'); } changed(); res(ok); };
      if (!q) { done(false); return; }
      q.onsuccess = () => done(true);
      q.onerror = q.onblocked = () => done(false);
    });
  }
  function info() {
    const p = S.print;
    return Object.freeze(p ? { saved: true, made: p.made, count: p.count, quality: quality(p), source: p.source } : { saved: false });
  }

  // ---- boot ------------------------------------------------------------------------------------------------------
  async function boot() {
    if (!S.ok) { changed(); return; }
    try { S.print = await readPrint(); } catch (_) { S.print = null; S.failed = true; }   // another key, a damaged record
    S.read = true;
    changed();
    prepare();
  }
  window.addEventListener('storage', (e) => { if (e.key === OFF_KEY) { if (isOn()) prepare(); changed(); } });
  if (hooks) {
    hooks.embed = (pcm) => embed(Int16Array.from(pcm)).then((e) => (e ? Array.from(e) : null));
    hooks.sessionKept = () => session.length;
  }
  window.JarvisVoicePrint = Object.freeze({
    state, active, verify, measure, recordReading, offerSessionClip, sessionCount: () => session.length, useSession,
    setOn, isOn, forget, info, CHECK_MS, READ_MS, ENROL_MIN, MODEL,
  });
  boot();
})();
