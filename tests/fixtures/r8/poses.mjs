// tests/fixtures/r8/poses.mjs -- R8 I0 seam S23 (docs/plans/r8-vision.md v8.0.3 section 8): synthetic bodies for the
// coaches' tests and evals. Never a real person's data. A body is the engine's 33 MediaPipe pose points (0..1 of the
// frame, z relative, visibility 0..1), built from a few joint angles so a test can script an exercise:
//   body({hip, knee, elbow, shoulder, torso, neck}, {cx, cy, scale, noise, seed, visibility}) -> 33 points
//   sequence(fn, {seconds, fps, ...}) -> [{t, points}]  fn(t) gives the angles at time t (seconds)
//   pose(bodies, {track}) -> the pose v2 data {bodies: [{track, who: '', points}]}  (the owner's D6: everyone in view)
//   drop(seq, every)      every n-th frame missing (points [])     tilt(points, deg)   the camera tilted
//   child(points)         a child-sized body (scaled about the hips)  second(points, dx)  another body beside it
// Angles in degrees: 180 is straight. Builders add their own exercise scripts in their own fixture files beside this.
const RAD = Math.PI / 180;
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const at = (o, len, deg) => ({ x: o.x + len * Math.sin(deg * RAD), y: o.y + len * Math.cos(deg * RAD) });

export function body(angles, opts) {
  const a = Object.assign({ hip: 180, knee: 180, elbow: 180, shoulder: 10, torso: 0, neck: 0 }, angles || {});
  const o = Object.assign({ cx: 0.5, cy: 0.55, scale: 0.35, noise: 0, seed: 7, visibility: 0.95 }, opts || {});
  const r = rng(o.seed), n = () => (r() - 0.5) * 2 * o.noise, k = o.scale;
  const hip = { x: o.cx, y: o.cy };
  const torsoUp = 180 + a.torso; // the torso leans forward by `torso` degrees
  const shoulder = at(hip, 0.5 * k, torsoUp);
  const head = at(shoulder, 0.18 * k, torsoUp + a.neck);
  const thigh = 180 - a.hip + a.torso; // hip flexion bends the thigh forward
  const knee = at(hip, 0.45 * k, thigh);
  const ankle = at(knee, 0.45 * k, thigh + (180 - a.knee));
  const elbow = at(shoulder, 0.3 * k, a.shoulder);
  const wrist = at(elbow, 0.28 * k, a.shoulder + (180 - a.elbow));
  const pts = new Array(33).fill(null).map(() => ({ x: head.x, y: head.y }));
  const set = (ids, p) => ids.forEach((i) => { pts[i] = { x: p.x, y: p.y }; });
  set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], head); set([11, 12], shoulder); set([13, 14], elbow); set([15, 16, 17, 18, 19, 20, 21, 22], wrist);
  set([23, 24], hip); set([25, 26], knee); set([27, 28, 29, 30, 31, 32], ankle);
  return pts.map((p) => ({ x: p.x + n(), y: p.y + n(), z: 0, visibility: o.visibility }));
}

export function sequence(fn, opts) {
  const o = Object.assign({ seconds: 10, fps: 15 }, opts || {});
  const out = [];
  for (let i = 0; i <= Math.round(o.seconds * o.fps); i += 1) { const t = i / o.fps; out.push({ t, points: body(fn(t), Object.assign({}, o, { seed: (o.seed || 7) + i })) }); }
  return out;
}

export function pose(bodies) { return { bodies: bodies.map((points, track) => ({ track, who: '', points })) }; }
export function drop(seq, every) { return seq.map((f, i) => (every && i % every === every - 1 ? { t: f.t, points: [] } : f)); }
export function tilt(points, deg) {
  const c = Math.cos(deg * RAD), s = Math.sin(deg * RAD);
  return points.map((p) => ({ ...p, x: 0.5 + (p.x - 0.5) * c - (p.y - 0.5) * s, y: 0.5 + (p.x - 0.5) * s + (p.y - 0.5) * c }));
}
export function child(points) { const h = points[23]; return points.map((p) => ({ ...p, x: h.x + (p.x - h.x) * 0.6, y: h.y + (p.y - h.y) * 0.6 })); }
export function second(points, dx) { return points.map((p) => ({ ...p, x: p.x + dx })); }
