// src/jarvis/api/static/console-helpers-house.js -- R11 Part B's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D10-D14, D19): the chores rota, home upkeep, weather and disaster alerts for
// your place, breach notices. An ES module loaded by console-helpers.js (never linked). It uses only
// window.JarvisHelpers' builders, the existing components (.btn.bact, .minput, label.k, .vt-grid / .vt-field,
// .lrow, .lerr, .bsw) and textContent: no new colours, fonts, radii or shadows; no HTML from the server; ASCII.
// Data: GET /v1/helpers/house (every change answers the whole view again). SACHET's own words are shown only as
// SACHET's ("From SACHET:"), never as JARVIS's; the official SACHET app, SMS and cell broadcast come first.
const H = window.JarvisHelpers;
const BASE = '/v1/helpers/house';
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const KIND_WORD = { disaster_alert: 'Urgent', weather_warning: 'Warning', weather_note: 'Advisory' };
const STATE_WORD = { ok: 'On schedule', soon: 'Due soon', due: 'Due today', overdue: 'Overdue' };
let uid = 0;

function hhmm(iso) {
  if (typeof iso !== 'string') return '';
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function dayMonth(iso) {
  if (typeof iso !== 'string') return '';
  const d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : ''));
  return isNaN(d) ? '' : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function makeTab(host) {
  const { mk, row, section, empty, note, toggle, txt } = H;
  const status = mk('p', 'sfine hp-note');
  status.setAttribute('role', 'status');
  const lists = {};
  let view = null;
  let busy = false;

  function button(label, fn, cls) {
    const b = mk('button', cls || 'btn bact', label);
    b.type = 'button';
    b.addEventListener('click', () => fn(b));
    return b;
  }
  function control(tag, type, max) {
    const c = mk(tag, 'minput');
    if (type) c.type = type;
    if (max) c.maxLength = max;
    c.autocomplete = 'off';
    c.id = 'hph-' + (++uid);
    return c;
  }
  function field(text, input, wide) {
    const w = mk('div', 'vt-field' + (wide ? ' wide' : ''));
    const l = mk('label', 'k', text);
    l.htmlFor = input.id;
    w.append(l, input);
    return w;
  }
  function select(options, words) {
    const s = control('select');
    options.forEach((v) => { const o = mk('option', '', words ? words[v] || v : v); o.value = v; s.append(o); });
    return s;
  }
  function form(fields, label, submit) {
    const f = mk('form', '');
    f.noValidate = true;
    const grid = mk('div', 'vt-grid');
    fields.forEach((x) => grid.append(x));
    const err = mk('p', 'lerr');
    err.setAttribute('role', 'alert');
    const go = mk('button', 'btn bact', label);
    go.type = 'submit';
    const acts = mk('div', 'lrow');
    acts.append(go);
    f.append(grid, err, acts);
    f.addEventListener('submit', (e) => { e.preventDefault(); submit(err); });
    return f;
  }

  async function call(path, opts, err) {
    if (busy) return;
    busy = true;
    if (err) err.textContent = '';
    try {
      render(await H.api(path, opts));
      note(status, 'ok', 'Saved.');
    } catch (e) {
      const words = e && e.name === 'TypeError' ? 'Can\u2019t reach JARVIS. Check your connection.' : (e && e.message) || 'That didn\u2019t work.';
      if (err) err.textContent = txt(words, 200); else note(status, 'bad', words);
    } finally { busy = false; }
  }
  async function load() {
    try { render(await H.api(BASE)); } catch (e) {
      note(status, 'bad', e && e.code === 'helpers_off' ? 'The Home helpers are off on this server.' : 'Couldn\u2019t load Home.');
    }
  }

  // ---- chores ------------------------------------------------------------------------------------------
  const chores = section('Chores rota');
  lists.chores = mk('div', '');
  const cf = {
    label: control('input', 'text', 40), freq: select(['daily', 'weekly', 'every'], { daily: 'Every day', weekly: 'On some days', every: 'Every N days' }),
    days: control('input', 'text', 40), every: control('input', 'number'), at: control('input', 'time'), members: control('input', 'text', 160),
  };
  cf.at.value = '09:00';
  cf.every.min = '2'; cf.every.max = '90';
  cf.days.placeholder = 'Mon, Thu';
  cf.members.placeholder = 'Labels, comma-separated';
  const adults = mk('p', 'sfine', '');
  chores.append(lists.chores, adults, form([
    field('Chore', cf.label, true), field('How often', cf.freq), field('Time', cf.at), field('Days (if some days)', cf.days),
    field('Every N days', cf.every), field('Rota (adults only)', cf.members, true),
  ], 'Add chore', (err) => {
    const days = cf.days.value.split(',').map((d) => d.trim().toLowerCase().slice(0, 3)).filter((d) => DAYS.includes(d));
    const body = { label: cf.label.value.trim(), freq: cf.freq.value, at: cf.at.value || '09:00',
      members: cf.members.value.split(',').map((m) => m.trim()).filter(Boolean).slice(0, 6) };
    if (body.freq === 'weekly') body.days = days;
    if (body.freq === 'every') body.every = parseInt(cf.every.value, 10) || 0;
    call(BASE + '/chores', { method: 'POST', body }, err).then(() => { if (!err.textContent) cf.label.value = ''; });
  }));

  // ---- upkeep ------------------------------------------------------------------------------------------
  const upkeep = section('Home upkeep');
  lists.upkeep = mk('div', '');
  lists.starters = mk('div', '');
  const uf = {
    label: control('input', 'text', 40), every: control('input', 'number'), unit: select(['days', 'months']),
    last: control('input', 'date'), lead: control('input', 'number'),
  };
  uf.every.min = '1'; uf.lead.min = '0'; uf.lead.max = '60'; uf.lead.value = '7';
  upkeep.append(lists.upkeep, lists.starters, form([
    field('Item', uf.label, true), field('Every', uf.every), field('Days or months', uf.unit), field('Last done', uf.last),
    field('Remind days before', uf.lead),
  ], 'Add item', (err) => {
    const body = { label: uf.label.value.trim(), every: parseInt(uf.every.value, 10) || 0, unit: uf.unit.value,
      lead: parseInt(uf.lead.value, 10) || 0 };
    if (uf.last.value) body.last_done = uf.last.value;
    call(BASE + '/upkeep', { method: 'POST', body }, err).then(() => { if (!err.textContent) uf.label.value = ''; });
  }));

  // ---- weather and alerts --------------------------------------------------------------------------------
  const outside = section('Weather and disaster alerts');
  const first = mk('p', 'sfine hp-note');
  const offNote = mk('p', 'sfine hp-note');
  lists.feeds = mk('div', '');
  lists.warnings = mk('div', '');
  const pf = {
    district: control('input', 'text', 40), state: control('select'), lat: control('input', 'number'), lon: control('input', 'number'),
    lgd: control('input', 'text', 6),
  };
  pf.lat.step = '0.01'; pf.lon.step = '0.01';
  pf.district.placeholder = 'As official warnings write it';
  const clear = button('Clear my place', () => call(BASE + '/place', { method: 'DELETE' }));
  const placeForm = form([
    field('Your district', pf.district, true), field('State', pf.state, true), field('Latitude (optional)', pf.lat),
    field('Longitude (optional)', pf.lon), field('LGD district code (optional)', pf.lgd),
  ], 'Save my place', (err) => {
    const body = { district: pf.district.value.trim(), state: pf.state.value };
    if (pf.lat.value && pf.lon.value) { body.lat = parseFloat(pf.lat.value); body.lon = parseFloat(pf.lon.value); }
    if (pf.lgd.value.trim()) body.lgd = pf.lgd.value.trim();
    call(BASE + '/place', { method: 'PUT', body }, err);
  });
  placeForm.querySelector('.lrow').append(clear);
  const attribution = mk('p', 'sfine', '');
  outside.append(first, offNote, lists.feeds, lists.warnings, placeForm, attribution);

  // ---- breach notices --------------------------------------------------------------------------------------
  const breach = section('Breach notices');
  lists.breach = mk('div', '');
  const how = mk('p', 'sfine', '');
  breach.append(lists.breach, how);

  host.append(status, chores, upkeep, outside, breach);

  // ---- render -------------------------------------------------------------------------------------------
  function renderChores(v) {
    lists.chores.replaceChildren();
    adults.textContent = txt(v.adults_only || '', 200);
    const cs = Array.isArray(v.chores) ? v.chores : [];
    if (!cs.length) lists.chores.append(empty('No chores yet. Add one below; reminders go only to you.'));
    cs.forEach((c) => {
      const turn = c.whose ? c.whose + '\u2019s turn' : 'No rota';
      const when = c.done_today ? 'Done today' : c.today ? 'Today at ' + c.at : 'Next ' + dayMonth(c.next) + ' at ' + c.at;
      lists.chores.append(row(c.label, txt(c.how_often, 60) + ' \u00b7 ' + when + ' \u00b7 ' + turn, [
        button('Done', () => call(BASE + '/chores/' + encodeURIComponent(c.id) + '/done', { method: 'POST' })),
        button('Remove', () => call(BASE + '/chores/' + encodeURIComponent(c.id), { method: 'DELETE' })),
      ]));
    });
  }
  function renderUpkeep(v) {
    lists.upkeep.replaceChildren();
    lists.starters.replaceChildren();
    const xs = Array.isArray(v.upkeep) ? v.upkeep : [];
    if (!xs.length) lists.upkeep.append(empty('No upkeep items yet.'));
    xs.forEach((x) => {
      const sub = 'Every ' + x.every + ' ' + x.unit + ' \u00b7 due ' + dayMonth(x.due) + ' \u00b7 ' + (STATE_WORD[x.state] || '');
      lists.upkeep.append(row(x.label, sub, [
        button('Done', () => call(BASE + '/upkeep/' + encodeURIComponent(x.id) + '/done', { method: 'POST' })),
        button('Remove', () => call(BASE + '/upkeep/' + encodeURIComponent(x.id), { method: 'DELETE' })),
      ]));
    });
    (Array.isArray(v.starters) ? v.starters : []).forEach((s) => {
      lists.starters.append(row(s.label, 'Suggested: every ' + s.every + ' ' + s.unit + ' (not added until you add it)', [
        button('Add', () => call(BASE + '/upkeep', { method: 'POST', body: { label: s.label, every: s.every, unit: s.unit } })),
      ]));
    });
  }
  function feedLine(name, f, okWords) {
    if (f && f.fail_since) return ['Can\u2019t reach ' + name + ' since ' + hhmm(f.fail_since), 'bad'];
    if (f && f.ok_at) return [name + ': ' + okWords + ', checked ' + hhmm(f.checked_at || f.ok_at), ''];
    return [name + ': not checked yet', ''];
  }
  function renderOutside(o) {
    first.textContent = txt(o.official_first || '', 240);
    lists.feeds.replaceChildren();
    lists.warnings.replaceChildren();
    if (!o.available) {
      note(offNote, 'bad', o.off || 'Weather and alerts are off on this server.');
      placeForm.hidden = true;
    } else {
      placeForm.hidden = false;
      offNote.textContent = o.place ? '' : 'Off until you type your district: then JARVIS checks Open-Meteo and SACHET for it.';
      if (pf.state.options.length !== (o.states || []).length) {
        pf.state.replaceChildren();
        (o.states || []).forEach((s) => { const op = mk('option', '', s); op.value = s; pf.state.append(op); });
      }
      if (o.place) {
        pf.district.value = o.place.district || ''; pf.state.value = o.place.state || '';
        pf.lat.value = o.place.lat == null ? '' : String(o.place.lat); pf.lon.value = o.place.lon == null ? '' : String(o.place.lon);
        pf.lgd.value = o.place.lgd || '';
        const w = o.weather || {};
        const s = w.summary;
        const sum = s ? (s.t_max != null ? 'up to ' + Math.round(s.t_max) + ' \u00b0C' : 'no temperature') + (s.rain_from ? ', rain likely after ' + s.rain_from : ', no rain expected') : 'no forecast yet';
        if (o.weather_enabled) lists.feeds.append(statusRow(...feedLine('Open-Meteo', w, sum)));
        if (!o.point_known) lists.feeds.append(statusRow('Weather needs your district centre\u2019s latitude and longitude.', 'bad'));
        if (o.disaster_enabled) lists.feeds.append(statusRow(...feedLine('SACHET', o.sachet, 'warnings for ' + o.place.district)));
      }
      const ws = (o.sachet && Array.isArray(o.sachet.warnings)) ? o.sachet.warnings : [];
      ws.forEach((w) => {
        const said = w.outside_text || {};
        const words = [said.headline, said.instruction].filter((x) => typeof x === 'string' && x).join(' ');
        lists.warnings.append(row((KIND_WORD[w.kind] || 'Warning') + ': ' + w.event + (w.until ? ' until ' + hhmm(w.until) : ''),
          words ? 'From SACHET: ' + txt(words, 180) : 'From SACHET'));
      });
    }
    const a = o.attribution || {};
    attribution.textContent = [a.weather, a.sachet].filter(Boolean).join(' \u00b7 ');
  }
  function statusRow(text, kind) {
    return mk('p', 'sfine hp-note' + (kind ? ' ' + kind : ''), txt(text, 200));
  }
  function renderBreach(o) {
    lists.breach.replaceChildren();
    how.textContent = txt(o.breach_how || '', 240) + (o.breach_link ? ' (' + o.breach_link.replace(/^https:\/\//, '') + ')' : '');
    if (!o.available) { lists.breach.append(empty('Off on this server: it has no token key.')); return; }
    const b = o.breach || {};
    const sub = !o.google_linked ? 'Link Google in Integrations first.'
      : b.last_day ? 'Last notice ' + dayMonth(b.last_day) + '. ' + (b.notices || 0) + ' so far.' : 'No notice so far.';
    lists.breach.append(row('Watch my Gmail for breach notices', sub,
      [toggle('Watch my Gmail for breach notices', !!b.on, (on) => call(BASE + '/breach', { method: 'PUT', body: { on } }))]));
  }
  function render(v) {
    if (!v || typeof v !== 'object') return;
    view = v;
    status.textContent = '';
    renderChores(v);
    renderUpkeep(v);
    renderOutside(v.outside || {});
    renderBreach(v.outside || {});
  }
  return { load, view: () => view };
}

if (H) {
  let tab = null;
  H.register('house', {
    mount(host) { tab = makeTab(host); tab.load(); },
    refresh() { if (tab) tab.load(); },
  });
}
