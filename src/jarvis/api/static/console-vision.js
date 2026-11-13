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
