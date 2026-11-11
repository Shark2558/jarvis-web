// src/jarvis/api/static/console-helpers-nudges.js -- R11 Part C's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D6, D19): each nudge (stand-up, water, a planned activity, free time, focus)
// with its switch, Snooze 1 h and Stop for today (I0's taps: /v1/helpers/gate/{kind}/snooze|stop|resume), its
// settings, today's water and stand-ups (the sealed log), and the free-time list. Data: /v1/helpers/nudges.
// An ES module loaded by console-helpers.js; only window.JarvisHelpers' builders and the existing components
// (.btn.bact, .bsw, .minput in .pskadd, .sfine); textContent only; 44 px targets on the phone; ASCII source.
const H = window.JarvisHelpers;
const BASE = '/v1/helpers/nudges';
const GATE = '/v1/helpers/gate/';
const SNOOZE_MIN = 60;
const PLACES = [['any', 'Indoor or outdoor'], ['indoor', 'Indoor'], ['outdoor', 'Outdoor']];

function button(text, aria, act) {
  const b = H.mk('button', 'btn bact', text);
  b.type = 'button';
  if (aria) b.setAttribute('aria-label', aria);
  b.addEventListener('click', act);
  return b;
}

function input(type, aria, value, extra) {
  const i = H.mk('input', 'minput');
  i.type = type;
  i.setAttribute('aria-label', aria);
  i.autocomplete = 'off';
  if (value !== undefined && value !== null) i.value = String(value);
  Object.assign(i, extra || {});
  return i;
}

function hhmm(iso) {
  const at = typeof iso === 'string' ? new Date(iso) : null;
  return at && !isNaN(at) ? at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
}

function held(view, kind) {
  const g = view.gate || {};
  const stopped = g.stopped || {};
  const today = g.today;
  if (stopped[kind] === today || stopped['*'] === today) return 'Stopped for today.';
  const until = [(g.snoozed || {})[kind], (g.snoozed || {})['*']].filter(Boolean).sort().pop();
  if (until && new Date(until) > new Date()) return 'Snoozed until ' + hhmm(until) + '.';
  return '';
}

if (H) {
  const S = { host: null, note: null, view: null, busy: false };

  async function call(path, opts) {
    if (S.busy) return;
    S.busy = true;
    try {
      const got = await H.api(path, opts);
      if (path.startsWith(GATE)) await load(); else render(got);
      H.note(S.note, 'ok', 'Saved.');
    } catch (e) {
      const words = e && typeof e.message === 'string' && e.message.length < 200 ? e.message : 'Couldn\'t save that just now.';
      H.note(S.note, 'bad', e && e.name === 'TypeError' ? 'Can\'t reach JARVIS. Check your connection.' : words);
    } finally { S.busy = false; }
  }

  function nudgeRow(view, n) {
    const acts = [H.toggle('Switch ' + n.label, !!n.on, (on) => call(BASE + '/' + n.name, { method: 'PUT', body: { on } }))];
    const state = held(view, n.kind);
    if (n.on && state) acts.push(button('Resume', 'Resume ' + n.label, () => call(GATE + n.kind + '/resume', { method: 'POST' })));
    if (n.on && !state) {
      acts.push(button('Snooze', 'Snooze ' + n.label + ' for 1 hour', () => call(GATE + n.kind + '/snooze', { body: { minutes: SNOOZE_MIN } })));
      acts.push(button('Stop', 'Stop ' + n.label + ' for today', () => call(GATE + n.kind + '/stop', { method: 'POST' })));
    }
    const r = H.row(n.label, [n.when || n.line, state].filter(Boolean).join(' '), acts);
    r.dataset.nudge = n.name;
    return r;
  }

  function allRow(view) {
    const state = held(view, '*');
    const acts = state
      ? [button('Resume all', 'Resume every nudge', () => call(GATE + 'all/resume', { method: 'POST' }))]
      : [button('Snooze all', 'Snooze every nudge for 1 hour', () => call(GATE + 'all/snooze', { body: { minutes: SNOOZE_MIN } })),
         button('No more today', 'Stop every nudge for today', () => call(GATE + 'all/stop', { method: 'POST' }))];
    return H.row('Every nudge', state || 'Nudges come only inside your hours and never at night.', acts);
  }

  function form(title, fields, save) {
    const wrap = H.mk('div', 'pskadd');
    fields.forEach((f) => wrap.append(f));
    wrap.append(button('Save', 'Save ' + title, save));
    const s = H.mk('div');
    s.append(H.mk('p', 'sfine', title), wrap);
    return s;
  }

  function list(text) { return String(text || '').split(',').map((x) => x.trim()).filter(Boolean); }

  function settings(view) {
    const sec = H.section('When they come');
    const by = {};
    (view.nudges || []).forEach((n) => { by[n.name] = n; });
    ['standup', 'water'].forEach((name) => {
      const n = by[name]; if (!n) return;
      const every = input('number', n.label + ': every how many minutes', n.every, { min: 15, max: 240, step: 15 });
      const from = input('time', n.label + ': from', n.start);
      const to = input('time', n.label + ': until', n.end);
      sec.append(form(n.label + ': every N minutes, from, until', [every, from, to], () =>
        call(BASE + '/' + name, { method: 'PUT', body: { every: Number(every.value), start: from.value, end: to.value } })));
    });
    const up = by.standup;
    if (up) {
      const word = input('text', 'The word your stand-up meeting is called', up.word, { maxLength: 30 });
      const meet = H.toggle('Also 10 minutes before my stand-up meeting', !!up.meeting, (on) =>
        call(BASE + '/standup', { method: 'PUT', body: { meeting: on, word: word.value.trim() } }));
      sec.append(H.row('Your stand-up meeting', '"Your stand-up starts in 10 minutes", from your calendar.', [meet]));
      sec.append(form('Its title contains', [word], () => call(BASE + '/standup', { method: 'PUT', body: { word: word.value.trim() } })));
    }
    [['focus', 'times'], ['free_time', 'times'], ['activity', 'words']].forEach(([name, field]) => {
      const n = by[name]; if (!n) return;
      const label = field === 'times' ? n.label + ': at (HH:MM, comma separated)' : n.label + ': your activity words';
      const box = input('text', label, (n[field] || []).join(', '), { maxLength: 120 });
      sec.append(form(label, [box], () => call(BASE + '/' + name, { method: 'PUT', body: { [field]: list(box.value) } })));
    });
    return sec;
  }

  function logSection(view) {
    const sec = H.section('Today');
    if (!view.sealed || !view.today) {
      sec.append(H.empty('The water and stand-up log is off: it needs JARVIS\'s token key, so nothing is kept. The reminders still work.'));
      return sec;
    }
    sec.append(H.row('Water', view.today.water + ' glasses today', [button('+1 glass', 'Log a glass of water', () => call(BASE + '/water', { body: { glasses: 1 } }))]));
    sec.append(H.row('Stand-ups', view.today.stood + ' today', [button('+1', 'Log a stand-up', () => call(BASE + '/stood', { method: 'POST' }))]));
    return sec;
  }

  function ideas(view) {
    const sec = H.section('Your free-time list');
    const items = view.ideas || [];
    if (!items.length) sec.append(H.empty('No ideas yet. Add what you like doing; JARVIS picks one that fits your free time.'));
    items.forEach((i) => {
      const sub = i.minutes + ' min, ' + i.place + (i.last_done ? ', last done ' + i.last_done : '');
      sec.append(H.row(i.text, sub, [
        button('Done', 'Done today: ' + i.text, () => call(BASE + '/ideas/' + encodeURIComponent(i.id) + '/done', { method: 'POST' })),
        button('Remove', 'Remove ' + i.text, () => call(BASE + '/ideas/' + encodeURIComponent(i.id), { method: 'DELETE' })),
      ]));
    });
    const text = input('text', 'A free-time idea', '', { maxLength: 80, placeholder: 'Read a novel' });
    const mins = input('number', 'Minutes it takes', 30, { min: 5, max: 480, step: 5 });
    const place = H.mk('select', 'minput');
    place.setAttribute('aria-label', 'Indoor or outdoor');
    PLACES.forEach(([v, t]) => { const o = H.mk('option', '', t); o.value = v; place.append(o); });
    const wrap = H.mk('div', 'pskadd');
    wrap.append(text, mins, place, button('Add', 'Add the idea', () => {
      if (!text.value.trim()) { H.note(S.note, 'bad', 'Type the idea first.'); return; }
      call(BASE + '/ideas', { body: { text: text.value.trim(), minutes: Number(mins.value), place: place.value } });
    }));
    sec.append(wrap);
    return sec;
  }

  function render(view) {
    if (!S.host || !view || typeof view !== 'object') return;
    S.view = view;
    const top = H.section('Nudges');
    top.append(H.mk('p', 'sfine', 'Each one is off until you switch it on. Say "snooze the water reminder for an hour" or "stop water" too.'));
    (view.nudges || []).forEach((n) => top.append(nudgeRow(view, n)));
    top.append(allRow(view));
    const note = H.mk('p', 'sfine hp-note');
    note.setAttribute('role', 'status');
    S.note = note;
    S.host.replaceChildren(top, note, logSection(view), ideas(view), settings(view));
  }

  async function load() {
    try {
      render(await H.api(BASE));
    } catch (e) {
      if (!S.host) return;
      const off = e && e.status === 404;
      S.host.replaceChildren(H.empty(off ? 'The nudges are off on this server.' : 'Couldn\'t load your nudges.'));
    }
  }

  H.register('nudges', {
    mount(host) { S.host = host; host.append(H.empty('Loading your nudges...')); load(); },
    refresh() { if (S.host && !S.busy) load(); },
  });
}
