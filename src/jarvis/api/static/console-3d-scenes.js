// src/jarvis/api/static/console-3d-scenes.js — the three 3D scenes of the Command Deck (ES module).
// Each builder takes the THREE namespace (loaded lazily by console-3d.js) and returns
//   { scene, camera, update(t, dt), palette(p), state(s), dispose(), info }.
// All shapes are original and abstract: rings, ticks, polyhedra, a sphere. No figures, armour,
// emblems or film characters. Materials are unlit (MeshBasic / LineBasic / Points): cheapest path.
const TAU = Math.PI * 2;
const AMBER_NIGHT = '#F59E0B';
const AMBER_DAY = '#B45309';

// ---- shared helpers --------------------------------------------------------------------------
/** Material registry for one scene: colours come from palette roles, alert tints toward amber. */
function makeKit(THREE) {
  const mats = [], geos = [], texs = [];
  const tmpA = new THREE.Color(), tmpB = new THREE.Color();
  let pal = null, alertMix = 0;
  const ROLE = {
    line: (p) => (p.night ? p.accent2 : p.ink),
    bold: (p) => (p.night ? p.accent : p.accent),
    soft: (p) => (p.night ? p.accent : p.ink),
    core: (p) => (p.night ? p.accent2 : p.ink),
    dot: (p) => (p.night ? p.accent2 : p.accent),
    glow: (p) => (p.night ? p.accent : p.accent2),
  };
  function track(mat, role, night, day, alert) {
    mat.userData = { role, night, day, alert: alert || 0 };
    mats.push(mat); return mat;
  }
  function line(role, night, day, alert) {
    return track(new THREE.LineBasicMaterial({ transparent: true, depthWrite: false }), role, night, day, alert);
  }
  function mesh(role, night, day, alert) {
    return track(new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }), role, night, day, alert);
  }
  // Point sizes are CSS pixels (no attenuation): one renderer draws views of very different sizes,
  // and attenuated sizes would scale with the shared renderer's height instead of each view.
  function points(role, night, day, px, map) {
    const m = track(new THREE.PointsMaterial({ transparent: true, depthWrite: false, size: px, map, sizeAttenuation: false }), role, night, day, 0);
    m.userData.px = px; return m;
  }
  function sprite(role, night, day, map) {
    return track(new THREE.SpriteMaterial({ transparent: true, depthWrite: false, map }), role, night, day, 0.6);
  }
  function geo(g) { geos.push(g); return g; }
  function glowTexture() {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const x = c.getContext('2d');
    if (x) {
      const g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.25, 'rgba(255,255,255,.55)');
      g.addColorStop(0.6, 'rgba(255,255,255,.12)'); g.addColorStop(1, 'rgba(255,255,255,0)');
      x.fillStyle = g; x.fillRect(0, 0, 64, 64);
    }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; texs.push(t); return t;
  }
  function paint() {
    if (!pal) return;
    const amber = pal.night ? AMBER_NIGHT : AMBER_DAY;
    mats.forEach(m => {
      const u = m.userData;
      tmpA.set(ROLE[u.role](pal)); tmpB.set(amber);
      m.color.copy(tmpA).lerp(tmpB, alertMix * u.alert);
      m.opacity = pal.night ? u.night : u.day;
      const blend = pal.night ? THREE.AdditiveBlending : THREE.NormalBlending;
      if (m.blending !== blend) { m.blending = blend; m.needsUpdate = true; }
    });
  }
  return {
    line, mesh, points, sprite, geo, glowTexture,
    palette(p) { pal = p; paint(); },
    alert(m) { if (Math.abs(m - alertMix) > 0.001) { alertMix = m; paint(); } },
    pixelRatio(d) { mats.forEach(m => { if (m.userData.px) m.size = m.userData.px * d; }); },
    base(m) { return pal ? (pal.night ? m.userData.night : m.userData.day) : 1; },
    dispose() { geos.forEach(g => g.dispose()); mats.forEach(m => m.dispose()); texs.forEach(t => t.dispose()); },
  };
}
function circleGeo(THREE, r, n) {
  const p = [];
  for (let i = 0; i < n; i++) { const a = i / n * TAU; p.push(Math.cos(a) * r, Math.sin(a) * r, 0); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return g;
}
function ticksGeo(THREE, r, count, majorEvery, majorLen, minorLen) {
  const p = [];
  for (let i = 0; i < count; i++) {
    const a = i / count * TAU, l = i % majorEvery === 0 ? majorLen : minorLen, c = Math.cos(a), s = Math.sin(a);
    p.push(c * r, s * r, 0, c * (r - l), s * (r - l), 0);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return g;
}
function dashGeo(THREE, r, count, fill) {
  const p = [], seg = 4;
  for (let i = 0; i < count; i++) {
    const a0 = i / count * TAU, da = TAU / count * fill;
    for (let k = 0; k < seg; k++) {
      const a = a0 + da * k / seg, b = a0 + da * (k + 1) / seg;
      p.push(Math.cos(a) * r, Math.sin(a) * r, 0, Math.cos(b) * r, Math.sin(b) * r, 0);
    }
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); return g;
}
/** Edges + unique-vertex count of a polyhedron (the Construct panel shows these real numbers). */
function polyStats(geometry, edges) {
  const pos = geometry.getAttribute('position'), seen = new Set();
  for (let i = 0; i < pos.count; i++) seen.add(`${pos.getX(i).toFixed(3)},${pos.getY(i).toFixed(3)},${pos.getZ(i).toFixed(3)}`);
  return { vertices: seen.size, edges: edges.getAttribute('position').count / 2 };
}
const ease = (cur, target, dt, rate) => (dt <= 0 ? target : cur + (target - cur) * Math.min(1, dt * rate));
/** Shared idle / thinking / needs-you dynamics. */
function makeMood() {
  let speed = 1, alert = 0, busy = false, wantAlert = false;
  return {
    state(s) { busy = !!(s && s.busy); wantAlert = !!(s && s.alert); },
    step(dt) {
      speed = ease(speed, busy ? 3.2 : 1, dt, 2.5);
      alert = ease(alert, wantAlert && !busy ? 1 : 0, dt, 3);
      return { speed, alert, busy };
    },
  };
}

// ---- Core: tilted concentric rings with ticks, a faceted glowing core, orbiting particles ------
export function createCore(THREE) {
  const K = makeKit(THREE), mood = makeMood();
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50); camera.position.set(0, 0, 10);
  const glow = K.glowTexture();
  const rig = new THREE.Group(); rig.rotation.set(0.32, -0.18, 0); scene.add(rig);
  const add = (obj, parent = rig) => { parent.add(obj); return obj; };

  const halo = add(new THREE.Sprite(K.sprite('glow', 0.22, 0.1, glow)), scene); halo.scale.setScalar(5.4);
  const outerTicks = add(new THREE.LineSegments(K.geo(ticksGeo(THREE, 2.3, 180, 15, 0.17, 0.06)), K.line('line', 0.7, 0.75, 0.5)));
  add(new THREE.LineLoop(K.geo(circleGeo(THREE, 2.38, 160)), K.line('line', 0.32, 0.4)));
  const bold = add(new THREE.Group());
  [[0.15, 1.15], [1.5, 0.45], [2.15, 1.7], [4.05, 0.95], [5.15, 0.9]].forEach(([s, l], i) => {
    const r0 = i % 2 ? 2.0 : 2.02, w = i % 2 ? 0.035 : 0.07;
    bold.add(new THREE.Mesh(K.geo(new THREE.RingGeometry(r0, r0 + w, 64, 1, s, l)), K.mesh('bold', 0.95, 0.9, 1)));
  });
  const dashed = add(new THREE.LineSegments(K.geo(dashGeo(THREE, 1.86, 60, 0.45)), K.line('line', 0.55, 0.6)));
  const gyroA = add(new THREE.Group()), gyroB = add(new THREE.Group());
  gyroA.rotation.x = 1.15; gyroB.rotation.y = 1.2;
  const gyroLoopA = new THREE.LineLoop(K.geo(circleGeo(THREE, 1.62, 128)), K.line('soft', 0.5, 0.45));
  const gyroLoopB = new THREE.LineLoop(K.geo(circleGeo(THREE, 1.5, 128)), K.line('soft', 0.38, 0.35));
  gyroA.add(gyroLoopA); gyroB.add(gyroLoopB);
  const beads = new THREE.BufferGeometry();
  beads.setAttribute('position', new THREE.Float32BufferAttribute([1.62, 0, 0, -0.81, 1.403, 0, -0.81, -1.403, 0], 3));
  gyroLoopA.add(new THREE.Points(K.geo(beads), K.points('dot', 1, 0.9, 10, glow)));
  const innerTicks = add(new THREE.LineSegments(K.geo(ticksGeo(THREE, 1.3, 72, 6, 0.12, 0.05)), K.line('line', 0.6, 0.65, 0.6)));
  add(new THREE.LineLoop(K.geo(circleGeo(THREE, 1.08, 96)), K.line('line', 0.3, 0.35)));
  const sweep = add(new THREE.Mesh(K.geo(new THREE.CircleGeometry(1.06, 32, 0, 0.55)), K.mesh('glow', 0.16, 0.08)));
  const coreGroup = add(new THREE.Group(), scene);
  const ico = new THREE.IcosahedronGeometry(0.46, 1);
  coreGroup.position.y = 0.12; // the label sits just below the core
  const coreEdges = new THREE.LineSegments(K.geo(new THREE.EdgesGeometry(ico)), K.line('core', 1, 0.95, 1));
  const coreFill = new THREE.Mesh(K.geo(ico), K.mesh('bold', 0.12, 0.1, 1));
  const coreGlow = new THREE.Sprite(K.sprite('glow', 0.6, 0.26, glow)); coreGlow.scale.setScalar(1.9);
  coreGroup.add(coreGlow, coreFill, coreEdges);
  // three bands of particles orbiting at different speeds
  const bands = [[1.4, 1.75, 140, 0.32], [1.9, 2.2, 160, -0.2], [2.45, 2.7, 110, 0.12]].map(([r0, r1, n, w]) => {
    const p = [];
    for (let i = 0; i < n; i++) { const a = Math.random() * TAU, r = r0 + Math.random() * (r1 - r0); p.push(Math.cos(a) * r, Math.sin(a) * r, (Math.random() - 0.5) * 0.2); }
    const g = K.geo(new THREE.BufferGeometry()); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
    const pts = add(new THREE.Points(g, K.points('dot', 0.85, 0.55, 4.5, glow)));
    return { pts, w };
  });

  return {
    scene, camera,
    update(t, dt) {
      const m = mood.step(dt), k = dt * m.speed;
      outerTicks.rotation.z += 0.03 * k; bold.rotation.z -= 0.07 * k; dashed.rotation.z += 0.14 * k;
      gyroLoopA.rotation.z += 0.45 * k; gyroLoopB.rotation.z -= 0.32 * k;
      gyroA.rotation.y = Math.sin(t * 0.21) * 0.25; gyroB.rotation.x = Math.cos(t * 0.17) * 0.3;
      innerTicks.rotation.z -= 0.2 * k; sweep.rotation.z -= 1.1 * k;
      bands.forEach(b => { b.pts.rotation.z += b.w * k; });
      coreGroup.rotation.x += 0.22 * k; coreGroup.rotation.y += 0.31 * k;
      const pulse = m.busy ? 1 + 0.09 * Math.sin(t * 7.5) : 1 + 0.025 * Math.sin(t * 1.6);
      coreGroup.scale.setScalar(pulse);
      coreGlow.material.opacity = Math.min(1, K.base(coreGlow.material) * (m.busy ? 1.2 : 1));
      rig.rotation.y = -0.18 + Math.sin(t * 0.12) * 0.06;
      K.alert(m.alert);
    },
    palette(p) { K.palette(p); },
    pixelRatio(d) { K.pixelRatio(d); },
    state(s) { mood.state(s); },
    dispose() { K.dispose(); },
    info: {},
  };
}

// ---- Globe: graticule sphere + point cloud, the device's time-zone meridian, an orbit ring ----
export function createGlobe(THREE, opts = {}) {
  const K = makeKit(THREE), mood = makeMood();
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50); camera.position.set(0, 0.25, 4.6); camera.lookAt(0, 0, 0);
  const glow = K.glowTexture();
  const R = 0.95;
  const halo = new THREE.Sprite(K.sprite('glow', 0.2, 0.08, glow)); halo.scale.setScalar(3.2); scene.add(halo);
  const limb = new THREE.LineLoop(K.geo(circleGeo(THREE, R * 1.01, 120)), K.line('line', 0.75, 0.7)); scene.add(limb);
  const axis = new THREE.Group(); axis.rotation.z = 23.4 * Math.PI / 180; scene.add(axis);
  const globe = new THREE.Group(); axis.add(globe);
  const grat = [];
  for (let lat = -60; lat <= 60; lat += 20) {
    const phi = lat * Math.PI / 180, r = Math.cos(phi) * R, y = Math.sin(phi) * R;
    for (let i = 0; i < 64; i++) { const a = i / 64 * TAU, b = (i + 1) / 64 * TAU; grat.push(Math.cos(a) * r, y, Math.sin(a) * r, Math.cos(b) * r, y, Math.sin(b) * r); }
  }
  const meridian = (lonDeg, out) => {
    const lon = lonDeg * Math.PI / 180;
    for (let i = 0; i < 48; i++) {
      const a = -Math.PI / 2 + i / 48 * Math.PI, b = -Math.PI / 2 + (i + 1) / 48 * Math.PI;
      out.push(Math.cos(a) * Math.cos(lon) * R, Math.sin(a) * R, -Math.cos(a) * Math.sin(lon) * R,
        Math.cos(b) * Math.cos(lon) * R, Math.sin(b) * R, -Math.cos(b) * Math.sin(lon) * R);
    }
  };
  for (let lon = 0; lon < 360; lon += 20) meridian(lon, grat);
  const gg = K.geo(new THREE.BufferGeometry()); gg.setAttribute('position', new THREE.Float32BufferAttribute(grat, 3));
  globe.add(new THREE.LineSegments(gg, K.line('line', 0.26, 0.28)));
  // fibonacci point cloud
  const pts = [], N = 520;
  for (let i = 0; i < N; i++) {
    const y = 1 - (i + 0.5) / N * 2, r = Math.sqrt(1 - y * y), a = i * 2.39996;
    pts.push(Math.cos(a) * r * R, y * R, Math.sin(a) * r * R);
  }
  const pg = K.geo(new THREE.BufferGeometry()); pg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  globe.add(new THREE.Points(pg, K.points('dot', 0.55, 0.45, 3, glow)));
  // the device's time zone: UTC offset in hours x 15 degrees of longitude (honest, not a location)
  const tzLon = ((opts.offsetMin || 0) / 60) * 15;
  const tzLine = []; meridian(tzLon, tzLine);
  const tg = K.geo(new THREE.BufferGeometry()); tg.setAttribute('position', new THREE.Float32BufferAttribute(tzLine, 3));
  globe.add(new THREE.LineSegments(tg, K.line('bold', 1, 0.95, 1)));
  const mark = K.geo(new THREE.BufferGeometry());
  const lon = tzLon * Math.PI / 180;
  mark.setAttribute('position', new THREE.Float32BufferAttribute([Math.cos(lon) * R, 0, -Math.sin(lon) * R], 3));
  globe.add(new THREE.Points(mark, K.points('bold', 1, 1, 12, glow)));
  // orbit ring, dashed, with one bead
  const orbit = new THREE.Group(); orbit.rotation.set(1.22, 0, 0.32); scene.add(orbit);
  const ring = new THREE.LineSegments(K.geo(dashGeo(THREE, 1.24, 54, 0.55)), K.line('soft', 0.6, 0.5));
  orbit.add(ring);
  const bead = K.geo(new THREE.BufferGeometry()); bead.setAttribute('position', new THREE.Float32BufferAttribute([1.24, 0, 0], 3));
  ring.add(new THREE.Points(bead, K.points('dot', 1, 0.9, 8, glow)));
  globe.rotation.y = -lon + 0.6; // start with the time-zone meridian turned toward the viewer

  return {
    scene, camera,
    update(t, dt) {
      const m = mood.step(dt);
      globe.rotation.y += 0.16 * dt * m.speed; ring.rotation.z += 0.35 * dt * m.speed;
      K.alert(m.alert * 0.6);
    },
    palette(p) { K.palette(p); },
    pixelRatio(d) { K.pixelRatio(d); },
    state(s) { mood.state(s); },
    dispose() { K.dispose(); },
    info: { meridian: tzLon },
  };
}

// ---- Construct: nested wireframe polyhedra, a scanning plane, a projector base -----------------
export function createConstruct(THREE) {
  const K = makeKit(THREE), mood = makeMood();
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 50); camera.position.set(0, 0.9, 6.4); camera.lookAt(0, -0.15, 0);
  const glow = K.glowTexture();
  const body = new THREE.Group(); body.position.y = 0.15; scene.add(body);
  const solids = [
    [new THREE.IcosahedronGeometry(1.45, 0), 'line', 0.85, 0.85],
    [new THREE.DodecahedronGeometry(1.0, 0), 'soft', 0.7, 0.7],
    [new THREE.OctahedronGeometry(0.55, 0), 'core', 1, 0.95],
  ];
  let vertices = 0, edges = 0;
  const shells = solids.map(([g, role, on, od]) => {
    K.geo(g);
    const e = K.geo(new THREE.EdgesGeometry(g));
    const st = polyStats(g, e); vertices += st.vertices; edges += st.edges;
    const grp = new THREE.Group();
    grp.add(new THREE.LineSegments(e, K.line(role, on, od, 0.8)));
    const vp = K.geo(new THREE.BufferGeometry()); vp.setAttribute('position', e.getAttribute('position').clone());
    grp.add(new THREE.Points(vp, K.points('dot', 0.9, 0.7, 7, glow)));
    body.add(grp); return grp;
  });
  shells[2].add(new THREE.Mesh(solids[2][0], K.mesh('bold', 0.18, 0.14, 1)));
  const heart = new THREE.Sprite(K.sprite('glow', 0.7, 0.25, glow)); heart.scale.setScalar(1.3); body.add(heart);
  // scan plane: a translucent slab with a bright outline that sweeps up and down
  const scan = new THREE.Group(); scene.add(scan);
  const plane = new THREE.Mesh(K.geo(new THREE.PlaneGeometry(3.4, 3.4)), K.mesh('glow', 0.07, 0.05));
  plane.rotation.x = -Math.PI / 2; scan.add(plane);
  const edge = K.geo(new THREE.BufferGeometry());
  edge.setAttribute('position', new THREE.Float32BufferAttribute([-1.7, 0, -1.7, 1.7, 0, -1.7, 1.7, 0, 1.7, -1.7, 0, 1.7], 3));
  scan.add(new THREE.LineLoop(edge, K.line('line', 0.55, 0.5)));
  // projector base: concentric rings + radial ticks on the floor
  const base = new THREE.Group(); base.position.y = -1.85; scene.add(base);
  [0.55, 1.05, 1.6].forEach((r, i) => { const l = new THREE.LineLoop(K.geo(circleGeo(THREE, r, 96)), K.line('line', 0.5 - i * 0.12, 0.5 - i * 0.12)); l.rotation.x = -Math.PI / 2; base.add(l); });
  const bt = new THREE.LineSegments(K.geo(ticksGeo(THREE, 1.75, 48, 4, 0.18, 0.08)), K.line('soft', 0.45, 0.4)); bt.rotation.x = -Math.PI / 2; base.add(bt);
  const beam = []; for (let i = 0; i < 6; i++) { const a = i / 6 * TAU; beam.push(Math.cos(a) * 0.55, 0, Math.sin(a) * 0.55, Math.cos(a) * 0.12, 1.7, Math.sin(a) * 0.12); }
  const bg = K.geo(new THREE.BufferGeometry()); bg.setAttribute('position', new THREE.Float32BufferAttribute(beam, 3));
  base.add(new THREE.LineSegments(bg, K.line('soft', 0.2, 0.2)));

  return {
    scene, camera,
    update(t, dt) {
      const m = mood.step(dt), k = dt * m.speed;
      shells[0].rotation.y += 0.25 * k; shells[0].rotation.x += 0.07 * k;
      shells[1].rotation.y -= 0.36 * k; shells[1].rotation.z += 0.12 * k;
      shells[2].rotation.x += 0.6 * k; shells[2].rotation.y += 0.5 * k;
      scan.position.y = 0.15 + Math.sin(t * 0.8) * 1.45;
      base.rotation.y += 0.1 * k;
      body.position.y = 0.15 + Math.sin(t * 0.9) * 0.05;
      K.alert(m.alert * 0.7);
    },
    palette(p) { K.palette(p); },
    pixelRatio(d) { K.pixelRatio(d); },
    state(s) { mood.state(s); },
    dispose() { K.dispose(); },
    info: { polyhedra: shells.length, vertices, edges },
  };
}
