// src/jarvis/api/static/console-book-fx.js -- R6.4 D11 (docs/plans/r6-4-book-look.md): the chapter player's effects
// engine, an ES module imported by console-book-chapter.js (never linked by the page). Builder B writes it: the
// catalogue's families (path tracing, box entrances, kind accents, camera, section cards, storyboard, costs, failures,
// captions, page change, ambient), the deterministic picker seeded by chapter and line, and its safety rules (Pause
// stops all motion; Calm and reduced motion cross-fade only, Off none; nothing flashes more than 3 times a second; it
// pauses when the tab is hidden; a phone drops the ambient layer first). CSS, SVG and the Web Animations API only,
// transform and opacity only; no library.
// I0 (the seams): this empty-safe stub, so the page loads before B lands. Its contract (I0-NOTES.md section 7):
//   createFx(stage, {motion: 'full'|'calm'|'off'}) -> {cue(line, cue), page(fromId, toId), pause(), resume(), stop(),
//   dispose()}; every call returns at once and does nothing here.
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
const NONE = Object.freeze({ cue() {}, page() {}, pause() {}, resume() {}, stop() {}, dispose() {} });

export function createFx(_stage, _options) {
  return NONE;
}
