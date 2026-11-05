// src/jarvis/api/static/console-notes-memo.js -- voice memos for the Notes panel (R2 D10).
// A memo is a TRANSCRIPT, never audio: the microphone (window.JarvisAudio) is cut into pieces of
// at most 55 s, each sent to the existing POST /v1/voice/transcribe as a WAV (window.JarvisWav);
// the words appear in an editable box and only Save stores them (as kind "memo", which the server
// records as reviewed by the owner). Audio exists only in this page's memory and is dropped as soon
// as it has been sent. At most 5 minutes per memo. When Google's cloud voice is off (402 / 503) the
// browser's own speech recognition is used instead, if it has one.
// Needs console-notes.js (window.JarvisNotes) and console-voice-capture.js; adds its Record button to
// #notesActions after each render of the panel.
(() => {
  'use strict';
  const FRAMES_PER_PIECE = Math.floor(55000 / 80);   // 55 s of 80 ms frames
  const MAX_FRAMES = Math.floor(5 * 60 * 1000 / 80); // 5 minutes
  const MIN_FRAMES = 4;
  const TEXT_MAX = 4000;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const Notes = () => window.JarvisNotes;
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  const S = { mode: 'idle', text: '', error: '', unsub: null, frames: [], total: 0, pieces: 0, chain: Promise.resolve(), cloud: true, rec: null, busy: false, sid: 0, pending: 0 };
  let box = null;

  const say = (kind, text) => { const n = Notes(); if (n) n.flash(kind, text); };
  function fail(text) { S.error = text; draw(); }

  // ---- transcribing one piece --------------------------------------------------------------------
  async function sendPiece(frames) {
    if (frames.length < MIN_FRAMES) return '';
    const raw = window.JarvisChat && window.JarvisChat.raw;
    if (!raw) throw Object.assign(new Error('no transport'), { cloud: false });
    const r = await raw('/v1/voice/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: window.JarvisWav.encode(frames) });
    if (r.status === 402 || r.status === 503) throw Object.assign(new Error('cloud off'), { cloud: false });
    if (!r.ok) throw Object.assign(new Error('refused'), { cloud: true });
    let j = null;
    try { j = await r.json(); } catch (_) { j = null; }
    const t = j && typeof j.text === 'string' ? j.text.trim() : '';
    return t && j.no_speech !== true ? t : '';
  }
  // Each recording has a session number; a piece that comes back after Discard (or after a new
  // recording began) is dropped, and Save waits until every piece of this session is back.
  function queue(frames) {
    const sid = S.sid;
    S.pieces += 1; S.pending += 1;
    S.chain = S.chain.then(() => (sid === S.sid ? sendPiece(frames) : '')).then((t) => {
      if (sid === S.sid && t) S.text = (S.text ? S.text + ' ' : '') + t;
    }).catch((e) => {
      if (sid !== S.sid) return;
      if (e && e.cloud === false && Speech && S.mode !== 'browser') { S.cloud = false; useBrowser(); }
      else fail(e && e.cloud === false ? 'Cloud voice is off and this browser can\'t listen on its own. Type the note instead.' : 'Couldn\'t turn that recording into words. Try again, or type the note.');
    }).then(() => { if (sid === S.sid) S.pending = Math.max(0, S.pending - 1); draw(); });
  }

  // ---- recording through JarvisAudio -------------------------------------------------------------
  async function start() {
    if (S.mode !== 'idle') return;
    S.sid += 1; S.pending = 0; S.error = ''; S.text = ''; S.frames = []; S.total = 0; S.pieces = 0; S.cloud = true;
    const A = window.JarvisAudio;
    if (!A || !A.supported || !A.supported()) { if (Speech) { useBrowser(); return; } fail('This browser can\'t record. Type the note instead.'); return; }
    S.mode = 'recording'; draw();
    try { await A.open(); } catch (_) { S.mode = 'idle'; if (Speech) { useBrowser(); return; } fail('JARVIS needs the microphone. Allow it in the browser, or type the note.'); return; }
    S.unsub = A.subscribe((frame) => {
      if (S.mode !== 'recording') return;
      S.frames.push(frame); S.total += 1;
      if (S.frames.length >= FRAMES_PER_PIECE) { queue(S.frames); S.frames = []; }
      if (S.total >= MAX_FRAMES) stop();
    });
    A.onEnd(() => { if (S.mode === 'recording') stop(); });
  }
  function release() { if (S.unsub) { S.unsub(); S.unsub = null; } try { window.JarvisAudio.close(); } catch (_) {} }
  function stop() {
    if (S.mode === 'browser') { try { S.rec.stop(); } catch (_) {} S.mode = 'review'; draw(); return; }
    if (S.mode !== 'recording') return;
    release();
    if (S.frames.length) queue(S.frames);
    S.frames = []; S.mode = 'review'; draw();
  }

  // ---- the browser's own recognition (cloud voice off) -------------------------------------------
  function useBrowser() {
    release(); S.frames = []; S.mode = 'browser'; S.text = '';
    try {
      const rec = new Speech(); rec.continuous = true; rec.interimResults = false; rec.lang = navigator.language || 'en-IN';
      rec.onresult = (ev) => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) S.text = (S.text ? S.text + ' ' : '') + ev.results[i][0].transcript.trim(); draw(); };
      rec.onerror = () => { if (S.mode === 'browser') { S.mode = 'review'; fail('The browser couldn\'t listen. Type the note instead.'); } };
      rec.onend = () => { if (S.mode === 'browser') { S.mode = 'review'; draw(); } };
      S.rec = rec; rec.start();
    } catch (_) { S.mode = 'idle'; fail('This browser can\'t listen. Type the note instead.'); return; }
    draw();
  }

  // ---- save or discard ---------------------------------------------------------------------------
  async function saveMemo() {
    const text = S.text.trim();
    if (!text || S.busy || S.pending > 0) return;
    S.busy = true; S.error = ''; draw();
    try {
      await Notes().save({ kind: 'memo', text });
      S.busy = false; reset(); say('ok', 'Memo saved.');
    } catch (e) {
      S.busy = false;
      if (e && e.status === 401) { draw(); return; }
      S.error = e && e.status === 422 && e.code === 'sensitive' ? 'JARVIS doesn\'t keep that. IDs go in the Vault; JARVIS doesn\'t keep passwords or card numbers.'
        : (e && typeof e.message === 'string' && e.message.length <= 300 ? e.message : 'Please try again.');
      draw();
    }
  }
  function reset() { S.sid += 1; S.pending = 0; release(); if (S.rec) { try { S.rec.abort(); } catch (_) {} S.rec = null; } S.mode = 'idle'; S.text = ''; S.error = ''; S.frames = []; draw(); }

  // ---- the box under the buttons -----------------------------------------------------------------
  function draw() {
    const slot = document.getElementById('notesRecordSlot');
    if (!slot) return;
    if (!slot.querySelector('#nRecord')) {
      const b = mk('button', 'btn lift bact', 'Record memo'); b.type = 'button'; b.id = 'nRecord';
      b.addEventListener('click', () => { if (S.mode === 'idle') start(); else if (S.mode === 'recording' || S.mode === 'browser') stop(); });
      slot.append(b);
    }
    const btn = slot.querySelector('#nRecord');
    btn.textContent = S.mode === 'recording' || S.mode === 'browser' ? 'Stop' : 'Record memo';
    btn.setAttribute('aria-pressed', S.mode === 'recording' || S.mode === 'browser' ? 'true' : 'false');
    btn.toggleAttribute('hidden', S.mode === 'review');
    const host = slot.closest('#notes');
    if (!host) return;
    if (box && box.parentNode) box.remove();
    if (S.mode === 'idle' && !S.error) return;
    box = mk('div', 'nmemo'); box.id = 'nMemo'; box.setAttribute('aria-live', 'polite');
    if (S.mode === 'recording' || S.mode === 'browser') {
      box.append(mk('p', 'nmeta', S.mode === 'browser' ? 'Listening with your browser. Press Stop when done.' : 'Recording. Press Stop when done (up to 5 minutes).'));
    }
    if (S.mode === 'review' || S.text) {
      const l = mk('label', 'bl', 'Transcript (edit before saving)'); l.htmlFor = 'nMemoText';
      const t = mk('textarea', 'mta'); t.id = 'nMemoText'; t.rows = 5; t.maxLength = TEXT_MAX; t.value = S.text;
      t.addEventListener('input', () => { S.text = t.value; });
      box.append(l, t);
      const row = mk('div', 'mrow');
      const waiting = S.pending > 0;
      const save = mk('button', 'btn lift bact primary', S.busy ? 'Saving' : (waiting ? 'Turning speech into words' : 'Save memo')); save.type = 'button'; save.id = 'nMemoSave';
      if (S.busy || waiting) save.setAttribute('aria-disabled', 'true');
      save.addEventListener('click', () => { if (!S.busy && !waiting) saveMemo(); });
      const drop = mk('button', 'btn lift bact', 'Discard'); drop.type = 'button'; drop.id = 'nMemoDiscard'; drop.addEventListener('click', reset);
      row.append(save, drop); box.append(row);
      if (S.mode === 'review' && !S.text && S.pieces === 0) box.append(mk('p', 'nmeta', 'Nothing was heard. Try again, or type the note.'));
    }
    if (S.error) { const er = mk('p', 'mstat bad', S.error); er.setAttribute('role', 'alert'); box.append(er); }
    const anchor = host.querySelector('.nacts');
    if (anchor) anchor.after(box); else host.append(box);
  }

  window.addEventListener('jarvis:notes-rendered', draw);
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'notes' && !d.open && S.mode !== 'idle') reset(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && (S.mode === 'recording' || S.mode === 'browser')) stop(); });
  draw();
})();
