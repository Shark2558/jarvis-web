// tests/fixtures/r8/tests_sequences.mjs -- R8.1 builder H (docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8): the
// partner, walk, sit-to-stand and meal coaches' synthetic sessions, run in Node by tests/test_r81_h_coaches.py and
// evals/r8_1/care.py through tests/r8_fakes.run_node. Never a real person's data: every body and hand here is made up
// from numbers. Each scenario loads the REAL use-case module (src/jarvis/api/static/console-coach-<x>.js) behind a
// stand-in for JarvisVision.use, feeds it Results the way the engine's driver does (a state per body, keyed by its
// track; a lone body on the phone is "me", two or more are ""; hands reach every body's state), and returns what a
// test checks: the module's tally, view and states, and the scenario's own truth (computed here from the script, never
// read from the module). Times are seconds; `t` rides on each Result (the engine's clock stand-in) and `setup` is what
// the Workout pane passes (a contract line for I1: live(..., {setup}) puts each use case's setup on its Results).
//   partnerSession(o)  row 240: the owner lying side-on, stretched by a partner kneeling beside him
//   partnerDriver(o)   row 240 through the REAL port core (console-vision.js in a vm, a fake camera, a fake pose task)
//   walkSession(o)     row 263: lengths of a course seen side-on or end-on, with turns, for six minutes
//   sitStandSession(o) row 269: a closed loop on the coach's Go: full stands, partial stands, the 30-second edge
//   mealSession(o)     row 247: bites at a table, things that are not bites, and another person in view
import fs from 'node:fs';
import vm from 'node:vm';
import * as handsFx from './hands.mjs';
import * as posesFx from './poses.mjs';

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
export function res(task, data, t, extra) {
  return freeze(Object.assign({ task, v: task === 'pose' ? 2 : 1, at: BASE_AT + Math.floor(t), ms: 20, device: 'phone', ok: true,
    data, quality: { light: 0.8, sharp: 0.8 }, t }, extra || {}));
}
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const lerp = (a, b, k) => a + (b - a) * k;
const minJerk = (k) => { const c = Math.min(1, Math.max(0, k)); return c * c * c * (10 - 15 * c + 6 * c * c); };
const plainOut = (v) => JSON.parse(JSON.stringify(v === undefined ? null : v));
const hasNumber = (v) => /[0-9]/.test(JSON.stringify(v === undefined ? null : v));

/** The engine's driver, as a stand-in: a state per body (its track); a lone body on this phone is "me" (no face is
 *  matched on a device); target 'me' tells only such a body; a hands Result reaches every body's state. */
function driver(uc, opts) {
  const o = Object.assign({ target: 'all', setup: undefined }, opts || {});
  const states = new Map(), seen = new Map();
  const extra = (more) => Object.assign(o.setup ? { setup: o.setup } : {}, more || {});
  return {
    states,
    seen,
    pose(bodies, t) {
      const who = bodies.length === 1 ? 'me' : '';
      bodies.filter(() => o.target === 'all' || who === 'me').forEach((b) => {
        const r = res('pose', { points: b.points }, t, extra({ track: b.track, who }));
        const next = uc.onResult(r, states.get(b.track));
        states.set(b.track, next);
        if (!seen.has(b.track)) seen.set(b.track, new Set());
        seen.get(b.track).add(JSON.stringify(next === undefined ? null : next));
      });
    },
    hands(list, t) {
      const r = res('hands', { hands: list.slice(0, 2) }, t, extra());
      [...states.keys()].forEach((k) => {
        const next = uc.onResult(r, states.get(k));
        states.set(k, next);
        seen.get(k).add(JSON.stringify(next === undefined ? null : next));
      });
    },
  };
}

// ---- row 240: assisted stretching ---------------------------------------------------------------------------------------
// The owner lies side-on to the phone (torso level, head to the left). A stretch moves one joint and the others rest:
//   hip       the straight leg raised (hamstring): the hip's flexion   = 180 - the shoulder-hip-knee angle
//   knee      the heel drawn to the seat (quad): the knee's flexion     = 180 - the hip-knee-ankle angle
//   shoulder  the straight arm taken overhead: the arm off the torso   = the hip-shoulder-elbow angle
// This file's OWN truth of each stretch's range (from the script's joint angles, never from the module).
const ARM_REST = 80; // the arm along the body: the shoulder's own rest angle is |ARM_REST - 90| = 10 degrees
export function stretchRange(joint, amount) { return joint === 'shoulder' ? Math.abs(ARM_REST + amount - 90) : amount; }

function ownerLying(flex, o, seed) {
  return posesFx.body({ torso: 90, hip: 180 - flex.hip, knee: 180 - flex.knee, shoulder: ARM_REST + flex.shoulder, elbow: 180 },
    { cx: o.cx, cy: 0.72, scale: 0.36, noise: o.noise, seed });
}
function partnerKneeling(t, o, seed) {
  const wild = o.partner === 'wild';
  const wave = wild ? 70 * Math.sin(2.1 * t) : 8 * Math.sin(0.7 * t);
  return posesFx.body({ hip: 95 + (wild ? 30 * Math.sin(0.9 * t) : 0), knee: 95, torso: 15 + (wild ? 20 * Math.sin(1.3 * t) : 0),
    shoulder: 60 + wave, elbow: 120 + wave / 2 }, { cx: 0.78 + (wild ? 0.03 * Math.sin(0.5 * t) : 0), cy: 0.45, scale: 0.36,
    noise: o.noise, seed: seed + 7 });
}

/** The scripted timeline: [{from, to, phase, joint, amount(t)}] and the stretches' truths. */
function stretchPlan(opt) {
  const plan = [], truths = [];
  let t = opt.lead;
  for (const st of opt.stretches) {
    const x = Object.assign({ joint: 'hip', peak: 70, hold: 12, rise: 2, release: 1.5, rest: 4, deepen: 0 }, st);
    const from = t;
    plan.push({ from, to: from + x.rise, phase: 'into', joint: x.joint, amount: (u) => x.peak * minJerk((u - from) / x.rise) });
    const holdFrom = t + x.rise;
    plan.push({ from: holdFrom, to: holdFrom + x.hold, phase: 'hold', joint: x.joint, amount: (u) => x.peak + x.deepen * (u - holdFrom) / x.hold });
    const relFrom = holdFrom + x.hold, top = x.peak + x.deepen;
    plan.push({ from: relFrom, to: relFrom + x.release, phase: 'release', joint: x.joint, amount: (u) => top * (1 - minJerk((u - relFrom) / x.release)) });
    truths.push({ joint: x.joint, range: stretchRange(x.joint, top), hold: x.hold });
    t = relFrom + x.release + x.rest;
  }
  return { plan, truths, end: t };
}
function flexAt(plan, t) {
  const flex = { hip: 0, knee: 0, shoulder: 0 };
  const seg = plan.find((p) => t >= p.from && t < p.to);
  if (seg) flex[seg.joint] = seg.amount(t);
  return { flex, phase: seg ? seg.phase : 'rest' };
}

/** o: {seed, fps, noise, lead, partnerAt, partnerTill, partner: 'none'|'still'|'wild', stretches, consent, consentAt,
 *  stretch, swapAt, ownerTrackAt, partnerAloneAt, base} -> the owner's tally, view and stretches; the partner's
 *  states (every one the module returned), its view and tally; frame phases for the hold's F1; the truths. */
export async function partnerSession(o) {
  const opt = Object.assign({ seed: 1, fps: 10, noise: 0.002, lead: 2, partnerAt: 1.2, partnerTill: Infinity, partner: 'still',
    stretches: [{}], consent: true, consentAt: 0, stretch: undefined, swapAt: null, partnerAloneAt: null, cx: 0.5 }, o || {});
  const uc = await useCase('console-coach-partner.js', opt.base);
  const setup = opt.consent ? { consent: true, consent_at: BASE_AT + opt.consentAt } : { consent: false };
  if (opt.stretch) setup.stretch = opt.stretch;
  const d = driver(uc, { setup });
  const { plan, truths, end } = stretchPlan(opt);
  const hold = { tp: 0, fp: 0, fn: 0 };
  let ownerTrack = 0;
  for (let i = 0; i <= Math.round((end + 1) * opt.fps); i += 1) {
    const t = i / opt.fps, seed = opt.seed * 7919 + i;
    const { flex, phase } = flexAt(plan, t);
    const owner = ownerLying(flex, opt, seed);
    const withPartner = opt.partner !== 'none' && t >= opt.partnerAt && t < opt.partnerTill;
    const partner = withPartner ? partnerKneeling(t, opt, seed) : null;
    const bodies = [];
    // the owner leaves the view (and the partner is alone, on a new track) from partnerAloneAt
    if (opt.partnerAloneAt !== null && t >= opt.partnerAloneAt) bodies.push({ track: 5, points: partnerKneeling(t, opt, seed) });
    else {
      // a swap: from swapAt the engine's track 0 follows the partner and track 1 the owner
      const swapped = opt.swapAt !== null && t >= opt.swapAt;
      ownerTrack = swapped ? 1 : 0;
      bodies.push({ track: ownerTrack, points: owner });
      if (partner) bodies.push({ track: swapped ? 0 : 1, points: partner });
    }
    d.pose(bodies.sort((a, b) => a.track - b.track), t);
    if (opt.swapAt === null && opt.partnerAloneAt === null) {
      const got = d.states.get(0) && d.states.get(0).phase === 'hold', want = phase === 'hold';
      if (got && want) hold.tp += 1; else if (got) hold.fp += 1; else if (want) hold.fn += 1;
    }
  }
  const sumOf = (k) => (d.states.has(k) ? uc.summary(d.states.get(k)) : null);
  const owner = sumOf(0), partner = sumOf(1), alone = sumOf(5);
  const others = [1, 5].filter((k) => d.seen.has(k));
  return plainOut({
    truths,
    tally: owner && owner.tally, view: owner && owner.view,
    done: d.states.get(0) && d.states.get(0).done, kind: d.states.get(0) && d.states.get(0).kind,
    lost: !!(d.states.get(0) && d.states.get(0).lost),
    partnerStates: others.flatMap((k) => [...d.seen.get(k)]),
    partnerHoldsNumbers: others.some((k) => [...d.seen.get(k)].some((s) => /[0-9]/.test(s))),
    partnerView: partner && partner.view, partnerTally: partner && partner.tally,
    aloneView: alone && alone.view, aloneTally: alone && alone.tally,
    partnerViewHasNumber: !!(partner && hasNumber(partner.view)) || !!(alone && hasNumber(alone.view)),
    hold,
  });
}

/** The same session through the REAL port core: console-vision.js runs in a vm with a fake camera and a fake `pose`
 *  task that reports the scripted bodies; the use case registers with the real JarvisVision.use (a pass-through records
 *  every state it returns, and adds `setup` to its Results as I1's contract line will); a virtual clock drives the
 *  driver's own timers. -> the engine's tracks and its tally() for each track, and the partner's recorded states. */
export async function partnerDriver(o) {
  const opt = Object.assign({ seed: 3, noise: 0.002, lead: 2, partnerAt: 1.2, partner: 'wild', consent: true, rate: 10,
    stretches: [{ peak: 65, hold: 8 }] }, o || {});
  const src = fs.readFileSync(new URL('console-vision.js', STATIC), 'utf8');
  const cut = src.replace(/\nsealRegistry\(\);\n?/, '\n').replace("id: 'pose', v: 2,", "id: 'pose-shell', v: 2,");
  if (cut === src || !cut.includes("id: 'pose-shell'")) throw new Error('the port core changed shape: update partnerDriver');
  let now = 0;
  const timers = [];
  const clock = { now: () => now };
  const ctx = { navigator: { userAgent: 'Android' }, console, performance: clock, addEventListener: () => {},
    setTimeout: (fn, ms) => { timers.push({ at: now + Math.max(0, Number(ms) || 0), fn }); return timers.length; }, clearTimeout: () => {},
    document: { createElement: () => ({ getContext: () => null }), head: { append() {} } } };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(cut, ctx, { filename: 'console-vision.js' });
  const V = ctx.JarvisVision;
  const { plan, end } = stretchPlan(opt);
  const scene = (t) => {
    const seed = opt.seed * 7919 + Math.round(t * 100);
    const bodies = [{ track: 0, who: '', points: ownerLying(flexAt(plan, t).flex, { cx: 0.5, noise: opt.noise }, seed) }];
    if (t >= opt.partnerAt) bodies.push({ track: 1, who: '', points: partnerKneeling(t, { partner: opt.partner, noise: opt.noise }, seed) });
    return bodies;
  };
  V.register({ id: 'pose', v: 2, input: 'both', rate: 15, run: (f) => { if (!f) throw new Error('There is no picture to look at.'); return { data: { bodies: scene(now / 1000) } }; },
    check: (dd) => !!dd && Array.isArray(dd.bodies) });
  ctx.JarvisCamera = { live: () => true, frame: () => ({ w: 1 }), onChange: () => () => {} };
  const consentAt = Math.floor(Date.now() / 1000);
  const setup = opt.consent ? Object.freeze({ consent: true, consent_at: consentAt }) : null;
  const recorded = [];
  const realPerf = Object.getOwnPropertyDescriptor(globalThis, 'performance');
  Object.defineProperty(globalThis, 'performance', { value: clock, configurable: true, writable: true });
  globalThis.JarvisVision = Object.freeze({ use: (u) => V.use({ id: u.id, tasks: u.tasks, summary: u.summary,
    onResult: (r, s) => {
      const next = u.onResult(setup ? Object.freeze(Object.assign({}, r, { setup })) : r, s);
      recorded.push({ track: r.track, who: r.who, state: JSON.stringify(next === undefined ? null : next) });
      return next;
    } }) });
  await import(new URL(`console-coach-partner.js?driver=${opt.seed}`, opt.base ? new URL(`file://${opt.base.replace(/\/?$/, '/')}`) : STATIC).href);
  const errors = [];
  const h = V.live(['pose'], { uses: ['partner-stretch'], rate: opt.rate, target: { kind: 'all' }, onError: (e) => errors.push(String(e && e.message)) });
  while (now < (end + 1) * 1000) {
    await new Promise((r) => setImmediate(r));
    timers.sort((a, b) => a.at - b.at);
    const next = timers.shift();
    if (!next) break;
    now = next.at;
    next.fn();
  }
  await new Promise((r) => setImmediate(r));
  h.end();
  if (realPerf) Object.defineProperty(globalThis, 'performance', realPerf);
  const tracks = plainOut(V.tracks('partner-stretch'));
  const tallies = tracks.map((tr) => Object.assign({ track: tr.track }, plainOut(V.tally('partner-stretch', tr.track))));
  const partner = recorded.filter((x) => x.track === 1);
  return plainOut({ errors, tracks, tallies, frames: recorded.length, partnerFrames: partner.length,
    partnerStates: [...new Set(partner.map((x) => x.state))], ownerFrames: recorded.filter((x) => x.track === 0).length });
}

// ---- row 263: the six-minute walk ---------------------------------------------------------------------------------------
const WALK_S = 360;
/** One length's progress 0..1 at tau of len seconds: speed ramps up and down over `ramp` seconds at each end. */
function along(tau, len, ramp) {
  const r = Math.min(ramp, len / 3), v = 1 / (len - r);
  if (tau <= 0) return 0;
  if (tau >= len) return 1;
  if (tau < r) return 0.5 * v * tau * tau / r;
  if (tau > len - r) return 1 - 0.5 * v * (len - tau) * (len - tau) / r;
  return 0.5 * v * r + v * (tau - r);
}
function walkPlan(opt, lead, scale) {
  const r = rng(opt.seed), legs = [], f = scale || 1;
  let t = lead;
  for (let i = 0; t < lead + WALK_S + 30; i += 1) {
    const len = f * opt.lengthS * (1 + opt.jitter * (r() - 0.5)), turn = f * opt.turnS * (1 + opt.jitter * (r() - 0.5));
    legs.push({ from: t, to: t + len, off: t + len + turn, dir: i % 2 ? -1 : 1, len });
    t += len + turn;
  }
  return legs;
}
function walkTruth(legs, lead) {
  const T = lead + WALK_S;
  const laps = legs.filter((l) => l.to <= T).length, turns = legs.filter((l) => l.off <= T).length;
  const margin = Math.min(...legs.map((l) => Math.min(Math.abs(T - l.to), Math.abs(T - l.off))));
  return { laps, turns, margin, until: T };
}
function walker(legs, t, opt, seed) {
  const leg = legs.find((l) => t < l.off) || legs[legs.length - 1];
  const u0 = along(t - leg.from, leg.len, opt.ramp), u = leg.dir > 0 ? u0 : 1 - u0;
  const moving = t >= leg.from && t < leg.to, gait = moving ? Math.sin(2 * Math.PI * 1.8 * t) : 0;
  const angles = { hip: 180 - 20 * Math.max(0, gait), knee: 180 - 35 * Math.max(0, -gait), shoulder: 10 + 15 * gait };
  if (opt.view === 'end') {
    const metres = opt.near + opt.course * u, k = 0.8 / metres;
    return posesFx.body(angles, { cx: 0.5 + 0.03 * Math.sin(0.1 * t), cy: 0.45 + 0.25 * k, scale: k, noise: opt.noise, seed });
  }
  return posesFx.body(angles, { cx: lerp(opt.xa, opt.xb, u), cy: 0.55, scale: 0.3, noise: opt.noise, seed });
}

/** o: {seed, view: 'side'|'end', course (metres, typed), lengthS, turnS, jitter, lead, fps, noise, drop, clean, ends}
 *  clean: the walk's pace changes a little until the six minutes end at least 1 s from any length's end or set-off
 *  (so "exact" is fair); ends: 'mid' (default) or 'at-end' (time is up halfway through his pause at the end of a
 *  length, before he turns). The boundary is the walk's own (six minutes from his first step), so the pace moves it.
 *  -> the tally, the view, the truth {laps, turns, margin} */
export async function walkSession(o) {
  const opt = Object.assign({ seed: 1, view: 'side', course: 8, lengthS: 6, turnS: 1.2, jitter: 0.3, lead: 3, fps: 10, noise: 0.002,
    ramp: 0.6, drop: 0, clean: true, ends: 'mid', xa: 0.15, xb: 0.85, near: 1.5, setup: undefined }, o || {});
  const uc = await useCase('console-coach-walk.js', opt.base);
  const setup = opt.setup !== undefined ? opt.setup : { course_m: opt.course };
  const lead = opt.lead;
  let scale = 1, legs = walkPlan(opt, lead, scale), truth = walkTruth(legs, lead);
  for (let k = 1; opt.clean && opt.ends === 'mid' && truth.margin < 1.0 && k < 60; k += 1) {
    scale = 1 + 0.004 * k; legs = walkPlan(opt, lead, scale); truth = walkTruth(legs, lead);
  }
  if (opt.ends === 'at-end') { // scale the pace so the six minutes end halfway through a pause at a length's end
    const leg = legs.find((l) => l.to - lead > WALK_S - 15 && l.off - l.to > 0.8);
    scale = WALK_S / ((leg.to + leg.off) / 2 - lead);
    legs = walkPlan(opt, lead, scale);
    const T = lead + WALK_S, again = legs.find((l) => l.to <= T && l.off > T);
    truth = Object.assign(walkTruth(legs, lead), { atEnd: !!again });
  }
  const d = driver(uc, { setup });
  const stopAt = lead + WALK_S + 4;
  for (let i = 0; i <= Math.round(stopAt * opt.fps); i += 1) {
    if (opt.drop && i % opt.drop === opt.drop - 1) continue;
    const t = i / opt.fps;
    d.pose([{ track: 0, points: walker(legs, t, opt, opt.seed * 7919 + i) }], t);
  }
  const sum = uc.summary(d.states.get(0));
  return plainOut({ tally: sum.tally, view: sum.view, truth, scale });
}

// ---- row 269: sit to stand ----------------------------------------------------------------------------------------------
const SEATED = 90, UPRIGHT = 175, HALFWAY = (SEATED + UPRIGHT) / 2;
/** One cycle from `at`: rise (to UPRIGHT, or to `peak` for a partial stand), stand, sit, pause. -> {top, end, angle(t)} */
function cycle(at, x) {
  const peak = x.partial ? x.partialPeak : UPRIGHT, up = at + x.rise, down = up + x.stand, seat = down + x.sit;
  return { at, up, seat, end: seat + x.pause, partial: !!x.partial,
    angle: (t) => (t < at ? SEATED : t < up ? lerp(SEATED, peak, minJerk((t - at) / x.rise)) : t < down ? peak
      : t < seat ? lerp(peak, SEATED, minJerk((t - down) / x.sit)) : SEATED) };
}

/** o: {seed, fps, noise, rise, stand, sit, pause, react, jitter, partial: [cycle numbers], edge: 'above'|'below'|null,
 *  count, falseStart} -> the tally, the view, the truth {in30, five} (seconds from the coach's Go), go seen */
export async function sitStandSession(o) {
  const opt = Object.assign({ seed: 1, fps: 15, noise: 0.002, rise: 0.9, stand: 0.3, sit: 1.0, pause: 0.3, react: 0.4, jitter: 0.2,
    partial: [], partialPeak: 140, edge: null, count: 99, falseStart: false, seconds: 75 }, o || {});
  const uc = await useCase('console-coach-sitstand.js', opt.base);
  const d = driver(uc);
  const r = rng(opt.seed);
  let go = null, cycles = [];
  const plan = (g) => { // this file's schedule, from the coach's Go (the person reacts to it)
    const out = [], want = opt.edge === 'above' ? 0.62 : 0.3; // where in the edge rise the 30 s mark falls
    let t = g + opt.react, edged = !opt.edge;
    for (let n = 1; n <= opt.count && t < g + opt.seconds; n += 1) {
      const j = (v) => v * (1 + opt.jitter * (r() - 0.5));
      const x = { rise: j(opt.rise), stand: j(opt.stand), sit: j(opt.sit), pause: j(opt.pause), partial: opt.partial.includes(n), partialPeak: opt.partialPeak };
      const target = g + 30 - want * x.rise; // the edge: this full rise straddles the 30-second mark (only ever delayed)
      if (!edged && target - t < x.rise + x.stand + x.sit + x.pause) { t = Math.max(t, target); x.partial = false; edged = true; }
      const c = cycle(t, x);
      out.push(c);
      t = c.end;
    }
    return out;
  };
  let lean = 10;
  for (let i = 0; i <= Math.round((opt.seconds + 10) * opt.fps); i += 1) {
    const t = i / opt.fps;
    let a = SEATED;
    if (go === null && opt.falseStart && t > 1.6 && t < 2.6) a = lerp(SEATED, 150, minJerk((t - 1.6) / 0.5)); // rises early
    const c = cycles.find((x) => t >= x.at && t < x.end);
    if (c) a = c.angle(t);
    lean = c && t < c.up ? 10 + 25 * Math.sin(Math.PI * Math.min(1, (t - c.at) / (c.up - c.at))) : (a > 160 ? 0 : 10);
    const pts = posesFx.body({ hip: a, knee: a, torso: lean }, { cx: 0.5, cy: 0.55, scale: 0.34, noise: opt.noise, seed: opt.seed * 7919 + i });
    d.pose([{ track: 0, points: pts }], t);
    const s = d.states.get(0);
    if (go === null && s && Number.isFinite(s.go) && t >= s.go) { go = s.go; cycles = plan(go); }
  }
  const sum = uc.summary(d.states.get(0));
  if (go === null) return plainOut({ tally: sum.tally, view: sum.view, go: null, truth: null });
  const full = cycles.filter((c) => !c.partial), tops = full.map((c) => c.up - go);
  const at30 = cycles.find((c) => go + 30 >= c.at && go + 30 < c.up && !c.partial);
  const half = !!(at30 && at30.angle(go + 30) >= HALFWAY);
  return plainOut({ tally: sum.tally, view: sum.view, go,
    truth: { in30: tops.filter((x) => x <= 30).length + (half ? 1 : 0), five: tops.length >= 5 ? tops[4] : 0, half,
      stands: tops.length, partial: cycles.filter((c) => c.partial).length } });
}

// ---- row 247: eating pace -----------------------------------------------------------------------------------------------
// A front view of a person at a table, the phone propped in front: the head, shoulders (0.3 of the frame apart), the
// arms; the hips are behind the table (barely seen). A hand's fingers point up; at a bite the index tip is at the lips.
const HAND = 0.13; // the hand's length (wrist to fingertip), frame units
function upper(cx, right, left, noise, seed) {
  const r = rng(seed), n = () => (r() - 0.5) * 2 * noise;
  const pts = new Array(33).fill(null).map(() => ({ x: cx, y: 0.3 }));
  const set = (i, x, y, vis) => { pts[i] = { x: x + n(), y: y + n(), z: 0, visibility: vis === undefined ? 0.95 : vis }; };
  set(0, cx, 0.32); [1, 2, 3].forEach((i, k) => set(i, cx - 0.02 - 0.01 * k, 0.29)); [4, 5, 6].forEach((i, k) => set(i, cx + 0.02 + 0.01 * k, 0.29));
  set(7, cx - 0.06, 0.3); set(8, cx + 0.06, 0.3); set(9, cx - 0.02, 0.37); set(10, cx + 0.02, 0.37);
  set(11, cx - 0.15, 0.52); set(12, cx + 0.15, 0.52);
  const arm = (sh, w, el, wr, pinky, index, thumb, side) => {
    set(el, lerp(sh.x, w.x, 0.5) + 0.06 * side, lerp(sh.y, w.y, 0.5) + 0.08);
    set(wr, w.x, w.y); set(pinky, w.x + 0.02 * side, w.y - 0.7 * HAND); set(index, w.x, w.y - HAND); set(thumb, w.x - 0.03 * side, w.y - 0.5 * HAND);
  };
  arm({ x: cx - 0.15, y: 0.52 }, left, 13, 15, 17, 19, 21, -1);
  arm({ x: cx + 0.15, y: 0.52 }, right, 14, 16, 18, 20, 22, 1);
  [23, 24].forEach((i, k) => set(i, cx + (k ? 0.1 : -0.1), 0.88, 0.2));
  [25, 26, 27, 28, 29, 30, 31, 32].forEach((i) => set(i, cx, 0.98, 0.05));
  return pts;
}
const mouthOf = (cx) => ({ x: cx, y: 0.37 });

/** A meal's script: bites (the right hand to the lips and back) and gestures that are not bites. */
function mealPlan(opt) {
  const r = rng(opt.seed), acts = [];
  let t = opt.lead;
  while (t < opt.minutes * 60 + opt.lead) {
    const dwell = opt.dwell * (0.7 + 0.6 * r());
    acts.push({ kind: opt.bites === false ? (r() < 0.5 ? 'chin' : 'reach') : 'bite', at: t, up: 0.6, dwell, down: 0.6 });
    t += 1.2 + dwell;
    const gap = opt.gapS * (0.5 + r());
    if (opt.distractors && r() < 0.5) acts.push({ kind: r() < 0.5 ? 'chin' : 'reach', at: t + gap * 0.4, up: 0.6, dwell: 0.8, down: 0.6 });
    t += gap;
  }
  return acts;
}
function handAt(acts, t, cx) {
  const rest = { x: cx + 0.08, y: 0.85 };
  const a = acts.find((x) => t >= x.at && t < x.at + x.up + x.dwell + x.down);
  if (!a) return rest;
  const goal = a.kind === 'bite' ? { x: cx + 0.01, y: mouthOf(cx).y + HAND } : a.kind === 'chin' ? { x: cx + 0.1, y: 0.63 } : { x: cx + 0.32, y: 0.78 };
  const u = t - a.at;
  const k = u < a.up ? minJerk(u / a.up) : u < a.up + a.dwell ? 1 : 1 - minJerk((u - a.up - a.dwell) / a.down);
  return { x: lerp(rest.x, goal.x, k), y: lerp(rest.y, goal.y, k) };
}

/** o: {seed, minutes, gapS, dwell, distractors, bites (false: only gestures that are not bites), others: [[from, to]
 *  seconds], target: 'all'|'me', fps, noise, hands}
 *  -> the tally, the view, the views while another person was in view, the truth {bites, minutes} */
export async function mealSession(o) {
  const opt = Object.assign({ seed: 1, minutes: 12, gapS: 25, dwell: 0.5, distractors: true, others: [], target: 'all', fps: 10,
    noise: 0.002, hands: true, lead: 5 }, o || {});
  const uc = await useCase('console-coach-meal.js', opt.base);
  const d = driver(uc, { target: opt.target });
  const acts = mealPlan(opt), other = mealPlan(Object.assign({}, opt, { seed: opt.seed + 101, distractors: false }));
  const inOthers = (t) => opt.others.some(([a, b]) => t >= a && t < b);
  const pausedViews = [];
  const end = opt.lead + opt.minutes * 60 + 10;
  for (let i = 0; i <= Math.round(end * opt.fps); i += 1) {
    const t = i / opt.fps, seed = opt.seed * 7919 + i;
    const right = handAt(acts, t, 0.5), left = { x: 0.38, y: 0.85 };
    const bodies = [{ track: 0, points: upper(0.5, right, left, opt.noise, seed) }];
    const theirs = inOthers(t) ? handAt(other, t, 0.84) : null;
    if (theirs) bodies.push({ track: 1, points: upper(0.84, theirs, { x: 0.72, y: 0.85 }, opt.noise, seed + 3) });
    d.pose(bodies, t);
    if (opt.hands) {
      const list = [handsFx.hand({ side: 'right', cx: right.x, cy: right.y, size: HAND, noise: opt.noise, seed: seed + 11 })];
      if (theirs) list.push(handsFx.hand({ side: 'right', cx: theirs.x, cy: theirs.y, size: HAND, noise: opt.noise, seed: seed + 13 }));
      d.hands(list, t + 0.5 / opt.fps);
    }
    if (inOthers(t) && inOthers(t - 1) && i % (opt.fps * 10) === 0 && d.states.has(0)) pausedViews.push(uc.summary(d.states.get(0)).view);
  }
  const counted = acts.filter((a) => a.kind === 'bite' && !inOthers(a.at + a.up) && !inOthers(a.at + a.up + 0.3));
  const first = counted.length ? counted[0].at + counted[0].up : 0, last = counted.length ? counted[counted.length - 1].at + counted[counted.length - 1].up : 0;
  const sum = uc.summary(d.states.get(0));
  return plainOut({ tally: sum.tally, view: sum.view, pausedViews,
    truth: { bites: counted.length, minutes: (last - first) / 60, all: acts.filter((a) => a.kind === 'bite').length,
      other: acts.filter((a) => a.kind !== 'bite').length } });
}

/** A module's summary of no state (for the view checks). */
export async function emptySummary(file, base) {
  const uc = await useCase(file, base);
  return plainOut(uc.summary(undefined));
}
/** What a module registered: its id and tasks (the functions stay behind). */
export async function registered(file) {
  const u = await useCase(file);
  return { id: u.id, tasks: u.tasks, onResult: typeof u.onResult, summary: typeof u.summary };
}
export const CONSTANTS = Object.freeze({ WALK_S, HALFWAY, BASE_AT, RAD });
