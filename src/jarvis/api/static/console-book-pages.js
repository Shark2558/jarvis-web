// src/jarvis/api/static/console-book-pages.js -- R6.3 D14 (docs/plans/r6-3-book-content.md): the Full book in the Book
// panel's reader (parts as .dsc disclosures, chapters as .bsec rows, a page's six sections with plain and example open,
// who wrote it, its references as code chips, older kept releases through the existing picker) and "continue where I
// left off" (localStorage jarvis_book_place_v1 {release, page}, ids only, owner only; another part's place is kept).
// console-book.js loads it ONCE at the panel's first open and calls mount(host, deps): `host` sits under the reader of an
// open OWNER session; deps = { api, booked, ask, say, render, token(), release() }. The panel re-renders by itself, so
// this module watches its host: it reads the index again when the session or the release read changes.
// Also page(host, raw) (a page's meta line and sections, for the writer's trial pages) and more(node) (the reader's G4
// line "+N more in the full book" under its limitations, from the index's `limitations`).
// Routes: GET /v1/book/pages?release=, GET /v1/book/pages/{id}?release= (X-Jarvis-Book). A refusal (a guest's 403, a
// release without pages) draws nothing. No build step; CSP script-src 'self'; textContent only; ASCII; <= 400 lines.
(() => {
  'use strict';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const PLACE = 'jarvis_book_place_v1';
  const PAGE = /^pg_(?:chapter|module|card|screen|service)_[a-z0-9_]{1,40}$/, RID = /^[0-9a-f]{7}$/, VER = /^v\d{1,3}\.\d{1,3}\.\d{1,4}$/;
  const SECTIONS = ['plain', 'example', 'how', 'costs', 'fails', 'code'], OPEN = { plain: true, example: true };
  const NOT_WRITTEN = 'Not written by AI yet', CHANGED = 'Changed in this release: waiting for your Update'; // writer.model
  const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const SVG = 'http://www.w3.org/2000/svg';
  let D = null, H = null, key = '', index = null, reading = null, note = '', seq = 0, gen = 0;
  let shownMore = []; // the reader's G4 lines, filled when the index is here
  const opened = {}; // part id -> its disclosure open (kept across repaints)

  // ---- shapes: what the routes send, checked field by field ----------------------------------------
  function meta(v) {
    const m = obj(v);
    if (!m || !txt(m.model, 80)) return null;
    return { label: txt(m.brain_label, 60) || txt(m.brain, 40), model: txt(m.model, 80), version: VER.test(m.version || '') ? m.version : '',
      release: RID.test(m.release || '') ? m.release : '', at: txt(m.written_at, 40) };
  }
  function row(v) {
    const p = obj(v);
    return p && PAGE.test(p.id || '') ? { id: p.id, title: txt(p.title, 120) || p.id, meta: meta(p.written), changed: p.changed === true } : null;
  }
  function normalIndex(raw) {
    const d = obj(raw);
    if (!d) return null;
    const parts = arr(d.parts).map(obj).filter(Boolean).map((p) => ({ id: txt(p.id, 20), title: txt(p.title, 60),
      chapters: arr(p.chapters).map(obj).filter(Boolean).map((c) => ({ id: txt(c.id, 60), title: txt(c.title, 120), pages: arr(c.pages).map(row).filter(Boolean) }))
        .filter((c) => c.pages.length) })).filter((p) => p.id && p.chapters.length);
    const lim = obj(d.limitations) || {};
    return parts.length ? { parts, shown: num(lim.shown), total: num(lim.total) } : null;
  }
  function normalPage(raw) {
    const p = obj(raw);
    if (!p || !PAGE.test(p.id || '')) return null;
    const by = {};
    arr(p.sections).map(obj).filter(Boolean).forEach((s) => { if (SECTIONS.includes(s.id)) by[s.id] = s; });
    const sections = SECTIONS.filter((id) => by[id]).map((id) => ({ id, heading: txt(by[id].heading, 60) || id,
      text: typeof by[id].text === 'string' ? by[id].text.replace(INVISIBLE, '').slice(0, 2400) : '', refs: arr(by[id].refs).map((r) => txt(r, 200)).filter(Boolean) }));
    return sections.length ? { id: p.id, title: txt(p.title, 120) || p.id, meta: meta(p.meta), changed: p.changed === true, sections } : null;
  }
  const pages = () => (index ? index.parts.flatMap((p) => p.chapters.flatMap((c) => c.pages)) : []);
  const find = (id) => pages().find((p) => p.id === id) || null;

  // ---- pieces ------------------------------------------------------------------------------------
  function chevron() {
    const s = document.createElementNS(SVG, 'svg'), p = document.createElementNS(SVG, 'path');
    s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('aria-hidden', 'true');
    s.setAttribute('class', 'dchev'); p.setAttribute('d', 'm6 8 4 4 4-4'); s.append(p); return s;
  }
  /** The reader's disclosure (.bset / .dsc / .dbody): its body is built when first opened. */
  function disclosure(label, summary, build, open, toggled) {
    const wrap = mk('div', 'bset bk-sec'), id = 'bkPg' + (++seq);
    const btn = mk('button', 'dsc'); btn.type = 'button'; btn.setAttribute('aria-controls', id);
    btn.append(mk('span', 'dl', label), chevron(), mk('span', 'dsum', summary));
    const body = mk('div', 'dbody'); body.id = id;
    let built = false;
    const set = (on) => {
      btn.setAttribute('aria-expanded', String(on)); body.hidden = !on;
      if (on && !built) { built = true; build(body); }
    };
    btn.addEventListener('click', () => { const on = btn.getAttribute('aria-expanded') !== 'true'; set(on); if (toggled) toggled(on); });
    set(!!open); wrap.append(btn, body); return wrap;
  }
  function button(label, kind, fn) {
    const b = mk('button', 'btn lift' + (kind ? ' ' + kind : ''), label); b.type = 'button'; b.addEventListener('click', fn); return b;
  }
  function day(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(d); } catch (_) { return ''; }
  }
  /** "Written by Claude (balanced tier, claude-sonnet-5-5) for v6.3.0 on 24 Nov 2026", or "Not written by AI yet". */
  function writtenBy(m, rid) {
    if (!m) return NOT_WRITTEN;
    const when = day(m.at), forRel = m.version || m.release || rid;
    return 'Written by ' + m.label + ' (balanced tier, ' + m.model + ')' + (forRel ? ' for ' + forRel : '') + (when ? ' on ' + when : '');
  }
  /** A section's words: blank lines part paragraphs; a block of "- " lines is a list. */
  function words(body, text) {
    text.split(/\n\s*\n/).forEach((block) => {
      const lines = block.split('\n').map((l) => txt(l, 2400)).filter(Boolean);
      if (!lines.length) return;
      if (lines.every((l) => /^[-*] /.test(l))) {
        const ul = mk('ul', 'blines'); lines.forEach((l) => ul.append(mk('li', '', l.slice(2)))); body.append(ul);
      } else body.append(mk('p', 'snote', lines.join(' ')));
    });
  }
  function refs(body, list) {
    if (!list.length) return;
    const ul = mk('ul', 'bchips'); ul.setAttribute('aria-label', 'Where in the code');
    list.forEach((r) => ul.append(mk('li', 'bchip', r))); body.append(ul);
  }
  /** One page: who wrote it, the changed label, its six sections (plain and example open). */
  function drawPage(box, p, rid) {
    box.append(mk('p', 'bfine', writtenBy(p.meta, rid)));
    if (p.changed) box.append(mk('p', 'bfine', CHANGED));
    p.sections.forEach((s) => box.append(disclosure(s.heading, '', (body) => {
      words(body, s.text); refs(body, s.refs);
      if (!body.childElementCount) body.append(mk('p', 'bempty', 'Nothing here yet.'));
    }, !!OPEN[s.id])));
  }

  // ---- continue where I left off (ids only). The key is shared with the tour (console-book-tour.js keeps
  // {release, scene} there): read first and merge, never overwrite another part's fields. ------------------
  function place() {
    try { return obj(JSON.parse(localStorage.getItem(PLACE) || 'null')) || {}; } catch (_) { return {}; }
  }
  function remember(rid, pageId) {
    const old = place(), others = Object.keys(old).filter((k) => k !== 'page' && k !== 'release');
    if (others.length && old.release !== rid) return; // the tour's place of another release stays as it is
    const next = {};
    others.forEach((k) => { next[k] = old[k]; }); // the tour's fields, exactly as it wrote them
    next.release = rid; next.page = pageId;
    try { localStorage.setItem(PLACE, JSON.stringify(next)); } catch (_) { /* full or blocked: nothing kept */ }
  }
  function offered(rid) {
    const p = place();
    return !reading && p.release === rid && PAGE.test(p.page || '') ? find(p.page) : null;
  }

  // ---- views -------------------------------------------------------------------------------------
  const rel = () => { const r = D.release(); return RID.test(r || '') ? r : ''; };
  const query = () => (rel() ? '?release=' + rel() : '');
  function head(label, action) {
    const h = mk('div', 'rhead bk-rhead'); h.append(mk('span', 'k', label));
    if (action) h.append(action);
    return h;
  }
  function contents() {
    const list = mk('div', 'bk-sections');
    index.parts.forEach((part) => {
      const all = part.chapters.flatMap((c) => c.pages), ai = all.filter((p) => p.meta).length;
      const sum = all.length + (all.length === 1 ? ' page' : ' pages') + (ai ? ', ' + ai + ' written by AI' : '');
      list.append(disclosure(part.title, sum, (body) => part.chapters.forEach((c) => body.append(chapter(c))), !!opened[part.id],
        (on) => { opened[part.id] = on; }));
    });
    return list;
  }
  function chapter(c) {
    const sec = mk('div', 'bsec'), h = mk('h3', '', c.title), ul = mk('ul', 'bk-sealed');
    h.append(mk('span', 'bcount', String(c.pages.length)));
    c.pages.forEach((p) => {
      const li = mk('li', 'bk-row'), t = mk('span', 'bk-rtxt'), acts = mk('span', 'bk-racts');
      t.append(mk('b', '', p.title), mk('small', '', p.changed ? CHANGED : p.meta ? 'Written by ' + p.meta.label : NOT_WRITTEN));
      const go = button('Read', '', () => open(p.id)); go.setAttribute('aria-label', 'Read ' + p.title);
      acts.append(go); li.append(t, acts); ul.append(li);
    });
    sec.append(h, ul); return sec;
  }
  function paint() {
    if (!H) return;
    const a = document.activeElement, had = a && H.contains(a) ? a.textContent : '';
    H.textContent = '';
    H.hidden = !(index && D.token());
    if (H.hidden) { fillMore(); return; }
    const rid = rel(), at = offered(rid);
    const go = at ? button('Continue: ' + at.title, '', () => open(at.id)) : null;
    if (reading) {
      H.append(head('Reading ' + reading.title, button('Back to the contents', '', () => { reading = null; note = ''; paint(); })));
      const box = mk('div', 'bk-sections'); drawPage(box, reading, rid); H.append(box);
    } else H.append(head('Full book', go), contents());
    if (note) H.append(mk('p', 'bnote bad', note));
    const back = had && [...H.querySelectorAll('button')].find((b) => b.textContent === had);
    if (back) back.focus();
    fillMore();
  }
  function failed(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'Couldn\u2019t open that page.';
  }
  async function open(pageId) {
    if (!PAGE.test(pageId)) return;
    const mine = gen;
    try {
      const got = normalPage(await D.api('/v1/book/pages/' + pageId + query(), D.booked()));
      if (mine !== gen) return;
      if (!got) throw new Error('That page came back in a shape this page doesn\u2019t know.');
      reading = got; note = ''; remember(rel() || '', pageId);
    } catch (e) { if (mine !== gen) return; note = failed(e); }
    paint();
    const top = H.querySelector('.bk-rhead');
    if (top && reading && top.scrollIntoView) top.scrollIntoView({ block: 'nearest' });
  }
  async function load(k) {
    const mine = ++gen;
    index = null; reading = null; note = ''; paint();
    if (!H.isConnected || !D.token()) return;
    try {
      const got = normalIndex(await D.api('/v1/book/pages' + query(), D.booked()));
      if (mine === gen && k === key) { index = got; paint(); }
    } catch (_) { /* a guest's 403, a release without pages, offline: the reader stays as it was */ }
  }
  function sync() {
    const k = (H.isConnected ? 'on' : 'off') + '|' + D.token() + '|' + rel();
    if (k === key) return;
    key = k; load(k);
  }

  // ---- the reader's G4 line (owner session only) -------------------------------------------------------
  function fillMore() {
    shownMore = shownMore.filter((n) => n.isConnected);
    const n = index && D && D.token() ? Math.max(0, index.total - index.shown) : 0;
    shownMore.forEach((el) => { el.textContent = n ? '+' + n + ' more in the full book' : ''; el.hidden = !n; });
  }
  function more(body) {
    if (!body || typeof body.append !== 'function') return;
    const el = mk('p', 'bfine'); el.hidden = true; body.append(el); shownMore.push(el); fillMore();
  }

  // ---- the joins ------------------------------------------------------------------------------------
  function mount(host, deps) {
    if (H || !host || !deps || typeof deps.api !== 'function') return;
    H = host; D = deps; H.hidden = true; H.classList.add('bk-set');
    const panel = document.getElementById('p-book');
    if (panel && typeof MutationObserver === 'function') new MutationObserver(sync).observe(panel, { childList: true, subtree: true });
    sync();
  }
  /** A page drawn into `host` (the writer's trial pages): true when it was. */
  function page(host, raw) {
    const p = normalPage(raw);
    if (!host || !p) return false;
    drawPage(host, p, ''); return true;
  }

  window.JarvisBookPages = Object.freeze({ mount, page, more });
})();
