// src/jarvis/api/static/console-3d.js — 3D layer of the Command Deck (ES module, CSP script-src 'self').
// Loads the vendored three.js (MIT) only when WebGL2 works, then draws three scenes with ONE shared
// renderer: each scene renders into a corner of the offscreen renderer and is copied into its own
// on-page <canvas>, so panels can stack above or below any scene. If anything fails, the page keeps
// the 2D Core / globe / construct (html lacks the `gl-on` class) and every feature still works.
//
// Nothing loads until a 3D canvas is actually on screen: on phones (rails and stage hidden) three.js
// is never fetched and no GL context is created unless the owner opens the Construct tab.
// Budget: <= 30 fps, devicePixelRatio <= 1.5. A scene renders only while its canvas is on screen
// (IntersectionObserver) and the tab is visible; Motion Calm/Off renders still frames on change.
// Teardown releases everything at once: one AbortController owns every listener, and the GL
// context is force-released instead of waiting for garbage collection.
// Governor: content always wins over decoration. If the whole page sustains under ~22 fps while the
// scenes animate (a weak or software GPU), step down to 20 fps at DPR 1, then 12 fps, then retire the
// 3D layer and let the cheap CSS-animated 2D emblems take over. It never steps back up during a page
// load, so it cannot oscillate.
const TIERS = [{ fps: 30, dpr: 1.5 }, { fps: 20, dpr: 1 }, { fps: 12, dpr: 1 }];
const SLOW_GAP_MS = 45;     // average gap between page frames that counts as "struggling"
const WINDOW_MS = 2000;     // measurement window; two slow windows in a row => one step down
const root = document.documentElement;
const FX = window.JarvisFX;

function webgl2Works() {
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2');
    if (!gl) return false;
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext(); // release the probe context straight away
    return true;
  } catch (_) {
    return false;
  }
}

function palette() {
  const tk = FX.tokens(), night = FX.surface() === 'night';
  return { night, accent: tk.accent, accent2: tk.accent2, ink: tk.ink };
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el && el.textContent !== text) el.textContent = text;
}

/** `made` receives the renderer and the teardown as soon as they exist, so boot() can release a
 *  half-built engine if construction throws. */
function createEngine(THREE, S, made) {
  const ac = new AbortController();
  const on = { signal: ac.signal };
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  made.renderer = renderer;
  renderer.setPixelRatio(1); // we size in device pixels ourselves
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const gl = renderer.domElement;
  const views = [];
  const observers = [];
  let running = false, lost = false, last = 0, t = 0, shown = false, disposed = false;
  let fpsFrames = 0, fpsSince = 0;
  let tier = 0; // governor state
  const cadence = { prev: 0, sum: 0, n: 0, since: 0, slow: 0, warm: true };
  made.teardown = dispose;

  function addView(canvasId, build) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas ? canvas.getContext('2d') : null;
    if (!ctx) return null;
    const v = { id: canvasId, canvas, ctx, s: build(), visible: false, pw: 0, ph: 0, dpr: 1 };
    views.push(v);
    return v;
  }
  function sizeView(v) {
    const dpr = Math.min(TIERS[tier].dpr, window.devicePixelRatio || 1);
    const w = v.canvas.clientWidth, h = v.canvas.clientHeight;
    v.pw = Math.round(w * dpr); v.ph = Math.round(h * dpr); v.dpr = dpr;
    if (v.canvas.width !== v.pw) v.canvas.width = v.pw;
    if (v.canvas.height !== v.ph) v.canvas.height = v.ph;
    if (v.ph) { v.s.camera.aspect = v.pw / v.ph; v.s.camera.updateProjectionMatrix(); }
    v.s.pixelRatio(dpr);
    const needW = Math.max(1, ...views.map(x => x.pw)), needH = Math.max(1, ...views.map(x => x.ph));
    const size = renderer.getSize(new THREE.Vector2());
    if (size.x < needW || size.y < needH) renderer.setSize(Math.max(size.x, needW), Math.max(size.y, needH), false);
  }
  function renderView(v, dt) {
    if (!v.pw || !v.ph || lost) return;
    v.s.update(t, dt);
    renderer.setViewport(0, 0, v.pw, v.ph);
    renderer.setScissor(0, 0, v.pw, v.ph);
    renderer.setScissorTest(true);
    renderer.render(v.s.scene, v.s.camera);
    v.ctx.clearRect(0, 0, v.pw, v.ph);
    v.ctx.drawImage(gl, 0, gl.height - v.ph, v.pw, v.ph, 0, 0, v.pw, v.ph);
    if (!shown) { shown = true; root.classList.add('gl-on'); }
  }
  /** Returns false once the 3D layer has been retired (the caller must stop drawing). */
  function govern(now) {
    if (cadence.prev) { cadence.sum += now - cadence.prev; cadence.n++; }
    cadence.prev = now;
    if (now - cadence.since < WINDOW_MS) return true;
    const slow = cadence.n > 0 && cadence.sum / cadence.n > SLOW_GAP_MS;
    if (cadence.warm) cadence.warm = false; // the first window after a (re)start is warm-up
    else cadence.slow = slow ? cadence.slow + 1 : 0;
    Object.assign(cadence, { sum: 0, n: 0, since: now });
    if (cadence.slow < 2) return true;
    cadence.slow = 0;
    if (tier < TIERS.length - 1) { tier++; views.forEach(sizeView); return true; }
    retire(); // the 2D emblems take over
    return false;
  }
  function frame(now) {
    if (disposed || !govern(now)) return;
    if (now - last < 1000 / TIERS[tier].fps - 1) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now; t += dt;
    try {
      views.forEach(v => { if (v.visible) renderView(v, dt); });
    } catch (err) {
      fail(err);
      return;
    }
    fpsFrames++;
    if (now - fpsSince >= 1000) { setText('kFps', `${Math.round(fpsFrames * 1000 / (now - fpsSince))} fps`); fpsFrames = 0; fpsSince = now; }
  }
  /** One still frame of every visible scene (Motion Calm/Off, hidden-then-shown, theme changes). */
  function still() {
    if (lost || disposed) return;
    try { views.forEach(v => { if (v.visible) renderView(v, 0); }); } catch (err) { fail(err); }
  }
  function sync() {
    if (disposed) return;
    const should = !lost && FX.motion() === 'full' && !document.hidden && views.some(v => v.visible);
    if (should && !running) {
      running = true; last = performance.now(); fpsSince = last; fpsFrames = 0;
      Object.assign(cadence, { prev: 0, sum: 0, n: 0, since: last, slow: 0, warm: true });
      renderer.setAnimationLoop(frame);
    }
    if (!should && running) { running = false; renderer.setAnimationLoop(null); }
    if (!running) { still(); setText('kFps', FX.motion() === 'full' ? 'Paused' : 'Still'); }
  }
  /** Hand over to the 2D emblems for the rest of this page load (and free the GPU memory). */
  function retire() {
    dispose();
    root.classList.remove('gl-on');
    root.classList.add('gl-off');
    setText('kVerts', '13'); setText('kEdges', '13'); setText('kFps', 'CSS'); // the 2D preview's real counts
  }
  function fail(err) {
    // Decoration must never break the console.
    retire();
    if (window.console && console.warn) console.warn('JARVIS 3D disabled:', err && err.message ? err.message : err);
  }
  function dispose() {
    if (disposed) return;
    disposed = true; running = false;
    ac.abort(); // removes every document / window / canvas listener this engine added
    try { renderer.setAnimationLoop(null); } catch (_) { /* already gone */ }
    observers.forEach(o => o.disconnect());
    views.forEach(v => { try { v.s.dispose(); } catch (_) { /* best effort */ } });
    try { renderer.dispose(); } catch (_) { /* best effort */ }
    try { renderer.forceContextLoss(); } catch (_) { /* best effort */ }
  }

  gl.addEventListener('webglcontextlost', (e) => {
    if (disposed) return; // our own forceContextLoss() on teardown is not an outage
    e.preventDefault(); // allow the browser to restore it
    lost = true; running = false; renderer.setAnimationLoop(null);
    root.classList.remove('gl-on'); root.classList.add('gl-lost');
  }, on);
  gl.addEventListener('webglcontextrestored', () => {
    if (disposed) return;
    lost = false; shown = false; root.classList.remove('gl-lost');
    views.forEach(sizeView); sync();
  }, on);

  const tzOffset = -new Date().getTimezoneOffset();
  const core = addView('coreGL', () => S.createCore(THREE));
  addView('globeGL', () => S.createGlobe(THREE, { offsetMin: tzOffset }));
  const construct = addView('constructGL', () => S.createConstruct(THREE));
  if (construct) {
    setText('kVerts', String(construct.s.info.vertices));
    setText('kEdges', String(construct.s.info.edges));
  }
  const pal = palette(), mood = FX.state();
  views.forEach(v => { v.s.palette(pal); v.s.state(mood); });

  if (window.ResizeObserver) {
    const ro = new ResizeObserver(entries => {
      entries.forEach(en => { const v = views.find(x => x.canvas === en.target); if (v) sizeView(v); });
      if (!running) still();
    });
    views.forEach(v => ro.observe(v.canvas));
    observers.push(ro);
  }
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => { const v = views.find(x => x.canvas === en.target); if (v) v.visible = en.isIntersecting && en.boundingClientRect.width > 0; });
    sync();
  });
  views.forEach(v => { sizeView(v); io.observe(v.canvas); });
  observers.push(io);

  document.addEventListener('jarvis:theme', () => { const p = palette(); views.forEach(v => v.s.palette(p)); if (!running) still(); }, on);
  document.addEventListener('jarvis:state', (e) => { views.forEach(v => v.s.state(e.detail || {})); if (!running) still(); }, on);
  document.addEventListener('jarvis:motion', sync, on);
  document.addEventListener('visibilitychange', sync, on);
  window.addEventListener('pagehide', (e) => { if (!e.persisted) dispose(); }, on);
  return { core, sync };
}

async function boot() {
  if (!FX || !document.getElementById('coreGL')) return;
  if (!webgl2Works()) { root.classList.add('gl-off'); return; }
  let THREE, S;
  try {
    [THREE, S] = await Promise.all([
      import('/static/vendor/three-0.187.0/three.module.min.js'),
      import('./console-3d-scenes.js'),
    ]);
  } catch (err) {
    root.classList.add('gl-off');
    return;
  }
  const made = {};
  try {
    createEngine(THREE, S, made).sync();
  } catch (err) {
    if (made.teardown) made.teardown();
    else if (made.renderer) { try { made.renderer.dispose(); made.renderer.forceContextLoss(); } catch (_) { /* best effort */ } }
    root.classList.remove('gl-on');
    root.classList.add('gl-off');
  }
}

/** Run `start` once, when the first of these canvases is actually on screen. */
function whenAnyVisible(canvasIds, start) {
  const els = canvasIds.map(id => document.getElementById(id)).filter(Boolean);
  if (!els.length) return;
  if (!window.IntersectionObserver) { start(); return; }
  const io = new IntersectionObserver(entries => {
    if (!entries.some(en => en.isIntersecting && en.boundingClientRect.width > 0)) return;
    io.disconnect();
    start();
  });
  els.forEach(el => io.observe(el));
}

whenAnyVisible(['coreGL', 'globeGL', 'constructGL'], boot);
