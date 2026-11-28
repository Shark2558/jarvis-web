// src/jarvis/api/static/console-coach-reach.js -- R8 builder D, row 276 (docs/plans/r8-vision.md v8.0.4 2.1): the
// occupational-therapy reach-and-grasp practice on the desk webcam. Use case `reach-grasp`: `hands` and `objects`
// (cup) at up to 15 a second, one state. A trial: rest the hand away from the cup until it is still for HOLD_S ("go"),
// reach, close the hand on the cup and keep it closed for GRIP_S. The reach time runs from the moment the palm has
// moved ONSET_D from where it rested to the moment the thumb-to-index gap closes below CLOSE of its resting width, on
// the cup; both moments are interpolated between frames. A trial not done within TIMEOUT_S of "go" is a missed grasp.
// Each trial scores 100 at REACH_FAST_MS or quicker, falling evenly to 20 at REACH_SLOW_MS (slower stays 20), a miss 0;
// the session's score is their mean. Fixed rules and nothing random: the same sequence always gives the same score.
// Practice scores, never a clinical rating (it says so). A use case, held to the guard (tests/r7_jsguard.py); its
// tally is ReachTally. View widgets: targets {dots: [{x, y, r, lit}], hands: [{x, y}]}, big, line, bar, paused.
import { dist } from './console-coach-geom.js';

const ROUNDS = 10;
const HOLD_S = 0.8; // still this long, away from the cup: "go"
const STILL = 0.015; // the palm's drift that still counts as resting, frame units
const ONSET_D = 0.02; // the palm's move from rest that starts the reach
const CLOSE = 0.6; // the thumb-to-index gap, of its resting width, that is a grasp
const GRIP_S = 0.2; // a grasp held this long counts
const TIMEOUT_S = 8;
const LEFT_S = 0.5; // the hand off the cup this long ends a trial
const REACH_FAST_MS = 700;
const REACH_SLOW_MS = 3000;
const SCORE_MIN = 0.4;
const WORDS = Object.freeze({
  find: 'Put a cup within reach, where the camera sees it and your hand.',
  home: 'Rest your hand on the desk, away from the cup.',
  go: 'Reach for the cup and pick it up.',
  release: 'Put the cup down and bring your hand back.',
  over: 'Ten reaches done. Well done, Sir.',
  practice: 'Practice score, not a clinical rating.',
  hurts: 'Stop if anything hurts.',
  reaches: 'reaches',
  score: 'practice score',
});

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const mean = (vs) => (vs.length ? vs.reduce((n, v) => n + v, 0) / vs.length : 0);
const meets = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const grow = (b, m) => ({ x: b.x - m, y: b.y - m, w: b.w + 2 * m, h: b.h + 2 * m });
const across = (a, b, level) => a.t + (b.t - a.t) * (level - a.v) / (b.v - a.v); // when a value crossed `level`

function handOf(r) {
  const hs = r.ok && r.data && Array.isArray(r.data.hands) ? r.data.hands : [];
  const h = hs.filter((x) => x && x.score >= SCORE_MIN && Array.isArray(x.points) && x.points.length === 21)
    .reduce((b, x) => (!b || x.score > b.score ? x : b), null);
  if (!h) return null;
  const ps = h.points, base = [ps[0], ps[5], ps[9], ps[13], ps[17]];
  const palm = { x: mean(base.map((p) => p.x)), y: mean(base.map((p) => p.y)) };
  const size = dist(ps[0], ps[9]);
  const xs = ps.map((p) => p.x), ys = ps.map((p) => p.y), x = Math.min(...xs), y = Math.min(...ys);
  return size > 0.01 ? { palm, gap: dist(ps[4], ps[8]) / size, box: { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y } } : null;
}

function cupOf(r) {
  const os = r.ok && r.data && Array.isArray(r.data.objects) ? r.data.objects : [];
  const c = os.filter((o) => o.label === 'cup' && o.score >= SCORE_MIN).reduce((b, o) => (!b || o.score > b.score ? o : b), null);
  return c ? c.box : null;
}

function trialScore(ms) {
  if (ms === null) return 0;
  if (ms <= REACH_FAST_MS) return 100;
  return Math.round(Math.max(20, 100 - 80 * (ms - REACH_FAST_MS) / (REACH_SLOW_MS - REACH_FAST_MS)));
}

function rest(s, h, t) { // waiting for a still hand away from the cup, then "go"
  const away = !meets(h.box, grow(s.cup, 0.03));
  if (!s.still || dist(h.palm, s.still.p) > STILL || !away) {
    return Object.assign({}, s, { phase: 'home', still: away ? { p: h.palm, since: t, gap: h.gap } : null });
  }
  const still = { p: s.still.p, since: s.still.since, gap: s.still.gap * 0.8 + h.gap * 0.2 };
  if (t - still.since < HOLD_S) return Object.assign({}, s, { phase: 'home', still });
  return Object.assign({}, s, { phase: 'go', goAt: t, from: still.p, openGap: still.gap, near: { t, v: 0 }, onset: 0, prev: null });
}

function done(s, ms, t) {
  const trials = s.trials.concat([ms]);
  return Object.assign({}, s, { trials, phase: trials.length >= ROUNDS ? 'over' : (ms === null ? 'home' : 'release'),
    still: null, offSince: t, last: ms });
}

function step(s, h, t) {
  if (s.phase === 'home') return rest(s, h, t);
  if (s.phase === 'release') {
    const on = meets(h.box, grow(s.cup, 0.03));
    if (on) return Object.assign({}, s, { offSince: t });
    return t - s.offSince >= LEFT_S ? Object.assign({}, s, { phase: 'home', still: null }) : s;
  }
  if (t - s.goAt > TIMEOUT_S) return done(s, null, t);
  if (s.phase === 'go') {
    const d = dist(h.palm, s.from);
    if (d <= ONSET_D) return Object.assign({}, s, { near: { t, v: d } });
    return Object.assign({}, s, { phase: 'reach', onset: across(s.near, { t, v: d }, ONSET_D), prev: null, grip: null });
  }
  // 'reach': the grasp, on the cup, held GRIP_S
  const ratio = h.gap / s.openGap, on = meets(h.box, grow(s.cup, 0.03));
  const now = { t, v: ratio };
  if (s.grip) {
    if (!(ratio <= CLOSE && on)) return Object.assign({}, s, { grip: null, prev: now });
    return t - s.grip >= GRIP_S ? done(s, Math.max(0, Math.round((s.grip - s.onset) * 1000)), t) : s;
  }
  if (ratio <= CLOSE && on) {
    const at = s.prev && s.prev.v > CLOSE && t > s.prev.t ? across(s.prev, now, CLOSE) : t;
    return Object.assign({}, s, { grip: at, prev: now });
  }
  return Object.assign({}, s, { prev: now });
}

function onResult(r, state) {
  if (!r || (r.task !== 'hands' && r.task !== 'objects')) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = state || { began: at, at, phase: 'home', cup: null, cupAt: -Infinity, still: null, trials: [], last: null,
    cursor: [], goAt: 0 };
  const s = Object.assign({}, s0, { at: Math.max(s0.at, at) });
  if (s.phase === 'over') return s;
  if (r.task === 'objects') {
    const cup = cupOf(r);
    return cup ? Object.assign({}, s, { cup, cupAt: t }) : s;
  }
  const h = handOf(r);
  const cursor = h ? [{ x: Math.round(h.palm.x * 100) / 100, y: Math.round(h.palm.y * 100) / 100 }] : [];
  if (!h || !s.cup || t - s.cupAt > 2) return Object.assign({}, s, { cursor, missing: true });
  return Object.assign({}, step(s, h, t), { cursor, missing: false });
}

function summary(s) {
  const stop = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [{ kind: 'paused', why: WORDS.find }, { kind: 'line', text: WORDS.practice }, stop], tally: null };
  const made = s.trials.filter((ms) => ms !== null);
  const score = s.trials.length ? Math.round(mean(s.trials.map(trialScore))) : 0;
  const cup = s.cup;
  const dots = cup ? [{ x: Math.round((cup.x + cup.w / 2) * 100) / 100, y: Math.round((cup.y + cup.h / 2) * 100) / 100,
    r: Math.round((Math.max(cup.w, cup.h) / 2) * 100) / 100, lit: s.phase === 'go' || s.phase === 'reach' }] : [];
  const say = new Map([['home', WORDS.home], ['go', WORDS.go], ['reach', WORDS.go], ['release', WORDS.release], ['over', WORDS.over]]);
  const view = [
    { kind: 'targets', dots, hands: s.cursor },
    s.missing && s.phase !== 'over' ? { kind: 'paused', why: WORDS.find } : { kind: 'line', text: say.get(s.phase) },
    { kind: 'big', n: made.length, word: WORDS.reaches },
    { kind: 'line', text: s.last === null ? `${s.trials.length - made.length} missed` : `Last reach ${(s.last / 1000).toFixed(2)} s` },
    { kind: 'bar', n: score, word: WORDS.score },
    { kind: 'line', text: WORDS.practice },
    stop,
  ];
  const tally = s.trials.length ? { started_at: s.began, ended_at: Math.max(s.began, s.at), reaches: made.length,
    mean_ms: Math.min(60000, Math.round(mean(made))), score } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'reach-grasp', tasks: ['hands', 'objects'], onResult, summary });
