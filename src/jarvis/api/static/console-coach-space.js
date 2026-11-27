// src/jarvis/api/static/console-coach-space.js -- R8.1 I0 stub (docs/plans/r8-vision.md v8.0.3; owner from I0 on: R8.1
// builder E). The use case `space-check` (row 223): objects, pose at up to 2 a second, on the phone camera.
// Its whole API is the bare global JarvisVision.use({id: 'space-check', tasks: [...], onResult(result, state), summary(state)}):
// one body's Results in (the engine's driver keeps a state per body: the owner's D6), {view, tally} out, where view holds
// only the fixed widget kinds and tally fits jarvis.coach.usecases' model for 'space-check'. It may import from
// './console-coach-geom.js' and nothing else; no page, no network, no storage, no camera (tests/r7_jsguard.py).
// The pane that runs it imports this file. I0: not built, so it registers nothing.
