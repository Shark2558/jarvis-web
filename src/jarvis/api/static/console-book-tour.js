// src/jarvis/api/static/console-book-tour.js -- R6.3 D9 (docs/plans/r6-3-book-content.md): the short tour's own parts
// of the show page. PART D builds this file (<= 300 lines): each scene's chapter name in the chapters menu (for the
// owner, its full-book chapter by name), the owner-only scenes, and "continue where I left off" (this browser keeps
// {release, scene} in localStorage jarvis_book_place_v1, ids only, owner only; it restarts the scene, never the middle of
// a line). console-book-show.js calls these three hooks, only while it plays a tour (script kind "tour"):
//   label(script, n, title) -> the chapters menu's words for scene n      seen(script, beat) -> nothing (remember)
//   start(script, beats)     -> the beat index to begin at (0: the start)
// I0's stub: today's titles, nothing remembered, always from the start. No build step; CSP script-src 'self'; ASCII.
(() => {
  'use strict';
  window.JarvisBookTour = Object.freeze({
    label: (script, n, title) => title,
    seen: () => {},
    start: () => 0,
  });
})();
