// src/jarvis/api/static/console-book-chapter.js -- R6.4 D7 (docs/plans/r6-4-book-look.md): the chapter player of the
// full book's page (/book/read), an ES module. Builder B writes it: GET /v1/book/chapters/{id} (window.JarvisBook.api,
// the book token on the page), the timeline of spoken lines, the browser voice through console-book-voice.js
// (window.JarvisBookVoice), captions with the spoken words lit, the cues (page, show, node, edge, count) drawn by the
// effects engine (console-book-fx.js), the controls and keys of D7, and Continue where I left off.
// I0 (the seams): this empty-safe stub, so the reader can call it before B lands. Its contract (I0-NOTES.md section 7):
//   window.JarvisBookChapter = {open(chapterId, {line}) -> Promise<boolean>, stop(), state() -> {open, chapter, line,
//   playing}}; the player draws only inside #brPlayer and sets #bookRead[data-mode="player"] while it is open.
// No build step; CSP script-src 'self'; textContent only; ASCII source; <= 400 lines.
import { createFx } from './console-book-fx.js';

const S = { open: false, chapter: '', line: 0, playing: false, fx: null };

function state() {
  return { open: S.open, chapter: S.chapter, line: S.line, playing: S.playing };
}
async function open(_chapterId, _options) {
  if (!S.fx) S.fx = createFx(document.getElementById('brPlayer'), { motion: 'off' });
  return false; // not built yet: the reader keeps its page
}
function stop() {
  S.open = false; S.playing = false;
  if (S.fx) S.fx.stop();
}

window.JarvisBookChapter = Object.freeze({ open, stop, state });
export { open, state, stop };
