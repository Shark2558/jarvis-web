// src/jarvis/api/static/console-vision-check.js -- R8 builder A (docs/plans/r8-vision.md 2.1 row 216, 4.8, D4). The setup
// test: an ENGINE file (tests/test_r13_seams.py ENGINE), so it may hand the engine frames. B's Cameras pane (and the
// workout pane, R8.1) calls it on a look he started with a tap:
//   run(taskIds, {seconds, rate, model}) -> Promise<{fps, ms, core, model, tasks: {id: {n, fps, ms, core}}}>
//     fps   the Results a second the slowest task kept       ms    one frame's look, milliseconds (the tasks together)
//     core  the share of one CPU core the look used (each task's frame time x its rate, summed; 0.1 = 10 %)
//     model the pose model kept ('lite' | 'full'; '' with no pose): with {model: 'full'} the full model is tried and
//           kept only if pose still keeps 15 a second with it (its look under FULL_MAX_MS), else lite again (D4)
//   choose(model) -> Promise<'lite' | 'full'>   puts a pose model the device's earlier test kept back in use
// Each task is loaded once before the timing starts (a model's first load is not a frame's look). Nothing is recorded,
// kept or sent: the numbers are handed back, and B's pane decides what to post as camera health. The camera is never
// started here: no tap-started look, no test. ASCII source.
const SECONDS = 20, SECONDS_MIN = 1, SECONDS_MAX = 120, TASKS_MAX = 4;
const FULL_MIN_FPS = 15; // D4: the full pose model only where it keeps 15 frames a second...
const FULL_MAX_MS = 1000 / (2 * FULL_MIN_FPS); // ...that is, where the engine never slows itself at 15 (console-vision.js
// stream(): a look that takes over half a frame's gap doubles the gap)
const CAMERA_TAP = 'The camera starts only from a tap.';
const CAMERA_STOPPED = 'The camera was stopped.';
const NO_TASK = 'Pick a vision task to test.';
const round = (v, k) => Math.round((Number.isFinite(v) ? v : 0) * k) / k;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let engine8 = null;
const r8 = () => { // the pose model's switch lives with the task bodies (one module, the engine's own copy)
  if (!engine8) engine8 = import('./console-vision-r8.js').catch((e) => { engine8 = null; throw e; });
  return engine8;
};

function parts() {
  const V = window.JarvisVision, C = window.JarvisCamera;
  if (!V || typeof V.stream !== 'function' || typeof V.run !== 'function') throw new Error('The vision tools are not loaded.');
  if (!C || typeof C.live !== 'function' || typeof C.frame !== 'function' || !C.live()) throw new Error(CAMERA_TAP);
  return { V, C };
}
function picked(V, taskIds) {
  const live = new Set(V.tasks().filter((t) => t.input !== 'photo').map((t) => t.id));
  const ids = Array.isArray(taskIds) ? [...new Set(taskIds.filter((x) => typeof x === 'string' && live.has(x)))] : [];
  if (!ids.length) throw new Error(NO_TASK);
  return ids.slice(0, TASKS_MAX);
}

/** Times the tasks together on the live camera for `seconds`; -> {fps, ms, core, tasks}. */
async function measure(V, C, ids, seconds, rate) {
  const frame = () => (C.live() ? C.frame() : null);
  for (const id of ids) await V.run(id, frame()); // the first load is not timed (a task that can't load says why)
  const per = {}, streams = [];
  ids.forEach((id) => { per[id] = { n: 0, ms: 0 }; });
  let failed = null, off = null;
  if (typeof C.onChange === 'function') off = C.onChange((d) => { if (!d || !d.live) failed = failed || new Error(CAMERA_STOPPED); });
  const began = performance.now();
  try {
    ids.forEach((id) => streams.push(V.stream(id, { frame, rate, onError: (e) => { failed = failed || e; } }, (r) => {
      if (r && r.ok) { per[id].n += 1; per[id].ms += r.ms; }
    })));
    while (!failed && performance.now() - began < seconds * 1000) await sleep(Math.min(250, seconds * 1000));
  } finally {
    streams.forEach((s) => s.stop());
    if (off) { try { off(); } catch (_) {} }
  }
  if (failed) throw failed;
  const took = Math.max(0.001, (performance.now() - began) / 1000), tasks = {};
  ids.forEach((id) => {
    const fps = per[id].n / took, ms = per[id].n ? per[id].ms / per[id].n : 0;
    tasks[id] = Object.freeze({ n: per[id].n, fps: round(fps, 10), ms: round(ms, 10), core: round((fps * ms) / 1000, 1000) });
  });
  const all = Object.values(tasks);
  return { fps: round(Math.min(...all.map((t) => t.fps)), 10), ms: round(all.reduce((s, t) => s + t.ms, 0), 10),
    core: round(all.reduce((s, t) => s + t.core, 0), 1000), tasks: Object.freeze(tasks) };
}

/** The setup test (see the top of this file). */
export async function run(taskIds, opts) {
  const o = opts || {}, { V, C } = parts(), ids = picked(V, taskIds);
  const seconds = Math.min(SECONDS_MAX, Math.max(SECONDS_MIN, Number(o.seconds) || SECONDS));
  const rate = Number(o.rate) > 0 ? Number(o.rate) : undefined;
  if (ids.includes('pose') && o.model === 'full') {
    const R = await r8();
    R.prefer('full');
    let got = null;
    try { got = await measure(V, C, ids, seconds, rate); } catch (e) { R.prefer('lite'); throw e; }
    if (R.preferred() === 'full' && got.tasks.pose.n && got.tasks.pose.ms <= FULL_MAX_MS) return Object.freeze({ ...got, model: 'full' });
    R.prefer('lite'); // too slow here, or the full model has not arrived: lite, measured again
  }
  const got = await measure(V, C, ids, seconds, rate);
  const model = ids.includes('pose') ? ((await r8()).preferred() || 'lite') : '';
  return Object.freeze({ ...got, model });
}

/** A pose model an earlier setup test on this device kept, put back in use ('lite' unless 'full'). */
export async function choose(model) { return (await r8()).prefer(model === 'full' ? 'full' : 'lite'); }
