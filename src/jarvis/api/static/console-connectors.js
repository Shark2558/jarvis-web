// src/jarvis/api/static/console-connectors.js -- R4 C: the Connectors panel. GitHub (paste a token,
// it is sent once and never shown again), YouTube (own channel, via the Google link) and Google
// Photos (pick-only: you choose photos in Google's picker; they go to your home laptop, which finds
// faces; naming anyone needs their consent). Everything the server sends reaches the page through
// textContent, never as markup. No build step; CSP script-src 'self'; ASCII source with backslash-u
// escapes only; no CDN; amounts, if ever shown, are in rupees only. Transport is the console's api().
// Mounts into #p-connectors .pbody (the panel shell is in console.html). Listens: jarvis:ready,
// jarvis:panel (Connectors shown).
// API: GET /v1/connectors -> {github:{connected,login}, youtube:{connected,reason}, photos:{connected,
// reason}, statements:{adult,child,version}}; PUT/DELETE /v1/connectors/github; POST
// /v1/connectors/photos/start -> {picker_uri}; POST .../photos/import -> {status, photos, faces_found,
// recognised:[{name,child}], unknown:[id], skipped}; POST .../photos/enrol.
(() => {
  'use strict';
  const panel = document.getElementById('p-connectors');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const CHILD = 'a child from your family';
  const MAX_ROWS = 50;
  const WHY = { no_google: 'Sign in with Google first.', not_granted: 'Press Grant for this in Integrations.', unavailable: 'Not available on this server.' };
  const S = { data: null, unknown: [], busy: false, confirm: false };
  let el = {};

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const Deck = window.JarvisDeck || { isOpen: () => false, open: () => {} };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, text) { el.note.className = 'bnote hnote' + (kind === 'bad' ? ' bad' : ''); el.note.textContent = text || ''; }
  
  // ---- normalise what the server sent ------------------------------------------------------
  function statusOf(raw) {
    const r = obj(raw); if (!r) return null;
    const one = (k) => { const o = obj(r[k]) || {}; return { connected: o.connected === true, login: txt(o.login, 60), reason: txt(o.reason, 40), reconnect: o.needs_reconnect === true }; };
    const st = obj(r.statements) || {};
    return { github: one('github'), youtube: one('youtube'), photos: one('photos'), adult: txt(st.adult, 400), child: txt(st.child, 400), version: txt(st.version, 16) };
  }
  function importOf(raw) {
    const r = obj(raw) || {};
    return {
      status: txt(r.status, 20), photos: Number.isInteger(r.photos) ? r.photos : 0, faces: Number.isInteger(r.faces_found) ? r.faces_found : 0,
      skipped: Number.isInteger(r.skipped) ? r.skipped : 0, uri: txt(r.picker_uri, 500),
      recognised: arr(r.recognised).slice(0, MAX_ROWS).map((p) => ({ name: p && p.child === true ? CHILD : txt(p && p.name, 40) })),
      unknown: arr(r.unknown).filter((x) => typeof x === 'string' && /^c_[0-9a-f]{8,16}$/.test(x)).slice(0, MAX_ROWS),
    };
  }

  // ---- build / render: each service is an Integrations-style card (.integ) -----------------
  const btn = (cls, text, fn) => { const b = mk('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; };
  function card(name, hint) {
    const c = mk('section', 'integ cardx'); c.dataset.state = 'unlinked';
    const head = mk('div', 'ihead'), state = mk('span', 'istate'), body = mk('div', 'ibody');
    head.append(mk('b', '', name), state); body.append(mk('p', 'fine', hint)); c.append(head, body); host.appendChild(c);
    return { c, state, body, extra: mk('div', 'cextra'), acts: mk('div', 'actions') };
  }
  function build() {
    host.textContent = '';
    el.note = mk('p', 'bnote hnote'); el.note.setAttribute('role', 'status'); host.appendChild(el.note);
    const g = el.g = card('GitHub', 'Read-only: your profile, repositories and recent activity. Your token is kept encrypted and never shown again.');
    el.who = mk('p', 'who');
    el.tokenBox = mk('div', 'cfield'); const tl = mk('label', 'k', 'GitHub token'); tl.htmlFor = 'ghToken';
    el.token = mk('input', 'dinput'); el.token.id = 'ghToken'; el.token.type = 'password'; el.token.autocomplete = 'new-password'; el.token.spellcheck = false; el.token.setAttribute('autocapitalize', 'off'); el.token.placeholder = 'Paste a GitHub token';
    el.tokenBox.append(tl, el.token);
    el.gconnect = btn('btn primary lift', 'Connect GitHub', connectGithub);
    el.gdrop = btn('btn lift', 'Disconnect', () => { S.confirm = true; render(); el.gkeep.focus(); });
    el.confirm = mk('div', 'confirm'); el.confirm.setAttribute('role', 'group'); el.confirm.setAttribute('aria-label', 'Confirm disconnect');
    el.gkeep = btn('btn lift', 'Keep', () => { S.confirm = false; render(); el.gdrop.focus(); });
    el.gyes = btn('btn danger lift', 'Disconnect', dropGithub);
    el.confirm.append(mk('span', '', 'Disconnect GitHub? JARVIS forgets the token.'), el.gkeep, el.gyes);
    g.acts.append(el.gconnect, el.gdrop); g.body.append(el.who, el.tokenBox, g.acts, el.confirm);
    const y = el.y = card('YouTube', 'Your own channel and uploads, read-only, through your Google sign-in.');
    el.ywhy = mk('p', 'warn'); y.body.append(el.ywhy);
    const p = el.p = card('Google Photos', 'Pick-only: Google no longer lets apps read a whole library, so you choose the photos. They go to your home laptop to find faces; JARVIS keeps ids, never pictures.');
    el.pwhy = mk('p', 'warn');
    el.pstart = btn('btn lift', 'Choose photos', startPick); el.pimport = btn('btn lift', 'Import chosen photos', runImport);
    el.pinteg = btn('btn lift', 'Open Integrations', () => Deck.open('integrations', { focus: true }));
    el.pout = mk('p', 'bfine cout'); el.enrol = mk('div', 'cenrol');
    p.acts.append(el.pstart, el.pimport, el.pinteg); p.body.append(el.pwhy, p.acts, el.pout, el.enrol);
    [el.who, el.tokenBox, el.g.acts, el.confirm, el.ywhy, el.pwhy, el.pstart, el.pimport, el.pinteg].forEach((n) => { n.hidden = true; });   // until the server has answered
  }
  function setCard(c, ok, label, warn) { c.c.dataset.state = ok ? 'linked' : warn ? 'reconnect' : 'unlinked'; c.state.textContent = label; }
  function render() {
    const d = S.data; if (!d) return;
    const gh = d.github;
    setCard(el.g, gh.connected, gh.connected ? 'Connected' : gh.reconnect ? 'Reconnect' : 'Not connected', gh.reconnect);
    if (gh.connected) el.token.value = '';   // never keep a pasted token in a hidden field
    el.who.hidden = !gh.connected; el.who.replaceChildren('Connected as ', mk('b', '', gh.login || 'GitHub'));
    el.tokenBox.hidden = el.gconnect.hidden = gh.connected; el.gdrop.hidden = !gh.connected || S.confirm; el.confirm.hidden = !(gh.connected && S.confirm);
    el.g.acts.hidden = gh.connected && S.confirm;
    el.gconnect.disabled = el.gdrop.disabled = el.gyes.disabled = S.busy;
    if (gh.reconnect && !gh.connected) el.who.hidden = false, el.who.replaceChildren('Needs reconnecting: paste a new token.');
    setCard(el.y, d.youtube.connected, d.youtube.connected ? 'Connected' : 'Not connected', false);
    el.ywhy.hidden = !!d.youtube.connected || !WHY[d.youtube.reason]; el.ywhy.textContent = WHY[d.youtube.reason] || '';
    setCard(el.p, d.photos.connected, d.photos.connected ? 'Ready' : 'Off', false);
    el.pwhy.hidden = !!d.photos.connected || !WHY[d.photos.reason]; el.pwhy.textContent = WHY[d.photos.reason] || '';
    el.pstart.hidden = el.pimport.hidden = !d.photos.connected; el.pinteg.hidden = !!d.photos.connected;
    el.pstart.disabled = el.pimport.disabled = S.busy;
    renderEnrol();
  }
  function renderEnrol() {
    el.enrol.replaceChildren();
    S.unknown.forEach((id, i) => {
      const row = mk('div', 'crow'), name = mk('input', 'dinput'), nl = mk('label', 'k', 'Name for face ' + (i + 1));
      const box = mk('input'), kid = mk('input'), lbl = mk('label', 'ctick');
      name.id = 'faceName' + i; nl.htmlFor = name.id; name.maxLength = 40;
      box.type = 'checkbox'; kid.type = 'checkbox';
      lbl.append(box, ' ', (S.data && S.data.adult) || 'They agree to be recognised.');
      const kl = mk('label', 'ctick'); kl.append(kid, ' This is a child (a parent or guardian agrees).');
      const go = btn('btn lift bact', 'Add', () => enrol(id, name.value, box.checked, kid.checked));
      row.append(nl, name, lbl, kl, go); el.enrol.appendChild(row);
    });
  }

  // ---- actions -----------------------------------------------------------------------------
  // `after` runs once the card is drawn again: the busy render disables the button that had focus,
  // so a keyboard user is put back on a control that exists in the new state.
  async function guard(fn, fail, after) {
    if (S.busy || !hasApi()) return; S.busy = true; render();
    try { await fn(); } catch (e) { say('bad', detailOf(e) || fail); } finally { S.busy = false; render(); if (after) after(); }
  }
  const connectGithub = () => guard(async () => {
    const token = el.token.value.trim(); if (!token) { say('bad', 'Paste your GitHub token first.'); return; }
    el.token.value = '';      // the token leaves the field at once: a failed save never leaves it sitting there
    await api('/v1/connectors/github', { method: 'PUT', body: { token } });
    S.confirm = false; say('ok', 'GitHub connected.'); await load(true);
  }, 'Couldn\'t connect GitHub. Please try again.', () => { if (!el.gconnect.hidden) el.token.focus(); else el.gdrop.focus(); });
  const dropGithub = () => guard(async () => { S.confirm = false; await api('/v1/connectors/github', { method: 'DELETE' }); say('ok', 'GitHub disconnected.'); await load(true); },
    'Couldn\'t disconnect. Please try again.', () => { (el.tokenBox.hidden ? el.gdrop : el.token).focus(); });
  const startPick = () => guard(async () => {
    const r = obj(await api('/v1/connectors/photos/start', { method: 'POST', body: {} })) || {};
    const uri = txt(r.picker_uri, 500);
    if (!uri.startsWith('https://photos.google.com/')) { say('bad', 'Google Photos didn\'t give a picker link.'); return; }
    window.open(uri, '_blank', 'noopener'); say('ok', 'Choose your photos in the new tab, then press Import.');
  }, 'Couldn\'t open the picker. Please try again.');
  const runImport = () => guard(async () => {
    const r = importOf(await api('/v1/connectors/photos/import', { method: 'POST', body: {} }));
    S.unknown = r.unknown;
    const words = { waiting: 'Still waiting for you to choose photos.', no_session: 'Press Choose photos first.', laptop_offline: 'Your home laptop is off or asleep.', edge_error: 'Your home laptop answered in a way JARVIS could not use.', timed_out: 'That took too long. Your picks are kept: press Import again.' };
    if (r.status === 'waiting' && r.uri.startsWith('https://photos.google.com/')) { window.open(r.uri, '_blank', 'noopener'); }
    if (r.status !== 'done') { say('ok', words[r.status] || 'Nothing to import yet.'); return; }
    el.pout.textContent = r.photos + ' photos looked at, ' + r.faces + ' faces found' + (r.recognised.length ? '; recognised: ' + r.recognised.map((p) => p.name).join(', ') : '') + (r.unknown.length ? '; ' + r.unknown.length + ' not recognised (not named).' : '.');
    say('ok', 'Done.');
  }, 'Couldn\'t import. Please try again.');
  const enrol = (cluster, name, agreed, child) => guard(async () => {
    const body = { cluster, name: name.trim(), relation: 'friend', child, vip: false, given_by: child ? 'parent_guardian' : 'self', consent_version: (S.data && S.data.version) || 'fc1', confirm: agreed === true };
    if (!body.name) { say('bad', 'Type a name first.'); return; }
    const r = obj(await api('/v1/connectors/photos/enrol', { method: 'POST', body })) || {};
    if (r.at_home !== false) S.unknown = S.unknown.filter((x) => x !== cluster);
    say('ok', r.at_home === false ? 'Added. Your laptop is off: press Add again on that face when it is on.' : 'Added.');
  }, 'Couldn\'t add that person. Tick the consent box and try again.');

  async function load(force) {
    if (!hasApi() || (!force && S.data)) return;
    try { S.data = statusOf(await api('/v1/connectors')); } catch (e) { if (e && e.status === 401) return; say('bad', detailOf(e) || 'Couldn\'t read your connectors.'); }
    render();
  }

  build();
  const shown = () => { if (Deck.isOpen('connectors')) load(false); };
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'connectors' && d.open) load(true); });
  document.addEventListener('jarvis:ready', shown);
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) shown();
  window.JarvisConnectors = Object.freeze({ refresh: () => load(true), statusOf, importOf });
})();
