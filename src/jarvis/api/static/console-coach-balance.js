// src/jarvis/api/static/console-coach-balance.js -- R8.1 builder F, row 226 (HF-07, the single-leg balance and stability
// coach; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `balance`: `pose` at up to 15 a second on the tripod
// phone, one body's state at a time (D6). No setup: the standing leg is found from the body, side on or facing the
// phone. One foot is off the floor while its ankle is a quarter of the torso's length above the other (a tenth less to
// stay off, so a wobble near the line does not flicker), the standing leg is straight-ish and the body upright; a change
// counts once it has lasted 0.2 s, and is timed from where it began. The hold runs from the foot leaving the floor to it
// coming down. Sway is the spread of the body's centre (the middle of the hips and shoulders) left and right during the
// hold, after its first half second, over the torso's length, scored 0 (still) .. 100 (a lot). Tally:
// jarvis.coach.usecases' BalanceTally -- the longest hold's standing side, seconds and sway. A use case, held to the guard
// (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared geometry.
import { angle, dist, ema } from './console-coach-geom.js';

const WORDS = Object.freeze({
  lift: 'Lift one foot and hold it off the floor.',
  wall: 'Stand near a wall or a chair you can hold.',
  steady: 'Steadiness', on: 'on your', leg: 'leg', best: 'Best', hurts: 'Stop if anything hurts.',
});
const SIDES = new Map([['left', 'left'], ['right', 'right']]);
const SEEN = 0.5;
const LIFT_ON = 0.25; // torso lengths the lifted ankle is above the standing one
const LIFT_OFF = 0.15;
const DEBOUNCE_S = 0.2;
const SETTLE_S = 0.5; // the first half second of a hold is not counted in its sway
const SMOOTH_S = 0.15; // the centre's smoothing time
const SWAY_REF = 0.08; // the spread (torso lengths) that scores 63
const STRAIGHT = 140; // the standing knee's least angle
const UPRIGHT = 40; // the torso's most lean from upright
const LOG_MAX = 20;

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const round1 = (v) => Math.round(v * 10) / 10;

function bodyOf(p) { // the torso, the two legs, or null when a needed point is not seen
  if (![11, 12, 23, 24, 25, 26, 27, 28].every((i) => seen(p.at(i)))) return null;
  const S = mid(p[11], p[12]), H = mid(p[23], p[24]), len = dist(S, H);
  if (!(len > 0.02)) return null;
  const lean = (Math.acos(Math.min(1, Math.max(-1, (H.y - S.y) / len))) * 180) / Math.PI;
  return { S, H, len, lean, left: { knee: angle(p[23], p[25], p[27]), y: p[27].y }, right: { knee: angle(p[24], p[26], p[28]), y: p[28].y } };
}

function sideOf(b, on) { // the standing leg, '' when both feet are down (or the body is not in a stand)
  if (!b || b.lean > UPRIGHT) return '';
  const rise = (b.right.y - b.left.y) / b.len; // > 0: the left ankle is higher, so he stands on the right
  const need = (side) => (on === side ? LIFT_OFF : LIFT_ON);
  if (rise > need('right') && b.right.knee > STRAIGHT) return 'right';
  if (-rise > need('left') && b.left.knee > STRAIGHT) return 'left';
  return '';
}

function swayScore(st) {
  if (!st || st.n < 2 || !(st.len > 0)) return 0;
  const spread = Math.sqrt(Math.max(0, st.m2 / st.n)) / (st.len / st.n);
  return Math.min(100, Math.max(0, Math.round(100 * (1 - Math.exp(-spread / SWAY_REF)))));
}
function swayAdd(st, x, len) { // Welford's running spread of the centre, and the torso's mean length
  const n = st.n + 1, d = x - st.mean, mean = st.mean + d / n;
  return { n, mean, m2: st.m2 + d * (x - mean), len: st.len + len };
}
const NO_SWAY = Object.freeze({ n: 0, mean: 0, m2: 0, len: 0 });

function begin(t, at) { return { began: at, at, t, raw: '', rawSince: t, on: '', since: -1, cx: undefined, sw: NO_SWAY, log: [], best: null }; }

function endHold(s, until) {
  const hold = { side: s.on, s: round1(Math.max(0, until - s.since)), sway: swayScore(s.sw) };
  const best = !s.best || hold.s > s.best.s ? hold : s.best;
  return Object.assign({}, s, { on: '', since: -1, sw: NO_SWAY, cx: undefined, log: s.log.concat([hold]).slice(-LOG_MAX), best });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  let s = Object.assign({}, state || begin(t, at), { at: Math.max((state && state.at) || at, at) });
  const b = bodyOf(p), raw = sideOf(b, s.on), dt = Math.max(0, t - s.t);
  s = Object.assign({}, s, { t }, raw !== s.raw ? { raw, rawSince: t } : {});
  if (s.raw !== s.on && t - s.rawSince >= DEBOUNCE_S) {
    if (s.on) s = endHold(s, s.rawSince);
    if (s.raw) s = Object.assign({}, s, { on: s.raw, since: s.rawSince });
  }
  if (!s.on || !b) return s;
  const centre = (b.S.x + b.H.x) / 2, cx = ema(s.cx, centre, s.cx === undefined ? 1 : 1 - Math.exp(-dt / SMOOTH_S));
  const settled = t - s.since >= SETTLE_S;
  return Object.assign({}, s, { cx, sw: settled ? swayAdd(s.sw, cx, b.len) : s.sw });
}

function summary(s) {
  const tail = [{ kind: 'line', text: WORDS.wall }, { kind: 'line', text: WORDS.hurts }];
  if (!s) return { view: [{ kind: 'line', text: WORDS.lift }, ...tail], tally: null };
  const live = s.on ? { side: s.on, s: round1(Math.max(0, s.t - s.since)), sway: swayScore(s.sw) } : null;
  const best = live && (!s.best || live.s > s.best.s) ? live : s.best;
  const view = [];
  if (live) view.push({ kind: 'timer', s: Math.round(live.s), word: `${WORDS.on} ${SIDES.get(live.side)} ${WORDS.leg}` },
    { kind: 'bar', n: 100 - live.sway, word: WORDS.steady });
  else view.push({ kind: 'line', text: WORDS.lift });
  if (best) view.push({ kind: 'line', text: `${WORDS.best} ${Math.round(best.s)} s ${WORDS.on} ${SIDES.get(best.side)} ${WORDS.leg}` });
  view.push(...tail);
  const tally = best ? { started_at: s.began, ended_at: Math.max(s.began, s.at), side: best.side, hold_s: best.s, sway: best.sway } : null;
  return { view, tally };
}

JarvisVision.use({ id: 'balance', tasks: ['pose'], onResult, summary });
