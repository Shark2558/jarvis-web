// src/jarvis/api/static/console-coach-kettlebell.js -- R8.1 builder G, row 239 (HF-99, the kettlebell swing path and
// hip-hinge feedback; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `kettlebell`: `pose` at up to 15 a second,
// one body's state at a time (D6). The phone sees him side-on. Both hands hold the bell, so the middle of his wrists is
// the bell's path. A swing is the bell going well below his shoulders (past 0.8 of the torso's length, as when it hangs
// or passes between his legs) and then rising to chest height (within 0.55 of the torso below the shoulders); a part
// swing never counts. At the bottom of each swing (the most bent hip) the hip and the knee are compared: a hinge bends
// the hip at least 40 degrees and the knee less than 0.55 of what the hip bends; anything else is a squat, and gets the
// one tip. The bell's last moments are drawn as its path (targets: dots, the bell as a ring).
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' KettlebellTally (swings, hinge: the share of swings that were hinges, 0..100,
// the session's start and end). View: big {n, word}, targets {lit, dots, hands}, bar {n, word}, tip, line.
import { angle, dist, reps } from './console-coach-geom.js';

const SEEN = 0.5;
const LIMITS = Object.freeze({ down: -0.8, up: -0.55 }); // the bell's height to the shoulders, in torso lengths
const HINGE_MIN = 40;
const HINGE_RATIO = 0.55;
const PATH_MAX = 24;
const DOTS = 8;
const WORDS = Object.freeze([
  'Stand side-on to the phone, the bell in both hands.', 'swings', 'Hip hinge', 'Stop if anything hurts.',
  'Push your hips back and keep your shins nearly upright.', 'Good hinge.',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (seen(a) ? a : (seen(b) ? b : null)));
const round2 = (v) => Math.round(v * 100) / 100;

function begin(t, at) {
  return { began: at, at, t, c: undefined, bottom: null, swings: 0, hinges: 0, lastHinge: null, path: [], bell: null };
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const sh = mid(p[11], p[12]), hip = mid(p[23], p[24]), kn = mid(p[25], p[26]), an = mid(p[27], p[28]), bell = mid(p[15], p[16]);
  if (!sh || !hip || !bell) return state;
  const torso = dist(sh, hip);
  if (!(torso > 0)) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = state && state.path ? state : begin(t, at);
  const c = reps(s.c, (sh.y - bell.y) / torso, { down: LIMITS.down, up: LIMITS.up, t });
  const hipFlex = kn ? 180 - angle(sh, hip, kn) : NaN, kneeFlex = kn && an ? 180 - angle(hip, kn, an) : NaN;
  let bottom = s.bottom;
  if (c.phase === 'down' && Number.isFinite(hipFlex) && (!bottom || hipFlex > bottom.hip)) bottom = { hip: hipFlex, knee: kneeFlex };
  const path = s.path.concat([{ x: round2(bell.x), y: round2(bell.y) }]).slice(-PATH_MAX);
  const n = Object.assign({}, s, { t, at: Math.max(s.at, at), c, bottom, path, bell: { x: round2(bell.x), y: round2(bell.y) } });
  if (!s.c || c.count === s.c.count) return n;
  const hinge = !!bottom && bottom.hip >= HINGE_MIN && bottom.knee < HINGE_RATIO * bottom.hip;
  return Object.assign({}, n, { swings: s.swings + 1, hinges: s.hinges + (hinge ? 1 : 0), lastHinge: hinge, bottom: null });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[3] };
  if (!s || !s.swings) return { view: [{ kind: 'big', n: 0, word: WORDS[1] }, { kind: 'line', text: WORDS[0] }, hurts], tally: null };
  const score = Math.round(100 * s.hinges / s.swings);
  const every = Math.max(1, Math.floor(s.path.length / DOTS));
  const dots = s.path.filter((_, i) => (s.path.length - 1 - i) % every === 0).slice(-DOTS);
  const view = [{ kind: 'big', n: s.swings, word: WORDS[1] },
    { kind: 'targets', lit: -1, dots, hands: s.bell ? [s.bell] : [] },
    { kind: 'bar', n: score, word: WORDS[2] },
    s.lastHinge ? { kind: 'line', text: WORDS[5] } : { kind: 'tip', text: WORDS[4] },
    hurts];
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), swings: s.swings, hinge: score };
  return { view, tally };
}

JarvisVision.use({ id: 'kettlebell', tasks: ['pose'], onResult, summary });
