// src/jarvis/api/static/console-vault.js -- R2 D1-D8: the Vault panel (documents, dates, reminders).
// Lists the owner's documents grouped by person (type, title, "\u2022\u20224821", expiry with the time left,
// chips "Check details" / "From DigiLocker"), the item view (Open, Edit, Delete with Undo, reminder
// ticks), collapsed settings (alert detail, brief, inbox copy, family list), the storage line,
// Export and "Check DigiLocker now". Files open only here: the page asks for an unlock (a passkey
// where one is in force, else a recent Google sign-in), keeps the unlock token in memory only (never
// storage; forgotten when the panel closes or the tab hides), asks for a single-use ticket and
// downloads the decrypted bytes. No build step; CSP script-src 'self'; every server string reaches
// the page through textContent or an input's value (never markup). Transport: window.JarvisConsole
// .api (cookie + X-Requested-With, or the bearer token; 401 -> gate) and window.JarvisChat.raw for bytes.
// The panel markup is `#p-vault .pbody > #vaultBody` (console.html); the add and edit forms are in
// console-vault-add.js, which this file loads before it (window.JarvisVaultAdd).
// API: GET /v1/vault; POST /v1/vault/upload; PATCH|DELETE /v1/vault/items/{id}; POST|DELETE
// /v1/vault/holders; PUT /v1/vault/settings; POST /v1/vault/unlock; POST .../ticket; GET .../download/{t}.
(() => {
  'use strict';
  const ITEM_ID = /^v_[0-9a-f]{12}$/, FILE_ID = /^f_[0-9a-f]{12}$/, HOLDER_ID = /^(me|h_[0-9a-f]{8})$/;
  const UNDO_ID = /^del_[0-9a-f]{20}$/, TYPE_ID = /^[a-z_]{2,24}$/, ISO = /^\d{4}-\d{2}-\d{2}$/;
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const STALE_MS = 20 * 1000;
  const REMINDERS = [180, 90, 60, 30, 14, 7, 1];
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: false, open: '', adding: false, editing: '',
    token: '', until: 0, inbox: undefined, settingsOpen: false, preview: null };
  let host = null, noteEl = null, listEl = null, lastTrigger = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const quoted = (s) => '\u201c' + s + '\u201d';
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? txt(e.message, 400) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }

  // ---- dates in words -------------------------------------------------------------------------
  function niceDate(iso) {
    if (!ISO.test(iso || '')) return '';
    const [y, m, d] = iso.split('-').map(Number);
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d)); } catch (_) { return iso; }
  }
  const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
  /** "in 38 days", "8 years", "expired 3 days ago": how long is left, in the biggest sensible unit. */
  function left(n) {
    if (!Number.isInteger(n)) return '';
    if (n < 0) return 'expired ' + plural(-n, 'day') + ' ago';
    if (n === 0) return 'expires today';
    if (n <= 90) return 'in ' + plural(n, 'day');
    if (n < 730) return 'in ' + plural(Math.round(n / 30), 'month');
    return plural(Math.floor(n / 365), 'year');
  }
  const level = (n) => (!Number.isInteger(n) ? '' : n <= 7 ? 'alert' : n <= 30 ? 'warn' : n <= 90 ? 'note' : '');

  // ---- what the server sends, checked field by field -------------------------------------------
  function normalItem(raw) {
    const it = obj(raw);
    if (!it || typeof it.id !== 'string' || !ITEM_ID.test(it.id)) return null;
    const files = arr(it.files).map(obj).filter((f) => f && FILE_ID.test(f.fid || '')).slice(0, 2)
      .map((f) => ({ fid: f.fid, mime: txt(f.mime, 40), size: Number.isInteger(f.size) ? f.size : 0 }));
    const p = obj(it.proposal);
    const proposal = p ? { type: TYPE_ID.test(p.type || '') ? p.type : '', typeLabel: txt(p.type_label, 60),
      issued: ISO.test(p.issued_on || '') ? p.issued_on : '', issuedLabel: txt(p.issued_label, 40),
      expires: ISO.test(p.expires_on || '') ? p.expires_on : '', expiresLabel: txt(p.expires_label, 40), last4: txt(p.last4, 4) } : null;
    return { id: it.id, type: TYPE_ID.test(it.type || '') ? it.type : 'other', typeLabel: txt(it.type_label, 60) || 'Document',
      holderId: HOLDER_ID.test(it.holder_id || '') ? it.holder_id : 'me', holder: txt(it.holder, 40) || 'you',
      title: txt(it.title, 60), last4: txt(it.last4, 4), ends: txt(it.ends, 8), note: txt(it.note, 300),
      issued: ISO.test(it.issued_on || '') ? it.issued_on : '', expires: ISO.test(it.expires_on || '') ? it.expires_on : '',
      left: Number.isInteger(it.days_left) ? it.days_left : null, confirmed: it.dates_confirmed === true,
      reminders: arr(it.reminders).filter((n) => REMINDERS.includes(n)), digilocker: it.from_digilocker === true,
      normallyExpires: it.normally_expires !== false, files, proposal: proposal && (proposal.expires || proposal.issued || proposal.last4 || proposal.type) ? proposal : null };
  }
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    if (d.available !== true) return { available: false, reason: txt(d.reason, 200) };
    const t = obj(d.totals) || {}, st = obj(d.settings) || {}, un = obj(d.unlock) || {};
    return { available: true,
      items: arr(d.items).map(normalItem).filter(Boolean).slice(0, 100),
      holders: arr(d.holders).map(obj).filter((h) => h && HOLDER_ID.test(h.id || '')).slice(0, 13)
        .map((h) => ({ id: h.id, label: txt(h.label, 40) || 'you', count: Number.isInteger(h.count) ? h.count : 0 })),
      mb: typeof t.mb === 'number' ? t.mb : 0, limit: Number.isInteger(t.limit_mb) ? t.limit_mb : 150,
      count: Number.isInteger(t.items) ? t.items : 0, max: Number.isInteger(t.max_items) ? t.max_items : 100,
      settings: { detail: st.alert_detail === 'type' ? 'type' : 'generic', brief: st.brief !== false, inboxCopy: st.inbox_copy === true },
      unlock: { required: ['passkey', 'sign_in', 'none'].includes(un.required) ? un.required : 'sign_in', console: un.console !== false } };
  }

  // ---- notes, dialogs --------------------------------------------------------------------------
  function note(kind, text, action) {
    if (!noteEl) return;
    noteEl.className = 'vnote' + (kind === 'bad' ? ' bad' : kind === 'ok' ? ' ok' : '');
    noteEl.replaceChildren();
    if (text) noteEl.append(mk('span', '', text));
    if (action) { const b = mk('button', 'btn bact', action.label); b.type = 'button'; b.addEventListener('click', action.run); noteEl.append(b); }
    noteEl.hidden = !text;
  }
  /** A confirm dialog with a focus trap: Esc cancels, focus returns to what opened it. Resolves the
   *  chosen action id, or '' when cancelled. `actions`: [{id, label, kind}]. */
  function dialog(title, lines, actions) {
    return new Promise((resolve) => {
      const opener = document.activeElement;
      const back = mk('div', 'vd-back'), box = mk('div', 'vd-box');
      box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
      const h = mk('h3', '', title); h.id = 'vdTitle'; box.setAttribute('aria-labelledby', 'vdTitle');
      box.append(h);
      arr(lines).forEach((l) => box.append(typeof l === 'string' ? mk('p', 'vd-line', l) : l));
      const row = mk('div', 'vd-actions');
      const done = (id) => { document.removeEventListener('keydown', onKey, true); back.remove(); if (opener && opener.focus) opener.focus(); resolve(id); };
      actions.forEach((a) => { const b = mk('button', 'btn lift ' + (a.kind || ''), a.label); b.type = 'button'; b.dataset.act = a.id; b.addEventListener('click', () => done(a.id)); row.append(b); });
      box.append(row); back.append(box); document.body.append(back);
      function onKey(e) {
        if (e.key === 'Escape' && !e.isComposing) { e.preventDefault(); e.stopPropagation(); done(''); return; }
        if (e.key !== 'Tab') return;
        const f = Array.from(box.querySelectorAll('button,input,select,textarea,a[href]')).filter((n) => !n.disabled);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        else if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      }
      document.addEventListener('keydown', onKey, true);
      const first = row.querySelector('button'); if (first) first.focus();
    });
  }

  // ---- unlock ------------------------------------------------------------------------------------
  const unlocked = () => !!S.token && Date.now() < S.until;
  function forget() {
    if (S.token && hasApi()) { api('/v1/vault/unlock', { method: 'DELETE' }).catch(() => {}); }
    S.token = ''; S.until = 0; S.preview = null;
  }
  /** The unlock token, asking for it when there is none. '' = the owner cancelled or it failed. */
  async function ensureUnlocked() {
    if (unlocked()) return S.token;
    const d = S.data || {}, need = (d.unlock || {}).required || 'sign_in';
    const asks = need === 'passkey' ? 'Use your passkey to open the vault. It stays open for a few minutes, in this tab only.'
      : need === 'sign_in' ? 'Opening a document needs a Google sign-in from the last 5 minutes.'
        : 'Open the vault for a few minutes, in this tab only?';
    const go = await dialog('Open your vault', [asks, 'An opened file is saved decrypted in your Downloads folder, outside JARVIS\u2019s protection.'],
      [{ id: '', label: 'Cancel' }, { id: 'go', label: need === 'passkey' ? 'Use my passkey' : 'Unlock', kind: 'primary' }]);
    if (go !== 'go') return '';
    try {
      let body = {};
      if (need === 'passkey') {
        if (!window.JarvisPasskey) throw new Error('Passkeys are not available in this page.');
        body = { proof: await window.JarvisPasskey.prove('vault_unlock') };
      }
      const r = obj(await api('/v1/vault/unlock', { method: 'POST', body }));
      if (!r || typeof r.token !== 'string') throw new Error('The vault could not be unlocked.');
      S.token = r.token; S.until = Date.now() + (Number.isInteger(r.minutes) ? r.minutes : 10) * 60 * 1000 - 5000;
      log('info', 'Vault unlocked');
      return S.token;
    } catch (e) {
      if (e && e.status === 401) return '';
      if (e && e.code === 'reauth_required') {
        const again = await dialog('Sign in again', [detailOf(e) || 'Sign in with Google again to open your vault.'],
          [{ id: '', label: 'Not now' }, { id: 'go', label: 'Sign in with Google', kind: 'primary' }]);
        if (again === 'go') { try { window.location.assign('/auth/login?reauth=1'); } catch (_) {} }
        return '';
      }
      const m = window.JarvisPasskey && window.JarvisPasskey.message && e && !e.status ? window.JarvisPasskey.message(e) : '';
      note('bad', detailOf(e) || m || 'The vault could not be unlocked.');
      return '';
    }
  }
  async function fetchTicket(path, retry) {
    const token = await ensureUnlocked();
    if (!token) return '';
    try {
      const r = obj(await api(path, { method: 'POST', headers: { 'X-Jarvis-Vault': token } }));
      return r && typeof r.ticket === 'string' ? r.ticket : '';
    } catch (e) {
      if (e && e.status === 403 && e.code === 'locked' && retry) { S.token = ''; return fetchTicket(path, false); }
      throw e;
    }
  }
  async function download(ticket) {
    const chat = window.JarvisChat;
    if (!chat || typeof chat.raw !== 'function') throw new Error('Downloads are not available in this page.');
    const r = await chat.raw('/v1/vault/download/' + encodeURIComponent(ticket));
    if (!r.ok) {
      let detail = '';
      try { detail = txt((await r.json()).detail, 300); } catch (_) {}
      const err = new Error(detail || 'The download did not work.'); err.status = r.status; throw err;
    }
    const cd = r.headers.get('Content-Disposition') || '', m = /filename="([A-Za-z0-9._-]{1,80})"/.exec(cd);
    return { blob: await r.blob(), name: m ? m[1] : 'document' };
  }
  function save(blob, name) {
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = name; a.rel = 'noopener'; a.hidden = true; document.body.append(a); a.click();
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1500);
  }
  function dataUrl(blob) {
    return new Promise((resolve, reject) => { const fr = new FileReader(); fr.onload = () => resolve(String(fr.result)); fr.onerror = () => reject(fr.error); fr.readAsDataURL(blob); });
  }
  async function openFile(item, file, label) {
    if (S.busy) return;
    S.busy = true; render();
    try {
      const ticket = await fetchTicket('/v1/vault/items/' + item.id + '/files/' + file.fid + '/ticket', true);
      if (!ticket) return;
      const got = await download(ticket);
      if (/^image\/(jpeg|png)$/.test(file.mime)) { S.preview = { id: item.id, fid: file.fid, url: await dataUrl(got.blob), label }; note('ok', 'Opened. Closing this panel hides the picture.'); }
      else { save(got.blob, got.name); note('ok', 'Saved ' + got.name + ' to your Downloads.'); }
      log('info', 'Vault document opened');
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t open it. Please try again.');
    } finally { S.busy = false; render(); }
  }
  async function exportAll() {
    if (S.busy) return;
    S.busy = true; render();
    try {
      const ticket = await fetchTicket('/v1/vault/export/ticket', true);
      if (!ticket) return;
      const got = await download(ticket);
      save(got.blob, got.name); note('ok', 'Saved ' + got.name + ' to your Downloads. Keep it somewhere safe.'); log('info', 'Vault exported');
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'The export did not work. Please try again.');
    } finally { S.busy = false; render(); }
  }

  // ---- changes -----------------------------------------------------------------------------------
  async function call(path, opts, okText) {
    if (!hasApi() || S.busy) return null;
    S.busy = true; render();
    try {
      const r = await api(path, opts);
      if (okText) note('ok', okText);
      await reload();
      return r === null ? {} : r;
    } catch (e) {
      if (e && e.status === 401) return null;
      note('bad', detailOf(e) || 'That didn\'t work. Please try again.');
      return null;
    } finally { S.busy = false; render(); }
  }
  async function reload() { try { S.data = normal(await api('/v1/vault')); S.error = ''; } catch (e) { if (!(e && e.status === 401)) S.error = detailOf(e) || 'Please try again.'; } S.loadedAt = Date.now(); }
  async function remove(item) {
    const pick = await dialog('Delete this document?', [quoted(item.title || item.typeLabel) + ' moves to Recently deleted for 30 days. You can undo it there or right here.'],
      [{ id: '', label: 'Keep it' }, { id: 'del', label: 'Delete', kind: 'danger' }]);
    if (pick !== 'del') return;
    S.open = '';
    const r = await call('/v1/vault/items/' + item.id, { method: 'DELETE' }, '');
    if (r && UNDO_ID.test(r.undo_id || '')) {
      note('ok', 'Deleted. It stays in Recently deleted for 30 days.', { label: 'Undo', run: () => undo(r.undo_id) });
      log('info', 'Vault document deleted');
    }
  }
  async function undo(id) {
    const r = await call('/v1/deleted/' + id + '/restore', { method: 'POST', body: {} }, '');
    if (r) note('ok', 'Restored.');
  }
  const setReminders = (item, list) => call('/v1/vault/items/' + item.id, { method: 'PATCH', body: { reminders: list } }, '');
  const saveSettings = (patch) => call('/v1/vault/settings', { method: 'PUT', body: patch }, 'Saved.');

  // ---- rendering ---------------------------------------------------------------------------------
  function chip(text, cls) { return mk('span', 'vchip' + (cls ? ' ' + cls : ''), text); }
  function itemRow(item) {
    const li = mk('li', 'vitem'); li.dataset.id = item.id; if (S.open === item.id) li.classList.add('open');
    const head = mk('button', 'vhead'); head.type = 'button'; head.setAttribute('aria-expanded', String(S.open === item.id));
    const main = mk('span', 'vmain');
    main.append(mk('b', 'vtype', item.typeLabel));
    if (item.title && item.title !== item.typeLabel) main.append(mk('span', 'vtitle', item.title));
    const meta = mk('span', 'vmeta');
    meta.append(mk('span', '', item.holder));
    if (item.ends) meta.append(mk('span', 'vends', item.ends));
    main.append(meta); head.append(main);
    const side = mk('span', 'vside');
    if (!item.confirmed) side.append(chip('Check details', 'chk'));
    else if (item.expires) side.append(mk('span', 'vleft ' + level(item.left), left(item.left) + (item.left !== null && item.left <= 90 ? '' : '')));
    if (item.digilocker) side.append(chip('From DigiLocker', 'dl'));
    head.append(side);
    head.setAttribute('aria-label', item.typeLabel + ', ' + item.holder + (item.confirmed && item.expires ? ', ' + left(item.left) : ', check details'));
    head.addEventListener('click', () => { S.open = S.open === item.id ? '' : item.id; S.editing = ''; S.preview = null; render(); const n = host.querySelector('.vitem[data-id="' + item.id + '"] .vhead'); if (n) n.focus(); });
    li.append(head);
    if (S.open === item.id) li.append(itemView(item));
    return li;
  }
  function itemView(item) {
    const box = mk('div', 'vview');
    const Add = window.JarvisVaultAdd;
    if (S.editing === item.id && Add) { box.append(Add.editForm(item, ctx())); return box; }
    if (item.expires) box.append(mk('p', 'vline', 'Expires ' + niceDate(item.expires) + (item.issued ? ' \u00b7 issued ' + niceDate(item.issued) : '') + (item.confirmed ? '' : ' (not confirmed)')));
    if (item.proposal && !item.confirmed) box.append(mk('p', 'vline vfound', foundText(item.proposal)));
    if (item.note) box.append(mk('p', 'vline vnotetxt', item.note));
    const acts = mk('div', 'vacts');
    item.files.forEach((f, i) => {
      const label = item.files.length > 1 ? (i === 0 ? 'Open front' : 'Open back') : 'Open';
      const b = mk('button', 'btn bact', label); b.type = 'button'; b.disabled = S.busy;
      b.addEventListener('click', () => openFile(item, f, label)); acts.append(b);
    });
    if (item.files.length < 2 && Add) { const b = mk('button', 'btn bact', 'Add the back'); b.type = 'button'; b.addEventListener('click', () => Add.pickFile(item, ctx())); acts.append(b); }
    const ed = mk('button', 'btn bact', item.confirmed ? 'Edit' : 'Check details'); ed.type = 'button'; ed.addEventListener('click', () => { S.editing = item.id; render(); });
    const del = mk('button', 'btn bact bdel', 'Delete'); del.type = 'button'; del.addEventListener('click', () => remove(item));
    acts.append(ed, del); box.append(acts);
    if (S.preview && S.preview.id === item.id) {
      const img = document.createElement('img'); img.className = 'vpreview'; img.src = S.preview.url; img.alt = 'Preview of ' + item.typeLabel;
      box.append(img);
    }
    box.append(reminderTicks(item));
    return box;
  }
  function foundText(p) {
    const bits = [];
    if (p.expires) bits.push('expires ' + niceDate(p.expires) + (p.expiresLabel ? ' (' + p.expiresLabel + ')' : ''));
    if (p.issued) bits.push('issued ' + niceDate(p.issued) + (p.issuedLabel ? ' (' + p.issuedLabel + ')' : ''));
    if (p.last4) bits.push('ends ' + p.last4);
    return bits.length ? 'Found: ' + bits.join(', ') + '. Check details to confirm.' : '';
  }
  function reminderTicks(item) {
    const fs = mk('fieldset', 'vticks'); fs.append(mk('legend', '', 'Remind me before it expires'));
    if (!item.confirmed) { fs.append(mk('p', 'vfine', 'Reminders start once you confirm the dates.')); return fs; }
    REMINDERS.forEach((n) => {
      const l = mk('label', 'vtick'), c = document.createElement('input'); c.type = 'checkbox'; c.checked = item.reminders.includes(n); c.disabled = S.busy;
      c.addEventListener('change', () => { const cur = new Set(item.reminders); if (c.checked) cur.add(n); else cur.delete(n); setReminders(item, Array.from(cur).sort((a, b) => b - a)); });
      l.append(c, mk('span', '', n === 1 ? '1 day' : n + ' days')); fs.append(l);
    });
    return fs;
  }
  function groups(d) {
    const wrap = mk('div', 'vgroups');
    d.holders.forEach((h) => {
      const items = d.items.filter((i) => i.holderId === h.id);
      if (!items.length) return;
      const sec = mk('section', 'vgroup'), head = mk('h3', '', h.label === 'you' ? 'Yours' : h.label);
      head.append(mk('span', 'bcount', '\u00b7 ' + items.length));
      const ul = mk('ul', 'vlist'); items.forEach((i) => ul.append(itemRow(i)));
      sec.append(head, ul); wrap.append(sec);
    });
    return wrap;
  }
  function settingsBox(d) {
    const det = mk('details', 'vset'); det.open = S.settingsOpen;
    det.addEventListener('toggle', () => { S.settingsOpen = det.open; });
    det.append(mk('summary', '', 'Settings'));
    const sel = document.createElement('select'); sel.id = 'vaultDetail'; sel.className = 'dinput';
    [['generic', 'Say only that a document is due'], ['type', 'Say which kind of document (not whose)']].forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; sel.append(o); });
    sel.value = d.settings.detail; sel.addEventListener('change', () => saveSettings({ alert_detail: sel.value }));
    const l1 = mk('label', 'dlbl', 'Telegram reminder wording'); l1.htmlFor = 'vaultDetail';
    const box = (id, label, on, key) => { const w = mk('label', 'vtick'); const c = document.createElement('input'); c.type = 'checkbox'; c.id = id; c.checked = on; c.addEventListener('change', () => saveSettings({ [key]: c.checked })); w.append(c, mk('span', '', label)); return w; };
    det.append(l1, sel, box('vaultBrief', 'Show documents that are due in my morning brief', d.settings.brief, 'brief'),
      box('vaultInboxCopy', 'Put the details in the brief\u2019s Gmail copy', d.settings.inboxCopy, 'inbox_copy'));
    det.append(mk('h4', 'vsub', 'Family members'));
    const ul = mk('ul', 'vholders');
    d.holders.filter((h) => h.id !== 'me').forEach((h) => {
      const li = mk('li'); li.append(mk('span', '', h.label + (h.count ? ' \u00b7 ' + plural(h.count, 'document') : '')));
      const rm = mk('button', 'btn bact', 'Remove'); rm.type = 'button'; rm.setAttribute('aria-label', 'Remove ' + h.label); rm.disabled = h.count > 0 || S.busy;
      rm.addEventListener('click', () => call('/v1/vault/holders/' + h.id, { method: 'DELETE' }, quoted(h.label) + ' removed.')); li.append(rm); ul.append(li);
    });
    det.append(ul);
    const f = mk('form', 'vaddh'), inp = document.createElement('input'); inp.className = 'dinput'; inp.maxLength = 40; inp.placeholder = 'Add a family member, e.g. Anjali'; inp.setAttribute('aria-label', 'Family member name'); inp.autocomplete = 'off';
    const go = mk('button', 'btn bact', 'Add'); go.type = 'submit';
    f.addEventListener('submit', (e) => { e.preventDefault(); const v = txt(inp.value, 40); if (v) call('/v1/vault/holders', { method: 'POST', body: { label: v } }, quoted(v) + ' added.'); });
    f.append(inp, go); det.append(f);
    return det;
  }
  function inboxLine() {
    const ib = S.inbox, row = mk('div', 'vinbox');
    if (!ib || !ib.available) return null;
    if (!ib.configured) { row.append(mk('p', 'vfine', 'DigiLocker import: set it up in Integrations, then Google Drive.')); return row; }
    const b = mk('button', 'btn bact', 'Check DigiLocker now'); b.type = 'button'; b.disabled = S.busy; b.id = 'vaultCheck';
    b.addEventListener('click', async () => {
      const r = await call('/v1/vault/inbox/check', { method: 'POST', body: {} }, '');
      if (r) { const n = Number.isInteger(r.imported) ? r.imported : 0; note('ok', n ? plural(n, 'document') + ' imported. Imported \u2014 you can delete the copy in Drive now; JARVIS keeps an encrypted one.' : 'Nothing new to import.'); }
    });
    row.append(b); return row;
  }

  function render() {
    if (!host) return;
    const keep = noteEl;
    host.replaceChildren();
    const d = S.data;
    if (S.error && d === undefined) { host.append(mk('p', 'warn', 'Couldn\'t load your vault. ' + S.error)); const r = mk('button', 'btn bact', 'Retry'); r.type = 'button'; r.addEventListener('click', () => load(true)); host.append(r); return; }
    if (d === undefined) { host.append(mk('p', 'vfine', 'Checking\u2026')); return; }
    if (!d || !d.available) { host.append(mk('p', 'vfine', (d && d.reason) || 'Not available on this server.')); return; }
    const top = mk('div', 'vtop');
    top.append(mk('span', 'vstore', d.count + ' document' + (d.count === 1 ? '' : 's') + ' \u00b7 ' + d.mb + ' MB of ' + d.limit + ' MB'));
    const acts = mk('div', 'vacts');
    const add = mk('button', 'btn primary lift bact', S.adding ? 'Close' : 'Add'); add.type = 'button'; add.id = 'vaultAdd'; add.setAttribute('aria-expanded', String(S.adding));
    add.addEventListener('click', () => { S.adding = !S.adding; render(); });
    const ex = mk('button', 'btn bact', 'Export'); ex.type = 'button'; ex.id = 'vaultExport'; ex.disabled = S.busy || !d.items.length;
    ex.addEventListener('click', exportAll);
    acts.append(add, ex); top.append(acts); host.append(top);
    host.append(keep || mk('div'));
    if (S.adding && window.JarvisVaultAdd) host.append(window.JarvisVaultAdd.addForm(d, ctx()));
    const inbox = inboxLine(); if (inbox) host.append(inbox);
    if (!d.items.length) host.append(mk('p', 'vempty', 'No documents yet. Add a passport, licence or insurance policy (PDF, JPEG or PNG, up to 10 MB). JARVIS keeps them encrypted and reminds you before they expire.'));
    else host.append(groups(d));
    host.append(settingsBox(d));
    host.append(mk('p', 'vfine', 'Files are encrypted by JARVIS and can\u2019t be read by the assistant: it sees only the type, the last 4 characters and the dates.'));
  }
  const ctx = () => ({ mk, txt, arr, api, call, note, dialog, detailOf, niceDate, quoted, data: () => S.data, busy: () => S.busy,
    refresh: async () => { await reload(); render(); }, openItem: (id) => { S.open = id; S.editing = id; S.adding = false; }, close: () => { S.adding = false; S.editing = ''; render(); },
    setBusy: (b) => { S.busy = b; render(); }, log });

  function build() {
    if (host) return true;
    host = document.getElementById('vaultBody');
    if (!host) return false;
    noteEl = mk('div', 'vnote'); noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    return true;
  }
  async function loadInbox() {
    try { const r = obj(await api('/v1/vault/inbox')); S.inbox = r ? { available: r.available !== false, configured: r.configured === true } : null; } catch (_) { S.inbox = null; }
  }
  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) { render(); return Promise.resolve(); }
    S.loading = (async () => {
      try { S.data = normal(await api('/v1/vault')); S.error = ''; await loadInbox(); }
      catch (e) { if (e && e.status === 401) return; S.error = detailOf(e) || 'Please try again.'; S.data = undefined; }
      finally { S.loadedAt = Date.now(); S.loading = null; render(); }
    })();
    return S.loading;
  }
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id !== 'vault') return;
    if (d.open) load(false); else { forget(); S.open = ''; S.editing = ''; S.adding = false; render(); }
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden && S.token) { forget(); S.preview = null; render(); } });
  document.addEventListener('jarvis:reply', () => { if (S.data !== undefined) load(true); });
  document.addEventListener('jarvis:ready', () => { if (document.getElementById('p-vault') && !document.getElementById('p-vault').hidden) load(false); });

  window.JarvisVault = Object.freeze({ refresh: () => load(true), normal, left, niceDate, lastTrigger: () => lastTrigger });
})();
