// src/jarvis/api/static/console-voice-mic.js — talking to JARVIS from the composer (slice 9 §5,
// docs/plans/phase1-slice9-voice.md). No build step; CSP script-src 'self'.
// The mic button: tap = listen; tap again = stop and send; tap while JARVIS speaks = stop him and
// listen; Esc cancels (listening), stops (speaking) or drops the turn (thinking: the transcript is
// discarded, or the answer is shown but not spoken); Ctrl+Space toggles. States idle / listening /
// thinking / speaking: the button's name stays "Voice input"; the state is said by aria-pressed
// (listening), the top-bar pill and a polite live region.
// Engines (§1 D3, per device): the cloud (JarvisAudio frames → energy VAD → WAV → POST
// /v1/voice/transcribe) or the browser's own recognition (interim words in the composer).
// Listening has wall-clock limits as well as the VAD's: nothing heard in 6 s (3 s after a reply in
// conversation mode) ends it; 30 s sends what was heard. Conversation mode ("Keep listening")
// carries on hands-free for at most 3 turns after a tap or "Hey Jarvis", then waits for a tap.
// A spoken message goes to the chat with `channel: "voice"`. Replies are spoken per "Speak replies";
// when a spoken turn leaves an approval waiting, JARVIS says only the fixed line "That one needs your
// approval on screen, {honorific}." (D11) and nothing is ever approved by voice.
// "Hey Jarvis" (D12): window.JarvisWake (console-wakeword.js) gets the same 16 kHz frames; it is
// paused (JarvisWake.pause()) while JARVIS listens, thinks or speaks, and resumed ~0.4 s after the
// last clip ends. Its state is checked every second: an error switches it off with a plain line.
// R5 I0 (docs/plans/r5-voice.md): the hard mic lock (JarvisAudio.lock) is honoured here: listen()
// refuses while locked, the browser recogniser is built through JarvisAudio.recognizer(), a lock
// cancels the turn and shows the 'off' state, and "Hey Jarvis" waits ('micoff' chip). The minimal
// window.JarvisVoiceLoop (state, inConversation, say, ask, offer, end) is the seam the devices module
// and the tests use; workstream A completes the loop behind the same shape.
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
  const JC = window.JarvisConsole;
  const signedIn = () => !!(JC && typeof JC.ready === 'function' && JC.ready());

  const NO_SPEECH_MS = 6000;       // a tap: nothing heard this long after the mic opened → stop
  const RELISTEN_START_MS = 3000;  // conversation mode: speech must start this soon after a reply
  const MAX_LISTEN_MS = 30000;     // one listening turn at most, whatever the frames say
  const MAX_HANDS_FREE = 3;        // follow-up turns without a tap (or "Hey Jarvis")
  const RELISTEN_DELAY_MS = 350;
  const LINE_MS = 8000;
  const MIN_FRAMES = 4;            // under ~0.3 s is not worth a transcription
  const NAME = 'Voice input';
  const TITLES = { idle: 'Speak (Ctrl + Space)', listening: 'Stop and send', thinking: 'JARVIS is answering', speaking: 'Stop JARVIS and speak',
    standby: 'Speak (Ctrl + Space)', off: 'Microphone off: switch it on in Voice' };
  const LIVE = { idle: '', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', standby: 'Standing by', off: 'Microphone off' };
  const FX_MODE = { listening: 'listening', speaking: 'speaking', standby: 'standby', off: 'micoff' };
  const OFFER_MS = 30000;
  const LOCKED_LINE = 'The microphone is switched off. Switch it on in the Voice panel.';
  const HELP = {
    blocked: 'The microphone is blocked for JARVIS. Allow it in the site settings (the icon beside the address), then tap the mic again.',
    no_mic: 'No microphone was found. Plug one in or check the sound settings, then tap the mic again.',
    busy: 'Another app is using the microphone. Close it, then tap the mic again.',
    unsupported: 'This browser can\'t record audio here. You can still type.',
    failed: 'The microphone didn\'t start. Please try again.',
    ended: 'The microphone stopped (unplugged or switched off). Check it, then tap the mic again.',
    mic_off: LOCKED_LINE,
    cloud_down: 'Cloud listening isn\'t available right now. In Voice, set Speech engine to Automatic to use this browser\'s recognition, or type.',
  };

  const S = { mode: 'idle', turn: 0, vad: null, unsub: null, rec: null, recText: '', stop: false, cancel: false,
    keep: false, before: '', placeholder: input.getAttribute('placeholder') || '', raf: 0, level: 0, lineTimer: 0,
    relisten: 0, convTimer: 0, fallbackSaid: false, soft: false, startMs: NO_SPEECH_MS, chain: 0, mute: false,
    noSpeech: 0, maxTimer: 0, spoken: [] };

  // ---- state ---------------------------------------------------------------------------------
  function setMode(mode) {
    if (mode === 'idle' && A.locked()) mode = 'off';   // at rest while the microphone is locked
    if (S.mode === mode) return;
    S.mode = mode;
    btn.dataset.state = mode;
    if (mode !== 'listening') { btn.classList.remove('nolevel'); clearClocks(); }
    btn.setAttribute('aria-pressed', String(mode === 'listening'));
    btn.title = TITLES[mode];
    input.setAttribute('placeholder', mode === 'listening' ? 'Listening…' : S.placeholder);
    if (typeof FX.setVoice === 'function') FX.setVoice(FX_MODE[mode] || null);
    if (liveEl) liveEl.textContent = LIVE[mode];
    emit('jarvis:voice-loop', { state: mode, conversation: inConversation(), turns: S.chain });
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
  /** Start a listening turn. opts.soft: started without a tap ("Hey Jarvis"), so quiet when nothing
   *  is heard; opts.relisten: conversation mode after a spoken reply (speech must start within 3 s,
   *  and it counts towards the hands-free limit). Anything else (a tap) starts a new conversation. */
  async function listen(opts = {}) {
    if (S.mode === 'listening') return;
    if (A.locked()) { say(LOCKED_LINE); return; }     // D11: nothing listens while the microphone is off
    clearTimeout(S.relisten); clearTimeout(S.convTimer);
    if (V.speaker.speaking()) V.speaker.stop();
    V.speaker.unlock();                     // inside the tap: later replies may start playing
    if (A.supported()) A.prime();           // the same, for the microphone's audio context
    help(null);
    const t = ++S.turn;
    S.soft = !!(opts.soft || opts.relisten);
    S.startMs = opts.relisten ? RELISTEN_START_MS : NO_SPEECH_MS;
    if (!opts.relisten) S.chain = 0;
    setMode('listening');
    await V.load(false);
    if (t !== S.turn || S.mode !== 'listening') return;
    const engine = V.inputEngine();
    if (engine === 'cloud') listenCloud(t);
    else if (engine === 'browser') listenBrowser(t);
    else { setMode('idle'); help(V.device().engine === 'cloud' && A.supported() ? 'cloud_down' : 'unsupported'); releaseMic(); }
  }

  /** Wall-clock limits, independent of frames (a stalled worklet or a suspended context sends none). */
  function startClocks(t) {
    clearClocks();
    S.noSpeech = setTimeout(() => { if (t === S.turn && S.mode === 'listening') nothingHeard(); }, S.startMs);
    S.maxTimer = setTimeout(() => { if (t === S.turn && S.mode === 'listening') stopAndSend(); }, MAX_LISTEN_MS);
  }
  function clearClocks() {
    clearTimeout(S.noSpeech); clearTimeout(S.maxTimer); clearTimeout(S.convTimer);
    S.noSpeech = S.maxTimer = S.convTimer = 0;
  }
  function nothingHeard() {
    if (S.rec) { S.cancel = true; S.quietEnd = true; try { S.rec.abort(); } catch (_) {} return; } // its onend says it
    endCapture();
    setMode('idle');
    if (!S.soft) say('I didn\'t hear anything.');
  }

  async function listenCloud(t) {
    try { await A.open(); } catch (e) {
      if (t === S.turn) { setMode('idle'); if (!e || e.code !== 'closed') help(e && e.code); releaseMic(); }
      return;
    }
    if (t !== S.turn || S.mode !== 'listening') { if (S.mode !== 'listening') releaseMic(); return; } // a newer turn keeps it
    A.flush();
    S.vad = window.JarvisVad.create({ noSpeechMs: S.startMs });
    startClocks(t);
    S.unsub = A.subscribe((frame) => {
      if (t !== S.turn || !S.vad) return;
      const ev = S.vad.push(frame);
      if (!ev) return;
      if (ev.type === 'start') { clearTimeout(S.noSpeech); if (liveEl) liveEl.textContent = 'Hearing you'; return; }
      if (ev.type === 'timeout') { nothingHeard(); return; }
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
    if (t !== S.turn) return;
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
    releaseMic(); // the browser records on its own: our primed audio context is not needed
    btn.classList.toggle('nolevel', !A.isOpen()); // no level to show unless "Hey Jarvis" keeps the mic open
    let rec;
    try { rec = A.recognizer(); } catch (e) { setMode('idle'); help(e && e.code === 'mic_off' ? 'mic_off' : 'unsupported'); return; }
    S.rec = rec; S.recText = ''; S.stop = false; S.cancel = false; S.quietEnd = false; S.before = input.value;
    let finalText = '', interim = '', error = '';
    rec.lang = V.language(); rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      if (t !== S.turn) return;
      interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript; else interim += res[0].transcript;
      }
      clearTimeout(S.noSpeech);
      S.recText = clean(finalText + ' ' + interim);
      showWords(S.recText);
    };
    rec.onerror = (e) => { error = e && e.error ? String(e.error) : 'error'; };
    rec.onend = () => {
      if (t !== S.turn) return;
      S.rec = null; clearClocks();
      releaseMic(); // in case "Hey Jarvis" was switched off meanwhile
      input.classList.remove('interim');
      if (S.cancel) {
        restore(); setMode('idle');
        if (S.quietEnd && !S.soft) say('I didn\'t hear anything.');
        return;
      }
      if (error === 'not-allowed' || error === 'service-not-allowed') { restore(); setMode('idle'); help('blocked'); return; }
      if (error === 'audio-capture') { restore(); setMode('idle'); help('no_mic'); return; }
      const text = clean(finalText || interim);
      if (!text) { restore(); setMode('idle'); if (!S.soft) say(error === 'network' ? 'The browser\'s speech service couldn\'t be reached.' : 'I didn\'t hear anything.'); return; }
      restore();
      deliver(text);
    };
    try { rec.start(); } catch (_) { S.rec = null; setMode('idle'); help('failed'); return; }
    startClocks(t);
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

  /** Tap again while listening (or 30 s are up): stop now and send what was heard. */
  function stopAndSend() {
    if (S.rec) { S.stop = true; try { S.rec.stop(); } catch (_) {} return; }
    const frames = S.vad ? S.vad.frames() : [];
    if (!frames.length) { cancel(); if (!S.soft) say('I didn\'t hear anything.'); return; }
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
  /** Esc while JARVIS is working on a spoken turn: a transcript on its way is dropped; a message
   *  already sent is answered on screen, but not out loud (and no conversation-mode re-listen). */
  function abandon() {
    S.turn++;
    if (Chat.busy()) S.mute = true;
    clearTimeout(S.relisten);
    S.keep = false;
    setMode('idle');
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
    if (A.locked()) { say(LOCKED_LINE); return; }
    S.chain = 0;                                                                        // the owner is here
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
    if (S.mute) { S.mute = false; if (S.mode === 'thinking') setMode('idle'); return; } // Esc'd: shown, not said
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
    syncWake(); // a Preview in the Voice panel speaks too: the wake word must not hear it
    if (!d.speaking) S.spoken.splice(0).forEach(r => r());
    if (d.speaking || S.mode !== 'speaking') return;
    const wanted = d.reason === 'done' && S.keep;
    const again = wanted && S.chain < MAX_HANDS_FREE;
    S.keep = false;
    setMode('idle');
    if (again) {
      S.chain++;
      S.relisten = setTimeout(() => { if (S.mode === 'idle' && !Chat.busy()) listen({ relisten: true }); }, RELISTEN_DELAY_MS);
    } else if (wanted) say('Tap the mic to carry on.');
  });
  V.speaker.on('fallback', (d) => {
    const reason = d && d.reason;
    if (reason === 'blocked') { say('This browser is holding JARVIS\'s audio back: tap the page once. Speaking with this browser\'s voice for now.'); return; }
    if (S.fallbackSaid) return;
    S.fallbackSaid = true; // once per page load
    say(reason === 'budget' ? 'This month\'s voice limit is reached: speaking with this browser\'s voice.'
      : 'The cloud voice isn\'t available: speaking with this browser\'s voice.');
    log('info', 'Browser voice in use');
  });

  // ---- the console's own turns ------------------------------------------------------------------
  document.addEventListener('jarvis:turn', (e) => {
    const d = e.detail || {}, dev = V.device();
    // inside the owner's Enter / tap: let the reply's audio start later (only if it will be spoken)
    if (d.channel === 'voice' ? dev.speak !== 'never' : dev.speak === 'always') V.speaker.unlock();
    if (d.channel === 'voice') { clearTimeout(S.relisten); S.mute = false; if (S.mode !== 'thinking') setMode('thinking'); return; }
    S.chain = 0;
    stopAll(); // a typed message is a barge-in too
  });
  document.addEventListener('jarvis:turn-end', (e) => {
    const d = e.detail || {};
    S.mute = false;
    if (!d.ok && S.mode === 'thinking') setMode('idle');
  });
  document.addEventListener('jarvis:switch', stopAll); // new or another conversation: silence

  // ---- the microphone stopped by itself (unplugged, switched off) ---------------------------------
  A.onEnd(() => {
    if (wake.on) wakeFail(wake.UNPLUGGED);
    if (S.mode === 'listening' && !S.rec) { cancel(); help('ended'); }
  });

  // ---- the hard microphone lock (R5 D11) ------------------------------------------------------------
  A.onLock(({ locked }) => {
    if (!locked) { if (S.mode === 'off') setMode('idle'); bootWake(); return; }
    clearTimeout(S.relisten); clearTimeout(S.convTimer);
    S.keep = false;                                    // no re-listen after a reply that is still playing
    if (S.mode === 'listening') cancel();              // nothing is sent
    else if (S.mode === 'thinking' && !Chat.busy()) S.turn++; // a transcription on its way is dropped
    if (wake.on) { wakeHalt(); wakeState('micoff'); } else if (V.device().wake) wakeState('micoff');
    if (S.mode === 'idle' || (S.mode === 'thinking' && !Chat.busy())) setMode('off');
  });

  // ---- keys and the button ------------------------------------------------------------------------
  btn.addEventListener('click', press);
  document.addEventListener('keydown', (e) => {
    if (e.isComposing || btn.hidden) return;
    if (e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey && (e.code === 'Space' || e.key === ' ')) { e.preventDefault(); press(); return; }
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    let said = '';
    if (S.mode === 'listening') { cancel(); said = 'Cancelled'; }
    else if (S.mode === 'speaking') { stopAll(); said = 'Stopped'; }
    else if (S.mode === 'thinking') { abandon(); said = 'Cancelled'; }
    if (!said) return;
    e.preventDefault(); e.stopPropagation();
    if (liveEl) liveEl.textContent = said;
  }, true);
  input.addEventListener('input', () => { if (!input.value.trim()) delete input.dataset.channel; });

  // ---- "Hey Jarvis" (D12) lives in console-voice-wake.js ------------------------------------------
  const wake = window.JarvisWakeCtl.create({ A, V, Chat, emit, log, help, HELP, signedIn,
    busy: () => S.mode !== 'idle' || V.speaker.speaking(),
    listen: (o) => listen(o),
    micInUse: () => S.mode === 'listening' || !!S.unsub });
  const syncWake = () => wake.sync(), wakeHalt = () => wake.halt(), wakeState = (s, n) => wake.state(s, n);
  const wakeStop = () => wake.stop(), wakeFail = (n) => wake.fail(n), bootWake = () => wake.boot();


  // ---- boot ----------------------------------------------------------------------------------
  btn.hidden = !(A.supported() || recognition());
  btn.dataset.state = 'idle';
  btn.setAttribute('aria-label', NAME);
  btn.title = TITLES.idle;
  if (A.locked()) setMode('off');
  document.addEventListener('jarvis:ready', bootWake);
  if (JC && typeof JC.ready === 'function' && JC.ready()) bootWake();
  document.addEventListener('DOMContentLoaded', bootWake);
  window.addEventListener('load', bootWake);
  // Leaving the page: microphone and wake word off. Back from the back/forward cache: on again if
  // saved. (A hidden tab keeps listening on purpose: "Hey Jarvis" works from another tab on desktop.)
  window.addEventListener('pagehide', () => { stopAll(); if (wake.on) wakeStop(); A.close(); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) bootWake(); });

  // ---- window.JarvisVoiceLoop: the seam other modules use (workstream A completes it) ---------------
  const offerEl = $('voiceOffer');
  let offerTimer = 0;
  function inConversation() { return (S.mode !== 'idle' && S.mode !== 'off') || S.chain > 0; }
  function clearOffer() {
    clearTimeout(offerTimer); offerTimer = 0;
    if (offerEl) { offerEl.textContent = ''; offerEl.hidden = true; }
  }
  /** Show a line and, with {speak: true}, say it out loud (not over a turn in progress). Resolves when said. */
  function loopSay(text, o) {
    if (typeof text !== 'string' || !text.trim()) return Promise.resolve();
    const t = text.trim().slice(0, 300);
    say(t);
    if (!(o && o.speak === true) || V.device().speak === 'never' || V.outputEngine() === 'none') return Promise.resolve();
    if (S.mode !== 'idle' && S.mode !== 'off') return Promise.resolve();
    return new Promise(resolve => { S.spoken.push(resolve); speak([t], false); });
  }
  /** Ask a yes / no question: said aloud, then the router waits for the answer ('yes' | 'no' | 'timeout' | 'cancelled'). */
  function loopAsk(question, o) {
    const C = window.JarvisVoiceCommands;
    loopSay(question, { speak: true });
    return C ? C.ask(question, o) : Promise.resolve('timeout');
  }
  /** A suggestion with buttons under the voice line for 30 s; returns a function that removes it. */
  function loopOffer(text, actions) {
    const list = (Array.isArray(actions) ? actions : []).filter(a => a && typeof a.label === 'string' && typeof a.run === 'function').slice(0, 3);
    if (!offerEl || typeof text !== 'string' || !text.trim() || !list.length) return () => {};
    clearOffer();
    const msg = document.createElement('span');
    msg.textContent = text.trim().slice(0, 200);
    offerEl.append(msg);
    list.forEach(a => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn lift bact'; b.textContent = a.label.slice(0, 40);
      b.addEventListener('click', () => { clearOffer(); try { a.run(); } catch (_) {} });
      offerEl.append(b);
    });
    offerEl.hidden = false;
    const mine = offerTimer = setTimeout(clearOffer, OFFER_MS);
    return () => { if (offerTimer === mine) clearOffer(); };
  }
  /** End the voice conversation: stop listening and speaking; the keyboard gets the focus. */
  function loopEnd(reason) {
    clearOffer();
    S.chain = 0;
    stopAll();
    if (reason === 'keyboard' || reason === 'pause') input.focus();
  }
  window.JarvisVoiceLoop = Object.freeze({
    state: () => S.mode,
    inConversation,
    say: loopSay,
    ask: loopAsk,
    offer: loopOffer,
    end: loopEnd,
  });
})();
