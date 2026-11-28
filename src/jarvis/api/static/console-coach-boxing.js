// src/jarvis/api/static/console-coach-boxing.js -- R8.1 builder G, row 228 (HF-08, the shadowboxing punch and
// combination tracker; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `boxing`: `pose` at up to 15 a second
// (30 only once the setup test shows the phone keeps it: D4), one body's state at a time (D6). He faces the phone in
// his stance, hands up. Each wrist has a guard (where it rests, learnt while it is near it); a punch is the wrist
// leaving its guard by more than 35 % of the torso's length and coming back inside 20 %, within 1.2 s. Its type is read
// from the whole movement: straight (the elbow opens past 150 degrees and the wrist goes mostly forward) is a jab from
// the lead hand and a cross from the rear; otherwise an uppercut when the wrist first drops well below its guard, else
// a hook (it swings out to the side). The lead side is the shoulder nearer the camera (z); level shoulders fall back
// to the pane's setup (`stance`), else orthodox. Punches less than 0.6 s apart are one combination. Under 25 frames a
// second the counts stand but the types are marked "about" (risk 3).
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' BoxingTally (punches, jabs, crosses, hooks, uppercuts, about, the session's
// start and end). View: big {n, word}, line.
import { ema } from './console-coach-geom.js';

const SEEN = 0.5;
const OUT = 0.35; // the wrist this far from its guard (a share of the torso) is punching
const BACK = 0.2; // ... and this near again ends the punch
const STRAIGHT_DEG = 150;
const LOW = 0.35; // an uppercut's dip below the guard
const LONG_S = 1.2; // out longer than this is not a punch (the hands came down)
const COMBO_S = 0.6;
const GUARD_K = 0.1;
const LEAD_K = 0.05;
const FAST_FPS = 25;
const GAPS_MAX = 15;
const COMBO_MAX = 6;
const ARMS = Object.freeze([Object.freeze({ sh: 11, el: 13, wr: 15 }), Object.freeze({ sh: 12, el: 14, wr: 16 })]);
const TYPES = Object.freeze(['jab', 'cross', 'hook', 'uppercut']);
const WORDS = Object.freeze([
  'Face the phone in your stance, hands up, then throw.', 'punches', 'Stop if anything hurts.',
  'Punch types are about right at this frame rate.', 'Last combination: ',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const z = (p) => (Number.isFinite(p.z) ? p.z : 0);
const d3 = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, z(a) - z(b));
const median = (vs) => (vs.length ? [...vs].sort((a, b) => a - b).at(Math.floor(vs.length / 2)) : 0);
const fpsOf = (s) => { const m = median(s.gaps); return m > 0 ? 1 / m : 0; };
function elbow3(sh, el, wr) { // the elbow's angle in three dimensions, degrees
  const u = [sh.x - el.x, sh.y - el.y, z(sh) - z(el)], v = [wr.x - el.x, wr.y - el.y, z(wr) - z(el)];
  const nu = Math.hypot(...u), nv = Math.hypot(...v);
  if (!nu || !nv) return NaN;
  return Math.acos(Math.min(1, Math.max(-1, (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (nu * nv)))) * 180 / Math.PI;
}
const torsoOf = (p) => (seen(p[11]) && seen(p[12]) && seen(p[23]) && seen(p[24])
  ? Math.hypot((p[11].x + p[12].x - p[23].x - p[24].x) / 2, (p[11].y + p[12].y - p[23].y - p[24].y) / 2) : NaN);
const setupOf = (r) => (r && r.setup && typeof r.setup === 'object' ? r.setup : {}); // the pane's stance, on each Result

function begin(t, at, setup) {
  const arm = () => ({ guard: null, out: null, endAt: -1 });
  return { began: at, at, t, gaps: [], torso: NaN, lead: 0, stance: setup.stance === 'southpaw' ? 1 : 0, arms: [arm(), arm()],
    punches: 0, jabs: 0, crosses: 0, hooks: 0, uppercuts: 0, about: false, combo: [], lastEnd: -9, lastAbout: false };
}

function kind(w, isLead) { // a finished punch's type, from its whole movement
  if (w.elbow >= STRAIGHT_DEG && w.fwd >= w.side && w.fwd >= w.low) return isLead ? 'jab' : 'cross';
  return w.low >= LOW && w.low >= w.side ? 'uppercut' : 'hook';
}

function step(a, k, p, t, torso) { // one arm's frame: -> {arm, done: the finished punch's window or null}
  const ix = ARMS.at(k), sh = p.at(ix.sh), el = p.at(ix.el), wr = p.at(ix.wr);
  if (!seen(sh) || !seen(el) || !seen(wr)) return { arm: a, done: null };
  const g = a.guard || { x: wr.x, y: wr.y, z: z(wr) };
  const d = d3(wr, g) / torso;
  if (!a.out) {
    if (d > OUT) return { arm: Object.assign({}, a, { guard: g, out: { from: t, elbow: elbow3(sh, el, wr), fwd: (g.z - z(wr)) / torso,
      side: Math.abs(wr.x - g.x) / torso, low: (wr.y - g.y) / torso, peak: d } }), done: null };
    const near = d < BACK ? { x: ema(g.x, wr.x, GUARD_K), y: ema(g.y, wr.y, GUARD_K), z: ema(g.z, z(wr), GUARD_K) } : g;
    return { arm: Object.assign({}, a, { guard: near }), done: null };
  }
  const o = a.out;
  if (t - o.from > LONG_S) return { arm: Object.assign({}, a, { out: null, guard: { x: wr.x, y: wr.y, z: z(wr) } }), done: null };
  const w = { from: o.from, elbow: Math.max(o.elbow, elbow3(sh, el, wr) || 0), fwd: Math.max(o.fwd, (g.z - z(wr)) / torso),
    side: Math.max(o.side, Math.abs(wr.x - g.x) / torso), low: Math.max(o.low, (wr.y - g.y) / torso), peak: Math.max(o.peak, d) };
  if (d < BACK) return { arm: Object.assign({}, a, { out: null, endAt: t }), done: w };
  return { arm: Object.assign({}, a, { out: w }), done: null };
}

function counted(s, type, from, t, about) {
  const combo = from - s.lastEnd <= COMBO_S ? s.combo.concat([type]).slice(-COMBO_MAX) : [type];
  return Object.assign({}, s, { punches: s.punches + 1, combo, lastEnd: t, lastAbout: about, about: s.about || about,
    jabs: s.jabs + (type === 'jab' ? 1 : 0), crosses: s.crosses + (type === 'cross' ? 1 : 0),
    hooks: s.hooks + (type === 'hook' ? 1 : 0), uppercuts: s.uppercuts + (type === 'uppercut' ? 1 : 0) });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0, tor = torsoOf(p);
  let s = state && state.arms ? state : begin(t, at, setupOf(r));
  const gap = t - s.t, gaps = gap > 0 ? s.gaps.concat([gap]).slice(-GAPS_MAX) : s.gaps;
  const torso = Number.isFinite(tor) && tor > 0 ? ema(s.torso, tor, 0.1) : s.torso;
  s = Object.assign({}, s, { t, at: Math.max(s.at, at), gaps, torso });
  if (!(torso > 0)) return s;
  const quiet = !s.arms[0].out && !s.arms[1].out && seen(p[11]) && seen(p[12]);
  const lead = quiet ? ema(s.lead, (z(p[11]) - z(p[12])) / torso, LEAD_K) : s.lead;
  const steps = s.arms.map((a, k) => step(a, k, p, t, torso));
  s = Object.assign({}, s, { lead, arms: steps.map((x) => x.arm) });
  const leadArm = Math.abs(lead) > 0.02 ? (lead < 0 ? 0 : 1) : s.stance; // 0 left (orthodox), 1 right
  const about = fpsOf(s) < FAST_FPS;
  steps.forEach((x, k) => { if (x.done) s = counted(s, kind(x.done, k === leadArm), x.done.from, t, about); });
  return s;
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[2] };
  if (!s || !s.punches) return { view: [{ kind: 'big', n: 0, word: WORDS[1] }, { kind: 'line', text: WORDS[0] }, hurts], tally: null };
  const counts = TYPES.map((n) => `${n} ${n === 'jab' ? s.jabs : n === 'cross' ? s.crosses : n === 'hook' ? s.hooks : s.uppercuts}`);
  const view = [{ kind: 'big', n: s.punches, word: WORDS[1] },
    { kind: 'line', text: `${counts.join(', ')}.`.replace(/^j/, 'J') },
    { kind: 'line', text: `${WORDS[4]}${s.combo.join(', ')}.` }];
  if (s.lastAbout) view.push({ kind: 'line', text: WORDS[3] });
  view.push(hurts);
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), punches: s.punches, jabs: s.jabs,
    crosses: s.crosses, hooks: s.hooks, uppercuts: s.uppercuts, about: s.about };
  return { view, tally };
}

JarvisVision.use({ id: 'boxing', tasks: ['pose'], onResult, summary });
