// src/jarvis/api/static/console-coach-taichi.js -- R8.1 builder F, row 232 (HF-35, the tai-chi form sequence and flow
// reviewer; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `tai-chi`: `pose` at up to 10 a second on the tripod
// phone, one body's state at a time (D6). Against HIS recorded reference (coach_routines `tai-chi-1`..`9`):
//   record  (no reference, or `setup.record`): the body's nine segment directions (the torso, each upper arm, forearm,
//           thigh and shin; degrees in the picture, smoothed over 0.2 s) on a grid of 10 rows a second, at most 3,000
//           rows (5 minutes). Angles only: never a point. The tally carries the recording for the pane to keep,
//           {record: {rid, kind, chunks}} (rows in chunks of 100, the engine's plain-data limit), and no result.
//   follow  (`setup.angles` rows or `setup.chunks`): the form's steps are its pauses -- each stretch of the reference
//           where it moves under 6 degrees a second for 0.3 s or more, after the opening stance; a step is done when
//           his posture comes within 15 degrees of it (the mean over the segments), in order; reaching the step
//           after it (within 11) first marks it missed. Smoothness: a sudden flick (a segment more than 11 degrees off
//           the mean of its own path over 0.3 s either side, or two more than 7) costs 12 points a minute's worth.
// The setup rides on each Result as `setup` (the pane's choices: a contract line for I1). Tally (follow):
// jarvis.coach.usecases' TaiChiTally -- steps done and the smoothness score. A use case, held to the guard
// (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared geometry.
import { dist } from './console-coach-geom.js';

const WORDS = Object.freeze({
  record: 'Recording your form: move through it once, then press Stop.', limit: 'Your form is at its five-minute limit.',
  recorded: 'recorded', steps: 'steps of', smooth: 'Smoothness', next: 'Next: step', complete: 'Form complete.',
  flick: 'Keep it slow and even.', place: 'Stand where the phone sees all of you.', hurts: 'Stop if anything hurts.',
});
const SEEN = 0.5;
const COLS = 9;
const ROW_S = 0.1; // the recording's grid
const ROWS_MAX = 3000;
const ROWS_MIN = 20;
const CHUNK = 100;
const SMOOTH_S = 0.2;
const STILL_DPS = 6; // a pause in the reference: slower than this ...
const PAUSE_ROWS = 3; // ... for this many rows
const MERGE_DEG = 8; // two pauses this alike are one step
const MATCH_DEG = 15;
const SKIP_DEG = 11;
const HALF_S = 0.3; // a flick is judged against the path 0.3 s either side
const FLICK_ONE = 11;
const FLICK_TWO = 7;
const REFRACTORY_S = 0.6;
const FLICK_PTS = 12; // points a flick costs, per minute of practice (a minute at least)
const ROUTINES = 9;

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const dir = (a, b) => (((Math.atan2(b.x - a.x, b.y - a.y) * 180) / Math.PI) + 360) % 360;
const off = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
const signed = (a, b) => ((b - a + 540) % 360) - 180;
const wrap = (d) => ((d % 360) + 360) % 360;
const round1 = (v) => Math.round(v * 10) / 10;
const mean = (xs) => (xs.length ? xs.reduce((n, x) => n + x, 0) / xs.length : NaN);
const apart = (a, b) => mean(a.map((x, i) => off(x, b.at(i))).filter(Number.isFinite)); // posture distance, degrees

function shape(p) { // the nine segment directions (NaN where a point is not seen)
  const H = seen(p[23]) && seen(p[24]) ? mid(p[23], p[24]) : null, S = seen(p[11]) && seen(p[12]) ? mid(p[11], p[12]) : null;
  const seg = (a, b) => (seen(p.at(a)) && seen(p.at(b)) ? dir(p.at(a), p.at(b)) : NaN);
  const torso = H && S && dist(H, S) > 0.02 ? dir(H, S) : NaN;
  return [torso, seg(11, 13), seg(13, 15), seg(12, 14), seg(14, 16), seg(23, 25), seg(25, 27), seg(24, 26), seg(26, 28)];
}
function smoothed(prev, now, k) {
  if (!prev) return now;
  return now.map((d, i) => { const q = prev.at(i); if (!Number.isFinite(d)) return q; if (!Number.isFinite(q)) return d; return wrap(q + k * signed(q, d)); });
}

// ---- the reference -------------------------------------------------------------------------------------------------
function rowsOf(setup) { // his routine's rows from the setup, or null when there is none that can be read
  const raw = setup && Array.isArray(setup.angles) ? setup.angles : (setup && Array.isArray(setup.chunks) ? setup.chunks.flat() : null);
  if (!raw || raw.length < ROWS_MIN || raw.length > ROWS_MAX) return null;
  const good = raw.every((row) => Array.isArray(row) && row.length === COLS && row.every((a) => Number.isFinite(a) && a >= 0 && a <= 360));
  return good ? raw : null;
}
function circMean(rows) { return rows.at(0).map((a, i) => wrap(a + mean(rows.map((r) => signed(a, r.at(i)))))); }
function stepsOf(rows) { // the pauses after the opening stance, alike neighbours merged
  const speed = rows.map((row, i) => (i < 2 || i > rows.length - 3 ? Infinity : apart(rows.at(i + 2), rows.at(i - 2)) / (4 * ROW_S)));
  const spans = [];
  let from = -1;
  speed.concat([Infinity]).forEach((v, i) => {
    if (v < STILL_DPS && from < 0) from = i;
    else if (!(v < STILL_DPS) && from >= 0) { if (i - from >= PAUSE_ROWS) spans.push([from, i]); from = -1; }
  });
  const opening = spans.length > 0 && spans.at(0).at(0) <= 2; // the stance he starts from is not a step
  const pauses = (opening ? spans.slice(1) : spans).map(([a, b]) => circMean(rows.slice(a, b)));
  return pauses.reduce((out, pz) => (out.length && apart(out.at(-1), pz) < MERGE_DEG ? out : out.concat([pz])), []);
}

// ---- record ----------------------------------------------------------------------------------------------------------
function recordRow(s, t) { // every grid slot passed since the last row gets this frame's posture
  if (s.rows.length >= ROWS_MAX) return s;
  const last = s.rows.at(-1), row = s.dirs.map((d, i) => round1(Number.isFinite(d) ? d : (last ? last.at(i) : 0)) % 360);
  const due = Math.floor((t - s.t0) / ROW_S + 1e-6) + 1 - s.rows.length;
  if (due <= 0) return s;
  return Object.assign({}, s, { rows: s.rows.concat(Array.from({ length: Math.min(due, ROWS_MAX - s.rows.length) }, () => row)) });
}

// ---- follow ----------------------------------------------------------------------------------------------------------
function advance(s) { // the next step reached (or the one after it, the next missed)
  const d = s.dirs, n = s.steps.length;
  if (s.next >= n) return s;
  if (apart(d, s.steps.at(s.next)) <= MATCH_DEG) return Object.assign({}, s, { next: s.next + 1, marks: s.marks.concat([{ step: s.next + 1, done: true }]) });
  if (s.next + 1 < n && apart(d, s.steps.at(s.next + 1)) <= SKIP_DEG) {
    return Object.assign({}, s, { next: s.next + 2, marks: s.marks.concat([{ step: s.next + 1, done: false }, { step: s.next + 2, done: true }]) });
  }
  return s;
}
function flicks(s, t) { // judge the frame HALF_S ago against its own path either side
  const raw = s.raw.filter((x) => x.t >= t - 2 * HALF_S - 0.05);
  const at = raw.find((x) => x.t >= t - HALF_S - 1e-6);
  if (!at || raw.at(0).t > at.t - HALF_S + 0.05 || at.judged) return Object.assign({}, s, { raw });
  const offs = at.d.map((a, i) => { const path = raw.map((x) => x.d.at(i)).filter(Number.isFinite); return Number.isFinite(a) && path.length > 4 ? Math.abs(signed(wrap(a + mean(path.map((b) => signed(a, b)))), a)) : 0; });
  const flick = offs.some((x) => x > FLICK_ONE) || offs.filter((x) => x > FLICK_TWO).length >= 2;
  const count = flick && t - s.lastFlick >= REFRACTORY_S;
  return Object.assign({}, s, { raw: raw.map((x) => (x === at ? Object.assign({}, x, { judged: true }) : x)),
    flicks: s.flicks + (count ? 1 : 0), lastFlick: count ? t : s.lastFlick });
}

function routineOf(setup) { const n = setup && Number.isInteger(setup.routine) ? setup.routine : 1; return n >= 1 && n <= ROUTINES ? n : 1; }

function begin(r, t, at) {
  const setup = r.setup, rows = setup && setup.record === true ? null : rowsOf(setup);
  return { began: at, at, t, t0: t, mode: rows ? 'follow' : 'record', routine: routineOf(setup), dirs: null, rows: [],
    steps: rows ? stepsOf(rows) : [], next: 0, marks: [], raw: [], flicks: 0, lastFlick: -Infinity };
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = Object.assign({}, state || begin(r, t, at), { at: Math.max((state && state.at) || at, at) });
  const now = shape(p), k = 1 - Math.exp(-Math.max(0, t - s0.t) / SMOOTH_S);
  const s = Object.assign({}, s0, { t, dirs: smoothed(s0.dirs, now, s0.dirs ? k : 1) });
  if (s.mode === 'record') return recordRow(s, t);
  return flicks(advance(Object.assign({}, s, { raw: s.raw.concat([{ t, d: now }]) })), t);
}

function chunks(rows) { return Array.from({ length: Math.ceil(rows.length / CHUNK) }, (_, i) => rows.slice(i * CHUNK, (i + 1) * CHUNK)); }
function smoothness(s) {
  const minutes = Math.max(1, (s.t - s.t0) / 60);
  return Math.max(0, Math.min(100, Math.round(100 - (FLICK_PTS * s.flicks) / minutes)));
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [{ kind: 'line', text: WORDS.place }, hurts], tally: null };
  if (s.mode === 'record') {
    const full = s.rows.length >= ROWS_MAX;
    const view = [{ kind: 'timer', s: Math.round(s.rows.length * ROW_S), word: WORDS.recorded }, { kind: 'line', text: full ? WORDS.limit : WORDS.record }, hurts];
    const tally = s.rows.length >= ROWS_MIN ? { record: { rid: `tai-chi-${s.routine}`, kind: 'tai-chi', chunks: chunks(s.rows) } } : null;
    return { view, tally };
  }
  const done = s.marks.filter((m) => m.done).length, smooth = smoothness(s), recent = s.t - s.lastFlick <= 5;
  const view = [{ kind: 'big', n: done, word: `${WORDS.steps} ${s.steps.length}` }, { kind: 'bar', n: smooth, word: WORDS.smooth }];
  if (recent) view.push({ kind: 'tip', text: WORDS.flick });
  view.push({ kind: 'line', text: s.next < s.steps.length ? `${WORDS.next} ${s.next + 1}` : WORDS.complete }, hurts);
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), done: Math.min(500, done), smooth };
  return { view, tally };
}

JarvisVision.use({ id: 'tai-chi', tasks: ['pose'], onResult, summary });
