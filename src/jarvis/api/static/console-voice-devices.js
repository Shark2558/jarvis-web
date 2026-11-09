// src/jarvis/api/static/console-voice-devices.js - R5 I0 stub (docs/plans/r5-voice.md D13, workstream B).
// The frozen shape of the audio route. Workstream B fills it in; until then nothing is listed or
// switched and the output is 'unknown' (the safe side for the interrupt policy). No build step.
//   window.JarvisAudioRoute  supported(), refresh() -> Promise, current() -> {output, input},
//     chooseOutput(id) -> Promise<{ok, reason?}>, chooseInput(id) -> Promise<{ok, reason?}>,
//     outputKind() -> 'headphones' | 'speakers' | 'unknown', find(name) -> device | null,
//     on(kind, fn). Device labels and ids stay in this browser: no server call carries them.
(() => {
  'use strict';
  const none = () => Promise.resolve({ ok: false, reason: 'unsupported' });
  window.JarvisAudioRoute = Object.freeze({
    supported: () => false,
    refresh: () => Promise.resolve({ outputs: [], inputs: [] }),
    current: () => ({ output: null, input: null }),
    chooseOutput: none,
    chooseInput: none,
    outputKind: () => 'unknown',
    find: () => null,
    on() {},
  });
})();
