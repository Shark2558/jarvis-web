// src/jarvis/api/static/console-book-3d.js -- R6 D15 (book.html): the show's 3D engine and governor
// (ES module; <= 30 fps, DPR <= 1.5, <= 150 draw calls, console-3d's governor tiers, full teardown at
// close). three.js only from /static/vendor/three-0.187.0/three.module.min.js. The scene modules are
// loaded from here, never by a page tag.
// I0 STUB: builder D fills it. No build step; CSP script-src 'self'; textContent only; ASCII source;
// <= 400 lines.
export const SCENE_MODULES = Object.freeze([
  './console-book-scenes.js', './console-book-scenes-flow.js', './console-book-scenes-data.js',
]);

/** The three scene modules, loaded when the show starts. */
export function loadScenes() {
  return Promise.all([
    import('./console-book-scenes.js'),
    import('./console-book-scenes-flow.js'),
    import('./console-book-scenes-data.js'),
  ]);
}
