// src/jarvis/api/static/console-coach-handstand.js -- R8.1 builder G, row 237 (HF-113, handstand hold drift and safe
// exit, with a wall or a spotter only; docs/plans/r8-vision.md v8.0.4 sections 2.2 and 6.7). Use case `handstand`:
// `pose` at up to 10 a second, one body's state at a time (D6). The phone sees him side-on.
// SAFETY FIRST: it times nothing until he has confirmed "a wall behind me" or "a spotter with me" on the Workout pane;
// that confirmation reaches this use case only as its first state, {setup: {support: 'wall'|'spotter', limit}} (the S2
// contract line R8.1 asks for). Without it, it only asks for the confirmation, and if he is upside down anyway it tells
// him to come down; no hold is timed or kept. A spotter in view is another body with its own state, which never holds.
// Upside down: the hips above the shoulders by half the torso's length, the feet above the hips, the hands below the
// shoulders. A hold starts at the first upside-down frame and ends at the last one before half a second the right way
// up (or unseen). Its first 0.6 s set where his hips stack over his hands; the drift is how far the hips then move
// sideways from there (a share of the torso's length): past two thirds of the limit (0.3 unless set) a warning, past
// the limit "Come down now." (each time counted). Upside-down tracking is "to be tried" (risk 4): when the model loses
// him, the hold ends and he is told to come down safely.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' HandstandTally (support, hold_s the best hold, drifts, the session's start and
// end). View: timer {s, word}, line, tip, paused.
import { dist } from './console-coach-geom.js';

const SEEN = 0.3; // upside down, the model is less sure: a lower bar to see a point at all
const SUPPORTS = Object.freeze(['wall', 'spotter']);
const LIMIT = 0.3;
const LIMIT_MIN = 0.1;
const LIMIT_MAX = 0.8;
const UP = 0.5; // the hips above the shoulders by this share of the torso
const END_S = 0.5; // the right way up (or unseen) this long ends a hold
const REF_S = 0.6;
const WARN = 2 / 3;
const CLEAR = 0.5; // back under half the limit, a new drift may be counted
const OVER_S = 0.3; // past the limit this long (not a moment of coming down) is a drift
const LOST_S = 1.5;
const WORDS = Object.freeze([
  'Confirm a wall behind you or a spotter with you first.', 'Come down now. Confirm a wall or a spotter first.',
  'hold', 'Stop if anything hurts.', 'Kick up against the wall when you are ready.', 'Kick up when your spotter is ready.',
  'Hips drifting. Push tall through your shoulders.', 'Come down now.', 'I cannot see you. Come down safely.',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const wall = () => performance.now() / 1000;
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (seen(a) ? a : (seen(b) ? b : null)));
const secs = (v) => Math.round(v * 10) / 10;
function setupOf(state) { // the support he confirmed, else null: nothing is timed without it
  const su = state && state.setup && typeof state.setup === 'object' ? state.setup : null;
  if (!su || !SUPPORTS.includes(su.support)) return null;
  const limit = Number.isFinite(su.limit) ? Math.min(LIMIT_MAX, Math.max(LIMIT_MIN, su.limit)) : LIMIT;
  return { support: su.support, limit };
}
function upside(p) { // -> {up: bool, dx: the hips' sideways offset from the hands in torso lengths} or null (unseen)
  const sh = mid(p[11], p[12]), hip = mid(p[23], p[24]), ft = mid(p[27], p[28]), hand = mid(p[15], p[16]);
  if (!sh || !hip || !ft || !hand) return null;
  const torso = dist(sh, hip);
  if (!(torso > 0)) return null;
  return { up: sh.y - hip.y >= UP * torso && ft.y < hip.y && hand.y > sh.y, dx: (hip.x - hand.x) / torso };
}

function begin(t, at, su) {
  return { began: at, at, t, seenAt: wall(), support: su ? su.support : '', limit: su ? su.limit : LIMIT, blocked: false,
    holding: false, since: 0, lastUp: 0, ref: { sum: 0, n: 0 }, drift: 0, warn: false, over: false, overSince: -1, drifts: 0,
    holds: 0, best: 0, last: 0, cur: 0 };
}

function ended(s) {
  const last = Math.max(0, s.lastUp - s.since);
  return Object.assign({}, s, { holding: false, warn: false, over: false, holds: s.holds + 1, last, cur: 0,
    best: Math.max(s.best, last) });
}

function holdFrame(s, u, t) { // upside down this frame
  const fresh = !s.holding;
  const base = fresh ? Object.assign({}, s, { holding: true, since: t, ref: { sum: 0, n: 0 }, drift: 0, warn: false, over: false,
    overSince: -1 }) : s;
  const cur = t - base.since;
  if (cur <= REF_S) return Object.assign({}, base, { lastUp: t, cur, ref: { sum: base.ref.sum + u.dx, n: base.ref.n + 1 } });
  const drift = Math.abs(u.dx - base.ref.sum / Math.max(1, base.ref.n)) / base.limit; // a share of the limit
  const past = base.over ? drift > CLEAR : drift > 1;
  const overSince = past ? (base.overSince < 0 ? t : base.overSince) : -1;
  const over = past && (base.over || t - overSince >= OVER_S);
  return Object.assign({}, base, { lastUp: t, cur, drift, warn: drift > WARN, over, overSince,
    drifts: base.drifts + (over && !base.over ? 1 : 0), best: Math.max(base.best, cur) });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  let s = state && state.support !== undefined ? state : begin(t, at, setupOf(state));
  s = Object.assign({}, s, { t, at: Math.max(s.at, at), seenAt: wall() });
  const u = upside(p);
  if (!s.support) return Object.assign({}, s, { blocked: !!(u && u.up) }); // no wall, no spotter: never a hold
  if (u && u.up) return holdFrame(s, u, t);
  return s.holding && t - s.lastUp >= END_S ? ended(s) : s;
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[3] };
  if (!s || !s.support) return { view: [{ kind: 'paused', why: s && s.blocked ? WORDS[1] : WORDS[0] }, hurts], tally: null };
  const lost = s.holding && wall() - s.seenAt > LOST_S;
  const view = [{ kind: 'timer', s: secs(s.holding ? s.cur : s.last), word: WORDS[2] }];
  if (s.best) view.push({ kind: 'line', text: `Best hold ${secs(s.best)} s.` });
  if (lost) view.push({ kind: 'paused', why: WORDS[8] });
  else if (s.over) view.push({ kind: 'paused', why: WORDS[7] });
  else if (s.warn) view.push({ kind: 'tip', text: WORDS[6] });
  if (!s.holding) view.push({ kind: 'line', text: s.support === 'wall' ? WORDS[4] : WORDS[5] });
  view.push(hurts);
  const best = Math.max(s.best, s.holding ? s.cur : 0);
  const tally = s.holds || s.holding ? { started_at: s.began, ended_at: Math.max(s.began, s.at), support: s.support,
    hold_s: secs(best), drifts: s.drifts } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'handstand', tasks: ['pose'], onResult, summary });
