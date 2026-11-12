// src/jarvis/api/static/console-vitals.js -- the Vitals board (R4 D2-D4; R5.1 D1, D2). Everything
// JARVIS watches by itself (its keys and connections, allowances and quotas, bills), grouped, each with
// a status chip in WORDS (never colour alone), a thin usage bar where there is a limit, its dates and,
// when it needs attention, the reason, what stops and what to do. The owner's own items sit behind a
// closed "Track something JARVIS can't see" disclosure; their id is made from the name. The AI spend
// figures stay in the "This month" block above (never repeated here). Styles: console-vitals.css.
// No build step; CSP script-src 'self'; ASCII source; every server string reaches the page through
// textContent or a control's .value. Rupees only. A key's VALUE is never asked for (the server refuses
// one). Transport: window.JarvisConsole.api. API (src/jarvis/vitals/api.py): GET /v1/vitals;
// PUT /v1/vitals/keys; DELETE /v1/vitals/keys/{id}. Listens: jarvis:ready, jarvis:panel, jarvis:reply.
// R6.1 D4: the same GET carries `version` and `build_date`; they fill the read-only #vAbout line
// ("About JARVIS \u00b7 v6.1.0 \u00b7 built 11 Nov 2026") at the foot of the panel, in its .sfine text.
// R11.1 D19: an item the server is reading right now (`checking`) says "Checking..." on its chip, and
// the board is read again by itself every few seconds until no item is checking, for at most FOLLOW_FOR_MS
// (code review M4). Past that the chip gives up "Checking..." and the row says GitHub didn't answer and to
// press Refresh; a press of Refresh follows from the start again.
(() => {
  'use strict';
  const root = document.getElementById('vitals-board');
  if (!root) return;
  const KINDS = ['key', 'quota', 'billing', 'storage', 'allowance'];
  const KIND_WORDS = { key: 'Key or login', quota: 'Quota', billing: 'Bill or renewal', storage: 'Storage', allowance: 'Free allowance' };
  const KIND_GROUP = { key: 'keys', quota: 'allowances', allowance: 'allowances', billing: 'bills', storage: 'bills' };
  const STATUS_WORDS = { ok: 'OK', amber: 'Watch', red: 'Act now', unknown: 'Unknown' };
  const GROUPS = [['keys', 'Keys & connections'], ['allowances', 'Allowances & quotas'], ['bills', 'Bills']];
  const ORDER = { red: 0, amber: 1, unknown: 2, ok: 3 };
  const SPEND_ID = 'ai_spend', ID_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/;
  const STALE_MS = 60 * 1000, NOTE_MS = 5000, TEXT_MAX = 300, SLUG_MAX = 34, FOLLOW_MS = 3000, FOLLOW_FOR_MS = 45 * 1000;
  const SLOW = 'GitHub didn\'t answer; press Refresh.';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const MANUAL_NOTE = 'The items you track yourself can\'t be read just now. Try again in a minute.';
  const HINT = 'Type a name, a limit and a date. Never paste a key itself: JARVIS refuses it.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const NS = (document.querySelector('svg.pico') || {}).namespaceURI; // the SVG namespace, from the page
  const VER_RE = /^v\d{1,3}\.\d{1,3}\.\d{1,4}$/, DAY_RE = /^\d{1,2} [A-Z][a-z]{2} \d{4}$/;
  const aboutEl = document.getElementById('vAbout');

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
  function fmt(iso, opts) {
    const d = new Date(typeof iso === 'string' || typeof iso === 'number' ? iso : NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], opts).format(d); } catch (_) { return ''; }
  }
  const when = (iso) => fmt(iso, { day: 'numeric', month: 'short', year: 'numeric' });
  const figure = (n) => (Number.isInteger(n) ? n.toLocaleString('en-IN') : n.toLocaleString('en-IN', { maximumFractionDigits: 2 }));
  const amount = (n, unit) => (unit === '\u20b9' ? '\u20b9' + figure(n) : unit ? figure(n) + ' ' + unit : figure(n));
  function svg(cls, d) {
    if (!NS) return null;
    const s = document.createElementNS(NS, 'svg');
    [['class', cls], ['viewBox', '0 0 16 16'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.6'],
      ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true']].forEach(([k, v]) => s.setAttribute(k, v));
    const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); s.appendChild(p);
    return s;
  }
  function button(text, cls, onClick) {
    const b = mk('button', cls, text);
    b.type = 'button';
    b.addEventListener('click', () => { if (!S.busy) onClick(b); });
    return b;
  }

  // ---- what the server sends, checked field by field ---------------------------------------------
  function item(v) {
    const o = obj(v);
    const id = o && typeof o.id === 'string' && ID_RE.test(o.id) ? o.id : '';
    if (!id) return null;
    const kind = own(KIND_WORDS, o.kind) ? o.kind : 'key';
    return {
      id, kind, label: txt(o.label, 80) || id, manual: o.source === 'manual',
      status: own(STATUS_WORDS, o.status) ? o.status : 'unknown', checking: o.checking === true,
      group: GROUPS.some(([g]) => g === o.group) ? o.group : KIND_GROUP[kind],
      limit: num(o.limit), used: num(o.used), unit: txt(o.unit, 20), percent: num(o.percent),
      reason: txt(o.reason, 120), note: txt(o.note, TEXT_MAX), impact: txt(o.impact, TEXT_MAX), fix: txt(o.fix, TEXT_MAX),
      reset: when(o.reset_at), expires: when(o.expires_at), expiresRaw: txt(o.expires_at, 40), resetRaw: txt(o.reset_at, 40),
    };
  }
  function aboutLine(o) { // R6.1 D4: never the page's own clock; a date the server doesn't know says so
    const v = typeof o.version === 'string' && VER_RE.test(o.version) ? o.version : '';
    if (!v) return '';
    const built = typeof o.build_date === 'string' && DAY_RE.test(o.build_date) ? 'built ' + o.build_date : 'build date unknown';
    return 'About JARVIS \u00b7 ' + v + ' \u00b7 ' + built;
  }
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    return {
      about: aboutLine(o),
      overall: own(STATUS_WORDS, o.overall) ? o.overall : 'unknown',
      items: arr(o.items).map(item).filter(Boolean),
      manualUnavailable: o.manual_unavailable === true,
      manualNote: txt(o.manual_note, TEXT_MAX),
    };
  }

  // ---- the board's frame (built once) ------------------------------------------------------------
  const S = { data: null, busy: false, loadedAt: 0, checkedAt: 0, error: '', noteTimer: 0, editing: null, followSince: 0, followTimer: 0, slow: false };
  root.classList.add('vt');
  const card = mk('section', 'vt-card');
  card.setAttribute('aria-labelledby', 'vtTitle');
  const head = mk('div', 'rhead');
  const title = mk('h3', 'k nw', 'Keys, allowances & bills'); title.id = 'vtTitle';
  head.append(title);
  const sub = mk('div', 'vt-sub'); // the overall chip, when JARVIS last looked, Refresh
  const overallEl = mk('span', 'vt-chip vt-overall');
  const checked = mk('span', 'vt-checked');
  const sum = mk('p', 'vt-sum'); sum.append(overallEl, checked);
  const refresh = button('Refresh', 'btn lift sact', () => load(true, true));
  sub.append(sum, refresh);
  const stateEl = mk('p', 'vt-state'); stateEl.setAttribute('role', 'status');
  const errEl = mk('p', 'bnote bad'); errEl.setAttribute('role', 'alert');
  const noteEl = mk('p', 'bnote');
  const flashEl = mk('p', 'bnote ok'); flashEl.setAttribute('role', 'status'); flashEl.setAttribute('aria-live', 'polite');
  const groupsEl = mk('div', 'vt-groups');
  card.append(head, sub, stateEl, errEl, noteEl, flashEl, groupsEl);

  // ---- one item -----------------------------------------------------------------------------------
  function chip(status, checking) {
    const c = mk('span', 'vt-chip', checking && status === 'unknown' ? 'Checking\u2026' : STATUS_WORDS[status]);
    c.dataset.status = status;
    return c;
  }
  function usage(it) { // "850 of 1,000 credits" + " \u00b7 85%" (the percent never wraps alone)
    const p = mk('p', 'vt-use');
    if (it.used !== null && it.limit !== null) {
      p.textContent = (it.unit === '\u20b9' ? '\u20b9' : '') + figure(it.used) + ' of ' + amount(it.limit, it.unit);
      if (it.percent !== null) p.appendChild(mk('span', 'vt-pct', ' \u00b7 ' + Math.round(it.percent) + '%'));
    } else if (it.limit !== null) p.textContent = 'Limit ' + amount(it.limit, it.unit);
    else if (it.used !== null) p.textContent = amount(it.used, it.unit) + ' used';
    return p.textContent ? p : null;
  }
  function row(it) {
    const r = mk('div', 'vt-row');
    r.dataset.id = it.id; r.dataset.status = it.status;
    const top = mk('div', 'vt-top');
    const slow = it.checking && S.slow; // GitHub kept it waiting past the follow time
    top.append(mk('b', 'vt-label', it.label), chip(it.status, it.checking && !slow));
    r.appendChild(top);
    if (it.id === SPEND_ID) r.appendChild(mk('p', 'vt-note', 'The figures are under This month, above.'));
    else {
      if (it.limit !== null && it.limit > 0 && it.percent !== null) {
        const bar = mk('div', 'mbar'); bar.setAttribute('aria-hidden', 'true');
        const fill = mk('i'); fill.style.width = Math.max(0, Math.min(100, it.percent)) + '%';
        bar.appendChild(fill); r.appendChild(bar);
      }
      const use = usage(it);
      if (use) r.appendChild(use);
    }
    const meta = [it.manual ? 'Tracked by you' : '', it.reset ? 'Resets ' + it.reset : '', it.expires ? 'Expires ' + it.expires : ''].filter(Boolean);
    if (meta.length) r.appendChild(mk('p', 'vt-meta', meta.join(' \u00b7 ')));
    if (it.status !== 'ok' && it.reason && !slow) r.appendChild(mk('p', 'vt-why', it.label + ' ' + it.reason + '.'));
    if (it.note || slow) r.appendChild(mk('p', 'vt-note', slow ? SLOW : it.note));
    if (it.status === 'amber' || it.status === 'red') {
      if (it.impact) r.appendChild(mk('p', 'vt-fine', it.impact));
      if (it.fix) r.appendChild(mk('p', 'vt-fine vt-do', it.fix));
    }
    if (it.manual) {
      const acts = mk('div', 'vt-acts');
      const old = / \(old\)$/.test(it.label); // a stored record under a name a built-in item now uses: removable only
      if (!old) acts.append(button('Edit', 'btn lift bact', () => openForm(it)));
      acts.append(button('Stop tracking', 'btn lift bact', (b) => askStop(r, it, b)));
      r.appendChild(acts);
    }
    return r;
  }
  function askStop(r, it, trigger) { // two steps, like Integrations -> Google -> Disconnect
    if (r.querySelector('.confirm')) return;
    const box = mk('div', 'confirm'); box.setAttribute('role', 'alert');
    const keep = () => { box.remove(); trigger.focus(); };
    const no = button('Keep', 'btn lift', keep);
    const yes = button('Stop tracking', 'btn danger lift', () => remove(it, [no, yes]));
    box.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.isComposing) return; e.preventDefault(); e.stopPropagation(); keep(); });
    box.append(mk('span', '', 'Stop tracking ' + it.label + '? You can add it again any time.'), no, yes);
    r.appendChild(box); no.focus();
  }

  // ---- rendering ----------------------------------------------------------------------------------
  function shown() {
    const d = S.data;
    if (!d) return [];
    return d.items.filter((it) => it.id !== SPEND_ID || it.status === 'amber' || it.status === 'red');
  }
  function render() {
    const d = S.data, items = shown();
    overallEl.hidden = !d;
    overallEl.textContent = d ? STATUS_WORDS[d.overall] : '';
    overallEl.dataset.status = d ? d.overall : 'unknown';
    checked.textContent = d && S.checkedAt ? 'Checked ' + fmt(S.checkedAt, { hour: '2-digit', minute: '2-digit' })
      : S.busy ? 'Checking\u2026' : '';
    refresh.setAttribute('aria-disabled', S.busy ? 'true' : 'false');
    root.setAttribute('aria-busy', S.busy ? 'true' : 'false');
    errEl.textContent = S.error ? (d && !S.stopFailed ? 'Couldn\'t refresh just now. ' : '') + S.error : '';
    noteEl.textContent = d && d.manualUnavailable ? d.manualNote || MANUAL_NOTE : '';
    if (aboutEl && d) aboutEl.textContent = d.about;
    stateEl.textContent = !d && S.busy ? 'Checking your keys, allowances and bills\u2026'
      : d && !items.length ? 'Nothing to watch yet. JARVIS adds its own keys here as you connect them.' : '';
    groupsEl.replaceChildren();
    GROUPS.forEach(([g, name]) => {
      const mine = items.filter((it) => it.group === g)
        .sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.label.localeCompare(b.label));
      if (!mine.length) return;
      const sec = mk('section', 'vt-group');
      const h = mk('h4', '', name); h.id = 'vtG-' + g;
      sec.setAttribute('aria-labelledby', h.id);
      sec.appendChild(h);
      mine.forEach((it) => sec.appendChild(row(it)));
      groupsEl.appendChild(sec);
    });
    add.hidden = !d || d.manualUnavailable;
    const n = d ? d.items.filter((it) => it.manual).length : 0;
    dsum.textContent = n ? 'You track ' + n + ' item' + (n === 1 ? '' : 's') + ' yourself.' : 'Renewals, bills or limits only you know about.';
  }
  function flash(text) {
    flashEl.textContent = text;
    clearTimeout(S.noteTimer);
    S.noteTimer = setTimeout(() => { flashEl.textContent = ''; }, NOTE_MS);
  }

  // ---- "Track something JARVIS can't see": a closed disclosure with the form ----------------------
  const add = mk('section', 'bset vt-add');
  add.setAttribute('aria-labelledby', 'vtAddBtn');
  const dh = mk('h3', 'dhead');
  const dsc = mk('button', 'dsc'); dsc.type = 'button'; dsc.id = 'vtAddBtn';
  dsc.setAttribute('aria-expanded', 'false'); dsc.setAttribute('aria-controls', 'vtAddBody');
  const dsum = mk('span', 'dsum');
  [svg('dgear', 'M8 3.2v9.6M3.2 8h9.6'), mk('span', 'dl', 'Track something JARVIS can\'t see'),
    svg('dchev', 'M4.5 6.5 8 10l3.5-3.5'), dsum].forEach((n) => { if (n) dsc.appendChild(n); });
  dh.appendChild(dsc);
  const dbody = mk('div', 'dbody'); dbody.id = 'vtAddBody'; dbody.hidden = true;
  add.append(dh, dbody);
  root.append(card, add);
  const setOpen = (open) => { dsc.setAttribute('aria-expanded', open ? 'true' : 'false'); dbody.hidden = !open; };

  function control(tag, type, max) {
    const c = mk(tag, 'minput');
    if (type) c.type = type;
    if (max) c.maxLength = max;
    c.autocomplete = 'off';
    if (type === 'number') { c.min = '0'; c.step = 'any'; c.inputMode = 'decimal'; }
    return c;
  }
  const F = {
    label: control('input', 'text', 80), kind: control('select'), limit: control('input', 'number'),
    unit: control('input', 'text', 20), used: control('input', 'number'), expires: control('input', 'date'),
    note: control('input', 'text', TEXT_MAX),
  };
  KINDS.forEach((k) => { const o = mk('option', '', KIND_WORDS[k]); o.value = k; F.kind.appendChild(o); });
  function field(key, text, wide) {
    const w = mk('div', 'vt-field' + (wide ? ' wide' : ''));
    const l = mk('label', 'k', text);   // the themed label, like People / Things
    F[key].id = 'vtF-' + key; l.htmlFor = F[key].id;
    w.append(l, F[key]);
    return w;
  }
  const form = mk('form', 'vt-form'); form.noValidate = true;
  const ftitle = mk('p', 'vt-ftitle');
  const ferr = mk('p', 'lerr'); ferr.setAttribute('role', 'alert');
  const save = mk('button', 'btn primary lift', 'Save'); save.type = 'submit';
  const cancel = button('Cancel', 'btn lift', () => closeForm(true));
  const acts = mk('div', 'lrow'); acts.append(save, cancel);
  const grid = mk('div', 'vt-grid');
  grid.append(field('label', 'Name', true), field('kind', 'Kind', true), field('used', 'Used so far'), field('limit', 'Limit'),
    field('unit', 'Unit'), field('expires', 'Renews or expires on', true), field('note', 'Note (optional)', true));
  form.append(ftitle, mk('p', 'sfine', HINT), grid, ferr, acts);
  dbody.appendChild(form);

  function slug(name) { // "Car insurance" -> "car-insurance"; taken -> "car-insurance-2"
    const base = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+/, '').slice(0, SLUG_MAX).replace(/-+$/, '') || 'item';
    const taken = new Set(S.data ? S.data.items.map((it) => it.id) : []);
    let id = base, n = 2;
    while (taken.has(id)) id = base + '-' + n++;
    return id;
  }
  function openForm(it) {
    S.editing = it || null;
    ftitle.textContent = it ? 'Edit ' + it.label : 'Add something to watch';
    F.label.value = it ? it.label : ''; F.kind.value = it ? it.kind : 'key';
    F.limit.value = it && it.limit !== null ? String(it.limit) : ''; F.used.value = it && it.used !== null ? String(it.used) : '';
    F.unit.value = it ? it.unit : ''; F.note.value = it ? it.note : '';
    F.expires.value = it && /^\d{4}-\d{2}-\d{2}/.test(it.expiresRaw) ? it.expiresRaw.slice(0, 10) : '';
    ferr.textContent = ''; F.label.removeAttribute('aria-invalid');
    setOpen(true); F.label.focus();
  }
  function closeForm(collapse) {
    S.editing = null; form.reset(); ferr.textContent = ''; ftitle.textContent = 'Add something to watch';
    if (collapse) { setOpen(false); dsc.focus(); }
  }
  // Opening always starts a fresh "add"; collapsing ends any edit (Save can never hit a stale item).
  dsc.addEventListener('click', () => { if (dsc.getAttribute('aria-expanded') === 'true') closeForm(true); else openForm(null); });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const label = F.label.value.trim();
    if (!label) { ferr.textContent = 'Type a name first.'; F.label.setAttribute('aria-invalid', 'true'); F.label.focus(); return; }
    const ed = S.editing;
    const body = { id: ed ? ed.id : slug(label), label, kind: F.kind.value, unit: F.unit.value.trim(), note: F.note.value.trim() };
    if (!ed) body.create = true; // a NEW item never replaces an existing record (409 if the name is taken)
    if (F.limit.value !== '') body.limit = Number(F.limit.value);
    if (F.used.value !== '') body.used = Number(F.used.value);
    if (F.expires.value) body.expires_at = F.expires.value; // a date: the end of that day, owner's zone
    if (ed && ed.resetRaw) body.reset_at = ed.resetRaw;
    submit(body);
  });
  async function submit(body, retried) {
    if (!hasApi() || S.busy) return;
    S.busy = true; ferr.textContent = ''; save.disabled = true;
    try {
      await api('/v1/vitals/keys', { method: 'PUT', body });
      S.busy = false; save.disabled = false; closeForm(true); await load(true); flash('Saved.');
    } catch (e) {
      S.busy = false; save.disabled = false;
      if (e && e.status === 409 && body.create && !retried) { // the name is taken: reload, take the next suffix, once
        await load(true);
        submit({ ...body, id: slug(body.label) }, true);
        return;
      }
      ferr.textContent = e && e.status === 409 ? 'You already track something with that name. Pick another name.' : detailOf(e);
    }
  }
  async function remove(it, buttons) {
    if (!hasApi() || S.busy) return;
    S.busy = true; buttons.forEach((b) => { b.disabled = true; });
    try {
      await api('/v1/vitals/keys/' + encodeURIComponent(it.id), { method: 'DELETE' });
      S.busy = false; await load(true); flash('Stopped tracking ' + it.label + '. You can add it again any time.');
      dsc.focus(); // the stopped row (and its button) is gone: keep keyboard focus on the page
    } catch (e) {
      S.busy = false; S.error = 'Couldn\'t stop tracking ' + it.label + '. ' + detailOf(e); S.stopFailed = true; render();
    }
  }

  // ---- loading ------------------------------------------------------------------------------------
  async function load(force, fresh) { // fresh: his own press, so "Checking..." is followed from the start
    if (!hasApi() || S.busy) return;
    if (fresh) { S.followSince = 0; S.slow = false; }
    if (!force && S.data && Date.now() - S.loadedAt < STALE_MS) return;
    S.busy = true; render();
    try {
      S.stopFailed = false;
      const d = normal(await api('/v1/vitals'));
      if (d) { S.data = d; S.error = ''; S.loadedAt = S.checkedAt = Date.now(); } else S.error = 'Vitals sent something unexpected.';
    } catch (e) { S.error = detailOf(e); }
    S.busy = false; render(); follow();
  }
  function follow() { // an answer is on its way (R11.1 D19): look again until it is there, FOLLOW_FOR_MS at most
    clearTimeout(S.followTimer);
    const waiting = !!S.data && S.data.items.some((it) => it.checking);
    if (!waiting) { S.followSince = 0; S.slow = false; return; }
    const now = Date.now();
    if (!S.followSince) S.followSince = now;
    if (now - S.followSince < FOLLOW_FOR_MS) { S.followTimer = setTimeout(() => load(true), FOLLOW_MS); return; }
    if (!S.slow) { S.slow = true; render(); }   // say so plainly instead of "Checking..." for ever
  }
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'vitals' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => load(false));
  document.addEventListener('jarvis:reply', () => { S.loadedAt = 0; });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) load(false);
  render();
})();
