// src/jarvis/api/static/console-brief-sections.js -- R1 D13 / D15: the Brief's "Deliveries" and
// "Family today" sections, drawn from brief.data.deliveries / brief.data.family. Kept out of
// console-brief.js (size); that file calls window.JarvisBriefSections.render(data) and appends what
// it returns, in order, before the JARVIS section. No build step; CSP script-src 'self'; ASCII source
// with backslash-u escapes only. Everything the server sends reaches the page through textContent:
// parcel subjects and event titles are other people's words, shown as quoted text, never markup or
// links. A field of the wrong type is dropped. A missing key means "not in this brief": no section.
// R11.1 D20: "Inbox by kind" from brief.data.inbox.groups / .withheld / .exact / .failed (the whole
// inbox, by Gmail's own categories; what could not be read is said); a brief whose inbox carries
// none of them shows no such section.
// R7 D18 (I1): "Last night" from brief.data.sleep (the pinned SleepLine {minutes, start, end,
// source}): ONE fixed line, "Sleep: 6 h 40 min, 23:50 to 06:30 \u00b7 from your watch". Only in this
// console's brief: the e-mailed copy and Telegram never carry it. A line of the wrong shape is dropped.
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
    if (state === 'paused') return 'Paused by your Permissions: set \'Search and read email\' to Allow there to see your ' + what + ' here.';
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

  /** R2 "Documents": what is due in the vault (type and time left; never a number or a file). */
  function documents(v) {
    const box = obj(v);
    if (!box) return null;
    const items = arr(box.items).map(obj).filter(Boolean).slice(0, MAX_ITEMS);
    if (!items.length) return null;
    const total = Number.isInteger(box.total) && box.total >= items.length ? box.total : items.length;
    const s = section('documents', 'Documents', total + ' due');
    const ul = mk('ul', 'bpark');
    items.forEach((it) => {
      const li = mk('li'), n = Number.isInteger(it.days_left) ? it.days_left : null;
      const when = n === null ? '' : n < 0 ? 'expired ' + (-n) + (n === -1 ? ' day ago' : ' days ago') : n === 0 ? 'expires today' : 'expires in ' + n + (n === 1 ? ' day' : ' days');
      li.append(mk('b', '', txt(it.type_label, 60) || 'Document'), mk('span', '', when ? ' \u00b7 ' + when : ''));
      if (it.whose === 'family') li.append(mk('small', '', 'family'));
      ul.append(li);
    });
    s.append(ul);
    if (total > items.length) s.append(mk('p', 'bfine', '\u2026 and ' + (total - items.length) + ' more.'));
    return s;
  }

  /** R3 "Home overnight": counts and times with fixed words (never a name or a picture). */
  function home(h) {
    const box = obj(h);
    if (!box) return null;
    const items = arr(box.items).map(obj).filter(Boolean).slice(0, MAX_ITEMS);
    if (!items.length) return null;
    const total = Number.isInteger(box.total) && box.total >= items.length ? box.total : items.length;
    const s = section('home', 'Home overnight', total + (total === 1 ? ' thing' : ' things'));
    const ul = mk('ul', 'bpark');
    items.forEach((it) => {
      const li = mk('li');
      li.append(mk('span', 'btime', txt(it.when, 10) || '\u2014'), mk('span', '', ' ' + txt(it.words, 160)));
      ul.append(li);
    });
    s.append(ul);
    if (Number.isInteger(box.held) && box.held > 0) s.append(mk('p', 'bfine', box.held + (box.held === 1 ? ' alert was' : ' alerts were') + ' held for quiet hours.'));
    if (total > items.length) s.append(mk('p', 'bfine', '\u2026 and ' + (total - items.length) + ' more.'));
    return s;
  }

  /** R4 "Vitals": the board's red / amber lines and the AI spend (labels and limits, never a key). */
  function vitals(v) {
    const box = obj(v);
    if (!box) return null;
    const lines = arr(box.lines).map((l) => txt(l, 160)).filter(Boolean).slice(0, MAX_ITEMS + 1);
    const note = stateLine(box.state, 'Vitals board');
    if (!lines.length && !note) return null;
    const s = section('vitals', 'Vitals', lines.length ? lines.length + (lines.length === 1 ? ' line' : ' lines') : '');
    if (note) { s.append(mk('p', 'bfine', note)); return s; }
    const ul = mk('ul', 'bpark');
    lines.forEach((line) => ul.append(mk('li', '', line)));
    s.append(ul);
    return s;
  }

  /** R11 "Helpers": today's fixed helper lines (bills, birthdays, chores, the weather, spend). */
  function helpers(v) {
    const box = obj(v);
    if (!box) return null;
    const lines = arr(box.lines).map((l) => txt(l, 160)).filter(Boolean).slice(0, 8);
    const note = stateLine(box.state, 'helpers');
    if (!lines.length && !note) return null;
    const s = section('helpers', 'Helpers', lines.length ? lines.length + (lines.length === 1 ? ' line' : ' lines') : '');
    if (note) { s.append(mk('p', 'bfine', note)); return s; }
    const ul = mk('ul', 'bpark');
    lines.forEach((line) => ul.append(mk('li', '', line)));
    s.append(ul);
    return s;
  }

  /** R7 D18 "Last night": one line, the night's length and times and where it came from. */
  const SLEEP_FROM = { watch: 'from your watch', phone: 'from your phone', app: 'from another health app', typed: 'typed by you' };
  const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
  function sleep(v) {
    const n = obj(v);
    if (!n || !Number.isInteger(n.minutes) || n.minutes < 0 || n.minutes > 1440) return null;
    if (!HHMM.test(n.start) || !HHMM.test(n.end) || !Object.prototype.hasOwnProperty.call(SLEEP_FROM, n.source)) return null;
    const h = Math.floor(n.minutes / 60), m = n.minutes % 60;
    const long = h && m ? h + ' h ' + m + ' min' : (h ? h + ' h' : m + ' min');
    const s = section('sleep', 'Last night', ''), ul = mk('ul', 'bpark');
    ul.append(mk('li', '', 'Sleep: ' + long + ', ' + n.start + ' to ' + n.end + ' \u00b7 ' + SLEEP_FROM[n.source]));
    s.append(ul);
    return s;
  }

  /** R11.1 D20 "Inbox by kind": Gmail's own categories counted (labels are JARVIS's own words), and
   *  how many messages are not listed because they look like a code or a bank message. Drawn only
   *  when the brief's inbox carries `groups` / `withheld`. */
  function inboxKinds(v) {
    const box = obj(v);
    if (!box) return null;
    const kinds = arr(box.groups).map(obj).filter(Boolean).slice(0, 6)
      .map((g) => ({ label: txt(g.label, 30), n: Number.isInteger(g.unread) && g.unread > 0 ? g.unread : 0 }))
      .filter((g) => g.label && g.n);
    const held = Number.isInteger(box.withheld) && box.withheld > 0 ? box.withheld : 0;
    const failed = Number.isInteger(box.failed) && box.failed > 0 ? box.failed : 0;
    const listed = Number.isInteger(box.listed) && box.listed >= failed ? box.listed : failed;
    if (!kinds.length && !held && !failed && box.exact !== false) return null;
    const s = section('inboxkinds', 'Inbox by kind', box.exact === false ? 'of the newest unread' : '');
    if (box.exact === false) s.append(mk('p', 'bfine', 'Gmail didn\u2019t give its own count just now: the number is an estimate.'));
    if (failed) s.append(mk('p', 'bfine', 'I couldn\u2019t read ' + (failed >= listed ? 'any' : failed) + ' of the ' + listed + ' newest unread messages just now.'));
    if (kinds.length) {
      const ul = mk('ul', 'bpark');
      kinds.forEach((g) => { const li = mk('li'); li.append(mk('b', '', g.label), mk('span', '', ' \u00b7 ' + g.n + ' unread')); ul.append(li); });
      s.append(ul);
    }
    if (held) s.append(mk('p', 'bfine', held === 1 ? '1 more looks like a code or a bank message: open it in Gmail.' : held + ' more look like codes or bank messages: open them in Gmail.'));
    return s;
  }

  /** The sections this brief carries, in display order (an absent one is simply left out). */
  function render(data) {
    const d = obj(data) || {};
    return [inboxKinds(d.inbox), deliveries(d.deliveries), family(d.family), documents(d.vault), home(d.home), vitals(d.vitals), helpers(d.helpers), sleep(d.sleep)].filter(Boolean);
  }

  window.JarvisBriefSections = Object.freeze({ render });
})();
