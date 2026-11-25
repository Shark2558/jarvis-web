// src/jarvis/api/static/console-book-read-page.js -- R6.4 D3 (docs/plans/r6-4-book-look.md): one page of the full book on
// /book/read, an ES module. drawPage(host, page, ctx) draws the approved mockup's page: the breadcrumb, the title, who
// wrote it and when with its reading time (words / 200), the chapter's Play card (only when the page's chapter is
// narrated), the sections (In plain words as the lead, the made-up Example in its callout with its tag, How it works with
// the flowchart (console-book-flow.js, as its figure()) and `backticked` words as code, What it costs with a rupee figure only
// when the text opens with a plain amount, When it fails as the amber list, the code's files in a closed "Where in the
// code"), then the previous and next page (the next chapter at a chapter's end). drawToc(host, ...) fills "On this page"
// and "In this chapter"; follow(main, toc, drawn) keeps the reader's section lit as the page scrolls (IntersectionObserver).
// Server words go in through textContent only. No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
import { normalFlow, renderFlow } from './console-book-flow.js';
import { PARTS, amount, blocks, day, icon, inline, items, minutesOf, mk, whereIs } from './console-book-read-data.js';

const NOT_WRITTEN = 'Not written yet', BY = 'Written by the Workshop', TAG = 'Made-up example';
const EXAMPLE_MARK = 'Example (made up)'; // writer.model.EXAMPLE_MARK
const LIT_AT = 0.3; // a section is the reader's once its top passes 30% of the page's height
const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);

/** The chapter's length as words: "5 pages, about 9 minutes". */
export function chapterWords(ch) {
  const parts = [plural(ch.pages.length, 'page', 'pages')];
  if (ch.minutes) parts.push('about ' + plural(ch.minutes, 'minute', 'minutes'));
  return parts.join(', ');
}

function paragraphs(host, text, lead) {
  let first = !!lead;
  blocks(text).forEach((b) => {
    if (b.list) {
      const ul = mk('ul', 'bk-list');
      b.list.forEach((l) => ul.append(inline(mk('li'), l)));
      host.append(ul);
      return;
    }
    host.append(inline(mk('p', 'bk-p' + (first ? ' bk-lead' : '')), b.p));
    first = false;
  });
}
function heading(id, words) {
  const h = mk('h2', 'bk-h2', words);
  h.id = 'brH-' + id;
  return h;
}
function section(id, words) {
  const s = mk('section', 'bk-sec');
  s.id = 'brSec-' + id; s.dataset.sec = id;
  s.setAttribute('aria-labelledby', 'brH-' + id);
  s.append(heading(id, words));
  return s;
}
/** "Where in the code \u00b7 13 files": a closed disclosure of the files as code chips. */
function codeRefs(code) {
  const refs = code ? (code.refs.length ? code.refs : (code.text.match(/`([^`\n]{1,200})`/g) || []).map((r) => r.slice(1, -1))) : [];
  if (!refs.length) return null;
  const d = mk('details', 'bk-more'), sum = mk('summary');
  sum.append(icon('chev', 'bk-chev'), mk('span', '', 'Where in the code \u00b7 ' + plural(refs.length, 'file', 'files')));
  const ul = mk('ul', 'bk-refs');
  ul.setAttribute('aria-label', 'Files of code');
  refs.forEach((r) => ul.append(mk('li', '', r)));
  d.append(sum, ul);
  return d;
}
/** The chart's frame now; the chart once the page is in place: figure()'s own figure (caption, chart, key, steps), but
 *  put in the page first, so renderFlow lays it out once in its real width and its one fade runs. */
function flowchart(raw) {
  if (!raw) return null;
  const box = mk('div', 'bk-fig');
  box.fill = () => {
    try {
      const spec = normalFlow(raw);
      if (!spec) { box.remove(); return; }
      const fig = mk('figure', 'bk-flow');
      fig.append(mk('figcaption', 'bk-flowcap', spec.title));
      box.append(fig);
      renderFlow(spec, fig);
    } catch (_) { box.remove(); } // a chart never breaks a page
  };
  return box;
}
function costs(s) {
  const sec = section('costs', s.heading), a = amount(s.text);
  if (!a) { paragraphs(sec, s.text, false); return sec; }
  const row = mk('div', 'bk-cost'), tile = mk('span', 'n'), words = mk('div', 'bk-costw');
  tile.append(mk('b', '', a.value));
  if (a.unit) tile.append(mk('small', '', a.unit));
  paragraphs(words, s.text, false);
  row.append(tile, words); sec.append(row);
  return sec;
}
function fails(s) {
  const sec = section('fails', s.heading), ul = mk('ul', 'bk-fails');
  items(s.text).forEach((t) => { const li = mk('li'); li.append(icon('warn'), inline(mk('span'), t)); ul.append(li); });
  if (ul.childElementCount) sec.append(ul);
  return sec;
}
function example(s) {
  const sec = section('example', s.heading === EXAMPLE_MARK || !s.heading ? 'Example' : s.heading), box = mk('div', 'bk-ex');
  box.append(mk('span', 'bk-tag', TAG));
  paragraphs(box, s.text, false);
  sec.append(box);
  return sec;
}
/** The sections in order; "Where in the code" closes How it works (or stands alone when a page has no How it works). */
function sections(page) {
  const out = [], code = page.sections.find((s) => s.id === 'code'), refs = codeRefs(code);
  page.sections.forEach((s) => {
    if (s.id === 'code') return;
    const empty = !s.text.trim();
    if (s.id === 'how') {
      const fig = flowchart(page.flow);
      if (empty && !fig && !refs) return;
      const sec = section('how', s.heading || 'How it works');
      if (fig) sec.append(fig);
      paragraphs(sec, s.text, false);
      if (refs) sec.append(refs);
      out.push(sec);
      return;
    }
    if (empty) return;
    if (s.id === 'plain') { const sec = section('plain', s.heading || 'In plain words'); paragraphs(sec, s.text, true); out.push(sec); }
    else if (s.id === 'example') out.push(example(s));
    else if (s.id === 'costs') out.push(costs(s));
    else if (s.id === 'fails') out.push(fails(s));
  });
  if (refs && !out.some((s) => s.dataset.sec === 'how')) { const sec = section('code', 'Where in the code'); sec.append(refs); out.push(sec); }
  return out;
}

function crumb(book, page, at) {
  const c = mk('nav', 'bk-crumb');
  c.setAttribute('aria-label', 'Where this page is');
  const bits = [];
  if (at.chapter && at.chapter.kind === 'story') {
    const k = book.chapters.filter((x) => x.kind === 'story');
    bits.push(PARTS.plain, 'Chapter ' + (k.indexOf(at.chapter) + 1) + ' of ' + k.length);
  } else if (at.chapter) bits.push(PARTS.modules, at.chapter.title, 'Page ' + at.n + ' of ' + at.of);
  else bits.push(PARTS[page.part] || 'The book');
  bits.forEach((b, i) => { if (i) c.append(mk('span', 'sep', '\u203a')); c.append(mk('span', 'k', b)); });
  return c;
}
function metaLine(page) {
  const m = mk('div', 'bk-meta'), when = page.meta ? day(page.meta.on) : '';
  const code = page.sections.find((s) => s.id === 'code'), files = code ? code.refs.length : 0;
  const bits = [[page.meta ? BY + (when ? ' \u00b7 ' + when : '') : NOT_WRITTEN, ''], [minutesOf(page) + ' min read', '']];
  if (files) bits.push([plural(files, 'file', 'files') + ' of code', 'bk-wide']);
  bits.forEach(([t, cls], i) => { if (i) m.append(mk('span', 'sep' + (cls ? ' ' + cls : ''), '\u00b7')); m.append(mk('span', cls, t)); });
  return m;
}
/** The chapter's Play card: one tap starts the narrated chapter (builder B's player). */
function playCard(ch, ctx) {
  const card = mk('div', 'bk-play'), go = mk('button', 'pbtn'), words = mk('span', 'bk-playw');
  card.id = 'brPlay';
  go.type = 'button'; go.setAttribute('aria-label', 'Play the chapter ' + ch.title);
  go.append(icon('play'));
  go.addEventListener('click', () => ctx.onPlay(ch));
  words.append(mk('b', '', 'Play this chapter'),
    mk('small', '', ch.title + ' \u00b7 ' + chapterWords(ch) + ' \u00b7 narrated with captions \u00b7 your browser\u2019s voice, \u20b90'));
  const list = mk('button', 'bk-btn bk-chaplist', 'Chapter list');
  list.type = 'button';
  list.addEventListener('click', () => ctx.onChapterList(ch));
  const note = mk('p', 'bk-playnote');
  note.id = 'brPlayNote'; note.setAttribute('role', 'status'); note.hidden = true;
  card.append(go, words, list);
  const wrap = mk('div', 'bk-playwrap');
  wrap.append(card, note);
  return wrap;
}
function step(book, id, label, title, cls) {
  const a = mk('a', cls || '');
  a.href = '#' + id; a.dataset.page = id;
  a.append(mk('span', 'k', label), mk('b', '', title || (book.pages.get(id) || {}).title || id));
  return a;
}
function prevNext(book, at) {
  const nav = mk('nav', 'bk-pn');
  nav.setAttribute('aria-label', 'Previous and next');
  if (at.prevChapter) nav.append(step(book, at.prevChapter.pages[0], '\u2039 Previous chapter', at.prevChapter.title));
  else if (at.prev) nav.append(step(book, at.prev, '\u2039 Previous page'));
  else nav.append(mk('span'));
  if (at.nextChapter) nav.append(step(book, at.nextChapter.pages[0], 'Next chapter \u203a', at.nextChapter.title, 'next'));
  else if (at.next) nav.append(step(book, at.next, 'Next page \u203a', '', 'next'));
  return nav;
}

/** The page into `host` (#brPage). ctx: {book, onPlay(chapter), onChapterList(chapter)}. Returns {sections, play}. */
export function drawPage(host, page, ctx) {
  const at = whereIs(ctx.book, page.id), h1 = mk('h1', 'bk-h1', page.title);
  h1.id = 'brTitle'; h1.tabIndex = -1;
  const out = [crumb(ctx.book, page, at), h1, metaLine(page)];
  const ch = at.chapter && at.chapter.narrated ? at.chapter : null;
  const play = ch ? playCard(ch, ctx) : null;
  if (play) out.push(play);
  const drawn = sections(page);
  out.push(...drawn, prevNext(ctx.book, at));
  host.replaceChildren(...out);
  host.querySelectorAll('.bk-fig').forEach((box) => { if (box.fill) box.fill(); });
  host.setAttribute('aria-labelledby', 'brTitle');
  return { sections: drawn, play: play ? play.firstChild : null, chapter: ch, at };
}

function tocLink(href, words, on, current) {
  const li = mk('li'), a = mk('a', on ? 'on' : '', words);
  a.href = href;
  if (on) a.setAttribute('aria-current', current);
  li.append(a);
  return { li, a };
}
/** "On this page" (the sections, the reader's lit) and "In this chapter" (its pages, this one marked). */
export function drawToc(host, page, drawn, ctx) {
  const out = [], at = whereIs(ctx.book, page.id);
  if (drawn.sections.length) {
    const ol = mk('ol', 'bk-onpage');
    drawn.sections.forEach((s, i) => {
      const { li, a } = tocLink('#' + s.id, s.firstChild.textContent, i === 0, 'location');
      a.dataset.sec = s.dataset.sec;
      a.addEventListener('click', (e) => { e.preventDefault(); ctx.toSection(s); });
      ol.append(li);
    });
    out.push(mk('span', 'k', 'On this page'), ol);
  }
  if (at.chapter && at.chapter.pages.length > 1) {
    const ol = mk('ol', 'bk-chap');
    at.chapter.pages.forEach((id) => {
      const { li, a } = tocLink('#' + id, (ctx.book.pages.get(id) || {}).title || id, id === page.id, 'page');
      a.dataset.page = id; ol.append(li);
    });
    out.push(mk('span', 'k', 'In this chapter'), ol);
  }
  host.replaceChildren(...out);
}
function light(toc, id) {
  toc.querySelectorAll('.bk-onpage a').forEach((a) => {
    const on = a.dataset.sec === id;
    a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
  });
}
/** Keep "On this page" on the section being read as `main` scrolls; returns a stop function. */
export function follow(main, toc, drawn) {
  const secs = drawn.sections;
  if (!secs.length) return () => {};
  let last = '';
  const pick = () => {
    const top = main.getBoundingClientRect().top, line = top + main.clientHeight * LIT_AT;
    let at = secs[0];
    secs.forEach((s) => { if (s.getBoundingClientRect().top <= line) at = s; });
    if (main.scrollTop + main.clientHeight >= main.scrollHeight - 4) at = secs[secs.length - 1];
    if (at.dataset.sec !== last) { last = at.dataset.sec; light(toc, last); }
  };
  if (typeof IntersectionObserver !== 'function') { pick(); return () => {}; }
  // the band is the page's top 30%: a section enters or leaves it exactly when its top or its end crosses that line
  const io = new IntersectionObserver(pick, { root: main, rootMargin: '0px 0px -' + Math.round((1 - LIT_AT) * 100) + '% 0px', threshold: 0 });
  secs.forEach((s) => io.observe(s));
  const end = () => { if (main.scrollTop + main.clientHeight >= main.scrollHeight - 4) pick(); };
  main.addEventListener('scroll', end, { passive: true });
  pick();
  return () => { io.disconnect(); main.removeEventListener('scroll', end); };
}
