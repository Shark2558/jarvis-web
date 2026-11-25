// src/jarvis/api/static/console-book-chapter.js -- R6.4 D7 (docs/plans/r6-4-book-look.md): the chapter player of the
// full book's page (/book/read), an ES module. The reader's Play card calls open(chapterId, {line}): GET
// /v1/book/chapters/{id} (the book token on the page's transport, window.JarvisBook) gives the chapter's spoken lines with
// their cues; GET /v1/book/pages/{id} gives each page's sections and flowchart (kept for the visit: a chapter played
// again asks for none of them, review L-3). Then the timeline: one line at a time, the
// next when the line's voice ends (console-book-voice.js, always the browser's voice: start('browser') from the Play tap;
// captions only when Sound is off or there is no voice: 330 ms a word + 800 ms), the caption's words lit as they are said
// (the voice's word boundaries, else a timed estimate), the stage drawn by the effects engine (console-book-fx.js), the
// controls and the tour's keys: Space play/pause, Left/Right a line, Page Up/Down a page, C captions, M sound, Esc Stop.
// Stop goes back to reading: the player closes and the document event 'jarvis:book-chapter' {action: 'stop', chapter,
// page, line, release} names the page being told (the reader opens it). Continue where I left off: localStorage
// jarvis_book_place_v1 {release, chapter, line, heard_at} (ids, and when it was heard: ms, so the reader's Continue can
// tell it from a page read later; I1), merged with the tour's and the reader's fields, never over a place of another
// release that they wrote; a chapter played to its end is forgotten. The tab hidden pauses it; back,
// it plays on only if it was playing. Contract (I0-NOTES.md section 7): window.JarvisBookChapter = {open(chapterId,
// {line}) -> Promise<boolean>, stop(), state() -> {open, chapter, line, playing, page}}; it draws only in #brPlayer and
// sets #bookRead[data-mode="player"] while open. No build step; CSP script-src 'self'; textContent only; ASCII; <= 400 lines.
import { createFx } from './console-book-fx.js';
import { mount } from './console-book-chapter-view.js';

const $ = (id) => document.getElementById(id);
const CHAPTER = /^(?:story|module)_[a-z0-9_]{1,40}$/, PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/;
const RID = /^[0-9a-f]{7}$/, PLACE = 'jarvis_book_place_v1', CUES = new Set(['page', 'show', 'node', 'edge', 'count']);
const MINE = ['release', 'chapter', 'line', 'heard_at'];
const WORD_MS = 330, TAIL_MS = 800, FIRST_WORD_MS = 700, TICK_MS = 100, RATES = [0.85, 1, 1.25], WPM = 150;
const GONE = new Set([401, 403, 410]), KEEP = 60; // KEEP: pages kept for this visit (a sealed release's never change)
const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
const WORDS = Object.freeze({
  gone: 'The book session ended. Open the book again from the Book panel in the console.',
  missing: 'This chapter isn\u2019t in this release of the book.',
  down: 'This chapter can\u2019t be loaded right now. Try again in a moment.',
  silent: 'This chapter has no narration yet. Its pages can still be read.',
  end: 'That is the end of the chapter.',
});
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const txt = (v, max) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
const wordsIn = (t) => String(t || '').split(/\s+/).filter(Boolean).length;
const voice = () => window.JarvisBookVoice || null;
const book = () => window.JarvisBook || null;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const KEPT = new Map(); // '<release>:<page id>' -> the page as checked: a chapter played again asks for none (review L-3)

const S = { open: false, gen: 0, id: '', release: '', title: '', lines: [], pages: {}, list: [], plan: [], first: {},
  est: [], index: 0, playing: false, run: 0, loop: 0, waiters: [], cc: true, sound: true, rate: 1, fx: null, view: null,
  state: 'closed', hiddenHold: false, opener: null, line: { ms: 0, bound: false, timer: 0 }, cloud: null, keys: false };

// ---- the server's words, checked ---------------------------------------------------------------------------------------
function lineOf(raw) {
  const l = obj(raw);
  if (!l || !Number.isInteger(l.n) || typeof l.page !== 'string' || !PAGE.test(l.page)) return null;
  const text = txt(l.text, 600);
  if (!text) return null;
  const cues = (Array.isArray(l.cues) ? l.cues : []).map(obj).filter((c) => c && CUES.has(c.kind) && typeof c.target === 'string')
    .map((c) => ({ kind: c.kind, target: txt(c.target, 120) }));
  return { n: l.n, page: l.page, text, cues };
}
function pageOf(raw, id) {
  const p = obj(raw);
  if (!p) return null;
  const sections = (Array.isArray(p.sections) ? p.sections : []).map(obj).filter(Boolean)
    .map((s) => ({ id: txt(s.id, 20), text: typeof s.text === 'string' ? s.text.replace(INVISIBLE, '').slice(0, 2400) : '' }));
  return { id, title: txt(p.title, 120), kind: txt(p.kind, 20), sections, flow: obj(p.flow) };
}
const lineMs = (l) => (wordsIn(l.text) * WORD_MS + TAIL_MS) / S.rate;
const query = () => {
  const r = window.JarvisBookRead && typeof window.JarvisBookRead.release === 'function' ? window.JarvisBookRead.release() : '';
  return RID.test(r || '') ? '?release=' + r : '';
};

// ---- continue where I left off (ids only; the tour's and the reader's fields kept) -----------------------------------
function readPlace() {
  try { return obj(JSON.parse(localStorage.getItem(PLACE) || 'null')) || {}; } catch (_) { return {}; }
}
function remember() {
  const l = S.lines[S.index];
  if (!RID.test(S.release) || !l || S.state !== 'ready') return;
  const old = readPlace(), others = Object.keys(old).filter((k) => !MINE.includes(k));
  if (others.length && old.release !== S.release) return; // another part's place of another release stays as it is
  const next = {};
  others.forEach((k) => { next[k] = old[k]; });
  next.release = S.release; next.chapter = S.id; next.line = l.n; next.heard_at = Date.now();
  try { localStorage.setItem(PLACE, JSON.stringify(next)); } catch (_) { /* full or blocked: nothing kept */ }
}
function forgetPlace() {
  const old = readPlace();
  if (old.release !== S.release || old.chapter !== S.id) return;
  delete old.chapter; delete old.line; delete old.heard_at;
  try {
    if (Object.keys(old).some((k) => k !== 'release')) localStorage.setItem(PLACE, JSON.stringify(old)); else localStorage.removeItem(PLACE);
  } catch (_) { /* blocked */ }
}
/** This browser's chapter place for a release ({chapter, line}) or null: for the reader's Continue card. */
function place(release) {
  const p = readPlace();
  return p.release === release && CHAPTER.test(p.chapter || '') && Number.isInteger(p.line) ? { chapter: p.chapter, line: p.line } : null;
}

// ---- state shown -------------------------------------------------------------------------------------------------------
function pageIndex(i) { const l = S.lines[i]; return l ? S.list.findIndex((p) => p.id === l.page) : 0; }
function sync() {
  if (!S.view || S.state === 'loading' || S.state === 'failed') return;
  const i = S.index, pi = Math.max(0, pageIndex(i)), pg = S.list[pi], cur = S.est[i] || 0;
  const into = Math.min(cur, S.line.ms), before = S.est.slice(0, i).reduce((a, b) => a + b, 0);
  const firstOf = S.first[pg ? pg.id : ''] || 0, inPage = i - firstOf;
  S.view.sync({ playing: S.playing, cc: S.cc, sound: S.sound, rate: S.rate, pageIndex: pi, lineInPage: inPage,
    view: S.plan[i] ? S.plan[i].scene.view : '', elapsed: before + into, total: S.est.reduce((a, b) => a + b, 0),
    pageFrac: pg && pg.lines ? Math.min(1, (inPage + (cur ? into / cur : 0)) / pg.lines) : 0 });
}

// ---- the caption: lit by the voice's word boundaries, else by the timed estimate ----------------------------------------
function tickOn(l) {
  clearInterval(S.line.timer);
  S.line = { ms: 0, bound: false, timer: 0 };
  const per = WORD_MS / S.rate, wait0 = S.sound ? FIRST_WORD_MS : 0, me = S.line;
  me.timer = setInterval(() => {
    if (!S.playing || S.line !== me) return;
    me.ms += TICK_MS;
    if (!me.bound && me.ms >= wait0) S.view.lightTo(Math.floor(me.ms / per));
    if (me.ms % 500 === 0) sync();
  }, TICK_MS);
}
function tickOff() { clearInterval(S.line.timer); }
function speak(i) {
  const l = S.lines[i], V = voice(), me = S.line;
  const onWord = (charIndex) => { if (S.line !== me) return; me.bound = true; S.view.lightTo(S.view.wordAt(charIndex)); };
  const said = V ? V.say('chapter', l.text, { rate: S.rate, onWord }) : wait(lineMs(l));
  return said.then((how) => { if (how !== 'stopped' && S.line === me) S.view.lightTo(S.view.words()); });
}

// ---- playback ------------------------------------------------------------------------------------------------------------
function present(i, jump) {
  S.index = i;
  S.view.caption(S.lines[i].text);
  S.view.lightTo(-1);
  tickOn(S.lines[i]);
  sync();
  if (S.fx) S.fx.show(i, { jump });
  remember();
}
function resumed() { return new Promise((r) => S.waiters.push(r)); }
function release() { const w = S.waiters; S.waiters = []; w.forEach((r) => r()); }
async function play(from) {
  const run = ++S.run;
  S.loop = run; S.playing = true; S.state = 'ready';
  if (S.fx) S.fx.resume();
  for (let i = from; i < S.lines.length; i += 1) {
    if (run !== S.run) return;
    present(i, false);
    await speak(i);
    while (run === S.run && !S.playing) await resumed();
    if (run !== S.run) return;
  }
  if (run === S.run) finish();
}
function pause() {
  if (!S.open || !S.playing) return;
  S.playing = false; S.hiddenHold = false;
  const V = voice(); if (V) V.pause();
  if (S.fx) S.fx.pause();
  sync(); remember();
}
function resume() {
  if (!S.open || S.playing || S.state !== 'ready' || !S.lines.length) return;
  S.playing = true; S.hiddenHold = false;
  if (S.loop !== S.run) { play(S.index); return; } // paused after a jump: no line is running, start this one
  const V = voice(); if (V) V.resume();
  if (S.fx) S.fx.resume();
  sync(); release();
}
function toggle() {
  if (S.state === 'done') { again(); return; }
  if (S.playing) pause(); else resume();
}
/** Jump to a line: playing goes on from there; paused shows it at once and waits. */
function jump(i) {
  if (!S.open || !S.lines.length || S.state === 'loading' || S.state === 'failed') return;
  const to = Math.max(0, Math.min(S.lines.length - 1, i));
  S.run += 1;
  const V = voice(); if (V) V.stop();
  release(); tickOff();
  if (S.state === 'done') { S.state = 'ready'; S.view.ready(info()); }
  if (S.playing) { play(to); return; }
  present(to, true);
}
function stepPage(dir) {
  const pi = pageIndex(S.index), first = S.first[(S.list[pi] || {}).id] || 0;
  if (dir < 0 && S.index > first && S.playing) { jump(first); return; } // back to this page's start first, while playing
  const to = S.list[pi + dir];
  if (to) jump(S.first[to.id]); else if (dir < 0) jump(0);
}
function finish() {
  S.playing = false; S.state = 'done'; tickOff();
  forgetPlace();
  sync();
  S.view.done(WORDS.end);
}
function again() {
  if (!S.open || !S.lines.length) return;
  S.state = 'ready'; S.view.ready(info()); S.playing = true;
  S.run += 1; const V = voice(); if (V) V.stop();
  release(); play(0);
}

// ---- controls ------------------------------------------------------------------------------------------------------------
function toggleCaptions() { S.cc = !S.cc; sync(); }
function toggleSound() { S.sound = !S.sound; const V = voice(); if (V) V.mute(!S.sound); sync(); }
function cycleSpeed() {
  S.rate = RATES[(RATES.indexOf(S.rate) + 1) % RATES.length];
  S.est = S.lines.map(lineMs);
  sync(); // the next line speaks at the new speed
}
const typing = (e) => !!(e.target && e.target.closest && e.target.closest('textarea, input, select, [contenteditable="true"]'));
function onKey(e) {
  if (!S.open || typing(e) || e.altKey || e.ctrlKey || e.metaKey || document.querySelector('dialog[open]')) return;
  const k = e.key, map = { ' ': toggle, ArrowRight: () => jump(S.index + 1), ArrowLeft: () => jump(S.index - 1),
    PageDown: () => stepPage(1), PageUp: () => stepPage(-1), c: toggleCaptions, C: toggleCaptions, m: toggleSound,
    M: toggleSound, Escape: stop };
  if (!map[k]) return;
  if (k === ' ' && e.target && e.target.closest && e.target.closest('button')) return; // a focused button takes Space itself
  e.preventDefault(); e.stopPropagation();
  map[k]();
}
function onVisible() {
  if (!S.open) return;
  if (document.hidden) { if (S.playing) { pause(); S.hiddenHold = true; } return; }
  if (S.hiddenHold) { S.hiddenHold = false; resume(); }
}
function listen() {
  if (S.keys) return;
  S.keys = true;
  window.addEventListener('keydown', onKey, true); // the player's keys first, while it is open
  document.addEventListener('visibilitychange', onVisible);
  window.addEventListener('pagehide', () => { if (S.open) { const V = voice(); if (V) V.stop(); } });
}

// ---- open and stop -------------------------------------------------------------------------------------------------------
function info() {
  const minutes = Math.max(1, Math.round(S.lines.reduce((a, l) => a + wordsIn(l.text), 0) / WPM));
  return { title: S.title, pages: S.list, minutes };
}
function failWords(e) {
  if (e && GONE.has(e.status)) return WORDS.gone;
  return e && e.status === 404 ? WORDS.missing : WORDS.down;
}
async function cloudVoice() {
  if (S.cloud === null) {
    try { const s = obj(await book().api('/v1/book/settings')); S.cloud = !!s && s.show_voice === 'cloud'; } catch (_) { S.cloud = false; }
  }
  if (S.view && S.open) S.view.cloudNote(S.cloud);
}
/** Open a chapter in the player: true once it plays, false when it can't (the player then says why, with Back to reading). */
async function open(chapterId, options) {
  const id = String(chapterId || ''), opts = obj(options) || {};
  const root = $('brPlayer'), B = book();
  if (!CHAPTER.test(id) || !root || !B) return false;
  const V = voice();
  if (V) V.start('browser'); // from the Play tap (a user gesture): chapters always use the browser's voice
  if (S.open) halt();
  const my = ++S.gen;
  S.opener = document.activeElement; S.open = true; S.id = id; S.state = 'loading'; S.playing = false; S.index = 0;
  S.view = mount(root, { toggle, prevLine: () => jump(S.index - 1), nextLine: () => jump(S.index + 1), prevPage: () => stepPage(-1),
    nextPage: () => stepPage(1), cc: toggleCaptions, sound: toggleSound, speed: cycleSpeed, stop, page: (i) => { if (S.list[i]) jump(S.first[S.list[i].id]); }, again });
  S.view.loading();
  root.hidden = false;
  const app = $('bookRead');
  if (app) app.dataset.mode = 'player';
  listen();
  let got;
  try { got = obj(await B.api('/v1/book/chapters/' + id + query())) || {}; } catch (e) {
    if (my === S.gen) { S.state = 'failed'; S.view.fail(failWords(e)); }
    return false;
  }
  if (my !== S.gen) return false;
  S.release = RID.test(got.release || '') ? got.release : '';
  S.title = txt(got.title, 120);
  S.lines = (Array.isArray(got.lines) ? got.lines : []).map(lineOf).filter(Boolean);
  const titles = {};
  (Array.isArray(got.pages) ? got.pages : []).map(obj).filter((p) => p && PAGE.test(p.id || '')).forEach((p) => { titles[p.id] = txt(p.title, 120); });
  if (!S.lines.length) { S.state = 'failed'; S.view.fail(WORDS.silent); return false; }
  S.first = {}; S.list = [];
  S.lines.forEach((l, i) => {
    if (!(l.page in S.first)) { S.first[l.page] = i; S.list.push({ id: l.page, title: titles[l.page] || l.page, lines: 0, words: 0 }); }
    const p = S.list[S.list.length - 1]; p.lines += 1; p.words += wordsIn(l.text);
  });
  S.list.forEach((p) => { p.minutes = Math.round(p.words / WPM); });
  const ids = S.list.map((p) => p.id), at = (pid) => S.release + ':' + pid, fresh = ids.filter((pid) => !KEPT.has(at(pid)));
  const answers = await Promise.allSettled(fresh.map((pid) => B.api('/v1/book/pages/' + pid + query())));
  if (my !== S.gen) return false;
  answers.forEach((r, k) => { const p = r.status === 'fulfilled' ? pageOf(r.value, fresh[k]) : null; if (p) KEPT.set(at(fresh[k]), p); });
  while (KEPT.size > KEEP) KEPT.delete(KEPT.keys().next().value);
  S.pages = {};
  ids.forEach((pid, k) => { const p = KEPT.get(at(pid)); if (p) { S.pages[pid] = p; if (p.title) S.list[k].title = p.title; } });
  S.est = S.lines.map(lineMs);
  S.view.ready(info());
  S.fx = createFx(S.view.stage, { root, steps: S.view.steps });
  S.plan = S.fx.load({ chapter: id, title: S.title, lines: S.lines, pages: S.pages, titles });
  cloudVoice();
  if (V) V.mute(!S.sound);
  const want = Number.isInteger(opts.line) ? S.lines.findIndex((l) => l.n >= opts.line) : 0;
  S.state = 'ready';
  S.view.buttons.play.focus();
  play(want > 0 ? want : 0);
  return true;
}
/** Close the player quietly (no event): the voice stops, the engine and the DOM go. */
function halt() {
  S.gen += 1; S.run += 1; S.playing = false; S.open = false; S.state = 'closed'; S.hiddenHold = false;
  tickOff(); release();
  const V = voice(); if (V) V.stop();
  if (S.fx) { S.fx.dispose(); S.fx = null; }
  const root = $('brPlayer');
  if (root) { root.textContent = ''; root.hidden = true; delete root.dataset.state; delete root.dataset.playing; }
  const app = $('bookRead');
  if (app) delete app.dataset.mode;
  S.view = null;
}
/** Stop: back to reading at the page being told. */
function stop() {
  if (!S.open) return;
  const l = S.lines[S.index], detail = { action: 'stop', chapter: S.id, page: l ? l.page : (S.list[0] ? S.list[0].id : ''),
    line: l ? l.n : 0, release: S.release };
  if (S.state === 'ready') remember();
  const back = S.opener;
  halt();
  document.dispatchEvent(new CustomEvent('jarvis:book-chapter', { detail }));
  const to = back && back.isConnected && back.offsetParent !== null ? back : $('brMain');
  if (to && typeof to.focus === 'function') to.focus();
}
function state() {
  const l = S.lines[S.index];
  return { open: S.open, chapter: S.open ? S.id : '', line: S.open && l ? l.n : 0, playing: S.playing, page: S.open && l ? l.page : '',
    status: S.state, rate: S.rate, sound: S.sound, captions: S.cc, fx: S.fx ? S.fx.state() : null };
}

window.JarvisBookChapter = Object.freeze({ open, stop, state, place });
export { open, place, state, stop };
