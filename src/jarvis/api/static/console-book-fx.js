// src/jarvis/api/static/console-book-fx.js -- R6.4 D11 (docs/plans/r6-4-book-look.md): the chapter player's effects
// engine, an ES module imported by console-book-chapter.js (never linked by the page). No library: CSS, SVG and the Web
// Animations API, animating transform, opacity, stroke-dashoffset and filter only, colours only from the console's
// tokens. The script's cues say WHAT the stage shows (console-book-fx-plan.js works out the scene at every line); the
// engine picks HOW, from the catalogue's eleven families: path tracing, box entrances, kind accents and the camera
// (console-book-fx-chart.js); section cards, the example's storyboard, the costs count-up and the failure frame
// (console-book-fx-cards.js); the lit captions (the player); the page change (the chapter's steps slide, a wipe in the
// accent) and a slow ambient HUD grid behind the stage (here). The picker is deterministic (chapter id and line number)
// and never repeats a variant of a family twice in a row.
// Safety: pause() freezes every animation in the player (WAAPI pause(), CSS animation-play-state) -- WCAG 2.2.2; motion
// "calm" or prefers-reduced-motion: cross-fades only (CSS transitions; no camera moves, no packets, no WAAPI at all);
// "off": no animation at all, instant states; nothing repeats faster than 3 times a second; a phone, or a frame rate
// under 45 fps, drops the ambient layer first, then the packets. The player pauses it when the tab is hidden.
// Contract (I0-NOTES.md section 7): createFx(stage, {motion}) -> {cue(line, cue), page(fromId, toId), pause(), resume(),
// stop(), dispose()}; the player also uses load(), show(i, {jump}), motion(m) and state().
// No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
import { pagesOf, plan as planOf, unitOf, FAMILIES } from './console-book-fx-plan.js';
import { chartLayer } from './console-book-fx-chart.js';
import { cardLayer } from './console-book-fx-cards.js';

const MOTIONS = ['full', 'calm', 'off'];
const LOW_FPS = 45, SAMPLE_MS = 2000, AMBIENT_MS = 36000, WIPE_MS = 850;
const NONE = Object.freeze({ cue() {}, page() {}, pause() {}, resume() {}, stop() {}, dispose() {}, load() {}, show() {},
  motion() {}, state: () => ({ motion: 'off', level: 0, view: '', idx: -1, paused: false, ambient: false }) });
const media = (q) => { try { return window.matchMedia(q); } catch (_) { return { matches: false, addEventListener() {}, removeEventListener() {} }; } };
const isTransition = (x) => typeof CSSTransition === 'function' && x instanceof CSSTransition;
const norm = (m) => (MOTIONS.includes(m) ? m : (window.JarvisFX && MOTIONS.includes(window.JarvisFX.motion()) ? window.JarvisFX.motion() : 'full'));
function mk(tag, cls) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  return n;
}
export { FAMILIES };

/**
 * The engine in `stage`. options: {motion: 'full'|'calm'|'off', root: the element whose animations Pause holds (the
 * player; default the stage), steps: the chapter's step list (the page change slides its marker)}.
 */
export function createFx(stage, options = {}) {
  if (!stage || typeof stage.append !== 'function') return NONE;
  const root = options.root || stage, steps = options.steps || null;
  const reduceQ = media('(prefers-reduced-motion: reduce)'), phoneQ = media('(max-width: 860px), (pointer: coarse)');
  const st = { asked: norm(options.motion), paused: false, level: phoneQ.matches ? 1 : 0, held: [], lines: [], plan: [],
    pages: {}, titles: {}, order: [], chapter: '', title: '', idx: -1, view: '', amb: null, raf: 0, gone: false, hl: -1 };
  const motion = () => (st.asked === 'full' && reduceQ.matches ? 'calm' : st.asked);
  const full = () => motion() === 'full';

  stage.classList.add('fx-stage');
  const amb = mk('div', 'fx-amb'), chartEl = mk('div', 'fx-layer fx-chart'), cardEl = mk('div', 'fx-layer fx-cards');
  const hud = mk('div', 'fx-hud'), wipe = mk('div', 'fx-wipe');
  [amb, hud, wipe].forEach((n) => n.setAttribute('aria-hidden', 'true'));
  amb.hidden = true;
  stage.replaceChildren(amb, chartEl, cardEl, hud, wipe);

  /** Every animation goes through here: none unless motion is Full; one made while paused starts paused. */
  function a(el, frames, opts) {
    if (!full() || st.gone || !el || typeof el.animate !== 'function') return null;
    try {
      const an = el.animate(frames, opts);
      if (st.paused) { an.pause(); st.held.push(an); }
      return an;
    } catch (_) { return null; }
  }
  const tokens = () => { try { return (window.JarvisFX && window.JarvisFX.tokens()) || {}; } catch (_) { return {}; } };
  const ctx = { a, full, calm: () => motion() === 'calm', level: () => st.level, tok: tokens, seed: () => st.chapter };
  const chart = chartLayer(chartEl, ctx), cards = cardLayer(cardEl, hud, ctx);

  function applyMotion() {
    stage.dataset.motion = motion();
    if (!full()) all().forEach((x) => { if (!isTransition(x)) { try { x.cancel(); } catch (_) { /* gone */ } } });
    ambient();
  }
  const all = () => (typeof root.getAnimations === 'function' ? root.getAnimations({ subtree: true }) : []);

  // ---- 11. ambient: a slow HUD grid drift behind the stage (dropped first on a phone or a slow device) ---------------
  function ambient() {
    const want = full() && st.level === 0 && !st.gone && st.lines.length > 0;
    if (want && !st.amb) {
      amb.hidden = false;
      st.amb = a(amb, [{ transform: 'translate(0,0)' }, { transform: 'translate(-48px,-48px)' }], { duration: AMBIENT_MS, iterations: Infinity });
    } else if (!want) {
      if (st.amb) { try { st.amb.cancel(); } catch (_) { /* gone */ } }
      st.amb = null; amb.hidden = true;
    }
  }
  /** The frame rate while playing: under 45 fps over 2 s drops one layer (ambient, then the packets). */
  function sample() {
    if (st.raf || st.level >= 2 || !full() || st.paused || st.gone) return;
    let n = 0;
    const t0 = performance.now();
    const loop = (t) => {
      if (st.paused || st.gone || !full()) { st.raf = 0; return; }
      n += 1;
      if (t - t0 >= SAMPLE_MS) {
        st.raf = 0;
        if ((n * 1000) / (t - t0) < LOW_FPS) { st.level = Math.min(2, st.level + 1); ambient(); }
        return;
      }
      st.raf = requestAnimationFrame(loop);
    };
    st.raf = requestAnimationFrame(loop);
  }

  // ---- the two layers: the flowchart and the cards (a cross-fade; Calm by CSS transition, Off at once) ---------------
  function setLayer(which, fade, pullback) {
    const inc = which === 'chart' ? chartEl : cardEl, out = which === 'chart' ? cardEl : chartEl;
    if (inc.dataset.on === '1' && out.dataset.on !== '1') return;
    inc.dataset.on = '1'; out.dataset.on = '0';
    inc.removeAttribute('aria-hidden'); out.setAttribute('aria-hidden', 'true');
    if (!fade) return;
    if (pullback) chart.pullback();
    a(inc, [{ opacity: 0 }, { opacity: 1 }], { duration: 480, easing: 'ease-out' });
    a(out, [{ opacity: 1 }, { opacity: 0 }], { duration: 420, easing: 'ease-in' });
  }

  // ---- 10. page change: the steps' marker slides, a wipe in the accent crosses the stage --------------------------------
  function slideSteps(to, live) {
    if (!steps) return;
    const items = Array.from(steps.children).filter((n) => !n.classList.contains('fx-hl'));
    const li = items[to];
    let hl = steps.querySelector('.fx-hl');
    if (!li || !li.offsetHeight) { if (hl) hl.hidden = true; return; }
    if (!hl) { hl = mk('li', 'fx-hl'); hl.setAttribute('aria-hidden', 'true'); steps.append(hl); }
    hl.hidden = false;
    const from = hl.dataset.top ? Number(hl.dataset.top) : li.offsetTop;
    hl.dataset.top = String(li.offsetTop);
    hl.style.height = li.offsetHeight + 'px'; hl.style.transform = 'translateY(' + li.offsetTop + 'px)';
    if (live && from !== li.offsetTop) a(hl, [{ transform: 'translateY(' + from + 'px)' }, { transform: 'translateY(' + li.offsetTop + 'px)' }], { duration: 650, easing: 'cubic-bezier(.65,0,.35,1)' });
  }
  function turn(fromId, toId, variant) {
    st.hl = st.order.indexOf(toId);
    slideSteps(st.hl, !!variant);
    if (!variant) return;
    wipe.dataset.dir = variant;
    const frames = variant === 'v' ? [{ transform: 'translateY(-110%)' }, { transform: 'translateY(110%)' }]
      : variant === 'diag' ? [{ transform: 'translateX(-135%) skewX(-18deg)' }, { transform: 'translateX(135%) skewX(-18deg)' }]
        : [{ transform: 'translateX(-110%)' }, { transform: 'translateX(110%)' }];
    a(wipe, frames, { duration: WIPE_MS, easing: 'cubic-bezier(.65,0,.35,1)' });
  }

  // ---- a line on the stage ----------------------------------------------------------------------------------------------
  const info = (pageId) => ({ n: st.order.indexOf(pageId) + 1, of: st.order.length, chapter: st.title });
  /** Draw line i: at once for a jump (or Calm, Off, paused), else with the effects the plan picked for it. */
  function show(i, opts = {}) {
    const P = st.plan[i];
    if (!P || st.gone) return;
    const sc = P.scene, line = st.lines[i], prev = st.idx >= 0 && st.plan[st.idx] ? st.plan[st.idx].scene : null;
    const instant = !!opts.jump || st.paused || !full();
    const fx = Object.assign({}, instant ? {} : P.fx, { from: prev && prev.page === sc.page && prev.view === 'chart' ? prev.now : '' });
    st.idx = i;
    cards.clearHud();
    const page = st.pages[sc.page] || { id: sc.page, title: st.titles[sc.page] || '', kind: '', sections: [] };
    if (!prev || prev.page !== sc.page) {
      chart.mount(sc.page, page.flow || null);
      turn(prev ? prev.page : '', sc.page, prev ? fx.swap : '');
    } else if (st.hl < 0) slideSteps(st.order.indexOf(sc.page), false);
    const onChart = sc.view === 'chart' && chart.has();
    setLayer(onChart ? 'chart' : 'cards', !instant && st.view !== '', !!fx.pullback);
    st.view = onChart ? 'chart' : sc.view;
    if (onChart) chart.apply(sc, fx, instant);
    else cards.show(sc.view === 'chart' ? Object.assign({}, sc, { view: 'how' }) : sc, fx, page, info(sc.page), instant);
    if (sc.count) cards.readout(sc.count, unitOf(line.text, sc.count), fx.count, instant, sc.view === 'costs' || sc.view === 'fails');
    sample();
  }

  /** The chapter: its lines (with cues), its pages' JSON by id ({title, kind, sections, flow}) and their titles. */
  function load(ch) {
    st.chapter = String(ch.chapter || ''); st.title = String(ch.title || '');
    st.lines = Array.isArray(ch.lines) ? ch.lines : []; st.pages = ch.pages || {}; st.titles = ch.titles || {};
    const flows = {};
    Object.keys(st.pages).forEach((id) => { if (st.pages[id] && st.pages[id].flow) flows[id] = st.pages[id].flow; });
    st.plan = planOf(st.chapter, st.lines, flows);
    st.order = pagesOf(st.lines).order;
    st.idx = -1; st.view = ''; st.hl = -1;
    chart.reset(); cards.reset();
    chartEl.dataset.on = '0'; cardEl.dataset.on = '0';
    ambient();
    return st.plan;
  }
  /** Contract: a cue of a line -> that line's whole scene (its cues are applied together). */
  function cue(line, _cue) {
    const i = st.lines.findIndex((l) => l && line && l.n === line.n);
    if (i >= 0 && i !== st.idx) show(i, {});
  }
  /** Contract: a page change, on its own (show() calls it when the page of a line changes). */
  function page(fromId, toId) {
    const i = st.lines.findIndex((l) => l && l.page === toId);
    turn(fromId, toId, full() && !st.paused ? ((st.plan[i] && st.plan[i].fx.swap) || 'h') : '');
  }

  // ---- safety: pause holds everything; stop and dispose end it ----------------------------------------------------------
  function pause() {
    if (st.paused || st.gone) return;
    st.paused = true; root.dataset.fx = 'paused';
    if (st.raf) { cancelAnimationFrame(st.raf); st.raf = 0; }
    st.held = all().filter((x) => x.playState === 'running');
    st.held.forEach((x) => { try { x.pause(); } catch (_) { /* gone */ } });
  }
  function resume() {
    if (!st.paused || st.gone) return;
    st.paused = false; delete root.dataset.fx;
    const held = st.held;
    st.held = [];
    held.forEach((x) => { if (x.playState === 'paused') { try { x.play(); } catch (_) { /* gone */ } } });
    sample();
  }
  function stop() {
    if (st.raf) { cancelAnimationFrame(st.raf); st.raf = 0; }
    all().forEach((x) => { try { x.cancel(); } catch (_) { /* gone */ } });
    st.held = []; st.amb = null; amb.hidden = true;
    chart.clear(); cards.clearHud();
  }
  const onMotion = (e) => { st.asked = norm(e && e.detail ? e.detail.motion : ''); applyMotion(); };
  const onReduce = () => applyMotion();
  let rq = 0;
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => {
    if (rq) return;
    rq = requestAnimationFrame(() => { rq = 0; chart.relayout(); if (st.hl >= 0) slideSteps(st.hl, false); });
  }) : null;
  if (ro) ro.observe(stage);
  document.addEventListener('jarvis:motion', onMotion);
  if (reduceQ.addEventListener) reduceQ.addEventListener('change', onReduce);
  function dispose() {
    if (st.gone) return;
    stop(); st.gone = true;
    if (ro) ro.disconnect();
    document.removeEventListener('jarvis:motion', onMotion);
    if (reduceQ.removeEventListener) reduceQ.removeEventListener('change', onReduce);
    chart.reset(); cards.reset(); stage.textContent = ''; stage.classList.remove('fx-stage');
    delete root.dataset.fx;
  }
  applyMotion();
  return {
    cue, page, pause, resume, stop, dispose, load, show,
    motion(m) { st.asked = norm(m); applyMotion(); },
    state: () => ({ motion: motion(), level: st.level, view: st.view, idx: st.idx, paused: st.paused, ambient: !!st.amb }),
    plan: () => st.plan.slice(),
  };
}
