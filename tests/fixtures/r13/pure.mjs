// tests/fixtures/r13/pure.mjs -- R13 Part D: console-vision.js's WARDROBE-PURE region, run as it is in Node, on drawn
// colour patches and recorded-shape model outputs (no model, no DOM). tests/test_r13_d_vision.py reads the JSON line.
//   node tests/fixtures/r13/pure.mjs <repo root>
import { readFileSync } from 'node:fs';

const src = readFileSync(process.argv[2] + '/src/jarvis/api/static/console-vision.js', 'utf8');
const region = src.slice(src.indexOf('/*WARDROBE-PURE-BEGIN*/'), src.indexOf('/*WARDROBE-PURE-END*/'));
const P = new Function(region + '\nreturn { COLOURS13, colourOf, faceBoxes, personBoxes, found, b64, quantize, ramp, silhouette, chw, MEAN13, STD13 };')();

const patch = (n, f) => { const out = []; for (let i = 0; i < n; i += 1) out.push(...f(i), 255); return out; };
const solid = (c) => patch(400, () => c);
const halves = (a, b) => patch(400, (i) => (i % 20 < 10 ? a : b));
const noisy = (c) => patch(400, (i) => c.map((v) => Math.max(0, Math.min(255, v + ((i * 37) % 21) - 10))));
const colours = {};
for (const [name, c] of Object.entries(P.COLOURS13)) colours[name] = P.colourOf(noisy(c)).name;

// UltraFace shape: scores [n, 2], boxes [n, 4] (x1 y1 x2 y2); two overlapping faces and one apart, one weak
const fs = Float32Array.from([0.1, 0.9, 0.2, 0.8, 0.95, 0.05, 0.25, 0.75, 0.4, 0.6]);
const fb = Float32Array.from([0.1, 0.1, 0.3, 0.4, 0.11, 0.1, 0.31, 0.41, 0, 0, 1, 1, 0.6, 0.5, 0.8, 0.8, 0.5, 0.5, 0.6, 0.6]);
// SSD shape: classes, scores, boxes [n, 4] (ymin xmin ymax xmax), count
const sc = Float32Array.from([1, 37, 1, 1]), ss = Float32Array.from([0.9, 0.95, 0.49, 0.7]);
const sb = Float32Array.from([0.1, 0.2, 0.9, 0.6, 0, 0, 1, 1, 0.2, 0.2, 0.3, 0.3, 0.5, 0.05, 0.7, 0.25]);
const sil = P.silhouette();
console.log(JSON.stringify({
  names: Object.keys(P.COLOURS13),
  colours,
  white: P.colourOf(solid([250, 250, 250])),
  stripes: P.colourOf(halves([28, 36, 78], [245, 245, 242])),
  mostly_navy: P.colourOf(patch(400, (i) => (i % 10 < 8 ? [28, 36, 78] : [245, 245, 242]))),
  empty: P.colourOf([]),
  faces: P.found(P.faceBoxes(fs, fb, 0.7, 0.3, 20)),
  faces_max1: P.faceBoxes(fs, fb, 0.7, 0.3, 1).length,
  people: P.found(P.personBoxes(sc, ss, sb, 4, 0.5, 20)),
  people_count2: P.personBoxes(sc, ss, sb, 2, 0.5, 20).length,
  b64: P.b64(Uint8Array.from([0, 255, 1, 2])),
  b64_len: P.b64(new Uint8Array(1280)).length,
  quantized: Array.from(P.quantize(Float32Array.from([-1, 0, 0.0095, 0.0096, 1, 100]), 0.019110053777694702)),
  ramp: Array.from(P.ramp(3)).concat(P.ramp(252)[251]).map((v) => Math.round(v * 1000) / 1000),
  silhouette: { bytes: sil.length, sky: Array.from(sil.slice(0, 3)), ink: Array.from(sil.slice((55 * 300 + 150) * 3, (55 * 300 + 150) * 3 + 3)) },
  chw: Array.from(P.chw([255, 0, 0, 255], 1, 1, P.MEAN13, P.STD13)).map((v) => Math.round(v * 1000) / 1000),
}));
