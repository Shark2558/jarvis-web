// src/jarvis/api/static/console-book-talk.js -- R6 D11-D14 (book.html): questions (typed or spoken), the closing lines in order,
// the guest hand-back and Resume (JarvisPasskey.prove('book_resume', lockId)).
// Questions: POST /v1/book/show/ask {text} -> {reply_id, reply, refused, follow_up, left}; the guarded reply is shown and
// spoken by its id (the server holds its text), then the follow-up line. A spoken question goes to POST /v1/book/show/hear
// (a WAV <= 15 s) and comes back as text in the box for the guest to send. The closing lines themselves are the last
// beats of the show (console-book-show.js); this file shows what comes after: the session closed, its conversation deleted,
// and -- while a guest lock holds the owner's consoles (D10) -- the hand-back line and Resume, also in any other console
// tab the lock sent here. The lock id comes from GET /v1/book/show/lock, or from a refused POST /v1/book/resume.
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
// A dropped connection is said calmly ("Can't reach JARVIS..."), never as the browser's raw error.
// window.JarvisBookTalk = { open({lines, phase}), hide(), clear(), done({audience, line, reason}), locked(), offline(retry) }
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const LOCK = /^bl_[0-9a-f]{12}$/, REPLY = /^r_[0-9a-f]{12}$/, MAX_Q = 500, POLL_MS = 4000;
  const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const txt = (v, max = 1200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const B = () => window.JarvisBook;
  const Show = () => window.JarvisBookShow;
  const V = () => window.JarvisBookVoice;
  const S = { lines: {}, phase: 'show', busy: false, left: null, lockId: '', poll: 0, recording: false, wired: false, gen: 0, retry: null };
  /** Plain words for a failure: a dropped connection (fetch's TypeError) gets the calm sentence. */
  const words = (e, fallback) => (e && e.name === 'TypeError' ? OFFLINE : (e && e.message) || fallback);

  // ---- the questions panel -------------------------------------------------------------------------
  function row(who, text, cls) {
    const r = mk('div', 'row ' + who + (cls ? ' ' + cls : '')), b = mk('div', 'bubble', text);
    r.append(b); $('shThread').append(r); r.scrollIntoView({ block: 'nearest' });
    return r;
  }
  function sys(text) { const d = mk('div', 'sys error', text); $('shThread').append(d); }
  function leftWords() {
    $('shLeft').textContent = S.left === null ? '' : S.left + ' question' + (S.left === 1 ? '' : 's') + ' left';
    const out = S.left === 0; // out of questions: the box goes away (the server's limit line says why)
    $('shQ').disabled = out || S.busy; $('shSend').disabled = S.busy; $('shMic').disabled = out || S.busy;
    $('shTalk').querySelector('.composer-wrap').hidden = out;
  }
  function open(opts) {
    wire();
    S.lines = obj(opts && opts.lines) || {}; S.phase = opts && opts.phase === 'questions' ? 'questions' : 'show';
    $('shFinish').textContent = S.phase === 'questions' ? 'No more questions' : 'Back to the show';
    $('shTalk').hidden = false; $('show').classList.add('talking');
    const R = V() && V().record;
    $('shMic').hidden = !(R && R.supported());
    leftWords(); $('shQ').focus();
  }
  function hide() {
    const had = $('shTalk').contains(document.activeElement); // keep the focus in the show (D15)
    S.gen += 1; $('shTalk').hidden = true; $('show').classList.remove('talking'); stopRec(true);
    if (had) $('shPlay').focus();
  }
  function clear() {
    stopRec(true);
    $('shThread').textContent = ''; $('shQ').value = ''; $('shLeft').textContent = '';
    S.left = null; S.lines = {}; hide();
  }
  function normal(raw) {
    const d = obj(raw);
    if (!d || typeof d.reply !== 'string') return null;
    return { id: REPLY.test(d.reply_id || '') ? d.reply_id : '', reply: txt(d.reply), refused: d.refused === true,
      follow: txt(d.follow_up, 200), left: Number.isInteger(d.left) && d.left >= 0 ? d.left : null };
  }
  async function ask() {
    const text = $('shQ').value.replace(/\s+/g, ' ').trim().slice(0, MAX_Q);
    if (!text || S.busy || S.left === 0) return;
    S.busy = true; $('shQ').value = ''; row('user', text); leftWords();
    const gen = S.gen; // the panel closed (Finish, End, the close) while waiting: drop what comes back
    const thinking = row('jarvis', '', 'pending'); thinking.firstChild.classList.add('typing');
    thinking.firstChild.append(mk('span', 'lbl', 'Thinking'));
    try {
      const r = normal(await B().api('/v1/book/show/ask', { method: 'POST', body: { text } }));
      thinking.remove();
      if (gen !== S.gen) { S.busy = false; return; }
      if (!r) throw new Error('The answer came back in a shape this page doesn\u2019t know.');
      row('jarvis', r.reply, r.refused ? 'refused' : '');
      if (r.left !== null) S.left = r.left;
      S.busy = false; leftWords(); $('shQ').focus();
      const sh = Show();
      if (sh && r.id) await sh.say(r.id, r.reply);
      if (gen !== S.gen) return;
      if (r.follow) { row('jarvis', r.follow); const id = S.lines.anything_else ? S.lines.anything_else.id : ''; if (sh && id) await sh.say(id, r.follow); }
    } catch (e) {
      thinking.remove(); S.busy = false; leftWords();
      if (e && e.status === 401) { const sh = Show(); if (sh) sh.expired(); return; }
      sys(words(e, 'That question did not go through.'));
    }
  }
  // a spoken question: record (tap again to stop, 15 s at most), then the words land in the box
  async function mic() {
    const R = V() && V().record;
    if (!R || S.busy) return;
    if (S.recording) { await sendRec(); return; }
    const gen = S.gen; // the panel closed (a jump, End, the close) while the microphone was starting: it never records
    try {
      if (!(await R.start())) return;
      if (gen !== S.gen) { R.cancel(); return; }
      S.recording = true; R.onFull(() => sendRec());
      $('shMic').setAttribute('aria-pressed', 'true'); $('shMic').setAttribute('aria-label', 'Stop and use what I said');
    } catch (_) { if (gen === S.gen) sys('The microphone is not available. Type the question instead.'); }
  }
  function stopRec(cancel) {
    const R = V() && V().record;
    S.recording = false; $('shMic').setAttribute('aria-pressed', 'false'); $('shMic').setAttribute('aria-label', 'Ask by voice');
    if (!R) return null;
    if (cancel) { R.cancel(); return null; }
    return R.stop();
  }
  async function sendRec() {
    const wav = stopRec(false);
    if (!wav) return;
    S.busy = true; leftWords();
    try {
      const r = await B().raw('/v1/book/show/hear', { method: 'POST', body: wav, headers: { 'Content-Type': 'audio/wav' } });
      if (!r.ok) throw await B().failure(r);
      const d = obj(await r.json());
      $('shQ').value = txt(d && d.text, MAX_Q);
    } catch (e) { if (e && e.status === 401) { const sh = Show(); if (sh) sh.expired(); return; } sys(words(e, 'I didn\u2019t catch that. Type the question instead.')); }
    S.busy = false; leftWords(); $('shQ').focus();
  }
  function finish() {
    const sh = Show();
    if (S.phase === 'questions') { stopRec(true); if (sh) sh.toClosing(); return; }
    hide(); if (sh) sh.resume();
  }
  function wire() {
    if (S.wired) return;
    S.wired = true;
    $('shSend').addEventListener('click', ask);
    $('shQ').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } });
    $('shMic').addEventListener('click', mic);
    $('shFinish').addEventListener('click', finish);
  }

  // ---- after the close: the session is gone; a guest lock may hold the owner's consoles ------------
  async function lockState() {
    if (B().mode() === 'token') return { on: false }; // token mode has no guest shows, so no lock to ask about
    try {
      const d = obj(await B().api('/v1/book/show/lock'));
      if (d) return { on: d.on === true, id: LOCK.test(d.id || '') ? d.id : '', line: txt(d.line, 200) };
    } catch (e) { if (e.status !== 404 && e.status !== 405) return { on: false, unknown: true }; }
    try { await B().api('/auth/me'); return { on: false }; } catch (e) { return { on: e.status === 423, id: '' }; } // /auth/me is 423 under a lock
  }
  function card(title, line, note) {
    $('shStart').hidden = true; $('shDone').hidden = false; $('shStartWrap').classList.add('show');
    $('shDoneTitle').textContent = title; $('shDoneLine').textContent = line || ''; $('shDoneNote').textContent = note || '';
    $('shDoneFine').textContent = ''; $('shRetry').hidden = true;
  }
  function home() { clearInterval(S.poll); window.location.assign('/'); }
  function showLocked(st, line) {
    S.lockId = st.id || S.lockId;
    card('Locked', line || st.line || '', 'A build book show holds this account\u2019s consoles. Your passkey unlocks them on this device or any other.');
    $('shResume').hidden = false; $('shBack').hidden = true; $('shResume').focus();
    clearInterval(S.poll);
    S.poll = setInterval(async () => { const now = await lockState(); if (!now.on && !now.unknown) home(); }, POLL_MS);
  }
  async function done(opts) {
    const o = obj(opts) || {};
    wireDone();
    hide();
    const st = await lockState();
    if (st.on) { showLocked(st, o.line); return; }
    const words = o.reason === 'expired' ? 'This session has ended. Its conversation was deleted.'
      : o.reason === 'error' ? (o.detail || 'The show could not start.') : o.failed ? 'The session ends by itself within 10 minutes; its conversation is then deleted.'
        : 'Session closed. Its conversation was deleted.';
    card('Build book', o.reason === 'closing' && o.audience === 'guest' ? o.line || '' : '', words);
    $('shResume').hidden = true; $('shBack').hidden = false; $('shBack').focus();
  }
  async function locked() {
    wireDone();
    const st = await lockState();
    if (st.on) { showLocked(st, ''); return; }
    card('Build book', '', 'There is no build book session in this tab. Open the book from the console\u2019s Book panel.');
    $('shResume').hidden = true; $('shBack').hidden = false; $('shBack').focus();
  }
  let doneWired = false;
  function wireDone() {
    if (doneWired) return;
    doneWired = true;
    $('shBack').addEventListener('click', home);
    $('shResume').addEventListener('click', resume);
    $('shRetry').addEventListener('click', () => {
      if ($('shRetry').disabled || !S.retry) return;
      $('shRetry').disabled = true; $('shDoneFine').textContent = 'Trying again\u2026'; S.retry();
    });
  }
  /** The show could not be loaded (the network, or the server for a moment): the session and its token stay. */
  function offline(retry) {
    wireDone();
    S.retry = typeof retry === 'function' ? retry : null;
    card('Build book', '', OFFLINE);
    $('shResume').hidden = true; $('shBack').hidden = true;
    const b = $('shRetry'); b.hidden = !S.retry; b.disabled = false; if (S.retry) b.focus();
  }
  /** Resume (D10): a book_resume passkey bound to the lock id lifts the lock for every console. */
  async function resume() {
    const btn = $('shResume'), fine = $('shDoneFine');
    if (btn.disabled) return;
    btn.disabled = true; fine.textContent = 'Waiting for your passkey\u2026';
    try {
      let id = S.lockId;
      if (!id) {
        try { const r = obj(await B().api('/v1/book/resume', { method: 'POST', body: {} })); if (r && r.resumed) { home(); return; } }
        catch (e) { id = LOCK.test((e.body || {}).lock_id || '') ? e.body.lock_id : ''; if (!id) throw e; }
        S.lockId = id;
      }
      const P = window.JarvisPasskey;
      if (!P || typeof P.prove !== 'function') throw new Error('Passkeys are not available in this page.');
      const proof = await P.prove('book_resume', id);
      const r = obj(await B().api('/v1/book/resume', { method: 'POST', body: { proof } }));
      if (r && r.resumed) { home(); return; }
      throw new Error('The consoles are still locked. Please try again.');
    } catch (e) {
      const P = window.JarvisPasskey;
      fine.textContent = (e && e.passkeyMessage) || (e && e.name === 'TypeError' ? OFFLINE : '') || (e && e.message)
        || (P && P.message ? P.message(e) : '') || 'That did not work. Please try again.';
    }
    btn.disabled = false;
  }

  window.JarvisBookTalk = Object.freeze({ open, hide, clear, done, locked, offline });
})();
