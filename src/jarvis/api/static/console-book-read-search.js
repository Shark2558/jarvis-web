// src/jarvis/api/static/console-book-read-search.js -- R6.4 D4 (docs/plans/r6-4-book-look.md): the full book's search
// box on /book/read, an ES module, over GET /v1/book/pages/search?q= (I0's route: owner only, its own limit, no AI, Rs 0).
// createSearch({input, list, api, open, gone, note, phone}) wires one box (the top bar's, or the phone sheet's): typing
// asks after 250 ms once there are at least 2 characters (an older answer never replaces a newer one); the answer is a
// listbox of at most 20 pages, each with its title, its kind and a snippet whose matched words are <mark>s built from the
// server's [start, end) ranges with text nodes (never HTML); "Showing N of M"; a helpful line when nothing matches.
// Keys (a combobox: focus stays in the box, aria-activedescendant names the lit option): Down and Up move, Enter opens
// the lit page or the first (never while an input method is composing), Esc closes the list, then clears the box.
// The counts are said once in the page's polite status line too. textContent only; ASCII source; <= 400 lines.
import { KIND, mk, normalSearch } from './console-book-read-data.js';

const WAIT_MS = 250, MIN = 2, MAX = 60;
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
let seq = 0;

function snippet(text, marks) {
  const p = mk('p');
  let at = 0;
  marks.forEach(([a, b]) => {
    if (a > at) p.append(document.createTextNode(text.slice(at, a)));
    p.append(mk('mark', '', text.slice(a, b)));
    at = b;
  });
  if (at < text.length) p.append(document.createTextNode(text.slice(at)));
  return p;
}
function said(q) { return '\u201c' + q + '\u201d'; }
function why(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  if (e && e.status === 429) return 'Too many searches in a minute. Wait a moment, then try again.';
  return 'Search can\u2019t be reached right now. Try again in a moment.';
}

/** One search box. Returns {close(), clear(), focus()}. */
export function createSearch(o) {
  const { input, list } = o, id = 'brQ' + (++seq);
  const S = { timer: 0, asked: 0, q: '', hits: [], lit: -1, ctl: null };
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-autocomplete', 'list');
  input.maxLength = MAX;

  function show(on) {
    list.hidden = !on;
    input.setAttribute('aria-expanded', String(on));
    if (!on) { S.lit = -1; input.removeAttribute('aria-activedescendant'); }
  }
  function light(i) {
    const opts = [...list.querySelectorAll('[role="option"]')];
    if (!opts.length) return;
    S.lit = (i + opts.length) % opts.length;
    opts.forEach((el, k) => { el.setAttribute('aria-selected', String(k === S.lit)); el.classList.toggle('on', k === S.lit); });
    input.setAttribute('aria-activedescendant', opts[S.lit].id);
    if (opts[S.lit].scrollIntoView) opts[S.lit].scrollIntoView({ block: 'nearest' });
  }
  function pick(hit) {
    if (!hit) return;
    show(false);
    o.open(hit.id, { from: 'search' });
  }
  function option(hit, i) {
    const el = mk('div', 'bk-res'), tt = mk('span', 'tt');
    el.id = id + '-' + i; el.setAttribute('role', 'option'); el.setAttribute('aria-selected', 'false'); el.dataset.page = hit.id;
    tt.append(mk('span', 'ti', hit.title));
    if (hit.kind) tt.append(mk('span', 'kind', KIND[hit.kind]));
    el.append(tt);
    if (hit.snippet) el.append(snippet(hit.snippet, hit.marks));
    el.addEventListener('mousedown', (e) => e.preventDefault()); // the box keeps its focus
    el.addEventListener('click', () => pick(hit));
    return el;
  }
  function head(words, hint) {
    const h = mk('div', 'head');
    h.setAttribute('aria-hidden', 'true');
    h.append(mk('span', 'k', words));
    if (hint && !o.phone()) h.append(mk('span', 'k', '\u2191\u2193 Enter'));
    return h;
  }
  function foot(words) {
    const f = mk('div', 'foot', words);
    f.setAttribute('aria-hidden', 'true');
    return f;
  }
  function draw(q, got) {
    S.hits = got.results;
    const n = got.results.length, total = got.total;
    if (!n) {
      const none = mk('div', 'bk-none');
      none.setAttribute('aria-hidden', 'true');
      none.append(mk('b', '', 'No page mentions ' + said(q) + '.'), mk('span', '', 'Try a shorter word, or open the contents.'));
      list.replaceChildren(none);
      show(true);
      o.note('No page mentions ' + said(q) + '. Try a shorter word, or open the contents.');
      return;
    }
    const words = total === 1 ? '1 page mentions ' + said(q) : total + ' pages mention ' + said(q);
    list.replaceChildren(head(words, true), ...got.results.map(option),
      foot('Showing ' + n + ' of ' + total + (o.phone() ? '' : ' \u00b7 Enter opens the first \u00b7 Esc closes')));
    show(true);
    o.note(words + '. Showing ' + n + ' of ' + total + '. Down arrow to choose, Enter to open.');
  }
  function fail(q, e) {
    if (o.gone(e)) return;
    const none = mk('div', 'bk-none');
    none.setAttribute('aria-hidden', 'true');
    none.append(mk('b', '', why(e)));
    S.hits = [];
    list.replaceChildren(none);
    show(true);
    o.note(why(e));
  }
  async function ask(q) {
    const mine = ++S.asked;
    if (S.ctl) S.ctl.abort();
    S.ctl = typeof AbortController === 'function' ? new AbortController() : null;
    try {
      const raw = await o.api('/v1/book/pages/search?q=' + encodeURIComponent(q), S.ctl ? { signal: S.ctl.signal } : {});
      if (mine !== S.asked) return;
      S.q = q; draw(q, normalSearch(raw));
    } catch (e) {
      if (mine !== S.asked || (e && e.name === 'AbortError')) return;
      S.q = q; fail(q, e);
    }
  }
  function typed() {
    clearTimeout(S.timer);
    const q = input.value.trim().replace(/\s+/g, ' ');
    if (q.length < MIN) { S.asked += 1; if (S.ctl) S.ctl.abort(); S.q = ''; S.hits = []; list.replaceChildren(); show(false); return; }
    if (q === S.q && list.childElementCount) { show(true); return; }
    S.timer = setTimeout(() => ask(q.slice(0, MAX)), WAIT_MS);
  }
  function clear() { input.value = ''; typed(); }
  input.addEventListener('input', typed);
  input.addEventListener('focus', () => { if (S.q && S.q === input.value.trim().replace(/\s+/g, ' ') && list.childElementCount) show(true); });
  input.addEventListener('keydown', (e) => {
    if (e.isComposing || e.keyCode === 229) return; // an input method is still composing: its Enter is not ours
    const open = !list.hidden, many = S.hits.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!many) return;
      e.preventDefault();
      if (!open) show(true);
      light(S.lit < 0 ? (e.key === 'ArrowDown' ? 0 : many - 1) : S.lit + (e.key === 'ArrowDown' ? 1 : -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(S.timer);
      const q = input.value.trim().replace(/\s+/g, ' ');
      if (q !== S.q && q.length >= MIN) { ask(q.slice(0, MAX)).then(() => { if (S.q === q) pick(S.hits[0]); }); return; }
      pick(S.hits[S.lit >= 0 ? S.lit : 0]);
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); e.stopPropagation(); show(false); } else if (input.value) { e.preventDefault(); e.stopPropagation(); clear(); }
    }
  });
  const box = o.box || input.parentElement;
  box.addEventListener('focusout', (e) => { if (!o.keepOpen && !(e.relatedTarget && box.contains(e.relatedTarget))) show(false); });
  return { close: () => show(false), clear, focus: () => { input.focus(); input.select(); }, open: () => !list.hidden };
}
