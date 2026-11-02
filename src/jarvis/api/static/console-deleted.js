// src/jarvis/api/static/console-deleted.js — slice 11 D1 (docs/plans/phase2-slice11-full-control.md):
// "Recently deleted" in the Approvals panel (a collapsed section above Permissions, built here so the
// page markup stays untouched) and the Undo chip under a reply that deleted something. No build step;
// CSP script-src 'self'; every server string reaches the page through textContent (never markup); a
// field of the wrong type is dropped, never guessed. Transport is the console's api() (window.
// JarvisConsole: cookie + X-Requested-With, or the bearer token; 401 → gate).
// API: GET /v1/deleted → {items: [{id, kind, title, deleted_at, expires_at, restored}], kept_days};
// POST /v1/deleted/{id}/restore → {status: restored | already_restored, message, title, …}, or
// {error, detail}: 404 not_found, 410 expired, 409 busy / still_there, 503 unavailable,
// 502 restore_failed. DELETE /v1/deleted/{id} ("Remove now", asked twice) → {removed, id} | 404.
//   window.JarvisDeleted  chips(row, undo) — console.js calls it for a fresh reply's `undo`
//     ([{undo_id, kind}]): one Undo chip per delete in the reply's meta line. The chip's title comes
//     from the list (plain text); a click restores the item and the chip then says "Restored". Why a
//     restore didn't happen (failed, expired, busy) is said in words next to the chip (aria-live).
//   refresh() — reload the list (also on sign-in, when Approvals opens, after a reply with undo).
// Keyboard focus survives a re-render of the list (the row's button, else the row itself), and chips
// gone from the page are dropped from the registry.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const ID = /^del_[0-9a-f]{20}$/;
  const KINDS = { event: 'Event', task: 'To-do' };
  const WORDS = { event: 'event', task: 'to-do' };
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const STALE_MS = 60 * 1000;
  const OPEN_KEY = 'jarvis_deleted_open';
  const MAX_ITEMS = 50;
  const FAILED = 'Couldn\'t restore it. Try again in a moment.';
  const NOT_REMOVED = 'Couldn\'t remove it. Try again in a moment.';
  const NOT_HERE = 'Recently deleted isn\'t available on this server: deletes always ask first here.';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const CONFIRM_MS = 5000;
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const S = { items: undefined, kept: 30, error: '', loadedAt: 0, loading: null, busy: new Set(), errs: {}, confirm: '', confirmTimer: 0 };
  const chipsById = new Map(); // undo id → the chips that restore it (pruned when they leave the page)
  let msgSeq = 0;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  function svg(paths) {
    const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.6'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => s.setAttribute(k, v));
    paths.forEach(d => { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); s.appendChild(p); });
    return s;
  }
  const UNDO_PATHS = ['M7.5 5 4 8.5 7.5 12', 'M4.5 8.5H12a4 4 0 0 1 0 8H9'];
  const BIN_PATHS = ['M4 6h12M8 6V4.5h4V6M6 6l.7 10h6.6L14 6', 'M8.5 9v4.5M11.5 9v4.5'];
  const CHEV_PATHS = ['M6.5 8 10 11.5 13.5 8'];
  const CHECK_PATHS = ['m5 10.5 3.2 3.2L15 7'];
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function fmt(iso, opts) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], opts).format(d); } catch (_) { return ''; }
  }
  const when = (iso) => fmt(iso, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const day = (iso) => fmt(iso, { day: 'numeric', month: 'short' });

  /** GET /v1/deleted, checked field by field; anything odd is dropped. */
  function normal(data) {
    const d = obj(data) || {};
    const items = arr(d.items).slice(0, MAX_ITEMS).map((raw) => {
      const it = obj(raw);
      if (!it || typeof it.id !== 'string' || !ID.test(it.id) || !Object.prototype.hasOwnProperty.call(KINDS, it.kind)) return null;
      return { id: it.id, kind: it.kind, title: txt(it.title) || '(no title)', deleted: txt(it.deleted_at, 40),
        expires: txt(it.expires_at, 40), restored: it.restored === true };
    }).filter(Boolean);
    const kept = Number.isInteger(d.kept_days) && d.kept_days > 0 && d.kept_days < 1000 ? d.kept_days : 30;
    return { items, kept, available: d.available !== false };
  }

  // ---- the section in the Approvals panel ------------------------------------------------------
  let section = null, btn = null, body = null, sum = null, listEl = null, noteEl = null;
  function build() {
    const panel = document.querySelector('#p-approvals .pbody');
    if (!panel || section) return !!section;
    section = mk('section', 'bset'); section.id = 'delSet'; section.setAttribute('aria-labelledby', 'delSetBtn');
    const h = mk('h3', 'dhead');
    btn = mk('button', 'dsc'); btn.type = 'button'; btn.id = 'delSetBtn';
    btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-controls', 'delSetBody');
    const icon = svg(BIN_PATHS); icon.setAttribute('class', 'dgear');
    const chev = svg(CHEV_PATHS); chev.setAttribute('class', 'dchev');
    sum = mk('span', 'dsum'); sum.id = 'delSum';
    btn.append(icon, mk('span', 'dl', 'Recently deleted'), chev, sum);
    h.appendChild(btn);
    body = mk('div', 'dbody'); body.id = 'delSetBody'; body.hidden = true;
    noteEl = mk('div', 'bnote'); noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    const lead = mk('p', 'bfine plead', 'What JARVIS deleted for you. Restore brings one back as a new copy; an event comes back without its guests.');
    listEl = mk('div', ''); listEl.id = 'delList';
    body.append(noteEl, lead, listEl);
    section.append(h, body);
    const perm = $('permSet');
    if (perm && perm.parentNode === panel) panel.insertBefore(section, perm); else panel.appendChild(section);
    btn.addEventListener('click', () => expand(body.hidden, true));
    return true;
  }
  function expand(open, remember) {
    if (!build()) return;
    body.hidden = !open; sum.hidden = open;
    btn.setAttribute('aria-expanded', String(open));
    if (remember) store.set(OPEN_KEY, open ? '1' : '0');
    if (open && stale()) load(); else render();
  }
  const stale = () => S.items === undefined || Date.now() - S.loadedAt > STALE_MS;
  function note(kind, text) { if (!noteEl) return; noteEl.className = 'bnote' + (kind ? ' ' + kind : ''); noteEl.textContent = text || ''; }

  function summary() {
    if (!sum) return;
    if (S.items === undefined) { sum.textContent = S.error === NOT_HERE ? 'Not available here' : S.error ? 'Couldn\'t load' : ''; return; }
    const open = S.items.filter(i => !i.restored).length;
    sum.textContent = open ? `${open} ${open === 1 ? 'item' : 'items'} you can restore · kept ${S.kept} days` : `Nothing to restore · kept ${S.kept} days`;
  }
  /** Where keyboard focus is inside the list, so a re-render can put it back. */
  function focusedIn() {
    const a = document.activeElement;
    if (!listEl || !a || !listEl.contains(a)) return null;
    const li = a.closest('.drow');
    return li ? { id: li.dataset.id, act: a.dataset ? a.dataset.act || '' : '' } : null;
  }
  function refocus(f) {
    if (!f || !ID.test(f.id || '')) return;
    const li = listEl.querySelector(`.drow[data-id="${f.id}"]`);
    if (!li) { if (body && !body.hidden) btn.focus(); return; } // the row went: back to the section
    const target = (f.act && li.querySelector(`[data-act="${f.act}"]`)) || li.querySelector('button') || li;
    if (target === li) li.tabIndex = -1;
    target.focus();
  }
  function render() {
    summary();
    labelChips();
    if (!listEl || body.hidden) return;
    const f = focusedIn();
    listEl.replaceChildren();
    if (S.items === undefined) {
      if (!S.error) { listEl.appendChild(mk('div', 'empty', 'Loading…')); return; }
      listEl.appendChild(mk('div', 'empty', S.error));
      if (S.error === NOT_HERE) return; // nothing to retry
      const retry = mk('button', 'btn lift retry', 'Retry'); retry.type = 'button';
      retry.addEventListener('click', () => { retry.disabled = true; load(); });
      listEl.appendChild(retry);
      return;
    }
    if (!S.items.length) { listEl.appendChild(mk('div', 'empty', `Nothing deleted in the last ${S.kept} days.`)); return; }
    const ul = mk('ul', 'dlist');
    S.items.forEach(it => ul.appendChild(row(it)));
    listEl.appendChild(ul);
    refocus(f);
  }
  function row(it) {
    const li = mk('li', 'drow'); li.dataset.id = it.id;
    const t = mk('div', 'btxt');
    const b = mk('b', '', it.title); b.title = it.title;
    const bits = [KINDS[it.kind], it.deleted && `deleted ${when(it.deleted)}`, !it.restored && it.expires && `kept until ${day(it.expires)}`];
    t.append(b, mk('small', '', bits.filter(Boolean).join(' · ')));
    li.appendChild(t);
    const acts = mk('div', 'dacts');
    if (it.restored) {
      const p = mk('span', 'dpill'); p.append(svg(CHECK_PATHS), mk('span', '', 'Restored')); acts.appendChild(p);
    } else {
      const go = mk('button', 'btn lift bact', S.busy.has(it.id) ? 'Restoring…' : 'Restore'); go.type = 'button';
      go.dataset.act = 'restore';
      go.setAttribute('aria-label', `Restore ${WORDS[it.kind]} “${it.title}”`);
      if (S.busy.has(it.id)) go.setAttribute('aria-disabled', 'true');
      go.addEventListener('click', () => restore(it.id));
      acts.appendChild(go);
    }
    acts.appendChild(removeButton(it));
    li.appendChild(acts);
    const err = mk('p', 'lerr', S.errs[it.id] || ''); err.setAttribute('role', 'alert');
    li.appendChild(err);
    return li;
  }
  /** "Remove now": the copy goes for good, so the first click only asks ("Remove for good?"). */
  function removeButton(it) {
    const asking = S.confirm === it.id;
    const rm = mk('button', 'btn lift bdel' + (asking ? ' ask' : ''), asking ? 'Remove for good?' : 'Remove now');
    rm.type = 'button'; rm.dataset.act = 'remove';
    rm.setAttribute('aria-label', asking ? `Remove “${it.title}” for good: it can't be restored after`
      : `Remove ${WORDS[it.kind]} “${it.title}” from Recently deleted now`);
    if (S.busy.has(it.id)) rm.setAttribute('aria-disabled', 'true');
    rm.addEventListener('click', () => { if (rm.getAttribute('aria-disabled') !== 'true') removeNow(it.id); });
    return rm;
  }
  async function removeNow(id) {
    if (!ID.test(id) || S.busy.has(id) || !hasApi()) return;
    clearTimeout(S.confirmTimer);
    if (S.confirm !== id) { // first click: ask, and stop asking after a few seconds
      S.confirm = id; render();
      S.confirmTimer = setTimeout(() => { if (S.confirm === id) { S.confirm = ''; render(); } }, CONFIRM_MS);
      return;
    }
    S.confirm = ''; S.busy.add(id); delete S.errs[id]; note('', ''); render();
    try {
      await api(`/v1/deleted/${encodeURIComponent(id)}`, { method: 'DELETE' });
      S.items = (S.items || []).filter(i => i.id !== id);
      note('ok', 'Removed from Recently deleted.'); log('info', 'Removed from Recently deleted');
      chipState(id, 'gone', 'Removed from Recently deleted: it can no longer be undone.');
    } catch (e) {
      S.errs[id] = detailOf(e) || NOT_REMOVED;
      if (e && e.status === 404) S.loadedAt = 0;
    } finally {
      S.busy.delete(id);
      if (stale()) await load(); else render();
    }
  }

  async function load() {
    if (!hasApi()) return;
    if (S.loading) return S.loading;
    S.loading = (async () => {
      try {
        const d = normal(await api('/v1/deleted'));
        if (!d.available) { S.items = undefined; S.error = NOT_HERE; S.loadedAt = Date.now(); return; }
        S.items = d.items; S.kept = d.kept; S.error = ''; S.loadedAt = Date.now();
      } catch (e) {
        if (e && e.status === 401) return; // the sign-in gate's job
        S.items = undefined; S.error = e && e.status === 404 ? NOT_HERE : 'Couldn\'t load Recently deleted.';
      } finally { S.loading = null; render(); }
    })();
    return S.loading;
  }

  // ---- restoring: from a row or from a reply's Undo chip -----------------------------------------
  function titleOf(id) { const it = (S.items || []).find(i => i.id === id); return it ? it.title : ''; }
  async function restore(id) {
    if (!ID.test(id) || S.busy.has(id) || !hasApi()) return false;
    S.busy.add(id); delete S.errs[id]; note('', ''); render(); chipState(id, 'busy');
    let ok = false;
    try {
      const r = obj(await api(`/v1/deleted/${encodeURIComponent(id)}/restore`, { method: 'POST' })) || {};
      ok = r.status === 'restored' || r.status === 'already_restored';
      const name = txt(r.title) || titleOf(id);
      const it = (S.items || []).find(i => i.id === id); if (it && ok) it.restored = true;
      chipState(id, ok ? 'done' : 'bad', ok ? '' : FAILED);
      if (ok) { note('ok', txt(r.message, 300) || 'Restored.'); log('ok', `Restored${name ? ' · ' + name : ''}`); }
    } catch (e) {
      const msg = detailOf(e) || FAILED;
      S.errs[id] = msg; chipState(id, 'bad', msg);
      log('error', 'Restore failed');
      if (e && (e.status === 404 || e.status === 410)) S.loadedAt = 0; // the list is out of date
    } finally {
      S.busy.delete(id);
      if (stale()) await load(); else render();
    }
    return ok;
  }

  /** Chips no longer on the page (a cleared or reloaded conversation) leave the registry. */
  function prune() {
    chipsById.forEach((list, id) => {
      const live = list.filter(c => c.isConnected);
      if (live.length) chipsById.set(id, live); else chipsById.delete(id);
    });
  }
  /** One Undo chip per undo-able delete in a fresh reply (console.js: handleResponse). Next to each,
   *  an aria-live line says in words why a restore didn't happen (failed, expired, busy). */
  function chips(rowEl, undo) {
    if (!rowEl) return [];
    prune();
    const refs = arr(undo).slice(0, 20).map(obj).filter(r => r && typeof r.undo_id === 'string' && ID.test(r.undo_id) &&
      Object.prototype.hasOwnProperty.call(KINDS, r.kind));
    if (!refs.length) return [];
    let meta = rowEl.querySelector('.meta');
    if (!meta) { meta = mk('div', 'meta'); rowEl.appendChild(meta); }
    const made = refs.map(r => {
      const c = mk('button', 'mchip uchip'); c.type = 'button'; c.dataset.undo = r.undo_id; c.dataset.kind = r.kind;
      c.append(svg(UNDO_PATHS), mk('span', 'uw', 'Undo'), mk('span', 'ut', ''));
      c.setAttribute('aria-label', `Undo: restore the deleted ${WORDS[r.kind]}`);
      const msg = mk('span', 'umsg'); msg.id = `umsg${++msgSeq}`;
      msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite');
      c.setAttribute('aria-describedby', msg.id);
      c.addEventListener('click', () => { if (c.getAttribute('aria-disabled') !== 'true') restore(r.undo_id); });
      const list = chipsById.get(r.undo_id) || []; list.push(c); chipsById.set(r.undo_id, list);
      meta.append(c, msg);
      return c;
    });
    // the new items: titles for the chips, and the panel's list (after any load already under way)
    const again = () => { S.loadedAt = 0; return load(); };
    if (S.loading) S.loading.then(again); else again();
    return made;
  }
  function labelChips() {
    prune();
    chipsById.forEach((list, id) => {
      const it = (S.items || []).find(i => i.id === id);
      list.forEach(c => {
        if (it) {
          c.querySelector('.ut').textContent = it.title; c.title = it.title;
          if (!['done', 'gone'].includes(c.dataset.state)) c.setAttribute('aria-label', `Undo: restore the deleted ${WORDS[it.kind]} “${it.title}”`);
          if (it.restored && c.dataset.state !== 'busy') chipState(id, 'done');
        }
      });
    });
  }
  /** busy → "Undoing…"; done → "Restored"; gone → removed for good; bad → "Undo" again, and the
   *  reason in words in the chip's aria-live line (visible, not just a tooltip). */
  function chipState(id, state, msg) {
    (chipsById.get(id) || []).forEach(c => {
      c.dataset.state = state;
      c.classList.toggle('done', state === 'done'); c.classList.toggle('bad', state === 'bad' || state === 'gone');
      const w = c.querySelector('.uw');
      const line = c.nextElementSibling && c.nextElementSibling.classList.contains('umsg') ? c.nextElementSibling : null;
      if (line) line.textContent = state === 'bad' || state === 'gone' ? (msg || FAILED) : '';
      if (state === 'busy') { c.setAttribute('aria-disabled', 'true'); w.textContent = 'Undoing…'; }
      else if (state === 'done') { c.setAttribute('aria-disabled', 'true'); w.textContent = 'Restored'; c.setAttribute('aria-label', 'Restored'); }
      else if (state === 'gone') { c.setAttribute('aria-disabled', 'true'); w.textContent = 'Removed'; c.setAttribute('aria-label', 'Removed from Recently deleted'); }
      else { c.removeAttribute('aria-disabled'); w.textContent = 'Undo'; c.title = msg || ''; }
    });
  }

  // ---- sign-in, panel ----------------------------------------------------------------------------
  function ready() {
    if (!build()) return;
    S.items = undefined; S.error = ''; S.loadedAt = 0;
    expand(store.get(OPEN_KEY) === '1', false);
    load(); // the summary line says what can be restored even while the section is closed
  }
  document.addEventListener('jarvis:ready', ready);
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'approvals' && d.open && stale()) load(); });
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) ready();

  window.JarvisDeleted = Object.freeze({ chips, refresh: load, normal });
})();
