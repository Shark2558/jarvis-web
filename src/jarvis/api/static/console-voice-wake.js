// src/jarvis/api/static/console-voice-wake.js - the "Hey Jarvis" controller (slice 9 D12, R5 D8).
// Moved out of console-voice-mic.js with no behaviour change (docs/plans/r5-voice.md workstream A).
// window.JarvisWakeCtl.create(host) -> controller. `host` is what the listening loop lends it:
//   {A, V, Chat, emit, log, help(code), HELP, signedIn(), busy(), listen(opts), micInUse()}
// "Hey Jarvis" (D12): window.JarvisWake (console-wakeword.js) gets the same 16 kHz frames; it is
// paused (JarvisWake.pause()) while JARVIS listens, thinks or speaks, and resumed ~0.4 s after the
// last clip ends. Its state is checked every second: an error switches it off with a plain line.
// Fires jarvis:wake {state, note}. No build step; CSP script-src 'self'.
(() => {
  'use strict';
  const WAKE_RESUME_MS = 400;      // after the last clip: its echo in the room, the speakers' delay
  const WAKE_POLL_MS = 1000;       // a running wake-word module is checked this often for an error
  const WAKE_LATE_MS = 10000;      // a saved "Hey Jarvis" waits this long for its module to arrive
  const SPEAK_THRESHOLD = 0.6;     // a stricter score while JARVIS speaks: his own voice must not wake him
  const IDLE_THRESHOLD = 0.5;
  const WAKE_FAILED = '‘Hey Jarvis’ stopped working on this device, so it was switched off. You can switch it on again here.';
  const WAKE_UNPLUGGED = 'The microphone stopped, so ‘Hey Jarvis’ was switched off. You can switch it on again here.';

  function create(host) {
    const { A, V, Chat, emit, log } = host;
    // wake.held: the module is paused (and frames are not passed on) while JARVIS listens, thinks or
    // speaks; it resumes WAKE_RESUME_MS after all of that is over.
    const wake = { only: false, on: false, started: false, handle: null, subs: new Set(), armed: false, seq: 0, held: false,
      resumeTimer: 0, poll: 0, waiting: 0 };
    const wakeApi = () => window.JarvisWake || null;
    const wakeSupported = () => { const W = wakeApi(); try { return !!(W && typeof W.supported === 'function' && W.supported()); } catch (_) { return false; } };
    function wakeState(state, note) { if (!wake.only) emit('jarvis:wake', { state, note: note || '' }); }
    const speakWake = () => typeof host.speakWake === 'function' && !!host.speakWake();
    function setThreshold(v) { const W = wakeApi(); try { if (W && 'threshold' in W) W.threshold = v; } catch (_) {} }
    function hold(on) {
      if (on) { clearTimeout(wake.resumeTimer); wake.resumeTimer = 0; }
      if (wake.held === on) return;
      wake.held = on;
      const W = wakeApi();
      try {
        if (on && W && typeof W.pause === 'function') W.pause();
        else if (!on && W && typeof W.resume === 'function') W.resume(); // fresh buffers: the gap breaks the stream
      } catch (_) {}
    }
    function sync() {
      if (!wake.on || !wake.started) return;
      if (A.suspended()) { hold(true); wakeState('resume'); armResume(); return; }
      if (speakWake()) { setThreshold(SPEAK_THRESHOLD); hold(false); wakeState('on'); return; }  // D8: running while he speaks
      setThreshold(IDLE_THRESHOLD);
      if (host.busy()) { hold(true); wakeState('paused'); return; }
      if (!wake.held) { wakeState('on'); return; }
      if (wake.resumeTimer) return;
      wake.resumeTimer = setTimeout(() => {
        wake.resumeTimer = 0;
        if (!wake.on || host.busy() || A.suspended()) return;
        hold(false);
        wakeState('on');
      }, WAKE_RESUME_MS);
    }
    function gated(fn) {
      if (typeof fn !== 'function') return () => {};
      const un = A.subscribe((frame) => { if (wake.on && !wake.held) fn(frame); });
      const off = () => { un(); wake.subs.delete(off); };
      wake.subs.add(off);
      return off;
    }
    async function start() {
      if (A.locked()) { wakeState('micoff'); return; }
      const W = wakeApi(), my = ++wake.seq;
      if (!wakeSupported()) { wakeState('off'); return; }
      wake.on = true; wake.started = false; wake.held = false;
      wakeState('loading');
      try {
        const opened = A.open();               // inside the switch's click when the owner turns it on
        opened.catch(() => {});                // awaited below, after the model loads
        if (typeof W.load === 'function') await W.load();
        await opened;
        if (my !== wake.seq || !wake.on) return;
        wake.handle = await W.start({ subscribe: gated, sampleRate: A.SAMPLE_RATE }, onWake);
        if (my !== wake.seq) return;
        wake.started = true;
        watch(my);
        sync();
        log('info', 'Listening for "Hey Jarvis"');
      } catch (e) {
        if (my !== wake.seq) return;
        if (wake.only) { fail(''); return; }
        if (e && e.code && host.HELP[e.code]) host.help(e.code);
        fail(e && e.code === 'blocked' ? 'The microphone is blocked, so ‘Hey Jarvis’ can\'t listen.' : 'Couldn\'t start ‘Hey Jarvis’ in this browser.');
      }
    }
    /** Stop the module, unhook its frames and close the microphone if nothing else uses it. */
    function halt() {
      wake.seq++;
      const W = wakeApi(), h = wake.handle;
      wake.on = false; wake.started = false; wake.handle = null; wake.held = false;
      clearTimeout(wake.resumeTimer); wake.resumeTimer = 0;
      clearInterval(wake.poll); wake.poll = 0;
      try { if (h && typeof h.stop === 'function') h.stop(); else if (W && typeof W.stop === 'function') W.stop(); } catch (_) {}
      Array.from(wake.subs).forEach(off => off());
      if (!host.micInUse()) A.close();
    }
    function stop() { halt(); wakeState('off'); }
    /** An error: off, with a plain line (console-voice.js switches this device's setting off). */
    function fail(note) {
      if (wake.only) { wake.only = false; halt(); if (typeof host.nameOff === 'function') host.nameOff(); return; } // D8: never flips the owner's setting
      halt(); wakeState('error', note);
    }
    /** D8: with "Hey Jarvis" off the model runs only while JARVIS speaks (when the policy needs it). */
    function speaking(on) {
      if (on && !wake.on && speakWake() && wakeSupported() && A.isOpen()) { wake.only = true; start(); }
      else if (!on && wake.only) { wake.only = false; halt(); }
    }
    /** The module reports trouble only through JarvisWake.state ('error': too slow, inference failed). */
    function watch(my) {
      clearInterval(wake.poll);
      wake.poll = setInterval(() => {
        if (my !== wake.seq || !wake.on) { clearInterval(wake.poll); wake.poll = 0; return; }
        let st = null;
        try { const W = wakeApi(); st = W ? W.state : null; } catch (_) { st = null; }
        if (st === 'error') fail(WAKE_FAILED);
      }, WAKE_POLL_MS);
    }
    function onWake() {
      if (!wake.on) return;
      if (host.busy()) { if (speakWake() && typeof host.barge === 'function') host.barge(); return; }
      if (Chat.busy()) return;
      log('info', '"Hey Jarvis" heard');
      host.listen({ soft: true });
    }
    /** After a reload the audio context may wait for a gesture: the first tap anywhere resumes it. */
    function armResume() {
      if (wake.armed) return;
      wake.armed = true;
      const go = () => {
        wake.armed = false;
        document.removeEventListener('pointerdown', go, true); document.removeEventListener('keydown', go, true);
        Promise.resolve(A.resume()).then(sync, sync);
      };
      document.addEventListener('pointerdown', go, true); document.addEventListener('keydown', go, true);
    }
    document.addEventListener('jarvis:voice-device', (e) => {
      const d = e.detail || {};
      if (d.wake && wake.only) { wake.only = false; wakeState('on'); }   // switched on while it ran only for his speech: it stays on after (D8)
      else if (d.wake && !wake.on) start();
      else if (!d.wake && wake.on) stop();
    });
    /** Start a saved "Hey Jarvis" once signed in. Its module normally loads before this script; if it
     *  arrives later (a slow or late <script>), it is waited for, briefly. */
    function boot() {
      if (!host.signedIn() || !V.device().wake || wake.on) return;
      if (A.locked()) { wakeState('micoff'); return; }
      if (wakeApi()) { start(); return; }
      if (wake.waiting) return;
      const until = Date.now() + WAKE_LATE_MS;
      wake.waiting = setInterval(() => {
        if (!wakeApi() && Date.now() < until) return;
        clearInterval(wake.waiting); wake.waiting = 0;
        if (wakeApi()) boot();
      }, 250);
    }
    return { get on() { return wake.on; }, sync, start, halt, stop, fail, boot, speaking, state: wakeState, UNPLUGGED: WAKE_UNPLUGGED };
  }
  window.JarvisWakeCtl = Object.freeze({ create });
})();
