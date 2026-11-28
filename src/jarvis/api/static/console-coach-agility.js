// src/jarvis/api/static/console-coach-agility.js -- R8.1 builder G, row 230 (HF-13, the agility drill and cone-crossing
// timer; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `agility`: `pose` at up to 15 a second, one body's state
// at a time (D6). The marks are the ones he taps on the picture at setup (2 to 12, in the order he will run them; tap a
// mark again for a shuttle): they reach this use case only on its Results, r.setup = {marks: [{x, y}], radius} (S2's
// contract line from R8's join: live(..., {setup})); with no marks it times nothing and says so. Each mark is a gate: a circle of
// `radius` (0.05 of the frame unless set) round the spot. His foot point (the middle of his heels and toes) standing
// in the first gate for half a second makes him ready; the clock starts the moment it leaves that gate and each split
// ends the moment it enters the next mark's gate, both found between two frames (so the times don't depend on the frame
// rate). A run ends at the last mark; he walks back to the first to run again. A gate he skips is counted as missed and
// that run is not his best. 30 s without the next mark abandons a run.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' AgilityTally (marks, splits timed, best_s the fastest whole run, total_s all
// the split time, the session's start and end). View: targets {lit, dots, hands}, big {n, word}, line, paused.
import { dist } from './console-coach-geom.js';

const SEEN = 0.5;
const R_DEFAULT = 0.05;
const R_MIN = 0.02;
const R_MAX = 0.15;
const MARKS_MIN = 2;
const MARKS_MAX = 12;
const DOTS_MAX = 8; // the view draws at most eight
const READY_S = 0.5;
const RUN_MAX_S = 30;
const WORDS = Object.freeze([
  'Tap the marks on the screen first, in the order you will run them.', 'Stand on the first mark, then go.',
  'seconds', 'Stop if anything hurts.', 'Go when you are ready.', 'Missed a mark: this run is not your best.',
  'Run to the lit mark.',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const unit = (v) => Number.isFinite(v) && v >= 0 && v <= 1;
const two = (v) => v.toFixed(2);
function footOf(p) { // the middle of his heels and toes, else of his ankles
  const feet = [p[29], p[30], p[31], p[32]].filter(seen), use = feet.length >= 2 ? feet : [p[27], p[28]].filter(seen);
  return use.length ? { x: use.reduce((n, q) => n + q.x, 0) / use.length, y: use.reduce((n, q) => n + q.y, 0) / use.length } : null;
}
function setupOf(r) { // the marks and the gate's radius he set (r.setup), or null
  const su = r && r.setup && typeof r.setup === 'object' ? r.setup : null;
  const raw = su && Array.isArray(su.marks) ? su.marks.slice(0, MARKS_MAX) : [];
  const marks = raw.filter((m) => !!m && unit(m.x) && unit(m.y)).map((m) => ({ x: m.x, y: m.y }));
  const radius = su && Number.isFinite(su.radius) ? Math.min(R_MAX, Math.max(R_MIN, su.radius)) : R_DEFAULT;
  return marks.length >= MARKS_MIN && marks.length === raw.length ? { marks, radius } : null;
}
const cross = (a, b, r) => a.t + (b.t - a.t) * (a.d - r) / (a.d - b.d); // when the distance passed r between two frames

function begin(t, at, su) {
  return { began: at, at, t, marks: su ? su.marks : [], r: su ? su.radius : R_DEFAULT, ok: !!su, phase: 'wait', onSince: -1,
    prev: null, foot: null, next: 1, from: 0, legs: [], runMissed: 0, runs: 0, best: 0, total: 0, splits: 0, last: 0,
    lastRun: 0, missed: 0 };
}

function toward(s, f, t) { // running: the next mark's gate entered (or the one after it, the next one skipped)
  const want = s.marks.at(s.next), after = s.next + 1 < s.marks.length ? s.marks.at(s.next + 1) : null;
  const dw = dist(f, want), da = after ? dist(f, after) : Infinity;
  const apart = after && dist(after, want) >= 2 * s.r && dist(after, s.marks.at(s.next - 1)) >= 2 * s.r;
  const entered = dw <= s.r ? { d: dw, skip: 0 } : (apart && da <= s.r ? { d: da, skip: 1 } : null);
  if (!entered) return t - s.from > RUN_MAX_S ? Object.assign({}, s, { phase: 'wait', legs: [] }) : s;
  const mark = s.marks.at(s.next + entered.skip), pd = s.prev ? dist(s.prev.f, mark) : NaN;
  const tc = s.prev && pd > s.r ? cross({ t: s.prev.t, d: pd }, { t, d: entered.d }, s.r) : t;
  const split = Math.max(0, tc - s.from), legs = s.legs.concat([split]), next = s.next + 1 + entered.skip;
  const n = Object.assign({}, s, { from: tc, legs, next, splits: s.splits + 1, total: s.total + split, last: split,
    missed: s.missed + entered.skip, runMissed: s.runMissed + entered.skip });
  if (next < s.marks.length) return n;
  const time = legs.reduce((m, v) => m + v, 0), clean = !n.runMissed;
  return Object.assign({}, n, { phase: 'done', onSince: -1, runs: s.runs + 1, lastRun: time,
    best: clean && (!s.best || time < s.best) ? time : s.best });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const f = footOf(p);
  if (!f) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  let s = state && state.phase ? state : begin(t, at, setupOf(r));
  s = Object.assign({}, s, { t, at: Math.max(s.at, at), foot: { x: Math.round(f.x * 100) / 100, y: Math.round(f.y * 100) / 100 } });
  if (!s.ok) return s;
  const d0 = dist(f, s.marks[0]);
  if (s.phase === 'wait' || s.phase === 'done') {
    const on = d0 <= s.r, since = on ? (s.onSince < 0 ? t : s.onSince) : -1;
    const ready = on && t - since >= READY_S;
    s = Object.assign({}, s, { onSince: since, phase: ready ? 'ready' : s.phase });
  } else if (s.phase === 'ready' && d0 > s.r) {
    const pd = s.prev ? dist(s.prev.f, s.marks[0]) : NaN;
    const tc = s.prev && pd <= s.r ? cross({ t: s.prev.t, d: pd }, { t, d: d0 }, s.r) : t;
    s = Object.assign({}, s, { phase: 'run', from: tc, next: 1, legs: [], runMissed: 0 });
  } else if (s.phase === 'run') {
    s = toward(s, f, t);
  }
  return Object.assign({}, s, { prev: { t, f } });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[3] };
  if (!s || !s.ok) return { view: [{ kind: 'paused', why: WORDS[0] }, hurts], tally: null };
  const lit = s.phase === 'run' ? s.next : 0;
  const dots = s.marks.slice(0, DOTS_MAX).map((m) => ({ x: m.x, y: m.y }));
  const view = [{ kind: 'targets', lit: lit < DOTS_MAX ? lit : -1, dots, hands: s.foot ? [{ x: s.foot.x, y: s.foot.y }] : [] }];
  if (s.splits) view.push({ kind: 'big', n: Math.round(s.last * 100) / 100, word: WORDS[2] });
  if (s.runs) view.push({ kind: 'line', text: `Run ${s.runs}: ${two(s.lastRun)} s.${s.best ? ` Best ${two(s.best)} s.` : ''}` });
  const say = s.phase === 'ready' ? WORDS[4] : (s.phase !== 'run' ? WORDS[1] : (s.runMissed ? WORDS[5] : WORDS[6]));
  view.push({ kind: 'line', text: say });
  view.push(hurts);
  const tally = s.splits ? { started_at: s.began, ended_at: Math.max(s.began, s.at), marks: s.marks.length,
    splits: s.splits, best_s: Math.round(s.best * 100) / 100, total_s: Math.round(s.total * 100) / 100 } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'agility', tasks: ['pose'], onResult, summary });
