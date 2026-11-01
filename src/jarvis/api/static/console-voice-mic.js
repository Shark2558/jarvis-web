// src/jarvis/api/static/console-voice-mic.js — talking to JARVIS from the composer (slice 9 §5,
// docs/plans/phase1-slice9-voice.md). No build step; CSP script-src 'self'.
// The mic button: tap = listen; tap again = stop and send; tap while JARVIS speaks = stop him and
// listen; Esc cancels (listening) or stops (speaking); Ctrl+Space toggles. States idle / listening /
// thinking / speaking, said in aria-pressed, the button's label, the top-bar pill and a live region.
// Engines (§1 D3, per device): the cloud (JarvisAudio frames → energy VAD → WAV → POST
// /v1/voice/transcribe) or the browser's own recognition (interim words in the composer).
// A spoken message goes to the chat with `channel: "voice"`. Replies are spoken per "Speak replies";
// when a spoken turn leaves an approval waiting, JARVIS says only the fixed line "That one needs your
// approval on screen, {honorific}." (D11) and nothing is ever approved by voice.
// "Hey Jarvis" (D12): window.JarvisWake (console-wakeword.js) gets the same 16 kHz frames through a
// gate that drops them while JARVIS listens, thinks or speaks.
// Listens: jarvis:turn / jarvis:turn-end / jarvis:answer / jarvis:switch (console.js),
// jarvis:voice-device (console-voice.js), jarvis:motion. Fires: jarvis:wake {state, note}.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const btn = $('micBtn'), input = $('input'), lineEl = $('voiceLine'), helpEl = $('micHelp'), liveEl = $('voiceLive');
  const V = window.JarvisVoice, A = window.JarvisAudio, Chat = window.JarvisChat;
  if (!btn || !input || !V || !A || !Chat) return;
  const FX = window.JarvisFX || { setVoice() {}, motion: () => 'full' };
  const root = document.documentElement;
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const honorific = () => (typeof Chat.honorific === 'function' && Chat.honorific()) || 'Sir';

  const RELISTEN_MS = 6000;     // conversation mode: listen this long after a spoken reply
  const RELISTEN_DELAY_MS = 350;
  const LINE_MS = 8000;
  const MIN_FRAMES = 4;         // under ~0.3 s is not worth a transcription
  const LABELS = { idle: 'Speak to JARVIS', listening: 'Stop and send', thinking: 'JARVIS is answering', speaking: 'Stop JARVIS and speak' };
  const LIVE = { idle: '', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking' };
  const HELP = {
    blocked: 'The microphone is blocked for JARVIS. Allow it in the site settings (the icon beside the address), then tap the mic again.',
    no_mic: 'No microphone was found. Plug one in or check the sound settings, then tap the mic again.',
    busy: 'Another app is using the microphone. Close it, then tap the mic again.',
    unsupported: 'This browser can\'t record audio here. You can still type.',
    failed: 'The microphone didn\'t start. Please try again.',
    cloud_down: 'Cloud listening isn\'t available right now. In Voice, set Speech engine to Automatic to use this browser\'s recognition, or type.',
  };

  const S = { mode: 'idle', turn: 0, vad: null, unsub: null, rec: null, recText: '', stop: false, cancel: false,
    keep: false, before: '', placeholder: input.getAttribute('placeholder') || '', raf: 0, level: 0, lineTimer: 0,
    relisten: 0, convTimer: 0, fallbackSaid: false, turnChannel: null };

  // ---- state ---------------------------------------------------------------------------------
  function setMode(mode) {
    if (S.mode === mode) return;
    S.mode = mode;
    btn.dataset.state = mode;
    if (mode !== 'listening') btn.classList.remove('nolevel');
    btn.setAttribute('aria-pressed', String(mode === 'listening'));
    btn.setAttribute('aria-label', LABELS[mode]);
    btn.title = mode === 'idle' ? 'Speak (Ctrl + Space)' : LABELS[mode];
    input.setAttribute('placeholder', mode === 'listening' ? 'Listening…' : S.placeholder);
    if (typeof FX.setVoice === 'function') FX.setVoice(mode === 'listening' || mode === 'speaking' ? mode : null);
    if (liveEl) liveEl.textContent = LIVE[mode];
    syncWake();
    levels();
  }
  function say(text) {
    if (!lineEl) return;
    clearTimeout(S.lineTimer);
    lineEl.textContent = text || '';
    if (text) S.lineTimer = setTimeout(() => { lineEl.textContent = ''; }, LINE_MS);
  }
  function help(code) {
    if (!helpEl) return;
    helpEl.textContent = code ? HELP[code] || HELP.failed : '';
    helpEl.hidden = !code;
  }

  // ---- live level: the mic ring, the Core, real data only ---------------------------------------
  function levels() {
    const on = (S.mode === 'listening' || S.mode === 'speaking') && FX.motion() !== 'off';
    if (on && !S.raf) S.raf = requestAnimationFrame(tick);
    if (!on) { cancelAnimationFrame(S.raf); S.raf = 0; S.level = 0; paint(0); }
  }
  function tick() {
    S.raf = 0;
    const raw = S.mode === 'listening' ? (A.isOpen() ? A.level() : 0) : S.mode === 'speaking' ? V.speaker.level() : 0;
    S.level = S.level * 0.55 + raw * 0.45;
    paint(Math.min(1, Math.sqrt(S.level) * 1.8));
    if (S.mode === 'listening' || S.mode === 'speaking') S.raf = requestAnimationFrame(tick);
  }
  let shown = 0;
  function paint(v) {
    shown = v;
    const s = v.toFixed(3);
    btn.style.setProperty('--lvl', s);
    root.style.setProperty('--vlevel', s);
  }
  V.setVisual(() => ({ mode: S.mode === 'listening' || S.mode === 'speaking' ? S.mode : null, level: shown }));
  document.addEventListener('jarvis:motion', levels);

  // ---- listening ----------------------------------------------------------------------------
  /** Start a listening turn. `soft`: conversation mode / wake word (no tap) — quiet when nothing heard. */
  async function listen(opts = {}) {
    if (S.mode === 'listening') return;
    clearTimeout(S.relisten); clearTimeout(S.convTimer);
    if (V.speaker.speaking()) V.speaker.stop();
    V.speaker.unlock();                     // inside the tap: later replies may start playing
    if (A.supported()) A.prime();           // the same, for the microphone's audio context
    help(null);
    const t = ++S.turn;
    S.soft = !!opts.soft;
    setMode('listening');
    await V.load(false);
    if (t !== S.turn || S.mode !== 'listening') return;
    const engine = V.inputEngine();
    if (engine === 'cloud') listenCloud(t);
    else if (engine === 'browser') listenBrowser(t);
    else { setMode('idle'); help(V.device().engine === 'cloud' && A.supported() ? 'cloud_down' : 'unsupported'); releaseMic(); }
  }

  async function listenCloud(t) {
    try { await A.open(); } catch (e) { if (t === S.turn) { setMode('idle'); help(e && e.code); releaseMic(); } return; }
    if (t !== S.turn || S.mode !== 'listening') { releaseMic(); return; }
    A.flush();
    S.vad = window.JarvisVad.create({ noSpeechMs: RELISTEN_MS });
    S.unsub = A.subscribe((frame) => {
      if (t !== S.turn || !S.vad) return;
      const ev = S.vad.push(frame);
      if (!ev) return;
      if (ev.type === 'start') { if (liveEl) liveEl.textContent = 'Hearing you'; return; }
      if (ev.type === 'timeout') { endCapture(); setMode('idle'); if (!S.soft) say('I didn\'t hear anything.'); return; }
      transcribe(t, ev.frames);
    });
  }
  function endCapture() {
    if (S.unsub) { S.unsub(); S.unsub = null; }
    S.vad = null;
    releaseMic();
  }
  /** Close the microphone unless "Hey Jarvis" still needs it (the browser's mic light goes off). */
  function releaseMic() { if (!wake.on && !S.unsub) A.close(); }

  async function transcribe(t, frames) {
    endCapture();
    if (!frames || frames.length < MIN_FRAMES) { setMode('idle'); if (!S.soft) say('I didn\'t catch that.'); return; }
    setMode('thinking');
    if (liveEl) liveEl.textContent = 'Transcribing';
    let r;
    try {
      r = await Chat.raw('/v1/voice/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: window.JarvisWav.encode(frames) });
    } catch (e) {
      if (t === S.turn) { setMode('idle'); if (!e || e.status !== 401) say('Couldn\'t reach JARVIS. Check your connection.'); }
      return;
    }
    if (t !== S.turn) return;
    if (!r.ok) { const f = await V.refused(r); if (t === S.turn) { setMode('idle'); transcribeFailed(f); } return; }
    let j = null;
    try { j = await r.json(); } catch (_) { j = null; }
    const text = j && typeof j.text === 'string' ? clean(j.text) : '';
    if (!text || (j && j.no_speech === true)) { setMode('idle'); if (!S.soft) say('I didn\'t catch that.'); return; }
    deliver(text);
  }
  /** The cloud refused the recording ({error, detail, reason}; Retry-After on 429). 402, 503 and
   *  voice_busy hand listening to this browser's recognition (when the engine is Automatic). */
  function transcribeFailed(f) {
    if (f.status === 401) return;
    if (f.status === 413 || (f.status === 422 && f.code === 'bad_audio')) { say('That recording couldn\'t be used. Please try again.'); return; }
    if (f.status === 429 && f.code !== 'voice_busy') { say('Too many voice requests just now. Wait a moment, then try again.'); return; }
    const what = V.refusal(f.status, f.code, f.reason, f.retryAfter);
    if (what.fallback && what.downMs) {
      V.markDown('stt', what.downMs);
      if (V.inputEngine() === 'browser') {
        say(f.status === 402 ? 'Cloud listening has reached this month\'s limit. Say that again: this browser is listening.'
          : 'Cloud listening isn\'t available. Say that again: this browser is listening.');
        listen();
        return;
      }
      say('Cloud listening isn\'t available right now. You can still type.');
      return;
    }
    say(f.detail || 'JARVIS couldn\'t hear that. Please try again.');
  }
  const clean = (s) => String(s).replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 4000);

  function listenBrowser(t) {
    const R = recognition();
    releaseMic(); // the browser records on its own: our primed audio context is not needed
    btn.classList.toggle('nolevel', !A.isOpen()); // no level to show unless "Hey Jarvis" keeps the mic open
    let rec;
    try { rec = new R(); } catch (_) { setMode('idle'); help('unsupported'); return; }
    S.rec = rec; S.recText = ''; S.stop = false; S.cancel = false; S.before = input.value;
    let finalText = '', interim = '', error = '';
    rec.lang = V.language(); rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      if (t !== S.turn) return;
      interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript; else interim += res[0].transcript;
      }
      clearTimeout(S.convTimer);
      S.recText = clean(finalText + ' ' + interim);
      showWords(S.recText);
    };
    rec.onerror = (e) => { error = e && e.error ? String(e.error) : 'error'; };
    rec.onend = () => {
      if (t !== S.turn) return;
      S.rec = null; clearTimeout(S.convTimer);
      input.classList.remove('interim');
      if (S.cancel) { restore(); setMode('idle'); return; }
      if (error === 'not-allowed' || error === 'service-not-allowed') { restore(); setMode('idle'); help('blocked'); return; }
      if (error === 'audio-capture') { restore(); setMode('idle'); help('no_mic'); return; }
      const text = clean(finalText || interim);
      if (!text) { restore(); setMode('idle'); if (!S.soft) say(error === 'network' ? 'The browser\'s speech service couldn\'t be reached.' : 'I didn\'t hear anything.'); return; }
      restore();
      deliver(text);
    };
    try { rec.start(); } catch (_) { S.rec = null; setMode('idle'); help('failed'); return; }
    if (S.soft) S.convTimer = setTimeout(() => { if (S.rec === rec && !S.recText) { S.cancel = true; try { rec.abort(); } catch (_) {} } }, RELISTEN_MS);
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

  /** A transcript: send it now (default) or leave it in the message box to check first. */
  function deliver(text) {
    const d = V.device();
    if (d.autoSend && !Chat.busy()) {
      setMode('thinking');
      Promise.resolve(Chat.send(text, { channel: 'voice' })).then(ok => { if (!ok && S.mode === 'thinking') setMode('idle'); });
      return;
    }
    const before = input.value.replace(/\s+$/, '');
    input.value = before ? before + ' ' + text : text;
    input.dataset.channel = 'voice'; // console.js sends it as a spoken message when the owner presses Enter
    input.dispatchEvent(new Event('input', { bubbles: true }));
    setMode('idle');
    input.focus();
    say(Chat.busy() ? 'JARVIS is still answering: your words are in the message box.' : 'Check your words, then press Enter to send.');
  }

  /** Tap again while listening: stop now and send what was heard. */
  function stopAndSend() {
    if (S.rec) { S.stop = true; try { S.rec.stop(); } catch (_) {} return; }
    const frames = S.vad ? S.vad.frames() : [];
    if (!frames.length) { cancel(); say('I didn\'t hear anything.'); return; }
    transcribe(S.turn, frames);
  }
  /** Esc while listening: nothing is sent. */
  function cancel() {
    S.turn++;
    if (S.rec) { S.cancel = true; const r = S.rec; S.rec = null; try { r.abort(); } catch (_) {} restore(); }
    endCapture();
    setMode('idle');
    releaseMic();
  }
  function stopAll() {
    clearTimeout(S.relisten); clearTimeout(S.convTimer);
    S.keep = false;
    if (S.mode === 'listening') cancel(); else S.turn++; // a transcription still on its way is dropped
    V.speaker.stop();
    if (S.mode !== 'idle') setMode('idle');
  }
  function press() {
    if (btn.hidden) return;
    if (S.mode === 'listening') { stopAndSend(); return; }
    if (S.mode === 'speaking') { S.keep = false; V.speaker.stop(); listen(); return; } // barge-in + listen
    if (S.mode === 'thinking') { say('JARVIS is still answering.'); return; }
    listen();
  }

  // ---- speaking -------------------------------------------------------------------------------
  const APPROVAL_LINE = () => `That one needs your approval on screen, ${honorific()}.`;
  function speak(chunks, keep) {
    const out = V.outputEngine();
    if (out === 'none' || !chunks.length) { if (S.mode === 'thinking') setMode('idle'); return; }
    V.speaker.browser(out !== 'cloud');
    V.speaker.setRate(V.settings().rate);
    S.keep = keep;
    setMode('speaking');
    chunks.forEach(c => V.speaker.say(c));
    V.speaker.end();
  }
  document.addEventListener('jarvis:answer', (e) => {
    const d = e.detail || {}, dev = V.device();
    const spoken = d.channel === 'voice';
    if (S.mode === 'listening') return; // the owner is already talking again
    if (dev.speak === 'never' || (dev.speak === 'voice' && !spoken) || typeof d.text !== 'string') {
      if (S.mode === 'thinking') setMode('idle');
      return;
    }
    if (spoken && d.approvals > 0) { speak([APPROVAL_LINE()], false); return; } // D11: fixed, wit-free, no re-listen
    const c = window.JarvisSpeechChunker.create({ honorific: honorific() });
    speak(c.push(d.text).concat(c.end()), spoken && dev.keepListening);
  });
  V.speaker.on('state', (d) => {
    if (d.speaking || S.mode !== 'speaking') return;
    const again = d.reason === 'done' && S.keep;
    S.keep = false;
    setMode('idle');
    if (again) S.relisten = setTimeout(() => { if (S.mode === 'idle' && !Chat.busy()) listen({ soft: true }); }, RELISTEN_DELAY_MS);
  });
  V.speaker.on('fallback', (d) => {
    if (S.fallbackSaid) return;
    S.fallbackSaid = true; // once per page load
    say(d && d.reason === 'budget' ? 'This month\'s voice limit is reached: speaking with this browser\'s voice.'
      : 'The cloud voice isn\'t available: speaking with this browser\'s voice.');
    log('info', 'Browser voice in use');
  });

  // ---- the console's own turns ------------------------------------------------------------------
  document.addEventListener('jarvis:turn', (e) => {
    const d = e.detail || {}, dev = V.device();
    // inside the owner's Enter / tap: let the reply's audio start later (only if it will be spoken)
    if (d.channel === 'voice' ? dev.speak !== 'never' : dev.speak === 'always') V.speaker.unlock();
    if (d.channel === 'voice') { clearTimeout(S.relisten); if (S.mode !== 'thinking') setMode('thinking'); return; }
    stopAll(); // a typed message is a barge-in too
  });
  document.addEventListener('jarvis:turn-end', (e) => {
    const d = e.detail || {};
    if (!d.ok && S.mode === 'thinking') setMode('idle');
  });
  document.addEventListener('jarvis:switch', stopAll); // new or another conversation: silence

  // ---- keys and the button ------------------------------------------------------------------------
  btn.addEventListener('click', press);
  document.addEventListener('keydown', (e) => {
    if (e.isComposing || btn.hidden) return;
    if (e.ctrlKey && !e.altKey && !e.metaKey && (e.code === 'Space' || e.key === ' ')) { e.preventDefault(); press(); return; }
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    if (S.mode === 'listening') { e.preventDefault(); e.stopPropagation(); cancel(); if (liveEl) liveEl.textContent = 'Cancelled'; }
    else if (S.mode === 'speaking') { e.preventDefault(); e.stopPropagation(); stopAll(); if (liveEl) liveEl.textContent = 'Stopped'; }
  }, true);
  input.addEventListener('input', () => { if (!input.value.trim()) delete input.dataset.channel; });

  // ---- "Hey Jarvis" (D12): on-device, opt-in, frames gated while JARVIS is busy -----------------------
  const wake = { on: false, handle: null, subs: new Set(), armed: false, seq: 0 };
  const wakeApi = () => window.JarvisWake || null;
  const wakeSupported = () => { const W = wakeApi(); try { return !!(W && typeof W.supported === 'function' && W.supported()); } catch (_) { return false; } };
  function wakeState(state, note) { emit('jarvis:wake', { state, note: note || '' }); }
  function syncWake() {
    if (!wake.on) return;
    if (A.suspended()) { wakeState('resume'); armResume(); return; }
    wakeState(S.mode === 'idle' ? 'on' : 'paused');
  }
  function gated(fn) {
    if (typeof fn !== 'function') return () => {};
    const un = A.subscribe((frame) => { if (wake.on && S.mode === 'idle' && !V.speaker.speaking()) fn(frame); });
    const off = () => { un(); wake.subs.delete(off); };
    wake.subs.add(off);
    return off;
  }
  async function wakeStart() {
    const W = wakeApi(), my = ++wake.seq;
    if (!wakeSupported()) { wakeState('off'); return; }
    wake.on = true;
    wakeState('loading');
    try {
      const opened = A.open();               // inside the switch's click when the owner turns it on
      if (typeof W.load === 'function') await W.load();
      await opened;
      if (my !== wake.seq || !wake.on) return;
      wake.handle = await W.start({ subscribe: gated, sampleRate: A.SAMPLE_RATE }, onWake);
      if (my !== wake.seq) return;
      syncWake();
      log('info', 'Listening for "Hey Jarvis"');
    } catch (e) {
      if (my !== wake.seq) return;
      wake.on = false;
      if (e && e.code && HELP[e.code]) help(e.code);
      wakeState('error', e && e.code === 'blocked' ? 'The microphone is blocked, so ‘Hey Jarvis’ can\'t listen.' : 'Couldn\'t start ‘Hey Jarvis’ in this browser.');
      if (S.mode !== 'listening') A.close();
    }
  }
  function wakeStop() {
    wake.seq++;
    const W = wakeApi(), h = wake.handle;
    wake.on = false; wake.handle = null;
    try { if (h && typeof h.stop === 'function') h.stop(); else if (W && typeof W.stop === 'function') W.stop(); } catch (_) {}
    Array.from(wake.subs).forEach(off => off());
    wakeState('off');
    if (S.mode !== 'listening') A.close();
  }
  function onWake() {
    if (!wake.on || S.mode !== 'idle' || Chat.busy()) return;
    log('info', '"Hey Jarvis" heard');
    listen({ soft: true });
  }
  /** After a reload the audio context may wait for a gesture: the first tap anywhere resumes it. */
  function armResume() {
    if (wake.armed) return;
    wake.armed = true;
    const go = () => {
      wake.armed = false;
      document.removeEventListener('pointerdown', go, true); document.removeEventListener('keydown', go, true);
      Promise.resolve(A.resume()).then(syncWake, syncWake);
    };
    document.addEventListener('pointerdown', go, true); document.addEventListener('keydown', go, true);
  }
  document.addEventListener('jarvis:voice-device', (e) => {
    const d = e.detail || {};
    if (d.wake && !wake.on) wakeStart();
    else if (!d.wake && wake.on) wakeStop();
  });
  function bootWake() { if (V.device().wake && !wake.on) wakeStart(); }

  // ---- boot ----------------------------------------------------------------------------------
  btn.hidden = !(A.supported() || recognition());
  btn.dataset.state = 'idle';
  document.addEventListener('jarvis:ready', bootWake);
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) bootWake();
  window.addEventListener('pagehide', () => { stopAll(); if (wake.on) wakeStop(); A.close(); });
})();
