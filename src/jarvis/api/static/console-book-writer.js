// src/jarvis/api/static/console-book-writer.js -- R6.3 D6, D7, D11, D12 (docs/plans/r6-3-book-content.md): Book settings ->
// Writer trial and Writer (the estimate, what is sent, the YES box, "Step while I watch", the side-by-side pages, the
// pick and its caps with the server's Rs words and the YES box for every grant, the first write's YES, Update's YES,
// Stop) and the 80 % storage line at the top of the Book panel. PART C builds this file (<= 400 lines).
// console-book.js loads it ONCE at the panel's first open and calls settings(host, deps): `host` sits under Book
// settings; deps = { api, booked, ask, say, render, token(), release(), top } (`top`: a box at the top of the panel).
// Routes: GET /v1/book/writer, /estimate, POST /trial, PUT /pick, POST /first, /update, /stop, /step, the trial's pages
// (buildbook/writer/http.py). I0's stub draws nothing. No build step; CSP script-src 'self'; textContent only; ASCII.
(() => {
  'use strict';
  window.JarvisBookWriter = Object.freeze({ settings: () => {} });
})();
