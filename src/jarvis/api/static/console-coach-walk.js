// src/jarvis/api/static/console-coach-walk.js -- R8.1 builder H, row 263 (HC-101, the remote six-minute walk test's lap
// and turn counter; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `walk-test`: `pose` at up to 10 a second on
// the tripod phone. He walks up and down a course whose length he types (the Workout pane's setup {course_m: 1..100},
// a contract line for I1: live(..., {setup}) puts a use case's setup on its Results); without it nothing is counted.
// The phone sees the course side on (his hips move across the frame) or from one end (he grows and shrinks): both are
// watched, as his hips' x (frame widths) and as the log of his torso's length, each smoothed; whichever turns first
// over a real length is the way the phone looks. A turn is a reversal of H_X (or H_Z) after a length of at least SPAN_X
// (SPAN_Z), and never after less than half a usual length (a step back mid-course is not a turn). The six minutes start
// with his first step; at six minutes the count stops: laps are the lengths he finished (the length he is on counts if
// he had reached its end), turns the turnarounds he made, distance = laps x the course length.
// Practice, not a clinical test: fixed words only, never a judgement of the distance.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' WalkTestTally (course_m, laps, turns, metres, the session's start and end).
import { dist, ema } from './console-coach-geom.js';

const TEST_S = 360;
const H_X = 0.05; // a turn: back this far across the frame (side on)
const H_Z = 0.12; // ... or this much change of size, as a log (end on)
const SPAN_X = 0.2; // a length is at least this (side on)
const SPAN_Z = 0.4; // ... or this (end on: about one and a half times his size)
const SHORT = 0.5; // a reversal after less than half a usual length is not a turn
const LAST = 0.85; // at six minutes, the length he is on counts if it reached this much of a usual one
const START = 0.25; // of H: still at his start until he moved this far
const K = 0.3; // smoothing
const BUF_S = 3; // the moments before his first step, to find when it was
const SEEN = 0.5;
const COURSE_MIN = 1;
const COURSE_MAX = 100;
const METRES_MAX = 10000;
const WORDS = Object.freeze({
  course: 'Type the course length in metres to start.',
  place: 'Stand at one end of the course. Set the phone side on, or at one end facing along it.',
  first: 'The six minutes start with your first step. Walk as far as you can; slow down or rest if you need to.',
  laps: 'laps',
  left: 'to go',
  turns: 'Turns',
  distance: 'distance',
  five: 'Five minutes to go. Keep going.',
  four: 'Four minutes to go. Keep it up.',
  three: 'Halfway: three minutes to go.',
  two: 'Two minutes to go. Keep going.',
  one: 'One minute to go.',
  soon: 'In a moment, stop where you are.',
  going: 'Walk at your own pace.',
  over: 'Time is up: stop where you are.',
  test: 'Practice, not a clinical test.',
  hurts: 'Stop if anything hurts.',
  practice: 'Practice only, not medical advice.',
});
const line = (text) => ({ kind: 'line', text });
const SAFE = Object.freeze([line(WORDS.test), line(WORDS.hurts), line(WORDS.practice)]);
const NO_COURSE = Object.freeze({ kind: 'course' });

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const atOf = (r) => (Number.isInteger(r.at) ? r.at : 0);
const round1 = (v) => Math.round(v * 10) / 10;
const seen = (q) => !!q && Number.isFinite(q.x) && Number.isFinite(q.y) && !(q.visibility < SEEN);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : null);
const median = (vs) => { const o = vs.slice().sort((a, b) => a - b); return o.length ? o.at(Math.floor(o.length / 2)) : 0; };

function courseOf(r) {
  const c = r.setup ? r.setup.course_m : undefined;
  return typeof c === 'number' && Number.isFinite(c) && c >= COURSE_MIN && c <= COURSE_MAX ? c : 0;
}

function signals(r) { // his hips across the frame, and the log of his size: NaN when not seen
  const p = r.ok && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null;
  if (!p) return null;
  const h = mid(p.at(23), p.at(24)), s = mid(p.at(11), p.at(12));
  const torso = h && s ? dist(h, s) : NaN;
  return { x: h ? h.x : (s ? s.x : NaN), z: torso > 0 ? -Math.log(torso) : NaN };
}

function detector(v) { return { dir: 0, from: v, ext: v, spans: [], turns: 0 }; }
function step(d, v, h, least) { // one signal's lengths and turns
  if (!Number.isFinite(v)) return d;
  if (!Number.isFinite(d.from)) return detector(v);
  if (!d.dir) return Math.abs(v - d.from) >= h ? Object.assign({}, d, { dir: Math.sign(v - d.from), ext: v }) : d;
  if ((v - d.ext) * d.dir > 0) return Object.assign({}, d, { ext: v });
  if ((d.ext - v) * d.dir < h) return d;
  const span = Math.abs(d.ext - d.from);
  if (span < least || (d.spans.length && span < SHORT * median(d.spans))) return d; // a step back, not a turn
  return { dir: -d.dir, from: d.ext, ext: v, spans: d.spans.concat([span]).slice(-60), turns: d.turns + 1 };
}

function begin(r, course) {
  return { kind: 'walk', course, began: atOf(r), at: atOf(r), t: clock(r), x: undefined, z: undefined, origin: null, buf: [],
    t0: null, dx: detector(NaN), dz: detector(NaN), mode: '', over: false, laps: 0, turns: 0 };
}

function counted(s) { // the detector that settled how the phone looks (or the one further on)
  if (s.mode === 'x') return s.dx;
  if (s.mode === 'z') return s.dz;
  return Math.abs(s.dx.ext - s.dx.from) / SPAN_X >= Math.abs(s.dz.ext - s.dz.from) / SPAN_Z ? s.dx : s.dz;
}

function finish(s) { // six minutes: the length he is on counts if he had reached its end
  const d = counted(s), usual = median(d.spans);
  const reached = d.dir !== 0 && usual > 0 && Math.abs(d.ext - d.from) >= LAST * usual;
  return Object.assign({}, s, { over: true, turns: d.turns, laps: d.turns + (reached ? 1 : 0) });
}

function waiting(s, t) { // before his first step: when did he set off?
  const o = s.origin || { x: s.x, z: s.z };
  const buf = s.buf.concat([[t, s.x, s.z]]).filter((b) => t - b.at(0) <= BUF_S);
  const away = (b, k) => Math.abs(b.at(1) - o.x) >= k * H_X || Math.abs(b.at(2) - o.z) >= k * H_Z;
  if (!away(buf.at(-1), 1)) return Object.assign({}, s, { origin: o, buf });
  const still = buf.filter((b) => !away(b, START));
  return Object.assign({}, s, { origin: o, buf: [], t0: still.length ? still.at(-1).at(0) : buf.at(0).at(0) });
}

function onResult(r, state) {
  if (!r || r.task !== 'pose') return state;
  if (!state || state.kind !== 'walk') {
    const course = courseOf(r);
    if (!course) return NO_COURSE;
    return walking(begin(r, course), r);
  }
  return walking(state, r);
}

function walking(state, r) {
  const g = signals(r);
  if (state.over || !g) return state;
  const t = clock(r);
  const s = Object.assign({}, state, { t, at: Math.max(state.at, atOf(r)), x: ema(state.x, g.x, K), z: ema(state.z, g.z, K) });
  if (s.t0 === null) {
    const w = waiting(s, t);
    if (w.t0 === null) return Object.assign(w, { dx: detector(w.origin.x), dz: detector(w.origin.z) });
    return track(w);
  }
  if (t - s.t0 >= TEST_S) return finish(s);
  return track(s);
}

function track(s) {
  const dx = step(s.dx, s.x, H_X, SPAN_X), dz = step(s.dz, s.z, H_Z, SPAN_Z);
  let mode = s.mode;
  if (!mode && dx.turns > 0) mode = 'x';
  else if (!mode && dz.turns > 0) mode = 'z';
  const next = Object.assign({}, s, { dx, dz, mode });
  const d = counted(next);
  return Object.assign(next, { turns: d.turns, laps: d.turns });
}

function cheer(left) {
  if (left > 300) return WORDS.going;
  if (left > 240) return WORDS.five;
  if (left > 180) return WORDS.four;
  if (left > 120) return WORDS.three;
  if (left > 60) return WORDS.two;
  if (left > 15) return WORDS.one;
  return WORDS.soon;
}

function tallyOf(s) {
  if (s.t0 === null) return null;
  return { started_at: s.began, ended_at: Math.max(s.began, s.at), course_m: s.course, laps: s.laps, turns: s.turns,
    metres: Math.min(METRES_MAX, round1(s.laps * s.course)) };
}

function summary(s) {
  if (!s || s.kind !== 'walk') return { view: [line(WORDS.course), line(WORDS.place), ...SAFE], tally: null };
  if (s.t0 === null) return { view: [line(WORDS.place), line(WORDS.first), ...SAFE], tally: null };
  const left = s.over ? 0 : Math.max(0, Math.ceil(TEST_S - (s.t - s.t0)));
  const metres = Math.min(METRES_MAX, round1(s.laps * s.course));
  const view = [{ kind: 'timer', s: left, word: WORDS.left }, { kind: 'big', n: s.laps, word: WORDS.laps },
    line(`${WORDS.turns}: ${s.turns}; ${WORDS.distance} ${metres} m.`), line(s.over ? WORDS.over : cheer(left)), ...SAFE];
  return { view, tally: tallyOf(s) };
}

JarvisVision.use({ id: 'walk-test', tasks: ['pose'], onResult, summary });
