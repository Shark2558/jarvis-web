// tests/fixtures/r13_1/d_engine.mjs -- R13.1 Part D's fake 3D engine (a TEST stand-in for Part B's
// static/console-tryon-3d.js). The browser tests route /static/console-tryon-3d.js to this file, so Part D's console
// runs against an engine that keeps the contract (tests/fixtures/r13_1/engine_contract.mjs) before B's lands. It draws a
// flat, labelled silhouette (SVG, the slots' colours) so a screenshot shows where the figure sits; it is never shipped.
//
//   window.__r131d = { mounts, disposes, live, maxLive, shown: [{figures, opts}], views: [], spins: [], zooms: [],
//                      closer: 0, snapshots: [{caption}], lost: 0 }
//   window.__glFail  'no-webgl2' -> supported() false; 'asset' -> mount() throws (a file failed its check);
//                    'lost' -> onLost() after the first show; 'timeout' -> the first frame never draws (triangles 0)
const VIEWS = { front: 0, side: 90, back: 180 };
const NS = 'http://www.w3.org/2000/svg';
const rec = window.__r131d || (window.__r131d = { mounts: 0, disposes: 0, live: 0, maxLive: 0, shown: [], views: [], spins: [],
  zooms: [], closer: 0, snapshots: [], lost: 0 });
const fail = () => (typeof window.__glFail === 'string' ? window.__glFail : '');
const hex = (rgb) => (Array.isArray(rgb) ? '#' + rgb.map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, '0')).join('') : '#808080');
const BODY = '#c3c9d2', BASE = '#66748a';

function shape(svg, tag, attrs) {
  const el = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
  svg.append(el);
  return el;
}
function figure(svg, f, x, opts) {
  const by = {};
  ((f && f.look && f.look.slots) || []).forEach((s) => { if (s && !s.private) by[s.slot] = s; });
  const layer = opts.layers || 'all', top = layer === 'base' ? null : by.top, bottom = layer === 'base' ? null : by.bottom;
  const outer = layer === 'all' ? by.outer : null;
  shape(svg, 'circle', { cx: x, cy: 40, r: 16, fill: BODY });
  shape(svg, 'rect', { x: x - 26, y: 60, width: 52, height: 90, rx: 10, fill: top ? hex(top.rgb) : BASE, 'data-slot': top ? 'top' : 'base' });
  shape(svg, 'rect', { x: x - 24, y: 148, width: 48, height: 110, rx: 6, fill: bottom ? hex(bottom.rgb) : BASE, 'data-slot': bottom ? 'bottom' : 'base' });
  if (outer) {
    const w = opts.open ? 14 : 30;
    shape(svg, 'rect', { x: x - 30, y: 58, width: w, height: 100, rx: 6, fill: hex(outer.rgb), 'data-slot': 'outer' });
    shape(svg, 'rect', { x: x + 30 - w, y: 58, width: w, height: 100, rx: 6, fill: hex(outer.rgb), 'data-slot': 'outer' });
  }
  if (by.shoes) shape(svg, 'rect', { x: x - 26, y: 258, width: 52, height: 12, rx: 4, fill: hex(by.shoes.rgb), 'data-slot': 'shoes' });
  if (by.watch && layer !== 'base') shape(svg, 'circle', { cx: x - 34, cy: 150, r: 5, fill: hex(by.watch.rgb), 'data-slot': 'watch' });
  if (by.belt && opts.tucked && layer !== 'base') shape(svg, 'rect', { x: x - 24, y: 146, width: 48, height: 5, fill: hex(by.belt.rgb), 'data-slot': 'belt' });
}

function supported() { return fail() !== 'no-webgl2'; }

function mount(host, o) {
  if (fail() === 'asset') throw new Error('A file of the 3D figure did not pass its check.');
  const opts = o || {};
  let figures = [], view = 'front', yaw = 0, shown = 0, gone = false, last = { tucked: false, open: true, layers: 'all', view: 'front' };
  rec.mounts += 1; rec.live += 1; rec.maxLive = Math.max(rec.maxLive, rec.live);
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 320 290'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Test stand-in for the 3D figure');
  svg.dataset.fake = 'd-engine';
  const label = document.createElement('p');
  label.textContent = 'Test stand-in for the 3D figure';
  label.className = 'sfine';
  host.append(svg, label);
  const draw = () => {
    svg.replaceChildren();
    const xs = figures.length > 1 ? [100, 220] : [160];
    figures.forEach((f, i) => figure(svg, f, xs[i], last));
    svg.dataset.yaw = String(yaw);
  };
  const stage = {
    show(fs, op) {
      if (gone) throw new Error('disposed');
      figures = Array.isArray(fs) ? fs : [];
      last = Object.assign({}, last, op || {});
      if (last.view && VIEWS[last.view] !== undefined) { view = last.view; yaw = VIEWS[view]; }
      rec.shown.push(JSON.parse(JSON.stringify({ figures, opts: last })));
      shown += 1;
      if (fail() !== 'timeout') draw();
      if (shown === 1 && fail() === 'lost' && typeof opts.onLost === 'function') setTimeout(() => { rec.lost += 1; opts.onLost(); }, 0);
      const drawn = [], approx = {}, cards = [];
      figures.forEach((f) => ((f.look && f.look.slots) || []).forEach((s) => {
        if (s.private) { drawn.push(s.slot); return; }
        if (!s.template) { cards.push(s.slot); return; }
        drawn.push(s.slot);
        approx[s.slot] = ['template'].concat(s.photo ? ['texture'] : [], s.rgb ? [] : ['colour']);
      }));
      return { drawn, approx, cards };
    },
    view(name) { if (VIEWS[name] === undefined) return; view = name; yaw = VIEWS[name]; last.view = name; rec.views.push(name); draw(); },
    spin(on) { rec.spins.push(!!on); },
    zoom(step) { rec.zooms.push(step); },
    closer() { rec.closer += 1; },
    snapshot(s) {
      const caption = Array.isArray(s && s.caption) ? s.caption.slice() : [];
      rec.snapshots.push({ caption });
      const c = document.createElement('canvas'); c.width = 320; c.height = 120 + caption.length * 18;
      const g = c.getContext('2d'); g.fillStyle = '#20242c'; g.fillRect(0, 0, c.width, c.height);
      g.fillStyle = '#e8ecf2'; g.font = '13px sans-serif'; caption.forEach((t, i) => g.fillText(t, 10, 110 + i * 18));
      return new Promise((ok) => c.toBlob((b) => ok(b), 'image/png'));
    },
    stats() { return { triangles: fail() === 'timeout' || !shown ? 0 : 12000 * figures.length, figures: figures.length, fps: 60, dpr: 1, shadows: true, yaw }; },
    dispose() { if (gone) return; gone = true; rec.disposes += 1; rec.live -= 1; svg.remove(); label.remove(); },
  };
  return stage;
}

const engine = Object.freeze({ supported, mount });
window.JarvisTryOn3D = engine;
export { supported, mount };
export default engine;
