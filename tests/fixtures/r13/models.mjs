// tests/fixtures/r13/models.mjs -- R13 Part D (docs/plans/r13-wardrobe.md D7, D8, "Browser" and INV-06): the three
// wardrobe models on the VENDORED onnxruntime-web 1.30.0 (one thread, no proxy: the wake word's settings), driven by
// the engine's OWN arithmetic (console-vision-r13.js, imported as the module it is) and its own
// references (SELF13). Every picture is drawn here: generated test patterns, never a photo, never a real face.
//   node tests/fixtures/r13/models.mjs <repo root>   -> one JSON line on stdout:
//   selfcheck {embed, face, person}   each model's fixed input gives SELF13's reference
//   face / clean_face                 a drawn face is found once; a laid-out shirt has none
//   person / clean_person             a drawn silhouette is a "person"; the shirt is not
//   inv06 {rotated, folded, back}     a drawn striped shirt's views find the striped shirt first (centred cosine over
//                                     the gallery's mean, as the scan module compares), with the margin to the next
// Used by tests/test_r13_d_assets.py. ASCII only.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const root = process.argv[2];
const STATIC = root + '/src/jarvis/api/static';
const src = readFileSync(STATIC + '/console-vision.js', 'utf8');
const asModule = (path) => import('data:text/javascript;base64,' + Buffer.from(readFileSync(path, 'utf8')).toString('base64'));
const P = await asModule(STATIC + '/console-vision-r13.js');
const SELF13 = JSON.parse(src.slice(src.indexOf('/*SELF13-BEGIN*/') + 16, src.indexOf('/*SELF13-END*/')));

const ort = await import(STATIC + '/vendor/ort/ort.wasm.min.mjs');
ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false; ort.env.wasm.wasmPaths = STATIC + '/vendor/ort/';
const OPTS = { executionProviders: ['wasm'], graphOptimizationLevel: 'all', logSeverityLevel: 3 };
const open = (name) => ort.InferenceSession.create(readFileSync(STATIC + '/vendor/vision/r13-1/' + name), OPTS);
const [embedS, faceS, personS] = await Promise.all(['mobilenetv2-int8-embed.onnx', 'version-RFB-320.onnx', 'ssd_mobilenet_v1_12-int8.onnx'].map(open));

// ---- drawing (RGBA, no canvas): test(x, y) is true (paint colour(x, y)), a colour, or nothing ------------------------------------------------------------------------------------
function pic(w, h, bg) { const d = new Uint8ClampedArray(w * h * 4); for (let i = 0; i < w * h; i += 1) d.set([...bg, 255], i * 4); return { w, h, d }; }
function fill(p, test, colour) { for (let y = 0; y < p.h; y += 1) for (let x = 0; x < p.w; x += 1) { const c = test(x, y); if (c) p.d.set([...(c === true ? colour(x, y) : c), 255], (y * p.w + x) * 4); } }
const inEllipse = (cx, cy, rx, ry) => (x, y) => ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1;
const inRect = (x0, y0, w, h) => (x, y) => x >= x0 && x < x0 + w && y >= y0 && y < y0 + h;
function resize(p, w, h) { // bilinear
  const o = pic(w, h, [0, 0, 0]);
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) {
    const fx = Math.min(p.w - 1.001, (x + 0.5) * p.w / w - 0.5), fy = Math.min(p.h - 1.001, (y + 0.5) * p.h / h - 0.5);
    const x0 = Math.max(0, Math.floor(fx)), y0 = Math.max(0, Math.floor(fy)), ax = Math.max(0, fx - x0), ay = Math.max(0, fy - y0);
    for (let k = 0; k < 3; k += 1) {
      const at = (xx, yy) => p.d[(yy * p.w + xx) * 4 + k];
      o.d[(y * w + x) * 4 + k] = (1 - ay) * ((1 - ax) * at(x0, y0) + ax * at(x0 + 1, y0)) + ay * ((1 - ax) * at(x0, y0 + 1) + ax * at(x0 + 1, y0 + 1));
    }
  }
  return o;
}
function rotate(p, deg) { // about the centre, the surface colour outside
  const o = pic(p.w, p.h, Array.from(p.d.slice(0, 3))), a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  for (let y = 0; y < p.h; y += 1) for (let x = 0; x < p.w; x += 1) {
    const dx = x - p.w / 2, dy = y - p.h / 2, sx = Math.round(c * dx + s * dy + p.w / 2), sy = Math.round(-s * dx + c * dy + p.h / 2);
    if (sx >= 0 && sx < p.w && sy >= 0 && sy < p.h) o.d.set(p.d.subarray((sy * p.w + sx) * 4, (sy * p.w + sx) * 4 + 4), (y * p.w + x) * 4);
  }
  return o;
}
const SURFACE = [232, 228, 220];
const stripes = (a, b, every) => (x) => (Math.floor(x / every) % 2 ? a : b);
const checks = (a, b, every) => (x, y) => ((Math.floor(x / every) + Math.floor(y / every)) % 2 ? a : b);
const plain = (a) => () => a;
function shirt(colour, { sleeves = true, collar = true, height = 1 } = {}) { // laid flat on a surface
  const p = pic(256, 320, SURFACE), top = 40, h = Math.round(240 * height);
  fill(p, inRect(68, top, 120, h), colour);
  if (sleeves) { fill(p, (x, y) => y >= top && y < top + 90 && x >= 28 && x < 68 && x - 28 > (y - top) * 0.2, colour); fill(p, (x, y) => y >= top && y < top + 90 && x >= 188 && x < 228 && 228 - x > (y - top) * 0.2, colour); }
  if (collar) { fill(p, inRect(108, top - 12, 40, 16), () => [245, 245, 245]); for (let i = 0; i < 5; i += 1) fill(p, inEllipse(128, top + 30 + i * 40, 4, 4), () => [240, 240, 240]); }
  return p;
}
function trousers(colour) { const p = pic(256, 320, SURFACE); fill(p, inRect(70, 30, 116, 40), colour); fill(p, inRect(70, 70, 52, 230), colour); fill(p, inRect(134, 70, 52, 230), colour); return p; }
function shoe(colour) { const p = pic(256, 320, SURFACE); fill(p, inEllipse(128, 200, 100, 46), colour); fill(p, inEllipse(90, 170, 40, 30), colour); return p; }
function face(p, cx, cy, s) {
  fill(p, inEllipse(cx, cy + s * 0.05, s * 0.42, s * 0.55), () => [70, 45, 30]);
  const skin = inEllipse(cx, cy + s * 0.12, s * 0.36, s * 0.47), shade = (x, y) => ((x - cx) / (s * 0.36)) ** 2 + ((y - cy - s * 0.12) / (s * 0.47)) ** 2;
  fill(p, (x, y) => skin(x, y) && [224, 172, 140].map((q) => q * (1 - 0.25 * Math.min(1, shade(x, y)))), null); // shaded skin
  for (const sx of [-0.14, 0.14]) { fill(p, inEllipse(cx + s * sx, cy, s * 0.07, s * 0.035), () => [250, 250, 250]); fill(p, inEllipse(cx + s * sx, cy, s * 0.03, s * 0.03), () => [40, 30, 20]); }
  fill(p, inEllipse(cx, cy + s * 0.15, s * 0.04, s * 0.08), () => [200, 140, 110]);
  fill(p, inEllipse(cx, cy + s * 0.32, s * 0.11, s * 0.035), () => [170, 70, 70]);
  return p;
}
function figure() { // a different silhouette from the self-check's: larger, off centre, a warmer sky
  const p = pic(480, 480, [205, 220, 240]), ink = () => [30, 28, 34];
  fill(p, inEllipse(200, 80, 36, 44), ink); fill(p, inEllipse(200, 210, 78, 104), ink); fill(p, inRect(144, 285, 48, 190), ink);
  fill(p, inRect(210, 285, 48, 190), ink); fill(p, inEllipse(112, 218, 20, 90), ink); fill(p, inEllipse(288, 218, 20, 90), ink);
  return p;
}

// ---- the engine's preprocessing and decoding, as console-vision.js runs them -------------------------------------
const hex = (u8) => createHash('sha256').update(Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength)).digest('hex');
async function embed(p) {
  const r = resize(p, 224, 224);
  const out = await embedS.run({ input: new ort.Tensor('float32', P.chw(r.d, 224, 224, P.MEAN13, P.STD13), [1, 3, 224, 224]) });
  return out['472_quantized'].data;
}
async function faces(p) {
  const r = resize(p, 320, 240);
  const out = await faceS.run({ input: new ort.Tensor('float32', P.chwFace(r.d, 320 * 240), [1, 3, 240, 320]) });
  return P.found(P.faceBoxes(out.scores.data, out.boxes.data, 0.7, 0.3, 20));
}
async function people(p) {
  const r = resize(p, 300, 300);
  const out = await personS.run({ inputs: new ort.Tensor('uint8', P.rgb(r.d, 300 * 300), [1, 300, 300, 3]) });
  return P.found(P.personBoxes(out.detection_classes.data, out.detection_scores.data, out.detection_boxes.data, out.num_detections.data[0], 0.5, 20));
}

// ---- 1: the self-checks with the engine's inputs and references --------------------------------------------------
const e0 = (await embedS.run({ input: new ort.Tensor('float32', P.ramp(3 * 224 * 224), [1, 3, 224, 224]) }))['472_quantized'].data;
const f0 = await faceS.run({ input: new ort.Tensor('float32', P.ramp(3 * 240 * 320), [1, 3, 240, 320]) });
const ftop = P.topScores(f0.scores.data, 5);
const p0 = await personS.run({ inputs: new ort.Tensor('uint8', P.silhouette(), [1, 300, 300, 3]) });
const ref = SELF13.person;
const selfcheck = {
  embed: hex(e0) === SELF13.embed.sha256,
  face: SELF13.face.top.every((v, i) => P.near(ftop[i], v, SELF13.face.tol)),
  person: p0.num_detections.data[0] >= 1 && Math.round(p0.detection_classes.data[0]) === ref.class
    && P.near(p0.detection_scores.data[0], ref.score, ref.tol) && ref.box.every((v, i) => P.near(p0.detection_boxes.data[i], v, ref.tol)),
};

// ---- 2: a drawn face, a drawn silhouette, and a shirt that has neither --------------------------------------------
const laid = shirt(stripes([28, 36, 78], [240, 240, 236], 14));
const out = {
  selfcheck, embed_dims: e0.length, embed_b64: P.b64(e0).length,
  face: await faces(face(pic(640, 480, [120, 150, 170]), 320, 240, 220)), clean_face: await faces(laid),
  person: await people(figure()), clean_person: await people(laid),
};

// ---- 3: INV-06's real half: one striped shirt under rotation and folding -------------------------------------------
const gallery = {
  striped: laid,
  checked: shirt(checks([200, 30, 40], [240, 240, 236], 18)),
  grey_tee: shirt(plain([128, 128, 128]), { collar: false }),
  white_shirt: shirt(plain([245, 245, 242])),
  trousers: trousers(plain([54, 60, 66])),
  jeans: trousers(checks([40, 90, 200], [36, 80, 180], 3)),
  shoe: shoe(plain([110, 70, 40])),
};
const names = Object.keys(gallery);
const vecs = {};
for (const n of names) vecs[n] = Float32Array.from(await embed(gallery[n]));
const mean = new Float32Array(1280);
names.forEach((n) => vecs[n].forEach((v, i) => { mean[i] += v / names.length; }));
const centred = (v) => Float32Array.from(v, (x, i) => x - mean[i]);
const cos = (a, b) => { let d = 0, na = 0, nb = 0; for (let i = 0; i < a.length; i += 1) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; } return d / Math.sqrt(na * nb || 1); };
async function rank(p) {
  const q = centred(Float32Array.from(await embed(p)));
  const scored = names.map((n) => [n, cos(q, centred(vecs[n]))]).sort((a, b) => b[1] - a[1]);
  return { top: scored[0][0], score: Math.round(scored[0][1] * 1000) / 1000, margin: Math.round((scored[0][1] - scored[1][1]) * 1000) / 1000, next: scored[1][0] };
}
const navyWhite = stripes([28, 36, 78], [240, 240, 236], 14);
out.inv06 = {
  rotated: await rank(rotate(laid, 25)),
  folded: await rank(shirt(navyWhite, { sleeves: false, height: 0.55 })),
  back: await rank(shirt(navyWhite, { collar: false })),
};
out.inv06.other_top = (await rank(rotate(gallery.checked, 25))).top;
console.log(JSON.stringify(out));
