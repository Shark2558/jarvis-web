// src/jarvis/api/static/console-coach-partner.js -- R8.1 builder H, row 240 (HF-70, the assisted-stretching partner
// monitor; docs/plans/r8-vision.md v8.0.4 sections 2.2 and 6.8). Use case `partner-stretch`: `pose` at up to 10 a
// second on the tripod phone, side on. Two bodies are in view, him and the partner who stretches him, and ONLY HIS
// stretch is measured or kept: this use case never tracks the partner (the owner's rule of 28 Nov 2026).
// Which body is his: the phone matches no face, so the engine calls a body "me" only while it is alone in view. A body
// is taken as his only when its first OWNER_FRAMES Results in a row come alone in view, within OWNER_WINDOW_S of his
// consent tap. Every other body (the partner, anyone who walks in, a body first seen beside someone) gets the frozen
// NOT_YOU state for the whole session: no point, count, time or angle; its summary shows no number and keeps nothing.
// Nothing starts before he confirms the partner's consent line: the Workout pane's setup {consent: true, consent_at:
// unix seconds} rides on each Result (a contract line for I1: live(..., {setup}) puts a use case's setup on its
// Results). Without it every body stays NO_CONSENT (frozen, empty).
// His stretch: the joint the partner moves (`setup.stretch`, else the joint that rose most from rest): hip (the leg
// raised, 180 - shoulder-hip-knee), knee (the heel to the seat, 180 - hip-knee-ankle) or shoulder (the arm taken
// overhead, hip-shoulder-elbow), in degrees, on the side the camera sees better. A stretch starts MIN_RISE above
// rest; it is held while within BAND of its deepest and moving less than STILL degrees a second; it ends back near
// rest, and counts if it was held MIN_HOLD_S. Kept per stretch: its range (the deepest) and its hold (seconds). If his
// body suddenly jumps across the frame (the engine swapped the two bodies' tracks) his session ends there, keeping
// only what came before: never a partner's angle.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' PartnerStretchTally (stretches, hold_s in all, range_deg the best).
import { angle, dist, ema, hold } from './console-coach-geom.js';

const OWNER_FRAMES = 5; // Results in a row alone in view before a body is taken as his
const OWNER_WINDOW_S = 20; // ... and only this soon after his consent tap
const SKEW_S = 1; // whole seconds: the pane's clock and the engine's
const JUMP = 1.2; // torso lengths in one step: another body, not his
const JUMP_FRAMES = 3; // such steps in a row end his session
const MIN_RISE = 20; // degrees above rest that make a stretch
const BAND = 6; // degrees under the stretch's deepest that still hold
const STILL = 10; // degrees a second at most while holding
const STILL_WINDOW_S = 0.5;
const MIN_HOLD_S = 3;
const K = 0.35; // smoothing of each joint's angle
const SEEN = 0.5;
const DONE_MAX = 200;
const JOINTS = Object.freeze([
  Object.freeze({ name: 'hip', sides: Object.freeze([[11, 23, 25], [12, 24, 26]]), flex: true }),
  Object.freeze({ name: 'knee', sides: Object.freeze([[23, 25, 27], [24, 26, 28]]), flex: true }),
  Object.freeze({ name: 'shoulder', sides: Object.freeze([[23, 11, 13], [24, 12, 14]]), flex: false }),
]);
const WORDS = Object.freeze({
  consent: 'Confirm that your partner agrees to be in view.',
  kept: 'Only your stretch is measured and kept; your partner is never tracked.',
  first: 'Stand alone in view first: JARVIS keeps only your stretch.',
  alone: 'Stay alone in view for a moment so JARVIS knows which one is you.',
  ready: 'Got you. Your partner can join now.',
  notYou: 'Not tracked: nothing about this person is kept.',
  lost: 'Lost track of you: start again to go on.',
  into: 'Into the stretch.',
  hold: 'Hold it. Breathe.',
  release: 'Ease out slowly.',
  rest: 'Rest, then the next stretch.',
  held: 'held',
  stretches: 'stretches',
  best: 'Best range',
  degrees: 'degrees; last held',
  ease: 'Tell your partner to ease off if anything hurts.',
  hurts: 'Stop if anything hurts.',
  practice: 'Practice only, not medical advice.',
});
const NO_CONSENT = Object.freeze({ kind: 'consent' });
const NOT_YOU = Object.freeze({ kind: 'not-you' });
const line = (text) => ({ kind: 'line', text });
const STOP = Object.freeze(line(WORDS.hurts));

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const atOf = (r) => (Number.isInteger(r.at) ? r.at : 0);
const round1 = (v) => Math.round(v * 10) / 10;
const pointsOf = (r) => (r.ok && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const seenOf = (q) => (q && Number.isFinite(q.x) && Number.isFinite(q.y) ? (Number.isFinite(q.visibility) ? q.visibility : 1) : 0);
const mid = (a, b) => (seenOf(a) >= SEEN && seenOf(b) >= SEEN ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : null);
const hips = (p) => mid(p.at(23), p.at(24));
const shoulders = (p) => mid(p.at(11), p.at(12));
const centreOf = (p) => hips(p) || shoulders(p);
const torsoOf = (p) => { const h = hips(p), s = shoulders(p); return h && s ? dist(h, s) : NaN; };

function consented(r) {
  const s = r.setup;
  return !!s && s.consent === true && Number.isInteger(s.consent_at);
}
function inWindow(r) {
  const at = atOf(r), c = r.setup.consent_at;
  return at >= c - SKEW_S && at <= c + OWNER_WINDOW_S;
}
function chosen(r) {
  const want = r.setup && typeof r.setup.stretch === 'string' ? r.setup.stretch : '';
  return JOINTS.findIndex((j) => j.name === want);
}

function rangeOf(joint, p) { // degrees, on the side the camera sees better; NaN when that side is hidden
  const vis = (ids) => Math.min(...ids.map((i) => seenOf(p.at(i))));
  const one = joint.sides.at(0), two = joint.sides.at(1);
  const ids = vis(one) >= vis(two) ? one : two;
  if (vis(ids) < SEEN) return NaN;
  const a = angle(p.at(ids.at(0)), p.at(ids.at(1)), p.at(ids.at(2)));
  return joint.flex ? 180 - a : a;
}

function begin(r) {
  const s = { kind: 'you', began: atOf(r), at: atOf(r), t: clock(r), c: null, scale: 0, far: 0, lost: false, joint: chosen(r),
    sm: [NaN, NaN, NaN], rest: [NaN, NaN, NaN], phase: 'rest', active: -1, peak: 0, h: null, win: [], done: [] };
  const p = pointsOf(r);
  return p ? measure(s, p, s.t, s.at) : s;
}

function close(s) { // a stretch ends: kept if it was held long enough; his rest is where he is now
  const held = s.h ? s.h.total : 0;
  const done = held >= MIN_HOLD_S
    ? s.done.concat([{ range: Math.round(Math.min(180, Math.max(0, s.peak))), hold: round1(held) }]).slice(-DONE_MAX) : s.done;
  return Object.assign({}, s, { done, phase: 'rest', active: -1, peak: 0, h: null, win: [], rest: s.sm.slice() });
}

function resting(s) {
  const rest = s.sm.map((v, i) => {
    const was = s.rest.at(i);
    if (!Number.isFinite(v)) return was;
    return Number.isFinite(was) ? Math.min(was, v) : v;
  });
  const rise = s.sm.map((v, i) => ((s.joint < 0 || s.joint === i) && Number.isFinite(v) && Number.isFinite(rest.at(i)) ? v - rest.at(i) : -1));
  const best = Math.max(...rise);
  if (best < MIN_RISE) return Object.assign({}, s, { rest });
  const active = rise.indexOf(best);
  return Object.assign({}, s, { rest, phase: 'into', active, peak: s.sm.at(active), h: null, win: [] });
}

function stretching(s) {
  const v = s.sm.at(s.active);
  if (!Number.isFinite(v)) return s;
  const peak = Math.max(s.peak, v);
  const win = s.win.concat([[s.t, v]]).filter((w) => s.t - w.at(0) <= STILL_WINDOW_S);
  const first = win.at(0), span = s.t - first.at(0);
  const speed = win.length > 1 && span > 0 ? Math.abs(v - first.at(1)) / span : Infinity;
  const good = v >= peak - BAND && speed <= STILL;
  const h = hold(s.h || undefined, good, s.t);
  const phase = good ? 'hold' : (v < peak - BAND ? 'release' : 'into');
  const next = Object.assign({}, s, { peak, win, h, phase });
  return v < s.rest.at(s.active) + MIN_RISE / 2 ? close(next) : next;
}

function measure(s, p, t, at) {
  const sm = JOINTS.map((j, i) => ema(s.sm.at(i), rangeOf(j, p), K));
  const c = centreOf(p), torso = torsoOf(p);
  const scale = Number.isFinite(torso) ? ema(s.scale || undefined, torso, 0.2) : s.scale;
  const next = Object.assign({}, s, { t, at, sm, c: c || s.c, scale });
  return next.phase === 'rest' ? resting(next) : stretching(next);
}

function yours(s, r) {
  if (s.lost) return s;
  const p = pointsOf(r);
  if (!p) return s;
  const t = clock(r), at = Math.max(s.at, atOf(r)), c = centreOf(p);
  if (s.c && c && dist(c, s.c) > JUMP * Math.max(s.scale, 0.05)) { // not his body: skipped; if it lasts, his session ends
    const far = s.far + 1;
    return far < JUMP_FRAMES ? Object.assign({}, s, { far }) : Object.assign(close(s), { far, lost: true, at });
  }
  return measure(Object.assign({}, s, { far: 0 }), p, t, at);
}

function onResult(r, state) {
  if (!r || r.task !== 'pose') return state;
  const s = state || NO_CONSENT;
  if (s.kind === 'not-you') return NOT_YOU;
  if (s.kind === 'you') return yours(s, r);
  if (!consented(r)) return NO_CONSENT;
  if (r.who !== 'me' || !inWindow(r)) return NOT_YOU; // seen beside someone, or long after the consent: never his
  const alone = (s.kind === 'who' ? s.alone : 0) + 1;
  return alone < OWNER_FRAMES ? Object.freeze({ kind: 'who', alone }) : begin(r);
}

function tallyOf(s) {
  if (!s.done.length) return null;
  return { started_at: s.began, ended_at: Math.max(s.began, s.at), stretches: s.done.length,
    hold_s: round1(s.done.reduce((n, d) => n + d.hold, 0)), range_deg: Math.max(...s.done.map((d) => d.range)) };
}

function phaseWord(s) {
  if (s.phase === 'into') return WORDS.into;
  if (s.phase === 'hold') return WORDS.hold;
  if (s.phase === 'release') return WORDS.release;
  return s.done.length ? WORDS.rest : WORDS.ready;
}

function summary(s) {
  if (!s || s.kind === 'consent') return { view: [line(WORDS.consent), line(WORDS.kept), line(WORDS.first), STOP], tally: null };
  if (s.kind === 'not-you') return { view: [{ kind: 'paused', why: WORDS.notYou }, line(WORDS.first), STOP], tally: null };
  if (s.kind === 'who') return { view: [line(WORDS.alone), line(WORDS.kept), STOP], tally: null };
  const now = s.h && s.h.holding ? s.t - s.h.since : 0;
  const view = [s.lost ? { kind: 'paused', why: WORDS.lost } : { kind: 'timer', s: Math.round(now), word: WORDS.held },
    { kind: 'big', n: s.done.length, word: WORDS.stretches }];
  if (!s.lost) view.push(line(phaseWord(s)));
  const last = s.done.at(-1);
  if (last) view.push(line(`${WORDS.best} ${Math.max(...s.done.map((d) => d.range))} ${WORDS.degrees} ${last.hold} s.`));
  view.push(line(WORDS.ease), STOP, line(WORDS.practice));
  return { view, tally: tallyOf(s) };
}

JarvisVision.use({ id: 'partner-stretch', tasks: ['pose'], onResult, summary });
