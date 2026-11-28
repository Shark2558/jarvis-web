// src/jarvis/api/static/console-coach-reps.js -- R8.1 builder E, row 132 (= HF-03, rep and tempo; docs/plans/r8-vision.md
// v8.0.4 section 2.2): the tripod phone counts reps and their tempo. Use case `reps`: `pose` at up to 15 a second, one
// body's state at a time (the owner's D6: the driver keeps a state per body). The engine gives a use case no settings,
// so the exercise is found from the body: squat, lunge (side view, feet apart front to back), push-up (body level),
// curl (upper arm down, elbow bends), shoulder press (upper arm up, elbow straightens overhead), jumping jack (arms over
// the head and back). Each exercise has its own counter on one joint angle: a rep is a dip below `down` then a rise
// above `up` (console-coach-geom.js reps), so a half rep never counts. Tempo: how long the body moved down and up in
// each rep, read from the angle's speed (from the frame the movement passes a tenth of its top speed to the frame it
// falls under it again, scaled by the share of a smooth movement's time spent above that), so a pause at the top or
// bottom is not counted as moving. A gap of 20 s starts a new set.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; no page, network, storage or
// camera; it imports only the shared geometry. Angles live in this body's state for a few seconds (memory only).
// Tally: jarvis.coach.usecases' RepsTally (exercise, sets, reps, down_s, up_s, the session's start and end).
// Time: a Result's `t` (seconds) when the engine gives one, else the page's clock less the frame's own look time.
import { angle, dist } from './console-coach-geom.js';

const L = Object.freeze({ sh: 11, el: 13, wr: 15, hip: 23, kn: 25, an: 27 });
const R = Object.freeze({ sh: 12, el: 14, wr: 16, hip: 24, kn: 26, an: 28 });
const SEEN = 0.5; // a point's visibility below this is not used
const REST_S = 20; // a gap this long between reps starts a new set
const KEEP_S = 12; // seconds of angles held for the tempo
const SPEED = 0.1; // a movement starts and ends where its speed passes this share of its top speed
const MIN_SPEED = 20; // degrees a second: slower than this is not a movement
const SHARE = 1 - 2 * Math.asin(SPEED) / Math.PI; // a smooth movement spends this share of its time above SPEED
const LIMITS = Object.freeze({ // degrees: the dip below `down`, then the rise above `up`
  squat: Object.freeze({ down: 110, up: 160 }), lunge: Object.freeze({ down: 115, up: 160 }),
  push_up: Object.freeze({ down: 105, up: 150 }), curl: Object.freeze({ down: 70, up: 140 }),
  shoulder_press: Object.freeze({ down: 105, up: 155 }), jumping_jack: Object.freeze({ down: 60, up: 140 }),
});
const ORDER = Object.freeze(['squat', 'lunge', 'push_up', 'curl', 'shoulder_press', 'jumping_jack']);
const WORDS = Object.freeze([
  'reps', 'this set', 'Set', 'Tempo: down', 'up', 'Start when you are ready. Each full rep counts.',
  'Stop if anything hurts.', 'Squats', 'Lunges', 'Push-ups', 'Curls', 'Shoulder presses', 'Jumping jacks',
]);
const NAMES = Object.freeze({ squat: WORDS[7], lunge: WORDS[8], push_up: WORDS[9], curl: WORDS[10], shoulder_press: WORDS[11], jumping_jack: WORDS[12] });

const get = (o, k) => { const e = Object.entries(o || {}).find((x) => x[0] === k); return e ? e[1] : undefined; };
const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const sideScore = (p, s) => [s.sh, s.el, s.wr, s.hip, s.kn, s.an].reduce((n, i) => n + (seen(p.at(i)) ? 1 : 0), 0);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (seen(a) ? a : (seen(b) ? b : null)));
const round1 = (v) => Math.round(v * 10) / 10;

function tiltOf(p) { // the torso's angle from upright, degrees (0 standing, 90 level)
  const sh = mid(p[11], p[12]), hip = mid(p[23], p[24]);
  if (!sh || !hip) return NaN;
  const dx = sh.x - hip.x, dy = sh.y - hip.y, n = Math.hypot(dx, dy);
  return n ? Math.acos(Math.min(1, Math.max(-1, -dy / n))) * 180 / Math.PI : NaN;
}
function armUp(p, s) { return angle(p.at(s.hip), p.at(s.sh), p.at(s.el)); } // 0 arm down by the side, 180 straight overhead

function signals(p) { // one number per exercise this frame, or NaN where that exercise's body shape is not met
  const s = sideScore(p, L) >= sideScore(p, R) ? L : R;
  const tilt = tiltOf(p), knee = angle(p.at(s.hip), p.at(s.kn), p.at(s.an)), elbow = angle(p.at(s.sh), p.at(s.el), p.at(s.wr));
  const arm = armUp(p, s), leg = dist(p.at(s.hip), p.at(s.kn)) + dist(p.at(s.kn), p.at(s.an));
  const level = seen(p.at(s.an)) && seen(p.at(s.hip)) && Math.abs(p.at(s.an).y - p.at(s.hip).y) < 0.25 * leg; // legs out behind
  const stance = seen(p[27]) && seen(p[28]) && leg ? Math.abs(p[27].x - p[28].x) / leg : 0;
  const knees = Math.min(angle(p[23], p[25], p[27]), angle(p[24], p[26], p[28]));
  const arms = [armUp(p, L), armUp(p, R)].filter(Number.isFinite);
  const both = arms.length ? arms.reduce((n, v) => n + v, 0) / arms.length : NaN;
  const nan = NaN;
  return {
    squat: tilt < 60 && stance < 0.45 ? knee : nan,
    lunge: tilt < 45 && stance >= 0.45 ? knees : nan,
    push_up: tilt > 55 && level ? elbow : nan,
    curl: tilt < 35 && arm < 45 ? elbow : nan,
    shoulder_press: tilt < 35 && arm > 60 ? elbow : nan,
    jumping_jack: tilt < 25 && knee > 150 ? 180 - both : nan,
  };
}

function step(c, v, t, lim) { // one exercise's counter (geom reps' rule; times kept for the tempo)
  if (!Number.isFinite(v)) return c;
  if (c.phase === 'up' && v < lim.down) return Object.assign({}, c, { phase: 'down', downAt: t });
  if (c.phase === 'down' && v > lim.up) return Object.assign({}, c, { phase: 'up', count: c.count + 1, doneAt: t, prevDone: c.doneAt });
  return c;
}

function smooth(vs) { // a centred mean of five
  return vs.map((_, i) => { const w = vs.slice(Math.max(0, i - 2), i + 3); return w.reduce((n, v) => n + v, 0) / w.length; });
}
function moving(buf, from, to, sign) { // seconds the angle moved in one direction (sign -1 down, +1 up) between two times
  const pts = buf.filter((b) => b.t >= from && b.t <= to);
  if (pts.length < 5) return 0;
  const ts = pts.map((b) => b.t), s = smooth(pts.map((b) => b.v));
  const v = s.map((_, i) => (i === 0 || i === s.length - 1 ? 0 : sign * (s.at(i + 1) - s.at(i - 1)) / (ts.at(i + 1) - ts.at(i - 1))));
  let p = 0;
  v.forEach((x, i) => { if (x > v.at(p)) p = i; });
  if (v.at(p) < MIN_SPEED) return 0;
  const thr = SPEED * v.at(p);
  const cross = (i, j) => ts.at(i) + (thr - v.at(i)) / (v.at(j) - v.at(i) || 1) * (ts.at(j) - ts.at(i));
  let a = p, b = p;
  while (a > 0 && v.at(a - 1) > thr) a -= 1;
  while (b < v.length - 1 && v.at(b + 1) > thr) b += 1;
  const start = a > 0 ? cross(a - 1, a) : ts.at(a), end = b < v.length - 1 ? cross(b, b + 1) : ts.at(b);
  return Math.max(0, end - start) / SHARE;
}
function bottomAt(buf, from, to) { // the time of the lowest angle between two times
  let best = null;
  buf.forEach((b) => { if (b.t >= from && b.t <= to && (!best || b.v < best.v)) best = b; });
  return best ? best.t : from;
}

function begin(t, at) {
  const counters = Object.fromEntries(ORDER.map((e) => [e, { phase: 'up', count: 0, downAt: t, doneAt: t, prevDone: t }]));
  const bufs = Object.fromEntries(ORDER.map((e) => [e, []]));
  return { began: at, at, t, counters, bufs, downs: [], ups: [], pendingUp: null, sets: 0, setBase: 0, setStart: t, lastRep: -1, last: '' };
}

function tick(s, e, before, after, t) { // a rep of `e` just finished: its down time now, its up time once he tops out
  const buf = get(s.bufs, e), low = bottomAt(buf, before.doneAt, t);
  const down = moving(buf, before.doneAt, low, -1);
  const fresh = s.lastRep < 0 || t - s.lastRep > REST_S;
  return Object.assign({}, s, {
    downs: s.downs.concat([down]).slice(-500), pendingUp: { e, from: low }, lastRep: t, last: e,
    sets: s.sets + (fresh ? 1 : 0), setBase: fresh ? after.count - 1 : s.setBase, setStart: fresh ? before.downAt : s.setStart,
  });
}
function settle(s, e, t) { // the pending rep's rise ends when the next dip starts: its up time is known now
  const pu = s.pendingUp;
  if (!pu || pu.e !== e) return s;
  return Object.assign({}, s, { ups: s.ups.concat([moving(get(s.bufs, e), pu.from, t, 1)]).slice(-500), pendingUp: null });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  let s = state || begin(t, at);
  s = Object.assign({}, s, { t, at: Math.max(s.at, at) });
  const sig = signals(p);
  const bufs = Object.fromEntries(ORDER.map((e) => { const b = get(s.bufs, e), x = get(sig, e);
    return [e, Number.isFinite(x) ? b.concat([{ t, v: x }]).filter((q) => q.t >= t - KEEP_S) : b]; }));
  s = Object.assign({}, s, { bufs });
  for (const e of ORDER) {
    const before = get(s.counters, e), after = step(before, get(sig, e), t, get(LIMITS, e));
    const counters = Object.assign({}, s.counters, Object.fromEntries([[e, after]]));
    s = Object.assign({}, s, { counters });
    if (before.phase === 'up' && after.phase === 'down') s = settle(s, e, t);
    if (after.count > before.count) s = tick(s, e, before, after, t);
  }
  return s;
}

function chosen(s) { // the exercise with the most reps (the latest on a tie)
  return ORDER.reduce((best, e) => {
    const n = get(s.counters, e).count;
    if (!n) return best;
    const b = best ? get(s.counters, best).count : 0;
    if (!best || n > b || (n === b && e === s.last)) return e;
    return best;
  }, '');
}
const mean = (vs) => (vs.length ? vs.reduce((n, v) => n + v, 0) / vs.length : 0);

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[6] };
  const e = s ? chosen(s) : '';
  if (!e) return { view: [{ kind: 'big', n: 0, word: WORDS[0] }, { kind: 'line', text: WORDS[5] }, hurts], tally: null };
  const pu = s.pendingUp, ups = pu && pu.e === e ? s.ups.concat([moving(get(s.bufs, e), pu.from, s.t, 1)]) : s.ups;
  const total = get(s.counters, e).count, down = s.downs.slice(-1)[0] || 0, up = ups.slice(-1)[0] || 0;
  const view = [
    { kind: 'big', n: Math.max(0, total - s.setBase), word: WORDS[0] },
    { kind: 'line', text: `${WORDS[2]} ${s.sets}` },
    { kind: 'timer', s: Math.max(0, s.t - s.setStart), word: WORDS[1] },
    { kind: 'line', text: `${WORDS[3]} ${down.toFixed(1)} s, ${WORDS[4]} ${up.toFixed(1)} s` },
    { kind: 'line', text: get(NAMES, e) }, hurts,
  ];
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), exercise: e, sets: Math.max(1, s.sets), reps: total,
    down_s: round1(mean(s.downs)), up_s: round1(mean(ups)) };
  return { view, tally };
}

JarvisVision.use({ id: 'reps', tasks: ['pose'], onResult, summary });
