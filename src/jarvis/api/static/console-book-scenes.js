// src/jarvis/api/static/console-book-scenes.js -- R6 D15: scenes 1, 2, 12, 13 (the Core assembling, eight layers, the Core
// listening, the closing fold into a vault cube).
// ES module imported by console-book-3d.js. All facts come from book.show; none are hard-coded.
// Each builder takes the engine's kit {THREE, K (palette-role materials), facts, scene, ctx, motion(), core(mode), level}
// and returns {root, labels: [{text, obj, at, key?, cls?, align?}], reset(full)?, enter(beatIndex, lit, beat, ctx),
// update(t, dt, level)}. Unlit materials only; every colour is a palette role. Calm / Off: the end state at once.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
const ease = (x) => 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);
const fmt = (n) => { try { return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n); } catch (_) { return String(n); } };
const words = (f, max) => { const s = [f.value, f.label].filter(Boolean).join(' \u00b7 '); return s.length > max ? s.slice(0, max - 1) + '\u2026' : s; };

/** A rectangle outline in the XY plane, centred. */
function rect(K, w, h) {
  const x = w / 2, y = h / 2;
  return K.positions([-x, -y, 0, x, -y, 0, x, -y, 0, x, y, 0, x, y, 0, -x, y, 0, -x, y, 0, -x, -y, 0]);
}

// ---- 1 \u00b7 The build book: the Core assembles, the release's facts appear below it ---------------
function book(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [];
  const core = k.core(() => 'speaking');
  core.scene.position.set(0, 0.9, 0); root.add(core.scene);
  const facts = k.facts.slice(0, 6), n = facts.length, w = 1.9, gap = 0.22, x0 = -((n * w + (n - 1) * gap) / 2) + w / 2;
  const plane = K.geo(new THREE.PlaneGeometry(w, 0.95)), edge = rect(K, w, 0.95), tiles = [];
  facts.forEach((f, i) => {
    const g = new THREE.Group(), fill = K.mesh('bold', 'fill'), line = K.line('line');
    g.add(new THREE.Mesh(plane, fill), new THREE.LineSegments(edge, line));
    g.position.set(x0 + i * (w + gap), -2.55, 0); root.add(g); tiles.push({ g, fill, line });
    labels.push({ text: (f.value || (f.n !== null ? fmt(f.n) : '')) + '\n' + f.label, obj: g, at: new THREE.Vector3(0, 0, 0), key: i, cls: 'tile' });
  });
  let a = 1;
  return {
    root, labels,
    reset(full) { a = full ? 0 : 1; },
    enter(i, lit) {
      tiles.forEach((t, j) => { K.setRole(t.line, lit.has(j) ? 'lit' : 'line'); K.setRole(t.fill, 'bold', lit.has(j) ? 'litfill' : 'fill'); });
    },
    update(t, dt) {
      if (a < 1) a = dt > 0 ? Math.min(1, a + dt / 2.6) : 1;
      core.scene.scale.setScalar(0.25 + 0.95 * ease(a));
      core.scene.rotation.z = (1 - ease(a)) * 1.4;
      tiles.forEach((tile, j) => { const s = ease((a - 0.45 - j * 0.06) * 3); K.fade(tile.line, s); K.fade(tile.fill, s); });
    },
  };
}

// ---- 2 \u00b7 Eight layers: translucent plates stacked, a tick ring of module counts on each ------------
function layers(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], plates = [];
  root.rotation.x = 0.42;
  const facts = k.facts.slice(0, 9), n = facts.length, step = n > 1 ? 6.2 / (n - 1) : 0;
  const plane = K.geo(new THREE.PlaneGeometry(5.2, 1.5)), edge = rect(K, 5.2, 1.5);
  facts.forEach((f, i) => {
    const g = new THREE.Group(), fill = K.mesh('bold', 'fill'), line = K.line('line'), tick = K.line('soft');
    const body = new THREE.Group(); body.rotation.x = -Math.PI / 2; body.add(new THREE.Mesh(plane, fill), new THREE.LineSegments(edge, line));
    const count = Math.max(0, Math.min(60, Math.round(f.n || 0)));
    const ring = new THREE.LineSegments(count ? K.ticks(0.27, count, 0.11) : K.circle(0.27, 24), tick);
    ring.rotation.x = -root.rotation.x; ring.position.set(3.2, 0, 0.2); // faces the viewer: one tick a module
    g.add(body, ring); g.position.y = -3.1 + i * step; root.add(g);
    plates.push({ g, fill, line, tick, ring, y: g.position.y });
    labels.push({ text: words(f, 46) + (f.n !== null ? ' \u00b7 ' + fmt(f.n) : ''), obj: g, at: new THREE.Vector3(-2.5, 0, 0.8), key: i, align: 'left' });
  });
  let litNow = new Set();
  return {
    root, labels,
    enter(i, lit) {
      litNow = lit;
      plates.forEach((p, j) => {
        const on = lit.has(j);
        K.setRole(p.line, on ? 'lit' : 'line'); K.setRole(p.fill, 'bold', on ? 'litfill' : 'fill'); K.setRole(p.tick, on ? 'lit' : 'soft');
        if (!k.motion()) p.g.position.y = p.y + (on ? 0.14 : 0);
      });
    },
    update(t, dt) {
      if (dt <= 0) { plates.forEach((p, j) => { p.g.position.y = p.y + (litNow.has(j) ? 0.14 : 0); }); return; } // a still
      plates.forEach((p, j) => {
        p.ring.rotation.z += dt * (litNow.has(j) ? 0.9 : 0.12);
        const want = p.y + (litNow.has(j) ? 0.14 : 0);
        p.g.position.y += (want - p.g.position.y) * Math.min(1, dt * 4);
      });
    },
  };
}

// ---- 12 \u00b7 Questions: the Core listens (its halo breathes with the voice; it swells when JARVIS answers)
function questions(k) {
  const { THREE, K } = k, root = new THREE.Group();
  const core = k.core(() => (k.level() > 0.04 ? 'speaking' : 'listening'));
  core.scene.scale.setScalar(1.45); root.add(core.scene);
  const ring = new THREE.LineLoop(K.circle(3.3, 120), K.line('soft'));
  const ticks = new THREE.LineSegments(K.ticks(3.45, 48, 0.14), K.line('line'));
  root.add(ring, ticks);
  return {
    root, labels: [],
    enter() {},
    update(t, dt, lv) { if (dt > 0) { ticks.rotation.z -= dt * 0.08; ring.scale.setScalar(1 + 0.04 * lv); } },
  };
}

// ---- 13 \u00b7 Closing: the emblem folds into a sealed vault cube, the lock turns, everything fades -------
function closing(k) {
  const { THREE, K } = k, root = new THREE.Group();
  const core = k.core(() => 'speaking');
  root.add(core.scene);
  const cubeLine = K.line('bold'), cubeFill = K.mesh('bold', 'fill'), lockLine = K.line('lit');
  const box = K.geo(new THREE.BoxGeometry(2.4, 2.4, 2.4));
  const cube = new THREE.Group();
  cube.add(new THREE.LineSegments(K.geo(new THREE.EdgesGeometry(box)), cubeLine), new THREE.Mesh(box, cubeFill));
  cube.rotation.set(0.5, 0.6, 0); root.add(cube);
  const lock = new THREE.Group(), arc = [], at = (i) => [Math.cos(Math.PI * i / 16) * 0.3, 0.36 + Math.sin(Math.PI * i / 16) * 0.36, 0];
  for (let i = 0; i < 16; i += 1) arc.push(...at(i), ...at(i + 1));
  const shackle = new THREE.LineSegments(K.positions(arc), lockLine), key = new THREE.LineSegments(K.positions([0, -0.16, 0, 0, 0.16, 0]), lockLine);
  lock.add(new THREE.LineSegments(rect(K, 0.95, 0.72), lockLine), shackle, key);
  lock.position.set(0, 0, 1.6); root.add(lock);
  const state = { now: 0, want: 0 };
  const apply = (x) => {
    const fold = ease(x), fade = ease(x - 1);
    core.scene.scale.setScalar(1.2 - 0.85 * fold);
    cube.scale.setScalar(0.2 + 0.8 * fold);
    K.fade(cubeLine, fold * (1 - 0.85 * fade)); K.fade(cubeFill, fold * (1 - 0.85 * fade)); K.fade(lockLine, ease((x - 0.5) * 2) * (1 - 0.85 * fade));
    const shut = ease((x - 0.55) * 2.2); // the shackle drops shut and the key turns a quarter
    shackle.position.y = 0.22 * (1 - shut); key.rotation.z = -Math.PI / 2 * shut;
    core.scene.visible = fade < 0.95;
  };
  return {
    root, labels: [],
    reset() { state.now = 0; state.want = 0; apply(0); },
    enter(i) { state.want = Math.min(2, i); if (!k.motion()) { state.now = state.want; apply(state.now); } },
    update(t, dt) {
      if (dt <= 0) state.now = state.want; // a still shows where the line ends
      else if (state.now !== state.want) state.now = Math.min(state.want, state.now + dt / 1.3);
      apply(state.now);
      if (dt > 0) cube.rotation.y += dt * 0.15;
    },
  };
}

export const SCENES = Object.freeze({ 1: book, 2: layers, 12: questions, 13: closing });
