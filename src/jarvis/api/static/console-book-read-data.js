// src/jarvis/api/static/console-book-read-data.js -- R6.4 D3, D4 (docs/plans/r6-4-book-look.md): the full book reader's
// data, an ES module. What GET /v1/book/pages, /v1/book/pages/{id}, /v1/book/chapters and /v1/book/pages/search send,
// checked field by field (a field of the wrong type is dropped, never guessed); the contents (The story, Modules with
// their pages, Screens, Outside services) merged from the pages index and the chapters; the places this browser keeps
// (localStorage, ids only, every access in try/catch): "continue where I left off" in jarvis_book_place_v1, shared with
// the tour (console-book-tour.js keeps {release, scene}; the player keeps {chapter, line, heard_at}): read first and
// merge, never overwrite another part's fields, and another release's place of another part stays as it is; the read
// dots in jarvis_book_read_v1 (page ids per release, the last 3 releases). I1: the reader keeps {page, read_at} (when
// the owner last chose a page; ms), the player its heard_at, so Continue offers whichever came last. Small DOM helpers: textContent only, icons from
// constant paths. No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
export const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
export const PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/;
export const CHAPTER = /^(?:story|module)_[a-z0-9_]{1,40}$/;
export const RID = /^[0-9a-f]{7}$/;
const VER = /^v\d{1,3}\.\d{1,3}\.\d{1,4}$/, YMD = /^(\d{4})-(\d{2})-(\d{2})$/;
export const SECTIONS = ['plain', 'example', 'how', 'costs', 'fails', 'code'];
export const PLACE_KEY = 'jarvis_book_place_v1', READ_KEY = 'jarvis_book_read_v1';
const READ_RELEASES = 3, READ_IDS = 400, WORDS_A_MINUTE = 200;
export const KIND = Object.freeze({ chapter: 'Story', module: 'Module', card: 'Part', screen: 'Screen', service: 'Service' });
export const PARTS = Object.freeze({ plain: 'The story', modules: 'Modules', parts: 'Modules', screens: 'Screens', services: 'Outside services' });

export const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
export const arr = (v) => (Array.isArray(v) ? v : []);
export const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
const int = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);
export function mk(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text) n.textContent = text;
  return n;
}

// ---- icons: constant shapes only (the mockup's), built as SVG nodes ---------------------------------------------------
const SVG = 'http://www.w3.org/2000/svg';
const LINE = { fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
const ICONS = {
  search: [['circle', { cx: 9, cy: 9, r: 5.5 }], ['path', { d: 'm13.2 13.2 3.8 3.8' }]],
  play: [['path', { d: 'M6 4.2v11.6L15.5 10z', fill: 'currentColor', stroke: 'none' }]],
  close: [['path', { d: 'm5 5 10 10M15 5 5 15' }]],
  chev: [['path', { d: 'm8 6 4 4-4 4' }]],
  resume: [['path', { d: 'M4 10a6 6 0 1 0 2-4.5M4 4v3h3' }]],
  warn: [['path', { d: 'M10 3 2.5 16.5h15z' }], ['path', { d: 'M10 8v4M10 14.2v.1' }]],
  code: [['path', { d: 'm7 6-4 4 4 4M13 6l4 4-4 4' }]],
};
export function icon(name, cls) {
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('focusable', 'false');
  Object.keys(LINE).forEach((k) => s.setAttribute(k, LINE[k]));
  if (cls) s.setAttribute('class', cls);
  (ICONS[name] || []).forEach(([tag, attrs]) => {
    const e = document.createElementNS(SVG, tag);
    Object.keys(attrs).forEach((k) => e.setAttribute(k, String(attrs[k])));
    s.append(e);
  });
  return s;
}

// ---- shapes ----------------------------------------------------------------------------------------------------------
export function meta(v) {
  const m = obj(v);
  if (!m || !txt(m.written_by, 60)) return null;
  return { by: txt(m.written_by, 60), on: YMD.test(m.written_on || '') ? m.written_on : '',
    release: RID.test(m.release || '') ? m.release : '', version: VER.test(m.version || '') ? m.version : '' };
}
function row(v) {
  const p = obj(v);
  return p && PAGE.test(p.id || '') ? { id: p.id, kind: KIND[p.kind] ? p.kind : '', title: txt(p.title, 120) || p.id, meta: meta(p.written) } : null;
}
/** GET /v1/book/pages: {release, parts: [{id, title, chapters: [{id, title, pages: [row]}]}]} or null. */
export function normalIndex(raw) {
  const d = obj(raw);
  if (!d) return null;
  const parts = arr(d.parts).map(obj).filter(Boolean).map((p) => ({ id: txt(p.id, 20), title: txt(p.title, 60),
    chapters: arr(p.chapters).map(obj).filter(Boolean).map((c) => ({ id: txt(c.id, 60), title: txt(c.title, 120),
      pages: arr(c.pages).map(row).filter(Boolean) })).filter((c) => c.pages.length) }))
    .filter((p) => PARTS[p.id] && p.chapters.length);
  return parts.length ? { release: RID.test(d.release || '') ? d.release : '', parts } : null;
}
/** GET /v1/book/chapters' rows (I0 checked the envelope): [{id, title, kind, pages, minutes, narrated}]. */
export function normalChapters(list) {
  return arr(list).map(obj).filter(Boolean).filter((c) => CHAPTER.test(c.id || '')).map((c) => ({
    id: c.id, title: txt(c.title, 120) || c.id, kind: c.kind === 'story' ? 'story' : 'module',
    pages: arr(c.pages).filter((p) => typeof p === 'string' && PAGE.test(p)), minutes: int(c.minutes), narrated: c.narrated === true,
    lines: int(c.lines),
  })).filter((c) => c.pages.length);
}
/** GET /v1/book/pages/{id}: the page's sections in their order, who wrote it, its flowchart (checked by the flow module). */
export function normalPage(raw) {
  const p = obj(raw);
  if (!p || !PAGE.test(p.id || '')) return null;
  const by = {};
  arr(p.sections).map(obj).filter(Boolean).forEach((s) => { if (SECTIONS.includes(s.id) && !by[s.id]) by[s.id] = s; });
  const sections = SECTIONS.filter((id) => by[id]).map((id) => ({ id, heading: txt(by[id].heading, 60),
    text: typeof by[id].text === 'string' ? by[id].text.replace(INVISIBLE, '').slice(0, 2400) : '',
    refs: arr(by[id].refs).map((r) => txt(r, 200)).filter(Boolean).slice(0, 60) }));
  if (!sections.length) return null;
  return { id: p.id, kind: KIND[p.kind] ? p.kind : '', title: txt(p.title, 120) || p.id, part: PARTS[p.part] ? p.part : '',
    meta: meta(p.meta), sections, flow: obj(p.flow) };
}
/** GET /v1/book/pages/search: at most 20 hits, each snippet's marks as sorted, separate [start, end) ranges inside it. */
export function normalSearch(raw) {
  const d = obj(raw) || {};
  const results = arr(d.results).map(obj).filter(Boolean).filter((r) => PAGE.test(r.id || '')).slice(0, 20).map((r) => {
    const snippet = typeof r.snippet === 'string' ? r.snippet.replace(INVISIBLE, '').slice(0, 200) : '';
    let end = 0;
    const marks = arr(r.marks).filter((m) => Array.isArray(m) && m.length === 2 && Number.isInteger(m[0]) && Number.isInteger(m[1]))
      .map((m) => [m[0], m[1]]).sort((a, b) => a[0] - b[0])
      .filter(([a, b]) => { const ok = a >= end && a < b && b <= snippet.length; if (ok) end = b; return ok; });
    return { id: r.id, title: txt(r.title, 120) || r.id, kind: KIND[r.kind] ? r.kind : '', snippet, marks };
  });
  return { total: Math.max(int(d.total), results.length), results };
}

// ---- the book: contents, chapters, reading order ---------------------------------------------------------------------
function item(page, chapter) { return { page, chapter }; }
/** The contents rail's model from the index and the chapters. Every page of the index is somewhere: a page in no chapter
 *  stays readable (I0-NOTES section 2), under its own part or in "More pages". */
export function bookOf(index, chapterRows) {
  const pages = new Map(), chapters = [], chapterOf = new Map();
  index.parts.forEach((p) => p.chapters.forEach((c) => c.pages.forEach((r) => {
    if (!pages.has(r.id)) pages.set(r.id, Object.assign({ part: p.id }, r));
  })));
  normalChapters(chapterRows).forEach((c) => {
    const known = c.pages.filter((id) => pages.has(id) && !chapterOf.has(id));
    if (!known.length) return;
    const ch = Object.assign({}, c, { pages: known });
    chapters.push(ch); known.forEach((id) => chapterOf.set(id, ch));
  });
  const of = (part) => [...pages.values()].filter((p) => p.part === part);
  const groups = [];
  const story = of('plain').map((p) => item(p, chapterOf.get(p.id) || null));
  if (story.length) groups.push({ id: 'story', title: PARTS.plain, items: story });
  const modules = chapters.filter((c) => c.kind === 'module').map((c) => ({ chapter: c, pages: c.pages.map((id) => pages.get(id)) }));
  if (!modules.length) { // an index with no chapters: each module page with its cards (the index's own grouping)
    const cards = index.parts.find((p) => p.id === 'parts');
    of('modules').forEach((m) => {
      const mine = cards ? cards.chapters.find((c) => 'pg_module_' + c.id === m.id) : null;
      modules.push({ chapter: null, title: m.title, pages: [m, ...(mine ? mine.pages.map((r) => pages.get(r.id)) : [])] });
    });
  }
  if (modules.length) groups.push({ id: 'modules', title: PARTS.modules, items: modules });
  [['screens', PARTS.screens], ['services', PARTS.services]].forEach(([id, title]) => {
    const list = of(id).map((p) => item(p, chapterOf.get(p.id) || null));
    if (list.length) groups.push({ id, title, items: list });
  });
  const placed = new Set();
  groups.forEach((g) => g.items.forEach((x) => (x.pages || [x.page]).forEach((p) => placed.add(p.id))));
  const rest = [...pages.values()].filter((p) => !placed.has(p.id)).map((p) => item(p, null));
  if (rest.length) groups.push({ id: 'more', title: 'More pages', items: rest });
  const order = [];
  groups.forEach((g) => g.items.forEach((x) => (x.pages || [x.page]).forEach((p) => { if (!order.includes(p.id)) order.push(p.id); })));
  return { pages, chapters, chapterOf, groups, order, size: pages.size };
}
/** Where a page sits: its chapter (or null), its place in it, the chapter's neighbours; or the index order's neighbours. */
export function whereIs(book, id) {
  const ch = book.chapterOf.get(id) || null;
  if (ch) {
    const i = ch.pages.indexOf(id), k = book.chapters.indexOf(ch);
    return { chapter: ch, n: i + 1, of: ch.pages.length, prev: i > 0 ? ch.pages[i - 1] : '', next: i < ch.pages.length - 1 ? ch.pages[i + 1] : '',
      prevChapter: i === 0 && k > 0 ? book.chapters[k - 1] : null, nextChapter: i === ch.pages.length - 1 ? book.chapters[k + 1] || null : null };
  }
  const j = book.order.indexOf(id);
  return { chapter: null, n: 0, of: 0, prev: j > 0 ? book.order[j - 1] : '', next: j >= 0 ? book.order[j + 1] || '' : '', prevChapter: null, nextChapter: null };
}

// ---- words: dates, reading time, amounts, paragraphs, inline code ------------------------------------------------------
export function day(ymd) {
  const m = YMD.exec(ymd || '');
  if (!m) return '';
  try { return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(ymd + 'T12:00:00Z')); } catch (_) { return ''; }
}
export function minutesOf(page) {
  const words = page.sections.filter((s) => s.id !== 'code').reduce((n, s) => n + s.text.split(/\s+/).filter(Boolean).length, 0);
  return Math.max(1, Math.ceil(words / WORDS_A_MINUTE));
}
/** The costs' figure: only when the text opens with a plain rupee amount ("Rs 0: ...", "Rs 0 for the book"); never a cap. */
export function amount(text) {
  const m = /^\s*(?:about\s+|around\s+)?\u20b9\s?([0-9][0-9,]{0,12}(?:\.[0-9]{1,2})?)(?![0-9])(\s+(?:a|per)\s+(?:month|year|day))?/i.exec(text || '');
  return m ? { value: '\u20b9' + m[1], unit: m[2] ? m[2].trim() : '' } : null;
}
/** A section's blocks: blank lines part paragraphs; a block of "- " lines is a list. */
export function blocks(text) {
  const out = [];
  String(text || '').split(/\n\s*\n/).forEach((b) => {
    const lines = b.split('\n').map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return;
    if (lines.every((l) => /^[-*] /.test(l))) out.push({ list: lines.map((l) => l.slice(2).trim()) });
    else out.push({ p: lines.join(' ') });
  });
  return out;
}
/** "When it fails" as a list: its "- " items, or its sentences (a sentence ends at . ! ? before a capital or a quote). */
export function items(text) {
  const out = [];
  blocks(text).forEach((b) => {
    if (b.list) { out.push(...b.list); return; }
    out.push(...b.p.split(/(?<=[.!?]["\u201d\u2019]?)\s+(?=[A-Z"\u201c\u2018])/).map((s) => s.trim()).filter(Boolean));
  });
  return out;
}
/** `host` gets `text` with each `backticked` word as a <code> (text nodes only). */
export function inline(host, text) {
  String(text || '').split(/(`[^`\n]{1,200}`)/).forEach((part) => {
    if (!part) return;
    if (part.length > 2 && part[0] === '`' && part[part.length - 1] === '`') host.append(mk('code', '', part.slice(1, -1)));
    else host.append(document.createTextNode(part));
  });
  return host;
}

// ---- the places this browser keeps (ids only) ------------------------------------------------------------------------
function load(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* full or blocked: nothing kept */ }
}
export function place() { return obj(load(PLACE_KEY)) || {}; }
const MINE = ['release', 'page', 'read_at'];
const stamp = (v) => (Number.isFinite(v) && v >= 0 ? v : 0);
/** Remember the page read, keeping every other part's fields exactly as they were written. `chosen`: the owner opened
 *  it (a link, search, Continue, Back) -- not the address on arrival, nor the player's Stop -- so it is newer than the
 *  chapter listened to (read_at). */
export function remember(rid, pageId, chosen) {
  if (!RID.test(rid || '') || !PAGE.test(pageId || '')) return;
  const old = place(), others = Object.keys(old).filter((k) => !MINE.includes(k));
  if (others.length && old.release !== rid) return; // another part's place of another release stays as it is
  const next = {};
  others.forEach((k) => { next[k] = old[k]; });
  next.release = rid; next.page = pageId;
  const when = chosen ? Date.now() : (old.release === rid ? stamp(old.read_at) : 0);
  if (when) next.read_at = when;
  save(PLACE_KEY, next);
}
/** The page this browser left off at, for this release, or ''. */
export function offered(rid) {
  const p = place();
  return p.release === rid && PAGE.test(p.page || '') ? p.page : '';
}
/** The player's place in this release, if it kept one: {chapter, line} (read only; the player writes it). */
export function chapterPlace(rid) {
  const p = place();
  return p.release === rid && CHAPTER.test(p.chapter || '') && Number.isInteger(p.line) && p.line > 0 ? { chapter: p.chapter, line: p.line } : null;
}
/** I1: the player's place when the owner listened after the last page he chose to read, else null (Continue's chapter). */
export function heardPlace(rid) {
  const at = chapterPlace(rid), p = place();
  return at && stamp(p.heard_at) >= stamp(p.read_at) ? at : null;
}
function readList() {
  return arr(load(READ_KEY)).map(obj).filter((x) => x && RID.test(x.r || '')).map((x) => ({ r: x.r, ids: arr(x.ids).filter((i) => typeof i === 'string' && PAGE.test(i)) }));
}
export function readIds(rid) {
  const mine = readList().find((x) => x.r === rid);
  return new Set(mine ? mine.ids : []);
}
/** The page read, added to this release's list (and to `seen`, this visit's own, for a storage that is blocked). */
export function markRead(rid, id, seen) {
  if (!RID.test(rid || '') || !PAGE.test(id || '')) return new Set(seen || []);
  const list = readList(), mine = list.find((x) => x.r === rid) || { r: rid, ids: [] };
  const prior = [...new Set([...mine.ids, ...(seen || [])])];
  const ids = [...prior.filter((i) => i !== id), id].slice(-READ_IDS);
  save(READ_KEY, [{ r: rid, ids }, ...list.filter((x) => x.r !== rid)].slice(0, READ_RELEASES));
  return new Set(ids);
}
