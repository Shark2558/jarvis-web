// src/jarvis/api/static/console-coach-jump.js -- R8.1 builder G, row 235 (HF-06, jump height and landing mechanics;
// docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `jump`: `pose` at up to 15 a second (30 only once the setup
// test shows the phone keeps it: D4), one body's state at a time (D6). He faces the phone, whole body and feet in view.
// Height comes from the flight time alone (h = g T^2 / 8), so it needs no scale: the LOWER foot leaves the floor and
// meets it again (one foot lifted is not a jump). The airborne frames' foot heights are fitted with a parabola whose
// two floor crossings are takeoff and landing, so the time does not depend on where the frames fell; with too few
// airborne frames the crossings are interpolated between frames and corrected for the air threshold. Under 25 frames
// a second the heights are marked "about" (risk 3). The landing is the half second after it: stiff when the hips
// sink less than 8 % of leg length, knees-in when the knees come closer together than 75 % of the feet's width.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports only the shared
// geometry. Tally: jarvis.coach.usecases' JumpTally (jumps, best_cm, stiff, knees_in, about, the session's start and
// end). View: big {n, word}, line, tip.
import { ema } from './console-coach-geom.js';

const G = 9.81;
const SEEN = 0.5;
const AIR = 0.04; // airborne: the lower foot this share of leg length above the floor
const FLIGHT_MIN_S = 0.12;
const FLIGHT_MAX_S = 1.2;
const LAND_S = 0.5; // the landing that is judged
const STIFF_DROP = 0.08; // the hips sink less than this share of leg length: stiff
const KNEES_IN = 0.75; // the knees closer than this share of the feet's width: knees in
const FAST_FPS = 25; // under this, a height is "about"
const GAPS_MAX = 15;
const WORDS = Object.freeze([
  'Face the phone with your whole body and feet in view, then jump.', 'cm', 'cm, about',
  'Land softly: bend your knees as you land.', 'Keep your knees over your toes as you land.', 'Stop if anything hurts.',
  'Heights are about right at this frame rate.', 'Good landing.',
]);

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);
const pointsOf = (r) => (r && r.ok && r.task === 'pose' && r.data && Array.isArray(r.data.points) && r.data.points.length === 33 ? r.data.points : null);
const mid = (a, b) => (seen(a) && seen(b) ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (seen(a) ? a : (seen(b) ? b : null)));
const lowest = (ps) => { const ys = ps.filter(seen).map((q) => q.y); return ys.length ? Math.max(...ys) : NaN; };
const median = (vs) => (vs.length ? [...vs].sort((a, b) => a - b).at(Math.floor(vs.length / 2)) : 0);
const fpsOf = (s) => { const m = median(s.gaps); return m > 0 ? 1 / m : 0; };
const round1 = (v) => Math.round(v * 10) / 10;

function body(p) { // the lower foot, the hips, the knees' and feet's widths, the leg length
  const left = lowest([p[27], p[29], p[31]]), right = lowest([p[28], p[30], p[32]]);
  const foot = Number.isFinite(left) && Number.isFinite(right) ? Math.max(left, right) : (Number.isFinite(left) ? left : right);
  const hip = mid(p[23], p[24]), ankle = mid(p[27], p[28]);
  const leg = hip && ankle ? Math.hypot(hip.x - ankle.x, hip.y - ankle.y) : NaN;
  const knees = seen(p[25]) && seen(p[26]) ? Math.abs(p[25].x - p[26].x) : NaN;
  const feet = seen(p[27]) && seen(p[28]) ? Math.abs(p[27].x - p[28].x) : NaN;
  return { foot, hip: hip ? hip.y : NaN, leg, knees, feet };
}

function begin(t, at, b) {
  return { began: at, at, t, gaps: [], leg: b.leg, floor: b.foot, phase: 'ground', prev: null, air: [],
    land: null, jumps: 0, best: 0, last: 0, lastAbout: false, stiff: 0, kneesIn: 0, about: false, verdict: '' };
}

function fit(air) { // least squares h = a t^2 + b t + c over the airborne frames; its two floor crossings, or null
  if (air.length < 3) return null;
  const t0 = air[0].t;
  const m = air.reduce((o, f) => { const u = f.t - t0, u2 = u * u; return { n: o.n + 1, s1: o.s1 + u, s2: o.s2 + u2,
    s3: o.s3 + u2 * u, s4: o.s4 + u2 * u2, y0: o.y0 + f.h, y1: o.y1 + u * f.h, y2: o.y2 + u2 * f.h }; },
  { n: 0, s1: 0, s2: 0, s3: 0, s4: 0, y0: 0, y1: 0, y2: 0 });
  const det3 = (a, b, c, d, e, f, g, h, i) => a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  const D = det3(m.s4, m.s3, m.s2, m.s3, m.s2, m.s1, m.s2, m.s1, m.n);
  if (!D) return null;
  const a = det3(m.y2, m.s3, m.s2, m.y1, m.s2, m.s1, m.y0, m.s1, m.n) / D;
  const b = det3(m.s4, m.y2, m.s2, m.s3, m.y1, m.s1, m.s2, m.y0, m.n) / D;
  const c = det3(m.s4, m.s3, m.y2, m.s3, m.s2, m.y1, m.s2, m.s1, m.y0) / D;
  const disc = b * b - 4 * a * c;
  if (!(a < 0) || !(disc > 0)) return null;
  const r1 = (-b + Math.sqrt(disc)) / (2 * a), r2 = (-b - Math.sqrt(disc)) / (2 * a);
  return { up: t0 + Math.min(r1, r2), down: t0 + Math.max(r1, r2) };
}

function flight(s, landing) { // seconds in the air: the fit, else the corrected interpolation
  const air = s.air, first = air[0], last = air.at(-1), before = s.liftFrom;
  const up = before && first.h > before.h ? before.t + (first.t - before.t) * (AIR - before.h) / (first.h - before.h) : first.t;
  const down = last.h > landing.h ? last.t + (landing.t - last.t) * (last.h - AIR) / (last.h - landing.h) : landing.t;
  const apex = Math.max(...air.map((f) => f.h));
  const rough = (down - up) / Math.sqrt(Math.max(0.05, 1 - AIR / apex));
  const fitted = fit(air);
  const exact = fitted ? fitted.down - fitted.up : NaN;
  return Number.isFinite(exact) && Math.abs(exact - rough) < 0.1 ? exact : rough;
}

function judge(s) { // the landing's half second is over: stiff, knees in, or good
  const l = s.land;
  const stiff = !(l.sink >= STIFF_DROP), knees = l.ratio < KNEES_IN;
  const verdict = stiff ? WORDS[3] : (knees ? WORDS[4] : WORDS[7]);
  return Object.assign({}, s, { land: null, stiff: s.stiff + (stiff ? 1 : 0), kneesIn: s.kneesIn + (knees ? 1 : 0), verdict });
}

function onResult(r, state) {
  const p = pointsOf(r);
  if (!p) return state;
  const b = body(p);
  if (!Number.isFinite(b.foot) || !Number.isFinite(b.leg) || !(b.leg > 0)) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  let s = state && state.phase ? state : begin(t, at, b);
  const gap = t - s.t, gaps = gap > 0 ? s.gaps.concat([gap]).slice(-GAPS_MAX) : s.gaps;
  s = Object.assign({}, s, { t, at: Math.max(s.at, at), gaps });
  const h = (s.floor - b.foot) / s.leg, frame = { t, h };
  if (s.land) { // the landing's half second
    const l = s.land;
    const sink = Number.isFinite(b.hip) ? Math.max(l.sink, (b.hip - l.hip) / s.leg) : l.sink;
    const ratio = b.feet > 0.1 * s.leg && Number.isFinite(b.knees) ? Math.min(l.ratio, b.knees / b.feet) : l.ratio;
    s = Object.assign({}, s, { land: Object.assign({}, l, { sink, ratio }) });
    if (t - l.t >= LAND_S) s = judge(s);
  }
  if (s.phase === 'ground') {
    if (h > AIR) return Object.assign({}, s.land ? judge(s) : s, { phase: 'air', air: [frame], liftFrom: s.prev }); // a rebound
    const near = Math.abs(h) < AIR / 2;
    return Object.assign({}, s, { prev: frame, floor: near ? ema(s.floor, b.foot, 0.2) : s.floor,
      leg: s.land || !Number.isFinite(b.leg) ? s.leg : Math.max(s.leg * 0.999, b.leg) });
  }
  if (h > AIR) return Object.assign({}, s, { air: s.air.concat([frame]).slice(-90) });
  const T = flight(s, frame);
  const back = Object.assign({}, s, { phase: 'ground', air: [], prev: frame });
  if (!(T >= FLIGHT_MIN_S && T <= FLIGHT_MAX_S)) return back;
  const cm = Math.min(200, Math.max(0, 100 * G * T * T / 8)), about = fpsOf(s) < FAST_FPS;
  return Object.assign({}, back, { jumps: s.jumps + 1, best: Math.max(s.best, cm), last: cm, lastAbout: about,
    about: s.about || about, verdict: '', land: { t, hip: b.hip, sink: 0, ratio: Infinity } });
}

function summary(s) {
  const hurts = { kind: 'line', text: WORDS[5] };
  if (!s || !s.jumps) return { view: [{ kind: 'big', n: 0, word: WORDS[1] }, { kind: 'line', text: WORDS[0] }, hurts], tally: null };
  const view = [{ kind: 'big', n: Math.round(s.last), word: s.lastAbout ? WORDS[2] : WORDS[1] },
    { kind: 'line', text: `Best ${Math.round(s.best)} cm from ${s.jumps} ${s.jumps === 1 ? 'jump' : 'jumps'}.` }];
  if (s.verdict) view.push(s.verdict === WORDS[7] ? { kind: 'line', text: s.verdict } : { kind: 'tip', text: s.verdict });
  if (s.lastAbout) view.push({ kind: 'line', text: WORDS[6] });
  view.push(hurts);
  const tally = { started_at: s.began, ended_at: Math.max(s.began, s.at), jumps: s.jumps, best_cm: round1(s.best),
    stiff: s.stiff, knees_in: s.kneesIn, about: s.about };
  return { view, tally };
}

JarvisVision.use({ id: 'jump', tasks: ['pose'], onResult, summary });
