// src/jarvis/api/static/console-book-fx-cards.js -- R6.4 D11 (docs/plans/r6-4-book-look.md): the effects engine's card
// layer, an ES module imported by console-book-fx.js. The section cards a page's `show` cues call up -- the title card
// ("Module", "Part", "Screen"), In plain words, How it works (a page with no flowchart), the Example as a storyboard of
// captioned frames, What it costs, When it fails (an amber frame with a soft alert) -- each entering with one of four HUD
// reveals (split, typewriter, decode, iris); their points come in one by one as the lines are told, and the card follows
// the newest one. The `count` cue's readout counts up to the filled number (a Rupee sign kept) beside a bar. Text comes
// from the page JSON and the script, always by textContent (inline `code` as <code>). Calm: cross-fades only; Off: none.
// Motion: transform, opacity and filter only (the Web Animations API). No build step; CSP script-src 'self'; ASCII; <= 400.
import { lead, parseCount, rng, hash, sentences } from './console-book-fx-plan.js';

const KIND = Object.freeze({ module: 'Module', card: 'Part', screen: 'Screen', service: 'Outside service', chapter: 'Story' });
const LABEL = Object.freeze({ plain: 'In plain words', example: 'Example', how: 'How it works', costs: 'What it costs',
  fails: 'When it fails' });
const CAP = Object.freeze({ plain: 4, how: 6, fails: 5, example: 6 });
const OUT = 'cubic-bezier(.16,1,.3,1)', EASE = 'cubic-bezier(.45,0,.2,1)';
const SVGNS = 'http://www.w3.org/2000/svg';
const WARN = 'M10 3 2.5 16.5h15zM10 8v4M10 14.2v.1';

function mk(tag, cls, words) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (words !== undefined) n.textContent = words;
  return n;
}
/** Text with `code` spans: text nodes and <code>, never markup. */
function rich(el, text) {
  String(text || '').split('`').forEach((part, i) => { if (part) el.append(i % 2 ? mk('code', '', part) : document.createTextNode(part)); });
  return el;
}
function warn() {
  const s = document.createElementNS(SVGNS, 'svg'), p = document.createElementNS(SVGNS, 'path');
  s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('focusable', 'false');
  p.setAttribute('d', WARN); s.append(p);
  return s;
}
const sectionText = (page, id) => {
  const s = page && Array.isArray(page.sections) ? page.sections.find((x) => x && x.id === id) : null;
  return s && typeof s.text === 'string' ? s.text : '';
};
/** Letters as spans (for the typewriter and decode reveals); the words stay whole for a screen reader. */
function letters(el) {
  const text = el.textContent;
  el.textContent = '';
  const sr = mk('span', 'sr-only', text), vis = mk('span', 'fx-chars');
  vis.setAttribute('aria-hidden', 'true');
  Array.from(text).forEach((ch) => vis.append(mk('span', 'fx-ch', ch)));
  el.append(sr, vis);
  return Array.from(vis.children);
}

/** The card layer inside `layer`, the readout spot in `hud`; ctx = the engine's {a, full, calm, seed}. */
export function cardLayer(layer, hud, ctx) {
  const K = { key: '', card: null, win: null, list: null, items: [], shown: 0, slot: null, shift: 0 };

  function head(card, label, extra) {
    const h = mk('div', 'fx-head'), k = mk('span', 'fx-k', label);
    h.append(k);
    if (extra) h.append(mk('span', 'fx-tag', extra));
    card.append(h);
    return k;
  }
  /** Build the card for a view: its label, its body, the points it will tell one by one. */
  function build(sc, page, info) {
    const card = mk('div', 'fx-card'), inner = mk('div', 'fx-cardin');
    card.dataset.kind = sc.view; card.append(inner);
    K.items = []; K.list = null; K.win = null; K.slot = null; K.shown = 0; K.shift = 0;
    const title = page && typeof page.title === 'string' ? page.title : '';
    if (sc.view === 'title') {
      head(inner, (KIND[page && page.kind] || 'Page') + ' \u00b7 page ' + info.n + ' of ' + info.of);
      const same = !info.chapter || info.chapter === title;
      inner.append(mk('h3', 'fx-h', title), mk('span', 'fx-rule'),
        mk('p', 'fx-sub', same ? 'This chapter: ' + info.of + (info.of === 1 ? ' page' : ' pages') : 'From the chapter ' + info.chapter));
      return card;
    }
    head(inner, LABEL[sc.view] || '', sc.view === 'example' ? 'Made-up' : title);
    if (sc.view === 'costs') { // a Rupee mark: the card is about money (a number only ever comes from a count cue)
      const coin = mk('span', 'fx-coin', '\u20b9');
      coin.setAttribute('aria-hidden', 'true');
      inner.firstChild.prepend(coin);
    }
    K.slot = mk('div', 'fx-slot'); inner.append(K.slot); // a count told on this card shows here
    const text = sectionText(page, sc.view === 'chart' ? 'how' : sc.view);
    if (sc.view === 'costs') {
      inner.append(rich(mk('p', 'fx-lead'), lead(text, 300)));
      return card;
    }
    const items = sentences(text, sc.view === 'example' ? 200 : 240).slice(0, CAP[sc.view] || 4);
    K.win = mk('div', 'fx-win');
    K.list = mk('ol', sc.view === 'example' ? 'fx-board' : 'fx-pts');
    K.items = items.map((s, i) => {
      const li = mk('li', sc.view === 'example' ? 'fx-frame next' : 'fx-pt next');
      if (sc.view === 'example') li.append(mk('span', 'fx-no', 'Frame ' + String(i + 1).padStart(2, '0')));
      else if (sc.view === 'fails') li.append(warn());
      else li.append(mk('span', 'fx-mk'));
      li.append(rich(mk('p', ''), s));
      K.list.append(li);
      return li;
    });
    K.win.append(K.list); inner.append(K.win);
    return card;
  }

  // ---- 5. the card's HUD reveal --------------------------------------------------------------------------------------
  function reveal(card, variant) {
    const inner = card.firstChild, k = inner.querySelector('.fx-k'), h = inner.querySelector('.fx-h');
    const rule = inner.querySelector('.fx-rule');
    if (rule) ctx.a(rule, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: 700, delay: 250, easing: OUT, fill: 'backwards' });
    if (variant === 'split') {
      const seam = mk('span', 'fx-seam'), t = mk('span', 'fx-shut t'), b = mk('span', 'fx-shut b');
      inner.append(t, b, seam);
      ctx.a(seam, [{ transform: 'scaleX(0)', opacity: 1 }, { transform: 'scaleX(1)', opacity: 1, offset: 0.35 }, { transform: 'scaleX(1)', opacity: 0 }], { duration: 760, easing: EASE });
      const end = (n) => (a) => { if (a) a.finished.then(() => n.remove(), () => n.remove()); else n.remove(); };
      end(t)(ctx.a(t, [{ transform: 'translateY(0)' }, { transform: 'translateY(-101%)' }], { duration: 620, delay: 240, easing: EASE, fill: 'backwards' }));
      end(b)(ctx.a(b, [{ transform: 'translateY(0)' }, { transform: 'translateY(101%)' }], { duration: 620, delay: 240, easing: EASE, fill: 'backwards' }));
      end(seam)(null);
      return;
    }
    if (variant === 'iris') {
      const ring = mk('span', 'fx-iris');
      card.append(ring);
      const a = ctx.a(ring, [{ transform: 'translate(-50%,-50%) scale(0)', opacity: 1 }, { transform: 'translate(-50%,-50%) scale(5)', opacity: 0 }], { duration: 850, easing: OUT });
      if (a) a.finished.then(() => ring.remove(), () => ring.remove()); else ring.remove();
      ctx.a(inner, [{ transform: 'scale(.94)', opacity: 0, filter: 'blur(3px)' }, { transform: 'scale(1)', opacity: 1, filter: 'blur(0)' }], { duration: 650, delay: 120, easing: OUT, fill: 'backwards' });
      return;
    }
    const chars = [k, h].filter(Boolean).flatMap((el) => letters(el));
    if (variant === 'type') {
      const step = Math.max(8, Math.min(32, 700 / Math.max(1, chars.length)));
      chars.forEach((c, i) => ctx.a(c, [{ opacity: 0 }, { opacity: 1 }], { duration: 60, delay: i * step, fill: 'backwards' }));
      const caret = mk('span', 'fx-caret');
      (h || k).append(caret);
      const a = ctx.a(caret, [{ opacity: 1 }, { opacity: 0 }], { duration: 500, delay: chars.length * step, iterations: 2, direction: 'alternate' });
      if (a) a.finished.then(() => caret.remove(), () => caret.remove()); else caret.remove();
    } else { // decode: the letters come into focus in a scrambled order
      const r = rng(hash(ctx.seed() + ':' + K.key));
      chars.forEach((c) => ctx.a(c, [{ opacity: 0, filter: 'blur(6px)', transform: 'translateY(-3px)' }, { opacity: 1, filter: 'blur(0)', transform: 'translateY(0)' }], { duration: 320, delay: Math.floor(r() * 520), easing: OUT, fill: 'backwards' }));
    }
    ctx.a(inner, [{ transform: 'translateY(10px)' }, { transform: 'translateY(0)' }], { duration: 600, easing: OUT });
  }

  // ---- 6 and points: the next frame or point comes in; the card follows the newest --------------------------------------
  function enterItem(li, variant, board) {
    const from = variant === 'flip' ? (board ? 'perspective(700px) rotateY(70deg)' : 'perspective(700px) rotateX(-65deg)')
      : variant === 'slide' ? (board ? 'translateX(36px)' : 'translateX(-26px)') : 'translateY(18px) scale(.97)';
    ctx.a(li, [{ transform: from, opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 620, easing: OUT, fill: 'backwards' });
  }
  function progress(sc, fx, instant) {
    if (!K.items.length) return;
    const want = Math.max(1, Math.min(K.items.length, Math.ceil((K.items.length * sc.frame) / Math.max(1, sc.frames))));
    const board = sc.view === 'example';
    K.items.forEach((li, i) => {
      const was = !li.classList.contains('next');
      li.classList.toggle('next', i >= want);
      li.classList.toggle('past', i < want - 1);
      li.classList.toggle('cur', i === want - 1);
      if (!was && i < want && !instant && K.shown > 0) enterItem(li, fx.frame || 'rise', board);
    });
    K.shown = want;
    follow(K.items[want - 1], instant);
  }
  /** Keep the newest point in view: the list moves up when it runs past the card's window. */
  function follow(li, instant) {
    if (!K.win || !K.list || !li) return;
    const room = K.win.clientHeight, over = K.list.offsetHeight - room;
    const shift = over > 0 ? Math.max(0, Math.min(over, li.offsetTop + li.offsetHeight + 8 - room)) : 0;
    if (shift) K.win.dataset.shifted = '1'; else delete K.win.dataset.shifted;
    if (shift === K.shift) return;
    const from = K.shift;
    K.shift = shift; K.list.style.transform = shift ? 'translateY(' + (-shift) + 'px)' : '';
    if (!instant) ctx.a(K.list, [{ transform: 'translateY(' + (-from) + 'px)' }, { transform: 'translateY(' + (-shift) + 'px)' }], { duration: 700, easing: EASE });
  }

  // ---- 8. the failure frame's alert (at most one soft pulse a second, never a flash) -----------------------------------
  function alert(card, variant) {
    const inner = card.firstChild;
    if (variant === 'sweep') {
      const band = mk('span', 'fx-aband');
      inner.append(band);
      const a = ctx.a(band, [{ transform: 'translateX(-110%)' }, { transform: 'translateX(110%)' }], { duration: 1500, delay: 300, easing: EASE, fill: 'backwards' });
      if (a) a.finished.then(() => band.remove(), () => band.remove()); else band.remove();
      return;
    }
    const ring = mk('span', 'fx-aring');
    inner.append(ring);
    if (variant === 'corners') {
      ['tl', 'tr', 'bl', 'br'].forEach((c, i) => {
        const s = mk('span', 'fx-acorner ' + c);
        ring.append(s);
        const dx = c[1] === 'l' ? -14 : 14, dy = c[0] === 't' ? -14 : 14;
        ctx.a(s, [{ transform: 'translate(' + dx + 'px,' + dy + 'px)', opacity: 0 }, { transform: 'translate(0,0)', opacity: 1 }], { duration: 520, delay: 200 + i * 70, easing: OUT, fill: 'backwards' });
      });
      ctx.a(ring, [{ opacity: 0.35 }, { opacity: 1 }, { opacity: 0.6 }], { duration: 1600, delay: 700, easing: 'ease-in-out', fill: 'backwards' });
      return;
    }
    ctx.a(ring, [{ opacity: 0.25 }, { opacity: 1 }, { opacity: 0.25 }], { duration: 2400, iterations: 3, easing: 'ease-in-out' });
  }

  /** The card for this line: a new one when the view starts (with its reveal), else its next point. */
  function show(sc, fx, page, info, instant) {
    const key = sc.page + ':' + sc.view + ':' + sc.run;
    const live = !instant && ctx.full();
    if (key !== K.key) {
      K.key = key;
      const card = build(sc, page, info);
      layer.replaceChildren(card); K.card = card;
      if (live && fx.reveal) reveal(card, fx.reveal);
      if (live && sc.view === 'fails') alert(card, fx.alert || 'pulse');
    }
    progress(sc, fx, !live);
  }

  // ---- 7. the readout: a count-up to the filled number, a bar beside it -------------------------------------------------
  function clearHud() {
    Array.from(hud.children).forEach((n) => {
      const a = ctx.a(n, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, fill: 'forwards' });
      if (a) a.finished.then(() => n.remove(), () => n.remove()); else n.remove();
    });
  }
  function readout(target, unit, variant, instant, inCard) {
    const c = parseCount(target);
    if (!c) return;
    const fmt = (v) => c.prefix + (c.commas ? v.toLocaleString('en-IN', { minimumFractionDigits: c.decimals, maximumFractionDigits: c.decimals }) : v.toFixed(c.decimals));
    const box = mk('div', 'fx-read'), num = mk('b', 'fx-num', fmt(c.value)), bar = mk('span', 'fx-bar'), fill = mk('i');
    num.style.minWidth = fmt(c.value).length + 'ch';
    bar.setAttribute('aria-hidden', 'true'); bar.append(fill);
    box.append(num);
    if (unit) box.append(mk('small', 'fx-unit', unit));
    box.append(bar);
    const host = inCard && K.slot && K.card && K.card.isConnected ? K.slot : hud;
    box.dataset.in = host === hud ? 'hud' : 'card';
    host.replaceChildren(box);
    if (host !== hud) follow(K.items[K.shown - 1], true); // the card's window is smaller now: its newest point stays in view
    if (instant || !ctx.full()) return;
    const stamp = variant === 'stamp', dur = stamp ? 900 : 1300, start = stamp ? 0.55 : 0;
    if (host === hud) ctx.a(box, [{ transform: 'translateY(-10px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 450, easing: OUT });
    if (stamp) ctx.a(num, [{ transform: 'scale(1.35)', filter: 'blur(6px)' }, { transform: 'scale(1)', filter: 'blur(0)' }], { duration: 520, easing: OUT });
    ctx.a(fill, [{ transform: 'scaleX(' + start + ')' }, { transform: 'scaleX(1)' }], { duration: dur, easing: 'cubic-bezier(.2,.7,.3,1)' });
    const driver = ctx.a(num, [{ opacity: 1 }, { opacity: 1 }], { duration: dur }); // the count's clock: paused with the rest
    if (!driver) return;
    const at = (f) => { const v = c.value * (start + (1 - start) * (1 - Math.pow(1 - f, 3))); return c.decimals ? Number(v.toFixed(c.decimals)) : Math.floor(v); };
    const tick = () => {
      if (!num.isConnected || driver.playState === 'finished' || driver.playState === 'idle') { num.textContent = fmt(c.value); return; }
      num.textContent = fmt(at(Math.min(1, (Number(driver.currentTime) || 0) / dur)));
      requestAnimationFrame(tick);
    };
    num.textContent = fmt(at(0));
    requestAnimationFrame(tick);
    driver.finished.then(() => { num.textContent = fmt(c.value); }, () => { num.textContent = fmt(c.value); });
  }
  function reset() { K.key = ''; layer.textContent = ''; hud.textContent = ''; K.items = []; }
  return { show, readout, clearHud, reset, key: () => K.key };
}
