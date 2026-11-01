// src/jarvis/api/static/console-fx.js — JARVIS console visual engine (no build step; CSP 'self').
// Surfaces (Night / Day), themes + owner colour (WCAG-checked tokens per surface), motion levels,
// the 2D Core emblem, the background field canvas, top-bar clock/status and the appearance menu.
// Loaded first; console-deck.js, console.js and console-3d.js use window.JarvisFX and listen for
// its document events (jarvis:theme, jarvis:motion, jarvis:state). Never touches server data:
// every string it renders is a constant below.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
    del(k) { try { localStorage.removeItem(k); } catch (_) {} },
  };
  const media = (q) => { try { return window.matchMedia(q); } catch (_) { return { matches: false, addEventListener() {} }; } };

  const THEMES = [
    { id: 'workshop', name: 'Workshop', feel: 'Holographic workbench, blueprint grid', accent: '#0071E3', accent2: '#00C2E0', field: 'blueprint' },
    { id: 'hotrod', name: 'Hot Rod', feel: 'Crimson and gold, metallic light sweeps', accent: '#C8102E', accent2: '#D4A017', field: 'sparks' },
    { id: 'nanotech', name: 'Nanotech', feel: 'Graphite particles that assemble into cells', accent: '#20262E', accent2: '#C9A227', field: 'nano' },
    { id: 'stealth', name: 'Stealth', feel: 'Steel and silver, the calmest field', accent: '#4A5868', accent2: '#9AA8B8', field: 'grid' },
    { id: 'reactor', name: 'Reactor', feel: 'Electric blue pulses from the Core', accent: '#1E6BFF', accent2: '#5FD4FF', field: 'rings' },
  ];
  const PRESETS = [['Holo blue', '#0071E3'], ['Cyan', '#00A3C4'], ['Emerald', '#0E9F6E'], ['Lime', '#65A30D'], ['Gold', '#D4A017'],
    ['Ember', '#F05A1A'], ['Crimson', '#C8102E'], ['Magenta', '#D6246E'], ['Violet', '#7B2CFF'], ['Indigo', '#4F46E5']];
  const MOTIONS = ['full', 'calm', 'off'];
  const SURFACES = ['night', 'day'];
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const HEX = /^#[0-9a-f]{6}$/i;

  // ---- colour maths (WCAG 2.x relative luminance) -------------------------------------------
  const WHITE = [255, 255, 255];
  const INK = [10, 18, 32];          // near-black used for text on light accents
  const PAGE_EDGE = [244, 247, 251]; // darkest Day surface text can sit on (--bg-2)
  const NIGHT_BG = [4, 7, 13];       // Night --bg
  const NIGHT_PANEL = [10, 17, 27];  // Night --panel-solid (cards are 90 % of this)
  const AA = 4.5;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const hexToRgb = (h) => { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
  const rgbToHex = (c) => '#' + c.map(v => clamp(Math.round(v), 0, 255).toString(16).padStart(2, '0')).join('').toUpperCase();
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  function rgbToHsl([r, g, b]) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    if (!d) return [0, 0, l];
    const s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h / 6, s, l];
  }
  function hslToRgb([h, s, l]) {
    if (!s) return [l * 255, l * 255, l * 255];
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
    return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
  }
  const mix = (a, b, w) => a.map((v, i) => v * w + b[i] * (1 - w));
  /** Move HSL lightness (hue and saturation kept) in `dir` (-1 darker, +1 lighter) until `rgb`
   *  reaches `target` contrast against every background in `bgs`. */
  function shiftUntil(rgb, bgs, target, dir) {
    const hsl = rgbToHsl(rgb); let out = rgb.map(Math.round);
    const worst = () => Math.min(...bgs.map(bg => contrast(out, bg)));
    while (worst() < target && (dir < 0 ? hsl[2] > 0 : hsl[2] < 1)) {
      hsl[2] = clamp(hsl[2] + dir * 0.01, 0, 1); out = hslToRgb(hsl).map(Math.round);
    }
    return out;
  }
  /** Theme tokens from one accent, for one surface.
   *  Day:   fills stay visible on white; accent-ink is darkened until text reaches AA on the page
   *         edge, the accent glow (12 %), and a 90 % white card with a dark stroke behind it.
   *  Night: fills are lightened until they read on the near-black page (3:1); accent-ink is
   *         lightened until text reaches AA on the panel, its tint, the page, and a panel with a
   *         bright glow behind it (the cards are 90 % opaque).
   *  Both:  on-accent is white or ink, whichever contrasts more; if neither reaches AA the fill
   *         itself is nudged until one does. */
  function derive(accentHex, accent2Hex, surface) {
    const night = surface === 'night';
    let accent = hexToRgb(accentHex);
    if (night) { if (contrast(accent, NIGHT_BG) < 3) accent = shiftUntil(accent, [NIGHT_BG], 3, +1); }
    else if (contrast(accent, WHITE) < 1.4) accent = shiftUntil(accent, [WHITE], 1.4, -1);
    const cw = contrast(WHITE, accent), ci = contrast(INK, accent);
    if (Math.max(cw, ci) < AA) accent = cw >= ci ? shiftUntil(accent, [WHITE], AA, -1) : shiftUntil(accent, [INK], AA, +1);
    const onAccent = contrast(WHITE, accent) >= contrast(INK, accent) ? WHITE : INK;
    const ink = night
      ? shiftUntil(accent, [NIGHT_PANEL, mix(accent, NIGHT_PANEL, 0.12), NIGHT_BG, mix(NIGHT_PANEL, WHITE, 0.9)], AA, +1)
      : shiftUntil(accent, [PAGE_EDGE, mix(accent, WHITE, 0.12), mix(INK, WHITE, 0.1)], AA, -1);
    let accent2;
    if (accent2Hex) accent2 = hexToRgb(accent2Hex);
    else { const [h, s, l] = rgbToHsl(accent); accent2 = hslToRgb([(h + 32 / 360) % 1, clamp(s * 1.05 + 0.05, 0, 1), clamp(l + 0.1, 0.45, 0.64)]); }
    if (night && contrast(accent2, NIGHT_BG) < 3) accent2 = shiftUntil(accent2, [NIGHT_BG], 3, +1);
    return { accent: rgbToHex(accent), accent2: rgbToHex(accent2), ink: rgbToHex(ink), onAccent: rgbToHex(onAccent) };
  }

  // ---- state ---------------------------------------------------------------------------------
  const reduceQ = media('(prefers-reduced-motion: reduce)');
  const state = {
    theme: THEMES.some(t => t.id === store.get('jarvis_theme')) ? store.get('jarvis_theme') : 'workshop',
    custom: HEX.test(store.get('jarvis_accent') || '') ? store.get('jarvis_accent').toUpperCase() : null,
    motion: MOTIONS.includes(store.get('jarvis_motion')) ? store.get('jarvis_motion') : (reduceQ.matches ? 'calm' : 'full'),
    surface: SURFACES.includes(store.get('jarvis_surface')) ? store.get('jarvis_surface') : 'night',
    busy: false, alert: false, offline: !navigator.onLine, voice: null, tokens: null,
  };
  const themeOf = (id) => THEMES.find(t => t.id === id) || THEMES[0];

  function applyTokens() {
    const t = themeOf(state.theme);
    const tok = derive(state.custom || t.accent, state.custom ? null : t.accent2, state.surface);
    state.tokens = tok;
    root.dataset.theme = t.id;
    root.dataset.surface = state.surface;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', state.surface === 'night' ? '#04070D' : '#FFFFFF');
    root.style.setProperty('--accent', tok.accent);
    root.style.setProperty('--accent-2', tok.accent2);
    root.style.setProperty('--accent-ink', tok.ink);
    root.style.setProperty('--on-accent', tok.onAccent);
    field.colours(hexToRgb(tok.accent), hexToRgb(tok.accent2));
    emit('jarvis:theme', { surface: state.surface, theme: t.id, tokens: Object.assign({}, tok) });
  }
  function applyMotion() {
    root.dataset.motion = state.motion;
    field.sync(); clock.restart(); setBusy(state.busy);
    emit('jarvis:motion', { motion: state.motion });
  }

  // ---- the Core (original emblem: three tick rings + breathing nucleus) -----------------------
  let coreSeq = 0;
  const f2 = (n) => Math.round(n * 100) / 100;
  function tick(deg, r0, r1, cls, w) {
    const a = (deg - 90) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return `<line class="${cls}" x1="${f2(60 + r0 * c)}" y1="${f2(60 + r0 * s)}" x2="${f2(60 + r1 * c)}" y2="${f2(60 + r1 * s)}" stroke-width="${w}"/>`;
  }
  function diamond(deg, r, size) {
    const a = (deg - 90) * Math.PI / 180, x = f2(60 + r * Math.cos(a)), y = f2(60 + r * Math.sin(a));
    return `<rect class="mark" x="${f2(x - size / 2)}" y="${f2(y - size / 2)}" width="${size}" height="${size}" transform="rotate(${deg + 45} ${x} ${y})"/>`;
  }
  function coreSVG(size) {
    const lg = size === 'lg' || size === 'xl', k = size === 'xl' ? 0.55 : lg ? 1 : 2.3; // stroke scale: the top-bar Core is ~30 px wide
    const n = lg ? 72 : 24, every = lg ? 6 : 3, gid = 'jxg' + (++coreSeq);
    let outer = `<circle class="faint" cx="60" cy="60" r="57.5" stroke-width="${0.8 * k}"/>`;
    for (let i = 0; i < n; i++) {
      const major = i % every === 0;
      outer += tick(i * 360 / n, major ? 48.5 : 52.5, 56, major ? 'tick major' : 'tick', (major ? 1.7 : 0.9) * k);
    }
    const c2 = 2 * Math.PI * 43, c3 = 2 * Math.PI * 31;
    const mid = `<circle class="arc" cx="60" cy="60" r="43" stroke-width="${3 * k}" stroke-dasharray="${f2(c2 * 70 / 360)} ${f2(c2 * 50 / 360)}"/>` +
      (lg ? diamond(95, 36.5, 4) + diamond(215, 36.5, 4) + diamond(335, 36.5, 4) : '');
    const inner = (lg ? `<circle class="faint" cx="60" cy="60" r="31" stroke-width="1" stroke-dasharray="1 3"/>` : '') +
      `<circle class="arc2" cx="60" cy="60" r="31" stroke-width="${2.2 * k}" stroke-dasharray="${f2(c3 * 40 / 360)} ${f2(c3 * 140 / 360)}"/>`;
    return `<svg viewBox="0 0 120 120" focusable="false"><defs><radialGradient id="${gid}">` +
      '<stop offset="0" stop-color="#fff"/><stop class="s1" offset=".5" stop-opacity=".55"/><stop class="s2" offset="1" stop-opacity="0"/></radialGradient></defs>' +
      `<g class="r1">${outer}</g><g class="r2">${mid}</g><g class="r3">${inner}</g>` +
      `<g class="glow"><circle cx="60" cy="60" r="22" fill="url(#${gid})"/><circle class="nucleus" cx="60" cy="60" r="${lg ? 8 : 11}" stroke-width="${1.5 * k}"/>` +
      `<circle cx="60" cy="60" r="${lg ? 3.2 : 4.5}" fill="var(--accent)"/></g></svg>`;
  }
  function core(size) {
    const sz = size === 'lg' || size === 'sm' || size === 'xl' ? size : '';
    const cls = 'core ' + sz + (state.busy ? ' busy' : '') + (state.alert ? ' alert' : '');
    return `<span class="${cls.trim()}" aria-hidden="true">${coreSVG(size)}</span>`;
  }
  const ringAnims = () => {
    const out = [];
    document.querySelectorAll('.core .r1, .core .r2, .core .r3').forEach(g => {
      if (g.getAnimations) out.push(...g.getAnimations());
    });
    return out;
  };

  // ---- status ticker + clock -------------------------------------------------------------------
  const STATUS_WORDS = { ok: 'Online', busy: 'Thinking', alert: 'Needs you', offline: 'Offline', listening: 'Listening', speaking: 'Speaking' };
  function renderStatus() {
    const el = $('status'); if (!el) return;
    const mode = state.offline ? 'offline' : state.voice ? state.voice : state.busy ? 'busy' : (state.alert ? 'alert' : 'ok');
    ['busy', 'alert', 'offline', 'listening', 'speaking'].forEach(m => el.classList.toggle(m, mode === m));
    $('statusText').textContent = STATUS_WORDS[mode];
  }
  const publishState = () => emit('jarvis:state', { busy: state.busy, alert: state.alert, offline: state.offline, voice: state.voice });
  /** Slice 9: 'listening' | 'speaking' | null, from the voice module (real microphone / playback). */
  function setVoice(mode) {
    const next = mode === 'listening' || mode === 'speaking' ? mode : null;
    if (next === state.voice) return;
    state.voice = next;
    root.dataset.voice = next || '';
    renderStatus(); publishState();
  }
  function setBusy(on) {
    state.busy = !!on;
    document.querySelectorAll('.core').forEach(c => c.classList.toggle('busy', state.busy));
    const rate = state.busy && state.motion === 'full' ? 3.2 : 1;
    ringAnims().forEach(a => { try { a.updatePlaybackRate ? a.updatePlaybackRate(rate) : (a.playbackRate = rate); } catch (_) {} });
    renderStatus(); publishState();
  }
  function setAlert(on) {
    state.alert = !!on;
    document.querySelectorAll('.core').forEach(c => c.classList.toggle('alert', state.alert));
    renderStatus(); publishState();
  }
  function setOffline() { state.offline = !navigator.onLine; renderStatus(); publishState(); }
  function ripple(el) {
    if (!el || state.motion !== 'full') return;
    el.classList.remove('ripple'); void el.offsetWidth; el.classList.add('ripple');
  }
  const clock = (() => {
    let timer = 0;
    const fmt = (sec) => { try { return new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', second: sec ? '2-digit' : undefined, hour12: false }); } catch (_) { return null; } };
    const dateFmt = (() => { try { return new Intl.DateTimeFormat([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }); } catch (_) { return null; } })();
    let f = null;
    const tickNow = () => {
      const now = new Date(), el = $('clock'), d = $('clockDate');
      if (el && f) el.textContent = f.format(now);
      if (d && dateFmt) d.textContent = dateFmt.format(now).replace(/,/g, '');
    };
    return {
      restart() {
        clearInterval(timer);
        const sec = state.motion === 'full'; f = fmt(sec); tickNow();
        timer = setInterval(tickNow, sec ? 1000 : 15000);
      },
    };
  })();

  // ---- background field: one canvas, <= 30 fps. Alphas below are final on-screen strengths
  // (<= 0.10); they are drawn x10 and the canvas element's CSS opacity (.1) scales them back,
  // so even overlapping strokes can never exceed 10 %. -----------------------------------------
  const field = (() => {
    const cv = $('field');
    const screen = cv && cv.getContext ? cv.getContext('2d') : null;
    let ctx = screen;
    const MAX_A = 0.1, FRAME_MS = 1000 / 30;
    let W = 0, H = 0, dpr = 1, kind = 'blueprint', ps = [], raf = 0, last = 0, t = 0, running = false;
    let A = [10, 132, 255], B = [0, 194, 224], origin = { x: 0, y: 0, at: -1 }, grid = null;
    const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${(clamp(a, 0, MAX_A) / MAX_A).toFixed(3)})`;
    const rnd = (a, b) => a + Math.random() * (b - a);
    const phone = () => W < 600;
    const count = () => Math.round(phone() ? clamp(W * H / 8000, 16, 40) : clamp(W * H / 16000, 24, 80));

    function coreCentre() {
      if (t - origin.at < 0.4) return origin;
      const cands = [document.querySelector('.gate.show .core'), $('coreWrap'), document.querySelector('#welcome .core'), $('orb')];
      const r = cands.map(el => (el ? el.getBoundingClientRect() : null)).find(b => b && b.width) || null;
      origin = r && r.width ? { x: r.left + r.width / 2, y: r.top + r.height / 2, at: t } : { x: W / 2, y: H / 3, at: t };
      return origin;
    }
    function line(x1, y1, x2, y2) { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
    function cross(x, y, s) { line(x - s, y, x + s, y); line(x, y - s, x, y + s); }
    function drawGrid(step, major, aMinor, aMajor, ox, oy) {
      ctx.lineWidth = 1;
      const x0 = ((ox % step) + step) % step, y0 = ((oy % step) + step) % step;
      const ix0 = Math.floor(ox / step), iy0 = Math.floor(oy / step);
      for (let x = x0 - step, i = 0; x < W + step; x += step, i++) {
        ctx.strokeStyle = rgba(A, (i - ix0) % major === 0 ? aMajor : aMinor); line(Math.round(x) + 0.5, 0, Math.round(x) + 0.5, H);
      }
      for (let y = y0 - step, j = 0; y < H + step; y += step, j++) {
        ctx.strokeStyle = rgba(A, (j - iy0) % major === 0 ? aMajor : aMinor); line(0, Math.round(y) + 0.5, W, Math.round(y) + 0.5);
      }
    }
    function cachedBlueprint() {
      if (grid && grid.w === W && grid.h === H && grid.c === A.join()) return grid.cv;
      const off = document.createElement('canvas'); off.width = Math.round(W * dpr); off.height = Math.round(H * dpr);
      const o = off.getContext('2d');
      if (!o) return null; // no 2D context: skip the grid rather than throw every frame
      o.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx = o; // the drawing helpers use `ctx`; point them at the offscreen grid for one pass
      try {
        drawGrid(28, 4, 0.04, 0.075, 0, 0);
        ctx.strokeStyle = rgba(A, 0.1);
        for (let x = 0; x < W; x += 112) for (let y = 0; y < H; y += 112) cross(x + 0.5, y + 0.5, 3);
      } finally { ctx = screen; }
      grid = { w: W, h: H, c: A.join(), cv: off };
      return off;
    }

    function hexCells(cx, cy, r, cells) {
      const centres = [[cx, cy]];
      const ring = cells >= 7 ? [0, 60, 120, 180, 240, 300] : [30, 150];
      ring.forEach(d => { const a = d * Math.PI / 180; centres.push([cx + Math.sqrt(3) * r * Math.cos(a), cy + Math.sqrt(3) * r * Math.sin(a)]); });
      const verts = [], key = new Map(), edges = new Set();
      const vid = (x, y) => { const k = Math.round(x) + ',' + Math.round(y); if (!key.has(k)) { key.set(k, verts.length); verts.push({ x, y }); } return key.get(k); };
      centres.forEach(([x, y]) => {
        const ids = [];
        for (let i = 0; i < 6; i++) { const a = (60 * i + 30) * Math.PI / 180; ids.push(vid(x + r * Math.cos(a), y + r * Math.sin(a))); }
        ids.forEach((v, i) => { const w = ids[(i + 1) % 6]; edges.add(v < w ? v + '-' + w : w + '-' + v); });
      });
      return { verts, edges: [...edges].map(e => e.split('-').map(Number)) };
    }

    const F = {
      blueprint: {
        seed() { ps = Array.from({ length: count() }, () => { const a = rnd(0, 6.283), s = rnd(6, 16); return { x: rnd(0, W), y: rnd(0, H), vx: Math.cos(a) * s, vy: Math.sin(a) * s, r: rnd(1.2, 2.2), plus: Math.random() < 0.18 }; }); },
        step(dt) { ps.forEach(p => { p.x += p.vx * dt; p.y += p.vy * dt; if (p.x < -20) p.x = W + 20; if (p.x > W + 20) p.x = -20; if (p.y < -20) p.y = H + 20; if (p.y > H + 20) p.y = -20; }); },
        draw() {
          const bp = cachedBlueprint(); if (bp) ctx.drawImage(bp, 0, 0, W, H);
          const L = phone() ? 110 : 140, L2 = L * L; ctx.lineWidth = 1;
          for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) {
            const dx = ps[i].x - ps[j].x, dy = ps[i].y - ps[j].y, d2 = dx * dx + dy * dy;
            if (d2 < L2) { ctx.strokeStyle = rgba(A, 0.075 * (1 - Math.sqrt(d2) / L)); line(ps[i].x, ps[i].y, ps[j].x, ps[j].y); }
          }
          ps.forEach(p => {
            if (p.plus) { ctx.strokeStyle = rgba(B, 0.1); ctx.lineWidth = 1.2; cross(p.x, p.y, 3.5); ctx.lineWidth = 1; return; }
            ctx.fillStyle = rgba(A, 0.1); ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
          });
        },
        still() { const bp = cachedBlueprint(); if (bp) ctx.drawImage(bp, 0, 0, W, H); },
      },
      sparks: {
        spawn(p, fresh) { p.x = rnd(-40, W); p.y = fresh ? rnd(0, H) : rnd(H * 0.55, H + 20); p.vx = rnd(14, 48); p.vy = -rnd(26, 80); p.max = rnd(1.8, 4.2); p.life = fresh ? rnd(0, p.max) : p.max; p.gold = Math.random() < 0.6; },
        seed() { ps = Array.from({ length: count() }, () => { const p = {}; F.sparks.spawn(p, true); return p; }); },
        step(dt) { ps.forEach(p => { p.vy += 9 * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt; if (p.life <= 0) F.sparks.spawn(p, false); }); },
        sweep(pos, w, peak) {
          const g = ctx.createLinearGradient(pos, 0, pos + w, w * 0.6);
          g.addColorStop(0, rgba(B, 0)); g.addColorStop(0.42, rgba(B, peak * 0.55)); g.addColorStop(0.5, rgba(A, peak));
          g.addColorStop(0.53, rgba(B, peak * 0.8)); g.addColorStop(0.62, rgba(B, peak * 0.3)); g.addColorStop(1, rgba(B, 0));
          ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
        },
        pinstripes() { ctx.strokeStyle = rgba(B, 0.035); ctx.lineWidth = 1; for (let x = -H; x < W; x += 46) line(x, H, x + H * 0.6, 0); },
        draw() {
          F.sparks.pinstripes();
          const w = Math.max(320, W * 0.28), span = W + H + w * 2;
          F.sparks.sweep(((t * 120) % span) - w - H * 0.6, w, 0.08);
          F.sparks.sweep(((t * 70 + span / 2) % span) - w - H * 0.6, w * 0.6, 0.05);
          ctx.lineCap = 'round'; ctx.lineWidth = 1.8;
          ps.forEach(p => { ctx.strokeStyle = rgba(p.gold ? B : A, 0.1 * clamp(1.6 * p.life / p.max, 0, 1)); line(p.x, p.y, p.x - p.vx * 0.2, p.y - p.vy * 0.2); });
        },
        still() { F.sparks.pinstripes(); F.sparks.sweep(W * 0.35, Math.max(320, W * 0.28), 0.06); },
      },
      nano: {
        cycle: 9.5, phase: 'flow', cluster: null,
        seed() { ps = Array.from({ length: count() }, () => ({ x: rnd(0, W), y: rnd(0, H), gold: Math.random() < 0.22 })); F.nano.phase = 'flow'; F.nano.cluster = null; },
        gather() {
          const r = phone() ? 18 : 24, cells = ps.length >= 48 ? 7 : 3;
          const cx = rnd(W * 0.12, W * 0.88), cy = rnd(H * 0.18, H * 0.82);
          const hc = hexCells(cx, cy, r, cells), free = ps.slice();
          hc.slots = hc.verts.map(v => {
            let best = -1, bd = Infinity;
            free.forEach((p, i) => { if (!p) return; const d = (p.x - v.x) ** 2 + (p.y - v.y) ** 2; if (d < bd) { bd = d; best = i; } });
            if (best < 0) return null; const p = free[best]; free[best] = null; return p;
          });
          F.nano.cluster = hc;
        },
        step(dt) {
          const ph = t % F.nano.cycle, next = ph < 5 ? 'flow' : ph < 6.4 ? 'gather' : ph < 8 ? 'hold' : 'release';
          if (next !== F.nano.phase) { if (next === 'gather') F.nano.gather(); F.nano.phase = next; }
          const hc = F.nano.cluster, pinned = new Set();
          if (hc && (next === 'gather' || next === 'hold')) {
            const k = Math.min(1, dt * (next === 'hold' ? 6 : 3.2));
            hc.slots.forEach((p, i) => { if (!p) return; pinned.add(p); p.x += (hc.verts[i].x - p.x) * k; p.y += (hc.verts[i].y - p.y) * k; });
          }
          ps.forEach(p => {
            if (pinned.has(p)) return;
            const a = (Math.sin(p.x * 0.0045 + t * 0.25) + Math.cos(p.y * 0.004 - t * 0.2)) * 1.4;
            p.x += Math.cos(a) * 18 * dt; p.y += Math.sin(a) * 18 * dt;
            if (p.x < -10) p.x = W + 10; if (p.x > W + 10) p.x = -10; if (p.y < -10) p.y = H + 10; if (p.y > H + 10) p.y = -10;
          });
        },
        draw() {
          const hc = F.nano.cluster, ph = t % F.nano.cycle;
          const a = F.nano.phase === 'gather' ? (ph - 5) / 1.4 : F.nano.phase === 'hold' ? 1 : F.nano.phase === 'release' ? 1 - (ph - 8) / 1.5 : 0;
          if (hc && a > 0) {
            ctx.strokeStyle = rgba(B, 0.1 * a); ctx.lineWidth = 1.8;
            hc.edges.forEach(([i, j]) => { const p = hc.slots[i], q = hc.slots[j]; if (p && q) line(p.x, p.y, q.x, q.y); });
          }
          ps.forEach(p => { ctx.fillStyle = rgba(p.gold ? B : A, 0.1); ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, 6.283); ctx.fill(); });
        },
        still() {
          const r = 26, w = Math.sqrt(3) * r; ctx.strokeStyle = rgba(A, 0.045); ctx.lineWidth = 1;
          for (let row = 0, y = 0; y < H + r * 2; row++, y += r * 1.5) {
            for (let x = (row % 2) * w / 2; x < W + w; x += w) {
              ctx.beginPath();
              for (let i = 0; i <= 6; i++) { const ang = (60 * i + 30) * Math.PI / 180; ctx[i ? 'lineTo' : 'moveTo'](x + r * Math.cos(ang), y + r * Math.sin(ang)); }
              ctx.stroke();
            }
          }
        },
      },
      grid: {
        seed() { ps = []; },
        step() {},
        draw() {
          const ox = t * 4, oy = t * 2.5; drawGrid(76, 3, 0.04, 0.065, ox, oy);
          ctx.strokeStyle = rgba(A, 0.08); ctx.lineWidth = 1;
          const x0 = ((ox % 228) + 228) % 228, y0 = ((oy % 228) + 228) % 228;
          for (let x = x0 - 228; x < W + 228; x += 228) for (let y = y0 - 228; y < H + 228; y += 228) cross(Math.round(x) + 0.5, Math.round(y) + 0.5, 4);
        },
        still() { F.grid.draw(); },
      },
      rings: {
        rings: [], lastSpawn: -9,
        seed() {
          F.rings.rings = []; F.rings.lastSpawn = -9;
          ps = Array.from({ length: Math.round(count() / 3) }, () => F.rings.mote({}, true));
        },
        mote(p, fresh) { const a = rnd(0, 6.283), o = coreCentre(); p.a = a; p.r = fresh ? rnd(20, Math.max(W, H) * 0.6) : rnd(20, 70); p.v = rnd(18, 40); p.ox = o.x; p.oy = o.y; return p; },
        step(dt) {
          const maxR = Math.hypot(W, H) * 0.8;
          if (t - F.rings.lastSpawn > 1.7) { F.rings.rings.push({ r: 24, alt: F.rings.rings.length % 2 }); F.rings.lastSpawn = t; }
          F.rings.rings.forEach(r => { r.r += 62 * dt; });
          F.rings.rings = F.rings.rings.filter(r => r.r < maxR);
          ps.forEach(p => { p.r += p.v * dt; if (p.r > maxR * 0.7) F.rings.mote(p, false); });
        },
        guides(o) { ctx.strokeStyle = rgba(A, 0.035); ctx.lineWidth = 1; for (let r = 110; r < Math.hypot(W, H); r += 110) { ctx.beginPath(); ctx.arc(o.x, o.y, r, 0, 6.283); ctx.stroke(); } },
        draw() {
          const o = coreCentre(), maxR = Math.hypot(W, H) * 0.8; F.rings.guides(o);
          F.rings.rings.forEach(r => { ctx.strokeStyle = rgba(r.alt ? B : A, 0.1 * Math.pow(1 - r.r / maxR, 1.3)); ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(o.x, o.y, r.r, 0, 6.283); ctx.stroke(); });
          ps.forEach(p => { ctx.fillStyle = rgba(B, 0.09); ctx.beginPath(); ctx.arc(p.ox + Math.cos(p.a) * p.r, p.oy + Math.sin(p.a) * p.r, 1.5, 0, 6.283); ctx.fill(); });
        },
        still() { const o = coreCentre(); F.rings.guides(o); [90, 200, 330].forEach((r, i) => { ctx.strokeStyle = rgba(i % 2 ? B : A, 0.07 - i * 0.015); ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(o.x, o.y, r, 0, 6.283); ctx.stroke(); }); },
      },
    };
    function frame(now) {
      raf = requestAnimationFrame(frame);
      if (now - last < FRAME_MS - 1) return;
      const dt = Math.min(0.1, (now - last) / 1000); last = now; t += dt;
      try { ctx.clearRect(0, 0, W, H); F[kind].step(dt); F[kind].draw(); }
      catch (_) { stop(); } // decoration must never spam errors; the page keeps working
    }
    function stop() { running = false; cancelAnimationFrame(raf); }
    function paintStill() { stop(); if (!ctx) return; ctx.clearRect(0, 0, W, H); origin.at = -1; F[kind].still(); }
    function sync() {
      if (!ctx) return;
      if (state.motion !== 'full') { paintStill(); return; }
      if (document.hidden) { stop(); return; }
      if (!running) { running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
    }
    function resize() {
      if (!ctx) return;
      dpr = Math.min(2, window.devicePixelRatio || 1); W = window.innerWidth; H = window.innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      grid = null; origin.at = -1; F[kind].seed();
      if (state.motion !== 'full') paintStill();
    }
    let fadeTimer = 0;
    function setKind(next) {
      if (!ctx) return;
      clearTimeout(fadeTimer); // a pending swap from a quick A->B->A switch must not land
      if (next === kind) { cv.style.opacity = ''; return; }
      const swap = () => { kind = next; origin.at = -1; F[kind].seed(); if (state.motion !== 'full') paintStill(); cv.style.opacity = ''; };
      if (state.motion === 'off' || !W) { swap(); return; }
      cv.style.opacity = '0'; fadeTimer = setTimeout(swap, 200);
    }
    if (ctx) {
      let pending = 0;
      window.addEventListener('resize', () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(resize); });
      document.addEventListener('visibilitychange', sync);
    }
    return {
      init(k) { kind = k; resize(); sync(); },
      setKind,
      sync,
      colours(a, b) { A = a; B = b; grid = null; if (ctx && W && state.motion !== 'full') paintStill(); },
      refresh() { origin.at = -1; if (ctx && W && state.motion !== 'full' && kind === 'rings') paintStill(); },
    };
  })();

  // ---- theme menu (popover on desktop, bottom sheet on phones) ---------------------------------
  const menu = $('themeMenu'), btn = $('themeBtn'), scrim = $('menuScrim');
  const MOON = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15.5 12.6A6.3 6.3 0 0 1 7.4 4.5a6.3 6.3 0 1 0 8.1 8.1z"/></svg>';
  const SUN = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="10" r="3.4"/><path d="M10 2.5v1.8M10 15.7v1.8M2.5 10h1.8M15.7 10h1.8M4.7 4.7l1.3 1.3M14 14l1.3 1.3M4.7 15.3 6 14M14 6l1.3-1.3"/></svg>';
  function buildMenu() {
    const themes = THEMES.map(t => `
      <input class="opt-in" type="radio" name="jx-theme" id="jx-t-${t.id}" value="${t.id}">
      <label class="theme-opt" for="jx-t-${t.id}"><span class="pv pv-${t.id}" aria-hidden="true"><i></i><b></b></span>
        <span><b>${t.name}</b><small>${t.feel}</small></span><span class="tick" aria-hidden="true"></span></label>`).join('');
    const swatches = PRESETS.map(([name, hex], i) => `
      <span><input class="opt-in" type="radio" name="jx-accent" id="jx-c-${i}" value="${hex}" aria-label="${name}">
      <label class="sw" for="jx-c-${i}" title="${name}" style="--c:${hex}"></label></span>`).join('');
    const motions = [['full', 'Full'], ['calm', 'Calm'], ['off', 'Off']].map(([v, l]) => `
      <span class="seg-wrap"><input class="opt-in" type="radio" name="jx-motion" id="jx-m-${v}" value="${v}"><label class="seg-opt" for="jx-m-${v}">${l}</label></span>`).join('');
    const surfaces = [['night', 'Night', MOON], ['day', 'Day', SUN]].map(([v, l, icon]) => `
      <span class="seg-wrap"><input class="opt-in" type="radio" name="jx-surface" id="jx-s-${v}" value="${v}"><label class="seg-opt" for="jx-s-${v}">${icon}${l}</label></span>`).join('');
    menu.innerHTML = '<h3 id="themeMenuTitle">Appearance</h3>' +
      `<fieldset><legend>Surface</legend><div class="seg two">${surfaces}</div></fieldset>` +
      `<fieldset><legend>Theme</legend><div class="themes">${themes}</div></fieldset>` +
      `<fieldset><legend>Accent colour</legend><div class="sw-row">${swatches}</div>` +
      '<div class="custom-row"><label class="yours" id="jxYours"><input type="color" id="jxColor" value="#7b2cff"><span>Your colour</span></label>' +
      '<button type="button" class="btn lift" id="jxReset">Reset to theme colour</button></div></fieldset>' +
      `<fieldset><legend>Motion</legend><div class="seg">${motions}</div>` +
      '<p class="fine">Calm stops the moving background, scan line and rotations, and holds the 3D scenes still. Off stops all animation. Saved on this device.</p></fieldset>' +
      '<fieldset><legend>Layout</legend><button type="button" class="btn lift row-btn" id="jxLayout">Reset layout</button>' +
      '<p class="fine">Puts every panel back in its default place and size.</p></fieldset>';
    menu.addEventListener('change', onMenuChange);
    $('jxColor').addEventListener('input', (e) => setCustom(e.target.value, false));
    $('jxReset').addEventListener('click', () => setCustom(null, true));
    $('jxLayout').addEventListener('click', () => { emit('jarvis:reset-layout', {}); closeMenu(true); });
  }
  function syncMenu() {
    menu.querySelectorAll('input[name="jx-theme"]').forEach(i => { i.checked = i.value === state.theme; });
    menu.querySelectorAll('input[name="jx-accent"]').forEach(i => { i.checked = !!state.custom && i.value.toUpperCase() === state.custom; });
    menu.querySelectorAll('input[name="jx-motion"]').forEach(i => { i.checked = i.value === state.motion; });
    menu.querySelectorAll('input[name="jx-surface"]').forEach(i => { i.checked = i.value === state.surface; });
    const preset = PRESETS.some(([, h]) => h === state.custom);
    $('jxYours').classList.toggle('on', !!state.custom && !preset);
    if (state.custom) $('jxColor').value = state.custom.toLowerCase();
    $('jxReset').disabled = !state.custom;
  }
  function setTheme(id) {
    state.theme = themeOf(id).id; store.set('jarvis_theme', state.theme);
    applyTokens(); field.setKind(themeOf(state.theme).field); syncMenu();
  }
  function setCustom(hex, save) {
    state.custom = hex && HEX.test(hex) ? hex.toUpperCase() : null;
    if (save !== false) { if (state.custom) store.set('jarvis_accent', state.custom); else store.del('jarvis_accent'); }
    applyTokens(); syncMenu();
  }
  function setMotion(m) { state.motion = MOTIONS.includes(m) ? m : 'full'; store.set('jarvis_motion', state.motion); applyMotion(); syncMenu(); }
  function setSurface(v) { state.surface = SURFACES.includes(v) ? v : 'night'; store.set('jarvis_surface', state.surface); applyTokens(); syncMenu(); }
  function onMenuChange(e) {
    const el = e.target;
    if (el.name === 'jx-theme') setTheme(el.value);
    else if (el.name === 'jx-accent') setCustom(el.value, true);
    else if (el.name === 'jx-motion') setMotion(el.value);
    else if (el.name === 'jx-surface') setSurface(el.value);
    else if (el.id === 'jxColor') setCustom(el.value, true);
  }
  const isOpen = () => !menu.hidden;
  function placeMenu() {
    const r = btn.getBoundingClientRect();
    menu.style.top = Math.round(r.bottom + 12) + 'px';
    menu.style.right = Math.max(8, Math.round(window.innerWidth - r.right - 6)) + 'px';
  }
  function openMenu() {
    syncMenu(); menu.hidden = false; btn.setAttribute('aria-expanded', 'true'); placeMenu();
    scrim.hidden = window.innerWidth >= 900;
    const first = menu.querySelector('input[name="jx-theme"]:checked') || menu.querySelector('input');
    if (first) first.focus();
  }
  function closeMenu(returnFocus) {
    if (!isOpen()) return;
    menu.hidden = true; scrim.hidden = true; btn.setAttribute('aria-expanded', 'false');
    if (returnFocus) btn.focus();
  }
  if (menu && btn) {
    buildMenu();
    btn.addEventListener('click', () => (isOpen() ? closeMenu(true) : openMenu()));
    scrim.addEventListener('click', () => closeMenu(true));
    document.addEventListener('pointerdown', (e) => { if (isOpen() && !menu.contains(e.target) && !btn.contains(e.target) && e.target !== scrim) closeMenu(false); }, true);
    menu.addEventListener('focusout', (e) => { if (isOpen() && e.relatedTarget && !menu.contains(e.relatedTarget) && e.relatedTarget !== btn) closeMenu(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen()) { e.stopImmediatePropagation(); e.preventDefault(); closeMenu(true); } });
    window.addEventListener('resize', () => { if (isOpen()) placeMenu(); });
  }

  // ---- boot ----------------------------------------------------------------------------------
  reduceQ.addEventListener && reduceQ.addEventListener('change', () => {
    if (!MOTIONS.includes(store.get('jarvis_motion'))) { state.motion = reduceQ.matches ? 'calm' : 'full'; applyMotion(); if (menu) syncMenu(); }
  });
  const orb = $('orb'); if (orb) orb.innerHTML = coreSVG('sm');
  const big = $('coreFallback'); if (big) big.innerHTML = core('xl');
  window.addEventListener('online', setOffline); window.addEventListener('offline', setOffline);
  root.classList.add('instant');
  applyTokens();
  void getComputedStyle(root).getPropertyValue('--accent'); // commit before re-enabling transitions
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('instant')));
  field.init(themeOf(state.theme).field);
  applyMotion();

  renderStatus();

  window.JarvisFX = Object.freeze({
    core, setBusy, setAlert, setVoice, ripple,
    refresh: () => field.refresh(),
    tokens: () => Object.assign({}, state.tokens),
    surface: () => state.surface,
    motion: () => state.motion,
    state: () => ({ busy: state.busy, alert: state.alert, offline: state.offline, voice: state.voice }),
    contrast: (a, b) => contrast(hexToRgb(a), hexToRgb(b)),
    derive: (accent, accent2, surface) => derive(accent, accent2 || null, SURFACES.includes(surface) ? surface : 'night'),
  });
})();
