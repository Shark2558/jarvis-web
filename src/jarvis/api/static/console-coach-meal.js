// src/jarvis/api/static/console-coach-meal.js -- R8.1 builder H, row 247 (DN-03, the eating pace and meal length tracker;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `meal`: `pose` and `hands` at up to 10 a second, the phone
// propped on the table facing him. A bite is a hand brought to his lips: a hand point (the pose's wrist and finger
// points, or the hand task's 21 points) within NEAR shoulder widths of his mouth for DWELL_S, after being further than
// FAR (so a hand resting near the chin, a reach across the table or a hand passing his face is not one). The meal runs
// from his first bite to his last; the pace is bites a minute.
// Only he is counted: the phone matches no face, so the engine calls a body "me" only while it is alone in view.
// While anyone else is in view (his body's Results come as "" instead of "me", or none come while the hands still
// do) the count pauses and says so; he angles the phone at himself. A bite while paused is never counted.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' MealTally (bites, minutes, per_minute, the session's start and end).
import { dist } from './console-coach-geom.js';

const NEAR = 0.4; // shoulder widths from his lips: a hand at his mouth
const FAR = 0.75; // ... and gone again
const DWELL_S = 0.2; // at his mouth this long is a bite
const STALE_S = 0.6; // with no Result of his body for this long, the count pauses
const MIN_WIDTH = 0.04; // frame units: shoulders closer than this are not seen side by side
const PACE_BITES = 5; // the recent pace: over his last few bites
const FAST_PER_MIN = 6; // a quick recent pace: one gentle tip
const SEEN = 0.5;
const HAND_POINTS = Object.freeze([15, 16, 17, 18, 19, 20, 21, 22]);
const WORDS = Object.freeze({
  place: 'Prop the phone on the table in front of you, facing you.',
  alone: 'Only you in view: anyone else pauses the count.',
  eat: 'Eat as you normally would.',
  bites: 'bites',
  meal: 'meal',
  pace: 'bites a minute',
  paused: 'Someone else is in view: angle the phone at yourself.',
  slow: 'Try a short pause between bites.',
  hurts: 'Stop if anything hurts.',
  practice: 'Practice only, not medical advice.',
});
const line = (text) => ({ kind: 'line', text });
const SAFE = Object.freeze([line(WORDS.hurts), line(WORDS.practice)]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const atOf = (r) => (Number.isInteger(r.at) ? r.at : 0);
const round1 = (v) => Math.round(v * 10) / 10;
const seen = (q) => !!q && Number.isFinite(q.x) && Number.isFinite(q.y) && !(q.visibility < SEEN);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : null);
const nearest = (pts, mouth) => pts.filter(seen).reduce((best, q) => Math.min(best, dist(q, mouth)), Infinity);

function widthOf(p, was) { // his shoulders' width, else most of his torso's length, else what it was
  const a = p.at(11), b = p.at(12);
  if (seen(a) && seen(b) && dist(a, b) >= MIN_WIDTH) return dist(a, b);
  const s = mid(a, b), h = mid(p.at(23), p.at(24));
  return s && h ? 0.8 * dist(s, h) : was;
}

function begin(t, at) {
  return { began: at, at, t, mouth: null, width: 0, poseT: null, alone: false, near: false, nearAt: 0, counted: false,
    bites: 0, first: null, last: null, recent: [] };
}

const paused = (s, t) => !s.alone || s.poseT === null || t - s.poseT > STALE_S;

function gesture(s, d, t) { // far -> near (the hand at his lips) -> a bite after DWELL_S -> far again
  if (!Number.isFinite(d)) return s;
  if (!s.near) return d < NEAR ? Object.assign({}, s, { near: true, nearAt: t, counted: false }) : s;
  if (d > FAR) return Object.assign({}, s, { near: false });
  if (s.counted || d >= NEAR || t - s.nearAt < DWELL_S) return s;
  if (paused(s, t)) return Object.assign({}, s, { counted: true }); // perhaps not his hand: never counted
  const at = s.nearAt;
  return Object.assign({}, s, { counted: true, bites: s.bites + 1, first: s.first === null ? at : s.first, last: at,
    recent: s.recent.concat([at]).slice(-PACE_BITES) });
}

function fromPose(s, r, t) {
  const p = r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null;
  if (!p) return s;
  const mouth = mid(p.at(9), p.at(10)) || (seen(p.at(0)) ? { x: p.at(0).x, y: p.at(0).y } : null);
  const width = widthOf(p, s.width);
  const next = Object.assign({}, s, { mouth: mouth || s.mouth, width, poseT: t, alone: r.who === 'me' });
  if (!mouth || !(width > 0)) return next;
  return gesture(next, nearest(HAND_POINTS.map((i) => p.at(i)), mouth) / width, t);
}

function fromHands(s, r, t) {
  const hands = r.data && Array.isArray(r.data.hands) ? r.data.hands : [];
  if (!s.mouth || !(s.width > 0) || s.poseT === null || t - s.poseT > STALE_S) return s;
  const pts = hands.flatMap((h) => (h && Array.isArray(h.points) ? h.points : []));
  return pts.length ? gesture(s, nearest(pts, s.mouth) / s.width, t) : s;
}

function onResult(r, state) {
  if (!r || !r.ok || (r.task !== 'pose' && r.task !== 'hands')) return state;
  const t = clock(r), at = atOf(r), s0 = state || begin(t, at);
  const s = Object.assign({}, s0, { t: Math.max(s0.t, t), at: Math.max(s0.at, at) });
  return r.task === 'pose' ? fromPose(s, r, t) : fromHands(s, r, t);
}

function minutesOf(s) { return s.first === null ? 0 : round1((s.last - s.first) / 60); }
function perMinute(bites, minutes) { return minutes >= 1 ? Math.min(60, round1(bites / minutes)) : 0; }

function tallyOf(s) {
  if (!s.bites) return null;
  const minutes = minutesOf(s);
  return { started_at: s.began, ended_at: Math.max(s.began, s.at), bites: s.bites, minutes, per_minute: perMinute(s.bites, minutes) };
}

function summary(s) {
  if (!s) return { view: [line(WORDS.place), line(WORDS.alone), ...SAFE], tally: null };
  const minutes = minutesOf(s), per = perMinute(s.bites, minutes);
  const view = [{ kind: 'big', n: s.bites, word: WORDS.bites }, { kind: 'timer', s: s.first === null ? 0 : Math.round(s.last - s.first), word: WORDS.meal }];
  if (paused(s, s.t)) view.push({ kind: 'paused', why: WORDS.paused });
  view.push(line(per ? `${per} ${WORDS.pace}` : WORDS.eat));
  const recent = s.recent, span = recent.length >= PACE_BITES ? recent.at(-1) - recent.at(0) : 0;
  if (span > 0 && (recent.length - 1) / (span / 60) > FAST_PER_MIN) view.push({ kind: 'tip', text: WORDS.slow });
  return { view: view.concat(SAFE), tally: tallyOf(s) };
}

JarvisVision.use({ id: 'meal', tasks: ['pose', 'hands'], onResult, summary });
