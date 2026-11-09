// src/jarvis/api/static/console-systems.js -- R4 (docs/plans/r4-vitals-health-people.md D5/D6), tidied
// in R5.1 (docs/plans/r5-1-observations.md D6, audit #7 #10 #22): the Systems card in Integrations.
// No build step; CSP script-src 'self'; ASCII source only; every server string reaches the page
// through textContent (never markup); a field of the wrong type is dropped.
// The card: a head with the overall state in a word, "Checked 10 Nov, 13:05", one Activity-style
// row per system (dot + name with the reason under it + the status word: never colour alone), a note
// for errors (.bnote, hidden when empty) and two actions. Run opens the systems-check pop-up
// (console-systems-modal.js, window.JarvisSystemsCheck); without it, Run checks here as in R4.
// Speak says the last briefing through the shared speaker (window.JarvisVoice.speaker).
// API: GET /v1/health -> {overall: ok|degraded|down|null, spoken, checked_at, systems:[{key, name,
// status, reason, at}], briefing?{spoken}}; POST /v1/health/run -> the same, after running the probes.
// Listens: jarvis:ready (load), jarvis:health {data} (the pop-up's finished check: repaint).
// The check calls no AI model, so it works with the brain switched off.
// Host: an element with id "systems" if the page has one, else a section beside #integrations.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STATES = Object.freeze({ ok: 'OK', degraded: 'Degraded', down: 'Down' });
  const HEAD = Object.freeze({ ok: 'Nominal', degraded: 'Degraded', down: 'Down' });
  const DOT = Object.freeze({ ok: 'ok', degraded: 'warn', down: 'bad' });
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const NEVER = 'No systems check yet. Press Run check.';
  const MAX_ROWS = 40;
  const TEXT_MAX = 200;
  const S = { data: null, busy: false, error: '' };
  let card = null, listEl = null, metaEl = null, noteEl = null, headEl = null, runBtn = null, speakBtn = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = TEXT_MAX) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const known = (s) => (typeof s === 'string' && Object.prototype.hasOwnProperty.call(STATES, s) ? s : null);
  const modal = () => (window.JarvisSystemsCheck && typeof window.JarvisSystemsCheck.open === 'function' ? window.JarvisSystemsCheck : null);

  /** The server answer, checked field by field. null overall: nothing has run yet. */
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const rows = Array.isArray(d.systems) ? d.systems.slice(0, MAX_ROWS) : [];
    const systems = [];
    rows.forEach((r) => {
      const o = obj(r), status = o ? known(o.status) : null, name = o ? txt(o.name, 60) : '';
      if (status && name) systems.push({ key: txt(o.key, 40), name, status, reason: txt(o.reason, 120) });
    });
    const b = obj(d.briefing);
    return {
      overall: known(d.overall),
      spoken: (b && txt(b.spoken, 1200)) || txt(d.spoken, 400),
      at: typeof d.checked_at === 'number' && Number.isFinite(d.checked_at) ? d.checked_at : null,
      systems,
    };
  }

  /** "Checked 10 Nov, 13:05" in the owner's locale, never the browser's long default. */
  function when(at) {
    if (at === null) return '';
    try {
      const d = new Date(at * 1000);
      const day = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(d);
      const time = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(d);
      return `Checked ${day}, ${time}`;
    } catch (_) { return ''; }
  }

  function row(r) {
    const li = mk('li', 'event'); li.dataset.state = r.status; if (r.key) li.dataset.key = r.key;
    const dot = mk('span', 'dot ' + DOT[r.status]); dot.setAttribute('aria-hidden', 'true');
    const what = mk('span', 'what', cap(r.name));
    if (r.reason) what.appendChild(mk('small', '', r.reason));
    li.append(dot, what, mk('span', 'v up ' + DOT[r.status], STATES[r.status]));
    return li;
  }

  function paint() {
    if (!card) return;
    const d = S.data;
    card.dataset.state = d && d.overall ? d.overall : 'unknown';
    headEl.textContent = d && d.overall ? HEAD[d.overall] : 'Not checked';
    metaEl.textContent = d ? when(d.at) : '';
    metaEl.hidden = !metaEl.textContent;
    listEl.textContent = '';
    if (d && d.systems.length) d.systems.forEach((r) => listEl.appendChild(row(r)));
    else if (!S.error) listEl.appendChild(mk('li', 'empty', NEVER));
    noteEl.textContent = S.error;
    noteEl.className = S.error ? 'bnote bad' : 'bnote';
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

  /** Run: the pop-up when it is here (it streams each system as it is checked), else a check here. */
  async function run() {
    const m = modal();
    if (m) { S.error = ''; paint(); m.open({ via: 'button', opener: runBtn }); return; }
    if (S.busy || !hasApi()) return;
    S.busy = true; S.error = ''; paint();
    try {
      S.data = normal(await api('/v1/health/run', { method: 'POST', body: {} }));
      log('info', 'Systems check done');
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
    headEl = mk('span', 'istate', 'Not checked');
    head.appendChild(headEl);
    metaEl = mk('div', 'bmade');
    listEl = mk('ul', 'syslist'); listEl.setAttribute('aria-label', 'Systems checked');
    noteEl = mk('div', 'bnote'); noteEl.setAttribute('role', 'status');
    const actions = mk('div', 'actions');
    runBtn = mk('button', 'btn primary lift', 'Run check'); runBtn.type = 'button';
    speakBtn = mk('button', 'btn lift', 'Speak'); speakBtn.type = 'button';
    runBtn.addEventListener('click', run);
    speakBtn.addEventListener('click', speak);
    actions.appendChild(runBtn); actions.appendChild(speakBtn);
    [head, metaEl, listEl, noteEl, actions].forEach((n) => card.appendChild(n));
    host.appendChild(card);
    paint();
    return true;
  }

  function start() { if (build()) load(); }
  document.addEventListener('jarvis:ready', start);
  document.addEventListener('jarvis:health', (e) => {
    const d = normal(e && e.detail && e.detail.data);
    if (!d) return;
    S.data = d; S.error = '';
    if (build()) paint();
  });
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) start();
})();
