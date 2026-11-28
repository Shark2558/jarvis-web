// tests/fixtures/r8/flow_sequences.mjs -- R8.1 builder F (docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8): the flow
// and balance coaches' synthetic sessions, run in Node by tests/test_r81_f_coaches.py and evals/r8_1/flow.py through
// tests/r8_fakes.run_node. Never a real person's data: every body here is drawn from segment directions.
// Each scenario loads the REAL use-case module (src/jarvis/api/static/console-coach-<x>.js) behind a stand-in for the
// engine's JarvisVision.use, feeds it one body's pose Results the way the driver does (frozen plain data, `t` the
// engine's clock stand-in, `setup` the pane's choices: the contract line the report asks I1 for), and returns what a
// test checks: the module's tally and view, and the scenario's own truth (computed here from the script, never read
// from the module).
//   figure(dirs, opts)      33 pose points from segment directions (degrees: 0 straight down, 90 towards +x, 180 up);
//                           dirs {torso, neck, thigh: [left, right], shin, upper, fore}; side view by default (left and
//                           right overlap), `front: true` for a front view (the body's left on the picture's right)
//   yogaSession(o)          row 221: poses from the list held in a row, a rest between, holds timed by the script
//   balanceSession(o)       row 226: one-leg stands with scripted lifts, touch-downs and sway
//   pilatesSession(o)       row 231: the mat sequence's steps in a given order (swaps, skips)
//   taichiSession(o)        row 232: the form recorded once, then followed (tempo, a skipped step, injected jerks)
//   danceSession(o)         row 236: a routine recorded once, then danced in time or off by an offset, in four styles
const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const BASE_AT = 1764300000; // 28 Nov 2026, unix seconds
const LOADED = new Map();
const RAD = Math.PI / 180;

/** The use case a console-coach module registers, through a stand-in for JarvisVision.use. `base` (a directory path)
 *  loads the module from elsewhere: the eval's negative controls run a changed copy. */
export async function useCase(file, base) {
  const href = new URL(file, base ? new URL(`file://${base.replace(/\/?$/, '/')}`) : STATIC).href;
  if (LOADED.has(href)) return LOADED.get(href);
  const got = [];
  globalThis.JarvisVision = Object.freeze({ use: (u) => { got.push(u); return true; } });
  await import(href);
  if (got.length !== 1) throw new Error(`${file} registered ${got.length} use cases`);
  LOADED.set(href, got[0]);
  return got[0];
}

function freeze(v) {
  if (Array.isArray(v)) return Object.freeze(v.map(freeze));
  if (v && typeof v === 'object') return Object.freeze(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, freeze(x)])));
  return v;
}
/** One body's pose Result, as the driver hands it to a use case (data {points}, track, who); `setup` rides on it. */
export function res(points, t, setup) {
  const r = { task: 'pose', v: 2, at: BASE_AT + Math.floor(t), ms: 20, device: 'phone', ok: true, data: freeze({ points }),
    quality: Object.freeze({ light: 0.8, sharp: 0.8 }), t, track: 0, who: 'me' };
  if (setup) r.setup = setup; // already frozen once by the caller (the same object on every Result)
  return Object.freeze(r);
}
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const plainOut = (v) => JSON.parse(JSON.stringify(v));
const ease = (k) => (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, k)))) / 2;
const minJerk = (k) => { const c = Math.min(1, Math.max(0, k)); return c * c * c * (10 - 15 * c + 6 * c * c); };
const v = (deg) => ({ x: Math.sin(deg * RAD), y: Math.cos(deg * RAD) });
const wrap = (d) => ((d % 360) + 360) % 360;
const turn = (a, b) => ((b - a + 540) % 360) - 180; // the shortest signed turn from a to b

// ---- the body ------------------------------------------------------------------------------------------------------
const LEN = Object.freeze({ torso: 0.25, neck: 0.09, thigh: 0.22, shin: 0.22, upper: 0.15, fore: 0.14, foot: 0.05 });
const PAIRS = ['thigh', 'shin', 'upper', 'fore'];
export const STAND = Object.freeze({ torso: 180, neck: 180, thigh: [0, 0], shin: [0, 0], upper: [0, 0], fore: [0, 0] });

export function figure(dirs, opts) {
  const d = Object.assign({}, STAND, dirs || {});
  const o = Object.assign({ cx: 0.5, floor: 0.92, scale: 0.8, front: false, hipW: 0.08, shW: 0.15, noise: 0, seed: 7,
    visibility: 0.95, facing: 1, tilt: 0, anchor: -1, dx: 0, lens: {}, hide: [] }, opts || {});
  const k = o.scale, lenOf = (name, i) => LEN[name] * k * (o.lens[name] ? o.lens[name][i] : 1);
  const add = (p, len, deg) => ({ x: p.x + len * v(deg).x, y: p.y + len * v(deg).y });
  const H = { x: 0, y: 0 }, S = add(H, LEN.torso * k, d.torso), nose = add(S, LEN.neck * k, d.neck);
  const tv = v(d.torso), half = (w) => (o.front ? (w * k) / 2 : 0.003 * k);
  const across = (p, w, s) => ({ x: p.x - s * tv.y * half(w), y: p.y + s * tv.x * half(w) });
  const hips = [across(H, o.hipW, 1), across(H, o.hipW, -1)], shoulders = [across(S, o.shW, 1), across(S, o.shW, -1)];
  const knees = [0, 1].map((i) => add(hips[i], lenOf('thigh', i), d.thigh[i]));
  const ankles = [0, 1].map((i) => add(knees[i], lenOf('shin', i), d.shin[i]));
  const elbows = [0, 1].map((i) => add(shoulders[i], lenOf('upper', i), d.upper[i]));
  const wrists = [0, 1].map((i) => add(elbows[i], lenOf('fore', i), d.fore[i]));
  const toes = ankles.map((a, i) => add(a, LEN.foot * k, wrap(d.shin[i] + 90 * o.facing)));
  const heels = ankles.map((a, i) => add(a, 0.015 * k, wrap(d.shin[i] - 90 * o.facing)));
  const hand = (i, off) => add(wrists[i], 0.03 * k, wrap(d.fore[i] + off));
  const face = [nose, ...[1, 2, 3, 4, 5, 6].map((j) => ({ x: nose.x + (j <= 3 ? 0.01 : -0.01) * k, y: nose.y - 0.012 * k })),
    { x: nose.x + 0.02 * k, y: nose.y }, { x: nose.x - 0.02 * k, y: nose.y },
    { x: nose.x + 0.006 * k, y: nose.y + 0.015 * k }, { x: nose.x - 0.006 * k, y: nose.y + 0.015 * k }];
  let pts = [...face, ...shoulders, ...elbows, ...wrists, hand(0, 15), hand(1, -15), hand(0, 0), hand(1, 0), hand(0, -25),
    hand(1, 25), ...hips, ...knees, ...ankles, ...heels, ...toes];
  if (o.tilt) { const c = Math.cos(o.tilt * RAD), s = Math.sin(o.tilt * RAD); pts = pts.map((p) => ({ x: p.x * c - p.y * s, y: p.x * s + p.y * c })); }
  const ref = o.anchor >= 0 ? pts[o.anchor] : null;
  const ox = ref ? ref.x : (Math.min(...pts.map((p) => p.x)) + Math.max(...pts.map((p) => p.x))) / 2;
  const oy = ref ? ref.y : Math.max(...pts.map((p) => p.y));
  const r = rng(o.seed), n = () => (r() - 0.5) * 2 * o.noise;
  return pts.map((p, i) => ({ x: p.x - ox + o.cx + o.dx + n(), y: p.y - oy + o.floor + n(), z: 0,
    visibility: o.hide.includes(i) ? 0.1 : o.visibility }));
}

/** Directions between two shapes, k 0..1 along the shortest turn of each. */
export function blend(a, b, k) {
  const one = (x, y) => wrap(x + turn(x, y) * k);
  const out = { torso: one(a.torso, b.torso), neck: one(a.neck, b.neck) };
  PAIRS.forEach((p) => { out[p] = [one(a[p][0], b[p][0]), one(a[p][1], b[p][1])]; });
  return out;
}
function full(d) { return Object.assign({}, STAND, d); }
/** The same shape seen from the other side (side view) or with left and right swapped (front view). */
export function mirror(d, front) {
  const f = full(d), out = { torso: wrap(360 - f.torso), neck: wrap(360 - f.neck) };
  PAIRS.forEach((p) => { const m = [wrap(360 - f[p][0]), wrap(360 - f[p][1])]; out[p] = front ? [m[1], m[0]] : m; });
  return out;
}
function jitter(d, r, j) {
  const f = full(d), w = (x) => wrap(x + (r() - 0.5) * 2 * j), out = { torso: w(f.torso), neck: w(f.neck) };
  PAIRS.forEach((p) => { out[p] = [w(f[p][0]), w(f[p][1])]; });
  return out;
}

// ---- row 221: yoga -------------------------------------------------------------------------------------------------
// Each pose as a person holds it (this file's own description of the shapes, never the module's rules).
const FRONT = true, SIDE = false;
export const YOGA = Object.freeze({
  mountain: { front: FRONT, d: { upper: [6, 354], fore: [3, 357] } },
  tree: { front: FRONT, d: { thigh: [50, 0], shin: [250, 0], upper: [165, 195], fore: [200, 160] } },
  warrior_i: { front: SIDE, d: { torso: 182, neck: 178, thigh: [70, 325], shin: [0, 325], upper: [178, 178], fore: [180, 180] } },
  warrior_ii: { front: FRONT, d: { thigh: [70, 330], shin: [10, 330], upper: [90, 270], fore: [90, 270] } },
  triangle: { front: FRONT, d: { torso: 120, neck: 115, thigh: [35, 325], shin: [35, 325], upper: [0, 180], fore: [0, 180] } },
  chair: { front: SIDE, d: { torso: 150, neck: 145, thigh: [60, 60], shin: [345, 345], upper: [160, 160], fore: [165, 165] } },
  cobra: { front: SIDE, d: { torso: 140, neck: 150, thigh: [270, 270], shin: [270, 270], upper: [30, 30], fore: [330, 330] } },
  child: { front: SIDE, d: { torso: 80, neck: 60, thigh: [75, 75], shin: [270, 270], upper: [90, 90], fore: [90, 90] } },
  downward_dog: { front: SIDE, d: { torso: 50, neck: 40, thigh: [330, 330], shin: [330, 330], upper: [45, 45], fore: [45, 45] } },
  bridge: { front: SIDE, d: { torso: 300, neck: 285, thigh: [110, 110], shin: [20, 20], upper: [90, 90], fore: [90, 90] } },
  cat_cow: { front: SIDE, d: { torso: 90, neck: 120, thigh: [0, 0], shin: [270, 270], upper: [0, 0], fore: [0, 0] },
    lens: { upper: [0.8, 0.8], fore: [0.75, 0.75] } },
  seated_forward_bend: { front: SIDE, d: { torso: 115, neck: 100, thigh: [90, 90], shin: [90, 90], upper: [75, 75], fore: [85, 85] } },
});
export const YOGA_NAMES = Object.keys(YOGA);
const REST = Object.freeze({ thigh: [8, 352], shin: [0, 0], upper: [30, 330], fore: [300, 60] }); // hands on hips: no pose

function poseShape(name, r, j, flip) {
  const p = YOGA[name], d = jitter(p.d, r, j);
  return { d: flip ? mirror(d, p.front) : d, front: p.front, lens: p.lens || {} };
}

/** A session through `poses`, each held `hold` s (a number or a list), `move` s to and from a rest between.
 *  o: {poses, hold, move, rest, fps, noise, seed, jitter, tilt, scale, flip, base} -> holds found against the script */
export async function yogaSession(o) {
  const opt = Object.assign({ poses: ['tree'], hold: 8, move: 1.5, rest: 2, fps: 10, noise: 0.003, seed: 1, jitter: 6,
    tilt: 0, scale: 0.8, flip: false }, o || {});
  const uc = await useCase('console-coach-yoga.js', opt.base);
  const r = rng(opt.seed * 977 + 13);
  const rest = { d: full(REST), front: FRONT, lens: {} };
  const plan = []; // [{shape, from, to, hold: bool, pose}]
  let t = 0;
  plan.push({ a: rest, b: rest, from: t, to: (t += opt.rest), pose: '' });
  opt.poses.forEach((name, i) => {
    const shape = poseShape(name, r, opt.jitter, Array.isArray(opt.flip) ? opt.flip[i] : opt.flip);
    const hold = Array.isArray(opt.hold) ? opt.hold[i] : opt.hold;
    plan.push({ a: rest, b: shape, from: t, to: (t += opt.move), pose: '', move: true });
    plan.push({ a: shape, b: shape, from: t, to: (t += hold), pose: name });
    plan.push({ a: shape, b: rest, from: t, to: (t += opt.move), pose: '', move: true });
    plan.push({ a: rest, b: rest, from: t, to: (t += opt.rest), pose: '' });
  });
  let state;
  for (let i = 0; i <= Math.round(t * opt.fps); i += 1) {
    const now = i / opt.fps, seg = plan.find((p) => now < p.to) || plan.at(-1);
    const k = seg.move ? ease((now - seg.from) / (seg.to - seg.from)) : 1;
    const shape = seg.move ? (k < 0.5 ? seg.a : seg.b) : seg.b;
    const d = blend(full(seg.a.d), full(seg.b.d), k);
    const pts = figure(d, { front: shape.front, lens: shape.lens, noise: opt.noise, seed: opt.seed * 100000 + i, tilt: opt.tilt, scale: opt.scale });
    state = uc.onResult(res(pts, now), state);
  }
  const truth = plan.filter((p) => p.pose).map((p) => ({ pose: p.pose, from: p.from, s: p.to - p.from }));
  const found = (state && state.log) || [];
  const matched = truth.map((tr) => { // the module's hold overlapping this scripted hold the most
    const over = (h) => Math.max(0, Math.min(tr.from + tr.s, h.from + h.s) - Math.max(tr.from, h.from));
    const best = found.reduce((b, h) => (over(h) > (b ? over(b) : 0) ? h : b), null);
    return { pose: tr.pose, truth_s: tr.s, got: best ? best.pose : '', got_s: best ? best.s : 0 };
  });
  const sum = uc.summary(state);
  return plainOut({ matched, holds: found.length, tally: sum.tally, view: sum.view });
}

// ---- row 226: single-leg balance -------------------------------------------------------------------------------------
/** o: {stand: 'left'|'right', holds: [[lift_s, down_s], ...], seconds, sway (degrees of lean), fps, noise, seed, front}.
 *  The body leans about the standing ankle; the free foot rises over `lift` s and comes down over the same. */
export async function balanceSession(o) {
  const opt = Object.assign({ stand: 'left', holds: [[2, 17]], seconds: 20, sway: 1, fps: 15, noise: 0.003, seed: 1,
    front: false, lift: 0.4, base: undefined }, o || {});
  const uc = await useCase('console-coach-balance.js', opt.base);
  const sIdx = opt.stand === 'left' ? 0 : 1, fIdx = 1 - sIdx, phase = rng(opt.seed)() * 6;
  const lean = (t) => opt.sway * (Math.sin(2 * Math.PI * 0.7 * t + phase) + 0.6 * Math.sin(2 * Math.PI * 1.3 * t + 1 + phase));
  const raised = (t) => opt.holds.reduce((m, [a, b]) => Math.max(m, Math.min(ease((t - a + opt.lift / 2) / opt.lift),
    ease((b + opt.lift / 2 - t) / opt.lift))), 0);
  let state, tp = 0, fp = 0, fn = 0, tn = 0;
  for (let i = 0; i <= Math.round(opt.seconds * opt.fps); i += 1) {
    const t = i / opt.fps, up = raised(t), th = lean(t) * (up > 0.5 ? 1 : 0.2);
    const thigh = [0, 0], shin = [0, 0], lens = { thigh: [1, 1] };
    thigh[sIdx] = wrap(th); shin[sIdx] = wrap(th);
    if (opt.front) { thigh[fIdx] = wrap(th); shin[fIdx] = wrap(th); lens.thigh[fIdx] = 1 - 0.55 * up; } else { thigh[fIdx] = wrap(th + 70 * up); shin[fIdx] = wrap(th - 20 * up); }
    const d = { torso: wrap(180 + th), neck: wrap(180 + th), thigh, shin, upper: [wrap(25 + th), wrap(335 + th)], fore: [wrap(20 + th), wrap(340 + th)] };
    const pts = figure(d, { front: opt.front, lens, anchor: 27 + sIdx, noise: opt.noise, seed: opt.seed * 100000 + i });
    state = uc.onResult(res(pts, t), state);
    const truth = up >= 0.5, got = !!(state && state.on);
    if (truth && got) tp += 1; else if (got) fp += 1; else if (truth) fn += 1; else tn += 1;
  }
  const sum = uc.summary(state);
  const truthHolds = opt.holds.map(([a, b]) => b - a);
  return plainOut({ tp, fp, fn, tn, f1: tp ? (2 * tp) / (2 * tp + fp + fn) : 0, truth: truthHolds, log: (state && state.log) || [],
    tally: sum.tally, view: sum.view });
}

// ---- row 231: Pilates ------------------------------------------------------------------------------------------------
// The mat steps as a person does them, side on, lying with the head towards -x (this file's own shapes).
export const PILATES = Object.freeze({
  hundred: { torso: 245, neck: 235, thigh: [135, 135], shin: [135, 135], upper: [95, 95], fore: [95, 95] },
  roll_up: { torso: 112, neck: 100, thigh: [90, 90], shin: [90, 90], upper: [80, 80], fore: [85, 85] },
  leg_circle: { torso: 270, neck: 270, thigh: [180, 90], shin: [180, 90], upper: [90, 90], fore: [90, 90] },
  single_leg_stretch: { torso: 245, neck: 235, thigh: [215, 125], shin: [100, 125], upper: [130, 100], fore: [60, 100] },
  spine_stretch: { torso: 145, neck: 135, thigh: [90, 90], shin: [90, 90], upper: [90, 90], fore: [90, 90] },
  teaser: { torso: 220, neck: 210, thigh: [135, 135], shin: [135, 135], upper: [140, 140], fore: [140, 140] },
  swan: { torso: 135, neck: 150, thigh: [270, 270], shin: [270, 270], upper: [15, 15], fore: [345, 345] },
  shoulder_bridge: { torso: 300, neck: 285, thigh: [110, 110], shin: [20, 20], upper: [90, 90], fore: [90, 90] },
});
export const PILATES_ORDER = Object.freeze(Object.keys(PILATES));
const MAT = Object.freeze({ torso: 270, neck: 270, thigh: [90, 90], shin: [90, 90], upper: [90, 90], fore: [90, 90] }); // lying flat

/** This file's own reckoning of which performed steps are out of order: one that comes before a step already done. */
export function outOfOrder(done) {
  let far = -1;
  return done.filter((step) => { const k = PILATES_ORDER.indexOf(step); if (k < 0) return false; if (k < far) return true; far = Math.max(far, k); return false; });
}

/** o: {steps (names in the order done), hold, move, fps, noise, seed, jitter, base} */
export async function pilatesSession(o) {
  const opt = Object.assign({ steps: PILATES_ORDER, hold: 5, move: 1.5, fps: 10, noise: 0.003, seed: 1, jitter: 5 }, o || {});
  const uc = await useCase('console-coach-pilates.js', opt.base);
  const r = rng(opt.seed * 31 + 7), mat = full(MAT);
  const plan = [{ a: mat, b: mat, from: 0, to: 2, step: '' }];
  let t = 2, prev = mat;
  opt.steps.forEach((name) => {
    const shape = full(jitter(PILATES[name], r, opt.jitter));
    plan.push({ a: prev, b: shape, from: t, to: (t += opt.move), step: '', move: true });
    plan.push({ a: shape, b: shape, from: t, to: (t += opt.hold), step: name });
    plan.push({ a: shape, b: mat, from: t, to: (t += opt.move), step: '', move: true });
    plan.push({ a: mat, b: mat, from: t, to: (t += 1), step: '' });
    prev = mat;
  });
  let state;
  const tips = [];
  for (let i = 0; i <= Math.round(t * opt.fps); i += 1) {
    const now = i / opt.fps, seg = plan.find((p) => now < p.to) || plan.at(-1);
    const k = seg.move ? ease((now - seg.from) / (seg.to - seg.from)) : 1;
    const pts = figure(blend(seg.a, seg.b, k), { noise: opt.noise, seed: opt.seed * 100000 + i, scale: 0.8 });
    state = uc.onResult(res(pts, now), state);
    if (i % opt.fps === 0) uc.summary(state).view.filter((w) => w.kind === 'tip').forEach((w) => { if (!tips.includes(w.text)) tips.push(w.text); });
  }
  const sum = uc.summary(state);
  const truth = plan.filter((p) => p.step).map((p) => ({ step: p.step, s: p.to - p.from }));
  return plainOut({ truth, wrong: outOfOrder(opt.steps), log: (state && state.log) || [], tips, tally: sum.tally, view: sum.view });
}

// ---- rows 232 and 236: a routine recorded once, then followed -----------------------------------------------------
// Tai-chi: key postures (front view), joined by slow minimum-jerk moves with a short pause at each.
export const TAICHI = Object.freeze([
  { thigh: [10, 350], shin: [355, 5], upper: [10, 350], fore: [15, 345] }, // preparation
  { thigh: [15, 345], shin: [350, 10], upper: [95, 265], fore: [95, 265] }, // commence: arms rise
  { thigh: [22, 338], shin: [345, 15], upper: [40, 320], fore: [100, 260] }, // the hands sink, the knees bend
  { thigh: [32, 345], shin: [350, 5], upper: [125, 40], fore: [205, 60] }, // ward off
  { thigh: [15, 328], shin: [0, 350], upper: [60, 145], fore: [10, 205] }, // roll back
  { thigh: [26, 340], shin: [345, 12], upper: [100, 100], fore: [90, 90] }, // press
  { thigh: [36, 350], shin: [355, 5], upper: [150, 230], fore: [120, 240] }, // push
  { thigh: [20, 318], shin: [350, 345], upper: [90, 240], fore: [45, 190] }, // single whip
  { thigh: [10, 350], shin: [355, 5], upper: [10, 350], fore: [15, 345] }, // closing
]);

function taichiAt(t, opt) { // the form's directions at time t for this performance
  const keys = opt.keys, pause = opt.pause * opt.tempo, move = opt.move * opt.tempo;
  let at = opt.lead, prev = keys[0];
  for (let i = 1; i < keys.length; i += 1) {
    if (opt.skip.includes(i)) continue;
    if (t < at + move) return blend(prev, keys[i], minJerk((t - at) / move));
    at += move;
    if (t < at + pause) return keys[i];
    at += pause;
    prev = keys[i];
  }
  return prev;
}
function taichiLength(opt) { return opt.lead + (opt.keys.length - 1 - opt.skip.length) * (opt.move + opt.pause) * opt.tempo + opt.tail; }
function flick(d, t, jerks) { // an arm flicked 20 degrees off its path and back within 0.3 s at each jerk time
  const out = Object.assign({}, d, { upper: d.upper.slice(), fore: d.fore.slice() });
  jerks.forEach((j) => { const k = 1 - Math.abs(t - j) / 0.15; if (k > 0) { out.upper[0] = wrap(out.upper[0] + 20 * k); out.fore[0] = wrap(out.fore[0] + 25 * k); } });
  return out;
}

async function follow(file, shapeAt, seconds, opt, setup) {
  const uc = await useCase(file, opt.base);
  const frozen = setup ? freeze(setup) : undefined;
  let state;
  for (let i = 0; i <= Math.round(seconds * opt.fps); i += 1) {
    const t = i / opt.fps;
    const pts = figure(shapeAt(t), { front: true, noise: opt.noise, seed: opt.seed * 100000 + i, scale: opt.scale, dx: opt.dx });
    state = uc.onResult(res(pts, t, frozen), state);
  }
  return { uc, state, sum: uc.summary(state) };
}

/** o: {mode: 'record' | 'follow', reference (rows), routine, tempo, skip: [key numbers], jerks: [times], seed, noise,
 *  fps, personal (degrees of his own variation)} */
export async function taichiSession(o) {
  const opt = Object.assign({ mode: 'follow', routine: 1, tempo: 1, skip: [], jerks: [], seed: 1, noise: 0.003, fps: 15,
    personal: 4, move: 2.5, pause: 0.7, lead: 1.5, tail: 1.5, scale: 0.8, dx: 0, reference: null }, o || {});
  const r = rng(opt.seed * 53 + 1);
  opt.keys = TAICHI.map((k) => full(jitter(k, r, opt.personal)));
  const shape = (t) => flick(taichiAt(t, opt), t, opt.jerks);
  const setup = opt.mode === 'record' ? { record: true, routine: opt.routine } : (opt.reference ? { routine: opt.routine, angles: opt.reference } : undefined);
  const { state, sum } = await follow('console-coach-taichi.js', shape, taichiLength(opt), opt, setup);
  const performed = [...Array(TAICHI.length - 1).keys()].map((i) => i + 1).filter((i) => !opt.skip.includes(i));
  return plainOut({ steps: (state && state.steps) ? state.steps.length : 0, marks: (state && state.marks) || [], performed,
    tally: sum.tally, view: sum.view });
}

// Dance: four styles, each a seeded string of moves (never periodic), danced at its own pace.
export const STYLES = Object.freeze({
  lyrical: { beat: 2.0, snap: 1.0, arms: 70, legs: 8 }, // slow, flowing
  pop: { beat: 0.5, snap: 0.5, arms: 60, legs: 20 }, // a move on every beat
  bhangra: { beat: 0.5, snap: 0.6, arms: 45, legs: 25, up: true }, // arms high, knees bouncing
  classical: { beat: 1.2, snap: 0.2, arms: 55, legs: 15 }, // held shapes, quick changes
});
function danceMoves(style, seconds) {
  const st = STYLES[style], r = rng(style.length * 7919 + 17), moves = [];
  for (let t = 0; t <= seconds + 4; t += st.beat) {
    const a = () => (r() - 0.5) * 2 * st.arms, l = () => (r() - 0.5) * 2 * st.legs, base = st.up ? 150 : 70;
    moves.push({ torso: wrap(180 + (r() - 0.5) * 20), neck: 180, thigh: [wrap(l()), wrap(l())], shin: [wrap(l() / 2), wrap(l() / 2)],
      upper: [wrap(base + a()), wrap(360 - base + a())], fore: [wrap(base + a() * 1.3), wrap(360 - base + a() * 1.3)] });
  }
  return moves;
}
function danceAt(t, style, moves) {
  const st = STYLES[style], i = Math.max(0, Math.floor(t / st.beat)), into = t - i * st.beat;
  const a = moves[Math.min(i, moves.length - 1)], b = moves[Math.min(i + 1, moves.length - 1)];
  return blend(a, b, ease(into / (st.beat * st.snap)));
}

/** o: {mode, style, offset (s; + is late), seconds, reference, routine, seed, noise, fps, personal} */
export async function danceSession(o) {
  const opt = Object.assign({ mode: 'follow', style: 'pop', offset: 0, seconds: 40, routine: 1, seed: 1, noise: 0.003, fps: 15,
    personal: 4, scale: 0.8, dx: 0, reference: null }, o || {});
  const r = rng(opt.seed * 61 + 5);
  const moves = danceMoves(opt.style, opt.seconds).map((m) => full(jitter(m, r, opt.personal)));
  const shape = (t) => danceAt(Math.max(0, t - opt.offset), opt.style, moves);
  const setup = opt.mode === 'record' ? { record: true, routine: opt.routine } : (opt.reference ? { routine: opt.routine, angles: opt.reference } : undefined);
  const { state, sum } = await follow('console-coach-dance.js', shape, opt.seconds, opt, setup);
  return plainOut({ lag: state ? state.lag : null, tally: sum.tally, view: sum.view });
}

/** A recording's rows, as the pane would PUT them to /v1/coach/routines/{rid} (its chunks joined). */
export function rowsOf(out) {
  const rec = out && out.tally && out.tally.record;
  return rec && Array.isArray(rec.chunks) ? rec.chunks.flat() : [];
}
/** Record a routine, then follow it: [recording session, following session]. */
export async function recordThenFollow(fn, rec, fol) {
  const recorded = await (fn === 'dance' ? danceSession : taichiSession)(Object.assign({ mode: 'record' }, rec));
  const followed = await (fn === 'dance' ? danceSession : taichiSession)(Object.assign({ mode: 'follow', reference: rowsOf(recorded) }, fol));
  return [recorded, followed];
}
