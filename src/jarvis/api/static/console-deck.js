// src/jarvis/api/static/console-deck.js — the Command Deck (slice 5c): floating panels, dock, rails,
// 24-hour ruler, activity radar and vitals. No build step; CSP script-src 'self'.
// Real data only: every number shown comes from a document event fired by console.js (chat,
// approvals, audit) or console-fx.js (state), or from the browser itself (clock, time zone,
// navigator.onLine). Nothing here talks to the server, and nothing here invents a reading.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const FX = window.JarvisFX || null;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
    del(k) { try { localStorage.removeItem(k); } catch (_) {} },
  };
  const media = (q) => { try { return window.matchMedia(q); } catch (_) { return { matches: false, addEventListener() {} }; } };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const motion = () => (FX ? FX.motion() : 'full');
  const phoneQ = media('(max-width: 899px)');
  const isPhone = () => phoneQ.matches;

  const LAYOUT_KEY = 'jarvis_deck_v1';
  const TAB_KEY = 'jarvis_deck_tab';
  const ORDER = ['chat', 'brief', 'approvals', 'activity', 'history', 'memory', 'integrations', 'vitals', 'voice', 'media', 'construct'];
  const STEP = 16; // keyboard move (Shift = x4)
  const RADAR_WINDOW_S = 300; // radar shows the last five minutes
  const SPARK_MAX = 20;

  // ================================================================================== panels
  const panels = {};
  document.querySelectorAll('.panel[data-panel]').forEach(el => {
    const id = el.dataset.panel;
    const h2 = el.querySelector('.ptitle h2'); if (h2) h2.tabIndex = -1;
    panels[id] = { id, el, btn: document.querySelector(`.dk[data-open="${id}"]`), resizable: !el.classList.contains('fixed-size') };
  });
  const ids = ORDER.filter(id => panels[id]);
  let layout = loadLayout();
  let zOrder = ids.slice();
  let phoneTab = ids.includes(store.get(TAB_KEY)) ? store.get(TAB_KEY) : 'chat';
  let lastApply = 0; // geometry we wrote ourselves must not be remembered as a user resize

  /** Where floating panels may live: below the ruler and the privacy banner, above the dock. */
  function deckBounds() {
    const ruler = $('ruler'), banner = $('banner'), dock = $('dock');
    let top = ruler && ruler.offsetHeight ? ruler.getBoundingClientRect().bottom : 84;
    if (banner && banner.offsetHeight) top = Math.max(top, banner.getBoundingClientRect().bottom);
    const bottom = dock && dock.offsetHeight && !isPhone() ? dock.getBoundingClientRect().top - 8 : window.innerHeight - 8;
    return { left: 8, right: window.innerWidth - 8, top: Math.round(top + 6), bottom: Math.round(bottom) };
  }
  /** CSS needs two measured lengths: the banner (phone panels start below it) and the room a
   *  panel may take (its max-height, so a corner-resize can never reach under the dock). */
  function syncMetrics() {
    const b = deckBounds(), banner = $('banner');
    root.style.setProperty('--notice-h', (banner && banner.offsetHeight ? Math.round(banner.getBoundingClientRect().height) : 0) + 'px');
    root.style.setProperty('--panel-max-h', Math.max(160, b.bottom - b.top) + 'px');
  }
  function railWidth() { const r = document.querySelector('.rail-l'); return r && r.offsetWidth ? r.offsetWidth : 190; }
  /** Default places, derived from the viewport. Only the Conversation is open at first; the rest
   *  open from the dock (Approvals opens itself when something waits; the Brief when today's
   *  brief is ready and not yet seen — console-brief.js). */
  function defaults() {
    const b = deckBounds(), rail = railWidth();
    const sL = rail + 12, sR = window.innerWidth - rail - 12;
    const bottom = b.bottom, availH = Math.max(240, bottom - b.top);
    const chatW = clamp(Math.round(window.innerWidth * 0.28), 360, 440);
    const col2 = sL + 300 + 14;
    return {
      chat: { x: sR - chatW, y: b.top, w: chatW, h: Math.min(availH, 680), open: true },
      brief: { x: sL, y: b.top, w: 380, h: Math.min(availH, 760), open: false },
      vitals: { x: sL, y: b.top, w: 300, h: null, open: false },
      activity: { x: sL, y: Math.max(b.top, bottom - 250), w: 300, h: 250, open: false },
      approvals: { x: col2, y: b.top, w: 340, h: null, open: false },
      history: { x: col2, y: b.top + 36, w: 320, h: Math.min(440, availH), open: false },
      memory: { x: Math.max(sL, sR - chatW - 14 - 400), y: b.top, w: 400, h: Math.min(availH, 760), open: false },
      integrations: { x: col2, y: b.top + 72, w: 340, h: null, open: false },
      voice: { x: Math.max(sL, sR - chatW - 14 - 380), y: b.top + 24, w: 380, h: Math.min(availH, 720), open: false },
      media: { x: Math.max(sL, sR - chatW - 14 - 420), y: b.top + 12, w: 420, h: Math.min(availH, 620), open: false },
      construct: { x: Math.max(sL, sR - chatW - 14 - 330), y: b.top, w: 330, h: Math.min(380, availH), open: false },
    };
  }
  /** Stored layout, validated field by field. Anything malformed falls back to the defaults, and a
   *  layout with every panel closed reopens the Conversation, so the deck can never come up empty. */
  function loadLayout() {
    const d = defaults();
    try {
      const saved = JSON.parse(store.get(LAYOUT_KEY) || 'null');
      const obj = (o) => !!o && typeof o === 'object' && !Array.isArray(o);
      if (!obj(saved) || saved.v !== 1 || !obj(saved.p)) return { v: 1, p: d };
      const num = (n, fb, lo, hi) => (Number.isFinite(n) && n >= lo && n <= hi ? n : fb);
      const p = {};
      ids.forEach(id => {
        const s = obj(saved.p[id]) ? saved.p[id] : {}, def = d[id];
        p[id] = { x: num(s.x, def.x, -1e4, 1e5), y: num(s.y, def.y, -1e4, 1e5), w: num(s.w, def.w, 200, 1e4),
          h: s.h === null ? null : num(s.h, def.h, 120, 1e4), open: typeof s.open === 'boolean' ? s.open : def.open };
      });
      if (!ids.some(id => p[id].open) && p.chat) p.chat.open = true;
      return { v: 1, p };
    } catch (_) {
      return { v: 1, p: d };
    }
  }
  function saveLayout() { store.set(LAYOUT_KEY, JSON.stringify(layout)); }

  function applyGeom(p) {
    const g = layout.p[p.id], b = deckBounds();
    lastApply = performance.now();
    const maxW = b.right - b.left, maxH = b.bottom - b.top;
    p.el.style.width = Math.min(g.w, maxW) + 'px';
    p.el.style.height = g.h ? Math.min(g.h, maxH) + 'px' : '';
    const pos = clampPos(p.el, g.x, g.y);
    p.el.style.left = pos.x + 'px'; p.el.style.top = pos.y + 'px';
  }
  function clampTo(x, y, w, h, b) {
    return { x: Math.round(clamp(x, b.left, Math.max(b.left, b.right - w))), y: Math.round(clamp(y, b.top, Math.max(b.top, b.bottom - h))) };
  }
  function clampPos(el, x, y) { return clampTo(x, y, el.offsetWidth || 300, el.offsetHeight || 200, deckBounds()); }
  function place(el, pos) { el.style.left = pos.x + 'px'; el.style.top = pos.y + 'px'; }
  function clearGeom(p) { ['left', 'top', 'width', 'height', 'zIndex'].forEach(k => { p.el.style[k] = ''; }); }
  function setVisible(p, on) { p.el.hidden = !on; }
  const isOpen = (id) => !!panels[id] && !panels[id].el.hidden;

  function front(p) {
    zOrder = zOrder.filter(id => id !== p.id).concat(p.id);
    zOrder.forEach((id, i) => { panels[id].el.style.zIndex = String(20 + i); panels[id].el.classList.toggle('front', id === p.id); });
  }
  function syncDock() {
    ids.forEach(id => { const p = panels[id]; if (p.btn) p.btn.setAttribute('aria-pressed', String(isOpen(id))); });
    syncMore();
  }

  // ---- phones: at most eight tabs; the "ovf" tabs live in the More sheet (native modal dialog:
  // the page behind is inert, Tab stays inside, Esc and the backdrop close it, focus returns) ----
  const moreBtn = $('dockMore'), sheet = $('moreSheet');
  const overflow = () => ids.filter(id => panels[id].btn && panels[id].btn.classList.contains('ovf'));
  const titleOf = (id) => { const h = panels[id].el.querySelector('.ptitle h2'); return h ? h.textContent.trim() : id; };
  function syncMore() {
    if (!moreBtn) return;
    const shown = isPhone() && overflow().includes(phoneTab) ? phoneTab : null;
    moreBtn.classList.toggle('on', !!shown);
    moreBtn.setAttribute('aria-label', shown ? `More panels, ${titleOf(shown)} shown` : 'More panels');
  }
  function closeSheet() { if (sheet && sheet.open) sheet.close(); }
  if (moreBtn && sheet && typeof sheet.showModal === 'function') {
    moreBtn.addEventListener('click', () => {
      if (sheet.open) { closeSheet(); return; }
      sheet.querySelectorAll('[data-sheet-open]').forEach(b => {
        const on = isPhone() && phoneTab === b.dataset.sheetOpen;
        if (on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
      });
      sheet.showModal();
      moreBtn.setAttribute('aria-expanded', 'true');
      const first = sheet.querySelector('[data-sheet-open]'); if (first) first.focus();
    });
    sheet.addEventListener('close', () => { // a chosen panel takes focus; otherwise it goes back to More
      moreBtn.setAttribute('aria-expanded', 'false');
      const a = document.activeElement;
      if (!a || a === document.body || sheet.contains(a)) moreBtn.focus({ preventScroll: true });
    });
    sheet.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); }); // the backdrop
    sheet.querySelectorAll('[data-sheet-open]').forEach(b => b.addEventListener('click', () => {
      closeSheet(); open(b.dataset.sheetOpen, { focus: true });
    }));
    const done = $('moreClose'); if (done) done.addEventListener('click', closeSheet);
  } else if (moreBtn) { // no <dialog>: no More tab, and the overflow tabs stay in the bar
    moreBtn.hidden = true; root.classList.add('no-sheet');
  }
  function focusPanel(p) {
    const target = p.id === 'chat' ? $('input') : p.el.querySelector('.ptitle h2');
    if (target) target.focus({ preventScroll: true });
  }

  function open(id, opts = {}) {
    const p = panels[id]; if (!p) return;
    if (isPhone()) {
      phoneTab = id; store.set(TAB_KEY, id);
      ids.forEach(k => setVisible(panels[k], k === id));
    } else {
      layout.p[id].open = true; setVisible(p, true); applyGeom(p); front(p); saveLayout(); layoutCore();
    }
    syncDock();
    if (opts.focus) focusPanel(p);
    document.dispatchEvent(new CustomEvent('jarvis:panel', { detail: { id, open: true } }));
  }
  function close(id, opts = {}) {
    const p = panels[id]; if (!p) return;
    if (isPhone()) { if (id !== 'chat') open('chat', { focus: !!opts.returnFocus }); return; }
    layout.p[id].open = false; setVisible(p, false); saveLayout(); syncDock(); layoutCore();
    if (opts.returnFocus && p.btn) p.btn.focus();
    document.dispatchEvent(new CustomEvent('jarvis:panel', { detail: { id, open: false } }));
  }
  function toggle(id) {
    if (isPhone()) { open(id, { focus: false }); return; }
    if (!isOpen(id)) { open(id, { focus: true }); return; }
    if (zOrder[zOrder.length - 1] !== id) { front(panels[id]); return; } // behind others: raise first
    close(id);
  }

  /** The Core centres itself in the widest free span beside the Conversation panel. */
  function layoutCore() {
    const stage = $('stage'), wrap = $('coreWrap');
    if (!stage || !wrap || isPhone() || !stage.offsetWidth) return;
    const sr = stage.getBoundingClientRect();
    let cx = sr.left + sr.width / 2, span = sr.width;
    if (isOpen('chat')) {
      const r = panels.chat.el.getBoundingClientRect();
      if (r.left < sr.right && r.right > sr.left) {
        const leftSpan = Math.max(0, r.left - sr.left), rightSpan = Math.max(0, sr.right - r.right);
        if (leftSpan >= rightSpan) { cx = sr.left + leftSpan / 2; span = leftSpan; } else { cx = r.right + rightSpan / 2; span = rightSpan; }
      }
    }
    const reads = document.querySelector('.core-read');
    const footprint = wrap.offsetWidth + (reads && reads.offsetWidth ? 2 * (reads.offsetWidth + 12) : 0);
    const scale = clamp((span - 24) / footprint, 0.42, 1);
    wrap.style.transform = `translateX(${Math.round(cx - (sr.left + sr.width / 2))}px) scale(${scale.toFixed(3)})`;
  }

  function applyMode() {
    if (isPhone()) {
      ids.forEach(id => { clearGeom(panels[id]); setVisible(panels[id], id === phoneTab); panels[id].el.classList.remove('front'); });
    } else {
      ids.forEach(id => { const p = panels[id]; setVisible(p, layout.p[id].open); if (layout.p[id].open) applyGeom(p); });
      zOrder.filter(isOpen).forEach(id => front(panels[id]));
      layoutCore();
    }
    syncDock();
  }
  function resetLayout() {
    layout = { v: 1, p: defaults() }; saveLayout();
    phoneTab = 'chat'; store.del(TAB_KEY);
    applyMode();
  }

  // ---- drag by the title bar (pointer events, captured), keyboard move on the grip button ----
  let drag = null;
  ids.forEach(id => {
    const p = panels[id], bar = p.el.querySelector('.ptitle');
    p.el.addEventListener('pointerdown', () => { if (!isPhone()) front(p); }, true);
    p.el.addEventListener('focusin', () => { if (!isPhone() && zOrder[zOrder.length - 1] !== id) front(p); });
    const closeBtn = p.el.querySelector('[data-close]');
    if (closeBtn) closeBtn.addEventListener('click', () => close(id, { returnFocus: true }));
    const grip = p.el.querySelector('[data-grip]');
    if (grip) grip.addEventListener('keydown', (e) => moveByKey(p, e));
    if (!bar) return;
    bar.addEventListener('pointerdown', (e) => {
      if (isPhone() || e.button !== 0 || (e.target.closest('button,a,input,select,textarea') && !e.target.closest('[data-grip]'))) return;
      const r = p.el.getBoundingClientRect(); // size and bounds are read once, not on every move
      drag = { p, pid: e.pointerId, dx: e.clientX - r.left, dy: e.clientY - r.top, w: r.width, h: r.height, b: deckBounds() };
      p.el.classList.add('dragging');
      try { bar.setPointerCapture(e.pointerId); } catch (_) {}
      e.preventDefault();
    });
    bar.addEventListener('pointermove', (e) => {
      if (!drag || drag.p !== p || e.pointerId !== drag.pid) return;
      place(p.el, clampTo(e.clientX - drag.dx, e.clientY - drag.dy, drag.w, drag.h, drag.b));
    });
    const end = (e) => {
      if (!drag || drag.p !== p || e.pointerId !== drag.pid) return;
      p.el.classList.remove('dragging');
      try { bar.releasePointerCapture(e.pointerId); } catch (_) {}
      drag = null; remember(p); layoutCore();
    };
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
  });
  function remember(p) {
    if (isPhone()) return;
    const g = layout.p[p.id];
    g.x = p.el.offsetLeft; g.y = p.el.offsetTop;
    if (p.resizable && p.el.offsetWidth) { g.w = p.el.offsetWidth; g.h = p.el.offsetHeight; }
    else if (p.el.offsetWidth) g.w = p.el.offsetWidth;
    saveLayout();
  }
  function moveByKey(p, e) {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!d || isPhone()) return;
    e.preventDefault();
    const k = e.shiftKey ? STEP * 4 : STEP;
    place(p.el, clampPos(p.el, p.el.offsetLeft + d[0] * k, p.el.offsetTop + d[1] * k));
    remember(p); layoutCore();
  }
  // a resize by the corner grip is remembered too (debounced; ignores our own geometry writes)
  if (window.ResizeObserver) {
    const timers = {};
    const ro = new ResizeObserver(entries => entries.forEach(en => {
      const p = panels[en.target.dataset.panel];
      if (!p || performance.now() - lastApply < 400 || isPhone() || p.el.hidden || !p.resizable || !en.contentRect.width) return;
      clearTimeout(timers[p.id]);
      timers[p.id] = setTimeout(() => { // a grown panel is pushed back inside the deck (never under the dock)
        place(p.el, clampPos(p.el, p.el.offsetLeft, p.el.offsetTop)); remember(p); if (p.id === 'chat') layoutCore();
      }, 250);
    }));
    ids.forEach(id => ro.observe(panels[id].el));
  }

  ids.forEach(id => { const b = panels[id].btn; if (b) b.addEventListener('click', () => toggle(id)); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return;
    const t = e.target;
    if (t && t.closest && (t.closest('input,textarea,select') || t.isContentEditable)) return; // Esc while typing is not "close"
    const el = document.activeElement && document.activeElement.closest ? document.activeElement.closest('.panel[data-panel]') : null;
    if (!el) return;
    e.preventDefault();
    close(el.dataset.panel, { returnFocus: true });
  });
  document.addEventListener('jarvis:reset-layout', resetLayout);
  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(reflow);
  });
  function reflow() { syncMetrics(); if (!isPhone()) ids.filter(isOpen).forEach(id => applyGeom(panels[id])); layoutCore(); drawRuler(); }
  // the privacy banner appears / disappears with the brain: panels move to stay clear of it
  if (window.ResizeObserver && $('banner')) new ResizeObserver(() => reflow()).observe($('banner'));
  if (phoneQ.addEventListener) phoneQ.addEventListener('change', () => { closeSheet(); syncMetrics(); applyMode(); });

  // ================================================================================== vitals
  // Money is shown in rupees only (slice 7b): the server converts at the day's rate and sends
  // `*_inr` beside its USD fields; every figure is an estimate, so it reads "≈ ₹". No dollar sign here.
  function rupees(v) {
    if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) return '₹0.00';
    if (v < 0.01) return '< ₹0.01';
    const d = v < 100 ? 2 : 0; // paise matter for a reply, not for a month in the hundreds
    let s;
    try { s = v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }); } catch (_) { s = v.toFixed(d); }
    return '≈ ₹' + s;
  }
  /** An exact whole-rupee amount the owner set (a limit): "₹1,00,000". */
  function wholeRupees(n) {
    if (!Number.isInteger(n)) return '';
    try { return '₹' + n.toLocaleString('en-IN'); } catch (_) { return '₹' + n; }
  }
  // wait: undefined = not loaded yet, null = could not load ("—", never a fake 0); audit likewise
  const V = { lat: [], turns: 0, brain: '—', model: '—', cost: 0, wait: undefined, audit: null, auditCount: 0, events: [], busy: false, alert: false, voice: null };
  const started = Date.now();
  const setText = (id, text) => { const el = $(id); if (el && el.textContent !== text) el.textContent = text; };
  const setCls = (id, base, extra) => { const el = $(id); if (el) el.className = base + (extra ? ' ' + extra : ''); };
  const ms = (n) => (n == null ? '—' : n >= 10000 ? (n / 1000).toFixed(1) + ' s' : Math.round(n) + ' ms');
  const avg = () => (V.lat.length ? V.lat.reduce((a, b) => a + b, 0) / V.lat.length : null);
  const hhmmss = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  function spark(svgId) {
    const svg = $(svgId); if (!svg) return;
    const line = svg.querySelector('polyline'), area = svg.querySelector('.area');
    const n = V.lat.length;
    if (!n) { line.setAttribute('points', ''); area.setAttribute('points', ''); return; }
    const lo = Math.min(...V.lat), hi = Math.max(...V.lat), span = hi - lo || 1;
    const pts = V.lat.map((v, i) => [n === 1 ? 100 : (i / (n - 1)) * 100, n === 1 ? 15 : 27 - ((v - lo) / span) * 24]);
    if (n === 1) pts.unshift([0, 15]); // one sample: a level line at mid height
    const s = pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    line.setAttribute('points', s);
    area.setAttribute('points', `0,30 ${s} 100,30`);
  }
  function renderVitals() {
    const last = V.lat.length ? V.lat[V.lat.length - 1] : null, mean = avg();
    setText('rLat', ms(last)); setText('cLat', ms(last)); setText('sLat', ms(last));
    setText('sAvg', ms(mean)); setText('cAvg', ms(mean));
    const bar = $('rLatBar'); if (bar) bar.style.width = last == null ? '0' : Math.round((last / Math.max(...V.lat)) * 100) + '%';
    const lo = Math.min(...V.lat), hi = Math.max(...V.lat);
    setText('sRange', !V.lat.length ? '—' : hi < 10000 ? `${Math.round(lo)}–${Math.round(hi)} ms` : `${ms(lo)}–${ms(hi)}`);
    spark('railSpark'); spark('vitSpark');
    const turns = String(V.turns);
    setText('rTurns', turns); setText('cTurns', turns); setText('sTurns', turns);
    setText('rBrain', V.brain); setText('sBrain', V.brain);
    setText('rModel', V.model); setText('sModel', V.model);
    setText('sCost', rupees(V.cost)); // this conversation so far (total_cost_inr)
    const known = Number.isFinite(V.wait), wait = known ? String(V.wait) : '—';
    setText('rApprovals', known ? V.wait + ' waiting' : '—'); setCls('rApprovals', 'v', V.wait ? 'warn' : '');
    setText('cWait', wait); setCls('cWait', 'v', V.wait ? 'warn' : '');
    setText('sWait', wait);
    const auditWord = V.audit == null ? '—' : V.audit ? 'Verified' : 'Tampered';
    setText('rAudit', auditWord); setCls('rAudit', 'v', V.audit == null ? '' : V.audit ? 'ok' : 'bad');
    setText('cAudit', auditWord); setCls('cAudit', 'v', V.audit == null ? '' : V.audit ? 'ok' : 'bad');
    setText('sAudit', V.audit == null ? '—' : `${auditWord} · ${V.auditCount} ${V.auditCount === 1 ? 'entry' : 'entries'}`);
    const badge = $('dockBadge'); if (badge) { badge.hidden = V.wait === 0 || V.wait === undefined; badge.textContent = wait; }
    const ab = panels.approvals && panels.approvals.btn;
    if (ab) ab.setAttribute('aria-label', V.wait === null ? 'Approvals, could not load' : V.wait ? `Approvals, ${V.wait} waiting` : 'Approvals');
    if (panels.approvals) panels.approvals.el.classList.toggle('attention', V.wait > 0);
    setText('chatMeta', V.turns ? `${V.turns} ${V.turns === 1 ? 'turn' : 'turns'}` : '');
  }
  function renderNet() {
    const on = navigator.onLine;
    const link = $('rLink');
    if (link) { link.className = 'v ' + (on ? 'ok' : 'bad'); link.lastChild.textContent = on ? 'Online' : 'Offline'; }
    setText('rNet', on ? 'Online' : 'Offline'); setCls('rNet', 'v', on ? 'ok' : 'bad');
    setText('sNet', on ? 'Online' : 'Offline');
  }
  function renderState() {
    const deck = $('app');
    if (deck) {
      deck.classList.toggle('busy', V.busy); deck.classList.toggle('alert', V.alert && !V.busy && !V.voice);
      deck.classList.toggle('listening', V.voice === 'listening'); deck.classList.toggle('speaking', V.voice === 'speaking');
    }
    setText('coreState', V.voice === 'listening' ? 'Listening' : V.voice === 'speaking' ? 'Speaking'
      : V.busy ? 'Thinking' : V.alert ? 'Needs you' : navigator.onLine ? 'Standing by' : 'Offline');
  }

  // ---- events -------------------------------------------------------------------------------
  function addEvent(ev) {
    const at = Number.isFinite(ev.at) ? ev.at : Date.now();
    V.events.push({ kind: ev.kind || 'info', text: String(ev.text || ''), at, seed: Math.random() });
    if (V.events.length > 400) V.events = V.events.slice(-400);
    if (ev.live !== false || Date.now() - at < 60000) {
      setText('logTime', hhmmss(new Date(at))); setText('logText', String(ev.text || ''));
    }
    renderEventCounts();
    if (!eventRaf) eventRaf = requestAnimationFrame(() => { eventRaf = 0; drawRuler(); radar.kick(); }); // batch bursts
  }
  let eventRaf = 0;
  function renderEventCounts() {
    const now = Date.now(), recent = V.events.filter(e => now - e.at <= RADAR_WINDOW_S * 1000);
    setText('rEvents', String(recent.length));
    const last = V.events.reduce((m, e) => (e.at > m ? e.at : m), 0);
    setText('rLast', last ? new Date(last).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '—');
  }
  document.addEventListener('jarvis:vitals', (e) => {
    const d = e.detail || {};
    if (Number.isFinite(d.rttMs)) { V.lat.push(d.rttMs); if (V.lat.length > SPARK_MAX) V.lat.shift(); }
    if (Number.isFinite(d.turns)) V.turns = d.turns;
    if ('brain' in d) V.brain = d.brain || '—';
    if ('model' in d) V.model = d.model || '—';
    if (Number.isFinite(d.cost)) V.cost = d.cost;
    renderVitals();
  });
  document.addEventListener('jarvis:approvals', (e) => {
    const d = e.detail || {}; V.wait = Number.isFinite(d.count) ? d.count : null; renderVitals();
    if (d.fresh && !isPhone()) open('approvals', { focus: false }); // something new needs the owner
  });
  document.addEventListener('jarvis:audit', (e) => {
    const d = e.detail || {}; V.audit = typeof d.verified === 'boolean' ? d.verified : null; V.auditCount = d.count || 0; renderVitals();
  });
  document.addEventListener('jarvis:event', (e) => addEvent(e.detail || {}));
  // Integrations (slice 6): console.js reports the Google link state; the rail shows it in one word
  const GOOGLE_WORDS = { linked: ['Linked', 'ok'], unlinked: ['Not linked', ''], reconnect: ['Reconnect', 'warn'] };
  document.addEventListener('jarvis:integrations', (e) => {
    const d = e.detail || {}, w = GOOGLE_WORDS[d.google];
    setText('rGoogle', w ? w[0] : '—'); setCls('rGoogle', 'v up', w ? w[1] : '');
  });
  document.addEventListener('jarvis:state', (e) => {
    const d = e.detail || {}; V.busy = !!d.busy; V.alert = !!d.alert;
    V.voice = d.voice === 'listening' || d.voice === 'speaking' ? d.voice : null;
    renderState(); radar.kick();
  });
  window.addEventListener('online', () => { renderNet(); renderState(); addEvent({ kind: 'info', text: 'Connection restored' }); });
  window.addEventListener('offline', () => { renderNet(); renderState(); addEvent({ kind: 'error', text: 'Connection lost' }); });

  // ---- clock-driven readouts: uptime, time zone, ruler "now" -------------------------------
  function tz() {
    let zone = '';
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) {}
    const off = -new Date().getTimezoneOffset(), sign = off >= 0 ? '+' : '−', a = Math.abs(off);
    return { zone, city: zone ? zone.split('/').pop().replace(/_/g, ' ') : 'Local', region: zone.includes('/') ? zone.split('/')[0] : '',
      offset: `UTC${sign}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}` };
  }
  function renderClockBits() {
    const up = Math.floor((Date.now() - started) / 1000), full = motion() === 'full';
    const hh = String(Math.floor(up / 3600)).padStart(2, '0'), mm = String(Math.floor(up / 60) % 60).padStart(2, '0'), ss = String(up % 60).padStart(2, '0');
    setText('rUptime', full ? `${hh}:${mm}:${ss}` : `${hh}:${mm}`);
    const t = tz();
    setText('rTz', t.city); setText('rTzShort', t.region); setText('rOffset', t.offset);
    try { setText('rDate', new Intl.DateTimeFormat([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).format(new Date()).replace(/,/g, '')); } catch (_) {}
    const g = $('globeBox'); if (g) g.title = `${t.zone || 'Local time'} · ${t.offset}`;
    renderEventCounts();
  }
  let clockTimer = 0;
  function restartClock() { clearInterval(clockTimer); renderClockBits(); clockTimer = setInterval(() => { renderClockBits(); drawRulerNow(); }, motion() === 'full' ? 1000 : 15000); }

  // ---- ruler: 24 h, ticks every 15 min, hour labels every 3 h, today's events, now ---------
  const ruler = $('ruler');
  function buildRuler() {
    if (!ruler) return;
    ruler.innerHTML = '';
    for (let h = 0; h <= 24; h += 3) {
      const s = document.createElement('span'); s.className = 'hr'; s.style.left = (h / 24 * 100) + '%'; s.textContent = String(h).padStart(2, '0');
      ruler.appendChild(s);
    }
    const now = document.createElement('i'); now.className = 'now'; now.id = 'rulerNow'; now.appendChild(document.createElement('b'));
    ruler.appendChild(now);
  }
  const dayFrac = (d) => (d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400;
  function drawRulerNow() {
    const n = $('rulerNow'); if (!n) return;
    const d = new Date(), f = dayFrac(d);
    n.style.left = (f * 100).toFixed(3) + '%'; n.classList.toggle('flip', f > 0.9);
    n.firstChild.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function drawRuler() {
    if (!ruler || !ruler.offsetWidth) return;
    ruler.querySelectorAll('.ev').forEach(n => n.remove());
    const today = new Date().toDateString();
    V.events.filter(e => new Date(e.at).toDateString() === today).slice(-120).forEach(e => {
      const m = document.createElement('i');
      m.className = 'ev' + (e.kind === 'approval' ? ' warn' : e.kind === 'error' ? ' bad' : '');
      m.style.left = (dayFrac(new Date(e.at)) * 100).toFixed(3) + '%';
      ruler.appendChild(m);
    });
    drawRulerNow();
  }

  // ================================================================================== radar
  // Sectors: messages you sent, replies, approvals, tool use (audit). New events appear at the rim
  // and drift to the centre over five minutes as they fade. The sweep only animates on Motion=Full.
  const radar = (() => {
    const cv = $('radar'), ctx = cv && cv.getContext ? cv.getContext('2d') : null;
    const SECTOR = { send: 0, reply: 90, info: 90, approval: 180, error: 180, tool: 270 };
    const LABELS = [['MSG', 45], ['REPLY', 135], ['APPROVAL', 225], ['TOOL', 315]];
    let W = 0, dpr = 1, raf = 0, last = 0, t = 0, visible = true, running = false;
    const pal = () => {
      const tk = FX ? FX.tokens() : { accent: '#0071E3', accent2: '#00C2E0', ink: '#3B9BFF' };
      const night = !FX || FX.surface() === 'night';
      return { a: tk.accent, b: night ? tk.accent2 : tk.ink, ink: night ? tk.accent2 : tk.ink, text: getComputedStyle(root).getPropertyValue('--ink-3').trim() || '#97A4B8', amber: '#F59E0B', night };
    };
    function size() {
      if (!ctx) return;
      dpr = Math.min(1.5, window.devicePixelRatio || 1); W = cv.clientWidth;
      cv.width = Math.round(W * dpr); cv.height = Math.round(W * dpr);
    }
    function draw() {
      if (!ctx || !W) return;
      const P = pal(), c = W / 2, R = W / 2 - 14, now = Date.now();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, W);
      ctx.lineWidth = 1;
      for (let i = 1; i <= 4; i++) { ctx.strokeStyle = hexA(P.b, i === 4 ? 0.55 : 0.22); ctx.beginPath(); ctx.arc(c, c, R * i / 4, 0, 6.283); ctx.stroke(); }
      ctx.strokeStyle = hexA(P.b, 0.18); ctx.beginPath(); ctx.moveTo(c - R, c); ctx.lineTo(c + R, c); ctx.moveTo(c, c - R); ctx.lineTo(c, c + R); ctx.stroke();
      for (let i = 0; i < 72; i++) {
        const a = i / 72 * 6.283, l = i % 6 === 0 ? 7 : 3;
        ctx.strokeStyle = hexA(P.b, i % 6 === 0 ? 0.7 : 0.35);
        ctx.beginPath(); ctx.moveTo(c + Math.cos(a) * (R + 2), c + Math.sin(a) * (R + 2)); ctx.lineTo(c + Math.cos(a) * (R + 2 + l), c + Math.sin(a) * (R + 2 + l)); ctx.stroke();
      }
      ctx.font = `400 ${Math.max(8, Math.round(W / 26))}px "Share Tech Mono", monospace`; ctx.fillStyle = P.text; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      LABELS.forEach(([s, deg]) => { const a = (deg - 90) * Math.PI / 180; ctx.fillText(s, c + Math.cos(a) * R * 0.62, c + Math.sin(a) * R * 0.62); });
      const sweep = ((t * 90) % 360);
      if (motion() === 'full') {
        const a0 = (sweep - 90) * Math.PI / 180;
        const g = ctx.createConicGradient ? ctx.createConicGradient(a0 - 1.1, c, c) : null;
        if (g) { g.addColorStop(0, hexA(P.b, 0)); g.addColorStop(0.175, hexA(P.b, P.night ? 0.28 : 0.18)); g.addColorStop(0.176, hexA(P.b, 0)); ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(c, c); ctx.arc(c, c, R, a0 - 1.1, a0); ctx.closePath(); ctx.fill(); }
        ctx.strokeStyle = hexA(P.b, 0.85); ctx.beginPath(); ctx.moveTo(c, c); ctx.lineTo(c + Math.cos(a0) * R, c + Math.sin(a0) * R); ctx.stroke();
      }
      V.events.forEach(e => {
        const age = (now - e.at) / 1000; if (age < 0 || age > RADAR_WINDOW_S) return;
        const deg = (SECTOR[e.kind] ?? 90) + 8 + e.seed * 74, a = (deg - 90) * Math.PI / 180;
        const r = R * (0.12 + 0.84 * (1 - age / RADAR_WINDOW_S));
        let lit = 1 - age / RADAR_WINDOW_S;
        if (motion() === 'full') { const diff = ((sweep - deg) % 360 + 360) % 360; lit = Math.min(1, lit * 0.6 + (diff < 50 ? (1 - diff / 50) : 0)); }
        const col = e.kind === 'approval' ? P.amber : e.kind === 'error' ? '#F2555A' : P.ink;
        const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r;
        ctx.fillStyle = hexA(col, 0.25 * lit + 0.1); ctx.beginPath(); ctx.arc(x, y, 6, 0, 6.283); ctx.fill();
        ctx.fillStyle = hexA(col, 0.45 + 0.55 * lit); ctx.beginPath(); ctx.arc(x, y, 2.4, 0, 6.283); ctx.fill();
      });
      ctx.fillStyle = hexA(P.b, 0.9); ctx.beginPath(); ctx.arc(c, c, 2, 0, 6.283); ctx.fill();
    }
    function frame(now) {
      raf = requestAnimationFrame(frame);
      if (now - last < 1000 / 30 - 1) return;
      t += Math.min(0.1, (now - last) / 1000); last = now;
      try { draw(); } catch (_) { stop(); }
    }
    function stop() { running = false; cancelAnimationFrame(raf); }
    function sync() {
      if (!ctx) return;
      const should = motion() === 'full' && visible && !document.hidden && !isPhone();
      if (should && !running) { running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
      else if (!should) { stop(); draw(); }
      setText('radarState', motion() === 'full' ? 'Live' : 'Still');
    }
    if (ctx) {
      size();
      if (window.ResizeObserver) new ResizeObserver(() => { size(); draw(); }).observe(cv);
      if (window.IntersectionObserver) new IntersectionObserver(es => { visible = es.some(x => x.isIntersecting); sync(); }).observe(cv);
      document.addEventListener('visibilitychange', sync);
      setInterval(() => { if (!running) draw(); }, 15000); // blips age even when still
    }
    return { sync, kick() { if (!running) draw(); } };
  })();
  function hexA(hex, a) {
    const h = /^#([0-9a-f]{6})$/i.exec(String(hex).trim()); if (!h) return `rgba(0,194,224,${a})`;
    const n = parseInt(h[1], 16);
    return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${clamp(a, 0, 1).toFixed(3)})`;
  }

  // ================================================================================== boot
  document.addEventListener('jarvis:motion', () => { radar.sync(); restartClock(); });
  document.addEventListener('jarvis:theme', () => radar.kick());
  buildRuler();
  syncMetrics();
  applyMode();
  renderVitals(); renderNet(); renderState(); restartClock(); drawRuler(); radar.sync();
  setText('kVerts', '13'); setText('kEdges', '13'); setText('kFps', 'CSS'); // the flat 2D preview's real counts
  addEvent({ kind: 'info', text: 'Console online' });

  window.JarvisDeck = Object.freeze({
    open: (id, opts) => open(id, opts || {}),
    close: (id) => close(id),
    isOpen,
    isPhone,
    reset: resetLayout,
    rupees,
    wholeRupees,
  });
})();
