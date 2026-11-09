// src/jarvis/api/static/console-vitals.js -- the Vitals board (R4 D2-D4): every key, quota, bill and
// allowance with a limit or a renewal, as amber / red chips, plus this month's spend vs the limit.
// No build step; CSP script-src 'self'; no CDN. Every server string reaches the page through
// textContent or a form control's .value, never as markup. Money is rupees only (the server sends
// "₹120 of ₹500 this month"); a field that is missing or of the wrong type shows "—", never a guess.
// The shell is one empty <div id="vitals-board"> inside a panel's .pbody (see INTEGRATION.md).
// Transport: window.JarvisConsole.api (cookie + X-Requested-With, or the bearer token).
// API (src/jarvis/vitals/api.py): GET /v1/vitals; PUT /v1/vitals/keys; DELETE /v1/vitals/keys/{id}.
// Listens: jarvis:ready, jarvis:panel (Vitals shown), jarvis:reply (spend may have changed).
(() => {
  'use strict';
  const root = document.getElementById('vitals-board');
  if (!root) return;
  const KINDS = ['key', 'quota', 'billing', 'storage', 'allowance'];
  const KIND_WORDS = { key: 'Key', quota: 'Quota', billing: 'Bill', storage: 'Storage', allowance: 'Allowance' };
  const STATUS_WORDS = { ok: 'OK', amber: 'Watch', red: 'Act now', unknown: 'Unknown' };
  const STALE_MS = 60 * 1000, NOTE_MS = 5000, TEXT_MAX = 300;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 120) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const own = (map, key) => (typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const detailOf = (e) => {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'Please try again.';
  };
  function when(iso) {
    const d = new Date(typeof iso === 'string' ? iso : NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', year: 'numeric' }).format(d); } catch (_) { return ''; }
  }
  function amount(n, unit) {
    if (n === null) return '—';
    const t = Number.isInteger(n) ? n.toLocaleString('en-IN') : n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
    return unit === '₹' ? '₹' + t : unit ? t + ' ' + unit : t;
  }

  // ---- what the server sends, checked field by field ---------------------------------------------
  function item(v) {
    const o = obj(v);
    const id = o && typeof o.id === 'string' && /^[a-z0-9][a-z0-9_-]{0,39}$/.test(o.id) ? o.id : '';
    if (!id) return null;
    const status = own(STATUS_WORDS, o.status) ? o.status : 'unknown';
    return {
      id, status, label: txt(o.label, 80) || id, kind: own(KIND_WORDS, o.kind) ? o.kind : 'key',
      manual: o.source === 'manual', limit: num(o.limit), used: num(o.used), unit: txt(o.unit, 20),
      percent: num(o.percent), reason: txt(o.reason, 100), note: txt(o.note, TEXT_MAX),
      reset: when(o.reset_at), expires: when(o.expires_at), expiresRaw: txt(o.expires_at, 40), limitRaw: num(o.limit),
    };
  }
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const sp = obj(o.spend);
    return {
      overall: own(STATUS_WORDS, o.overall) ? o.overall : 'ok',
      items: arr(o.items).map(item).filter(Boolean),
      spend: sp ? { text: txt(sp.text, 120), used: num(sp.used_inr), limit: num(sp.limit_inr) } : null,
    };
  }

  // ---- state + rendering -------------------------------------------------------------------------
  const S = { data: null, busy: false, loadedAt: 0, error: '', note: '', noteTimer: 0, editing: null };
  const head = mk('div', 'vt-head');
  const spendEl = mk('div', 'vt-spend');
  const bar = mk('div', 'vt-bar');
  const barFill = mk('div', 'vt-barfill');
  bar.appendChild(barFill);
  const stateEl = mk('div', 'vt-state');
  stateEl.setAttribute('role', 'status');
  const list = mk('div', 'vt-list');
  const formBox = mk('div', 'vt-formbox');
  root.append(head, spendEl, bar, stateEl, list, formBox);

  function chip(status) {
    const c = mk('span', 'vt-chip vt-' + status, STATUS_WORDS[status]);
    return c;
  }
  function usageLine(it) {
    const parts = [];
    if (it.used !== null || it.limit !== null) {
      parts.push(amount(it.used, it.unit) + ' of ' + amount(it.limit, it.unit));
      if (it.percent !== null) parts.push(Math.round(it.percent) + '%');
    }
    return parts.join(' · ');
  }
  function row(it) {
    const r = mk('div', 'vt-row vt-row-' + it.status);
    const top = mk('div', 'vt-top');
    top.append(mk('span', 'vt-label', it.label), mk('span', 'vt-kind', KIND_WORDS[it.kind]), chip(it.status));
    r.appendChild(top);
    const use = usageLine(it);
    if (use) r.appendChild(mk('div', 'vt-use', use));
    const dates = [];
    if (it.reset) dates.push('Resets ' + it.reset);
    if (it.expires) dates.push('Expires ' + it.expires);
    if (dates.length) r.appendChild(mk('div', 'vt-dates', dates.join(' · ')));
    if (it.reason && it.status !== 'ok') r.appendChild(mk('div', 'vt-reason', it.label + ' ' + it.reason + '.'));
    if (it.note) r.appendChild(mk('div', 'vt-note', it.note));
    if (it.manual) r.appendChild(actions(it));
    return r;
  }
  function actions(it) {
    const a = mk('div', 'vt-actions');
    const edit = button('Edit', () => openForm(it));
    const del = button('Stop tracking', () => remove(it));
    a.append(edit, del);
    return a;
  }
  function button(text, onClick) {
    const b = mk('button', 'btn lift vt-btn', text);
    b.type = 'button';
    b.addEventListener('click', () => { if (!S.busy) onClick(); });
    return b;
  }
  function render() {
    const d = S.data;
    head.replaceChildren(mk('h3', 'vt-title', 'Vitals'), d ? chip(d.overall) : mk('span'));
    const addBtn = button('Track a key', () => openForm(null));
    head.appendChild(addBtn);
    spendEl.textContent = d && d.spend && d.spend.text ? 'AI spend: ' + d.spend.text : 'AI spend: —';
    const sp = d && d.spend;
    const pct = sp && sp.used !== null && sp.limit ? Math.min(100, Math.round((sp.used / sp.limit) * 100)) : 0;
    barFill.style.width = pct + '%';
    bar.hidden = !(sp && sp.limit);
    stateEl.textContent = S.error || S.note || '';
    stateEl.className = 'vt-state' + (S.error ? ' vt-err' : '');
    list.replaceChildren();
    if (!d) return;
    if (!d.items.length) list.appendChild(mk('div', 'vt-empty', 'Nothing is tracked yet.'));
    d.items.forEach((it) => list.appendChild(row(it)));
  }
  function flash(text) {
    S.note = text; render();
    clearTimeout(S.noteTimer);
    S.noteTimer = setTimeout(() => { S.note = ''; render(); }, NOTE_MS);
  }

  // ---- add / edit form (control values only; never a key's value) --------------------------------
  function field(labelText, input) {
    const w = mk('label', 'vt-field');
    w.append(mk('span', 'vt-flabel', labelText), input);
    return w;
  }
  function input(type, value, max) {
    const i = document.createElement('input');
    i.type = type; i.value = value || ''; if (max) i.maxLength = max;
    if (type === 'number') { i.min = '0'; i.step = 'any'; }
    return i;
  }
  function openForm(it) {
    S.editing = it ? it.id : null;
    const f = document.createElement('form');
    const id = input('text', it ? it.id : '', 40);
    id.readOnly = !!it;
    const label = input('text', it ? it.label : '', 80);
    const kind = document.createElement('select');
    KINDS.forEach((k) => { const o = document.createElement('option'); o.value = k; o.textContent = KIND_WORDS[k]; kind.appendChild(o); });
    kind.value = it ? it.kind : 'key';
    const limit = input('number', it && it.limit !== null ? String(it.limit) : '');
    const used = input('number', it && it.used !== null ? String(it.used) : '');
    const unit = input('text', it ? it.unit : '', 20);
    const expires = input('date', it && it.expiresRaw ? it.expiresRaw.slice(0, 10) : '');
    const note = input('text', it ? it.note : '', TEXT_MAX);
    const err = mk('div', 'vt-err');
    const hint = mk('div', 'vt-hint', 'Type a name, limit and expiry. Never paste the key itself.');
    const save = mk('button', 'btn lift vt-btn', 'Save'); save.type = 'submit';
    const cancel = button('Cancel', () => closeForm());
    f.append(hint, field('Id (a-z, 0-9, - _)', id), field('Name', label), field('Kind', kind), field('Limit', limit),
      field('Used so far', used), field('Unit', unit), field('Expires', expires), field('Note', note), err, save, cancel);
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { id: id.value.trim(), label: label.value.trim(), kind: kind.value, unit: unit.value.trim(), note: note.value.trim() };
      if (limit.value !== '') body.limit = Number(limit.value);
      if (used.value !== '') body.used = Number(used.value);
      if (expires.value) body.expires_at = new Date(expires.value + 'T00:00:00Z').toISOString();
      submit(body, err);
    });
    formBox.replaceChildren(f);
    label.focus();
  }
  function closeForm() { S.editing = null; formBox.replaceChildren(); }
  async function submit(body, err) {
    if (!hasApi() || S.busy) return;
    S.busy = true; err.textContent = '';
    try {
      await api('/v1/vitals/keys', { method: 'PUT', body });
      closeForm(); S.busy = false; await load(true); flash('Saved.');
    } catch (e) { err.textContent = detailOf(e); S.busy = false; }
  }
  async function remove(it) {
    if (!hasApi() || S.busy) return;
    S.busy = true;
    try {
      await api('/v1/vitals/keys/' + encodeURIComponent(it.id), { method: 'DELETE' });
      S.busy = false; await load(true); flash('Stopped tracking ' + it.label + '. You can add it again any time.');
    } catch (e) { S.busy = false; S.error = detailOf(e); render(); }
  }

  // ---- loading -----------------------------------------------------------------------------------
  async function load(force) {
    if (!hasApi() || S.busy) return;
    if (!force && S.data && Date.now() - S.loadedAt < STALE_MS) return;
    S.busy = true;
    try {
      const d = normal(await api('/v1/vitals'));
      if (d) { S.data = d; S.error = ''; S.loadedAt = Date.now(); } else { S.error = 'Vitals sent something unexpected.'; }
    } catch (e) { S.error = detailOf(e); }
    S.busy = false; render();
  }
  const shown = () => load(false);
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'vitals' && d.open) load(false); });
  document.addEventListener('jarvis:ready', shown);
  document.addEventListener('jarvis:reply', () => { S.loadedAt = 0; });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) shown();
  render();
})();
