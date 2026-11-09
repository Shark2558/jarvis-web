// src/jarvis/api/static/console-systems-voice.js -- R5.1 D6: the words and the voice of the systems-check
// pop-up (console-systems-modal.js). No build step; CSP script-src 'self'; ASCII source.
//   window.JarvisSystemsVoice = { matches, canHear, say, stop, unlock, usable, speaking, voiced, forget }
// matches(text, {typed, named}): the few phrases that open the pop-up. Voice (the default): "(hey) jarvis,
//   run a systems check" and variants; "system status" alone needs the name (`named`, or "jarvis" in the
//   text). typed: the WHOLE message is one phrase ("jarvis," / "hey jarvis" first, ending punctuation only).
// canHear(text): the echo guard for the pop-up's own speech -- false while it speaks, for 2 s after, and
//   for words that are mostly what it just said (the same JarvisBarge.isEcho the mic loop uses; the real
//   speaker also fires its 'chunk' event for every line, which the mic loop already records).
// say(text, then, asked): through the shared speaker (not when "Speak replies: Never" or no voice, unless
//   `asked`); only the end of the pop-up's OWN utterance counts, never a speaker that was already talking.
(() => {
  'use strict';
  if (window.JarvisSystemsVoice) return;
  const SPEAK_MS_PER_CHAR = 75, SPEAK_SLACK_MS = 2500, SPEAK_MAX_MS = 90000;
  const QUIET_MS = 2000, ECHO_WINDOW_MS = 3000; // 3 s: the mic loop's own reverb window
  const PHRASES = new Set(['run a systems check', 'run a system check', 'run systems check', 'run system check',
    'systems check', 'system check', 'system status', 'systems status', 'run diagnostics']);
  const NEEDS_NAME = new Set(['system status', 'systems status']); // too common in talk to be heard bare
  const T = { speaking: false, afterSpeech: null, voiced: false, hooked: false, timer: 0, quietAt: 0, said: '' };
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);

  function matches(text, opts) {
    if (typeof text !== 'string') return false;
    const o = obj(opts) || {}, flat = text.normalize('NFKC').toLowerCase();
    if (o.typed === true) {
      const m = /^\s*(?:(?:hey\s+)?jarvis[\s,:;-]+)?([a-z ]+?)\s*[.!?]*\s*$/.exec(flat);
      return !!m && PHRASES.has(m[1].replace(/\s+/g, ' '));
    }
    let w = flat.replace(/[^a-z0-9'\s]/g, ' ').split(/\s+/).filter(Boolean), named = o.named === true;
    if (w[0] === 'hey' || w[0] === 'ok' || w[0] === 'okay') { if (w[1] === 'jarvis') { w = w.slice(2); named = true; } }
    else if (w[0] === 'jarvis') { w = w.slice(1); named = true; }
    const phrase = w.join(' ');
    return PHRASES.has(phrase) && (named || !NEEDS_NAME.has(phrase));
  }

  const shared = () => { try { const V = window.JarvisVoice; return V && V.speaker && typeof V.speaker.say === 'function' ? V.speaker : null; } catch (_) { return null; } };
  function speaker(asked) {
    const sp = shared();
    if (!sp) return null;
    try {
      const V = window.JarvisVoice, dev = typeof V.device === 'function' ? V.device() : null;
      if (!asked && dev && dev.speak === 'never') return null;
      if (typeof V.outputEngine === 'function' && V.outputEngine() === 'none') return null;
    } catch (_) { return null; }
    return sp;
  }
  const talking = (sp) => { try { return !!sp && typeof sp.speaking === 'function' && !!sp.speaking(); } catch (_) { return false; } };
  function canHear(text) {
    if (T.speaking || talking(shared()) || Date.now() - T.quietAt < QUIET_MS) return false;
    const B = window.JarvisBarge;
    if (T.said && B && typeof B.isEcho === 'function' && typeof text === 'string' && Date.now() - T.quietAt < ECHO_WINDOW_MS) {
      try { if (B.isEcho(text, T.said, 0, typeof B.margin === 'function' ? B.margin() : undefined)) return false; } catch (_) {}
    }
    return true;
  }

  function unlock(asked) { const sp = speaker(asked); if (sp && typeof sp.unlock === 'function') { try { sp.unlock(); } catch (_) {} } }
  function hook() {
    const sp = shared();
    if (T.hooked || !sp || typeof sp.on !== 'function') return;
    try {
      sp.on('state', (d) => {
        if (!d || d.speaking !== false) return;
        T.quietAt = Date.now(); // any speech ending: the room still rings for a moment
        if (T.speaking && !talking(sp)) ended(); // a speaker still talking is not our end
      });
      T.hooked = true;
    } catch (_) { /* no listener: the estimate below still ends it */ }
  }
  function say(text, then, asked) {
    const sp = speaker(asked);
    if (!sp || !text) { if (then) then(); return; }
    hook();
    stop(false);
    if (talking(sp) && typeof sp.stop === 'function') { try { sp.stop(); } catch (_) {} } // not behind someone else's words
    T.speaking = true; T.afterSpeech = then; T.voiced = true; T.said = text; T.quietAt = Date.now();
    T.timer = setTimeout(ended, Math.min(SPEAK_MAX_MS, text.length * SPEAK_MS_PER_CHAR + SPEAK_SLACK_MS));
    try { sp.say(text); if (typeof sp.end === 'function') sp.end(); } catch (_) { ended(); }
  }
  function ended() {
    if (!T.speaking) return;
    T.speaking = false; T.quietAt = Date.now(); clearTimeout(T.timer);
    const then = T.afterSpeech; T.afterSpeech = null;
    if (then) then();
  }
  function stop(hush) {
    const was = T.speaking;
    T.speaking = false; T.afterSpeech = null; clearTimeout(T.timer);
    if (hush !== false && was) { const sp = speaker(); if (sp && typeof sp.stop === 'function') { try { sp.stop(); } catch (_) {} } }
  }
  window.JarvisSystemsVoice = Object.freeze({ matches, canHear, say, stop, unlock, hook,
    usable: (asked) => !!speaker(asked), speaking: () => T.speaking, voiced: () => T.voiced, forget: () => { T.voiced = false; } });
})();
