// tests/fixtures/r52_v5/voices.js -- R5.2 V5 (row 84): synthetic "voices" for the speaker check's tests.
// No recording of anyone: a voice here is arithmetic. A speaker is a pitch, a vocal-tract length (it scales the
// formants) and a spectral tilt; an utterance is a seeded run of syllables (each a vowel of that speaker, with its
// own pitch movement) and gaps. Two utterances of one speaker share his formants and pitch range but not a sample.
// A plain script: the node harness (voiceprint_node.mjs) and the browser tests (add_init_script) load it the same way.
//   JarvisTestVoices.SPEAKERS                       {owner, other, tv}
//   JarvisTestVoices.utter(speaker, seconds, seed)  -> Int16Array at 16 kHz
//   JarvisTestVoices.frames(pcm)                     -> [Int16Array(1280), ...] (the console's 80 ms frames)
(() => {
  'use strict';
  const RATE = 16000, FRAME = 1280;
  const VOWELS = [[730, 1090, 2440], [270, 2290, 3010], [300, 870, 2240], [530, 1840, 2480], [640, 1190, 2390]];
  const SPEAKERS = Object.freeze({
    owner: Object.freeze({ f0: 118, tract: 1.0, tilt: 1.1, breath: 0.02, rate: 1.0 }),
    other: Object.freeze({ f0: 240, tract: 1.45, tilt: 0.5, breath: 0.03, rate: 0.7 }),
    tv: Object.freeze({ f0: 150, tract: 0.8, tilt: 1.7, breath: 0.05, rate: 1.3 }),
  });
  function rng(seed) {
    let a = seed | 0;
    return () => {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // the vocal tract: three resonances, each a bump on a log-frequency scale
  function envelope(freq, formants, tilt) {
    let a = 0;
    formants.forEach((fm, i) => {
      const d = Math.log(freq / fm) / 0.12;
      a += Math.exp(-0.5 * d * d) / (1 + i * 0.6);
    });
    return (a + 0.02) * Math.pow(100 / Math.max(freq, 100), tilt * 0.5);
  }
  function utter(speaker, seconds, seed) {
    const sp = typeof speaker === 'string' ? SPEAKERS[speaker] : speaker;
    const next = rng(seed >>> 0);
    const n = Math.round(seconds * RATE), out = new Float32Array(n);
    let t = Math.round(RATE * (0.05 + next() * 0.1));
    while (t < n) {
      const len = Math.round(RATE * (0.16 + next() * 0.18) * sp.rate), gap = Math.round(RATE * (0.04 + next() * 0.1) * sp.rate);
      const vowel = VOWELS[Math.floor(next() * VOWELS.length)].map((f) => f / sp.tract);
      const f0a = sp.f0 * (0.9 + next() * 0.2), f0b = sp.f0 * (0.9 + next() * 0.2);
      const harmonics = Math.floor(4000 / Math.max(f0a, f0b));
      const amps = [];
      for (let k = 1; k <= harmonics; k++) amps.push(envelope(k * (f0a + f0b) / 2, vowel, sp.tilt) / Math.sqrt(k));
      let phase = 0;
      for (let i = 0; i < len && t + i < n; i++) {
        const u = i / len, f0 = f0a + (f0b - f0a) * u, shape = Math.sin(Math.PI * u) ** 0.6;
        phase += (2 * Math.PI * f0) / RATE;
        let s = 0;
        for (let k = 0; k < amps.length; k++) s += amps[k] * Math.sin((k + 1) * phase);
        out[t + i] = shape * (s + sp.breath * (next() * 2 - 1));
      }
      t += len + gap;
    }
    let peak = 0;
    for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(out[i]));
    const pcm = new Int16Array(n), gain = peak > 0 ? 9000 / peak : 0;
    for (let i = 0; i < n; i++) pcm[i] = Math.round(out[i] * gain + (next() - 0.5) * 40);
    return pcm;
  }
  function frames(pcm) {
    const list = [];
    for (let at = 0; at + FRAME <= pcm.length; at += FRAME) list.push(pcm.slice(at, at + FRAME));
    return list;
  }
  globalThis.JarvisTestVoices = Object.freeze({ SPEAKERS, utter, frames, RATE, FRAME });
})();
