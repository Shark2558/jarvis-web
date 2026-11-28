// src/jarvis/api/static/console-coach-warmup.js -- R8.1 builder E, row 218 (HF-38, the dynamic warm-up checklist;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `warm-up`: `pose` at up to 15 a second, one body's state at a
// time (D6). Six moves, each ticked once it is done the set number of times, in any order:
//   reach   both arms straight overhead, feet together (seen from the front)           5
//   knees   one knee lifted to hip height while the other leg stays straight            10 (either side)
//   squat   both knees bent past 110 degrees and back up                                 5
//   bend    a side bend of more than 15 degrees, arms down, legs straight (front)        6 (either side)
//   hinge   the torso tipped forward past 45 degrees on straight legs (side view)        5
//   jack    arms overhead with the feet apart, then arms down (front)                   10
// Each move has its own counter on one number and a gate on the body's shape, so another move never counts for it
// (an arm wave is not a reach, a half squat is not a squat, a jack is not a reach). A use case, held to the guard
// (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared geometry.
// Tally: jarvis.coach.usecases' WarmUpTally (done, of, the session's start and end).
import { angle, dist, reps } from './console-coach-geom.js';

const SEEN = 0.5;
const ITEMS = Object.freeze([ // id, words, times, the dip below `down` and the rise above `up`
  Object.freeze({ id: 'reach', text: 'Reach overhead', times: 5, down: 40, up: 120 }),
  Object.freeze({ id: 'knees', text: 'Lift your knees', times: 10, down: 110, up: 160 }),
  Object.freeze({ id: 'squat', text: 'Squat', times: 5, down: 110, up: 160 }),
  Object.freeze({ id: 'bend', text: 'Bend to each side', times: 6, down: 15, up: 25 }),
  Object.freeze({ id: 'hinge', text: 'Hinge at the hips', times: 5, down: 45, up: 75 }),
  Object.freeze({ id: 'jack', text: 'Jumping jacks', times: 10, down: 40, up: 140 }),
]);
const WORDS = Object.freeze(['done', 'Warm-up done. Well done, Sir.', 'Stop if anything hurts.', 'of', 'Step back so I can see all of you.']);

const get = (o, k) => { const e = Object.entries(o || {}).find((x) => x[0] === k); return e ? e[1] : undefined; };
const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : null);
const a3 = (p, i, j, k) => (seen(p.at(i)) && seen(p.at(j)) && seen(p.at(k)) ? angle(p.at(i), p.at(j), p.at(k)) : NaN);

function shape(p) { // this frame's numbers, NaN where unseen
  const sh = mid(p[11], p[12]), hip = mid(p[23], p[24]);
  if (!sh || !hip) return null;
  const torso = dist(sh, hip), dy = sh.y - hip.y;
  const tilt = torso ? Math.acos(Math.min(1, Math.max(-1, -dy / torso))) * 180 / Math.PI : NaN;
  const front = Math.abs(p[11].x - p[12].x) / torso > 0.3;
  const arms = (a3(p, 23, 11, 13) + a3(p, 24, 12, 14)) / 2, elbows = Math.min(a3(p, 11, 13, 15), a3(p, 12, 14, 16));
  const hips = [a3(p, 11, 23, 25), a3(p, 12, 24, 26)], knees = [a3(p, 23, 25, 27), a3(p, 24, 26, 28)];
  const hipW = Math.abs(p[23].x - p[24].x), feet = seen(p[27]) && seen(p[28]) && hipW ? Math.abs(p[27].x - p[28].x) / hipW : 0;
  const ankle = mid(p[27], p[28]), low = ankle ? ankle.y - hip.y > 0.5 * torso : false;
  return { tilt, front, arms, elbows, hips, knees, feet, low };
}

function values(f) { // one number per move, NaN where the body is not in that move's shape
  const nan = NaN, straight = Math.min(...f.knees) > 150;
  const lifted = Math.max(...f.hips) > 160 ? Math.min(...f.hips) : nan;
  return {
    reach: f.front && f.feet < 1.5 && f.elbows > 150 && f.tilt < 15 ? 180 - f.arms : nan,
    knees: f.tilt < 25 && !f.front ? lifted : nan,
    squat: f.tilt < 60 && f.low ? Math.max(...f.knees) : nan,
    bend: f.front && f.arms < 60 && straight ? 30 - f.tilt : nan,
    hinge: !f.front && straight && f.low ? 90 - f.tilt : nan,
    jack: f.front && f.tilt < 15 && straight && !(f.arms > 100 && f.feet < 2.5) ? 180 - f.arms : nan,
  };
}

function begin(at) {
  return { began: at, at, t: 0, counters: {}, done: {}, seen: true };
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = state || begin(at), f = shape(p);
  if (!f) return Object.assign({}, s, { t, seen: false });
  const v = values(f);
  const counters = Object.fromEntries(ITEMS.map((it) => [it.id, reps(get(s.counters, it.id), get(v, it.id), { down: it.down, up: it.up, t })]));
  const done = Object.fromEntries(ITEMS.map((it) => [it.id, Math.min(it.times, get(counters, it.id).count)]));
  return Object.assign({}, s, { t, at: Math.max(s.at, at), counters, done, seen: true });
}

function summary(s) {
  const items = ITEMS.map((it) => { const n = (s && get(s.done, it.id)) || 0; return { text: `${it.text}: ${n} ${WORDS[3]} ${it.times}`, ok: n >= it.times ? true : null }; });
  const done = items.filter((x) => x.ok).length;
  const view = [{ kind: 'big', n: done, word: `${WORDS[3]} ${ITEMS.length} ${WORDS[0]}` }, { kind: 'checklist', items }];
  if (done === ITEMS.length) view.push({ kind: 'line', text: WORDS[1] });
  if (s && !s.seen) view.push({ kind: 'paused', why: WORDS[4] });
  view.push({ kind: 'line', text: WORDS[2] });
  const any = s && ITEMS.some((it) => get(s.done, it.id) > 0);
  return { view, tally: any ? { started_at: s.began, ended_at: Math.max(s.began, s.at), done, of: ITEMS.length } : null };
}

JarvisVision.use({ id: 'warm-up', tasks: ['pose'], onResult, summary });
