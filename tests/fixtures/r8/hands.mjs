// tests/fixtures/r8/hands.mjs -- R8 I0 seam S23 (docs/plans/r8-vision.md v8.0.3 section 8): synthetic hands, the engine's
// `hands` data (MediaPipe's 21 points: the wrist, then four per finger, thumb first). Never a real person's data.
//   hand({side, open, cx, cy, size, noise, seed}) -> {side, score, points: 21 x {x, y, z}}   open 0 (a fist) .. 1 (open)
//   tap(finger, amount)  the hand with one fingertip bent towards the thumb (0 none .. 1 touching): finger 1..4
//   hands(list) -> the task's data {hands: [...]} (at most 2)
const FINGER_ANGLES = [-60, -25, -5, 15, 35]; // thumb, index, middle, ring, little: degrees from straight up
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1103515245 + 12345) >>> 0; return s / 4294967296; }; }

export function hand(opts) {
  const o = Object.assign({ side: 'right', open: 1, cx: 0.5, cy: 0.6, size: 0.18, noise: 0, seed: 3, bend: [0, 0, 0, 0, 0] }, opts || {});
  const r = rng(o.seed), n = () => (r() - 0.5) * 2 * o.noise, flip = o.side === 'left' ? -1 : 1;
  const pts = [{ x: o.cx + n(), y: o.cy + n(), z: 0 }];
  FINGER_ANGLES.forEach((deg, f) => {
    const curl = Math.min(1, (1 - o.open) + (o.bend[f] || 0));
    for (let j = 1; j <= 4; j += 1) {
      const reach = o.size * (j / 4) * (1 - 0.6 * curl), a = (flip * deg + curl * 40 * j) * Math.PI / 180;
      pts.push({ x: o.cx + reach * Math.sin(a) + n(), y: o.cy - reach * Math.cos(a) + n(), z: -0.01 * j });
    }
  });
  return { side: o.side, score: 0.95, points: pts };
}

export function tap(finger, amount, opts) {
  const bend = [0, 0, 0, 0, 0];
  bend[Math.max(1, Math.min(4, finger))] = Math.max(0, Math.min(1, amount));
  return hand(Object.assign({}, opts || {}, { bend }));
}

export function hands(list) { return { hands: (list || []).slice(0, 2) }; }
