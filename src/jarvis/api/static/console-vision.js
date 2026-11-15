// src/jarvis/api/static/console-vision.js -- R7 D13 (I0 core; Part B fills the tasks): the vision engine's ONE port.
// Tasks see pixels; use cases never do. Loaded by console-r7.js (an ES module); the same file runs on the phone and
// in the laptop browser. No task is built here: Part B registers text, code, objects, pose and quality.
//   JarvisVision.tasks()                      -> [{id, v, input: 'photo'|'live'|'both', ready, why}]
//   JarvisVision.run(task, source, opts)      -> Promise<Result>     one photo (a Blob, ImageBitmap or canvas)
//   JarvisVision.stream(task, opts, onResult) -> {stop()}            live, at the task's capped rate
//   JarvisVision.register(task)               (closed after the five built-in tasks: later tasks are added by editing
//                                             this engine, never from a use case) a task = {id, v, input, rate?, load() -> Promise, run(frame, opts) -> data,
//                                             check(data) -> bool}   (its schema: numbers in ranges, labels from its own
//                                             list, text <= 2,000 characters; the server's jarvis.vision.results)
//   JarvisVision.use(usecase)                 a use case = {id, tasks: [...], onResult(result, state), summary(state)}
//   Result = {task, v, at, ms, device: 'phone'|'browser'|'home', ok, data, quality: {light, sharp}}
// A Result is a frozen copy of plain data: a task's answer that fails its own check is dropped (ok: false, data {}),
// and a use case receives Results only, never a frame, never the task, never the source. This file holds no frame
// after run() returns. A use case's module may not read pixels or send bytes (Part B's static test lists the APIs).
const M = window.JarvisMobile;
const TASK_ID = /^[a-z][a-z-]{1,20}$/;
const INPUTS = ['photo', 'live', 'both'];
const LIVE_MAX_PER_S = 15; // D13: pose at most 15 a second, objects 5; a slow device slows itself
const tasks = new Map();
const uses = new Map();
let sealed = false; // v7.0.2: after the five built-in tasks nobody adds one (a use case never reaches a frame)

const device = () => (/Android|iPhone|iPad/i.test(navigator.userAgent || '') ? 'phone' : 'browser');
const unit = (v) => (Number.isFinite(v) && v >= 0 && v <= 1 ? v : 0);

function plain(v, depth) { // a deep, frozen copy of JSON-shaped data only (no objects with prototypes, no buffers)
  if (depth > 6) return null;
  if (v === null || typeof v === 'boolean' || typeof v === 'string') return typeof v === 'string' ? v.slice(0, 2000) : v;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (Array.isArray(v)) return Object.freeze(v.slice(0, 100).map((x) => plain(x, depth + 1)));
  if (Object.prototype.toString.call(v) !== '[object Object]') return null;
  const out = {};
  Object.keys(v).slice(0, 50).forEach((k) => { out[k] = plain(v[k], depth + 1); });
  return Object.freeze(out);
}

function result(task, data, ms, quality) {
  const ok = !!data && typeof task.check === 'function' && task.check(data) === true;
  return Object.freeze({
    task: task.id, v: task.v, at: Math.floor(Date.now() / 1000), ms: Math.max(0, Math.round(ms)), device: device(), ok,
    data: ok ? plain(data, 0) : Object.freeze({}),
    quality: Object.freeze({ light: unit(quality && quality.light), sharp: unit(quality && quality.sharp) }),
  });
}

function sealRegistry() { sealed = true; }
function register(task) {
  if (sealed || !task || !TASK_ID.test(task.id || '') || tasks.has(task.id)) return false;
  if (typeof task.run !== 'function' || typeof task.check !== 'function' || !INPUTS.includes(task.input)) return false;
  tasks.set(task.id, { id: task.id, v: Number.isInteger(task.v) ? task.v : 1, input: task.input, rate: Math.min(LIVE_MAX_PER_S, task.rate || 5),
    load: typeof task.load === 'function' ? task.load : () => Promise.resolve(), run: task.run, check: task.check,
    ready: false, why: '', loading: null });
  return true;
}

async function ready(t) {
  if (t.ready) return true;
  if (!t.loading) t.loading = Promise.resolve().then(() => t.load()).then(() => { t.ready = true; t.why = ''; }, (e) => { t.why = String((e && e.message) || 'not installed').slice(0, 120); });
  await t.loading;
  t.loading = t.ready ? t.loading : null;
  return t.ready;
}

function list() {
  return [...tasks.values()].map((t) => Object.freeze({ id: t.id, v: t.v, input: t.input, ready: t.ready, why: t.why }));
}

function tell(r) { // every use case that asked for this task gets the Result, nothing else
  uses.forEach((u) => {
    if (!u.tasks.includes(r.task)) return;
    try { u.state = u.onResult(r, u.state); } catch (_) {}
  });
}

async function run(id, source, opts) {
  const t = tasks.get(id);
  if (!t) throw new Error('That vision task is not installed.');
  if (!(await ready(t))) throw new Error(t.why || 'That vision task is not installed.');
  const start = performance.now();
  const out = await t.run(source, opts || {});
  const r = result(t, out && out.data, performance.now() - start, out && out.quality);
  tell(r);
  return r;
}

const NO_PICTURE = 'There is no picture to look at.';
const MISSES_MAX = 20; // frames in a row with no picture before a live look says so
function stream(id, opts, onResult) {
  const t = tasks.get(id);
  let on = !!t && t.input !== 'photo', timer = 0, misses = 0;
  const stop = () => { on = false; clearTimeout(timer); };
  const fail = (e) => { stop(); if (opts && typeof opts.onError === 'function') { try { opts.onError(e); } catch (_) {} } };
  if (!on) { if (opts && typeof opts.onError === 'function') fail(new Error('That vision task is not installed.')); return { stop }; }
  const source = opts && typeof opts.frame === 'function' ? opts.frame : null; // the camera hands a frame per call
  const loop = async () => {
    if (!on || !source) return;
    const start = performance.now();
    try {
      const r = await run(id, source(), opts);
      misses = 0;
      if (on && typeof onResult === 'function') onResult(r);
    } catch (e) {
      if (!(e && e.message === NO_PICTURE)) { fail(e); return; } // a task that cannot load or run is said, never silent
      misses += 1; // a frame that is not there yet (the camera is warming up) is skipped
      if (misses > MISSES_MAX) { fail(e); return; }
    }
    const took = performance.now() - start, gap = Math.max(1000 / t.rate, took * 2); // slows itself when slow
    if (on) timer = setTimeout(loop, gap);
  };
  loop();
  return { stop };
}

function use(usecase) {
  if (!usecase || !TASK_ID.test(usecase.id || '') || uses.has(usecase.id) || typeof usecase.onResult !== 'function') return false;
  const wanted = Array.isArray(usecase.tasks) ? usecase.tasks.filter((x) => typeof x === 'string').slice(0, 8) : [];
  uses.set(usecase.id, { id: usecase.id, tasks: wanted, onResult: usecase.onResult, summary: usecase.summary, state: undefined });
  return true;
}

const api = Object.freeze({ tasks: list, run, stream, register, use });
window.JarvisVision = api;
if (M) M.part('vision', api);

// ==== R7 Part B: the five tasks (D13, D14) =============================================================================
// Each task is the only code that touches a frame; it returns plain data its own check() holds to the server's schema
// (jarvis.vision.results: labels from its own list, numbers in ranges, text <= 2,000 characters, nothing else). Its files
// come only from JARVIS (BASE: static/vendor/vision/<release>/, served only when they match MANIFEST.json's SHA-256),
// the first time the task is used; nothing is fetched from another site (connect-src 'self'). A drawn copy of a frame
// lives in one scratch canvas for the length of a run and is emptied after it.
//   text     tesseract.js 7 (worker, core and English data from BASE; workerBlobURL false, no IndexedDB cache)
//   code     zxing-wasm 3 reader (its .wasm from BASE, never the CDN default)
//   objects  MediaPipe Object Detector (80 everyday things)   } "not installed" until their model files arrive
//   pose     MediaPipe Pose Landmarker (33 body points)       } (D14; the model card's limits are the panel's words)
//   quality  light and sharpness: plain arithmetic, no model
const BASE = '/static/vendor/vision/r7-1/';
const NOT_INSTALLED = 'not installed';
const NO_LOAD = 'The vision tools could not load. Check the connection and try again.';
const TEXT_MAX = 2000;
const SIDE_MAX = 2000; // a photo is read at most this many pixels on its long side
const SMALL = 160; // light and sharpness are measured on a copy this small
const POSE_MODEL = 'pose_landmarker_lite.task';
const OBJECT_MODEL = 'efficientdet_lite0.tflite';
const MP_FILES = { wasmLoaderPath: BASE + 'vision_wasm_internal.js', wasmBinaryPath: BASE + 'vision_wasm_internal.wasm' };
// the lists of jarvis.vision.results (tests/test_r7_b_console.py keeps them equal)
const OBJECT_LABELS = Object.freeze(/*LABELS-BEGIN*/('person bicycle car motorcycle airplane bus train truck boat traffic_light '
  + 'fire_hydrant stop_sign parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella '
  + 'handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard surfboard '
  + 'tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot hot_dog pizza '
  + 'donut cake chair couch potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave oven '
  + 'toaster sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush')/*LABELS-END*/.split(' '));
const CODE_FORMATS = Object.freeze(/*CODES-BEGIN*/['qr_code', 'ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39',
  'itf', 'data_matrix', 'pdf_417', 'aztec']/*CODES-END*/);
const ZX = [['QRCode', 'qr_code'], ['MicroQRCode', 'qr_code'], ['RMQRCode', 'qr_code'], ['EAN13', 'ean_13'], ['ISBN', 'ean_13'],
  ['EAN8', 'ean_8'], ['UPCA', 'upc_a'], ['UPCE', 'upc_e'], ['Code128', 'code_128'], ['Code39', 'code_39'],
  ['Code32', 'code_39'], ['ITF', 'itf'], ['DataMatrix', 'data_matrix'], ['PDF417', 'pdf_417'],
  ['CompactPDF417', 'pdf_417'], ['MicroPDF417', 'pdf_417'], ['Aztec', 'aztec']];

// ---- the checks: exactly the server's schema -------------------------------------------------------------------------
const isObj = (o) => !!o && typeof o === 'object' && !Array.isArray(o);
const only = (o, keys) => isObj(o) && Object.keys(o).every((k) => keys.includes(k));
const num = (v, lo, hi) => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
const inUnit = (v) => num(v, 0, 1);
const clamp = (v, lo, hi) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo);
const text = (s) => typeof s === 'string' && s.length <= TEXT_MAX;
const CHECKS = {
  text: (d) => only(d, ['text', 'confidence']) && text(d.text) && (d.confidence === undefined || d.confidence === null || inUnit(d.confidence)),
  code: (d) => only(d, ['codes']) && Array.isArray(d.codes) && d.codes.length <= 20
    && d.codes.every((c) => only(c, ['format', 'value']) && CODE_FORMATS.includes(c.format) && text(c.value)),
  objects: (d) => only(d, ['objects']) && Array.isArray(d.objects) && d.objects.length <= 50
    && d.objects.every((o) => only(o, ['label', 'score', 'box']) && OBJECT_LABELS.includes(o.label) && inUnit(o.score)
      && only(o.box, ['x', 'y', 'w', 'h']) && ['x', 'y', 'w', 'h'].every((k) => inUnit(o.box[k]))),
  pose: (d) => only(d, ['points']) && Array.isArray(d.points) && d.points.length <= 33
    && d.points.every((p) => only(p, ['x', 'y', 'z', 'visibility']) && num(p.x, -1, 2) && num(p.y, -1, 2)
      && num(p.z, -10, 10) && inUnit(p.visibility)),
  quality: (d) => only(d, ['light', 'sharp']) && inUnit(d.light) && inUnit(d.sharp),
};

// ---- frames: whatever the camera or a photo gives, drawn into this run's own canvases ---------------------------------
function sizeOf(f) {
  return { w: f.videoWidth || f.naturalWidth || f.width || 0, h: f.videoHeight || f.naturalHeight || f.height || 0 };
}
async function drawable(frame) {
  if (!frame) throw new Error(NO_PICTURE);
  if (typeof Blob !== 'undefined' && frame instanceof Blob) {
    const bmp = await createImageBitmap(frame);
    return { img: bmp, w: bmp.width, h: bmp.height, done: () => bmp.close() };
  }
  const { w, h } = sizeOf(frame);
  if (!w || !h) throw new Error(NO_PICTURE);
  return { img: frame, w, h, done: () => {} };
}
function drawn(src, side) { // a canvas of this run only; look() empties it when the run ends
  const k = Math.min(1, side / Math.max(src.w, src.h));
  const w = Math.max(1, Math.round(src.w * k)), h = Math.max(1, Math.round(src.h * k));
  const c = document.createElement('canvas');
  src.pads.push(c);
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src.img, 0, 0, w, h);
  return { c, ctx, w, h };
}
const empty = (c) => { c.width = 0; c.height = 0; };

/** Light (mean luminance) and sharpness (spread of the Laplacian), both 0..1: plain arithmetic. */
function measure(img) {
  const d = img.data, w = img.width, h = img.height, n = w * h;
  if (!n) return { light: 0, sharp: 0 };
  const lum = new Float32Array(n);
  let sum = 0;
  for (let i = 0; i < n; i += 1) { const l = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]; lum[i] = l; sum += l; }
  let acc = 0, cnt = 0;
  for (let y = 1; y < h - 1; y += 1) {
    for (let x = 1; x < w - 1; x += 1) {
      const i = y * w + x, lap = 4 * lum[i] - lum[i - 1] - lum[i + 1] - lum[i - w] - lum[i + w];
      acc += lap * lap; cnt += 1;
    }
  }
  const round = (v) => Math.round(clamp(v, 0, 1) * 1000) / 1000;
  return { light: round(sum / n / 255), sharp: round(cnt ? Math.sqrt(acc / cnt) / 50 : 0) };
}
function qualityOf(src) {
  const s = drawn(src, SMALL);
  return measure(s.ctx.getImageData(0, 0, s.w, s.h));
}
async function look(frame, fn) { // one run on one frame; every copy drawn for it is emptied after it
  const src = Object.assign(await drawable(frame), { pads: [] });
  try { return await fn(src); } finally { src.done(); src.pads.forEach(empty); }
}

// ---- loading a task's own files, from JARVIS only ----------------------------------------------------------------------
// Whatever goes wrong while loading is said in two plain ways only: "not installed" (a model file that has not arrived)
// or NO_LOAD; the browser's own wording never reaches the screen (a task's load() runs through guard()).
const guard = (load) => async () => {
  try { await load(); } catch (e) { throw e && e.message === NOT_INSTALLED ? e : new Error(NO_LOAD); }
};
const scripts = new Map();
function script(src, global) { // one <script> per file: a failed one is removed so the next try starts clean
  if (window[global]) return Promise.resolve(window[global]);
  if (scripts.has(src)) return scripts.get(src);
  const p = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    const fail = () => { scripts.delete(src); if (s.parentNode) s.parentNode.removeChild(s); reject(new Error(NO_LOAD)); };
    s.src = src;
    s.addEventListener('load', () => (window[global] ? resolve(window[global]) : fail()));
    s.addEventListener('error', fail);
    document.head.append(s);
  });
  scripts.set(src, p);
  return p;
}
async function model(name) { // 404: the model file has not arrived (D14)
  const r = await fetch(BASE + name, { credentials: 'same-origin' });
  if (r.status === 404) throw new Error(NOT_INSTALLED);
  if (!r.ok) throw new Error(NO_LOAD);
  return new Uint8Array(await r.arrayBuffer());
}
let mediapipe = null;
const mp = () => { // a failed import is not kept: the next request tries again
  if (!mediapipe) mediapipe = import(BASE + 'vision_bundle.mjs').catch(() => { mediapipe = null; throw new Error(NO_LOAD); });
  return mediapipe;
};

// ---- the tasks -----------------------------------------------------------------------------------------------------------
let ocr = null;
const textTask = {
  id: 'text', v: 1, input: 'both',
  load: guard(async () => {
    const T = (await import(BASE + 'tesseract.esm.min.js')).default;
    ocr = await T.createWorker('eng', 1, {
      workerPath: BASE + 'tesseract-worker.min.js', corePath: BASE + 'tesseract-core-simd-lstm.js', langPath: BASE,
      workerBlobURL: false, cacheMethod: 'none', gzip: false, logger: () => {}, errorHandler: () => {},
    });
  }),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src);
    const s = drawn(src, SIDE_MAX);
    const { data } = await ocr.recognize(s.c);
    const read = String((data && data.text) || '').replace(/[ \t]+\n/g, '\n').trim().slice(0, TEXT_MAX);
    return { data: { text: read, confidence: clamp(Number(data && data.confidence) / 100, 0, 1) }, quality };
  }),
  check: CHECKS.text,
};

let zx = null;
const codeOf = (format) => { const hit = ZX.find(([name]) => String(format).startsWith(name)); return hit ? hit[1] : null; };
const codeTask = {
  id: 'code', v: 1, input: 'both',
  load: guard(async () => {
    const Z = await script(BASE + 'zxing-reader.iife.js', 'ZXingWASM');
    await Z.prepareZXingModule({ overrides: { locateFile: (p, pre) => (p.endsWith('.wasm') ? BASE + 'zxing_reader.wasm' : pre + p) }, fireImmediately: true });
    zx = Z;
  }),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src);
    const s = drawn(src, SIDE_MAX);
    const found = await zx.readBarcodes(s.ctx.getImageData(0, 0, s.w, s.h), { tryHarder: true, maxNumberOfSymbols: 20 });
    const codes = (found || []).filter((r) => r && r.isValid !== false && codeOf(r.format))
      .map((r) => ({ format: codeOf(r.format), value: String(r.text || '').slice(0, TEXT_MAX) })).slice(0, 20);
    return { data: { codes }, quality };
  }),
  check: CHECKS.code,
};

let poser = null, finder = null;
const poseTask = {
  id: 'pose', v: 1, input: 'both', rate: 15,
  load: guard(async () => {
    const bytes = await model(POSE_MODEL);
    const V = await mp();
    poser = await V.PoseLandmarker.createFromOptions(MP_FILES, { baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', numPoses: 1 });
  }),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src);
    const r = poser.detectForVideo(src.img, performance.now());
    const points = ((r && r.landmarks && r.landmarks[0]) || []).slice(0, 33).map((p) => ({
      x: clamp(p.x, -1, 2), y: clamp(p.y, -1, 2), z: clamp(p.z, -10, 10), visibility: clamp(Number(p.visibility) || 0, 0, 1) }));
    return { data: { points }, quality };
  }),
  check: CHECKS.pose,
};
const objectsTask = {
  id: 'objects', v: 1, input: 'both', rate: 5,
  load: guard(async () => {
    const bytes = await model(OBJECT_MODEL);
    const V = await mp();
    finder = await V.ObjectDetector.createFromOptions(MP_FILES, { baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', scoreThreshold: 0.5, maxResults: 20 });
  }),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src);
    const r = finder.detectForVideo(src.img, performance.now());
    const objects = ((r && r.detections) || []).map((d) => {
      const c = (d.categories && d.categories[0]) || {}, b = d.boundingBox || {};
      return { label: String(c.categoryName || '').replace(/ /g, '_'), score: clamp(Number(c.score), 0, 1),
        box: { x: clamp(b.originX / src.w, 0, 1), y: clamp(b.originY / src.h, 0, 1), w: clamp(b.width / src.w, 0, 1), h: clamp(b.height / src.h, 0, 1) } };
    }).filter((o) => OBJECT_LABELS.includes(o.label)).slice(0, 50);
    return { data: { objects }, quality };
  }),
  check: CHECKS.objects,
};
const qualityTask = {
  id: 'quality', v: 1, input: 'both', rate: 2,
  run: (frame) => look(frame, async (src) => { const q = qualityOf(src); return { data: q, quality: q }; }),
  check: CHECKS.quality,
};

// ==== R13 Part D: the wardrobe's four tasks (docs/plans/r13-wardrobe.md D7-D9) ==========================================
// Run ONLY by the two named pixel panels (Camera and Camera -> Wardrobe: tests/test_r13_seams.py PANELS). Their results
// are checked like the others (the server's jarvis.vision.results WARDROBE_DATA) and are never kept vision results.
//   embed   MobileNet v2 int8, cut after its pool: the piece's fingerprint, uint8 x 1,280 (1,708 base64) and its model
//   colour  plain arithmetic: the box's centre in Lab, the nearest of 18 named colours; "multicolour" for two far apart
//   person  SSD-MobileNetV1 int8: "person" >= 0.5        } the check before a photo, a fingerprint or an AI tag is kept
//   face    UltraFace RFB-320: a face >= 0.7, after NMS  } or sent (D9); either one found refuses all three
// The model files come only from BASE13 (vendor/vision/r13-1/, served only when they match MANIFEST.json), the first
// time a task is used. The runtime is the wake word's own onnxruntime-web 1.30.0: the same module URL and the same
// env.wasm values (one thread, no proxy), so a page has one runtime (console-wakeword.js is not edited). Each load()
// runs its fixed self-check input (SELFCHECK below) and compares the answer with SELF13, the manifest's references:
// a mismatch is "not installed", so a quantized operator that runs wrongly on a phone is found and never trusted.
const BASE13 = '/static/vendor/vision/r13-1/';
const ORT_BASE = '/static/vendor/ort-1.30.0/';
const EMBED_MODEL = 'mobilenetv2-int8-embed.onnx';
const FACE_MODEL = 'version-RFB-320.onnx';
const PERSON_MODEL = 'ssd_mobilenet_v1_12-int8.onnx';
const INT8_SCALE = 0.019110053777694702; // 472_quantized: uint8, zero point 0 (the fp32 fallback would quantize with it)
const EMBED_DIMS = 1280, EMBED_B64 = 1708, EMBED_MODELS = ['mnv2-int8-1', 'mnv2-fp32-1'];
const PERSON_MIN = 0.5, FACE_MIN = 0.7, NMS_IOU = 0.3, BOXES_MAX = 20;
const COLOUR_SIDE = 96; // the colour is read on a copy this small
const SELF13 = Object.freeze(/*SELF13-BEGIN*/{"embed": {"sha256": "e5b53d7e5bf35dda17217bb1feed42f900451b5fe1f2db3eca1f50442bf15abd", "model": "mnv2-int8-1"}, "face": {"top": [0.07956, 0.07937, 0.07899, 0.07852, 0.07781], "tol": 0.002}, "person": {"class": 1, "score": 0.9449, "box": [0.1013, 0.2648, 0.8171, 0.7278], "tol": 0.03}}/*SELF13-END*/);
/*WARDROBE-PURE-BEGIN*/
// Plain arithmetic only (no DOM, no network): tests/fixtures/r13/models.mjs runs this very text in Node.
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
/*WARDROBE-PURE-END*/
const COLOUR_NAMES = Object.freeze(Object.keys(COLOURS13));
const SESSION = { executionProviders: ['wasm'], graphOptimizationLevel: 'all', logSeverityLevel: 3 };

// ---- their checks: exactly the server's WARDROBE_DATA -----------------------------------------------------------------
const B64 = /^[A-Za-z0-9+/]+=*$/;
const unitBox13 = (b) => only(b, ['x', 'y', 'w', 'h']) && ['x', 'y', 'w', 'h'].every((k) => inUnit(b[k]));
const foundOk = (d) => only(d, ['found', 'count', 'boxes']) && typeof d.found === 'boolean' && Number.isInteger(d.count)
  && d.count >= 0 && d.count <= BOXES_MAX && Array.isArray(d.boxes) && d.boxes.length === d.count && d.boxes.every(unitBox13)
  && d.found === d.count > 0;
const CHECKS13 = {
  embed: (d) => only(d, ['v', 'dims', 'model']) && typeof d.v === 'string' && d.v.length === EMBED_B64 && B64.test(d.v)
    && d.dims === EMBED_DIMS && EMBED_MODELS.includes(d.model),
  colour: (d) => only(d, ['name', 'second', 'share']) && (COLOUR_NAMES.includes(d.name) || d.name === 'multicolour')
    && (d.second === undefined || COLOUR_NAMES.includes(d.second)) && inUnit(d.share),
  person: foundOk,
  face: foundOk,
};

// ---- one runtime, the model files from JARVIS, the self-checks -----------------------------------------------------
let ortLoad = null;
const runtime = () => { // a failed import is not kept: the next use tries again
  if (!ortLoad) {
    ortLoad = import(ORT_BASE + 'ort.wasm.min.mjs').then((mod) => {
      const o = mod.InferenceSession ? mod : mod.default;
      o.env.wasm.numThreads = 1; o.env.wasm.proxy = false; o.env.wasm.wasmPaths = ORT_BASE; // the wake word's values
      return o;
    }, () => { ortLoad = null; throw new Error(NO_LOAD); });
  }
  return ortLoad;
};
async function model13(name) { // 404: the model file has not arrived (D8)
  const r = await fetch(BASE13 + name, { credentials: 'same-origin' });
  if (r.status === 404) throw new Error(NOT_INSTALLED);
  if (!r.ok) throw new Error(NO_LOAD);
  return new Uint8Array(await r.arrayBuffer());
}
const sessions = {};
async function open13(id, name, check) { // the session is kept only once its self-check matched SELF13
  const o = await runtime();
  const s = await o.InferenceSession.create(await model13(name), SESSION);
  let ok = false;
  try { ok = await check(o, s); } catch (_) { ok = false; }
  if (!ok) { try { await s.release(); } catch (_) {} throw new Error(NOT_INSTALLED); }
  sessions[id] = { o, s };
}
async function sha256hex(bytes) {
  if (!(crypto && crypto.subtle)) return ''; // no digest here: the check fails closed
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(h, (b) => b.toString(16).padStart(2, '0')).join('');
}
const CHECKS_AT_LOAD = {
  embed: async (o, s) => {
    const out = await s.run({ input: new o.Tensor('float32', ramp(3 * 224 * 224), [1, 3, 224, 224]) });
    return (await sha256hex(out['472_quantized'].data)) === SELF13.embed.sha256;
  },
  face: async (o, s) => {
    const out = await s.run({ input: new o.Tensor('float32', ramp(3 * 240 * 320), [1, 3, 240, 320]) });
    const top = topScores(out.scores.data, 5);
    return SELF13.face.top.every((v, i) => near(top[i], v, SELF13.face.tol));
  },
  person: async (o, s) => {
    const out = await s.run({ inputs: new o.Tensor('uint8', silhouette(), [1, 300, 300, 3]) });
    const ref = SELF13.person;
    return out.num_detections.data[0] >= 1 && Math.round(out.detection_classes.data[0]) === ref.class
      && near(out.detection_scores.data[0], ref.score, ref.tol) && ref.box.every((v, i) => near(out.detection_boxes.data[i], v, ref.tol));
  },
};
function sized(src, w, h) { // a canvas of this run only, exactly w x h (look() empties it when the run ends)
  const c = document.createElement('canvas');
  src.pads.push(c);
  c.width = w; c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src.img, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h).data;
}
function centreOf(box, w, h) { // the middle half of the box, in pixels of a w x h copy
  const b = box && unitBox13(box) ? box : { x: 0, y: 0, w: 1, h: 1 };
  const x0 = Math.floor((b.x + b.w / 4) * w), y0 = Math.floor((b.y + b.h / 4) * h);
  return { x: x0, y: y0, w: Math.max(1, Math.round(b.w / 2 * w)), h: Math.max(1, Math.round(b.h / 2 * h)) };
}

// ---- the four tasks -------------------------------------------------------------------------------------------------
const embedTask = {
  id: 'embed', v: 1, input: 'photo',
  load: guard(() => open13('embed', EMBED_MODEL, CHECKS_AT_LOAD.embed)),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src), { o, s } = sessions.embed;
    const out = await s.run({ input: new o.Tensor('float32', chw(sized(src, 224, 224), 224, 224, MEAN13, STD13), [1, 3, 224, 224]) });
    return { data: { v: b64(out['472_quantized'].data), dims: EMBED_DIMS, model: SELF13.embed.model }, quality };
  }),
  check: CHECKS13.embed,
};
const colourTask = {
  id: 'colour', v: 1, input: 'photo',
  run: (frame, opts) => look(frame, async (src) => {
    const quality = qualityOf(src), k = Math.min(1, COLOUR_SIDE / Math.max(src.w, src.h));
    const w = Math.max(1, Math.round(src.w * k)), h = Math.max(1, Math.round(src.h * k));
    const all = sized(src, w, h), c = centreOf(opts && opts.box, w, h), px = [];
    for (let y = c.y; y < Math.min(h, c.y + c.h); y += 1) for (let x = c.x; x < Math.min(w, c.x + c.w); x += 1) px.push(...all.subarray((y * w + x) * 4, (y * w + x) * 4 + 4));
    return { data: colourOf(px), quality };
  }),
  check: CHECKS13.colour,
};
const personTask = {
  id: 'person', v: 1, input: 'photo',
  load: guard(() => open13('person', PERSON_MODEL, CHECKS_AT_LOAD.person)),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src), { o, s } = sessions.person;
    const out = await s.run({ inputs: new o.Tensor('uint8', rgb(sized(src, 300, 300), 300 * 300), [1, 300, 300, 3]) });
    const boxes = personBoxes(out.detection_classes.data, out.detection_scores.data, out.detection_boxes.data, out.num_detections.data[0], PERSON_MIN, BOXES_MAX);
    return { data: found(boxes), quality };
  }),
  check: CHECKS13.person,
};
const faceTask = {
  id: 'face', v: 1, input: 'photo',
  load: guard(() => open13('face', FACE_MODEL, CHECKS_AT_LOAD.face)),
  run: (frame) => look(frame, async (src) => {
    const quality = qualityOf(src), { o, s } = sessions.face;
    const out = await s.run({ input: new o.Tensor('float32', chwFace(sized(src, 320, 240), 320 * 240), [1, 3, 240, 320]) });
    return { data: found(faceBoxes(out.scores.data, out.boxes.data, FACE_MIN, NMS_IOU, BOXES_MAX)), quality };
  }),
  check: CHECKS13.face,
};
function unload13() { // the page left: the three sessions go; the next use loads them again
  ['embed', 'person', 'face'].forEach((id) => {
    const t = tasks.get(id), got = sessions[id];
    delete sessions[id];
    if (t) { t.ready = false; t.loading = null; }
    if (got) { try { Promise.resolve(got.s.release()).catch(() => {}); } catch (_) {} }
  });
}
window.addEventListener('pagehide', unload13);

[textTask, codeTask, objectsTask, poseTask, qualityTask].forEach((t) => register(t));
[embedTask, colourTask, personTask, faceTask].forEach((t) => register(t)); // R13 D: before the seal
sealRegistry();

// When the page is left, the worker and the landmarkers are let go (a phone keeps no 100 MB it no longer needs); the
// next look loads them again.
function unload() {
  const gone = [[ocr, 'text', (o) => o.terminate()], [poser, 'pose', (o) => o.close()], [finder, 'objects', (o) => o.close()]];
  ocr = null; poser = null; finder = null;
  gone.forEach(([o, id, close]) => {
    const t = tasks.get(id);
    if (t) t.ready = false;
    if (o) { try { Promise.resolve(close(o)).catch(() => {}); } catch (_) {} }
  });
}
window.addEventListener('pagehide', unload);
