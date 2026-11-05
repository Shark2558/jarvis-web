// src/jarvis/api/static/console-systems.js -- R4 (docs/plans/r4-vitals-health-people.md D5/D6):
// the Systems panel. A Run button, the last result per integration (ok / degraded / down) and a
// Speak button. No build step; CSP script-src 'self'; ASCII source only; every server string
// reaches the page through textContent (never markup); a field of the wrong type is dropped.
// Transport is the console's api() (cookie + X-Requested-With, or the bearer token; 401 -> gate).
// Speech goes through the shared speaker (window.JarvisVoice.speaker), which asks /v1/voice/speak.
// API: GET /v1/health -> {overall: ok|degraded|down|null, spoken, checked_at, systems:[{key, name,
// status, reason, at}]}; POST /v1/health/run -> the same, after running the probes now.
// The check calls no AI model, so it works with the brain switched off.
// Host: an element with id "systems" if the page has one, else a section beside #integrations.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STATES = Object.freeze({ ok: 'OK', degraded: 'Degraded', down: 'Down' });
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const NEVER = 'No systems check yet. Press Run.';
  const MAX_ROWS = 40;
  const TEXT_MAX = 200;
  const S = { data: null, busy: false, error: '' };
  let card = null, listEl = null, metaEl = null, noteEl = null, headEl = null, runBtn = null, speakBtn = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = TEXT_MAX) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const known = (s) => (typeof s === 'string' && Object.prototype.hasOwnProperty.call(STATES, s) ? s : null);

  /** The server answer, checked field by field. null overall: nothing has run yet. */
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const rows = Array.isArray(d.systems) ? d.systems.slice(0, MAX_ROWS) : [];
    const systems = [];
    rows.forEach((r) => {
      const o = obj(r), status = o ? known(o.status) : null, name = o ? txt(o.name, 60) : '';
      if (status && name) systems.push({ name, status, reason: txt(o.reason, 120) });
    });
    return {
      overall: known(d.overall),
      spoken: txt(d.spoken, 400),
      at: typeof d.checked_at === 'number' && Number.isFinite(d.checked_at) ? d.checked_at : null,
      systems,
    };
  }

  function when(at) {
    if (at === null) return '';
    try { return 'Checked ' + new Date(at * 1000).toLocaleString(); } catch (_) { return ''; }
  }

  function row(r) {
    const li = mk('li', 'sysrow'); li.dataset.state = r.status;
    li.appendChild(mk('b', 'sysname', r.name));
    li.appendChild(mk('span', 'sysstate', STATES[r.status]));
    if (r.reason) li.appendChild(mk('span', 'sysreason', r.reason));
    return li;
  }

  function paint() {
    if (!card) return;
    const d = S.data;
    card.dataset.state = d && d.overall ? d.overall : 'unknown';
    headEl.textContent = d && d.overall ? (d.overall === 'ok' ? 'All systems nominal' : 'Attention: ' + STATES[d.overall]) : 'Not checked yet';
    metaEl.textContent = d ? when(d.at) : '';
    listEl.textContent = '';
    if (d && d.systems.length) d.systems.forEach((r) => listEl.appendChild(row(r)));
    else if (!S.error) listEl.appendChild(mk('li', 'sysrow muted', NEVER));
    noteEl.textContent = S.error;
    runBtn.disabled = S.busy;
    speakBtn.disabled = S.busy || !d || !d.spoken;
  }

  function fail(e) {
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    S.error = e && e.name === 'TypeError' ? OFFLINE : (m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'The check did not complete.');
  }

  async function load() {
    if (!hasApi()) return;
    try { S.data = normal(await api('/v1/health')); S.error = ''; } catch (e) { fail(e); }
    paint();
  }

  async function run() {
    if (S.busy || !hasApi()) return;
    S.busy = true; S.error = ''; paint();
    try {
      S.data = normal(await api('/v1/health/run', { method: 'POST', body: {} }));
      log('info', S.data && S.data.spoken ? S.data.spoken : 'Systems check done');
    } catch (e) { fail(e); }
    S.busy = false; paint();
  }

  function speak() {
    const v = window.JarvisVoice, sp = v && v.speaker;
    if (!S.data || !S.data.spoken || !sp || typeof sp.say !== 'function') { S.error = 'The voice is not ready.'; paint(); return; }
    if (typeof sp.unlock === 'function') sp.unlock();
    sp.say(S.data.spoken);
    if (typeof sp.end === 'function') sp.end();
  }

  function build() {
    if (card) return true;
    const host = $('systems') || ($('integrations') && $('integrations').parentNode);
    if (!host) return false;
    card = mk('section', 'integ systems'); card.id = 'systemsCard'; card.dataset.state = 'unknown';
    card.setAttribute('aria-labelledby', 'systemsHead');
    const head = mk('div', 'ihead');
    head.appendChild(mk('b', '', 'Systems')).id = 'systemsHead';
    headEl = mk('span', 'istate', 'Not checked yet');
    head.appendChild(headEl);
    metaEl = mk('div', 'sysmeta');
    listEl = mk('ul', 'syslist');
    const actions = mk('div', 'iactions');
    runBtn = mk('button', 'btn', 'Run'); runBtn.type = 'button';
    speakBtn = mk('button', 'btn', 'Speak'); speakBtn.type = 'button';
    runBtn.addEventListener('click', run);
    speakBtn.addEventListener('click', speak);
    actions.appendChild(runBtn); actions.appendChild(speakBtn);
    noteEl = mk('div', 'inote'); noteEl.setAttribute('role', 'status');
    [head, metaEl, listEl, actions, noteEl].forEach((n) => card.appendChild(n));
    host.appendChild(card);
    paint();
    return true;
  }

  function start() { if (build()) load(); }
  document.addEventListener('jarvis:ready', start);
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) start();
})();
