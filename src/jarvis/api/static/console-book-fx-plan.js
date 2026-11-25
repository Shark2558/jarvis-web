// src/jarvis/api/static/console-book-fx-plan.js -- R6.4 D11 (docs/plans/r6-4-book-look.md): the pure half of the chapter
// player's effects engine, an ES module with no DOM. Two jobs:
//   sceneAt(lines, i, flows) -> what the stage shows at line i (the page, the view, the spoken box, the boxes told before
//     it, the connector just told, a count, the example's frame), worked out from the script's cues alone, so a jump to
//     any line draws the same stage as playing up to it. Cues say WHAT is shown (page, show, node, edge, count).
//   plan(chapterId, lines, flows) -> for every line, HOW it is shown: which variant of each effect family runs. The
//     picker is deterministic (seeded by the chapter id and the line number), never deals the same variant of a family
//     twice in a row, and deals every variant of a family before any comes round again (a shuffled bag), so each
//     family is spread across the chapter wherever its cue exists.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.

/** The effect families (D11) and their variants. Kind accents and the camera's establish / pull-back are structural. */
export const FAMILIES = Object.freeze({
  trace: Object.freeze(['draw', 'packet', 'comet']), // 1. path tracing along the connector just told
  enter: Object.freeze(['ping', 'bracket', 'scan', 'lift']), // 2. the spoken box's entrance
  accent: Object.freeze(['lock', 'fill', 'turn', 'wave', 'nudge']), // 3. by kind: guard, store, service, person, step
  cam: Object.freeze(['glide', 'swoop', 'push', 'drift']), // 4. the camera's move to the spoken box
  reveal: Object.freeze(['split', 'type', 'decode', 'iris']), // 5. a section card's HUD reveal
  frame: Object.freeze(['slide', 'flip', 'rise']), // 6. a storyboard frame's entrance
  count: Object.freeze(['tick', 'stamp']), // 7. a count-up's style
  alert: Object.freeze(['pulse', 'sweep', 'corners']), // 8. the failure frame's alert
  swap: Object.freeze(['h', 'v', 'diag']), // 10. the page change's wipe
});
export const ACCENT_OF = Object.freeze({ guard: 'lock', store: 'fill', service: 'turn', person: 'wave', step: 'nudge' });
export const SHOWS = Object.freeze(['title', 'plain', 'example', 'how', 'costs', 'fails', 'overview']);
const CARDS = new Set(['title', 'plain', 'example', 'how', 'costs', 'fails']);
const POINTS = new Set(['plain', 'example', 'how', 'fails']); // cards told point by point (the example: frame by frame)

/** FNV-1a, 32 bits: a stable number for a string. */
export function hash(text) {
  let h = 0x811c9dc5;
  const s = String(text);
  for (let i = 0; i < s.length; i += 1) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}
/** mulberry32: a small seeded generator, 0 <= r < 1. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The picker, pure: one variant for the slot at line `n` of chapter `seed`.
 * `bag` holds the variants not yet dealt this round (an empty or missing bag starts a new round); `last` is the
 * variant dealt last time. Returns {choice, bag} (the bag left after this deal). The choice is never `last`.
 */
export function pick(seed, n, variants, last, bag) {
  const all = Array.from(variants || []);
  if (!all.length) return { choice: '', bag: [] };
  let left = Array.isArray(bag) && bag.length ? bag.filter((v) => all.includes(v)) : [];
  if (!left.length) left = all.slice();
  let pool = left.filter((v) => v !== last);
  if (!pool.length) { left = all.slice(); pool = left.filter((v) => v !== last); } // only `last` was left
  if (!pool.length) return { choice: all[0], bag: [] }; // a family of one
  const r = rng(hash(String(seed) + ':' + n + ':' + all.join('|')))();
  const choice = pool[Math.min(pool.length - 1, Math.floor(r * pool.length))];
  return { choice, bag: left.filter((v) => v !== choice) };
}

/** A dealer per family for one chapter: deal(family, n) -> a variant, in play order. */
export function dealer(seed) {
  const st = {};
  return (family, n) => {
    const s = st[family] || (st[family] = { last: '', bag: [] });
    const got = pick(seed, n, FAMILIES[family], s.last, s.bag);
    s.last = got.choice; s.bag = got.bag;
    return got.choice;
  };
}

// ---- the scene at a line -------------------------------------------------------------------------------------------
const cuesOf = (line) => (line && Array.isArray(line.cues) ? line.cues : []);
const flowOf = (flows, page) => (flows && flows[page] && Array.isArray(flows[page].nodes) ? flows[page] : null);
const hasNode = (flow, id) => !!flow && flow.nodes.some((x) => x && x.id === id);
const kindOf = (flow, id) => { const x = flow && flow.nodes.find((y) => y && y.id === id); return x ? x.kind : ''; };
/** Is there a connector between two boxes of this chart (either way round)? */
export function linked(flow, a, b) {
  return !!flow && Array.isArray(flow.edges) && flow.edges.some((e) => e && ((e.from === a && e.to === b) || (e.from === b && e.to === a)));
}
/** The connector told by an edge cue, "from>to"; null when it isn't a box pair of this chart. */
export function edgeOf(flow, target) {
  const m = /^([a-z0-9_]{1,40})>([a-z0-9_]{1,40})$/.exec(String(target || ''));
  return m && hasNode(flow, m[1]) && hasNode(flow, m[2]) ? [m[1], m[2]] : null;
}
/** "Rs2.9" or "10" or "1,000": {prefix, value, decimals, commas} or null. The Rupee sign is U+20B9. */
export function parseCount(target) {
  const m = /^(\u20b9?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)$/.exec(String(target || '').trim());
  if (!m) return null;
  const digits = m[2].replace(/,/g, ''), value = Number(digits);
  if (!Number.isFinite(value)) return null;
  const dot = digits.indexOf('.');
  return { prefix: m[1], value, decimals: dot < 0 ? 0 : digits.length - dot - 1, commas: m[2].includes(',') };
}
/** The words after the number in the spoken line ("10 files, and" -> "files"), at most 3, as the readout's unit. */
export function unitOf(text, target) {
  const num = String(target || '').replace(/^\u20b9/, '');
  if (!num) return '';
  const at = String(text || '').indexOf(num);
  if (at < 0) return '';
  const rest = String(text).slice(at + num.length).replace(/^\s+/, '');
  const m = /^([^.,;:!?()]{1,40})/.exec(rest);
  return m ? m[1].trim().split(/\s+/).slice(0, 3).join(' ') : '';
}

/** Where each page starts, and the first line index of every page in order. */
export function pagesOf(lines) {
  const order = [], first = {};
  (lines || []).forEach((l, i) => { if (l && !(l.page in first)) { first[l.page] = i; order.push(l.page); } });
  return { order, first };
}

/**
 * The stage at line `i`: {page, view ('title'|'plain'|'example'|'how'|'costs'|'fails'|'chart'), overview, now, kind,
 * done[], edge, count, run, frame, frames, last} -- `run` is the index where this view began, `frame` this line's place
 * in it (1-based) and `frames` the run's length; `last` true on the view's last line.
 */
export function sceneAt(lines, i, flows) {
  const L = lines || [], line = L[i];
  if (!line) return null;
  const page = line.page, flow = flowOf(flows, page);
  let j = i;
  while (j > 0 && L[j - 1] && L[j - 1].page === page) j -= 1;
  const sc = { page, view: flow ? 'chart' : 'title', overview: false, now: '', kind: '', done: [], edge: null, count: '',
    run: j, frame: 1, frames: 1, last: false, cue: false };
  const told = new Set();
  const tell = (id) => { if (sc.now && sc.now !== id) told.add(sc.now); };
  for (let k = j; k <= i; k += 1) {
    const before = sc.view;
    let shown = false;
    cuesOf(L[k]).forEach((c) => {
      if (!c || typeof c.target !== 'string') return;
      if (c.kind === 'show' && CARDS.has(c.target)) {
        shown = true; sc.view = c.target === 'how' && flow ? 'chart' : c.target;
        sc.overview = c.target === 'how' && !!flow;
        if (k === i) sc.cue = sc.overview;
      } else if (c.kind === 'show' && c.target === 'overview' && flow) {
        shown = true; sc.view = 'chart'; sc.overview = true; tell(''); sc.now = '';
        if (k === i) sc.cue = true;
      } else if (c.kind === 'node' && hasNode(flow, c.target)) {
        tell(c.target); sc.view = 'chart'; sc.overview = false; sc.now = c.target;
      } else if (c.kind === 'edge' && edgeOf(flow, c.target)) {
        const e = edgeOf(flow, c.target);
        tell(e[1]); told.add(e[0]); sc.view = 'chart'; sc.overview = false; sc.now = e[1];
        if (k === i) sc.edge = e;
      } else if (c.kind === 'count' && k === i && parseCount(c.target)) {
        sc.count = c.target;
      }
    });
    if (sc.view !== before || k === j || shown) sc.run = k;
  }
  sc.done = Array.from(told).filter((id) => id !== sc.now);
  sc.kind = kindOf(flow, sc.now);
  sc.frame = i - sc.run + 1;
  let end = i;
  while (L[end + 1] && L[end + 1].page === page && !viewChanges(L[end + 1], flow, sc.view)) end += 1;
  sc.frames = end - sc.run + 1;
  sc.last = end === i;
  return sc;
}
/** Does this line's cues move the stage to another view than `view`? */
function viewChanges(line, flow, view) {
  return cuesOf(line).some((c) => {
    if (!c) return false;
    if (c.kind === 'page') return true;
    if (c.kind === 'show') return c.target === 'overview' ? view !== 'chart' : (c.target === 'how' && flow ? 'chart' : c.target) !== view;
    if (c.kind === 'node') return hasNode(flow, c.target) && view !== 'chart';
    if (c.kind === 'edge') return !!edgeOf(flow, c.target) && view !== 'chart';
    return false;
  });
}

/**
 * The whole chapter's choreography, in play order: [{scene, fx}] with fx = {swap, reveal, enter, trace, accent, cam,
 * frame, count, alert, establish, pullback} (a variant name, true, or '' when that family has nothing to do here).
 */
export function plan(chapterId, lines, flows) {
  const deal = dealer(String(chapterId || ''));
  const out = [];
  let prev = null;
  (lines || []).forEach((line, i) => {
    const sc = sceneAt(lines, i, flows), n = Number.isInteger(line && line.n) ? line.n : i + 1;
    const fx = { swap: '', reveal: '', enter: '', trace: '', accent: '', cam: '', frame: '', count: '', alert: '',
      establish: false, pullback: false };
    const newPage = !prev || prev.page !== sc.page, newView = newPage || prev.view !== sc.view || sc.run === i;
    if (prev && newPage) fx.swap = deal('swap', n);
    if (sc.view !== 'chart' && newView) {
      fx.reveal = deal('reveal', n);
      if (prev && prev.view === 'chart' && !newPage) fx.pullback = true;
      if (sc.view === 'fails') fx.alert = deal('alert', n);
    }
    if (POINTS.has(sc.view) && (newView || sc.frame > 1)) fx.frame = deal('frame', n); // a frame or a point comes in
    if (sc.view === 'chart') {
      fx.establish = newView || sc.cue;
      if (sc.now && (!prev || prev.now !== sc.now || prev.page !== sc.page || newView)) {
        fx.enter = deal('enter', n);
        fx.cam = deal('cam', n);
        fx.accent = ACCENT_OF[sc.kind] || '';
        const pair = sc.edge || (prev && prev.page === sc.page && prev.now ? [prev.now, sc.now] : null);
        if (pair && linked(flowOf(flows, sc.page), pair[0], pair[1])) fx.trace = deal('trace', n);
      }
    }
    if (sc.count) fx.count = deal('count', n);
    out.push({ scene: sc, fx });
    prev = sc;
  });
  return out;
}

/** Sentences of a page section, without the code citations in brackets ("(`src/...`)"), each at most `max` chars. */
export function sentences(text, max = 220) {
  const plainText = String(text || '').replace(/\s*\((?:`[^`]{1,200}`(?:,\s*)?)+\)/g, '').replace(/([.!?]["\u201d]?)\./g, '$1')
    .replace(/\s+/g, ' ').trim();
  if (!plainText) return [];
  return plainText.split(/(?<=[.!?]["\u201d]?)\s+(?=[A-Z0-9"\u201c])/).map((s) => (s.length > max ? s.slice(0, max - 1).replace(/\s+\S*$/, '') + '\u2026' : s));
}
/** The first sentences of a section that fit in `max` characters (at least one). */
export function lead(text, max = 360) {
  const out = [];
  let len = 0;
  for (const s of sentences(text, max)) {
    if (out.length && len + s.length + 1 > max) break;
    out.push(s); len += s.length + 1;
  }
  return out.join(' ');
}
