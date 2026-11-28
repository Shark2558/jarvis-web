// src/jarvis/api/static/console-vision-r8.js -- R8 builder A (docs/plans/r8-vision.md 4.2, D4, D6-D9, row 216; seam S3).
// The bodies of three engine tasks whose shells console-vision.js registers before its seal:
//   pose   v2  MediaPipe Pose Landmarker, up to 4 poses (lite by default; full when the setup test kept 15 frames a
//              second with it, D4: prefer()). The owner's D6, everyone in view: each body gets a `track` that follows
//              its torso centre from frame to frame (follow()). Data {bodies: [{track: 0..63, who: '', points: 33 x
//              {x, y, z, visibility}}]}: `who` is always '' here (no face is matched in a browser; the driver calls a
//              lone body 'me', and the home laptop names enrolled people)
//   hands  v1  MediaPipe Hand Landmarker, VIDEO mode, up to 2 hands. Data {hands: [{side, score, points: 21 x {x, y,
//              z}}]}. `side` is the person's own hand on a camera's raw (unmirrored) frame, as MediaPipe's Hand
//              Landmarker page says ("Left and Right handedness correspond to the subject's hands"); opts.mirrored
//              swaps it for a mirrored picture
//   digits v1  a seven-segment display's numbers (D7: a blood-pressure monitor's), read from one frame on a tap by
//              plain segment arithmetic (no model, so no licence to read): readDisplay(). Data {lines: [{value:
//              0..999, score}]} top to bottom, at most 4; a line read with any doubt scores below 0.8, which
//              jarvis.coach.bp.READ_MIN_SCORE never proposes. Its load reads a known display through this device's
//              own canvas first (a browser that blurs or changes canvas pixels is found, never trusted)
// D9's fallback for `objects` (SSD-MobileNet v1 from r13-1) needs the COCO ids mapped to the engine's 80 labels:
// cocoObjects() and COCO_IDS, for console-vision.js's objects task (wired at the I1 join).
// Imported on first use by console-vision.js (an ES module); called only from there and from the setup test
// (console-vision-check.js: prefer, preferred), never by a use case. Each call gets the engine's own kit (KIT8):
// NOT_INSTALLED, NO_PICTURE, POSE_MODEL, POSE_FULL_MODEL, HAND_MODEL, MP_FILES, look(frame, fn), qualityOf(src),
// drawn(src, side), clamp, model(name) (r7-1), model8(name) (r8-1), mp() (the MediaPipe runtime), sha256hex(bytes).
// Every model file's bytes are compared with SUMS8 (the manifests' sums, written by `scripts/vision_assets.py sums`)
// before use: a file that differs, or has no sum yet, is "not installed". This file reads no camera, sends nothing,
// keeps no frame and stores nothing. ASCII source.

const R7 = 'r7-1', R8 = 'r8-1';
// the pinned model files' SHA-256, by release/name (tests/test_r8_a_assets.py keeps them equal to the manifests)
const SUMS8 = Object.freeze(/*SUMS8-BEGIN*/{}/*SUMS8-END*/);
const POSES_MAX = 4, POINTS = 33, HANDS_MAX = 2, HAND_POINTS = 21, TRACK_MAX = 63;
const MISSED_MAX = 15; // frames a body may be unseen (about a second at 15 a second) and keep its track
const FOLLOW_MAX = 0.75; // a body keeps its track if its torso centre moved at most this many torso lengths
const SIZE_MIN = 0.02;
const CONFIDENCE = 0.5; // MediaPipe's detection, presence and tracking floors (its defaults)
const DIGIT_SIDE = 960; // a frame is read for digits at most this many pixels on its long side
const DIGIT_WORK = 420; // ...and the display (or the box he framed) at most this wide
const LINES_MAX = 4;
const r4 = (v) => Math.round(v * 10000) / 10000;
const cl = (v, lo, hi) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo);

async function pinned(kit, release, name, bytes) { // the bytes the manifest pinned, or "not installed"
  const want = SUMS8[release + '/' + name];
  if (!want || (await kit.sha256hex(bytes)) !== want) throw new Error(kit.NOT_INSTALLED);
  return bytes;
}
function stamp(s) { // VIDEO mode needs a timestamp that always rises
  s.ts = Math.max(Math.floor(performance.now()), s.ts + 1);
  return s.ts;
}
const close = (lm) => { if (lm) { try { lm.close(); } catch (_) {} } };

// ==== pose v2 ===========================================================================================================
const P = { lm: null, model: '', want: 'lite', ts: 0, follow: { tracks: [], next: 0 } };

/** D4: the pose model the next look uses: 'full' only where the setup test kept 15 a second with it. */
export function prefer(model) {
  const m = model === 'full' ? 'full' : 'lite';
  if (m !== P.want) { P.want = m; close(P.lm); P.lm = null; P.model = ''; }
  return P.want;
}
/** The pose model loaded now ('' before the first look). */
export function preferred() { return P.model; }

async function openPose(kit) {
  let model = P.want, bytes = null;
  if (model === 'full') {
    try { bytes = await pinned(kit, R8, kit.POSE_FULL_MODEL, await kit.model8(kit.POSE_FULL_MODEL)); } catch (e) {
      if (!(e && e.message === kit.NOT_INSTALLED)) throw e;
      model = 'lite'; P.want = 'lite'; // the full model has not arrived: lite, and no retry every frame
    }
  }
  if (!bytes) bytes = await pinned(kit, R7, kit.POSE_MODEL, await kit.model(kit.POSE_MODEL));
  const V = await kit.mp();
  const lm = await V.PoseLandmarker.createFromOptions(kit.MP_FILES, {
    baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', numPoses: POSES_MAX,
    minPoseDetectionConfidence: CONFIDENCE, minPosePresenceConfidence: CONFIDENCE, minTrackingConfidence: CONFIDENCE,
    outputSegmentationMasks: false,
  });
  close(P.lm);
  Object.assign(P, { lm, model, ts: 0, follow: { tracks: [], next: 0 } });
}

/** Pose v2's landmarker, from JARVIS's own pinned file. */
export async function loadPose(kit) { if (!P.lm || P.model !== P.want) await openPose(kit); }

/** 33 points in the engine's ranges (rounded), or null when the landmarker gave another count. */
export function bodyPoints(lms) {
  if (!Array.isArray(lms) || lms.length !== POINTS) return null;
  return lms.map((p) => ({ x: r4(cl(+p.x, -1, 2)), y: r4(cl(+p.y, -1, 2)), z: r4(cl(+p.z, -10, 10)),
    visibility: r4(cl(Number(p.visibility), 0, 1)) }));
}
/** A body's torso centre (shoulders 11, 12; hips 23, 24) and its torso length. */
export function centre(points) {
  const at = (i) => points[i] || { x: 0.5, y: 0.5 };
  const sx = (at(11).x + at(12).x) / 2, sy = (at(11).y + at(12).y) / 2, hx = (at(23).x + at(24).x) / 2, hy = (at(23).y + at(24).y) / 2;
  return { x: (sx + hx) / 2, y: (sy + hy) / 2, size: Math.max(SIZE_MIN, Math.hypot(sx - hx, sy - hy)) };
}
/** The tracks after one frame: each body keeps the track it is nearest to (nearest first, each track once; a track's
 *  place is where its last steps say it is now, and a body of another size is further away), a new body takes the next
 *  free number (counting on, so a number just let go is not handed to someone else at once), and a track unseen for
 *  MISSED_MAX frames is let go. Pure: state {tracks, next} in, {tracks, next, ids} out. */
export function follow(state, bodies) {
  const prev = (state && Array.isArray(state.tracks)) ? state.tracks : [];
  const seen = bodies.map(centre), pairs = [];
  seen.forEach((c, i) => prev.forEach((t, j) => {
    const k = t.missed + 1, px = t.x + (t.vx || 0) * k, py = t.y + (t.vy || 0) * k;
    const d = Math.hypot(c.x - px, c.y - py) / Math.max(c.size, t.size) + Math.abs(Math.log(c.size / t.size));
    if (d <= FOLLOW_MAX) pairs.push([d, i, j]);
  }));
  pairs.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  const ids = bodies.map(() => -1), was = bodies.map(() => null), taken = new Set();
  pairs.forEach(([, i, j]) => { if (ids[i] < 0 && !taken.has(j)) { ids[i] = prev[j].track; was[i] = prev[j]; taken.add(j); } });
  const held = new Set(prev.map((t) => t.track));
  let next = state && Number.isInteger(state.next) ? state.next : 0;
  ids.forEach((id, i) => {
    if (id >= 0) return;
    for (let k = 0; k <= TRACK_MAX; k += 1) {
      const n = (next + k) % (TRACK_MAX + 1);
      if (!held.has(n)) { ids[i] = n; held.add(n); next = (n + 1) % (TRACK_MAX + 1); return; }
    }
  });
  const step = (c, t) => { // the body's steps a frame, smoothed (none for a new body)
    if (!t) return { vx: 0, vy: 0 };
    const k = t.missed + 1;
    return { vx: r4(0.5 * (t.vx || 0) + (0.5 * (c.x - t.x)) / k), vy: r4(0.5 * (t.vy || 0) + (0.5 * (c.y - t.y)) / k) };
  };
  const tracks = seen.map((c, i) => ({ track: ids[i], x: c.x, y: c.y, size: c.size, missed: 0, ...step(c, was[i]) }))
    .filter((t) => t.track >= 0)
    .concat(prev.filter((t, j) => !taken.has(j) && t.missed < MISSED_MAX).map((t) => ({ ...t, missed: t.missed + 1 })));
  return { tracks, next, ids };
}
/** The landmarker's poses as the engine's bodies, each with the track that follows it (P's state moves on). */
function bodiesOf(landmarks) {
  const found = (Array.isArray(landmarks) ? landmarks : []).map(bodyPoints).filter(Boolean).slice(0, POSES_MAX);
  const f = follow(P.follow, found);
  P.follow = { tracks: f.tracks, next: f.next };
  return found.map((points, i) => ({ track: f.ids[i], who: '', points })).filter((b) => b.track >= 0);
}

/** One frame through pose v2 -> {data: {bodies}, quality}. */
export async function runPose(frame, opts, kit) {
  await loadPose(kit);
  return kit.look(frame, async (src) => {
    const quality = kit.qualityOf(src);
    const r = P.lm.detectForVideo(src.img, stamp(P));
    return { data: { bodies: bodiesOf(r && r.landmarks) }, quality };
  });
}

// ==== hands v1 ==========================================================================================================
const H = { lm: null, ts: 0 };

/** The hand landmarker, from JARVIS's own pinned file. */
export async function loadHands(kit) {
  if (H.lm) return;
  const bytes = await pinned(kit, R8, kit.HAND_MODEL, await kit.model8(kit.HAND_MODEL));
  const V = await kit.mp();
  H.lm = await V.HandLandmarker.createFromOptions(kit.MP_FILES, {
    baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', numHands: HANDS_MAX,
    minHandDetectionConfidence: CONFIDENCE, minHandPresenceConfidence: CONFIDENCE, minTrackingConfidence: CONFIDENCE,
  });
  H.ts = 0;
}
/** The landmarker's answer as the engine's hands: at most 2, each all 21 points and a known side, or left out. */
export function handsOf(r, mirrored) {
  const lms = (r && Array.isArray(r.landmarks)) ? r.landmarks : [];
  const sides = (r && (r.handedness || r.handednesses)) || [];
  const out = [];
  lms.slice(0, HANDS_MAX).forEach((pts, i) => {
    const cat = (Array.isArray(sides[i]) && sides[i][0]) || {};
    let side = String(cat.categoryName || '').toLowerCase();
    if (!Array.isArray(pts) || pts.length !== HAND_POINTS || (side !== 'left' && side !== 'right')) return;
    if (mirrored) side = side === 'left' ? 'right' : 'left';
    out.push({ side, score: r4(cl(Number(cat.score), 0, 1)),
      points: pts.map((p) => ({ x: r4(cl(+p.x, -1, 2)), y: r4(cl(+p.y, -1, 2)), z: r4(cl(+p.z, -10, 10)) })) });
  });
  return out;
}
/** One frame through the hand landmarker -> {data: {hands}, quality}. */
export async function runHands(frame, opts, kit) {
  await loadHands(kit);
  return kit.look(frame, async (src) => {
    const quality = kit.qualityOf(src);
    const r = H.lm.detectForVideo(src.img, stamp(H));
    return { data: { hands: handsOf(r, !!(opts && opts.mirrored)) }, quality };
  });
}

// ==== digits v1: a seven-segment display, by segment arithmetic =========================================================
// The display (or the box he framed) is made grey, its polarity found (dark segments on a light LCD, or bright ones on
// a dark LED), its background flattened (a wide max filter, so a shadow across it is not read as a segment), split at
// Otsu's threshold; pieces touching the edge (the monitor's bezel) or too small to be a segment are dropped. Rows of ink
// make the lines (labels and icons, much shorter than the digits, are left out); in each line the slant is found (the
// shear that opens the most empty columns), the digits are its column runs, and each digit is read from its seven
// segments' fill. A digit's score is its least sure segment; a line's, its least sure digit (half for anything that
// is not a digit, so it is never proposed).
//   a        segments: a top, b top right, c bottom right, d bottom, e bottom left, f top left, g middle
//  f b
//   g
//  e c
//   d
// each segment's region in the digit box, [u0, u1, v0, v1], for strokes tu wide (of the box's width) and tv tall (of
// its height): a horizontal segment's region is its own thickness, a vertical one's its own width
const regions = (tu, tv) => ({ a: [0.3, 0.7, 0, tv], g: [0.3, 0.7, 0.5 - tv / 2, 0.5 + tv / 2], d: [0.3, 0.7, 1 - tv, 1],
  f: [0, tu, 0.15, 0.42], b: [1 - tu, 1, 0.15, 0.42], e: [0, tu, 0.58, 0.85], c: [1 - tu, 1, 0.58, 0.85] });
export const SEGMENTS = regions(0.25, 0.14);
const ORDER = 'abcdefg';
const PATTERNS = { abcdef: 0, bc: 1, abdeg: 2, abcdg: 3, bcfg: 4, acdfg: 5, acdefg: 6, cdefg: 6, abc: 7, abcf: 7,
  abcdefg: 8, abcdfg: 9, abcfg: 9 }; // a 6 without its top, a 7 with its top left, a 9 without its bottom: as drawn
const FILL_ON = 0.3; // a region darker than this has a segment in it (the line's top and bottom, a narrow one)
const SEG_ON = 0.7, SEG_OFF = 0.08; // a lit segment fills its region at least this dark; an unlit one at most this
const COST_OK = 0.12, COST_MAX = 0.5, GAP_SURE = 0.12; // a digit's match: its misfit, and its lead on the next digit
const SHEARS = Array.from({ length: 17 }, (_, i) => (i - 4) * 0.025).sort((p, q) => Math.abs(p) - Math.abs(q)); // -0.1..0.3
const TURNS = Array.from({ length: 29 }, (_, i) => Math.tan(((i - 14) * 0.5 * Math.PI) / 180)) // held at -7..7 deg,
  .sort((p, q) => Math.abs(p) - Math.abs(q)); // level first: a turn must be clearly sharper to be taken
const MIN_CONTRAST = 0.12; // the ink's and the background's levels at least this far apart (of 255)
const TINY = 5; // pixels: a smaller piece of ink is a speck, never a segment (a small line's segment is a dozen)
// fractions of a line's height (or of the tallest row of ink, or of a digit's width, where said):
const GLYPH_MIN = 0.5; // anything shorter is not a digit (a dot, an icon; a one drawn inset is about 0.6)
const LABEL_GAP = 0.95, LABEL_DIGITS = 1.6; // the reading is one group: further left is a label (and of a digit's width)
const INNER_GAP = 0.07; // empty columns this narrow are a digit's own segment gaps
const PIECE_GAP = 0.15; // a digit's horizontals or a left-hand stroke this near the rest of it are one digit
const WIDE_MAX = 0.9, TOUCH = 1.3; // a wider glyph is two digits that touch (TOUCH: of the display's digit width)
const HOLE_MAX = 0.45; // a digit's two counters (inside its loops) are this empty at least
const HALF_GAP = 0.35; // of the shorter: two rows of ink this near may be the halves of one line
const HALVES = 0.65; // of the tallest row of ink: two rows both this short are halves, if they read as one line
const SURE = 0.8; // jarvis.coach.bp.READ_MIN_SCORE: a line read at least this surely is proposed
const THIN = 0.35, THIN_GAP = 0.3; // of the tallest row of ink: a thinner row (of segments) joins a line this near

/** Otsu's threshold of values 0..255: a value v is in the lower class when (v | 0) <= the threshold. */
export function otsu(v) {
  const hist = new Float64Array(256);
  for (let i = 0; i < v.length; i += 1) hist[Math.max(0, Math.min(255, v[i] | 0))] += 1;
  let all = 0, sum = 0;
  for (let i = 0; i < 256; i += 1) { all += hist[i]; sum += i * hist[i]; }
  let wB = 0, sB = 0, best = -1, at = 127;
  for (let t = 0; t < 256; t += 1) {
    wB += hist[t]; if (!wB) continue;
    const wF = all - wB; if (!wF) break;
    sB += t * hist[t];
    const mB = sB / wB, mF = (sum - sB) / wF, between = wB * wF * (mB - mF) * (mB - mF);
    if (between > best) { best = between; at = t; }
  }
  return at;
}
function maxLine(src, out, n, stride, off, k) { // a sliding max of width k along one line (van Herk / Gil-Werman)
  const g = new Float32Array(n), h = new Float32Array(n), r = k >> 1;
  for (let i = 0; i < n; i += 1) { const v = src[off + i * stride]; g[i] = i % k === 0 ? v : Math.max(g[i - 1], v); }
  for (let i = n - 1; i >= 0; i -= 1) { const v = src[off + i * stride]; h[i] = (i % k === k - 1 || i === n - 1) ? v : Math.max(h[i + 1], v); }
  for (let i = 0; i < n; i += 1) { const lo = Math.max(0, i - r), hi = Math.min(n - 1, i + r); out[off + i * stride] = Math.max(h[lo], g[hi]); }
}
function maxFilter(px, w, h, k) {
  const a = new Float32Array(w * h), b = new Float32Array(w * h);
  for (let y = 0; y < h; y += 1) maxLine(px, a, w, 1, y * w, k);
  for (let x = 0; x < w; x += 1) maxLine(a, b, h, w, x, k);
  return b;
}
/** The ink of a grey display: polarity, a flattened background, Otsu -> {bin (1 ink), soft (darkness 0..1, the
 *  ink's level 1, the background's 0)}; null when there is too little contrast. */
export function ink(px, w, h) {
  let dark = 0, n = 0;
  const t0 = otsu(px), x0 = Math.floor(w * 0.2), x1 = Math.ceil(w * 0.8), y0 = Math.floor(h * 0.2), y1 = Math.ceil(h * 0.8);
  for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) { n += 1; if ((px[y * w + x] | 0) <= t0) dark += 1; }
  const flip = dark > n / 2; // most of the middle is dark: bright segments on a dark display
  const v = flip ? px.map((p) => 255 - p) : px;
  const bg = maxFilter(v, w, h, Math.max(5, Math.round(Math.min(w, h) * 0.35)) | 1);
  const norm = new Float32Array(w * h);
  for (let i = 0; i < norm.length; i += 1) norm[i] = Math.min(255, (255 * v[i]) / Math.max(bg[i], 1));
  const t = otsu(norm);
  let lo = 0, nl = 0, hi = 0, nh = 0;
  for (let i = 0; i < norm.length; i += 1) { if ((norm[i] | 0) <= t) { lo += norm[i]; nl += 1; } else { hi += norm[i]; nh += 1; } }
  if (!nl || !nh || (hi / nh - lo / nl) / 255 < MIN_CONTRAST) return null;
  const bin = new Uint8Array(w * h), soft = new Float32Array(w * h), inkAt = lo / nl, bgAt = hi / nh;
  for (let i = 0; i < bin.length; i += 1) {
    bin[i] = (norm[i] | 0) <= t ? 1 : 0;
    soft[i] = Math.min(1, Math.max(0, (bgAt - norm[i]) / (bgAt - inkAt)));
  }
  return { bin, soft };
}
/** Pieces of ink touching the edge, or too small or too big to be a segment, removed (8-connected). */
export function clean(found, w, h) {
  const out = new Uint8Array(found.bin), soft = new Float32Array(found.soft), seen = new Uint8Array(w * h), stack = [];
  const tiny = TINY, huge = w * h * 0.25; // a small line's segment may be only a dozen pixels
  for (let s = 0; s < w * h; s += 1) {
    if (!out[s] || seen[s]) continue;
    const piece = []; let edge = false;
    seen[s] = 1; stack.push(s);
    while (stack.length) {
      const i = stack.pop(), x = i % w, y = (i - x) / w;
      piece.push(i);
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) edge = true;
      for (let dy = -1; dy <= 1; dy += 1) for (let dx = -1; dx <= 1; dx += 1) {
        const nx = x + dx, ny = y + dy, j = ny * w + nx;
        if (nx >= 0 && ny >= 0 && nx < w && ny < h && out[j] && !seen[j]) { seen[j] = 1; stack.push(j); }
      }
    }
    if (edge || piece.length < tiny || piece.length > huge) piece.forEach((i) => { out[i] = 0; soft[i] = 0; });
  }
  return { bin: out, soft };
}
/** The display held level: each column moved up or down by the turn that makes its rows of ink sharpest. Pure. */
export function level(img, w, h) {
  const cx = w / 2;
  let best = { k: 0, score: -1 };
  TURNS.forEach((k) => {
    const rows = new Float64Array(h * 3);
    for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) if (img.bin[y * w + x]) rows[h + y + Math.round(k * (x - cx))] += 1;
    let score = 0;
    for (let i = 0; i < rows.length; i += 1) score += rows[i] * rows[i];
    if (score > best.score * (best.score < 0 ? 1 : 1.003)) best = { k, score };
  });
  if (!best.k) return img;
  const bin = new Uint8Array(w * h), soft = new Float32Array(w * h);
  for (let x = 0; x < w; x += 1) {
    const dy = Math.round(best.k * (x - cx));
    for (let y = 0; y < h; y += 1) {
      const ty = y + dy;
      if (ty >= 0 && ty < h) { bin[ty * w + x] = img.bin[y * w + x]; soft[ty * w + x] = img.soft[y * w + x]; }
    }
  }
  return { bin, soft };
}
function runs(on, gapMax) { // [start, end] of the true stretches, a gap of at most gapMax closed
  const out = [];
  on.forEach((v, i) => {
    if (!v) return;
    const last = out[out.length - 1];
    if (last && i - last[1] - 1 <= gapMax) last[1] = i; else out.push([i, i]);
  });
  return out;
}
function bands(bin, w, h) { // stretches of inked rows: lines of digits, their halves, labels and icons
  const rows = new Array(h).fill(0);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) rows[y] += bin[y * w + x];
  const hh = (r) => r[1] - r[0] + 1, rs = runs(rows.map((c) => c >= Math.max(2, w * 0.01)), 0);
  const tall = Math.max(0, ...rs.map(hh));
  const bars = (r) => { // a row of segments only: every piece of it is a bar, much wider than the row is tall
    const cols = new Array(w).fill(0);
    for (let y = r[0]; y <= r[1]; y += 1) for (let x = 0; x < w; x += 1) cols[x] += bin[y * w + x];
    const widths = runs(cols.map((c) => c > 0), 1).map(([p, q]) => q - p + 1);
    return widths.length > 0 && widths.every((x) => x >= 1.2 * hh(r));
  };
  for (let moved = true; moved;) { // a row of top or bottom segments drawn apart from its digits joins the nearer line
    moved = false;
    for (let i = 0; i < rs.length && !moved; i += 1) {
      if (hh(rs[i]) >= THIN * tall || !bars(rs[i])) continue; // a clock or a date line keeps to itself
      const up = i > 0 ? rs[i][0] - rs[i - 1][1] - 1 : Infinity, down = i < rs.length - 1 ? rs[i + 1][0] - rs[i][1] - 1 : Infinity;
      const j = up <= down ? i - 1 : i + 1;
      if (Math.min(up, down) > THIN_GAP * tall) continue;
      rs.splice(Math.min(i, j), 2, [rs[Math.min(i, j)][0], rs[Math.max(i, j)][1]]); moved = true;
    }
  }
  return rs; // a line drawn with no middle segment comes as two halves: readDisplay joins them by reading
}

function sheared(img, w, y0, y1, s) { // the band's ink with each row moved back by its slant: (x, y) -> bool
  const mid = (y0 + y1) / 2, h = img.bin.length / w;
  const where = (x, y) => { const sx = Math.round(x + s * (mid - y)); return sx >= 0 && sx < w && y >= 0 && y < h ? y * w + sx : -1; };
  const at = (x, y) => { const i = where(x, y); return i >= 0 && img.bin[i] === 1; };
  at.dark = (x, y) => { const i = where(x, y); return i >= 0 ? img.soft[i] : 0; };
  return at;
}
function columns(at, w, y0, y1, pad) {
  const cols = new Array(w + 2 * pad).fill(0);
  for (let x = -pad; x < w + pad; x += 1) for (let y = y0; y <= y1; y += 1) if (at(x, y)) cols[x + pad] += 1;
  return cols;
}
function slant(img, w, lines) { // one display, one font: the shear that stands every line's strokes upright, found on
  let best = null; //                all lines together (the sharpest column profiles; the least slant on a tie)
  SHEARS.forEach((s) => {
    const sharp = lines.reduce((sum, [y0, y1]) => sum + columns(sheared(img, w, y0, y1, s), w, y0, y1, 0).reduce((t, c) => t + c * c * c, 0), 0);
    if (!best || sharp > best.sharp * 1.0001) best = { s, sharp };
  });
  return best ? best.s : 0;
}
function fill(at, x0, x1, y0, y1, box) { // how dark a segment's region is, 0..1 (the ink's own darkness is 1)
  const [u0, u1, v0, v1] = box, w = x1 - x0 + 1, h = y1 - y0 + 1;
  const a0 = Math.floor(x0 + u0 * w), a1 = Math.max(a0, Math.ceil(x0 + u1 * w) - 1);
  const b0 = Math.floor(y0 + v0 * h), b1 = Math.max(b0, Math.ceil(y0 + v1 * h) - 1);
  let n = 0, k = 0;
  for (let y = b0; y <= b1; y += 1) for (let x = a0; x <= a1; x += 1) { n += 1; k += at.dark(x, y); }
  return n ? k / n : 0;
}
function extent(at, x0, x1, y0, y1) { // the glyph's own top and bottom rows inside the band
  let top = -1, bottom = -1;
  for (let y = y0; y <= y1; y += 1) {
    let any = false;
    for (let x = x0; x <= x1 && !any; x += 1) any = at(x, y);
    if (any) { if (top < 0) top = y; bottom = y; }
  }
  return [top, bottom];
}
function stroked(at, x0, x1, y0, y1, v0, v1) { // the share of rows v0..v1 of the box with a dark pixel (0.5) in x0..x1
  const h = y1 - y0 + 1, b0 = Math.floor(y0 + v0 * h), b1 = Math.max(b0, Math.ceil(y0 + v1 * h) - 1);
  let n = 0, k = 0;
  for (let y = b0; y <= b1; y += 1) { let m = 0; for (let x = x0; x <= x1; x += 1) m = Math.max(m, at.dark(x, y)); n += 1; if (m >= 0.5) k += 1; }
  return n ? k / n : 0;
}
const CANDIDATES = Object.entries(PATTERNS).map(([key, digit]) => ({ digit, on: [...ORDER].map((x) => (key.includes(x) ? 1 : 0)) }));
const clamp01 = (v) => Math.min(1, Math.max(0, v));
/** The digit whose segments best fit seven region darknesses (abcdefg order) -> {digit, score}: its score is low when
 *  the fit is poor or another digit fits nearly as well. Pure. */
export function nearest(fills) {
  const best = new Map();
  CANDIDATES.forEach((c) => {
    const cost = c.on.reduce((sum, on, i) => sum + (on ? Math.max(0, SEG_ON - fills[i]) : Math.max(0, fills[i] - SEG_OFF)) ** 2, 0);
    if (!best.has(c.digit) || cost < best.get(c.digit)) best.set(c.digit, cost);
  });
  const ranked = [...best.entries()].sort((p, q) => p[1] - q[1]), [d, c1] = ranked[0], c2 = ranked[1][1];
  return { digit: d, score: clamp01((c2 - c1) / GAP_SURE) * clamp01((COST_MAX - c1) / (COST_MAX - COST_OK)) };
}
function digitOf(at, x0, x1, y0, y1, narrow, t) { // {digit, score}; t: the line's stroke thickness, px
  if (narrow) { // a one: a stroke down each half (the share of its rows with ink in them)
    const up = stroked(at, x0, x1, y0, y1, 0.22, 0.42), down = stroked(at, x0, x1, y0, y1, 0.58, 0.78); // inset strokes too
    const ok = up > 0.6 && down > 0.6;
    return { digit: ok ? 1 : null, score: ok ? clamp01(0.4 + (Math.min(up, down) - 0.6) * 4) : 0 };
  }
  const box = t ? regions(Math.min(0.35, Math.max(0.1, t / (x1 - x0 + 1))), Math.min(0.2, Math.max(0.06, t / (y1 - y0 + 1)))) : SEGMENTS;
  const holes = [[0.4, 0.6, 0.26, 0.34], [0.4, 0.6, 0.66, 0.74]].map((r) => fill(at, x0, x1, y0, y1, r));
  if (holes.some((f) => f > HOLE_MAX)) return { digit: null, score: 0 }; // a block, a mark: a digit's counters are empty
  return nearest([...ORDER].map((x) => fill(at, x0, x1, y0, y1, box[x])));
}
function edgeInk(at, glyphs, y0, y1) { // does any wide glyph have ink across its middle in rows y0..y1 (an a or a d)?
  return glyphs.some((g) => g.wide && fill(at, g.x0, g.x1, y0, y1, [0.3, 0.7, 0, 1]) > FILL_ON);
}
function tallest(at, x, y0, y1) { // the longest stretch of ink down one column
  let best = 0, n = 0;
  for (let y = y0; y <= y1; y += 1) { if (at(x, y)) { n += 1; best = Math.max(best, n); } else n = 0; }
  return best;
}
function pieces(sl, at, y0, y1, ew) { // the band's column runs, joined into digits and split where two digits touch
  const hb = y1 - y0 + 1, gaps = Math.max(1, Math.floor(INNER_GAP * hb)), near = PIECE_GAP * hb; // ew: a digit's width
  let ps = runs(sl.cols.map((c) => c >= Math.max(1, hb * 0.03)), gaps).map(([a, b]) => {
    let up = 0;
    for (let x = a - sl.pad; x <= b - sl.pad; x += 1) up = Math.max(up, tallest(at, x, y0, y1));
    return { x0: a - sl.pad, x1: b - sl.pad, stroke: up >= 0.25 * hb };
  });
  for (let i = 0; i < ps.length; i += 1) { // a digit drawn as separate segments: its horizontals join its strokes
    if (ps[i].stroke) continue;
    const r = ps[i + 1], l = ps[i - 1];
    if (r && r.x0 - ps[i].x1 - 1 <= near) { ps[i] = { x0: ps[i].x0, x1: r.x1, stroke: true }; ps.splice(i + 1, 1); }
    if (l && l.x1 - l.x0 + 1 <= 0.3 * hb && ps[i].x0 - l.x1 - 1 <= near) { ps[i] = { ...ps[i], x0: l.x0 }; ps.splice(i - 1, 1); i -= 1; }
  }
  const cut = (g) => { // wider than any digit: two that touch, parted at their thinnest column
    if (g.x1 - g.x0 + 1 <= (ew ? TOUCH * ew : WIDE_MAX * hb)) return [g];
    let at0 = -1, least = Infinity;
    for (let x = g.x0 + Math.ceil(0.08 * hb); x <= g.x1 - Math.ceil(0.08 * hb); x += 1) {
      const c = sl.cols[x + sl.pad]; if (c < least) { least = c; at0 = x; }
    }
    return at0 < 0 ? [g] : [...cut({ ...g, x1: at0 - 1 }), ...cut({ ...g, x0: at0 + 1 })];
  };
  ps = ps.flatMap(cut);
  for (let i = 0; i + 1 < ps.length; i += 1) { // a left-hand stroke (f, e) drawn apart from the rest of its digit
    const l = ps[i], r = ps[i + 1], gap = r.x0 - l.x1 - 1;
    if (l.x1 - l.x0 + 1 > 0.3 * hb || gap > near) continue;
    const up = stroked(at, l.x0, l.x1, y0, y1, 0.22, 0.42) > 0.6, down = stroked(at, l.x0, l.x1, y0, y1, 0.58, 0.78) > 0.6;
    const both = r.x1 - l.x0 + 1, half = up !== down; // a lone f or e; else both halves, which a one has too:
    if (half ? both > (ew ? TOUCH * ew : WIDE_MAX * hb) : !(up && ew && gap <= 1 && both <= 1.15 * ew)) continue; // a one
    ps.splice(i, 2, { x0: l.x0, x1: r.x1, stroke: true }); i -= 1;
  }
  return ps;
}
function stroke(at, glyphs, rows) { // the vertical strokes' width: the median run of ink along the given rows
  const widths = [];
  rows.forEach((y) => glyphs.forEach((g) => {
    let n = 0;
    for (let x = g.x0; x <= g.x1 + 1; x += 1) { if (x <= g.x1 && at(x, y)) n += 1; else if (n) { widths.push(n); n = 0; } }
  }));
  widths.sort((p, q) => p - q);
  return widths.length ? widths[widths.length >> 1] : 0;
}
function glyphsOf(img, w, y0, y1, s, ratio) { // one band's digits (column runs after the slant s; ratio: a digit's width
  const at = sheared(img, w, y0, y1, s), hb = y1 - y0 + 1, pad = Math.ceil(0.3 * hb); // over its height, once known)
  const sl = { s, pad, cols: columns(at, w, y0, y1, pad) };
  const glyphs = pieces(sl, at, y0, y1, ratio * hb).map(({ x0, x1 }) => {
    const [top, bottom] = extent(at, x0, x1, y0, y1);
    return { x0, x1, top, bottom, gh: bottom - top + 1 };
  }).filter((g) => g.top >= 0 && g.gh >= GLYPH_MIN * hb); // a one drawn inset is shorter than its line
  const apart = Math.max(LABEL_GAP * hb, ratio ? LABEL_DIGITS * ratio * hb : 0); // ones stand a digit apart
  const ink0 = glyphs.length ? [Math.min(...glyphs.map((g) => g.top)), Math.max(...glyphs.map((g) => g.bottom))] : [y0, y1];
  const t0 = stroke(at, glyphs, [0.28, 0.72].map((v) => Math.round(ink0[0] + v * (ink0[1] - ink0[0] + 1))));
  const digitLike = (g) => { // a one's stroke down both halves, or a glyph that reads surely as a digit
    const d = digitOf(at, g.x0, g.x1, ink0[0], ink0[1], g.x1 - g.x0 + 1 < 0.35 * hb, t0);
    return d.digit !== null && d.score >= SURE;
  };
  for (let i = glyphs.length - 1; i > 0; i -= 1) { // the reading is the right-hand group: a label or icon left of it goes
    if (glyphs[i].x0 - glyphs[i - 1].x1 > apart && !glyphs.slice(0, i).some(digitLike)) { glyphs.splice(0, i); break; }
  }
  if (!glyphs.length) return null;
  const top = Math.min(...glyphs.map((g) => g.top)), bottom = Math.max(...glyphs.map((g) => g.bottom)), lh = bottom - top + 1;
  glyphs.forEach((g) => { g.wide = g.x1 - g.x0 + 1 >= 0.35 * lh; });
  const wd = ratio ? ratio * lh : Math.max(0, ...glyphs.filter((g) => g.wide).map((g) => g.x1 - g.x0 + 1)); // a 3, a 7: no left side
  const full = glyphs.filter((g) => g.wide && [0.25, 0.75].some((v) => stroked(at, g.x0, g.x0 + Math.max(1, Math.round(0.2 * (g.x1 - g.x0 + 1))), top, bottom, v - 0.15, v + 0.15) > 0.6))
    .map((g) => (g.x1 - g.x0 + 1) / lh).filter((r) => r <= 0.8); // digits drawn from their left side to their right
  const edge = Math.max(1, Math.round(0.08 * lh));
  const t = stroke(at, glyphs, [0.28, 0.72].map((v) => Math.round(top + v * lh)));
  const sides = glyphs.map((g) => { // the right-hand verticals' height, where both are lit (not a 2, a 5 or a 6)
    const x0 = g.x1 - Math.max(1, Math.round(0.25 * (g.x1 - g.x0 + 1))) + 1;
    const both = stroked(at, x0, g.x1, top, bottom, 0.15, 0.4) > 0.6 && stroked(at, x0, g.x1, top, bottom, 0.6, 0.85) > 0.6;
    return both ? extent(at, x0, g.x1, y0, y1) : [-1, -1];
  }).filter(([a]) => a >= 0).map(([a, b]) => b - a + 1).sort((p, q) => p - q);
  return { at, glyphs, top, bottom, wd, t, full, side: sides.length ? sides[sides.length >> 1] : 0,
    hasTop: edgeInk(at, glyphs, top, top + edge), hasBottom: edgeInk(at, glyphs, bottom - edge, bottom) };
}
function readLine(L, top, bottom, width, doubt) { // a band's digits in the box top..bottom -> {value, score} or null
  const lh = bottom - top + 1, wd = Math.max(L.wd, width) || 0.55 * lh;
  let digits = '', score = 1, odd = false, plain = true;
  L.glyphs.forEach((g) => {
    const gw = g.x1 - g.x0 + 1, parts = gw > 1.7 * wd ? Math.round(gw / wd) : 1;
    for (let p = 0; p < parts; p += 1) {
      const b = g.x0 + Math.floor(((p + 1) * gw) / parts) - 1, narrow = parts === 1 && !g.wide && gw < 0.45 * wd;
      let a = g.x0 + Math.floor((p * gw) / parts);
      const left = [0.27, 0.72].some((v) => stroked(L.at, a, a + Math.max(1, Math.round(0.2 * (b - a + 1))), top, bottom, v - 0.12, v + 0.12) > 0.6);
      if (!narrow && !left && b - a + 1 < 0.9 * wd) a = b - Math.round(wd) + 1; // no left side (a 3, a 7): a whole digit wide
      let d = digitOf(L.at, a, b, top, bottom, narrow, L.t);
      if (narrow && d.digit === 1 && fill(L.at, b - Math.round(wd) + 1, a - 1, top, bottom, [0, 1, 0, 0.18]) > 0.15) {
        d = { digit: 1, score: Math.min(d.score, 0.5) }; // ink where a seven's top would be: a one is not sure
      }
      if (!narrow) plain = false;
      if (d.digit === null) { odd = true; continue; }
      digits += String(d.digit); score = Math.min(score, d.score);
    }
  });
  if (!digits || digits.length > 3) return null;
  if (odd) score = Math.min(score, 0.5); // something that is not a digit: never proposed
  if (doubt && !plain) score = Math.min(score, 0.7); // its height could not be known: never proposed
  return { value: Number(digits), score: Math.round(score * 1000) / 1000 };
}
/** A grey display (values 0..255, w x h) -> its lines top to bottom, at most 4: [{value, score}]. Pure.
 *  A line whose digits show no top segment or no bottom one (only 1, 4 and 7) is sized by the display's other lines:
 *  how tall a digit is beside its right-hand verticals, and how wide; with no such line it is read, but never sure. */
export function readDisplay(px, w, h) {
  if (!(w >= 16 && h >= 16) || px.length !== w * h) return [];
  const raw = ink(px, w, h);
  if (!raw) return [];
  const img = level(clean(raw, w, h), w, h);
  const mid = (xs) => { const v = xs.slice().sort((p, q) => p - q), k = v.length >> 1; return !v.length ? 0 : v.length % 2 ? v[k] : (v[k - 1] + v[k]) / 2; };
  const rows = bands(img.bin, w, h), s = slant(img, w, rows), hh = (r) => r[1] - r[0] + 1;
  const sure = (y0, y1) => { const L = glyphsOf(img, w, y0, y1, s, 0), got = L && readLine(L, L.top, L.bottom, 0, false); return !!got && got.score >= SURE; };
  const joined = [], rowsTall = Math.max(0, ...rows.map(hh));
  for (let i = 0; i < rows.length; i += 1) { // two halves of one line (no digit of it has a middle segment) join: they
    const a = rows[i], b = rows[i + 1], small = b ? Math.min(hh(a), hh(b)) : 0; // read surely together, not apart
    const halves = b && Math.max(hh(a), hh(b)) <= HALVES * rowsTall; // both much shorter than the big lines
    if (b && b[0] - a[1] - 1 <= HALF_GAP * small && Math.max(hh(a), hh(b)) <= 1.6 * small && sure(a[0], b[1])
      && (halves || !(sure(a[0], a[1]) && sure(b[0], b[1])))) { joined.push([a[0], b[1]]); i += 1; } else joined.push(a);
  }
  const tallest = Math.max(0, ...joined.map(hh)), lines0 = joined.filter((r) => hh(r) >= Math.max(8, tallest * 0.35));
  let found = lines0.map(([y0, y1]) => glyphsOf(img, w, y0, y1, s, 0)).filter(Boolean);
  const wideByTall = mid(found.flatMap((L) => L.full)); // one font: every line's digits as wide for their height
  if (wideByTall) found = lines0.map(([y0, y1]) => glyphsOf(img, w, y0, y1, s, wideByTall)).filter(Boolean);
  const whole = found.filter((L) => L.hasTop && L.hasBottom && L.side);
  const tallBySide = mid(whole.map((L) => (L.bottom - L.top + 1) / L.side));
  const lines = found.map((L) => {
    if (L.hasTop && L.hasBottom) return { L, line: readLine(L, L.top, L.bottom, 0, false) };
    if (!tallBySide || !L.side) return { L, line: readLine(L, L.top, L.bottom, 0, true) };
    const tall = Math.round(tallBySide * L.side), width = Math.round((wideByTall || 0.55) * tall), lh = L.bottom - L.top + 1;
    const grow = Math.max(0, Math.round((tall - lh) / 2));
    const sized = L.hasTop ? readLine(L, L.top, L.top + tall - 1, width, false)
      : L.hasBottom ? readLine(L, L.bottom - tall + 1, L.bottom, width, false) : readLine(L, L.top - grow, L.bottom + grow, width, false);
    return { L, line: sized };
  }).filter((x) => x.line);
  const kept = lines.slice().sort((p, q) => (q.L.bottom - q.L.top) - (p.L.bottom - p.L.top)).slice(0, LINES_MAX);
  return lines.filter((x) => kept.includes(x)).map((x) => x.line);
}
/** Grey (Rec. 601) of an RGBA picture, cropped to box {x, y, w, h} (0..1) and shrunk to at most DIGIT_WORK wide. */
export function grey(rgba, w, h, box) {
  const b = box && [box.x, box.y, box.w, box.h].every((v) => Number.isFinite(v)) ? box : { x: 0, y: 0, w: 1, h: 1 };
  const cx = Math.floor(cl(b.x, 0, 1) * w), cy = Math.floor(cl(b.y, 0, 1) * h);
  const cw = Math.max(1, Math.min(w - cx, Math.round(cl(b.w, 0, 1) * w))), ch = Math.max(1, Math.min(h - cy, Math.round(cl(b.h, 0, 1) * h)));
  const k = Math.max(1, Math.ceil(cw / DIGIT_WORK)), ow = Math.floor(cw / k), oh = Math.floor(ch / k);
  const px = new Float32Array(Math.max(0, ow * oh));
  for (let y = 0; y < oh; y += 1) for (let x = 0; x < ow; x += 1) {
    let s = 0;
    for (let j = 0; j < k; j += 1) for (let i = 0; i < k; i += 1) {
      const o = ((cy + y * k + j) * w + cx + x * k + i) * 4;
      s += 0.299 * rgba[o] + 0.587 * rgba[o + 1] + 0.114 * rgba[o + 2];
    }
    px[y * ow + x] = s / (k * k);
  }
  return { px, w: ow, h: oh };
}
// the load's own check: this display, drawn here and read back through the device's canvas
const SELF_LINES = [128, 82, 71];
/** A plain test display (dark segments on a light LCD) as RGBA, for the load's self-check. */
export function paint(values) {
  const W = 180, Hh = 200, rgba = new Uint8ClampedArray(W * Hh * 4).fill(235);
  const box = (x0, y0, x1, y1) => {
    for (let y = Math.round(y0); y < Math.round(y1); y += 1) for (let x = Math.round(x0); x < Math.round(x1); x += 1) {
      const o = (y * W + x) * 4; rgba[o] = 40; rgba[o + 1] = 45; rgba[o + 2] = 40;
    }
  };
  const ON = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
  values.forEach((v, row) => {
    const dh = row < 2 ? 52 : 34, dw = dh * 0.55, t = dh * 0.13, top = 12 + row * 64, digits = String(v).padStart(3, ' ');
    [...digits].forEach((ch, k) => {
      if (ch === ' ') return;
      const x = 168 - (3 - k) * (dw + 8), on = ON[Number(ch)];
      const mid = top + dh / 2, gp = Math.max(1, dh * 0.04), l = x + t + gp, r = x + dw - t - gp;
      const seg = { a: [l, top, r, top + t], d: [l, top + dh - t, r, top + dh], g: [l, mid - t / 2, r, mid + t / 2],
        f: [x, top + gp, x + t, mid - gp / 2], b: [x + dw - t, top + gp, x + dw, mid - gp / 2],
        e: [x, mid + gp / 2, x + t, top + dh - gp], c: [x + dw - t, mid + gp / 2, x + dw, top + dh - gp] };
      [...on].forEach((s) => box(...seg[s]));
    });
  });
  for (let i = 3; i < rgba.length; i += 4) rgba[i] = 255;
  return { rgba, w: W, h: Hh };
}
const D = { ok: false };
async function readFrame(frame, opts, kit) {
  return kit.look(frame, async (src) => {
    const quality = kit.qualityOf(src), s = kit.drawn(src, DIGIT_SIDE);
    const g = grey(s.ctx.getImageData(0, 0, s.w, s.h).data, s.w, s.h, opts && opts.box);
    return { data: { lines: readDisplay(g.px, g.w, g.h) }, quality };
  });
}
async function selfCheck(kit) {
  if (typeof document === 'undefined' || typeof ImageData === 'undefined') return false;
  const p = paint(SELF_LINES), c = document.createElement('canvas');
  c.width = p.w; c.height = p.h;
  try {
    c.getContext('2d').putImageData(new ImageData(p.rgba, p.w, p.h), 0, 0);
    const got = (await readFrame(c, {}, kit)).data.lines;
    return got.length === SELF_LINES.length && got.every((l, i) => l.value === SELF_LINES[i] && l.score >= 0.8);
  } finally { c.width = 0; c.height = 0; }
}

/** The seven-segment reader: no file to fetch; it proves itself on this device's canvas once. */
export async function loadDigits(kit) {
  if (D.ok) return;
  let ok = false;
  try { ok = await selfCheck(kit); } catch (_) { ok = false; }
  if (!ok) throw new Error(kit.NOT_INSTALLED);
  D.ok = true;
}
/** One frame (or photo) of the display -> {data: {lines}, quality}; opts.box: the part he framed (0..1). */
export async function runDigits(frame, opts, kit) {
  await loadDigits(kit);
  return readFrame(frame, opts || {}, kit);
}

// ==== D9's fallback for `objects`: SSD-MobileNet v1's COCO ids as the engine's 80 labels ================================
// The 80 labels in COCO id order (ids 12, 26, 29, 30, 45, 66, 68, 69, 71 and 83 are unused); equal to console-vision.js's
// OBJECT_LABELS and jarvis.vision.results.OBJECT_LABELS (tests/test_r8_a_engine.py).
export const COCO_IDS = Object.freeze([...Array.from({ length: 90 }, (_, i) => i + 1)]
  .filter((id) => ![12, 26, 29, 30, 45, 66, 68, 69, 71, 83].includes(id)));
const COCO_NAMES = ('person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign '
  + 'parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag tie suitcase '
  + 'frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard surfboard tennis_racket bottle '
  + 'wine_glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch '
  + 'potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave oven toaster sink '
  + 'refrigerator book clock vase scissors teddy_bear hair_drier toothbrush').split(' ');
export const COCO_LABELS = Object.freeze(COCO_NAMES);
/** SSD's outputs (boxes as ymin xmin ymax xmax, 0..1) -> the objects task's data list, best first, at most `max`. */
export function cocoObjects(classes, scores, boxes, count, min, max) {
  const out = [];
  for (let i = 0; i < Math.min(count, scores.length); i += 1) {
    const at = COCO_IDS.indexOf(Math.round(classes[i]));
    if (at < 0 || !(scores[i] >= min)) continue;
    const y0 = cl(boxes[i * 4], 0, 1), x0 = cl(boxes[i * 4 + 1], 0, 1), y1 = cl(boxes[i * 4 + 2], 0, 1), x1 = cl(boxes[i * 4 + 3], 0, 1);
    out.push({ label: COCO_LABELS[at], score: r4(cl(scores[i], 0, 1)),
      box: { x: r4(x0), y: r4(y0), w: r4(Math.max(0, x1 - x0)), h: r4(Math.max(0, y1 - y0)) } });
  }
  return out.sort((p, q) => q.score - p.score).slice(0, max);
}

/** The page left: close the landmarkers; the next look loads them again. */
export function unload() {
  close(P.lm); close(H.lm);
  P.lm = null; P.model = ''; H.lm = null;
  P.follow = { tracks: [], next: 0 };
}
