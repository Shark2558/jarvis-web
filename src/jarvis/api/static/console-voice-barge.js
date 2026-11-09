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
    CLIPS_REPLY: 3, CLIPS_CONVERSATION: 20, CLIPS_HOUR: 12, HOUR_MS: 60 * 60 * 1000,   // SM5: what a noisy room may spend
    NOISE_WINDOW: 25, NOISE_MIN_SAMPLES: 10, NOISE_PCT: 0.1, NOISE_MAX: 0.06, NOISE_MIX: 0.1,   // the room's floor adapts slowly (M5)
    MEMORY_MS: 30 * 60 * 1000,              // what was learned about the room is trusted this long
    VOLUME_BACK_MS: 2500,
    ECHO_WORDS: 0.6, ECHO_PEAK: 1.5,
  });
  const HEADSET = /head(set|phone)|ear(phone|bud|pod)|buds|airpods|hands-?free/i;
  const A = () => window.JarvisAudio, V = () => window.JarvisVoice;

  // ---- the pure gate ------------------------------------------------------------------------------
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);
  /** The room's floor: starts low, then follows the 10th percentile of its recent quiet frames, slowly, up to a cap.
   *  A room that is loud all the time stops counting as speech; one loud frame, or a voice, does not move it (M5). */
  function createFloor(seed) {
    const lows = [];
    let noise = seed;
    return {
      value: () => noise,
      start(e) { if (noise === null) noise = Math.min(e, BARGE.NOISE_START); },
      observe(e) {
        lows.push(e); if (lows.length > BARGE.NOISE_WINDOW) lows.shift();
        if (lows.length < BARGE.NOISE_MIN_SAMPLES) return;
        const p = [...lows].sort((a, b) => a - b)[Math.floor((lows.length - 1) * BARGE.NOISE_PCT)];
        noise = Math.min(BARGE.NOISE_MAX, noise * (1 - BARGE.NOISE_MIX) + p * BARGE.NOISE_MIX);
      },
    };
  }
  /** How much of JARVIS leaks back into the microphone: the 20th percentile of the last 3 s, or a guess before that. */
  function createLeak(guess) {
    const leaks = [];
    let last = null;
    return {
      add(t, r) { leaks.push({ t, r }); },
      last: () => last,
      guess,
      at(t) {
        while (leaks.length && t - leaks[0].t > BARGE.LEAK_MS) leaks.shift();
        if (!leaks.length) return guess;
        const sorted = leaks.map(l => l.r).sort((a, b) => a - b);
        last = Math.min(BARGE.LEAK_MAX, Math.max(0, sorted[Math.floor((sorted.length - 1) * BARGE.LEAK_PCT)]));
        return last;
      },
    };
  }
  function createGate(kind, over) {
    const base = kind === 'headphones' ? BARGE.HEADPHONES : BARGE.SPEAKERS;
    const margin = over && typeof over.margin === 'number' ? over.margin : base.margin;   // `over` is for tests
    const which = kind === 'headphones' ? 'headphones' : 'speakers';
    const seedLeak = over ? num(over.leak) : null;
    const floor = BARGE.LEAK_FLOOR[which];
    const leak = createLeak(seedLeak !== null && seedLeak > 0 ? seedLeak : BARGE.LEAK_GUESS[which]);
    const room = createFloor(over ? num(over.noise) : null);
    const outs = [];
    let run = 0, peak = 0;
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
        if (loud > BARGE.LEAK_MIN_OUT) leak.add(t, e / loud);
        room.start(e);
        const echo = Math.max(leak.at(t), floor) * loud;
        const need = Math.max(BARGE.MIN_RMS, room.value() * BARGE.NOISE_RATIO, echo * margin);
        if (e > need) { run++; peak = Math.max(peak, echo > 0 ? e / echo : Infinity); } else run = 0;
        if (loud <= BARGE.LEAK_MIN_OUT) room.observe(e);                      // only while he is silent: never his own echo
        const open = run >= base.frames + (replyAgeMs < BARGE.FIRST_MS ? BARGE.FIRST_EXTRA : 0);
        if (!run) peak = 0;
        return { open, ratio: echo > 0 ? e / echo : Infinity, peak, run };
      },
      reset() { run = 0; peak = 0; },
      /** What was learned: numbers only, for the event log and for the next reply's gate. */
      stats: () => ({ leak: leak.last() === null ? leak.guess : leak.last(), noise: room.value(), peak }),
    };
  }

  // ---- the text-aware echo guard ------------------------------------------------------------------
  // Combining marks stay with their letters: a Malayalam or Hindi word must not fall apart into pieces (M6)
  const wordsOf = (s) => String(s || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{M}\p{N}'\s]/gu, ' ').split(/\s+/).filter(Boolean);
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
  /** The echo margin of the output in use now (earphones need less room than speakers). */
  const margin = () => (kind() === 'headphones' ? BARGE.HEADPHONES.margin : BARGE.SPEAKERS.margin);
  function policy() {
    const v = V();
    const by = v && typeof v.device === 'function' ? v.device().interruptBy : 'tap';
    if (by === 'speech' || by === 'name' || by === 'tap') return by;
    return kind() === 'headphones' ? 'speech' : 'name';                // Automatic
  }

  // ---- what a conversation remembers about the room, and what check clips may spend (SM3, SM5) -------
  const memory = { kind: null, at: 0, leak: null, noise: null, clips: 0, hour: [] };
  /** The conversation is over: the room is forgotten and its clips are not counted against the next one. */
  function forget() { memory.kind = memory.leak = memory.noise = null; memory.clips = 0; }
  const recall = (kd) => (memory.kind === kd && Date.now() - memory.at < BARGE.MEMORY_MS ? { leak: memory.leak, noise: memory.noise } : {});
  function remember(kd, st) {
    if (!st) return;
    memory.kind = kd; memory.at = Date.now();
    if (typeof st.leak === 'number') memory.leak = st.leak;
    if (typeof st.noise === 'number') memory.noise = st.noise;
  }
  function clipAllowed(sentThisReply) {
    const now = Date.now();
    memory.hour = memory.hour.filter(x => now - x < BARGE.HOUR_MS);
    return sentThisReply < BARGE.CLIPS_REPLY && memory.clips < BARGE.CLIPS_CONVERSATION && memory.hour.length < BARGE.CLIPS_HOUR;
  }
  function countClip() { memory.clips++; memory.hour.push(Date.now()); }
  /** Clips still allowed in this conversation and this hour (numbers only; the tests read it). */
  const clipsLeft = () => { clipAllowed(0); return { conversation: BARGE.CLIPS_CONVERSATION - memory.clips, hour: BARGE.CLIPS_HOUR - memory.hour.length }; };

  /** Whether the energy gate may run for this reply, and with what: null means "do nothing" (tap / name only). */
  function plan(o) {
    const pol = policy(), Au = A();
    if (pol === 'tap' || o.energyOff === true || !Au || Au.locked() || !Au.isOpen() || typeof o.onBarge !== 'function') return null;
    const kd = kind();
    // the browser's own voice gives no echo reference: on speakers (or an unknown output) only tap / name can be trusted
    const energy = pol === 'speech' ? !(o.browserVoice && kd === 'speakers') : !o.browserVoice;
    return energy ? { pol, kd, Au } : null;
  }

  function arm(opts) {
    const o = opts || {}, noop = { disarm() {}, gate: () => null, recentLoud: () => false };
    const p = plan(o);
    if (!p) return noop;
    const { pol, kd, Au } = p, speaker = V().speaker;
    const gate = createGate(kd, recall(kd));
    const s = { off: false, ring: [], clip: null, clips: 0, empties: 0, lastClip: 0, ducked: false, duckTimer: 0, hot: 0, loudAt: 0,
      began: false, t0: performance.now(), ctrl: new AbortController() };
    const sampler = setInterval(() => sample(s, gate, speaker, o), BARGE.OUT_MS);
    const unduck = () => { clearTimeout(s.duckTimer); if (s.ducked) { s.ducked = false; try { speaker.duck(false); } catch (_) {} } };
    function disarm() {
      if (s.off) return;
      s.off = true; clearInterval(sampler); off(); unduck(); s.clip = null;
      try { s.ctrl.abort(); } catch (_) {}                     // a check clip on its way is dropped
      remember(kd, gate.stats());
    }
    function interrupt(ev) {
      if (s.off) return;
      const e = Object.assign({ stats: gate.stats() }, ev);
      disarm();
      o.onBarge(e);
    }
    const clips = makeClips(o, s, gate, speaker, unduck, makeJudge(o, s, gate, kd, Au, unduck, interrupt));
    const off = Au.subscribe(onFrame);
    function onFrame(frame) {
      if (s.off) return;
      const t = performance.now();
      s.ring.push(frame); if (s.ring.length > BARGE.RING_FRAMES) s.ring.shift();
      if (s.clip) { clips.collect(frame); return; }
      const g = gate.frame(window.JarvisVad.rms(frame), t, s.began ? t - s.t0 : 0);
      if (g.run) s.loudAt = t;
      if (!g.open) { if (!g.run) s.hot = 0; else if (!s.hot) s.hot = t - g.run * BARGE.FRAME_MS; return; }
      if (!s.hot) s.hot = t - g.run * BARGE.FRAME_MS;
      const ms = Math.round(t - s.hot);
      if (pol === 'speech') { interrupt({ how: 'speech', ms, frames: s.ring.slice(-Math.min(s.ring.length, g.run + BARGE.SEED_BEFORE)), peak: g.peak }); return; }
      clips.start(t, g);
    }
    return { disarm, gate: () => gate, recentLoud: (ms) => performance.now() - s.loudAt <= ms };
  }
  /** Every 20 ms: his output level goes to the gate; the reply's age counts from the first audible sound (M5). */
  function sample(s, gate, speaker, o) {
    const lvl = o.browserVoice ? 0 : speaker.level();
    if (!s.began && (o.browserVoice || lvl > BARGE.LEAK_MIN_OUT)) { s.began = true; s.t0 = performance.now(); }
    gate.out(lvl, performance.now());
  }

  // ---- name mode: lower the volume, listen for 2.5 s, ask the router ----------------------------------
  function makeClips(o, s, gate, speaker, unduck, judge) {
    const seed = (n) => s.ring.slice(-Math.min(s.ring.length, n));
    function start(t, g) {
      // clips only inside a conversation the owner started (D18), at most 3 a reply / 20 a conversation / 12 an hour (SM5)
      if (o.clips !== true || !clipAllowed(s.clips) || s.empties >= BARGE.MAX_EMPTY || t - s.lastClip < BARGE.CLIP_GAP_MS) { gate.reset(); return; }
      s.lastClip = t;
      s.ducked = true; try { speaker.duck(true); } catch (_) { s.ducked = false; }
      clearTimeout(s.duckTimer);
      s.duckTimer = setTimeout(unduck, BARGE.CLIP_MS + BARGE.VOLUME_BACK_MS + 4000);
      s.clip = { frames: seed(g.run + BARGE.SEED_BEFORE), speech: g.run, quiet: 0, peak: g.peak, started: t };
    }
    function collect(frame) {
      const c = s.clip, loud = window.JarvisVad.rms(frame) > BARGE.MIN_RMS;
      c.frames.push(frame);
      if (loud) { c.speech++; c.quiet = 0; } else c.quiet++;
      const done = c.frames.length * BARGE.FRAME_MS >= BARGE.CLIP_MS || (c.speech >= BARGE.CLIP_MIN_FRAMES && c.quiet >= BARGE.CLIP_QUIET_FRAMES);
      if (done) { s.clip = null; gate.reset(); judge(c); }
    }
    return { start, collect };
  }
  /** The clip goes to the cloud engine and then to the local router; its words are dropped unless they are a command. */
  function makeJudge(o, s, gate, kd, Au, unduck, interrupt) {
    return async function judge(c) {
      s.clips++; countClip();                                        // counted when the request is SENT
      let text = '';
      try {
        const r = await window.JarvisChat.raw('/v1/voice/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: window.JarvisWav.encode(c.frames), signal: s.ctrl.signal });
        const j = r.ok ? await r.json() : null;
        text = j && typeof j.text === 'string' && j.no_speech !== true ? j.text.trim() : '';
      } catch (_) { text = ''; }
      if (s.off || Au.locked()) return;
      const said = typeof o.said === 'function' ? o.said() : '';
      if (!text || isEcho(text, said, c.peak, margin())) { s.empties++; unduck(); return; }
      const C = window.JarvisVoiceCommands, ms = Math.round(performance.now() - (s.hot || c.started));
      let res = { handled: false };
      try { res = typeof o.handle === 'function' ? await o.handle(text, { source: 'voice', state: 'speaking', spoken: said, peak: c.peak, clip: true }) : res; } catch (_) { res = { handled: false }; }
      if (s.off || Au.locked()) return;                               // locked while the router ran: nothing happens
      if (res.handled) { interrupt({ how: 'stop', ms, handled: true, result: res.result || {} }); return; }
      if (C && C.addressed(text)) { interrupt({ how: 'stop', ms, text: afterName(C, text), handled: false }); return; }
      s.empties++; unduck();                                          // not for JARVIS: the words are dropped here
    };
  }
  /** Only the part after "Jarvis" becomes the next turn (the name itself is not part of the question). */
  function afterName(C, text) {
    const w = String(text).trim().split(/\s+/);
    for (let n = 1; n <= 3 && n <= w.length; n++) if (C.addressed(w.slice(0, n).join(' '))) return w.slice(n).join(' ').replace(/^[,.:;!?-]+\s*/, '');
    return '';
  }

  window.JarvisBarge = Object.freeze({ policy, arm, createGate, isEcho, BARGE, kind, margin, forget, clipsLeft });
})();
