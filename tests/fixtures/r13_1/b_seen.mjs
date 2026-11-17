// tests/fixtures/r13_1/b_seen.mjs -- R13.1 Part B (review B-1, finding 6): what an eye would SEE of a layer that is
// meant to be covered. A small software depth buffer in Node: from each direction of a list (orthographic, round the
// figure, within the camera's own range of heights) the covering parts are drawn into a depth buffer, then the
// covered layer's triangles are drawn against it; a fragment nearer the eye than everything else by more than EPS is
// a speck showing through. No GPU, no browser: the same answer on every machine.
const PX = 0.002, EPS = 0.0004; // a 2 mm pixel; 0.4 mm in front counts as seen
/** [yaw, elevation] in degrees. LEVEL: round the figure at eye height and a little above (the engine's own camera
 *  tilts from 11 degrees below to 50 above). ABOVE: looking down, where a real line of sight runs INTO a waistband. */
const ring = (step, el) => Array.from({ length: 360 / step }, (_, k) => [k * step, el]);
export const LEVEL = [...ring(45, -8), ...ring(45, 12)], ABOVE = ring(90, 38);

function basis(yaw, el) {
  const a = (yaw * Math.PI) / 180, e = (el * Math.PI) / 180;
  const v = [Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)]; // towards the eye
  const r = [Math.cos(a), 0, -Math.sin(a)], u = [v[1] * r[2] - v[2] * r[1], v[2] * r[0] - v[0] * r[2], v[0] * r[1] - v[1] * r[0]];
  return { v, r, u };
}

/** Draw triangles; `each(pixel, depth, y, triangle)` is called for every covered pixel centre (y: the fragment's
 *  height; triangle: its number in the part). */
function raster(part, b, box, each) {
  const { pos, index } = part, P = new Float64Array(9), Y = [0, 0, 0];
  for (let t = 0; t < index.length; t += 3) {
    for (let c = 0; c < 3; c++) {
      const i = index[t + c] * 3, x = pos[i], y = pos[i + 1], z = pos[i + 2];
      P[c * 3] = (x * b.r[0] + y * b.r[1] + z * b.r[2] - box.x0) / PX;
      P[c * 3 + 1] = (x * b.u[0] + y * b.u[1] + z * b.u[2] - box.y0) / PX;
      P[c * 3 + 2] = x * b.v[0] + y * b.v[1] + z * b.v[2];
      Y[c] = y;
    }
    const x0 = Math.max(0, Math.floor(Math.min(P[0], P[3], P[6]))), x1 = Math.min(box.w - 1, Math.ceil(Math.max(P[0], P[3], P[6])));
    const y0 = Math.max(0, Math.floor(Math.min(P[1], P[4], P[7]))), y1 = Math.min(box.h - 1, Math.ceil(Math.max(P[1], P[4], P[7])));
    const area = (P[3] - P[0]) * (P[7] - P[1]) - (P[6] - P[0]) * (P[4] - P[1]);
    if (Math.abs(area) < 1e-9) continue;
    for (let py = y0; py <= y1; py++) for (let px = x0; px <= x1; px++) {
      const cx = px + 0.5, cy = py + 0.5;
      const w0 = ((P[3] - cx) * (P[7] - cy) - (P[6] - cx) * (P[4] - cy)) / area, w1 = ((P[6] - cx) * (P[1] - cy) - (P[0] - cx) * (P[7] - cy)) / area, w2 = 1 - w0 - w1;
      if (w0 < 0 || w1 < 0 || w2 < 0) continue;
      each(py * box.w + px, w0 * P[2] + w1 * P[5] + w2 * P[8], w0 * Y[0] + w1 * Y[1] + w2 * Y[2], t / 3);
    }
  }
}

/** The triangles of a part that reach into a band of heights (the rest cannot hide anything there). */
function near(part, lo, hi) {
  const { pos, index } = part, keep = [];
  for (let t = 0; t < index.length; t += 3) {
    const a = pos[index[t] * 3 + 1], b = pos[index[t + 1] * 3 + 1], c = pos[index[t + 2] * 3 + 1];
    if (Math.max(a, b, c) >= lo && Math.min(a, b, c) <= hi) keep.push(index[t], index[t + 1], index[t + 2]);
  }
  return { pos, index: keep };
}

/** How much of `inner` ({pos, index}) shows past `covers` (a list of {pos, index}). `counts(triangle)` says which
 *  of its triangles are the layer that must stay covered (all of them when left out); the rest of `inner` still
 *  hides what is behind it (a shirt's back hides the tail tucked in at its front). Returns { cm2 (the worst view's
 *  area), view ([yaw, elevation]), views (how many see it), band (the lowest and highest height seen in that view) }. */
export function seen(inner, covers, counts = null, from = LEVEL) {
  let worst = 0, at = null, views = 0, band = null;
  let ymin = Infinity, ymax = -Infinity;
  for (let i = 1; i < inner.pos.length; i += 3) { ymin = Math.min(ymin, inner.pos[i]); ymax = Math.max(ymax, inner.pos[i]); }
  const close = covers.map((c) => near(c, ymin - 0.35, ymax + 0.35));
  for (const [yaw, el] of from) {
    const b = basis(yaw, el), box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    for (let i = 0; i < inner.pos.length; i += 3) {
      const sx = inner.pos[i] * b.r[0] + inner.pos[i + 2] * b.r[2], sy = inner.pos[i] * b.u[0] + inner.pos[i + 1] * b.u[1] + inner.pos[i + 2] * b.u[2];
      box.x0 = Math.min(box.x0, sx); box.x1 = Math.max(box.x1, sx); box.y0 = Math.min(box.y0, sy); box.y1 = Math.max(box.y1, sy);
    }
    box.w = Math.ceil((box.x1 - box.x0) / PX) + 1; box.h = Math.ceil((box.y1 - box.y0) / PX) + 1;
    const n = box.w * box.h, cover = new Float32Array(n).fill(-Infinity), front = new Float32Array(n).fill(-Infinity), high = new Float32Array(n), hit = new Uint8Array(n);
    for (const c of close) raster(c, b, box, (k, d) => { if (d > cover[k]) cover[k] = d; });
    raster(inner, b, box, (k, d, y, t) => { if (d > front[k]) { front[k] = d; high[k] = y; hit[k] = !counts || counts(t) ? 1 : 0; } });
    let px = 0, ylo = Infinity, yhi = -Infinity;
    for (let k = 0; k < n; k++) if (hit[k] && front[k] > cover[k] + EPS) { px++; ylo = Math.min(ylo, high[k]); yhi = Math.max(yhi, high[k]); }
    const cm2 = px * PX * PX * 1e4;
    if (cm2 > 0) views++;
    if (cm2 > worst) { worst = cm2; at = [yaw, el]; band = [+ylo.toFixed(3), +yhi.toFixed(3)]; }
  }
  return { cm2: +worst.toFixed(2), view: at, views, band };
}
