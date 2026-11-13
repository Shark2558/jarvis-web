// src/jarvis/api/static/console-helpers-watch.js -- R7 Part D (docs/plans/r7-mobile.md D17, D18): Helpers -> Watch,
// the fifth sub-tab (not an R11 part): today's steps and heart rate, last night, the week, "Last synced", and a
// sleep time he types ("typed by you"). Every sentence is fixed here or JARVIS's own words from the server; the
// numbers are the watch's or the phone's estimates, never a diagnosis. Loaded by console-helpers.js (an ES module);
// window.JarvisHelpers builders and existing classes only; textContent only; ASCII source.
// It asks the server NOTHING before sign-in (BRIEF-COMMON.md): the tab may mount at page load (the remembered tab),
// so it draws its frame and loads only once the console says it is signed in (jarvis:ready / JarvisConsole.ready()).
// API: GET /v1/watch -> {part, ready, enabled, sealed, note?, last_synced, kinds, today: {steps: {count, source},
//   heart: {min, avg, max, source}} | null, last_night: {minutes, start, end, source, stages} | null,
//   week: {nights, avg_minutes, bed_from, bed_to} | null}; POST /v1/watch/sleep {start, end} -> {message, night}.
const H = window.JarvisHelpers;
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const FROM = { watch: 'from your watch', phone: 'from your phone', typed: 'typed by you' };
const NOTE = 'Daily sums from your watch or phone through Health Connect, kept encrypted. Estimates, never a diagnosis.';
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const UI = { host: null, body: null, note: null, busy: false, loaded: false, loading: null };

const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
const int = (v, lo, hi) => (Number.isInteger(v) && v >= lo && v <= hi ? v : null);
const clock = (v) => (typeof v === 'string' && HHMM.test(v) ? v : '');
const from = (v) => FROM[v] || '';
function hm(minutes) {
  const m = int(minutes, 0, 1440);
  if (m === null) return '';
  const h = Math.floor(m / 60), r = m % 60;
  if (h && r) return h + ' h ' + r + ' min';
  return h ? h + ' h' : r + ' min';
}
function synced(iso) {
  const at = typeof iso === 'string' ? new Date(iso) : null;
  if (!at || isNaN(at)) return 'Your phone hasn\u2019t synced yet. Link the JARVIS app in Integrations \u2192 Phone app and open it once.';
  return 'Last synced: ' + at.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ', '
    + at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + '.';
}

function todayRows(t) {
  const out = [];
  const steps = t && t.steps ? int(t.steps.count, 0, 200000) : null;
  if (steps !== null) out.push(H.row(steps.toLocaleString() + ' steps', 'Today so far, ' + from(t.steps.source)));
  const h = t && t.heart;
  if (h && int(h.min, 20, 250) !== null && int(h.avg, 20, 250) !== null && int(h.max, 20, 250) !== null) {
    out.push(H.row('Heart rate ' + h.min + ' lowest, ' + h.avg + ' average, ' + h.max + ' highest', 'Today, ' + from(h.source)));
  }
  return out.length ? out : [H.empty('Nothing from your watch or phone for today yet.')];
}
function nightRows(n) {
  if (!n || !hm(n.minutes) || !clock(n.start) || !clock(n.end)) {
    return [H.empty('No sleep for last night yet. Type it below, or let the phone app send it.')];
  }
  const rows = [H.row(hm(n.minutes) + ', ' + n.start + ' to ' + n.end, 'Last night, ' + from(n.source))];
  const st = n.stages;
  if (st && typeof st === 'object') {
    const parts = [['awake', 'awake'], ['light', 'light'], ['deep', 'deep'], ['rem', 'REM']]
      .map(([k, w]) => (hm(st[k]) ? hm(st[k]) + ' ' + w : '')).filter(Boolean);
    if (parts.length === 4) rows.push(H.row('Stages', parts.join(', ')));
  }
  return rows;
}
function weekRows(w) {
  if (!w || !hm(w.avg_minutes) || !int(w.nights, 1, 7)) return [H.empty('No nights recorded in the last 7 days.')];
  const beds = clock(w.bed_from) === clock(w.bed_to) ? 'Bedtime ' + clock(w.bed_from) : 'Bedtimes ' + clock(w.bed_from) + ' to ' + clock(w.bed_to);
  return [H.row(hm(w.avg_minutes) + ' on average', (w.nights === 1 ? '1 night' : w.nights + ' nights') + ' recorded. ' + beds + '.')];
}

function section(title, rows) {
  const s = H.section(title);
  s.append(...rows);
  return s;
}
function typedForm() {
  const s = H.section('Type last night\u2019s sleep');
  const grid = H.mk('div', 'hp-grid wt-grid');
  const pair = [['wtStart', 'Went to sleep', '23:30'], ['wtEnd', 'Woke up', '06:30']].map(([id, label, value]) => {
    const l = H.mk('label', 'hp-field');
    l.htmlFor = id;
    l.append(H.mk('span', 'snote', label));
    const i = H.mk('input', 'minput wt-time');
    i.type = 'time'; i.id = id; i.value = value; i.step = 60;
    l.append(i);
    grid.append(l);
    return i;
  });
  const save = H.mk('button', 'btn primary wt-save', 'Save');
  save.type = 'button';
  save.addEventListener('click', () => typed(pair[0].value, pair[1].value, save));
  const acts = H.mk('div', 'sacts');
  acts.append(save);
  s.append(H.mk('p', 'sfine', 'Marked \u201ctyped by you\u201d. You can also say \u201cI slept 11:30 to 6\u201d.'), grid, acts);
  return s;
}

function draw(v) {
  if (!UI.body) return;
  const d = v && typeof v === 'object' ? v : {};
  const parts = [];
  if (d.enabled === false) parts.push(H.empty('Watch data is switched off on this server.'));
  else if (d.sealed === false) parts.push(H.empty(H.txt(d.note, 200) || 'Watch data is off: JARVIS has no token key to keep it sealed.'));
  else {
    parts.push(H.mk('p', 'sfine wt-sync', synced(d.last_synced)));
    parts.push(section('Today', todayRows(d.today)), section('Last night', nightRows(d.last_night)));
    parts.push(section('This week', weekRows(d.week)), typedForm());
  }
  parts.push(H.mk('p', 'sfine', NOTE));
  UI.body.replaceChildren(...parts);
}

async function load() {
  if (!UI.body || !signedIn()) return null;
  if (UI.loading) return UI.loading;
  UI.loading = (async () => {
    try {
      draw(await H.api('/v1/watch'));
      UI.loaded = true;
    } catch (e) {
      if (e && e.status === 401) return;
      H.note(UI.note, 'bad', e && e.name === 'TypeError' ? OFFLINE : 'Couldn\u2019t load your watch data.');
    } finally { UI.loading = null; }
  })();
  return UI.loading;
}

async function typed(start, end, btn) {
  if (UI.busy || !signedIn()) return;
  if (!HHMM.test(start) || !HHMM.test(end)) { H.note(UI.note, 'bad', 'Please give both times, like 23:30 and 06:30.'); return; }
  UI.busy = true; btn.disabled = true;
  try {
    const r = await H.api('/v1/watch/sleep', { method: 'POST', body: { start, end } });
    H.note(UI.note, 'ok', H.txt(r && r.message, 200) || 'Noted.');
    await load();
  } catch (e) {
    H.note(UI.note, 'bad', e && e.name === 'TypeError' ? OFFLINE : H.txt(e && e.message, 200) || 'That didn\u2019t work.');
  } finally { UI.busy = false; btn.disabled = false; }
}

if (H) {
  H.register('watch', {
    mount(host) {
      UI.host = host;
      UI.note = H.mk('p', 'sfine hp-note');
      UI.note.setAttribute('role', 'status');
      UI.body = H.mk('div', 'hp-watch');
      UI.body.append(H.empty(signedIn() ? 'Loading your watch and sleep\u2026' : 'Sign in to see your watch and sleep.'));
      host.append(UI.body, UI.note);
      load();
    },
    refresh() { load(); },
  });
  document.addEventListener('jarvis:ready', () => { if (UI.body) load(); });
}
