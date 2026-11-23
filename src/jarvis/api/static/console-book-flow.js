// src/jarvis/api/static/console-book-flow.js -- R6.3.1 D3, D10 (docs/plans/r6-3-1-book-at-build.md): the Full book's
// flowcharts in the console's own look (no Markdy, no library). figure(raw) -> a framed <figure> (the flow's title as its
// caption) or null; renderFlow(spec, host) draws a checked FlowSpec into `host`: an inline SVG placed by
// console-book-flow-layout.js (rank and col, no layout engine: the same spec and room, the same chart), orthogonal
// connectors with rounded corners and arrowheads, labels on pills, a key of the shapes, and the steps in order as a text
// list (role="img" + aria-describedby; "Show steps as a list" shows it). A kind is its SHAPE plus a corner glyph, never
// colour alone: step a rounded card, store a cylinder, service a double border, guard a shield (amber), person a pill.
// The main path is the accent with the theme's glow, a side path dashed; colours are console-book.css classes on the
// console's tokens, so Night and Day both work. A box under 560 px is laid out "down" and packed to its width: no
// sideways scroll, never drawn below 1:1 (text >= 12 px), taller instead; it lays itself out again when its box changes
// (ResizeObserver). Imported by console-book-pages.js. Data reaches the page through textContent and setAttribute only.
// No build step; CSP script-src 'self'; ASCII; <= 400 lines.
import { KINDS, SIZE, layout, normalFlow, stepsOf } from './console-book-flow-layout.js';

/**
 * The page JSON's optional `flow` (GET /v1/book/pages/{id}; null or absent: no chart). Plan D3: I0's pydantic model is the
 * source of truth; this module checks every field again and drops what it can't draw.
 * @typedef {'step'|'store'|'service'|'guard'|'person'} FlowKind
 * @typedef {{id: string, label: string, kind: FlowKind, rank: number, col: number, ref?: string}} FlowNode  id a unique
 *   slug; label <= 28 chars; rank 0-9 along the flow (a row "down", a column "right"); col 0-5 across; ref a cited path
 * @typedef {{from: string, to: string, label?: string, style?: 'main'|'side'}} FlowEdge  label <= 20 chars (a pill);
 *   style "main" (the default) solid in the accent, "side" dashed
 * @typedef {{title: string, dir: 'down'|'right', nodes: FlowNode[], edges: FlowEdge[]}} FlowSpec  title <= 60 chars;
 *   2-14 nodes, 1-24 edges
 */

const SVG = 'http://www.w3.org/2000/svg';
const { PAD, LINE, REF, GLYPH, PILL_H } = SIZE, REF_CH = 7.3, CORNER = 8, HEAD = 7;
const SHOW = 'Show steps as a list', HIDE = 'Hide the list';
const f = (v) => String(Math.round(v * 10) / 10);
let seq = 0;
export { normalFlow, stepsOf };

// ---- drawing ------------------------------------------------------------------------------------------
function el(tag, attrs, cls) {
  const n = document.createElementNS(SVG, tag);
  Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, String(attrs[k])));
  if (cls) n.setAttribute('class', cls);
  return n;
}
function mk(tag, cls, words) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (words) n.textContent = words;
  return n;
}
/** The path of a polyline with rounded corners; the end pulled back for the arrowhead, and the head itself. */
function stroke(pts) {
  const [px, py] = pts[pts.length - 2], [ex, ey] = pts[pts.length - 1], l = Math.hypot(ex - px, ey - py) || 1;
  const ux = (ex - px) / l, uy = (ey - py) / l, line = [...pts.slice(0, -1), [ex - ux * (HEAD - 1), ey - uy * (HEAD - 1)]];
  let d = 'M' + f(line[0][0]) + ' ' + f(line[0][1]);
  for (let i = 1; i < line.length - 1; i += 1) {
    const [ax, ay] = line[i - 1], [x, y] = line[i], [bx, by] = line[i + 1];
    const l1 = Math.hypot(x - ax, y - ay), l2 = Math.hypot(bx - x, by - y), k = Math.min(CORNER, l1 / 2, l2 / 2);
    d += 'L' + f(x - (x - ax) / l1 * k) + ' ' + f(y - (y - ay) / l1 * k) + 'Q' + f(x) + ' ' + f(y) + ' ' + f(x + (bx - x) / l2 * k) + ' ' + f(y + (by - y) / l2 * k);
  }
  d += 'L' + f(line[line.length - 1][0]) + ' ' + f(line[line.length - 1][1]);
  const head = 'M' + f(ex) + ' ' + f(ey) + 'L' + f(ex - ux * HEAD - uy * 4) + ' ' + f(ey - uy * HEAD + ux * 4) + 'L' + f(ex - ux * HEAD + uy * 4) + ' ' + f(ey - uy * HEAD - ux * 4) + 'Z';
  return { d, head };
}
// the corner glyphs (12 x 12): a chevron, a cylinder, a hexagon, a shield, a person
const GLYPHS = {
  step: 'M4.5 2.5 8 6l-3.5 3.5',
  store: 'M1.5 3.2c0-1 2-1.7 4.5-1.7s4.5.7 4.5 1.7-2 1.7-4.5 1.7-4.5-.7-4.5-1.7Zm0 0v5.6c0 1 2 1.7 4.5 1.7s4.5-.7 4.5-1.7V3.2',
  service: 'M6 1.2l4.4 2.4v4.8L6 10.8 1.6 8.4V3.6Z',
  guard: 'M6 1l4.5 1.7V6c0 2.6-2 4.3-4.5 5.2C3.5 10.3 1.5 8.6 1.5 6V2.7Z',
  person: 'M6 6.2a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6ZM1.8 11c.6-2.6 2.2-3.6 4.2-3.6s3.6 1 4.2 3.6',
};
/** A card's outline by kind (the shape tells the kind; colour only adds to it). */
function shape(kind, w, h) {
  const g = el('g', {}, 'fl-shape');
  if (kind === 'store') {
    const e = Math.min(5, h / 4);
    g.append(el('path', { d: `M0 ${f(e)}A${f(w / 2)} ${f(e)} 0 0 1 ${f(w)} ${f(e)}V${f(h - e)}A${f(w / 2)} ${f(e)} 0 0 1 0 ${f(h - e)}Z` }, 'fl-card'),
      el('ellipse', { cx: f(w / 2), cy: f(e), rx: f(w / 2), ry: f(e) }, 'fl-lid'));
  } else if (kind === 'guard') {
    const c = Math.min(7, h / 4), p = Math.min(9, h / 3);
    g.append(el('path', { d: `M${f(c)} 0H${f(w - c)}L${f(w)} ${f(c)}V${f(h - p)}L${f(w / 2)} ${f(h)}L0 ${f(h - p)}V${f(c)}Z` }, 'fl-card'));
  } else {
    g.append(el('rect', { width: f(w), height: f(h), rx: f(kind === 'person' ? h / 2 : Math.min(10, h / 4)) }, 'fl-card'));
    const s = Math.min(3.5, h / 5);
    if (kind === 'service') g.append(el('rect', { x: f(s), y: f(s), width: f(w - 2 * s), height: f(h - 2 * s), rx: f(Math.min(7, h / 5)) }, 'fl-inner'));
  }
  return g;
}
function label(words, x, y, cls, max) {
  const t = el('text', { x: f(x), y: f(y), 'text-anchor': 'middle', 'data-max': f(max) }, cls);
  t.textContent = words;
  return t;
}
/** One card: its shape, the corner glyph, the label lines, the ref's file name, and a tooltip with the whole ref. */
function card(c) {
  const { n, w, h, lines } = c, g = el('g', { transform: `translate(${f(c.x)} ${f(c.y)})`, 'data-id': n.id }, 'fl-node fl-k-' + n.kind);
  const tip = el('title');
  tip.textContent = n.label + ' (' + KINDS[n.kind] + ')' + (n.ref ? ' \u00b7 ' + n.ref : '');
  const gx = n.kind === 'person' ? w - 22 : w - 19, gy = n.kind === 'person' ? h / 2 - 6 : n.kind === 'store' ? 11 : 6;
  g.append(tip, shape(n.kind, w, h), el('path', { d: GLYPHS[n.kind], transform: `translate(${f(gx)} ${f(gy)})` }, 'fl-glyph fl-g-' + n.kind));
  const block = lines.length * LINE + (n.ref ? REF : 0), top = (h - block) / 2 + (n.kind === 'store' ? 3 : n.kind === 'guard' ? -2 : 0);
  const room = w - 2 * (PAD + GLYPH);
  lines.forEach((line, i) => g.append(label(line, w / 2, top + i * LINE + 12, 'fl-t', room)));
  if (n.ref) {
    const name = n.ref.split('/').filter(Boolean).pop() || n.ref, most = Math.max(4, Math.floor(room / REF_CH));
    g.append(label(name.length > most ? name.slice(0, most - 1) + '\u2026' : name, w / 2, top + lines.length * LINE + 13, 'fl-ref', room));
  }
  return g;
}
/** The chart for one layout. */
function chart(spec, L, id, describedBy) {
  const [vx, vy, vw, vh] = L.vb;
  const svg = el('svg', { viewBox: [vx, vy, vw, vh].map(f).join(' '), width: f(vw), height: f(vh), role: 'img',
    'aria-labelledby': id + 't', 'aria-describedby': describedBy, focusable: 'false', 'data-dir': L.dir }, 'fl-svg');
  const name = el('title', { id: id + 't' }), sides = el('g', {}, 'fl-sides'), mains = el('g', {}, 'fl-mains');
  const cards = el('g', {}, 'fl-nodes'), pills = el('g', {}, 'fl-pills');
  name.textContent = spec.title;
  L.edges.filter(({ pts }) => pts.length > 1).forEach(({ e, pts }) => {
    const s = stroke(pts), g = el('g', { 'data-from': e.from, 'data-to': e.to }, 'fl-link');
    g.append(el('path', { d: s.d }, 'fl-edge'), el('path', { d: s.head }, 'fl-head'));
    (e.style === 'side' ? sides : mains).append(g);
  });
  L.cards.forEach((c) => cards.append(card(c)));
  L.pills.forEach((p) => {
    const g = el('g', { transform: `translate(${f(p.x)} ${f(p.y)})` }, 'fl-pill');
    g.append(el('rect', { width: f(p.w), height: PILL_H, rx: PILL_H / 2 }), label(p.text, p.w / 2, 14, 'fl-pt', p.w - 10));
    pills.append(g);
  });
  svg.append(name, sides, mains, cards, pills);
  return svg;
}
/** A label wider than its room (a font wider than the estimate) is squeezed to fit: nothing ever spills. */
function fit(svg) {
  svg.querySelectorAll('text[data-max]').forEach((t) => {
    const max = Number(t.getAttribute('data-max'));
    try {
      if (t.getComputedTextLength() > max) { t.setAttribute('textLength', f(max)); t.setAttribute('lengthAdjust', 'spacingAndGlyphs'); }
    } catch (_) { /* not rendered yet: the next layout fits it */ }
  });
}
/** The key: the shapes and line styles this chart uses, each drawn and named. */
function key(spec) {
  const ul = mk('ul', 'bk-flowkey');
  ul.setAttribute('aria-label', 'Key to the shapes');
  const sample = (build) => { const s = el('svg', { viewBox: '-1 -1 26 16', width: 26, height: 16, 'aria-hidden': 'true', focusable: 'false' }, 'fl-swatch'); build(s); return s; };
  Object.keys(KINDS).filter((k) => spec.nodes.some((n) => n.kind === k)).forEach((k) => {
    const li = mk('li');
    li.append(sample((s) => { const g = el('g', {}, 'fl-k-' + k); g.append(shape(k, 24, 14)); s.append(g); }), mk('span', '', KINDS[k]));
    ul.append(li);
  });
  [['main', 'Main path', 'fl-mains'], ['side', 'Side path', 'fl-sides']].filter(([s]) => spec.edges.some((e) => e.style === s)).forEach(([, words, cls]) => {
    const li = mk('li');
    li.append(sample((s) => { const g = el('g', {}, cls); g.append(el('path', { d: 'M1 7H23' }, 'fl-edge')); s.append(g); }), mk('span', '', words));
    ul.append(li);
  });
  return ul;
}
/** The steps in order, visually hidden until "Show steps as a list" (always there for a screen reader). */
function stepList(spec, id) {
  const box = mk('div', 'bk-flowsteps sr-only'), ol = mk('ol');
  box.id = id;
  stepsOf(spec).forEach((s) => ol.append(mk('li', '', s)));
  box.append(mk('p', 'bk-flowsteps-h', 'Steps in order'), ol);
  return box;
}

/** Draw `spec` (a FlowSpec from normalFlow) into `host`: the chart, its key and toggle, the steps list. Returns the chart's
 *  box (its SVG is drawn again, the same way, whenever the box's width asks for another layout), or null. */
export function renderFlow(spec, host) {
  if (!spec || !host || typeof host.append !== 'function') return null;
  const id = 'bkFlow' + (++seq), box = mk('div', 'bk-flowbox'), steps = stepList(spec, id + 's'), foot = mk('div', 'bk-flowfoot');
  const btn = mk('button', 'btn lift bk-flowbtn', SHOW);
  btn.type = 'button'; btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-controls', steps.id);
  btn.addEventListener('click', () => {
    const on = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', String(on)); btn.textContent = on ? HIDE : SHOW; steps.classList.toggle('sr-only', !on);
  });
  foot.append(key(spec), btn);
  host.append(box, foot, steps);
  let laid = '', first = true, seen = false, fitted = false;
  const draw = () => {
    const L = layout(spec, box.clientWidth);
    if (L.key !== laid) {
      const svg = chart(spec, L, id, steps.id);
      if (first && box.isConnected && box.clientWidth) { svg.classList.add('fl-in'); first = false; } // one fade, when first seen
      laid = L.key; fitted = false; box.replaceChildren(svg);
    }
    if (!fitted && box.isConnected && box.clientWidth) { fit(box.firstChild); fitted = true; } // measured once it is shown
  };
  draw();
  if (typeof ResizeObserver === 'function') {
    const watch = new ResizeObserver(() => {
      if (box.isConnected) seen = true; else if (seen) { watch.disconnect(); return; }
      draw();
    });
    watch.observe(box);
  }
  return box;
}

/** The page's framed figure: caption (the flow's title), chart, key, toggle and steps. Null when there is nothing to draw. */
export function figure(raw) {
  const spec = normalFlow(raw);
  if (!spec) return null;
  const fig = mk('figure', 'bk-flow');
  fig.append(mk('figcaption', 'bk-flowcap', spec.title));
  renderFlow(spec, fig);
  return fig;
}
