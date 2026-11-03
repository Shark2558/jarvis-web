// src/jarvis/api/static/console-drive.js -- slice 12 D1 (docs/plans/phase2-slice12-integrations.md):
// Integrations -> Google Drive. JARVIS reads Drive as its own Google account, and only the folders the
// owner shares with it AND switches on here. Built beside #integrations (console.js redraws that box),
// so the page markup stays untouched. No build step; CSP script-src 'self'; ASCII source with
// backslash-u escapes only; every server string reaches the page through textContent or an input's
// value (never markup); a field of the wrong type is dropped, never guessed. Transport is the console's
// api() (cookie + X-Requested-With, or the bearer token; 401 -> gate). Loads when the Integrations
// panel opens (it asks Google), never on page load.
// API: GET /v1/drive -> {configured:false} | {configured, service_email, folders:[{id, name, confirmed,
// readable}], others, others_more, max_folders}; PUT /v1/drive/roots/{id} {use} -> the same, or
// {error, detail}. `readable` is what JARVIS acts on: a switched-on folder it can't read now is said
// so, never "can't be read" while it can; the switch here always stops access at once.
// Review FE-1: switching a folder ON asks first (#driveDialog, a native modal like the Brief and
// Memory confirms: Esc and "Not now" cancel); switching off stays one tap. Focus returns to the switch.
// Final review: hidden while jarvis:integrations says drive: false (off on this server, or the owner
// set the Drive permission row to Never; an open confirm is cancelled); invisible characters go by
// window.JarvisText (console-text.js).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const ID = /^[A-Za-z0-9_-]{1,128}$/;
  const SA = /^[a-z0-9][a-z0-9-]{4,62}@[a-z0-9-]{4,64}\.iam\.gserviceaccount\.com$/;
  const STALE_MS = 30 * 1000;
  const MAX_FOLDERS = 50;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const STEPS = [
    'Open the folder in Google Drive and press Share.',
    'Paste JARVIS\'s address (Copy above) into the box.',
    'Choose Viewer, then press Send.',
  ];
  const CHECKING = 'Checking\u2026';
  const quoted = (name) => '\u201c' + name + '\u201d';
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: new Set(), note: null, off: false };
  let card = null, stateEl = null, bodyEl = null, noteEl = null;

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => window.JarvisText.strip(v); // console-text.js: keeps ZWNJ / ZWJ
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }

  /** GET /v1/drive, checked field by field; anything odd is dropped. null = not set up here. */
  function normal(raw) {
    const d = obj(raw);
    if (!d || d.configured !== true) return null;
    const email = typeof d.service_email === 'string' && SA.test(d.service_email) ? d.service_email : '';
    const seen = new Set();
    const folders = arr(d.folders).slice(0, MAX_FOLDERS).map((f) => {
      const it = obj(f);
      if (!it || typeof it.id !== 'string' || !ID.test(it.id) || seen.has(it.id)) return null;
      seen.add(it.id);
      return { id: it.id, name: txt(it.name) || '(no name)', confirmed: it.confirmed === true, readable: it.readable !== false };
    }).filter(Boolean);
    const others = Number.isInteger(d.others) && d.others >= 0 && d.others < 10000 ? d.others : 0;
    const max = Number.isInteger(d.max_folders) && d.max_folders > 0 ? d.max_folders : 20;
    return { email, folders, others, othersMore: d.others_more === true, max };
  }

  // ---- the card -------------------------------------------------------------------------------
  function build() {
    if (card) return true;
    const host = $('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ drive'); card.id = 'driveSet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'driveHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Google Drive'); title.id = 'driveHead';
    stateEl = mk('span', 'istate', CHECKING);
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'driveNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'driveBody';
    card.append(head, bodyEl, noteEl);
    host.parentNode.insertBefore(card, host.nextSibling);
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }

  function addressRow(email) {
    const wrap = mk('div', 'daddr');
    const label = mk('label', 'dlbl', 'JARVIS\'s address'); label.htmlFor = 'driveAddr';
    const row = mk('div', 'drow2');
    const input = mk('input', 'dinput'); input.id = 'driveAddr'; input.type = 'text'; input.readOnly = true;
    input.value = email; input.spellcheck = false; input.setAttribute('autocomplete', 'off');
    const copy = mk('button', 'btn bact', 'Copy'); copy.type = 'button'; copy.id = 'driveCopy';
    copy.setAttribute('aria-describedby', 'driveAddr');
    copy.addEventListener('click', () => copyAddress(input, copy));
    row.append(input, copy);
    wrap.append(label, row);
    return wrap;
  }
  async function copyAddress(input, btn) {
    const value = input.value;
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') throw new Error('no clipboard');
      await navigator.clipboard.writeText(value);
      btn.textContent = 'Copied';
      note('ok', 'Address copied. Paste it in Google Drive\'s Share box.');
      setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
    } catch (_) {
      input.focus(); input.select();
      note('ok', 'Address selected: press Ctrl+C (\u2318C on a Mac) to copy it.');
    }
  }
  function steps() {
    const ol = mk('ol', 'dsteps'); ol.id = 'driveSteps';
    STEPS.forEach(s => ol.appendChild(mk('li', '', s)));
    return ol;
  }
  function useSwitch(f) {
    const b = mk('button', 'bsw'); b.type = 'button'; b.dataset.id = f.id;
    b.setAttribute('aria-pressed', String(f.confirmed));
    b.setAttribute('aria-label', 'Use ' + quoted(f.name));
    const track = mk('span', 'track'); track.appendChild(mk('i', ''));
    b.append(track, mk('span', 'st', f.confirmed ? 'On' : 'Off'));
    const blocked = !f.readable && !f.confirmed; // switching off is always allowed
    if (S.busy.has(f.id) || blocked) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') toggle(f, b); });
    return b;
  }
  /** Off -> On asks first (FE-1); On -> Off is one tap. */
  async function toggle(f, trigger) {
    if (f.confirmed) { setUse(f, false); return; }
    if (await askOn(f, trigger)) setUse(f, true);
  }

  // ---- confirm dialog: native modal (the rest of the page is inert), Tab stays inside, Esc = Not now
  let settle = null;
  function askOn(f, trigger) {
    const dlg = $('driveDialog');
    if (!dlg || typeof dlg.showModal !== 'function') {
      note('bad', 'This browser can\'t show the confirmation, so the folder was not switched on.');
      return Promise.resolve(false);
    }
    if (settle) settle(false);
    $('driveDialogTitle').textContent = 'Let JARVIS read this folder?';
    const body = $('driveDialogText'); body.textContent = '';
    const first = mk('p', 'strong');
    first.append('JARVIS will be able to read the files in ', mk('b', '', quoted(f.name)), ' and in every folder inside it.');
    body.append(first,
      mk('p', '', 'When you ask about them, JARVIS sends what it reads to the brain (Claude) to answer you.'),
      mk('p', '', 'It can\'t change or delete anything. You can switch it off here at any time.'));
    return new Promise((resolve) => {
      settle = (val) => {
        settle = null;
        if (dlg.open) dlg.close();
        refocus(trigger, f.id);
        resolve(val);
      };
      dlg.showModal();
      $('driveDialogNo').focus(); // the safe choice is where Enter lands
    });
  }
  /** Focus back on the switch: the same element, or the one a re-render put in its place. */
  function refocus(trigger, id) {
    const now = trigger && document.contains(trigger) ? trigger : card && card.querySelector(`.bsw[data-id="${id}"]`);
    if (now && !now.closest('[hidden]')) now.focus({ preventScroll: true });
  }
  function wireDialog() {
    const dlg = $('driveDialog');
    if (!dlg) return;
    $('driveDialogYes').addEventListener('click', () => { if (settle) settle(true); });
    $('driveDialogNo').addEventListener('click', () => { if (settle) settle(false); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('close', () => { if (settle && !dlg.open) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const items = [...dlg.querySelectorAll('button:not([disabled])')];
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
  }
  function folderList(d) {
    const ul = mk('ul', 'dfolders'); ul.id = 'driveList'; ul.setAttribute('aria-label', 'Folders shared with JARVIS');
    d.folders.forEach((f) => {
      const li = mk('li', 'dfolder'); li.dataset.id = f.id;
      const t = mk('div', 'btxt');
      t.append(mk('b', '', f.name), mk('small', '', !f.confirmed
        ? 'Not in use: JARVIS won\'t read it.'
        : f.readable ? 'In use: JARVIS can read it and everything inside it.'
          : 'Switched on, but JARVIS can\'t currently read it: it is no longer shared with JARVIS from your account, or it is in the trash. Share it again, or switch it off here.'));
      li.append(t, useSwitch(f));
      ul.appendChild(li);
    });
    return ul;
  }
  function others(n, more) {
    const p = mk('p', 'fine dothers'); p.id = 'driveOthers';
    const many = more || n !== 1;
    p.textContent = `${n}${more ? ' or more' : ''} ${many ? 'folders' : 'folder'} not offered: shared by another account. JARVIS never reads ${many ? 'them' : 'it'}.`;
    return p;
  }

  function render() {
    if (!build()) return;
    if (S.off) { card.hidden = true; return; } // off here, or Never in Permissions
    const d = S.data;
    bodyEl.textContent = '';
    if (S.error) {
      card.dataset.state = 'error'; stateEl.textContent = 'Unknown';
      bodyEl.appendChild(mk('p', 'warn', 'Couldn\'t check Google Drive. ' + S.error));
      const r = mk('button', 'btn bact', 'Retry'); r.type = 'button'; r.id = 'driveRetry';
      r.addEventListener('click', () => { r.disabled = true; load(true); });
      bodyEl.appendChild(r);
      return;
    }
    if (d === undefined) { card.dataset.state = 'loading'; stateEl.textContent = CHECKING; bodyEl.appendChild(mk('p', '', 'Checking folders shared with JARVIS\u2026')); return; }
    if (d === null) { card.hidden = true; return; }
    card.hidden = false;
    const inUse = d.folders.filter(f => f.confirmed && f.readable).length;
    card.dataset.state = inUse ? 'linked' : 'unlinked';
    stateEl.textContent = inUse ? `${inUse} in use` : 'No folders in use';
    bodyEl.appendChild(mk('p', '', 'JARVIS reads only the folders you share with it and switch on here (and what is inside them). It can\'t change or delete anything in your Drive.'));
    if (d.email) bodyEl.appendChild(addressRow(d.email));
    else bodyEl.appendChild(mk('p', 'warn', 'JARVIS\'s address isn\'t available right now. Try again in a minute.'));
    if (d.folders.length) {
      const how = mk('details', 'dhow');
      how.appendChild(mk('summary', '', 'How to share another folder'));
      how.appendChild(steps());
      bodyEl.append(folderList(d), how);
    } else {
      bodyEl.append(steps(), mk('p', 'fine', 'The folder shows up here within a minute. Then switch on Use.'));
    }
    if (d.others || d.othersMore) bodyEl.appendChild(others(d.others, d.othersMore));
    const refresh = mk('button', 'btn bact', 'Check again'); refresh.type = 'button'; refresh.id = 'driveRefresh';
    refresh.addEventListener('click', () => load(true));
    bodyEl.appendChild(refresh);
  }

  async function setUse(f, on) {
    if (!hasApi() || S.busy.has(f.id)) return;
    S.busy.add(f.id); render();
    try {
      const r = normal(await api(`/v1/drive/roots/${encodeURIComponent(f.id)}`, { method: 'PUT', body: { use: on } }));
      if (r) S.data = r;
      note('ok', on ? `JARVIS can now read ${quoted(f.name)} and what is inside it.` : `JARVIS no longer reads ${quoted(f.name)}.`);
      log('info', on ? 'Drive folder in use' : 'Drive folder switched off');
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t change it. Please try again.');
    } finally {
      S.busy.delete(f.id); render();
      refocus(null, f.id);
    }
  }

  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.off) { render(); return Promise.resolve(); } // nothing to ask Google for
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try {
        S.data = normal(await api('/v1/drive')); S.error = '';
      } catch (e) {
        if (e && e.status === 401) return;
        if (e && e.status === 404) { S.data = null; S.error = ''; } else { S.error = detailOf(e) || 'Please try again.'; }
      } finally {
        S.loadedAt = Date.now(); S.loading = null; render();
      }
    })();
    return S.loading;
  }

  const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));
  wireDialog();
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  // /v1/integrations drive_available (a server without the field says nothing: shown as before)
  document.addEventListener('jarvis:integrations', (e) => {
    const d = e.detail || {};
    if (typeof d.drive !== 'boolean' || S.off === !d.drive) return;
    S.off = !d.drive;
    if (S.off && settle) settle(false); // never switch a folder on for a Drive that is now off
    if (S.off) render(); else if (card) load(true);
  });
  document.addEventListener('jarvis:ready', () => { if (integOpen()) load(false); });
  // FE-9: this script can arrive after jarvis:ready (deferred; a slow network holds it back): ask too
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready() && integOpen()) load(false);

  window.JarvisDrive = Object.freeze({ refresh: () => load(true), normal });
})();
