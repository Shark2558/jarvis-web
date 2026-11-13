// src/jarvis/api/static/console-vision.js -- R7 D13 (I0 core; Part B fills the tasks): the vision engine's ONE port.
// Tasks see pixels; use cases never do. Loaded by console-r7.js (an ES module); the same file runs on the phone and
// in the laptop browser. No task is built here: Part B registers text, code, objects, pose and quality.
//   JarvisVision.tasks()                      -> [{id, v, input: 'photo'|'live'|'both', ready, why}]
//   JarvisVision.run(task, source, opts)      -> Promise<Result>     one photo (a Blob, ImageBitmap or canvas)
//   JarvisVision.stream(task, opts, onResult) -> {stop()}            live, at the task's capped rate
//   JarvisVision.register(task)               a task = {id, v, input, rate?, load() -> Promise, run(frame, opts) -> data,
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

function register(task) {
  if (!task || !TASK_ID.test(task.id || '') || tasks.has(task.id)) return false;
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

function stream(id, opts, onResult) {
  const t = tasks.get(id);
  let on = !!t && t.input !== 'photo', timer = 0;
  const stop = () => { on = false; clearTimeout(timer); };
  if (!on) return { stop };
  const source = opts && typeof opts.frame === 'function' ? opts.frame : null; // the camera hands a frame per call
  const loop = async () => {
    if (!on || !source) return;
    const start = performance.now();
    try {
      const r = await run(id, source(), opts);
      if (on && typeof onResult === 'function') onResult(r);
    } catch (_) { stop(); return; }
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
  if (!frame) throw new Error('There is no picture to look at.');
  if (typeof Blob !== 'undefined' && frame instanceof Blob) {
    const bmp = await createImageBitmap(frame);
    return { img: bmp, w: bmp.width, h: bmp.height, done: () => bmp.close() };
  }
  const { w, h } = sizeOf(frame);
  if (!w || !h) throw new Error('There is no picture to look at.');
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
function script(src, global) {
  if (window[global]) return Promise.resolve(window[global]);
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.addEventListener('load', () => (window[global] ? resolve(window[global]) : reject(new Error(NO_LOAD))));
    s.addEventListener('error', () => reject(new Error(NO_LOAD)));
    document.head.append(s);
  });
}
async function model(name) { // 404: the model file has not arrived (D14)
  const r = await fetch(BASE + name, { credentials: 'same-origin' });
  if (r.status === 404) throw new Error(NOT_INSTALLED);
  if (!r.ok) throw new Error(NO_LOAD);
  return new Uint8Array(await r.arrayBuffer());
}
let mediapipe = null;
const mp = () => (mediapipe = mediapipe || import(BASE + 'vision_bundle.mjs'));

// ---- the tasks -----------------------------------------------------------------------------------------------------------
let ocr = null;
const textTask = {
  id: 'text', v: 1, input: 'both',
  load: async () => {
    let T;
    try { T = (await import(BASE + 'tesseract.esm.min.js')).default; } catch (_) { throw new Error(NO_LOAD); }
    ocr = await T.createWorker('eng', 1, {
      workerPath: BASE + 'tesseract-worker.min.js', corePath: BASE + 'tesseract-core-simd-lstm.js', langPath: BASE,
      workerBlobURL: false, cacheMethod: 'none', gzip: false, logger: () => {}, errorHandler: () => {},
    });
  },
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
  load: async () => {
    const Z = await script(BASE + 'zxing-reader.iife.js', 'ZXingWASM');
    await Z.prepareZXingModule({ overrides: { locateFile: (p, pre) => (p.endsWith('.wasm') ? BASE + 'zxing_reader.wasm' : pre + p) }, fireImmediately: true });
    zx = Z;
  },
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
  load: async () => {
    const bytes = await model(POSE_MODEL);
    const V = await mp();
    poser = await V.PoseLandmarker.createFromOptions(MP_FILES, { baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', numPoses: 1 });
  },
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
  load: async () => {
    const bytes = await model(OBJECT_MODEL);
    const V = await mp();
    finder = await V.ObjectDetector.createFromOptions(MP_FILES, { baseOptions: { modelAssetBuffer: bytes, delegate: 'CPU' }, runningMode: 'VIDEO', scoreThreshold: 0.5, maxResults: 20 });
  },
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
[textTask, codeTask, objectsTask, poseTask, qualityTask].forEach((t) => register(t));
