// tests/fixtures/r13_1/b_looks.mjs -- R13.1 Part B: made-up looks for the figure's tests (no real piece, id or
// measurement): each is what Part D builds from GET /v1/tryon/look, cut to what the engine draws.
const id = (n) => 'wi_' + String(n).padStart(12, '0');
const photo = (n) => 'wh_' + String(n).padStart(12, '0');
const slot = (name, n, template, variant, rgb, pattern = 'solid', withPhoto = false) => (
  { slot: name, piece: id(n), template, variant, rgb, pattern, photo: withPhoto ? photo(n) : null, private: false });
export const PRIVATE = Object.freeze({ slot: 'base', private: true });
export const WEIGHTS0 = Object.freeze({ height: 0, shoulders: 0, chest: 0, waist: 0, hips: 0, inseam: 0, waist_down: 0 });
export const body = (weights = {}, typed = ['height']) => ({ weights: { ...WEIGHTS0, ...weights }, typed });

export const formal = () => ({ slots: [
  slot('top', 1, 'shirt', 'tucked', [150, 190, 225], 'solid'),
  slot('bottom', 2, 'trousers', null, [64, 66, 70]),
  slot('outer', 3, 'jacket', 'open', [30, 42, 80]),
  slot('shoes', 4, 'shoe', null, [110, 75, 50]),
  slot('belt', 5, 'belt', null, [110, 75, 50]),
  slot('watch', 6, 'watch', null, [110, 75, 50]),
  slot('socks', 7, 'socks', null, [28, 28, 30]),
  PRIVATE,
] });
export const festive = () => ({ slots: [
  slot('top', 11, 'kurta', 'knee', [110, 30, 40], 'printed'),
  slot('bottom', 12, 'trousers', null, [240, 240, 236]),
  slot('shoes', 13, 'sandal', null, [110, 75, 50]),
  slot('watch', 14, 'watch', null, [28, 28, 30]),
  PRIVATE,
] });
export const casual = () => ({ slots: [
  slot('top', 21, 'tee', 'untucked', [40, 120, 60]),
  slot('bottom', 22, 'shorts', null, [190, 170, 120]),
  slot('shoes', 23, 'shoe', null, [240, 240, 236]),
  slot('socks', 24, 'socks', null, [240, 240, 236]),
] });
export const mundu = () => ({ slots: [
  slot('top', 31, 'shirt', 'untucked', [240, 240, 236], 'checked'),
  slot('bottom', 32, 'wrap', 'ankle', [240, 240, 236]),
  slot('shoes', 33, 'sandal', null, [28, 28, 30]),
] });
/** A look with a piece that has no 3D shape (a tie: an image card) and one photo texture. */
export const withCard = () => ({ slots: [
  slot('top', 41, 'shirt', 'tucked', [240, 240, 236], 'striped', true),
  slot('bottom', 42, 'trousers', null, [30, 42, 80]),
  { slot: 'accessory', piece: id(43), template: null, variant: null, rgb: [190, 40, 40], pattern: 'solid', photo: photo(43), private: false },
  PRIVATE,
] });
export const swapWatch = (look, n, rgb) => ({ slots: look.slots.map((s) => (s.slot === 'watch' ? { ...s, piece: id(n), rgb } : s)) });
export const figure = (look, weights, typed) => ({ body: body(weights, typed), look });
export const opts = (o = {}) => ({ tucked: true, open: true, layers: 'all', view: 'front', ...o });
export const LOOKS = { formal, festive, casual, mundu, withCard };
