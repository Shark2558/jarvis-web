// src/jarvis/api/static/console-coach-plank.js -- R8.1 builder E, row 222 (HF-16, the plank hold and alignment coach,
// side view; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `plank`: `pose` at up to 10 a second, one body's
// state at a time (D6). A plank is the torso near level (55 to 125 degrees from upright) with the feet out behind at
// about hip height. The hold runs from the first plank frame to the last; a second out of the plank ends it (one lost
// frame does not). Alignment is how far the shoulder-hip-ankle line bends at the hip: hips more than 10 degrees below
// it for a second is one sag, above it one pike; each is said once, as a fixed tip. The longest hold is kept.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' PlankTally (hold_s, sags, pikes, the session's start and end).
import { angle, dist } from './console-coach-geom.js';

const SEEN = 0.5;
const BEND = 10; // degrees off the straight line before it counts
const SPAN_S = 1; // a sag or pike held this long is one
const GRACE_S = 1; // out of the plank this long ends the hold
const WORDS = Object.freeze([
  'hold', 'Lift your hips a little: one straight line.', 'Lower your hips into one straight line.',
  'Straight line. Keep breathing.', 'Get into a plank, side on to the phone.', 'Best', 'Stop if anything hurts.',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const round1 = (v) => Math.round(v * 10) / 10;

function plankOf(p) { // null when not in a plank; else the line's bend (+ hips low, - hips high)
  const k = [11, 23, 27].filter((i) => seen(p.at(i))).length >= [12, 24, 28].filter((i) => seen(p.at(i))).length ? 0 : 1;
  const sh = p.at(11 + k), hip = p.at(23 + k), an = p.at(27 + k);
  if (!seen(sh) || !seen(hip) || !seen(an)) return null;
  const torso = dist(sh, hip), n = Math.hypot(sh.x - hip.x, sh.y - hip.y);
  const tilt = n ? Math.acos(Math.min(1, Math.max(-1, -(sh.y - hip.y) / n))) * 180 / Math.PI : 0;
  if (tilt < 55 || tilt > 125 || Math.abs(an.y - hip.y) > 0.6 * torso) return null;
  const a = angle(sh, hip, an), lineY = sh.y + (an.y - sh.y) * ((hip.x - sh.x) / ((an.x - sh.x) || 1e-9));
  return { bend: (hip.y > lineY ? 1 : -1) * (180 - a) };
}

function begin(t, at) { return { began: at, at, t, since: -1, lastIn: -1, best: 0, now: 0, kind: '', kindSince: -1, said: '', sags: 0, pikes: 0 }; }

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = Object.assign({}, state || begin(t, at), { t, at: Math.max((state && state.at) || at, at) });
  const f = plankOf(p);
  if (!f) { // out of the plank: the hold ends after the grace
    if (s.since >= 0 && t - s.lastIn >= GRACE_S) return Object.assign({}, s, { since: -1, now: 0, kind: '', kindSince: -1, said: '' });
    return s;
  }
  const since = s.since >= 0 ? s.since : t, now = t - since;
  const kind = f.bend > BEND ? 'sag' : (f.bend < -BEND ? 'pike' : '');
  const kindSince = kind && kind === s.kind ? s.kindSince : (kind ? t : -1);
  const fresh = kind && t - kindSince >= SPAN_S && s.said !== kind;
  return Object.assign({}, s, { since, lastIn: t, now, best: Math.max(s.best, now), kind, kindSince,
    said: kind ? (fresh ? kind : s.said) : '', sags: s.sags + (fresh && kind === 'sag' ? 1 : 0), pikes: s.pikes + (fresh && kind === 'pike' ? 1 : 0) });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[6] };
  if (!s || !s.best) return { view: [{ kind: 'timer', s: 0, word: WORDS[0] }, { kind: 'line', text: WORDS[4] }, hurts], tally: null };
  const view = [{ kind: 'timer', s: Math.round(s.now), word: WORDS[0] }];
  if (s.said === 'sag') view.push({ kind: 'tip', text: WORDS[1] });
  else if (s.said === 'pike') view.push({ kind: 'tip', text: WORDS[2] });
  else if (s.since >= 0) view.push({ kind: 'line', text: WORDS[3] });
  view.push({ kind: 'line', text: `${WORDS[5]} ${Math.round(s.best)} s` }, hurts);
  return { view, tally: { started_at: s.began, ended_at: Math.max(s.began, s.at), hold_s: round1(s.best), sags: s.sags, pikes: s.pikes } };
}

JarvisVision.use({ id: 'plank', tasks: ['pose'], onResult, summary });
