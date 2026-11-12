// src/jarvis/api/static/console-voice-loop-browser.js - R5 (docs/plans/r5-voice.md workstream A): the
// browser's own speech recognition for a listening turn (engine "browser"), moved out of console-voice-mic.js.
// window.JarvisLoopBrowser.create(host) -> {listen(turn, retried), restore(), showWords(text)}.
// `host` is what the loop lends it: its state S, A (JarvisAudio), V (JarvisVoice), the mic button and the
// composer, and the loop's own functions. The recogniser always comes from JarvisAudio.recognizer() (the mic
// lock refuses it); interim words appear in the composer; a recogniser that refuses recognition hints
// (Web Speech "phrases-not-supported") is retried at once without them. R11.1 D9: it is asked for three
// alternatives; the other two go with the words to "heard / understood as". No build step; CSP script-src 'self'.
(() => {
  'use strict';
  const PHRASES_REFUSED = 'phrases-not-supported'; // Web Speech: the browser can't take recognition hints (V1)
  const BROWSER_RESTART_MS = 4000;                 // the browser recogniser is restarted quietly at most this often

  function create(h) {
    const { S, A, V, btn, input } = h;
    const { help, say, setMode, isListening } = h;
  function listen(t, retried) {
    h.releaseMic(); // the browser records on its own: our primed audio context is not needed
    btn.classList.toggle('nolevel', !A.isOpen()); // no level to show unless "Hey Jarvis" keeps the mic open
    let rec;
    try { rec = A.recognizer(); } catch (e) { S.conv = false; setMode('idle'); help(e && e.code === 'mic_off' ? 'mic_off' : 'unsupported'); return; }
    const P = window.JarvisVoicePhrases;
    // no-op unless the browser can take hints; a browser that refuses them (phrases-not-supported) is never offered them again
    if (!S.noPhrases) { try { if (P && typeof P.apply === 'function') P.apply(rec); } catch (_) {} }
    S.rec = rec; S.recText = ''; S.stop = false; S.cancel = false; S.quietEnd = false; S.before = input.value; S.recStart = performance.now();
    let finalText = '', interim = '', error = '', confidence = null;
    const others = ['', ''];   // the recogniser's second and third guess for the whole turn (R11.1 D9)
    rec.lang = V.language(); rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 3;
    rec.onresult = (e) => {
      if (t !== S.turn) return;
      interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (!res.isFinal) { interim += res[0].transcript; continue; }
        finalText += res[0].transcript;
        for (let k = 0; k < others.length; k++) others[k] += (res[k + 1] || res[0]).transcript;
        if (confidence === null && Number.isFinite(res[0].confidence) && res[0].confidence > 0) confidence = res[0].confidence;
      }
      clearTimeout(S.noSpeech);
      h.markHeard(0);
      S.recText = h.clean(finalText + ' ' + interim);
      showWords(S.recText);
    };
    rec.onerror = (e) => { error = e && e.error ? String(e.error) : 'error'; if (error === PHRASES_REFUSED) S.noPhrases = true; };
    rec.onend = () => {
      if (t !== S.turn) return;
      S.rec = null; h.clearClocks();
      h.releaseMic(); // in case "Hey Jarvis" was switched off meanwhile
      input.classList.remove('interim');
      if (error === PHRASES_REFUSED && !retried && !S.cancel && !A.locked()) { restore(); listen(t, true); return; } // V1: the same turn, at once, without the hints
      if (S.cancel) {
        restore(); setMode('idle');
        if (S.quietEnd && !S.soft) say('I didn\'t hear anything.');
        return;
      }
      if (error === 'not-allowed' || error === 'service-not-allowed') { restore(); S.conv = false; setMode('idle'); help('blocked'); return; }
      if (error === 'audio-capture') { restore(); S.conv = false; setMode('idle'); help('no_mic'); return; }
      const text = h.clean(finalText || interim);
      if (!text && S.holdWait && S.conv && h.getClock() && h.getClock().waiting() && !A.locked()) { restore(); restart(t); return; }
      if (!text) { restore(); S.conv = false; setMode('idle'); if (!S.soft) say(error === 'network' ? 'The browser\'s speech service couldn\'t be reached.' : 'I didn\'t hear anything.'); return; }
      restore();
      const alternatives = finalText ? others.map(h.clean).filter(a => a && a !== text) : [];
      h.deliver(text, { state: 'listening', alternatives, confidence });
    };
    try { rec.start(); } catch (_) { S.rec = null; S.conv = false; setMode('idle'); help('failed'); return; }
    h.startClocks(t);
  }
  /** The browser recogniser gives up after a few silent seconds: start it again quietly, not faster than every 4 s. */
  function restart(t) {
    const wait = Math.max(0, BROWSER_RESTART_MS - (performance.now() - S.recStart));
    S.browserTimer = setTimeout(() => { if (t === S.turn && isListening() && !S.rec && !A.locked()) listen(t); }, wait);
  }
  function showWords(text) {
    input.classList.add('interim');
    input.value = (S.before ? S.before.replace(/\s+$/, '') + ' ' : '') + text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function restore() {
    input.classList.remove('interim');
    input.value = S.before;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
    return { listen, restore, showWords };
  }
  window.JarvisLoopBrowser = Object.freeze({ create });
})();
