// src/jarvis/api/static/console-voiceprint-math.js - R5.2 row 84 (docs/plans/r5-2-voice.md 3.5, D6): the speaker
// check's arithmetic. Pure: no network, no storage, no DOM; the same file runs in the page and in the node test
// harness (tests/fixtures/r52_v5/voiceprint_node.mjs). No build step; CSP script-src 'self'.
//   window.JarvisVoicePrintMath
//     fbank(pcm, {window})      Kaldi's filterbank as torchaudio.compliance.kaldi.fbank computes it for WeSpeaker:
//                               80 mel bands (20 Hz to 8 kHz), 25 ms frames every 10 ms (snip edges), DC removed,
//                               pre-emphasis 0.97, a Hamming window ('povey' for 3D-Speaker exports), a 512-point
//                               power spectrum, log with the float32 epsilon floor; no dither. pcm: Int16Array at
//                               16 kHz, used at int16 scale (WeSpeaker reads wav files unnormalised).
//                               -> {data: Float32Array(T * 80), frames: T}
//     cmn(f)                    each band's mean over time removed (a new object; WeSpeaker and 3D-Speaker do this)
//     features(pcm, model)      -> {data, dims: [1, T, 80]} for the model, or null under MIN_FRAMES
//     join(frames), voicedMs(pcm), segments(pcm, opts)   the console's 80 ms frames; how much of it is voice
//     unit(v), cosine(a, b), buildPrint(embeddings), verdict(score, voicedMs, threshold)
//     encodeVector(v) / decodeVector(b64, dims)          a print's numbers for the encrypted store
// A voice print is the mean direction of several embeddings of the owner's speech; a clip is his when its own
// embedding points the same way (cosine at or above the model's threshold). Nothing here decides anything else.
(() => {
  'use strict';
  const RATE = 16000, FRAME = 1280, FRAME_MS = 80, MEL_BINS = 80;
  const WIN = 400, SHIFT = 160, FFT = 512, BINS = FFT / 2;
  const PREEMPH = 0.97, LOW_HZ = 20, EPS = 1.1920928955078125e-7;   // torch.finfo(float32).eps
  const MIN_FRAMES = 30;                     // 0.3 s of features: anything shorter says nothing about a voice
  const VOICE_RMS = 0.018;                   // = JarvisBarge's MIN_RMS: a frame above it counts as voice
  const MIN_VOICED_MS = 400;                 // a clip with less voice than this is 'short', never 'owner' (= the
                                             // 5 loud frames after which the barge-in hook may end a check clip)
  const SEGMENT_MS = 3000, SEGMENT_VOICED_MS = 1200;   // enrolment: 3 s pieces with at least 1.2 s of voice
  const MAX_DIMS = 1024;

  // ---- the filterbank ------------------------------------------------------------------------------------
  const melOf = (hz) => 1127 * Math.log(1 + hz / 700);
  function windowOf(kind) {
    const w = new Float64Array(WIN);
    for (let n = 0; n < WIN; n++) {
      const c = Math.cos((2 * Math.PI * n) / (WIN - 1));
      w[n] = kind === 'povey' ? Math.pow(0.5 - 0.5 * c, 0.85) : 0.54 - 0.46 * c;
    }
    return w;
  }
  const WINDOWS = { hamming: windowOf('hamming'), povey: windowOf('povey') };
  /** [MEL_BINS][BINS + 1] triangle weights; the Nyquist bin gets none (torchaudio pads a zero column). */
  const BANKS = (() => {
    const low = melOf(LOW_HZ), high = melOf(RATE / 2), delta = (high - low) / (MEL_BINS + 1);
    const banks = [];
    for (let b = 0; b < MEL_BINS; b++) {
      const left = low + b * delta, centre = low + (b + 1) * delta, right = low + (b + 2) * delta;
      const row = new Float64Array(BINS + 1);
      for (let i = 0; i < BINS; i++) {
        const m = melOf((RATE / FFT) * i);
        row[i] = Math.max(0, Math.min((m - left) / (centre - left), (right - m) / (right - centre)));
      }
      banks.push(row);
    }
    return banks;
  })();
  const REV = (() => {
    const r = new Uint16Array(FFT), bits = Math.log2(FFT);
    for (let i = 0; i < FFT; i++) { let x = i, y = 0; for (let b = 0; b < bits; b++) { y = (y << 1) | (x & 1); x >>= 1; } r[i] = y; }
    return r;
  })();
  const COS = new Float64Array(FFT / 2), SIN = new Float64Array(FFT / 2);
  for (let i = 0; i < FFT / 2; i++) { COS[i] = Math.cos((2 * Math.PI * i) / FFT); SIN[i] = -Math.sin((2 * Math.PI * i) / FFT); }
  /** In place, radix 2: re/im of length FFT. */
  function fftInPlace(re, im) {
    for (let i = 0; i < FFT; i++) {
      const j = REV[i];
      if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (let size = 2; size <= FFT; size <<= 1) {
      const half = size >> 1, step = FFT / size;
      for (let start = 0; start < FFT; start += size) {
        for (let k = 0; k < half; k++) {
          const wr = COS[k * step], wi = SIN[k * step], a = start + k, b = a + half;
          const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
          re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        }
      }
    }
  }
  function fbank(pcm, opts) {
    const x = pcm instanceof Int16Array || pcm instanceof Float32Array ? pcm : new Int16Array(0);
    const win = WINDOWS[opts && opts.window === 'povey' ? 'povey' : 'hamming'];
    const frames = x.length >= WIN ? 1 + Math.floor((x.length - WIN) / SHIFT) : 0;
    const data = new Float32Array(frames * MEL_BINS);
    const re = new Float64Array(FFT), im = new Float64Array(FFT), power = new Float64Array(BINS + 1);
    for (let f = 0; f < frames; f++) {
      const at = f * SHIFT;
      let mean = 0;
      for (let n = 0; n < WIN; n++) mean += x[at + n];
      mean /= WIN;
      let prev = x[at] - mean;                      // pre-emphasis repeats the first sample (torchaudio's replicate pad)
      for (let n = 0; n < WIN; n++) {
        const v = x[at + n] - mean;
        re[n] = (v - PREEMPH * prev) * win[n];
        prev = v;
      }
      re.fill(0, WIN); im.fill(0);
      fftInPlace(re, im);
      for (let i = 0; i <= BINS; i++) power[i] = re[i] * re[i] + im[i] * im[i];
      for (let b = 0; b < MEL_BINS; b++) {
        const row = BANKS[b];
        let e = 0;
        for (let i = 0; i <= BINS; i++) if (row[i]) e += row[i] * power[i];
        data[f * MEL_BINS + b] = Math.log(Math.max(e, EPS));
      }
    }
    return { data, frames };
  }
  function cmn(feats) {
    const { data, frames } = feats, out = new Float32Array(data.length);
    if (!frames) return { data: out, frames };
    for (let b = 0; b < MEL_BINS; b++) {
      let s = 0;
      for (let f = 0; f < frames; f++) s += data[f * MEL_BINS + b];
      const m = s / frames;
      for (let f = 0; f < frames; f++) out[f * MEL_BINS + b] = data[f * MEL_BINS + b] - m;
    }
    return { data: out, frames };
  }
  function features(pcm, model) {
    const f = fbank(pcm, { window: model && model.window });
    if (f.frames < MIN_FRAMES) return null;
    const c = cmn(f);
    return { data: c.data, dims: [1, c.frames, MEL_BINS] };
  }

  // ---- frames and voice ----------------------------------------------------------------------------------
  function join(frames) {
    const list = Array.from(frames || []).filter((f) => f instanceof Int16Array);
    const out = new Int16Array(list.reduce((n, f) => n + f.length, 0));
    let at = 0;
    list.forEach((f) => { out.set(f, at); at += f.length; });
    return out;
  }
  function rms(pcm, from, to) {
    let s = 0;
    for (let i = from; i < to; i++) { const v = pcm[i] / 32768; s += v * v; }
    return Math.sqrt(s / Math.max(1, to - from));
  }
  function voicedMs(pcm) {
    let n = 0;
    for (let at = 0; at + FRAME <= pcm.length; at += FRAME) if (rms(pcm, at, at + FRAME) > VOICE_RMS) n++;
    return n * FRAME_MS;
  }
  /** Enrolment's pieces: consecutive SEGMENT_MS slices that hold at least SEGMENT_VOICED_MS of voice. */
  function segments(pcm, opts) {
    const o = opts || {}, len = Math.round(((o.segmentMs || SEGMENT_MS) / 1000) * RATE), need = o.minVoicedMs || SEGMENT_VOICED_MS;
    const out = [];
    for (let at = 0; at + len <= pcm.length; at += len) {
      const piece = pcm.subarray(at, at + len);
      if (voicedMs(piece) >= need) out.push(piece);
    }
    return out;
  }

  // ---- embeddings and the print --------------------------------------------------------------------------
  function unit(v) {
    if (!v || !(v.length > 0) || v.length > MAX_DIMS) return null;
    let s = 0;
    for (let i = 0; i < v.length; i++) { if (!Number.isFinite(v[i])) return null; s += v[i] * v[i]; }
    if (!(s > 0)) return null;
    const n = Math.sqrt(s), out = new Float32Array(v.length);
    for (let i = 0; i < v.length; i++) out[i] = v[i] / n;
    return out;
  }
  function cosine(a, b) {
    const ua = unit(a), ub = unit(b);
    if (!ua || !ub || ua.length !== ub.length) return 0;
    let s = 0;
    for (let i = 0; i < ua.length; i++) s += ua[i] * ub[i];
    return Math.max(-1, Math.min(1, s));
  }
  /** The mean direction of the embeddings, and how well each agrees with the others (leave one out). */
  function buildPrint(embeddings) {
    const list = (embeddings || []).map(unit).filter(Boolean);
    if (list.length < 2 || list.some((e) => e.length !== list[0].length)) return null;
    const dims = list[0].length, sum = new Float64Array(dims);
    list.forEach((e) => { for (let i = 0; i < dims; i++) sum[i] += e[i]; });
    const self = list.map((e) => {
      const rest = new Float32Array(dims);
      for (let i = 0; i < dims; i++) rest[i] = sum[i] - e[i];
      return cosine(e, rest);
    });
    const vector = unit(Float32Array.from(sum));
    if (!vector) return null;
    return { vector, count: list.length, selfMean: self.reduce((a, b) => a + b, 0) / self.length, selfMin: Math.min(...self) };
  }
  function verdict(score, voiced, threshold) {
    if (!(voiced >= MIN_VOICED_MS)) return 'short';
    return Number.isFinite(score) && score >= threshold ? 'owner' : 'other';
  }

  // ---- a print's numbers, for the encrypted store ----------------------------------------------------------
  function encodeVector(v) {
    const bytes = new Uint8Array(Float32Array.from(v).buffer);
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }
  function decodeVector(b64, dims) {
    try {
      const s = atob(String(b64 || ''));
      if (s.length !== dims * 4 || !(dims > 0) || dims > MAX_DIMS) return null;
      const bytes = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i);
      return unit(new Float32Array(bytes.buffer));
    } catch (_) { return null; }
  }

  window.JarvisVoicePrintMath = Object.freeze({
    RATE, FRAME, FRAME_MS, MEL_BINS, MIN_FRAMES, VOICE_RMS, MIN_VOICED_MS, SEGMENT_MS, SEGMENT_VOICED_MS,
    fbank, cmn, features, join, voicedMs, segments, unit, cosine, buildPrint, verdict, encodeVector, decodeVector,
  });
})();
