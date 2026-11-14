// src/jarvis/api/static/console-dock.js — R6.1 D7: the dock fits every screen ("priority plus").
// The dock measures itself at every width: the tabs keep their order, and the ones that do not fit
// fold into the More sheet, last tabs first. More shows only when a tab is folded and lights up
// while a folded panel is open; the sheet lists exactly the folded tabs, in dock order. Nothing
// scrolls sideways. A tab shows only while it holds its label with air beside it (review A, H1/M1):
// a phone tab needs its label + borders + LABEL_CLEAR (and 44 px); a desktop tab whose label is
// wider than the tab (900-1180 px) folds wherever it sits. Chat, Brief and Approvals never fold
// for lack of room; when Approvals folds for its label, More carries the approvals badge. Phones
// keep at most eight tabs in the bar (More included). The chat box's hint fits on one line too.
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

  const PINNED = 3; // the first three tabs (Chat, Brief, Approvals) never fold for lack of room
  const PHONE_MAX = 8; // phones: at most eight tabs in the bar, More included (slice 8)
  const MIN_TOUCH = 44; // phones: every tab is at least a 44 px touch target (R5.1 D11)
  const LABEL_CLEAR = 8; // phones: px of air a tab keeps beside its label (two labels never touch)
  const BADGED = 'approvals'; // its tab carries #dockBadge (the waiting count); folded, More does
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

  // R7 I0 (seam 10): the More sheet's entries are built HERE from the dock, as the page had them (same
  // order, words and markup): every tab after Chat and Brief, with its own icon and name and one line
  // on what the panel is for. A tab with no line gets no entry (tests keep the list complete).
  const DESCRIBE = {
    approvals: 'Anything that sends, pays or can\'t be undone, waiting for your yes',
    activity: 'Every tool JARVIS used, from its tamper-checked log',
    history: 'Your past conversations, to reopen or delete',
    memory: 'What JARVIS remembers about you, to correct or forget',
    integrations: 'Your linked Google account, alerts and the systems check',
    vault: 'Your ID documents and their expiry reminders',
    things: 'Where you keep your passport, keys and papers',
    notes: 'Notes, voice memos and saved links',
    privacy: 'Everything JARVIS keeps about you, with export and delete',
    home: 'Arm the burglar alarm, the camera\'s feed and history',
    faces: 'People JARVIS may recognise at home, with their consent',
    vitals: 'Reply speed, this month\'s spend and your limit',
    connectors: 'GitHub, your YouTube channel and Google Photos',
    people: 'Public figures and work due-diligence, profiles open in your browser',
    book: 'How JARVIS is built, sealed in your vault with each release',
    voice: 'JARVIS\'s voice, speed and wit; how this device listens',
    media: 'Play the videos and music JARVIS found for you',
    construct: 'The rotating hologram',
    helpers: 'Bills, chores, weather and alerts, nudges and the kitchen',
    camera: 'Look at a photo or the live picture, on this device', // R7
  };
  function buildSheet() {
    const close = $('moreClose'), into = close ? close.parentNode : null;
    if (!into) return;
    tabs.slice(2).forEach((tab) => {
      const id = tab.dataset.open, icon = tab.querySelector('svg'), words = DESCRIBE[id];
      if (!words || !icon) return;
      const item = document.createElement('button');
      item.className = 'sheet-item'; item.type = 'button'; item.dataset.sheetOpen = id;
      const span = document.createElement('span'), name = document.createElement('b'), small = document.createElement('small');
      name.textContent = tab.getAttribute('aria-label') || (tab.querySelector('span') || tab).textContent.trim();
      small.textContent = words;
      span.append(name, small);
      item.append(icon.cloneNode(true), span);
      into.insertBefore(item, close);
    });
  }
  if (sheet) buildSheet();
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
  /** A tab's visible label, rounded up (Integrations shows its short one on a phone; under 360 px
   *  only icons show, and the names are visually hidden). */
  function labelWidth(tab) {
    const label = [...tab.querySelectorAll('span')].find((s) => shown(s) && getComputedStyle(s).position !== 'absolute');
    return label ? Math.ceil(label.getBoundingClientRect().width) : 0;
  }
  function borders(el) { const s = getComputedStyle(el); return px(s.borderLeftWidth) + px(s.borderRightWidth); }
  /** What every tab needs, read with all of them unfolded. The reads force one layout; the tabs are
   *  folded again (apply) before the frame is painted, so the unfolded dock is never seen. */
  function measure() {
    tabs.forEach((t) => { if (t.hidden) t.hidden = false; });
    if (sep && sep.hidden) sep.hidden = false;
    if (moreBtn.hidden) moreBtn.hidden = false;
    const s = getComputedStyle(dock), phone = isPhone();
    const width = (el) => el.getBoundingClientRect().width;
    // phone tabs share the bar: each needs its label, its borders and LABEL_CLEAR of air, and 44 px.
    // Desktop tabs keep their own widths, and a tab holds its label only if it is not wider.
    const need = (el) => (phone ? Math.max(MIN_TOUCH, labelWidth(el) + borders(el) + LABEL_CLEAR) : width(el));
    const holds = (el) => phone || labelWidth(el) + borders(el) <= width(el) + EPS;
    let sepW = 0;
    if (sep && shown(sep)) { const ss = getComputedStyle(sep); sepW = width(sep) + px(ss.marginLeft) + px(ss.marginRight); }
    return { phone, room: room(s), gap: px(s.columnGap), tabs: tabs.map(need), holds: tabs.map(holds), more: need(moreBtn), sepW };
  }
  /** Do these tabs (indexes, in dock order) fit the room, beside More when some are left out? */
  function fits(m, show) {
    const folded = show.length < m.tabs.length, items = show.length + (folded ? 1 : 0);
    const needs = show.map((i) => m.tabs[i]);
    if (m.phone) {
      if (items > PHONE_MAX) return false;
      const widest = Math.max(...needs, folded ? m.more : 0);
      return (m.room - m.gap * (items - 1)) / items >= widest - EPS;
    }
    const withSep = m.sepW > 0 && afterSep >= 0 && show.some((i) => i >= afterSep);
    const sum = needs.reduce((a, b) => a + b, 0) + (folded ? m.more : 0) + (withSep ? m.sepW : 0);
    return sum + m.gap * (items + (withSep ? 1 : 0) - 1) <= m.room + EPS;
  }
  /** Which tabs show: those that hold their label, in order, all when they fit, else the most that
   *  fit beside More, never fewer than the pinned ones (they fit a 320 px phone with room to spare). */
  function choose(m) {
    const able = m.tabs.map((_, i) => i).filter((i) => m.holds[i]);
    const pinned = able.filter((i) => i < PINNED).length;
    for (let k = able.length; k > pinned; k--) if (fits(m, able.slice(0, k))) return able.slice(0, k);
    return able.slice(0, pinned);
  }
  /** Fold every tab not in `show`; show More and the matching sheet entries only when needed. */
  function apply(show) {
    const focused = document.activeElement; // read first: hiding the focused tab blurs it at once
    const on = new Set(show);
    tabs.forEach((t, i) => { const fold = !on.has(i); if (t.hidden !== fold) t.hidden = fold; });
    const sepOff = afterSep >= 0 && !show.some((i) => i >= afterSep);
    if (sep && sep.hidden !== sepOff) sep.hidden = sepOff;
    const none = show.length >= tabs.length;
    if (moreBtn.hidden !== none) moreBtn.hidden = none;
    entries.forEach((b, id) => { const t = tabFor(id), off = !t || !t.hidden; if (b.hidden !== off) b.hidden = off; });
    if (none) closeSheet();
    carryBadge();
    rescueFocus(focused);
    syncMore();
  }
  /** The approvals badge sits on its tab, or on More while that tab is folded (console-deck.js
   *  keeps its count by id wherever it is; the .dk .badge look is the same on both). */
  function carryBadge() {
    const badge = $('dockBadge'), tab = tabFor(BADGED);
    if (!badge || !tab) return;
    const home = tab.hidden ? moreBtn : tab;
    if (badge.parentElement !== home) home.appendChild(badge);
  }
  function unfoldAll() { // the fallback: every tab reachable, even if the dock is crowded
    tabs.forEach((t) => { t.hidden = false; });
    if (sep) sep.hidden = false;
    moreBtn.hidden = true;
    closeSheet();
    carryBadge();
  }
  let raf = 0, lastWidth = -1;
  function fit() {
    lastWidth = root.clientWidth;
    fitHint();
    try { apply(choose(measure())); } catch (err) { unfoldAll(); throw err; } // reported, never silent
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
  /** More is lit while a folded panel is open; its accessible name says which, and carries the
   *  waiting count while the Approvals tab is folded ("Approvals, 3 waiting" -> "Approvals 3 waiting"). */
  function syncMore() {
    const open = tabs.filter((t) => t.hidden && pressed(t)).map((t) => titleOf(t.dataset.open));
    moreBtn.classList.toggle('on', open.length > 0);
    const parts = ['More panels'], badged = tabFor(BADGED);
    const count = badged && badged.hidden ? (badged.getAttribute('aria-label') || '').split(', ') : [];
    if (count.length > 1) parts.push(count.join(' '));
    if (open.length) parts.push(`${open.join(', ')} shown`);
    const label = parts.join(', ');
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

  // ============================================================================== the chat box's hint
  // On a narrow phone "Message JARVIS" is wider than the chat box (beside its attach, mic and send
  // buttons) and wrapped onto a cut second line: there the hint says "Message" (console.css keeps a
  // hint on one line; the box's label stays "Message JARVIS"). Same font and size; re-read when the
  // box changes width (a mic button appears) and with every refit (window width, fonts, theme).
  const input = $('input');
  const HINT = input ? input.getAttribute('placeholder') || '' : '', SHORT_HINT = 'Message';
  let pen = null;
  function textWidth(el, text) {
    pen = pen || document.createElement('canvas').getContext('2d');
    if (!pen) return 0;
    const s = getComputedStyle(el);
    pen.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    return pen.measureText(text).width + px(s.letterSpacing) * text.length;
  }
  function fitHint() {
    if (!input || !HINT || !input.getClientRects().length) return; // a closed chat panel: later
    // R11.1 I1: an attached file's own hint ("Ask about the attached file") is console-attach.js's
    if (input.placeholder !== HINT && input.placeholder !== SHORT_HINT) return;
    const s = getComputedStyle(input);
    const roomFor = input.clientWidth - px(s.paddingLeft) - px(s.paddingRight);
    const want = textWidth(input, HINT) <= roomFor ? HINT : SHORT_HINT;
    if (input.placeholder !== want) input.placeholder = want;
  }

  // ============================================================================== triggers + boot
  // console-deck.js marks open panels with aria-pressed and names the waiting count on the Approvals
  // tab (aria-label): More follows both (its own name changes are skipped, so this cannot loop)
  new MutationObserver((records) => { if (records.some((r) => r.target !== moreBtn)) syncMore(); })
    .observe(dock, { subtree: true, attributes: true, attributeFilter: ['aria-pressed', 'aria-label'] });
  if (window.ResizeObserver) { // the window's width (a height change alone never refits)
    new ResizeObserver(() => { if (root.clientWidth !== lastWidth) schedule(); }).observe(root);
    if (input) new ResizeObserver(fitHint).observe(input); // its hint never changes its width
  } else {
    window.addEventListener('resize', schedule);
  }
  if (phoneQ.addEventListener) phoneQ.addEventListener('change', () => { closeSheet(); schedule(); });
  if (document.fonts) { // a late web font changes the labels' widths
    if (document.fonts.ready) document.fonts.ready.then(schedule);
    if (document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', schedule);
  }
  document.addEventListener('jarvis:theme', schedule); // surface and theme (console-fx.js)
  // R11.1 I1: console-attach.js writes the full hint back whenever it redraws (its limits from the
  // server, a file removed): fit it again then, as the box may be narrower (the folder button)
  document.addEventListener('jarvis:attach', fitHint);
  fit();
})();
