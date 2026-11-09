// src/jarvis/api/static/console-voice-barge.js - R5 I0 stub (docs/plans/r5-voice.md D7, workstream A).
// The frozen shape of the speak-to-interrupt module. Workstream A adds the double-talk gate, the
// policy, the check clips and the echo guard; until then interruption is by tap only. No build step.
//   window.JarvisBarge  policy() -> 'speech' | 'name' | 'tap', arm(opts) -> {disarm()}
(() => {
  'use strict';
  window.JarvisBarge = Object.freeze({
    policy: () => 'tap',
    arm: () => ({ disarm() {} }),
  });
})();
