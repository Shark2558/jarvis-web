// src/jarvis/api/static/console-voice-mic.js — talking to JARVIS from the composer (slice 9 §5,
// docs/plans/phase1-slice9-voice.md; R5 "Voice that listens", docs/plans/r5-voice.md D2-D12). No build
// step; CSP script-src 'self'.
// The mic button: tap = listen; tap again = stop and send; tap while JARVIS speaks = stop him and
// listen; Esc cancels (listening), stops (speaking) or drops the turn (thinking); Ctrl+Space toggles.
// States idle / listening / standby / thinking / speaking / handover / off. The button's name stays
// "Voice input"; the state is said by aria-pressed (listening), the top-bar pill and a live region.
// Engines (§1 D3, per device): the cloud (JarvisAudio frames → energy VAD → WAV → POST
// /v1/voice/transcribe) or the browser's own recognition (interim words in the composer).
// A conversation (tap, Ctrl+Space or "Hey Jarvis" with "Keep listening") has NO turn limit (D4): after
// a spoken reply the loop listens for `followUpS`, stands by (a stricter start gate) until `longPauseS`,
// and then tells the owner it is switching to the keyboard (D5). The microphone stays open for the whole
// conversation on the cloud engine (D3), so the owner can talk over JARVIS (console-voice-barge.js, D7);
// a stopped reply is picked up again if the interruption turns out to be empty (D9). A room that keeps
// talking gets a check-in after 8 quick turns (D6, console-voice-conversation.js). Spoken transcripts go
// through the local command router first (D12): "mic off", "stop", "switch to the keyboard", devices.
// A spoken message goes to the chat with `channel: "voice"`. When a spoken turn leaves an approval
// waiting, JARVIS says only the fixed line "That one needs your approval on screen, {honorific}." (D11)
// and nothing is ever approved by voice. "Hey Jarvis" lives in console-voice-wake.js. The hard mic lock
// (JarvisAudio.lock) is honoured everywhere: listen() refuses, nothing re-listens, recognisers come from
// JarvisAudio.recognizer(). window.JarvisVoiceLoop (state, inConversation, say, ask, offer, end) is the
// seam the devices module and the tests use.
// Listens: jarvis:turn / jarvis:turn-end / jarvis:answer / jarvis:switch (console.js),
// jarvis:voice-device (console-voice.js), jarvis:motion. Fires: jarvis:wake, jarvis:voice-loop, jarvis:barge.
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
  const Cmd = () => window.JarvisVoiceCommands || null;
  const Pace = () => window.JarvisVoicePace || { cue: () => Promise.resolve(), mark() {} };
  const CUE_MAX_MS = 800;          // never wait longer than this for a tone: the loop must not hang on a stalled audio context
  const CUE_GAP_MS = 100;          // the VAD starts this long after a cue ends (the tone must not be heard as speech)
  const cue = (name) => { try { return Promise.resolve(Pace().cue(name)).catch(() => {}); } catch (_) { return Promise.resolve(); } };

  const NO_SPEECH_MS = 6000;       // a tap: nothing heard this long after the mic opened → stop
  const MAX_LISTEN_MS = 55000;     // one listening turn at most (STT v1's 60 s synchronous limit)
  const RELISTEN_DELAY_MS = 350;
  const LINE_MS = 8000;
  const MIN_FRAMES = 4;            // under ~0.3 s is not worth a transcription
  const VAD_LAG_MS = 160;          // two frames of speech before the VAD says "start"
  const ECHO_AFTER_MS = 3000;      // a turn that began this soon after a reply ended may be the room's reverb of it (SM4)
  const SAID_MS = 4000;            // JARVIS's own words kept this long for the echo guard
  const FILLER = new Set(['um', 'uh', 'hmm', 'mm', 'uhm', 'er', 'ah', 'umm', 'uhh', 'hm', 'mhm']);
  const FIXED = window.JarvisLoopGlue.FIXED;      // fixed lines: their audio is cached per page
  const NAME = 'Voice input';
  const TITLES = { idle: 'Speak (Ctrl + Space)', listening: 'Stop and send', thinking: 'JARVIS is answering', speaking: 'Stop JARVIS and speak',
    standby: 'Speak (Ctrl + Space)', off: 'Microphone off: tap to switch it on (Ctrl + Shift + Space)' };
  const LIVE = { idle: '', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', standby: 'Standing by', off: 'Microphone off', handover: 'Speaking' };
  const FX_MODE = { listening: 'listening', speaking: 'speaking', standby: 'standby', off: 'micoff' };
  const OFFER_MS = 30000;
  const LOCKED_LINE = 'The microphone is switched off. Switch it on with the mic button (or Ctrl + Shift + Space).';
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
    relisten: 0, fallbackSaid: false, soft: false, startMs: NO_SPEECH_MS, chain: 0, mute: false,
    noSpeech: 0, maxTimer: 0, spoken: [],
    conv: false, handsFree: '', holdWait: false, heardMarked: false, seed: null, info: null, recStart: 0,
    said: [], rest: null, restAt: 0, restKeep: false, silent: false, handing: false, checking: false,
    barge: null, abort: null, nameOff: false, browserTimer: 0, noPhrases: false, realAt: 0, empties: 0, closeAfter: false, wakeGate: false, replyEndAt: 0, turnAt: 0, bargeOff: false, resumed: false };
  let clock = null;                                    // the follow-up / standby / long-pause clock of this reply
  const runaway = window.JarvisConversation.runaway();
  const isListening = () => S.mode === 'listening' || S.mode === 'standby';
  // the conversation glue (barge, check-in, handover, built-in command actions): console-voice-loop-glue.js
  const glue = window.JarvisLoopGlue.create({ S, A, V, Chat, emit, log, input, Cmd, runaway, wake: () => wake,
    saidText: () => saidText(), inConversation: () => inConversation(), setMode: (m) => setMode(m), speak: (...a) => speak(...a), silence: () => silence(),
    listen: (o) => listen(o), deliver: (t, o) => deliver(t, o), settle: (r) => settle(r), say: (t) => say(t),
    cue: (n) => cue(n), honorific, loopSay: (t, o) => loopSay(t, o), startClock: () => startClock(),
    stopClock: () => stopClock(), resumeListening: () => resumeListening(), isListening, restore: () => browserEngine.restore(),
    endCapture: () => endCapture(), releaseMic: () => releaseMic(),
    answering: () => S.mode === 'thinking' || !!(S.vad && S.vad.started()) || !!S.recText });
  const { armBarge, disarmBarge, bargeWake, resumeSpeech, bindCommands, speakWake, checkIn, handover, finishHandover } = glue;
  // the browser's own recognition (engine 'browser'): console-voice-loop-browser.js
  const browserEngine = window.JarvisLoopBrowser.create({ S, A, V, btn, input, getClock: () => clock, help, say, setMode,
    isListening, releaseMic: () => releaseMic(), clearClocks: () => clearClocks(), startClocks: (t) => startClocks(t),
    markHeard: (n) => markHeard(n), clean: (x) => clean(x), deliver: (t, o) => deliver(t, o) });

  // ---- state ---------------------------------------------------------------------------------
  function setMode(mode) {
    if (mode === 'idle' && A.locked()) mode = 'off';   // at rest while the microphone is locked
    if (S.mode === mode) return;
    if (S.mode === 'handover' && mode !== 'handover') S.handing = false;   // never stuck "handing over" (M1)
    S.mode = mode;
    const shown = mode === 'handover' ? 'speaking' : mode;
    btn.dataset.state = shown;
    if (!isListening()) { btn.classList.remove('nolevel'); clearClocks(); }
    btn.setAttribute('aria-pressed', String(mode === 'listening'));
    btn.title = TITLES[shown];
    input.setAttribute('placeholder', mode === 'listening' ? 'Listening…' : S.placeholder);
    if (typeof FX.setVoice === 'function') FX.setVoice(FX_MODE[shown] || null);
    if (liveEl) liveEl.textContent = LIVE[mode];
    emit('jarvis:voice-loop', { state: mode, conversation: inConversation(), turns: S.chain, barge: S.handsFree === 'barge' });   // barge: an interruption's own turn (no cue)
    if (mode === 'speaking') armBarge(); else disarmBarge();
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
  const lit = () => S.mode === 'listening' || S.mode === 'speaking' || S.mode === 'handover';
  function levels() {
    const on = lit() && FX.motion() !== 'off';
    if (on && !S.raf) S.raf = requestAnimationFrame(tick);
    if (!on) { cancelAnimationFrame(S.raf); S.raf = 0; S.level = 0; paint(0); }
  }
  function tick() {
    S.raf = 0;
    const raw = S.mode === 'listening' ? (A.isOpen() ? A.level() : 0) : lit() ? V.speaker.level() : 0;
    S.level = S.level * 0.55 + raw * 0.45;
    paint(Math.min(1, Math.sqrt(S.level) * 1.8));
    if (lit()) S.raf = requestAnimationFrame(tick);
  }
  let shown = 0;
  function paint(v) {
    shown = v;
    const s = v.toFixed(3);
    btn.style.setProperty('--lvl', s);
    root.style.setProperty('--vlevel', s);
  }
  V.setVisual(() => ({ mode: S.mode === 'listening' ? 'listening' : (S.mode === 'speaking' || S.mode === 'handover') ? 'speaking' : null, level: shown }));
  document.addEventListener('jarvis:motion', levels);

  // ---- listening ----------------------------------------------------------------------------
  /** Start a listening turn. opts.soft: started without a tap ("Hey Jarvis"), so quiet when nothing
   *  is heard; opts.relisten: the next turn of a conversation (the clock decides when to give up);
   *  opts.barge (+ seed frames): the owner talked over JARVIS. Anything else starts a conversation. */
  async function listen(opts = {}) {
    if (isListening()) return;
    if (A.locked()) { say(LOCKED_LINE); return; }
    clearTimeout(S.relisten); clearTimeout(S.browserTimer);
    if (V.speaker.speaking()) silence();
    V.speaker.unlock();                     // inside the tap: later replies may start playing
    if (A.supported()) A.prime();           // the same, for the microphone's audio context
    help(null);
    const t = ++S.turn;
    const hands = !!(opts.relisten || opts.barge);
    S.turnAt = performance.now();
    S.soft = !!(opts.soft || hands);
    S.handsFree = opts.barge ? 'barge' : opts.relisten ? 'relisten' : '';
    S.holdWait = hands; S.heardMarked = false; S.seed = opts.seed || null; S.info = opts.info || null;
    S.startMs = NO_SPEECH_MS;
    if (!hands) { S.chain = 0; S.rest = null; S.conv = !!V.device().keepListening; S.realAt = performance.now(); S.empties = 0; stopClock(); }
    setMode('listening');
    const cued = opts.barge ? null : cue('listen');      // an interruption starts at once, without a tone
    await V.load(false);
    if (t !== S.turn || !isListening()) return;
    const engine = V.inputEngine();
    if (engine === 'cloud') listenCloud(t, cued);
    else if (engine === 'browser') browserEngine.listen(t);
    else { S.conv = false; setMode('idle'); help(V.device().engine === 'cloud' && A.supported() ? 'cloud_down' : 'unsupported'); releaseMic(); }
  }

  /** Wall-clock limits, independent of frames (a stalled worklet or a suspended context sends none). */
  function startClocks(t) {
    clearClocks();
    if (!S.holdWait) S.noSpeech = setTimeout(() => { if (t === S.turn && isListening()) nothingHeard(); }, S.startMs);
    S.maxTimer = setTimeout(() => { if (t === S.turn && isListening()) stopAndSend(); }, MAX_LISTEN_MS);
  }
  function clearClocks() {
    clearTimeout(S.noSpeech); clearTimeout(S.maxTimer);
    S.noSpeech = S.maxTimer = 0;
  }
  function nothingHeard() {
    S.conv = false; stopClock();
    if (S.rec) { S.cancel = true; S.quietEnd = true; try { S.rec.abort(); } catch (_) {} return; } // its onend says it
    endCapture();
    setMode('idle');
    if (!S.soft) say('I didn\'t hear anything.');
  }
  /** The owner began to speak: the waits stop, and the turn counts for the check-in (D6). */
  function markHeard(lagMs) {
    if (S.heardMarked) return;
    S.heardMarked = true;
    if (S.rec) { try { Pace().mark('spoke'); } catch (_) {} }   // the browser engine: when its first words came (the cloud engine marks at the VAD's end)
    clock && clock.heard();
    if (S.mode === 'standby') setMode('listening');
    if (!S.handsFree) { runaway.touch(); return; }
    // the gap is measured from when JARVIS finished, minus the VAD's lag only: the microphone stays open (D3), so his
    // own re-listen delay is not part of how quickly the owner (or the room) answered
    runaway.turn(S.handsFree === 'barge' ? 0 : Math.max(0, (clock ? clock.sinceReplyMs() : 0) - lagMs), Date.now());
  }

  async function listenCloud(t, cued) {
    try { await A.open(); } catch (e) {
      if (t === S.turn) { S.conv = false; setMode('idle'); if (!e || e.code !== 'closed') help(e && e.code); releaseMic(); }
      return;
    }
    if (t !== S.turn || !isListening()) { if (!isListening()) releaseMic(); return; } // a newer turn keeps it
    if (cued) { await Promise.race([cued, new Promise(r => setTimeout(r, CUE_MAX_MS))]); await new Promise(r => setTimeout(r, CUE_GAP_MS)); if (t !== S.turn || !isListening()) return; }
    A.flush();
    const d = V.device(), wait = S.handsFree === 'relisten';
    S.vad = window.JarvisVad.create({
      noSpeechMs: wait ? (d.longPauseS + 10) * 1000 : S.startMs, endSilenceMs: d.endSilenceMs, maxMs: MAX_LISTEN_MS, seed: S.seed,
      strictAfterMs: wait ? Math.max(0, d.followUpS * 1000 - RELISTEN_DELAY_MS) : 0,
    });
    startClocks(t);
    if (S.seed) markHeard(0);
    S.unsub = A.subscribe((frame) => {
      if (t !== S.turn || !S.vad) return;
      const ev = S.vad.push(frame);
      if (!ev) return;
      if (ev.type === 'start') { clearTimeout(S.noSpeech); markHeard(VAD_LAG_MS); if (liveEl) liveEl.textContent = 'Hearing you'; return; }
      if (ev.type === 'timeout') { nothingHeard(); return; }
      // 'spoke' is when the owner's words ENDED: now, less the silence that told the VAD so (the 'listening' timing)
      try { Pace().mark('spoke', performance.now() - d.endSilenceMs); } catch (_) {}
      transcribe(t, ev.frames);
    });
  }
  function endCapture() {
    if (S.unsub) { S.unsub(); S.unsub = null; }
    S.vad = null;
    releaseMic();
  }
  /** The cloud engine keeps the microphone open for the whole conversation (D3). */
  const holdMic = () => S.conv && !A.locked() && V.inputEngine() === 'cloud';
  /** Close the microphone unless "Hey Jarvis" or the conversation still needs it. */
  function releaseMic() { if (!wake.on && !S.unsub && !holdMic()) A.close(); }

  async function transcribe(t, frames) {
    endCapture();
    if (!frames || frames.length < MIN_FRAMES) { afterEmpty('I didn\'t catch that.'); return; }
    setMode('thinking');
    if (liveEl) liveEl.textContent = 'Transcribing';
    const ctrl = S.abort = new AbortController();
    let r;
    try {
      r = await Chat.raw('/v1/voice/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: window.JarvisWav.encode(frames), signal: ctrl.signal });
    } catch (e) {
      if (t === S.turn) { S.conv = false; setMode('idle'); releaseMic(); if (!e || (e.status !== 401 && e.name !== 'AbortError')) say('Couldn\'t reach JARVIS. Check your connection.'); }
      return;
    }
    if (t !== S.turn) return;
    if (!r.ok) { const f = await V.refused(r); if (t === S.turn) { setMode('idle'); transcribeFailed(f); } return; }
    let j = null;
    try { j = await r.json(); } catch (_) { j = null; }
    if (t !== S.turn) return;
    const text = j && typeof j.text === 'string' ? clean(j.text) : '';
    if (!text || (j && j.no_speech === true) || emptyWords(text) || echoed(text)) { afterEmpty('I didn\'t catch that.'); return; }
    deliver(text, { state: 'listening' });
  }
  const emptyWords = (text) => { const w = text.toLowerCase().replace(/[^a-z\s]/g, ' ').split(/\s+/).filter(Boolean); return !w.length || w.every(x => FILLER.has(x)); };
  /** An interruption's words that are mostly JARVIS's own coming back through the speakers are dropped (D7). */
  const echoed = (text) => !!(S.info && window.JarvisBarge.isEcho(text, S.info.said, S.info.peak, S.info.margin));
  /** Nothing usable was heard. After an interruption JARVIS carries on reading; in a conversation the
   *  loop keeps listening (the clock decides when to hand over); otherwise it ends quietly. */
  function afterEmpty(msg) {
    if (S.handsFree === 'barge') S.bargeOff = true;       // noise or echo set it off: no more energy interruptions this reply (SM3)
    if (resumeSpeech()) return;
    if (!S.soft && msg) say(msg);
    if (S.conv && !A.locked()) {
      if (++S.empties >= window.JarvisConversation.RUNAWAY.MAX_EMPTY) { handover('pause'); return; }  // SH1: noise is not a conversation
      setMode('idle'); resumeListening(true); return;
    }
    S.conv = false;
    setMode('idle');
    releaseMic();
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
        if (A.locked()) { say(LOCKED_LINE); return; }
        say(f.status === 402 ? 'Cloud listening has reached this month\'s limit. Say that again: this browser is listening.'
          : 'Cloud listening isn\'t available. Say that again: this browser is listening.');
        listen();
        return;
      }
      if (S.conv) { handover('cloud_down'); return; }
      say('Cloud listening isn\'t available right now. You can still type.');
      return;
    }
    say(f.detail || 'JARVIS couldn\'t hear that. Please try again.');
  }
  const clean = (s) => String(s).replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 4000);


  /** A transcript: the local command router first (D12), then send it (default) or leave it in the box. */
  async function deliver(text, o = {}) {
    if (o.state !== 'speaking' && !S.info && reverb(text, o.peak)) { afterEmpty('I didn\'t catch that.'); return; }   // his own words coming back (SM4)
    const t = S.turn;
    S.rest = null; S.info = null;
    if (S.mode !== 'thinking') setMode('thinking');
    const C = Cmd();
    if (C && !A.locked()) {
      let r = { handled: false };
      try { r = await C.handle(text, { source: 'voice', state: o.state || 'listening', spoken: saidText(), peak: o.peak || 0 }); } catch (_) { r = { handled: false }; }
      if (t !== S.turn) return;
      if (r.handled) { settle(r); return; }
    }
    if (A.locked()) { setMode('idle'); return; }
    if (S.checking) { putBack(text); handover('checkin'); return; }   // anything but "yes" answers the check-in: hand over (D6)
    S.empties = 0;                                      // a real turn: words are on their way
    const d = V.device();
    if (d.autoSend && !Chat.busy()) {
      cue('heard');
      Promise.resolve(Chat.send(text, { channel: 'voice' })).then(ok => { if (!ok && S.mode === 'thinking') endOrResume(); });
      return;
    }
    const before = input.value.replace(/\s+$/, '');
    input.value = before ? before + ' ' + text : text;
    input.dataset.channel = 'voice'; // console.js sends it as a spoken message when the owner presses Enter
    input.dispatchEvent(new Event('input', { bubbles: true }));
    S.conv = false; setMode('idle'); releaseMic();
    input.focus();
    say(Chat.busy() ? 'JARVIS is still answering: your words are in the message box.' : 'Check your words, then press Enter to send.');
  }
  const cancelAsk = () => { const C = Cmd(); if (C && typeof C.cancelAsk === 'function') C.cancelAsk(); };   // a stale question must not swallow a later yes / no (M2)
  /** A turn that began within 3 s of a reply ending, whose words are mostly that reply's: the room's reverb, not the owner. */
  function reverb(text, peak) {
    if (S.handsFree !== 'relisten' || S.turnAt - S.replyEndAt > ECHO_AFTER_MS) return false;   // a tap or "Hey Jarvis" is the owner, by choice
    const C = Cmd(), id = C && C.pending() ? C.owns(text, 'listening') : null;
    if (id && id.startsWith('answer.')) return false;                   // the answer to his own question echoes it by nature
    return window.JarvisBarge.isEcho(text, saidText(), peak || 0, window.JarvisBarge.margin());
  }
  /** The owner's words are never lost: what answered the check-in goes back into the message box (M3). */
  function putBack(text) {
    const before = input.value.replace(/\s+$/, '');
    input.value = before ? before + ' ' + text : text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  /** A command ran (from a turn or from a check clip). Say its line, then do what it asked for. */
  function settle(r) {
    const res = (r && r.result) || {};
    const answer = !!(r && typeof r.id === 'string' && r.id.startsWith('answer.'));
    const next = res.then || (answer ? 'none' : S.conv ? 'listen' : 'idle');
    const go = () => {
      if (next === 'listen') resumeListening();
      else if (next === 'keyboard') handover('keyboard');
      else if (next === 'none') { setMode('idle'); if (S.conv && !S.checking) setTimeout(() => { if (S.mode === 'idle' && !Chat.busy()) resumeListening(); }, 60); }
      else if (next !== 'off') { if (!S.conv) releaseMic(); setMode('idle'); }
    };
    // a device command's own line (the new output's name) is on screen already: the loop says it, it does not overwrite it
    const show = !(r && typeof r.id === 'string' && r.id.startsWith('device.'));
    if (typeof res.say === 'string' && res.say && next !== 'keyboard' && next !== 'off') { setMode('idle'); loopSay(res.say, { speak: true, show }).then(go); } else go();
  }
  /** Keep the conversation going: the waits start again from now. */
  function resumeListening(empty) {
    if (A.locked() || !S.conv) { setMode('idle'); return; }
    startClock(empty ? performance.now() - S.realAt : 0);   // after noise the waits still count from the last real turn (SH1)
    if (!empty && needsCheck()) { checkIn(); return; }
    listen({ relisten: true });
  }
  /** The check-in is due: the room keeps talking (D6, when the owner left it on) or the absolute bound is reached (SH1). */
  function needsCheck() {
    const now = Date.now();
    return !S.checking && ((V.device().checkIn && runaway.due(now)) || runaway.capped(now));
  }

  /** Tap again while listening (or 55 s are up): stop now and send what was heard. */
  function stopAndSend() {
    if (S.rec) { S.stop = true; try { S.rec.stop(); } catch (_) {} return; }
    const frames = S.vad ? S.vad.frames() : [];
    if (!frames.length) { cancel(); if (!S.soft) say('I didn\'t hear anything.'); return; }
    transcribe(S.turn, frames);
  }
  /** Esc while listening: nothing is sent, and the conversation is over. */
  function cancel() {
    S.turn++;
    S.conv = false; stopClock(); cancelAsk();
    if (S.rec) { S.cancel = true; const r = S.rec; S.rec = null; try { r.abort(); } catch (_) {} browserEngine.restore(); }
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
    S.keep = false; S.conv = false; stopClock();
    setMode('idle');
    releaseMic();
  }
  function stopAll() {
    clearTimeout(S.relisten); clearTimeout(S.browserTimer); cancelAsk();
    try { window.JarvisBarge.forget(); } catch (_) {}
    S.keep = false; S.rest = null; S.handing = false; S.checking = false;
    if (isListening()) cancel(); else { S.turn++; S.conv = false; stopClock(); } // a transcription still on its way is dropped
    silence();
    if (S.mode !== 'idle') setMode('idle');
    releaseMic();
  }
  function press(e) {
    if (btn.hidden) return;
    // a tap on the locked mic switches it on and listens; only a real, trusted tap or key counts (SM1)
    if (A.locked() && !((e && e.isTrusted) && A.unlock('button'))) { say(LOCKED_LINE); return; }
    S.chain = 0; S.empties = 0; runaway.touch();                           // the owner is here
    if (S.mode === 'off') setMode('idle');
    if (isListening()) { stopAndSend(); return; }
    if (S.mode === 'speaking' || S.mode === 'handover') {
      S.keep = false; S.rest = null; S.handing = false; silence();
      emit('jarvis:barge', { how: 'tap', ms: 0 });
      listen(); return;
    }                                                                      // barge-in + listen
    if (S.mode === 'thinking') { say('JARVIS is still answering.'); return; }
    listen();
  }

  // ---- the conversation clock (D4) --------------------------------------------------------------------
  function startClock(elapsedMs) {
    const d = V.device();
    stopClock();
    if (!elapsedMs) S.realAt = performance.now();
    clock = window.JarvisConversation.create({
      followUpMs: d.followUpS * 1000, longPauseMs: d.longPauseS * 1000,
      onStandby: () => { if (S.mode === 'listening' && S.conv && !(S.vad && S.vad.started()) && !S.recText) setMode('standby'); },
      onLongPause: () => { if (S.conv && !S.checking && (isListening() || S.mode === 'idle')) handover('pause'); },
    });
    clock.replyEnded(elapsedMs || 0);
  }
  function stopClock() { if (clock) { clock.stop(); clock = null; } }
  // ---- speaking -------------------------------------------------------------------------------
  const APPROVAL_LINE = () => `That one needs your approval on screen, ${honorific()}.`;
  function speak(chunks, keep, mode, meta) {
    const out = V.outputEngine();
    if (out === 'none' || !chunks.length) { if (S.mode === 'thinking') endOrResume(); return; }
    V.speaker.browser(out !== 'cloud');
    V.speaker.setRate(V.settings().rate);
    S.keep = keep;
    setMode(mode || 'speaking');
    chunks.forEach(c => V.speaker.say(c, meta));
    V.speaker.end();
  }
  /** A turn ended with nothing to say (or nothing that can be said): keep listening with the clock restarted,
   *  or, outside a conversation, close the microphone. Never leave it hot with no clock (H1). */
  function endOrResume() {
    if (S.conv && !A.locked()) { setMode('idle'); resumeListening(); return; }
    S.conv = false; setMode('idle'); releaseMic();
  }
  /** Stop JARVIS now (the state handler stays out of it); returns {rest}. */
  function silence() {
    S.silent = true;
    try { return V.speaker.stop(); } finally { S.silent = false; }
  }
  document.addEventListener('jarvis:answer', (e) => {
    const d = e.detail || {}, dev = V.device();
    const spoken = d.channel === 'voice';
    if (S.mode === 'handover') return;   // the owner is being handed to the keyboard: the reply is on screen, not said (M1)
    S.bargeOff = false; S.resumed = false;   // a new reply: the interruption budget starts again
    if (S.mute) { S.mute = false; if (S.mode === 'thinking') setMode('idle'); return; } // Esc'd: shown, not said
    if (isListening()) return; // the owner is already talking again
    if (dev.speak === 'never' || (dev.speak === 'voice' && !spoken) || typeof d.text !== 'string') {
      if (S.mode === 'thinking') endOrResume();
      return;
    }
    if (spoken && d.approvals > 0) { S.conv = false; S.closeAfter = true; speak([APPROVAL_LINE()], false); return; } // D11: fixed, wit-free; it ends the conversation
    const c = window.JarvisSpeechChunker.create({ honorific: honorific() });
    speak(c.push(d.text).concat(c.end()), spoken && dev.keepListening && S.conv);
  });
  V.speaker.on('chunk', (d) => { S.said.push({ text: String(d && d.text || ''), at: performance.now() }); if (S.said.length > 12) S.said.shift(); });
  /** What JARVIS said in the last few seconds, plus the chunk being spoken (for the echo guard). */
  function saidText() {
    const now = performance.now();
    const cur = S.said.length && V.speaker.speaking() ? [S.said[S.said.length - 1]] : [];
    return S.said.filter(x => now - x.at <= SAID_MS).concat(cur).map(x => x.text).join(' ');
  }
  V.speaker.on('state', (d) => {
    syncWake(); // a Preview in the Voice panel speaks too: the wake word must not hear it
    if (!d.speaking) { S.replyEndAt = performance.now(); S.spoken.splice(0).forEach(r => r()); }
    if (d.speaking || S.silent) return;
    if (S.mode === 'handover') { finishHandover(); return; }
    if (S.mode !== 'speaking') return;
    const wanted = d.reason === 'done' && S.keep;
    S.keep = false;
    setMode('idle');
    if (S.closeAfter) { S.closeAfter = false; if (!S.conv) releaseMic(); }
    if (!wanted || !S.conv || A.locked()) return;
    S.chain++;
    startClock();
    const dev = V.device();
    S.relisten = setTimeout(() => {
      if (S.mode !== 'idle' || Chat.busy() || A.locked()) return;
      if (needsCheck()) { checkIn(); return; }
      listen({ relisten: true });
    }, RELISTEN_DELAY_MS);
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

  bindCommands();

  // ---- the console's own turns ------------------------------------------------------------------
  document.addEventListener('jarvis:turn', (e) => {
    const d = e.detail || {}, dev = V.device();
    // inside the owner's Enter / tap: let the reply's audio start later (only if it will be spoken)
    if (d.channel === 'voice' ? dev.speak !== 'never' : dev.speak === 'always') V.speaker.unlock();
    if (d.channel === 'voice') { clearTimeout(S.relisten); S.mute = false; clock && clock.heard(); if (S.mode !== 'thinking') setMode('thinking'); return; }
    S.chain = 0;
    stopAll(); // a typed message is a barge-in too
  });
  document.addEventListener('jarvis:turn-end', (e) => {
    const d = e.detail || {};
    S.mute = false;
    if (!d.ok && S.mode === 'thinking') { setMode('idle'); if (S.conv && !A.locked()) resumeListening(); }
  });
  document.addEventListener('jarvis:switch', stopAll); // new or another conversation: silence

  // ---- the microphone stopped by itself (unplugged, switched off) ---------------------------------
  A.onEnd(() => {
    if (wake.on) wake.fail(wake.UNPLUGGED);
    if (S.conv) { if (isListening() && !S.rec) help('ended'); handover('mic_ended'); return; }
    if (isListening() && !S.rec) { cancel(); help('ended'); }
  });

  // ---- the hard microphone lock (R5 D11) ------------------------------------------------------------
  A.onLock(({ locked, by }) => {
    if (!locked) {
      if (S.mode === 'off') setMode('idle');
      if (by === 'storage') { wakeAfterGesture(); return; }   // another tab switched it on: ready, but only a gesture here opens it (SM1)
      bootWake(); return;
    }
    clearTimeout(S.relisten); clearTimeout(S.browserTimer);
    S.keep = false; S.rest = null; S.checking = false; S.handing = false;  // no re-listen after a reply that is still playing
    if (isListening()) cancel();                        // nothing is sent
    else if (S.mode === 'thinking' && !Chat.busy()) S.turn++; // a transcription on its way is dropped
    S.conv = false; stopClock();
    if (S.abort) { try { S.abort.abort(); } catch (_) {} S.abort = null; }
    if (wake.on) { wakeHalt(); wakeState('micoff'); } else if (V.device().wake) wakeState('micoff');
    cue('micoff');
    if (S.mode === 'idle' || (S.mode === 'thinking' && !Chat.busy())) setMode('off');
  });

  /** An unlock that came from another tab never starts "Hey Jarvis" by itself: the next real tap or key here does. */
  function wakeAfterGesture() {
    if (S.wakeGate) return;
    S.wakeGate = true;
    const go = (e) => {
      if (!e.isTrusted) return;
      S.wakeGate = false;
      document.removeEventListener('pointerdown', go, true); document.removeEventListener('keydown', go, true);
      if (!A.locked()) bootWake();
    };
    document.addEventListener('pointerdown', go, true); document.addEventListener('keydown', go, true);
  }

  // ---- keys and the button ------------------------------------------------------------------------
  btn.addEventListener('click', press);
  const here = (e) => { if (e && e.isTrusted) runaway.touch(); };                   // a tap or a key: the owner is here (D6)
  document.addEventListener('pointerdown', here, true);
  document.addEventListener('keydown', (e) => {
    here(e);
    if (e.isComposing || btn.hidden) return;
    if (e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey && (e.code === 'Space' || e.key === ' ')) { e.preventDefault(); press(e); return; }
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    let said = '';
    if (isListening()) { cancel(); said = 'Cancelled'; }
    else if (S.mode === 'speaking' || S.mode === 'handover') { stopAll(); said = 'Stopped'; }
    else if (S.mode === 'thinking') { abandon(); said = 'Cancelled'; }
    if (!said) return;
    e.preventDefault(); e.stopPropagation();
    if (liveEl) liveEl.textContent = said;
  }, true);
  input.addEventListener('input', () => { if (!input.value.trim()) delete input.dataset.channel; });

  // ---- "Hey Jarvis" (D12, D8) lives in console-voice-wake.js ----------------------------------------
  const wake = window.JarvisWakeCtl.create({ A, V, Chat, emit, log, help, HELP, signedIn, speakWake,
    busy: () => S.mode !== 'idle' || V.speaker.speaking(),
    listen: (o) => listen(o),
    barge: () => bargeWake(),
    nameOff: () => { S.nameOff = true; say('Interrupting by name stopped working on this page. Tapping still works.'); },
    micInUse: () => isListening() || !!S.unsub || holdMic() });
  const syncWake = () => wake.sync(), wakeHalt = () => wake.halt(), wakeState = (s, n) => wake.state(s, n);
  const wakeStop = () => wake.stop(), bootWake = () => wake.boot();

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
  // saved. (A hidden tab keeps listening on purpose on a computer; on a phone the page being hidden
  // ends the conversation with the spoken line, D5.)
  window.addEventListener('pagehide', () => { stopAll(); if (wake.on) wakeStop(); A.close(); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) bootWake(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && S.conv && /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent || '')) handover('hidden');
  });

  // ---- window.JarvisVoiceLoop: the seam other modules use ---------------------------------------------
  const offers = window.JarvisConversation.offers($('voiceOffer'), OFFER_MS);
  function inConversation() { return S.conv && S.mode !== 'off'; }
  /** Show a line and, with {speak: true}, say it out loud (not over a turn in progress). Resolves when said. */
  function loopSay(text, o) {   // o.fixed: a fixed line (cached audio)
    if (typeof text !== 'string' || !text.trim()) return Promise.resolve();
    const t = text.trim().slice(0, 300);
    if (!(o && o.show === false)) say(t);
    if (!(o && o.speak === true) || V.device().speak === 'never' || V.outputEngine() === 'none') return Promise.resolve();
    if (S.mode !== 'idle' && S.mode !== 'off') return Promise.resolve();
    return new Promise(resolve => { S.spoken.push(resolve); speak([t], false, 'speaking', (o && o.fixed) ? FIXED : undefined); });
  }
  /** Ask a yes / no question: said aloud, then the router waits for the answer ('yes' | 'no' | 'timeout' | 'cancelled'). */
  function loopAsk(question, o) {
    const C = Cmd();
    loopSay(question, { speak: true });
    return C ? C.ask(question, o) : Promise.resolve('timeout');
  }
  const loopOffer = offers.offer;
  /** End the voice conversation: stop listening and speaking; the keyboard gets the focus. */
  function loopEnd(reason) {
    offers.clear();
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
