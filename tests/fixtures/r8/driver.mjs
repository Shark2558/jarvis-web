// tests/fixtures/r8/driver.mjs -- R8.1 I1 join (docs/plans/r8-integration/R81-I1-NOTES.md): R8.1's use cases through
// the REAL port core. console-vision.js runs in a vm with a fake camera and a fake `pose` task that reports the scripted
// bodies; the use case registers with the real JarvisVision.use; a virtual clock drives the driver's own timers; the
// pane's setup goes in through live(..., {setup}) exactly as the Workout pane passes it (S2's contract line from R8's
// join: it rides on every Result as r.setup). Builder H's partnerDriver (tests_sequences.mjs) is the same harness for
// row 240; this one serves any module. Synthetic bodies only, never a real person's.
//   drive(o) o: {file, id, scene(t) -> [{track, who, points}], seconds, setup, rate, target, base, tag}
//            -> {errors, tracks, tallies: [{track, view, tally, who}], frames, setups: [the distinct r.setup, as JSON]}
import fs from 'node:fs';
import vm from 'node:vm';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const plainOut = (v) => JSON.parse(JSON.stringify(v));
let loads = 0;

function core(clock, timers) { // the port core, its seal lifted only so the fake pose task can take the real one's place
  const src = fs.readFileSync(new URL('console-vision.js', STATIC), 'utf8');
  const cut = src.replace(/\nsealRegistry\(\);\n?/, '\n').replace("id: 'pose', v: 2,", "id: 'pose-shell', v: 2,");
  if (cut === src || !cut.includes("id: 'pose-shell'")) throw new Error('the port core changed shape: update drive()');
  const ctx = { navigator: { userAgent: 'Android' }, console, performance: clock, addEventListener: () => {},
    setTimeout: (fn, ms) => { timers.push({ at: clock.now() + Math.max(0, Number(ms) || 0), fn }); return timers.length; },
    clearTimeout: () => {}, document: { createElement: () => ({ getContext: () => null }), head: { append() {} } } };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(cut, ctx, { filename: 'console-vision.js' });
  return ctx;
}

export async function drive(o) {
  const opt = Object.assign({ seconds: 10, rate: 10, target: { kind: 'all' }, tag: '' }, o || {});
  let now = 0;
  const timers = [];
  const clock = { now: () => now };
  const ctx = core(clock, timers);
  const V = ctx.JarvisVision;
  V.register({ id: 'pose', v: 2, input: 'both', rate: 15,
    run: (f) => { if (!f) throw new Error('There is no picture to look at.'); return { data: { bodies: opt.scene(now / 1000) } }; },
    check: (d) => !!d && Array.isArray(d.bodies) });
  ctx.JarvisCamera = { live: () => true, frame: () => ({ w: 1 }), onChange: () => () => {} };
  const setups = new Set();
  let frames = 0;
  const realPerf = Object.getOwnPropertyDescriptor(globalThis, 'performance');
  Object.defineProperty(globalThis, 'performance', { value: clock, configurable: true, writable: true });
  globalThis.JarvisVision = Object.freeze({ use: (u) => V.use({ id: u.id, tasks: u.tasks, summary: u.summary,
    onResult: (r, s) => { frames += 1; setups.add(JSON.stringify(r.setup === undefined ? null : r.setup)); return u.onResult(r, s); } }) });
  const errors = [], id = String(opt.id || '');
  try {
    loads += 1;
    const base = opt.base ? new URL(`file://${opt.base.replace(/\/?$/, '/')}`) : STATIC;
    await import(new URL(`${opt.file}?drive=${loads}${opt.tag}`, base).href);
    const h = V.live(['pose'], { uses: [id], rate: opt.rate, target: opt.target, setup: opt.setup,
      onError: (e) => errors.push(String(e && e.message)) });
    while (now < opt.seconds * 1000) {
      await new Promise((r) => setImmediate(r));
      timers.sort((a, b) => a.at - b.at);
      const next = timers.shift();
      if (!next) break;
      now = next.at;
      next.fn();
    }
    await new Promise((r) => setImmediate(r));
    h.end();
  } finally {
    if (realPerf) Object.defineProperty(globalThis, 'performance', realPerf);
  }
  const tracks = plainOut(V.tracks(id));
  const tallies = tracks.map((tr) => Object.assign({ track: tr.track }, plainOut(V.tally(id, tr.track))));
  return plainOut({ errors, tracks, tallies, frames, setups: [...setups] });
}
