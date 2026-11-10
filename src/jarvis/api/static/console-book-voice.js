// src/jarvis/api/static/console-book-voice.js -- R6 D15 (book.html): narration -- POST /v1/book/show/speak, one beat
// prefetched, a Web Audio queue, the browser voice on 402/503/a decode error, level() for the Core.
// say(lineId, text) resolves when the line's audio ends: the cloud voice (the server speaks ITS text for that line id,
// a beat id, a fixed line's key or a reply id; decoded by Web Audio, so no media element and no CSP change), else the
// browser's speechSynthesis (from the first 402 / 503 / decode error on, for the rest of the show), else -- sound off,
// or no voice at all -- captions only: 330 ms a word + 800 ms. Pause, resume and stop work in every mode, also while a
// line's audio is still being fetched: it then waits, paused, and starts on resume (never late, never by itself).
// record: a spoken question (<= 15 s, 16 kHz PCM16 WAV) through the console's capture worklet, for POST /v1/book/show/hear.
// The microphone opens only from a tap; a cancel or the close while it is still starting (the permission prompt, the
// worklet) wins: the stream is stopped and nothing is recorded. Nothing is stored; dispose() stops and closes
// everything (the page calls it at the close, D14).
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
// window.JarvisBookVoice = {start(voice), say, prefetch, pause, resume, stop, mute, level, state, dispose, record}
(() => {
  'use strict';
  const ID = /^(s\d{2}b\d{2}|[a-z_]{2,20}|r_[0-9a-f]{12})$/;
  const WORD_MS = 330, TAIL_MS = 800, START_MS = 1500, CACHE = 3, MAX_REC_S = 15, RATE = 16000;
  const S = { ctx: null, gain: null, an: null, data: null, mode: 'cloud', muted: false, closed: false, seq: 0, cur: null,
    cache: new Map(), pulse: 0, lv: 0, paused: false };
  const captionMs = (text) => (String(text || '').split(/\s+/).filter(Boolean).length * WORD_MS) + TAIL_MS;
  const B = () => window.JarvisBook;
  const synth = () => { try { return window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function' ? window.speechSynthesis : null; } catch (_) { return null; } };

  /** Called from the Begin click (a user gesture), so the AudioContext may start. */
  function start(voice) {
    S.mode = voice === 'browser' ? 'browser' : 'cloud';
    if (S.ctx || S.closed) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) { if (S.mode === 'cloud') S.mode = 'browser'; return; }
      S.ctx = new AC(); S.an = S.ctx.createAnalyser(); S.an.fftSize = 512; S.data = new Uint8Array(S.an.fftSize);
      S.an.connect(S.ctx.destination);
      if (S.ctx.state === 'suspended') S.ctx.resume().catch(() => {});
    } catch (_) { S.ctx = null; if (S.mode === 'cloud') S.mode = 'browser'; }
  }

  // ---- the cloud voice ---------------------------------------------------------------------------
  async function fetchLine(id) {
    const r = await B().raw('/v1/book/show/speak', { method: 'POST', body: { line_id: id } });
    if (!r.ok) { const e = await B().failure(r); throw e; }
    const bytes = await r.arrayBuffer();
    return S.ctx.decodeAudioData(bytes);
  }
  function load(id) {
    if (S.cache.has(id)) return S.cache.get(id);
    const p = fetchLine(id);
    p.catch(() => {});
    S.cache.set(id, p);
    while (S.cache.size > CACHE) S.cache.delete(S.cache.keys().next().value);
    return p;
  }
  /** One beat ahead: its audio is fetched and decoded while the current line plays. */
  function prefetch(id) {
    if (S.closed || S.muted || S.mode !== 'cloud' || !S.ctx || !ID.test(id || '')) return;
    load(id);
  }
  function playBuffer(buf, my) {
    return new Promise((resolve) => {
      if (my !== S.seq || S.closed) { resolve('stopped'); return; }
      const src = S.ctx.createBufferSource();
      src.buffer = buf; src.connect(S.an);
      const cur = { kind: 'audio', src, resolve, at: performance.now(), ms: buf.duration * 1000 };
      src.onended = () => end(cur, 'ended');
      S.cur = cur;
      if (held(cur)) return; // paused while it was fetched: it starts on resume
      if (S.ctx.state === 'suspended') S.ctx.resume().catch(() => {}); // a pause, then a jump: the new line plays
      src.start();
    });
  }
  /** Pause came while the line was still on its way: it waits, paused, for resume() to start it. */
  function held(cur) {
    if (!S.paused) return false;
    cur.paused = true; cur.waiting = true;
    return true;
  }

  // ---- the browser voice -------------------------------------------------------------------------
  function speakBrowser(text, my) {
    const sp = synth();
    return new Promise((resolve) => {
      if (!sp || my !== S.seq) { resolve('stopped'); return; }
      const u = new SpeechSynthesisUtterance(text), cur = { kind: 'speech', u, resolve, text, at: performance.now(), started: false };
      u.lang = 'en-GB'; u.rate = 1;
      u.onstart = () => { cur.started = true; };
      u.onboundary = () => { S.pulse = 1; };
      u.onend = () => end(cur, 'ended');
      u.onerror = () => failed(cur);
      S.cur = cur;
      if (!held(cur)) utter(cur, sp);
    });
  }
  /** A voice that fails before it starts (none installed, as headless Chromium): the captions set the
   *  pace from here on, never an instant end (the show would race to Questions). Once a timer, a late
   *  error (our own cancel) changes nothing. */
  function failed(cur) {
    if (cur.kind !== 'speech') return;
    if (cur.started || S.cur !== cur) { end(cur, 'ended'); return; }
    S.mode = 'captions'; toTimer(cur, captionMs(cur.text));
  }
  function utter(cur, sp) {
    const text = cur.text;
    cur.at = performance.now();
    // no voice in this browser (it never starts): captions set the pace from here on
    cur.watch = setTimeout(() => { if (!cur.started && S.cur === cur) { S.mode = 'captions'; try { sp.cancel(); } catch (_) {} toTimer(cur, captionMs(text)); } }, START_MS);
    cur.cap = setTimeout(() => end(cur, 'ended'), captionMs(text) * 2 + 4000);
    try { sp.resume(); sp.speak(cur.u); } catch (_) { toTimer(cur, captionMs(text)); }
  }

  // ---- captions only: a pausable timer -------------------------------------------------------------
  function timed(ms, my) {
    return new Promise((resolve) => {
      if (my !== S.seq) { resolve('stopped'); return; }
      const cur = { kind: 'timer', resolve, left: ms, at: performance.now() };
      S.cur = cur;
      if (S.paused) { cur.paused = true; return; } // resume() starts its timer
      cur.timer = setTimeout(() => end(cur, 'ended'), ms);
    });
  }
  /** The current line goes on as a timer for its remaining caption time (sound switched off mid-line). */
  function toTimer(cur, ms) {
    clearTimeout(cur.watch); clearTimeout(cur.cap);
    cur.kind = 'timer'; cur.left = Math.max(300, ms); cur.at = performance.now(); cur.waiting = false;
    if (!cur.paused) cur.timer = setTimeout(() => end(cur, 'ended'), cur.left); // paused: resume() starts it
  }
  function end(cur, how) {
    if (cur.done) return;
    cur.done = true; clearTimeout(cur.timer); clearTimeout(cur.watch); clearTimeout(cur.cap);
    if (S.cur === cur) S.cur = null;
    cur.resolve(how);
  }

  async function say(id, text) {
    stop();
    const my = ++S.seq;
    S.paused = false; // a new line is meant to be heard; a Pause while its audio loads holds it (held())
    if (S.closed || !text) return 'stopped';
    if (!S.muted && S.mode === 'cloud' && S.ctx && ID.test(id || '')) {
      try {
        const buf = await load(id);
        S.cache.delete(id);
        if (my !== S.seq) return 'stopped';
        return await playBuffer(buf, my);
      } catch (_) {
        S.cache.delete(id);
        if (my !== S.seq) return 'stopped';
        S.mode = 'browser'; // 402 (allowance), 503 (no cloud voice), a decode error: the browser voice from here on
      }
    }
    if (!S.muted && S.mode === 'browser' && synth()) return speakBrowser(text, my);
    return timed(captionMs(text), my);
  }
  function stop() {
    S.seq += 1;
    const cur = S.cur;
    if (!cur) return;
    if (cur.kind === 'audio') { try { cur.src.onended = null; cur.src.stop(); } catch (_) {} }
    if (cur.kind === 'speech') { const sp = synth(); try { if (sp) sp.cancel(); } catch (_) {} }
    end(cur, 'stopped');
  }
  function pause() {
    S.paused = true; // also holds a line whose audio is still being fetched
    const cur = S.cur;
    if (!cur || cur.paused) return;
    cur.paused = true;
    if (cur.kind === 'audio' && S.ctx) S.ctx.suspend().catch(() => {});
    else if (cur.kind === 'speech') { const sp = synth(); try { if (sp) sp.pause(); } catch (_) {} clearTimeout(cur.cap); }
    else { clearTimeout(cur.timer); cur.left = Math.max(0, cur.left - (performance.now() - cur.at)); }
  }
  function resume() {
    S.paused = false;
    if (S.ctx && S.ctx.state === 'suspended' && !S.closed) S.ctx.resume().catch(() => {});
    const cur = S.cur;
    if (!cur || !cur.paused) return;
    cur.paused = false;
    if (cur.waiting) { cur.waiting = false; if (cur.kind === 'audio') { cur.at = performance.now(); cur.src.start(); } else utter(cur, synth()); return; }
    if (cur.kind === 'speech') { const sp = synth(); try { if (sp) sp.resume(); } catch (_) {} cur.cap = setTimeout(() => end(cur, 'ended'), captionMs(cur.text) + 4000); }
    else if (cur.kind === 'timer') { cur.at = performance.now(); cur.timer = setTimeout(() => end(cur, 'ended'), cur.left); }
  }
  /** M: sound off -> the line playing now ends on its caption time; sound on -> the next line speaks. */
  function mute(on) {
    S.muted = !!on;
    const cur = S.cur;
    if (!S.muted || !cur || cur.kind === 'timer') return;
    const spent = performance.now() - cur.at;
    if (cur.kind === 'audio') { try { cur.src.onended = null; cur.src.stop(); } catch (_) {} toTimer(cur, Math.max(cur.ms || 0, 1200) - spent); }
    else { const sp = synth(); try { if (sp) sp.cancel(); } catch (_) {} toTimer(cur, captionMs(cur.text) - spent); }
  }
  /** 0..1, smoothed: the playback level (cloud), a pulse per spoken word (browser), else 0. */
  function level() {
    let v = 0;
    const cur = S.cur;
    if (cur && !cur.paused && cur.kind === 'audio' && S.an) {
      S.an.getByteTimeDomainData(S.data);
      let sum = 0;
      for (let i = 0; i < S.data.length; i += 1) { const x = (S.data[i] - 128) / 128; sum += x * x; }
      v = Math.min(1, Math.sqrt(sum / S.data.length) * 4);
    } else if (cur && !cur.paused && cur.kind === 'speech') { S.pulse *= 0.9; v = 0.35 + 0.45 * S.pulse; }
    S.lv += (v - S.lv) * 0.35;
    return S.lv;
  }
  function state() { return S.closed ? 'closed' : S.ctx ? S.ctx.state : 'none'; }
  function dispose() {
    if (S.closed) return;
    stop(); rec.cancel();
    S.closed = true; S.cache.clear();
    const sp = synth(); try { if (sp) sp.cancel(); } catch (_) {}
    if (S.ctx) { try { S.ctx.close(); } catch (_) {} }
    S.an = null; S.data = null;
  }

  // ---- a spoken question: the console's one capture pipeline (console-voice-capture.js, R5: the only module that opens
  // the microphone, so the owner's microphone lock holds here too), 16 kHz frames, a WAV for show/hear ------------------
  const rec = (() => {
    let live = null, starting = false, gen = 0; // gen: bumped by cancel() and dispose(); a start that sees it move gives up
    const A = () => window.JarvisAudio || null;
    const supported = () => { const a = A(); return !!(a && a.supported() && window.JarvisWav); };
    /** true: recording now. false: not started (already busy, closed, or cancelled while it was starting). */
    async function begin() {
      const a = A();
      if (!a || live || starting || S.closed) return false;
      const my = gen, stale = () => my !== gen || S.closed;
      starting = true;
      try {
        try { await a.open(); } catch (e) { if (stale()) return false; throw e; } // .code 'mic_off': the lock is on
        if (stale()) { a.close(); return false; }
        const frames = [];
        const off = a.subscribe((f) => { if (frames.length * f.length < MAX_REC_S * RATE) frames.push(new Int16Array(f)); });
        live = { frames, off };
        live.timer = setTimeout(() => { if (live && live.onfull) live.onfull(); }, MAX_REC_S * 1000);
        return true;
      } finally {
        starting = false;
      }
    }
    function release() {
      const l = live; live = null;
      if (!l) return null;
      clearTimeout(l.timer); l.off();
      const a = A(); if (a) a.close();
      return l.frames;
    }
    return {
      supported,
      start: begin,
      onFull(fn) { if (live) live.onfull = fn; },
      stop() { const f = release(); return f && f.length ? window.JarvisWav.encode(f, RATE) : null; },
      cancel() { gen += 1; const was = starting; release(); const a = A(); if (was && a) a.close(); }, // a pending open stops its tracks
      active: () => !!live,
    };
  })();

  window.JarvisBookVoice = Object.freeze({ start, say, prefetch, pause, resume, stop, mute, level, state, dispose, record: rec });
})();
