// src/jarvis/api/static/console-brief-sections.js -- R1 D13 / D15: the Brief's "Deliveries" and
// "Family today" sections, drawn from brief.data.deliveries / brief.data.family. Kept out of
// console-brief.js (size); that file calls window.JarvisBriefSections.render(data) and appends what
// it returns, in order, before the JARVIS section. No build step; CSP script-src 'self'; ASCII source
// with backslash-u escapes only. Everything the server sends reaches the page through textContent:
// parcel subjects and event titles are other people's words, shown as quoted text, never markup or
// links. A field of the wrong type is dropped. A missing key means "not in this brief": no section.
(() => {
  'use strict';
  const MAX_ITEMS = 5;
  const MAX_MEMBERS = 20;
  const MAX_EVENTS = 30;
  const STATUS = { ordered: 'Ordered', shipped: 'Shipped', out_for_delivery: 'Out for delivery', delivered: 'Delivered' };
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v : '').replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const quoted = (s) => '\u201c' + s + '\u201d';

  function section(key, title, meta) {
    const s = mk('section', 'bsec'), h = mk('h3', '');
    h.id = 'bsec-' + key; h.append(mk('span', '', title));
    if (meta) h.append(mk('span', 'bcount', '\u00b7 ' + meta));
    s.setAttribute('aria-labelledby', h.id); s.append(h);
    return s;
  }
  function stateLine(state, what) {
    if (state === 'not_connected') return 'Connect Google to see your ' + what + ' here.';
    if (state === 'unavailable' || state === 'not_granted') return 'Couldn\'t read your ' + what + ' just now.';
    return '';
  }
  /** "Mon 9 Nov" from YYYY-MM-DD, read as a calendar date (never shifted by time zone). */
  function day(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return '';
    try {
      return new Intl.DateTimeFormat([], { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
        .format(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    } catch (_) { return ''; }
  }

  function deliveries(d) {
    const box = obj(d);
    if (!box) return null;
    const total = Number.isInteger(box.total) && box.total >= 0 ? box.total : 0;
    const s = section('deliveries', 'Deliveries', total ? total + ' on the way or just delivered' : '');
    const state = txt(box.state, 20), line = stateLine(state, 'deliveries');
    if (state && state !== 'ok' && line) { s.append(mk('p', 'bmiss warn', line)); return s; }
    const items = arr(box.items).map(obj).filter(Boolean).slice(0, MAX_ITEMS);
    if (!items.length) { s.append(mk('p', 'bempty', 'No parcels on the way.')); return s; }
    const ul = mk('ul', 'bpark');
    items.forEach((it) => {
      const li = mk('li');
      const word = Object.hasOwn(STATUS, it.status) ? STATUS[it.status] : 'Update';
      li.append(mk('b', '', word), mk('span', '', ' \u00b7 ' + quoted(txt(it.item, 160) || '(no subject)')));
      const when = day(txt(it.expected, 10));
      const bits = [txt(it.merchant, 60), txt(it.carrier, 60), when ? 'expected ' + when : ''].filter(Boolean);
      if (bits.length) li.append(mk('small', '', bits.join(' \u00b7 ')));
      ul.append(li);
    });
    s.append(ul);
    if (total > items.length) s.append(mk('p', 'bfine', '\u2026 and ' + (total - items.length) + ' more.'));
    return s;
  }

  function family(f) {
    const box = obj(f);
    if (!box) return null;
    const s = section('family', 'Family today');
    const state = txt(box.state, 20), line = stateLine(state, 'family calendars');
    if (state && state !== 'ok' && line) { s.append(mk('p', 'bmiss warn', line)); return s; }
    const members = arr(box.members).map(obj).filter(Boolean).slice(0, MAX_MEMBERS);
    const ul = mk('ul', 'bfam');
    members.forEach((m) => {
      const li = mk('li'), name = txt(m.name, 40) || '(no name)';
      if (m.unavailable === true) { li.append(mk('b', '', name), mk('span', '', ': not shared with you any more.')); ul.append(li); return; }
      const events = arr(m.events).map(obj).filter(Boolean).slice(0, MAX_EVENTS);
      if (!events.length) { li.append(mk('b', '', name), mk('span', '', ': nothing today.')); ul.append(li); return; }
      li.append(mk('b', '', name));
      if (m.busy_only === true) li.append(mk('small', '', 'busy times only'));
      events.forEach((e) => {
        const row = mk('div', 'bfev'), title = txt(e.title, 160);
        row.append(mk('span', 'btime', txt(e.when, 20) || '\u2014'), mk('span', '', title ? quoted(title) : 'busy'));
        li.append(row);
      });
      ul.append(li);
    });
    if (!ul.childElementCount) { s.append(mk('p', 'bempty', 'Nothing on the family calendars today.')); return s; }
    s.append(ul);
    return s;
  }

  /** The sections this brief carries, in display order (an absent one is simply left out). */
  function render(data) {
    const d = obj(data) || {};
    return [deliveries(d.deliveries), family(d.family)].filter(Boolean);
  }

  window.JarvisBriefSections = Object.freeze({ render });
})();
