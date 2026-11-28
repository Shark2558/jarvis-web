// src/jarvis/api/static/console-coach-sitstand.js -- R8.1 builder H, row 269 (HC-06, the sit-to-stand test assistant;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `sit-to-stand`: `pose` at up to 15 a second on the tripod phone,
// side on to a chair. One session gives both practice measures:
//   in_30s  the 30-second chair stand: full stands from Go to 30 seconds; a stand he is more than halfway up at 30
//           seconds counts (halfway between his own seated and standing levels)
//   five_s  the five-times sit to stand: seconds from Go until he is fully up for the fifth time (0: not reached within
//           FIVE_MAX_S)
// He sits still SEATED_S, then a COUNT_IN_S count-in ends in Go (the pane says it); rising before Go starts the count-in
// again. His posture is the lesser of the hip angle (shoulder-hip-knee) and the knee angle (hip-knee-ankle), on the
// side the camera sees better, smoothed: seated is under SEAT, fully up over STAND. A full stand's moment is when the
// rise reaches its plateau (within TOP_BAND of its highest), found between frames, so it does not hang on the frame
// rate; a rise that never gets over STAND (a partial stand) is not counted. Practice, not a clinical test.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' SitToStandTally (in_30s, five_s, the session's start and end).
import { angle, ema } from './console-coach-geom.js';

const SEAT = 115; // degrees: seated under this
const STAND = 160; // ... fully up over this
const SEATED_S = 1; // seated still this long, then the count-in
const COUNT_IN_S = 3;
const TEST_S = 30;
const FIVE = 5;
const FIVE_MAX_S = 60;
const TOP_BAND = 2.5; // degrees under the rise's highest: the moment he is fully up
const TOP_DROP = 3; // a fall this far from the highest ends the rise
const TOP_WAIT_S = 0.3; // ... or this long with no new highest
const K = 0.5; // smoothing
const SEEN = 0.5;
const STANDS_MAX = 100;
const GUESS_SEATED = 95;
const GUESS_UP = 172;
const WORDS = Object.freeze({
  place: 'Sit side on to the phone, feet flat, arms crossed on your chest.',
  how: 'At Go, stand up fully and sit down fully, as quickly as is safe, for 30 seconds.',
  ready: 'Get ready',
  still: 'Sit still: Go is coming.',
  stands: 'stands',
  left: 'left',
  in30: 'stands in 30 seconds',
  fiveSoFar: 'Five stands: so far',
  fiveTook: 'Five stands took',
  fiveNot: 'Five stands: not reached.',
  done: 'Done. Rest now.',
  test: 'Practice, not a clinical test.',
  hurts: 'Stop if anything hurts.',
  practice: 'Practice only, not medical advice.',
});
const line = (text) => ({ kind: 'line', text });
const SAFE = Object.freeze([line(WORDS.test), line(WORDS.hurts), line(WORDS.practice)]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const atOf = (r) => (Number.isInteger(r.at) ? r.at : 0);
const round2 = (v) => Math.round(v * 100) / 100;
const seenOf = (q) => (q && Number.isFinite(q.x) && Number.isFinite(q.y) ? (Number.isFinite(q.visibility) ? q.visibility : 1) : 0);
const median = (vs) => { const o = vs.slice().sort((a, b) => a - b); return o.length ? o.at(Math.floor(o.length / 2)) : NaN; };
const between = (a, b, at) => (b.at(0) > a.at(0) ? a.at(1) + (b.at(1) - a.at(1)) * (at - a.at(0)) / (b.at(0) - a.at(0)) : b.at(1));

function postureOf(r) { // the lesser of the hip and knee angles, on the side seen better; NaN when hidden
  const p = r.ok && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null;
  if (!p) return NaN;
  const sides = [[11, 23, 25, 27], [12, 24, 26, 28]].map((ids) => ({ ids, vis: Math.min(...ids.map((i) => seenOf(p.at(i)))) }));
  const best = sides.at(0).vis >= sides.at(1).vis ? sides.at(0) : sides.at(1);
  if (best.vis < SEEN) return NaN;
  const [sh, hip, knee, ankle] = best.ids.map((i) => p.at(i));
  return Math.min(angle(sh, hip, knee), angle(hip, knee, ankle));
}

function halfway(s) { // between his own seated and standing levels
  const low = median(s.lows), high = median(s.highs);
  return ((Number.isFinite(low) ? low : GUESS_SEATED) + (Number.isFinite(high) ? high : GUESS_UP)) / 2;
}

function plateau(buf) { // the moment the rise first came within TOP_BAND of its highest, between frames
  const high = Math.max(...buf.map((b) => b.at(1))), want = high - TOP_BAND;
  const i = buf.findIndex((b) => b.at(1) >= want);
  if (i <= 0) return { t: buf.at(Math.max(0, i)).at(0), high };
  const a = buf.at(i - 1), b = buf.at(i);
  return { t: a.at(0) + (b.at(0) - a.at(0)) * (want - a.at(1)) / (b.at(1) - a.at(1)), high };
}

function rep(s, t, v) { // sit -> rise (over STAND) -> up (its plateau found) -> sit (under SEAT)
  if (s.rep === 'sit') {
    const low = Math.min(s.low, v);
    if (v <= STAND) return Object.assign({}, s, { low });
    return Object.assign({}, s, { rep: 'rise', low, lows: s.lows.concat([low]).slice(-STANDS_MAX), buf: (s.prev ? [s.prev] : []).concat([[t, v]]) });
  }
  if (s.rep === 'rise') {
    const buf = s.buf.concat([[t, v]]), high = Math.max(...buf.map((b) => b.at(1)));
    const highAt = buf.find((b) => b.at(1) === high).at(0);
    if (v >= high - TOP_DROP && t - highAt < TOP_WAIT_S) return Object.assign({}, s, { buf });
    const got = plateau(buf), late = s.rise30 && got.t > s.go + TEST_S;
    return Object.assign({}, s, { rep: 'up', buf: [], tops: s.tops.concat([got.t]).slice(0, STANDS_MAX),
      highs: s.highs.concat([got.high]).slice(-STANDS_MAX), half: s.half || late, rise30: false });
  }
  return v < SEAT ? Object.assign({}, s, { rep: 'sit', low: v }) : s;
}

function testing(s, t, v, raw) {
  let n = s;
  if (!n.judged && t >= n.go + TEST_S) { // the 30-second mark: more than halfway up (unsmoothed, so on time) counts
    const v30 = n.raw ? between(n.raw, [t, raw], n.go + TEST_S) : raw;
    n = Object.assign({}, n, { judged: true, half: n.rep === 'sit' && v30 >= halfway(n), rise30: n.rep === 'rise' });
  }
  n = Object.assign(rep(n, t, v), { prev: [t, v], raw: [t, raw] });
  const over = n.judged && n.rep !== 'rise' && (n.tops.length >= FIVE || t >= n.go + FIVE_MAX_S);
  return over ? Object.assign({}, n, { phase: 'done' }) : n;
}

function begin(t, at) {
  return { began: at, at, t, v: undefined, phase: 'wait', since: null, go: null, rep: 'sit', low: 180, lows: [], highs: [],
    buf: [], prev: null, raw: null, tops: [], judged: false, half: false, rise30: false };
}

function onResult(r, state) {
  if (!r || r.task !== 'pose') return state;
  const raw = postureOf(r);
  if (!Number.isFinite(raw)) return state;
  const t = clock(r), at = atOf(r), s0 = state || begin(t, at);
  if (s0.phase === 'done') return s0;
  const v = ema(s0.v, raw, K);
  const s = Object.assign({}, s0, { t, at: Math.max(s0.at, at), v });
  if (s.phase === 'wait') {
    const since = v < SEAT ? (s.since === null ? t : s.since) : null;
    return since !== null && t - since >= SEATED_S ? Object.assign({}, s, { since, phase: 'count', go: t + COUNT_IN_S }) : Object.assign({}, s, { since });
  }
  if (s.phase === 'count') {
    if (v >= halfway(s)) return Object.assign({}, s, { phase: 'wait', since: null, go: null }); // up before Go
    if (t < s.go) return Object.assign({}, s, { prev: [t, v], raw: [t, raw], low: Math.min(s.low, v) });
    return testing(Object.assign({}, s, { phase: 'go' }), t, v, raw);
  }
  return testing(s, t, v, raw);
}

function in30(s) { return s.tops.filter((x) => x <= s.go + TEST_S).length + (s.half ? 1 : 0); }
function five(s) { return s.tops.length >= FIVE ? round2(s.tops.at(FIVE - 1) - s.go) : 0; }

function summary(s) {
  if (!s || s.phase === 'wait') return { view: [line(WORDS.place), line(WORDS.how), ...SAFE], tally: null };
  if (s.phase === 'count') {
    return { view: [{ kind: 'timer', s: Math.max(0, Math.ceil(s.go - s.t)), word: WORDS.ready }, line(WORDS.still), ...SAFE], tally: null };
  }
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), in_30s: in30(s), five_s: five(s) };
  const fiveLine = tally.five_s ? `${WORDS.fiveTook} ${tally.five_s} s.` : (s.phase === 'done' ? WORDS.fiveNot : `${WORDS.fiveSoFar} ${Math.min(FIVE, s.tops.length)}.`);
  if (s.phase === 'done') {
    return { view: [{ kind: 'big', n: tally.in_30s, word: WORDS.in30 }, line(fiveLine), line(WORDS.done), ...SAFE], tally };
  }
  const left = Math.max(0, Math.ceil(s.go + TEST_S - s.t));
  return { view: [{ kind: 'big', n: s.judged ? tally.in_30s : s.tops.length, word: WORDS.stands }, { kind: 'timer', s: left, word: WORDS.left },
    line(fiveLine), ...SAFE], tally };
}

JarvisVision.use({ id: 'sit-to-stand', tasks: ['pose'], onResult, summary });
