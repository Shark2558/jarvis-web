// src/jarvis/api/static/console-coach-bp.js -- R8 builder D, row 262's reading (docs/plans/r8-vision.md v8.0.4 D7, seam
// S26). PURE (held to the use-case guard, `export` aside): grey levels in, numbers out; no page, network, storage,
// camera or engine, and it keeps nothing.
//   readDisplay({w, h, px}) -> {lines: [{value, score}]}   the engine's `digits` data. The `digits` task (builder A's
//        body in console-vision-r8.js) draws one tapped frame -- the box the pane asks him to hold the monitor's screen
//        in -- turns it into w x h grey levels (0..255, row by row) and calls this; nothing else here sees a pixel.
//        The method is segment arithmetic, written here (no model, nothing to licence): the ink is the smaller of the
//        two tones Otsu's threshold splits (dark segments on a light screen, or lit ones on a dark screen); the stroke
//        is the median width of the ink's horizontal runs; text lines are bands of inked rows (a gap no wider than a
//        stroke is inside a digit); a band shorter than SMALL of the tallest (labels, the clock, icons) is left out;
//        each band's slant is the one, of -10 to 10 degrees, that makes its columns sharpest; digits are runs of inked
//        columns; a narrow full-height one is a 1; every other digit is read from its seven segments' ink, each
//        segment's certainty from how far its ink is from ON. A line that holds anything it cannot read as a digit is
//        left out, never guessed: three lines are needed for a proposal.
//   proposal(lines) -> {systolic, diastolic, pulse} | null   the same rule as jarvis.coach.bp.proposal_from_digits:
//        three lines top to bottom, each read with a score of at least READ_MIN_SCORE, the top number the larger;
//        else null. The desk pane shows it; he confirms or corrects; only then is it sent (POST /v1/coach/bp/readings).
export const READ_MIN_SCORE = 0.8;
const ON = 0.3; // a segment's share of inked pixels at which it counts as lit
const SMALL = 0.38; // a band shorter than this share of the tallest band is not a number line
const DIGIT_TALL = 0.75; // a mark in a line shorter than this share of the line (a label, an icon) is not a digit
const HALF = 5; // half a digit is at most this many strokes tall (a whole one is about seven)
const JOIN = 0.6; // inside a digit, columns of ink may be this many strokes apart (the corners between its segments)
const GROUP_GAP = 1.0; // marks further apart than this share of the digits' height are not one number
const ONE_WIDE = 1.7; // a mark no wider than this many of its line's strokes is a 1 (if it is inked top to bottom)
const LINES_MAX = 4;
const SLANTS = [-10, -7.5, -5, -2.5, 0, 2.5, 5, 7.5, 10];
// the segments a to g: [x from, x to, y from, y to], shares of the digit's box
const SEGMENTS = [[0.33, 0.67, 0, 0.15], [0.75, 1, 0.2, 0.38], [0.75, 1, 0.62, 0.8], [0.33, 0.67, 0.85, 1],
  [0, 0.25, 0.62, 0.8], [0, 0.25, 0.2, 0.38], [0.33, 0.67, 0.43, 0.57]];
const LEFT = [[0, 0.2, 0.18, 0.4], [0, 0.2, 0.6, 0.82]]; // a digit's left-hand segments (f, e): it fills its cell
const PATTERNS = new Map([['1111110', 0], ['0110000', 1], ['1101101', 2], ['1111001', 3], ['0110011', 4], ['1011011', 5],
  ['1011111', 6], ['0011111', 6], ['1110000', 7], ['1110010', 7], ['1111111', 8], ['1111011', 9], ['1110011', 9]]);

const within = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
export function proposal(lines) {
  if (!Array.isArray(lines) || lines.length !== 3 || lines.some((l) => !l || !(l.score >= READ_MIN_SCORE))) return null;
  const [s, d, p] = lines.map((l) => l.value);
  if (!within(s, 60, 260) || !within(d, 30, 160) || !within(p, 30, 220) || d >= s) return null;
  return Object.freeze({ systolic: s, diastolic: d, pulse: p });
}

function otsu(px) {
  const hist = new Map();
  px.forEach((v) => hist.set(v, (hist.get(v) || 0) + 1));
  let sum = 0;
  hist.forEach((c, v) => { sum += c * v; });
  let wB = 0, sumB = 0, best = -1, thr = 128;
  for (let v = 0; v < 256; v += 1) {
    const c = hist.get(v) || 0;
    wB += c; sumB += c * v;
    const wF = px.length - wB;
    if (wB && wF) {
      const gap = sumB / wB - (sum - sumB) / wF, between = wB * wF * gap * gap;
      if (between > best) { best = between; thr = v + 0.5; }
    }
  }
  return thr;
}

function median(vs) { const s = vs.slice().sort((a, b) => a - b); return s.length ? s.at(s.length >> 1) : 0; }

function strokeOf(ink, w, from, to) { // the median width of the ink's horizontal runs, in rows from..to
  const runs = [];
  for (let y = from; y < to; y += 1) {
    let run = 0;
    for (let x = 0; x <= w; x += 1) {
      const on = x < w && ink.at(y * w + x) === 1;
      if (on) run += 1;
      else { if (run >= 2) runs.push(run); run = 0; }
    }
  }
  return Math.max(1, median(runs));
}

function spans(counts, least, gap) { // runs of entries >= least, joined across gaps of at most `gap`
  const out = [];
  counts.forEach((c, i) => {
    if (c < least) return;
    const last = out.at(-1);
    if (last && i - last.to <= gap + 1) out.splice(-1, 1, { from: last.from, to: i });
    else out.push({ from: i, to: i });
  });
  return out.map((s) => ({ from: s.from, to: s.to + 1 }));
}

function sheared(ink, w, band, k) { // inked(x, y) for a band read with a slant k (x shift per row above the band's middle)
  const mid = (band.from + band.to) / 2;
  return (x, y) => {
    const sx = Math.round(x + (mid - y) * k);
    return sx >= 0 && sx < w && ink.at(y * w + sx) === 1 ? 1 : 0;
  };
}

function columns(at, w, band) {
  return Array.from({ length: w }, (_, x) => { let n = 0; for (let y = band.from; y < band.to; y += 1) n += at(x, y); return n; });
}

function slantOf(ink, w, band) { // the slant that makes the band's columns sharpest
  return SLANTS.reduce((b, deg) => {
    const k = Math.tan(deg * Math.PI / 180);
    const cols = columns(sheared(ink, w, band, k), w, band);
    const sharp = cols.reduce((n, c) => n + c * c, 0);
    return sharp > b.sharp ? { k, sharp } : b;
  }, { k: 0, sharp: -1 }).k;
}

function share(at, box, seg) {
  const [x0, x1, y0, y1] = seg;
  const xa = box.x + Math.floor(x0 * box.w), xb = box.x + Math.ceil(x1 * box.w);
  const ya = box.y + Math.floor(y0 * box.h), yb = box.y + Math.ceil(y1 * box.h);
  let n = 0, all = 0;
  for (let y = ya; y < yb; y += 1) for (let x = xa; x < xb; x += 1) { n += at(x, y); all += 1; }
  return all ? n / all : 0;
}

function digit(at, box, lineH, stroke) { // {value, score} or null
  if (box.w <= ONE_WIDE * stroke) {
    let rows = 0;
    for (let y = box.y; y < box.y + box.h; y += 1) { let any = 0; for (let x = box.x; x < box.x + box.w; x += 1) any |= at(x, y); rows += any; }
    const cover = rows / box.h;
    return box.h >= 0.8 * lineH && cover >= 0.7 ? { value: 1, score: Math.min(1, 0.4 + 0.6 * cover) } : null;
  }
  const fr = SEGMENTS.map((seg) => share(at, box, seg));
  const key = fr.map((f) => (f >= ON ? '1' : '0')).join('');
  if (!PATTERNS.has(key)) return null;
  const score = Math.min(...fr.map((f) => Math.min(1, 0.5 + Math.abs(f - ON) / ON)));
  return { value: PATTERNS.get(key), score };
}

function marks(at, band, stroke, w) { // the boxes of the inked column runs in a band, each its own ink's height
  const cols = columns(at, w, band);
  return spans(cols, 1, Math.ceil(JOIN * stroke)).map((sp) => {
    let y0 = band.to, y1 = band.from;
    for (let y = band.from; y < band.to; y += 1) {
      let any = 0;
      for (let x = sp.from; x < sp.to; x += 1) any |= at(x, y);
      if (any) { y0 = Math.min(y0, y); y1 = Math.max(y1, y + 1); }
    }
    return { x: sp.from, w: sp.to - sp.from, y: y0, h: Math.max(0, y1 - y0) };
  });
}

function group(boxes, lineH) { // the number: the run of close-set marks with the most in it (the rightmost of a tie)
  const runs = [];
  boxes.forEach((b) => {
    const last = runs.at(-1), prev = last && last.at(-1);
    if (prev && b.x - (prev.x + prev.w) <= GROUP_GAP * lineH) runs.splice(-1, 1, last.concat([b]));
    else runs.push([b]);
  });
  return runs.reduce((best, r) => (!best || r.length >= best.length ? r : best), null) || [];
}

function readLine(ink, w, band) {
  const k = slantOf(ink, w, band);
  const at = sheared(ink, w, band, k);
  const stroke = strokeOf(ink, w, band.from, band.to);
  const all = marks(at, band, stroke, w).filter((b) => b.w >= 0.5 * stroke);
  const tallest = Math.max(0, ...all.map((b) => b.h));
  const boxes = group(all.filter((b) => b.h >= DIGIT_TALL * tallest), tallest);
  if (!boxes.length || boxes.length > 3) return null;
  const lineH = median(boxes.map((b) => b.h));
  // a 3 or a 7 has no left-hand segments, so its box starts where they would end: it is read in a full cell, as wide as
  // the line's digits that have them (else its own width and a stroke more), right-aligned
  const wide = boxes.filter((b) => b.w > ONE_WIDE * stroke);
  const filled = wide.filter((b) => LEFT.some((seg) => share(at, b, seg) >= ON));
  const full = filled.length ? Math.max(...filled.map((b) => b.w)) : Math.max(0, ...wide.map((b) => b.w)) + 1.2 * stroke;
  const cells = boxes.map((b) => (b.w > ONE_WIDE * stroke && b.w < 0.9 * full
    ? Object.assign({}, b, { x: Math.round(b.x + b.w - full), w: Math.round(full) }) : b));
  const read = cells.map((b) => digit(at, b, lineH, stroke));
  if (read.some((d) => d === null)) return null;
  const value = read.reduce((n, d) => n * 10 + d.value, 0);
  return { value, score: Math.round(Math.min(...read.map((d) => d.score)) * 1000) / 1000, y: band.from };
}

function bandsOf(rows, stroke) { // inked row runs; a short gap joins two only when both are half a digit (a 1's halves)
  const raw = spans(rows, Math.max(1, Math.round(stroke / 2)), 0);
  const out = [];
  raw.forEach((b) => {
    const last = out.at(-1);
    const hl = last ? last.to - last.from : 0, hb = b.to - b.from;
    const halves = Math.max(hl, hb) <= HALF * stroke && Math.min(hl, hb) >= 0.5 * Math.max(hl, hb);
    if (last && b.from - last.to <= 1.2 * stroke && halves) out.splice(-1, 1, { from: last.from, to: b.to });
    else out.push(b);
  });
  return out;
}

/** The numbers a seven-segment display shows, top to bottom: the `digits` task's data. */
export function readDisplay(img) {
  const w = img && Number.isInteger(img.w) ? img.w : 0, h = img && Number.isInteger(img.h) ? img.h : 0;
  const raw = img && img.px && typeof img.px.length === 'number' ? img.px : [];
  if (w < 16 || h < 16 || raw.length !== w * h) return { lines: [] };
  const px = Uint8Array.from(raw, (v) => Math.max(0, Math.min(255, Math.round(v))));
  const thr = otsu(px);
  let below = 0;
  px.forEach((v) => { below += v < thr ? 1 : 0; });
  const darkInk = below <= px.length - below;
  const ink = Uint8Array.from(px, (v) => ((darkInk ? v < thr : v >= thr) ? 1 : 0));
  const stroke = strokeOf(ink, w, 0, h);
  const rows = Array.from({ length: h }, (_, y) => { let n = 0; for (let x = 0; x < w; x += 1) n += ink.at(y * w + x); return n; });
  const bands = bandsOf(rows, stroke);
  const tallest = Math.max(0, ...bands.map((b) => b.to - b.from));
  const lines = bands.filter((b) => b.to - b.from >= SMALL * tallest && b.to - b.from >= 3 * stroke)
    .map((b) => readLine(ink, w, b)).filter((l) => l !== null)
    .sort((a, b) => a.y - b.y).slice(0, LINES_MAX);
  return { lines: lines.map((l) => ({ value: l.value, score: l.score })) };
}
