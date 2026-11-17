// tests/fixtures/r13_1/b_stage.mjs -- R13.1 Part B: the stage page's module for the figure's browser tests
// (GET /r131/stage?mod=b_stage.mjs&surface=day|night&w=<px>&h=<px>&door=1&fail=<a GL_FAIL word>). It dresses the bare
// page in the console's own style sheets (so the engine reads the console's real colours and fonts), mounts nothing by
// itself, and leaves on window.__b what a test drives: { C, L, engine, mount(), stage, lost, door }.
import * as C from './engine_contract.mjs';
import * as L from './b_looks.mjs';

const q = new URLSearchParams(location.search);
for (const f of ['console.css', 'console-deck.css']) {
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/static/' + f;
  document.head.append(link);
  await new Promise((ok) => { link.onload = ok; link.onerror = ok; });
}
document.documentElement.dataset.surface = q.get('surface') === 'day' ? 'day' : 'night';
if (q.get('motion')) document.documentElement.dataset.motion = q.get('motion');
Object.assign(document.body.style, { margin: '0', padding: '12px', background: 'var(--bg)', color: 'var(--ink)', fontFamily: 'var(--font)' });
const host = document.getElementById('stage');
Object.assign(host.style, { width: (q.get('w') || '480') + 'px', height: (q.get('h') || '560') + 'px', background: 'var(--panel-solid)' });
if (q.get('fail')) window.__glFail = q.get('fail');
const door = { asked: [] };
if (q.get('door')) { // a stand-in for the picture door's read-only thumb(): a drawn striped crop, as a data: URL
  const thumb = async (id) => {
    door.asked.push(id);
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    g.fillStyle = '#f0f0ec'; g.fillRect(0, 0, 64, 64);
    g.fillStyle = '#1e2a50'; for (let x = 0; x < 64; x += 8) g.fillRect(x, 0, 3, 64);
    return c.toDataURL('image/jpeg');
  };
  window.JarvisMobile = { parts: { send: { thumb } } };
}
const out = { C, L, engine: null, stage: null, lost: [], door, error: '' };
window.__b = out;
try {
  await import('/static/console-tryon-3d.js');
  out.engine = window.JarvisTryOn3D;
  out.mount = () => { out.stage = out.engine.mount(host, { release: C.RELEASE, onLost: (why) => out.lost.push(String(why)) }); return out.stage; };
  /** Show a named look (or two, compared) and wait for the frame. */
  out.show = async (names, o, weights) => {
    if (!out.stage) out.mount();
    const res = out.stage.show([].concat(names).map((n) => L.figure(typeof n === 'string' ? L.LOOKS[n]() : n, weights)), L.opts(o));
    await out.stage.ready;
    await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
    return res;
  };
} catch (e) { out.error = String((e && e.message) || e); }
out.loaded = true;
