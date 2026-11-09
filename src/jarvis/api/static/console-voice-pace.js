// src/jarvis/api/static/console-voice-pace.js - R5 I0 stub (docs/plans/r5-voice.md D15, workstream C).
// The frozen shape of the sound cues and the timing line. Workstream C fills it in; until then
// it does nothing. No build step.
//   window.JarvisVoicePace  cue(name), mark(stage), last() -> {heard, words, answer, voice, total} | null
(() => {
  'use strict';
  window.JarvisVoicePace = Object.freeze({
    cue() {},
    mark() {},
    last: () => null,
  });
})();
