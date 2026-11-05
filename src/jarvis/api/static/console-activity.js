// src/jarvis/api/static/console-activity.js -- R1 B (docs/plans/r1-free-tools.md D7/D8): the
// Activity panel's "What JARVIS did" list in plain words, above the existing raw log (now behind
// "Show full log"; the Log verified badge in the panel header stays). Built beside #audit so the
// page markup stays untouched. No build step; CSP script-src 'self'; ASCII source with backslash-u
// escapes only; every server string reaches the page through textContent (never markup); a field of
// the wrong type is dropped, never guessed. Transport is the console's api() (window.JarvisConsole:
// cookie + X-Requested-With, or the bearer token; 401 -> gate), read when a call is made.
// API: GET /v1/activity?day=today|yesterday -> {day, items: [{id, at, words, outcome, channel,
// offline, undo: {id, state: available|restored|expired|gone} | null, undo_note}], verified,
// available}. Undo is the existing POST /v1/deleted/{id}/restore: the button exists only for
// state "available"; every other row shows the server's reason (undo_note) instead.
// Listens: jarvis:reply (a reply that used tools), jarvis:audit (the log was refreshed),
// jarvis:panel (Activity shown). A refresh never runs more than once every 2 s unless forced.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STALE_MS = 2000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const FAILED = 'Couldn\'t undo it. Try again in a moment.';
  const LOAD_FAILED = 'Couldn\'t load what JARVIS did.';
  const NOT_HERE = 'JARVIS doesn\'t record its activity on this server. The full log is below.';
  const OUTCOMES = { done: 'Done', waiting: 'Waiting for you', refused: 'Blocked', failed: 'Failed', declined: 'Declined' };
  const CHANNELS = { telegram: 'Telegram', voice: 'Voice' };
  const STATES = ['available', 'restored', 'expired', 'gone'];
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const S = { day: 'today', data: undefined, error: '', at: 0, loading: false, again: false, busy: new Set(), errs: {}, showLog: false };
  let root = null, listEl = null, logBtn = null, tabs = {};

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 300) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  function failText(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? txt(e.message) : '';
    return m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function clock(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); } catch (_) { return ''; }
  }

  /** GET /v1/activity, checked field by field. */
  function normal(raw) {
    const o = obj(raw);
    if (!o) return null;
    const items = arr(o.items).slice(0, 500).map((r) => {
      const x = obj(r);
      if (!x || typeof x.id !== 'string' || !txt(x.words)) return null;
      const u = obj(x.undo);
      const undo = u && typeof u.id === 'string' && STATES.includes(u.state) ? { id: u.id, state: u.state } : null;
      return { id: x.id.slice(0, 64), at: txt(x.at, 40), words: txt(x.words),
        outcome: Object.prototype.hasOwnProperty.call(OUTCOMES, x.outcome) ? x.outcome : 'done',
        channel: Object.prototype.hasOwnProperty.call(CHANNELS, x.channel) ? x.channel : 'console',
        offline: x.offline === true, undo, note: txt(x.undo_note) };
    }).filter(Boolean);
    return { items, available: o.available !== false };
  }

  // ---- loading ------------------------------------------------------------------------------------
  async function load(force) {
    if (!hasApi() || !root) return;
    if (S.loading) { S.again = true; return; }
    if (!force && S.data !== undefined && Date.now() - S.at < STALE_MS) return;
    S.loading = true; S.again = false;
    const day = S.day;
    try {
      const d = normal(await api('/v1/activity?day=' + day));
      if (day === S.day) { S.data = d || { items: [], available: false }; S.error = ''; }
    } catch (e) {
      if (e && e.status === 404) { S.data = { items: [], available: false }; S.error = ''; }
      else if (!e || e.status !== 401) S.error = failText(e) || LOAD_FAILED;
    } finally { S.loading = false; S.at = Date.now(); render(); }
    if (S.again) load(true);
  }

  // ---- undo: the existing restore route, nothing else ---------------------------------------------
  async function undo(row) {
    const id = row.undo.id;
    if (S.busy.has(id)) return;
    S.busy.add(id); delete S.errs[id]; render();
    try {
      const r = obj(await api('/v1/deleted/' + encodeURIComponent(id) + '/restore', { method: 'POST' })) || {};
      if (r.status !== 'restored' && r.status !== 'already_restored') S.errs[id] = FAILED;
      else emit('jarvis:event', { kind: 'info', text: 'Activity \u00b7 restored from Recently deleted', at: Date.now(), live: true });
    } catch (e) { S.errs[id] = failText(e) || FAILED; }
    finally { S.busy.delete(id); }
    await load(true);
    emit('jarvis:deleted-changed', {});
  }

  // ---- drawing ------------------------------------------------------------------------------------
  function chips(r) {
    const out = [];
    if (CHANNELS[r.channel]) out.push(mk('span', 'achip', CHANNELS[r.channel]));
    if (r.offline) out.push(mk('span', 'achip off', 'Offline'));
    return out;
  }
  function rowEl(r) {
    const li = mk('li', 'arow ' + r.outcome);
    li.dataset.id = r.id;
    const head = mk('div', 'ahead');
    head.append(mk('time', 'atime', clock(r.at)), ...chips(r), mk('span', 'aout ' + r.outcome, OUTCOMES[r.outcome]));
    const words = mk('div', 'awords', r.words);
    const tail = mk('div', 'atail');
    if (r.undo && r.undo.state === 'available') {
      const b = mk('button', 'btn lift abtn', S.busy.has(r.undo.id) ? 'Undoing\u2026' : 'Undo');
      b.type = 'button'; b.dataset.act = 'undo';
      b.setAttribute('aria-label', 'Undo: ' + r.words);
      b.disabled = S.busy.has(r.undo.id);
      b.addEventListener('click', () => undo(r));
      tail.appendChild(b);
    } else if (r.undo && r.undo.state === 'restored') {
      tail.appendChild(mk('span', 'apill', 'Restored'));
    } else if (r.note) {
      tail.appendChild(mk('span', 'anote', r.note));
    }
    const err = r.undo ? S.errs[r.undo.id] : '';
    if (err) { const p = mk('div', 'lerr', err); p.setAttribute('role', 'alert'); tail.appendChild(p); }
    li.append(head, words, tail);
    return li;
  }
  function render() {
    if (!listEl) return;
    listEl.replaceChildren();
    listEl.setAttribute('aria-busy', S.loading ? 'true' : 'false');
    Object.keys(tabs).forEach((k) => tabs[k].setAttribute('aria-pressed', k === S.day ? 'true' : 'false'));
    const logEl = $('audit');
    if (S.error && S.data === undefined) {
      listEl.appendChild(mk('div', 'empty', S.error));
      const retry = mk('button', 'btn lift retry', 'Retry'); retry.type = 'button';
      retry.addEventListener('click', () => { S.error = ''; load(true); });
      listEl.appendChild(retry);
    } else if (S.data === undefined) {
      listEl.appendChild(mk('div', 'empty', 'Loading\u2026'));
    } else if (!S.data.available) {
      listEl.appendChild(mk('div', 'empty', NOT_HERE));
    } else if (!S.data.items.length) {
      listEl.appendChild(mk('div', 'empty', S.day === 'today' ? 'JARVIS hasn\'t done anything today.' : 'Nothing from yesterday.'));
    } else {
      const ul = mk('ul', 'alist');
      S.data.items.forEach((r) => ul.appendChild(rowEl(r)));
      listEl.appendChild(ul);
    }
    const unavailable = !!(S.data && !S.data.available);
    if (logEl) logEl.hidden = !(S.showLog || unavailable);
    if (logBtn) {
      logBtn.hidden = unavailable;
      logBtn.textContent = S.showLog ? 'Hide full log' : 'Show full log';
      logBtn.setAttribute('aria-expanded', S.showLog ? 'true' : 'false');
    }
  }

  function build() {
    const log = $('audit');
    if (!log || !log.parentNode) return false;
    root = mk('section', 'actp'); root.id = 'actPanel';
    root.setAttribute('aria-label', 'What JARVIS did');
    const bar = mk('div', 'atabs'); bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Day');
    [['today', 'Today'], ['yesterday', 'Yesterday']].forEach(([k, label]) => {
      const b = mk('button', 'btn lift atab', label); b.type = 'button'; b.dataset.day = k;
      b.addEventListener('click', () => { if (S.day === k) return; S.day = k; S.data = undefined; S.error = ''; render(); load(true); });
      tabs[k] = b; bar.appendChild(b);
    });
    listEl = mk('div', 'alistbox'); listEl.id = 'actList'; listEl.setAttribute('aria-live', 'polite');
    logBtn = mk('button', 'btn lift alog', 'Show full log'); logBtn.type = 'button'; logBtn.id = 'actLogBtn';
    logBtn.setAttribute('aria-controls', 'audit');
    logBtn.addEventListener('click', () => { S.showLog = !S.showLog; render(); });
    root.append(bar, listEl, logBtn);
    log.parentNode.insertBefore(root, log);
    render();
    return true;
  }

  document.addEventListener('jarvis:reply', (e) => { const d = e.detail || {}; if (d.tools > 0 || d.undo > 0) load(true); });
  document.addEventListener('jarvis:audit', () => load(false));
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'activity' && d.open) load(false); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
  window.JarvisActivity = Object.freeze({ refresh: () => load(true) });
})();
