// src/jarvis/api/static/console-book-scenes-data.js -- R6 D15: scenes 4, 7, 9, 10, 11 (memory and privacy, home, stack and
// licences, costs, not built yet).
// ES module imported by console-book-3d.js. All facts come from book.show; none are hard-coded.
// 4: the vault as sealed chunk cubes (instanced) and the keyring root branching to its purposes (facts of group
// 'purpose'; the others label the vault). 7: the home boundary, its nodes inside (group 'home'), the laptop at the edge
// (group 'edge'), everything else outside; only the edge talks out. 9: library tags orbiting on one ring per role
// (group), flagged licences amber and in words. 10: rupee bars on a log scale (n = rupees; free ones flat), the owner's
// month against his limit. 11: dimmed nodes labelled "later". Labels <= 24 a scene; colours are palette roles.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
const MAX = 24;
const FLAG = { copyleft: 'Copyleft', non_commercial: 'Non-commercial' };
const fmt = (n) => { try { return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n); } catch (_) { return String(n); } };
const cut = (s, max) => (s.length > max ? s.slice(0, max - 1) + '\u2026' : s);
const text = (f, max) => cut([f.label, f.value].filter(Boolean).join(' \u00b7 '), max);

function node(k, at, role) {
  const { THREE, K } = k, g = new THREE.Group(), edge = K.line(role || 'line'), fill = K.mesh('bold', 'fill');
  const octa = K.geo(new THREE.OctahedronGeometry(0.26, 0));
  g.add(new THREE.LineSegments(K.geo(new THREE.EdgesGeometry(octa)), edge), new THREE.Mesh(octa, fill));
  g.position.set(...at);
  return { g, edge, fill };
}
function light(K, items, lit, base) {
  items.forEach((n, j) => { const on = lit.has(n.key === undefined ? j : n.key); K.setRole(n.edge, on ? 'lit' : base || 'line'); if (n.fill) K.setRole(n.fill, 'bold', on ? 'litfill' : 'fill'); n.on = on; });
}

// ---- 4 \u00b7 Memory and privacy -------------------------------------------------------------------------
function memory(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], items = [];
  const purposes = [], vault = [];
  k.facts.forEach((f, i) => ((f.group || '').toLowerCase() === 'purpose' ? purposes : vault).push(i));
  // the vault: 4 x 3 x 2 sealed chunks, one instanced draw for the faces and one for every edge
  const cube = K.geo(new THREE.BoxGeometry(0.62, 0.62, 0.62)), m = new THREE.Matrix4(), edges = [];
  const fill = K.mesh('bold', 'faint'), cubes = new THREE.InstancedMesh(cube, fill, 24), edgeMat = K.line('line'); // 24 faces: a faint fill
  const unit = K.geo(new THREE.EdgesGeometry(cube)).getAttribute('position').array;
  let c = 0;
  for (let x = 0; x < 4; x += 1) for (let y = 0; y < 3; y += 1) for (let z = 0; z < 2; z += 1) {
    const at = [-4.6 + x * 0.78, -0.9 + y * 0.78, -z * 0.78];
    m.makeTranslation(...at); cubes.setMatrixAt(c, m); c += 1;
    for (let i = 0; i < unit.length; i += 3) edges.push(unit[i] + at[0], unit[i + 1] + at[1], unit[i + 2] + at[2]);
  }
  const vaultG = new THREE.Group(); vaultG.add(cubes, new THREE.LineSegments(K.positions(edges), edgeMat)); vaultG.rotation.y = 0.35; root.add(vaultG);
  const vaultItem = { edge: edgeMat, key: vault.length ? vault[0] : -1 };
  items.push(vaultItem);
  vault.slice(0, 3).forEach((i, j) => labels.push({ text: text(k.facts[i], 40), obj: vaultG, at: new THREE.Vector3(-3.4, 1.8 + j * 0.5, 0), key: i }));
  // the keyring root and its purposes
  const rootNode = node(k, [1.1, 0, 0], 'bold'); root.add(rootNode.g);
  const branches = [], n = Math.min(purposes.length, 14);
  for (let j = 0; j < n; j += 1) {
    const a = -1.15 + 2.3 * (n > 1 ? j / (n - 1) : 0.5), at = [1.1 + 3.6 * Math.cos(a), 3.0 * Math.sin(a), 0];
    branches.push(1.1, 0, 0, ...at);
    const p = node(k, at); p.key = purposes[j]; root.add(p.g); items.push(p);
    labels.push({ text: cut(k.facts[purposes[j]].label, 28), obj: p.g, at: new THREE.Vector3(0.42, 0, 0), key: purposes[j], align: 'left' });
  }
  if (branches.length) root.add(new THREE.LineSegments(K.positions(branches), K.line('soft')));
  return {
    root, labels,
    enter(i, lit) { light(K, items, lit); K.setRole(fill, 'bold', vaultItem.on ? 'litfaint' : 'faint'); },
    update(t, dt) { if (dt > 0) { rootNode.g.rotation.y += dt * 0.6; items.forEach((p) => { if (p.g) p.g.rotation.y += dt * (p.on ? 1.2 : 0.2); }); } },
  };
}

// ---- 7 \u00b7 Home: the laptop at the edge; faces and the camera stay home --------------------------------
function home(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], items = [];
  const R = 2.7, cx = -1.6;
  root.add(new THREE.LineLoop(K.circle(R, 120), K.line('bold')), new THREE.LineSegments(K.ticks(R + 0.05, 60, 0.12), K.line('soft')));
  root.children.forEach((o) => { o.position.x = cx; });
  const inside = [], edge = [], out = [];
  k.facts.slice(0, MAX).forEach((f, i) => { const g = (f.group || '').toLowerCase(); (g === 'home' ? inside : g === 'edge' ? edge : out).push(i); });
  const put = (i, at) => {
    const n = node(k, at); n.key = i; root.add(n.g); items.push(n);
    labels.push({ text: text(k.facts[i], 30), obj: n.g, at: new THREE.Vector3(0, -0.55, 0), key: i });
    return at;
  };
  inside.forEach((i, j) => { const a = (j / Math.max(1, inside.length)) * Math.PI * 2 + 0.4, r = inside.length > 1 ? 1.35 : 0; put(i, [cx + r * Math.cos(a), r * Math.sin(a), 0]); });
  const links = [];
  const edgeAt = edge.map((i, j) => {
    const a = -0.25 + j * 0.5, at = [cx + R * Math.cos(a), R * Math.sin(a), 0], n = node(k, at, 'bold');
    const lap = new THREE.LineSegments(K.geo(new THREE.EdgesGeometry(K.geo(new THREE.BoxGeometry(0.9, 0.08, 0.6)))), n.edge);
    lap.position.set(...at); lap.rotation.x = 0.5; root.add(lap);
    n.key = i; items.push(n);
    labels.push({ text: text(k.facts[i], 30), obj: lap, at: new THREE.Vector3(0, 0.55, 0), key: i });
    return at;
  });
  out.forEach((i, j) => {
    const at = put(i, [3.9, (out.length > 1 ? 2.4 - 4.8 * j / (out.length - 1) : 0), 0]);
    (edgeAt.length ? edgeAt : [[cx + R, 0, 0]]).forEach((e) => links.push(...e, ...at));
  });
  if (links.length) root.add(new THREE.LineSegments(K.positions(links), K.line('soft')));
  return {
    root, labels,
    enter(i, lit) { light(K, items, lit); },
    update(t, dt) { if (dt > 0) items.forEach((n) => { n.g.rotation.y += dt * (n.on ? 1.2 : 0.25); }); },
  };
}

// ---- 9 \u00b7 Stack and licences: one orbit per role, flagged licences amber ---------------------------
function stack(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], orbits = [], tags = [];
  root.rotation.x = 0.5;
  const groups = new Map();
  k.facts.forEach((f, i) => { const g = f.group || ''; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(i); });
  const tag = K.geo(new THREE.EdgesGeometry(K.geo(new THREE.OctahedronGeometry(0.13, 0)))), plainMat = K.line('line'), amberMat = K.line('amber');
  const litMat = K.line('lit');
  [...groups.keys()].slice(0, 6).forEach((g, gi) => {
    const r = 1.2 + gi * 0.78, spin = new THREE.Group(), ids = groups.get(g);
    spin.add(new THREE.LineLoop(K.circle(r, 120), K.line('soft')));
    ids.forEach((i, j) => {
      const a = (j / ids.length) * Math.PI * 2 + gi * 0.7, at = [r * Math.cos(a), r * Math.sin(a), 0];
      const flag = !!FLAG[k.facts[i].flag], mark = tags.length < 40 ? new THREE.LineSegments(tag, flag ? amberMat : plainMat) : null;
      if (mark) { mark.position.set(...at); spin.add(mark); } // <= 40 marks: the draw-call budget
      tags.push({ key: i, spin, at, mark, flag });
    });
    root.add(spin); orbits.push({ spin, speed: (gi % 2 ? -1 : 1) * (0.05 + 0.03 * gi) });
  });
  const flagged = (x) => (FLAG[k.facts[x.key].flag] ? 1 : 0);
  tags.slice().sort((a, b) => flagged(b) - flagged(a)).slice(0, MAX).forEach((x) => { // flagged licences first
    const f = k.facts[x.key], flag = FLAG[f.flag];
    labels.push({ text: cut(f.label, 22) + (f.value ? ' \u00b7 ' + cut(f.value, 20) : '') + (flag ? ' \u00b7 ' + flag : ''), obj: x.spin,
      at: new THREE.Vector3(x.at[0] + 0.24, x.at[1], 0), key: x.key, cls: flag ? 'amber' : '', align: 'left' }); // beside its mark
  });
  return {
    root, labels,
    enter(i, lit) { tags.forEach((x) => { if (x.mark) { x.mark.material = lit.has(x.key) ? litMat : x.flag ? amberMat : plainMat; x.mark.scale.setScalar(lit.has(x.key) ? 1.6 : 1); } }); },
    update(t, dt) { if (dt > 0) orbits.forEach((x) => { x.spin.rotation.z += dt * x.speed; }); },
  };
}

// ---- 10 \u00b7 Costs: rupee bars (log scale), free allowances flat; the owner's month against his limit ----
function costs(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], bars = [];
  const rows = k.facts.slice(0, 10).map((f, i) => ({ f, v: f.n || 0, key: i }));
  const c = (k.ctx && k.ctx.costs) || {};
  if (k.ctx && k.ctx.audience === 'owner' && c.month !== null && c.month !== undefined && c.limit) {
    rows.push({ f: { label: 'This month', value: '\u20b9' + fmt(c.month) }, v: c.month, mine: true });
    rows.push({ f: { label: 'Your monthly limit', value: '\u20b9' + fmt(c.limit) }, v: c.limit, mine: true });
  }
  const top = Math.max(1, ...rows.map((r) => Math.log10(1 + r.v))), n = rows.length, w = Math.min(0.8, 9.6 / Math.max(1, n) - 0.25);
  const box = K.geo(new THREE.BoxGeometry(w, 1, w)), boxEdges = K.geo(new THREE.EdgesGeometry(box));
  root.add(new THREE.LineSegments(K.positions([-5.6, -2.4, 0, 5.6, -2.4, 0]), K.line('soft')));
  rows.forEach((r, i) => {
    const h = r.v > 0 ? Math.max(0.12, 4.4 * Math.log10(1 + r.v) / top) : 0.06, g = new THREE.Group();
    const free = !(r.v > 0) || r.f.flag === 'free';
    const edge = K.line(r.mine ? 'bold' : free ? 'dim' : 'line'), fill = K.mesh('bold', 'fill');
    const body = new THREE.Group(); body.add(new THREE.Mesh(box, fill), new THREE.LineSegments(boxEdges, edge));
    body.scale.y = h; body.position.y = h / 2;
    g.add(body); g.position.set(-5 + (n > 1 ? 10 * i / (n - 1) : 5), -2.4, 0); root.add(g);
    bars.push({ g, edge, fill, key: r.mine ? -1 - i : r.key, base: r.mine ? 'bold' : free ? 'dim' : 'line' });
    labels.push({ text: cut(r.f.label, 22) + '\n' + cut(r.f.value || '', 26), obj: g, at: new THREE.Vector3(0, h + 0.45, 0), key: r.mine ? undefined : r.key, cls: 'tile' });
  });
  root.rotation.x = 0.18;
  return {
    root, labels,
    enter(i, lit) { bars.forEach((b) => { const on = lit.has(b.key); K.setRole(b.edge, on ? 'lit' : b.base); K.setRole(b.fill, 'bold', on ? 'litfill' : 'fill'); }); },
    update(t, dt) { if (dt > 0) root.rotation.y = Math.sin(t * 0.2) * 0.12; },
  };
}

// ---- 11 \u00b7 Not built yet: dimmed nodes labelled "later" ------------------------------------------------
function later(k) {
  const { THREE, K } = k, root = new THREE.Group(), labels = [], items = [];
  const facts = k.facts.slice(0, MAX), cols = facts.length > 12 ? 4 : 3, rows = Math.ceil(facts.length / cols), at = [];
  const octa = K.geo(new THREE.OctahedronGeometry(0.2, 0)), edges = K.geo(new THREE.EdgesGeometry(octa));
  facts.forEach((f, i) => {
    const x = -4.6 + 8.2 * (cols > 1 ? (i % cols) / (cols - 1) : 0.5), y = 2.5 - 5 * (rows > 1 ? Math.floor(i / cols) / (rows - 1) : 0.5);
    const edge = K.line('soft'), g = new THREE.LineSegments(edges, edge);
    g.position.set(x, y, 0); root.add(g); at.push([x, y, 0]); items.push({ g, edge, key: i });
    labels.push({ text: cut(f.label, 40) + ' \u00b7 later', obj: g, at: new THREE.Vector3(0.32, 0, 0), key: i, cls: 'dim', align: 'left' });
  });
  const grid = [];
  at.forEach((p, i) => { if (i + 1 < at.length && (i + 1) % cols) grid.push(...p, ...at[i + 1]); if (i + cols < at.length) grid.push(...p, ...at[i + cols]); });
  if (grid.length) root.add(new THREE.LineSegments(K.positions(grid), K.line('dim')));
  return {
    root, labels,
    enter(i, lit) { light(K, items, lit, 'soft'); },
    update(t, dt) { if (dt > 0) items.forEach((n) => { n.g.rotation.y += dt * (n.on ? 1.2 : 0.15); }); },
  };
}

export const SCENES = Object.freeze({ 4: memory, 7: home, 9: stack, 10: costs, 11: later });
