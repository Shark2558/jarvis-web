// src/jarvis/api/static/console-coach-dance.js -- R8.1 builder F, row 236 (HF-09, the dance choreography sync coach;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `dance`: `pose` at up to 15 a second on the tripod phone, one
// body's state at a time (D6). Against HIS recorded routine (coach_routines `dance-1`..`20`):
//   record  (no reference, or `setup.record`): the body's nine segment directions (the torso, each upper arm, forearm,
//           thigh and shin; degrees in the picture, smoothed over 0.15 s) on a grid of 10 rows a second, at most 3,000
//           rows (5 minutes). Angles only: never a point. The tally carries the recording for the pane to keep,
//           {record: {rid, kind, chunks}} (rows in chunks of 100, the engine's plain-data limit), and no result.
//   follow  (`setup.angles` rows or `setup.chunks`): from the session's first frame, each frame is compared with his
//           routine at every offset from 1 s behind to 1 s ahead (every 0.05 s, read between rows); the offset with the
//           least mean difference over the session is his timing error, and its difference his shape error. The sync
//           score is 100 less 60 points a second of timing error, less 1.5 a degree of shape error past 10 degrees, so
//           a half-second offset costs 30 points in any style, fast or slow. A routine too still to time is scored on
//           its shape alone. The hint ("behind", "ahead") uses the last few seconds only.
// The setup rides on each Result as `setup` (the pane's choices: a contract line for I1). Tally (follow):
// jarvis.coach.usecases' DanceTally -- the routine's number and the sync score. A use case, held to the guard
// (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared geometry.
import { dist } from './console-coach-geom.js';

const WORDS = Object.freeze({
  record: 'Recording your routine: dance it once, then press Stop.', limit: 'Your routine is at its five-minute limit.',
  recorded: 'recorded', danced: 'danced', sync: 'In time', ended: 'Your routine has ended.', behind: 'behind the routine',
  ahead: 'ahead of the routine', inTime: 'In time with your routine.', about: 'About', place: 'Stand where the phone sees all of you.',
  hurts: 'Stop if anything hurts.',
});
const SEEN = 0.5;
const COLS = 9;
const ROW_S = 0.1;
const ROWS_MAX = 3000;
const ROWS_MIN = 20;
const CHUNK = 100;
const SMOOTH_S = 0.15;
const LAG_MAX_S = 1;
const LAG_STEP_S = 0.05;
const LAGS = Object.freeze(Array.from({ length: Math.round((2 * LAG_MAX_S) / LAG_STEP_S) + 1 }, (_, j) => Math.round((j * LAG_STEP_S - LAG_MAX_S) * 100) / 100));
const TIMING_PTS = 60; // points a second of timing error costs
const SHAPE_OK = 10; // degrees of shape error that cost nothing
const SHAPE_PTS = 1.5; // points each degree past it costs
const FLAT_DEG = 2; // a curve shallower than this cannot be timed
const RECENT_S = 4; // the hint's memory
const IN_TIME_S = 0.15;
const ROUTINES = 20;

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

function rowsOf(setup) { // his routine's rows from the setup, or null when there is none that can be read
  const raw = setup && Array.isArray(setup.angles) ? setup.angles : (setup && Array.isArray(setup.chunks) ? setup.chunks.flat() : null);
  if (!raw || raw.length < ROWS_MIN || raw.length > ROWS_MAX) return null;
  const good = raw.every((row) => Array.isArray(row) && row.length === COLS && row.every((a) => Number.isFinite(a) && a >= 0 && a <= 360));
  return good ? raw : null;
}
function refAt(rows, e) { // his routine at e seconds, read between its rows; null outside it
  const x = e / ROW_S, i = Math.floor(x);
  if (i < 0 || i >= rows.length - 1) return null;
  const a = rows.at(i), b = rows.at(i + 1), k = x - i;
  return a.map((v, c) => wrap(v + k * signed(v, b.at(c))));
}
function apart(live, ref) { const ds = live.map((d, i) => off(d, ref.at(i))).filter(Number.isFinite); return ds.length >= 5 ? mean(ds) : NaN; }

function recordRow(s, t) { // every grid slot passed since the last row gets this frame's posture
  if (s.rows.length >= ROWS_MAX) return s;
  const last = s.rows.at(-1), row = s.dirs.map((d, i) => round1(Number.isFinite(d) ? d : (last ? last.at(i) : 0)) % 360);
  const due = Math.floor((t - s.t0) / ROW_S + 1e-6) + 1 - s.rows.length;
  if (due <= 0) return s;
  return Object.assign({}, s, { rows: s.rows.concat(Array.from({ length: Math.min(due, ROWS_MAX - s.rows.length) }, () => row)) });
}

function best(sums, counts) { // the offset with the least mean difference (the nearer to 0 on a tie), and that difference
  const curve = LAGS.map((lag, j) => (counts.at(j) > 0 ? sums.at(j) / counts.at(j) : NaN));
  const known = curve.filter(Number.isFinite);
  if (!known.length) return { lag: 0, err: NaN };
  const j = curve.reduce((b, v, i) => (Number.isFinite(v) && (b < 0 || v + 0.01 * Math.abs(LAGS.at(i)) < curve.at(b) + 0.01 * Math.abs(LAGS.at(b))) ? i : b), -1);
  if (Math.max(...known) - Math.min(...known) < FLAT_DEG) return { lag: 0, err: curve.at(LAGS.indexOf(0)) };
  const [l, m, r] = [curve.at(j - 1), curve.at(j), curve.at(j + 1)];
  const bend = j > 0 && j < LAGS.length - 1 && Number.isFinite(l) && Number.isFinite(r) ? l - 2 * m + r : 0;
  const shift = bend > 0 ? Math.max(-0.5, Math.min(0.5, (l - r) / (2 * bend))) : 0; // between the steps
  return { lag: LAGS.at(j) + shift * LAG_STEP_S, err: m };
}

function compare(s, t) { // add this frame's difference at every offset to the session's and the recent curves
  const e = t - s.t0, fade = Math.exp(-Math.max(0, t - s.t) / RECENT_S);
  const errs = LAGS.map((lag) => { const ref = refAt(s.ref, e + lag); return ref ? apart(s.dirs, ref) : NaN; });
  if (!errs.some(Number.isFinite)) return Object.assign({}, s, { over: e > 0 });
  const add = (xs, w) => xs.map((x, j) => (Number.isFinite(errs.at(j)) ? x + w * errs.at(j) : x));
  const cnt = (xs, w) => xs.map((x, j) => (Number.isFinite(errs.at(j)) ? x + w : x));
  const sums = add(s.sums, 1), counts = cnt(s.counts, 1);
  const rs = add(s.rs.map((x) => x * fade), 1), rc = cnt(s.rc.map((x) => x * fade), 1);
  const whole = best(sums, counts), now = best(rs, rc);
  return Object.assign({}, s, { sums, counts, rs, rc, lag: Math.round(whole.lag * 100) / 100, err: whole.err, lagNow: now.lag, over: false });
}

function routineOf(setup) { const n = setup && Number.isInteger(setup.routine) ? setup.routine : 1; return n >= 1 && n <= ROUTINES ? n : 1; }
const zeros = () => LAGS.map(() => 0);

function begin(r, t, at) {
  const setup = r.setup, ref = setup && setup.record === true ? null : rowsOf(setup);
  return { began: at, at, t, t0: t, mode: ref ? 'follow' : 'record', routine: routineOf(setup), dirs: null, rows: [], ref,
    sums: zeros(), counts: zeros(), rs: zeros(), rc: zeros(), lag: 0, err: NaN, lagNow: 0, over: false };
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s0 = Object.assign({}, state || begin(r, t, at), { at: Math.max((state && state.at) || at, at) });
  const k = 1 - Math.exp(-Math.max(0, t - s0.t) / SMOOTH_S);
  const s = Object.assign({}, s0, { dirs: smoothed(s0.dirs, shape(p), s0.dirs ? k : 1) });
  return Object.assign({}, s.mode === 'record' ? recordRow(s, t) : compare(s, t), { t });
}

function chunks(rows) { return Array.from({ length: Math.ceil(rows.length / CHUNK) }, (_, i) => rows.slice(i * CHUNK, (i + 1) * CHUNK)); }
function syncOf(s) {
  if (!Number.isFinite(s.err)) return 0;
  return Math.max(0, Math.min(100, Math.round(100 - TIMING_PTS * Math.abs(s.lag) - SHAPE_PTS * Math.max(0, s.err - SHAPE_OK))));
}
function hint(s) {
  if (s.over) return WORDS.ended;
  if (Math.abs(s.lagNow) < IN_TIME_S) return WORDS.inTime;
  return `${WORDS.about} ${Math.abs(round1(s.lagNow))} s ${s.lagNow < 0 ? WORDS.behind : WORDS.ahead}`;
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS.hurts };
  if (!s) return { view: [{ kind: 'line', text: WORDS.place }, hurts], tally: null };
  if (s.mode === 'record') {
    const full = s.rows.length >= ROWS_MAX;
    const view = [{ kind: 'timer', s: Math.round(s.rows.length * ROW_S), word: WORDS.recorded }, { kind: 'line', text: full ? WORDS.limit : WORDS.record }, hurts];
    const tally = s.rows.length >= ROWS_MIN ? { record: { rid: `dance-${s.routine}`, kind: 'dance', chunks: chunks(s.rows) } } : null;
    return { view, tally };
  }
  const sync = syncOf(s), timed = Number.isFinite(s.err);
  const view = [{ kind: 'bar', n: sync, word: WORDS.sync }, { kind: 'line', text: timed ? hint(s) : WORDS.place },
    { kind: 'timer', s: Math.round(s.t - s.t0), word: WORDS.danced }, hurts];
  const tally = timed ? { started_at: s.began, ended_at: Math.max(s.began, s.at), routine: s.routine, sync } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'dance', tasks: ['pose'], onResult, summary });
