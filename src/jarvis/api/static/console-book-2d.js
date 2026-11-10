// src/jarvis/api/static/console-book-2d.js -- R6 D15 (book.html): the 2D show for phones (< 900 px), reduced motion and no
// WebGL2 -- the same beats as HTML/CSS cards (opacity/transform only), no GL context.
// One card a scene, built from that scene's facts (book.show; nothing is hard-coded): the Core and the release's tiles
// (1), stacked layer plates with their module ticks (2), a flow of steps with a moving packet (3, 5, 6, 8), groups of
// nodes (4, 7, 11; "later" dimmed), library tags by role with flagged licences in amber and in words (9), rupee bars
// (10, the owner's month against his limit), the Core listening (12) and folding into the sealed vault cube (13).
// A beat lights what its `focus` names (a fact's label, value or group, or its 1-based place); a flow with no focus
// walks one step a beat. Also fills every `.sh-emblem` with the console's 2D Core (built node by node, no markup).
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
// window.JarvisBook2D = { mount(host) -> { show(scene, beatIndex, beat, ctx), dispose() }, emblem(el) }
(() => {
  'use strict';
  const SVG = 'http://www.w3.org/2000/svg';
  const KIND = { 1: 'core', 2: 'plates', 3: 'flow', 4: 'grid', 5: 'flow', 6: 'flow', 7: 'grid', 8: 'flow', 9: 'tags', 10: 'bars', 11: 'grid', 12: 'core', 13: 'core' };
  const FLAG = { copyleft: 'Copyleft', non_commercial: 'Non-commercial' };
  const MAX_TICKS = 60, MAX_ITEMS = 24;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const fmt = (n) => { try { return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n); } catch (_) { return String(n); } };

  // ---- the console's 2D Core (console-fx.js coreSVG 'lg'), node by node -------------------------
  function sv(tag, attrs, parent) {
    const n = document.createElementNS(SVG, tag);
    Object.keys(attrs).forEach((k) => n.setAttribute(k, String(attrs[k])));
    if (parent) parent.append(n);
    return n;
  }
  const r2 = (n) => Math.round(n * 100) / 100;
  let gid = 0;
  function emblem(host) {
    if (!host || host.firstChild) return;
    const s = sv('svg', { viewBox: '0 0 120 120', focusable: 'false' }), id = 'bkg' + (++gid);
    const grad = sv('radialGradient', { id }, sv('defs', {}, s));
    sv('stop', { offset: 0, 'stop-color': '#fff' }, grad); sv('stop', { class: 's1', offset: 0.5, 'stop-opacity': 0.55 }, grad);
    sv('stop', { class: 's2', offset: 1, 'stop-opacity': 0 }, grad);
    const g1 = sv('g', { class: 'r1' }, s), g2 = sv('g', { class: 'r2' }, s), g3 = sv('g', { class: 'r3' }, s), glow = sv('g', { class: 'glow' }, s);
    sv('circle', { class: 'faint', cx: 60, cy: 60, r: 57.5, 'stroke-width': 0.8 }, g1);
    for (let i = 0; i < 72; i += 1) {
      const major = i % 6 === 0, a = (i * 5 - 90) * Math.PI / 180, r0 = major ? 48.5 : 52.5;
      sv('line', { class: major ? 'tick major' : 'tick', x1: r2(60 + r0 * Math.cos(a)), y1: r2(60 + r0 * Math.sin(a)),
        x2: r2(60 + 56 * Math.cos(a)), y2: r2(60 + 56 * Math.sin(a)), 'stroke-width': major ? 1.7 : 0.9 }, g1);
    }
    const c2 = 2 * Math.PI * 43, c3 = 2 * Math.PI * 31;
    sv('circle', { class: 'arc', cx: 60, cy: 60, r: 43, 'stroke-width': 3, 'stroke-dasharray': r2(c2 * 70 / 360) + ' ' + r2(c2 * 50 / 360) }, g2);
    sv('circle', { class: 'faint', cx: 60, cy: 60, r: 31, 'stroke-width': 1, 'stroke-dasharray': '1 3' }, g3);
    sv('circle', { class: 'arc2', cx: 60, cy: 60, r: 31, 'stroke-width': 2.2, 'stroke-dasharray': r2(c3 * 40 / 360) + ' ' + r2(c3 * 140 / 360) }, g3);
    sv('circle', { cx: 60, cy: 60, r: 22, fill: 'url(#' + id + ')' }, glow);
    sv('circle', { class: 'nucleus', cx: 60, cy: 60, r: 8, 'stroke-width': 1.5 }, glow);
    sv('circle', { cx: 60, cy: 60, r: 3.2, fill: 'var(--accent)' }, glow);
    host.append(s);
  }
  /** The sealed vault cube with its lock (scene 13), drawn in the Core's own strokes (inside a .core, like the emblem). */
  function cube() {
    const box = mk('span', 'core sh2-cube'), s = sv('svg', { viewBox: '0 0 120 120', focusable: 'false' });
    box.setAttribute('aria-hidden', 'true'); box.append(s);
    sv('path', { class: 'arc', d: 'M60 14 100 36v48L60 106 20 84V36z', 'stroke-width': 2, fill: 'none' }, s);
    sv('path', { class: 'faint', d: 'M20 36l40 22 40-22M60 58v48', 'stroke-width': 1.4 }, s);
    const lock = sv('g', { class: 'sh2-lock' }, s);
    sv('path', { class: 'arc2 sh2-shackle', d: 'M53 60v-6a7 7 0 0 1 14 0v6', 'stroke-width': 2, fill: 'none' }, lock);
    sv('rect', { class: 'nucleus', x: 48, y: 60, width: 24, height: 18, rx: 3, 'stroke-width': 1.5 }, lock);
    sv('path', { class: 'arc sh2-key', d: 'M60 65v8', 'stroke-width': 2 }, lock);
    return box;
  }

  // ---- which facts a beat lights ------------------------------------------------------------------
  function lit(facts, beat, kind) {
    const f = String(beat && beat.focus || '').toLowerCase(), on = new Set();
    if (f) {
      facts.forEach((x, i) => {
        if ([x.label, x.value, x.group].some((v) => v && v.toLowerCase() === f) || String(i + 1) === f) on.add(i);
      });
    } else if (kind === 'flow' && facts.length) on.add(Math.min(beat ? beat.i : 0, facts.length - 1));
    return on;
  }
  function item(cls, f) {
    const el = mk('li', cls);
    el.append(mk('b', '', f.label || f.value));
    if (f.value && f.label) el.append(mk('small', '', f.value));
    return el;
  }

  // ---- one builder per kind: returns the card and the elements a beat can light ---------------
  function buildCore(scene, ctx) {
    const card = mk('div', 'sh2-core'), em = mk('span', 'core sh2-emblem');
    em.setAttribute('aria-hidden', 'true'); emblem(em); card.append(em);
    if (scene.n === 13) card.append(cube());
    const tiles = mk('ul', 'tiles sh2-tiles'), items = [];
    scene.facts.slice(0, 6).forEach((f) => {
      const t = mk('li', 'tile'); t.append(mk('b', '', f.value || (f.n !== null ? fmt(f.n) : '')), mk('span', '', f.label));
      tiles.append(t); items.push(t);
    });
    if (items.length) card.append(tiles);
    if (scene.n === 12 && ctx && ctx.listening) em.classList.add('busy');
    return { card, items };
  }
  function buildPlates(scene) {
    const list = mk('ol', 'sh2-plates'), items = [];
    scene.facts.slice(0, 9).forEach((f) => {
      const p = mk('li', 'sh2-plate'), head = mk('div', 'sh2-ph'), ticks = mk('span', 'sh2-ticks');
      head.append(mk('span', 'k', f.value), mk('b', '', f.label));
      if (f.n !== null) head.append(mk('span', 'v', fmt(f.n)));
      for (let i = 0; i < Math.min(MAX_TICKS, Math.max(0, Math.round(f.n || 0))); i += 1) ticks.append(mk('i'));
      ticks.setAttribute('aria-hidden', 'true');
      p.append(head, ticks); list.append(p); items.push(p);
    });
    return { card: list, items };
  }
  function buildFlow(scene) {
    const wrap = mk('div', 'sh2-flowwrap'), list = mk('ol', 'sh2-flow'), packet = mk('span', 'sh2-packet'), items = [];
    packet.setAttribute('aria-hidden', 'true');
    scene.facts.slice(0, 12).forEach((f, i) => {
      const n = item('sh2-node', f); n.prepend(mk('span', 'k', String(i + 1).padStart(2, '0'))); list.append(n); items.push(n);
    });
    wrap.append(list, packet);
    return { card: wrap, items, packet };
  }
  function grouped(scene, cls, decorate) {
    const wrap = mk('div', 'sh2-groups'), items = [], groups = new Map();
    scene.facts.slice(0, MAX_ITEMS).forEach((f) => {
      const key = f.group || '';
      if (!groups.has(key)) {
        const g = mk('section', 'sh2-group'), ul = mk('ul', 'sh2-chips');
        if (key) g.append(mk('h3', 'k', key.replace(/_/g, ' ')));
        g.append(ul); wrap.append(g); groups.set(key, ul);
      }
      const chip = item(cls, f); decorate(chip, f); groups.get(key).append(chip); items.push(chip);
    });
    return { card: wrap, items };
  }
  function buildGrid(scene) {
    return grouped(scene, 'sh2-chip' + (scene.n === 11 ? ' later' : ''), (chip) => { if (scene.n === 11) chip.append(mk('span', 'k sh2-later', 'later')); });
  }
  function buildTags(scene) {
    return grouped(scene, 'sh2-chip', (chip, f) => { if (FLAG[f.flag]) { chip.classList.add('flagged'); chip.append(mk('span', 'tag', FLAG[f.flag])); } });
  }
  function buildBars(scene, ctx) {
    const list = mk('ul', 'sh2-bars'), items = [], rows = scene.facts.slice(0, 12).map((f) => ({ f, v: f.n || 0 }));
    const c = ctx && ctx.costs;
    if (ctx && ctx.audience === 'owner' && c && c.month !== null && c.limit) {
      rows.push({ f: { label: 'This month', value: '\u20b9' + fmt(c.month), flag: '' }, v: c.month, mine: true });
      rows.push({ f: { label: 'Your monthly limit', value: '\u20b9' + fmt(c.limit), flag: '' }, v: c.limit, mine: true });
    }
    const top = Math.max(1, ...rows.map((r) => Math.log10(1 + r.v)));
    rows.forEach((r) => {
      const li = mk('li', 'sh2-bar' + (r.f.flag === 'free' || !r.v ? ' free' : '') + (r.mine ? ' mine' : '')), bar = mk('div', 'mbar'), fill = mk('i');
      li.append(mk('b', '', r.f.label), mk('span', 'v', r.f.value));
      fill.style.width = Math.max(2, Math.round(Math.log10(1 + r.v) / top * 100)) + '%';
      bar.append(fill); li.append(bar); list.append(li); items.push(li);
    });
    return { card: list, items };
  }
  const BUILD = { core: buildCore, plates: buildPlates, flow: buildFlow, grid: buildGrid, tags: buildTags, bars: buildBars };

  function mount(host) {
    if (!host) return null;
    let cur = null;
    host.hidden = false; host.textContent = '';
    document.documentElement.classList.add('book-2d');
    function place(packet, el) {
      if (!packet || !el) return;
      const x = el.offsetLeft + el.offsetWidth - 12, y = el.offsetTop + 12; // the step's top corner, clear of its words
      packet.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
      packet.classList.add('on');
    }
    function show(scene, beatIndex, beat, ctx) {
      const kind = KIND[scene.n] || 'grid';
      if (!cur || cur.n !== scene.n) {
        const built = BUILD[kind](scene, ctx || {});
        const box = mk('div', 'sh2-scene sh2-k-' + kind);
        box.dataset.scene = String(scene.n);
        box.append(built.card);
        host.replaceChildren(box);
        cur = Object.assign({ n: scene.n, box }, built); // it enters by a CSS animation (none in Calm / Off)
      }
      const on = lit(scene.facts, Object.assign({}, beat, { i: beatIndex }), kind);
      cur.items.forEach((el, i) => el.classList.toggle('on', on.has(i)));
      if (cur.packet) place(cur.packet, cur.items[[...on][0]]);
      if (scene.n === 13) { cur.box.classList.toggle('fold', beatIndex >= 1); cur.box.classList.toggle('fade', beatIndex >= 2); }
    }
    function dispose() { host.textContent = ''; host.hidden = true; cur = null; document.documentElement.classList.remove('book-2d'); }
    return { show, dispose };
  }

  window.JarvisBook2D = Object.freeze({ mount, emblem });
  document.querySelectorAll('.sh-emblem').forEach(emblem);
})();
