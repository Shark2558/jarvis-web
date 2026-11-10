// src/jarvis/api/static/console-book-show.js -- R6 D15 (book.html): the show's timeline, controls (Space, arrows, PageUp/
// PageDown, C, M, Q, Esc), captions (aria-live) and the 60-second beat.
// The page holds no data of its own: GET /v1/book/show/script (header X-Jarvis-Book, the token from THIS tab's
// sessionStorage) gives scenes 1-11 (book.show), the fixed lines (ask, hand_back, ...) and the closing; the timeline is
// those beats, then the ask line (scene 12), then the closing lines (scene 13). A beat is one line: the next starts when
// the line's audio ends (console-book-voice.js; captions only: 330 ms a word + 800 ms). The 3D engine (console-book-3d.js)
// or the 2D cards (console-book-2d.js) draw the beat; questions, the hand-back and Resume are console-book-talk.js.
// At the close (the closing ends, End, expiry) the page clears its DOM, the token and its audio (D14).
// Also gives window.JarvisBook (this page's transport) and a minimal window.JarvisConsole.api for JarvisPasskey.
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = 'jarvis_book_token', SESSION_KEY = 'jarvis_book_session', HEADER = 'X-Jarvis-Book';
  const BEAT_MS = 60 * 1000, READY_WAIT_MS = 6000, FADE_MS = 1400, WORD_MS = 330, TAIL_MS = 800;
  const LINE_ID = /^s\d{2}b\d{2}$/, KEY_ID = /^[a-z_]{2,20}$/, RID = /^[0-9a-f]{7}$/, OWN = /^\/(?![/\\])/;
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const LAST_TITLES = { 12: 'Questions', 13: 'Closing' };
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 400) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const ss = {
    get(k) { try { return sessionStorage.getItem(k) || ''; } catch (_) { return ''; } },
    del(k) { try { sessionStorage.removeItem(k); } catch (_) {} },
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const captionMs = (text) => (String(text).split(/\s+/).filter(Boolean).length * WORD_MS) + TAIL_MS;

  // ---- transport: same-origin, X-Requested-With, the console's bearer in token mode, the book token on book routes
  async function raw(path, opts = {}) {
    if (typeof path !== 'string' || !OWN.test(path)) throw new Error('Not a JARVIS path.');
    const headers = Object.assign({ 'X-Requested-With': 'JARVIS' }, opts.headers || {});
    const bearer = ss.get('jarvis_token'), token = ss.get(TOKEN_KEY);
    if (bearer) headers.Authorization = 'Bearer ' + bearer;
    if (token && path.startsWith('/v1/book/')) headers[HEADER] = token;
    let body = opts.body;
    if (body !== undefined && !(body instanceof ArrayBuffer) && !(body instanceof Blob)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
    return fetch(path, { method: opts.method || (body !== undefined ? 'POST' : 'GET'), headers, body, credentials: 'same-origin', cache: 'no-store', signal: opts.signal });
  }
  async function failure(r) {
    let d = null;
    try { d = obj(await r.json()); } catch (_) {}
    const e = new Error(txt(d && typeof d.detail === 'string' ? d.detail : '', 300) || 'That did not work. Please try again.');
    e.status = r.status; e.code = d && typeof d.error === 'string' ? d.error : ''; e.body = d || {};
    return e;
  }
  async function api(path, opts) {
    const r = await raw(path, opts);
    if (!r.ok) throw await failure(r);
    return r.status === 204 ? null : r.json();
  }
  let authMode = ''; // /console/config: a guest lock exists only in Google mode (a guest show needs it)
  window.JarvisBook = Object.freeze({ api, raw, failure, captionMs, token: () => ss.get(TOKEN_KEY), mode: () => authMode });
  // JarvisPasskey (console-permissions.js) asks window.JarvisConsole.api at call time: this page has no console.js
  if (!window.JarvisConsole) window.JarvisConsole = Object.freeze({ api, ready: () => null });

  // ---- the script, checked field by field ---------------------------------------------------------
  function line(v) {
    const o = obj(v), id = o ? txt(o.id, 40) : '', text = o ? txt(o.text, 1200) : txt(v, 1200);
    return text ? { id: KEY_ID.test(id) ? id : '', text } : null;
  }
  function normalScene(v) {
    const s = obj(v);
    if (!s || !Number.isInteger(s.n) || s.n < 1 || s.n > 11) return null;
    const beats = arr(s.beats).map(obj).filter((b) => b && LINE_ID.test(b.id || '') && txt(b.text))
      .map((b) => ({ id: b.id, text: txt(b.text), focus: txt(b.focus, 60) }));
    const facts = arr(s.facts).map(obj).filter(Boolean).slice(0, 60).map((f) => ({ label: txt(f.label, 80), value: txt(f.value, 120),
      n: num(f.n), group: txt(f.group, 40), flag: txt(f.flag, 20) }));
    return beats.length ? { n: s.n, id: txt(s.id, 40), title: txt(s.title, 60), beats, facts } : null;
  }
  function normalScript(raw, audience) {
    const d = obj(raw);
    if (!d) return null;
    const scenes = arr(d.scenes).map(normalScene).filter(Boolean).sort((a, b) => a.n - b.n);
    if (!scenes.length) return null;
    const L = obj(d.lines) || {}, lines = {};
    ['ask', 'anything_else', 'hand_back', 'ai_off'].forEach((k) => { const l = line(L[k]); if (l) lines[k] = { id: l.id || k, text: l.text }; });
    const who = d.audience === 'owner' || d.audience === 'guest' ? d.audience : audience;
    let closing = d.closing;
    if (obj(closing)) closing = closing[who];
    const rel = obj(d.release) || {}, talk = obj(d.talk) || {}, costs = obj(d.costs) || {};
    return { release: { id: RID.test(rel.id || '') ? rel.id : '', label: txt(rel.label, 8) }, audience: who, scenes, lines,
      closing: arr(closing).map(line).filter(Boolean).slice(0, 6), costs: { month: num(costs.month_inr), limit: num(costs.limit_inr) },
      talk: { on: talk.on !== false, why: txt(talk.why, 200) }, voice: d.voice === 'browser' ? 'browser' : 'cloud', until: txt(d.until, 40) };
  }
  function timeline(sc) {
    const out = [];
    sc.scenes.forEach((s) => s.beats.forEach((b, i) => out.push({ scene: s.n, i, id: b.id, text: b.text, focus: b.focus })));
    const q = sc.talk.on ? sc.lines.ask : sc.lines.ai_off;
    out.push({ scene: 12, i: 0, id: q ? q.id : '', text: q ? q.text : '', focus: '', ask: true });
    sc.closing.forEach((l, i) => out.push({ scene: 13, i, id: l.id, text: l.text, focus: '', closing: true }));
    return out;
  }

  // ---- state and rendering of one beat --------------------------------------------------------------
  const S = { script: null, beats: [], index: 0, playing: false, run: 0, phase: 'loading', audience: 'guest', captions: true,
    sound: true, R: null, rname: '', closing: false, beatTimer: 0, waiters: [], loop: 0 };
  const voice = () => window.JarvisBookVoice || null;
  const talk = () => window.JarvisBookTalk || null;
  function sceneData(n) {
    const sc = S.script;
    if (n <= 11) return sc.scenes.find((s) => s.n === n) || { n, id: '', title: '', beats: [], facts: [] };
    return { n, id: n === 12 ? 'questions' : 'closing', title: LAST_TITLES[n], beats: S.beats.filter((b) => b.scene === n), facts: [] };
  }
  const sceneTitle = (n) => (n <= 11 ? (S.script.scenes.find((s) => s.n === n) || {}).title || '' : LAST_TITLES[n]);
  function present(i) {
    const b = S.beats[i];
    if (!b) return;
    S.index = i;
    $('shCapText').textContent = b.text;
    $('shCount').textContent = String(b.scene).padStart(2, '0') + ' / 13';
    $('shScene').textContent = sceneTitle(b.scene);
    const pct = Math.round((i / Math.max(1, S.beats.length - 1)) * 100);
    $('shProg').setAttribute('aria-valuenow', String(pct)); $('shProg').firstElementChild.style.width = pct + '%';
    if (S.R) S.R.show(sceneData(b.scene), b.i, b, { audience: S.audience, costs: S.script.costs, listening: b.scene === 12 });
  }
  function sync() {
    const m = $('show');
    m.dataset.state = S.phase;
    $('shPlay').setAttribute('aria-pressed', String(S.playing));
    $('shPlay').setAttribute('aria-label', S.playing ? 'Pause (Space)' : 'Play (Space)');
    $('shCaptions').setAttribute('aria-pressed', String(S.captions));
    $('shCap').classList.toggle('off', !S.captions);
    $('shSound').setAttribute('aria-pressed', String(S.sound));
    $('shSound').textContent = S.sound ? 'Sound' : 'Muted';
  }

  // ---- playback: one line at a time, each starting when the previous one's audio ends ---------------
  function speak(b) {
    const V = voice();
    if (!b.text) return Promise.resolve();
    return V ? V.say(b.id, b.text) : wait(captionMs(b.text));
  }
  function resumed() { return new Promise((r) => S.waiters.push(r)); }
  async function play(from) {
    const run = ++S.run;
    S.playing = true; S.phase = 'playing'; S.loop = run; sync(); hold(false);
    for (let i = from; i < S.beats.length; i += 1) {
      if (run !== S.run) return;
      present(i);
      const said = speak(S.beats[i]), next = S.beats[i + 1], V = voice();
      if (next && V && next.id && !S.beats[i].ask) V.prefetch(next.id); // one beat ahead, never past the questions
      await said;
      while (run === S.run && !S.playing) await resumed();
      if (run !== S.run) return;
      if (S.beats[i].ask) { questions(); return; }
    }
    if (run === S.run) finish();
  }
  function pause() {
    if (!S.playing || S.phase !== 'playing') return;
    S.playing = false; const V = voice(); if (V) V.pause(); sync(); hold(true);
  }
  function hold(on) { if (S.R && S.R.hold) S.R.hold(on); }
  function resume() {
    if (S.phase !== 'playing' && S.phase !== 'paused') return;
    if (S.playing) return;
    S.playing = true; sync(); hold(false);
    if (S.loop !== S.run) { play(S.index); return; } // paused after a jump: no line is running, start this one
    const V = voice(); if (V) V.resume();
    const w = S.waiters; S.waiters = []; w.forEach((r) => r());
  }
  /** Jump to a beat: playing goes on from there; paused shows it and waits (Questions opens its panel, the closing
   *  waits for Play: a jump never ends the session by itself). */
  function jump(i) {
    if (!S.beats.length || S.closing) return;
    const to = Math.max(0, Math.min(S.beats.length - 1, i));
    const T = talk(); if (T && S.phase === 'questions' && S.beats[to].scene !== 12) T.hide();
    S.run += 1; const V = voice(); if (V) V.stop();
    const w = S.waiters; S.waiters = []; w.forEach((r) => r());
    S.phase = 'playing';
    if (S.playing) { play(to); return; }
    present(to); sync();
    if (S.beats[to].ask && S.script.talk.on) questions();
  }
  const sceneStart = (n) => S.beats.findIndex((b) => b.scene === n);
  function stepScene(dir) {
    const cur = S.beats[S.index] ? S.beats[S.index].scene : 1;
    for (let n = cur + dir; n >= 1 && n <= 13; n += dir) { const i = sceneStart(n); if (i >= 0) { jump(i); return; } }
  }
  function questions() {
    S.phase = 'questions'; S.playing = false; sync(); hold(false); // the Core listens: it keeps moving
    const T = talk();
    if (!S.script.talk.on) { toClosing(); return; }
    if (T) T.open({ lines: S.script.lines, phase: 'questions' });
  }
  function toClosing() {
    const i = sceneStart(13);
    const T = talk(); if (T) T.hide();
    if (i < 0) { finish(); return; }
    S.run += 1; const V = voice(); if (V) V.stop();
    play(i);
  }
  async function finish() {
    S.phase = 'closing'; sync();
    await wait(window.JarvisFX && window.JarvisFX.motion() !== 'full' ? 200 : FADE_MS);
    closeSession('closing');
  }

  // ---- the end: close on the server, then clear the page (D14) ---------------------------------------
  async function closeSession(reason) {
    if (S.closing) return;
    S.closing = true; S.run += 1; S.playing = false;
    let res = null;
    if (ss.get(TOKEN_KEY)) { try { res = obj(await api('/v1/book/close', { method: 'POST' })); } catch (e) { res = { failed: true, status: e.status }; } }
    const hand = S.script && S.script.lines.hand_back ? S.script.lines.hand_back.text : '';
    const audience = S.audience;
    wipe();
    const T = talk();
    if (T) T.done({ audience, line: hand, reason, closed: !!(res && res.closed), failed: !!(res && res.failed) });
  }
  function wipe() {
    clearInterval(S.beatTimer); S.beatTimer = 0;
    const V = voice(); if (V) V.dispose();
    if (S.R) { try { S.R.dispose(); } catch (_) { /* best effort */ } S.R = null; }
    ['shCapText', 'shScene', 'shCount', 'shRelease', 'shUntil', 'shLabels', 'sh2d', 'shStartRel', 'shStartNote'].forEach((id) => { const n = $(id); if (n) n.textContent = ''; });
    const T = talk(); if (T) T.clear();
    ss.del(TOKEN_KEY); ss.del(SESSION_KEY);
    S.script = null; S.beats = []; S.phase = 'done'; S.playing = false; S.waiters = [];
    $('show').dataset.state = 'done';
  }
  /** A book call answered 401: the session ended on the server (expiry, idle, a newer open). */
  function expired() { if (!S.closing) { S.closing = true; wipe(); const T = talk(); if (T) T.done({ audience: S.audience, reason: 'expired' }); } }
  async function beat() {
    try { await api('/v1/book/show/beat', { method: 'POST' }); } catch (e) { if (e.status === 401) expired(); }
  }

  // ---- controls and keys ---------------------------------------------------------------------------
  function toggleSound() { S.sound = !S.sound; const V = voice(); if (V) V.mute(!S.sound); sync(); }
  function toggleCaptions() { S.captions = !S.captions; sync(); }
  function ask() { const T = talk(); if (!T || S.phase === 'done' || S.phase === 'start') return; if (S.phase === 'playing') pause(); T.open({ lines: S.script.lines, phase: S.phase === 'questions' ? 'questions' : 'show' }); }
  function confirmEnd() {
    const d = $('shConfirm');
    if (d.open || S.closing || !S.script) return;
    const was = S.playing; pause();
    d.onclose = () => { if (d.returnValue !== 'end') { if (was) resume(); $('shEnd').focus(); } };
    d.returnValue = ''; d.showModal(); $('shKeep').focus();
  }
  function chapters() {
    const d = $('shChapterList'), list = $('shChapterItems');
    if (!S.script || d.open) return;
    list.textContent = '';
    for (let n = 1; n <= 13; n += 1) {
      const i = sceneStart(n); if (i < 0) continue;
      const li = document.createElement('li'), b = document.createElement('button');
      b.type = 'button'; b.className = 'btn lift sh-chapter'; b.textContent = String(n).padStart(2, '0') + ' \u00b7 ' + sceneTitle(n);
      b.addEventListener('click', () => { d.close(); jump(i); });
      li.append(b); list.append(li);
    }
    d.showModal();
    const cur = list.querySelectorAll('button')[Math.max(0, (S.beats[S.index] || { scene: 1 }).scene - 1)];
    if (cur) cur.focus();
  }
  const typing = (e) => !!(e.target && e.target.closest && e.target.closest('textarea, input, select, [contenteditable="true"]'));
  function onKey(e) {
    if (typing(e) || e.altKey || e.ctrlKey || e.metaKey || !S.script || S.phase === 'done') return;
    if (document.querySelector('dialog[open]')) return;
    const k = e.key, map = { ' ': () => (S.playing ? pause() : resume()), ArrowRight: () => jump(S.index + 1), ArrowLeft: () => jump(S.index - 1),
      PageDown: () => stepScene(1), PageUp: () => stepScene(-1), c: toggleCaptions, C: toggleCaptions, m: toggleSound, M: toggleSound,
      q: ask, Q: ask, Escape: confirmEnd };
    if (S.phase === 'start' && k !== 'm' && k !== 'M' && k !== 'c' && k !== 'C') return;
    if (!map[k]) return;
    if (k === ' ' && e.target && e.target.closest && e.target.closest('button')) return; // a focused button takes Space itself
    e.preventDefault(); map[k]();
  }
  function wire() {
    $('shPlay').addEventListener('click', () => (S.playing ? pause() : resume()));
    $('shPrev').addEventListener('click', () => jump(S.index - 1));
    $('shNext').addEventListener('click', () => jump(S.index + 1));
    $('shPrevScene').addEventListener('click', () => stepScene(-1));
    $('shNextScene').addEventListener('click', () => stepScene(1));
    $('shCaptions').addEventListener('click', toggleCaptions);
    $('shSound').addEventListener('click', toggleSound);
    $('shAsk').addEventListener('click', ask);
    $('shEnd').addEventListener('click', confirmEnd);
    $('shChapters').addEventListener('click', chapters);
    $('shChapClose').addEventListener('click', () => $('shChapterList').close());
    $('shKeep').addEventListener('click', () => $('shConfirm').close('keep'));
    $('shEndYes').addEventListener('click', () => { $('shConfirm').close('end'); closeSession('end'); });
    $('shBegin').addEventListener('click', begin);
    document.addEventListener('keydown', onKey);
    window.addEventListener('pagehide', () => { const V = voice(); if (V) V.dispose(); if (S.R) S.R.dispose(); });
  }

  // ---- boot ----------------------------------------------------------------------------------------
  async function renderer() {
    const B3 = window.JarvisBook3D, B2 = window.JarvisBook2D;
    if (B3 && B3.ready) {
      const ok = await Promise.race([B3.ready, wait(READY_WAIT_MS).then(() => false)]);
      if (ok) {
        const R = B3.mount({ canvas: $('showGL'), labels: $('shLabels'), level: () => (voice() ? voice().level() : 0), onRetire: () => fallback() });
        if (R) { S.rname = '3d'; return R; }
      }
    }
    S.rname = '2d';
    return B2 ? B2.mount($('sh2d')) : null;
  }
  /** The 3D layer retired (a weak GPU, a lost context, a narrow window): the same beat as 2D cards. */
  function fallback() {
    if (S.rname !== '3d') return;
    S.R = null; S.rname = '2d'; $('shLabels').textContent = '';
    const B2 = window.JarvisBook2D;
    if (B2 && S.script) { S.R = B2.mount($('sh2d')); present(S.index); }
    document.documentElement.dataset.bookRenderer = '2d';
  }
  function startCard(sc) {
    const rel = (sc.release.label ? sc.release.label + ' \u00b7 ' : '') + sc.release.id;
    $('shRelease').textContent = rel; $('shStartRel').textContent = rel;
    $('shStartNote').textContent = sc.audience === 'guest' ? 'A guest show: nothing of the owner\u2019s is in this session, and it is deleted when it ends.'
      : 'Your show, with this month\u2019s spend. It is deleted when it ends.';
    const until = new Date(sc.until);
    if (!isNaN(until) && until.getFullYear() < 2090) $('shUntil').textContent = 'Ends ' + until.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    S.phase = 'start'; sync();
    $('shStartWrap').classList.add('show'); $('shStart').hidden = false; $('shBegin').focus();
  }
  function begin() {
    if (S.phase !== 'start') return;
    const V = voice(); if (V) { V.start(S.script.voice); V.mute(!S.sound); }
    $('shStart').hidden = true; $('shStartWrap').classList.remove('show');
    S.phase = 'playing'; S.playing = true; sync(); // the controls show before focus moves to them
    S.beatTimer = setInterval(beat, BEAT_MS);
    $('shPlay').focus();
    play(0);
  }
  async function boot() {
    wire();
    try { const c = obj(await api('/console/config')); authMode = c && typeof c.auth_mode === 'string' ? c.auth_mode : ''; } catch (_) { authMode = ''; }
    let audience = 'guest';
    try { audience = (JSON.parse(ss.get(SESSION_KEY) || '{}') || {}).audience === 'owner' ? 'owner' : 'guest'; } catch (_) {}
    S.audience = audience;
    const T = talk();
    if (!ss.get(TOKEN_KEY)) { S.phase = 'done'; sync(); if (T) T.locked(); return; }
    let sc = null;
    try { sc = normalScript(await api('/v1/book/show/script'), audience); }
    catch (e) { if (e.status === 401 || e.status === 404) { expired(); return; } S.phase = 'done'; wipe(); if (T) T.done({ audience, reason: 'error', detail: e.message }); return; }
    if (!sc) { S.phase = 'done'; wipe(); if (T) T.done({ audience, reason: 'error' }); return; }
    S.script = sc; S.audience = sc.audience; S.beats = timeline(sc);
    S.R = await renderer();
    document.documentElement.dataset.bookRenderer = S.rname;
    present(0);
    startCard(sc);
  }
  window.JarvisBookShow = Object.freeze({
    state: () => ({ phase: S.phase, playing: S.playing, index: S.index, scene: S.beats[S.index] ? S.beats[S.index].scene : 0,
      renderer: S.rname, motion: window.JarvisFX ? window.JarvisFX.motion() : 'full', audio: voice() ? voice().state() : 'none' }),
    say: (id, text) => (S.closing ? Promise.resolve() : speak({ id, text })),
    toClosing, expired, resume: () => { if (S.phase === 'questions' || S.closing) return; S.phase = 'playing'; resume(); },
    pause,
  });
  // deferred: the voice, 2D and talk scripts after this one run before DOMContentLoaded, never before this line
  if (document.readyState === 'complete') boot(); else document.addEventListener('DOMContentLoaded', boot, { once: true });
})();
