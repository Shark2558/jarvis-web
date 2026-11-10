// src/jarvis/api/static/console-book-3d.js -- R6 D15 (book.html): the show's 3D engine and governor
// (ES module; <= 30 fps, DPR <= 1.5, <= 150 draw calls, console-3d's governor tiers, full teardown at
// close). three.js only from /static/vendor/three-0.187.0/three.module.min.js. The scene modules are
// loaded from here, never by a page tag.
// Nothing loads on a narrow window (< 900 px: the 2D show, no GL context) or without WebGL2. Materials are unlit and
// coloured by palette roles from JarvisFX.tokens() (the console's own accents; amber is console-3d's pair). The Core is
// console-3d-scenes.js createCore, unchanged. One scene is built when first shown and kept until the close; only the
// current one is visible. Labels are <= 24 HTML spans over the canvas (textContent), projected each drawn frame.
// Motion Full: <= 30 fps with a short camera move into each scene. Calm / Off / prefers-reduced-motion: no animation loop
// at all -- one still per beat, camera cuts, no particles. The governor (a copy of console-3d.js's tiers) steps down
// when the page struggles and finally retires the 3D layer: the show goes on as 2D cards (mount's onRetire).
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
// window.JarvisBook3D = { ready: Promise<boolean>, mount({canvas, labels, level, onRetire}) -> engine|null, stats() }
export const SCENE_MODULES = Object.freeze([
  './console-book-scenes.js', './console-book-scenes-flow.js', './console-book-scenes-data.js',
]);
const THREE_URL = '/static/vendor/three-0.187.0/three.module.min.js';
const TIERS = [{ fps: 30, dpr: 1.5 }, { fps: 20, dpr: 1 }, { fps: 12, dpr: 1 }];
const MIN_WIDTH = 900, MAX_DRAW_CALLS = 150, MAX_LABELS = 24, SLOW_GAP_MS = 45, WINDOW_MS = 2000;
const FRAME_W = 13, FRAME_H = 7.4, DOLLY_S = 1.1;
const AMBER = { night: '#F59E0B', day: '#B45309' };
const KIND = { 1: 'core', 2: 'plates', 3: 'flow', 4: 'grid', 5: 'flow', 6: 'flow', 7: 'grid', 8: 'flow', 9: 'tags', 10: 'bars', 11: 'grid', 12: 'core', 13: 'core' };
const FX = window.JarvisFX;
const stats = { state: 'loading', contexts: 0, running: false, frames: 0, calls: 0, labels: 0, dpr: 0, tier: 0, scene: 0, over: 0 };

/** The three scene modules, loaded when the show starts. */
export function loadScenes() {
  return Promise.all([
    import('./console-book-scenes.js'),
    import('./console-book-scenes-flow.js'),
    import('./console-book-scenes-data.js'),
  ]);
}

function webgl2Works() {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    if (!gl) return false;
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext(); // the probe gives its context back at once
    return true;
  } catch (_) { return false; }
}
/** Palette roles from the console's own tokens (the engine never starts without JarvisFX). */
function palette() {
  const tk = FX.tokens(), night = FX.surface() === 'night';
  return { night, accent: tk.accent, accent2: tk.accent2, ink: tk.ink, amber: night ? AMBER.night : AMBER.day };
}
const fullMotion = () => !FX || FX.motion() === 'full';

// palette roles (night | day colour) and looks (night, day opacity), as console-3d-scenes.js colours its Core
const ROLE = { line: (p) => (p.night ? p.accent2 : p.ink), bold: (p) => p.accent, soft: (p) => (p.night ? p.accent : p.ink),
  lit: (p) => (p.night ? p.accent2 : p.accent), dim: (p) => (p.night ? p.accent2 : p.ink), amber: (p) => p.amber };
const OPACITY = { line: [0.55, 0.6], bold: [0.95, 0.9], soft: [0.3, 0.28], lit: [1, 1], dim: [0.2, 0.22], amber: [0.95, 0.95],
  fill: [0.1, 0.07], litfill: [0.26, 0.16], glow: [0.5, 0.22], faint: [0.035, 0.03], litfaint: [0.09, 0.06] };
/** Materials by palette role, so a theme or surface change repaints every scene at once. */
function makeKit(THREE) {
  const mats = [], geos = [], texs = [], tmp = new THREE.Color();
  let pal = palette();
  function paint(m) {
    const u = m.userData;
    tmp.set(ROLE[u.role](pal)); m.color.copy(tmp);
    m.opacity = (pal.night ? u.o[0] : u.o[1]) * u.k;
    const blend = pal.night ? THREE.AdditiveBlending : THREE.NormalBlending;
    if (m.blending !== blend) { m.blending = blend; m.needsUpdate = true; }
  }
  function track(m, role, look) {
    m.userData = { role, o: OPACITY[look || role] || OPACITY.line, k: 1 };
    mats.push(m); paint(m); return m;
  }
  const base = { transparent: true, depthWrite: false };
  let glowTex = null;
  function glow() {
    if (glowTex) return glowTex;
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const x = c.getContext('2d');
    if (x) {
      const g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.3, 'rgba(255,255,255,.5)'); g.addColorStop(1, 'rgba(255,255,255,0)');
      x.fillStyle = g; x.fillRect(0, 0, 64, 64);
    }
    glowTex = new THREE.CanvasTexture(c); glowTex.colorSpace = THREE.SRGBColorSpace; texs.push(glowTex); return glowTex;
  }
  const geo = (g) => { geos.push(g); return g; };
  function positions(p) { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return geo(g); }
  return {
    line: (role, look) => track(new THREE.LineBasicMaterial(base), role, look),
    mesh: (role, look) => track(new THREE.MeshBasicMaterial(Object.assign({ side: THREE.DoubleSide }, base)), role, look),
    sprite: (role, look) => track(new THREE.SpriteMaterial(Object.assign({ map: glow() }, base)), role, look || 'glow'),
    /** Fade one material (0..1) on top of its role's opacity. */
    fade: (m, k) => { if (Math.abs(m.userData.k - k) > 0.001) { m.userData.k = k; paint(m); } },
    setRole: (m, role, look) => { m.userData.role = role; m.userData.o = OPACITY[look || role] || OPACITY.line; paint(m); },
    geo, positions,
    circle(r, n) { const p = []; for (let i = 0; i < n; i += 1) { const a = i / n * Math.PI * 2; p.push(Math.cos(a) * r, Math.sin(a) * r, 0); } return positions(p); },
    ticks(r, count, len) {
      const p = [];
      for (let i = 0; i < count; i += 1) { const a = i / count * Math.PI * 2, c = Math.cos(a), s = Math.sin(a); p.push(c * r, s * r, 0, c * (r + len), s * (r + len), 0); }
      return positions(p);
    },
    repaint(p) { pal = p; mats.forEach(paint); },
    palette: () => pal,
    dispose() { geos.forEach((g) => g.dispose()); mats.forEach((m) => m.dispose()); texs.forEach((t) => t.dispose()); },
  };
}

/** What a beat lights: the facts its focus names (label, value, group or 1-based place); a flow walks a step a beat. */
function litSet(facts, beat, kind) {
  const f = String(beat && beat.focus || '').toLowerCase(), on = new Set();
  if (f) facts.forEach((x, i) => { if ([x.label, x.value, x.group].some((v) => v && v.toLowerCase() === f) || String(i + 1) === f) on.add(i); });
  else if (kind === 'flow' && facts.length) on.add(Math.min(beat ? beat.i : 0, facts.length - 1));
  return on;
}

/** <= 24 labels over the canvas (textContent), each pinned to a point of its object, projected per drawn frame. */
function labelLayer(THREE, host, canvas, camera) {
  const v = new THREE.Vector3();
  let list = [];
  return {
    set(items) {
      host.textContent = '';
      list = items.slice(0, MAX_LABELS).map((l) => {
        const el = document.createElement('span');
        el.className = 'sh-lbl' + (l.cls ? ' ' + l.cls : ''); el.textContent = l.text;
        host.append(el); return Object.assign({ el }, l);
      });
      stats.labels = list.length;
    },
    light(lit) { list.forEach((l) => l.el.classList.toggle('on', l.key !== undefined && lit.has(l.key))); },
    place() {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      list.forEach((l) => {
        v.copy(l.at); l.obj.localToWorld(v); v.project(camera);
        const x = Math.max(4, Math.min(w - l.el.offsetWidth - 4, (v.x + 1) / 2 * w - (l.align === 'left' ? 0 : l.el.offsetWidth / 2)));
        const y = Math.max(4, Math.min(h - l.el.offsetHeight - 4, (1 - v.y) / 2 * h - l.el.offsetHeight / 2));
        l.el.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
        l.el.style.visibility = v.z > 1 ? 'hidden' : '';
      });
    },
    clear() { list = []; host.textContent = ''; },
  };
}
/** console-3d.js's governor: two slow windows in a row step down a tier; past the last tier, retire.
 *  tick(now) -> 'ok' | 'step' (a tier lower now) | 'retire'. */
function governor() {
  const c = { prev: 0, sum: 0, n: 0, since: 0, slow: 0, warm: true };
  return {
    restart(now) { Object.assign(c, { prev: 0, sum: 0, n: 0, since: now, slow: 0, warm: true }); },
    tick(now) {
      if (c.prev) { c.sum += now - c.prev; c.n += 1; }
      c.prev = now;
      if (now - c.since < WINDOW_MS) return 'ok';
      const slow = c.n > 0 && c.sum / c.n > SLOW_GAP_MS;
      if (c.warm) c.warm = false; else c.slow = slow ? c.slow + 1 : 0;
      Object.assign(c, { sum: 0, n: 0, since: now });
      if (c.slow < 2) return 'ok';
      c.slow = 0;
      return stats.tier < TIERS.length - 1 ? 'step' : 'retire';
    },
  };
}

function createEngine(THREE, builders, createCore, o) {
  const canvas = o.canvas;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
  stats.contexts += 1;
  try { return engineOn(THREE, builders, createCore, o, renderer); } catch (err) {
    try { renderer.dispose(); renderer.forceContextLoss(); } catch (_) { /* best effort */ }
    throw err;
  }
}
function engineOn(THREE, builders, createCore, o, renderer) {
  const ac = new AbortController(), on = { signal: ac.signal }, canvas = o.canvas;
  renderer.setClearColor(0x000000, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  const K = makeKit(THREE), built = new Map(), cores = [], labels = labelLayer(THREE, o.labels, canvas, camera), gov = governor();
  let cur = null, curN = 0, tier = 0, running = false, disposed = false, held = false, t = 0, last = 0, zBase = 14, zFrom = 0, dollyT = 1;
  const level = typeof o.level === 'function' ? o.level : () => 0;

  /** The console's Core, as console-3d.js draws it: `mode()` is 'speaking' (it swells with the narration) or 'listening'. */
  function core(mode) {
    const c = createCore(THREE, { voice: () => ({ mode: typeof mode === 'function' ? mode() : 'speaking', level: level() }) });
    c.palette(K.palette()); c.pixelRatio(stats.dpr || 1); c.state({});
    if (!fullMotion()) c.scene.traverse((n) => { if (n.isPoints) n.visible = false; }); // reduced motion: no particles
    cores.push(c); return c;
  }
  function size() {
    const dpr = Math.min(TIERS[tier].dpr, window.devicePixelRatio || 1), w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    const tan = Math.tan(camera.fov * Math.PI / 360);
    zBase = Math.max(FRAME_H / (2 * tan), FRAME_W / (2 * tan * camera.aspect));
    stats.dpr = dpr; cores.forEach((c) => c.pixelRatio(dpr));
  }
  function enter(sc, ctx) {
    if (cur) cur.root.visible = false;
    if (!built.has(sc.n)) {
      const make = builders[sc.n];
      if (!make) return false;
      const kit = { THREE, K, scene: sc, facts: sc.facts, ctx: ctx || {}, motion: fullMotion, core, level };
      const s = make(kit); scene.add(s.root); built.set(sc.n, s);
    }
    cur = built.get(sc.n); curN = sc.n; cur.root.visible = true; stats.scene = sc.n;
    if (cur.reset) cur.reset(fullMotion());
    labels.set(cur.labels || []);
    if (fullMotion()) { zFrom = zBase * 1.22; dollyT = 0; } else dollyT = 1;
    return true;
  }
  function show(sc, i, beat, ctx) {
    if (disposed) return;
    if (sc.n !== curN && !enter(sc, ctx)) return;
    const lit = litSet(sc.facts, Object.assign({}, beat, { i }), KIND[sc.n]);
    if (cur.enter) cur.enter(i, lit, beat || {}, ctx || {});
    labels.light(lit);
    if (!running) still();
  }
  function draw(dt) {
    if (!cur || disposed) return;
    t += dt;
    if (dollyT < 1) dollyT = dt > 0 ? Math.min(1, dollyT + dt / DOLLY_S) : 1;
    const e = 1 - Math.pow(1 - dollyT, 3);
    camera.position.set(fullMotion() ? Math.sin(t * 0.11) * 0.35 : 0, 0, zFrom + (zBase - zFrom) * e);
    if (dollyT >= 1) camera.position.z = zBase;
    camera.lookAt(0, 0, 0);
    cur.update(t, dt, level());
    cores.forEach((c) => { if (c.scene.parent && c.scene.parent.visible !== false && isShown(c.scene)) c.update(t, dt); });
    renderer.render(scene, camera);
    stats.calls = renderer.info.render.calls; stats.frames += 1;
    if (stats.calls > MAX_DRAW_CALLS) stats.over += 1;
    labels.place();
  }
  function isShown(n) { for (let x = n; x; x = x.parent) if (!x.visible) return false; return true; }
  function still() { try { draw(0); } catch (err) { fail(err); } }
  function frame(now) {
    if (disposed) return;
    const g = gov.tick(now);
    if (g === 'retire') { retire(); return; }
    if (g === 'step') { tier += 1; stats.tier = tier; size(); }
    if (now - last < 1000 / TIERS[tier].fps - 1) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    try { draw(dt); } catch (err) { fail(err); }
  }
  function sync() {
    if (disposed) return;
    const should = fullMotion() && !document.hidden && !held; // a paused show holds still (WCAG 2.2.2)
    if (should && !running) { running = true; last = performance.now(); gov.restart(last); renderer.setAnimationLoop(frame); }
    if (!should && running) { running = false; renderer.setAnimationLoop(null); }
    stats.running = running;
    if (!running) still();
  }
  function retire() { dispose(); stats.state = 'retired'; if (typeof o.onRetire === 'function') o.onRetire(); }
  function fail(err) { retire(); if (window.console && console.warn) console.warn('Build book 3D off:', err && err.message ? err.message : err); }
  function dispose() {
    if (disposed) return;
    disposed = true; running = false; stats.running = false;
    ac.abort();
    try { renderer.setAnimationLoop(null); } catch (_) { /* gone */ }
    built.forEach((s) => { try { if (s.dispose) s.dispose(); } catch (_) { /* best effort */ } });
    cores.forEach((c) => { try { c.dispose(); } catch (_) { /* best effort */ } });
    built.clear(); cores.length = 0; labels.clear();
    K.dispose();
    try { renderer.dispose(); } catch (_) { /* best effort */ }
    try { renderer.forceContextLoss(); } catch (_) { /* best effort */ }
    stats.state = 'closed';
  }
  canvas.addEventListener('webglcontextlost', (e) => { if (!disposed) { e.preventDefault(); retire(); } }, on);
  document.addEventListener('jarvis:theme', () => { const p = palette(); K.repaint(p); cores.forEach((c) => c.palette(p)); if (!running) still(); }, on);
  document.addEventListener('jarvis:motion', sync, on);
  document.addEventListener('visibilitychange', sync, on);
  const ro = new ResizeObserver(() => { if (window.innerWidth < MIN_WIDTH) { retire(); return; } size(); if (!running) still(); });
  ro.observe(canvas);
  ac.signal.addEventListener('abort', () => ro.disconnect());
  size(); sync();
  stats.state = 'on';
  return { show, dispose, hold(on) { held = !!on; sync(); }, stats: () => Object.assign({}, stats) };
}

async function boot() {
  if (!FX || window.innerWidth < MIN_WIDTH) { stats.state = 'narrow'; return null; }
  if (!webgl2Works()) { stats.state = 'no-webgl2'; return null; }
  try {
    const [THREE, core, mods] = await Promise.all([import(THREE_URL), import('./console-3d-scenes.js'), loadScenes()]);
    const builders = Object.assign({}, ...mods.map((m) => m.SCENES || {}));
    return { THREE, builders, createCore: core.createCore };
  } catch (_) { stats.state = 'load-failed'; return null; }
}
let lib = null, engine = null;
const ready = boot().then((x) => { lib = x; return !!x; });
window.JarvisBook3D = Object.freeze({
  ready,
  /** The engine on the show's canvas, or null (the show then runs as 2D cards). */
  mount(o) {
    if (engine) return engine;
    if (!lib || !o || !o.canvas || !o.labels || window.innerWidth < MIN_WIDTH) return null;
    try { engine = createEngine(lib.THREE, lib.builders, lib.createCore, o); } catch (err) { stats.state = 'failed'; engine = null; }
    return engine;
  },
  stats: () => Object.assign({}, stats),
});
