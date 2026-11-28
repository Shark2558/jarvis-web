// tests/fixtures/r8/dynamic_sequences.mjs -- R8.1 builder G (docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8): the
// dynamic coaches' synthetic sessions, run in Node by tests/test_r81_g_coaches.py and evals/r8_1/dynamic.py through
// tests/r8_fakes.run_node. Never a real person's data: every body here is made up from numbers (metres, then drawn
// into the frame the way the engine's pose points are: 0..1 of the frame, z relative, visibility 0..1).
// Each scenario loads the REAL use-case module (src/jarvis/api/static/console-coach-<x>.js) behind a stand-in for the
// engine's JarvisVision.use, feeds it one body's Results the way the engine's driver does (frozen plain data, a state
// per body), and returns what a test checks: the module's tally and view, and the scenario's own truth (computed here
// from the continuous script, never read from the module). Times are seconds; `t` rides on each Result.
// A session's setup (the pane's taps and confirmations: the wall or spotter, the marks, the stance) rides on every
// Result as `setup`, the way the driver puts it: S2's contract line from R8's join (live(..., {setup}) -> r.setup).
//   boxingSession(o)    row 228: jabs, crosses, hooks and uppercuts in combinations, front view
//   agilityRun(o)       row 230: runs between the marks he tapped; the exact gate crossings
//   jumpSession(o)      row 235: counter-movement jumps of set heights; soft, stiff and knees-in landings
//   handstandSession(o) row 237: a kick-up, a hold, a drift past the limit, coming down; with or without support
//   kettlebellSession(o) row 239: swings, each a hip hinge or a squat
import { drive } from './driver.mjs';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const BASE_AT = 1764300000; // 28 Nov 2026, unix seconds
const LOADED = new Map();
const G = 9.81;

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
/** What a coach shows before any Result: its view, and no tally. */
export async function emptySummary(file) { return plainOut((await useCase(file)).summary(undefined)); }
/** One body's pose Result, as the driver hands it to a use case (pose v2 cut to one body); the pane's setup, when
 *  there is one, rides on it as `setup` (the driver's own rule: none for undefined or null). */
export function res(points, t, setup) {
  const r = { task: 'pose', v: 2, at: BASE_AT + Math.floor(t), ms: 20, device: 'phone', ok: true,
    data: { points }, quality: { light: 0.8, sharp: 0.8 }, track: 0, who: 'me', t };
  return freeze(setup === undefined || setup === null ? r : Object.assign(r, { setup }));
}
export function rng(seed0) { let s = (seed0 >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const lerp = (a, b, k) => a + (b - a) * k;
const minJerk = (k) => { const c = Math.min(1, Math.max(0, k)); return c * c * c * (10 - 15 * c + 6 * c * c); };
const plainOut = (v) => JSON.parse(JSON.stringify(v));
const v3 = (x, y, z) => ({ x, y, z: z || 0 });
const add = (a, b) => v3(a.x + b.x, a.y + b.y, a.z + b.z);
const blend = (a, b, k) => v3(lerp(a.x, b.x, k), lerp(a.y, b.y, k), lerp(a.z, b.z, k));

// ---- drawing a body: named joints in metres (x to the frame's right, y up from the floor, z towards the camera < 0)
const NAMES = ['nose', 'lsh', 'rsh', 'lel', 'rel', 'lwr', 'rwr', 'lhip', 'rhip', 'lkn', 'rkn', 'lan', 'ran', 'lhe', 'rhe', 'lto', 'rto'];
const INDEX = { nose: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], lsh: [11], rsh: [12], lel: [13], rel: [14], lwr: [15, 17, 19, 21],
  rwr: [16, 18, 20, 22], lhip: [23], rhip: [24], lkn: [25], rkn: [26], lan: [27], ran: [28], lhe: [29], rhe: [30], lto: [31], rto: [32] };
/** The engine's 33 points: o {k: frame units a metre, cx, gy (the floor's y in the frame), noise, r (rng), vis}. */
export function draw(j, o) {
  const k = o.k || 0.3, cx = o.cx === undefined ? 0.5 : o.cx, gy = o.gy || 0.95, noise = o.noise || 0, r = o.r || Math.random;
  const pts = new Array(33).fill(null);
  NAMES.forEach((n) => { const p = j[n]; INDEX[n].forEach((i) => { pts[i] = p; }); });
  const vis = o.vis === undefined ? 0.95 : o.vis;
  return pts.map((p) => ({ x: cx + p.x * k + (r() - 0.5) * 2 * noise, y: gy - p.y * k + (r() - 0.5) * 2 * noise,
    z: p.z * k + (r() - 0.5) * 2 * noise * (o.zNoise || 1), visibility: vis })); // MediaPipe's depth is the noisier
}
function knee(hip, ankle, fwd, inward, px) { // the knee between a hip and an ankle (thigh and shin 0.45 m), bent forward
  const d = Math.hypot(hip.x - ankle.x, hip.y - ankle.y, hip.z - ankle.z), m = blend(hip, ankle, 0.5);
  const f = d < 0.9 ? Math.sqrt(0.45 * 0.45 - (d / 2) * (d / 2)) : 0;
  return v3(m.x + Math.sign(px - ankle.x) * (inward || 0), m.y, m.z - f * (fwd === undefined ? 1 : fwd)); // pushed in: valgus
}
/** A body facing the camera. o: {px, lift, drop, stance, kneeIn, turn (the lead side's shoulder forward), lead, arms}. */
export function frontBody(o) {
  const px = o.px || 0, lift = o.lift || 0, drop = o.drop || 0, half = (o.stance || 0.3) / 2;
  const lead = o.lead === 'right' ? -1 : 1, turn = o.turn || 0; // left is the frame's right (+x)
  const hipY = 0.92 - drop + lift, shY = hipY + 0.5;
  const lhip = v3(px + 0.1, hipY, -turn * lead * 0.5), rhip = v3(px - 0.1, hipY, turn * lead * 0.5);
  const lsh = v3(px + 0.18, shY, -turn * lead), rsh = v3(px - 0.18, shY, turn * lead);
  const footZ = (o.footZ || 0) * lead;
  const lan = v3(px + half, 0.08 + lift, -footZ), ran = v3(px - half, 0.08 + lift, footZ);
  const lkn = knee(lhip, lan, 1, o.kneeIn, px), rkn = knee(rhip, ran, 1, o.kneeIn, px);
  const guard = (side) => { const s = side > 0 ? lsh : rsh; return { el: add(s, v3(side * 0.03, -0.24, -0.12)), wr: add(s, v3(-side * 0.07, 0.08, -0.24)) }; };
  const arms = Object.assign({ l: guard(1), r: guard(-1) }, o.arms || {});
  const heel = (a) => add(a, v3(0, -0.06, 0.06)), toe = (a) => add(a, v3(0, -0.07, -0.14));
  return { nose: v3(px, shY + 0.27, -0.1), lsh, rsh, lel: arms.l.el, rel: arms.r.el, lwr: arms.l.wr, rwr: arms.r.wr,
    lhip, rhip, lkn, rkn, lan, ran, lhe: heel(lan), rhe: heel(ran), lto: toe(lan), rto: toe(ran) };
}

// ---- row 235: jumps ---------------------------------------------------------------------------------------------------
/** o: {heights: [m], fps, noise, seed, landings: ['soft'|'stiff'|'in'], phase (s), footLift: m (before the jumps, one
 *  foot raised for a second: never a jump), base}. Truth: each jump's height from its exact flight time. */
export async function jumpSession(o) {
  const opt = Object.assign({ heights: [0.3], fps: 30, noise: 0.002, seed: 1, landings: [], phase: 0.013 }, o || {});
  const uc = await useCase('console-coach-jump.js', opt.base);
  const r = rng(opt.seed);
  const plan = []; let t = opt.footLift ? 3.0 : 1.0; // stand a second first (and lift one foot)
  opt.heights.forEach((h, i) => {
    const v = Math.sqrt(2 * G * h), flight = 2 * v / G, kind = opt.landings.at(i) || 'soft';
    plan.push({ dip: t, up: t + 0.55, flight, h, v, kind, land: t + 0.55 + flight }); t += 0.55 + flight + 1.6 + r() * 0.6;
  });
  const at = (tt) => { // the body at time tt: the dip, the flight, the landing's sink
    for (const j of plan) {
      if (tt >= j.dip && tt < j.up) { const k = (tt - j.dip) / (j.up - j.dip); return { drop: 0.2 * Math.sin(Math.PI * Math.min(1, k * 1.2)) * (k < 0.85 ? 1 : (1 - k) / 0.15) }; }
      if (tt >= j.up && tt < j.land) { const u = tt - j.up; return { lift: j.v * u - G * u * u / 2 }; }
      if (tt >= j.land && tt < j.land + 1.2) {
        const u = (tt - j.land) / 1.2, depth = j.kind === 'stiff' ? 0.02 : 0.2;
        const sink = depth * Math.sin(Math.PI * Math.min(1, u * 1.6)) * (u < 0.625 ? 1 : 0);
        return { drop: sink, kneeIn: j.kind === 'in' ? 0.11 * (sink / depth) : 0 };
      }
    }
    return {};
  };
  let state;
  const seen = [];
  const n = Math.round((t + 0.5) * opt.fps);
  for (let i = 0; i <= n; i += 1) {
    const tt = opt.phase + i / opt.fps;
    const body = frontBody(Object.assign({ stance: 0.3 }, at(tt)));
    const up = opt.footLift && tt > 1 && tt < 2 ? v3(0, opt.footLift, -0.1) : null;
    const b = up ? Object.assign({}, body, { lan: add(body.lan, up), lhe: add(body.lhe, up), lto: add(body.lto, up) }) : body;
    const pts = draw(b, { noise: opt.noise, r });
    const was = state || { jumps: 0, stiff: 0, kneesIn: 0 };
    state = uc.onResult(res(pts, tt), state);
    if (state.jumps > was.jumps) seen.push({ cm: state.last, at: tt, stiff: false, kneesIn: false });
    if (state.stiff > was.stiff) seen.at(-1).stiff = true;
    if (state.kneesIn > was.kneesIn) seen.at(-1).kneesIn = true;
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, seen,
    truth: plan.map((j) => ({ cm: 100 * j.h, kind: j.kind, land: j.land })) });
}

// ---- row 228: shadowboxing ------------------------------------------------------------------------------------------
// Each punch is keyframes of the wrist and elbow, relative to its shoulder (side +1 left arm, -1 right; metres).
const KEYS = {
  straight: [{ wr: [-0.12, 0.03, -0.6], el: [-0.05, 0.01, -0.3] }],
  hook: [{ wr: [0.18, 0.02, -0.25], el: [0.22, -0.03, -0.05] }, { wr: [-0.2, 0.02, -0.42], el: [0.1, -0.02, -0.25] }],
  uppercut: [{ wr: [-0.03, -0.3, -0.22], el: [0.04, -0.3, -0.02] }, { wr: [-0.08, 0.1, -0.4], el: [0.02, -0.2, -0.3] }],
};
const GUARD = { wr: [-0.07, 0.08, -0.24], el: [0.03, -0.24, -0.12] };
const COMBOS = [['jab'], ['jab', 'cross'], ['jab', 'jab', 'cross'], ['jab', 'cross', 'hook'], ['cross', 'hook', 'cross'],
  ['jab', 'uppercut'], ['hook', 'uppercut', 'cross'], ['uppercut', 'hook'], ['jab', 'cross', 'uppercut', 'cross']];
const rel = (side, a) => v3(side * a[0], a[1], a[2]);

/** o: {punches (at least), fps, noise, zNoise, jitter (m), seed, lead: 'left'|'right', turn (0: level shoulders),
 *  setup, base, drops (every n-th frame lost)}. Truth: every punch's type, start and return, and each combination;
 *  seen: each count the module made (its type and time); combos: the module's last combination after each one. */
export async function boxingSession(o) {
  const opt = Object.assign({ punches: 40, fps: 30, noise: 0.003, zNoise: 3, jitter: 0.05, seed: 1, lead: 'left', turn: 0.06,
    phase: 0.007, drops: 0 }, o || {});
  const uc = await useCase('console-coach-boxing.js', opt.base);
  const r = rng(opt.seed), plan = [], combos = [];
  let t = 1.2;
  while (plan.length < opt.punches) {
    const combo = COMBOS.at(Math.floor(r() * COMBOS.length));
    combos.push({ types: combo });
    combo.forEach((type) => {
      const leadArm = opt.lead === 'left' ? 1 : -1;
      const side = type === 'jab' ? leadArm : type === 'cross' ? -leadArm : (r() < 0.5 ? leadArm : -leadArm);
      const shape = type === 'jab' || type === 'cross' ? 'straight' : type;
      const jit = () => v3((r() - 0.5) * 2 * opt.jitter, (r() - 0.5) * 2 * opt.jitter, (r() - 0.5) * 2 * opt.jitter);
      const keys = KEYS[shape].map((k) => ({ wr: add(rel(side, k.wr), jit()), el: add(rel(side, k.el), jit()) }));
      const durs = keys.length === 1 ? [0.14 + r() * 0.06] : [0.12 + r() * 0.04, 0.13 + r() * 0.05];
      const back = 0.18 + r() * 0.06, total = durs.reduce((n, v) => n + v, 0) + back;
      plan.push({ type, side, keys, durs, back, from: t, end: t + total });
      t += total + 0.05 + r() * 0.1;
    });
    combos.at(-1).check = plan.at(-1).end + 0.45;
    t += 0.9 + r() * 0.7;
  }
  const guard = (side) => ({ wr: rel(side, GUARD.wr), el: rel(side, GUARD.el) });
  const armAt = (side, tt) => { // the arm's offsets from its shoulder at time tt
    const g = guard(side);
    const j = plan.find((x) => x.side === side && tt >= x.from && tt < x.end);
    if (!j) return g;
    const stops = [g, ...j.keys, g], durs = [...j.durs, j.back];
    let u = tt - j.from;
    for (let i = 0; i < durs.length; i += 1) {
      if (u < durs.at(i)) { const k = minJerk(u / durs.at(i)); return { wr: blend(stops.at(i).wr, stops.at(i + 1).wr, k), el: blend(stops.at(i).el, stops.at(i + 1).el, k) }; }
      u -= durs.at(i);
    }
    return g;
  };
  let state;
  const seenOut = [], combosSeen = [];
  const n = Math.round((t + 0.5) * opt.fps);
  for (let i = 0; i <= n; i += 1) {
    if (opt.drops && i % opt.drops === opt.drops - 1) continue; // a lost frame never reaches a use case
    const tt = opt.phase + i / opt.fps;
    const b0 = frontBody({ turn: opt.turn, lead: opt.lead, footZ: 0.15 });
    const l = armAt(1, tt), rr = armAt(-1, tt);
    const b = Object.assign({}, b0, { lwr: add(b0.lsh, l.wr), lel: add(b0.lsh, l.el), rwr: add(b0.rsh, rr.wr), rel: add(b0.rsh, rr.el) });
    const was = state && state.punches !== undefined ? state.punches : 0;
    state = uc.onResult(res(draw(b, { noise: opt.noise, zNoise: opt.zNoise, r }), tt, opt.setup), state);
    if (state.punches > was) {
      const typeNow = ['jabs', 'crosses', 'hooks', 'uppercuts'].find((k, idx) => state[k] > ((seenOut.counts || [0, 0, 0, 0])[idx]));
      seenOut.push({ at: tt, type: { jabs: 'jab', crosses: 'cross', hooks: 'hook', uppercuts: 'uppercut' }[typeNow] });
      seenOut.counts = [state.jabs, state.crosses, state.hooks, state.uppercuts];
    }
    combos.forEach((c, ci) => { if (combosSeen.length === ci && tt >= c.check) combosSeen.push(state.combo || []); });
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, seen: seenOut.map((x) => x), combosSeen,
    combos: combos.map((c) => c.types), truth: plan.map((j) => ({ type: j.type, from: j.from, end: j.end })) });
}

/** Match each count to the truth punch it belongs to (in time order): -> {matched, sameType, extra, missed}. */
export function matchPunches(seen, truth) {
  let i = 0, matched = 0, same = 0, extra = 0;
  for (const s of seen) {
    while (i < truth.length && truth.at(i).end + 0.35 < s.at) i += 1;
    const j = truth.at(i);
    if (j && s.at >= j.from && s.at <= j.end + 0.35) { matched += 1; same += s.type === j.type ? 1 : 0; i += 1; } else extra += 1;
  }
  return { matched, sameType: same, extra, missed: truth.length - matched };
}

// ---- row 230: agility runs between tapped marks ---------------------------------------------------------------------
const HORIZON = 0.3;
/** A body whose foot point (the middle of its heels and toes) stands at (fx, fy) of the frame, smaller further away. */
function bodyAt(fx, fy, stride, r, noise) {
  const k = 0.3 * Math.max(0.2, (fy - HORIZON) / (0.95 - HORIZON));
  const b = frontBody({ stance: 0.25 });
  const sw = v3(stride, 0, 0);
  const moved = Object.assign({}, b, { lan: add(b.lan, sw), lhe: add(b.lhe, sw), lto: add(b.lto, sw),
    ran: add(b.ran, v3(-stride, 0, 0)), rhe: add(b.rhe, v3(-stride, 0, 0)), rto: add(b.rto, v3(-stride, 0, 0)) });
  const pts = draw(moved, { k, cx: 0, gy: 0, noise: 0, r });
  const feet = [29, 30, 31, 32].map((i) => pts.at(i)), mx = feet.reduce((n, q) => n + q.x, 0) / 4, my = feet.reduce((n, q) => n + q.y, 0) / 4;
  return pts.map((q) => Object.assign({}, q, { x: q.x - mx + fx + (r() - 0.5) * 2 * noise, y: q.y - my + fy + (r() - 0.5) * 2 * noise }));
}
const MARK_SETS = {
  line: [{ x: 0.2, y: 0.88 }, { x: 0.5, y: 0.8 }, { x: 0.8, y: 0.88 }],
  shuttle: [{ x: 0.25, y: 0.85 }, { x: 0.75, y: 0.85 }, { x: 0.25, y: 0.85 }, { x: 0.75, y: 0.85 }],
  box: [{ x: 0.25, y: 0.92 }, { x: 0.3, y: 0.62 }, { x: 0.72, y: 0.62 }, { x: 0.78, y: 0.92 }, { x: 0.5, y: 0.78 }],
};
/** o: {marks: a MARK_SETS name or a list, radius, runs, fps, noise, seed, skip: [mark index], noSetup, setupOverride
 *  (the raw setup the pane sends instead, however malformed), drops, base}.
 *  Truth: each run's exact splits, from the continuous path crossing each gate. */
export async function agilityRun(o) {
  const opt = Object.assign({ marks: 'line', radius: 0.05, runs: 2, fps: 15, noise: 0.003, seed: 1, skip: [], phase: 0.021, drops: 0 }, o || {});
  const uc = await useCase('console-coach-agility.js', opt.base);
  const r = rng(opt.seed), marks = typeof opt.marks === 'string' ? MARK_SETS[opt.marks] : opt.marks, rad = opt.radius;
  const legs = []; // {a, b, from, to, moving}
  let t = 0, here = { x: marks[0].x + 0.004, y: marks[0].y };
  const go = (to, dur, moving) => { legs.push({ a: here, b: to, from: t, to: t + dur, moving }); t += dur; here = to; };
  const near = (m) => { const a = r() * 2 * Math.PI, d = r() * 0.6 * rad; return { x: m.x + d * Math.cos(a), y: m.y + d * Math.sin(a) }; };
  for (let run = 0; run < opt.runs; run += 1) {
    go(here, 1.5 + r() * 0.5, false); // stand on the first mark
    for (let k = 1; k < marks.length; k += 1) {
      if (opt.skip.includes(k)) continue;
      const to = near(marks.at(k)), dd = Math.hypot(to.x - here.x, to.y - here.y);
      go(to, 0.6 + dd * (2.2 + r() * 0.8), true);
      go(here, r() * 0.15, false); // a turn or a plant
    }
    if (run + 1 < opt.runs) go({ x: marks[0].x + 0.004, y: marks[0].y }, 3 + r(), true); // walk back
  }
  go(here, 1.0, false);
  const pathAt = (tt) => {
    const l = legs.find((x) => tt >= x.from && tt < x.to) || legs.at(-1);
    const k = minJerk((tt - l.from) / Math.max(1e-6, l.to - l.from));
    return { x: lerp(l.a.x, l.b.x, k), y: lerp(l.a.y, l.b.y, k), moving: l.moving };
  };
  // the truth: the exact crossings of each run (1 ms steps)
  const truth = [];
  let cur = null, step = 0;
  for (let tt = 0; tt < t; tt += 0.001) {
    const q = pathAt(tt), d = (m) => Math.hypot(q.x - m.x, q.y - m.y);
    if (!cur && d(marks[0]) <= rad) cur = { armed: true, last: -1, splits: [], next: 1, from: 0 };
    if (cur && cur.armed && d(marks[0]) > rad && pathAt(tt).moving) { cur.armed = false; cur.from = tt; step = 1; }
    if (cur && !cur.armed && step) {
      const want = cur.next;
      if (opt.skip.includes(want)) cur.next += 1;
      if (d(marks.at(cur.next)) <= rad) { cur.splits.push(tt - cur.from); cur.from = tt; cur.next += 1; }
      if (cur.next >= marks.length) { truth.push(cur.splits); cur = null; step = 0; tt += 0.6; }
    }
  }
  const given = 'setupOverride' in opt ? opt.setupOverride : (opt.noSetup ? null : { marks, radius: rad });
  let state;
  const measured = [];
  const n = Math.round(t * opt.fps);
  for (let i = 0; i <= n; i += 1) {
    if (opt.drops && i % opt.drops === opt.drops - 1) continue;
    const tt = opt.phase + i / opt.fps, q = pathAt(tt);
    const stride = q.moving ? 0.12 * Math.sin(tt * 2 * Math.PI * 2.5) : 0;
    const was = state && state.runs !== undefined ? state.runs : 0;
    state = uc.onResult(res(bodyAt(q.x, q.y, stride, r, opt.noise), tt, given), state);
    if (state.runs > was) measured.push(state.legs);
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, truth, measured, missed: state.missed });
}

// ---- side-on bodies (rows 237, 239) ---------------------------------------------------------------------------------
const RAD = Math.PI / 180;
/** A body seen side-on, facing +x. Angles in degrees from the vertical: shin (the knee forward of the ankle), thigh
 *  (the hip behind the knee), lean (the shoulders forward of the hip), arm (from hanging down; + forward), bend (the
 *  elbow). Hip flexion is lean + thigh, knee flexion shin + thigh. */
export function sideBody(o) {
  const a = Object.assign({ ax: 0, shin: 0, thigh: 0, lean: 0, arm: 0, bend: 0 }, o || {});
  const seg = (from, len, deg, up) => add(from, v3(len * Math.sin(deg * RAD), (up ? 1 : -1) * len * Math.cos(deg * RAD), 0));
  const A = v3(a.ax, 0.08, 0), K = seg(A, 0.45, a.shin, true), H = seg(K, 0.45, -a.thigh, true), S = seg(H, 0.5, a.lean, true);
  const E = seg(S, 0.3, a.arm, false), W = seg(E, 0.28, a.arm + a.bend, false);
  const nose = add(seg(S, 0.25, a.lean, true), v3(0.08, 0, 0));
  const pair = (p) => [add(p, v3(0, 0, -0.1)), add(p, v3(0.01, 0, 0.1))];
  const [lsh, rsh] = pair(S), [lel, rel] = pair(E), [lwr, rwr] = pair(W), [lhip, rhip] = pair(H), [lkn, rkn] = pair(K), [lan, ran] = pair(A);
  const heel = (p) => add(p, v3(-0.05, -0.06, 0)), toe = (p) => add(p, v3(0.15, -0.07, 0));
  return { nose, lsh, rsh, lel, rel, lwr, rwr, lhip, rhip, lkn, rkn, lan, ran, lhe: heel(lan), rhe: heel(ran), lto: toe(lan), rto: toe(ran) };
}
/** Upside down on the hands at hx: shoulders over the hands, hips over the shoulders moved by `drift` (m), feet up. */
export function handstandBody(hx, drift, sway) {
  const W = v3(hx, 0.02, 0), S = v3(hx + 0.03, 0.62, 0), H = v3(hx + 0.03 + drift + sway, 1.12, 0);
  const K = add(H, v3(0.02, 0.45, 0)), A = add(K, v3(0.03, 0.45, 0)), E = blend(W, S, 0.5);
  const pair = (p) => [add(p, v3(0, 0, -0.1)), add(p, v3(0.01, 0, 0.1))];
  const [lsh, rsh] = pair(S), [lel, rel] = pair(E), [lwr, rwr] = pair(W), [lhip, rhip] = pair(H), [lkn, rkn] = pair(K), [lan, ran] = pair(A);
  const heel = (p) => add(p, v3(-0.05, 0.06, 0)), toe = (p) => add(p, v3(0.15, 0.07, 0));
  return { nose: v3(hx + 0.08, 0.42, 0), lsh, rsh, lel, rel, lwr, rwr, lhip, rhip, lkn, rkn, lan, ran,
    lhe: heel(lan), rhe: heel(ran), lto: toe(lan), rto: toe(ran) };
}
const blendBody = (a, b, k) => Object.fromEntries(NAMES.map((n) => [n, blend(a[n], b[n], k)]));

// ---- row 237: handstand holds ---------------------------------------------------------------------------------------
/** o: {holds: [s], drift: {hold, at (s into it), amount (m)}, setup ({support, limit} or none), fps, noise, seed, vis,
 *  spotter (the second body's own session: standing beside him), lostAt (s: the model loses him there, mid-hold),
 *  viewAt (s: the view then too), base}. Truth: each hold's span, when the drift passed the limit. */
export async function handstandSession(o) {
  const opt = Object.assign({ holds: [12], fps: 10, noise: 0.003, seed: 1, phase: 0.017, kick: 0.5, vis: 0.8 }, o || {});
  const uc = await useCase('console-coach-handstand.js', opt.base);
  const r = rng(opt.seed), stand = sideBody({ ax: 0.1, arm: 5 }), plan = [];
  let t = 1.5;
  opt.holds.forEach((h) => { plan.push({ kick: t, up: t + opt.kick, down: t + opt.kick + h, off: t + 2 * opt.kick + h }); t += 2 * opt.kick + h + 2.5; });
  const driftAt = (i, tt) => { // the hips' drift (m) of hold i at time tt: ramps to `amount` over a second, holds, back
    const d = opt.drift;
    if (!d || d.hold !== i) return 0;
    const u = tt - plan.at(i).up - d.at;
    return u < 0 ? 0 : d.amount * Math.min(1, u) * (u > 2.5 ? Math.max(0, 1 - (u - 2.5)) : 1);
  };
  let state, overAt = null, mid = null;
  const n = Math.round((t + 0.5) * opt.fps);
  for (let i = 0; i <= n; i += 1) {
    const tt = opt.phase + i / opt.fps;
    if (opt.lostAt && tt >= opt.lostAt) break; // nothing more reaches the use case
    const k = plan.findIndex((j) => tt >= j.kick && tt < j.off);
    let b = stand;
    if (k >= 0 && !opt.spotter) {
      const j = plan.at(k), sw = 0.015 * Math.sin(tt * 2.1);
      const inv = handstandBody(0.4, driftAt(k, tt), sw);
      b = tt < j.up ? blendBody(stand, inv, (tt - j.kick) / opt.kick) : tt < j.down ? inv : blendBody(inv, stand, (tt - j.down) / opt.kick);
    }
    state = uc.onResult(res(draw(b, { noise: opt.noise, r, vis: opt.vis }), tt, opt.setup), state);
    if (overAt === null && state.over) overAt = tt;
    if (opt.viewAt && !mid && tt >= opt.viewAt) mid = uc.summary(state).view;
  }
  if (opt.lostAt) await new Promise((ok) => { setTimeout(ok, 1700); }); // the pane asks again 1.7 s later
  const out = uc.summary(state);
  const lim = (opt.setup && opt.setup.limit) || 0.3;
  const passAt = opt.drift ? plan.at(opt.drift.hold).up + opt.drift.at + Math.min(1, lim * 0.5 / opt.drift.amount) : null;
  return plainOut({ tally: out.tally, view: out.view, mid, holds: state.holds, best: state.best, last: state.last,
    drifts: state.drifts, overAt, passAt, truth: plan.map((j) => j.down - j.up) });
}

/** Row 237 through the REAL port core (driver.mjs, the R8.1 join): one hold, the wall or spotter given (or not) only
 *  through live(..., {setup}), as the Workout pane passes it. -> drive()'s answer. */
export async function handstandDriver(o) {
  const opt = Object.assign({ hold: 12, seed: 4, noise: 0.003, setup: null }, o || {});
  const r = rng(opt.seed), stand = sideBody({ ax: 0.1, arm: 5 }), kick = 0.5, up = 1.5 + kick, down = up + opt.hold;
  const scene = (tt) => {
    const inv = handstandBody(0.4, 0, 0.015 * Math.sin(tt * 2.1));
    const b = tt < 1.5 ? stand : tt < up ? blendBody(stand, inv, (tt - 1.5) / kick) : tt < down ? inv
      : tt < down + kick ? blendBody(inv, stand, (tt - down) / kick) : stand;
    return [{ track: 0, who: '', points: draw(b, { noise: opt.noise, r, vis: 0.8 }) }];
  };
  return drive({ file: 'console-coach-handstand.js', id: 'handstand', scene, seconds: down + kick + 2, setup: opt.setup, rate: 10 });
}

// ---- row 239: kettlebell swings -------------------------------------------------------------------------------------
const HINGE = { lean: 60, thigh: 15, shin: 10 }; // the bottom of a hinge: hips back, shins near upright
const SQUAT = { lean: 35, thigh: 60, shin: 30 }; // the bottom of a squat swing: knees forward and deep
/** o: {swings, squats: [swing numbers that squat], partial: [swing numbers that stop at the belly: never a swing],
 *  fps, noise, seed, jitter (degrees), topArm, viewAt (s: the view then too), base}. Truth: each swing's style. */
export async function kettlebellSession(o) {
  const opt = Object.assign({ swings: 20, squats: [], partial: [], fps: 15, noise: 0.003, seed: 1, jitter: 6, topArm: 80,
    phase: 0.011 }, o || {});
  const uc = await useCase('console-coach-kettlebell.js', opt.base);
  const r = rng(opt.seed), j = () => (r() - 0.5) * 2 * opt.jitter, plan = [];
  let t = 1.0;
  for (let i = 0; i < opt.swings; i += 1) {
    const style = opt.squats.includes(i) ? 'squat' : 'hinge', b = style === 'squat' ? SQUAT : HINGE;
    const period = 1.1 + r() * 0.3;
    const top = opt.partial.includes(i) ? 40 + j() : opt.topArm + j();
    plan.push({ style, from: t, period, bottom: { lean: b.lean + j(), thigh: b.thigh + j(), shin: b.shin + j() }, top,
      part: opt.partial.includes(i) });
    t += period;
  }
  const at = (tt) => {
    const s = plan.find((x) => tt >= x.from && tt < x.from + x.period);
    if (!s) { // standing, the bell hanging; then parked at the end (bent over, the bell low)
      if (tt < plan[0].from) return { arm: 0 };
      const k = Math.min(1, (tt - t) / 0.8);
      return { lean: 70 * k, thigh: 15 * k, shin: 10 * k, arm: -5 * k };
    }
    const phi = (tt - s.from) / s.period, k = (1 - Math.cos(2 * Math.PI * phi)) / 2; // 0 at a bottom, 1 at the top
    const after = plan.at(plan.indexOf(s) + 1), low = phi < 0.5 ? s.bottom : (after ? after.bottom : s.bottom);
    return { lean: lerp(low.lean, 0, k), thigh: lerp(low.thigh, 0, k), shin: lerp(low.shin, 0, k), arm: lerp(-20, s.top, k) };
  };
  let state, mid = null;
  const styles = [];
  const n = Math.round((t + 2) * opt.fps);
  for (let i = 0; i <= n; i += 1) {
    const tt = opt.phase + i / opt.fps;
    const was = state && state.swings !== undefined ? state.swings : 0;
    state = uc.onResult(res(draw(sideBody(Object.assign({ ax: -0.1 }, at(tt))), { noise: opt.noise, r }), tt), state);
    if (state.swings > was) styles.push(state.lastHinge ? 'hinge' : 'squat');
    if (opt.viewAt && !mid && tt >= opt.viewAt) mid = uc.summary(state).view;
  }
  const out = uc.summary(state);
  return plainOut({ tally: out.tally, view: out.view, mid, styles, truth: plan.filter((x) => !x.part).map((x) => x.style) });
}

/** Row 235: rebound jumps (the next takeoff inside the last landing's half second): each landing is still judged. */
export async function reboundJumps(o) {
  const opt = Object.assign({ jumps: 5, h: 0.15, contact: 0.25, fps: 30, seed: 2, base: undefined }, o || {});
  const uc = await useCase('console-coach-jump.js', opt.base);
  const r = rng(opt.seed), v = Math.sqrt(2 * G * opt.h), flight = 2 * v / G, cycle = flight + opt.contact;
  let state;
  for (let i = 0; i <= Math.round((1 + opt.jumps * cycle + 1.5) * opt.fps); i += 1) {
    const tt = i / opt.fps, u = tt - 1, k = Math.floor(u / cycle), w = u - k * cycle;
    const air = u >= 0 && k < opt.jumps && w < flight;
    const lift = air ? v * w - G * w * w / 2 : 0, drop = !air && u > 0 && k <= opt.jumps ? 0.01 : 0; // stiff contacts
    state = uc.onResult(res(draw(frontBody({ lift, drop }), { noise: 0.002, r }), tt), state);
  }
  return plainOut({ tally: uc.summary(state).tally });
}
