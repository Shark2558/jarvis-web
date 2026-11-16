// src/jarvis/api/static/console-vision-r13.js -- R13 Part D (docs/plans/r13-wardrobe.md D7-D9): the plain arithmetic of the
// vision engine's four wardrobe tasks, moved out of console-vision.js (REVIEW-D-1 split) so the engine keeps room. The
// engine imports it the first time a wardrobe task is used (console-vision.js `pure()`); a failed import is "could not
// load" for those four tasks only, never for R7's five. Arrays in, arrays out: no DOM, no canvas, no network, no
// storage, no clock. tests/fixtures/r13/pure.mjs and models.mjs import this very file in Node. ASCII only.

const COLOURS13 = Object.freeze(/*COLOURS-BEGIN*/{ black: [20, 20, 22], white: [245, 245, 242], grey: [128, 128, 128],
  charcoal: [54, 60, 66], navy: [28, 36, 78], blue: [40, 90, 200], light_blue: [150, 190, 230], green: [40, 140, 60],
  olive: [110, 110, 50], yellow: [240, 210, 50], orange: [240, 130, 40], red: [200, 30, 40], maroon: [120, 25, 40],
  pink: [240, 160, 190], purple: [110, 50, 140], brown: [110, 70, 40], beige: [220, 200, 160], khaki: [190, 175, 120] }/*COLOURS-END*/);
const MEAN13 = [0.485, 0.456, 0.406], STD13 = [0.229, 0.224, 0.225]; // ImageNet, as MobileNet v2 was trained
const MULTI_SHARE = 0.35, MULTI_DE = 20; // two clusters, each at least this share and this far apart: multicolour

// The self-check inputs (D8): fixed arithmetic, the same bytes on every device
function ramp(n) { const x = new Float32Array(n); for (let i = 0; i < n; i += 1) x[i] = ((i % 251) / 250) * 2 - 1; return x; }
function silhouette() { // uint8[1, 300, 300, 3]: a dark figure against a pale sky (SSD's "person")
  const W = 300, d = new Uint8Array(W * W * 3), ink = [35, 30, 30];
  for (let i = 0; i < W * W; i += 1) { d[i * 3] = 190; d[i * 3 + 1] = 210; d[i * 3 + 2] = 235; }
  const put = (x, y) => { d.set(ink, (y * W + x) * 3); };
  const ellipse = (cx, cy, rx, ry) => {
    for (let y = Math.max(0, Math.floor(cy - ry)); y < Math.min(W, Math.ceil(cy + ry)); y += 1) {
      for (let x = Math.max(0, Math.floor(cx - rx)); x < Math.min(W, Math.ceil(cx + rx)); x += 1) {
        const u = (x - cx) / rx, v = (y - cy) / ry;
        if (u * u + v * v <= 1) put(x, y);
      }
    }
  };
  const rect = (x0, y0, w, h) => { for (let y = y0; y < Math.min(W, y0 + h); y += 1) for (let x = x0; x < x0 + w; x += 1) put(x, y); };
  ellipse(150, 55, 24, 30); ellipse(150, 140, 52, 70); rect(112, 190, 32, 110); rect(156, 190, 32, 110);
  ellipse(92, 145, 14, 60); ellipse(208, 145, 14, 60);
  return d;
}
const near = (a, b, tol) => Math.abs(a - b) <= tol;
function topScores(scores, k) { // face scores (column 1 of [n, 2]), the k highest
  const out = [];
  for (let i = 1; i < scores.length; i += 2) out.push(scores[i]);
  return out.sort((a, b) => b - a).slice(0, k);
}

// Pixels in, a model's input out
function chw(rgba, w, h, mean, std) { // RGBA bytes -> float32 [3, h, w], (v / 255 - mean) / std
  const n = w * h, x = new Float32Array(3 * n);
  for (let i = 0; i < n; i += 1) for (let k = 0; k < 3; k += 1) x[k * n + i] = (rgba[i * 4 + k] / 255 - mean[k]) / std[k];
  return x;
}
function chwFace(rgba, n) { const x = new Float32Array(3 * n); for (let i = 0; i < n; i += 1) for (let k = 0; k < 3; k += 1) x[k * n + i] = (rgba[i * 4 + k] - 127) / 128; return x; }
function rgb(rgba, n) { const x = new Uint8Array(3 * n); for (let i = 0; i < n; i += 1) { x[i * 3] = rgba[i * 4]; x[i * 3 + 1] = rgba[i * 4 + 1]; x[i * 3 + 2] = rgba[i * 4 + 2]; } return x; }
function b64(bytes) { let s = ''; for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i]); return btoa(s); }
function quantize(floats, scale) { return Uint8Array.from(floats, (v) => Math.max(0, Math.min(255, Math.round(v / scale)))); }

// The colour: CIE Lab (D65) and the nearest named colour by Delta E (CIE76)
function lab(r, g, b) {
  const lin = (c) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const R = lin(r), G = lin(g), B = lin(b);
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (t * 24389 / 27 + 16) / 116);
  const x = f((0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047), y = f(0.2126 * R + 0.7152 * G + 0.0722 * B);
  const z = f((0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
const dE = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
const NAMED13 = Object.keys(COLOURS13).map((k) => [k, lab(...COLOURS13[k])]);
function nearest(p) { let best = null, d = Infinity; NAMED13.forEach(([k, q]) => { const e = dE(p, q); if (e < d) { d = e; best = k; } }); return best; }
function median(xs) { const s = xs.slice().sort((a, b) => a - b); return s.length ? s[s.length >> 1] : 0; }
function twoMeans(pts) { // two clusters, started from the darkest and the lightest point, 8 rounds
  let a = pts[0], b = pts[0];
  pts.forEach((p) => { if (p[0] < a[0]) a = p; if (p[0] > b[0]) b = p; });
  let ca = [], cb = [];
  for (let round = 0; round < 8; round += 1) {
    ca = []; cb = [];
    pts.forEach((p) => (dE(p, a) <= dE(p, b) ? ca : cb).push(p));
    const mean = (c, was) => (c.length ? [0, 1, 2].map((k) => c.reduce((s, p) => s + p[k], 0) / c.length) : was);
    a = mean(ca, a); b = mean(cb, b);
  }
  return [[a, ca.length], [b, cb.length]].sort((x, y) => y[1] - x[1]);
}
function colourOf(rgba) { // {name, second?, share}: the colour of these pixels (D7)
  const pts = [];
  for (let i = 0; i + 3 < rgba.length; i += 4) pts.push(lab(rgba[i], rgba[i + 1], rgba[i + 2]));
  if (!pts.length) return { name: 'grey', share: 0 };
  const [[big, nBig], [small, nSmall]] = twoMeans(pts);
  const shareBig = nBig / pts.length, shareSmall = nSmall / pts.length;
  if (shareSmall >= MULTI_SHARE && dE(big, small) > MULTI_DE && nearest(big) !== nearest(small)) {
    return { name: 'multicolour', second: nearest(big), share: Math.round(shareBig * 1000) / 1000 };
  }
  const name = nearest([0, 1, 2].map((k) => median(pts.map((p) => p[k]))));
  const share = pts.filter((p) => nearest(p) === name).length / pts.length;
  return { name, share: Math.round(share * 1000) / 1000 };
}

// Boxes out of the two detectors, normalized {x, y, w, h}
function iou(p, q) {
  const x = Math.max(0, Math.min(p.x + p.w, q.x + q.w) - Math.max(p.x, q.x));
  const y = Math.max(0, Math.min(p.y + p.h, q.y + q.h) - Math.max(p.y, q.y));
  const both = x * y, all = p.w * p.h + q.w * q.h - both;
  return all > 0 ? both / all : 0;
}
function nms(cands, limit, max) { // cands: [{score, box}] -> the boxes kept, best first
  const kept = [];
  cands.slice().sort((a, b) => b.score - a.score).forEach((c) => {
    if (kept.length < max && kept.every((k) => iou(k.box, c.box) <= limit)) kept.push(c);
  });
  return kept.map((k) => k.box);
}
const unitBox = (x0, y0, x1, y1) => {
  const c = (v) => Math.min(1, Math.max(0, v));
  const x = c(x0), y = c(y0);
  return { x, y, w: Math.max(0, c(x1) - x), h: Math.max(0, c(y1) - y) };
};
function faceBoxes(scores, boxes, min, limit, max) { // UltraFace: scores [n, 2], boxes [n, 4] as x1 y1 x2 y2
  const cands = [];
  for (let i = 0; i * 2 + 1 < scores.length; i += 1) {
    if (scores[i * 2 + 1] >= min) cands.push({ score: scores[i * 2 + 1], box: unitBox(boxes[i * 4], boxes[i * 4 + 1], boxes[i * 4 + 2], boxes[i * 4 + 3]) });
  }
  return nms(cands, limit, max);
}
function personBoxes(classes, scores, boxes, count, min, max) { // SSD: boxes as ymin xmin ymax xmax; person is class 1
  const out = [];
  for (let i = 0; i < Math.min(count, scores.length); i += 1) {
    if (Math.round(classes[i]) === 1 && scores[i] >= min) out.push(unitBox(boxes[i * 4 + 1], boxes[i * 4], boxes[i * 4 + 3], boxes[i * 4 + 2]));
  }
  return out.slice(0, max);
}
const round3 = (b) => ({ x: Math.round(b.x * 1000) / 1000, y: Math.round(b.y * 1000) / 1000, w: Math.round(b.w * 1000) / 1000, h: Math.round(b.h * 1000) / 1000 });
const found = (boxes) => ({ found: boxes.length > 0, count: boxes.length, boxes: boxes.map(round3) });
const COLOUR_NAMES = Object.freeze(Object.keys(COLOURS13)); // the server's jarvis.vision.results.COLOUR_NAMES, in order

export { COLOURS13, COLOUR_NAMES, MEAN13, STD13, ramp, silhouette, near, topScores, chw, chwFace, rgb, b64, quantize, lab,
  nearest, colourOf, iou, nms, faceBoxes, personBoxes, found };
