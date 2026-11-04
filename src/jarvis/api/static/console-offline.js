// src/jarvis/api/static/console-offline.js -- R1 C (docs/plans/r1-free-tools.md D10-D12):
// Integrations -> Offline mode. When Claude can't be reached JARVIS asks a small model on the owner's
// laptop (Ollama behind a key gate, published by Tailscale Funnel). Off until set up. Built beside
// #integrations like console-drive.js, so the page markup stays untouched. No build step; CSP
// script-src 'self'; ASCII source with backslash-u escapes only; every server string reaches the page
// through textContent or an input's value (never markup); a field of the wrong type is dropped.
// Transport is the console's api() (cookie + X-Requested-With, or the bearer token; 401 -> gate).
// API: GET /v1/offline -> {available, configured, enabled, host, model, state off|standby|active|
// unreachable, last_ok_at, last_used_at}; PUT {url?, key?, model?, enabled?} -> the same or
// {error, detail}; DELETE -> the same; POST /v1/offline/test -> {ok, models, detail}. The key and the
// whole address are never sent back: only the host name. The key field is a password input that is
// emptied after every save.
// Also: window.JarvisOffline.mark(row, resp) adds the reply marker "Offline mode - answered by your
// laptop (model)" to a reply row when resp.offline is true (console.js calls it); the Vitals line
// #vOffline (if the page has one) reads "Offline mode: standby" etc. and document gets a
// 'jarvis:offline' event {state}.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STATES = { off: 'Off', standby: 'Standby', active: 'Active', unreachable: 'Laptop not answering' };
  const HOST = /^[a-z0-9-]{1,63}\.[a-z0-9-]{1,63}\.ts\.net$/;
  const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$/;
  const STALE_MS = 15 * 1000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const STEPS = [
    'Install Ollama on your laptop and pull a model (for example: ollama pull qwen2.5:7b).',
    'Install Tailscale, sign in and allow Funnel when it asks.',
    'Run deploy/local-brain/start-unix.sh (Windows: start-windows.ps1). It prints an address and a key.',
    'Paste the address, the key and the model name below, press Save, then Test.',
  ];
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: false, editing: false, test: null };
  let card = null, stateEl = null, bodyEl = null, noteEl = null, vitalsEl = null;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : v); // console-text.js
  const txt = (v, max = 200) => (typeof v === 'string' ? String(strip(v)).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  const when = (iso) => {
    const t = typeof iso === 'string' ? Date.parse(iso) : NaN;
    if (!Number.isFinite(t)) return '';
    try { return new Date(t).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); } catch (_) { return ''; }
  };

  /** GET /v1/offline, checked field by field; anything odd is dropped. */
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const state = Object.prototype.hasOwnProperty.call(STATES, d.state) ? d.state : 'off';
    return {
      available: d.available === true,
      configured: d.configured === true,
      enabled: d.enabled === true,
      host: typeof d.host === 'string' && HOST.test(d.host) ? d.host : '',
      model: typeof d.model === 'string' && MODEL.test(d.model) ? d.model : '',
      state,
      lastOk: when(d.last_ok_at),
      lastUsed: when(d.last_used_at),
    };
  }

  // ---- reply marker and Vitals -----------------------------------------------------------------
  /** Add the marker to a reply row (a DOM element) when the server says the laptop answered. */
  function mark(row, resp) {
    const r = obj(resp);
    if (!row || !(row instanceof Element) || !r || r.offline !== true) return false;
    if (row.querySelector('.offmark')) return true;
    const model = typeof r.model === 'string' && MODEL.test(r.model) ? ' (' + r.model + ')' : '';
    const m = mk('div', 'offmark', 'Offline mode \u2014 answered by your laptop' + model);
    m.setAttribute('role', 'note');
    row.appendChild(m);
    if (S.data) { S.data.state = 'active'; vitals(); }
    return true;
  }
  function vitals() {
    if (!vitalsEl) vitalsEl = $('vOffline');
    const st = S.data && S.data.available ? S.data.state : 'off';
    const label = STATES[st] || 'Off';
    if (vitalsEl) {
      vitalsEl.textContent = 'Offline mode: ' + label.toLowerCase();
      vitalsEl.dataset.state = st;
      vitalsEl.hidden = !(S.data && S.data.available && S.data.configured);
    }
    emit('jarvis:offline', { state: st });
  }

  // ---- the card -------------------------------------------------------------------------------
  function build() {
    if (card) return true;
    const host = $('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ offline'); card.id = 'offlineSet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'offlineHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Offline mode'); title.id = 'offlineHead';
    stateEl = mk('span', 'istate', 'Checking\u2026');
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'offlineNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'offlineBody';
    card.append(head, bodyEl, noteEl);
    host.parentNode.insertBefore(card, host.nextSibling);
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }
  function steps() {
    const ol = mk('ol', 'osteps'); ol.id = 'offlineSteps';
    STEPS.forEach((s) => ol.appendChild(mk('li', '', s)));
    return ol;
  }
  function field(id, label, attrs) {
    const wrap = mk('div', 'ofield');
    const l = mk('label', 'olbl', label); l.htmlFor = id;
    const i = mk('input', 'oinput'); i.id = id; i.spellcheck = false;
    i.setAttribute('autocomplete', 'off'); i.setAttribute('autocapitalize', 'off');
    Object.keys(attrs).forEach((k) => i.setAttribute(k, attrs[k]));
    wrap.append(l, i);
    return wrap;
  }
  function form(d) {
    const f = mk('form', 'oform'); f.id = 'offlineForm'; f.noValidate = true;
    const url = field('offlineUrl', 'Address', { type: 'text', inputmode: 'url', placeholder: 'https://my-laptop.tail1234.ts.net', maxlength: '300' });
    const key = field('offlineKey', 'Key', { type: 'password', placeholder: d && d.configured ? 'Paste again only to change it' : 'The key the start script printed', maxlength: '300' });
    const model = field('offlineModel', 'Model', { type: 'text', placeholder: 'qwen2.5:7b', maxlength: '100' });
    if (d && d.host) url.querySelector('input').placeholder = 'https://' + d.host;
    if (d && d.model) model.querySelector('input').value = d.model;
    const row = mk('div', 'orow');
    const save = mk('button', 'btn bact primary', 'Save'); save.type = 'submit'; save.id = 'offlineSave';
    row.appendChild(save);
    if (d && d.configured) {
      const cancel = mk('button', 'btn bact', 'Cancel'); cancel.type = 'button'; cancel.id = 'offlineCancel';
      cancel.addEventListener('click', () => { S.editing = false; render(); });
      row.appendChild(cancel);
    }
    f.append(url, key, model, row);
    f.addEventListener('submit', (e) => { e.preventDefault(); save.disabled = true; submit(f).finally(() => { save.disabled = false; }); });
    return f;
  }
  function toggle(d) {
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = 'offlineSwitch';
    b.setAttribute('aria-pressed', String(d.enabled));
    b.setAttribute('aria-label', 'Use my laptop when Claude can\'t be reached');
    const track = mk('span', 'track'); track.appendChild(mk('i', ''));
    b.append(track, mk('span', 'st', d.enabled ? 'On' : 'Off'));
    if (S.busy) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') change({ enabled: !d.enabled }, d.enabled ? 'Offline mode is off.' : 'Offline mode is on. If Claude can\'t be reached, your laptop answers.'); });
    return b;
  }
  function testResult() {
    const t = S.test;
    if (!t) return null;
    const p = mk('p', t.ok ? 'otest ok' : 'otest warn', t.detail); p.id = 'offlineTest'; p.setAttribute('role', 'status');
    return p;
  }

  function render() {
    if (!build()) return;
    const d = S.data;
    bodyEl.textContent = '';
    if (S.error) {
      card.dataset.state = 'error'; stateEl.textContent = 'Unknown';
      bodyEl.appendChild(mk('p', 'warn', 'Couldn\'t check Offline mode. ' + S.error));
      const r = mk('button', 'btn bact', 'Retry'); r.type = 'button'; r.id = 'offlineRetry';
      r.addEventListener('click', () => { r.disabled = true; load(true); });
      bodyEl.appendChild(r);
      return;
    }
    if (d === undefined || d === null) { card.dataset.state = 'loading'; stateEl.textContent = 'Checking\u2026'; bodyEl.appendChild(mk('p', '', 'Checking Offline mode\u2026')); return; }
    card.dataset.state = d.state;
    stateEl.textContent = d.available ? STATES[d.state] : 'Not available';
    bodyEl.appendChild(mk('p', '', 'If Claude can\'t be reached, JARVIS can ask a small model on your own laptop instead. It stays off until you set it up. Your words then go only to your laptop, never to a new service.'));
    if (!d.available) {
      bodyEl.appendChild(mk('p', 'warn', 'This server has no token key, so Offline mode can\'t be switched on here.'));
      return;
    }
    if (!d.configured || S.editing) {
      if (!d.configured) bodyEl.appendChild(steps());
      bodyEl.appendChild(form(d));
      return;
    }
    const who = mk('p', 'who');
    who.append('Laptop: ', mk('b', '', d.host || '(unknown)'), ' \u00b7 model ', mk('b', '', d.model || '(unknown)'));
    bodyEl.appendChild(who);
    const status = mk('p', 'fine ostatus');
    status.id = 'offlineStatus';
    status.textContent = d.state === 'off' ? 'Switched off.'
      : d.state === 'active' ? 'Claude can\'t be reached, so your laptop is answering. Every change asks first.'
        : d.state === 'unreachable' ? 'Your laptop did not answer last time. Is it awake, with Ollama and the gate running?'
          : 'On standby: your laptop answers only if Claude can\'t be reached.';
    if (d.lastOk) status.textContent += ' Last answered: ' + d.lastOk + '.';
    bodyEl.appendChild(status);
    const row = mk('div', 'orow');
    row.appendChild(toggle(d));
    const test = mk('button', 'btn bact', S.busy === 'test' ? 'Testing\u2026' : 'Test'); test.type = 'button'; test.id = 'offlineTestBtn';
    if (S.busy) test.disabled = true;
    test.addEventListener('click', runTest);
    const edit = mk('button', 'btn bact', 'Change'); edit.type = 'button'; edit.id = 'offlineEdit';
    edit.addEventListener('click', () => { S.editing = true; S.test = null; render(); const u = $('offlineUrl'); if (u) u.focus(); });
    const rm = mk('button', 'btn bact', 'Remove'); rm.type = 'button'; rm.id = 'offlineRemove';
    rm.addEventListener('click', () => askRemove(rm));
    row.append(test, edit, rm);
    bodyEl.appendChild(row);
    const t = testResult();
    if (t) bodyEl.appendChild(t);
  }

  // ---- actions --------------------------------------------------------------------------------
  function adopt(raw) {
    const n = normal(raw);
    if (n) { S.data = n; S.loadedAt = Date.now(); }
    vitals();
  }
  async function submit(f) {
    const body = {};
    const url = f.querySelector('#offlineUrl').value.trim();
    const key = f.querySelector('#offlineKey').value.trim();
    const model = f.querySelector('#offlineModel').value.trim();
    if (url) body.url = url;
    if (key) body.key = key;
    if (model) body.model = model;
    f.querySelector('#offlineKey').value = ''; // never kept in the page
    if (!Object.keys(body).length) { note('bad', 'Nothing to save yet.'); return; }
    await change(body, 'Saved. Press Test, then switch it On.', true);
  }
  async function change(body, okText, leaveEdit) {
    if (!hasApi() || S.busy) return;
    S.busy = true; render();
    try {
      adopt(await api('/v1/offline', { method: 'PUT', body }));
      if (leaveEdit) S.editing = false;
      S.test = null;
      note('ok', okText);
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t save that. Please try again.');
    } finally {
      S.busy = false; render();
    }
  }
  async function runTest() {
    if (!hasApi() || S.busy) return;
    S.busy = 'test'; render();
    try {
      const r = obj(await api('/v1/offline/test', { method: 'POST' })) || {};
      S.test = { ok: r.ok === true, detail: txt(r.detail, 300) || (r.ok === true ? 'Your laptop answered.' : 'Your laptop did not answer.') };
      note('', '');
      await load(true);
    } catch (e) {
      if (e && e.status === 401) return;
      S.test = { ok: false, detail: detailOf(e) || 'The test could not run. Please try again.' };
    } finally {
      S.busy = false; render();
    }
  }

  // ---- confirm to remove: a native modal made on demand (Esc and Not now cancel) --------------
  function askRemove(trigger) {
    if (typeof HTMLDialogElement === 'undefined') { note('bad', 'This browser can\'t show the confirmation, so nothing was removed.'); return; }
    const dlg = mk('dialog', 'odialog'); dlg.id = 'offlineDialog'; dlg.setAttribute('aria-labelledby', 'offlineDialogTitle');
    const h = mk('h3', '', 'Remove the laptop?'); h.id = 'offlineDialogTitle';
    const no = mk('button', 'btn bact', 'Not now'); no.type = 'button'; no.id = 'offlineDialogNo';
    const yes = mk('button', 'btn bact danger', 'Remove'); yes.type = 'button'; yes.id = 'offlineDialogYes';
    const row = mk('div', 'orow'); row.append(no, yes);
    dlg.append(h, mk('p', '', 'JARVIS forgets the address and the key. Offline mode goes off. You can set it up again any time.'), row);
    document.body.appendChild(dlg);
    const done = (go) => { if (dlg.open) dlg.close(); dlg.remove(); if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true }); if (go) remove(); };
    yes.addEventListener('click', () => done(true));
    no.addEventListener('click', () => done(false));
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); done(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const a = no, z = yes;
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
    dlg.showModal();
    no.focus(); // the safe choice is where Enter lands
  }
  async function remove() {
    if (!hasApi() || S.busy) return;
    S.busy = true; render();
    try {
      adopt(await api('/v1/offline', { method: 'DELETE' }));
      S.test = null; S.editing = false;
      note('ok', 'Removed. Offline mode is off.');
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t remove it. Please try again.');
    } finally {
      S.busy = false; render();
    }
  }

  function load(force) {
    if (!hasApi()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try {
        const n = normal(await api('/v1/offline'));
        if (n) { S.data = n; S.error = ''; }
      } catch (e) {
        if (e && e.status === 401) return;
        S.error = detailOf(e) || 'Please try again.';
      } finally {
        S.loadedAt = Date.now(); S.loading = null; vitals(); build() && render();
      }
    })();
    return S.loading;
  }

  const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  // after a reply the laptop answered, the status (and the Vitals line) is stale: ask again
  document.addEventListener('jarvis:reply', () => { if (S.data && S.data.configured) load(true); });
  document.addEventListener('jarvis:ready', () => { load(false); });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) load(false); // deferred script after jarvis:ready

  window.JarvisOffline = Object.freeze({ mark, refresh: () => load(true), normal, vitals: () => (S.data ? STATES[S.data.state] : ''), open: integOpen });
})();
