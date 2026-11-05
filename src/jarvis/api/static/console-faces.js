// src/jarvis/api/static/console-faces.js -- R3 D13: the Faces panel. Who JARVIS may recognise at home, and
// only with consent. Names, relation and consent records live here; face pictures NEVER do: they are added
// on the home laptop page and stay there. Add person asks for the consent statement (an adult's own
// agreement, or a parent's / guardian's for someone under 18). Delete asks first, then for a passkey
// (JarvisPasskey.prove('privacy_delete', 'face:<id>')); a sleeping laptop finishes the job when it is back.
// Server strings reach the page through textContent only. No build step; CSP script-src 'self'; ASCII
// source with backslash-u escapes. Mounts into #p-faces .pbody (shell in console.html, I1).
// API: GET /v1/faces -> {available, reason?, people:[{id, name, relation, child, vip, state, consent_at,
// renewal_due, pictures, laptop_code}], total, limit, statements:{version, adult, child}};
// POST /v1/faces {name, relation, child, vip, given_by, consent_version, confirm:true} -> 201;
// PATCH /v1/faces/{id} {reconfirm?, vip?}; POST /v1/faces/{id}/delete {proof?}; GET /v1/faces/local.
(() => {
  'use strict';
  const panel = document.getElementById('p-faces');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const ID = /^fp_[0-9a-f]{12}$/;
  const RELATIONS = ['family', 'friend', 'helper', 'other'];
  const STATES = ['consented', 'enrolled', 'deleting'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const STALE_MS = 60 * 1000, MAX_ROWS = 30;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const LOCAL = 'http://localhost:8098/faces';
  const S = { data: undefined, local: null, loadedAt: 0, busy: false };
  let list, stateEl, noteEl, addBtn, dlg, dlgTitle, dlgBody, dlgYes, dlgNo, settle = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const Deck = window.JarvisDeck || { isOpen: () => false };
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear(); };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, text) { noteEl.className = 'bnote fnote' + (kind === 'bad' ? ' bad' : ''); noteEl.textContent = text || ''; }

  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    if (d.available !== true) return { available: false, reason: txt(d.reason, 200) || 'Not available on this server.', people: [], limit: 30 };
    const st = obj(d.statements) || {};
    const seen = new Set();
    const people = arr(d.people).slice(0, MAX_ROWS).map((p) => {
      const it = obj(p);
      if (!it || typeof it.id !== 'string' || !ID.test(it.id) || seen.has(it.id)) return null;
      seen.add(it.id);
      return { id: it.id, name: txt(it.name, 40) || '(no name)', relation: RELATIONS.includes(it.relation) ? it.relation : 'other',
        child: it.child === true, vip: it.vip === true, state: STATES.includes(it.state) ? it.state : 'consented',
        consentAt: txt(it.consent_at, 40), due: it.renewal_due === true, pictures: Number.isInteger(it.pictures) && it.pictures >= 0 ? it.pictures : 0 };
    }).filter(Boolean);
    return { available: true, people, limit: Number.isInteger(d.limit) ? d.limit : 30,
      version: txt(st.version, 8) || 'fc1', adult: txt(st.adult, 400), child: txt(st.child, 400) };
  }

  // ---- dialog (focus stays inside; Escape cancels) -----------------------------------------------
  function build() {
    const root = mk('div', 'faces'); root.id = 'faces';
    noteEl = mk('div', 'bnote fnote'); noteEl.id = 'facesNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite');
    const intro = mk('p', 'bfine', 'JARVIS names only people you add here, with their consent. Pictures are added on your home laptop and never leave it.');
    addBtn = mk('button', 'btn lift bact', 'Add person'); addBtn.type = 'button'; addBtn.id = 'facesAdd';
    addBtn.addEventListener('click', addPerson);
    stateEl = mk('div', 'empty'); stateEl.id = 'facesState'; stateEl.setAttribute('role', 'status');
    list = mk('ul', 'tlist'); list.id = 'facesList'; list.setAttribute('aria-label', 'People JARVIS recognises');
    const lc = mk('p', 'bfine'); lc.id = 'facesLocal';
    dlg = mk('dialog', 'bdialog'); dlg.id = 'facesDialog'; dlg.setAttribute('role', 'alertdialog'); dlg.setAttribute('aria-labelledby', 'facesDialogTitle');
    dlgTitle = mk('h3'); dlgTitle.id = 'facesDialogTitle'; dlgBody = mk('div', 'fbody');
    const row = mk('div', 'brow');
    dlgNo = mk('button', 'btn', 'Cancel'); dlgNo.type = 'button';
    dlgYes = mk('button', 'btn lift', 'OK'); dlgYes.type = 'button';
    row.append(dlgNo, dlgYes); dlg.append(dlgTitle, dlgBody, row);
    dlgYes.addEventListener('click', () => settle && settle(true));
    dlgNo.addEventListener('click', () => settle && settle(false));
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const f = Array.from(dlg.querySelectorAll('input,select,button')).filter((n) => !n.disabled);
      if (!f.length) return;
      const a = f[0], z = f[f.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
    root.append(noteEl, intro, addBtn, stateEl, list, lc, dlg);
    host.appendChild(root);
  }
  function ask(title, yes, content, trigger, first) {
    if (typeof dlg.showModal !== 'function') return Promise.resolve(false);
    dlgTitle.textContent = title; dlgYes.textContent = yes; dlgBody.textContent = ''; dlgBody.appendChild(content);
    return new Promise((resolve) => {
      settle = (v) => { settle = null; if (dlg.open) dlg.close(); if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true }); resolve(v); };
      dlg.showModal(); (first || dlgNo).focus();
    });
  }

  // ---- render -----------------------------------------------------------------------------------
  function row(p) {
    const li = mk('li', 'trow'); li.dataset.id = p.id;
    const main = mk('div', 'ttxt');
    main.append(mk('b', 'tname', p.name));
    const tags = [p.relation, p.child ? 'under 18' : '', p.vip ? 'VIP' : ''].filter(Boolean).join(' \u00b7 ');
    main.appendChild(mk('span', 'tplace', tags));
    let pics;
    if (p.state === 'deleting') pics = 'Deleting on your laptop when it\'s back.';
    else if (p.pictures > 0) pics = p.pictures + (p.pictures === 1 ? ' picture' : ' pictures') + ' on your laptop';
    else pics = 'Add pictures on your laptop';
    const code = mk('code', 'fcode', p.id);
    const meta = mk('small', 'tmeta', 'Consent on ' + (when(p.consentAt) || 'record') + ' \u00b7 ' + pics + ' \u00b7 Laptop code ');
    meta.appendChild(code); main.appendChild(meta);
    const acts = mk('div', 'tacts');
    if (p.due && p.state !== 'deleting') {
      main.appendChild(mk('span', 'tmeta fdue', 'Still OK to recognise ' + p.name + '?'));
      const ok = mk('button', 'btn bact', 'Yes, still OK'); ok.type = 'button'; ok.setAttribute('aria-label', 'Confirm consent again for ' + p.name);
      ok.addEventListener('click', () => reconfirm(p));
      acts.appendChild(ok);
    }
    if (p.state !== 'deleting') {
      const de = mk('button', 'btn bact', 'Delete'); de.type = 'button'; de.setAttribute('aria-label', 'Delete ' + p.name);
      de.addEventListener('click', () => remove(p, de));
      acts.appendChild(de);
    }
    li.append(main, acts);
    return li;
  }
  function render() {
    const d = S.data;
    list.textContent = '';
    const lc = document.getElementById('facesLocal'); lc.textContent = '';
    if (d === undefined) { stateEl.textContent = 'People load when this panel opens.'; return; }
    if (!d.available) { stateEl.textContent = d.reason; addBtn.setAttribute('aria-disabled', 'true'); return; }
    addBtn.removeAttribute('aria-disabled');
    stateEl.textContent = d.people.length ? '' : 'Nobody is added. JARVIS names no one until you add them with their consent.';
    d.people.forEach((p) => list.appendChild(row(p)));
    lc.append('Add pictures at ', mk('code', 'fcode', LOCAL), ' \u2014 only works on your home laptop' + (S.local && S.local.online ? ' (it is online now).' : '.'));
  }

  // ---- actions ----------------------------------------------------------------------------------
  function field(label, input) { const l = mk('label', 'bl', label); const w = mk('div', 'ffield'); w.append(l, input); l.htmlFor = input.id; return w; }
  async function addPerson() {
    const d = S.data;
    if (S.busy || !d || !d.available) return;
    const box = mk('div', 'fform');
    const name = mk('input', 'tin'); name.id = 'facesName'; name.maxLength = 40; name.autocomplete = 'off';
    const rel = mk('select', 'tin'); rel.id = 'facesRel';
    RELATIONS.forEach((r) => { const o = mk('option', '', r); o.value = r; rel.appendChild(o); });
    const kid = mk('input'); kid.type = 'checkbox'; kid.id = 'facesChild';
    const vip = mk('input'); vip.type = 'checkbox'; vip.id = 'facesVip';
    const ok = mk('input'); ok.type = 'checkbox'; ok.id = 'facesConsent';
    const stmt = mk('p', 'fstmt'); stmt.id = 'facesStatement';
    const okLabel = mk('label', 'bl'); okLabel.htmlFor = 'facesConsent';
    const paint = () => {
      const t = kid.checked ? d.child : d.adult;
      stmt.textContent = t.replace('<name>', name.value.trim() || 'This person');
      okLabel.textContent = kid.checked ? 'I confirm this' : 'I confirm they agreed';
    };
    name.addEventListener('input', paint); kid.addEventListener('change', paint); paint();
    const kidL = mk('label', 'bl'); kidL.htmlFor = 'facesChild'; kidL.textContent = 'Under 18';
    const vipL = mk('label', 'bl'); vipL.htmlFor = 'facesVip'; vipL.textContent = 'VIP (their arrival is always worth a ring)';
    const k = mk('div', 'frow'); k.append(kid, kidL); const v = mk('div', 'frow'); v.append(vip, vipL);
    const o = mk('div', 'frow'); o.append(ok, okLabel);
    box.append(field('Name', name), field('Relation', rel), k, v, stmt, o);
    if (!(await ask('Add a person', 'Add', box, addBtn, name))) return;
    S.busy = true;
    try {
      await api('/v1/faces', { method: 'POST', body: { name: name.value, relation: rel.value, child: kid.checked, vip: vip.checked,
        given_by: kid.checked ? 'parent_guardian' : 'self', consent_version: d.version, confirm: ok.checked } });
      say('ok', 'Added. Now add their pictures on your home laptop.'); await load(true);
    } catch (e) { say('bad', detailOf(e) || 'Couldn\'t add that person. Please try again.'); }
    finally { S.busy = false; }
  }
  async function reconfirm(p) {
    try { await api('/v1/faces/' + p.id, { method: 'PATCH', body: { reconfirm: true } }); say('ok', 'Thanks. Consent for ' + p.name + ' renewed.'); await load(true); }
    catch (e) { say('bad', detailOf(e) || 'Couldn\'t save that. Please try again.'); }
  }
  async function prove(id) {
    const P = window.JarvisPasskey;
    if (!P || typeof P.prove !== 'function' || (typeof P.supported === 'function' && !P.supported())) return undefined;
    try { return await P.prove('privacy_delete', 'face:' + id); } catch (e) {
      throw new Error((typeof P.message === 'function' && P.message(e)) || detailOf(e) || 'The passkey check didn\'t finish, so nothing was deleted.');
    }
  }
  async function remove(p, trigger) {
    const c = mk('p', '', p.name + ' will no longer be recognised. Their name and consent are removed now, and their pictures are deleted from your laptop' + (p.pictures ? ' (' + p.pictures + ')' : '') + ' as soon as it is on. This can\'t be undone.');
    if (!(await ask('Delete ' + p.name + '?', 'Delete', c, trigger))) return;
    try {
      let body = {};
      try { await api('/v1/faces/' + p.id + '/delete', { method: 'POST', body }); } catch (e) {
        if (!(e && e.code === 'passkey_required')) throw e;
        body = { proof: await prove(p.id) };
        await api('/v1/faces/' + p.id + '/delete', { method: 'POST', body });
      }
      say('ok', p.name + ' is deleted. The pictures go from your laptop when it checks in.'); await load(true);
    } catch (e) { say('bad', detailOf(e) || 'Couldn\'t delete that. Please try again.'); }
  }
  async function load(force) {
    if (!hasApi()) return;
    if (!force && S.data !== undefined && Date.now() - S.loadedAt < STALE_MS) return;
    try {
      S.data = normal(await api('/v1/faces')) || { available: false, reason: 'Not available on this server.', people: [], limit: 30 };
      S.loadedAt = Date.now();
      try { const l = obj(await api('/v1/faces/local')); S.local = l ? { url: txt(l.url, 100), online: l.laptop_online === true } : null; } catch (_) { S.local = null; }
    } catch (e) {
      if (e && e.status === 401) return;
      say('bad', detailOf(e) || 'Couldn\'t load the people list. Please try again.');
    }
    render();
  }

  build(); render();
  const shown = () => { if (Deck.isOpen('faces')) load(false); };
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'faces' && d.open) load(false); });
  document.addEventListener('jarvis:ready', shown);
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) shown();
  window.JarvisFaces = Object.freeze({ refresh: () => load(true), normal });
})();
