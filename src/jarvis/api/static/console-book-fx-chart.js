// src/jarvis/api/static/console-book-fx-chart.js -- R6.4 D11 (docs/plans/r6-4-book-look.md): the effects engine's
// flowchart layer, an ES module imported by console-book-fx.js. The page's flowchart (console-book-flow.js figure()) in a
// camera; the lit boxes (fl-told on the chart, fl-now on the spoken box, fl-done on the boxes told before it: I0's CSS
// dims the rest by colour, never opacity on text), re-applied whenever the chart redraws itself for a new width; and four
// effect families: path tracing (the connector draws itself, a glowing packet or a comet runs along it), box entrances
// (sonar ping, bracket frame, scan-line wipe, lift and glow), kind accents (a guard's shield locks, a store's cylinder
// fills, a service's double border turns, a person's badge waves, a step's chevron nudges) and the camera (an establishing
// overview, a pan and zoom to the spoken box in one of four moves, a pull-back at the section's end; the stage follows the
// spoken box whenever the chart is taller than it). Calm and Off: no camera moves (the box is followed at once), no
// packets, no entrances. Motion uses transform, opacity, stroke-dashoffset and filter only (the Web Animations API).
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
import { figure } from './console-book-flow.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const PAD = 24, MIN_FIT = 0.5, EASE = 'cubic-bezier(.45,0,.2,1)', OUT = 'cubic-bezier(.16,1,.3,1)';
const ZOOM = Object.freeze({ glide: 1.12, swoop: 1.12, push: 1.2, drift: 1.06 });

function svgEl(tag, attrs, cls) {
  const n = document.createElementNS(SVGNS, tag);
  Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, String(attrs[k])));
  if (cls) n.setAttribute('class', cls);
  return n;
}
const tf = (t) => 'translate(' + t.x.toFixed(1) + 'px,' + t.y.toFixed(1) + 'px) scale(' + t.s.toFixed(4) + ')';
const sel = (id) => 'g.fl-node[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]';

/** The flowchart layer inside `layer`; ctx = the engine's {a, full, level, tok}. */
export function chartLayer(layer, ctx) {
  const cam = document.createElement('div');
  cam.className = 'fx-cam';
  layer.append(cam);
  const C = { page: '', fig: null, box: null, mo: null, scene: null, t: { x: 0, y: 0, s: 1 }, camAnim: null, seq: 0 };

  /** Draw a page's flowchart (or nothing); true when it has one. The same page keeps its chart. */
  function mount(pageId, raw) {
    if (C.page === pageId) return !!C.fig;
    if (C.mo) { C.mo.disconnect(); C.mo = null; }
    cam.textContent = ''; C.page = pageId; C.scene = null; C.fig = raw ? figure(raw) : null; C.box = null;
    C.t = { x: 0, y: 0, s: 1 }; cam.style.transform = '';
    if (!C.fig) return false;
    cam.append(C.fig);
    C.box = C.fig.querySelector('.bk-flowbox');
    if (C.box && typeof MutationObserver === 'function') {
      C.mo = new MutationObserver(() => redrawn());
      C.mo.observe(C.box, { childList: true });
    }
    return true;
  }
  const svg = () => (C.box ? C.box.querySelector('svg.fl-svg') : null);
  const node = (id) => { const s = svg(); return s && id ? s.querySelector(sel(id)) : null; };
  const has = () => !!svg();

  /** I0's lit-box classes: fl-told once a box has been told, fl-now on the spoken one, fl-done on those told before. */
  function lit(sc) {
    const s = svg();
    if (!s) return;
    const told = !!(sc && (sc.now || sc.done.length));
    s.classList.toggle('fl-told', told);
    s.querySelectorAll('g.fl-node').forEach((g) => {
      const id = g.getAttribute('data-id');
      g.classList.toggle('fl-now', told && id === sc.now);
      g.classList.toggle('fl-done', told && sc.done.includes(id));
    });
  }
  /** The chart drew itself again (a new width): the lit boxes and the camera come back at once. */
  function redrawn() {
    if (!C.scene) return;
    lit(C.scene);
    aim(C.scene, '', true);
  }

  // ---- geometry: everything in the camera's own (untransformed) pixels ---------------------------------------------
  function now() { // the camera's current visual transform (an animation in flight included)
    const m = /matrix\(([^)]+)\)/.exec(getComputedStyle(cam).transform || '');
    if (!m) return { x: 0, y: 0, s: 1 };
    const v = m[1].split(',').map(Number);
    return { x: v[4] || 0, y: v[5] || 0, s: v[0] || 1 };
  }
  function geo(id) {
    const s = svg();
    if (!s || !C.fig) return null;
    const cur = now(), camR = cam.getBoundingClientRect(), fr = C.fig.getBoundingClientRect(), sr = s.getBoundingClientRect();
    const vb = s.viewBox && s.viewBox.baseVal, k = vb && vb.width ? sr.width / cur.s / vb.width : 1;
    const loc = (r) => ({ x: (r.left - camR.left) / cur.s, y: (r.top - camR.top) / cur.s, w: r.width / cur.s, h: r.height / cur.s });
    const g = { chart: loc(fr), box: null };
    const n = id ? node(id) : null, shape = n && n.querySelector('.fl-shape');
    if (shape) {
      const m = /translate\(\s*([-\d.]+)[\s,]+([-\d.]+)/.exec(n.getAttribute('transform') || '');
      const bb = shape.getBBox(), o = loc(sr), tx = m ? Number(m[1]) : 0, ty = m ? Number(m[2]) : 0;
      g.box = { x: o.x + (tx + bb.x - (vb ? vb.x : 0)) * k, y: o.y + (ty + bb.y - (vb ? vb.y : 0)) * k, w: bb.width * k, h: bb.height * k };
    }
    return g;
  }
  /** Keep the chart in view on one axis: centred when it fits, else no wider gap than PAD at either end. */
  function fit(t, z, c0, c1, view) {
    if (z * (c1 - c0) <= view - 2 * PAD) return (view - z * (c0 + c1)) / 2;
    return Math.min(PAD - z * c0, Math.max(view - PAD - z * c1, t));
  }
  /** Where the camera goes for this scene: the spoken box (zoomed by the move), the overview, or the chart at rest. */
  function target(sc, move) {
    const g = geo(sc.now), W = layer.clientWidth, H = layer.clientHeight;
    if (!g || !W || !H) return { x: 0, y: 0, s: 1 };
    const c = g.chart;
    if (!g.box) {
      const z = sc.overview && ctx.full() ? Math.max(MIN_FIT, Math.min(1, (W - 2 * PAD) / c.w, (H - 2 * PAD) / c.h)) : 1;
      const y = z * c.h <= H - 2 * PAD ? (H - z * (2 * c.y + c.h)) / 2 : PAD - z * c.y;
      return { x: fit(0, z, c.x, c.x + c.w, W), y, s: z };
    }
    const b = g.box, small = W < 600;
    let z = ctx.full() && !small ? ZOOM[move] || 1 : 1;
    z = Math.max(1, Math.min(z, (W * 0.8) / b.w, (H * 0.6) / b.h));
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    return { x: fit(W / 2 - z * cx, z, c.x, c.x + c.w, W), y: fit(H / 2 - z * cy, z, c.y, c.y + c.h, H), s: z };
  }
  /** Move the camera: at once (Calm, Off, a jump, a redraw) or by one of the moves. */
  function aim(sc, move, instant, establish) {
    const to = target(sc, move || 'glide'), from = now();
    if (C.camAnim) { try { C.camAnim.cancel(); } catch (_) { /* gone */ } C.camAnim = null; }
    C.t = to; cam.style.transform = tf(to);
    if (instant || !ctx.full()) return;
    const mid = (f, a, b) => ({ x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, s: a.s + (b.s - a.s) * f });
    let frames = [{ transform: tf(from) }, { transform: tf(to) }], dur = 900, easing = EASE;
    if (establish) {
      const wide = { x: to.x - 0.04 * layer.clientWidth, y: to.y - 0.03 * layer.clientHeight, s: to.s * 1.08 };
      frames = [{ transform: tf(wide), opacity: 0.6 }, { transform: tf(to), opacity: 1 }]; dur = 1100; easing = OUT;
    } else if (move === 'swoop') {
      const m = mid(0.5, from, to); m.s = Math.min(from.s, to.s) * 0.9;
      frames = [{ transform: tf(from) }, { transform: tf(m) }, { transform: tf(to) }]; dur = 1200;
    } else if (move === 'push') {
      const pan = { x: to.x, y: to.y, s: from.s };
      frames = [{ transform: tf(from), offset: 0 }, { transform: tf(pan), offset: 0.55 }, { transform: tf(to), offset: 1 }]; dur = 1100;
    } else if (move === 'drift') {
      dur = 1500; easing = OUT;
    }
    C.camAnim = ctx.a(cam, frames, { duration: dur, easing });
  }
  /** The section ends here: the camera pulls back to the whole chart (the layer fades out meanwhile). */
  function pullback() {
    if (!ctx.full() || !C.scene) return;
    const to = target({ now: '', overview: true, done: [] }, ''), from = now();
    to.s *= 0.96;
    C.camAnim = ctx.a(cam, [{ transform: tf(from) }, { transform: tf(to) }], { duration: 700, easing: EASE, fill: 'forwards' });
  }

  // ---- overlays: drawn on top of the chart, gone with the next line ------------------------------------------------
  function clearFx() {
    const s = svg();
    if (!s) return;
    s.querySelectorAll('.fx-o').forEach((n) => { n.getAnimations({ subtree: true }).forEach((a) => a.cancel()); n.remove(); });
    s.querySelectorAll('.fx-turn').forEach((n) => n.classList.remove('fx-turn'));
  }
  function over() {
    const s = svg();
    let g = s.querySelector('g.fx-over');
    if (!g) { g = svgEl('g', { 'aria-hidden': 'true' }, 'fx-over fx-o'); s.append(g); }
    return g;
  }
  const gone = (a, el) => { if (a) a.finished.then(() => el.remove(), () => el.remove()); else el.remove(); };

  /** 1. Path tracing along the connector between two boxes (either way round). */
  function trace(variant, a, b) {
    const s = svg();
    let link = s.querySelector('g.fl-link[data-from="' + a + '"][data-to="' + b + '"]'), back = false;
    if (!link) { link = s.querySelector('g.fl-link[data-from="' + b + '"][data-to="' + a + '"]'); back = true; }
    const path = link && link.querySelector('path.fl-edge');
    if (!path) return;
    const L = path.getTotalLength(), d = path.getAttribute('d'), g = over();
    const v = ctx.level() >= 2 && variant !== 'draw' ? 'draw' : variant; // a slow device keeps the cheapest
    if (v === 'packet') {
      const dot = svgEl('circle', { r: 4.5, cx: 0, cy: 0 }, 'fx-packet');
      const pts = [];
      for (let i = 0; i <= 24; i += 1) { const p = path.getPointAtLength(L * (back ? 1 - i / 24 : i / 24)); pts.push({ transform: 'translate(' + p.x.toFixed(1) + 'px,' + p.y.toFixed(1) + 'px)' }); }
      pts[0].opacity = 0; pts[2].opacity = 1; pts[22].opacity = 1; pts[24].opacity = 0;
      g.append(dot); gone(ctx.a(dot, pts, { duration: 1100, easing: 'ease-in-out' }), dot);
      return;
    }
    const p = svgEl('path', { d }, v === 'comet' ? 'fx-comet' : 'fx-trace');
    g.append(p);
    if (v === 'comet') {
      const seg = Math.min(26, L / 3);
      p.style.strokeDasharray = seg.toFixed(1) + ' ' + (L + seg).toFixed(1);
      gone(ctx.a(p, [{ strokeDashoffset: back ? -L : seg }, { strokeDashoffset: back ? seg : -L }], { duration: 950, easing: 'ease-in-out' }), p);
      return;
    }
    p.style.strokeDasharray = L.toFixed(1);
    const draw = ctx.a(p, [{ strokeDashoffset: back ? -L : L }, { strokeDashoffset: 0 }], { duration: 800, easing: OUT });
    gone(draw ? ctx.a(p, [{ opacity: 1 }, { opacity: 0 }], { duration: 600, delay: 1100, fill: 'forwards' }) : null, p);
  }

  /** 2. The spoken box's entrance. */
  function enter(variant, n) {
    const shape = n.querySelector('.fl-shape'), card = shape && shape.querySelector('.fl-card');
    if (!card) return;
    const bb = shape.getBBox(), g = svgEl('g', { 'aria-hidden': 'true' }, 'fx-nov fx-o');
    n.append(g);
    if (variant === 'ping') {
      const ring = card.cloneNode(false);
      ring.setAttribute('class', 'fx-ring'); g.append(ring);
      gone(ctx.a(ring, [{ transform: 'scale(1)', opacity: 0.9 }, { transform: 'scale(1.3)', opacity: 0 }], { duration: 900, iterations: 2, easing: 'ease-out' }), ring);
    } else if (variant === 'bracket') {
      const x0 = bb.x - 5, y0 = bb.y - 5, x1 = bb.x + bb.width + 5, y1 = bb.y + bb.height + 5;
      [[x0, y0, 'M0 10V0H10', -10, -10], [x1, y0, 'M-10 0H0V10', 10, -10], [x0, y1, 'M0 -10V0H10', -10, 10], [x1, y1, 'M-10 0H0V-10', 10, 10]]
        .forEach(([x, y, d, dx, dy], i) => {
          const w = svgEl('g', { transform: 'translate(' + x.toFixed(1) + ' ' + y.toFixed(1) + ')' }), p = svgEl('path', { d }, 'fx-brk');
          w.append(p); g.append(w);
          ctx.a(p, [{ transform: 'translate(' + dx + 'px,' + dy + 'px)', opacity: 0 }, { transform: 'translate(0,0)', opacity: 1 }], { duration: 450, delay: i * 60, easing: OUT, fill: 'backwards' });
        });
      gone(ctx.a(g, [{ opacity: 1 }, { opacity: 0 }], { duration: 500, delay: 1700, fill: 'forwards' }), g);
    } else if (variant === 'scan') {
      const fill = svgEl('rect', { x: bb.x, y: bb.y, width: bb.width, height: bb.height, rx: 6 }, 'fx-scanfill');
      const line = svgEl('rect', { x: bb.x - 3, y: bb.y, width: bb.width + 6, height: 2 }, 'fx-scanline');
      g.append(fill, line);
      ctx.a(fill, [{ transform: 'scaleY(1)' }, { transform: 'scaleY(0)' }], { duration: 750, easing: EASE, fill: 'forwards' });
      gone(ctx.a(line, [{ transform: 'translateY(0)', opacity: 1 }, { transform: 'translateY(' + bb.height.toFixed(1) + 'px)', opacity: 0.2 }], { duration: 750, easing: EASE }), g);
    } else {
      const acc = ctx.tok().accent;
      const glow = (r) => (acc ? 'drop-shadow(0 0 ' + r + 'px ' + acc + ')' : 'none');
      g.remove();
      ctx.a(n, [{ translate: '0 0', filter: glow(0) }, { translate: '0 -5px', filter: glow(12), offset: 0.45 }, { translate: '0 0', filter: glow(3) }], { duration: 950, easing: 'ease-out' });
    }
  }

  /** 3. The kind accent of the spoken box. */
  function accent(variant, n) {
    const glyph = n.querySelector('.fl-glyph');
    if (variant === 'lock' && glyph) {
      ctx.a(glyph, [{ transform: 'scale(1.9) rotate(-25deg)', opacity: 0 }, { transform: 'scale(.85) rotate(4deg)', opacity: 1, offset: 0.7 }, { transform: 'scale(1) rotate(0deg)', opacity: 1 }], { duration: 650, delay: 300, easing: 'ease-out', fill: 'backwards' });
    } else if (variant === 'fill') {
      const card = n.querySelector('.fl-shape .fl-card'), bb = n.querySelector('.fl-shape').getBBox();
      if (!card) return;
      const id = 'fxc' + (++C.seq) + Math.floor(performance.now()), clip = svgEl('clipPath', { id }, 'fx-o'), g = svgEl('g', { 'clip-path': 'url(#' + id + ')', 'aria-hidden': 'true' }, 'fx-o');
      const shapeCopy = card.cloneNode(false), rect = svgEl('rect', { x: bb.x, y: bb.y, width: bb.width, height: bb.height }, 'fx-fill');
      shapeCopy.removeAttribute('class'); clip.append(shapeCopy); g.append(rect); n.append(clip, g);
      ctx.a(rect, [{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }], { duration: 900, delay: 250, easing: OUT, fill: 'backwards' });
      gone(ctx.a(rect, [{ opacity: 1 }, { opacity: 0 }], { duration: 700, delay: 1500, fill: 'forwards' }), g);
    } else if (variant === 'turn') {
      const inner = n.querySelector('.fl-inner');
      if (!inner) return;
      inner.classList.add('fx-turn');
      const a = ctx.a(inner, [{ strokeDashoffset: 0 }, { strokeDashoffset: -64 }], { duration: 1400, delay: 200, easing: 'linear' });
      if (a) a.finished.then(() => inner.classList.remove('fx-turn'), () => inner.classList.remove('fx-turn')); else inner.classList.remove('fx-turn');
    } else if (variant === 'wave' && glyph) {
      glyph.style.transformOrigin = '50% 100%';
      ctx.a(glyph, [{ transform: 'rotate(0deg)' }, { transform: 'rotate(-18deg)' }, { transform: 'rotate(14deg)' }, { transform: 'rotate(-8deg)' }, { transform: 'rotate(0deg)' }], { duration: 1100, delay: 250, easing: 'ease-in-out' });
    } else if (variant === 'nudge' && glyph) {
      ctx.a(glyph, [{ transform: 'translateX(0)' }, { transform: 'translateX(3px)' }, { transform: 'translateX(0)' }, { transform: 'translateX(3px)' }, { transform: 'translateX(0)' }], { duration: 900, delay: 250 });
    }
  }

  /** The stage for this line: lit boxes, the camera, and (playing, Full motion) the effects the plan picked. */
  function apply(sc, fx, instant) {
    const first = !C.scene;
    C.scene = sc;
    clearFx();
    lit(sc);
    const live = !instant && ctx.full();
    aim(sc, fx.cam, !live || (!fx.cam && !fx.establish && !first), live && !!fx.establish);
    if (!live || !sc.now) return;
    const n = node(sc.now);
    if (!n) return;
    if (fx.trace) { const pair = sc.edge || (fx.from ? [fx.from, sc.now] : null); if (pair) trace(fx.trace, pair[0], pair[1]); }
    if (fx.enter) enter(fx.enter, n);
    if (fx.accent) accent(fx.accent, n);
  }
  /** The stage changed size: the camera keeps the spoken box in view (no animation). */
  function relayout() { if (C.scene) aim(C.scene, '', true); }
  function reset() { if (C.mo) C.mo.disconnect(); C.mo = null; cam.textContent = ''; C.page = ''; C.fig = null; C.box = null; C.scene = null; }
  return { mount, has, apply, pullback, relayout, reset, clear: clearFx, svg };
}
