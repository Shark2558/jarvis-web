// src/jarvis/api/static/console-book-flow-layout.js -- R6.3.1 D3 (docs/plans/r6-3-1-book-at-build.md): the geometry of
// the Full book's flowcharts, pure (no DOM, no layout library); imported by console-book-flow.js, which draws it.
// normalFlow(raw) checks a page's `flow` field by field; stepsOf(spec) reads it as steps in order; layout(spec, width)
// places it: ranks and cols squeezed to a grid, each card as tall as its own words, a narrow box packed to its width;
// orthogonal connectors (straight when they can be, else elbows; back up the flow along an outer lane); every connector
// that crosses a gap rides a TRACK of its own and each gap is as tall as its tracks need, so no two lines run along each
// other and a label's pill sits on its own track: never on a card, never on another pill. Same spec, same room: same chart.
// No build step; CSP script-src 'self'; ASCII; <= 400 lines.

export const KINDS = Object.freeze({ step: 'Step', store: 'Store', service: 'Service', guard: 'Guard', person: 'Person' });
// shared with the drawing: card padding, a label line, the ref line, the corner glyph's room, a pill's height
export const SIZE = Object.freeze({ PAD: 8, LINE: 16, REF: 16, GLYPH: 13, PILL_H: 20 });
const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/;
const MAX_NODES = 14, MAX_EDGES = 24, NARROW = 560;
// card widths (the most; the least side by side; one column's most), characters' widths (13 px labels, 12 px pills),
// margins, gaps across (down, right), the outer lane's room, a gap along the flow (with labels / without)
const WIDE_W = 168, MIN_W = 124, ONE_W = 220, CH = 6.8, PILL_CH = 6.7, MARGIN = 8;
const GAP_DOWN = 24, GAP_RIGHT = 22, LANE = 14, GAP_LABELS = 50, GAP_PLAIN = 34;
const { PAD, LINE, REF, GLYPH, PILL_H } = SIZE;
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const txt = (v, max) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
const int = (v, lo, hi) => (Number.isInteger(v) && v >= lo && v <= hi ? v : null);

// ---- the spec, checked field by field --------------------------------------------------------------
/** A FlowSpec from the page JSON's `flow`, or null (fewer than 2 nodes or no edge left to draw). */
export function normalFlow(raw) {
  const d = obj(raw);
  if (!d) return null;
  const nodes = [], seen = new Set();
  arr(d.nodes).slice(0, MAX_NODES).map(obj).filter(Boolean).forEach((n) => {
    const id = typeof n.id === 'string' && ID.test(n.id) ? n.id : '', label = txt(n.label, 28);
    const rank = int(n.rank, 0, 9), col = int(n.col, 0, 5);
    if (!id || seen.has(id) || !label || !Object.hasOwn(KINDS, n.kind) || rank === null || col === null) return;
    seen.add(id); nodes.push({ id, label, kind: n.kind, rank, col, ref: txt(n.ref, 200) });
  });
  const edges = arr(d.edges).slice(0, MAX_EDGES).map(obj).filter((e) => e && seen.has(e.from) && seen.has(e.to) && e.from !== e.to)
    .map((e) => ({ from: e.from, to: e.to, label: txt(e.label, 20), style: e.style === 'side' ? 'side' : 'main' }));
  if (nodes.length < 2 || !edges.length) return null;
  return { title: txt(d.title, 60) || 'How it flows', dir: d.dir === 'right' ? 'right' : 'down', nodes, edges };
}

/** The text list: every edge "A -> B (label)", in order of the nodes' rank, then col (a topological reading). */
export function stepsOf(spec) {
  const at = new Map(), by = new Map(spec.nodes.map((n) => [n.id, n]));
  spec.nodes.map((n, i) => ({ n, i })).sort((a, b) => a.n.rank - b.n.rank || a.n.col - b.n.col || a.i - b.i)
    .forEach(({ n }, i) => at.set(n.id, i));
  return spec.edges.map((e, i) => ({ e, i }))
    .sort((a, b) => at.get(a.e.from) - at.get(b.e.from) || at.get(a.e.to) - at.get(b.e.to) || a.i - b.i)
    .map(({ e }) => {
      const note = [e.label, e.style === 'side' ? 'side path' : ''].filter(Boolean).join('; ');
      return by.get(e.from).label + ' \u2192 ' + by.get(e.to).label + (note ? ' (' + note + ')' : '');
    });
}

// ---- the grid --------------------------------------------------------------------------------------
/** A label in lines of at most `per` characters (whole words; a longer word is cut). */
function wrap(label, per) {
  const lines = [];
  let cur = '';
  label.split(' ').forEach((word) => {
    let w = word;
    while (w.length > per) { if (cur) { lines.push(cur); cur = ''; } lines.push(w.slice(0, per)); w = w.slice(per); }
    if (!w) return;
    if (!cur) cur = w; else if (cur.length + 1 + w.length <= per) cur += ' ' + w; else { lines.push(cur); cur = w; }
  });
  if (cur) lines.push(cur);
  return lines;
}
/** Rows of cells: unused ranks and cols take no room; two nodes in one cell, the later one moves along. */
function grid(spec) {
  const ranks = [...new Set(spec.nodes.map((n) => n.rank))].sort((a, b) => a - b), colOf = new Map(), used = new Set();
  const rows = ranks.map((r) => spec.nodes.filter((n) => n.rank === r).sort((a, b) => a.col - b.col));
  rows.forEach((row) => { let last = -1; row.forEach((n) => { last = Math.max(n.col, last + 1); colOf.set(n.id, last); used.add(last); }); });
  const index = new Map([...used].sort((a, b) => a - b).map((c, i) => [c, i]));
  return { rows: rows.map((row) => row.map((n) => ({ n, k: index.get(colOf.get(n.id)) }))), span: used.size };
}
/** More nodes across than the room holds: each rank in rows of `per`, centred. */
const pack = (rows, per) => rows.flatMap((row) => {
  const out = [];
  for (let i = 0; i < row.length; i += per) { const part = row.slice(i, i + per); out.push(part.map((x, j) => ({ n: x.n, k: j + (per - part.length) / 2 }))); }
  return out;
});
const hits = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const grow = (r, by) => ({ x: r.x - by, y: r.y - by, w: r.w + 2 * by, h: r.h + 2 * by });

/** Where everything goes for `width` px of room (0: not laid out yet): {dir, key, vb, cards, edges, pills}. */
export function layout(spec, width) {
  let L = place(spec, width > 0 && width < NARROW ? 'down' : spec.dir, width, 0);
  if (L.dir === 'right' && width > 0 && L.vb[2] > width) L = place(spec, 'down', width, 0);
  // "down" still wider than the room (a lane or a pill past the cards): the cards give up that much, twice at most
  for (let i = 0, less = 0; i < 2 && L.dir === 'down' && width > 0 && L.vb[2] > width + 0.5; i += 1) {
    less += Math.ceil(L.vb[2] - width); L = place(spec, 'down', width, less);
  }
  return L;
}
function place(spec, dir, width, less) {
  const down = dir === 'down', rankOf = new Map(spec.nodes.map((n) => [n.id, n.rank]));
  let { rows, span } = grid(spec), w = WIDE_W;
  if (down && width > 0) { // as many across as fit at MIN_W, then the cards share the room (never wider than WIDE_W)
    const at0 = new Map(spec.nodes.map((n) => [n.id, n])), up = (a, b) => b.rank < a.rank || (b.rank === a.rank && b.col < a.col);
    const backs = spec.edges.filter((e) => up(at0.get(e.from), at0.get(e.to))).length; // lanes beyond the cards (packing too)
    const room = width - 2 * MARGIN - (backs ? LANE + 10 * (backs - 1) : 0) - less;
    const across = Math.max(1, Math.floor((room + GAP_DOWN) / (MIN_W + GAP_DOWN)));
    if (span > across) { rows = pack(rows, across); span = across; }
    w = Math.max(80, Math.min(span === 1 ? ONE_W : WIDE_W, Math.floor((room - (span - 1) * GAP_DOWN) / span)));
  }
  const per = Math.max(8, Math.floor((w - 2 * (PAD + GLYPH)) / CH)), lines = new Map(spec.nodes.map((n) => [n.id, wrap(n.label, per)]));
  const hOf = (n) => 2 * PAD + 6 + lines.get(n.id).length * LINE + (n.ref ? REF : 0), tall = Math.max(...spec.nodes.map(hOf));
  const pillW = (e) => (e.label ? Math.ceil(e.label.length * PILL_CH) + 16 : 0), widest = Math.max(0, ...spec.edges.map(pillW));
  const sameRank = spec.edges.some((e) => e.label && rankOf.get(e.to) === rankOf.get(e.from)); // "right": a pill between
  const gapC = down ? GAP_DOWN : sameRank ? PILL_H + 28 : GAP_RIGHT, pitch = (down ? w : tall) + gapC, at = new Map();
  rows.forEach((row, r) => row.forEach(({ n, k }) => { // c: across the flow (known now); m: along it (after the tracks)
    const h = hOf(n), ce = down ? w : h, c0 = k * pitch + ((down ? w : tall) - ce) / 2;
    at.set(n.id, { n, r, k, h, me: down ? h : w, c0, c1: c0 + ce, cc: c0 + ce / 2 });
  }));
  const all = [...at.values()], paths = ports(spec.edges.map(router(all, gapC, !down)));
  const step = down ? (widest ? PILL_H + 4 : 10) : (widest ? widest + 8 : 10), base = down ? (widest ? GAP_LABELS : GAP_PLAIN) : Math.max(44, widest + 24);
  const slots = tracks(spec, at, paths, pillW, step);
  // m: rows as tall as their tallest card, each gap as tall as its tracks need (a gap outside the rows only when used)
  const rowH = rows.map((row) => Math.max(...row.map(({ n }) => at.get(n.id).me))), R = rows.length;
  const gh = (g) => (slots.has(g) ? base + (slots.get(g).n - 1) * step : g < 0 || g >= R - 1 ? 0 : base), top = [];
  let m = gh(-1);
  rows.forEach((_, r) => { top[r] = m; m += rowH[r] + gh(r); });
  all.forEach((p) => { p.m0 = top[p.r] + (rowH[p.r] - p.me) / 2; });
  const mid = (g) => (g < 0 ? gh(-1) / 2 : top[g] + rowH[g] + gh(g) / 2);
  const mOf = (s) => ('g' in s ? mid(s.g) + s.off : s.p.m0 + s.side * s.p.me), xy = (mm, c) => (down ? [c, mm] : [mm, c]);
  const cards = all.map((p) => ({ n: p.n, lines: lines.get(p.n.id), w, h: p.h, ...(down ? { x: p.c0, y: p.m0 } : { x: p.m0, y: p.c0 }) }));
  const edges = spec.edges.map((e, i) => ({ e, pts: tidy(paths[i].map(([s, c]) => xy(mOf(s), c))) }));
  const pills = [];
  slots.forEach(({ items }, g) => items.filter((it) => it.pill).forEach((it) => pills.push({ i: it.i, ...centred(xy(mid(g) + it.off, it.at), it.pill) })));
  spec.edges.forEach((e, i) => { if (e.label && !pills.some((p) => p.i === i)) pills.push({ i, ...spot(edges[i].pts, pillW(e), cards, pills) }); });
  pills.forEach((p) => { p.text = spec.edges[p.i].label; });
  const pts = [...cards.flatMap((c) => [[c.x, c.y], [c.x + c.w, c.y + c.h]]), ...edges.flatMap((r) => r.pts),
    ...pills.flatMap((p) => [[p.x, p.y], [p.x + p.w, p.y + p.h]])];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]), x0 = Math.min(...xs) - MARGIN, y0 = Math.min(...ys) - MARGIN;
  const vb = [x0, y0, Math.max(...xs) + MARGIN - x0, Math.max(...ys) + MARGIN - y0];
  return { dir, key: [dir, w, span, per].join('|'), vb, cards, edges, pills };
}
const centred = ([x, y], w) => ({ x: x - w / 2, y: y - PILL_H / 2, w, h: PILL_H });

// ---- connectors ------------------------------------------------------------------------------------
/** A route per edge, in flow terms: points [m, c] where m is {p, side} (a card's near side 0, middle .5, far side 1)
 *  or {g, off} (gap g after rank g, -1 before the first; `off` is its track, set later; both ends of a segment across a
 *  gap share one). Straight when it can be; else an elbow in a gap; back up the flow along a lane beyond every card. */
function router(all, gapC, pillFits) {
  const outer = Math.max(...all.map((p) => p.c1)) + 14, at = new Map(all.map((p) => [p.n.id, p]));
  const last = (p) => !all.some((q) => q.r === p.r && q.k > p.k); // nothing further across in its rank
  const clear = (a, b, c) => !all.some((p) => p.r > a.r && p.r < b.r && p.c0 - 6 < c && c < p.c1 + 6);
  const N = (p, side) => ({ p, side }), G = (g) => ({ g, off: 0 });
  let backs = 0;
  return (e) => {
    const a = at.get(e.from), b = at.get(e.to);
    if (b.r === a.r) { // across one rank: straight between neighbours (a pill fits when "right"); else under the rank
      const lo = Math.min(a.k, b.k), hi = Math.max(a.k, b.k), fwd = b.k > a.k;
      if ((!e.label || pillFits) && !all.some((p) => p.r === a.r && p.k > lo && p.k < hi)) return fwd ? [[N(a, 0.5), a.c1], [N(b, 0.5), b.c0]] : [[N(a, 0.5), a.c0], [N(b, 0.5), b.c1]];
      const g = G(a.r), ac = (a.cc + (fwd ? a.c1 : a.c0)) / 2, bc = (b.cc + (fwd ? b.c0 : b.c1)) / 2; // off-centre ends
      return [[N(a, 1), ac], [g, ac], [g, bc], [N(b, 1), bc]];
    }
    if (b.r < a.r) { // back up the flow, off-centre so it never runs along a main connector
      const lane = outer + 10 * backs++, ac = (a.cc + a.c1) / 2, bc = (b.cc + b.c1) / 2, go = G(a.r), gi = G(b.r - 1);
      const from = last(a) && !e.label ? [[N(a, 0.5), a.c1], [N(a, 0.5), lane]] : [[N(a, 1), ac], [go, ac], [go, lane]];
      return [...from, ...(last(b) ? [[N(b, 0.5), lane], [N(b, 0.5), b.c1]] : [[gi, lane], [gi, bc], [N(b, 0), bc]])];
    }
    const S = [N(a, 1), a.cc], E = [N(b, 0), b.cc];
    if (Math.abs(a.cc - b.cc) < 1 && clear(a, b, a.cc)) return [S, E];
    if (clear(a, b, a.cc)) { const g = G(b.r - 1); return [S, [g, a.cc], [g, b.cc], E]; }
    if (clear(a, b, b.cc)) { const g = G(a.r); return [S, [g, a.cc], [g, b.cc], E]; }
    const lane = [Math.max(a.c1, b.c1) + gapC / 2, Math.min(a.c0, b.c0) - gapC / 2].find((c) => clear(a, b, c)) ?? outer + 10 * backs++;
    const g1 = G(a.r), g2 = G(b.r - 1);
    return [S, [g1, a.cc], [g1, lane], [g2, lane], [g2, b.cc], E];
  };
}
/** Several connectors on one side of a card get ports of their own, spread over its middle and ordered by where each
 *  heads, so none runs along another; a straight one keeps its middle. Only a route's first or last leg moves. */
function ports(paths) {
  const sides = new Map(), add = (p, side, item) => { const k = p.n.id + '|' + side; sides.set(k, [...(sides.get(k) || []), { p, ...item }]); };
  paths.forEach((pts) => {
    const n = pts.length, a = pts[0][0], b = pts[n - 1][0], straight = n === 2;
    if (a.side === 0 || a.side === 1) add(a.p, a.side, { pts, ends: [0, 1], toward: straight ? pts[0][1] : pts[2][1], fixed: straight });
    if (b.side === 0 || b.side === 1) add(b.p, b.side, { pts, ends: [n - 1, n - 2], toward: straight ? pts[n - 1][1] : pts[n - 3][1], fixed: straight });
  });
  sides.forEach((list) => {
    if (list.length < 2) return;
    const { c0, c1, cc } = list[0].p, free = list.filter((x) => !x.fixed).sort((x, y) => x.toward - y.toward);
    const fixed = list.length - free.length, n = free.length + (fixed ? 1 : 0);
    const slots = Array.from({ length: n }, (_, j) => c0 + (c1 - c0) * (0.2 + (0.6 * (j + 0.5)) / n));
    if (fixed) slots.splice(slots.reduce((best, c, j) => (Math.abs(c - cc) < Math.abs(slots[best] - cc) ? j : best), 0), 1);
    free.forEach((x, j) => x.ends.forEach((i) => { x.pts[i] = [x.pts[i][0], slots[j]]; }));
  });
  return paths;
}
/** Per gap, every segment across it (and every label's pill there) on a track of its own: intervals that meet never
 *  share a track. Tracks are `step` apart around the gap's middle. Returns gap -> {n tracks, items}. */
function tracks(spec, at, paths, pillW, step) {
  const gaps = new Map(), add = (g, item) => gaps.set(g, [...(gaps.get(g) || []), item]), cs = [...at.values()];
  const X0 = Math.min(...cs.map((p) => p.c0)), X1 = Math.max(...cs.map((p) => p.c1));
  const inside = (lo, hi, mid, w) => { const a = Math.max(lo, X0 + w / 2), b = Math.min(hi, X1 - w / 2); return a <= b ? Math.min(b, Math.max(a, mid)) : mid; };
  paths.forEach((pts, i) => {
    const e = spec.edges[i], pw = pillW(e);
    let labelled = false;
    for (let j = 0; j + 1 < pts.length; j += 1) {
      const [p, q] = [pts[j], pts[j + 1]];
      if (!('g' in p[0]) || p[0] !== q[0]) continue; // a segment across a gap: both ends share one {g, off}
      const lo = Math.min(p[1], q[1]), hi = Math.max(p[1], q[1]), pill = pw && !labelled ? pw : 0;
      const c = pill ? inside(lo, hi, (lo + hi) / 2, pill) : (lo + hi) / 2; // a pill kept over the cards' width
      labelled = labelled || !!pill;
      add(p[0].g, { i, G: p[0], at: c, pill, lo: pill ? Math.min(lo, c - pill / 2) : lo, hi: pill ? Math.max(hi, c + pill / 2) : hi });
    }
    const a = at.get(e.from), b = at.get(e.to);
    if (pw && !labelled && pts.length === 2 && b.r > a.r) add(a.r, { i, at: a.cc, pill: pw, lo: a.cc - pw / 2, hi: a.cc + pw / 2 }); // straight
  });
  const out = new Map();
  gaps.forEach((items, g) => {
    const ends = [];
    items.sort((x, y) => x.lo - y.lo || x.hi - y.hi || x.i - y.i).forEach((it) => {
      let t = ends.findIndex((end) => end < it.lo - 6);
      if (t < 0) { t = ends.length; ends.push(0); }
      ends[t] = it.hi; it.t = t;
    });
    items.forEach((it) => { it.off = (it.t - (ends.length - 1) / 2) * step; if (it.G) it.G.off = it.off; });
    out.set(g, { n: ends.length, items });
  });
  return out;
}
/** Points without repeats or straight-through middles (so every corner is a real turn). */
function tidy(pts) {
  const out = [], same = (u, v) => Math.abs(u - v) < 0.5;
  pts.forEach((p) => {
    const q = out[out.length - 1], o = out[out.length - 2];
    if (q && same(q[0], p[0]) && same(q[1], p[1])) return;
    if (o && ((same(o[0], q[0]) && same(q[0], p[0])) || (same(o[1], q[1]) && same(q[1], p[1])))) out.pop();
    out.push(p);
  });
  return out;
}
/** A label with no track (a route along card sides only): the first free spot on its own edge, the middle first. */
function spot(pts, w, cards, placed) {
  const keep = cards.map((c) => grow(c, 3)), segs = [], mid = Math.floor((pts.length - 2) / 2);
  for (let i = 0; i + 1 < pts.length; i += 1) segs.push({ i, len: Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) });
  segs.sort((a, b) => (a.i === mid ? -1 : b.i === mid ? 1 : b.len - a.len));
  const spots = segs.flatMap((s) => [0.5, 0.3, 0.7].map((t) => centred([pts[s.i][0] + (pts[s.i + 1][0] - pts[s.i][0]) * t, pts[s.i][1] + (pts[s.i + 1][1] - pts[s.i][1]) * t], w)));
  return spots.find((r) => !keep.some((c) => hits(r, c)) && !placed.some((p) => hits(r, grow(p, 2)))) || spots[0];
}
