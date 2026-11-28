// src/jarvis/api/static/console-coach-yoga.js -- R8.1 builder F, row 221 (HF-04, the smart yoga and mobility coach;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `yoga`: `pose` at up to 10 a second on the tripod phone, one
// body's state at a time (D6). No setup: the pose is found from the body, by fixed rules for each pose in the list
// (POSES, the registry's own list), side on or facing the phone. A hold is a pose seen while the body is still: it
// begins at the first still frame of that pose and ends at its last, once the body has been out of it (or moving) for
// a second; a hold under 2 s is not one. Tally: jarvis.coach.usecases' YogaTally -- the longest hold's pose and seconds,
// and how many holds the session had. A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally}
// out; it imports only the shared geometry.
// Directions are degrees in the picture: 0 straight down, 90 towards the right, 180 up.
import { angle, dist } from './console-coach-geom.js';

const POSES = Object.freeze(['mountain', 'tree', 'warrior_i', 'warrior_ii', 'triangle', 'chair', 'cobra', 'child',
  'downward_dog', 'bridge', 'cat_cow', 'seated_forward_bend']);
const NAMES = new Map([['mountain', 'Mountain'], ['tree', 'Tree'], ['warrior_i', 'Warrior I'], ['warrior_ii', 'Warrior II'],
  ['triangle', 'Triangle'], ['chair', 'Chair'], ['cobra', 'Cobra'], ['child', 'Child'], ['downward_dog', 'Downward dog'],
  ['bridge', 'Bridge'], ['cat_cow', 'Cat-cow'], ['seated_forward_bend', 'Seated forward bend']]);
const WORDS = Object.freeze({
  find: 'Move into a pose from your list, side on or facing the phone.',
  breathe: 'Hold it and breathe evenly.',
  settle: 'Hold still to start the timer.',
  holds: 'holds', best: 'Best:', hurts: 'Stop if anything hurts.',
});
const SEEN = 0.5;
const STILL_DPS = 15; // degrees a second the body may move and still be holding
const BASE_S = 0.4; // the speed is measured over this long (smoothed directions)
const FASTEST = 3; // the speed is the mean of the three fastest segments (one moving limb is not averaged away)
const SMOOTH_S = 0.2; // the directions' smoothing time
const GRACE_S = 1; // out of the pose (or moving) this long ends a hold
const MIN_HOLD_S = 2;
const LOG_MAX = 50;

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const round1 = (v) => Math.round(v * 10) / 10;
const dir = (a, b) => (((Math.atan2(b.x - a.x, b.y - a.y) * 180) / Math.PI) + 360) % 360;
const off = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
const horiz = (d) => Math.min(off(d, 90), off(d, 270));
const between = (v, lo, hi) => v >= lo && v <= hi;

function limb(a, b, c) { // a two-segment limb: its two directions and the bend at its middle joint
  if (!seen(a) || !seen(b) || !seen(c)) return null;
  return { one: dir(a, b), two: dir(b, c), bend: angle(a, b, c), end: c, joint: b };
}
function pair(l, r) { const a = l || r, b = r || l; return a && b ? [a, b] : null; } // an unseen side copies the seen one

function features(p) {
  if (![11, 12, 23, 24].every((i) => seen(p.at(i)))) return null;
  const S = mid(p[11], p[12]), H = mid(p[23], p[24]), len = dist(S, H);
  const legs = pair(limb(p[23], p[25], p[27]), limb(p[24], p[26], p[28]));
  const arms = pair(limb(p[11], p[13], p[15]), limb(p[12], p[14], p[16]));
  if (!(len > 0.02) || !legs || !arms) return null;
  const T = dir(H, S), hip = [angle(S, H, legs[0].joint), angle(S, H, legs[1].joint)];
  return { S, H, len, T, tilt: off(T, 180), flat: horiz(T), legs, arms, hip, nose: seen(p[0]) ? p[0] : S,
    apart: Math.abs(legs[0].end.x - legs[1].end.x) / len, low: Math.max(legs[0].end.y, legs[1].end.y) };
}

const straight = (l) => l.bend > 155;
const upright = (l) => l.bend > 160 && off(l.one, 0) < 15 && off(l.two, 0) < 15;
const either = (f, test) => test(f.legs[0], f.legs[1]) || test(f.legs[1], f.legs[0]);
const both = (xs, test) => test(xs[0]) && test(xs[1]);
const flatLeg = (l) => horiz(l.one) < 25 && horiz(l.two) < 25 && l.bend > 150;

// each pose's rule on one frame's features (the order breaks no tie: the rules exclude each other)
const RULES = new Map(Object.entries({
  mountain: (f) => f.tilt < 15 && both(f.legs, upright) && f.apart < 0.6 && both(f.arms, (a) => off(a.one, 0) < 35 && a.bend > 140),
  tree: (f) => f.tilt < 20 && either(f, (st, fr) => upright(st) && fr.bend < 100 && off(fr.one, 0) > 25 && fr.end.y < st.end.y - 0.6 * f.len),
  warrior_ii: (f) => f.tilt < 20 && f.apart > 1.2 && either(f, (bent, st) => between(bent.bend, 80, 150) && st.bend > 155)
    && both(f.arms, (a) => horiz(a.one) < 25 && horiz(a.two) < 30) && off(f.arms[0].one, f.arms[1].one) > 140,
  warrior_i: (f) => f.tilt < 25 && f.apart > 1.0 && either(f, (bent, st) => between(bent.bend, 80, 150) && st.bend > 150)
    && both(f.arms, (a) => off(a.one, 180) < 35),
  triangle: (f) => f.apart > 1.2 && both(f.legs, straight) && between(f.tilt, 35, 110)
    && (off(f.arms[0].one, 180) < 35 ? off(f.arms[1].one, 0) < 35 : off(f.arms[0].one, 0) < 35 && off(f.arms[1].one, 180) < 35),
  chair: (f) => between(f.tilt, 12, 60) && both(f.legs, (l) => between(l.bend, 70, 150) && off(l.two, 0) < 35) && f.apart < 0.7
    && both(f.arms, (a) => off(a.one, 180) < 55),
  cobra: (f) => both(f.legs, flatLeg) && f.S.y < f.H.y && between(f.flat, 20, 70) && Math.abs(f.H.y - f.low) < 0.3 * f.len
    && both(f.hip, (h) => h > 100),
  child: (f) => both(f.legs, (l) => l.bend < 60 && horiz(l.two) < 30) && both(f.hip, (h) => h < 60) && f.nose.y > f.H.y,
  downward_dog: (f) => f.H.y < f.S.y && f.H.y < f.low - 0.5 * f.len && both(f.legs, (l) => l.bend > 150)
    && both(f.arms, (a) => a.bend > 145 && a.end.y > f.S.y) && both(f.hip, (h) => between(h, 45, 120)) && off(f.T, 0) < 75,
  bridge: (f) => f.H.y < f.S.y - 0.25 * f.len && both(f.legs, (l) => between(l.bend, 60, 120) && off(l.two, 0) < 35 && l.joint.y < f.H.y + 0.1 * f.len),
  cat_cow: (f) => f.flat < 25 && both(f.legs, (l) => off(l.one, 0) < 25 && between(l.bend, 60, 120) && horiz(l.two) < 30)
    && both(f.arms, (a) => off(a.one, 0) < 25),
  seated_forward_bend: (f) => both(f.legs, (l) => horiz(l.one) < 20 && horiz(l.two) < 20 && l.bend > 150) && both(f.hip, (h) => h < 70)
    && f.S.y < f.H.y,
}));

function poseOf(f) { return f ? POSES.find((name) => RULES.get(name)(f)) || '' : ''; }

function shape(p) { // nine segment directions, for the stillness check
  const ids = [[23, 11], [11, 13], [13, 15], [12, 14], [14, 16], [23, 25], [25, 27], [24, 26], [26, 28]];
  return ids.map(([a, b]) => (seen(p.at(a)) && seen(p.at(b)) ? dir(p.at(a), p.at(b)) : NaN));
}
function smoothDirs(prev, now, k) {
  if (!prev) return now;
  return now.map((d, i) => { const q = prev.at(i); if (!Number.isFinite(d)) return q; if (!Number.isFinite(q)) return d; const step = ((d - q + 540) % 360) - 180; return (q + k * step + 360) % 360; });
}
function speedOf(hist, t) { // degrees a second over the last BASE_S, from the smoothed directions
  const then = hist.find((h) => h.t >= t - BASE_S - 1e-6), last = hist.at(-1);
  if (!then || !last || last.t - then.t < BASE_S / 2) return Infinity;
  const ds = last.d.map((d, i) => off(d, then.d.at(i))).filter(Number.isFinite).sort((a, b) => b - a).slice(0, FASTEST);
  return ds.length ? ds.reduce((n, x) => n + x, 0) / ds.length / (last.t - then.t) : Infinity;
}

function begin(t, at) { return { began: at, at, t, hist: [], dirs: null, cur: '', since: -1, last: -1, holds: 0, best: null, log: [] }; }

function close(s) { // the current hold ends at its last still frame
  if (!s.cur) return s;
  const len = s.last - s.since;
  if (len < MIN_HOLD_S) return Object.assign({}, s, { cur: '', since: -1, last: -1 });
  const hold = { pose: s.cur, from: round1(s.since), s: round1(len) };
  const best = !s.best || len > s.best.s ? { pose: s.cur, s: len } : s.best;
  return Object.assign({}, s, { cur: '', since: -1, last: -1, holds: s.holds + 1, best, log: s.log.concat([hold]).slice(-LOG_MAX) });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = Object.assign({}, state || begin(t, at), { at: Math.max((state && state.at) || at, at) });
  const dt = Math.max(0, t - s0.t), k = 1 - Math.exp(-dt / SMOOTH_S);
  const dirs = smoothDirs(s0.dirs, shape(p), s0.dirs ? k : 1);
  const hist = s0.hist.filter((h) => h.t >= t - BASE_S - 0.2).concat([{ t, d: dirs }]);
  const s = Object.assign({}, s0, { t, dirs, hist });
  const name = poseOf(features(p)), holding = !!name && speedOf(hist, t) < STILL_DPS;
  const kept = s.cur && t - s.last >= GRACE_S ? close(s) : s; // out of it too long: it ended at its last frame
  if (kept.cur && holding && name === kept.cur) return Object.assign({}, kept, { last: t });
  if (kept.cur && !(holding && name !== kept.cur)) return kept; // inside the grace
  const ended = close(kept);
  if (!holding) return ended;
  return Object.assign({}, ended, { cur: name, since: t, last: t });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [{ kind: 'line', text: WORDS.find }, hurts], tally: null };
  const live = s.cur && s.last - s.since >= MIN_HOLD_S ? { pose: s.cur, s: s.last - s.since } : null;
  const best = live && (!s.best || live.s > s.best.s) ? live : s.best;
  const holds = s.holds + (live ? 1 : 0);
  const view = [];
  if (s.cur) view.push({ kind: 'timer', s: Math.round(s.last - s.since), word: NAMES.get(s.cur) || '' }, { kind: 'line', text: WORDS.breathe });
  else view.push({ kind: 'line', text: WORDS.find }, { kind: 'line', text: WORDS.settle });
  view.push({ kind: 'big', n: holds, word: WORDS.holds });
  if (best) view.push({ kind: 'line', text: `${WORDS.best} ${NAMES.get(best.pose) || ''}, ${Math.round(best.s)} s` });
  view.push(hurts);
  const tally = best ? { started_at: s.began, ended_at: Math.max(s.began, s.at), pose: best.pose, holds: Math.min(500, holds), hold_s: round1(best.s) } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'yoga', tasks: ['pose'], onResult, summary });
