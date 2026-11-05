// src/jarvis/api/static/console-things.js -- R2 D11: the Things panel, "Where did I keep it?".
// A search box first, then the list; a quick add (What / Where); each row shows the place and when it
// was noted, with Moved..., History and Delete. Delete asks first (focus stays inside the dialog) and
// then offers Undo (Recently deleted keeps it 30 days). Everything is the owner's own text and is still
// untrusted: it reaches the page through textContent or an input's value, never as markup. No build
// step; CSP script-src 'self'; ASCII source with backslash-u escapes only. Transport is the console's
// api() (cookie + X-Requested-With, or the bearer token; 401 -> gate). Loads when the panel is shown.
// Mounts into #p-things .pbody (the panel shell is in console.html). Listens: jarvis:ready,
// jarvis:panel (Things shown), jarvis:reply (a tool may have noted or moved something).
// API: GET /v1/things?q= -> {available, reason?, things:[{id, name, place, note, holder, updated_at,
// moves, origin}], holders, total}; POST /v1/things {name, place} (adds or moves) -> {thing,
// previous_place, moved}; PATCH /v1/things/{id} {place, adopt?} ; DELETE /v1/things/{id} -> {undo_id}; GET /v1/things/{id}/
// history -> {earlier:[{place, from_at, to_at}]}; POST /v1/deleted/{undo_id}/restore.
(() => {
  'use strict';
  const panel = document.getElementById('p-things');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const THING_ID = /^t_[0-9a-f]{12}$/, UNDO_ID = /^del_[0-9a-f]{20}$/;
  // R2 review S3: how a line was noted. A move keeps it; only "This is mine" (adopt) makes it his.
  const ORIGINS = ['typed', 'voice', 'outside'];
  const HOW = { voice: 'said by voice', outside: 'from someone else\'s words' };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const STALE_MS = 60 * 1000, MAX_ROWS = 500, SEARCH_MS = 250;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const S = { data: undefined, q: '', loadedAt: 0, busy: false, timer: 0 };
  let list, stateEl, noteEl, qIn, nameIn, placeIn, addBtn, dlg, dlgText, dlgYes, dlgNo, countEl, settle = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const Deck = window.JarvisDeck || { isOpen: () => false };
  const quoted = (s) => '\u201c' + s + '\u201d';
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.getDate() + ' ' + MONTHS[d.getMonth()]; };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, text, undo) {
    noteEl.className = 'bnote tnote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    if (undo) {
      const b = mk('button', 'btn bact tundo', 'Undo'); b.type = 'button';
      b.addEventListener('click', () => restore(undo, b));
      noteEl.append(' ', b);
    }
  }

  /** GET /v1/things, checked field by field; anything odd is dropped. */
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    if (d.available !== true) return { available: false, reason: txt(d.reason, 200) || 'Not available on this server.', things: [], total: 0 };
    const seen = new Set();
    const things = arr(d.things).slice(0, MAX_ROWS).map((t) => {
      const it = obj(t);
      if (!it || typeof it.id !== 'string' || !THING_ID.test(it.id) || seen.has(it.id)) return null;
      seen.add(it.id);
      return { id: it.id, name: txt(it.name, 60) || '(no name)', place: txt(it.place, 200), holder: txt(it.holder, 40),
        at: txt(it.updated_at, 40), moves: Number.isInteger(it.moves) && it.moves > 0 ? it.moves : 0,
        origin: ORIGINS.includes(it.origin) ? it.origin : 'typed' };
    }).filter(Boolean);
    return { available: true, things, total: Number.isInteger(d.total) ? d.total : things.length };
  }

  // ---- build ------------------------------------------------------------------------------------
  function build() {
    const root = mk('div', 'things'); root.id = 'things';
    noteEl = mk('div', 'bnote tnote'); noteEl.id = 'thingsNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    const sl = mk('label', 'bl', 'Where did I keep\u2026'); sl.htmlFor = 'thingsSearch';
    qIn = mk('input', 'tin'); qIn.id = 'thingsSearch'; qIn.type = 'search'; qIn.maxLength = 200; qIn.placeholder = 'passport, spare keys, gold'; qIn.autocomplete = 'off';
    qIn.addEventListener('input', () => { clearTimeout(S.timer); S.timer = setTimeout(() => { S.q = qIn.value.trim(); load(true); }, SEARCH_MS); });
    const form = mk('form', 'tadd'); form.id = 'thingsAdd'; form.setAttribute('aria-label', 'Note where something is kept');
    nameIn = mk('input', 'tin'); nameIn.id = 'thingsName'; nameIn.maxLength = 60; nameIn.placeholder = 'What (passport)'; nameIn.setAttribute('aria-label', 'What');
    placeIn = mk('input', 'tin'); placeIn.id = 'thingsPlace'; placeIn.maxLength = 200; placeIn.placeholder = 'Where (blue file, top shelf)'; placeIn.setAttribute('aria-label', 'Where');
    addBtn = mk('button', 'btn lift bact', 'Save'); addBtn.type = 'submit'; addBtn.id = 'thingsSave';
    form.append(nameIn, placeIn, addBtn);
    form.addEventListener('submit', (e) => { e.preventDefault(); add(); });
    stateEl = mk('div', 'empty'); stateEl.id = 'thingsState'; stateEl.setAttribute('role', 'status');
    countEl = mk('p', 'bfine tcount'); countEl.id = 'thingsCount';
    list = mk('ul', 'tlist'); list.id = 'thingsList'; list.setAttribute('aria-label', 'Things and where they are kept');
    dlg = mk('dialog', 'bdialog'); dlg.id = 'thingsDialog'; dlg.setAttribute('role', 'alertdialog'); dlg.setAttribute('aria-labelledby', 'thingsDialogTitle');
    dlg.append(mk('h3', '', 'Forget where this is kept?'), (dlgText = mk('p', '')));
    dlg.firstChild.id = 'thingsDialogTitle';
    const row = mk('div', 'brow');
    dlgNo = mk('button', 'btn', 'Keep it'); dlgNo.type = 'button';
    dlgYes = mk('button', 'btn lift', 'Forget'); dlgYes.type = 'button';
    row.append(dlgNo, dlgYes); dlg.appendChild(row);
    dlgYes.addEventListener('click', () => settle && settle(true));
    dlgNo.addEventListener('click', () => settle && settle(false));
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const a = dlgNo, z = dlgYes;
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
    root.append(noteEl, sl, qIn, form, stateEl, countEl, list, dlg);
    host.appendChild(root);
  }
  function confirmForget(t, trigger) {
    if (typeof dlg.showModal !== 'function') return Promise.resolve(false);
    dlgText.textContent = quoted(t.name) + ' is no longer noted. It stays in Recently deleted for 30 days, so you can undo it.';
    return new Promise((resolve) => {
      settle = (v) => { settle = null; if (dlg.open) dlg.close(); if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true }); resolve(v); };
      dlg.showModal(); dlgNo.focus();
    });
  }

  // ---- render -----------------------------------------------------------------------------------
  function row(t) {
    const li = mk('li', 'trow'); li.dataset.id = t.id;
    const main = mk('div', 'ttxt');
    main.append(mk('b', 'tname', t.name), mk('span', 'tplace', t.place));
    const meta = [t.holder ? 'for ' + t.holder : '', t.at ? 'updated ' + when(t.at) : '', HOW[t.origin] || ''].filter(Boolean).join(' \u00b7 ');
    if (meta) main.appendChild(mk('small', 'tmeta', meta));
    const acts = mk('div', 'tacts');
    const mv = mk('button', 'btn bact', 'Moved\u2026'); mv.type = 'button'; mv.setAttribute('aria-label', 'Move ' + quoted(t.name));
    mv.addEventListener('click', () => moveForm(li, t, main));
    const hi = mk('button', 'btn bact', 'History'); hi.type = 'button'; hi.setAttribute('aria-label', 'History of ' + quoted(t.name));
    hi.addEventListener('click', () => history(li, t, hi));
    const de = mk('button', 'btn bact', 'Delete'); de.type = 'button'; de.setAttribute('aria-label', 'Delete ' + quoted(t.name));
    de.addEventListener('click', async () => { if (await confirmForget(t, de)) remove(t); });
    acts.append(mv, hi, de);
    li.append(main, acts);
    return li;
  }
  function render() {
    const d = S.data;
    list.textContent = ''; countEl.textContent = '';
    if (d === undefined) { stateEl.textContent = 'Your things load when this panel opens.'; return; }
    if (!d.available) { stateEl.textContent = d.reason; return; }
    stateEl.textContent = d.things.length ? '' : (S.q ? 'Nothing matches that.' : 'Nothing noted yet. Add what you keep, and where.');
    d.things.forEach((t) => list.appendChild(row(t)));
    if (d.things.length) countEl.textContent = S.q ? d.things.length + ' of ' + d.total : d.total + (d.total === 1 ? ' thing' : ' things');
  }
  function moveForm(li, t, main) {
    if (li.querySelector('.tmove')) return;
    const f = mk('form', 'tmove');
    const inp = mk('input', 'tin'); inp.maxLength = 200; inp.value = t.place; inp.setAttribute('aria-label', 'New place for ' + t.name);
    const ok = mk('button', 'btn lift bact', 'Save'); ok.type = 'submit';
    const no = mk('button', 'btn bact', 'Cancel'); no.type = 'button';
    no.addEventListener('click', () => { f.remove(); });
    f.append(inp, ok, no);
    let mine = null;
    if (HOW[t.origin]) { // not typed by him: he may take it as his own, never by default
      const w = mk('label', 'tmeta tadopt'); mine = mk('input'); mine.type = 'checkbox';
      w.append(mine, ' This is mine: I checked the name and note'); f.appendChild(w);
    }
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = { place: inp.value }; if (mine && mine.checked) body.adopt = true;
      try { const r = await api('/v1/things/' + t.id, { method: 'PATCH', body }); movedNote(r); await load(true); }
      catch (err) { say('bad', detailOf(err) || 'Couldn\'t save that. Please try again.'); }
    });
    main.appendChild(f); inp.focus(); inp.select();
  }
  function movedNote(r) {
    const d = obj(r), prev = d && txt(d.previous_place, 200);
    say('ok', d && d.moved && prev ? 'Moved. It was in ' + prev + '.' : 'Saved.');
  }
  async function history(li, t, btn) {
    const old = li.querySelector('.thist');
    if (old) { old.remove(); btn.setAttribute('aria-expanded', 'false'); return; }
    try {
      const r = obj(await api('/v1/things/' + t.id + '/history')) || {};
      const ul = mk('ul', 'thist'); ul.setAttribute('aria-label', 'Earlier places of ' + t.name);
      const items = arr(r.earlier).slice(0, 10);
      if (!items.length) ul.appendChild(mk('li', '', 'No earlier places.'));
      items.forEach((m) => { const e = obj(m) || {}; ul.appendChild(mk('li', '', txt(e.place, 200) + (e.from_at ? ' (' + when(e.from_at) + ' to ' + when(e.to_at) + ')' : ''))); });
      li.appendChild(ul); btn.setAttribute('aria-expanded', 'true');
    } catch (err) { say('bad', detailOf(err) || 'Couldn\'t load the history.'); }
  }

  // ---- actions ----------------------------------------------------------------------------------
  async function add() {
    if (S.busy || !hasApi()) return;
    S.busy = true; addBtn.setAttribute('aria-disabled', 'true');
    try {
      const r = await api('/v1/things', { method: 'POST', body: { name: nameIn.value, place: placeIn.value } });
      movedNote(r); nameIn.value = ''; placeIn.value = ''; nameIn.focus();
      await load(true);
    } catch (e) { say('bad', detailOf(e) || 'Couldn\'t save that. Please try again.'); }
    finally { S.busy = false; addBtn.removeAttribute('aria-disabled'); }
  }
  async function remove(t) {
    try {
      const r = obj(await api('/v1/things/' + t.id, { method: 'DELETE' }));
      const undo = r && typeof r.undo_id === 'string' && UNDO_ID.test(r.undo_id) ? r.undo_id : '';
      say('ok', quoted(t.name) + ' removed.', undo);
      await load(true);
    } catch (e) { say('bad', detailOf(e) || 'Couldn\'t remove it. Please try again.'); }
  }
  async function restore(undoId, btn) {
    btn.disabled = true;
    try { await api('/v1/deleted/' + undoId + '/restore', { method: 'POST' }); say('ok', 'Restored.'); await load(true); }
    catch (e) { say('bad', detailOf(e) || 'Couldn\'t undo that. Try Recently deleted.'); }
  }
  async function load(force) {
    if (!hasApi()) return;
    if (!force && S.data !== undefined && Date.now() - S.loadedAt < STALE_MS) return;
    try {
      const path = '/v1/things' + (S.q ? '?q=' + encodeURIComponent(S.q) : '');
      S.data = normal(await api(path)) || { available: false, reason: 'Not available on this server.', things: [], total: 0 };
      S.loadedAt = Date.now();
    } catch (e) {
      if (e && e.status === 401) return;
      say('bad', detailOf(e) || 'Couldn\'t load your things. Please try again.');
    }
    render();
  }

  build(); render();
  const shown = () => { if (Deck.isOpen('things')) load(false); };
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'things' && d.open) load(false); });
  document.addEventListener('jarvis:reply', () => { if (Deck.isOpen('things') && S.data !== undefined) load(true); else S.loadedAt = 0; });
  document.addEventListener('jarvis:ready', shown);
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) shown();
  window.JarvisThings = Object.freeze({ refresh: () => load(true), normal });
})();
