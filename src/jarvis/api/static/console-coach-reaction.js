// src/jarvis/api/static/console-coach-reaction.js -- R8 builder D, row 224 (docs/plans/r8-vision.md v8.0.4 section 2.1):
// the gesture-controlled reaction game on the desk webcam. Use case `reaction-game`: `hands` at up to 15 a second (one
// state: hands belong to no body). Five circles; one lights; touch it with either hand. Each round's time runs from the
// moment the circle lit to the moment a hand first entered it (the crossing is interpolated between two frames), so the
// time does not depend on the frame rate. A hand already inside a circle when it lights must leave it first.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; no page, network, storage or
// camera; it imports only the shared geometry. Its view uses the fixed widgets (below); its tally is
// jarvis.coach.usecases' ReactionTally (counts, milliseconds, a 0..100 score, the session's start and end).
// View widgets: targets {dots: [{x, y, r, lit}], hands: [{x, y}]} (frame units 0..1, x and y each of its own side),
// big {n, word}, line {text}. Time: a Result's `t` (seconds) when the engine gives one, else the page's clock less
// the frame's own look time (r.ms).
import { dist } from './console-coach-geom.js';

const ROUNDS = 20; // circles a game lights
const R = 0.08; // a circle's radius, frame units
const LEAD_S = 1.5; // before the first circle
const GAP_S = 0.8; // between a touch (or a miss) and the next circle
const TIMEOUT_S = 3; // a circle not touched by then is missed
const DOTS = Object.freeze([[0.14, 0.2], [0.5, 0.12], [0.86, 0.2], [0.12, 0.72], [0.88, 0.72]]
  .map(([x, y]) => Object.freeze({ x, y })));
const WORDS = Object.freeze({
  lead: 'Raise a hand to the lit circle.',
  hits: 'hits',
  hurts: 'Stop if anything hurts.',
  done: 'Game over. Well played, Sir.',
  noHand: 'Show your hands to the camera.',
});

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const mean = (vs) => (vs.length ? vs.reduce((n, v) => n + v, 0) / vs.length : 0);
const palm = (ps) => {
  const base = [ps[0], ps[5], ps[9], ps[13], ps[17]];
  return { x: mean(base.map((p) => p.x)), y: mean(base.map((p) => p.y)) };
};
// the points of a hand that may touch: the palm's centre and the five fingertips
const touchers = (h) => (Array.isArray(h.points) && h.points.length === 21
  ? [palm(h.points), h.points[4], h.points[8], h.points[12], h.points[16], h.points[20]] : []);
const handsOf = (r) => (r.ok && r.data && Array.isArray(r.data.hands) ? r.data.hands : []);
const nearest = (hands, dot) => hands.reduce((best, h) => touchers(h).reduce((b, p) => Math.min(b, dist(p, dot)), best), Infinity);
const next = (seed) => (seed * 1103515245 + 12345) % 2147483648;

function begin(t, at) {
  return { t0: t, began: at, at, t, n: 0, hits: 0, misses: 0, rts: [], lit: -1, litAt: 0, armed: false,
    nextAt: t + LEAD_S, prev: null, seed: 7, last: -1, cursor: [], over: false, seen: false };
}

function light(s, t, hands) { // the next circle: never the last one, nor one a hand is already in
  const seed = next(s.seed);
  const free = (i) => i !== s.last && !(nearest(hands, DOTS.at(i)) <= R);
  const order = DOTS.map((_, k) => (seed + k) % DOTS.length);
  const idx = order.find(free) !== undefined ? order.find(free) : order.find((i) => i !== s.last);
  return Object.assign({}, s, { seed, lit: idx, last: idx, litAt: t, armed: false, prev: null, n: s.n + 1 });
}

function round(s, hands, t) { // a lit circle: touched, missed, or still waiting
  const d = nearest(hands, DOTS.at(s.lit));
  if (t - s.litAt >= TIMEOUT_S) return Object.assign({}, s, { misses: s.misses + 1, lit: -1, nextAt: t + GAP_S, prev: null });
  if (!s.armed && d <= R) return Object.assign({}, s, { prev: null }); // inside since it lit: leave it first
  if (d <= R) {
    const p = s.prev;
    const tc = p && Number.isFinite(p.d) && p.d > R && t > p.t ? p.t + (t - p.t) * (p.d - R) / (p.d - d) : t;
    const rt = Math.max(0, Math.round((tc - s.litAt) * 1000));
    return Object.assign({}, s, { hits: s.hits + 1, rts: s.rts.concat([rt]), lit: -1, nextAt: t + GAP_S, prev: null });
  }
  return Object.assign({}, s, { armed: true, prev: Number.isFinite(d) ? { d, t } : null });
}

function onResult(r, state) {
  if (!r || r.task !== 'hands') return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const hands = handsOf(r);
  let s = state || begin(t, at);
  if (s.over) return s;
  const cursor = hands.map((h) => palm(h.points || [])).filter((p) => Number.isFinite(p.x))
    .map((p) => ({ x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100 }));
  s = Object.assign({}, s, { t, at: Math.max(s.at, at), cursor, seen: s.seen || hands.length > 0 });
  if (s.lit >= 0) return round(s, hands, t);
  if (t < s.nextAt) return s;
  if (s.n >= ROUNDS) return Object.assign({}, s, { over: true });
  return round(light(s, t, hands), hands, t);
}

function score(s) {
  if (!s.n) return 0;
  const speed = Math.min(1, Math.max(0, (2 - mean(s.rts) / 1000) / 1.5)); // 0.5 s or quicker: full; 2 s: none
  return Math.round(100 * (s.hits / s.n) * (0.5 + 0.5 * speed));
}

function tallyOf(s) {
  if (!s || !s.n) return null;
  return { started_at: s.began, ended_at: Math.max(s.began, s.at), targets: s.n, hits: s.hits,
    best_ms: s.rts.length ? Math.min(...s.rts) : 0, mean_ms: Math.round(mean(s.rts)), score: score(s) };
}

function summary(s) {
  const stop = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [{ kind: 'line', text: WORDS.lead }, stop], tally: null };
  const dots = DOTS.map((d, i) => ({ x: d.x, y: d.y, r: R, lit: i === s.lit }));
  const avg = s.rts.length ? `Average ${(mean(s.rts) / 1000).toFixed(2)} s` : WORDS.lead;
  const view = [
    { kind: 'targets', dots, hands: s.cursor },
    { kind: 'big', n: s.hits, word: WORDS.hits },
    { kind: 'line', text: s.over ? WORDS.done : (s.seen ? avg : WORDS.noHand) },
    { kind: 'line', text: `${Math.max(0, ROUNDS - s.n)} to go, ${s.misses} missed` },
    stop,
  ];
  return { view, tally: tallyOf(s) };
}

JarvisVision.use({ id: 'reaction-game', tasks: ['hands'], onResult, summary });
