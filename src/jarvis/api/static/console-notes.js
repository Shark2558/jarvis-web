// src/jarvis/api/static/console-notes.js -- the Notes panel (R2 D10, docs/plans/r2-memory-vault.md).
// Notes, voice-memo transcripts and saved links. No build step; CSP script-src 'self'.
// Everything here is the owner's data and other people's words (saved page text): every server
// string reaches the page through textContent or a form control's .value, never as markup. A link
// opens in a new tab (rel noopener noreferrer nofollow) only when it is https; the host is shown as
// the server gives it (punycode stays punycode).
// The panel shell (#p-notes with a .pbody holding <div id="notes">) comes from console.html; this
// file builds everything inside #notes. It loads when the panel is shown (each GET costs reads).
// Transport: window.JarvisConsole.api (cookie + X-Requested-With, or the bearer token).
// API: GET /v1/notes?q=&kind=&page=; POST /v1/notes; PATCH and DELETE /v1/notes/{id};
// POST /v1/notes/{id}/fetch {confirm_credit}; GET /v1/notes/export; POST /v1/notes/import {data};
// POST /v1/deleted/{undo_id}/restore. Errors: {error, detail, reason?}.
// Exposes window.JarvisNotes {save(body), flash(kind, text), refresh()} for console-notes-memo.js.
// Listens: jarvis:ready, jarvis:panel (Notes shown), jarvis:reply (a tool may have saved a note).
(() => {
  'use strict';
  const root = document.getElementById('notes');
  if (!root) return;
  const KINDS = { note: 'Note', memo: 'Memo', link: 'Link' };
  const FILTERS = [['', 'All'], ['note', 'Notes'], ['memo', 'Memos'], ['link', 'Links']];
  const ORIGIN_WORDS = { voice: 'Saved by voice', outside: 'Saved from outside content' };
  const NOTE_MS = 5000, STALE_MS = 60 * 1000, TEXT_MAX = 4000, NOTE_MAX = 1000, IMPORT_MAX = 2 * 1024 * 1024;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 400) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const body = (v, max) => (typeof v === 'string' ? v.replace(INVISIBLE, '').slice(0, max) : '');
  const own = (map, key) => (typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  function button(id, cls, text, onClick) {
    const b = mk('button', 'btn lift bact' + (cls ? ' ' + cls : ''), text); b.type = 'button'; if (id) b.id = id;
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(b); });
    return b;
  }
  const busyAttr = (el, on) => { if (on) el.setAttribute('aria-disabled', 'true'); else el.removeAttribute('aria-disabled'); };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const detailOf = (e) => {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'Please try again.';
  };
  function day(iso) {
    const d = new Date(iso || NaN);
    if (isNaN(d)) return '';
    const o = d.getFullYear() === new Date().getFullYear() ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' };
    try { return new Intl.DateTimeFormat([], o).format(d); } catch (_) { return ''; }
  }
  /** An https address only: anything else is shown as text and never becomes a link. */
  function safeHref(u) { try { const x = new URL(u); return x.protocol === 'https:' && !x.username && !x.password ? x.href : ''; } catch (_) { return ''; } }

  // ---- what the server sends, checked field by field ---------------------------------------------
  function note(v) {
    const o = obj(v);
    const id = o && typeof o.id === 'string' && /^n_[0-9a-f]{12}$/.test(o.id) ? o.id : '';
    const kind = o && own(KINDS, o.kind) ? o.kind : '';
    if (!id || !kind) return null;
    const pg = obj(o.page);
    return { id, kind, title: txt(o.title, 160) || '(untitled)', text: body(o.text, TEXT_MAX + 50),
      tags: arr(o.tags).map(t => txt(t, 30)).filter(Boolean).slice(0, 8), origin: txt(o.origin, 20),
      url: txt(o.url, 2048), host: txt(o.host, 255), ownerNote: body(o.owner_note, NOTE_MAX + 50),
      page: pg ? { title: txt(pg.title, 200), excerpt: body(pg.excerpt, 6100), at: txt(pg.fetched_at, 40) } : null,
      trusted: o.trusted === true, snippet: txt(o.snippet, 400), updated: txt(o.updated_at, 40) };
  }
  function normal(r) {
    const o = obj(r);
    if (!o) return null;
    const c = obj(o.counts) || {};
    const n = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    return { available: o.available !== false, reason: txt(o.reason, 300), items: arr(o.items).map(note).filter(Boolean),
      total: n(o.total), page: Math.max(1, n(o.page)), pages: Math.max(1, n(o.pages)),
      counts: { note: n(c.note), memo: n(c.memo), link: n(c.link) } };
  }

  // ---- state -------------------------------------------------------------------------------------
  const S = { data: null, error: '', loading: false, seq: 0, fetchedAt: 0, signedIn: false, q: '', kind: '', page: 1,
    open: null, edit: null, form: null, busy: new Set(), undo: null, noteTimer: 0, confirmDel: null, shown: false };

  async function load() {
    if (!hasApi()) return;
    const seq = ++S.seq; S.loading = true; render();
    const qs = new URLSearchParams();
    if (S.q) qs.set('q', S.q); if (S.kind) qs.set('kind', S.kind); if (S.page > 1) qs.set('page', String(S.page));
    try {
      const d = normal(await api('/v1/notes' + (qs.toString() ? '?' + qs : '')));
      if (seq !== S.seq) return;
      S.data = d; S.error = d ? '' : 'JARVIS sent notes it could not read.'; S.fetchedAt = Date.now();
    } catch (e) {
      if (seq !== S.seq) return;
      if (e && e.status === 401) return;
      S.error = detailOf(e);
    } finally { if (seq === S.seq) { S.loading = false; render(); } }
  }

  // ---- notices -----------------------------------------------------------------------------------
  const noteEl = mk('div', 'bnote mlive'); noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
  function flash(kind, text) {
    clearTimeout(S.noteTimer);
    noteEl.textContent = kind ? text : ''; noteEl.className = 'bnote mlive' + (kind ? ' ' + kind : '');
    if (kind === 'ok') S.noteTimer = setTimeout(() => flash(null), NOTE_MS);
  }

  // ---- confirm dialog: native modal, so the rest of the page is inert and Tab stays inside --------
  function ask(trigger, title, lines, yesText, danger) {
    const dlg = mk('dialog', 'bdialog'); dlg.setAttribute('role', 'alertdialog');
    const h = mk('h2', '', title), b = mk('div');
    lines.forEach(l => b.append(mk('p', '', l)));
    const no = mk('button', 'btn lift', 'Not now'), yes = mk('button', 'btn ' + (danger ? 'danger' : 'primary') + ' lift', yesText);
    no.type = yes.type = 'button';
    const acts = mk('div', 'actions'); acts.append(no, yes);
    dlg.append(h, b, acts); root.append(dlg);
    return new Promise(resolve => {
      const done = (v) => { if (dlg.open) dlg.close(); dlg.remove(); if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true }); resolve(v); };
      yes.addEventListener('click', () => done(true)); no.addEventListener('click', () => done(false));
      dlg.addEventListener('cancel', (e) => { e.preventDefault(); done(false); });
      dlg.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;
        const first = no, last = yes;
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      });
      if (typeof dlg.showModal !== 'function') { done(false); return; }
      dlg.showModal(); no.focus();
    });
  }

  // ---- actions -----------------------------------------------------------------------------------
  function refusal(e) {
    if (e && e.status === 422 && e.code === 'sensitive') return 'JARVIS doesn\'t keep that. IDs go in the Vault; JARVIS doesn\'t keep passwords or card numbers.';
    return detailOf(e);
  }
  async function save(payload) {
    const n = await api('/v1/notes', { method: 'POST', body: payload });
    S.q = ''; S.kind = ''; S.page = 1;
    await load();
    return n;
  }
  async function submitForm(kind) {
    const f = S.form; if (!f || f.busy) return;
    const payload = { kind };
    if (kind === 'link') Object.assign(payload, { url: f.url.trim(), title: f.title.trim() || undefined, owner_note: f.note.trim() });
    else Object.assign(payload, { text: f.text, title: f.title.trim() || undefined });
    const tags = f.tags.split(',').map(t => t.trim()).filter(Boolean);
    if (tags.length) payload.tags = tags;
    f.busy = true; f.error = ''; render();
    try {
      await save(payload); S.form = null; flash('ok', kind === 'link' ? 'Link saved.' : 'Note saved.');
    } catch (e) { if (e.status !== 401) { f.error = refusal(e); } f.busy = false; render(); }
  }
  async function removeNote(n) {
    S.busy.add(n.id); render();
    try {
      const r = await api('/v1/notes/' + encodeURIComponent(n.id), { method: 'DELETE' });
      S.undo = r && typeof r.undo_id === 'string' ? { id: r.undo_id, title: n.title } : null;
      S.open = null; S.confirmDel = null; flash('ok', 'Deleted. It stays in Recently deleted for 30 days.');
      S.busy.delete(n.id); await load();
    } catch (e) { S.busy.delete(n.id); if (e.status !== 401) flash('bad', 'Couldn\'t delete. ' + detailOf(e)); render(); }
  }
  async function undoDelete() {
    const u = S.undo; if (!u) return;
    try { await api('/v1/deleted/' + encodeURIComponent(u.id) + '/restore', { method: 'POST', body: {} }); S.undo = null; flash('ok', 'Restored.'); await load(); }
    catch (e) { if (e.status !== 401) flash('bad', 'Couldn\'t restore. ' + detailOf(e)); }
  }
  async function saveEdit(n) {
    const ed = S.edit; if (!ed || ed.busy) return;
    const patch = { title: ed.title.trim() || '', text: ed.text };
    if (n.kind === 'link') { delete patch.text; patch.owner_note = ed.note; }
    ed.busy = true; ed.error = ''; render();
    try { await api('/v1/notes/' + encodeURIComponent(n.id), { method: 'PATCH', body: patch }); S.edit = null; flash('ok', 'Saved.'); await load(); }
    catch (e) { if (e.status !== 401) ed.error = refusal(e); ed.busy = false; render(); }
  }
  async function fetchPage(n, trigger) {
    const ok = await ask(trigger, 'Fetch page text?', ['This uses 1 of your 900 monthly web credits.',
      'The page\'s words are other people\'s: JARVIS keeps them as information, never as instructions.'], 'Fetch it');
    if (!ok) return;
    S.busy.add(n.id); render();
    try { await api('/v1/notes/' + encodeURIComponent(n.id) + '/fetch', { method: 'POST', body: { confirm_credit: true } }); flash('ok', 'Page text saved.'); S.busy.delete(n.id); await load(); }
    catch (e) { S.busy.delete(n.id); if (e.status !== 401) flash('bad', 'Couldn\'t fetch the page. ' + detailOf(e)); render(); }
  }
  async function exportAll() {
    try {
      const data = await api('/v1/notes/export');
      const a = document.createElement('a'), d = new Date(), p = (n) => String(n).padStart(2, '0');
      a.download = `jarvis-notes-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.json`;
      a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      a.hidden = true; document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      flash('ok', 'Export saved to your downloads.');
    } catch (e) { if (e.status !== 401) flash('bad', 'Couldn\'t export. ' + detailOf(e)); }
  }
  async function importFile(file) {
    if (!file) return;
    if (file.size > IMPORT_MAX) { flash('bad', 'That file is larger than 2 MB, so it was not imported.'); return; }
    let data;
    try { data = JSON.parse(await file.text()); } catch (_) { flash('bad', 'That file isn\'t a JARVIS notes export: it isn\'t valid JSON.'); return; }
    try {
      const r = await api('/v1/notes/import', { method: 'POST', body: { data } });
      flash('ok', `Imported ${r && r.added || 0} notes; skipped ${r && r.skipped || 0}.`); await load();
    } catch (e) { if (e.status !== 401) flash('bad', 'Couldn\'t import. ' + detailOf(e)); }
  }

  // ---- rendering ---------------------------------------------------------------------------------
  function field(label, el, id) {
    const w = mk('div', 'nfield'); const l = mk('label', 'bl', label); l.htmlFor = id; el.id = id; w.append(l, el); return w;
  }
  function input(value, onInput, max, ph) {
    const i = mk('input', 'minput'); i.type = 'text'; i.value = value; i.maxLength = max; if (ph) i.placeholder = ph;
    i.addEventListener('input', () => onInput(i.value)); return i;
  }
  function area(value, onInput, max, rows) {
    const t = mk('textarea', 'mta'); t.value = value; t.rows = rows || 4; t.maxLength = max;
    t.addEventListener('input', () => onInput(t.value)); return t;
  }
  function formView(kind) {
    const f = S.form, w = mk('form', 'nform'); w.setAttribute('aria-label', kind === 'link' ? 'Save a link' : 'Add a note');
    if (kind === 'link') {
      w.append(field('Web address (https)', input(f.url, v => { f.url = v; }, 2048, 'https://'), 'nfUrl'),
        field('Title (optional)', input(f.title, v => { f.title = v; }, 120), 'nfTitle'),
        field('Why you saved it (optional)', area(f.note, v => { f.note = v; }, NOTE_MAX, 2), 'nfNote'));
    } else {
      w.append(field('Note', area(f.text, v => { f.text = v; }, TEXT_MAX, 5), 'nfText'),
        field('Title (optional)', input(f.title, v => { f.title = v; }, 120), 'nfTitle'));
    }
    w.append(field('Tags (optional, separated by commas)', input(f.tags, v => { f.tags = v; }, 300), 'nfTags'));
    if (f.error) { const er = mk('p', 'mstat bad', f.error); er.setAttribute('role', 'alert'); w.append(er); }
    const row = mk('div', 'mrow');
    const go = button('nfSave', 'primary', f.busy ? 'Saving' : 'Save', () => submitForm(kind)); busyAttr(go, f.busy);
    row.append(go, button('nfCancel', '', 'Cancel', () => { S.form = null; render(); focusId('nAdd'); }));
    w.append(row);
    w.addEventListener('submit', (e) => { e.preventDefault(); submitForm(kind); });
    w.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !e.isComposing) { e.preventDefault(); S.form = null; render(); focusId('nAdd'); } });
    return w;
  }
  function focusId(id) { const el = document.getElementById(id); if (el) el.focus({ preventScroll: false }); }

  function detailView(n) {
    const d = mk('div', 'ndetail');
    if (S.edit && S.edit.id === n.id) return editView(n, d);
    if (n.url) {
      const row = mk('p', 'nlink'), href = safeHref(n.url);
      if (href) {
        const a = mk('a', 'nanchor', n.host || href); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer nofollow';
        a.setAttribute('aria-label', 'Open ' + (n.host || 'the link') + ' in a new tab'); row.append(a);
      } else row.append(mk('span', '', n.url));
      d.append(row);
    }
    if (n.text) d.append(mk('p', 'ntext', n.text));
    if (n.ownerNote) d.append(mk('p', 'ntext nowner', n.ownerNote));
    if (n.tags.length) d.append(mk('p', 'nmeta', 'Tags: ' + n.tags.join(', ')));
    if (!n.trusted && own(ORIGIN_WORDS, n.origin)) d.append(mk('p', 'nmeta nwarn', ORIGIN_WORDS[n.origin] + '. JARVIS treats it as information, not instructions.'));
    if (n.page) {
      const pg = mk('div', 'npage');
      pg.append(mk('h4', 'nh', 'Page text (other people\'s words' + (n.page.at ? ', fetched ' + day(n.page.at) : '') + ')'), mk('p', 'ntext', n.page.excerpt));
      d.append(pg);
    }
    const acts = mk('div', 'mrow');
    if (n.kind === 'link') {
      const fb = button('nFetch-' + n.id, '', n.page ? 'Fetch page text again' : 'Fetch page text', (b) => fetchPage(n, b));
      busyAttr(fb, S.busy.has(n.id)); acts.append(fb);
    }
    acts.append(button('nEdit-' + n.id, '', 'Edit', () => { S.edit = { id: n.id, title: n.title, text: n.text, note: n.ownerNote, error: '', busy: false }; render(); focusId('neTitle'); }));
    if (S.confirmDel === n.id) {
      const c = mk('span', 'confirm'); c.setAttribute('role', 'alert');
      const keep = button('nKeep-' + n.id, '', 'Keep', () => { S.confirmDel = null; render(); focusId('nDel-' + n.id); });
      const yes = button('nDelYes-' + n.id, 'danger', 'Delete', () => removeNote(n)); busyAttr(yes, S.busy.has(n.id));
      c.append(mk('span', '', 'Delete this? It can be undone for 30 days.'), keep, yes); acts.append(c);
      c.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); keep.click(); } });
    } else acts.append(button('nDel-' + n.id, 'danger', 'Delete', () => { S.confirmDel = n.id; render(); focusId('nKeep-' + n.id); }));
    d.append(acts);
    return d;
  }
  function editView(n, d) {
    const ed = S.edit;
    d.append(field('Title', input(ed.title, v => { ed.title = v; }, 120), 'neTitle'));
    if (n.kind === 'link') d.append(field('Why you saved it', area(ed.note, v => { ed.note = v; }, NOTE_MAX, 2), 'neNote'));
    else d.append(field('Text', area(ed.text, v => { ed.text = v; }, TEXT_MAX, 6), 'neText'));
    if (ed.error) { const er = mk('p', 'mstat bad', ed.error); er.setAttribute('role', 'alert'); d.append(er); }
    const row = mk('div', 'mrow'), go = button('neSave', 'primary', ed.busy ? 'Saving' : 'Save', () => saveEdit(n)); busyAttr(go, ed.busy);
    row.append(go, button('neCancel', '', 'Cancel', () => { S.edit = null; render(); focusId('nOpen-' + n.id); }));
    d.append(row);
    return d;
  }
  function rowView(n) {
    const li = mk('li', 'nrow' + (S.open === n.id ? ' open' : ''));
    const head = mk('button', 'nhead'); head.type = 'button'; head.id = 'nOpen-' + n.id;
    head.setAttribute('aria-expanded', S.open === n.id ? 'true' : 'false');
    head.addEventListener('click', () => { S.open = S.open === n.id ? null : n.id; S.edit = null; S.confirmDel = null; render(); focusId(head.id); });
    const title = mk('span', 'nt', n.title), meta = mk('span', 'nm', `${KINDS[n.kind]}${n.host ? ' - ' + n.host : ''} - ${day(n.updated)}`);
    head.append(title, meta);
    if (S.open !== n.id) {
      const sn = n.snippet || (n.text ? n.text.slice(0, 160) : n.ownerNote.slice(0, 160));
      if (sn) head.append(mk('span', 'nsn', sn));
    }
    li.append(head);
    if (S.open === n.id) li.append(detailView(n));
    return li;
  }

  function toolbar() {
    const bar = mk('div', 'ntools');
    const sf = mk('form', 'nsearch'); sf.setAttribute('role', 'search');
    const q = mk('input', 'minput'); q.type = 'search'; q.id = 'nSearch'; q.value = S.q; q.maxLength = 200;
    q.placeholder = 'Search your notes'; q.setAttribute('aria-label', 'Search your notes');
    sf.append(q); sf.addEventListener('submit', (e) => { e.preventDefault(); S.q = q.value.trim(); S.page = 1; load(); });
    const chips = mk('div', 'nchips'); chips.setAttribute('role', 'group'); chips.setAttribute('aria-label', 'Show');
    FILTERS.forEach(([k, label]) => {
      const c = mk('button', 'nchip' + (S.kind === k ? ' on' : ''), label); c.type = 'button'; c.setAttribute('aria-pressed', S.kind === k ? 'true' : 'false');
      c.addEventListener('click', () => { S.kind = k; S.page = 1; load(); }); chips.append(c);
    });
    const acts = mk('div', 'mrow nacts'); acts.id = 'notesActions';
    acts.append(button('nAdd', 'primary', 'Add note', () => { S.form = { kind: 'note', text: '', title: '', tags: '', error: '', busy: false }; render(); focusId('nfText'); }),
      button('nAddLink', '', 'Save link', () => { S.form = { kind: 'link', url: '', title: '', note: '', tags: '', error: '', busy: false }; render(); focusId('nfUrl'); }));
    const slot = mk('span', 'nrecord'); slot.id = 'notesRecordSlot'; acts.append(slot);
    bar.append(sf, chips, acts);
    return bar;
  }
  function footer() {
    const det = mk('details', 'nfoot'), sum = mk('summary', '', 'Export and import');
    const row = mk('div', 'mrow');
    const file = mk('input'); file.type = 'file'; file.accept = 'application/json,.json'; file.hidden = true; file.id = 'nImportFile';
    file.addEventListener('change', () => { importFile(file.files && file.files[0]); file.value = ''; });
    row.append(button('nExport', '', 'Export notes', exportAll), button('nImport', '', 'Import notes', () => file.click()), file);
    det.append(sum, mk('p', 'bfine', 'Export saves all your notes, memos and links (and any fetched page text) as one file. Import adds a file made this way; anything that looks like an ID, card number or password is skipped.'), row);
    return det;
  }
  function render() {
    const keepSearch = document.activeElement && document.activeElement.id === 'nSearch' ? document.getElementById('nSearch').value : null;
    root.textContent = '';
    root.setAttribute('aria-busy', S.loading ? 'true' : 'false');
    root.append(noteEl);
    const d = S.data;
    if (!d) {
      root.append(mk('div', 'empty', S.error || (S.loading ? 'Loading your notes' : 'Your notes load when this panel opens.')));
      return;
    }
    if (!d.available) { root.append(mk('div', 'empty', d.reason || 'Notes are not available on this server (no encryption key).')); return; }
    if (S.undo) {
      const u = mk('p', 'nundo', 'Deleted a note. '); u.append(button('nUndo', '', 'Undo', undoDelete)); root.append(u);
    }
    root.append(toolbar());
    if (S.form) root.append(formView(S.form.kind));
    if (S.error) { const er = mk('p', 'mstat bad', S.error); er.setAttribute('role', 'alert'); root.append(er); }
    if (!d.items.length) {
      root.append(mk('div', 'empty', S.q ? 'Nothing matches that. Try other words.' : 'Nothing saved yet. Add a note, save a link, or say "take a note".'));
    } else {
      const ul = mk('ul', 'nlist'); d.items.forEach(n => ul.append(rowView(n))); root.append(ul);
    }
    if (!S.q && d.pages > 1) {
      const pg = mk('div', 'mrow npages');
      const prev = button('nPrev', '', 'Newer', () => { S.page = Math.max(1, S.page - 1); load(); }); busyAttr(prev, d.page <= 1);
      const next = button('nNext', '', 'Older', () => { S.page += 1; load(); }); busyAttr(next, d.page >= d.pages);
      pg.append(prev, mk('span', 'mcount', `Page ${d.page} of ${d.pages}`), next); root.append(pg);
    }
    root.append(footer());
    window.dispatchEvent(new CustomEvent('jarvis:notes-rendered'));
    if (keepSearch !== null) { const el = document.getElementById('nSearch'); if (el) { el.focus(); el.setSelectionRange(keepSearch.length, keepSearch.length); } }
  }

  // ---- lifecycle ---------------------------------------------------------------------------------
  function shown() { S.shown = true; if (!S.data || Date.now() - S.fetchedAt > STALE_MS) load(); }
  function signedIn() { S.signedIn = true; if (S.shown) load(); }
  window.JarvisNotes = Object.freeze({ save, flash, refresh: load });
  document.addEventListener('jarvis:ready', signedIn);
  if (hasApi() && window.JarvisConsole.ready && window.JarvisConsole.ready()) S.signedIn = true;
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'notes') { if (d.open) shown(); else S.shown = false; } });
  document.addEventListener('jarvis:reply', () => { if (S.shown && S.data && !S.form && !S.edit) load(); else S.fetchedAt = 0; });
  render();
})();
