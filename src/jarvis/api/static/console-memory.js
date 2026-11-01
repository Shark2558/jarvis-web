// src/jarvis/api/static/console-memory.js — the Memory panel (slice 8,
// docs/plans/phase3-slice8-long-term-memory.md §5–§6). No build step; CSP script-src 'self'.
// Everything here is the owner's own data, and still untrusted: every server string reaches the page
// through textContent or a form control's .value, never parsed as markup; a field of the wrong type
// is dropped or shown empty, never guessed; server words ("learned", a category) map to ours via own().
// Transport is the console's own api() (window.JarvisConsole: cookie + X-Requested-With: JARVIS, or
// the bearer token; 401 → gate). The panel loads only when it is shown: each GET costs reads (D11).
// Listens: jarvis:ready (JarvisConsole.ready() covers arriving after it), jarvis:panel (Memory shown),
// jarvis:brain (memory is kept away from training brains, D6), jarvis:reply (a tool may have saved a
// fact). Fires: jarvis:event (deck log + radar).
// API (§5): GET /v1/memory; PUT /v1/memory/settings {use?, learn?, confirm_spend?} (409
// consent_required); PUT /v1/memory/profile/{label} {text}; POST /v1/memory/facts {text, category}
// (422 sensitive, 409 memory_full); PATCH and DELETE /v1/memory/facts/{id}; GET /v1/memory/export;
// POST /v1/memory/import {data} → {added, skipped}; DELETE /v1/memory {confirm: "FORGET"}.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const panel = $('p-memory'), box = $('memory'), stateEl = $('memState'), main = $('memMain'), list = $('memList');
  if (!panel || !box || !stateEl || !main || !list) return;
  const noteEl = $('memoryNote'), metaEl = $('memoryMeta'), refreshBtn = $('memoryRefresh'), dlg = $('memoryDialog');
  const setBtn = $('memSetBtn'), setBody = $('memSetBody'), setSum = $('memSetSum');
  const useBtn = $('memUse'), learnBtn = $('memLearn'), learnDesc = $('memLearnD');
  const filterIn = $('memFilter'), filterInfo = $('memFilterInfo'), factsCount = $('memFactsCount');
  const addForm = $('memAddForm'), addText = $('memAddText'), addCat = $('memAddCat'), addCount = $('memAddC');
  const addBtn = $('memAddBtn'), addErr = $('memAddErr');
  const exportBtn = $('memExport'), exportInfo = $('memExportInfo'), importBtn = $('memImport'), fileIn = $('memImportFile');
  const importBox = $('memImportBox'), importText = $('memImportText'), importNo = $('memImportNo'), importYes = $('memImportYes');
  const forgetBtn = $('memForget'), forgetBox = $('memForgetBox'), forgetIn = $('memForgetIn');
  const forgetNo = $('memForgetNo'), forgetYes = $('memForgetYes');
  const Deck = window.JarvisDeck || { open() {}, isOpen: () => false, isPhone: () => false };
  const store = { // per-device conveniences only; storage may throw or come back empty
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const PROFILE = ['about', 'preferences', 'people', 'work'];
  const CATEGORIES = { about_you: 'About you', preferences: 'Preferences', people: 'People', work: 'Work',
    places: 'Places', plans: 'Plans', other: 'Other' };
  const ORIGINS = { learned: 'learned', told: 'you told me', added: 'added by you', imported: 'imported' };
  const PROFILE_MAX = 1000, FACT_MAX = 300, IMPORT_MAX = 512 * 1024;
  const STALE_MS = 60 * 1000;           // reopening the panel reloads it after a minute
  const NOTE_MS = 5000;                 // a success line clears itself; errors stay until the next action
  const SETTINGS_OPEN_KEY = 'jarvis_memory_settings_open'; // D12: collapsed unless opened on this device
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const SENSITIVE = 'JARVIS doesn\'t keep that: it looks like private data (an ID, card or account number, a password, or a health detail).';
  const FULL = 'Memory is full. Delete some facts to make room.';
  // bidi overrides, zero-width and control characters can make text read differently than it is
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- small, type-checking helpers ---------------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  /** map[key] only for the map's own words: "__proto__" or "constructor" never reach Object.prototype. */
  const own = (map, key) => (typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const fmt = (n) => { try { return n.toLocaleString('en-IN'); } catch (_) { return String(n); } };
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  function button(id, cls, text, onClick) {
    const b = mk('button', 'btn lift bact' + (cls ? ' ' + cls : ''), text); b.type = 'button'; if (id) b.id = id;
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(b); });
    return b;
  }
  /** The server's plain-English `detail` (api() puts it in .message), never a bare code or "[object …]". */
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  const errText = (e) => detailOf(e) || 'Please try again.';
  const busyAttr = (el, on) => { if (on) el.setAttribute('aria-disabled', 'true'); else el.removeAttribute('aria-disabled'); };
  function icon(paths) {
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.6'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
    paths.forEach(d => { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p); });
    return svg;
  }
  const PIN = ['M7 3h6', 'M8 3v4.5l-2.5 3h9L12 7.5V3', 'M10 10.5V17'];
  const EDIT = ['M13.6 3.9a1.6 1.6 0 0 1 2.3 2.3l-8.4 8.4-3.2.9.9-3.2z', 'M11.8 5.7l2.3 2.3'];
  const TRASH = ['M4 6h12M8 6V4.5h4V6', 'M6 6l.7 10h6.6L14 6'];
  /** "30 Oct" this year, "30 Oct 2025" before it. */
  function day(iso) {
    const d = new Date(iso || NaN);
    if (isNaN(d)) return '';
    const opts = d.getFullYear() === new Date().getFullYear() ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' };
    try { return new Intl.DateTimeFormat([], opts).format(d); } catch (_) { return ''; }
  }

  // ---- what the server sends, checked field by field ------------------------------------------------
  function fact(v) {
    const o = obj(v);
    const id = o && typeof o.id === 'string' && o.id.length <= 80 ? o.id : '';
    const text = o ? txt(o.text, FACT_MAX + 100) : '';
    if (!id || !text) return null;
    const ms = (s) => { const t = Date.parse(txt(s, 40)); return Number.isFinite(t) ? t : 0; };
    return { id, text, category: own(CATEGORIES, o.category) ? o.category : 'other', origin: own(ORIGINS, o.origin) ? o.origin : '',
      pinned: o.pinned === true, created: txt(o.created_at, 40), changed: Math.max(ms(o.created_at), ms(o.updated_at)) };
  }
  function costNote(v) {
    if (typeof v === 'string') return txt(v, 300);
    const n = num(v), rupees = typeof Deck.rupees === 'function' ? Deck.rupees : null;
    return n !== null && n > 0 && rupees ? `Estimated cost: ${rupees(n)} a month.` : '';
  }
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const st = obj(o.settings) || {}, prof = obj(o.profile) || {}, counts = obj(o.counts) || {};
    const facts = arr(o.facts).map(fact).filter(Boolean);
    const profile = {};
    PROFILE.forEach(k => { const t = own(prof, k); profile[k] = typeof t === 'string' ? t.slice(0, PROFILE_MAX + 200) : ''; });
    return { use: st.use !== false, learn: st.learn === true, profile, facts,
      active: num(counts.active) ?? facts.length, replaced: num(counts.replaced) ?? 0, limit: num(counts.limit),
      costNote: costNote(o.learn_cost_note_inr), runsToday: num(o.runs_today) };
  }

  // ---- state --------------------------------------------------------------------------------------
  const S = {
    data: undefined,   // undefined = not loaded, null = this server has no memory (404), else normal()
    error: '', loading: false, seq: 0, fetchedAt: 0, signedIn: false, brain: null,
    filter: '', edit: null, confirming: null, busy: new Set(), saving: false, asking: false, adding: false,
    importing: null, importBusy: false, forgetBusy: false, exporting: false,
    saved: {}, profileBusy: new Set(), noteTimer: 0,
  };
  const keys = new Map(); // fact id → a local number: DOM ids never carry server text
  const keyOf = (id) => { if (!keys.has(id)) keys.set(id, keys.size + 1); return keys.get(id); };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const factPath = (id) => '/v1/memory/facts/' + encodeURIComponent(id);

  async function load() {
    if (!hasApi()) return;
    const seq = ++S.seq; // a newer load or a change wins over an older answer
    S.loading = true; render();
    try {
      const d = normal(await api('/v1/memory'));
      if (seq !== S.seq) return;
      if (d) { S.data = d; S.error = ''; } else S.error = 'The server sent something unexpected.';
    } catch (e) {
      if (seq !== S.seq) return;
      if (e.status === 401) { S.loading = false; render(); return; } // the sign-in gate takes over
      if (e.status === 404) { S.data = null; S.error = ''; } else S.error = errText(e);
    }
    S.loading = false; S.fetchedAt = Date.now();
    render();
  }
  /** A change was saved: an older GET still on its way must not overwrite it. */
  function changed(next) { ++S.seq; S.loading = false; S.data = { ...S.data, ...next }; }
  const setFacts = (facts, delta) => changed({ facts, active: Math.max(0, S.data.active + delta) });

  function flash(kind, text) {
    if (!noteEl) return;
    clearTimeout(S.noteTimer);
    noteEl.textContent = kind ? text : '';
    noteEl.className = 'bnote mlive' + (kind ? ' ' + kind : '');
    if (kind === 'ok') S.noteTimer = setTimeout(() => flash(null), NOTE_MS);
  }

  // ---- rendering ----------------------------------------------------------------------------------
  function render() {
    const a = document.activeElement, keep = a && a.id && panel.contains(a) ? a.id : null;
    renderMeta(); renderState();
    main.hidden = !S.data;
    if (S.data) { renderBrain(); renderSettings(); renderProfile(); renderFacts(); renderFoot(); }
    box.setAttribute('aria-busy', String(S.loading));
    if (refreshBtn) { busyAttr(refreshBtn, S.loading); refreshBtn.hidden = S.data === null; }
    const again = keep && $(keep); // re-rendered controls keep their ids: focus stays where it was
    if (again && again !== document.activeElement && !again.closest('[hidden]')) again.focus({ preventScroll: true });
  }
  function renderMeta() {
    if (!metaEl) return;
    const d = S.data;
    let text = '', cls = '';
    if (d === null) text = 'Not available';
    else if (d) {
      text = d.limit ? `${fmt(d.active)} of ${fmt(d.limit)} facts` : plural(d.active, 'fact', 'facts');
      if (d.limit && d.active >= d.limit) { text = 'Memory full'; cls = 'warn'; }
      else if (!d.use) text += ' · off in replies';
    }
    metaEl.textContent = text;
    metaEl.className = 'pmeta' + (cls ? ' ' + cls : '');
  }
  function renderState() {
    stateEl.textContent = '';
    if (S.data === null) { stateEl.append(mk('div', 'empty', 'Not available in this setup: this server has no long-term memory yet.')); return; }
    if (S.data && S.error) { stateEl.append(mk('p', 'bmiss warn', 'Couldn\'t refresh: showing what was loaded earlier.')); return; }
    if (S.data) return;
    if (S.error) {
      stateEl.append(mk('p', 'bmiss warn', 'Couldn\'t load your memory. ' + S.error), button('memRetry', '', 'Retry', () => load()));
      return;
    }
    stateEl.append(mk('div', 'empty', S.loading ? 'Loading your memory…' : 'Your memory loads when this panel opens.'));
  }
  function renderBrain() {
    const note = $('memBrainNote'), why = $('memBrainWhy'), b = obj(S.brain);
    const off = !!b && (b.trains === true || b.tools === false);
    if (!note) return;
    note.hidden = !off;
    if (why) why.textContent = !off ? '' : b.trains === true
      ? 'It may learn from what you type, so JARVIS keeps your notes away from it.'
      : 'It answers without tools, so your notes stay out of its replies.';
  }
  function renderSettings() {
    const d = S.data;
    [[useBtn, d.use], [learnBtn, d.learn]].forEach(([b, on]) => {
      if (!b) return;
      b.setAttribute('aria-pressed', String(on));
      const st = b.querySelector('.st'); if (st) st.textContent = on ? 'On' : 'Off';
      busyAttr(b, S.saving);
    });
    if (learnDesc) {
      const runs = d.learn && d.runsToday !== null ? ` Ran ${plural(d.runsToday, 'time', 'times')} today.` : '';
      learnDesc.textContent = 'Picks out facts from what you write and keeps them here. Asks you first.' + runs;
    }
    if (setSum) setSum.textContent = `Memory in replies ${d.use ? 'on' : 'off'} · Learning ${d.learn ? 'on' : 'off'}`;
  }
  function renderProfile() {
    PROFILE.forEach(label => {
      const ta = $('memP-' + label), saved = S.data.profile[label];
      if (!ta) return;
      // the server's text replaces the box only while the owner has nothing unsaved in it
      if (S.saved[label] === undefined || ta.value === S.saved[label]) { if (ta.value !== saved) ta.value = saved; }
      S.saved[label] = saved;
      syncProfile(label);
    });
  }
  function syncProfile(label) {
    const ta = $('memP-' + label), count = $('memC-' + label), save = $('memS-' + label);
    if (!ta || !count || !save) return;
    const n = ta.value.length;
    count.textContent = `${fmt(n)} / ${fmt(PROFILE_MAX)}`;
    count.classList.toggle('over', n > PROFILE_MAX);
    busyAttr(save, S.profileBusy.has(label) || ta.value === S.saved[label] || n > PROFILE_MAX);
  }
  function setStat(label, kind, text) {
    const el = $('memSt-' + label);
    if (el) { el.textContent = text; el.className = 'mstat' + (kind ? ' ' + kind : ''); }
  }
  const matches = (f, q) => [f.text, CATEGORIES[f.category], own(ORIGINS, f.origin) || ''].some(s => s.toLowerCase().includes(q));
  function renderFacts() {
    const facts = S.data.facts, q = S.filter.trim().toLowerCase();
    const shown = q ? facts.filter(f => matches(f, q)) : facts;
    const pinned = facts.filter(f => f.pinned).length;
    factsCount.textContent = facts.length ? '· ' + plural(facts.length, 'fact', 'facts') + (pinned ? ` · ${pinned} pinned` : '') : '';
    filterIn.parentNode.hidden = !facts.length && !q;
    filterInfo.textContent = q && shown.length ? `Showing ${shown.length} of ${facts.length}.` : '';
    list.textContent = '';
    if (!facts.length) {
      list.append(mk('p', 'bempty', 'No facts yet. Say “remember that …” in a conversation, or add one below.'));
      return;
    }
    if (!shown.length) { list.append(mk('p', 'bempty', `No facts match “${S.filter.trim()}”.`)); return; }
    Object.keys(CATEGORIES).forEach(cat => {
      const group = shown.filter(f => f.category === cat).sort((a, b) => (b.pinned - a.pinned) || (b.changed - a.changed));
      if (!group.length) return;
      const g = mk('div', 'mgrp'), h = mk('h4', 'mgh');
      h.append(mk('span', '', CATEGORIES[cat]), mk('span', 'bcount', '· ' + group.length));
      const ul = mk('ul', 'mfacts');
      group.forEach(f => ul.append(factRow(f)));
      g.append(h, ul); list.append(g);
    });
  }
  function iconButton(id, paths, label, describedBy, onClick) {
    const b = mk('button', 'mib'); b.type = 'button'; b.id = id; b.title = label;
    b.setAttribute('aria-label', label); b.setAttribute('aria-describedby', describedBy);
    b.append(icon(paths));
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(); });
    return b;
  }
  function factRow(f) {
    const k = keyOf(f.id), li = mk('li', 'mfact' + (f.pinned ? ' pinned' : ''));
    if (S.edit && S.edit.id === f.id) { li.append(editForm(f, k)); return li; }
    const text = mk('p', 'mft', f.text); text.id = 'mft-' + k;
    const meta = mk('div', 'mfm'), origin = own(ORIGINS, f.origin), when = day(f.created);
    if (origin) meta.append(mk('span', 'mbadge' + (f.origin === 'learned' ? ' learned' : ''), origin));
    if (when) meta.append(mk('span', 'mwhen', when));
    if (f.pinned) meta.append(mk('span', 'mpinned', 'Pinned'));
    const busy = S.busy.has(f.id), acts = mk('div', 'mfa');
    const pin = iconButton('mfPin-' + k, PIN, 'Pin', text.id, () => patchFact(f, { pinned: !f.pinned }));
    pin.setAttribute('aria-pressed', String(f.pinned));
    const edit = iconButton('mfEdit-' + k, EDIT, 'Edit', text.id, () => startEdit(f, k));
    const del = iconButton('mfDel-' + k, TRASH, 'Delete', text.id, () => askDelete(f, k));
    del.classList.add('del');
    [pin, edit, del].forEach(b => busyAttr(b, busy));
    acts.append(pin, edit, del);
    li.append(text, acts, meta);
    if (S.confirming === f.id) li.append(confirmDelete(f, k));
    return li;
  }
  function categorySelect(id, value) {
    const sel = mk('select', 'bsel'); sel.id = id;
    Object.keys(CATEGORIES).forEach(c => { const o = mk('option', '', CATEGORIES[c]); o.value = c; sel.append(o); });
    sel.value = own(CATEGORIES, value) ? value : 'other';
    return sel;
  }
  function editForm(f, k) {
    const form = mk('form', 'medit'); form.noValidate = true;
    const lab = mk('label', 'sr-only', 'Fact'); lab.htmlFor = 'mfText-' + k;
    const ta = mk('textarea', 'mta'); ta.id = 'mfText-' + k; ta.maxLength = FACT_MAX; ta.rows = 2; ta.value = S.edit.text;
    const count = mk('span', 'mcount'); count.id = 'mfC-' + k;
    const err = mk('p', 'lerr', S.edit.error); err.id = 'mfErr-' + k; err.setAttribute('role', 'alert');
    ta.setAttribute('aria-describedby', count.id + ' ' + err.id);
    const catLab = mk('label', 'sr-only', 'Category'); catLab.htmlFor = 'mfCat-' + k;
    const sel = categorySelect('mfCat-' + k, S.edit.category);
    const sync = () => { count.textContent = `${ta.value.length} / ${FACT_MAX}`; };
    ta.addEventListener('input', () => { S.edit = { ...S.edit, text: ta.value }; sync(); });
    sel.addEventListener('change', () => { S.edit = { ...S.edit, category: sel.value }; });
    sync();
    const cancel = button('mfCancel-' + k, '', 'Cancel', () => endEdit(k));
    const save = mk('button', 'btn primary lift bact', 'Save'); save.type = 'submit'; save.id = 'mfSave-' + k;
    busyAttr(save, S.busy.has(f.id));
    const row = mk('div', 'mrow'); row.append(catLab, sel, count, cancel, save);
    form.append(lab, ta, row, err);
    form.addEventListener('submit', (e) => { e.preventDefault(); if (save.getAttribute('aria-disabled') !== 'true') saveEdit(f, k); });
    form.addEventListener('keydown', (e) => { // Esc here means Cancel; it must not close the panel
      if (e.key !== 'Escape' || e.isComposing) return;
      e.preventDefault(); e.stopPropagation(); endEdit(k);
    });
    return form;
  }
  function confirmDelete(f, k) {
    const c = mk('div', 'confirm'); c.setAttribute('role', 'alert');
    const keep = button('mfKeep-' + k, '', 'Keep', () => { S.confirming = null; render(); focusId('mfDel-' + k); });
    const yes = button('mfDelYes-' + k, 'danger', 'Delete', () => removeFact(f, k));
    [keep, yes].forEach(b => busyAttr(b, S.busy.has(f.id)));
    c.append(mk('span', '', 'Delete this fact for good?'), keep, yes);
    c.addEventListener('keydown', (e) => { // Esc here means Keep
      if (e.key !== 'Escape' || e.isComposing) return;
      e.preventDefault(); e.stopPropagation(); keep.click();
    });
    return c;
  }
  function renderFoot() {
    const r = S.data.replaced;
    exportInfo.textContent = r ? `Export includes ${plural(r, 'replaced fact', 'replaced facts')}, kept 30 days for your history.` : '';
  }
  function focusId(id) { const el = $(id); if (el) el.focus({ preventScroll: false }); }

  // ---- settings ------------------------------------------------------------------------------------
  function settingsOpen(open, remember) {
    if (!setBtn || !setBody) return;
    setBody.hidden = !open;
    if (setSum) setSum.hidden = open; // the summary stands in for the switches only while they are hidden
    setBtn.setAttribute('aria-expanded', String(open));
    if (remember) store.set(SETTINGS_OPEN_KEY, open ? '1' : '0');
  }
  async function putSettings(patch, okText) {
    if (S.saving || !S.data) return;
    S.saving = true; flash(null); render();
    try {
      const r = obj(await api('/v1/memory/settings', { method: 'PUT', body: patch }));
      const full = r && Array.isArray(r.facts) ? normal(r) : null;
      const src = (r && obj(r.settings)) || (r && ('use' in r || 'learn' in r) ? r : patch);
      if (full) changed(full);
      else changed({ use: typeof src.use === 'boolean' ? src.use : S.data.use, learn: typeof src.learn === 'boolean' ? src.learn : S.data.learn });
      flash('ok', okText); log('info', 'Memory settings saved');
    } catch (e) {
      if (e.status === 409) flash('bad', detailOf(e) || 'JARVIS needs your go-ahead before it learns. Switch it on again to confirm.');
      else if (e.status !== 401) flash('bad', detailOf(e) || (e.status === 429 ? 'Too many changes just now. Try again in a minute.' : 'Couldn\'t save. Please try again.'));
    } finally { S.saving = false; render(); }
  }
  function toggleUse() {
    if (!S.data) return;
    const on = !S.data.use;
    putSettings({ use: on }, on ? 'Memory is used in replies again.' : 'Memory is off in replies. Nothing is deleted.');
  }
  async function askLearn(trigger) {
    if (!S.data || S.asking) return;
    if (S.data.learn) { putSettings({ learn: false }, 'Learning off. The facts already kept stay until you delete them.'); return; }
    S.asking = true;
    try {
      const ok = await askConfirm(trigger, 'Let JARVIS learn from your messages?', [
        { cls: 'strong', text: 'Uses Claude, the paid AI; never the free brain.' },
        S.data.costNote ? { text: S.data.costNote } : null,
        { text: 'Your messages in a conversation are sent to Claude so it can pick out facts about you. Only your own words: never emails, calendar text or JARVIS\'s replies.' },
        { text: 'Health details, ID and card numbers, passwords and the like are never kept. Every fact shows up here, where you can edit or delete it.' },
        { text: 'You can switch it off here at any time.' },
      ], 'Switch on');
      if (ok) await putSettings({ learn: true, confirm_spend: true }, 'Learning on. New facts will show up here.');
    } finally { S.asking = false; }
  }

  // ---- About you -----------------------------------------------------------------------------------
  async function saveProfile(label) {
    const ta = $('memP-' + label), save = $('memS-' + label);
    if (!S.data || !ta || !save || save.getAttribute('aria-disabled') === 'true') return;
    const text = ta.value;
    S.profileBusy.add(label); syncProfile(label); setStat(label, '', 'Saving…');
    try {
      const r = obj(await api('/v1/memory/profile/' + encodeURIComponent(label), { method: 'PUT', body: { text } }));
      const fromProfile = r && obj(r.profile) ? own(r.profile, label) : undefined;
      const saved = typeof fromProfile === 'string' ? fromProfile : r && typeof r.text === 'string' ? r.text : text;
      if (ta.value === text) ta.value = saved; // the server may have tidied it
      S.saved[label] = saved;
      changed({ profile: { ...S.data.profile, [label]: saved } });
      setStat(label, 'ok', 'Saved.'); log('info', 'About you saved');
    } catch (e) {
      if (e.status !== 401) setStat(label, 'bad', detailOf(e) || (e.status === 422 ? SENSITIVE : 'Couldn\'t save. ' + errText(e)));
      else setStat(label, '', '');
    } finally { S.profileBusy.delete(label); syncProfile(label); }
  }

  // ---- facts ---------------------------------------------------------------------------------------
  function startEdit(f, k) {
    S.edit = { id: f.id, text: f.text, category: f.category, error: '' }; S.confirming = null;
    render(); focusId('mfText-' + k);
  }
  function endEdit(k) { S.edit = null; render(); focusId('mfEdit-' + k); }
  function askDelete(f, k) { S.confirming = f.id; S.edit = null; render(); focusId('mfKeep-' + k); }
  async function patchFact(f, patch) {
    if (S.busy.has(f.id)) return false;
    S.busy.add(f.id); render();
    let ok = false;
    try {
      const r = fact(await api(factPath(f.id), { method: 'PATCH', body: patch }));
      const next = r && r.id === f.id ? r : { ...f, ...patch };
      setFacts(S.data.facts.map(x => (x.id === f.id ? next : x)), 0);
      ok = true;
      log('info', 'pinned' in patch ? (patch.pinned ? 'Memory fact pinned' : 'Memory fact unpinned') : 'Memory fact edited');
    } catch (e) {
      if (e.status === 404) { setFacts(S.data.facts.filter(x => x.id !== f.id), -1); flash('bad', 'That fact was already gone.'); }
      else if (e.status !== 401) {
        const m = detailOf(e) || (e.status === 422 ? SENSITIVE : 'Couldn\'t save. Please try again.');
        if (S.edit && S.edit.id === f.id) S.edit = { ...S.edit, error: m }; else flash('bad', m);
      }
    } finally { S.busy.delete(f.id); render(); }
    return ok;
  }
  async function saveEdit(f, k) {
    const text = S.edit.text.trim(), category = S.edit.category;
    if (!text) { S.edit = { ...S.edit, error: 'Write the fact, or cancel and delete it.' }; render(); focusId('mfText-' + k); return; }
    const patch = {};
    if (text !== f.text) patch.text = text;
    if (category !== f.category && own(CATEGORIES, category)) patch.category = category;
    if (!Object.keys(patch).length) { endEdit(k); return; }
    if (await patchFact(f, patch)) { flash('ok', 'Fact saved.'); endEdit(k); }
    else if (S.edit) focusId('mfText-' + k);
  }
  async function removeFact(f, k) {
    if (S.busy.has(f.id)) return;
    // where focus goes once the row is gone: the next fact, else the one before, else the filter
    const rows = [...list.querySelectorAll('.mft')].map(n => n.id), at = rows.indexOf('mft-' + k);
    const next = rows[at + 1] || rows[at - 1] || '';
    S.busy.add(f.id); render();
    let gone = false;
    try {
      await api(factPath(f.id), { method: 'DELETE' });
      gone = true; flash('ok', 'Fact deleted.'); log('info', 'Memory fact deleted');
    } catch (e) {
      if (e.status === 404) gone = true;
      else if (e.status !== 401) flash('bad', 'Couldn\'t delete that fact. ' + errText(e));
    } finally { S.busy.delete(f.id); }
    if (gone) { S.confirming = null; setFacts(S.data.facts.filter(x => x.id !== f.id), -1); }
    render();
    if (!gone) return;
    const target = next && $(next.replace('mft-', 'mfDel-'));
    if (target) target.focus(); else focusId(filterIn.parentNode.hidden ? 'memAddText' : 'memFilter');
  }
  async function addFact() {
    if (!S.data || S.adding) return;
    const text = addText.value.trim(), category = own(CATEGORIES, addCat.value) ? addCat.value : 'other';
    addErr.textContent = '';
    if (!text) { addErr.textContent = 'Write the fact first.'; addText.focus(); return; }
    S.adding = true; busyAttr(addBtn, true);
    try {
      const r = fact(await api('/v1/memory/facts', { body: { text, category } }));
      if (r) setFacts([r, ...S.data.facts.filter(x => x.id !== r.id)], 1); else await load();
      addText.value = ''; syncAdd();
      flash('ok', 'Fact added.'); log('info', 'Memory fact added');
    } catch (e) {
      if (e.status !== 401) addErr.textContent = detailOf(e) || (e.status === 409 ? FULL : e.status === 422 ? SENSITIVE : 'Couldn\'t add it. ' + errText(e));
    } finally { S.adding = false; busyAttr(addBtn, false); render(); }
  }
  function syncAdd() { addCount.textContent = `${addText.value.length} / ${FACT_MAX}`; }

  // ---- export, import, forget everything ----------------------------------------------------------
  function today() {
    const d = new Date(), p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  async function exportAll() {
    if (S.exporting) return;
    S.exporting = true; busyAttr(exportBtn, true);
    try {
      const data = await api('/v1/memory/export');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.download = `jarvis-memory-${today()}.json`;
      a.href = URL.createObjectURL(blob);
      a.hidden = true; document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      flash('ok', 'Export saved to your downloads.'); log('info', 'Memory exported');
    } catch (e) {
      if (e.status !== 401) flash('bad', 'Couldn\'t export. ' + errText(e));
    } finally { S.exporting = false; busyAttr(exportBtn, false); }
  }
  /** What an export file holds, or null when it doesn't look like one. */
  function preview(data) {
    const o = obj(data);
    if (!o || (!Array.isArray(o.facts) && !obj(o.profile))) return null;
    const facts = arr(o.facts).map(obj).filter(Boolean);
    const replaced = facts.filter(f => f.replaced_by || f.replaced_at).length;
    const prof = obj(o.profile) || {};
    const notes = PROFILE.filter(k => typeof own(prof, k) === 'string' && own(prof, k).trim()).length;
    return { facts: facts.length - replaced, replaced, notes };
  }
  async function readImport(file) {
    closeForget(false);
    if (!file) return;
    if (file.size > IMPORT_MAX) { flash('bad', 'That file is over 512 KB, so it isn\'t a JARVIS memory export.'); return; }
    let data;
    try { data = JSON.parse(await file.text()); } catch (_) { flash('bad', 'That file isn\'t a JARVIS memory export: it isn\'t valid JSON.'); return; }
    const p = preview(data);
    if (!p) { flash('bad', 'That file doesn\'t look like a JARVIS memory export.'); return; }
    S.importing = { data, p };
    const parts = [plural(p.facts, 'fact', 'facts')];
    if (p.replaced) parts.push(plural(p.replaced, 'replaced fact', 'replaced facts'));
    if (p.notes) parts.push(plural(p.notes, 'About you note', 'About you notes'));
    const name = txt(file.name, 80) || 'This file';
    importText.textContent = `${name} holds ${parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0]}.`;
    flash(null);
    importBox.hidden = false; importBtn.setAttribute('aria-expanded', 'true');
    importNo.focus(); // the safe choice is where Enter lands
  }
  function closeImport(focusBack) {
    S.importing = null; importBox.hidden = true; importBtn.setAttribute('aria-expanded', 'false');
    if (focusBack) importBtn.focus();
  }
  async function doImport() {
    if (!S.importing || S.importBusy) return;
    S.importBusy = true; [importYes, importNo].forEach(b => busyAttr(b, true));
    try {
      const r = obj(await api('/v1/memory/import', { body: { data: S.importing.data } }));
      const added = num(r && r.added), skipped = num(r && r.skipped);
      closeImport(true);
      flash('ok', added === null ? 'Imported.' : `Imported: ${plural(added, 'fact', 'facts')} added${skipped ? `, ${fmt(skipped)} skipped` : ''}.`);
      log('info', 'Memory imported');
      load();
    } catch (e) {
      if (e.status !== 401) flash('bad', detailOf(e) || 'Couldn\'t import. ' + errText(e));
    } finally { S.importBusy = false; [importYes, importNo].forEach(b => busyAttr(b, false)); }
  }
  function openForget() {
    closeImport(false);
    forgetBox.hidden = false; forgetBtn.setAttribute('aria-expanded', 'true');
    forgetIn.value = ''; forgetYes.disabled = true;
    forgetIn.focus();
  }
  function closeForget(focusBack) {
    forgetBox.hidden = true; forgetBtn.setAttribute('aria-expanded', 'false'); forgetIn.value = ''; forgetYes.disabled = true;
    if (focusBack) forgetBtn.focus();
  }
  const typedForget = () => forgetIn.value.trim() === 'FORGET';
  async function forgetAll() {
    if (!typedForget() || S.forgetBusy) return;
    S.forgetBusy = true; forgetYes.disabled = true; busyAttr(forgetNo, true);
    try {
      await api('/v1/memory', { method: 'DELETE', body: { confirm: 'FORGET' } });
      closeForget(true);
      S.edit = null; S.confirming = null;
      PROFILE.forEach(l => { const ta = $('memP-' + l); if (ta) ta.value = ''; S.saved[l] = ''; setStat(l, '', ''); });
      changed({ facts: [], active: 0, profile: { about: '', preferences: '', people: '', work: '' } });
      render();
      flash('ok', 'Memory cleared: every fact and your About you notes are gone. Your switches are kept.');
      log('info', 'Memory cleared');
      load();
    } catch (e) {
      if (e.status !== 401) flash('bad', 'Nothing was deleted. ' + errText(e));
      forgetYes.disabled = !typedForget();
    } finally { S.forgetBusy = false; busyAttr(forgetNo, false); }
  }

  // ---- confirm dialog: native modal (the rest of the page is inert), Tab stays inside, Esc = Not now
  let settle = null;
  function askConfirm(trigger, title, lines, yesText) {
    if (!dlg || typeof dlg.showModal !== 'function') { flash('bad', 'This browser can\'t show the confirmation, so nothing was switched on.'); return Promise.resolve(false); }
    if (settle) settle(false);
    $('memoryDialogTitle').textContent = title;
    const body = $('memoryDialogText'); body.textContent = '';
    lines.filter(Boolean).forEach(l => body.append(mk('p', l.cls || '', l.text)));
    $('memoryDialogYes').textContent = yesText;
    return new Promise(resolve => {
      settle = (val) => {
        settle = null;
        if (dlg.open) dlg.close();
        if (trigger && document.contains(trigger) && !trigger.closest('[hidden]')) trigger.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('memoryDialogNo').focus(); // the safe choice is where Enter lands
    });
  }
  if (dlg) {
    $('memoryDialogYes').addEventListener('click', () => { if (settle) settle(true); });
    $('memoryDialogNo').addEventListener('click', () => { if (settle) settle(false); });
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
  const pressable = (b) => b && b.getAttribute('aria-disabled') !== 'true';
  if (setBtn) setBtn.addEventListener('click', () => settingsOpen(setBody.hidden, true));
  settingsOpen(store.get(SETTINGS_OPEN_KEY) === '1', false);
  if (useBtn) useBtn.addEventListener('click', () => { if (pressable(useBtn)) toggleUse(); });
  if (learnBtn) learnBtn.addEventListener('click', () => { if (pressable(learnBtn)) askLearn(learnBtn); });
  PROFILE.forEach(label => {
    const ta = $('memP-' + label), save = $('memS-' + label);
    if (ta) ta.addEventListener('input', () => { syncProfile(label); setStat(label, '', ''); });
    if (save) save.addEventListener('click', () => saveProfile(label));
  });
  filterIn.addEventListener('input', () => { S.filter = filterIn.value.slice(0, 100); if (S.data) renderFacts(); });
  addText.addEventListener('input', () => { syncAdd(); if (addErr.textContent) addErr.textContent = ''; });
  addForm.addEventListener('submit', (e) => { e.preventDefault(); if (pressable(addBtn)) addFact(); });
  exportBtn.addEventListener('click', () => { if (pressable(exportBtn)) exportAll(); });
  importBtn.addEventListener('click', () => { if (importBox.hidden) fileIn.click(); else closeImport(true); });
  fileIn.addEventListener('change', () => { const f = fileIn.files && fileIn.files[0]; fileIn.value = ''; readImport(f); });
  importNo.addEventListener('click', () => { if (pressable(importNo)) closeImport(true); });
  importYes.addEventListener('click', () => { if (pressable(importYes)) doImport(); });
  importBox.addEventListener('keydown', (e) => { // Esc here means Cancel; it must not close the panel
    if (e.key !== 'Escape' || e.isComposing) return;
    e.preventDefault(); e.stopPropagation(); closeImport(true);
  });
  forgetBtn.addEventListener('click', () => { if (forgetBox.hidden) openForget(); else closeForget(true); });
  forgetIn.addEventListener('input', () => { forgetYes.disabled = !typedForget() || S.forgetBusy; });
  forgetIn.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); forgetAll(); } });
  forgetNo.addEventListener('click', () => { if (pressable(forgetNo)) closeForget(true); });
  forgetYes.addEventListener('click', forgetAll);
  forgetBox.addEventListener('keydown', (e) => { // Esc here means Keep
    if (e.key !== 'Escape' || e.isComposing) return;
    e.preventDefault(); e.stopPropagation(); closeForget(true);
  });
  if (refreshBtn) refreshBtn.addEventListener('click', () => { if (pressable(refreshBtn)) load(); });
  syncAdd();

  /** The panel is on screen: load it the first time, and again once it is a minute old. */
  function shown() {
    if (!S.signedIn || S.loading) return;
    if (S.data === undefined || Date.now() - S.fetchedAt > STALE_MS) load(); else render();
  }
  const JC = window.JarvisConsole;
  const brainNow = () => (JC && typeof JC.brain === 'function' ? obj(JC.brain()) : null);
  function signedIn() { S.signedIn = true; S.brain = brainNow() || S.brain; if (Deck.isOpen('memory')) shown(); }
  document.addEventListener('jarvis:ready', signedIn);
  // jarvis:ready fires once per sign-in, and this deferred script can arrive after it: ask too.
  const signedInAlready = JC && typeof JC.ready === 'function' ? JC.ready() : null;
  if (signedInAlready) signedIn();
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'memory' && d.open) shown(); });
  document.addEventListener('jarvis:brain', (e) => { S.brain = obj(e.detail); if (S.data) renderBrain(); });
  document.addEventListener('jarvis:reply', (e) => { // a reply that used tools may have saved or forgotten a fact
    const d = e.detail || {};
    if (!(d.tools > 0)) return;
    if (Deck.isOpen('memory') && S.data !== undefined) load(); else S.fetchedAt = 0;
  });
  render();
})();
