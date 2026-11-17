// src/jarvis/api/static/console-tryon-3d.js -- R13.1 Part B (docs/plans/r13-1-try-on.md D2, D5-D9): the free 3D figure
// of Helpers -> Wardrobe -> "Try it on" and of the card under "what should I wear?" (row 388). A plain grey mannequin
// shaped by seven morph weights, dressed in ready-made garment shapes coloured and textured from his own pieces. It is
// drawn on this device; nothing about it is sent or stored. The contract (tests/fixtures/r13_1/engine_contract.mjs):
//   window.JarvisTryOn3D = { supported() -> bool, mount(host, {release, onLost}) -> Stage }       (mount may throw)
//   Stage = { show(figures, opts) -> {drawn, approx, cards}, view(name), spin(on), zoom(step), closer(),
//             snapshot({caption}) -> Promise<Blob>, stats() -> {triangles, figures, fps, dpr, shadows, yaw}, dispose() }
// show() also answers `hidden` (worn but covered: a belt under an untucked top, the outer layer in "without the outer
// layer"), `forced` (slot -> the state drawn instead of the one asked: {top: 'tucked'} for a shirt over a wrap, which
// can only be drawn tucked; that slot's `approx` then names 'tuck'), `figures` (each figure's own answer when two are compared) and the Stage has `ready` (a promise: the
// first frame is drawn). One Stage at a time: dispose() frees the WebGL context, every listener, texture and buffer.
// CSP-clean: three.js only from the vendored file (no addon), our own GLB reader, turntable and lights; files only
// from /static/vendor/mannequin/<release>/, which the server checks against MANIFEST.json's SHA-256. Rendering is on demand (a
// change, a drag, the spin), never a loop at rest; device pixel ratio <= 1.5; the governor judges what each frame cost
// (never how often he touched a key) and steps down (shadows off and DPR 1), then retires 3D. Any failure calls onLost(reason) once: no WebGL2, a file missing or failing its sum,
// the context lost, the files over 30 s or the first frame over 10 s after them, the governor. Test hooks: window.__glFail = 'no-webgl2' | 'lost' |
// 'asset' | 'timeout'. A drawing module: it draws only on its own canvases and never calls the door's senders.
import { parse, join, geometry } from './console-tryon-glb.js';
import { plan, photoCloth, weave, contact, picture, LAYERS } from './console-tryon-cloth.js';

const THREE_URL = '/static/vendor/three-0.187.0/three.module.min.js';
const ASSETS = '/static/vendor/mannequin/';
const VIEWS = Object.freeze({ front: 0, side: 90, back: 180 });
const MORPHS = ['height', 'shoulders', 'chest', 'waist', 'hips', 'inseam', 'waist_down'];
const LABEL = 'Estimated from your measurements';
const BODY_GREY = 0xC3C9D2, BASE_GREY = 0x66748A; // preview v2's mannequin and base-layer greys (not theme colours)
const PITCH = [0.22 * Math.PI, 0.56 * Math.PI], PITCH0 = 0.468 * Math.PI;
const ZOOM_MAX = 4, GAP = 0.9, DPR_MAX = 1.5, SPIN_DEG_S = 40, MIN_H = 120;
const LOAD_MS = 30000, FIRST_MS = 10000; // the files may take 30 s to arrive (a phone link); then the first frame 10 s
const SLOW_MS = 45, WINDOW_MS = 2000, WINDOW_FRAMES = 8, AWAY_MS = 1000; // the governor (createGovernor)
const fail = () => (typeof window !== 'undefined' && window.__glFail) || '';
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const flag = (v) => (typeof v === 'boolean' ? v : undefined);

let probe = null;
function supported() {
  if (fail() === 'no-webgl2' || typeof document === 'undefined') return false;
  if (probe === null) {
    try {
      const gl = document.createElement('canvas').getContext('webgl2');
      probe = !!gl;
      const lose = gl && gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext(); // release the probe context straight away
    } catch (_) { probe = false; }
  }
  return probe;
}

/** The scene's state without a pixel: what is shown, from where. The Stage draws exactly this (AVT-02, AVT-08). */
function createModel() {
  const m = { figures: [], plans: [], opts: { tucked: undefined, open: undefined, layers: 'all' }, yaw: 0, pitch: PITCH0, zoom: 0, closer: false, spin: false };
  const answer = (p) => ({ drawn: p.drawn.slice(), approx: Object.assign({}, p.approx), cards: p.cards.slice(), hidden: p.hidden.slice(), forced: Object.assign({}, p.forced) });
  function show(figures, opts) {
    const list = Array.isArray(figures) ? figures.slice(0, 2).filter((f) => f && f.look) : [];
    if (!list.length) throw new Error('There is no look to show.');
    const o = opts || {};
    m.opts = { tucked: flag(o.tucked), open: flag(o.open), layers: LAYERS.includes(o.layers) ? o.layers : 'all' };
    m.figures = list.map((f) => {
      const w = {}, given = (f.body && f.body.weights) || {};
      for (const k of MORPHS) w[k] = clamp(Number(given[k]) || 0, -1.6, 1.6);
      return { weights: w, typed: Array.isArray(f.body && f.body.typed) ? f.body.typed.slice() : [], look: f.look };
    });
    m.plans = m.figures.map((f) => plan(f.look, m.opts));
    if (o.view !== undefined) view(o.view);
    const all = m.plans.map(answer);
    return Object.assign({}, all[0], { figures: all });
  }
  function view(name) {
    if (!Object.prototype.hasOwnProperty.call(VIEWS, name)) throw new Error('The view is front, side or back.');
    m.yaw = VIEWS[name]; // the pieces, tuck, open, layers and weights stay as they are
  }
  const turn = (deg, tilt) => { m.yaw = (((m.yaw + deg) % 360) + 360) % 360; m.pitch = clamp(m.pitch + (tilt || 0), PITCH[0], PITCH[1]); };
  const zoom = (step) => { m.zoom = clamp(m.zoom + (Number(step) || 0), 0, ZOOM_MAX); return m.zoom; };
  const closer = () => { m.closer = !m.closer; return m.closer; };
  const reset = () => { m.yaw = 0; m.pitch = PITCH0; m.zoom = 0; m.closer = false; };
  /** What a test may compare across views: pieces by slot, the styling state and the weights. */
  const identity = () => m.figures.map((f, i) => ({
    pieces: Object.fromEntries((f.look.slots || []).filter((s) => s && !s.private).map((s) => [s.slot, s.piece || null])),
    state: Object.assign({}, m.plans[i].state), weights: Object.assign({}, f.weights), drawn: m.plans[i].drawn.slice(), cards: m.plans[i].cards.slice(),
  }));
  return { state: m, show, view, turn, zoom, closer, reset, identity };
}

/** The performance governor, without a pixel (tests replay it). It judges what a frame COST: the wait for its turn
 *  (from the moment it was asked for to the moment the browser ran it) plus the drawing itself; never the gap between
 *  two frames, which with drawing on demand is only how often he touched a key. A window is at least `windowMs` and
 *  `frames` judged frames; its MEDIAN cost over `slowMs` makes it slow (one long frame is a hiccup). Two slow windows
 *  in a row: frame() answers 'down' once (shadows off, DPR 1), and after two more 'retire'. A wait over a second is
 *  the page being away (a hidden tab), not a frame. */
function createGovernor(o) {
  const { slowMs = SLOW_MS, windowMs = WINDOW_MS, frames = WINDOW_FRAMES } = o || {};
  let costs = [], start = 0, slow = 0, tier = 0, last = 0;
  const reset = () => { costs = []; slow = 0; };
  function frame(now, cost) {
    const wait = Number(cost && cost.wait) || 0, draw = Number(cost && cost.draw) || 0;
    if (wait > AWAY_MS || tier > 1) return 'ok';
    if (costs.length && now - start > 4 * windowMs) costs = []; // a stale window: too few frames to judge
    if (!costs.length) start = now;
    last = wait + draw;
    costs.push(last);
    if (costs.length < frames || now - start < windowMs) return 'ok';
    const mid = costs.sort((a, b) => a - b)[costs.length >> 1];
    costs = [];
    slow = mid > slowMs ? slow + 1 : 0;
    if (slow < 2) return 'ok';
    slow = 0; tier++;
    return tier === 1 ? 'down' : 'retire';
  }
  return { frame, reset, tier: () => tier, fps: () => (last > 0 ? Math.min(60, Math.round(1000 / last)) : 0) };
}

const FILES = ['body.glb', 'garments.glb']; // scripts/mannequin/build.py's two files of a release
const cache = new Map(); // release -> Promise of {meshes}: the files are immutable, parsed once a page
async function file(release, name) {
  // the server serves a file only when the release's MANIFEST.json lists it with a matching SHA-256 (else a 404)
  const r = await fetch(ASSETS + release + '/' + name, { credentials: 'same-origin' });
  if (!r.ok || fail() === 'asset') throw new Error(name + ' did not load or failed its check');
  return r.arrayBuffer();
}
function assets(release) {
  if (!cache.has(release)) {
    const job = (async () => ({ meshes: join((await Promise.all(FILES.map((n) => file(release, n)))).map(parse)) }))();
    job.catch(() => cache.delete(release)); // a failed load is tried afresh next time (Retry 3D)
    cache.set(release, job);
  }
  return cache.get(release);
}

function palette(host) {
  const FX = window.JarvisFX, css = getComputedStyle(host);
  let accent = css.getPropertyValue('--accent').trim() || '#00C2E0';
  try { if (FX && FX.tokens) accent = FX.tokens().accent || accent; } catch (_) { /* keep the CSS value */ }
  const night = FX && FX.surface ? FX.surface() === 'night' : document.documentElement.dataset.surface !== 'day';
  const bg = css.getPropertyValue('--panel-solid').trim() || css.getPropertyValue('--bg').trim() || (night ? '#0A111B' : '#FFFFFF');
  return { accent, night, bg, ink: css.color || (night ? '#E8EEF6' : '#10151C'), font: css.fontFamily || 'sans-serif' };
}
const motionOff = () => document.documentElement.dataset.motion === 'off';

/** The turntable: a drag turns (and tilts), a pinch or the wheel zooms, the arrow keys, + and -, Home, a double click
 *  or double tap. It never swallows the page's scrolling (review B-1, finding 5; the card under a chat reply): the
 *  wheel is the figure's only while a pointer is pressed on the canvas or the canvas has the focus, and only while
 *  the zoom can still move; a finger swiped up or down over an unfocused figure scrolls the page (touch-action pan-y),
 *  and a tap gives the figure the focus and every gesture (touch-action none) until he taps elsewhere. */
function controls(canvas, model, redraw, ac) {
  const pts = new Map(), on = { signal: ac.signal }, focused = () => document.activeElement === canvas;
  let pinch = 0, tapped = 0;
  const span = () => { const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  const touch = () => { canvas.style.touchAction = focused() ? 'none' : 'pan-y'; };
  touch();
  canvas.addEventListener('focus', touch, on);
  canvas.addEventListener('blur', touch, on);
  canvas.addEventListener('pointerdown', (e) => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* a synthetic pointer */ }
    if (pts.size === 2) pinch = span();
    if (pts.size === 1 && e.pointerType === 'touch') { if (e.timeStamp - tapped < 320) { model.reset(); redraw(); } tapped = e.timeStamp; }
  }, on);
  canvas.addEventListener('pointermove', (e) => {
    const p = pts.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y, tilts = e.pointerType !== 'touch' || focused();
    p.x = e.clientX; p.y = e.clientY;
    if (pts.size === 1) model.turn(-dx * 0.5, tilts ? -dy * 0.004 : 0);
    else if (pts.size === 2) { const s = span(); if (pinch > 0 && s > 0) model.zoom(Math.log(s / pinch) / Math.log(1.19)); pinch = s; }
    redraw();
  }, on);
  for (const type of ['pointerup', 'pointercancel']) canvas.addEventListener(type, (e) => { pts.delete(e.pointerId); pinch = 0; }, on);
  canvas.addEventListener('wheel', (e) => {
    if (!pts.size && !focused()) return; // only passing over: the page scrolls
    const before = model.state.zoom;
    if (model.zoom(-e.deltaY * 0.004) === before) return; // at a limit: the page's again
    e.preventDefault(); redraw();
  }, { signal: ac.signal, passive: false });
  canvas.addEventListener('dblclick', () => { model.reset(); redraw(); }, on);
  canvas.addEventListener('keydown', (e) => {
    const keys = { ArrowLeft: [-15, 0], ArrowRight: [15, 0], ArrowUp: [0, -0.08], ArrowDown: [0, 0.08] };
    if (keys[e.key]) model.turn(keys[e.key][0], keys[e.key][1]);
    else if (e.key === '+' || e.key === '=') model.zoom(1);
    else if (e.key === '-') model.zoom(-1);
    else if (e.key === 'Home') model.reset();
    else return;
    e.preventDefault(); redraw();
  }, on);
}

function createStage(host, release, onLost) {
  const model = createModel(), m = model.state, ac = new AbortController(), on = { signal: ac.signal };
  const canvas = document.createElement('canvas'), label = document.createElement('p');
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', '3D figure wearing this look. Drag or use the arrow keys to turn it; select it, then pinch, scroll or use plus and minus to zoom.');
  Object.assign(canvas.style, { display: 'block', width: '100%', outline: 'none' });
  label.className = 'sfine';
  label.textContent = LABEL;
  host.append(canvas, label);
  let T = null, A = null, renderer = null, scene = null, camera = null, key = null, pal = palette(host);
  const gov = createGovernor();
  let groups = [], owned = [], figureH = 1.75, dpr = 1, shadows = true;
  let raf = 0, timer = 0, dead = false, lost = false, drawnOnce = false, serial = 0;
  let triangles = 0, lastT = 0, askedAt = 0, warm = true; // warm: the next frame uploads or compiles, so it is not judged
  let readyOk, readyNo;
  const ready = new Promise((ok, no) => { readyOk = ok; readyNo = no; });
  ready.catch(() => {});

  function gone(reason) {
    if (lost || dead) return;
    lost = true;
    clearTimeout(timer); cancelAnimationFrame(raf); raf = 0;
    readyNo(new Error(reason));
    if (typeof onLost === 'function') { try { onLost(reason); } catch (_) { /* the page's handler is its own */ } }
  }

  function start(three, got) {
    T = three; A = got;
    renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.NeutralToneMapping;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFShadowMap;
    scene = new T.Scene();
    camera = new T.PerspectiveCamera(30, 1, 0.1, 30);
    scene.add(new T.HemisphereLight(0xFFFFFF, 0x3A4658, 0.95));
    key = new T.DirectionalLight(0xFFF6EA, 2.3); key.position.set(1.6, 3.2, 2.6);
    key.castShadow = true; key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 5; key.shadow.bias = -0.0004; key.shadow.normalBias = 0.012;
    Object.assign(key.shadow.camera, { left: -1.3, right: 1.3, top: 2.2, bottom: -0.2, near: 0.5, far: 9 });
    key.target.position.set(0, 0.9, 0);
    scene.add(key, key.target);
    for (const [colour, power, x, y, z] of [[0xDCE8FF, 0.9, -2.4, 1.6, 2.2], [0x9FE2FF, 0.55, -2, 2.2, -2.5], [0xFFFFFF, 1.25, 1.4, 2.8, -2.6]]) {
      const l = new T.DirectionalLight(colour, power); l.position.set(x, y, z); scene.add(l); // fill, rim, back
    }
    canvas.addEventListener('webglcontextlost', (e) => { if (!dead) { e.preventDefault(); gone('lost'); } }, on);
    if (timer) { clearTimeout(timer); timer = setTimeout(() => gone('timeout'), FIRST_MS); } // the files are in: now the frame's ten seconds
    size();
    if (m.figures.length) rebuild();
  }

  function size() {
    if (!renderer) return;
    const css = getComputedStyle(label), line = label.offsetHeight + (parseFloat(css.marginTop) || 0) + (parseFloat(css.marginBottom) || 0);
    const w = Math.max(1, host.clientWidth), h = Math.max(1, Math.round(clamp(host.clientHeight - line, MIN_H, 1200))); // the label and its margin stay inside the host
    dpr = gov.tier() ? 1 : Math.min(window.devicePixelRatio || 1, DPR_MAX);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    canvas.style.height = h + 'px';
    camera.aspect = w / h; camera.updateProjectionMatrix();
    warm = true;
    invalidate();
  }

  function material(part) {
    const side = T.DoubleSide;
    if (part.kind === 'body') return new T.MeshStandardMaterial({ color: BODY_GREY, roughness: 0.62 });
    if (part.kind === 'base') return new T.MeshStandardMaterial({ color: BASE_GREY, roughness: 0.85, side });
    if (part.kind === 'steel') return new T.MeshStandardMaterial({ color: 0xD3D8DF, roughness: 0.3, metalness: 0.35 });
    if (part.kind === 'button') return new T.MeshStandardMaterial({ color: 0xF4F1E8, roughness: 0.45 });
    if (part.kind === 'sole') return new T.MeshStandardMaterial({ color: 0x2A1D16, roughness: 0.7 });
    const colour = new T.Color().setRGB(part.rgb[0] / 255, part.rgb[1] / 255, part.rgb[2] / 255, T.SRGBColorSpace);
    return new T.MeshStandardMaterial({ color: colour, roughness: part.kind === 'leather' ? 0.5 : 0.92, side });
  }
  function texture(source, metres) {
    const tex = new T.CanvasTexture(source);
    tex.wrapS = tex.wrapT = T.RepeatWrapping; tex.colorSpace = T.SRGBColorSpace; tex.anisotropy = 4;
    tex.repeat.set(1 / metres, 1 / metres);
    owned.push(tex);
    return tex;
  }
  function dress(mat, part, mesh, mine) {
    if (part.kind !== 'cloth' || !mesh.uv) return;
    const drawn = weave(part.rgb, part.pattern);
    mat.map = texture(drawn.canvas, drawn.tile); mat.color.set(0xFFFFFF);
    if (!part.photo) return;
    photoCloth(part.photo).then((c) => { // his own crop, when it can be read; else the colour stays
      if (!c || dead || mine !== serial) return;
      mat.map = texture(c, 2 * part.tile); mat.needsUpdate = true; invalidate();
    });
  }

  function rebuild() {
    for (const g of groups) scene.remove(g);
    for (const o of owned) o.dispose();
    groups = []; owned = [];
    const mine = ++serial, two = m.figures.length > 1;
    if (m.plans.some((p) => p.parts.some((part) => !A.meshes[part.name]))) { gone('asset'); return; } // a part is missing: never a figure with a hole
    figureH = 0; triangles = 0;
    m.figures.forEach((f, i) => {
      const group = new T.Group(), worn = new T.Group();
      let low = Infinity, high = -Infinity;
      for (const part of m.plans[i].parts) {
        const mesh = A.meshes[part.name];
        const geo = geometry(T, mesh, Object.assign({}, f.weights, part.weights)), mat = material(part);
        dress(mat, part, mesh, mine);
        owned.push(geo, mat);
        const obj = new T.Mesh(geo, mat);
        obj.castShadow = obj.receiveShadow = true; obj.frustumCulled = false;
        triangles += mesh.index.length / 3;
        low = Math.min(low, geo.boundingBox.min.y); high = Math.max(high, geo.boundingBox.max.y);
        worn.add(obj);
      }
      worn.position.y = -low; // whatever is on the feet stands on the floor
      figureH = Math.max(figureH, high - low);
      const ring = new T.Mesh(new T.RingGeometry(0.36, 0.367, 96), new T.MeshBasicMaterial({ color: pal.accent, transparent: true, opacity: 0.55, side: T.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.y = 0.002; ring.name = 'ring';
      const shade = new T.Mesh(new T.PlaneGeometry(0.7, 0.62), new T.MeshBasicMaterial({ map: texture(contact(), 1), transparent: true, depthWrite: false }));
      shade.rotation.x = -Math.PI / 2; shade.position.set(0, 0.001, 0.02);
      owned.push(ring.geometry, ring.material, shade.geometry, shade.material);
      group.add(worn, ring, shade);
      group.userData.worn = worn;
      group.position.x = two ? (i ? GAP / 2 : -GAP / 2) : 0;
      scene.add(group); groups.push(group);
    });
    warm = true; gov.reset();
    invalidate();
  }

  function aim() {
    const t = Math.tan((camera.fov * Math.PI) / 360), wide = m.figures.length > 1 ? 1.0 + GAP : 1.0;
    const fit = Math.max((figureH * 1.2) / (2 * t), wide / (2 * t * camera.aspect));
    const dist = fit * Math.max(0.28, (m.closer ? 0.5 : 1) * Math.pow(0.84, m.zoom));
    const ty = figureH * (m.closer ? 0.8 : 0.5);
    camera.position.set(0, ty + dist * Math.cos(m.pitch), dist * Math.sin(m.pitch));
    camera.lookAt(0, ty, 0);
    for (const g of groups) g.userData.worn.rotation.y = (-m.yaw * Math.PI) / 180; // camera yaw = the figure turned the other way
  }

  /** The governor's step for a frame that cost `wait` + `draw` ms (review B-1, finding 2: the cost, not the cadence). */
  function govern(now, wait, draw) {
    if (warm) { warm = false; return; }
    const step = gov.frame(now, { wait, draw });
    if (step === 'down') { shadows = false; renderer.shadowMap.enabled = false; key.castShadow = false; size(); }
    if (step === 'retire') gone('slow');
  }

  function frame(now) {
    raf = 0;
    if (dead || lost || !renderer || !groups.length) return;
    if (!drawnOnce && fail() === 'timeout') return; // the test hook: the first frame never finishes
    const wait = Math.max(0, now - askedAt), t0 = performance.now();
    if (m.spin && !motionOff()) { const dt = lastT ? Math.min(100, now - lastT) : 16; model.turn((dt / 1000) * SPIN_DEG_S); }
    lastT = now;
    aim();
    renderer.render(scene, camera);
    govern(now, wait, performance.now() - t0);
    if (lost) return;
    if (!drawnOnce) { drawnOnce = true; clearTimeout(timer); readyOk(); if (fail() === 'lost') { gone('lost'); return; } }
    if (m.spin && !motionOff()) invalidate();
  }
  function invalidate() { if (!raf && !dead && !lost) { askedAt = performance.now(); raf = requestAnimationFrame(frame); } }

  function repaint() {
    pal = palette(host);
    for (const g of groups) g.children.forEach((o) => { if (o.name === 'ring') o.material.color.set(pal.accent); });
    invalidate();
  }

  controls(canvas, model, invalidate, ac);
  document.addEventListener('jarvis:theme', repaint, on);
  document.addEventListener('jarvis:motion', invalidate, on);
  document.addEventListener('visibilitychange', () => gov.reset(), on);
  window.addEventListener('pagehide', (e) => { if (!e.persisted) dispose(); }, on);
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(size) : null;
  if (ro) ro.observe(host);
  Promise.all([import(THREE_URL), assets(release)]).then(([three, got]) => { if (!dead && !lost) start(three, got); })
    .catch(() => gone('asset'));

  function show(figures, opts) {
    const res = model.show(figures, opts);
    if (!drawnOnce && !timer && !lost) timer = setTimeout(() => gone('timeout'), renderer ? FIRST_MS : LOAD_MS);
    if (renderer && !lost) rebuild();
    return res;
  }
  const act = (fn) => (...args) => { const out = fn(...args); invalidate(); return out; };
  function snapshot(o) {
    if (!renderer || lost || dead || !groups.length) return Promise.reject(new Error('The 3D view is not showing a look.'));
    aim();
    renderer.render(scene, camera); // drawn and copied in the same task, so the drawing buffer is still there
    return picture(canvas, (o && o.caption) || [], pal);
  }
  function stats() {
    return { triangles, figures: m.figures.length, fps: gov.fps(), dpr, shadows, yaw: m.yaw, pitch: m.pitch, zoom: m.zoom, closer: m.closer, spin: m.spin,
      state: dead ? 'disposed' : lost ? 'lost' : drawnOnce ? 'ready' : 'loading', label: LABEL, looks: model.identity() };
  }
  function dispose() {
    if (dead) return;
    dead = true;
    ac.abort(); clearTimeout(timer); cancelAnimationFrame(raf);
    if (ro) ro.disconnect();
    for (const o of owned) { try { o.dispose(); } catch (_) { /* best effort */ } }
    owned = []; groups = [];
    if (renderer) { try { renderer.dispose(); renderer.forceContextLoss(); } catch (_) { /* best effort */ } }
    canvas.remove(); label.remove();
    if (!drawnOnce) readyNo(new Error('disposed'));
  }
  return { show, view: act(model.view), spin: act((v) => { m.spin = !!v; lastT = 0; }), zoom: act(model.zoom), closer: act(model.closer),
    snapshot, stats, dispose, ready };
}

function mount(host, opts) {
  const o = opts || {};
  if (!host || typeof host.append !== 'function') throw new Error('The 3D view needs a place on the page.');
  if (!supported()) throw new Error('This device cannot draw the 3D view.');
  if (!/^[a-z0-9]{1,12}$/.test(String(o.release || ''))) throw new Error('The 3D view needs its release.');
  return createStage(host, o.release, o.onLost);
}

const engine = Object.freeze({ supported, mount });
if (typeof window !== 'undefined') window.JarvisTryOn3D = engine;
export { supported, mount, createModel, createGovernor, VIEWS, LABEL };
export default engine;
