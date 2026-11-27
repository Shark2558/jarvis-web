// src/jarvis/api/static/console-coach-geom.js -- R8 I0 seam S20 (docs/plans/r8-vision.md v8.0.3; frozen: an addition
// needs a contract line in docs/plans/r8-integration/I0-SEAMS.md). The coaches' shared geometry, PURE: numbers in,
// numbers out; no page, no network, no storage, no camera, no engine (tests/test_r8_console_seams.py holds it to the
// use-case guard, `export` aside). A use case imports what it needs:
//   import { angle, dist, ema, reps, hold, sway, sequence } from './console-coach-geom.js';
// Points are the engine's {x, y, z, visibility} (pose, 0..1 of the frame) or {x, y, z} (hands). Times are seconds.
// Every function returns a NEW object; nothing is changed in place.
//   angle(a, b, c)                 the angle at b, in degrees 0..180 (NaN when a point is missing or two coincide)
//   dist(a, b)                     the distance in the frame's units (x and y only)
//   ema(prev, value, k)            exponential smoothing; prev undefined starts at value; k 0..1 (the new value's weight)
//   reps(state, value, {down, up}) a rep counter on one number (an angle): a rep is a dip below `down` then a rise above
//                                  `up` (down < up, so a value between them changes nothing); -> {phase, count, at,
//                                  downAt, lastDown, lastUp} (lastDown / lastUp: the seconds each half took)
//   hold(state, ok, t)             a hold timer: -> {holding, since, best, total}; ok false ends a hold
//   sway(points)                   the spread (standard deviation) of x and y over a window of points -> {x, y, r}
//   sequence(steps, expected)      steps done in order -> {matched, outOfOrder, missing}
const DEG = 180 / Math.PI;
const ok = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y);

export function angle(a, b, c) {
  if (!ok(a) || !ok(b) || !ok(c)) return NaN;
  const ux = a.x - b.x, uy = a.y - b.y, vx = c.x - b.x, vy = c.y - b.y;
  const nu = Math.hypot(ux, uy), nv = Math.hypot(vx, vy);
  if (!nu || !nv) return NaN;
  const cos = Math.min(1, Math.max(-1, (ux * vx + uy * vy) / (nu * nv)));
  return Math.acos(cos) * DEG;
}

export function dist(a, b) {
  return ok(a) && ok(b) ? Math.hypot(a.x - b.x, a.y - b.y) : NaN;
}

export function ema(prev, value, k) {
  if (!Number.isFinite(value)) return prev;
  if (prev === undefined || !Number.isFinite(prev)) return value;
  const w = Math.min(1, Math.max(0, k));
  return prev + w * (value - prev);
}

export function reps(state, value, limits) {
  const s = state || { phase: 'up', count: 0, at: 0, downAt: 0, lastDown: 0, lastUp: 0 };
  const t = Number.isFinite(limits && limits.t) ? limits.t : s.at;
  if (!Number.isFinite(value) || !limits || !(limits.down < limits.up)) return s;
  if (s.phase === 'up' && value < limits.down) return Object.assign({}, s, { phase: 'down', downAt: t, lastDown: t - s.at, at: t });
  if (s.phase === 'down' && value > limits.up) return Object.assign({}, s, { phase: 'up', count: s.count + 1, lastUp: t - s.downAt, at: t });
  return s;
}

export function hold(state, good, t) {
  const s = state || { holding: false, since: 0, best: 0, total: 0, last: t };
  const gap = Math.max(0, t - (Number.isFinite(s.last) ? s.last : t));
  if (good && s.holding) {
    const now = t - s.since;
    return Object.assign({}, s, { best: Math.max(s.best, now), total: s.total + gap, last: t });
  }
  if (good) return Object.assign({}, s, { holding: true, since: t, last: t });
  return Object.assign({}, s, { holding: false, last: t });
}

export function sway(points) {
  const ps = (Array.isArray(points) ? points : []).filter(ok);
  if (ps.length < 2) return { x: 0, y: 0, r: 0 };
  const spread = (vs) => { const m = vs.reduce((n, v) => n + v, 0) / vs.length; return Math.sqrt(vs.reduce((n, v) => n + (v - m) * (v - m), 0) / vs.length); };
  const x = spread(ps.map((p) => p.x)), y = spread(ps.map((p) => p.y));
  return { x, y, r: Math.hypot(x, y) };
}

export function sequence(steps, expected) {
  const done = Array.isArray(steps) ? steps : [], want = Array.isArray(expected) ? expected : [];
  let next = 0, outOfOrder = 0;
  for (const step of done) {
    if (step === want.slice(next, next + 1)[0]) next += 1;
    else if (want.includes(step)) outOfOrder += 1;
  }
  return { matched: next, outOfOrder, missing: want.slice(next) };
}
