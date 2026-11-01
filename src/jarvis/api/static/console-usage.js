// src/jarvis/api/static/console-usage.js — this month's AI spend in rupees and the owner's monthly
// limit, in the Vitals panel (slice 7b, docs/plans/phase7-slice7b-inr-costs-budget.md). No build
// step; CSP script-src 'self'. Every server string reaches the DOM through textContent; a field
// that is missing or of the wrong type shows "—" or hides its line, never a guess. No dollar sign here:
// the owner sees rupees only. Transport is the console's own api() (window.JarvisConsole: cookie
// + X-Requested-With: JARVIS, or the bearer token; 401 → gate).
// Listens: jarvis:ready (signed in; JarvisConsole.ready() covers arriving after it), jarvis:panel
// (Vitals shown), jarvis:reply (a reply, or a refusal at the limit: spend may have changed).
// API (src/jarvis/api/usage.py): GET /v1/usage → UsageView; PUT /v1/usage/budget
// {monthly_limit_inr, confirm_raise?} → UsageView (422 carries a plain `detail`).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const box = $('spend');
  if (!box) return;
  const fig = $('sMonth'), ofEl = $('sMonthOf'), stateEl = $('spendState'), bar = $('sBar');
  const noteEl = $('spendNote'), brainsEl = $('sBrains'), rateEl = $('sRate'), retry = $('spendRetry');
  const btn = $('limitBtn'), form = $('limitForm'), input = $('limitIn'), errEl = $('limitErr');
  const removeBtn = $('limitRemove'), cancelBtn = $('limitCancel'), okEl = $('limitNote');
  const dlg = $('limitDialog');
  const Deck = window.JarvisDeck || {};
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const LIMIT_MIN = 1, LIMIT_MAX = 100000;
  const NOTE_MS = 5000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- type-checking helpers: anything unexpected becomes null / "" / [] ------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 80) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const rupees = (v) => (typeof Deck.rupees === 'function' ? Deck.rupees(v) : '—');
  const whole = (n) => (typeof Deck.wholeRupees === 'function' ? Deck.wholeRupees(n) : '');
  const setText = (el, t) => { if (el && el.textContent !== t) el.textContent = t; };
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  function detailOf(e) { // the server's plain-English `detail`, never a bare code or "[object …]"
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function dayMonth(iso) { // "1 Nov" for YYYY-MM-DD, read as a calendar date (never shifted by zone)
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return '';
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))); }
    catch (_) { return iso; }
  }
  function nextMonthStart(month) { // "2026-11" → "1 Dec"
    const m = /^(\d{4})-(\d{2})$/.exec(month || '');
    if (!m) return '';
    const y = +m[1], mo = +m[2]; // 1-based; Date.UTC's month is 0-based, so mo is already "next"
    return dayMonth(`${mo === 12 ? y + 1 : y}-${String(mo === 12 ? 1 : mo + 1).padStart(2, '0')}-01`);
  }

  /** GET /v1/usage, checked field by field. */
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const limit = Number.isInteger(o.limit_inr) && o.limit_inr > 0 ? o.limit_inr : null;
    const rate = obj(o.rate);
    return {
      month: /^\d{4}-\d{2}$/.test(txt(o.month, 7)) ? txt(o.month, 7) : '',
      used: Math.max(0, num(o.used_inr) ?? 0),
      limit,
      percent: limit === null ? null : Math.max(0, num(o.percent) ?? 0),
      warn: o.warn === true,
      reached: o.reached === true,
      brains: arr(o.by_brain).map(obj).filter(Boolean)
        .map(b => ({ label: txt(b.label, 40) || txt(b.brain, 40), used: num(b.used_inr) }))
        .filter(b => b.label && b.used !== null && b.used > 0),
      rate: rate && num(rate.inr_per_usd) ? { value: rate.inr_per_usd, asOf: txt(rate.as_of, 10), source: txt(rate.source, 12) } : null,
    };
  }

  // ---- state + server ----------------------------------------------------------------------------
  const S = { data: undefined, error: '', seq: 0, saving: false, asking: false, okTimer: 0 };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);

  async function load() {
    if (!hasApi()) return;
    const seq = ++S.seq; // a newer load or a save wins over an older answer
    try {
      const d = normal(await api('/v1/usage'));
      if (seq !== S.seq) return;
      if (d) { S.data = d; S.error = ''; } else S.error = 'The server sent something unexpected.';
    } catch (e) {
      if (seq !== S.seq || e.status === 401) return; // the sign-in gate takes over
      S.error = e.status === 404 ? 'Not available in this setup.' : detailOf(e) || 'Please try again.';
    }
    render();
  }
  async function put(body, okText) {
    if (!hasApi() || S.saving) return false;
    S.saving = true; setErr(''); render();
    let ok = false;
    try {
      const d = normal(await api('/v1/usage/budget', { method: 'PUT', body }));
      ++S.seq; // an older GET still on its way must not overwrite what was just saved
      if (d) { S.data = d; S.error = ''; }
      ok = true;
      flashOk(okText);
      log('info', 'Monthly limit saved');
    } catch (e) {
      if (e.status !== 401) setErr(detailOf(e) || 'Couldn\'t save. Please try again.');
    } finally { S.saving = false; render(); }
    return ok;
  }

  // ---- rendering -----------------------------------------------------------------------------------
  function stateOf(d) {
    if (!d) return S.error ? 'error' : 'loading';
    if (d.reached) return 'reached';
    if (d.warn) return 'warn';
    return d.limit === null ? 'none' : 'ok';
  }
  const STATE_WORDS = { loading: ['', 'Checking…'], error: ['', 'Unavailable'], none: ['', 'No limit set'], reached: ['bad', 'Limit reached'] };
  function render() {
    const d = S.data || null, st = stateOf(d);
    box.dataset.state = st;
    setText(fig, d ? rupees(d.used) : '—');
    setText(ofEl, d && d.limit !== null ? 'of ' + whole(d.limit) : '');
    const used = d && d.limit !== null ? Math.floor(d.percent) : null; // 99.6% is not "100%"
    const word = STATE_WORDS[st] || [st === 'warn' ? 'warn' : '', `${used}% used`];
    setText(stateEl, word[1]);
    stateEl.className = 'k nw sstate' + (word[0] ? ' ' + word[0] : '');
    bar.hidden = !(d && d.limit !== null);
    if (!bar.hidden) {
      const pct = Math.min(100, Math.max(0, d.percent));
      bar.firstElementChild.style.width = pct.toFixed(1) + '%';
      bar.setAttribute('aria-valuenow', String(Math.round(pct)));
      bar.setAttribute('aria-valuetext', `${rupees(d.used)} of ${whole(d.limit)} used`);
    }
    setText(noteEl, noteFor(st, d));
    setText(brainsEl, d && d.brains.length ? d.brains.map(b => `${b.label} ${rupees(b.used)}`).join(' · ') : '');
    setText(rateEl, rateLine(d && d.rate));
    retry.hidden = st !== 'error';
    const ready = !!d && !S.saving;
    btn.setAttribute('aria-disabled', String(!ready));
    removeBtn.hidden = !(d && d.limit !== null);
    [input, $('limitSave'), cancelBtn, removeBtn].forEach(el => { if (el) el.disabled = S.saving; });
  }
  function noteFor(st, d) {
    if (st === 'error') return 'Couldn\'t load this month\'s spending. ' + S.error;
    if (st === 'reached') {
      const when = nextMonthStart(d.month);
      return `This month's limit is used up: JARVIS won't call the paid AI${when ? ' until ' + when : ''} unless you raise it. Free brains still answer.`;
    }
    if (st === 'warn') return 'Over 80% of this month\'s limit is used.';
    return '';
  }
  function rateLine(r) {
    if (!r) return '';
    const day = dayMonth(r.asOf);
    const value = r.value.toFixed(2);
    if (r.source === 'default') return `₹${value} per US dollar · fixed rate${day ? ' (' + day + ')' : ''}`;
    if (r.source === 'cached') return `₹${value} per US dollar · last known rate${day ? ', ' + day : ''}`;
    return `₹${value} per US dollar${day ? ' · rate of ' + day : ''}`;
  }
  function setErr(t) { setText(errEl, t); input.setAttribute('aria-invalid', String(!!t)); }
  function flashOk(t) {
    clearTimeout(S.okTimer);
    setText(okEl, t || '');
    if (t) S.okTimer = setTimeout(() => setText(okEl, ''), NOTE_MS);
  }

  // ---- the limit form --------------------------------------------------------------------------------
  function openForm() {
    if (btn.getAttribute('aria-disabled') === 'true' || !S.data) return;
    form.hidden = false; btn.setAttribute('aria-expanded', 'true');
    input.value = S.data.limit !== null ? String(S.data.limit) : '';
    setErr(''); flashOk('');
    input.focus(); input.select();
  }
  function closeForm(focusBack) {
    form.hidden = true; btn.setAttribute('aria-expanded', 'false'); setErr('');
    if (focusBack) btn.focus({ preventScroll: true });
  }
  /** "1,00,000", "₹500", " 750 " → integer; anything else → null. */
  function parseLimit(raw) {
    const t = String(raw || '').replace(/[₹,\s]/g, '');
    if (!/^\d{1,6}$/.test(t)) return null;
    const n = parseInt(t, 10);
    return n >= LIMIT_MIN && n <= LIMIT_MAX ? n : null;
  }
  async function save() {
    if (S.saving || S.asking || !S.data) return;
    const want = parseLimit(input.value), cur = S.data.limit;
    if (want === null) { setErr('Enter a whole number of rupees from ₹1 to ₹1,00,000.'); input.focus(); return; }
    if (want === cur) { closeForm(true); flashOk(`The limit stays at ${whole(cur)}.`); return; }
    const raise = cur !== null && want > cur; // more spending allowed: confirm-before-commit
    if (raise) {
      const ok = await asking(() => askConfirm($('limitSave'), `Raise the monthly limit to ${whole(want)}?`, [
        { cls: 'strong', text: `JARVIS may then spend up to ${whole(want)} this month on the paid AI, ${whole(want - cur)} more than now.` },
        { text: `Spent so far this month: ${rupees(S.data.used)}.` },
        { text: 'Rupee figures are estimates. The spend limit in your Anthropic account still applies.' },
      ], `Raise to ${whole(want)}`));
      if (!ok) return;
    }
    const body = raise ? { monthly_limit_inr: want, confirm_raise: true } : { monthly_limit_inr: want };
    if (await put(body, `Monthly limit set to ${whole(want)}.`)) closeForm(true);
    else input.focus();
  }
  async function removeLimit() {
    if (S.saving || S.asking || !S.data || S.data.limit === null) return;
    const ok = await asking(() => askConfirm(removeBtn, 'Remove the monthly limit?', [
      { cls: 'strong', text: 'JARVIS won\'t stop paid replies this month.' },
      { text: `Spent so far this month: ${rupees(S.data.used)}.` },
      { text: 'The spend limit in your Anthropic account still applies. You can set a new limit here at any time.' },
    ], 'Remove limit'));
    if (!ok) return;
    if (await put({ monthly_limit_inr: null, confirm_raise: true }, 'Monthly limit removed.')) closeForm(true);
  }

  // ---- confirm dialog: native modal (the rest of the page is inert), Tab stays inside, Esc = Not now
  async function asking(fn) {
    if (S.asking) return false;
    S.asking = true;
    try { return await fn(); } finally { S.asking = false; }
  }
  let settle = null;
  function askConfirm(trigger, title, lines, yesText) {
    if (!dlg || typeof dlg.showModal !== 'function') { setErr('This browser can\'t show the confirmation, so nothing was changed.'); return Promise.resolve(false); }
    if (settle) settle(false);
    setText($('limitDialogTitle'), title);
    const body = $('limitDialogText'); body.textContent = '';
    lines.forEach(l => body.append(mk('p', l.cls || '', l.text)));
    setText($('limitDialogYes'), yesText);
    return new Promise(resolve => {
      settle = (val) => {
        settle = null;
        if (dlg.open) dlg.close();
        if (trigger && document.contains(trigger) && !trigger.closest('[hidden]')) trigger.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('limitDialogNo').focus(); // the safe choice is where Enter lands
    });
  }
  if (dlg) {
    $('limitDialogYes').addEventListener('click', () => { if (settle) settle(true); });
    $('limitDialogNo').addEventListener('click', () => { if (settle) settle(false); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('close', () => { if (settle && !dlg.open) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const items = [...dlg.querySelectorAll('button:not([disabled])')];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  // ---- wiring --------------------------------------------------------------------------------------
  btn.addEventListener('click', () => { if (form.hidden) openForm(); else closeForm(true); });
  form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  cancelBtn.addEventListener('click', () => closeForm(true));
  removeBtn.addEventListener('click', removeLimit);
  retry.addEventListener('click', () => { S.error = ''; render(); load(); });
  input.addEventListener('input', () => { if (errEl.textContent) setErr(''); });
  // Esc in the form means Cancel; it must not close the Vitals panel
  form.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.isComposing) return;
    e.preventDefault(); e.stopPropagation(); closeForm(true);
  });
  document.addEventListener('jarvis:ready', () => load());
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'vitals' && d.open) load(); });
  document.addEventListener('jarvis:reply', () => load());
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) load(); // arrived after jarvis:ready
  render();
})();
