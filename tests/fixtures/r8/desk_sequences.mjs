// tests/fixtures/r8/desk_sequences.mjs -- R8 builder D (docs/plans/r8-vision.md v8.0.4 sections 2.1 and 8): the desk
// coaches' synthetic sessions, run in Node by tests/test_r8_d_coaches.py and evals/r8/coaches.py through
// tests/r8_fakes.run_node. Never a real person's data: every hand, body, cup and display here is made up from numbers.
// Each scenario loads the REAL use-case module (src/jarvis/api/static/console-coach-<x>.js) behind a stand-in for the
// engine's JarvisVision.use, feeds it Results the way the engine's driver does (one state; frozen plain data), and
// returns what a test checks: the module's tally and view, and the scenario's own truth (computed here, never read
// from the module). Times are seconds; `t` rides on each Result (the engine's clock stand-in).
//   reactionGame(o)   row 224: a closed loop -- a hand reaches each lit circle after a scripted delay
//   breathSession(o)  row 238: shoulders rising and falling at a set rate, and the pacer's own timing
//   waterDay(o)       row 248: sips (a cup raised to the lips) and things that are not sips
//   rehabSession(o)   row 268: open-close, finger taps, thumb to each finger; the true bend range
//   reachSession(o)   row 276: reaches to a cup and grasps; the true reach times
//   bpDisplay(o)      row 262: a seven-segment monitor drawn as grey pixels, read by console-coach-bp.js
import * as handsFx from './hands.mjs';
import * as posesFx from './poses.mjs';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const BASE_AT = 1764300000; // 28 Nov 2026, unix seconds
const LOADED = new Map();

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
export function res(task, data, t, extra) {
  return freeze(Object.assign({ task, v: 1, at: BASE_AT + Math.floor(t), ms: 20, device: 'browser', ok: true, data,
    quality: { light: 0.8, sharp: 0.8 }, t }, extra || {}));
}
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const lerp = (a, b, k) => a + (b - a) * k;
const minJerk = (k) => { const c = Math.min(1, Math.max(0, k)); return c * c * c * (10 - 15 * c + 6 * c * c); };
const plainOut = (v) => JSON.parse(JSON.stringify(v));

// ---- row 224: the reaction game ----------------------------------------------------------------------------------------
const PALM = [0, 5, 9, 13, 17];
const TIPS = [4, 8, 12, 16, 20];
const palmOf = (pts) => ({ x: PALM.reduce((n, i) => n + pts[i].x, 0) / 5, y: PALM.reduce((n, i) => n + pts[i].y, 0) / 5 });
const touchDist = (pts, dot) => [palmOf(pts), ...TIPS.map((i) => pts[i])].reduce((b, p) => Math.min(b, Math.hypot(p.x - dot.x, p.y - dot.y)), Infinity);

/** o: {seed, fps, noise, delays: [s per round], move: s, skip: [round numbers left untouched], seconds} */
export async function reactionGame(o) {
  const opt = Object.assign({ seed: 1, fps: 15, noise: 0.003, delays: [], move: 0.25, skip: [], seconds: 150, size: 0.15 }, o || {});
  const uc = await useCase('console-coach-reaction.js', opt.base);
  const r = rng(opt.seed);
  const handAt = (c, noise, seed) => handsFx.hand({ cx: c.x, cy: c.y, size: opt.size, noise, seed });
  const offset = (() => { const h = handAt({ x: 0, y: 0 }, 0, 1); return palmOf(h.points); })();
  let pos = { x: 0.5, y: 0.92 }, plan = null, state, seenRound = 0;
  const truths = [];
  const at = (t) => {
    if (!plan || t < plan.from) return plan && t < plan.from ? plan.a : pos;
    const k = minJerk((t - plan.from) / plan.dur);
    return { x: lerp(plan.a.x, plan.b.x, k), y: lerp(plan.a.y, plan.b.y, k) };
  };
  for (let i = 0; i <= opt.seconds * opt.fps; i += 1) {
    const t = i / opt.fps;
    const c = at(t);
    const h = handAt(c, opt.noise, opt.seed * 1000 + i);
    state = uc.onResult(res('hands', { hands: [h] }, t), state);
    if (state.over) break;
    if (state.lit >= 0 && state.n !== seenRound) { // a new circle lit at this frame: plan the scripted reach
      seenRound = state.n;
      pos = c;
      const view = uc.summary(state).view.find((w) => w.kind === 'targets');
      const dot = view.dots[state.lit];
      if (opt.skip.includes(state.n)) { plan = null; truths.push(null); continue; }
      const delay = opt.delays[state.n - 1] !== undefined ? opt.delays[state.n - 1] : 0.25 + 0.5 * r();
      const b = { x: dot.x - offset.x, y: dot.y - offset.y };
      plan = { a: c, b, from: state.litAt + delay, dur: opt.move };
      let truth = null; // the first millisecond a clean hand's palm or fingertip is inside the circle
      for (let ms = 0; ms <= (delay + opt.move + 0.5) * 1000; ms += 1) {
        const tt = state.litAt + ms / 1000;
        if (touchDist(handAt(at(tt), 0, 1).points, dot) <= dot.r) { truth = ms; break; }
      }
      truths.push(truth);
    }
  }
  const sum = uc.summary(state);
  return plainOut({ truths, rts: state.rts, hits: state.hits, misses: state.misses, n: state.n, over: state.over,
    tally: sum.tally, view: sum.view });
}

// ---- row 238: the breath pacer -----------------------------------------------------------------------------------------
// This file's OWN copy of the rhythms (never read from the module it checks): [phase, seconds] ...
const PACE = {
  '4-4': [['in', 4], ['out', 4]],
  '4-7-8': [['in', 4], ['hold', 7], ['out', 8]],
  box: [['in', 4], ['hold', 4], ['out', 4], ['hold', 4]],
  '6-a-minute': [['in', 4], ['out', 6]],
  '5-5': [['in', 5], ['out', 5]],
};
export const RHYTHM_NAMES = Object.keys(PACE);
function expectPace(name, e) {
  const ph = PACE[name], cycle = ph.reduce((n, p) => n + p[1], 0);
  let x = e % cycle;
  for (const [phase, len] of ph) { if (x < len) return { phase, s: Math.round((len - x) * 10) / 10, of: len }; x -= len; }
  return null;
}

/** o: {perMinute, seconds, fps, noise, amp, rhythm, seed, still} -> the tally, the last view, pacer mismatches */
export async function breathSession(o) {
  const opt = Object.assign({ perMinute: 12, seconds: 90, fps: 10, noise: 0.0015, amp: 0.004, seed: 5, still: false }, o || {});
  const uc = await useCase('console-coach-breath.js', opt.base);
  const setup = opt.rhythm ? { rhythm: opt.rhythm } : undefined;
  const name = opt.rhythm && PACE[opt.rhythm] ? opt.rhythm : '6-a-minute';
  let state, mismatches = 0, checked = 0;
  for (let i = 0; i <= opt.seconds * opt.fps; i += 1) {
    const t = i / opt.fps;
    const lift = opt.still ? 0 : opt.amp * Math.sin(2 * Math.PI * (opt.perMinute / 60) * t);
    const pts = posesFx.body({ hip: 90, knee: 90 }, { noise: opt.noise, seed: opt.seed * 7919 + i })
      .map((p, k) => (k <= 12 ? Object.assign({}, p, { y: p.y - lift }) : p));
    state = uc.onResult(res('pose', { points: pts }, t, setup ? { setup } : {}), state);
    const got = uc.summary(state).view.find((w) => w.kind === 'pacer');
    const want = expectPace(name, t);
    checked += 1;
    if (!got || got.phase !== want.phase || Math.abs(got.s - want.s) > 0.05 || got.of !== want.of) mismatches += 1;
  }
  const sum = uc.summary(state);
  return plainOut({ tally: sum.tally, view: sum.view, mismatches, checked });
}

// ---- row 248: the water counter ----------------------------------------------------------------------------------------
// A webcam's view of a person at the desk: the object model's `person` box (head to the desk), a cup resting on the desk,
// and a hand. Events: {kind, at, dur}: sip (raised to the lips for `dur`), and things that are not sips: slide (the
// cup pushed across the desk), face (a hand to the face, the cup left down), phone (a phone raised to the ear), chest
// (the cup lifted to the chest), eyes (the cup held up at eye level). `hidden` is the share of at-the-lips frames in
// which the hand hides the cup from the object model.
const PERSON = { x: 0.3, y: 0.05, w: 0.4, h: 0.95 };
const MOUTH_Y = PERSON.y + PERSON.h / 3;
const REST = { x: 0.66, y: 0.86 };
function cupBox(c, label) { return { label: label || 'cup', score: 0.8, box: { x: c.x - 0.035, y: c.y - 0.06, w: 0.07, h: 0.12 } }; }
function handNear(c, noise, seed) { return handsFx.hand({ cx: c.x + 0.05, cy: c.y + 0.02, size: 0.1, noise, seed }); }

/** o: {seconds, fps, events: [{kind, at, dur}], hidden, noise, seed, setup} -> the tally and the truth */
export async function waterDay(o) {
  const opt = Object.assign({ seconds: 600, fps: 2, events: [], hidden: 0.25, noise: 0.004, seed: 9 }, o || {});
  const uc = await useCase('console-coach-water.js', opt.base);
  const r = rng(opt.seed);
  const extra = opt.setup ? { setup: opt.setup } : {};
  const RISE = 0.8; // seconds to raise or lower
  let state;
  for (let i = 0; i <= opt.seconds * opt.fps; i += 1) {
    const t = i / opt.fps;
    const ev = opt.events.find((e) => t >= e.at && t < e.at + e.dur + 2 * RISE);
    let cup = { x: REST.x, y: REST.y }, label = 'cup', hand = null, showCup = true;
    if (ev) {
      const k = t < ev.at + RISE ? (t - ev.at) / RISE : (t > ev.at + RISE + ev.dur ? 1 - (t - ev.at - RISE - ev.dur) / RISE : 1);
      const lift = (toY) => ({ x: lerp(REST.x, 0.52, k), y: lerp(REST.y, toY, k) });
      if (ev.kind === 'sip') cup = lift(MOUTH_Y + 0.02);
      else if (ev.kind === 'chest') cup = lift(0.62);
      else if (ev.kind === 'eyes') cup = lift(0.16);
      else if (ev.kind === 'slide') cup = { x: lerp(REST.x, 0.42, k), y: REST.y };
      else if (ev.kind === 'phone') { label = 'cell_phone'; cup = lift(0.3); }
      if (ev.kind === 'face') hand = { x: 0.48, y: MOUTH_Y };
      else hand = cup;
      if (ev.kind === 'sip' && k === 1 && r() < opt.hidden) showCup = false;
    }
    const jitter = () => (r() - 0.5) * 2 * opt.noise;
    const things = [{ label: 'person', score: 0.9, box: PERSON }];
    if (showCup) things.push(cupBox({ x: cup.x + jitter(), y: cup.y + jitter() }, label));
    if (label === 'cell_phone') things.push(cupBox(REST)); // the cup stays on the desk meanwhile
    const hands = hand ? [handNear(hand, opt.noise, opt.seed * 977 + i)] : [];
    state = uc.onResult(res('hands', { hands }, t, extra), state);
    state = uc.onResult(res('objects', { objects: things }, t + 0.01, extra), state);
  }
  const sum = uc.summary(state);
  return plainOut({ tally: sum.tally, view: sum.view, truth: opt.events.filter((e) => e.kind === 'sip').length });
}

/** A synthetic hour (or `seconds`): `sips` sips and `others` non-sips of every kind, shuffled, spread out, seeded. */
export function waterEvents(o) {
  const opt = Object.assign({ seconds: 3600, sips: 12, others: 24, seed: 4 }, o || {});
  const r = rng(opt.seed);
  const kinds = ['slide', 'face', 'phone', 'chest', 'eyes'];
  const list = [...Array(opt.sips).fill('sip'), ...Array.from({ length: opt.others }, (_, i) => kinds[i % kinds.length])];
  for (let i = list.length - 1; i > 0; i -= 1) { const j = Math.floor(r() * (i + 1)); [list[i], list[j]] = [list[j], list[i]]; }
  const slot = opt.seconds / (list.length + 1);
  return list.map((kind, i) => ({ kind, at: Math.round((i + 1) * slot + r() * slot * 0.3),
    dur: Math.round((1.5 + r() * 2.5) * 10) / 10 }));
}

// ---- a jointed hand (rows 268, 276) --------------------------------------------------------------------------------------
// A right hand, palm to the camera, fingers up; `flex` is each finger's bend at EACH of its three joints (degrees),
// folding towards the camera (z, the hand model's depth, on the x scale), so the picture shortens the finger as a real
// one does. `oppose` {finger 1..4, amount 0..1} brings the thumb's tip to that fingertip (which bends to meet it).
// `open` 0..1 spreads thumb and index apart for a grasp. Points are MediaPipe's 21: wrist, thumb 1-4, index 5-8, middle
// 9-12, ring 13-16, little 17-20.
const KNUCKLE = [[-14, 1.0], [-4, 1.02], [6, 0.97], [16, 0.88]]; // degrees from straight up, length of the palm
const SEGS = [0.42, 0.27, 0.2];
const SIZE = [1.0, 1.08, 1.0, 0.82];
const RAD8 = Math.PI / 180;
export function bendOf(flex) { // this file's OWN knuckle-to-tip bend for a finger bent `flex` at each joint (degrees)
  let u = 0, w = 0;
  SEGS.forEach((L, k) => { u += L * Math.cos((k + 1) * flex * RAD8); w += L * Math.sin((k + 1) * flex * RAD8); });
  return Math.atan2(w, u) / RAD8;
}
export function jointHand(o) {
  const opt = Object.assign({ side: 'right', cx: 0.5, cy: 0.7, size: 0.16, flex: [0, 0, 0, 0, 0], oppose: null, noise: 0, seed: 3 }, o || {});
  const r = rng(opt.seed), n = () => (r() - 0.5) * 2 * opt.noise, flip = opt.side === 'left' ? -1 : 1;
  const P = 0.45 * opt.size, W = { x: opt.cx, y: opt.cy, z: 0 };
  const flexes = opt.flex.slice();
  if (opt.oppose) flexes[opt.oppose.finger] = Math.max(flexes[opt.oppose.finger], 35 * opt.oppose.amount);
  const fingers = KNUCKLE.map(([deg, k], f) => {
    const a = flip * deg * RAD8, ux = Math.sin(a), uy = -Math.cos(a);
    const mcp = { x: W.x + P * k * ux, y: W.y + P * k * uy, z: 0 };
    const pts = [mcp];
    let p = mcp;
    SEGS.forEach((L, j) => {
      const th = (j + 1) * flexes[f + 1] * RAD8, l = L * P * SIZE[f];
      p = { x: p.x + l * Math.cos(th) * ux, y: p.y + l * Math.cos(th) * uy, z: p.z - l * Math.sin(th) };
      pts.push(p);
    });
    return pts;
  });
  const ta = flip * -48 * RAD8, tx = Math.sin(ta), ty = -Math.cos(ta);
  const cmc = { x: W.x + 0.3 * P * tx, y: W.y + 0.3 * P * ty, z: 0 };
  const tf = flexes[0] * RAD8;
  const thumbOpen = [cmc];
  [0.38, 0.3, 0.25].forEach((L, j) => {
    const prev = thumbOpen[thumbOpen.length - 1], th = (j + 1) * tf, l = L * P;
    const dx = Math.sin(ta + flip * th * 0.8), dy = -Math.cos(ta + flip * th * 0.8);
    thumbOpen.push({ x: prev.x + l * dx, y: prev.y + l * dy, z: prev.z - l * Math.sin(th) * 0.3 });
  });
  let thumb = thumbOpen;
  if (opt.oppose && opt.oppose.amount > 0) {
    const tip = fingers[opt.oppose.finger - 1][3], k = Math.min(1, opt.oppose.amount);
    thumb = thumbOpen.map((p, j) => (j === 0 ? p : { x: lerp(p.x, tip.x, k * j / 3), y: lerp(p.y, tip.y, k * j / 3), z: lerp(p.z, tip.z, k * j / 3) }));
  }
  const all = [W, ...thumb, ...fingers.flat()];
  return { side: opt.side, score: 0.95, points: all.map((p) => ({ x: p.x + n(), y: p.y + n(), z: p.z + n() })) };
}

// ---- row 268: hand and finger exercises -----------------------------------------------------------------------------------
// exercise: open_close (all four fingers and the thumb fold to `peak` per joint and open, `period` seconds a rep),
// finger_tap (index, middle, ring, little in turn bend to `peak` and straighten), thumb_to_finger (the thumb meets each
// fingertip in turn). `rest` is each rep's straightest bend per joint. Truth: the reps and the bend range.
export async function rehabSession(o) {
  const opt = Object.assign({ exercise: 'open_close', reps: 10, period: 1.6, peak: 70, rest: 0, fps: 15, noise: 0.002, seed: 21,
    side: 'right', setup: null, second: false }, o || {});
  const uc = await useCase('console-coach-handrehab.js', opt.base);
  const extra = opt.setup ? { setup: opt.setup } : {};
  let state;
  const lead = 1, total = lead + opt.reps * opt.period + 1.5;
  for (let i = 0; i <= total * opt.fps; i += 1) {
    const t = i / opt.fps, k = t - lead, rep = Math.floor(k / opt.period), ph = (k - rep * opt.period) / opt.period;
    const wave = k >= 0 && rep < opt.reps ? (1 - Math.cos(2 * Math.PI * ph)) / 2 : 0;
    const bend = opt.rest + (opt.peak - opt.rest) * wave;
    const flex = [opt.rest, opt.rest, opt.rest, opt.rest, opt.rest];
    let oppose = null;
    if (opt.exercise === 'open_close') flex.fill(bend);
    else if (opt.exercise === 'finger_tap') flex[1 + (((rep % 4) + 4) % 4)] = bend;
    else oppose = { finger: 1 + (((rep % 4) + 4) % 4), amount: wave };
    const hs = [jointHand({ side: opt.side, flex, oppose, noise: opt.noise, seed: opt.seed * 1009 + i })];
    if (opt.second) hs.push(jointHand({ side: opt.side === 'right' ? 'left' : 'right', cx: 0.25, flex: [60, 60, 60, 60, 60], noise: opt.noise, seed: i }));
    state = uc.onResult(res('hands', { hands: hs }, t, extra), state);
  }
  const sum = uc.summary(state);
  const truthRange = opt.exercise === 'thumb_to_finger' ? null : bendOf(opt.peak) - bendOf(opt.rest);
  return plainOut({ tally: sum.tally, view: sum.view, truth: { reps: opt.reps, range: truthRange } });
}

// ---- row 276: reach and grasp ------------------------------------------------------------------------------------------
// A cup on the desk; the hand rests at HOME_P; after the coach's "go" the hand waits `delay`, reaches the cup in `move`
// seconds (a smooth, minimum-jerk path), closes on it in CLOSE_IN, holds, opens and comes back. `skip` trials it never
// reaches (a missed grasp). Truth per trial, from the clean (noise-free) hand with THIS file's own copy of the rule: from
// the palm's first ONSET_D of movement to the thumb-to-index gap's first fall below CLOSE of its resting width.
const CUP = { x: 0.6, y: 0.45, w: 0.08, h: 0.13 };
const HOME_P = { x: 0.3, y: 0.85 };
const ONSET_D8 = 0.02;
const CLOSE8 = 0.6;
const CLOSE_IN = 0.25;
const gapOf = (pts) => Math.hypot(pts[4].x - pts[8].x, pts[4].y - pts[8].y) / Math.hypot(pts[0].x - pts[9].x, pts[0].y - pts[9].y);
export async function reachSession(o) {
  const opt = Object.assign({ fps: 15, noise: 0.002, seed: 31, delays: [], moves: [], skip: [], seconds: 120, cupEvery: 1 }, o || {});
  const uc = await useCase('console-coach-reach.js', opt.base);
  const r = rng(opt.seed);
  const handAt = (palmAt, amount, noise, seed) => {
    const probe = jointHand({ cx: 0, cy: 0, flex: [10, 10, 10, 10, 10] });
    const off = palmOf(probe.points);
    return jointHand({ cx: palmAt.x - off.x, cy: palmAt.y - off.y, flex: [10, 10 + 30 * amount, 10 + 40 * amount, 10 + 40 * amount, 10 + 40 * amount],
      oppose: amount > 0 ? { finger: 1, amount: 0.75 * amount } : null, noise, seed });
  };
  const target = { x: CUP.x - 0.02, y: CUP.y + CUP.h / 2 };
  const openGap = gapOf(handAt(HOME_P, 0, 0, 1).points);
  let state, plan = null, seenTrial = -1;
  const truths = [];
  const pose = (t) => { // where the clean hand is, and how closed, at time t
    if (!plan) return { p: HOME_P, a: 0 };
    const { t0, move, hold } = plan, t1 = t0 + move, t2 = t1 + CLOSE_IN, t3 = t2 + hold, t4 = t3 + CLOSE_IN, t5 = t4 + move;
    if (t < t0) return { p: HOME_P, a: 0 };
    if (t < t1) { const k = minJerk((t - t0) / move); return { p: { x: lerp(HOME_P.x, target.x, k), y: lerp(HOME_P.y, target.y, k) }, a: 0 }; }
    if (t < t2) return { p: target, a: (t - t1) / CLOSE_IN };
    if (t < t3) return { p: target, a: 1 };
    if (t < t4) return { p: target, a: 1 - (t - t3) / CLOSE_IN };
    if (t < t5) { const k = minJerk((t - t4) / move); return { p: { x: lerp(target.x, HOME_P.x, k), y: lerp(target.y, HOME_P.y, k) }, a: 0 }; }
    return { p: HOME_P, a: 0 };
  };
  for (let i = 0; i <= opt.seconds * opt.fps; i += 1) {
    const t = i / opt.fps;
    if (i % opt.cupEvery === 0) state = uc.onResult(res('objects', { objects: [{ label: 'cup', score: 0.85, box: CUP }] }, t), state);
    const q = pose(t);
    state = uc.onResult(res('hands', { hands: [handAt(q.p, q.a, opt.noise, opt.seed * 4001 + i)] }, t + 0.005), state);
    if (state.phase === 'over') break;
    if (state.phase === 'go' && state.trials.length !== seenTrial) {
      seenTrial = state.trials.length;
      const k = seenTrial;
      if (opt.skip.includes(k + 1)) { plan = null; truths.push(null); continue; }
      const delay = opt.delays[k] !== undefined ? opt.delays[k] : 0.3 + 0.4 * r();
      const move = opt.moves[k] !== undefined ? opt.moves[k] : 0.6 + 1.0 * r();
      plan = { t0: state.goAt + delay, move, hold: 1.0 };
      let onset = null, grasp = null;
      for (let ms = 0; ms < (delay + move + 1) * 1000 && grasp === null; ms += 1) {
        const tt = state.goAt + ms / 1000, c = pose(tt);
        if (onset === null && Math.hypot(c.p.x - HOME_P.x, c.p.y - HOME_P.y) >= ONSET_D8) onset = tt;
        if (onset !== null && gapOf(handAt(c.p, c.a, 0, 1).points) / openGap <= CLOSE8) grasp = tt;
      }
      truths.push(Math.round((grasp - onset) * 1000));
    }
  }
  const sum = uc.summary(state);
  return plainOut({ truths, trials: state.trials, phase: state.phase, tally: sum.tally, view: sum.view });
}

// ---- row 262's reading: a blood-pressure monitor's seven-segment screen, as grey levels ------------------------------------
// The screen fills the pane's guide box (w x h). Three number lines (SYS and DIA large, PUL small, right-aligned), small
// labels and a heart mark beside them, a clock line on top, a slant, a light gradient, noise and sometimes a blur; a
// backlit screen (lit segments on dark) for some. Segments a-g as in the module; this file draws them itself.
const SEG8 = { a: [1, 0, 1], b: [2, 1, 0], c: [2, 2, 0], d: [1, 3, 1], e: [0, 2, 0], f: [0, 1, 0], g: [1, 4, 1] };
const LIT = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
function drawDigit(rect, d, x0, y0, H, slant) {
  const W = 0.55 * H, s = 0.14 * H, g = 0.035 * H, k = Math.tan(slant * RAD8);
  for (const name of LIT[d]) {
    const [col, row, horiz] = SEG8[name];
    let xa, xb, ya, yb;
    if (horiz) { xa = s + g; xb = W - s - g; const yc = row === 0 ? s / 2 : (row === 3 ? H - s / 2 : H / 2); ya = yc - s / 2; yb = yc + s / 2; }
    else { xa = col === 0 ? 0 : W - s; xb = xa + s; ya = row === 1 ? g : H / 2 + g; yb = row === 1 ? H / 2 - g : H - g; }
    rect(x0, y0, xa, xb, ya, yb, H, k);
  }
}
export function bpScreen(o) {
  const opt = Object.assign({ w: 260, h: 220, sys: 128, dia: 82, pulse: 71, seed: 1, noise: 12, slant: 5, blur: false,
    backlit: false, gradient: 20, scale: 1, dx: 0, dy: 0, clock: true, marks: true }, o || {});
  const { w, h } = opt, r = rng(opt.seed);
  const bg = opt.backlit ? 35 : 185, fg = opt.backlit ? 215 : 45;
  const px = new Float32Array(w * h).map((_, i) => bg + opt.gradient * ((i % w) / w - 0.5));
  const fill = (x, y) => { if (x >= 0 && x < w && y >= 0 && y < h) px[y * w + x] = fg; };
  const rect = (x0, y0, xa, xb, ya, yb, H, k) => {
    for (let y = Math.round(y0 + ya); y < Math.round(y0 + yb); y += 1) {
      const shift = (y0 + H / 2 - y) * k;
      for (let x = Math.round(x0 + xa + shift); x < Math.round(x0 + xb + shift); x += 1) fill(x, y);
    }
  };
  const box = (x, y, bw, bh) => { for (let yy = Math.round(y); yy < Math.round(y + bh); yy += 1) for (let xx = Math.round(x); xx < Math.round(x + bw); xx += 1) fill(xx, yy); };
  const number = (value, right, top, H) => {
    const digits = String(value).split('').map(Number), W = 0.55 * H, gap = 0.22 * H;
    digits.forEach((d, i) => drawDigit(rect, d, right - (digits.length - i) * (W + gap) + gap, top, H, opt.slant));
  };
  const S = opt.scale, big = 0.29 * h * S, small = 0.15 * h * S, ox = opt.dx, oy = opt.dy;
  number(opt.sys, 0.94 * w + ox, 0.08 * h + oy, big);
  number(opt.dia, 0.94 * w + ox, 0.43 * h + oy, big);
  number(opt.pulse, 0.94 * w + ox, 0.8 * h + oy, small);
  if (opt.clock) { number(10, 0.3 * w + ox, 0.005 * h + oy, 0.06 * h); number(35, 0.48 * w + ox, 0.005 * h + oy, 0.06 * h); }
  if (opt.marks) { // "SYS", "DIA" and "mmHg" as small blocks, and a heart mark beside the pulse
    box(0.04 * w + ox, 0.1 * h + oy, 0.12 * w, 0.06 * h); box(0.04 * w + ox, 0.45 * h + oy, 0.12 * w, 0.06 * h);
    box(0.04 * w + ox, 0.62 * h + oy, 0.14 * w, 0.05 * h);
    const hx = 0.5 * w + ox, hy = 0.83 * h + oy, hs = 0.08 * h;
    for (let y = 0; y < hs; y += 1) { const half = hs / 2 - Math.abs(y - hs / 2); box(hx + hs / 2 - half, hy + y, 2 * half, 1); }
  }
  let out = Array.from(px, (v) => v + (r() - 0.5) * 2 * opt.noise);
  if (opt.blur) {
    out = out.map((_, i) => {
      const x = i % w, y = (i - x) / w;
      let n = 0, c = 0;
      for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy += 1) for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx += 1) { n += out[yy * w + xx]; c += 1; }
      return n / c;
    });
  }
  return { w, h, px: out.map((v) => Math.max(0, Math.min(255, Math.round(v)))) };
}

/** Many random screens through the module's reader and rule: how many read right, wrong, or not at all (null). */
export async function bpDisplays(o) {
  const opt = Object.assign({ n: 200, seed: 77, w: 260, h: 220 }, o || {});
  const mod = await import(new URL('console-coach-bp.js', opt.base ? new URL(`file://${opt.base.replace(/\/?$/, '/')}`) : STATIC).href);
  const r = rng(opt.seed);
  const pick = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
  let right = 0, wrong = 0, none = 0;
  const misses = [];
  for (let i = 0; i < opt.n; i += 1) {
    const sys = pick(95, 199), dia = pick(55, Math.min(125, sys - 20)), pulse = pick(48, 135);
    const screen = bpScreen({ w: opt.w, h: opt.h, sys, dia, pulse, seed: opt.seed * 31 + i, noise: pick(4, 18),
      slant: pick(0, 8), blur: r() < 0.5, backlit: r() < 0.2, gradient: pick(0, 30), scale: 0.9 + 0.2 * r(),
      dx: pick(-6, 6), dy: pick(-4, 4), clock: r() < 0.6, marks: r() < 0.8 });
    const got = mod.proposal(mod.readDisplay(screen).lines);
    if (!got) { none += 1; misses.push({ sys, dia, pulse, got: null }); }
    else if (got.systolic === sys && got.diastolic === dia && got.pulse === pulse) right += 1;
    else { wrong += 1; misses.push({ sys, dia, pulse, got }); }
  }
  return { n: opt.n, right, wrong, none, misses: misses.slice(0, 10) };
}

/** What a coach shows before any Result: summary(undefined). */
export async function emptySummary(file, base) {
  const uc = await useCase(file, base);
  return plainOut(uc.summary(undefined));
}
