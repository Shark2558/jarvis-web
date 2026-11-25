// src/jarvis/api/static/console-book-read-app.js -- R6.4 D1-D4 (docs/plans/r6-4-book-look.md): the full book's reader on
// /book/read, an ES module started by console-book-read.js once I0's hand-off is ready (the owner's book token, the
// release, its chapters). startReader(deps) reads GET /v1/book/pages (the contents), then one page at a time from
// GET /v1/book/pages/{id} (kept for this visit, 30 at most: the pages share a limit of 60 a minute), and follows the
// address: #<page id> is the page read, so every link, Back and Forward, a reload and the player's Stop land on it.
// The laptop layout of the approved mockup (contents rail, the page, "On this page" from 1280 px); the phone's (860 px
// and under): the contents sheet #brSheet with its own search box, one column, and the Play bar #brMini once the
// page's Play card has scrolled away. Keys: "/" goes to search (on a phone, to the sheet's), Esc closes the results,
// then the sheet; arrows and Enter in the results. The Play card asks builder B's player:
// window.JarvisBookChapter.open(chapterId, {line, page}); when it is missing or says no, a polite note says so.
// A refused session (401, 403, 410) goes back to I0's closed page. textContent only; ASCII source; <= 400 lines.
import { PAGE, bookOf, chapterPlace, icon, markRead, mk, normalIndex, normalPage, offered, readIds, remember, txt } from './console-book-read-data.js';
import { chapterWords, drawPage, drawToc, follow } from './console-book-read-page.js';
import { drawContents, drawContinue, mark, reveal } from './console-book-read-rail.js';
import { createSearch } from './console-book-read-search.js';

const $ = (id) => document.getElementById(id);
const PHONE_Q = '(max-width: 860px)', KEEP = 30;
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const NO_PLAY = 'This chapter can\u2019t be played right now. The page is here to read, and Play may work later.';
const media = (q) => { try { return window.matchMedia(q); } catch (_) { return { matches: false, addEventListener() {} }; } };
const phoneQ = media(PHONE_Q), stillQ = media('(prefers-reduced-motion: reduce)');
const R = { deps: null, book: null, rid: '', current: '', cache: new Map(), read: new Set(), resume: '', seq: 0, drawn: null,
  rail: { prefix: 'br', opened: new Set(), closed: new Set() }, sheet: { prefix: 'brS', opened: new Set(), closed: new Set() },
  stop: null, mini: null, sheetBuilt: false, searches: [] };
const isPhone = () => !!phoneQ.matches;
const smooth = () => (stillQ.matches || document.documentElement.dataset.motion === 'off' || document.documentElement.dataset.motion === 'calm' ? 'auto' : 'smooth');
const playing = () => ($('bookRead') || {}).dataset && $('bookRead').dataset.mode === 'player';

function note(words) {
  const n = $('brNote');
  if (!n) return;
  n.textContent = '';
  if (words) setTimeout(() => { n.textContent = words; }, 30); // a fresh node change, so the same words are said again
}
function wordsOf(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  if (e && e.status === 429) return 'Too many pages opened in a minute. Wait a moment, then open it again.';
  if (e && e.status === 404) return 'That page isn\u2019t in this release.';
  const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
  return m && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'Couldn\u2019t open that page. Try again in a moment.';
}
/** A refused session goes to I0's closed page; true when it did. */
const gone = (e) => !!(e && [401, 403, 410].includes(e.status) && R.deps.gone(e));

// ---- the address is the page -------------------------------------------------------------------------------------------
function go(id) {
  if (!PAGE.test(id || '')) return;
  if (location.hash === '#' + id) open(id); else location.hash = id;
}
function fromHash() {
  const id = location.hash.slice(1);
  return PAGE.test(id) && R.book && R.book.pages.has(id) ? id : '';
}

// ---- one page ----------------------------------------------------------------------------------------------------------
function busy(on) { const m = $('brMain'); if (m) m.setAttribute('aria-busy', String(on)); }
async function open(id, o = {}) {
  if (!R.book || !R.book.pages.has(id)) { note('That page isn\u2019t in this book.'); return false; }
  const mine = ++R.seq;
  R.current = id; marks();
  let page = R.cache.get(id);
  if (!page) {
    busy(true);
    try {
      page = normalPage(await R.deps.api('/v1/book/pages/' + id));
      if (!page) throw new Error('That page came back in a shape this page doesn\u2019t know.');
    } catch (e) {
      if (mine !== R.seq) return false;
      busy(false);
      if (!gone(e)) failed(id, wordsOf(e));
      return false;
    }
    if (mine !== R.seq) return false;
    R.cache.set(id, page);
    if (R.cache.size > KEEP) R.cache.delete(R.cache.keys().next().value);
  }
  busy(false);
  draw(page, o);
  return true;
}
function failed(id, words) {
  const box = mk('div', 'bk-err'), again = mk('button', 'bk-btn', 'Try again');
  box.setAttribute('role', 'alert');
  again.type = 'button';
  again.addEventListener('click', () => open(id));
  box.append(mk('p', '', words), again);
  $('brPage').replaceChildren(box);
  $('brToc').replaceChildren();
  stopMini();
}
function draw(page, o = {}) {
  const a = document.activeElement, sheet = $('brSheet');
  const kept = a && a !== document.body && ($('brRail').contains(a) || $('brToc').contains(a)) ? a : null;
  const drawn = drawPage($('brPage'), page, { book: R.book, onPlay: play, onChapterList: chapterList });
  R.drawn = drawn;
  drawToc($('brToc'), page, drawn, { book: R.book, toSection });
  if (R.stop) R.stop();
  R.stop = follow($('brMain'), $('brToc'), drawn);
  $('brMain').scrollTop = 0;
  R.read = markRead(R.rid, page.id, R.read);
  remember(R.rid, page.id);
  if (R.resume === page.id) R.resume = '';
  marks();
  miniBar(drawn);
  document.title = page.title + ' \u00b7 JARVIS Build book';
  const fromSheet = !!(sheet && sheet.open);
  if (fromSheet) sheet.close();
  if (o.initial) return; // the first page: the focus stays at the top of the page, so Tab starts at the top bar
  if (fromSheet || !kept || !kept.isConnected || kept.closest('[hidden]')) $('brTitle').focus({ preventScroll: true });
  else note('Opened ' + page.title + '.');
}
function toSection(sec) {
  sec.scrollIntoView({ behavior: smooth(), block: 'start' });
  const h = sec.querySelector('.bk-h2');
  if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
}
/** The marks of the page being read, in the rail and the sheet, and both Continue cards. */
function marks() {
  if (!R.book) return;
  const now = mark($('brContents'), R.book, R.current, R.read, R.rail);
  if (now && !isPhone() && now.scrollIntoView && !$('brRail').contains(document.activeElement)) now.scrollIntoView({ block: 'nearest' });
  drawContinue($('brContinue'), R.book, R.resume, R.current);
  if (R.sheetBuilt) {
    mark($('brSheetNav'), R.book, R.current, R.read, R.sheet);
    drawContinue($('brSheetContinue'), R.book, R.resume, R.current);
  }
}

// ---- Play: builder B's player -------------------------------------------------------------------------------------------
async function play(ch) {
  const P = window.JarvisBookChapter, at = chapterPlace(R.rid), line = at && at.chapter === ch.id ? at.line : undefined;
  let ok = false;
  try { ok = !!(P && typeof P.open === 'function') && (await P.open(ch.id, { line, page: R.current })) === true; } catch (_) { ok = false; }
  const n = $('brPlayNote');
  if (n) { n.hidden = ok; n.textContent = ok ? '' : NO_PLAY; }
  if (!ok) note(NO_PLAY);
}
function chapterList(ch) {
  if (isPhone()) { openSheet(false); reveal($('brSheetNav'), ch.id); return; }
  reveal($('brContents'), ch.id);
}
function stopMini() {
  if (R.mini) R.mini.disconnect();
  R.mini = null;
  const m = $('brMini');
  if (m) { m.hidden = true; m.replaceChildren(); }
}
/** The phone's Play bar: shown once the page's Play card has scrolled up and out of sight. */
function miniBar(drawn) {
  stopMini();
  const m = $('brMini'), ch = drawn.chapter;
  if (!m || !drawn.play || !ch || typeof IntersectionObserver !== 'function') return;
  const go = mk('button', 'pbtn'), words = mk('span');
  go.type = 'button'; go.setAttribute('aria-label', 'Play the chapter ' + ch.title);
  go.append(icon('play'));
  go.addEventListener('click', () => play(ch));
  words.append(mk('b', '', 'Play this chapter'), mk('small', '', ch.title + ' \u00b7 ' + chapterWords(ch) + ' \u00b7 \u20b90'));
  m.replaceChildren(go, words);
  m.setAttribute('role', 'region'); m.setAttribute('aria-label', 'Play this chapter');
  R.mini = new IntersectionObserver(([e]) => {
    const above = !e.isIntersecting && e.rootBounds && e.boundingClientRect.bottom <= e.rootBounds.top + 1;
    m.hidden = !(above && isPhone());
  }, { root: $('brMain'), threshold: 0 });
  R.mini.observe(drawn.play);
}

// ---- the phone's contents sheet -----------------------------------------------------------------------------------------
function buildSheet() {
  const d = $('brSheet');
  if (R.sheetBuilt || !d) return;
  const head = mk('div', 'bk-shead'), shut = mk('button', 'bk-btn icon');
  shut.type = 'button'; shut.setAttribute('aria-label', 'Close the contents');
  shut.append(icon('close'));
  shut.addEventListener('click', () => d.close());
  head.append(mk('span', 'bk-grab'), mk('h2', 'k', 'Contents'), shut);
  const box = mk('div', 'bk-search bk-ssearch'), input = mk('input'), list = mk('div', 'bk-results');
  box.setAttribute('role', 'search');
  input.id = 'brSheetSearch'; input.type = 'search'; input.setAttribute('role', 'combobox'); input.autocomplete = 'off';
  input.spellcheck = false; input.placeholder = $('brSearch').placeholder; input.setAttribute('aria-label', 'Search the book');
  list.id = 'brSheetResults'; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', 'Search results'); list.hidden = true;
  box.append(icon('search', 'ic'), input, list);
  const cont = mk('a', 'bk-cont'), nav = mk('nav', 'bk-snav');
  cont.id = 'brSheetContinue'; cont.hidden = true;
  nav.id = 'brSheetNav'; nav.setAttribute('aria-label', 'Contents');
  d.replaceChildren(head, box, cont, nav);
  R.searches.push(createSearch({ input, list, box, api: R.deps.api, open: go, gone, note, phone: () => true, keepOpen: true }));
  drawContents(nav, R.book, Object.assign(R.sheet, { read: R.read, current: R.current }));
  d.addEventListener('click', (e) => { // a tap on the dimmed page around the sheet closes it
    if (e.target !== d) return;
    const r = d.getBoundingClientRect();
    if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) d.close();
  });
  d.addEventListener('close', () => { const m = $('brMenu'); if (m && isPhone() && !$('brMain').contains(document.activeElement)) m.focus(); });
  R.sheetBuilt = true;
}
function openSheet(toSearch) {
  const d = $('brSheet');
  if (!d || !R.book) return;
  buildSheet(); marks();
  if (!d.open) { try { d.showModal(); } catch (_) { d.setAttribute('open', ''); } }
  const now = $('brSheetNav').querySelector('a.now');
  if (toSearch) $('brSheetSearch').focus();
  else if (now) { now.focus({ preventScroll: true }); now.scrollIntoView({ block: 'center' }); }
}

// ---- keys ----------------------------------------------------------------------------------------------------------------
const typing = (t) => !!(t && t.closest && t.closest('input, textarea, select, [contenteditable="true"]'));
function onKey(e) {
  if (e.key !== '/' || e.altKey || e.ctrlKey || e.metaKey || typing(e.target) || playing()) return;
  if (document.querySelector('dialog[open]:not(#brSheet)')) return;
  e.preventDefault();
  if (isPhone()) openSheet(true); else R.searches[0].focus();
}

// ---- start --------------------------------------------------------------------------------------------------------------
function chip(index) {
  const c = $('brRelease');
  const v = [...R.book.pages.values()].map((p) => p.meta).find((m) => m && m.release === R.rid && m.version);
  if (c && R.rid) c.textContent = (v ? v.version + ' \u00b7 ' : '') + R.rid;
  return index;
}
function empty(words) {
  const p = $('brPage'), box = mk('div', 'bk-err');
  box.append(mk('p', '', words));
  p.replaceChildren(box);
  $('brContents').replaceChildren(mk('p', 'bk-wait', 'No contents.'));
}
/** deps: {api, release, chapters, gone(e) -> bool}. Draws the contents and opens the page in the address, or the first. */
export async function startReader(deps) {
  R.deps = deps; R.rid = deps.release || '';
  R.read = readIds(R.rid); R.resume = offered(R.rid);
  $('brPage').replaceChildren(mk('p', 'bk-wait', 'Opening the book\u2026'));
  $('brContents').replaceChildren(mk('p', 'bk-wait', 'Reading the contents\u2026'));
  R.searches.push(createSearch({ input: $('brSearch'), list: $('brResults'), box: $('brSearchBox'), api: deps.api, open: go, gone, note, phone: isPhone }));
  document.addEventListener('keydown', onKey);
  const menu = $('brMenu'), find = $('brFind');
  if (menu) menu.addEventListener('click', () => openSheet(false));
  if (find) find.addEventListener('click', () => openSheet(true));
  let index = null;
  try { index = normalIndex(await deps.api('/v1/book/pages')); } catch (e) {
    if (!gone(e)) empty(e && e.status === 404 && txt(e.message, 300) ? txt(e.message, 300) : wordsOf(e));
    return false;
  }
  if (!index) { empty('This release has no full book to read.'); return false; }
  if (!R.rid) R.rid = index.release;
  R.book = bookOf(index, deps.chapters);
  chip(index);
  $('brSearch').placeholder = 'Search ' + R.book.size + ' pages';
  drawContents($('brContents'), R.book, Object.assign(R.rail, { read: R.read, current: '' }));
  window.addEventListener('hashchange', () => { const id = fromHash(); if (id && id !== R.current) open(id); });
  phoneQ.addEventListener('change', () => { if (R.drawn) miniBar(R.drawn); if (!isPhone() && $('brSheet').open) $('brSheet').close(); });
  const first = fromHash() || R.book.order[0];
  if (location.hash !== '#' + first) history.replaceState(null, '', '#' + first);
  await open(first, { initial: true });
  return true;
}
export { go as openPage };
export const currentPage = () => R.current;
