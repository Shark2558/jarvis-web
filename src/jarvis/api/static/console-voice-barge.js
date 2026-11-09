// src/jarvis/api/static/console-voice-barge.js - R5 D7 (docs/plans/r5-voice.md): speak to interrupt.
// No build step; CSP script-src 'self'.
//   window.JarvisBarge
//     policy()        'speech' | 'name' | 'tap'  the effective policy: the owner's "Interrupt JARVIS by"
//                     with Automatic resolved (earphones or a headset mic -> speech, otherwise name;
//                     an unknown output counts as speakers, the safe side).
//     arm(opts)       -> {disarm(), gate(), recentLoud(ms)}; called when JARVIS starts speaking, with
//                     opts {said() -> JARVIS's words of the last 4 s, onBarge(ev), browserVoice: bool,
//                           handle(text, ctx) -> Promise<{handled, result}>, onDuck?(on)}.
//                     ev {how: 'speech'|'stop', ms, frames?, text?, handled?, result?}. Nothing is called
//                     after disarm(). While the microphone is locked or closed arm() does nothing.
//     createGate(kind, {margin?})  the pure double-talk gate: {out(level, t), frame(micRms, t, replyAgeMs)
//                     -> {open, ratio, peak}}; kind 'headphones' | 'speakers'. Unit-tested in the page.
//     isEcho(text, said, peak, margin)  the text-aware echo guard (60 % of the words are JARVIS's own).
//     BARGE           the frozen constants.
// The gate: micRms must stay above max(0.018, noise x 3.2, echo estimate x margin) for N frames in a row;
// the echo estimate is how much of JARVIS leaks back into the mic (learned from the last 3 s) times
// his loudest output in the last 320 ms. In "name" mode a sound that opens the gate lowers his volume
// and a clip of up to 2.5 s goes to the cloud engine and then to the local router; anything that is not
// a command or an address ("Jarvis ...") is dropped unread and his volume returns.
// Privacy: the clip's words are never shown, logged or stored unless they are a command.
(() => {
  'use strict';
  const BARGE = Object.freeze({
    FRAME_MS: 80,
    MIN_RMS: 0.018,
    NOISE_RATIO: 3.2,
    NOISE_START: 0.012,                     // the noise estimate starts no higher than this
    HEADPHONES: Object.freeze({ frames: 3, margin: 2.0 }),
    SPEAKERS: Object.freeze({ frames: 4, margin: 4.0 }),
    FIRST_MS: 400, FIRST_EXTRA: 1,          // one more frame in the first 400 ms of a reply
    OUT_MS: 20,                             // output level sampling period
    ECHO_MS: 320,                           // loudest output in this window
    LEAK_MS: 3000, LEAK_MIN_OUT: 0.02, LEAK_PCT: 0.2, LEAK_MAX: 2,
    LEAK_FLOOR: Object.freeze({ headphones: 0.02, speakers: 0.12 }),  // never trust a learned leak below this
    LEAK_GUESS: Object.freeze({ headphones: 0.2, speakers: 1.0 }),   // before anything is learned
    RING_FRAMES: 14,                        // the last ~1.1 s kept to seed the turn
    SEED_BEFORE: 4,                         // frames before the gate opened that join the turn (320 ms)
    DUCK: 0.2,
    CLIP_MS: 2500, CLIP_QUIET_FRAMES: 4, CLIP_MIN_FRAMES: 5,
    CLIP_GAP_MS: 3000, MAX_EMPTY: 3,
    VOLUME_BACK_MS: 2500,
    ECHO_WORDS: 0.6, ECHO_PEAK: 1.5,
  });
  const HEADSET = /head(set|phone)|ear(phone|bud|pod)|buds|airpods|hands-?free/i;
  const A = () => window.JarvisAudio, V = () => window.JarvisVoice;

  // ---- the pure gate ------------------------------------------------------------------------------
  function createGate(kind, over) {
    const base = kind === 'headphones' ? BARGE.HEADPHONES : BARGE.SPEAKERS;
    const k = { frames: base.frames, margin: over && typeof over.margin === 'number' ? over.margin : base.margin };   // `over` is for tests
    const which = kind === 'headphones' ? 'headphones' : 'speakers';
    const guess = BARGE.LEAK_GUESS[which], floor = BARGE.LEAK_FLOOR[which];
    const outs = [], leaks = [];
    let noise = null, run = 0, peak = 0;
    function leak(t) {
      while (leaks.length && t - leaks[0].t > BARGE.LEAK_MS) leaks.shift();
      if (!leaks.length) return guess;
      const sorted = leaks.map(l => l.r).sort((a, b) => a - b);
      return Math.min(BARGE.LEAK_MAX, Math.max(0, sorted[Math.floor((sorted.length - 1) * BARGE.LEAK_PCT)]));
    }
    function loudest(t) {
      while (outs.length && t - outs[0].t > Math.max(BARGE.ECHO_MS, BARGE.LEAK_MS)) outs.shift();
      let m = 0;
      for (const o of outs) if (t - o.t <= BARGE.ECHO_MS && o.v > m) m = o.v;
      return m;
    }
    return {
      /** JARVIS's output level now (sampled every 20 ms while he speaks). */
      out(level, t) { outs.push({ t, v: Math.max(0, +level || 0) }); },
      /** One 80 ms microphone frame. */
      frame(micRms, t, replyAgeMs) {
        const e = Math.max(0, +micRms || 0);
        const loud = loudest(t);            // against his loudest output of the last 320 ms: the echo arrives late
        if (loud > BARGE.LEAK_MIN_OUT) leaks.push({ t, r: e / loud });
        const quiet = loud <= BARGE.LEAK_MIN_OUT;
        if (noise === null) noise = Math.min(e, BARGE.NOISE_START);
        const echo = Math.max(leak(t), floor) * loud;
        const need = Math.max(BARGE.MIN_RMS, noise * BARGE.NOISE_RATIO, echo * k.margin);
        if (e > need) { run++; peak = Math.max(peak, echo > 0 ? e / echo : Infinity); } else {
          run = 0;
          if (quiet) noise = noise * 0.9 + Math.min(e, need) * 0.1;      // the room's floor, never JARVIS's echo
        }
        const frames = k.frames + (replyAgeMs < BARGE.FIRST_MS ? BARGE.FIRST_EXTRA : 0);
        const open = run >= frames;
        if (!run) peak = 0;
        return { open, ratio: echo > 0 ? e / echo : Infinity, peak, run };
      },
      reset() { run = 0; peak = 0; },
    };
  }

  // ---- the text-aware echo guard ------------------------------------------------------------------
  const wordsOf = (s) => String(s || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}'\s]/gu, ' ').split(/\s+/).filter(Boolean);
  /** True when this transcript is mostly JARVIS's own words coming back, unless the sound was far louder. */
  function isEcho(text, said, peak, margin) {
    const w = wordsOf(text);
    if (!w.length) return false;
    const mine = new Set(wordsOf(said));
    const share = w.filter(x => mine.has(x)).length / w.length;
    if (share < BARGE.ECHO_WORDS) return false;
    return !(typeof peak === 'number' && peak >= BARGE.ECHO_PEAK * (margin || BARGE.SPEAKERS.margin));
  }

  // ---- policy -------------------------------------------------------------------------------------
  function kind() {
    const R = window.JarvisAudioRoute;
    let out = 'unknown';
    try { out = R && typeof R.outputKind === 'function' ? R.outputKind() : 'unknown'; } catch (_) { out = 'unknown'; }
    if (out === 'headphones') return 'headphones';
    let label = '';
    try { label = A().trackLabel() || ''; } catch (_) { label = ''; }
    return HEADSET.test(label) ? 'headphones' : 'speakers';
  }
  function policy() {
    const v = V();
    const by = v && typeof v.device === 'function' ? v.device().interruptBy : 'tap';
    if (by === 'speech' || by === 'name' || by === 'tap') return by;
    return kind() === 'headphones' ? 'speech' : 'name';                // Automatic
  }

  // ---- arming -------------------------------------------------------------------------------------
  function arm(opts) {
    const o = opts || {};
    const noop = { disarm() {}, gate: () => null, recentLoud: () => false };
    const pol = policy(), Au = A(), Vo = V();
    if (pol === 'tap' || !Au || Au.locked() || !Au.isOpen() || typeof o.onBarge !== 'function') return noop;
    const kd = kind();
    const energy = pol === 'speech' ? !(o.browserVoice && kd === 'speakers') : !o.browserVoice;  // browser voice has no echo reference
    if (!energy) return noop;
    const gate = createGate(kd), speaker = Vo.speaker, t0 = performance.now();
    const s = { off: false, ring: [], clip: null, clips: 0, empties: 0, lastClip: 0, ducked: false, duckTimer: 0, hot: 0, loudAt: 0 };
    const sampler = setInterval(() => gate.out(o.browserVoice ? 0 : speaker.level(), performance.now()), BARGE.OUT_MS);
    const unduck = () => { clearTimeout(s.duckTimer); if (s.ducked) { s.ducked = false; try { speaker.duck(false); } catch (_) {} } };
    function disarm() {
      if (s.off) return;
      s.off = true; clearInterval(sampler); off(); unduck(); s.clip = null;
    }
    const seedFrames = (n) => s.ring.slice(-Math.min(s.ring.length, n));
    function interrupt(ev) {
      if (s.off) return;
      const e = Object.assign({}, ev);
      disarm();
      o.onBarge(e);
    }
    function onFrame(frame) {
      if (s.off) return;
      const t = performance.now();
      s.ring.push(frame); if (s.ring.length > BARGE.RING_FRAMES) s.ring.shift();
      if (s.clip) { collect(frame); return; }
      const g = gate.frame(window.JarvisVad.rms(frame), t, t - t0);
      if (g.run) s.loudAt = t;
      if (!g.open) { if (!g.run) s.hot = 0; else if (!s.hot) s.hot = t - g.run * BARGE.FRAME_MS; return; }
      if (!s.hot) s.hot = t - g.run * BARGE.FRAME_MS;
      const ms = Math.round(t - s.hot);
      if (pol === 'speech') { interrupt({ how: 'speech', ms, frames: seedFrames(g.run + BARGE.SEED_BEFORE), peak: g.peak }); return; }
      startClip(t, g);
    }
    // ---- name mode: lower the volume, listen for 2.5 s, ask the router --------------------------------
    function startClip(t, g) {
      if (s.empties >= BARGE.MAX_EMPTY || t - s.lastClip < BARGE.CLIP_GAP_MS) { gate.reset(); return; }
      s.lastClip = t;
      s.ducked = true; try { speaker.duck(true); } catch (_) { s.ducked = false; }
      clearTimeout(s.duckTimer);
      s.duckTimer = setTimeout(unduck, BARGE.CLIP_MS + BARGE.VOLUME_BACK_MS + 4000);
      s.clip = { frames: seedFrames(g.run + BARGE.SEED_BEFORE), speech: g.run, quiet: 0, peak: g.peak, started: t };
    }
    function collect(frame) {
      const c = s.clip, loud = window.JarvisVad.rms(frame) > BARGE.MIN_RMS;
      c.frames.push(frame);
      if (loud) { c.speech++; c.quiet = 0; } else c.quiet++;
      const done = c.frames.length * BARGE.FRAME_MS >= BARGE.CLIP_MS || (c.speech >= BARGE.CLIP_MIN_FRAMES && c.quiet >= BARGE.CLIP_QUIET_FRAMES);
      if (done) { s.clip = null; gate.reset(); judge(c); }
    }
    async function judge(c) {
      s.clips++;
      let text = '';
      try {
        const r = await window.JarvisChat.raw('/v1/voice/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: window.JarvisWav.encode(c.frames) });
        const j = r.ok ? await r.json() : null;
        text = j && typeof j.text === 'string' && j.no_speech !== true ? j.text.trim() : '';
      } catch (_) { text = ''; }
      if (s.off) return;
      const margin = kd === 'headphones' ? BARGE.HEADPHONES.margin : BARGE.SPEAKERS.margin;
      const said = typeof o.said === 'function' ? o.said() : '';
      if (!text || isEcho(text, said, c.peak, margin)) { s.empties++; unduck(); return; }
      const C = window.JarvisVoiceCommands;
      const ms = Math.round(performance.now() - (s.hot || c.started));
      let res = { handled: false };
      try { res = typeof o.handle === 'function' ? await o.handle(text, { source: 'voice', state: 'speaking', spoken: said, peak: c.peak }) : res; } catch (_) { res = { handled: false }; }
      if (s.off) return;
      if (res.handled) { interrupt({ how: 'stop', ms, handled: true, result: res.result || {} }); return; }
      if (C && C.addressed(text)) { interrupt({ how: 'stop', ms, text, handled: false }); return; }
      s.empties++; unduck();             // not for JARVIS: the words are dropped here
    }
    const off = Au.subscribe(onFrame);
    return { disarm, gate: () => gate, recentLoud: (ms) => performance.now() - s.loudAt <= ms };
  }

  window.JarvisBarge = Object.freeze({ policy, arm, createGate, isEcho, BARGE, kind });
})();
