// tests/fixtures/r13_1/engine_contract.mjs -- R13.1 I0 seam 11 (docs/plans/r13-1-try-on.md D2, D6-D9; plan review
// L12, M9): the 3D engine's contract, every field pinned. Part B's engine (static/console-tryon-3d.js) answers exactly
// this; Part D's section calls exactly this; tests/test_r131_seams.py checks I0's stub against it with Node, and B's
// and D's own tests import it (`import * as C from './engine_contract.mjs'`).
//
//   window.JarvisTryOn3D = { supported() -> bool, mount(host, {release, onLost}) -> Stage }   (mount may throw: D8)
//   Stage = { show(figures, opts) -> {drawn, approx, cards}, view(name), spin(on), zoom(step), closer(),
//             snapshot({caption: string[]}) -> Promise<Blob>, stats() -> {...STATS}, dispose() }
//   figures[i] = { body: {weights, typed}, look: {slots: [SLOT...]} }   one or two (compare, 0.9 m apart)
//   opts = { tucked, open, layers, view }
// `weights`: the seven morph weights by name (B's manifest `sliders`, with `waist_down`), from the measurements;
// `typed`: the measurement names he typed (the rest are "estimated"). A slot is the look route's LookSlot, cut to what
// the engine draws: a private slot has {slot, private: true} and nothing else that names it (never drawn as itself).
// `show` answers what it drew: `drawn` (slot names), `approx` (slot -> what is approximate: template, texture, colour)
// and `cards` (slots shown as an image card beside the figure: no template, card only, a model that failed).

export const ENGINE = Object.freeze(['supported', 'mount']);
export const MOUNT_OPTS = Object.freeze(['release', 'onLost']);
export const STAGE = Object.freeze(['show', 'view', 'spin', 'zoom', 'closer', 'snapshot', 'stats', 'dispose']);
export const SHOW_RESULT = Object.freeze(['drawn', 'approx', 'cards']);
export const FIGURE = Object.freeze(['body', 'look']);
export const BODY = Object.freeze(['weights', 'typed']);
export const LOOK = Object.freeze(['slots']);
export const SLOT = Object.freeze(['slot', 'piece', 'template', 'variant', 'rgb', 'pattern', 'photo', 'private']);
export const OPTS = Object.freeze(['tucked', 'open', 'layers', 'view']);
export const SNAPSHOT = Object.freeze(['caption']);
export const STATS = Object.freeze(['triangles', 'figures', 'fps', 'dpr', 'shadows', 'yaw']);
export const VIEWS = Object.freeze({ front: 0, side: 90, back: 180 }); // camera yaw in degrees (AVT-02, +-1)
export const LAYERS = Object.freeze(['all', 'no_outer', 'base']);
export const MEASURES = Object.freeze(['height', 'shoulders', 'chest', 'waist', 'hips', 'inseam']);
export const MORPHS = Object.freeze([...MEASURES, 'waist_down']); // seven morph targets (H3)
export const TEMPLATES = Object.freeze(['shirt', 'tee', 'kurta', 'trousers', 'shorts', 'wrap', 'jacket', 'shoe',
  'sandal', 'belt', 'watch', 'socks']);
export const VARIANTS = Object.freeze({ shirt: ['tucked', 'untucked'], tee: ['tucked', 'untucked'], kurta: ['knee'],
  wrap: ['ankle'], jacket: ['open', 'closed'] });
export const LIMITS = Object.freeze({ triangles_one: 32000, triangles_two: 64000, dpr_max: 1.5, first_render_ms: 10000,
  zoom_steps: 4, undo_max: 20, figures_max: 2, gap_m: 0.9 });
export const RELEASE = 'm1';
export const THREE_URL = '/static/vendor/three-0.187.0/three.module.min.js';
export const ASSETS_URL = '/static/vendor/mannequin/';

/** A figure as Part D builds it from GET /v1/tryon/look (made-up pieces; one private slot). */
export function sampleFigure() {
  return {
    body: { weights: { height: 0.13, shoulders: 0, chest: 0, waist: 0, hips: 0, inseam: 0, waist_down: 0 },
      typed: ['height'] },
    look: { slots: [
      { slot: 'top', piece: 'wi_000000000001', template: 'shirt', variant: 'tucked', rgb: [30, 42, 80], pattern: 'checked', photo: 'wh_000000000001', private: false },
      { slot: 'bottom', piece: 'wi_000000000002', template: 'trousers', variant: null, rgb: [64, 66, 70], pattern: 'solid', photo: null, private: false },
      { slot: 'outer', piece: 'wi_000000000003', template: 'jacket', variant: 'open', rgb: [30, 42, 80], pattern: 'solid', photo: null, private: false },
      { slot: 'watch', piece: 'wi_000000000004', template: 'watch', variant: null, rgb: [110, 75, 50], pattern: null, photo: null, private: false },
      { slot: 'base', private: true },
    ] },
  };
}

export const sampleOpts = () => ({ tucked: true, open: true, layers: 'all', view: 'front' });

/** The problems of an engine object against this contract ([] when it fits). */
export function engineProblems(engine) {
  const out = [];
  for (const k of ENGINE) if (!engine || typeof engine[k] !== 'function') out.push('engine.' + k);
  return out;
}

/** The problems of a Stage against this contract ([] when it fits). */
export function stageProblems(stage) {
  const out = [];
  for (const k of STAGE) if (!stage || typeof stage[k] !== 'function') out.push('stage.' + k);
  return out;
}

/** The problems of what show() answered. */
export function showProblems(res) {
  const out = [];
  if (!res || !Array.isArray(res.drawn)) out.push('drawn');
  if (!res || typeof res.approx !== 'object' || res.approx === null) out.push('approx');
  if (!res || !Array.isArray(res.cards)) out.push('cards');
  return out;
}

/** A private slot carries nothing that names the piece (D6, AVT-14). */
export function privateSlotProblems(slot) {
  if (!slot || slot.private !== true) return [];
  return ['piece', 'template', 'variant', 'rgb', 'pattern', 'photo'].filter((k) => slot[k] !== undefined && slot[k] !== null);
}
