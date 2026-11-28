// src/jarvis/api/static/console-dock-edit.js -- R8 I (docs/plans/r8-vision.md v8.0.4 D13, part I "your bar, your way";
// the owner, 28 Nov 2026: "make every icon editable ... drag and drop each item and place it as per my requirement.
// Also, the items I remove should be in the More. I should also have the option to hide the bar as well.").
// The bar's editor, on the layout model (console-dock-layout.js, I0, pure). It alone reads and writes this device's
// localStorage['jarvis_dock_layout_v1']; console-dock.js draws what it is given (window.JarvisDock.arrange).
//   Ways in (never a new always-visible button): a right-click on the bar ("Edit the bar"), a long-press on touch,
//   Ctrl + Shift + . and the Appearance menu's "The bar" line. On a laptop the bar is edited in place: drag an item
//   (8 px makes a drag; Esc puts it back), or click it for Move left / Move right / Move to More; its x (or Delete)
//   takes it off the bar into More; Shift + arrows move it. Toolbar: Hide the bar, Reset to default (with Undo), Done.
//   On a phone (< 900 px) the bar is edited as a list in a sheet (top = left). More keeps today's behaviour: it
//   shows only when tabs overflow or he took one off; its sheet then lists them with Put back. A hidden bar leaves a
//   slim handle; Ctrl + . shows it again. Chat can't leave the bar; Reset to default puts the shipped bar back.
// With no saved layout this module draws nothing and writes nothing: the 1920 px bar stays byte-identical until he
// edits it (R18's rule, tests/browser/test_r8_dock_edit.py). Nothing here asks the server anything; cost Rs 0.
// textContent only; SVG built with createElementNS; CSP script-src 'self'. The pure part below is exported for the
// Node tests (tests/test_r8_i_dock.py); the page part starts only in a browser with console-dock.js's JarvisDock.
import { KEY, VERSION, FIXED, parse, apply, isDefault, move, toMore, fromMore, hide, serialize } from './console-dock-layout.js';

const STYLE = '/static/console-dock-edit.css'; // linked the first time it is needed (a saved layout, or editing)
export { KEY, STYLE, VERSION };
export const LONG_PRESS_MS = 500; // touch: a press this long opens the editor
export const DRAG_PX = 8; // a drag starts after this much movement; less is a click
export const SHOW_KEYS = 'Ctrl + .'; // shows a hidden bar (the console's mic keys are Ctrl + Space)
export const EDIT_KEYS = 'Ctrl + Shift + .'; // opens (and ends) editing
const X = '\u2715', LEFT = '\u2190', RIGHT = '\u2192';
export const WORDS = Object.freeze({
  title: 'Editing the bar',
  base: `Drag an item to move it, or click it for its Move buttons. Its ${X} takes it off the bar: it waits in More.`,
  list: `Hold the dots and drag to move an item, or tap them for Move up and Move down. ${X} takes it off the bar. The top of the list is the left of the bar.`,
  chat: "Chat stays on the bar: it's how you talk to JARVIS.",
  reset: 'Back to the shipped bar.',
  undone: 'Undone.',
  unsaved: 'This browser would not keep it, so the shipped bar comes back next time.',
  show: 'Show the bar',
  showHow: `Click here, or press [Ctrl] + [.]`,
});

// ---- pure: the editor's rules on the layout model ---------------------------------------------------------------------
/** 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th ... 21st, 22nd, 23rd. */
export function ordinal(n) {
  const k = Math.trunc(Number(n)) || 0, t = k % 100, u = k % 10;
  return k + (t >= 11 && t <= 13 ? 'th' : u === 1 ? 'st' : u === 2 ? 'nd' : u === 3 ? 'rd' : 'th');
}
/** "A", "A and B", "A, B and C". */
export function listWords(names) {
  const n = names.filter(Boolean);
  return n.length < 2 ? n.join('') : `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`;
}
/** The layout to draw from the saved text (null: nothing saved; unreadable: the shipped bar). */
export function layoutFrom(text, defaults) {
  return apply(defaults, text === null || text === undefined ? null : parse(text));
}
/** The text to keep for this layout, or null: the shipped bar is never written (its key is removed). */
export function toStore(defaults, layout) {
  return isDefault(defaults, layout) ? null : serialize(layout);
}
/** Put a tab back from More where the shipped bar had it: before the first later shipped tab on the bar. */
export function putBack(layout, id, shipped) {
  if (!layout.more.includes(id)) return layout;
  const later = shipped.slice(shipped.indexOf(id) + 1).find((x) => layout.order.includes(x));
  return fromMore(layout, id, later === undefined ? layout.order.length : layout.order.indexOf(later));
}
/** Drop `id` just before `before` (or just after `after` when it lands last); onto its own place: unchanged. */
export function dropTo(layout, id, before, after) {
  if (before === id || after === id || !layout.order.includes(id)) return layout;
  const rest = layout.order.filter((x) => x !== id);
  if (before && rest.includes(before)) return move(layout, id, rest.indexOf(before));
  if (after && rest.includes(after)) return move(layout, id, rest.indexOf(after) + 1);
  return layout;
}
/** One place left (-1) or right (+1); at either end: unchanged. */
export function step(layout, id, delta) {
  const i = layout.order.indexOf(id), to = i + delta;
  return i < 0 || to < 0 || to >= layout.order.length ? layout : move(layout, id, to);
}
/** The slot a pointer at `at` falls in among items whose centres are `centres` (in order). */
export function slot(centres, at) {
  let i = 0;
  while (i < centres.length && centres[i] < at) i += 1;
  return i;
}
/** 'show' (Ctrl + .), 'edit' (Ctrl + Shift + .) or null, from a keydown's keys. */
export function shortcut(e) {
  if (!e || !e.ctrlKey || e.altKey || e.metaKey || e.repeat || e.code !== 'Period') return null;
  return e.shiftKey ? 'edit' : 'show';
}
const nameIn = (names, id) => (names && names[id]) || id;
/** Where `id` sits in `order`: ['3rd', 'between Brief and Approvals'], ['first', 'before Chat'], ['last', 'after Camera']. */
export function whereWords(order, id, names) {
  const i = order.indexOf(id), prev = order[i - 1], next = order[i + 1];
  if (i < 0 || (!prev && !next)) return ['alone', 'with nothing beside it'];
  if (!prev) return ['first', `before ${nameIn(names, next)}`];
  if (!next) return ['last', `after ${nameIn(names, prev)}`];
  return [ordinal(i + 1), `between ${nameIn(names, prev)} and ${nameIn(names, next)}`];
}
export function placeWords(order, id, names) {
  const [at, near] = whereWords(order, id, names);
  return `${nameIn(names, id)} is ${at} now, ${near}.`;
}
export function dropWords(order, id, names) {
  const [at, near] = whereWords(order, id, names);
  return `Let go to put ${nameIn(names, id)} ${at}, ${near}. Esc puts it back.`;
}
/** What a change did to the bar's room: tabs that came onto it, and tabs that went into More for room. */
export function roomWords(before, after, names, except) {
  const n = (ids) => listWords(ids.filter((x) => x !== except).map((x) => nameIn(names, x)));
  const came = after.filter((x) => !before.includes(x)), went = before.filter((x) => !after.includes(x));
  const one = (ids) => ids.filter((x) => x !== except).length === 1;
  const words = [];
  if (n(came)) words.push(`${n(came)} ${one(came) ? 'has' : 'have'} room on the bar again.`);
  if (n(went)) words.push(`${n(went)} ${one(went) ? 'waits' : 'wait'} in More: no room for ${one(went) ? 'it' : 'them'} now.`);
  return words.join(' ');
}
/** Tabs on his bar that this width has no room for (named up to three, else counted). */
export function noRoomWords(folded, names, more) {
  if (!folded.length) return '';
  const one = folded.length === 1, who = folded.length > 3 ? `${folded.length} items` : listWords(folded.map((x) => nameIn(names, x)));
  return more ? `${who} ${one ? 'waits' : 'wait'} in More: no room for ${one ? 'it' : 'them'} at this width.`
    : `${who} ${one ? 'has' : 'have'} no room at this width.`;
}

// ---- the page -----------------------------------------------------------------------------------------------------
const SVG = 'http://www.w3.org/2000/svg';
const PATHS = {
  pen: ['M11.5 4.5h-6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-6', 'm9 11 .4-2.1 6-6a1.2 1.2 0 0 1 1.7 1.7l-6 6z'],
  x: ['m5.5 5.5 9 9M14.5 5.5l-9 9'], left: ['m12 4.5-5.5 5.5 5.5 5.5'], right: ['m8 4.5 5.5 5.5L8 15.5'],
  up: ['m4.5 12 5.5-5.5 5.5 5.5'], down: ['m4.5 8 5.5 5.5L15.5 8'],
  into: ['M10 3.5v9M6 9l4 4 4-4', 'M3.5 13.5v3h13v-3'], back: ['M10 16.5v-9M6 11l4-4 4 4', 'M3.5 6.5v-3h13v3'],
};
function icon(name, width) {
  const s = document.createElementNS(SVG, 'svg');
  const at = { viewBox: '0 0 20 20', fill: 'none', stroke: 'currentColor', 'stroke-width': String(width || 1.7),
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' };
  Object.keys(at).forEach((k) => s.setAttribute(k, at[k]));
  PATHS[name].forEach((d) => { const p = document.createElementNS(SVG, 'path'); p.setAttribute('d', d); s.append(p); });
  return s;
}
function dots(w, h, r) { // the grip: six dots
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', `0 0 ${w} ${h}`); s.setAttribute('aria-hidden', 'true'); s.setAttribute('fill', 'currentColor');
  [[w / 4, h / 6], [3 * w / 4, h / 6], [w / 4, h / 2], [3 * w / 4, h / 2], [w / 4, 5 * h / 6], [3 * w / 4, 5 * h / 6]].forEach(([x, y]) => {
    const c = document.createElementNS(SVG, 'circle');
    c.setAttribute('cx', String(x)); c.setAttribute('cy', String(y)); c.setAttribute('r', String(r)); s.append(c);
  });
  return s;
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function button(cls, text, act, ico, label) {
  const b = el('button', cls); b.type = 'button'; b.dataset.act = act;
  if (ico) b.append(ico);
  b.append(document.createTextNode(text));
  if (label) b.setAttribute('aria-label', label);
  return b;
}
/** Text with [Key] tokens drawn as keys. */
function rich(text) {
  return String(text).split(/\[([^\]]+)\]/).map((part, i) => (i % 2 ? el('kbd', 'dke-k', part) : document.createTextNode(part)));
}
const stop = (e) => { e.preventDefault(); e.stopPropagation(); };

function boot(D) {
  const $ = (id) => document.getElementById(id);
  const dock = $('dock'), moreBtn = $('dockMore'), sheet = $('moreSheet'), root = document.documentElement;
  if (!dock || !moreBtn) return;
  const shipped = D.shipped();
  const store = {
    get() { try { return localStorage.getItem(KEY); } catch (_) { return null; } },
    put(text) {
      try { if (text === null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, text); return true; } catch (_) { return false; }
    },
  };
  const S = { layout: layoutFrom(null, shipped), editing: false, phone: false, drag: null, press: null,
    ldrag: null, held: false, swallow: false, dragged: false, keys: null, undo: null, base: false, sel: null };
  const tabsAll = () => [...dock.querySelectorAll('.dk[data-open]')];
  const tabEl = (id) => tabsAll().find((t) => t.dataset.open === id) || null;
  const shownTabs = () => tabsAll().filter((t) => !t.hidden);
  const nameOf = (id) => { const t = tabEl(id); return t ? (t.querySelector('span') || t).textContent.trim() : id; };
  const names = () => Object.fromEntries(shipped.map((id) => [id, nameOf(id)]));
  let cssLoad = null;
  const css = () => cssLoad || (cssLoad = new Promise((done) => {
    const link = el('link'); link.rel = 'stylesheet'; link.href = STYLE;
    link.addEventListener('load', () => done()); link.addEventListener('error', () => done());
    document.head.append(link);
  }));

  // ---- drawing and keeping the layout -------------------------------------------------------------------------------
  const handle = button('dke-handle', '', 'show', null, WORDS.show);
  handle.append(el('i'));
  const handleTip = el('div', 'dke-tip dke-htip');
  handleTip.id = 'dkeHandleTip'; handleTip.setAttribute('role', 'tooltip'); handleTip.hidden = true;
  handleTip.append(el('b', '', WORDS.show), el('small'));
  handleTip.lastChild.append(...rich(WORDS.showHow));
  handle.setAttribute('aria-describedby', handleTip.id);
  function draw(layout) {
    const was = root.classList.contains('dke-hidden');
    D.arrange(layout);
    root.classList.toggle('dke-hidden', layout.hidden);
    if (layout.hidden) {
      css().then(() => {
        if (!S.layout.hidden || handle.isConnected) return;
        const inDock = dock.contains(document.activeElement);
        document.body.append(handle, handleTip);
        if (inDock || document.activeElement === document.body) handle.focus({ preventScroll: true });
      });
    } else { handle.remove(); handleTip.remove(); }
    if (was !== layout.hidden) window.dispatchEvent(new Event('resize')); // the deck takes the room back
  }
  function refocus(id) {
    if (id === undefined || id === null) return;
    const t = tabEl(id);
    const target = t && !t.hidden ? t : shownTabs().pop();
    if (target && !S.phone) target.focus({ preventScroll: true });
  }
  /** Draw and keep a new layout; say what changed (and what it did to the bar's room). */
  function commit(next, opts = {}) {
    if (serialize(next) === serialize(S.layout)) { if (opts.same) say(opts.same); return false; }
    const before = D.state().shown;
    S.undo = opts.undo ? S.layout : null;
    S.layout = next;
    draw(next);
    const kept = store.put(toStore(shipped, next));
    if (S.phone) drawList(opts.focus, opts.part); else refocus(opts.focus);
    const room = roomWords(before, D.state().shown, names(), opts.except);
    say([opts.words, room, kept ? '' : WORDS.unsaved].filter(Boolean).join(' '), !!S.undo);
    placeKeys();
    return true;
  }

  // ---- the toolbar (laptop) and the status line -----------------------------------------------------------------------
  const tools = el('div', 'card dke-tools');
  tools.setAttribute('role', 'region'); tools.setAttribute('aria-labelledby', 'dkeT');
  const toolsTitle = el('h2'); toolsTitle.id = 'dkeT'; toolsTitle.append(icon('pen', 1.6), document.createTextNode(WORDS.title));
  const toolsSay = el('p'); toolsSay.id = 'dkeSay'; toolsSay.setAttribute('role', 'status');
  const toolsActs = el('div', 'actions');
  toolsActs.append(button('btn lift', 'Hide the bar', 'hide'), button('btn lift', 'Reset to default', 'reset'), button('btn primary lift', 'Done', 'done'));
  tools.append(toolsTitle, toolsSay, toolsActs);
  tools.addEventListener('click', (e) => { const b = e.target.closest('button[data-act]'); if (b) act(b.dataset.act, null); });
  function say(text, undo) {
    const p = S.phone ? listSay : toolsSay;
    if (!S.editing || !p) return;
    const had = p.contains(document.activeElement); // Undo pressed: focus goes to Done, never to the page
    S.base = false;
    p.replaceChildren(...rich(text));
    if (undo) { p.append(' '); p.append(button('btn lift dke-undo', 'Undo', 'undo')); }
    const done = (S.phone ? list : tools).querySelector('[data-act="done"]');
    if (had && done) done.focus({ preventScroll: true });
  }
  function sayBase() {
    const st = D.state(), folded = st.order.filter((id) => !st.shown.includes(id) && !st.removed.includes(id));
    say(S.phone ? WORDS.list : [WORDS.base, noRoomWords(folded, names(), st.more)].filter(Boolean).join(' ')); // a phone's list draws the fold
    S.base = true;
  }
  function sayItem(id) {
    const order = S.layout.order;
    say(`${nameOf(id)}, ${ordinal(order.indexOf(id) + 1)} of ${order.length}. [Shift] + [${LEFT}] or [${RIGHT}] moves it, [Delete] puts it in More, [Esc] ends editing.`);
  }

  // ---- the actions ---------------------------------------------------------------------------------------------------
  function moveBy(id, delta, part) {
    const next = step(S.layout, id, delta);
    if (next === S.layout) return say(`${nameOf(id)} is already ${delta < 0 ? 'first' : 'last'}.`);
    return commit(next, { words: placeWords(next.order, id, names()), focus: id, part });
  }
  function remove(id) {
    if (FIXED.includes(id)) return say(WORDS.chat);
    const i = S.layout.order.indexOf(id), next = toMore(S.layout, id);
    return commit(next, { words: `${nameOf(id)} is off the bar: it waits in More, with Put back.`, except: id, undo: true,
      focus: next.order[Math.min(i, next.order.length - 1)], part: 'hold' });
  }
  function back(id, focus) {
    return commit(putBack(S.layout, id, shipped), { words: `${nameOf(id)} is back on the bar.`, except: id, focus: focus ? id : null, part: 'hold' });
  }
  function act(what, id) {
    const focusNow = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.open : null;
    if (what === 'done') return exit(true);
    if (what === 'hide') { exit(false); return commit(hide(S.layout, true)); }
    if (what === 'reset') return commit(apply(shipped, null), { words: WORDS.reset, undo: true, focus: focusNow, same: WORDS.reset });
    if (what === 'undo' && S.undo) return commit(S.undo, { words: WORDS.undone, focus: focusNow });
    if (what === 'show') return showBar();
    if (!id) return false;
    if (what === 'left' || what === 'up') return moveBy(id, -1, what);
    if (what === 'right' || what === 'down') return moveBy(id, 1, what);
    if (what === 'more' || what === 'del') return remove(id);
    if (what === 'put') return back(id, S.phone);
    return false;
  }
  function showBar() {
    commit(hide(S.layout, false));
    const first = shownTabs()[0];
    if (first) first.focus({ preventScroll: true });
  }
  handle.addEventListener('click', showBar);
  const tipOn = () => {
    const r = handle.getBoundingClientRect();
    handleTip.hidden = false;
    handleTip.style.left = Math.max(8, Math.round(r.left + r.width / 2 - handleTip.offsetWidth / 2)) + 'px';
    handleTip.style.bottom = Math.round(window.innerHeight - r.top + 8) + 'px';
  };
  const tipOff = () => { handleTip.hidden = true; };
  handle.addEventListener('pointerenter', tipOn); handle.addEventListener('focus', tipOn);
  handle.addEventListener('pointerleave', tipOff); handle.addEventListener('blur', tipOff);

  // ---- editing on the laptop: in place --------------------------------------------------------------------------------
  function decorate(t) {
    if (t.querySelector('.dke-grip')) return;
    const grip = el('i', 'dke-grip'), x = el('i', 'dke-x' + (FIXED.includes(t.dataset.open) ? ' dke-fixed' : ''));
    grip.setAttribute('aria-hidden', 'true'); x.setAttribute('aria-hidden', 'true');
    grip.append(dots(8, 12, 1.1)); x.append(icon('x', 2));
    t.append(grip, x);
    t.setAttribute('aria-describedby', 'dkeSay');
  }
  async function enter(focusId) {
    if (S.editing) return;
    await css();
    closeCtx();
    if (sheet && sheet.open) sheet.close(); // the bar is behind a modal sheet: edit it in the open
    if (S.layout.hidden) commit(hide(S.layout, false));
    S.editing = true;
    if (D.state().phone) { openList(focusId); return; }
    dock.classList.add('dke-edit');
    tabsAll().forEach(decorate);
    document.body.append(tools);
    const t = tabEl(focusId);
    const target = t && !t.hidden ? t : shownTabs()[0];
    if (target) target.focus({ preventScroll: true });
    sayBase(); // after the focus: the opening line, not the item's
  }
  function exit(keepFocus) {
    if (!S.editing) return;
    cancelDrag(); closeKeys(); chatTip(false);
    S.editing = false;
    if (S.phone) { S.phone = false; S.sel = null; if (list && list.open) list.close(); return; }
    dock.classList.remove('dke-edit');
    dock.querySelectorAll('.dke-grip, .dke-x').forEach((n) => n.remove());
    tabsAll().forEach((t) => t.removeAttribute('aria-describedby'));
    tools.remove();
    if (keepFocus && !dock.contains(document.activeElement)) { const f = shownTabs()[0]; if (f) f.focus({ preventScroll: true }); }
  }
  // the dimmed x on Chat says why on hover (touch has the list's line instead)
  const chatTipEl = el('div', 'dke-tip dke-line');
  chatTipEl.setAttribute('role', 'tooltip');
  function chatTip(on, x) {
    if (!on) { chatTipEl.remove(); return; }
    chatTipEl.textContent = WORDS.chat;
    document.body.append(chatTipEl);
    const r = x.getBoundingClientRect();
    chatTipEl.style.left = Math.max(8, Math.round(r.left - 20)) + 'px';
    chatTipEl.style.bottom = Math.round(window.innerHeight - r.top + 10) + 'px';
  }
  dock.addEventListener('pointerover', (e) => {
    const x = e.target.closest && e.target.closest('.dke-x.dke-fixed');
    if (S.editing && !S.drag) chatTip(!!x, x);
  });
  dock.addEventListener('pointerleave', () => chatTip(false));

  // the Move panel above an item (a click on it, or Enter): Move left, Move right, Move to More
  function openKeys(t) {
    closeKeys();
    const id = t.dataset.open, box = el('div', 'dke-keys'), h = el('h3', '', 'Move ');
    box.setAttribute('role', 'group'); box.setAttribute('aria-label', `Move ${nameOf(id)}`);
    h.append(el('b', '', nameOf(id)));
    const ul = el('ul'), row = (b, keys) => { const li = el('li'), k = el('span'); k.append(...rich(keys)); li.append(b, k); ul.append(li); };
    row(button('btn lift', 'Move left', 'left', icon('left', 1.8)), `[Shift] + [${LEFT}]`);
    const right = button('btn lift', 'Move right', 'right'); right.append(icon('right', 1.8));
    row(right, `[Shift] + [${RIGHT}]`);
    const more = button('btn lift', 'Move to More', 'more', icon('into'));
    if (FIXED.includes(id)) { more.setAttribute('aria-disabled', 'true'); more.title = WORDS.chat; }
    row(more, '[Delete]');
    box.append(h, ul);
    box.addEventListener('click', (e) => { const b = e.target.closest('button[data-act]'); if (b && S.keys) act(b.dataset.act, S.keys.id); });
    document.body.append(box);
    S.keys = { id, box };
    placeKeys();
  }
  function placeKeys() {
    if (!S.keys) return;
    const t = tabEl(S.keys.id);
    if (!S.editing || S.phone || !t || t.hidden) { closeKeys(); return; }
    const r = t.getBoundingClientRect(), w = S.keys.box.offsetWidth, mid = r.left + r.width / 2;
    const left = Math.max(8, Math.min(window.innerWidth - w - 8, Math.round(mid - w / 2)));
    S.keys.box.style.left = left + 'px';
    S.keys.box.style.bottom = Math.round(window.innerHeight - r.top + 12) + 'px';
    S.keys.box.style.setProperty('--ax', Math.round(mid - left) + 'px');
  }
  function closeKeys() { if (S.keys) { S.keys.box.remove(); S.keys = null; } }

  // drag and drop on the bar: the item lifts, a line shows where it lands, More lights as the place to take it off
  function dragBegin(d) {
    const r = d.tab.getBoundingClientRect();
    d.started = true; d.dx = d.x0 - r.left; d.dy = d.y0 - r.top;
    closeKeys(); chatTip(false);
    const ghost = d.tab.cloneNode(true);
    ['data-open', 'aria-controls', 'aria-pressed', 'aria-label', 'aria-describedby'].forEach((a) => ghost.removeAttribute(a));
    ghost.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
    ghost.classList.add('dke-ghost'); ghost.setAttribute('aria-hidden', 'true'); ghost.tabIndex = -1;
    ghost.style.width = r.width + 'px'; ghost.style.height = r.height + 'px';
    d.ghost = ghost; d.line = el('i', 'dke-drop');
    document.body.append(ghost); dock.append(d.line);
    d.tab.classList.add('dke-hole');
  }
  function dragMove(e) {
    const d = S.drag;
    if (!d.started) { if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < DRAG_PX) return; dragBegin(d); }
    d.ghost.style.left = Math.round(e.clientX - d.dx) + 'px';
    d.ghost.style.top = Math.round(e.clientY - d.dy) + 'px';
    const m = moreBtn.getBoundingClientRect(), slack = 6;
    const onMore = !moreBtn.hidden && e.clientX >= m.left - slack && e.clientX <= m.right + slack && e.clientY >= m.top - 24 && e.clientY <= m.bottom + slack;
    moreBtn.classList.toggle('dke-target', onMore && !FIXED.includes(d.id));
    if (onMore) {
      d.to = FIXED.includes(d.id) ? null : 'more'; d.line.hidden = true;
      say(d.to ? `Let go to take ${nameOf(d.id)} off the bar into More. Esc puts it back.` : WORDS.chat);
      return;
    }
    const items = shownTabs(), rects = items.map((t) => t.getBoundingClientRect());
    const i = slot(rects.map((r) => r.left + r.width / 2), e.clientX), dr = dock.getBoundingClientRect();
    const before = items[i] ? items[i].dataset.open : null, after = items[i - 1] ? items[i - 1].dataset.open : null;
    const x = rects[i] ? rects[i].left - 2 : rects[i - 1].right + 2;
    d.line.hidden = false; d.line.style.left = Math.round(x - dr.left) + 'px';
    const next = dropTo(S.layout, d.id, before, after);
    d.to = next === S.layout ? null : { before, after };
    say(d.to ? dropWords(next.order, d.id, names()) : `Let go to leave ${nameOf(d.id)} where it is.`);
  }
  function dragEnd() {
    const d = S.drag;
    S.drag = null;
    if (!d || !d.started) return;
    swallowNextClick();
    cleanDrag(d);
    if (d.to === 'more') remove(d.id);
    else if (d.to) {
      const next = dropTo(S.layout, d.id, d.to.before, d.to.after);
      commit(next, { words: placeWords(next.order, d.id, names()), focus: d.id });
    } else sayBase();
  }
  /** The click that ends a drag (same task as its pointerup) is not a press; any later one is. */
  function swallowNextClick() { S.dragged = true; setTimeout(() => { S.dragged = false; }, 0); }
  function cleanDrag(d) {
    if (d.ghost) d.ghost.remove();
    if (d.line) d.line.remove();
    if (d.tab) d.tab.classList.remove('dke-hole');
    moreBtn.classList.remove('dke-target');
  }
  function cancelDrag() {
    const d = S.drag;
    S.drag = null;
    if (d && d.started) { cleanDrag(d); sayBase(); }
    if (S.ldrag) listDragCancel();
  }

  // ---- the ways in: right-click, long-press, the shortcuts, the settings line ----------------------------------------
  let ctx = null;
  function openCtx(x, y, t) {
    css().then(() => {
      closeCtx();
      ctx = el('div', 'dke-ctx'); ctx.setAttribute('role', 'menu'); ctx.setAttribute('aria-label', 'The bar');
      const edit = button('', 'Edit the bar', 'edit', icon('pen', 1.6)), hideIt = button('', 'Hide the bar', 'hide');
      const keys = el('span', 'dke-keys-hint'); keys.append(...rich('[Ctrl] + [Shift] + [.]'));
      edit.append(keys);
      [edit, hideIt].forEach((b) => { b.setAttribute('role', 'menuitem'); ctx.append(b); });
      ctx.addEventListener('click', (e) => {
        const b = e.target.closest('button[data-act]'); if (!b) return;
        const id = t ? t.dataset.open : null, what = b.dataset.act;
        closeCtx(false);
        if (what === 'edit') enter(id); else commit(hide(S.layout, true));
      });
      ctx.addEventListener('keydown', (e) => {
        const items = [...ctx.querySelectorAll('button')], i = items.indexOf(document.activeElement);
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { stop(e); items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus(); }
        if (e.key === 'Escape' || e.key === 'Tab') { stop(e); closeCtx(true); }
      });
      document.body.append(ctx);
      const w = ctx.offsetWidth, h = ctx.offsetHeight;
      ctx.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, Math.round(x))) + 'px';
      ctx.style.top = Math.max(8, Math.round(y - h - 6)) + 'px';
      ctx.dataset.from = t ? t.dataset.open : '';
      edit.focus({ preventScroll: true });
    });
  }
  function closeCtx(refocusTab) {
    if (!ctx) return;
    const from = ctx.dataset.from;
    ctx.remove(); ctx = null;
    if (refocusTab) { const t = tabEl(from); (t && !t.hidden ? t : moreBtn).focus({ preventScroll: true }); }
  }
  document.addEventListener('pointerdown', (e) => { if (ctx && !ctx.contains(e.target)) closeCtx(false); }, true);
  dock.addEventListener('contextmenu', (e) => {
    e.preventDefault(); // the bar's own menu; on touch the long-press below opens the editor
    if (S.press || S.swallow || S.editing || (e.pointerType && e.pointerType !== 'mouse')) return;
    const t = e.target.closest('.dk[data-open]');
    let { clientX: x, clientY: y } = e;
    if (!x && !y) { const r = (t || moreBtn).getBoundingClientRect(); x = r.left; y = r.top; } // the menu key
    openCtx(x, y, t);
  });
  function clearPress() { if (S.press) { clearTimeout(S.press.timer); S.press = null; } }
  dock.addEventListener('pointerdown', (e) => {
    S.swallow = false; S.dragged = false;
    const t = e.target.closest('.dk[data-open]');
    if (S.editing && !S.phone) {
      if (t && e.button === 0 && !e.target.closest('.dke-x')) S.drag = { id: t.dataset.open, tab: t, x0: e.clientX, y0: e.clientY, started: false };
      return;
    }
    if (e.pointerType === 'mouse' || !e.isPrimary || S.editing) return;
    const id = t ? t.dataset.open : null;
    S.press = { x: e.clientX, y: e.clientY, timer: setTimeout(() => { S.press = null; S.swallow = true; holdUntilLift(); enter(id); }, LONG_PRESS_MS) };
  });
  /** A long-press opens the editor under his finger: until it lifts (and a moment after) nothing in the list
   *  takes a press, so the lift can't press a row's x or move focus. */
  function holdUntilLift() {
    const kinds = ['pointerup', 'pointercancel', 'touchend', 'touchcancel'];
    const free = () => {
      kinds.forEach((k) => window.removeEventListener(k, free, true));
      setTimeout(() => { S.held = false; S.swallow = false; }, 350);
    };
    S.held = true;
    kinds.forEach((k) => window.addEventListener(k, free, true));
    setTimeout(() => { S.held = false; }, 3000);
  }
  window.addEventListener('pointermove', (e) => {
    if (S.press && Math.hypot(e.clientX - S.press.x, e.clientY - S.press.y) > DRAG_PX) clearPress();
    if (S.drag) dragMove(e);
    if (S.ldrag) listDragMove(e);
  });
  window.addEventListener('pointerup', () => { clearPress(); if (S.drag) dragEnd(); if (S.ldrag) listDragEnd(); });
  window.addEventListener('pointercancel', () => { clearPress(); cancelDrag(); });
  dock.addEventListener('click', (e) => { // capture: while editing, a press on an item never opens its panel
    if (S.swallow) { S.swallow = false; stop(e); return; }
    const t = e.target.closest('.dk[data-open]');
    if (!S.editing || S.phone || !t) return;
    stop(e);
    if (S.dragged) { S.dragged = false; return; }
    if (e.target.closest('.dke-x')) { remove(t.dataset.open); return; }
    if (S.keys && S.keys.id === t.dataset.open) closeKeys(); else openKeys(t);
  }, true);
  dock.addEventListener('focusin', (e) => { // the item's place and keys; another item's Move panel closes
    const t = e.target.closest('.dk[data-open]');
    if (!S.editing || S.phone || !t) return;
    if (S.keys && S.keys.id !== t.dataset.open) closeKeys();
    sayItem(t.dataset.open);
  });
  dock.addEventListener('keydown', (e) => {
    const t = e.target.closest('.dk[data-open]');
    if (!S.editing || S.phone || !t) return;
    const id = t.dataset.open;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      stop(e);
      const delta = e.key === 'ArrowLeft' ? -1 : 1;
      if (e.shiftKey) { moveBy(id, delta); return; }
      const shown = shownTabs(), next = shown[shown.indexOf(t) + delta];
      if (next) next.focus({ preventScroll: true });
    } else if (e.key === 'Delete' || e.key === 'Backspace') { stop(e); remove(id); }
  });
  document.addEventListener('keydown', (e) => {
    const k = shortcut(e);
    if (k === 'show' && S.layout.hidden) { e.preventDefault(); css().then(showBar); return; }
    if (k === 'edit') { e.preventDefault(); if (S.editing) exit(true); else enter(document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.open : null); return; }
    if (e.key !== 'Escape' || !S.editing || S.phone) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (S.drag && S.drag.started) cancelDrag();
    else if (S.keys) { const t = tabEl(S.keys.id); closeKeys(); if (t) t.focus({ preventScroll: true }); } else exit(true);
  }, true);
  const menu = $('themeMenu'); // the console's settings: the Appearance menu gains "The bar"
  if (menu && !$('jxBar')) {
    const set = el('fieldset'), go = button('btn lift row-btn', 'Edit the bar', 'edit'), fine = el('p', 'fine');
    go.id = 'jxBar';
    fine.textContent = `Move the bar's items, take them off into More or hide the bar, on this device. Or right-click the bar, long-press it on a phone, or press ${EDIT_KEYS}`;
    set.append(el('legend', '', 'The bar'), go, fine);
    menu.append(set);
    go.addEventListener('click', () => { const tb = $('themeBtn'); if (!menu.hidden && tb) tb.click(); enter(null); });
  }

  // ---- editing on a phone: a list in a sheet (top = the left of the bar) ----------------------------------------------
  let list = null, listOl = null, listOff = null, listSay = null;
  function listDialog() {
    if (list) return list;
    list = el('dialog', 'sheet dke-ed'); list.id = 'dockEdit'; list.setAttribute('aria-labelledby', 'dkeET');
    const inner = el('div', 'sheet-in'), head = el('div', 'dke-ehead'), h = el('h2', '', 'Edit the bar'), two = el('div', 'dke-two');
    h.id = 'dkeET';
    two.append(button('btn lift', 'Reset to default', 'reset'), button('btn lift', 'Hide the bar', 'hide'));
    listSay = el('p'); listSay.id = 'dkeEP'; listSay.setAttribute('role', 'status');
    head.append(h, button('btn primary lift', 'Done', 'done'), two, listSay);
    listOl = el('ol', 'dke-list'); listOl.setAttribute('aria-label', 'The bar, from the left');
    listOff = el('div', 'dke-offs');
    inner.append(head, listOl, listOff); list.append(inner);
    ['pointerdown', 'mousedown', 'click'].forEach((k) => list.addEventListener(k, (e) => { if (S.held) stop(e); }, true));
    list.addEventListener('click', (e) => {
      if (e.defaultPrevented) return;
      if (e.target === list) { list.close(); return; } // the backdrop
      const b = e.target.closest('button[data-act]'); if (!b) return;
      const row = b.closest('[data-id]'), id = row ? row.dataset.id : null;
      if (b.dataset.act === 'hold') { if (S.dragged) { S.dragged = false; return; } S.sel = S.sel === id ? null : id; drawList(id, 'hold'); return; }
      if (b.dataset.act === 'done') { list.close(); return; }
      if (b.getAttribute('aria-disabled') === 'true') { say(WORDS.chat); return; }
      act(b.dataset.act, id);
    });
    list.addEventListener('keydown', (e) => {
      const b = e.target.closest('.dke-hold'); if (!b) return;
      const id = b.closest('[data-id]').dataset.id, holds = [...listOl.querySelectorAll('.dke-hold')], i = holds.indexOf(b);
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        stop(e);
        const delta = e.key === 'ArrowUp' ? -1 : 1;
        if (e.shiftKey) moveBy(id, delta, 'hold'); else if (holds[i + delta]) holds[i + delta].focus();
      } else if (e.key === 'Delete' || e.key === 'Backspace') { stop(e); remove(id); }
    });
    list.addEventListener('pointerdown', (e) => {
      S.dragged = false;
      const b = e.target.closest('.dke-hold'); if (!b || e.button !== 0) return;
      const row = b.closest('.dke-row');
      S.ldrag = { id: row.dataset.id, row, y0: e.clientY, x0: e.clientX, started: false };
    });
    list.addEventListener('close', () => {
      if (S.editing && S.phone) { cancelDrag(); S.editing = false; S.phone = false; S.sel = null; }
      const f = shownTabs()[0]; if (f) f.focus({ preventScroll: true });
    });
    document.body.append(list);
    return list;
  }
  function openList(focusId) {
    S.phone = true;
    listDialog().showModal();
    sayBase();
    drawList(focusId || S.layout.order[0], 'hold');
  }
  function listRow(id, i, n) {
    const li = el('li', 'dke-row' + (S.sel === id ? ' dke-sel' : '')), t = tabEl(id), fixed = FIXED.includes(id);
    li.dataset.id = id;
    const hold = button('dke-hold', '', 'hold', dots(10, 16, 1.4), `Move ${nameOf(id)}, ${ordinal(i + 1)} of ${n}`);
    hold.setAttribute('aria-expanded', String(S.sel === id));
    const words = el('span'); words.append(el('b', '', nameOf(id)));
    if (fixed) words.append(el('small', '', 'Stays on the bar: it\'s how you talk to JARVIS'));
    const del = button('dke-del', '', 'del', icon('x', 2), fixed ? 'Chat stays on the bar' : `Take ${nameOf(id)} off the bar`);
    if (fixed) del.setAttribute('aria-disabled', 'true');
    li.append(hold, t && t.querySelector('svg') ? t.querySelector('svg').cloneNode(true) : el('i'), words, del);
    if (S.sel === id) {
      const moves = el('div', 'dke-moves');
      moves.append(button('btn lift', 'Move up', 'up', icon('up', 1.8)), button('btn lift', 'Move down', 'down', icon('down', 1.8)), button('btn lift', 'Move to More', 'more', icon('into')));
      if (fixed) moves.lastChild.setAttribute('aria-disabled', 'true');
      li.append(moves);
    }
    return li;
  }
  function drawList(focusId, part) {
    if (!list || !list.open) return;
    const order = S.layout.order, st = D.state(), shownCount = order.filter((id) => st.shown.includes(id)).length;
    const rows = order.map((id, i) => listRow(id, i, order.length));
    if (shownCount < rows.length) {
      const fold = el('li', 'dke-fold', 'This phone\'s bar ends here'); fold.setAttribute('aria-hidden', 'true');
      rows.splice(shownCount, 0, fold);
    }
    listOl.replaceChildren(...rows);
    listOff.replaceChildren();
    if (S.layout.more.length) {
      listOff.append(el('h3', 'dke-sub', 'Taken off the bar'));
      S.layout.more.forEach((id) => listOff.append(offRow(id, false)));
    }
    const target = list.querySelector(`[data-id="${focusId}"] [data-act="${part || 'hold'}"]`) || list.querySelector(`[data-id="${focusId}"] [data-act="hold"]`);
    if (target) target.focus({ preventScroll: false });
  }
  function listDragMove(e) {
    const d = S.ldrag;
    if (!d.started) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < DRAG_PX) return;
      d.started = true; S.sel = null; d.row.classList.add('dke-lift');
      d.line = el('i', 'dke-drop dke-y'); listOl.append(d.line);
    }
    d.row.style.transform = `translateY(${Math.round(e.clientY - d.y0)}px)`;
    const others = [...listOl.querySelectorAll('.dke-row')].filter((r) => r !== d.row), rects = others.map((r) => r.getBoundingClientRect());
    const i = slot(rects.map((r) => r.top + r.height / 2), e.clientY), ol = listOl.getBoundingClientRect();
    const y = rects[i] ? rects[i].top - 3 : rects[i - 1].bottom + 3;
    d.line.style.top = Math.round(y - ol.top) + 'px';
    d.to = { before: others[i] ? others[i].dataset.id : null, after: others[i - 1] ? others[i - 1].dataset.id : null };
    const next = dropTo(S.layout, d.id, d.to.before, d.to.after);
    say(next === S.layout ? `Let go to leave ${nameOf(d.id)} where it is.` : dropWords(next.order, d.id, names()));
  }
  function listDragEnd() {
    const d = S.ldrag;
    S.ldrag = null;
    if (!d || !d.started) return;
    swallowNextClick();
    const next = dropTo(S.layout, d.id, d.to && d.to.before, d.to && d.to.after);
    if (!commit(next, { words: placeWords(next.order, d.id, names()), focus: d.id, part: 'hold' })) drawList(d.id, 'hold');
  }
  function listDragCancel() { const d = S.ldrag; S.ldrag = null; if (d && d.started) drawList(d.id, 'hold'); }

  // ---- the More sheet: the tabs he took off the bar, each with Put back ------------------------------------------------
  function offRow(id, inSheet) {
    const row = el('div', 'dke-off' + (inSheet ? ' dke-part' : '')), t = tabEl(id), open = el(inSheet ? 'button' : 'span', 'dke-open');
    row.dataset.id = id;
    if (inSheet) open.type = 'button';
    const entry = sheet ? [...sheet.querySelectorAll('[data-sheet-open]')].find((b) => b.dataset.sheetOpen === id) : null;
    const words = el('span'); words.append(el('b', '', nameOf(id)));
    const small = entry && entry.querySelector('small');
    if (small) words.append(el('small', '', small.textContent));
    open.append(t && t.querySelector('svg') ? t.querySelector('svg').cloneNode(true) : el('i'), words);
    if (inSheet && entry) open.addEventListener('click', () => entry.click()); // its panel, as the entry opens it
    const put = button('btn lift', 'Put back', 'put', icon('back'), `Put ${nameOf(id)} back on the bar`);
    if (inSheet) {
      put.addEventListener('click', () => { // focus stays in the sheet: the next row, else the first entry, else Close
        back(id, false);
        if (!sheet.open) return;
        const f = drawSheet(sheet) || sheet.querySelector('[data-sheet-open]:not([hidden])') || $('moreClose');
        if (f) f.focus();
      });
    }
    row.append(open, put);
    return row;
  }
  function drawSheet(into) {
    into.querySelectorAll('.dke-part').forEach((n) => n.remove());
    const title = into.querySelector('h2');
    if (!S.layout.more.length || !title) return null;
    const at = title.nextSibling, add = (n) => { n.classList.add('dke-part'); title.parentNode.insertBefore(n, at); return n; };
    add(el('h3', 'dke-sub', 'Taken off the bar'));
    const rows = S.layout.more.map((id) => add(offRow(id, true)));
    if (into.querySelector('[data-sheet-open]:not([hidden])')) add(el('h3', 'dke-sub', 'No room on this screen'));
    return rows.length ? rows[0].querySelector('.dke-open') : null;
  }
  D.onSheet(drawSheet);
  document.addEventListener('jarvis:dock', () => { // every refit (width, fonts, theme, a change here)
    if (sheet && sheet.open) drawSheet(sheet);
    if (S.editing && D.state().phone !== S.phone) { exit(false); return; }
    if (S.editing && S.base) sayBase();
    placeKeys();
  });
  window.addEventListener('storage', (e) => { // another window of this browser changed it
    if (e.key !== KEY) return;
    exit(false);
    S.layout = layoutFrom(e.newValue, shipped);
    draw(S.layout);
  });

  // ---- start: a saved layout is drawn (the bar waits unseen for it); none: nothing changes -----------------------------
  const text = store.get();
  if (text !== null) {
    const readable = parse(text) !== null;
    S.layout = layoutFrom(readable ? text : null, shipped);
    if (!readable || toStore(shipped, S.layout) === null) store.put(null); // unreadable or the shipped bar: no key
    css();
    draw(S.layout);
  }
}

if (typeof document !== 'undefined' && typeof window !== 'undefined' && window.JarvisDock) boot(window.JarvisDock);
