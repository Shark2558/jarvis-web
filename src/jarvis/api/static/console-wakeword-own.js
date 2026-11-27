// src/jarvis/api/static/console-wakeword-own.js - R5.2 row 83 (docs/plans/r5-2-voice.md 3.4, D5):
// the owner's own "Hey Jarvis" on this device (laptop and phone browsers). console-wakeword.js asks
// this file, when the page has it, for two things trained on his laptop kit:
//   stage 1, his personal verifier: plain JSON weights (openWakeWord's custom-verifier method) that
//     run after today's detector: when it scores at least the file's gate, the verifier's
//     probability that it is the owner saying it replaces the score, as openWakeWord does;
//   stage 2, his own model: an ONNX file in the console's format that runs in place of
//     hey_jarvis_v0.1 (CC BY-NC-SA, personal use only), offered only when it beat that model.
// Each comes from GET /v1/voice/profile/wakeword[/verifier|/model] through the console's own
// transport, and is used only when its SHA-256 is the one the status announced and (stage 1) it
// reads the very embedding model this browser runs. Anything missing, refused or odd: null, and
// the wake word works exactly as before. The files stay in this tab's memory; no audio, score or
// feature ever leaves it. Nothing here approves anything: a wake is only a wake (D6).
// No build step; CSP script-src 'self'; no DOM.
//   window.JarvisWakeOwn = { status() -> Promise<view | null>, verifier() -> Promise<{rescore} | null>,
//                            model() -> Promise<Uint8Array | null>, train('verifier' | 'owned'),
//                            rescorer(file) -> {gate, rescore(score, features)} | null }
(() => {
  'use strict';
  const BASE = '/v1/voice/profile/wakeword';
  const FRAMES = 16, DIM = 96, FEATURES = FRAMES * DIM; // console-wakeword.js EMB_FRAMES x EMB_DIM
  // static/wakeword/MANIFEST.txt: embedding_model.onnx, the features a verifier was trained on
  const EMBEDDING_SHA256 = '70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f';
  const OWNER_LICENCE = 'LicenseRef-Owner';
  const VERIFIER_MAX = 200000; // bytes (formats.VERIFIER_MAX_BYTES)
  const MODEL_MAX = 2000000; // bytes (formats.OWNED_MAX_BYTES)
  const STATUS_MS = 10000; // one status answers a load's two questions
  let cached = null; // { at, promise }

  const jsonApi = () => (window.JarvisConsole && typeof window.JarvisConsole.api === 'function'
    ? window.JarvisConsole.api : null);
  const rawApi = () => (window.JarvisChat && typeof window.JarvisChat.raw === 'function'
    ? window.JarvisChat.raw : null);

  function status() {
    const api = jsonApi();
    if (!api) return Promise.resolve(null);
    const now = Date.now();
    if (cached && now - cached.at < STATUS_MS) return cached.promise;
    const promise = api(BASE).then((v) => (v && typeof v === 'object' && v.available ? v : null), () => null);
    cached = { at: now, promise };
    return promise;
  }

  function sigmoid(z) {
    if (z >= 0) return 1 / (1 + Math.exp(-z));
    const e = Math.exp(z);
    return e / (1 + e);
  }

  /** Stage 1's rule (formats.VerifierFile.score): below the gate the score stands. */
  function rescorer(file) {
    if (!file || typeof file !== 'object') return null;
    if (file.format !== 'jarvis-wake-verifier' || file.version !== 1 || file.licence !== OWNER_LICENCE) return null;
    if (file.frames !== FRAMES || file.dim !== DIM || file.embedding_sha256 !== EMBEDDING_SHA256) return null;
    const { weights, bias, gate } = file;
    if (!Array.isArray(weights) || weights.length !== FEATURES || !Number.isFinite(bias)) return null;
    if (!(typeof gate === 'number' && gate > 0 && gate < 1)) return null;
    const w = Float64Array.from(weights, Number);
    if (!w.every(Number.isFinite)) return null;
    return Object.freeze({
      gate,
      rescore(score, features) {
        if (!(score >= gate) || !features || features.length !== FEATURES) return score;
        let z = bias;
        for (let i = 0; i < FEATURES; i++) z += w[i] * features[i];
        const p = sigmoid(z);
        return Number.isFinite(p) ? p : score;
      },
    });
  }

  async function bytesOf(path, max) {
    const raw = rawApi();
    if (!raw) return null;
    const r = await raw(path);
    if (!r.ok) return null;
    const bytes = new Uint8Array(await r.arrayBuffer());
    return bytes.length > 0 && bytes.length <= max ? bytes : null;
  }

  async function sha256(bytes) {
    const subtle = window.crypto && window.crypto.subtle;
    if (!subtle || typeof subtle.digest !== 'function') return null; // no check, no file
    const digest = new Uint8Array(await subtle.digest('SHA-256', bytes));
    return Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function announced(path, info, max) {
    if (!info || typeof info.sha256 !== 'string' || info.licence !== OWNER_LICENCE) return null;
    const bytes = await bytesOf(path, max);
    return bytes && (await sha256(bytes)) === info.sha256 ? bytes : null;
  }

  async function verifier() {
    try {
      const s = await status();
      if (!s || s.use_verifier !== true) return null;
      const bytes = await announced(BASE + '/verifier', s.verifier, VERIFIER_MAX);
      return bytes ? rescorer(JSON.parse(new TextDecoder().decode(bytes))) : null;
    } catch (_) {
      return null; // today's detector alone
    }
  }

  async function model() {
    try {
      const s = await status();
      if (!s || s.use_owned !== true) return null;
      return await announced(BASE + '/model', s.owned, MODEL_MAX);
    } catch (_) {
      return null; // today's model
    }
  }

  /** Starts a training run on the laptop (the "Your voice" screen's button). */
  async function train(artifact) {
    if (artifact !== 'verifier' && artifact !== 'owned') throw new Error('Not a wake-word file.');
    const api = jsonApi();
    if (!api) throw new Error('The console is not ready yet.');
    cached = null;
    return api(BASE + '/train', { method: 'POST', body: { artifact } });
  }

  window.JarvisWakeOwn = Object.freeze({ status, verifier, model, train, rescorer });
})();
