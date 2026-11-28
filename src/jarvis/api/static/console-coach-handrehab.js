// src/jarvis/api/static/console-coach-handrehab.js -- R8 builder D, row 268 (docs/plans/r8-vision.md v8.0.4 2.1): the
// hand and finger exercise game on the desk webcam. Use case `hand-rehab`: `hands` at up to 15 a second, one state;
// one hand (the first side seen, so a second hand in view changes nothing). Three exercises, each counted on its own:
//   open_close       the four fingers' mean bend passes CLOSED then OPEN again: one rep
//   finger_tap       one finger bends past TAP_ON while the others stay straight, and straightens: one tap (a bend that
//                    ends on the thumb is a thumb_to_finger instead, never both)
//   thumb_to_finger  the thumb's tip meets a fingertip (closer than TOUCH of the palm's length) with the other fingers
//                    open: one touch; it must part (past APART) before the next
// A finger's bend is the angle between its knuckle bone (wrist to knuckle) and the line from the knuckle to its tip,
// in 3D (the hand model's z is depth on the same scale): 0 straight, about 125 in a fist. The range of motion is the
// median, over the reps, of each rep's bend from straightest to most bent (open_close: the four fingers' mean; taps:
// the tapping finger; touches: the thumb's bend at its first knuckle). The exercise: a Result's `setup.exercise` if the
// pane passes one, else the one with the most reps. "Stop if anything hurts." is shown before and during.
// A use case, held to the guard (tests/r7_jsguard.py); its tally is HandRehabTally. View: big, line, bar, paused.
import { reps as repCounter } from './console-coach-geom.js';

const EXERCISES = Object.freeze(['open_close', 'finger_tap', 'thumb_to_finger']);
const FINGERS = Object.freeze([[5, 8], [9, 12], [13, 16], [17, 20]]); // index, middle, ring, little: knuckle, tip
const CLOSED = 80; // the fingers' mean bend for a closed hand
const OPEN = 30; // and an open one
const TAP_ON = 40;
const TAP_OFF = 20;
const OTHERS_STILL = 25; // the other fingers' bend, at most, during a tap
const TOUCH = 0.3; // thumb tip to fingertip, of the palm's length
const APART = 0.5;
const OTHERS_OPEN = 45; // the other fingers' mean bend, at most, during a touch (not a fist)
const SCORE_MIN = 0.5;
const WORDS = Object.freeze({
  hurts: 'Stop if anything hurts.',
  practice: 'Practice only, not medical advice.',
  noHand: 'Hold one hand up to the camera, palm towards it.',
  range: 'range of motion, degrees',
});
const HOW = new Map([
  ['open_close', 'Open your hand wide, then close it into a loose fist.'],
  ['finger_tap', 'Bend one finger at a time, then straighten it.'],
  ['thumb_to_finger', 'Touch your thumb to each fingertip in turn.'],
]);
const NAMES = new Map([['open_close', 'open and close'], ['finger_tap', 'finger taps'], ['thumb_to_finger', 'thumb to finger']]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y, z: (Number(a.z) || 0) - (Number(b.z) || 0) });
const len = (v) => Math.hypot(v.x, v.y, v.z);
const dist3 = (a, b) => len(sub(a, b));
function between(u, v) { // degrees between two 3D vectors (NaN when one is nothing)
  const nu = len(u), nv = len(v);
  if (!nu || !nv) return NaN;
  return Math.acos(Math.min(1, Math.max(-1, (u.x * v.x + u.y * v.y + u.z * v.z) / (nu * nv)))) * 180 / Math.PI;
}
const median = (vs) => { const s = vs.slice().sort((a, b) => a - b); return s.length ? (s.at((s.length - 1) >> 1) + s.at(s.length >> 1)) / 2 : 0; };
const mean = (vs) => (vs.length ? vs.reduce((n, v) => n + v, 0) / vs.length : 0);

function measure(ps) { // one hand's bends (four fingers and the thumb), palm length and thumb gaps
  const w = ps[0], palm = dist3(w, ps[9]);
  if (!(palm > 0.01)) return null;
  const bends = FINGERS.map(([k, tip]) => between(sub(ps.at(k), w), sub(ps.at(tip), ps.at(k))));
  if (!bends.every(Number.isFinite)) return null;
  const thumb = between(sub(ps[2], ps[1]), sub(ps[4], ps[2]));
  const gaps = FINGERS.map((f) => dist3(ps[4], ps.at(f.at(1))) / palm);
  return { bends, thumb: Number.isFinite(thumb) ? thumb : 0, gaps, mean: mean(bends) };
}

function begin(t, at, r) {
  const want = r.setup && EXERCISES.includes(r.setup.exercise) ? r.setup.exercise : '';
  return { began: at, at, t0: t, t, want, side: '', seen: false, m: null,
    oc: { rep: undefined, hi: -Infinity, lo: Infinity, ranges: [] },
    tap: { finger: -1, base: 0, peak: 0, touched: false, n: 0, ranges: [] },
    touch: { on: false, finger: -1, n: 0, hi: -Infinity, lo: Infinity, ranges: [] } };
}

function openClose(oc, m, t) {
  const rep = repCounter(oc.rep, 180 - m.mean, { down: 180 - CLOSED, up: 180 - OPEN, t });
  const hi = Math.max(oc.hi, m.mean), lo = Math.min(oc.lo, m.mean);
  if (rep.count > ((oc.rep && oc.rep.count) || 0)) return { rep, hi: m.mean, lo: m.mean, ranges: oc.ranges.concat([hi - lo]) };
  return { rep, hi, lo, ranges: oc.ranges };
}

function fingerTap(tap, m, touching) {
  const others = (f) => m.bends.filter((_, i) => i !== f);
  if (tap.finger < 0) {
    const f = m.bends.findIndex((b, i) => b > TAP_ON && Math.max(...others(i)) < OTHERS_STILL);
    if (f < 0) return tap;
    return Object.assign({}, tap, { finger: f, base: Math.min(...others(f)), peak: m.bends.at(f), touched: touching === f });
  }
  const b = m.bends.at(tap.finger);
  const step = Object.assign({}, tap, { peak: Math.max(tap.peak, b), touched: tap.touched || touching === tap.finger });
  if (b >= TAP_OFF) return step;
  const counts = !step.touched;
  return Object.assign({}, step, { finger: -1, n: step.n + (counts ? 1 : 0),
    ranges: counts ? step.ranges.concat([step.peak - step.base]) : step.ranges });
}

function thumbTouch(touch, m) {
  const hi = Math.max(touch.hi, m.thumb), lo = Math.min(touch.lo, m.thumb);
  if (touch.on) {
    if (m.gaps.at(touch.finger) <= APART) return Object.assign({}, touch, { hi, lo });
    return Object.assign({}, touch, { on: false, finger: -1, hi: m.thumb, lo: m.thumb, ranges: touch.ranges.concat([hi - lo]) });
  }
  const f = m.gaps.findIndex((g, i) => g < TOUCH && mean(m.bends.filter((_, k) => k !== i)) < OTHERS_OPEN);
  return f < 0 ? Object.assign({}, touch, { hi, lo }) : Object.assign({}, touch, { on: true, finger: f, n: touch.n + 1, hi, lo });
}

function pick(hands, side) {
  const ok = hands.filter((h) => h && h.score >= SCORE_MIN && Array.isArray(h.points) && h.points.length === 21);
  const same = side ? ok.filter((h) => h.side === side) : ok;
  return same.reduce((b, h) => (!b || h.score > b.score ? h : b), null);
}

function onResult(r, state) {
  if (!r || r.task !== 'hands') return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = state || begin(t, at, r);
  const s = Object.assign({}, s0, { t, at: Math.max(s0.at, at) });
  const h = pick(r.ok && r.data && Array.isArray(r.data.hands) ? r.data.hands : [], s.side);
  const m = h ? measure(h.points) : null;
  if (!m) return Object.assign({}, s, { m: null });
  const touch = thumbTouch(s.touch, m);
  const touching = touch.on ? touch.finger : -1;
  return Object.assign({}, s, { side: s.side || h.side, seen: true, m, touch,
    oc: openClose(s.oc, m, t), tap: fingerTap(s.tap, m, touching) });
}

function counts(s) {
  return new Map([['open_close', (s.oc.rep && s.oc.rep.count) || 0], ['finger_tap', s.tap.n], ['thumb_to_finger', s.touch.n]]);
}
function chosen(s) {
  if (s.want) return s.want;
  const c = counts(s);
  return EXERCISES.reduce((b, e) => (c.get(e) > c.get(b) ? e : b), EXERCISES[0]);
}
function rangeOf(s, ex) {
  const rs = ex === 'open_close' ? s.oc.ranges : (ex === 'finger_tap' ? s.tap.ranges : s.touch.ranges);
  return Math.round(Math.min(180, Math.max(0, median(rs))) * 10) / 10;
}

function summary(s) {
  const stop = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [stop, { kind: 'line', text: HOW.get('open_close') }, { kind: 'line', text: WORDS.practice }], tally: null };
  const ex = chosen(s), n = counts(s).get(ex), range = rangeOf(s, ex);
  const view = [stop];
  view.push(s.m ? { kind: 'big', n, word: NAMES.get(ex) } : { kind: 'paused', why: WORDS.noHand });
  view.push({ kind: 'line', text: HOW.get(ex) });
  view.push({ kind: 'bar', n: Math.round(Math.min(100, range / 1.25)), word: `${Math.round(range)} ${WORDS.range}` });
  view.push({ kind: 'line', text: WORDS.practice });
  return { view, tally: s.seen ? { started_at: s.began, ended_at: Math.max(s.began, s.at), exercise: ex, reps: Math.min(500, n),
    range_deg: range } : null };
}

JarvisVision.use({ id: 'hand-rehab', tasks: ['hands'], onResult, summary });
