// src/jarvis/api/static/console-book-pages.js -- R6.3 D14 (docs/plans/r6-3-book-content.md): the Full book in the Book
// panel's reader (parts as .dsc disclosures, chapters as .bsec rows, a page's six sections, who wrote it, its references
// as code chips, older kept releases) and "continue where I left off" (localStorage jarvis_book_place_v1, ids only,
// owner only). PART C builds this file (<= 400 lines). console-book.js loads it ONCE at the panel's first open and calls
// mount(host, deps): `host` sits under the reader of an open OWNER session; deps = { api, booked, ask, say, render,
// token(), release() }. Routes: GET /v1/book/pages?release=, /v1/book/pages/{id}?release= (X-Jarvis-Book).
// I0's stub draws nothing. No build step; CSP script-src 'self'; textContent only; ASCII.
(() => {
  'use strict';
  window.JarvisBookPages = Object.freeze({ mount: () => {} });
})();
