// src/jarvis/api/static/console-coach-form.js -- R8.1 builder E, row 220 (HF-01, "AI personal trainer and form
// corrector": fixed rules, no AI call; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `form`: `pose` at up to 15
// a second, one body's state at a time (D6). It follows squats and push-ups, seen from the side or the front, and
// judges each rep once, when it ends, by five fixed rules:
//   depth      squat (side): the knee never bent past 105 degrees; push-up (side): the elbow never bent past 110
//   back       squat (side): the torso leaned more than 55 degrees from upright
//   knees_in   squat (front): at the bottom the knees were less than 0.8 of the ankles' width apart
//   hips       push-up (side): the hips sagged, the shoulder-hip-ankle line bent by more than 15 degrees downwards
//   elbows     push-up (front, the phone at his head): the elbows more than 2.2 shoulder-widths apart at the bottom
// At most one tip a rep (the first rule broken, in that order); a clean rep says so. Reps are counted loosely here
// (a shallow rep is still a rep, so its depth can be judged); `reps` (row 132) counts only full reps.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; no page, network, storage or
// camera; it imports only the shared geometry. Tally: jarvis.coach.usecases' FormTally (exercise, reps, clean, tips).
import { angle, dist } from './console-coach-geom.js';

const SEEN = 0.5;
const TIP_S = 4; // a tip stays on screen this long after its rep
const ORDER = Object.freeze(['depth', 'knees_in', 'back', 'hips', 'elbows']);
const WORDS = Object.freeze([
  'Go a little lower: hips to knee height.', 'Lower your chest a little more.', 'Push your knees out over your toes.',
  'Keep your chest up.', 'Lift your hips into a straight line.', 'Keep your elbows closer to your sides.',
  'Good rep.', 'reps', 'clean', 'Squats', 'Push-ups', 'Form tips are fixed rules, checked on this phone.',
  'Stop if anything hurts.', 'Start a squat or a push-up. Each rep gets one tip at most.',
]);
const TIPS = Object.freeze({ squat: Object.freeze({ depth: WORDS[0], knees_in: WORDS[2], back: WORDS[3] }),
  push_up: Object.freeze({ depth: WORDS[1], hips: WORDS[4], elbows: WORDS[5] }) });
// each way of looking: the number a rep rides on (a dip below `down`, a rise above `up`)
const MODES = Object.freeze({
  'squat-side': Object.freeze({ exercise: 'squat', down: 140, up: 160 }),
  'squat-front': Object.freeze({ exercise: 'squat', down: 45, up: 65 }),
  'push-side': Object.freeze({ exercise: 'push_up', down: 140, up: 155 }),
  'push-front': Object.freeze({ exercise: 'push_up', down: 90, up: 150 }),
});

const get = (o, k) => { const e = Object.entries(o || {}).find((x) => x[0] === k); return e ? e[1] : undefined; };
const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (seen(a) ? a : (seen(b) ? b : null)));
const near = (p) => ([11, 13, 15, 23, 25, 27].filter((i) => seen(p.at(i))).length >= [12, 14, 16, 24, 26, 28].filter((i) => seen(p.at(i))).length ? 0 : 1);

function tiltOf(sh, hip) {
  const dx = sh.x - hip.x, dy = sh.y - hip.y, n = Math.hypot(dx, dy);
  return n ? Math.acos(Math.min(1, Math.max(-1, -dy / n))) * 180 / Math.PI : NaN;
}
function sagOf(sh, hip, an) { // degrees the body line bends at the hip: + the hips below the shoulder-ankle line
  const a = angle(sh, hip, an);
  if (!Number.isFinite(a)) return NaN;
  const lineY = sh.y + (an.y - sh.y) * ((hip.x - sh.x) / ((an.x - sh.x) || 1e-9));
  return (hip.y > lineY ? 1 : -1) * (180 - a);
}

function look(p) { // which way he is seen, and this frame's numbers
  const sh = mid(p[11], p[12]), hip = mid(p[23], p[24]);
  if (!sh || !hip || !seen(p[11]) || !seen(p[12])) return null;
  const span = Math.abs(p[11].x - p[12].x), torso = dist(sh, hip), wr = mid(p[15], p[16]);
  const k = near(p), S = k ? { sh: 12, el: 14, wr: 16, hip: 24, kn: 26, an: 28 } : { sh: 11, el: 13, wr: 15, hip: 23, kn: 25, an: 27 };
  const front = torso > 0 && span / torso > 0.3;
  if (front && wr && wr.y > sh.y && span > 1.2 * torso) { // a push-up seen from his head: shoulders over the hands
    const v = 100 * (wr.y - sh.y) / span;
    return { mode: 'push-front', v, flare: Math.abs(p[13].x - p[14].x) / span };
  }
  const tilt = tiltOf(sh, hip), level = seen(p.at(S.an)) && Math.abs(p.at(S.an).y - hip.y) < 0.5 * torso; // legs out behind
  if (!front && tilt > 55 && level) return { mode: 'push-side', v: angle(p.at(S.sh), p.at(S.el), p.at(S.wr)), sag: sagOf(p.at(S.sh), p.at(S.hip), p.at(S.an)) };
  if (front) {
    const kn = mid(p[25], p[26]), ankles = Math.abs(p[27].x - p[28].x), knees = Math.abs(p[25].x - p[26].x);
    return kn ? { mode: 'squat-front', v: 100 * (kn.y - hip.y) / torso, kneesIn: ankles ? knees / ankles : 1 } : null;
  }
  return { mode: 'squat-side', v: angle(p.at(S.hip), p.at(S.kn), p.at(S.an)), tilt };
}

function judge(mode, w) { // the rep's one fault ('' clean), from its extremes
  const found = {
    depth: (mode === 'squat-side' && w.low > 105) || (mode === 'push-side' && w.low > 110),
    knees_in: mode === 'squat-front' && w.kneesIn < 0.8,
    back: mode === 'squat-side' && w.tilt > 55,
    hips: mode === 'push-side' && w.sag > 15,
    elbows: mode === 'push-front' && w.flare > 2.2,
  };
  return ORDER.find((f) => get(found, f)) || '';
}

function begin(t, at) { return { began: at, at, t, mode: '', phase: 'up', w: null, reps: 0, clean: 0, tips: 0, log: [], last: null, ex: '' }; }

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = Object.assign({}, state || begin(t, at), { t, at: Math.max((state && state.at) || at, at) });
  const f = look(p);
  if (!f || !Number.isFinite(f.v)) return s;
  const m = get(MODES, f.mode);
  if (s.phase === 'up' && f.v < m.down) { // a rep begins: its extremes are watched until it ends
    return Object.assign({}, s, { phase: 'down', mode: f.mode, w: { low: f.v, tilt: f.tilt || 0, sag: f.sag || 0, kneesIn: f.kneesIn || 9, flare: f.flare || 0, lowV: f.v } });
  }
  if (s.phase !== 'down' || f.mode !== s.mode) return s;
  const w = s.w, lower = f.v < w.lowV;
  const nw = { low: Math.min(w.low, f.v), lowV: Math.min(w.lowV, f.v), tilt: Math.max(w.tilt, f.tilt || 0), sag: Math.max(w.sag, f.sag || 0),
    kneesIn: lower && f.kneesIn !== undefined ? f.kneesIn : w.kneesIn, flare: lower && f.flare !== undefined ? f.flare : w.flare };
  if (f.v <= m.up) return Object.assign({}, s, { w: nw });
  const fault = judge(s.mode, nw), ex = m.exercise;
  return Object.assign({}, s, { phase: 'up', w: null, reps: s.reps + 1, clean: s.clean + (fault ? 0 : 1), tips: s.tips + (fault ? 1 : 0),
    log: s.log.concat([fault]).slice(-500), last: { fault, ex, t }, ex });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[12] }, rule = { kind: 'line', text: WORDS[11] };
  if (!s || !s.reps) return { view: [{ kind: 'line', text: WORDS[13] }, rule, hurts], tally: null };
  const view = [{ kind: 'big', n: s.reps, word: WORDS[7] }];
  const fresh = s.last && s.t - s.last.t <= TIP_S;
  if (fresh && s.last.fault) view.push({ kind: 'tip', text: get(get(TIPS, s.last.ex), s.last.fault) });
  else if (fresh) view.push({ kind: 'line', text: WORDS[6] });
  view.push({ kind: 'line', text: `${s.clean} ${WORDS[8]} of ${s.reps} ${s.ex === 'push_up' ? WORDS[10] : WORDS[9]}` }, rule, hurts);
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), exercise: s.ex || 'squat', reps: s.reps, clean: s.clean, tips: s.tips };
  return { view, tally };
}

JarvisVision.use({ id: 'form', tasks: ['pose'], onResult, summary });
