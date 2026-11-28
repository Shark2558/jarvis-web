// src/jarvis/api/static/console-coach-band.js -- R8.1 builder E, row 219 (HF-24, the resistance-band tracker and the
// anchor visibility prompt; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `band`: `pose` at up to 15 a second,
// one body's state at a time (D6). It counts band reps (rows, curls, presses: the working elbow bends past 110 degrees
// and straightens past 150; a part rep never counts) and says at once when the hand holding the band leaves the
// picture: unseen or at its edge for 0.3 s (a single lost frame is not a prompt), so the prompt comes inside 1 s.
// The anchor area he taps at setup is the Workout pane's to watch (console-coach-workout.js): a use case never sees
// the picture. The working arm is the one whose elbow has moved more; until one has, either hand leaving counts.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' BandTally (reps, prompts, the session's start and end).
import { angle, reps } from './console-coach-geom.js';

const SEEN = 0.5;
const EDGE = 0.01; // a hand this close to the picture's edge has left it
const OUT_S = 0.3; // unseen this long before the prompt
const LIMITS = Object.freeze({ down: 110, up: 150 });
const ARMS = Object.freeze([Object.freeze({ sh: 11, el: 13, wr: 15 }), Object.freeze({ sh: 12, el: 14, wr: 16 })]);
const WORDS = Object.freeze([
  'reps', 'I can\u2019t see the hand holding the band. Keep it in view.', 'Pull the band, then let it back slowly.',
  'Stop if anything hurts.', 'prompts',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const inside = (p) => seen(p) && p.x > EDGE && p.x < 1 - EDGE && p.y > EDGE && p.y < 1 - EDGE;
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const elbowOf = (p, a) => (seen(p.at(a.sh)) && seen(p.at(a.el)) && seen(p.at(a.wr)) ? angle(p.at(a.sh), p.at(a.el), p.at(a.wr)) : NaN);

function begin(t, at) {
  return { began: at, at, t, arms: [{ lo: 999, hi: -1, c: undefined }, { lo: 999, hi: -1, c: undefined }], outSince: -1, out: false, prompts: 0 };
}
const working = (s) => { const r = s.arms.map((a) => a.hi - a.lo); return Math.max(...r) < 30 ? -1 : (r[0] >= r[1] ? 0 : 1); };

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = state || begin(t, at);
  const arms = s.arms.map((a, k) => {
    const e = elbowOf(p, ARMS.at(k));
    if (!Number.isFinite(e)) return a;
    return { lo: Math.min(a.lo, e), hi: Math.max(a.hi, e), c: reps(a.c, e, { down: LIMITS.down, up: LIMITS.up, t }) };
  });
  const w = working(Object.assign({}, s, { arms }));
  const gone = w < 0 ? ARMS.every((a) => !inside(p.at(a.wr))) : !inside(p.at(ARMS.at(w).wr));
  const since = gone ? (s.outSince < 0 ? t : s.outSince) : -1;
  const out = gone && t - since >= OUT_S;
  return Object.assign({}, s, { t, at: Math.max(s.at, at), arms, outSince: since, out, prompts: s.prompts + (out && !s.out ? 1 : 0) });
}

function count(s) { const w = working(s); const a = w < 0 ? null : s.arms.at(w); return a && a.c ? a.c.count : 0; }

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[3] };
  if (!s) return { view: [{ kind: 'big', n: 0, word: WORDS[0] }, { kind: 'line', text: WORDS[2] }, hurts], tally: null };
  const n = count(s), view = [{ kind: 'big', n, word: WORDS[0] }];
  if (s.out) view.push({ kind: 'paused', why: WORDS[1] });
  view.push({ kind: 'line', text: WORDS[2] }, hurts);
  const tally = n || s.prompts ? { started_at: s.began, ended_at: Math.max(s.began, s.at), reps: n, prompts: s.prompts } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'band', tasks: ['pose'], onResult, summary });
