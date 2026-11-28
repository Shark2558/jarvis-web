// src/jarvis/api/static/console-coach-pilates.js -- R8.1 builder F, row 231 (HF-34, Pilates movement-sequence adherence;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `pilates`: `pose` at up to 10 a second on the tripod phone, side
// on to the mat, one body's state at a time (D6). The sequence is the classical mat order of eight steps (ORDER); each
// step is found from the body by its own fixed rule. A step is held while its shape is seen and the body is steady (the
// hundred's arm pulses are steady enough; moving between steps is not), from its first such frame to its last, once the
// body has been out of it for a second; held for a second it counts as done. A step done when a later step of the
// order was already done is out of order: it is said by name, marked in the checklist and counted. Tally:
// jarvis.coach.usecases' PilatesTally -- the steps done (in any order) and how many were out of order. A use case, held
// to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared geometry.
// Directions are degrees in the picture: 0 straight down, 90 towards the right, 180 up.
import { angle, dist } from './console-coach-geom.js';

const ORDER = Object.freeze(['hundred', 'roll_up', 'leg_circle', 'single_leg_stretch', 'spine_stretch', 'teaser', 'swan',
  'shoulder_bridge']);
const NAMES = new Map([['hundred', 'The hundred'], ['roll_up', 'Roll up'], ['leg_circle', 'Leg circles'],
  ['single_leg_stretch', 'Single leg stretch'], ['spine_stretch', 'Spine stretch'], ['teaser', 'Teaser'], ['swan', 'Swan'],
  ['shoulder_bridge', 'Shoulder bridge']]);
const WORDS = Object.freeze({
  lie: 'Lie on your mat, side on to the phone, and begin with the hundred.',
  next: 'Next:', complete: 'Sequence complete.', of: `of ${ORDER.length} steps`,
  early: 'is out of order: it comes before', hurts: 'Stop if anything hurts.',
});
const SEEN = 0.5;
const STEADY_DPS = 25; // degrees a second the body may move and still be holding a step
const BASE_S = 0.4;
const FASTEST = 3; // the speed is the mean of the three fastest segments (one moving limb is not averaged away)
const SMOOTH_S = 0.2;
const GRACE_S = 1;
const MIN_STEP_S = 1;
const TIP_S = 8; // an out-of-order step is said this long
const LOG_MAX = 40;

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const round1 = (v) => Math.round(v * 10) / 10;
const dir = (a, b) => (((Math.atan2(b.x - a.x, b.y - a.y) * 180) / Math.PI) + 360) % 360;
const off = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
const horiz = (d) => Math.min(off(d, 90), off(d, 270));
const between = (v, lo, hi) => v >= lo && v <= hi;

function limb(a, b, c) {
  if (!seen(a) || !seen(b) || !seen(c)) return null;
  return { one: dir(a, b), two: dir(b, c), bend: angle(a, b, c), end: c, joint: b };
}
function pair(l, r) { const a = l || r, b = r || l; return a && b ? [a, b] : null; }

function features(p) {
  if (![11, 12, 23, 24].every((i) => seen(p.at(i)))) return null;
  const S = mid(p[11], p[12]), H = mid(p[23], p[24]), len = dist(S, H);
  const legs = pair(limb(p[23], p[25], p[27]), limb(p[24], p[26], p[28]));
  const arms = pair(limb(p[11], p[13], p[15]), limb(p[12], p[14], p[16]));
  if (!(len > 0.02) || !legs || !arms) return null;
  const T = dir(H, S);
  return { S, H, len, T, flat: horiz(T), legs, arms, hip: [angle(S, H, legs[0].joint), angle(S, H, legs[1].joint)],
    low: Math.max(legs[0].end.y, legs[1].end.y) };
}

const both = (xs, test) => test(xs[0]) && test(xs[1]);
const either = (f, test) => test(f.legs[0], f.legs[1]) || test(f.legs[1], f.legs[0]);
const straight = (l) => l.bend > 150;
const flatLeg = (l) => horiz(l.one) < 20 && horiz(l.two) < 20 && l.bend > 150;
const raised = (f, lo, hi) => (l) => straight(l) && between(horiz(l.one), lo, hi) && l.joint.y < f.H.y;
const lifted = (f, lo, hi) => f.S.y < f.H.y && between(f.flat, lo, hi);

const RULES = new Map(Object.entries({
  hundred: (f) => lifted(f, 10, 35) && both(f.legs, raised(f, 25, 70)) && both(f.arms, (a) => horiz(a.one) < 35),
  roll_up: (f) => both(f.legs, flatLeg) && both(f.hip, (h) => h < 40) && f.S.y < f.H.y,
  leg_circle: (f) => f.flat < 15 && either(f, (up, down) => off(up.one, 180) < 25 && straight(up) && horiz(down.one) < 20 && straight(down)),
  single_leg_stretch: (f) => lifted(f, 10, 45) && either(f, (bent, out) => bent.bend < 80 && bent.joint.y < f.H.y && raised(f, 15, 65)(out)),
  spine_stretch: (f) => both(f.legs, flatLeg) && both(f.hip, (h) => between(h, 42, 80)) && f.S.y < f.H.y && both(f.arms, (a) => horiz(a.one) < 30),
  teaser: (f) => lifted(f, 40, 80) && both(f.legs, raised(f, 25, 70)) && both(f.hip, (h) => between(h, 55, 115)),
  swan: (f) => both(f.legs, flatLeg) && lifted(f, 20, 70) && both(f.hip, (h) => h > 100) && Math.abs(f.H.y - f.low) < 0.3 * f.len,
  shoulder_bridge: (f) => f.H.y < f.S.y - 0.25 * f.len && both(f.legs, (l) => between(l.bend, 60, 120) && off(l.two, 0) < 35 && l.joint.y < f.H.y + 0.1 * f.len),
}));

function stepOf(f) { return f ? ORDER.find((name) => RULES.get(name)(f)) || '' : ''; }

function shape(p) {
  const ids = [[23, 11], [11, 13], [13, 15], [12, 14], [14, 16], [23, 25], [25, 27], [24, 26], [26, 28]];
  return ids.map(([a, b]) => (seen(p.at(a)) && seen(p.at(b)) ? dir(p.at(a), p.at(b)) : NaN));
}
function smoothDirs(prev, now, k) {
  if (!prev) return now;
  return now.map((d, i) => { const q = prev.at(i); if (!Number.isFinite(d)) return q; if (!Number.isFinite(q)) return d; const step = ((d - q + 540) % 360) - 180; return (q + k * step + 360) % 360; });
}
function speedOf(hist, t) {
  const then = hist.find((h) => h.t >= t - BASE_S - 1e-6), last = hist.at(-1);
  if (!then || !last || last.t - then.t < BASE_S / 2) return Infinity;
  const ds = last.d.map((d, i) => off(d, then.d.at(i))).filter(Number.isFinite).sort((a, b) => b - a).slice(0, FASTEST);
  return ds.length ? ds.reduce((n, x) => n + x, 0) / ds.length / (last.t - then.t) : Infinity;
}

function begin(t, at) {
  return { began: at, at, t, hist: [], dirs: null, cur: '', since: -1, last: -1, entered: false, prev: '', far: -1,
    marks: new Map(), wrong: 0, tip: null, log: [] };
}

function enter(s, step) { // a step reached its first second: done, in order or not
  if (step === s.prev) return Object.assign({}, s, { entered: true });
  const k = ORDER.indexOf(step), late = k < s.far;
  const marks = new Map(s.marks).set(step, late ? 'early' : 'ok');
  const tip = late ? { text: `${NAMES.get(step)} ${WORDS.early} ${(NAMES.get(ORDER.at(s.far)) || '').toLowerCase()}.`, at: s.t } : s.tip;
  return Object.assign({}, s, { entered: true, prev: step, far: Math.max(s.far, k), marks, wrong: s.wrong + (late ? 1 : 0), tip });
}

function close(s) {
  if (!s.cur) return s;
  const len = s.last - s.since, logged = s.entered ? s.log.concat([{ step: s.cur, s: round1(len) }]).slice(-LOG_MAX) : s.log;
  return Object.assign({}, s, { cur: '', since: -1, last: -1, entered: false, log: logged });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = Object.assign({}, state || begin(t, at), { at: Math.max((state && state.at) || at, at) });
  const k = 1 - Math.exp(-Math.max(0, t - s0.t) / SMOOTH_S), dirs = smoothDirs(s0.dirs, shape(p), s0.dirs ? k : 1);
  const hist = s0.hist.filter((h) => h.t >= t - BASE_S - 0.2).concat([{ t, d: dirs }]);
  const s = Object.assign({}, s0, { t, dirs, hist });
  const step = stepOf(features(p)), holding = !!step && speedOf(hist, t) < STEADY_DPS;
  let kept = s.cur && t - s.last >= GRACE_S ? close(s) : s;
  if (kept.cur && holding && step === kept.cur) kept = Object.assign({}, kept, { last: t });
  else if (!(kept.cur && !(holding && step !== kept.cur))) kept = holding ? Object.assign({}, close(kept), { cur: step, since: t, last: t }) : close(kept);
  return kept.cur && !kept.entered && kept.last - kept.since >= MIN_STEP_S ? enter(kept, kept.cur) : kept;
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS.hurts };
  const items = ORDER.map((step) => { const m = s ? s.marks.get(step) : ''; return { text: NAMES.get(step), ok: m === 'ok' ? true : (m === 'early' ? false : null) }; });
  if (!s) return { view: [{ kind: 'line', text: WORDS.lie }, { kind: 'checklist', items }, hurts], tally: null };
  const done = items.filter((i) => i.ok !== null).length, next = ORDER.at(s.far + 1);
  const view = [];
  if (s.cur) view.push({ kind: 'timer', s: Math.round(s.last - s.since), word: NAMES.get(s.cur) || '' });
  if (s.tip && s.t - s.tip.at <= TIP_S) view.push({ kind: 'tip', text: s.tip.text });
  view.push({ kind: 'big', n: done, word: WORDS.of }, { kind: 'checklist', items },
    { kind: 'line', text: next ? `${WORDS.next} ${NAMES.get(next)}` : WORDS.complete }, hurts);
  const tally = done ? { started_at: s.began, ended_at: Math.max(s.began, s.at), done, out_of_order: Math.min(500, s.wrong) } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'pilates', tasks: ['pose'], onResult, summary });
