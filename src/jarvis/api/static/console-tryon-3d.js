// src/jarvis/api/static/console-tryon-3d.js -- R13.1 I0 STUB (docs/plans/r13-1-try-on.md D2, D6-D9, seam 11): the 3D
// figure engine. Part B replaces this file; until then mount() throws, so Part D's checklist path (D8) is real from day
// one. The contract (every field pinned by tests/fixtures/r13_1/engine_contract.mjs):
//   window.JarvisTryOn3D = { supported() -> bool, mount(host, {release, onLost}) -> Stage }
//   Stage = { show(figures, opts) -> {drawn, approx, cards}, view(name), spin(on), zoom(step), closer(),
//             snapshot({caption: string[]}) -> Promise<Blob>, stats(), dispose() }
//   figures[i] = { body: {weights, typed}, look: {slots: [{slot, piece, template, variant, rgb, pattern, photo, private}]} }
//   opts = { tucked, open, layers, view }
// A drawing module (tests/test_r13_seams.py DRAWING): it draws only on its own canvases, imports three only from
// /static/vendor/three-0.187.0/three.module.min.js, fetches only /static/vendor/mannequin/, and reads his crops through
// the door's thumb() as data: URLs; it never calls JarvisVision, JarvisCamera, getUserMedia or the door's senders.
// Its two helpers: './console-tryon-glb.js' (the GLB reader) and './console-tryon-cloth.js' (textures).
const NOT_BUILT = 'The 3D view is not built yet.';
const parts = () => Promise.all([import('./console-tryon-glb.js'), import('./console-tryon-cloth.js')]);
function supported() { return true; }
function mount(host, opts) { void host; void opts; void parts; throw new Error(NOT_BUILT); }
const engine = Object.freeze({ supported, mount });
window.JarvisTryOn3D = engine;
export { supported, mount, NOT_BUILT };
export default engine;
