// tests/fixtures/r13_1/stage.mjs -- R13.1 I0: the bare stage page's default module (tests/r131_fake_server.py
// GET /r131/stage). It mounts the engine into #stage and shows it the contract's sample figure, and leaves what
// happened on window.__r131 = {engine, stage, shown, error} for Part B's browser tests. B may add its own
// tests/fixtures/r13_1/b_*.mjs and open /r131/stage?mod=b_<name>.mjs.
import * as C from './engine_contract.mjs';

const out = { engine: null, stage: null, shown: null, error: '' };
window.__r131 = out;
try {
  await import('/static/console-tryon-3d.js');
  out.engine = window.JarvisTryOn3D;
  if (!out.engine.supported()) throw new Error('no-webgl2');
  out.stage = out.engine.mount(document.getElementById('stage'), { release: C.RELEASE, onLost: () => { out.error = 'lost'; } });
  out.shown = out.stage.show([C.sampleFigure()], C.sampleOpts());
} catch (e) { out.error = String((e && e.message) || e); }
