// src/jarvis/api/static/console-voice-pace.js - R5 workstream C (docs/plans/r5-voice.md D15): the
// sound cues and the timing line. No build step; CSP script-src 'self'; textContent only.
//   window.JarvisVoicePace (frozen shape)
//     cue(name) -> Promise<boolean>   'listen' | 'heard' | 'micoff' | 'handover': a short generated tone
//         through the speaker's own audio context (speaker.tone), so it follows the chosen output and
//         the echo canceller. Never while JARVIS speaks, never when "Sound cues" is off. The same cue
//         asked twice within CUE_DEDUPE_MS returns the first one's promise, so the loop can await the
//         end of a cue (and start its VAD CUE_GAP_MS after it) whether the cue came from the loop or
//         from the events below.
//     mark(stage, at?)                'spoke' | 'heard' | 'words' | 'answer' | 'voice': a performance.mark
//         per stage of one spoken turn. The stages are also taken from the events a turn already fires,
//         so the loop need not call it. A stage seen again starts the next turn.
//     last() -> {heard, words, answer, voice, total, engine} (ms) | null
// Fires: jarvis:voice-timing {kind: 'reply', heard, words, answer, voice, total, engine} once per spoken
// turn, and {kind: 'barge', how, ms} for each interruption; plus a line in the event log.
// Listens: jarvis:voice-loop, jarvis:mic-lock, jarvis:turn, jarvis:answer, jarvis:speech, jarvis:barge,
// jarvis:voice-panel. Shows "Last reply: 3.1 s (listening 1.2 · words 0.6 · answer 0.9 · voice 0.4)" in
// JarvisVoice.panelSlot('pace'). No words, no audio and no device names are kept or logged.
(() => {
  'use strict';
  const CUE_GAP_MS = 100;        // the loop starts its VAD this long after a cue ends (D15)
  const CUE_DEDUPE_MS = 500;
  const CUE_GAIN = 0.12;
  const CUES = Object.freeze({
    listen: [{ freq: 660, ms: 70 }, { freq: 880, ms: 90 }],                       // rising
    heard: [{ freq: 1320, ms: 35, gain: 0.07 }],                                   // a soft tick
    micoff: [{ freq: 660, ms: 90 }, { freq: 440, ms: 140 }],                       // falling
    handover: [{ freq: 660, ms: 100 }, { freq: 520, ms: 120 }, { freq: 390, ms: 220 }], // a longer fall
  });
  const STAGES = Object.freeze(['spoke', 'heard', 'words', 'answer', 'voice']);
  const LOCK_CUE_BY = Object.freeze(['button', 'shortcut', 'voice', 'panel']); // not a reload or another tab
  const DEFAULT_END_SILENCE_MS = 1200;
  const MS_PER_S = 1000;

  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (text) => emit('jarvis:event', { kind: 'info', text, at: Date.now(), live: true });
  const V = () => window.JarvisVoice || null;
  const speaker = () => { const v = V(); return v && v.speaker ? v.speaker : null; };
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

  // ---------------------------------------------------------------------------------- cues
  const recent = new Map();   // cue name -> { at, p }
  function cuesOn() {
    const v = V(), d = v && typeof v.device === 'function' ? v.device() : null;
    return !d || d.cues !== false;
  }
  async function play(steps, sp) {
    let ok = false;
    for (const s of steps) ok = (await sp.tone({ gain: CUE_GAIN, ...s })) || ok;
    return ok;
  }
  function cue(name) {
    const steps = Object.prototype.hasOwnProperty.call(CUES, name) ? CUES[name] : null;
    const sp = speaker();
    if (!steps || !sp || typeof sp.tone !== 'function' || !cuesOn() || sp.speaking()) return Promise.resolve(false);
    const now = performance.now(), prior = recent.get(name);
    if (prior && now - prior.at < CUE_DEDUPE_MS) return prior.p;
    const p = play(steps, sp).catch(() => false);
    recent.set(name, { at: now, p });
    return p;
  }

  // ---------------------------------------------------------------------------------- timing
  let rec = {};               // stage -> performance.now() of the turn in progress
  let lastTiming = null;
  let engine = null;
  const order = (stage) => STAGES.indexOf(stage);

  function mark(stage, at) {
    const i = order(stage);
    if (i < 0) return;
    const t = num(at) !== null ? at : performance.now();
    if (Object.keys(rec).some(k => order(k) >= i)) rec = {};   // a stage seen again: the next turn
    rec[stage] = t;
    try { performance.mark('jarvis:' + stage, { startTime: t }); } catch (_) {}
    if (stage === 'voice') finish();
  }
  function endSilence() {
    const v = V(), d = v && typeof v.device === 'function' ? v.device() : null;
    return d && num(d.endSilenceMs) !== null ? d.endSilenceMs : DEFAULT_END_SILENCE_MS;
  }
  /** The stage lengths (ms) of a finished turn, or null when it was not a spoken-in, spoken-out turn. */
  function lengths(r) {
    if (r.heard === undefined || r.words === undefined || r.answer === undefined || r.voice === undefined) return null;
    const listening = r.spoke !== undefined ? r.heard - r.spoke : endSilence();
    const parts = { heard: listening, words: r.words - r.heard, answer: r.answer - r.words, voice: r.voice - r.answer };
    if (Object.values(parts).some(x => x < 0)) return null;
    const total = parts.heard + parts.words + parts.answer + parts.voice;
    return { heard: Math.round(parts.heard), words: Math.round(parts.words), answer: Math.round(parts.answer),
      voice: Math.round(parts.voice), total: Math.round(total), engine: engine || 'cloud' };
  }
  function finish() {
    const t = lengths(rec);
    rec = {};
    if (!t) return;
    lastTiming = t;
    emit('jarvis:voice-timing', { kind: 'reply', ...t });
    log('Voice timing: ' + line(t));
    paint();
  }
  const secs = (ms) => (ms / MS_PER_S).toFixed(1);
  function line(t) {
    return `${secs(t.total)} s (listening ${secs(t.heard)} · words ${secs(t.words)} · answer ${secs(t.answer)} · voice ${secs(t.voice)})`;
  }

  // ---------------------------------------------------------------------------------- panel line
  let lineEl = null;
  function paint() {
    const v = V(), slot = v && typeof v.panelSlot === 'function' ? v.panelSlot('pace') : null;
    if (!slot) return;
    if (!lineEl || !slot.contains(lineEl)) {
      lineEl = document.createElement('p');
      lineEl.className = 'bfine';
      lineEl.id = 'vPaceLine';
      slot.append(lineEl);
    }
    lineEl.textContent = lastTiming ? 'Last reply: ' + line(lastTiming) : 'Last reply: nothing timed yet. Talk to JARVIS and it appears here.';
  }

  // ---------------------------------------------------------------------------------- events
  let loopState = 'idle';
  document.addEventListener('jarvis:voice-loop', (e) => {
    const state = e.detail && e.detail.state, prev = loopState;
    loopState = state;
    if (state === 'listening' && prev !== 'listening') cue('listen');
    else if (state === 'thinking' && prev === 'listening') { mark('heard'); cue('heard'); }
    else if (state === 'handover') cue('handover');
  });
  document.addEventListener('jarvis:mic-lock', (e) => {
    const d = e.detail || {};
    if (d.locked && LOCK_CUE_BY.includes(d.by)) cue('micoff');
  });
  document.addEventListener('jarvis:turn', (e) => {
    if (e.detail && e.detail.channel === 'voice' && rec.heard !== undefined) mark('words');
  });
  document.addEventListener('jarvis:answer', (e) => {
    if (e.detail && e.detail.channel === 'voice' && rec.words !== undefined) mark('answer');
  });
  document.addEventListener('jarvis:speech', (e) => {
    if (rec.answer === undefined || rec.voice !== undefined) return;
    engine = e.detail && (e.detail.engine === 'browser' || e.detail.engine === 'cloud') ? e.detail.engine : null;
    mark('voice');
  });
  document.addEventListener('jarvis:barge', (e) => {
    const d = e.detail || {}, ms = num(d.ms);
    if (ms === null || typeof d.how !== 'string') return;
    emit('jarvis:voice-timing', { kind: 'barge', how: d.how.slice(0, 12), ms: Math.round(ms) });
    log(`Interrupted by ${d.how} in ${secs(ms)} s`);
  });
  document.addEventListener('jarvis:voice-panel', paint);
  document.addEventListener('jarvis:ready', paint);
  paint();

  window.JarvisVoicePace = Object.freeze({
    cue,
    mark,
    last: () => (lastTiming ? { ...lastTiming } : null),
  });
})();
