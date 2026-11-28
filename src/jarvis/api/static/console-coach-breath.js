// src/jarvis/api/static/console-coach-breath.js -- R8 builder D, row 238 (docs/plans/r8-vision.md v8.0.4 section 2.1):
// the visual breath-pacing companion on the desk webcam. Use case `breath`: `pose` (the shoulders) at up to 10 a
// second, one state per body. Two halves:
//   the pacer  a pure function of the seconds since the session began: the phase (in, hold, out) and the seconds left
//              in it, to 0.1 s, for the rhythm in use (RHYTHMS: the registry's fixed list)
//   the rate   breaths a minute from the shoulders' rise and fall: their height over the hips, against a slow-moving
//              torso length, smoothed, its slow drift taken off (a 20-second mean), and each upward crossing timed
//              between frames; the rate is 60 over the mean of the last four breaths. A practice estimate, never a
//              medical measure (it says so)
// The rhythm: a Result's `setup.rhythm` if the pane passes one (a contract line for I1), else "6-a-minute".
// A use case, held to the guard (tests/r7_jsguard.py); its tally is jarvis.coach.usecases' BreathTally.
// View widgets: pacer {phase, s, of, word}, big {n, word}, line {text}, paused {why}.
import { dist, ema } from './console-coach-geom.js';

const RHYTHMS = new Map([
  ['4-4', [['in', 4], ['out', 4]]],
  ['4-7-8', [['in', 4], ['hold', 7], ['out', 8]]],
  ['box', [['in', 4], ['hold', 4], ['out', 4], ['hold', 4]]],
  ['6-a-minute', [['in', 4], ['out', 6]]],
  ['5-5', [['in', 5], ['out', 5]]],
]);
const DEFAULT_RHYTHM = '6-a-minute';
const SAY = new Map([['in', 'Breathe in'], ['hold', 'Hold'], ['out', 'Breathe out']]);
const WORDS = Object.freeze({
  rate: 'breaths a minute',
  estimate: 'A practice estimate, not a medical measure.',
  wait: 'Keep breathing; the count starts after a few breaths.',
  unseen: 'Sit where the camera sees your shoulders and hips.',
  hurts: 'Stop if anything hurts.',
});
const WINDOW_S = 20; // the drift is the mean over this long
const SMOOTH = 0.2; // the fast smoothing's weight at 10 a second (keeps about 3 in 4 of a 20-a-minute breath's rise)
const SLOW = 0.01; // the torso length's
const VIS_MIN = 0.5;
const LAST = 4; // breaths the rate is the mean of
const H_MIN = 0.008; // the least rise (of the torso's length) that counts: below it is the camera's own jitter
const SETTLE_S = 3; // the first seconds only fill the window
const STALE_S = 15; // no breath counted for this long: no rate

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < VIS_MIN);
const avg = (vs) => (vs.length ? vs.reduce((n, v) => n + v, 0) / vs.length : 0);

/** The pacer at `elapsed` seconds into a rhythm: {phase, s (left, to 0.1 s), of (the phase's length), word}. */
function pacer(rhythm, elapsed) {
  const phases = RHYTHMS.get(rhythm) || RHYTHMS.get(DEFAULT_RHYTHM);
  const cycle = phases.reduce((n, p) => n + p.at(1), 0);
  const e = ((elapsed % cycle) + cycle) % cycle;
  const found = phases.reduce((acc, p) => (acc.hit ? acc : (e < acc.from + p.at(1)
    ? { hit: true, from: acc.from, phase: p.at(0), len: p.at(1) } : { hit: false, from: acc.from + p.at(1) })),
  { hit: false, from: 0 });
  const left = Math.max(0, Math.round((found.from + found.len - e) * 10) / 10);
  return { kind: 'pacer', phase: found.phase, s: left, of: found.len, word: SAY.get(found.phase) };
}

function rhythmOf(r) {
  const want = r.setup && typeof r.setup.rhythm === 'string' ? r.setup.rhythm : DEFAULT_RHYTHM;
  return RHYTHMS.has(want) ? want : DEFAULT_RHYTHM;
}

function sample(r) { // the shoulders' height over the hips, or null when they are not seen
  const ps = r.ok && r.data && Array.isArray(r.data.points) ? r.data.points : [];
  if (ps.length < 25) return null;
  const [ls, rs, lh, rh] = [ps[11], ps[12], ps[23], ps[24]];
  if (![ls, rs, lh, rh].every(seen)) return null;
  const sh = mid(ls, rs), hip = mid(lh, rh), torso = dist(sh, hip);
  return torso > 0.05 ? { rise: hip.y - sh.y, torso } : null;
}

function breathe(s, t, got) { // one frame of the rate: the smoothed, de-drifted height and its upward crossings
  const torso = ema(s.torso, got.torso, SLOW);
  const f = ema(s.f, got.rise / torso, SMOOTH);
  const win = s.win.filter((w) => w.t > t - WINDOW_S).concat([{ t, f }]);
  const m = avg(win.map((w) => w.f));
  const x = f - m;
  const h = Math.max(H_MIN, 0.35 * Math.sqrt(avg(win.map((w) => (w.f - m) * (w.f - m)))));
  const p = s.px, settled = t - s.t0 > SETTLE_S;
  let { armed, pending, crossings, breaths } = s;
  if (!settled) armed = false;
  else if (pending !== null && x > h) { // the rise is real: one breath, timed where it crossed the mean
    crossings = crossings.concat([pending]).slice(-(LAST + 2));
    breaths += 1; armed = false; pending = null;
  } else if (pending !== null && x < -h) pending = null; // it fell back: noise, not a breath
  else if (x < -h) armed = true;
  else if (armed && pending === null && p && p.x < 0 && x >= 0 && t > p.t) pending = p.t + (t - p.t) * (-p.x) / (x - p.x);
  return Object.assign({}, s, { torso, f, win, px: { t, x }, armed, pending, crossings, breaths });
}

function onResult(r, state) {
  if (!r || r.task !== 'pose') return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = state || { t0: t, began: at, at, t, rhythm: rhythmOf(r), torso: undefined, f: undefined, win: [],
    px: null, armed: false, pending: null, crossings: [], breaths: 0, unseen: false };
  const got = sample(r);
  const moved = Object.assign({}, s, { t, at: Math.max(s.at, at), unseen: !got });
  return got ? breathe(moved, t, got) : moved;
}

function rate(s) {
  const cs = s.crossings.slice(-(LAST + 1));
  if (cs.length < 3 || s.t - cs.at(-1) > STALE_S) return null;
  const gaps = cs.slice(1).map((c, i) => c - cs.at(i));
  return 60 / avg(gaps);
}

function summary(s) {
  const stop = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [pacer(DEFAULT_RHYTHM, 0), { kind: 'line', text: WORDS.estimate }, stop], tally: null };
  const per = rate(s);
  const view = [pacer(s.rhythm, s.t - s.t0)];
  view.push(s.unseen ? { kind: 'paused', why: WORDS.unseen }
    : (per === null ? { kind: 'line', text: WORDS.wait } : { kind: 'big', n: Math.round(per), word: WORDS.rate }));
  view.push({ kind: 'line', text: WORDS.estimate }, stop);
  const perMinute = per === null ? 0 : Math.round(Math.min(60, per) * 10) / 10;
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), rhythm: s.rhythm,
    minutes: Math.round(((s.t - s.t0) / 60) * 100) / 100, breaths: Math.min(500, s.breaths), per_minute: perMinute };
  return { view, tally };
}

JarvisVision.use({ id: 'breath', tasks: ['pose'], onResult, summary });
