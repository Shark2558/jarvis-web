// src/jarvis/api/static/console-tryon-glb.js -- R13.1 Part B (docs/plans/r13-1-try-on.md D2 (i), D3): the reader for
// EXACTLY the GLB subset scripts/mannequin/glb.py writes; anything else is refused. The subset: one JSON and one BIN
// chunk; every mesh ONE primitive of triangles (or of lines: the measure rig, never drawn); POSITION and each morph
// target's POSITION as normalised int16 VEC3 in an 8-byte stride (KHR_mesh_quantization) with the accessor's own
// extras.scale (and extras.offset for the base): value = int / 32767 * scale + offset; TEXCOORD_0 float32 VEC2;
// uint16 indices. The files carry no normals: `geometry()` applies the morph weights on the device and computes the
// normals of the shape it made (smoother than a blended normal, and about a megabyte smaller).
// No pixel API, no network, no storage here; three.js is handed in by the engine (console-tryon-3d.js), the only importer.
const MAGIC = 0x46546C67, JSON_CHUNK = 0x4E4F534A, BIN_CHUNK = 0x004E4942;
const I16 = 5122, U16 = 5123, F32 = 5126, Q = 32767;
const TRIANGLES = 4, LINES = 1;
const ATTRS = ['POSITION', 'TEXCOORD_0'];

class GlbRefused extends Error {}
const refuse = (why) => { throw new GlbRefused('The 3D model file is not one JARVIS made: ' + why); };

function accessor(doc, bin, i) {
  const a = doc.accessors && doc.accessors[i];
  if (!a || a.sparse) refuse('accessor ' + i);
  const v = doc.bufferViews && doc.bufferViews[a.bufferView];
  if (!v || v.buffer !== 0) refuse('buffer view of accessor ' + i);
  const at = bin.byteOffset + (v.byteOffset || 0) + (a.byteOffset || 0), n = a.count;
  const kind = a.componentType + ' ' + a.type;
  const room = (bytes) => { if ((v.byteOffset || 0) + bytes > bin.byteLength || bytes > v.byteLength) refuse('accessor ' + i + ' runs past its buffer'); };
  if (kind === I16 + ' VEC3') {
    const ex = a.extras || {};
    if (!a.normalized || v.byteStride !== 8 || !Array.isArray(ex.scale) || ex.scale.length !== 3) refuse('accessor ' + i + ' is not a quantised VEC3');
    room(n * 8);
    const raw = new Int16Array(bin.buffer.slice(at, at + n * 8)), out = new Float32Array(n * 3), off = ex.offset || [0, 0, 0];
    for (let k = 0; k < n; k++) for (let c = 0; c < 3; c++) out[k * 3 + c] = raw[k * 4 + c] / Q * ex.scale[c] + off[c];
    return { data: out, raw };
  }
  if (kind === F32 + ' VEC2') { room(n * 8); return { data: new Float32Array(bin.buffer.slice(at, at + n * 8)) }; }
  if (kind === U16 + ' SCALAR') { room(n * 2); return { data: new Uint16Array(bin.buffer.slice(at, at + n * 2)) }; }
  return refuse('accessor ' + i + ' has a type outside the subset (' + kind + ')');
}

/** Vertices that share a place (split only for a UV seam) get one group, so their normals stay one. */
function groups(raw, n) {
  const seen = new Map(), out = new Uint32Array(n);
  for (let k = 0; k < n; k++) {
    const key = raw[k * 4] + ',' + raw[k * 4 + 1] + ',' + raw[k * 4 + 2];
    let g = seen.get(key);
    if (g === undefined) { g = seen.size; seen.set(key, g); }
    out[k] = g;
  }
  return out;
}

function meshOf(doc, bin, m) {
  if (!m || !Array.isArray(m.primitives) || m.primitives.length !== 1) refuse('a mesh with other than one primitive');
  const p = m.primitives[0], mode = p.mode === undefined ? TRIANGLES : p.mode, ex = m.extras || {};
  if (mode !== TRIANGLES && mode !== LINES) refuse(m.name + ': a primitive that is neither triangles nor lines');
  for (const k of Object.keys(p.attributes || {})) if (!ATTRS.includes(k)) refuse(m.name + ': attribute ' + k);
  if (p.attributes.POSITION === undefined || p.indices === undefined) refuse(m.name + ': no positions or no index');
  const names = Array.isArray(ex.targetNames) ? ex.targetNames : [], tg = p.targets || [];
  if (names.length !== tg.length) refuse(m.name + ': morph targets without their names');
  const pos = accessor(doc, bin, p.attributes.POSITION), index = accessor(doc, bin, p.indices).data;
  if (!pos.raw || !(index instanceof Uint16Array)) refuse(m.name + ': positions or index of the wrong type');
  const n = pos.data.length / 3, targets = {};
  tg.forEach((t, i) => {
    if (Object.keys(t).join() !== 'POSITION') refuse(m.name + ': a morph target of more than positions');
    const d = accessor(doc, bin, t.POSITION);
    if (!d.raw || d.data.length !== n * 3) refuse(m.name + ': a morph target of the wrong size');
    targets[names[i]] = d.data;
  });
  let uv = null;
  if (p.attributes.TEXCOORD_0 !== undefined) {
    uv = accessor(doc, bin, p.attributes.TEXCOORD_0).data;
    if (!(uv instanceof Float32Array) || uv.length !== n * 2) refuse(m.name + ': UVs of the wrong type');
  }
  for (let k = 0; k < index.length; k++) if (index[k] >= n) refuse(m.name + ': an index past its points');
  return { name: m.name, x: pos.data, index, uv, targets, extras: ex, mode, group: groups(pos.raw, n) };
}

/** An ArrayBuffer of the subset -> { extras, meshes: { name: { x, index, uv, targets, extras, mode, group } } }. */
function parse(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 28) refuse('too short');
  const dv = new DataView(buffer);
  if (dv.getUint32(0, true) !== MAGIC || dv.getUint32(4, true) !== 2 || dv.getUint32(8, true) !== buffer.byteLength) refuse('not a version 2 GLB of the stated length');
  const jl = dv.getUint32(12, true);
  if (dv.getUint32(16, true) !== JSON_CHUNK || 28 + jl > buffer.byteLength) refuse('no JSON chunk');
  const bl = dv.getUint32(20 + jl, true);
  if (dv.getUint32(24 + jl, true) !== BIN_CHUNK || 28 + jl + bl !== buffer.byteLength) refuse('one JSON and one BIN chunk are wanted');
  let doc;
  try { doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jl))); } catch (_) { refuse('its JSON does not parse'); }
  if (!doc || !doc.asset || doc.asset.version !== '2.0' || !Array.isArray(doc.meshes)) refuse('not glTF 2.0');
  for (const e of doc.extensionsRequired || []) if (e !== 'KHR_mesh_quantization') refuse('extension ' + e);
  if (doc.skins || doc.animations || doc.materials || doc.textures || doc.images || doc.cameras) refuse('more than meshes');
  const bin = new Uint8Array(buffer, 28 + jl, bl), meshes = {};
  for (const m of doc.meshes) meshes[m.name] = meshOf(doc, bin, m);
  return { extras: doc.asset.extras || {}, meshes };
}

/** A mesh's points under morph weights ({name: weight}; a name the mesh lacks is ignored). */
function blend(mesh, weights) {
  const out = new Float32Array(mesh.x);
  for (const name of Object.keys(mesh.targets)) {
    const w = Number((weights || {})[name]) || 0;
    if (!w) continue;
    const d = mesh.targets[name];
    for (let k = 0; k < out.length; k++) out[k] += w * d[k];
  }
  return out;
}

/** Area-weighted normals of triangles, shared across each group of same-place vertices. */
function normals(pos, index, group) {
  const n = pos.length / 3, count = group ? Math.max(0, ...group) + 1 : n, acc = new Float32Array(count * 3);
  const g = (i) => (group ? group[i] : i);
  for (let t = 0; t < index.length; t += 3) {
    const a = index[t] * 3, b = index[t + 1] * 3, c = index[t + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const i of [index[t], index[t + 1], index[t + 2]]) { const k = g(i) * 3; acc[k] += nx; acc[k + 1] += ny; acc[k + 2] += nz; }
  }
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const k = g(i) * 3, len = Math.hypot(acc[k], acc[k + 1], acc[k + 2]) || 1;
    out[i * 3] = acc[k] / len; out[i * 3 + 1] = acc[k + 1] / len; out[i * 3 + 2] = acc[k + 2] / len;
  }
  return out;
}

/** A drawable mesh as a three.js BufferGeometry at these morph weights (its own arrays: dispose it when done). */
function geometry(THREE, mesh, weights) {
  if (mesh.mode !== TRIANGLES) refuse(mesh.name + ' is not drawn');
  const pos = blend(mesh, weights), geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(normals(pos, mesh.index, mesh.group), 3));
  if (mesh.uv) geo.setAttribute('uv', new THREE.BufferAttribute(mesh.uv, 2));
  geo.setIndex(new THREE.BufferAttribute(mesh.index, 1));
  geo.computeBoundingBox();
  return geo;
}

const read = parse;
export { parse, read, blend, normals, geometry, GlbRefused, TRIANGLES, LINES };
