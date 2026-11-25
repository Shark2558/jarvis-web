// src/jarvis/api/static/console-book-read-rail.js -- R6.4 D3 (docs/plans/r6-4-book-look.md): the full book's contents
// on /book/read, an ES module: The story (8 chapters), Modules (18, each opening to its pages: the module, its parts,
// and the screens and services the chapters place there), Screens and Outside services (each a group that opens), the
// page being read marked (aria-current="page"), a read dot on every page opened in this release (the word "read" for
// screen readers too, never the dot alone), each chapter's narrated minutes, and the Continue card from the remembered
// place. drawContents(host, book, opts) draws it (the laptop rail, or the phone's contents sheet: `prefix` keeps their
// ids apart); mark(host, book, current, read) moves the marks without drawing again, so focus and scroll stay.
// Every link is #<page id>: the reader follows the address, so Back and Forward work. textContent only; ASCII; <= 400.
import { icon, mk, whereIs } from './console-book-read-data.js';

const OPEN_BY_DEFAULT = new Set(['story', 'modules']); // Screens and Outside services start closed (D3)
const mins = (ch) => (ch && ch.minutes ? ch.minutes + ' min' : '');

function dot(read) {
  const d = mk('span', 'bk-dot' + (read ? ' read' : ''));
  d.setAttribute('aria-hidden', 'true');
  return d;
}
function pageLink(page, opts, minutes) {
  const a = mk('a');
  a.href = '#' + page.id; a.dataset.page = page.id;
  const read = opts.read.has(page.id);
  a.append(dot(read), mk('span', 't', page.title));
  const said = mk('span', 'sr-only bk-said', read ? ', read' : '');
  a.append(said);
  if (minutes) a.append(mk('span', 'm', minutes));
  return a;
}
function toggle(btn, list, on) {
  btn.setAttribute('aria-expanded', String(on));
  list.hidden = !on;
}
function disclosure(btn, list, onToggle) {
  btn.type = 'button';
  btn.setAttribute('aria-controls', list.id);
  btn.addEventListener('click', () => {
    const on = btn.getAttribute('aria-expanded') !== 'true';
    toggle(btn, list, on);
    if (onToggle) onToggle(on);
  });
}
function chapterRow(x, opts, n) {
  const li = mk('li', 'bk-chrow'), btn = mk('button', 'bk-chapbtn'), ul = mk('ul');
  const ch = x.chapter, title = ch ? ch.title : x.title, key = ch ? ch.id : 'm' + n;
  ul.id = opts.prefix + 'Ch-' + key;
  btn.dataset.chapter = key;
  btn.append(icon('chev', 'bk-chev'), mk('span', 't', title));
  if (mins(ch)) btn.append(mk('span', 'm', mins(ch)));
  x.pages.forEach((p) => { const i = mk('li'); i.append(pageLink(p, opts, '')); ul.append(i); });
  disclosure(btn, ul, (on) => { if (on) opts.opened.add(key); else opts.opened.delete(key); });
  toggle(btn, ul, opts.opened.has(key));
  li.append(btn, ul);
  return li;
}
/** The contents into `host`. opts: {prefix, read: Set, opened: Set (chapter keys and group ids open), current}. */
export function drawContents(host, book, opts) {
  const out = [];
  book.groups.forEach((g) => {
    const head = mk('button', 'bk-part'), ul = mk('ul', 'bk-nav'), count = g.items.length;
    ul.id = opts.prefix + 'Part-' + g.id;
    head.dataset.group = g.id;
    head.append(icon('chev', 'bk-chev'), mk('span', 'k', g.title), mk('span', 'k bk-count', String(count)));
    head.setAttribute('aria-label', g.title + ', ' + count);
    g.items.forEach((x, i) => {
      if (x.pages) { ul.append(chapterRow(x, opts, i)); return; }
      const li = mk('li');
      li.append(pageLink(x.page, opts, g.id === 'story' ? mins(x.chapter) : ''));
      ul.append(li);
    });
    if (!opts.opened.has('g:' + g.id) && !opts.closed.has('g:' + g.id) && OPEN_BY_DEFAULT.has(g.id)) opts.opened.add('g:' + g.id);
    disclosure(head, ul, (on) => {
      if (on) { opts.opened.add('g:' + g.id); opts.closed.delete('g:' + g.id); } else { opts.opened.delete('g:' + g.id); opts.closed.add('g:' + g.id); }
    });
    toggle(head, ul, opts.opened.has('g:' + g.id));
    out.push(head, ul);
  });
  host.replaceChildren(...out);
  mark(host, book, opts.current, opts.read, opts);
}
/** The page being read marked and its chapter and group opened; the read dots and words brought up to date. */
export function mark(host, book, current, read, opts) {
  host.querySelectorAll('a[data-page]').forEach((a) => {
    const id = a.dataset.page, on = id === current, was = a.classList.contains('now');
    a.classList.toggle('now', on);
    if (on) a.setAttribute('aria-current', 'page'); else if (was) a.removeAttribute('aria-current');
    const d = a.querySelector('.bk-dot'), said = a.querySelector('.bk-said'), isRead = read.has(id);
    if (d) d.classList.toggle('read', isRead);
    if (said) said.textContent = isRead ? ', read' : '';
  });
  const now = [...host.querySelectorAll('a.now')];
  now.forEach((a) => {
    const sub = a.closest('.bk-chrow');
    if (sub) {
      const btn = sub.querySelector('.bk-chapbtn'), ul = sub.querySelector('ul');
      if (btn && ul && ul.hidden) { toggle(btn, ul, true); if (opts) opts.opened.add(btn.dataset.chapter); }
      if (btn) btn.classList.add('open');
    }
    const group = a.closest('.bk-nav'), head = group && group.previousElementSibling;
    if (head && group.hidden && head.classList.contains('bk-part')) {
      toggle(head, group, true);
      if (opts) { opts.opened.add('g:' + head.dataset.group); opts.closed.delete('g:' + head.dataset.group); }
    }
  });
  host.querySelectorAll('.bk-chapbtn.open').forEach((b) => { if (!b.closest('.bk-chrow').querySelector('a.now')) b.classList.remove('open'); });
  return now[0] || null;
}
/** The Continue card: the page this browser left off at, while another page is open. */
export function drawContinue(el, book, pageId, current) {
  const page = pageId ? book.pages.get(pageId) : null;
  if (!el) return;
  if (!page || pageId === current) { el.hidden = true; el.replaceChildren(); return; }
  const at = whereIs(book, pageId), words = mk('span');
  el.href = '#' + pageId; el.dataset.page = pageId;
  words.append(mk('b', '', 'Continue: ' + page.title),
    mk('small', '', at.chapter && at.of > 1 ? at.chapter.title + ' \u00b7 page ' + at.n + ' of ' + at.of : 'Where you left off'));
  el.replaceChildren(icon('resume'), words);
  el.hidden = false;
}
/** Open the chapter's row (and its group) and give it focus: the Play card's "Chapter list". */
export function reveal(host, chapterId) {
  const btn = host.querySelector('.bk-chapbtn[data-chapter="' + chapterId + '"]');
  if (!btn) return false;
  const row = btn.closest('.bk-chrow'), ul = row.querySelector('ul'), group = row.closest('.bk-nav');
  if (group && group.hidden) toggle(group.previousElementSibling, group, true);
  if (ul.hidden) toggle(btn, ul, true);
  btn.focus({ preventScroll: true });
  if (btn.scrollIntoView) btn.scrollIntoView({ block: 'nearest' });
  return true;
}
