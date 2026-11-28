// tests/fixtures/r8/strength_sequences.mjs -- R8.1 builder E (docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8): the
// strength and form coaches' synthetic sessions, run in Node by tests/test_r81_e_coaches.py and evals/r8_1/strength.py
// through tests/r8_fakes.run_node. Never a real person's data: every body here is made up from joint directions.
// Each scenario loads the REAL use-case module (src/jarvis/api/static/console-coach-<x>.js) behind a stand-in for the
// engine's JarvisVision.use, feeds it one body's pose Results the way the driver does (frozen plain data, `t` the
// engine's clock stand-in), and returns what a test checks: the module's tally and view, and the scenario's own truth
// (computed here from the script, never read from the module).
//   body(dirs, opts)        33 pose points from segment directions (degrees from straight down; + is forward, or the
//                           body's left in a front view), side view by default, `front: true` for a front view
//   repsSession(o)          row 132: an exercise's reps with a down time, an up time, pauses, noise, half reps
//   formSession(o)          row 220: squats or push-ups, each rep clean or with one fault
//   warmupSession(o)        row 218: the warm-up's moves (or wrong ones) in a row
//   bandSession(o)          row 219: band reps, the holding hand leaving the frame
//   plankSession(o)         row 222: a plank held, with sags and pikes injected
//   spaceCheck(o)           row 223: object lists in front of a body: clear, or the thing to move
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
export function res(task, data, t) {
  return freeze({ task, v: task === 'pose' ? 2 : 1, at: BASE_AT + Math.floor(t), ms: 20, device: 'phone', ok: true, data,
    quality: { light: 0.8, sharp: 0.8 }, t });
}
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const plainOut = (v) => JSON.parse(JSON.stringify(v));
const ease = (k) => (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, k)))) / 2; // a smooth start and stop
const lerp = (a, b, k) => a + (b - a) * k;
const v = (deg) => ({ x: Math.sin(deg * RAD), y: Math.cos(deg * RAD) }); // 0 straight down, 90 forward, 180 up
const add = (o, len, deg, side) => ({ x: o.x + len * v(deg).x * (side || 1), y: o.y + len * v(deg).y });

// ---- the body ------------------------------------------------------------------------------------------------------
const LEN = Object.freeze({ torso: 0.26, thigh: 0.2, shank: 0.2, upper: 0.14, fore: 0.13, head: 0.08, foot: 0.05 });
const STAND = Object.freeze({ torso: 180, neck: 180, thighs: [0, 0], shanks: [0, 0], uppers: [5, 5], fores: [5, 5] });

/** 33 points. dirs: torso, neck (hip->shoulder, shoulder->nose), thighs, shanks, uppers, fores ([left, right]); each a
 *  direction in degrees from straight down. Side view: the body faces +x, left and right overlap. Front view
 *  (`front`): directions open sideways, the body's left on the picture's right; `hipW`, `shW` the widths. */
export function body(dirs, opts) {
  const d = Object.assign({}, STAND, dirs || {});
  const o = Object.assign({ cx: 0.5, cy: 0.5, front: false, hipW: 0.09, shW: 0.16, noise: 0, seed: 7, visibility: 0.95, hide: [] }, opts || {});
  const r = rng(o.seed), n = () => (r() - 0.5) * 2 * o.noise;
  const hip = { x: o.cx, y: o.cy };
  const sh = add(hip, LEN.torso, d.torso);
  const nose = add(sh, LEN.head, d.neck);
  const pts = new Array(33).fill(null);
  const set = (i, p) => { pts[i] = { x: p.x + n(), y: p.y + n(), z: 0, visibility: o.hide.includes(i) ? 0.1 : o.visibility }; };
  for (let i = 0; i <= 10; i += 1) set(i, { x: nose.x + (o.front ? (i % 2 ? 0.01 : -0.01) : 0.01), y: nose.y - (i ? 0.01 : 0) });
  [0, 1].forEach((k) => { // k 0 the body's left, 1 its right
    const sgn = o.front ? (k === 0 ? 1 : -1) : 1;
    const hipK = { x: hip.x + (o.front ? sgn * o.hipW / 2 : 0), y: hip.y };
    const shK = { x: sh.x + (o.front ? sgn * o.shW / 2 : 0), y: sh.y };
    const knee = add(hipK, LEN.thigh, d.thighs[k], sgn), ankle = add(knee, LEN.shank, d.shanks[k], sgn);
    const elbow = add(shK, LEN.upper, d.uppers[k], sgn), wrist = add(elbow, LEN.fore, d.fores[k], sgn);
    set(11 + k, shK); set(13 + k, elbow); set(15 + k, wrist);
    [17, 19, 21].forEach((i) => set(i + k, { x: wrist.x + 0.01, y: wrist.y + 0.01 }));
    set(23 + k, hipK); set(25 + k, knee); set(27 + k, ankle);
    set(29 + k, { x: ankle.x - (o.front ? 0 : 0.02), y: ankle.y + 0.01 });
    set(31 + k, o.front ? { x: ankle.x + sgn * 0.01, y: ankle.y + 0.02 } : { x: ankle.x + LEN.foot, y: ankle.y + 0.01 });
  });
  return pts;
}

/** A rep's shape: 0 at the top (start), 1 at the bottom; down, pause at the bottom, up, pause at the top. */
function cycle(t, o) {
  const T = o.down + o.pauseBottom + o.up + o.pauseTop, k = ((t - o.lead) % T + T) % T, n = Math.floor((t - o.lead) / T);
  if (t < o.lead) return { x: 0, rep: -1 };
  if (k < o.down) return { x: ease(k / o.down), rep: n };
  if (k < o.down + o.pauseBottom) return { x: 1, rep: n };
  if (k < o.down + o.pauseBottom + o.up) return { x: 1 - ease((k - o.down - o.pauseBottom) / o.up), rep: n };
  return { x: 0, rep: n };
}

// each exercise: the body at depth x (0 top, 1 bottom) of a rep; `deep` 1 a full rep, less is a partial one
const SHAPES = Object.freeze({
  squat: (x, deep) => { const h = lerp(0, 95, x * deep); return { opts: {}, dirs: { torso: 180 - 0.45 * h, thighs: [h, h], shanks: [-0.15 * h, -0.15 * h], uppers: [h, h], fores: [h, h] }, drop: 0.2 * (1 - Math.cos(h * RAD)) }; },
  lunge: (x, deep) => { const k = x * deep; return { opts: {}, dirs: { torso: 180, thighs: [lerp(25, 85, k), lerp(-25, -10, k)], shanks: [lerp(25, 0, k), lerp(-25, -95, k)] }, drop: 0.18 * k }; },
  push_up: (x, deep) => { const e = lerp(5, 95, x * deep); return { opts: { cy: 0.62 }, dirs: { torso: 95, neck: 95, thighs: [-85, -85], shanks: [-85, -85], uppers: [-e * 0.6, -e * 0.6], fores: [e * 0.4, e * 0.4] }, drop: 0 }; },
  curl: (x, deep) => { const e = lerp(5, 140, x * deep); return { opts: {}, dirs: { uppers: [8, 8], fores: [8 + e, 8 + e] }, drop: 0 }; },
  shoulder_press: (x, deep) => { const k = (1 - x) * deep + (1 - deep); return { opts: {}, dirs: { uppers: [lerp(95, 175, k), lerp(95, 175, k)], fores: [lerp(180, 178, k), lerp(180, 178, k)] }, drop: 0 }; },
  jumping_jack: (x, deep) => { const k = x * deep, a = lerp(10, 170, k), l = lerp(3, 22, k); return { opts: { front: true }, dirs: { uppers: [a, a], fores: [a, a], thighs: [l, l], shanks: [l, l] }, drop: 0 }; },
});

export function pose(points) { return { points }; } // one body, the driver's one-body Result

/** o: {exercise, reps, down, up, pauseTop, pauseBottom, lead, fps, noise, deep (1 full; less a partial rep), halfEvery
 *  (every n-th rep only to `half` depth), seed, drop (every n-th frame missing), gapAfter + gap (a rest in seconds)} */
export async function repsSession(o) {
  const opt = Object.assign({ exercise: 'squat', reps: 10, down: 1.5, up: 1, pauseTop: 0.6, pauseBottom: 0.3, lead: 1.5,
    fps: 15, noise: 0.002, deep: 1, halfEvery: 0, half: 0.45, seed: 1, drop: 0, gapAfter: 0, gap: 0, tail: 1.5 }, o || {});
  const uc = await useCase('console-coach-reps.js', opt.base);
  const T = opt.down + opt.pauseBottom + opt.up + opt.pauseTop;
  const seconds = opt.lead + T * opt.reps + (opt.gapAfter ? opt.gap : 0) + opt.tail;
  let state, full = 0, i = 0;
  const shape = SHAPES[opt.exercise];
  for (let t = 0; t <= seconds; t = (++i) / opt.fps) {
    const shifted = opt.gapAfter && t > opt.lead + T * opt.gapAfter ? Math.max(opt.lead + T * opt.gapAfter - 1e-9, t - opt.gap) : t;
    const c = cycle(Math.min(shifted, opt.lead + T * opt.reps), opt);
    const halfRep = opt.halfEvery && c.rep >= 0 && (c.rep + 1) % opt.halfEvery === 0;
    const sh = shape(c.x, halfRep ? opt.half : opt.deep);
    if (opt.drop && i % opt.drop === opt.drop - 1) continue;
    const pts = body(sh.dirs, Object.assign({ cy: 0.45 + sh.drop, noise: opt.noise, seed: opt.seed * 7919 + i }, sh.opts));
    state = uc.onResult(res('pose', pose(pts), t), state);
  }
  for (let k = 0; k < opt.reps; k += 1) if (!(opt.halfEvery && (k + 1) % opt.halfEvery === 0) && opt.deep >= 1) full += 1;
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, truth: { reps: full, down: opt.down, up: opt.up, sets: opt.gapAfter ? 2 : 1 } });
}

/** One rep's body, given the rep's depth x and its fault. Squat faults: depth, knees_in (front view), back (side);
 *  push-up faults: depth, hips (sag), elbows (flare, front view). */
const FORM = Object.freeze({
  squat: (x, fault, front) => {
    const deep = fault === 'depth' ? 0.55 : 1, h = lerp(0, 100, x * deep);
    const lean = fault === 'back' ? 0.78 : 0.4;
    if (front) { // front view: thighs come towards the camera, so they look shorter; knees in when the fault is set
      const kin = fault === 'knees_in' ? lerp(0, 16, x) : lerp(0, 4, x);
      return { dirs: { torso: 180, thighs: [-kin + 8, -kin + 8], shanks: [kin - 4, kin - 4], uppers: [h * 0.9, h * 0.9], fores: [h * 0.9, h * 0.9] },
        opts: { front: true, cy: 0.45 + 0.18 * x * deep }, shorten: 1 - 0.7 * Math.sin(h * RAD) };
    }
    return { dirs: { torso: 180 - lean * h, thighs: [h, h], shanks: [-0.15 * h, -0.15 * h], uppers: [h, h], fores: [h, h] }, opts: { cy: 0.45 + 0.2 * (1 - Math.cos(h * RAD)) } };
  },
  push_up: (x, fault, front) => {
    const deep = fault === 'depth' ? 0.45 : 1, e = lerp(5, 95, x * deep);
    if (front) { // seen from his head: the hands stay on the floor, the shoulders come down to them; elbows tucked or out
      const ys = lerp(0.5, 0.72, x), spread = fault === 'elbows' ? lerp(0.01, 0.15, x) : lerp(0.01, 0.04, x);
      return { points: frontPushUp(ys, spread) };
    }
    const sag = fault === 'hips' ? 12 : 0; // the hips drop below the shoulder-ankle line: both ends rise from them
    return { dirs: { torso: 95 + sag, neck: 95, thighs: [-85 - sag, -85 - sag], shanks: [-85 - sag * 0.3, -85 - sag * 0.3], uppers: [-e * 0.6, -e * 0.6], fores: [e * 0.4, e * 0.4] }, opts: { cy: 0.62 + 0.04 * x } };
  },
});

function frontPushUp(ys, spread) { // a push-up from the front: hips and legs hidden behind the shoulders (foreshortened)
  const pts = new Array(33).fill(null), at = (x, y, vis) => ({ x, y, z: 0, visibility: vis === undefined ? 0.95 : vis });
  for (let i = 0; i <= 10; i += 1) pts[i] = at(0.5 + (i % 2 ? 0.01 : -0.01), ys - 0.05);
  [0, 1].forEach((k) => {
    const sg = k === 0 ? 1 : -1;
    pts[11 + k] = at(0.5 + sg * 0.08, ys); pts[13 + k] = at(0.5 + sg * (0.08 + spread), (ys + 0.8) / 2); pts[15 + k] = at(0.5 + sg * 0.1, 0.8);
    [17, 19, 21].forEach((i) => { pts[i + k] = at(0.5 + sg * 0.1, 0.81); });
    pts[23 + k] = at(0.5 + sg * 0.05, ys - 0.03, 0.6); pts[25 + k] = at(0.5 + sg * 0.05, ys - 0.06, 0.55);
    pts[27 + k] = at(0.5 + sg * 0.05, ys - 0.08, 0.55); pts[29 + k] = at(0.5 + sg * 0.05, ys - 0.085, 0.55); pts[31 + k] = at(0.5 + sg * 0.05, ys - 0.09, 0.55);
  });
  return pts;
}

/** o: {exercise, faults: [one per rep: '' clean, or the fault], front, fps, noise, seed, down, up} -> the per-rep tips */
export async function formSession(o) {
  const opt = Object.assign({ exercise: 'squat', faults: ['', '', ''], front: false, fps: 15, noise: 0.002, seed: 3, down: 1.4, up: 1, pauseTop: 0.6, pauseBottom: 0.3, lead: 1.5 }, o || {});
  const uc = await useCase('console-coach-form.js', opt.base);
  const T = opt.down + opt.pauseBottom + opt.up + opt.pauseTop, seconds = opt.lead + T * opt.faults.length + 1.5;
  let state, i = 0;
  for (let t = 0; t <= seconds; t = (++i) / opt.fps) {
    const c = cycle(Math.min(t, opt.lead + T * opt.faults.length), opt);
    const f = c.rep >= 0 && c.rep < opt.faults.length ? opt.faults[c.rep] : '';
    const sh = FORM[opt.exercise](c.x, f, opt.front);
    const r = rng(opt.seed * 104729 + i), jit = (q) => Object.assign({}, q, { x: q.x + (r() - 0.5) * 2 * opt.noise, y: q.y + (r() - 0.5) * 2 * opt.noise });
    const pts = sh.points ? sh.points.map(jit) : body(sh.dirs, Object.assign({ noise: opt.noise, seed: opt.seed * 104729 + i }, sh.opts));
    if (sh.shorten) [25, 26].forEach((k) => { const hp = pts[k - 2], kn = pts[k], an = pts[k + 2]; // a thigh towards the camera
      const nk = { x: kn.x, y: hp.y + (kn.y - hp.y) * sh.shorten }; pts[k] = Object.assign({}, kn, nk);
      pts[k + 2] = Object.assign({}, an, { y: an.y - (kn.y - nk.y) }); pts[k + 4] = Object.assign({}, pts[k + 4], { y: an.y - (kn.y - nk.y) + 0.01 }); pts[k + 6] = Object.assign({}, pts[k + 6], { y: an.y - (kn.y - nk.y) + 0.02 }); });
    state = uc.onResult(res('pose', pose(pts), t), state);
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, log: state ? state.log : [], truth: opt.faults });
}

// ---- row 218: the warm-up --------------------------------------------------------------------------------------------
const MOVES = Object.freeze({ // each: the body at k (0 rest, 1 the move's peak); side 0/1 alternates where it matters
  reach: (k) => ({ dirs: { uppers: [lerp(5, 172, k), lerp(5, 172, k)], fores: [lerp(5, 175, k), lerp(5, 175, k)] }, opts: { front: true } }),
  knees: (k, side) => { const a = lerp(0, 85, k); return { dirs: { thighs: side ? [0, a] : [a, 0], shanks: side ? [0, a - 85 * k] : [a - 85 * k, 0] }, opts: {} }; },
  squat: (k) => { const h = lerp(0, 95, k); return { dirs: { torso: 180 - 0.4 * h, thighs: [h, h], shanks: [-0.15 * h, -0.15 * h], uppers: [h, h], fores: [h, h] }, opts: { cy: 0.45 + 0.2 * (1 - Math.cos(h * RAD)) } }; },
  bend: (k, side) => ({ dirs: { torso: 180 + (side ? -1 : 1) * lerp(0, 28, k), neck: 180 + (side ? -1 : 1) * lerp(0, 30, k), uppers: [5, 5], fores: [5, 5] }, opts: { front: true } }),
  hinge: (k) => ({ dirs: { torso: 180 - lerp(0, 75, k), neck: 180 - lerp(0, 80, k), uppers: [lerp(5, 60, k), lerp(5, 60, k)], fores: [lerp(5, 60, k), lerp(5, 60, k)] }, opts: {} }),
  jack: (k) => { const a = lerp(10, 170, k), l = lerp(3, 22, k); return { dirs: { uppers: [a, a], fores: [a, a], thighs: [l, l], shanks: [l, l] }, opts: { front: true } }; },
  // wrong moves: none of them is a warm-up item
  calf: (k) => ({ dirs: {}, opts: { cy: 0.45 - 0.03 * k } }),
  wave: (k, side) => ({ dirs: { uppers: side ? [5, lerp(5, 120, k)] : [lerp(5, 120, k), 5], fores: side ? [5, lerp(5, 150, k)] : [lerp(5, 150, k), 5] }, opts: { front: true } }),
  curl: (k) => ({ dirs: { uppers: [8, 8], fores: [lerp(8, 150, k), lerp(8, 150, k)] }, opts: {} }),
  halfsquat: (k) => { const h = lerp(0, 45, k); return { dirs: { torso: 180 - 0.3 * h, thighs: [h, h], shanks: [-0.15 * h, -0.15 * h] }, opts: {} }; },
});

/** o: {moves: [[name, times], ...], fps, noise, seed, rep (seconds a move takes)} */
export async function warmupSession(o) {
  const opt = Object.assign({ moves: [['reach', 5]], fps: 15, noise: 0.002, seed: 5, rep: 1.6, rest: 0.5, base: undefined }, o || {});
  const uc = await useCase('console-coach-warmup.js', opt.base);
  let state, t = 0, i = 0;
  const feed = (sh) => { const pts = body(sh.dirs, Object.assign({ noise: opt.noise, seed: opt.seed * 31 + i }, sh.opts)); state = uc.onResult(res('pose', pose(pts), t), state); i += 1; t = i / opt.fps; };
  for (const [name, times] of opt.moves) {
    for (let n = 0; n < times; n += 1) {
      const end = t + opt.rep;
      while (t < end) feed(MOVES[name](Math.sin(Math.PI * (1 - (end - t) / opt.rep)), n % 2));
      const rest = t + opt.rest;
      while (t < rest) feed(MOVES[name](0, n % 2));
    }
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, done: state ? state.done : {} });
}

// ---- row 219: the band ---------------------------------------------------------------------------------------------
/** o: {reps, fps, noise, seed, outAt: [seconds the holding hand leaves the frame], outFor, blink (single frames lost)} */
export async function bandSession(o) {
  const opt = Object.assign({ reps: 10, fps: 15, noise: 0.002, seed: 9, rep: 2.4, lead: 1, outAt: [], outFor: 2, blink: 0, partial: 0 }, o || {});
  const uc = await useCase('console-coach-band.js', opt.base);
  let state, i = 0;
  const seconds = opt.lead + opt.rep * opt.reps + 1.5, prompts = [];
  let was = false;
  for (let t = 0; t <= seconds; t = (++i) / opt.fps) {
    const k = t < opt.lead || t > opt.lead + opt.rep * opt.reps ? 0 : Math.sin(Math.PI * (((t - opt.lead) % opt.rep) / opt.rep));
    const n = Math.floor((t - opt.lead) / opt.rep), part = opt.partial && (n + 1) % opt.partial === 0 ? 0.4 : 1;
    const e = lerp(10, 120, k * part); // a band row: the elbow bends and comes back
    const out = opt.outAt.some((a) => t >= a && t < a + opt.outFor), blink = opt.blink && i % opt.blink === 0;
    const pts = body({ uppers: [lerp(80, 30, k * part), lerp(80, 30, k * part)], fores: [80 + e * 0.3, 80 + e * 0.3] },
      { noise: opt.noise, seed: opt.seed * 13 + i, hide: out || blink ? [15, 16, 17, 18, 19, 20, 21, 22] : [] });
    state = uc.onResult(res('pose', pose(pts), t), state);
    const v = uc.summary(state).view.some((w) => w.kind === 'paused');
    if (v && !was) prompts.push(Math.round(t * 1000) / 1000);
    was = v;
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, prompts, truth: { reps: opt.partial ? opt.reps - Math.floor(opt.reps / opt.partial) : opt.reps } });
}

// ---- row 222: the plank ----------------------------------------------------------------------------------------------
/** o: {hold (seconds), lead, after, faults: [[from, to, 'sag'|'pike'], ...], fps, noise, seed} */
export async function plankSession(o) {
  const opt = Object.assign({ hold: 30, lead: 2, after: 3, faults: [], fps: 10, noise: 0.002, seed: 11, wobble: 0 }, o || {});
  const uc = await useCase('console-coach-plank.js', opt.base);
  let state, i = 0;
  const seconds = opt.lead + opt.hold + opt.after, r = rng(opt.seed);
  for (let t = 0; t <= seconds; t = (++i) / opt.fps) {
    const on = t >= opt.lead && t < opt.lead + opt.hold;
    const f = opt.faults.find(([a, b]) => t >= opt.lead + a && t < opt.lead + b);
    const dev = f ? (f[2] === 'sag' ? 12 : -14) : (r() - 0.5) * 2 * opt.wobble;
    const dirs = on
      ? { torso: 98 + dev, neck: 98, thighs: [-82 - dev, -82 - dev], shanks: [-82 - dev * 0.3, -82 - dev * 0.3], uppers: [0, 0], fores: [90, 90] }
      : { torso: 180 }; // standing, before and after
    const pts = body(dirs, { cy: on ? 0.62 : 0.45, noise: opt.noise, seed: opt.seed * 17 + i });
    state = uc.onResult(res('pose', pose(pts), t), state);
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, truth: { hold: opt.hold, sags: opt.faults.filter((x) => x[2] === 'sag').length, pikes: opt.faults.filter((x) => x[2] === 'pike').length } });
}

// ---- row 223: the space check ----------------------------------------------------------------------------------------
/** o: {things: [{label, score, box}] (the same list each look), looks, fps} -> the module's verdict view */
export async function spaceCheck(o) {
  const opt = Object.assign({ things: [], looks: 6, fps: 2 }, o || {});
  const uc = await useCase('console-coach-space.js', opt.base);
  let state;
  for (let i = 0; i < opt.looks; i += 1) {
    const t = i / opt.fps;
    state = uc.onResult(res('pose', pose(body({}, { cy: 0.45 })), t), state);
    state = uc.onResult(res('objects', { objects: opt.things }, t + 0.01), state);
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view });
}


const SESSIONS = Object.freeze({ repsSession, formSession, warmupSession, bandSession, plankSession, spaceCheck });
/** Many scenarios in one Node run: [[name, options], ...] -> their results, in order. */
export async function many(calls) {
  const out = [];
  for (const [name, o] of calls) out.push(await SESSIONS[name](o));
  return out;
}
