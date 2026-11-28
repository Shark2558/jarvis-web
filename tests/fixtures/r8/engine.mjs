// tests/fixtures/r8/engine.mjs -- R8 builder A (docs/plans/r8-vision.md 2.1 row 216, 4.2, D4, D7, D9): the engine's
// tests in Node. Never a real person's data, never a real model.
//   - a fake browser (window, document with canvases that really hold pixels, ImageData, fetch serving FAKE model files
//     from /static/vendor/vision/<release>/, and a switch that takes the network away: "the Wi-Fi off")
//   - a fake MediaPipe (PoseLandmarker and HandLandmarker whose answers are scripted from poses.mjs and hands.mjs)
//   - Node module hooks: console-vision.js's `import('./console-vision-r8.js')` gets the real file with SUMS8 filled
//     with the fake files' sums, and the MediaPipe bundle's address gets the fake
//   - display(values, opts): a synthetic seven-segment display (an LCD or LED blood-pressure monitor), drawn from
//     segment polygons, supersampled, slanted, turned, blurred, shaded, noisy, with ghost segments, labels and a bezel
//   - scenarios (each returns plain JSON): loads, poseFrames, handsFrames, repsOffline, setupTest, digitsFrame, accuracy
// Run through tests/r8_fakes.py run_node(FIXTURES / "engine.mjs", "mod.<scenario>", input). ASCII only.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import * as poses from './poses.mjs';
import * as handsFx from './hands.mjs';
import { angle, reps } from '../../../src/jarvis/api/static/console-coach-geom.js';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const R8_SOURCE = readFileSync(new URL('console-vision-r8.js', STATIC), 'utf8');
const SUMS = /\/\*SUMS8-BEGIN\*\/[\s\S]*?\/\*SUMS8-END\*\//;
export const MODELS = Object.freeze({
  'r7-1/pose_landmarker_lite.task': 'FAKE pose lite model',
  'r8-1/pose_landmarker_full.task': 'FAKE pose full model',
  'r8-1/hand_landmarker.task': 'FAKE hand model',
});
const sha = (s) => createHash('sha256').update(Buffer.from(s)).digest('hex');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
function busy(ms) { const end = performance.now() + ms; while (performance.now() < end) { /* a slow device */ } }
function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

// ---- the hooks: the patched task module and the fake MediaPipe bundle --------------------------------------------------
const HOOK = { r8: '', hooked: false };
function hook(sums) {
  if (!SUMS.test(R8_SOURCE)) throw new Error('console-vision-r8.js has no SUMS8 block');
  HOOK.r8 = R8_SOURCE.replace(SUMS, '/*SUMS8-BEGIN*/' + JSON.stringify(sums) + '/*SUMS8-END*/');
  if (HOOK.hooked) return;
  HOOK.hooked = true;
  registerHooks({
    resolve(spec, ctx, next) {
      if (spec === '/static/vendor/vision/r7-1/vision_bundle.mjs') return { url: 'r8fake:mediapipe', shortCircuit: true };
      if (spec === './console-vision-r8.js') return { url: 'r8fake:r8', shortCircuit: true };
      return next(spec, ctx);
    },
    load(url, ctx, next) {
      if (url === 'r8fake:mediapipe') {
        return { format: 'module', shortCircuit: true, source: 'export const PoseLandmarker = globalThis.__mp.PoseLandmarker;\n'
          + 'export const HandLandmarker = globalThis.__mp.HandLandmarker;\nexport const ObjectDetector = globalThis.__mp.ObjectDetector;\n' };
      }
      if (url === 'r8fake:r8') return { format: 'module', shortCircuit: true, source: HOOK.r8 };
      return next(url, ctx);
    },
  });
}

// ---- a fake browser: canvases hold real pixels (nearest-neighbour drawing), fetch serves the fake files -------------
export class Img { constructor(w, h, px) { this.width = w; this.height = h; this.px = px || new Uint8ClampedArray(w * h * 4).fill(128); } }
function sizeOf(src) { return { w: src.videoWidth || src.width || 0, h: src.videoHeight || src.height || 0 }; }
function resample(src, w, h) {
  const s = sizeOf(src), out = new Uint8ClampedArray(w * h * 4);
  if (!src.px || !s.w || !s.h) return out.fill(128);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) {
    const sx = Math.min(s.w - 1, Math.floor(((x + 0.5) * s.w) / w)), sy = Math.min(s.h - 1, Math.floor(((y + 0.5) * s.h) / h));
    out.set(src.px.subarray((sy * s.w + sx) * 4, (sy * s.w + sx) * 4 + 4), (y * w + x) * 4);
  }
  return out;
}
function canvas(state) {
  const c = { width: 0, height: 0, px: null };
  const ctx = {
    drawImage(src, x, y, w, h) { c.px = resample(src, w === undefined ? c.width : w, h === undefined ? c.height : h); },
    getImageData(x, y, w, h) {
      const data = c.px && c.px.length === w * h * 4 ? new Uint8ClampedArray(c.px) : new Uint8ClampedArray(w * h * 4);
      if (state.canvas === 'blank') data.fill(0);
      return { width: w, height: h, data };
    },
    putImageData(img) { c.px = new Uint8ClampedArray(img.data); },
  };
  c.getContext = () => ctx;
  state.canvases += 1;
  return c;
}
function fakeMediaPipe(state) {
  const kind = (name) => ({
    async createFromOptions(files, opts) {
      const model = Buffer.from(opts.baseOptions.modelAssetBuffer).toString();
      const o = Object.assign({}, opts, { baseOptions: { delegate: opts.baseOptions.delegate } });
      state.created.push({ kind: name, model, opts: o, files });
      let i = 0;
      return {
        detectForVideo(img, ts) {
          state.stamps.push(ts); busy((state.slow && state.slow[model]) || 0);
          const f = state.script[name](i); i += 1; return f;
        },
        close() { state.closed.push(name); },
      };
    },
  });
  return { PoseLandmarker: kind('pose'), HandLandmarker: kind('hands'), ObjectDetector: kind('objects') };
}
async function boot(input) {
  const i = input || {};
  const state = { fetches: [], offline: false, created: [], closed: [], stamps: [], canvases: 0, canvas: i.canvas || '',
    files: Object.assign({}, MODELS, i.files || {}), slow: i.slow || {}, script: { pose: () => ({ landmarks: [] }), hands: () => ({ landmarks: [] }) } };
  Object.keys(i.files || {}).forEach((k) => { if (i.files[k] === null) delete state.files[k]; });
  hook(Object.assign(Object.fromEntries(Object.entries(MODELS).map(([k, v]) => [k, sha(v)])), i.sums || {}));
  globalThis.window = globalThis;
  globalThis.addEventListener = () => {};
  globalThis.document = { createElement: () => canvas(state), head: { append() {} } };
  if (i.canvas !== 'none') globalThis.ImageData = class { constructor(data, w, h) { this.data = data; this.width = w; this.height = h; } };
  globalThis.createImageBitmap = async () => new Img(8, 8);
  globalThis.fetch = async (url) => {
    state.fetches.push({ url: String(url), offline: state.offline });
    if (state.offline) throw new TypeError('Failed to fetch');
    const key = String(url).replace('/static/vendor/vision/', '');
    if (i.status) return { ok: false, status: i.status, arrayBuffer: async () => new ArrayBuffer(0) };
    if (!String(url).startsWith('/static/vendor/vision/') || !(key in state.files)) return { ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0) };
    const b = Buffer.from(state.files[key]);
    return { ok: true, status: 200, arrayBuffer: async () => b.buffer.slice(b.byteOffset, b.byteOffset + b.length) };
  };
  globalThis.__mp = fakeMediaPipe(state);
  await import(new URL('console-vision.js', STATIC).href);
  return { V: globalThis.JarvisVision, state };
}
const plainOf = (x) => JSON.parse(JSON.stringify(x));
async function attempt(fn) { try { return { ok: true, value: await fn() }; } catch (e) { return { ok: false, error: String(e && e.message) }; } }

// ---- scripted bodies and hands ------------------------------------------------------------------------------------------
const squat = (t) => ({ hip: 180 - 90 * (0.5 - 0.5 * Math.cos(2 * Math.PI * t)), knee: 180 - 100 * (0.5 - 0.5 * Math.cos(2 * Math.PI * t)) });
function bodiesScript(name, n) {
  const out = [];
  for (let f = 0; f < n; f += 1) {
    if (name === 'crossing') { // an adult walking right in front, a child walking left behind (smaller, higher)
      out.push([poses.body({}, { cx: 0.15 + 0.03 * f, cy: 0.6, scale: 0.4 }), poses.body({}, { cx: 0.85 - 0.03 * f, cy: 0.5, scale: 0.24 })]);
    } else if (name === 'leave-enter') { // one body throughout; a second leaves at frame 5; a new one enters at 30
      const one = [poses.body({}, { cx: 0.3 })];
      if (f < 5) one.push(poses.body({}, { cx: 0.7 }));
      if (f >= 30) one.push(poses.body({}, { cx: 0.72, scale: 0.3 }));
      out.push(one);
    } else if (name === 'five') { // five people in view: at most four are reported
      out.push([0.1, 0.3, 0.5, 0.7, 0.9].map((cx) => poses.body({}, { cx, scale: 0.15 })));
    } else if (name === 'wild') { // a landmarker answer outside the ranges and a short one
      const b = poses.body({}).map((p) => ({ ...p, x: p.x * 9, z: 40, visibility: 3 }));
      out.push([b, poses.body({}).slice(0, 20)]);
    } else out.push([poses.body(squat(f / 6), { noise: 0.002, seed: f })]); // squats, six frames a rep
  }
  return out;
}
const asLandmarks = (frame) => ({ landmarks: frame, worldLandmarks: [] });

/** Each R8 task once on a canvas (pose, hands, digits): what each said, the files fetched, the landmarkers made. */
export async function loads(input) {
  const { V, state } = await boot(input);
  const img = Object.assign(new Img(64, 48), {});
  const out = {};
  for (const id of ['pose', 'hands', 'digits']) {
    const r = await attempt(() => V.run(id, img));
    out[id] = r.ok ? { ran: true, ok: r.value.ok, task: r.value.task, v: r.value.v } : { ran: false, error: r.error };
  }
  return { out, fetches: state.fetches.map((f) => f.url), created: state.created.map((c) => ({ kind: c.kind, model: c.model, opts: c.opts, files: c.files })),
    tasks: plainOf(V.tasks()) };
}

/** Pose over a script ('squats', 'crossing', 'leave-enter', 'five', 'wild'): every Result, as the engine made it. */
export async function poseFrames(input) {
  const i = input || {}, { V, state } = await boot(i), script = bodiesScript(i.script || 'squats', i.frames || 12);
  state.script.pose = (k) => asLandmarks(script[Math.min(k, script.length - 1)]);
  const results = [];
  for (let k = 0; k < script.length; k += 1) results.push(plainOf(await V.run('pose', new Img(64, 48))));
  return { results, stamps: state.stamps, created: state.created.map((c) => c.opts) };
}

/** Hands over scripted answers: [{side ('Left' | 'Right' | other), score, points (n)}] per frame, opts.mirrored. */
export async function handsFrames(input) {
  const i = input || {}, { V, state } = await boot(i);
  const frames = i.frames || [[{ side: 'Left', score: 0.9 }]];
  state.script.hands = (k) => {
    const f = frames[Math.min(k, frames.length - 1)];
    return { landmarks: f.map((h, j) => handsFx.hand({ cx: 0.3 + 0.4 * j }).points.slice(0, h.points || 21)),
      handedness: f.map((h) => [{ categoryName: h.side, score: h.score, index: 0, displayName: '' }]) };
  };
  const results = [];
  for (let k = 0; k < frames.length; k += 1) results.push(plainOf(await V.run('hands', new Img(64, 48), { mirrored: !!i.mirrored })));
  return { results };
}

/** Row 216's own check: a rep count runs with the Wi-Fi off. The look loads its model, the network goes, ten squats
 *  are counted by a use case on the live driver; no request is made while the network is off. */
export async function repsOffline(input) {
  const i = input || {}, { V, state } = await boot(i), reps10 = i.reps || 10, script = bodiesScript('squats', reps10 * 6 + 2);
  state.script.pose = (k) => asLandmarks(script[Math.min(k, script.length - 1)]);
  const cam = new Img(64, 48);
  globalThis.JarvisCamera = { live: () => true, frame: () => cam, onChange: () => () => {} };
  let seen = 0, last = null;
  V.use({ id: 'reps-check', tasks: ['pose'], onResult: (r, s) => {
    seen += 1; const p = r.data.points || [];
    const knee = angle(p[23], p[25], p[27]);
    return Number.isFinite(knee) ? reps(s, knee, { down: 110, up: 160, t: seen / 15 }) : s;
  }, summary: (s) => { last = s; return { view: [{ kind: 'big', n: (s && s.count) || 0, word: 'reps' }], tally: { reps: (s && s.count) || 0 } }; } });
  await V.run('pose', cam); // the model is loaded while the network is on (served once, then cached by the browser)
  state.offline = !i.online;
  const before = state.fetches.length, errors = [];
  const look = V.live(['pose'], { uses: ['reps-check'], onError: (e) => errors.push(String(e && e.message)) });
  for (let k = 0; k < 400 && seen < script.length - 2 && !errors.length; k += 1) await wait(25);
  look.end();
  const t = V.tally('reps-check');
  return { count: t.tally && t.tally.reps, view: plainOf(t.view), who: t.who, seen, errors, fetched_offline: state.fetches.length - before, last: plainOf(last) };
}

/** The setup test on a fake camera: input {tasks, opts, slow: {model text: ms}, live: false}. */
export async function setupTest(input) {
  const i = input || {}, { state } = await boot(i);
  state.script.pose = () => asLandmarks([poses.body({})]);
  state.script.hands = () => ({ landmarks: [handsFx.hand({}).points], handedness: [[{ categoryName: 'Right', score: 0.9 }]] });
  const cam = new Img(64, 48), subs = new Set();
  globalThis.JarvisCamera = { live: () => i.live !== false, frame: () => cam, onChange: (fn) => { subs.add(fn); return () => subs.delete(fn); } };
  const check = await import(new URL('console-vision-check.js', STATIC).href);
  if (i.stopAfter) setTimeout(() => subs.forEach((fn) => fn({ live: false })), i.stopAfter);
  const r = await attempt(() => check.run(i.tasks || ['pose'], i.opts || {}));
  const after = [];
  if (i.choose) after.push(await check.choose(i.choose));
  return { result: r.ok ? plainOf(r.value) : null, error: r.ok ? '' : r.error, created: state.created.map((c) => c.model), after,
    sent: state.fetches.filter((f) => !f.url.startsWith('/static/vendor/vision/')).length };
}

// ---- synthetic seven-segment displays (D7) ------------------------------------------------------------------------------
const ON = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
const VARIANT = { 6: 'cdefg', 7: 'abcf', 9: 'abcfg' }; // some displays draw these without (or with) one segment
function segments(dw, dh, t, gp, style) { // each segment a convex polygon in the digit's own box
  const hx = (yc) => (style === 'rect' ? [[t + gp, yc - t / 2], [dw - t - gp, yc - t / 2], [dw - t - gp, yc + t / 2], [t + gp, yc + t / 2]]
    : [[t / 2 + gp, yc], [t + gp, yc - t / 2], [dw - t - gp, yc - t / 2], [dw - t / 2 - gp, yc], [dw - t - gp, yc + t / 2], [t + gp, yc + t / 2]]);
  const inset = style === 'rect' ? t : t / 2;
  const vx = (xc, y0, y1) => (style === 'rect' ? [[xc - t / 2, y0], [xc + t / 2, y0], [xc + t / 2, y1], [xc - t / 2, y1]]
    : [[xc, y0], [xc + t / 2, y0 + t / 2], [xc + t / 2, y1 - t / 2], [xc, y1], [xc - t / 2, y1 - t / 2], [xc - t / 2, y0 + t / 2]]);
  return { a: hx(t / 2), g: hx(dh / 2), d: hx(dh - t / 2), f: vx(t / 2, inset + gp, dh / 2 - gp / 2), b: vx(dw - t / 2, inset + gp, dh / 2 - gp / 2),
    e: vx(t / 2, dh / 2 + gp / 2, dh - inset - gp), c: vx(dw - t / 2, dh / 2 + gp / 2, dh - inset - gp) };
}
function inside(poly, x, y) { // a convex polygon, either winding
  let sign = 0;
  for (let i = 0; i < poly.length; i += 1) {
    const [x0, y0] = poly[i], [x1, y1] = poly[(i + 1) % poly.length], c = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0);
    if (c !== 0) { if (sign && Math.sign(c) !== sign) return false; sign = Math.sign(c); }
  }
  return true;
}
/** A synthetic display: values (3 lines, top to bottom) -> {w, h, px: RGBA, values}. Options (all optional): seed,
 *  dh (the top line's digit height, px), slant (0..0.25), thick (of the digit height), gap, style ('hex' | 'rect'),
 *  led, ghost (0..1 of the contrast), noise (grey levels), blur (px), shade (0..1), turn (degrees), bezel, labels,
 *  small (the bottom line's size), variants (6, 7, 9 drawn the other way). */
export function display(values, opts) {
  const o = Object.assign({ seed: 1, dh: 44, slant: 0.1, thick: 0.13, gap: 0.035, style: 'hex', led: false, ghost: 0, noise: 3, blur: 0,
    shade: 0, turn: 0, bezel: false, labels: true, small: 0.6, variants: false, aspect: 0.55, pitch: 1.3, spacing: 0.3, mid: 0.9 }, opts || {});
  const S = 3, sizes = [o.dh, o.dh * o.mid, o.dh * o.small], dw0 = o.dh * o.aspect;
  const turn = Math.abs(Math.sin((o.turn * Math.PI) / 180)), H0 = sizes.reduce((s, v) => s + v, 0) + o.dh * o.spacing * 2 + 30;
  const margin = Math.ceil(turn * H0 * 0.6); // turned, the corners must stay inside the picture too
  const W = Math.round(dw0 * o.pitch * 3 + o.dh * (1.8 + o.slant) + 24 + 2 * margin), H = Math.round(H0 + 2 * margin);
  const cov = new Float32Array(W * S * H * S), ghost = new Float32Array(W * S * H * S);
  const cx = W / 2, cy = H / 2, rad = (o.turn * Math.PI) / 180, cs = Math.cos(rad), sn = Math.sin(rad);
  const place = (x, y) => [cx + (x - cx) * cs - (y - cy) * sn, cy + (x - cx) * sn + (y - cy) * cs];
  const fillPoly = (poly, buf) => {
    const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
    for (let y = Math.max(0, Math.floor(Math.min(...ys) * S)); y < Math.min(H * S, Math.ceil(Math.max(...ys) * S)); y += 1) {
      for (let x = Math.max(0, Math.floor(Math.min(...xs) * S)); x < Math.min(W * S, Math.ceil(Math.max(...xs) * S)); x += 1) {
        if (inside(poly, (x + 0.5) / S, (y + 0.5) / S)) buf[y * W * S + x] = 1;
      }
    }
  };
  let top = 15 + margin;
  values.forEach((v, row) => {
    const dh = sizes[row], dw = dh * o.aspect, t = dh * o.thick, gp = Math.max(0.6, dh * o.gap), segs = segments(dw, dh, t, gp, o.style);
    const right = W - 12 - margin - o.slant * dh, digits = String(v); // the slant leans the tops right: they stay inside
    [...digits].forEach((ch, k) => {
      const x0 = right - (digits.length - k) * dw * o.pitch + (dw * o.pitch - dw), d = Number(ch);
      const lit = (o.variants && VARIANT[d]) || ON[d];
      Object.entries(segs).forEach(([name, poly]) => {
        const moved = poly.map(([x, y]) => place(x0 + x + o.slant * (dh - y), top + y));
        fillPoly(moved, lit.includes(name) ? cov : ghost);
      });
    });
    if (o.labels) { // "SYS" / "mmHg"-like marks, much smaller than the digits, on the left
      [[8, top + dh * 0.1], [8, top + dh * 0.55]].forEach(([lx, ly]) => {
        for (let q = 0; q < 3; q += 1) fillPoly([[lx + q * 7, ly], [lx + q * 7 + 5, ly], [lx + q * 7 + 5, ly + dh * 0.16], [lx + q * 7, ly + dh * 0.16]].map(([x, y]) => place(x, y)), cov);
      });
    }
    top += dh + o.dh * o.spacing;
  });
  const r = rng(o.seed), bg = o.led ? 22 : 190 + 30 * r(), fg = o.led ? 215 + 30 * r() : 35 + 20 * r();
  let img = new Float32Array(W * H);
  for (let y = 0; y < H; y += 1) for (let x = 0; x < W; x += 1) {
    let c = 0, g = 0;
    for (let j = 0; j < S; j += 1) for (let i = 0; i < S; i += 1) { c += cov[(y * S + j) * W * S + x * S + i]; g += ghost[(y * S + j) * W * S + x * S + i]; }
    c /= S * S; g = (g / (S * S)) * o.ghost;
    const v = bg + (fg - bg) * Math.min(1, c + g * (1 - c));
    const light = 1 - o.shade * (0.7 * (x / W) + 0.3 * (y / H));
    img[y * W + x] = o.bezel && (x < 6 || y < 6 || x >= W - 6 || y >= H - 6) ? 15 : v * light;
  }
  for (let pass = 0; pass < Math.round(o.blur); pass += 1) { // a box blur of radius 1, once per pass
    const next = new Float32Array(W * H);
    for (let y = 0; y < H; y += 1) for (let x = 0; x < W; x += 1) {
      let s = 0, n = 0;
      for (let dy = -1; dy <= 1; dy += 1) for (let dx = -1; dx <= 1; dx += 1) { const yy = y + dy, xx = x + dx; if (yy >= 0 && xx >= 0 && yy < H && xx < W) { s += img[yy * W + xx]; n += 1; } }
      next[y * W + x] = s / n;
    }
    img = next;
  }
  const px = new Uint8ClampedArray(W * H * 4);
  for (let k = 0; k < W * H; k += 1) {
    const v = img[k] + (r() - 0.5) * 2 * o.noise;
    px[k * 4] = v * 0.95; px[k * 4 + 1] = v; px[k * 4 + 2] = v * 0.9; px[k * 4 + 3] = 255;
  }
  return { w: W, h: H, px, values };
}
// The top line's digits at least DH_MIN pixels tall: the reading pane asks him to hold the monitor so its numbers fill
// the framing box (a webcam frame of 1280 x 720 with a 6 cm display at about 30 cm gives 40-60 px digits)
export const DH_MIN = 36;
/** The varied set: n displays from one seed, realistic readings and every kind of display above. */
export function displays(n, seed) {
  const r = rng(seed || 11), pick = (lo, hi) => lo + r() * (hi - lo), int = (lo, hi) => Math.floor(pick(lo, hi + 1));
  const out = [];
  for (let k = 0; k < n; k += 1) {
    const sys = int(92, 185), dia = Math.min(sys - 25, int(52, 112)), pulse = int(46, 125);
    out.push({ values: [sys, dia, pulse], opts: { seed: k + 1, dh: pick(DH_MIN, 64), slant: r() < 0.3 ? 0 : pick(0.04, 0.2), thick: pick(0.09, 0.16),
      gap: pick(0.02, 0.05), style: r() < 0.7 ? 'hex' : 'rect', led: r() < 0.1, ghost: r() < 0.4 ? pick(0.05, 0.25) : 0, noise: pick(0, 10),
      blur: r() < 0.4 ? 1 : 0, shade: pick(0, 0.35), turn: pick(-4, 4), bezel: r() < 0.4, labels: r() < 0.7, small: pick(0.5, 0.75),
      mid: pick(0.8, 1), variants: r() < 0.1, aspect: pick(0.5, 0.62), pitch: pick(1.2, 1.4), spacing: pick(0.2, 0.4) } });
  }
  return out;
}
const readRight = (lines, values) => lines.length === values.length && lines.every((l, i) => l.value === values[i] && l.score >= 0.8);
const sureWrong = (lines, values) => lines.length === values.length && lines.every((l) => l.score >= 0.8) && lines.some((l, i) => l.value !== values[i]);

/** The reader on n synthetic displays: {n, right, sure_wrong, misses: [the first few]}. `plain`: the default display
 *  only (an LCD, a little slant and noise); `mutate` is a negative control (a digit changed, every score made sure). */
export async function accuracy(input) {
  const i = input || {}, m = await import(new URL('console-vision-r8.js', STATIC).href);
  let right = 0, wrong = 0, ms = 0;
  const misses = [];
  const set = i.plain ? displays(i.n || 100, i.seed || 11).map((d) => ({ values: d.values, opts: { seed: d.opts.seed } })) : displays(i.n || 100, i.seed || 11);
  for (const d of set) {
    const pic = display(d.values, d.opts), g = m.grey(pic.px, pic.w, pic.h);
    const t0 = performance.now();
    let lines = m.readDisplay(g.px, g.w, g.h);
    ms += performance.now() - t0;
    if (i.mutate === 'last-digit') lines = lines.map((l) => ({ ...l, value: l.value - (l.value % 10) + ((l.value + 1) % 10) }));
    if (i.mutate === 'all-sure') lines = lines.map((l) => ({ ...l, score: 1 }));
    if (readRight(lines, d.values)) right += 1; else if (misses.length < 8) misses.push({ values: d.values, lines, opts: d.opts });
    if (sureWrong(lines, d.values)) wrong += 1;
  }
  return { n: i.n || 100, right, sure_wrong: wrong, ms_each: Math.round(ms / (i.n || 100)), misses };
}

/** `digits` through the engine on one synthetic display (opts.box: the part he framed), after the load's self-check. */
export async function digitsFrame(input) {
  const i = input || {}, { V, state } = await boot(i), pic = display(i.values || [128, 82, 71], i.opts || {});
  let frame = new Img(pic.w, pic.h, pic.px);
  if (i.frame) { // the display inside a bigger camera picture, at (fx, fy) of a fw x fh frame of grey 90
    const { fw, fh, fx, fy } = i.frame, px = new Uint8ClampedArray(fw * fh * 4).fill(90);
    for (let y = 0; y < pic.h; y += 1) px.set(pic.px.subarray(y * pic.w * 4, (y + 1) * pic.w * 4), ((fy + y) * fw + fx) * 4);
    frame = new Img(fw, fh, px);
  }
  const r = await attempt(() => V.run('digits', frame, i.box ? { box: i.box } : {}));
  return { result: r.ok ? plainOf(r.value) : null, error: r.ok ? '' : r.error, fetches: state.fetches.length, canvases: state.canvases };
}

/** D9's fallback: SSD-MobileNet v1's COCO ids as the engine's labels, and one decoded answer. */
export async function coco() {
  const m = await import(new URL('console-vision-r8.js', STATIC).href);
  const decoded = m.cocoObjects([47, 12, 44, 1, 90], [0.9, 0.99, 0.4, 0.7, 0.6], [0.1, 0.2, 0.5, 0.6, 0, 0, 1, 1, 0.3, 0.3, 0.4, 0.4,
    -0.2, 0.1, 1.4, 0.5, 0.2, 0.2, 0.3, 0.3], 5, 0.5, 2);
  return { ids: [...m.COCO_IDS], labels: [...m.COCO_LABELS], decoded };
}

// ---- a second set, after builder D's monitor screens (tests/fixtures/r8/desk_sequences.mjs on r8-d) ------------------
// The screen fills the pane's guide box: SYS and DIA large and close together, PUL small, right-aligned; a small clock
// line on top, label blocks and a heart mark beside the numbers; segments drawn apart (rectangles, a thin gap between
// each); a slant in degrees, a light gradient, noise, sometimes a blur, sometimes backlit. Drawn here, independently.
function monitorScreen(o) {
  const w = o.w, h = o.h, r = rng(o.seed), k = Math.tan((o.slant * Math.PI) / 180);
  const bg = o.backlit ? 35 : 185, fg = o.backlit ? 215 : 45;
  const px = new Float32Array(w * h).map((_, i) => bg + o.gradient * ((i % w) / w - 0.5));
  const put = (x, y) => { if (x >= 0 && x < w && y >= 0 && y < h) px[y * w + x] = fg; };
  const block = (x, y, bw, bh, shear, mid) => {
    for (let yy = Math.round(y); yy < Math.round(y + bh); yy += 1) {
      const dx = shear ? (mid - yy) * k : 0;
      for (let xx = Math.round(x + dx); xx < Math.round(x + bw + dx); xx += 1) put(xx, yy);
    }
  };
  const digit = (d, x0, y0, H) => {
    const W = 0.55 * H, s = 0.14 * H, g = 0.035 * H, mid = y0 + H / 2;
    const at = { a: [s + g, 0, W - 2 * s - 2 * g, s], g: [s + g, H / 2 - s / 2, W - 2 * s - 2 * g, s], d: [s + g, H - s, W - 2 * s - 2 * g, s],
      f: [0, g, s, H / 2 - 2 * g], b: [W - s, g, s, H / 2 - 2 * g], e: [0, H / 2 + g, s, H / 2 - 2 * g], c: [W - s, H / 2 + g, s, H / 2 - 2 * g] };
    for (const seg of ON[d]) { const [x, y, bw, bh] = at[seg]; block(x0 + x, y0 + y, bw, bh, true, mid); }
  };
  const number = (v, right, top, H) => [...String(v)].forEach((c, i, all) => digit(Number(c), right - (all.length - i) * 0.77 * H + 0.22 * H, top, H));
  const big = 0.29 * h * o.scale, small = 0.15 * h * o.scale;
  number(o.values[0], 0.94 * w + o.dx, 0.08 * h + o.dy, big);
  number(o.values[1], 0.94 * w + o.dx, 0.43 * h + o.dy, big);
  number(o.values[2], 0.94 * w + o.dx, 0.8 * h + o.dy, small);
  if (o.clock) { number(10, 0.3 * w + o.dx, 0.005 * h + o.dy, 0.06 * h); number(35, 0.48 * w + o.dx, 0.005 * h + o.dy, 0.06 * h); }
  if (o.marks) {
    block(0.04 * w + o.dx, 0.1 * h + o.dy, 0.12 * w, 0.06 * h); block(0.04 * w + o.dx, 0.45 * h + o.dy, 0.12 * w, 0.06 * h);
    block(0.04 * w + o.dx, 0.62 * h + o.dy, 0.14 * w, 0.05 * h);
    const hs = 0.08 * h;
    for (let y = 0; y < hs; y += 1) { const half = hs / 2 - Math.abs(y - hs / 2); block(0.5 * w + o.dx + hs / 2 - half, 0.83 * h + o.dy + y, 2 * half, 1); }
  }
  let out = Array.from(px, (v) => v + (r() - 0.5) * 2 * o.noise);
  if (o.blur) {
    out = out.map((_, i) => {
      const x = i % w, y = (i - x) / w;
      let n = 0, c = 0;
      for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy += 1) for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx += 1) { n += out[yy * w + xx]; c += 1; }
      return n / c;
    });
  }
  return Float32Array.from(out, (v) => Math.max(0, Math.min(255, Math.round(v))));
}
/** n monitor screens through the reader and the pane's own rule (console-coach-bp.js proposal): {n, right, wrong,
 *  none, misses}. A wrong reading is worse than none: the rule proposes only lines read surely (0.8). */
export async function monitors(input) {
  const i = Object.assign({ n: 200, seed: 41, w: 260, h: 220 }, input || {});
  const m = await import(new URL('console-vision-r8.js', STATIC).href), rule = await import(new URL('console-coach-bp.js', STATIC).href);
  const r = rng(i.seed), pick = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
  let right = 0, wrong = 0, none = 0;
  const misses = [];
  for (let k = 0; k < i.n; k += 1) {
    const sys = pick(95, 199), dia = pick(55, Math.min(125, sys - 20)), pulse = pick(48, 135);
    const px = monitorScreen({ w: i.w, h: i.h, values: [sys, dia, pulse], seed: i.seed * 31 + k, noise: pick(4, 18), slant: pick(0, 8),
      blur: r() < 0.5, backlit: r() < 0.2, gradient: pick(0, 30), scale: 0.9 + 0.2 * r(), dx: pick(-6, 6), dy: pick(-4, 4), clock: r() < 0.6, marks: r() < 0.8 });
    let lines = m.readDisplay(px, i.w, i.h);
    if (i.mutate === 'last-digit') lines = lines.map((l) => ({ ...l, value: l.value - (l.value % 10) + ((l.value + 1) % 10) }));
    const got = rule.proposal(lines);
    if (!got) { none += 1; if (misses.length < 6) misses.push({ want: [sys, dia, pulse], got: null }); }
    else if (got.systolic === sys && got.diastolic === dia && got.pulse === pulse) right += 1;
    else { wrong += 1; if (misses.length < 6) misses.push({ want: [sys, dia, pulse], got }); }
  }
  return { n: i.n, right, wrong, none, misses };
}
