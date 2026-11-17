// tests/fixtures/r13_1/b_check.mjs -- R13.1 Part B: the figure's checks that need no browser (Node 22), run by
// tests/test_r131_b_figure.py and evals/r13_1/figure.py:   node b_check.mjs [control]   -> {"cases": [{id, passed, failures}]}
// They read the COMMITTED files (static/vendor/mannequin/m1) through the console's own reader, and ask the engine's
// own plan() and model what is drawn. A control (the eval's negative controls) breaks one thing on purpose:
//   swap_morphs       two morph targets swapped in the file           -> the measure table fails
//   no_waist_down     the waist below the sample uses the waist morph  -> waist 62 reads 63.9 and fails
//   no_shorts         the base shorts dropped in "All"                 -> the privacy walk fails
//   long_sleeve       the blazer's sleeves 2 cm longer                 -> AVT-07 fails
//   side_is_front     Side returns Front's yaw                         -> AVT-02 fails
//   back_resets_tuck  Back resets the tuck                             -> AVT-08 fails
//   closed_is_open    the closed jacket is the open one                -> AVT-10 fails
//   input_cadence     the governor is fed the gap between frames, as the first build did (review B-1, finding 2)
//                                                                      -> a fast laptop is retired: the governor case fails
//   unsoftened_rig    the rig's top and floor taken before the head is softened (review B-1, finding 1: the
//                     old build)                                     -> the drawn figure's height fails
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import * as C from './engine_contract.mjs';
import * as L from './b_looks.mjs';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
// JARVIS_B_M1: another build's folder (a rebuild in a temporary folder is checked by the same cases)
const M1 = process.env.JARVIS_B_M1 ? pathToFileURL(process.env.JARVIS_B_M1 + '/') : new URL('vendor/mannequin/m1/', STATIC);
globalThis.window = globalThis.window || {};
const G = await import(new URL('console-tryon-glb.js', STATIC));
const K = await import(new URL('console-tryon-cloth.js', STATIC));
const E = await import(new URL('console-tryon-3d.js', STATIC));
const control = process.argv[2] || 'none';
const manifest = JSON.parse(readFileSync(new URL('MANIFEST.json', M1), 'utf8'));
const bytes = (name) => { const b = readFileSync(new URL(name, M1)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
const A = G.join([G.parse(bytes('body.glb')), G.parse(bytes('garments.glb'))]); // as the engine joins them
const MEASURES = manifest.sliders, J = manifest.joints, LV = manifest.levels, SH = manifest.shape;
if (control === 'swap_morphs') for (const m of Object.values(A)) { const t = m.targets; [t.chest, t.hips] = [t.hips, t.chest]; }

// ---- small geometry ----------------------------------------------------------------------------------------------
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const at = (arr, i) => [arr[i * 3], arr[i * 3 + 1], arr[i * 3 + 2]];
const range = (mesh, name) => { const [a, n] = mesh.extras.ranges[name]; return Array.from({ length: n }, (_, k) => a + k); };
/** A part at morph weights: { pos, nrm, index }. */
function shaped(name, weights) {
  const mesh = A[name], pos = G.blend(mesh, weights || {});
  return { mesh, pos, index: mesh.index, nrm: G.normals(pos, mesh.index, mesh.group) };
}
/** The signed distance (m) to the nearest crossing of a part's surface along a ray, within [lo, hi]; NaN: none. */
function hit(p, d, part, lo = -0.03, hi = 0.06) {
  let best = NaN;
  const { pos, index } = part;
  for (let t = 0; t < index.length; t += 3) {
    const a = at(pos, index[t]), e1 = sub(at(pos, index[t + 1]), a), e2 = sub(at(pos, index[t + 2]), a);
    const h = cross(d, e2), det = dot(e1, h);
    if (Math.abs(det) < 1e-12) continue;
    const s = sub(p, a), u = dot(s, h) / det;
    if (u < -1e-6 || u > 1 + 1e-6) continue;
    const q = cross(s, e1), v = dot(d, q) / det;
    if (v < -1e-6 || u + v > 1 + 1e-6) continue;
    const dist = dot(e2, q) / det;
    if (dist >= lo && dist <= hi && !(Math.abs(dist) >= Math.abs(best))) best = dist;
  }
  return best;
}
/** Is a point under a part's surface, looking outward along d? (the surface crosses the ray in front of it) */
const under = (p, d, part, reach = 0.05) => { const t = hit(p, d, part, -0.0006, reach); return !Number.isNaN(t); };
/** Outward from the left or right arm's axis (wrist - elbow - shoulder), and the place along it from the wrist (m). */
function armOf(p) {
  const s = p[0] >= 0 ? 'L' : 'R', w = J['wrist' + s], e = J['elbow' + s], sh = J['shoulder' + s];
  const fore = unit(sub(e, w)), along = dot(sub(p, w), fore), len = Math.hypot(...sub(e, w));
  if (along <= len) { const foot = [w[0] + fore[0] * along, w[1] + fore[1] * along, w[2] + fore[2] * along]; return { out: unit(sub(p, foot)), along, dist: Math.hypot(...sub(p, foot)) }; }
  const up = unit(sub(sh, e)), a2 = dot(sub(p, e), up), foot = [e[0] + up[0] * a2, e[1] + up[1] * a2, e[2] + up[2] * a2];
  return { out: unit(sub(p, foot)), along: len + a2, dist: Math.hypot(...sub(p, foot)) };
}
const theta = (p) => Math.atan2(p[0], p[2] - LV.zc);

// ---- the measure rig (scripts/mannequin/measure.py's `six`, in JS) -------------------------------------------------
function hullGirth(pts) {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]), turn = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (list) => { const h = []; for (const q of list) { while (h.length >= 2 && turn(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop(); h.push(q); } h.pop(); return h; };
  const hull = [...half(p), ...half(p.slice().reverse())];
  return hull.reduce((sum, q, i) => sum + Math.hypot(q[0] - hull[(i + 1) % hull.length][0], q[1] - hull[(i + 1) % hull.length][1]), 0);
}
function weightsOf(values) {
  const w = {}, S = manifest.sample, R = manifest.ranges;
  for (const k of MEASURES) w[k] = (values[k] - S[k]) / (R[k][1] - S[k]);
  w.waist_down = 0;
  if (values.waist < S.waist && control !== 'no_waist_down') { w.waist_down = (S.waist - values.waist) / (S.waist - R.waist[0]); w.waist = 0; }
  return w;
}
/** The rig's `ends` (the body's highest and lowest points); the control takes them before the head is softened. */
function endsOf(pos, sec, weights) {
  if (control !== 'unsoftened_rig') return Array.from({ length: sec.ends[1] }, (_, k) => at(pos, sec.ends[0] + k));
  const raw = manifest.controls.unsoftened_ends;
  return raw.x.map((p, k) => p.map((v, c) => v + Object.entries(raw.targets).reduce((s, [name, d]) => s + (Number(weights[name]) || 0) * d[k][c], 0)));
}
function measure(weights) {
  const rig = A.measure, pos = G.blend(rig, weights), sec = rig.extras.sections;
  const pts = (name) => Array.from({ length: sec[name][1] }, (_, k) => at(pos, sec[name][0] + k));
  const ys = endsOf(pos, sec, weights).map((p) => p[1]), top = Math.max(...ys), floor = Math.min(...ys);
  const waist = pts('waist'), sh = pts('shoulders'), wy = waist.reduce((s, p) => s + p[1], 0) / waist.length;
  const crotch = Math.min(...pts('mid').filter((p) => p[1] < wy).map((p) => p[1])), shy = (sh[0][1] + sh[1][1]) / 2;
  const cut = (y) => {
    const out = [];
    for (let k = 0; k < rig.index.length; k += 2) {
      const a = at(pos, rig.index[k]), b = at(pos, rig.index[k + 1]);
      if ((a[1] - y) * (b[1] - y) < 0) { const t = (y - a[1]) / (b[1] - a[1]); out.push([a[0] + t * (b[0] - a[0]), a[2] + t * (b[2] - a[2])]); }
    }
    return out;
  };
  const loop = waist.reduce((s, p, i) => s + Math.hypot(...sub(p, waist[(i + waist.length - 1) % waist.length])), 0);
  return [top - floor, Math.hypot(...sub(sh[0], sh[1])), hullGirth(cut(wy + 0.53 * (shy - wy))), loop, hullGirth(cut(crotch + 0.36 * (wy - crotch))), crotch - floor].map((v) => v * 100);
}

// review B-1, finding 1: the measurements are judged on the figure that is DRAWN (the body's regions), not on a rig
// beside it. The rig only stands in where the body is not drawn at all (the removed private zone).
const drawnBody = (weights) => manifest.body.map((n) => G.blend(A[n], weights));
function drawnHeight(parts) {
  let lo = Infinity, hi = -Infinity;
  for (const pos of parts) for (let i = 1; i < pos.length; i += 3) { if (pos[i] < lo) lo = pos[i]; if (pos[i] > hi) hi = pos[i]; }
  return (hi - lo) * 100;
}
/** Each rig point's twin among the drawn body's vertices at the sample: [part, vertex, distance (m)]. */
function twins(rig, parts) {
  const out = [];
  for (let k = 0; k < rig.length / 3; k++) {
    let best = [0, 0, Infinity];
    parts.forEach((pos, n) => {
      for (let i = 0; i < pos.length; i += 3) {
        const d = (pos[i] - rig[k * 3]) ** 2 + (pos[i + 1] - rig[k * 3 + 1]) ** 2 + (pos[i + 2] - rig[k * 3 + 2]) ** 2;
        if (d < best[2]) best = [n, i / 3, d];
      }
    });
    out.push([best[0], best[1], Math.sqrt(best[2])]);
  }
  return out;
}
// ---- the cases -----------------------------------------------------------------------------------------------------
const cases = [];
function check(id, fn) {
  const failures = [];
  try { fn((ok, why) => { if (!ok && failures.length < 12) failures.push(String(why)); }); } catch (e) { failures.push('threw: ' + ((e && e.message) || e)); }
  cases.push({ id: 'figure:' + id, passed: failures.length === 0, failures });
}
const plan = (look, opts) => {
  const p = K.plan(look, opts);
  if (control === 'no_shorts' && p.state.layers === 'all') p.parts = p.parts.filter((x) => x.name !== 'baseShorts');
  if (control === 'closed_is_open') for (const x of p.parts) if ('open' in x.weights) x.weights = { open: 1 };
  return p;
};
function model() {
  const m = E.createModel(), view = m.view;
  if (control === 'side_is_front') m.view = (name) => view(name === 'side' ? 'front' : name);
  if (control === 'back_resets_tuck') m.view = (name) => { view(name); if (name === 'back') { m.state.opts.tucked = false; m.state.plans = m.state.figures.map((f) => K.plan(f.look, m.state.opts)); } };
  return m;
}
const SHAPES = (() => { // the sample, each morph at its range's two ends, and two mixed bodies
  const out = [['sample', {}]];
  for (const [label, vals] of manifest.measure.map((r) => [r.case, Object.fromEntries(MEASURES.map((k, i) => [k, r.want[i]]))])) {
    if (/ (min|max)$/.test(label) || label.includes('+')) out.push([label, weightsOf(vals)]);
  }
  return out;
})();

check('glb_reader_refuses_what_is_outside_the_subset', (need) => {
  const good = bytes('garments.glb'), edit = (fn) => {
    const dv = new DataView(good), jl = dv.getUint32(12, true), doc = JSON.parse(new TextDecoder().decode(new Uint8Array(good, 20, jl)));
    fn(doc);
    let js = new TextEncoder().encode(JSON.stringify(doc));
    js = new Uint8Array([...js, ...new Array((4 - (js.length % 4)) % 4).fill(32)]);
    const bin = new Uint8Array(good, 20 + jl), out = new Uint8Array(20 + js.length + bin.length), o = new DataView(out.buffer);
    out.set(new Uint8Array(good, 0, 20)); out.set(js, 20); out.set(bin, 20 + js.length);
    o.setUint32(8, out.length, true); o.setUint32(12, js.length, true);
    return out.buffer;
  };
  const refused = (buf, what) => { try { G.parse(buf); need(false, what + ' was read'); } catch (e) { need(e instanceof G.GlbRefused, what + ': ' + e.message); } };
  need(Object.keys(G.parse(edit(() => {})).meshes).length > 10, 'an untouched copy must still read');
  refused(edit((d) => { d.accessors[0].componentType = 5126; }), 'an unknown accessor type (float VEC3)');
  refused(edit((d) => { d.accessors[0].type = 'VEC4'; }), 'a VEC4 accessor');
  refused(edit((d) => { d.meshes[0].primitives[0].attributes.NORMAL = 0; }), 'a NORMAL attribute');
  refused(edit((d) => { d.meshes[0].primitives[0].mode = 5; }), 'a triangle strip');
  refused(edit((d) => { d.extensionsRequired = ['KHR_draco_mesh_compression']; }), 'a required extension');
  refused(edit((d) => { d.accessors[0].sparse = {}; }), 'a sparse accessor');
  refused(edit((d) => { d.materials = [{}]; }), 'materials');
  refused(good.slice(0, good.byteLength - 8), 'a cut-off file');
  refused(new TextEncoder().encode('not a glb at all, just words that are long enough').buffer, 'other bytes');
});

// review B-1, finding 3: a malformed file is REFUSED (GlbRefused), never read as NaN, as bytes of the JSON chunk, or
// with a mesh silently lost. `P`, `U`, `I` are the first mesh's position, UV and index accessors.
check('glb_reader_refuses_malformed_files', (need) => {
  const good = bytes('garments.glb'), edit = (fn) => {
    const dv = new DataView(good), jl = dv.getUint32(12, true), doc = JSON.parse(new TextDecoder().decode(new Uint8Array(good, 20, jl)));
    const pr = doc.meshes[0].primitives[0], acc = (i) => doc.accessors[i], view = (i) => doc.bufferViews[doc.accessors[i].bufferView];
    fn({ doc, P: acc(pr.attributes.POSITION), U: acc(pr.attributes.TEXCOORD_0), I: acc(pr.indices), T: acc(pr.targets[0].POSITION), vP: view(pr.attributes.POSITION), vU: view(pr.attributes.TEXCOORD_0), vI: view(pr.indices) });
    let js = new TextEncoder().encode(JSON.stringify(doc));
    js = new Uint8Array([...js, ...new Array((4 - (js.length % 4)) % 4).fill(32)]);
    const bin = new Uint8Array(good, 20 + jl), out = new Uint8Array(20 + js.length + bin.length), o = new DataView(out.buffer);
    out.set(new Uint8Array(good, 0, 20)); out.set(js, 20); out.set(bin, 20 + js.length);
    o.setUint32(8, out.length, true); o.setUint32(12, js.length, true);
    return out.buffer;
  };
  const refused = (what, fn) => { try { G.parse(edit(fn)); need(false, what + ' was read'); } catch (e) { need(e instanceof G.GlbRefused, what + ': ' + ((e && e.constructor.name) + ' ' + e.message)); } };
  const clean = G.parse(edit(() => {}));
  need(Object.keys(clean.meshes).length > 10 && Object.getPrototypeOf(clean.meshes) === null, 'an untouched copy reads, into a map without a prototype');
  need(Object.values(clean.meshes).every((m) => m.x.every(Number.isFinite) && (!m.uv || m.uv.every(Number.isFinite))), 'every number read is finite');
  refused('an accessor offset past the BIN chunk', ({ P }) => { P.byteOffset = 1e9; });
  refused('an accessor offset past its view', ({ P, vP }) => { P.byteOffset = vP.byteLength - 8; });
  refused('a negative accessor offset', ({ P }) => { P.byteOffset = -64; });
  refused('a negative view offset (the JSON chunk\'s bytes)', ({ vP }) => { vP.byteOffset = -4096; });
  refused('a view past the BIN chunk', ({ vI }) => { vI.byteOffset = 1e9; });
  refused('a view longer than the BIN chunk', ({ vU }) => { vU.byteLength = 1e9; });
  refused('a fractional offset', ({ U }) => { U.byteOffset = 0.5; });
  refused('a negative count', ({ P }) => { P.count = -3; });
  refused('a fractional count', ({ I }) => { I.count = 7.5; });
  refused('a count as words', ({ U }) => { U.count = '12'; });
  refused('a scale that is not numbers', ({ P }) => { P.extras.scale = ['x', 1, 1]; });
  refused('a scale with a hole', ({ P }) => { P.extras.scale = [1, null, 1]; });
  refused('an offset that is not three numbers', ({ P }) => { P.extras.offset = 'abc'; });
  refused('a morph target\'s scale that is not numbers', ({ T }) => { T.extras.scale = [1, 1, '1e999']; });
  refused('an index count that is not whole triangles', ({ I }) => { I.count -= 1; });
  refused('a UV view with a stride', ({ vU }) => { vU.byteStride = 16; });
  refused('an index view with a stride', ({ vI }) => { vI.byteStride = 4; });
  refused('a position view with another stride', ({ vP }) => { vP.byteStride = 12; });
  for (const name of ['__proto__', 'constructor', 'toString', '', 7]) refused('a mesh named ' + JSON.stringify(name), ({ doc }) => { doc.meshes[0].name = name; });
  refused('two meshes with one name', ({ doc }) => { doc.meshes[1].name = doc.meshes[0].name; });
  refused('a morph target named __proto__', ({ doc }) => { doc.meshes[0].extras.targetNames[0] = '__proto__'; });
  refused('two morph targets with one name', ({ doc }) => { doc.meshes[0].extras.targetNames[1] = doc.meshes[0].extras.targetNames[0]; });
  refused('an accessor index out of range', ({ doc }) => { doc.meshes[0].primitives[0].attributes.POSITION = 99999; });
  refused('a buffer view index out of range', ({ P }) => { P.bufferView = 99999; });
  const nan = (() => { // a UV that is not a number, written into the BIN chunk itself
    const buf = edit(() => {}), dv = new DataView(buf), jl = dv.getUint32(12, true), doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jl)));
    const a = doc.accessors[doc.meshes[0].primitives[0].attributes.TEXCOORD_0], v = doc.bufferViews[a.bufferView];
    dv.setFloat32(28 + jl + v.byteOffset + (a.byteOffset || 0) + 8, NaN, true);
    return buf;
  })();
  try { G.parse(nan); need(false, 'a NaN UV was read'); } catch (e) { need(e instanceof G.GlbRefused, 'a NaN UV: ' + e.message); }
  const two = G.join([G.parse(bytes('body.glb')), G.parse(good)]);
  need(Object.keys(two).length === Object.keys(A).length && Object.getPrototypeOf(two) === null, 'the two files join into one map');
  try { G.join([G.parse(good), G.parse(good)]); need(false, 'one name in two files was read'); } catch (e) { need(e instanceof G.GlbRefused, 'one name in two files: ' + e.message); }
});

check('every_part_has_the_seven_morphs_and_the_templates_are_the_manifests', (need) => {
  for (const [name, m] of Object.entries(A)) need(C.MORPHS.every((k, i) => Object.keys(m.targets)[i] === k), name + ' lacks the seven morphs in order');
  for (const [t, spec] of Object.entries(manifest.templates)) {
    const mine = K.TEMPLATES[t];
    need(mine && JSON.stringify(mine.parts.map((p) => p[0])) === JSON.stringify(spec.parts), t + ': parts differ from the manifest');
    need((mine.state || null) === spec.state, t + ': state');
    for (const p of spec.parts) need(A[p] && A[p].mode === G.TRIANGLES, t + ': part ' + p + ' is missing');
    if (spec.state) need(spec.parts.every((p) => !A[p] || p.endsWith('Case') || spec.state in A[spec.parts[0]].targets), t + ': no ' + spec.state + ' state');
  }
  need(JSON.stringify(Object.keys(manifest.templates)) === JSON.stringify(C.TEMPLATES), 'the manifest lists other templates than the contract');
  need(JSON.stringify(Object.fromEntries(Object.entries(manifest.templates).filter(([, s]) => s.variants.length).map(([t, s]) => [t, s.variants]))) === JSON.stringify(C.VARIANTS), 'variants');
  need(A.measure.mode === G.LINES, 'the measure rig must be lines (never drawn)');
});

// A state's own answer to a morph: a target named "tuck*hips" takes the PRODUCT of the two weights (the reader's
// blend). Without it a tail tucked up to the waist would still widen with the hips it hung over when worn out.
check('a_states_own_answer_to_a_morph_is_a_product_target', (need) => {
  const one = (v) => new Float32Array([v, 0, 0]), toy = { x: one(1), targets: { hips: one(10), tuck: one(100), 'tuck*hips': one(1000) } };
  const x = (w) => G.blend(toy, w)[0];
  need(x({}) === 1 && x({ hips: 1 }) === 11 && x({ tuck: 1 }) === 101, 'the plain targets as before');
  need(x({ hips: 1, tuck: 1 }) === 1111 && x({ hips: -0.5, tuck: 1 }) === -404 && x({ hips: 0.5, tuck: 0 }) === 6, 'the product of the two weights');
  for (const name of ['shirt', 'tee', 'jacket']) {
    const t = Object.keys(A[name].targets), state = name === 'jacket' ? 'open' : 'tuck';
    need(t.indexOf(state) === 7 && t.slice(8).length > 0 && t.slice(8).every((k) => k.startsWith(state + '*') && C.MORPHS.includes(k.split('*')[1])), name + ': the seven, its state, then the state\'s answers (' + t.slice(7) + ')');
  }
  need(Object.keys(A.shirt.targets).includes('tuck*hips'), 'a tucked shirt answers the hips in its own way');
  const top = (name, w) => { const p = G.blend(A[name], w); let r = 0; for (let i = 0; i < p.length; i += 3) if (p[i + 1] > LV.trouser_top - 0.075 && p[i + 1] < LV.trouser_top - 0.02 && Math.abs(p[i]) < 0.1) r = Math.max(r, p[i + 2]); return r; };
  const wide = { hips: 1 };
  need(top('shirt', { ...wide, tuck: 1 }) < top('trousers', wide) - 0.004, 'hips 126: the tucked tail stays inside the trousers\' front (' + top('shirt', { ...wide, tuck: 1 }).toFixed(3) + ' against ' + top('trousers', wide).toFixed(3) + ')');
});

check('measure_table', (need) => {
  need(manifest.measure.length === 19, 'the table has 19 cases');
  for (const row of manifest.measure) {
    const vals = Object.fromEntries(MEASURES.map((k, i) => [k, row.want[i]])), got = measure(weightsOf(vals));
    const changed = MEASURES.filter((k) => vals[k] !== manifest.sample[k]), alone = changed.length <= 1;
    MEASURES.forEach((k, i) => {
      const off = Math.abs(got[i] - row.want[i]), limit = alone && (changed[0] === k || !changed.length) ? 0.5 : 3.5;
      need(off <= limit, row.case + ': ' + k + ' wanted ' + row.want[i] + ' measured ' + got[i].toFixed(2) + ' (limit ' + limit + ')');
      if (control === 'none') need(Math.abs(got[i] - row.got[i]) <= 0.05, row.case + ': ' + k + ' differs from the manifest (' + got[i].toFixed(3) + ' / ' + row.got[i] + ')');
      need(Math.abs(row.got[i] - row.float[i]) <= 0.2, row.case + ': ' + k + ' quantised away from the float build');
    });
  }
});

check('avt03_shape_height_178', (need) => {
  const tall = (cm) => drawnHeight(drawnBody(weightsOf({ ...manifest.sample, height: cm }))); // the figure that is DRAWN
  need(Math.abs(tall(178) - 178) <= 0.5, 'height 178: the drawn figure is ' + tall(178).toFixed(2) + ' cm');
  need(Math.abs(tall(172) - 172) <= 0.1, 'the sample is 172: the drawn figure is ' + tall(172).toFixed(2) + ' cm');
  need(tall(178) - tall(172) > 5.5, 'typing 178 makes the figure taller');
});

check('drawn_figure_measures_what_was_typed', (need) => {
  const rig = A.measure, sec = rig.extras.sections, base = drawnBody({}), pair = twins(G.blend(rig, {}), base);
  const on = pair.map(([, , d]) => d < 0.0005), share = on.filter(Boolean).length / on.length;
  need(share > 0.1, 'the rig shares points with the drawn body (' + share.toFixed(2) + ' of them; the rest stand in for the removed zone)');
  for (const name of ['ends', 'shoulders']) for (let k = sec[name][0]; k < sec[name][0] + sec[name][1]; k++) need(on[k], 'the rig\'s ' + name + ' point ' + k + ' is not a point of the drawn body (' + (pair[k][2] * 1000).toFixed(1) + ' mm away)');
  let worstOwn = 0, worstRig = 0;
  for (const row of manifest.measure) {
    const vals = Object.fromEntries(MEASURES.map((k, i) => [k, row.want[i]])), w = weightsOf(vals), parts = drawnBody(w);
    const tall = drawnHeight(parts), got = measure(w), changed = MEASURES.filter((k) => vals[k] !== manifest.sample[k]);
    const own = changed.length === 0 || (changed.length === 1 && changed[0] === 'height'), limit = own ? 0.5 : 3.5;
    need(Math.abs(tall - row.want[0]) <= limit, row.case + ': height wanted ' + row.want[0] + ', the drawn figure is ' + tall.toFixed(2) + ' cm (limit ' + limit + ')');
    need(Math.abs(tall - got[0]) <= 0.1, row.case + ': the rig reads ' + got[0].toFixed(2) + ' cm but the drawn figure is ' + tall.toFixed(2) + ' cm tall');
    if (own) worstOwn = Math.max(worstOwn, Math.abs(tall - row.want[0]));
    const pos = G.blend(rig, w);
    pair.forEach(([n, i], k) => {
      if (!on[k]) return;
      const d = Math.hypot(pos[k * 3] - parts[n][i * 3], pos[k * 3 + 1] - parts[n][i * 3 + 1], pos[k * 3 + 2] - parts[n][i * 3 + 2]);
      worstRig = Math.max(worstRig, d);
      need(d <= 0.001, row.case + ': rig point ' + k + ' left the drawn body by ' + (d * 1000).toFixed(1) + ' mm');
    });
  }
  cases.push({ id: 'figure:drawn_facts', passed: worstOwn <= 0.5 && worstRig <= 0.001, failures: [], drawn_height_own_cm: +worstOwn.toFixed(4), rig_off_drawn_mm: +(worstRig * 1000).toFixed(3) });
});

function walk(need) {
  const tops = [null, ['shirt', 'tucked'], ['shirt', 'untucked'], ['tee', 'tucked'], ['tee', 'untucked'], ['kurta', 'knee']];
  const bottoms = [null, 'trousers', 'shorts', 'wrap'], outers = [null, 'open', 'closed'];
  let n = 0;
  for (const layers of C.LAYERS) for (const top of tops) for (const bottom of bottoms) for (const outer of outers) for (const priv of [false, true]) for (const tucked of [true, false, undefined]) {
    const slots = [];
    if (top) slots.push({ slot: 'top', piece: 'wi_00000000000a', template: top[0], variant: top[1], rgb: [1, 2, 3], pattern: 'solid', photo: null, private: false });
    if (bottom) slots.push({ slot: 'bottom', piece: 'wi_00000000000b', template: bottom, variant: null, rgb: [4, 5, 6], pattern: 'solid', photo: null, private: false });
    if (outer) slots.push({ slot: 'outer', piece: 'wi_00000000000c', template: 'jacket', variant: outer, rgb: [7, 8, 9], pattern: 'solid', photo: null, private: false });
    if (priv) slots.push({ slot: 'underwear', private: true }, { slot: 'base', private: true });
    const where = JSON.stringify([layers, top, bottom, outer, priv, tucked]);
    const plans = Object.keys(C.VIEWS).map((view) => plan({ slots }, { layers, tucked, view }));
    const names = plans[0].parts.map((p) => p.name);
    need(plans.every((p) => JSON.stringify(p.parts) === JSON.stringify(plans[0].parts)), where + ': the view changed what is drawn');
    need(names.includes('baseShorts'), where + ': the base shorts are not drawn');
    const topDrawn = names.some((x) => ['shirt', 'tee', 'kurta'].includes(x));
    need(topDrawn || names.includes('vest'), where + ': neither a top nor the base vest is drawn');
    need(!plans[0].parts.some((p) => p.slot === 'base' || p.slot === 'underwear'), where + ': a private slot is drawn');
    need(names.every((x) => A[x] && A[x].mode === G.TRIANGLES && !x.startsWith('measure')), where + ': an unknown part');
    n++;
  }
  need(n === 3 * 6 * 4 * 3 * 2 * 3, 'the walk covers every combination (' + n + ')');
}
check('private_zone_is_covered_in_every_layer_state_slot_set_variant_and_view', (need) => {
  walk(need);
  const covers = { low: [['baseShorts', {}]], top: [['vest', {}], ['shirt', {}], ['shirt', { tuck: 1 }], ['tee', {}], ['tee', { tuck: 1 }], ['kurta', {}]] };
  for (const [label, w] of SHAPES) {
    const cover = {};
    for (const zone of ['low', 'top']) for (const [name, st] of covers[zone]) cover[name + JSON.stringify(st)] = shaped(name, { ...w, ...st });
    for (const name of manifest.body) {
      const part = shaped(name, w), rim = part.mesh.extras.rim;
      for (const zone of ['low', 'top']) for (const i of rim[zone]) for (const [cn, st] of covers[zone]) {
        need(under(at(part.pos, i), at(part.nrm, i), cover[cn + JSON.stringify(st)], 0.06), label + ': ' + name + ' point ' + i + ' at the edge of the zone is not under ' + cn + JSON.stringify(st));
      }
    }
  }
  const all = manifest.body.reduce((s, n) => s + A[n].extras.rim.low.length + A[n].extras.rim.top.length, 0);
  need(all > 100, 'the removed zone has an edge to check (' + all + ' points)');
});

function jacketOf(state) {
  const j = shaped('jacket', state);
  if (control === 'long_sleeve') { // every point of a sleeve's last 3 cm moves 2 cm towards the hand
    const end = SH.cuff_end + SH.sleeve_above_cuff;
    for (let i = 0; i < j.pos.length / 3; i++) {
      const p = at(j.pos, i);
      if (Math.abs(p[0]) < Math.abs(J.shoulderL[0]) + 0.015) continue;
      const s = p[0] >= 0 ? 'L' : 'R', dir = unit(sub(J['wrist' + s], J['elbow' + s])), a = armOf(p).along;
      if (a < end + 0.03) for (let c = 0; c < 3; c++) j.pos[i * 3 + c] += dir[c] * 0.02;
    }
  }
  return j;
}
/** Only the jacket's sleeves below the elbows (a hanging hand is near the jacket's skirt: that is not "inside the sleeve"). */
function sleevesOf(jk) {
  const keep = [], near = (i) => { const p = at(jk.pos, i), a = armOf(p); return a.dist < 0.07 && a.along < 0.22; };
  for (let t = 0; t < jk.index.length; t += 3) if (near(jk.index[t]) && near(jk.index[t + 1]) && near(jk.index[t + 2])) keep.push(jk.index[t], jk.index[t + 1], jk.index[t + 2]);
  return { pos: jk.pos, index: keep };
}
check('avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch', (need) => {
  const shirt = shaped('shirt', { tuck: 1 }), watch = shaped('watchCase', {}), strap = shaped('watchStrap', {});
  const end = SH.cuff_end + SH.sleeve_above_cuff, yv = J.neck[1] - SH.v_drop, sx = Math.abs(J.shoulderL[0]);
  for (const [word, state] of [['closed', {}], ['open', { open: 1 }]]) {
    const jk = jacketOf(state), sleeve = sleevesOf(jk);
    let sleeves = 0, torso = 0, cuffs = 0;
    need(sleeve.index.length > 300, word + ': the blazer has sleeves');
    for (const i of range(shirt.mesh, 'trunk')) {
      const p = at(shirt.pos, i);
      if (Math.abs(p[0]) > sx + 0.015 && p[1] > J.wristL[1]) { // a sleeve: from the shoulder to 1 cm above the jacket's end
        const a = armOf(p);
        if (a.along >= end + 0.01) { sleeves++; need(under(p, a.out, jk), word + ': a shirt sleeve point ' + a.along.toFixed(3) + ' m above the wrist is not inside the blazer'); }
      } else if (Math.abs(p[0]) < sx - 0.03 && p[1] > LV.trouser_top + 0.02 && p[1] < J.shoulderL[1] - 0.10) {
        const side = Math.abs(theta(p)) > 1.0, front = word === 'closed' && p[1] < yv - 0.04;
        if (side || front) { torso++; need(under(p, at(shirt.nrm, i), jk), word + ': a shirt torso point at ' + p.map((v) => v.toFixed(2)) + ' is not inside the blazer'); }
      }
    }
    for (const name of ['cuffL', 'cuffR']) for (const i of range(shirt.mesh, name)) {
      const p = at(shirt.pos, i), a = armOf(p);
      if (a.along <= SH.cuff_end + 0.01) { cuffs++; need(!under(p, a.out, sleeve), word + ': the last centimetre of the shirt cuff is under the blazer sleeve (' + a.along.toFixed(3) + ')'); }
    }
    need(sleeves > 60 && torso > 60 && cuffs > 20, word + ': too few points checked (' + [sleeves, torso, cuffs] + ')');
    for (const i of range(shirt.mesh, 'collar')) need(!under(at(shirt.pos, i), at(shirt.nrm, i), jk, 0.012), word + ': a shirt collar point lies under the blazer (cloth within 12 mm over it)');
    for (const part of [watch, strap]) for (let i = 0; i < part.pos.length / 3; i++) need(!under(at(part.pos, i), armOf(at(part.pos, i)).out, sleeve), word + ': the watch is under the blazer sleeve');
    const round = (p) => Math.atan2(p[0], p[2] - J.neck[2]), leaf = range(shirt.mesh, 'collar').map((i) => at(shirt.pos, i));
    for (const i of range(jk.mesh, 'trunk')) { // the blazer's neck edge sits under the shirt's collar: the collar stands above it all round
      const p = at(jk.pos, i);
      if (Math.hypot(...sub(p, J.neck)) > 0.15) continue;
      const top = Math.max(...leaf.filter((q) => Math.abs(Math.atan2(Math.sin(round(q) - round(p)), Math.cos(round(q) - round(p)))) < 0.3).map((q) => q[1]));
      need(p[1] <= top - 0.01, word + ': the blazer collar rises to the top of the shirt collar (' + p[1].toFixed(3) + ' against ' + top.toFixed(3) + ')');
    }
  }
  need(watch.pos[0] > 0 && Math.abs(watch.pos[1] - J.wristL[1]) < 0.03, 'the watch is on the LEFT wrist');
});

check('avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket', (need) => {
  const yv = J.neck[1] - SH.v_drop, look = L.formal(), shirt = shaped('shirt', { tuck: 1 });
  const stateOf = (p) => p.parts.find((x) => x.name === 'jacket').weights;
  const closedPlan = plan(look, L.opts({ open: false })), openPlan = plan(look, L.opts({ open: true }));
  const placket = range(shirt.mesh, 'placket').map((i) => [at(shirt.pos, i), at(shirt.nrm, i)]).filter(([p]) => p[1] < yv - 0.04 && p[1] > LV.trouser_top + 0.03);
  const hiddenBy = (p) => { const jk = shaped('jacket', stateOf(p)); return placket.filter(([q, n]) => under(q, n, jk)).length / placket.length; };
  need(placket.length > 20, 'placket points to check');
  need(hiddenBy(closedPlan) >= 0.98, 'closed: the shirt placket still shows (' + hiddenBy(closedPlan).toFixed(2) + ' hidden)');
  need(hiddenBy(openPlan) <= 0.1, 'open: the shirt placket is hidden (' + hiddenBy(openPlan).toFixed(2) + ')');
  const m = model();
  m.show([L.figure(look)], L.opts({ open: true }));
  const before = m.identity()[0];
  m.show([L.figure(look)], L.opts({ open: false }));
  const after = m.identity()[0];
  need(before.pieces.outer === after.pieces.outer && before.state.open === true && after.state.open === false, 'the same jacket stays selected, open then closed');
  const tucked = plan(look, L.opts({ layers: 'no_outer', tucked: true })), out = plan(look, L.opts({ layers: 'no_outer', tucked: false }));
  need(tucked.drawn.includes('belt') && !tucked.hidden.includes('belt'), 'tucked: the belt shows');
  need(!out.drawn.includes('belt') && out.hidden.includes('belt'), 'untucked: the belt is covered');
  need(tucked.parts.find((x) => x.name === 'shirt').weights.tuck === 1 && out.parts.find((x) => x.name === 'shirt').weights.tuck === 0, 'the shirt takes its tuck state');
  const tail = (w) => { const x = G.blend(A.shirt, w); return Math.min(...range(shirt.mesh, 'trunk').filter((i) => Math.abs(x[i * 3]) < 0.15).map((i) => x[i * 3 + 1])); };
  need(tail({ tuck: 1 }) > LV.trouser_top - 0.09 && tail({ tuck: 1 }) < LV.trouser_top - 0.03, 'tucked: the tail ends inside the waistband');
  need(tail({}) < LV.trouser_top - 0.12, 'untucked: the shirt hangs over the trousers');
  const kurta = plan(L.festive(), L.opts({ tucked: true }));
  need(kurta.state.tucked === false && !('tuck' in kurta.parts.find((x) => x.name === 'kurta').weights), 'a kurta offers no tuck');
  need(plan(L.casual(), L.opts({ tucked: true })).state.tucked === true, 'a tee can be tucked');
});

// review B-1, finding 4: a shirt or tee over a wrap can only be drawn tucked. The engine SAYS so in show()'s answer
// (`forced` and `approx`), so Part D can write "Drawn tucked into the mundu" and switch its tuck control off.
check('a_top_over_a_wrap_says_it_is_drawn_tucked', (need) => {
  const tee = { slots: L.mundu().slots.map((s) => (s.slot === 'top' ? { ...s, template: 'tee' } : s)) };
  for (const [word, look] of [['shirt', L.mundu()], ['tee', tee]]) {
    const out = plan(look, L.opts({ tucked: false }));
    need(out.state.tucked === true && out.parts.find((x) => x.slot === 'top').weights.tuck === 1, word + ' over a wrap is drawn tucked');
    need(JSON.stringify(out.forced) === '{"top":"tucked"}', word + ': the plan says the top was forced tucked (' + JSON.stringify(out.forced) + ')');
    need(out.approx.top.includes('tuck'), word + ': the tuck is named approximate (' + out.approx.top + ')');
    const asked = plan(look, L.opts({ tucked: true }));
    need(JSON.stringify(asked.forced) === '{}' && !asked.approx.top.includes('tuck'), word + ': asked tucked, nothing is forced');
    const byVariant = plan(look, L.opts({ tucked: undefined })); // the piece's own variant says untucked
    need(JSON.stringify(byVariant.forced) === '{"top":"tucked"}', word + ': an untucked variant is forced too');
  }
  const m = model(), res = m.show([L.figure(L.mundu()), L.figure(L.formal())], L.opts({ tucked: false }));
  need(JSON.stringify(res.forced) === '{"top":"tucked"}' && JSON.stringify(res.figures[0].forced) === '{"top":"tucked"}', 'show() answers it: ' + JSON.stringify(res.forced));
  need(JSON.stringify(res.figures[1].forced) === '{}' && m.identity()[1].state.tucked === false, 'over trousers the choice is honoured');
  need(C.showProblems(res).length === 0, 'the answer still fits the contract');
  const honoured = plan(L.formal(), L.opts({ tucked: false, layers: 'no_outer' }));
  need(JSON.stringify(honoured.forced) === '{}' && !honoured.approx.top.includes('tuck'), 'trousers: untucked is drawn untucked');
  const base = plan(L.mundu(), L.opts({ tucked: false, layers: 'base' }));
  need(JSON.stringify(base.forced) === '{}', 'base layer only: nothing is drawn, nothing is forced');
});

check('avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views', (need) => {
  const m = model(), seen = {};
  m.show([{ body: L.body({}, []), look: { slots: [] } }], L.opts());
  need(m.state.plans[0].parts.map((p) => p.name).join() === 'bodyCore,bodyArms,bodyShoulders,bodyShins,bodyThighs,bodyFeet,baseShorts,vest', 'typed measurements alone: the body in its base layer');
  for (const [name, deg] of Object.entries(C.VIEWS)) { m.view(name); seen[name] = m.state.yaw; need(Math.abs(m.state.yaw - deg) <= 1, name + ' is ' + m.state.yaw + ' degrees, not ' + deg); }
  need(new Set(Object.values(seen)).size === 3, 'three different yaws');
  m.view('front'); m.turn(-40, 0);
  need(m.state.yaw === 320, 'a drag turns the figure');
  let threw = false; try { m.view('top'); } catch (_) { threw = true; }
  need(threw && E.LABEL === 'Estimated from your measurements', 'an unknown view is refused; the label');
});

check('avt08_front_to_back_keeps_the_same_pieces_layers_and_figure', (need) => {
  const m = model(), fig = L.figure(L.withCard(), { height: 0.26, waist_down: 0.5 });
  const shown = m.show([fig], L.opts({ tucked: true, open: false, layers: 'all', view: 'front' }));
  const front = JSON.stringify(m.identity());
  m.view('back');
  need(m.state.yaw === 180, 'the back view');
  need(JSON.stringify(m.identity()) === front, 'front -> back changed the pieces, the styling state or the weights');
  need(shown.cards.join() === 'accessory' && m.identity()[0].cards.join() === 'accessory', 'a photo-only piece stays an image card');
  need(m.identity()[0].state.tucked === true && m.identity()[0].weights.height === 0.26, 'tuck and weights as shown');
});

check('avt06_swapping_the_watch_changes_the_left_wrist', (need) => {
  const a = plan(L.formal(), L.opts()), b = plan(L.swapWatch(L.formal(), 99, [28, 28, 30]), L.opts());
  const strap = (p) => p.parts.find((x) => x.name === 'watchStrap');
  need(strap(a).rgb.join() === '110,75,50' && strap(b).rgb.join() === '28,28,30', 'the strap takes the new watch\'s colour');
  need(JSON.stringify(a.parts.filter((x) => x.slot !== 'watch')) === JSON.stringify(b.parts.filter((x) => x.slot !== 'watch')), 'only the watch changed');
  const xs = (name) => Array.from(A[name].x).filter((_, i) => i % 3 === 0);
  need(Math.min(...xs('watchStrap')) > 0.15, 'the watch is on the figure\'s left');
  need(Math.min(...xs('shoes')) < -0.05 && Math.max(...xs('shoes')) > 0.05, 'shoes on both feet');
  const by = Array.from(A.belt.x).filter((_, i) => i % 3 === 1);
  need(Math.max(...by) <= LV.trouser_top + 0.001 && Math.min(...by) >= LV.trouser_top - 0.05, 'the belt at the trouser top');
});

check('avt05_template_colour_and_texture_are_named_approximate', (need) => {
  const p = plan(L.withCard(), L.opts());
  need(p.approx.top.join() === 'template,texture' && p.approx.bottom.join() === 'template', 'approximate: template, and texture from a crop');
  need(p.parts.find((x) => x.name === 'shirt').photo === 'wh_000000000041' && p.cards.join() === 'accessory', 'the crop and the card');
  const grey = plan({ slots: [{ slot: 'top', piece: 'wi_000000000001', template: 'tee', variant: 'untucked', rgb: null, pattern: null, photo: null, private: false }] }, L.opts());
  need(grey.approx.top.join() === 'template,colour' && grey.parts.find((x) => x.name === 'tee').rgb.join() === '128,128,128', 'no colour: mid-grey, named');
  for (const t of C.TEMPLATES) need(plan({ slots: [{ slot: 's', piece: 'wi_000000000001', template: t, variant: null, rgb: [9, 9, 9], pattern: 'solid', photo: null, private: false }, { slot: 'b', piece: 'wi_000000000002', template: 'trousers', variant: null, rgb: [9, 9, 9], pattern: 'solid', photo: null, private: false }] }, L.opts({ tucked: true })).approx.s || t === 'trousers', t + ' has no shape');
});

check('avt09_redraw_a_swap_changes_only_that_slot', (need) => {
  const m = model(), swapped = { slots: L.formal().slots.map((s) => (s.slot === 'outer' ? { ...s, piece: 'wi_0000000000ff', rgb: [110, 30, 40] } : s)) };
  m.show([L.figure(L.formal())], L.opts());
  const before = m.identity()[0], parts = JSON.stringify(m.state.plans[0].parts.filter((p) => p.slot !== 'outer'));
  m.show([L.figure(swapped)], L.opts());
  const after = m.identity()[0];
  need(after.pieces.outer === 'wi_0000000000ff' && before.pieces.outer !== after.pieces.outer, 'the outer layer is the new piece');
  need(m.state.plans[0].parts.find((p) => p.name === 'jacket').rgb.join() === '110,30,40', 'and is redrawn in its colour');
  need(JSON.stringify(m.state.plans[0].parts.filter((p) => p.slot !== 'outer')) === parts, 'nothing else changed');
});

check('avt11_two_figures_each_with_its_own_slots', (need) => {
  const m = model(), res = m.show([L.figure(L.formal()), L.figure(L.festive())], L.opts());
  need(res.figures.length === 2 && m.state.figures.length === 2, 'two figures');
  need(res.figures[0].drawn.includes('outer') && !res.figures[1].drawn.includes('outer') && res.figures[1].drawn.includes('top'), 'each its own slots');
  need(JSON.stringify(m.identity()[0].pieces) !== JSON.stringify(m.identity()[1].pieces), 'two item lists');
  need(C.LIMITS.gap_m === 0.9 && m.show([1, 2, 3].map(() => L.figure(L.formal())), L.opts()).figures.length === 2, 'at most two');
});

check('avt14_a_private_slot_draws_only_the_covered_base_layer', (need) => {
  const secret = { slot: 'underwear', private: true, piece: 'wi_5ec2e7000000', rgb: [201, 202, 203], pattern: 'dotted', photo: 'wh_5ec2e7000000', template: 'shorts', words: 'made-up private words' };
  const p = plan({ slots: [...L.formal().slots, secret] }, L.opts()), text = JSON.stringify(p);
  need(p.covered === true && !p.drawn.includes('underwear') && !p.cards.includes('underwear') && !p.hidden.includes('underwear'), 'covered, never drawn, carded or listed');
  for (const word of ['5ec2e7', '201', 'dotted', 'made-up private words']) need(!text.includes(word), 'the plan carries "' + word + '" of a private piece');
  need(p.parts.some((x) => x.name === 'baseShorts'), 'the base layer is drawn');
  for (const layers of C.LAYERS) need(plan({ slots: [secret] }, { layers }).parts.map((x) => x.name).includes('baseShorts'), layers + ': covered');
});

check('triangles_within_the_budget', (need) => {
  const count = (p) => p.parts.reduce((s, x) => s + A[x.name].index.length / 3, 0);
  let worst = 0;
  for (const top of ['shirt', 'tee', 'kurta', null]) for (const bottom of ['trousers', 'shorts', 'wrap', null]) for (const feet of ['shoe', 'sandal', null]) for (const layers of C.LAYERS) {
    const slots = [['top', top], ['bottom', bottom], ['outer', 'jacket'], ['shoes', feet], ['socks', 'socks'], ['belt', 'belt'], ['watch', 'watch']].filter(([, t]) => t)
      .map(([slot, template], i) => ({ slot, piece: 'wi_00000000000' + i, template, variant: null, rgb: [1, 1, 1], pattern: 'solid', photo: null, private: false }));
    worst = Math.max(worst, count(plan({ slots }, { layers, tucked: true })));
  }
  need(worst <= C.LIMITS.triangles_one, 'a dressed figure draws ' + worst + ' triangles');
  need(2 * worst <= C.LIMITS.triangles_two, 'two figures draw ' + 2 * worst);
  cases.push({ id: 'figure:facts', passed: true, failures: [], worst_triangles: worst });
});

// review B-1, finding 2: the governor judges what a frame COST (the wait for its turn and the drawing), never the gap
// between two inputs. Each replay is [frames a second, seconds, wait ms, draw ms]; frames are drawn on demand.
function replay(perSecond, seconds, wait, draw) {
  const g = E.createGovernor(), steps = [], gap = 1000 / perSecond;
  for (let t = 1000; t <= 1000 + seconds * 1000; t += gap) {
    const step = g.frame(t, control === 'input_cadence' ? { wait: gap, draw: 0 } : { wait, draw });
    if (step !== 'ok') steps.push(step + '@' + ((t - 1000) / 1000).toFixed(1));
  }
  return { steps, words: steps.map((x) => x.split('@')[0]).join(), fps: g.fps() };
}
check('governor_judges_render_cost_not_input_cadence', (need) => {
  const taps = replay(3, 20, 8, 4), drag = replay(1000 / 60, 20, 6, 5), spin = replay(60, 20, 12, 4);
  need(taps.words === '', 'a fast laptop, an arrow key tapped three times a second: ' + taps.steps);
  need(drag.words === '', 'a fast laptop, a slow drag (a move every 60 ms): ' + drag.steps);
  need(spin.words === '' && spin.fps === 60, 'a 60 fps spin: ' + spin.steps + ' at ' + spin.fps + ' fps');
  const slow = replay(1000 / 60, 20, 55, 5), heavy = replay(3, 30, 4, 70);
  need(slow.words === 'down,retire', 'a slow device (60 ms a frame): shadows off and DPR 1, then retired: ' + slow.steps);
  need(parseFloat(slow.steps[0].split('@')[1]) <= 4.2 && parseFloat((slow.steps[1] || '@99').split('@')[1]) <= 8.4, 'two slow windows a step: ' + slow.steps);
  need(heavy.words === 'down,retire', 'a slow draw (70 ms) is slow at any input rate: ' + heavy.steps);
  const g = E.createGovernor(), out = [];
  for (let t = 0; t < 20000; t += 16) out.push(g.frame(t, { wait: 10, draw: t % 2000 === 0 ? 400 : 4 })); // a hiccup every 2 s (a crop arriving)
  need(out.every((x) => x === 'ok'), 'one long frame in a window is a hiccup, not a slow device');
  const away = E.createGovernor(), got = [];
  for (let t = 0; t < 400000; t += 20000) got.push(away.frame(t, { wait: 19990, draw: 3 })); // the tab was hidden
  need(got.every((x) => x === 'ok'), 'a wait of many seconds is the page being away, not a slow frame');
  const w = E.createGovernor();
  for (let t = 0; t < 4200; t += 60) w.frame(t, { wait: 55, draw: 5 });
  need(w.tier() === 1, 'after the first step the tier is 1');
  w.reset();
  need(w.tier() === 1 && w.frame(5000, { wait: 55, draw: 5 }) === 'ok', 'a reset (a new look) starts the windows afresh and keeps the tier');
});

check('avt15_signals_without_a_browser', (need) => {
  need(E.supported() === false, 'no document: not supported');
  let threw = ''; try { E.mount(null, { release: 'm1' }); } catch (e) { threw = e.message; }
  need(threw === 'The 3D view needs a place on the page.', 'mount without a host throws plain words');
  need(C.engineProblems(globalThis.window.JarvisTryOn3D).length === 0, 'the engine fits the contract');
});

process.stdout.write(JSON.stringify({ control, cases }));
