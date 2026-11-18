// tests/fixtures/r13_1/b_poke.mjs -- R13.1 Part B (review B-1, finding 6): no layer that is meant to be covered shows
// through its cover, at the sample and at BOTH ends of every slider (inseam 66 too) and for two mixed bodies.
//   node b_poke.mjs [control]   -> {"cases": [{id, passed, failures, ...}]}        (run by tests/test_r131_b_figure.py)
// The committed files are read through the console's own reader and dressed by the engine's own plan(); what an eye
// would see is counted by b_seen.mjs (a software depth buffer). For each look and shape, in cm2 of the worst view:
//   base   the base shorts under a bottom (they are in every plan and must never be seen under trousers, shorts, a wrap)
//   tail   a tucked shirt's or tee's tail below the waistband
//   socks  the socks above the shoe, under a trouser leg
// LEVEL views (round the figure, 8 below to 12 above the horizon) must see nothing but a sliver; from ABOVE a real line
// of sight runs into a waistband, so a little of what is inside may be seen there. KNOWN are the documented limits
// (INTEGRATION-B, "Fix (review B-1)"): each is a cap, so a limit that grows fails too.
// Control `thin_trousers` (the eval's): the trousers drawn 4 mm inside their own shape, which is "their ease halved"
// -> the base shorts come through at the sample: red.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { seen, LEVEL, ABOVE } from './b_seen.mjs';

const STATIC = new URL('../../../src/jarvis/api/static/', import.meta.url);
const M1 = process.env.JARVIS_B_M1 ? pathToFileURL(process.env.JARVIS_B_M1 + '/') : new URL('vendor/mannequin/m1/', STATIC);
globalThis.window = globalThis.window || {};
const G = await import(new URL('console-tryon-glb.js', STATIC));
const K = await import(new URL('console-tryon-cloth.js', STATIC));
const control = process.argv[2] || 'none';
const manifest = JSON.parse(readFileSync(new URL('MANIFEST.json', M1), 'utf8'));
const bytes = (name) => { const b = readFileSync(new URL(name, M1)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
const A = G.join([G.parse(bytes('body.glb')), G.parse(bytes('garments.glb'))]);
const MEASURES = manifest.sliders;
function weightsOf(values) {
  const w = {}, S = manifest.sample, R = manifest.ranges;
  for (const k of MEASURES) w[k] = (values[k] - S[k]) / (R[k][1] - S[k]);
  w.waist_down = 0;
  if (values.waist < S.waist) { w.waist_down = (S.waist - values.waist) / (S.waist - R.waist[0]); w.waist = 0; }
  return w;
}
const SHAPES = [['sample', {}]]; // the sample, every slider's two ends, two mixed bodies
for (const r of manifest.measure) if (/ (min|max)$/.test(r.case) || r.case.includes('+')) SHAPES.push([r.case, weightsOf(Object.fromEntries(MEASURES.map((k, i) => [k, r.want[i]])))]);
const slot = (name, template, variant = null) => ({ slot: name, piece: 'wi_00000000000a', template, variant, rgb: [9, 9, 9], pattern: 'solid', photo: null, private: false });
const LOOKS = {
  'shirt tucked, trousers, socks, shoes': [slot('top', 'shirt', 'tucked'), slot('bottom', 'trousers'), slot('socks', 'socks'), slot('shoes', 'shoe')],
  'tee out, trousers': [slot('top', 'tee', 'untucked'), slot('bottom', 'trousers')],
  'tee tucked, shorts': [slot('top', 'tee', 'tucked'), slot('bottom', 'shorts')],
  'shirt, wrap': [slot('top', 'shirt', 'tucked'), slot('bottom', 'wrap')],
  'kurta, trousers': [slot('top', 'kurta', 'knee'), slot('bottom', 'trousers')],
};
const SLIVER = 0.6, INSIDE = 22; // cm2: what a LEVEL view may see of a covered layer; what a view from ABOVE may
const KNOWN = { // documented limits: [look or '*', layer] -> the most a LEVEL view sees (cm2)
  'inseam min': { '*|base': 12 }, // the body's own hip line folds over the shortened thigh: a ledge, and a line along it
  'waist max': { '*|base': 2, '*|tail': 2 }, // a waistband gapes a little under the belly of a 120 cm waist
};
const limitOf = (shape, look, layer) => { const k = KNOWN[shape] || {}; return k[look + '|' + layer] ?? k['*|' + layer] ?? SLIVER; };

/** The part drawn `by` metres inside its own shape (a control). */
function thinner(part, by) {
  const n = G.normals(part.pos, part.index, A[part.name].group), pos = new Float32Array(part.pos);
  for (let i = 0; i < pos.length; i++) pos[i] -= by * n[i];
  return { ...part, pos };
}
/** The layers of a look that must stay covered: [name, the layer, what covers it, which of its triangles count].
 *  Which triangles are "the tail" is settled on the SAMPLE shape (the same triangles at every shape: an arm that
 *  hangs nearer the hips on a narrow-shouldered body is still a sleeve). */
function layersOf(slots, w) {
  const p = K.plan({ slots }, {}), dress = (weights) => p.parts.map((x) => ({ name: x.name, pos: G.blend(A[x.name], { ...weights, ...x.weights }), index: A[x.name].index }));
  let parts = dress(w);
  const ref = dress({});
  if (control === 'thin_trousers') parts = parts.map((x) => (x.name === 'trousers' ? thinner(x, 0.004) : x));
  const part = (n) => parts.find((x) => x.name === n), others = (n) => parts.filter((x) => x.name !== n);
  const bottom = ref.find((x) => ['trousers', 'shortsG', 'wrap'].includes(x.name));
  let top = -Infinity, half = 0;
  for (let i = 0; i < bottom.pos.length; i += 3) top = Math.max(top, bottom.pos[i + 1]);
  for (let i = 0; i < bottom.pos.length; i += 3) if (bottom.pos[i + 1] > top - 0.1) half = Math.max(half, Math.abs(bottom.pos[i]));
  const out = [['base', part('baseShorts'), others('baseShorts'), null]];
  for (const name of ['shirt', 'tee']) {
    const pt = part(name), at = ref.find((x) => x.name === name);
    if (!pt || !p.state.tucked) continue;
    const low = (i) => at.pos[i * 3 + 1] < top - 0.012 && Math.abs(at.pos[i * 3]) < half + 0.012; // the trunk under the waistband, not a sleeve
    out.push(['tail', pt, others(name), (t) => low(pt.index[t * 3]) && low(pt.index[t * 3 + 1]) && low(pt.index[t * 3 + 2])]);
  }
  const so = part('socks');
  if (so) out.push(['socks', so, others('socks'), (t) => so.pos[so.index[t * 3] * 3 + 1] > 0.10]);
  return out;
}

const failures = [], table = {};
let worst = 0, worstAbove = 0, checked = 0;
for (const [shape, w] of control === 'none' ? SHAPES : SHAPES.slice(0, 1)) {
  table[shape] = {};
  for (const [look, slots] of Object.entries(LOOKS)) for (const [layer, inner, covers, counts] of layersOf(slots, w)) {
    const level = seen(inner, covers, counts, LEVEL), above = seen(inner, covers, counts, ABOVE), limit = limitOf(shape, look, layer);
    checked++;
    if (limit === SLIVER) worst = Math.max(worst, level.cm2);
    worstAbove = Math.max(worstAbove, above.cm2);
    if (level.cm2 > 0 || above.cm2 > 1) table[shape][look + ' | ' + layer] = [level.cm2, above.cm2];
    if (level.cm2 > limit) failures.push(shape + ': ' + look + ': the ' + layer + ' shows through, ' + level.cm2 + ' cm2 from yaw ' + level.view[0] + ', ' + level.view[1] + ' degrees up, at heights ' + level.band + ' (limit ' + limit + ')');
    if (above.cm2 > INSIDE) failures.push(shape + ': ' + look + ': from above, ' + above.cm2 + ' cm2 of the ' + layer + ' is seen (limit ' + INSIDE + ')');
  }
}
if (control === 'none' && checked < 15 * 8) failures.push('too few layers were checked (' + checked + ')');
process.stdout.write(JSON.stringify({ control, cases: [{ id: 'figure:no_layer_beneath_shows_through', passed: failures.length === 0, failures: failures.slice(0, 20),
  shapes: SHAPES.length, checked, worst_level_cm2: worst, worst_above_cm2: worstAbove, known: KNOWN, table }] }));
