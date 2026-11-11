// src/jarvis/api/static/console-dock.js — R6.1 D7: the dock fits every screen ("priority plus").
// The dock measures itself at every width: the tabs keep their order, and the ones that do not fit
// fold into the More sheet, last tabs first. More shows only when a tab is folded and lights up
// while a folded panel is open; the sheet lists exactly the folded tabs, in dock order. Nothing
// scrolls sideways. Chat, Brief and Approvals never fold, so the approvals badge is always on
// screen. Phones keep at most eight tabs in the bar (More included), each a 44 px touch target.
// The measure is taken against the room the window gives the dock, never the dock's own width
// (which changes with what it shows), at most once per animation frame, on resize, font load and
// theme change, so it cannot loop. Panel state stays in console-deck.js: this file reads the
// tabs' aria-pressed and opens panels through window.JarvisDeck. No build step; CSP script-src 'self'.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const dock = $('dock'), moreBtn = $('dockMore'), sheet = $('moreSheet');
  if (!dock || !moreBtn) return;

  const PINNED = 3; // the first three tabs (Chat, Brief, Approvals) never fold
  const PHONE_MAX = 8; // phones: at most eight tabs in the bar, More included (slice 8)
  const MIN_TOUCH = 44; // phones: every tab is at least a 44 px touch target (R5.1 D11)
  const EPS = 0.01; // sub-pixel slack when comparing measured lengths
  const media = (q) => { try { return window.matchMedia(q); } catch (_) { return { matches: false, addEventListener() {} }; } };
  const phoneQ = media('(max-width: 899px)'); // the phone layout, as in console-deck.js and .css
  const isPhone = () => phoneQ.matches;
  const px = (v) => parseFloat(v) || 0;
  const shown = (el) => el.getClientRects().length > 0;
  const pressed = (tab) => tab.getAttribute('aria-pressed') === 'true';

  const tabs = [...dock.querySelectorAll('.dk[data-open]')];
  const tabFor = (id) => tabs.find((t) => t.dataset.open === id) || null;
  const sep = dock.querySelector('.sep');
  // the first tab after the separator: while none of those shows, the separator is hidden too
  const afterSep = sep ? tabs.findIndex((t) => sep.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) : -1;
  const entries = new Map(sheet ? [...sheet.querySelectorAll('[data-sheet-open]')].map((b) => [b.dataset.sheetOpen, b]) : []);

  if (!sheet || typeof sheet.showModal !== 'function') { // no <dialog>: nothing folds, the dock wraps
    moreBtn.hidden = true; root.classList.add('no-sheet');
    return;
  }

  // ============================================================================== measure + fit
  /** The width the window gives the tabs: the dock's max-width on a desktop (the window less its
   *  gutters, console-deck.css) or the whole width on a phone, less the dock's padding and border. */
  function room(s) {
    const cap = parseFloat(s.maxWidth); // 'none' on a phone
    const outer = Number.isFinite(cap) ? Math.min(root.clientWidth, cap) : root.clientWidth;
    return outer - px(s.paddingLeft) - px(s.paddingRight) - px(s.borderLeftWidth) - px(s.borderRightWidth);
  }
  /** A phone tab's visible label (Integrations shows its short one; under 360 px only icons show). */
  function labelWidth(tab) {
    const label = [...tab.querySelectorAll('span')].find((s) => shown(s) && getComputedStyle(s).position !== 'absolute');
    return label ? Math.ceil(label.getBoundingClientRect().width) : 0;
  }
  /** What every tab needs, read with all of them unfolded. The reads force one layout; the tabs are
   *  folded again (apply) before the frame is painted, so the unfolded dock is never seen. */
  function measure() {
    tabs.forEach((t) => { if (t.hidden) t.hidden = false; });
    if (sep && sep.hidden) sep.hidden = false;
    if (moreBtn.hidden) moreBtn.hidden = false;
    const s = getComputedStyle(dock), phone = isPhone();
    const width = (el) => el.getBoundingClientRect().width;
    // desktop tabs keep their own widths; phone tabs share the bar, so they need their label or 44 px
    const need = (el) => (phone ? Math.max(MIN_TOUCH, labelWidth(el)) : width(el));
    let sepW = 0;
    if (sep && shown(sep)) { const ss = getComputedStyle(sep); sepW = width(sep) + px(ss.marginLeft) + px(ss.marginRight); }
    return { phone, room: room(s), gap: px(s.columnGap), tabs: tabs.map(need), more: need(moreBtn), sepW };
  }
  /** Do the first k tabs (and More, when some are left over) fit the room? */
  function fits(m, k) {
    const folded = k < m.tabs.length, items = k + (folded ? 1 : 0);
    if (m.phone) {
      if (items > PHONE_MAX) return false;
      const widest = Math.max(...m.tabs.slice(0, k), folded ? m.more : 0);
      return (m.room - m.gap * (items - 1)) / items >= widest - EPS;
    }
    const withSep = m.sepW > 0 && afterSep >= 0 && k > afterSep;
    const sum = m.tabs.slice(0, k).reduce((a, b) => a + b, 0) + (folded ? m.more : 0) + (withSep ? m.sepW : 0);
    return sum + m.gap * (items + (withSep ? 1 : 0) - 1) <= m.room + EPS;
  }
  /** How many tabs show: all when they fit, else the most that fit beside More, never fewer than
   *  the pinned three (they fit a 320 px phone with room to spare). */
  function count(m) {
    for (let k = m.tabs.length; k > PINNED; k--) if (fits(m, k)) return k;
    return Math.min(PINNED, m.tabs.length);
  }
  /** Fold every tab from index k on; show More and the matching sheet entries only when needed. */
  function apply(k) {
    const focused = document.activeElement; // read first: hiding the focused tab blurs it at once
    tabs.forEach((t, i) => { const fold = i >= k; if (t.hidden !== fold) t.hidden = fold; });
    const sepOff = afterSep >= 0 && k <= afterSep;
    if (sep && sep.hidden !== sepOff) sep.hidden = sepOff;
    const none = k >= tabs.length;
    if (moreBtn.hidden !== none) moreBtn.hidden = none;
    entries.forEach((b, id) => { const t = tabFor(id), off = !t || !t.hidden; if (b.hidden !== off) b.hidden = off; });
    if (none) closeSheet();
    rescueFocus(focused);
    syncMore();
  }
  function unfoldAll() { // the fallback: every tab reachable, even if the dock is crowded
    tabs.forEach((t) => { t.hidden = false; });
    if (sep) sep.hidden = false;
    moreBtn.hidden = true;
    closeSheet();
  }
  let raf = 0, lastWidth = -1;
  function fit() {
    lastWidth = root.clientWidth;
    try { apply(count(measure())); } catch (err) { unfoldAll(); throw err; } // reported, never silent
  }
  function schedule() { // one measure per animation frame, however many changes arrive in it
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; fit(); });
  }

  // ============================================================================== More + sheet
  const titleOf = (id) => {
    const h = document.querySelector(`.panel[data-panel="${id}"] .ptitle h2`);
    return h ? h.textContent.trim() : id;
  };
  /** More is lit while a folded panel is open; its accessible name says which. */
  function syncMore() {
    const open = tabs.filter((t) => t.hidden && pressed(t)).map((t) => titleOf(t.dataset.open));
    moreBtn.classList.toggle('on', open.length > 0);
    const label = open.length ? `More panels, ${open.join(', ')} shown` : 'More panels';
    if (moreBtn.getAttribute('aria-label') !== label) moreBtn.setAttribute('aria-label', label);
  }
  /** Focus never falls to the page: a tab that folds hands it to More; a More that goes (everything
   *  fits again) to the last tab; a sheet entry that goes to the first entry left, or to its tab
   *  once the sheet has closed. */
  function rescueFocus(was) {
    if (!was || !was.hidden) return;
    let target = null;
    if (tabs.includes(was)) target = moreBtn.hidden ? null : moreBtn;
    else if (was === moreBtn) target = tabs.filter((t) => !t.hidden).pop() || null;
    else if (sheet.contains(was)) {
      target = sheet.open ? [...entries.values()].find((b) => !b.hidden) || null : tabFor(was.dataset.sheetOpen);
    }
    if (target) target.focus({ preventScroll: true });
  }
  function closeSheet() { if (sheet.open) sheet.close(); }
  // native modal dialog: the page behind is inert, Tab stays inside, Esc and the backdrop close it
  function openSheet() {
    entries.forEach((b, id) => {
      const t = tabFor(id);
      if (t && pressed(t)) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
    });
    sheet.showModal();
    moreBtn.setAttribute('aria-expanded', 'true');
    const first = [...entries.values()].find((b) => !b.hidden);
    if (first) first.focus();
  }
  moreBtn.addEventListener('click', () => { if (sheet.open) closeSheet(); else openSheet(); });
  sheet.addEventListener('close', () => { // a chosen panel takes focus; otherwise it goes back to More
    moreBtn.setAttribute('aria-expanded', 'false');
    const a = document.activeElement;
    if ((!a || a === document.body || sheet.contains(a)) && !moreBtn.hidden) moreBtn.focus({ preventScroll: true });
  });
  sheet.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); }); // the backdrop
  entries.forEach((b, id) => b.addEventListener('click', () => {
    closeSheet();
    if (window.JarvisDeck) window.JarvisDeck.open(id, { focus: true });
  }));
  const done = $('moreClose'); if (done) done.addEventListener('click', closeSheet);

  // ============================================================================== triggers + boot
  // console-deck.js marks open panels with aria-pressed: More follows it
  new MutationObserver(syncMore).observe(dock, { subtree: true, attributes: true, attributeFilter: ['aria-pressed'] });
  if (window.ResizeObserver) { // the window's width (a height change alone never refits)
    new ResizeObserver(() => { if (root.clientWidth !== lastWidth) schedule(); }).observe(root);
  } else {
    window.addEventListener('resize', schedule);
  }
  if (phoneQ.addEventListener) phoneQ.addEventListener('change', () => { closeSheet(); schedule(); });
  if (document.fonts) { // a late web font changes the labels' widths
    if (document.fonts.ready) document.fonts.ready.then(schedule);
    if (document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', schedule);
  }
  document.addEventListener('jarvis:theme', schedule); // surface and theme (console-fx.js)
  fit();
})();
