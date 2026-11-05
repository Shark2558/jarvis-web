// src/jarvis/api/static/console-privacy.js - R2 D14: the Privacy panel. One card per kind of data
// JARVIS keeps (what, how many, how long, where, "encrypted by JARVIS"), Export, Delete (or the
// reason there is none), "Download everything" and the Faces placeholder. No build step; CSP
// script-src 'self'; every server string reaches the page through textContent; a field of the wrong
// type is dropped, never guessed. Transport is the console's api() (window.JarvisConsole).
// API: GET /v1/privacy -> {categories: [{id, section, label, what, count, unit, retention, where,
// size_hint, encrypted_by_jarvis, export, delete: none|simple|confirm|passkey, recoverable, note,
// rev, available}], passkey_in_force, generated_at}; GET /v1/privacy/{id}/export -> JSON;
// POST /v1/privacy/export-all {proof?}; POST /v1/privacy/{id}/delete {rev, confirm?, proof?} ->
// {deleted, category}. Errors {error, detail, reason?}: 409 changed, 403 proof_required {reason:
// reauth}, passkey_required / passkey_rejected, console_only.
// Deletes that can't be brought back: a passkey check (window.JarvisPasskey.prove, bound to the
// category and its rev) when passkeys are in force; otherwise the typed word DELETE plus a Google
// sign-in less than 5 minutes old (/auth/login?reauth=1).
// Loads when the panel (#p-privacy .pbody) is opened (jarvis:panel) or already shown.
(() => {
  'use strict';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const CLASSES = ['none', 'simple', 'confirm', 'passkey'];
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const CHANGED = 'This changed - check again.';
  const CONFIRM_WORD = 'DELETE';
  const STALE_MS = 30 * 1000;
  const MAX_CARDS = 60;
  const S = { data: null, loadedAt: 0, loading: null, busy: false };
  let root = null, listEl = null, noteEl = null, sumEl = null, allBtn = null, dlg = null;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 400) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    if (e && e.passkeyMessage) return e.passkeyMessage;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  const errText = (e) => detailOf(e) || 'Please try again.';
  const plural = (n, unit) => (n === 1 && unit.endsWith('s') ? unit.slice(0, -1) : unit);

  /** GET /v1/privacy, checked field by field. */
  function normal(data) {
    const d = obj(data) || {};
    const cats = arr(d.categories).slice(0, MAX_CARDS).map((raw) => {
      const c = obj(raw);
      if (!c || !/^[a-z][a-z0-9_]{0,31}$/.test(c.id || '')) return null;
      const cls = CLASSES.includes(c.delete) ? c.delete : 'none';
      return {
        id: c.id, section: txt(c.section, 60) || 'Other', label: txt(c.label, 80) || c.id,
        what: txt(c.what), unit: txt(c.unit, 40), retention: txt(c.retention), where: txt(c.where, 80),
        count: Number.isInteger(c.count) && c.count >= 0 ? c.count : null, size: txt(c.size_hint, 40),
        enc: c.encrypted_by_jarvis === true, canExport: c.export === true, del: cls,
        recoverable: c.recoverable === true, note: txt(c.note, 500), rev: txt(c.rev, 64),
        available: c.available !== false,
      };
    }).filter(Boolean);
    return { cats, passkey: d.passkey_in_force === true };
  }

  // ---- the panel ------------------------------------------------------------------------------
  function build() {
    const body = document.querySelector('#p-privacy .pbody');
    if (!body) return false;
    if (root && root.parentNode === body) return true;
    root = mk('div', 'pv'); root.id = 'pvRoot';
    sumEl = mk('p', 'pv-sum'); sumEl.id = 'pvSum';
    const lead = mk('p', 'bfine pv-lead', 'Everything JARVIS keeps about you and your family, in one place. Export what you want to keep. Delete what you want gone.');
    noteEl = mk('div', 'bnote'); noteEl.id = 'pvNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    allBtn = mk('button', 'btn bact', 'Download everything'); allBtn.type = 'button'; allBtn.id = 'pvAll';
    allBtn.addEventListener('click', downloadAll);
    const fine = mk('p', 'bfine', 'Vault files are not in that download. Use Vault, then Export, for the files.');
    listEl = mk('div', 'pv-list'); listEl.id = 'pvList';
    root.append(sumEl, lead, noteEl, allBtn, fine, listEl);
    body.replaceChildren(root);
    return true;
  }
  function note(kind, text) { if (noteEl) { noteEl.className = 'bnote' + (kind ? ' ' + kind : ''); noteEl.textContent = text || ''; } }

  function render() {
    if (!build() || !S.data) return;
    const { cats } = S.data;
    const holding = cats.filter((c) => c.count && c.count > 0).length;
    sumEl.textContent = cats.length ? `JARVIS keeps ${holding} kind${holding === 1 ? '' : 's'} of data about you and your family.` : '';
    const sections = [];
    cats.forEach((c) => { let s = sections.find((x) => x.name === c.section); if (!s) sections.push(s = { name: c.section, items: [] }); s.items.push(c); });
    const frag = document.createDocumentFragment();
    sections.forEach((s) => {
      const sec = mk('section', 'pv-sec'); const h = mk('h3', 'pv-h', s.name); sec.appendChild(h);
      s.items.forEach((c) => sec.appendChild(card(c)));
      frag.appendChild(sec);
    });
    if (!cats.length) frag.appendChild(mk('div', 'empty', 'Nothing to show yet.'));
    listEl.replaceChildren(frag);
  }

  function card(c) {
    const el = mk('article', 'pv-card'); el.id = 'pv-' + c.id; el.dataset.id = c.id;
    const head = mk('div', 'pv-head');
    head.appendChild(mk('h4', 'pv-label', c.label));
    if (c.available) {
      const n = c.count === null ? '' : `${c.count.toLocaleString()} ${plural(c.count, c.unit)}`.trim();
      if (n) head.appendChild(mk('span', 'pv-count', n));
    }
    el.appendChild(head);
    if (!c.available) { el.appendChild(mk('p', 'pv-note lerr', c.note || 'Couldn\'t check right now.')); return el; }
    if (c.what) el.appendChild(mk('p', 'pv-what', c.what));
    const facts = mk('dl', 'pv-facts');
    [['Kept', c.retention], ['Where', c.where], ['Size', c.size]].forEach(([k, v]) => {
      if (!v) return; facts.append(mk('dt', '', k), mk('dd', '', v));
    });
    el.appendChild(facts);
    if (c.enc) el.appendChild(mk('span', 'pv-badge', 'Encrypted by JARVIS'));
    if (c.note) el.appendChild(mk('p', 'pv-note', c.note));
    const acts = mk('div', 'pv-acts');
    if (c.canExport) {
      const b = mk('button', 'btn bact', 'Export'); b.type = 'button'; b.setAttribute('aria-label', `Export ${c.label}`);
      b.addEventListener('click', () => exportOne(c, b)); acts.appendChild(b);
    }
    if (c.del !== 'none') {
      const b = mk('button', 'btn bdel', 'Delete...'); b.type = 'button'; b.setAttribute('aria-label', `Delete ${c.label}`);
      b.addEventListener('click', () => askDelete(c, b)); acts.appendChild(b);
    } else if (!c.note) {
      acts.appendChild(mk('span', 'pv-note', 'This can\'t be deleted here.'));
    }
    if (acts.childNodes.length) el.appendChild(acts);
    return el;
  }

  async function load(force) {
    if (S.loading) return S.loading;
    if (!force && S.data && Date.now() - S.loadedAt < STALE_MS) return null;
    if (!hasApi() || !build()) return null;
    S.loading = (async () => {
      try { S.data = normal(await api('/v1/privacy')); S.loadedAt = Date.now(); render(); }
      catch (e) {
        if (e && e.status === 401) return;
        note('bad', e && e.status === 404 ? 'The privacy panel isn\'t available on this server.' : errText(e));
      } finally { S.loading = null; }
    })();
    return S.loading;
  }

  // ---- downloads ------------------------------------------------------------------------------
  function save(name, data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = mk('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  const stamp = () => new Date().toISOString().slice(0, 10);
  async function exportOne(c, btn) {
    btn.disabled = true; note('', '');
    try { save(`jarvis-${c.id}-${stamp()}.json`, await api(`/v1/privacy/${c.id}/export`)); note('ok', `${c.label} downloaded.`); }
    catch (e) { note('bad', errText(e)); } finally { btn.disabled = false; }
  }
  async function downloadAll() {
    if (S.busy) return; S.busy = true; allBtn.disabled = true; note('', '');
    try {
      const proof = await proveIf('privacy_export', 'all');
      save(`jarvis-everything-${stamp()}.json`, await api('/v1/privacy/export-all', { body: proof ? { proof } : {} }));
      note('ok', 'Everything downloaded, except vault files.');
    } catch (e) { fail(e); } finally { S.busy = false; allBtn.disabled = false; }
  }
  async function proveIf(purpose, target) {
    if (!(S.data && S.data.passkey)) return null;
    if (!window.JarvisPasskey || !window.JarvisPasskey.supported()) throw Object.assign(new Error('This browser can\'t use passkeys. Try an up-to-date Chrome, Edge, Safari or Firefox.'), { passkeyMessage: 'This browser can\'t use passkeys. Try an up-to-date Chrome, Edge, Safari or Firefox.' });
    return window.JarvisPasskey.prove(purpose, target);
  }
  function reauth() { try { window.location.assign('/auth/login?reauth=1'); } catch (_) {} }
  /** The note for an error; a stale sign-in gets a button that signs in again. */
  function fail(e) {
    note('bad', errText(e));
    if (e && e.code === 'proof_required' && noteEl) {
      const b = mk('button', 'btn bact', 'Sign in with Google again'); b.type = 'button'; b.id = 'pvReauth';
      b.addEventListener('click', reauth); noteEl.appendChild(b);
    }
  }

  // ---- the delete dialog ----------------------------------------------------------------------
  function trap(e) {
    if (e.key === 'Escape') { e.preventDefault(); closeDlg(); return; }
    if (e.key !== 'Tab' || !dlg) return;
    const f = Array.from(dlg.el.querySelectorAll('button:not([disabled]),input:not([disabled])')).filter((n) => !n.hidden);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  function closeDlg() {
    if (!dlg) return;
    document.removeEventListener('keydown', trap, true);
    const { el, opener } = dlg; dlg = null; el.remove();
    if (opener && opener.isConnected) opener.focus();
  }
  function askDelete(c, opener) {
    if (dlg) return;
    const typed = c.del === 'passkey' && !(S.data && S.data.passkey);
    const el = mk('div', 'pv-dlg'); el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-labelledby', 'pvDlgT');
    const n = c.count === null ? '' : `${c.count.toLocaleString()} ${plural(c.count, c.unit)}`;
    const box = mk('div', 'pv-box');
    box.appendChild(mk('h4', 'pv-dt', `Delete ${c.label}?`)); box.firstChild.id = 'pvDlgT';
    box.appendChild(mk('p', '', n ? `This removes ${n}: ${c.what}` : c.what));
    box.appendChild(mk('p', 'bfine', c.recoverable ? 'You can set this up again later.' : 'This can\'t be brought back.'));
    if (c.note) box.appendChild(mk('p', 'bfine', c.note));
    const input = mk('input', 'pv-type'); input.type = 'text'; input.autocomplete = 'off'; input.id = 'pvType';
    input.setAttribute('aria-label', `Type ${CONFIRM_WORD} to confirm`); input.placeholder = CONFIRM_WORD; input.hidden = !typed;
    const how = mk('p', 'bfine', c.del !== 'passkey' ? '' : typed ? `Type ${CONFIRM_WORD}. You also need to have signed in with Google in the last 5 minutes.` : 'You will be asked for your passkey.');
    const msg = mk('div', 'bnote bad'); msg.setAttribute('role', 'alert');
    const ok = mk('button', 'btn bdel ask', 'Delete'); ok.type = 'button'; ok.id = 'pvGo';
    const no = mk('button', 'btn bact', 'Cancel'); no.type = 'button'; no.id = 'pvNo';
    const row = mk('div', 'pv-acts'); row.append(no, ok);
    box.append(input, how, msg, row); el.appendChild(box); document.body.appendChild(el);
    dlg = { el, opener }; document.addEventListener('keydown', trap, true);
    no.addEventListener('click', closeDlg);
    ok.addEventListener('click', () => doDelete(c, { ok, no, input, msg, typed, box }));
    (typed ? input : no).focus();
  }
  async function doDelete(c, ui) {
    if (S.busy) return;
    if (ui.typed && ui.input.value !== CONFIRM_WORD) { ui.msg.textContent = `Type ${CONFIRM_WORD} to confirm.`; ui.input.focus(); return; }
    S.busy = true; ui.ok.disabled = true; ui.no.disabled = true; ui.msg.textContent = '';
    try {
      const body = { rev: c.rev };
      if (ui.typed) body.confirm = CONFIRM_WORD;
      if (c.del === 'passkey' && !ui.typed) body.proof = await proveIf('privacy_delete', `${c.id}:${c.rev}`);
      const out = obj(await api(`/v1/privacy/${c.id}/delete`, { body })) || {};
      closeDlg();
      note('ok', `Deleted ${Number.isInteger(out.deleted) ? out.deleted.toLocaleString() : 'it'} from ${c.label}.`);
      await load(true);
    } catch (e) {
      ui.ok.disabled = false; ui.no.disabled = false;
      if (e && e.status === 409) { closeDlg(); note('bad', CHANGED); await load(true); return; }
      ui.msg.textContent = errText(e);
      if (e && e.code === 'proof_required') {
        const b = mk('button', 'btn bact', 'Sign in with Google again'); b.type = 'button'; b.id = 'pvReauth';
        b.addEventListener('click', reauth); ui.box.insertBefore(b, ui.msg.nextSibling);
      }
    } finally { S.busy = false; }
  }

  // ---- when to load ---------------------------------------------------------------------------
  const shown = () => { const p = document.getElementById('p-privacy'); return !!p && !p.hidden; };
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'privacy' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (shown()) load(false); });
  document.addEventListener('DOMContentLoaded', () => { if (shown()) load(false); });
  window.JarvisPrivacy = Object.freeze({ refresh: () => load(true) });
})();
