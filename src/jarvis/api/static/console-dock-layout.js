// src/jarvis/api/static/console-dock-layout.js -- R8 I0 seam S28 (docs/plans/r8-vision.md v8.0.3 D13, part I "your
// bar, your way"; frozen: builder I builds the editor on it). The bar's layout model, PURE (no page, no storage of its
// own: the editor reads and writes localStorage['jarvis_dock_layout_v1'] on this device only and passes the text here).
//   layout = {v: 1, order: [tab ids in the bar, left to right], more: [tab ids he removed to More], hidden: bool}
//   parse(text)                 a layout, or null for anything it can't read (then the shipped bar is used)
//   apply(defaults, saved)      the layout to draw: `defaults` is the bar's own tab ids in the page's order. Ids the
//                               console no longer has are dropped; tabs a later release adds are appended at the END of
//                               the bar (never lost); chat and More can never leave the bar; null saved -> the defaults
//   isDefault(defaults, layout) true when it draws exactly the shipped bar (then the editor writes nothing: the 1920 px
//                               bar stays byte-identical until he edits it, R18's rule)
//   move(layout, id, to)        the id at bar index `to` (clamped)
//   toMore(layout, id)          removed from the bar to More (chat and More: unchanged)
//   fromMore(layout, id, at)    put back from More at bar index `at` (the end when omitted)
//   hide(layout, on)            the bar hidden (a slim handle and a shortcut show it again: builder I)
//   serialize(layout)           the text the editor saves
// Every function returns a NEW frozen layout. More itself is not a tab id here: it shows only when tabs overflow or he
// removed one (today's behaviour, the coordinator's correction to the mockup).
export const VERSION = 1;
export const KEY = 'jarvis_dock_layout_v1';
export const FIXED = Object.freeze(['chat']); // never removed from the bar (More is not in the list: it is never a tab)
const ID = /^[a-z][a-z0-9-]{0,23}$/;
const MAX = 40;

const ids = (list) => (Array.isArray(list) ? [...new Set(list.filter((x) => typeof x === 'string' && ID.test(x)))].slice(0, MAX) : []);
const freeze = (l) => Object.freeze({ v: VERSION, order: Object.freeze(l.order.slice()), more: Object.freeze(l.more.slice()), hidden: !!l.hidden });

export function parse(text) {
  let o = null;
  try { o = JSON.parse(String(text)); } catch (_) { return null; }
  if (!o || typeof o !== 'object' || Array.isArray(o) || o.v !== VERSION) return null;
  return freeze({ order: ids(o.order), more: ids(o.more).filter((x) => !FIXED.includes(x)), hidden: o.hidden === true });
}

export function apply(defaults, saved) {
  const all = ids(defaults);
  if (!saved) return freeze({ order: all, more: [], hidden: false });
  const known = (x) => all.includes(x);
  const more = saved.more.filter((x) => known(x) && !FIXED.includes(x));
  const order = saved.order.filter((x) => known(x) && !more.includes(x));
  const fresh = all.filter((x) => !order.includes(x) && !more.includes(x)); // a later release's tabs: at the end
  const bar = [...order, ...fresh];
  FIXED.forEach((x) => { if (known(x) && !bar.includes(x)) bar.unshift(x); });
  return freeze({ order: bar, more, hidden: saved.hidden });
}

export function isDefault(defaults, layout) {
  const all = ids(defaults);
  return !!layout && !layout.hidden && layout.more.length === 0 && layout.order.join(' ') === all.join(' ');
}

export function move(layout, id, to) {
  const order = layout.order.filter((x) => x !== id);
  if (order.length === layout.order.length) return layout;
  const at = Math.max(0, Math.min(order.length, Math.trunc(Number(to) || 0)));
  order.splice(at, 0, id);
  return freeze(Object.assign({}, layout, { order }));
}

export function toMore(layout, id) {
  if (FIXED.includes(id) || !layout.order.includes(id)) return layout;
  return freeze(Object.assign({}, layout, { order: layout.order.filter((x) => x !== id), more: [...layout.more, id] }));
}

export function fromMore(layout, id, at) {
  if (!layout.more.includes(id)) return layout;
  const order = layout.order.slice();
  const where = at === undefined ? order.length : Math.max(0, Math.min(order.length, Math.trunc(Number(at) || 0)));
  order.splice(where, 0, id);
  return freeze(Object.assign({}, layout, { order, more: layout.more.filter((x) => x !== id) }));
}

export function hide(layout, on) {
  return freeze(Object.assign({}, layout, { hidden: !!on }));
}

export function serialize(layout) {
  return JSON.stringify({ v: VERSION, order: layout.order, more: layout.more, hidden: layout.hidden });
}
