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
  const S = { data: null, unknown: [], busy: false };
  let el = {};

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const Deck = window.JarvisDeck || { isOpen: () => false };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, text) { el.note.className = 'bnote hnote' + (kind === 'bad' ? ' bad' : ''); el.note.textContent = text || ''; }
  const chip = (ok, on, off) => mk('span', 'chip' + (ok ? ' ok' : ''), ok ? on : off);

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

  // ---- build / render ----------------------------------------------------------------------
  function section(title, hint) {
    const s = mk('section', 'csec'); s.append(mk('h3', 'ctitle', title), mk('p', 'chint', hint)); host.appendChild(s); return s;
  }
  function build() {
    host.textContent = '';
    el.note = mk('p', 'bnote hnote'); el.note.setAttribute('role', 'status'); host.appendChild(el.note);
    const g = section('GitHub', 'Read-only: your profile, repositories and recent activity. Your token is kept encrypted and never shown again.');
    el.gstate = mk('div', 'crow');
    el.token = mk('input', 'cinput'); el.token.type = 'password'; el.token.autocomplete = 'off'; el.token.placeholder = 'Paste a GitHub token'; el.token.setAttribute('aria-label', 'GitHub token');
    el.gconnect = mk('button', 'btn', 'Connect GitHub'); el.gconnect.type = 'button'; el.gconnect.addEventListener('click', connectGithub);
    el.gdrop = mk('button', 'btn', 'Disconnect'); el.gdrop.type = 'button'; el.gdrop.addEventListener('click', dropGithub);
    g.append(el.gstate, el.token, el.gconnect, el.gdrop);
    const y = section('YouTube', 'Your own channel and uploads, read-only, through your Google sign-in.');
    el.ystate = mk('div', 'crow'); y.appendChild(el.ystate);
    const p = section('Google Photos', 'Pick-only: Google no longer lets apps read a whole library, so you choose the photos. They go to your home laptop to find faces; JARVIS keeps ids, never pictures.');
    el.pstate = mk('div', 'crow');
    el.pstart = mk('button', 'btn', 'Choose photos'); el.pstart.type = 'button'; el.pstart.addEventListener('click', startPick);
    el.pimport = mk('button', 'btn', 'Import chosen photos'); el.pimport.type = 'button'; el.pimport.addEventListener('click', runImport);
    el.pout = mk('div', 'cout'); el.enrol = mk('div', 'cenrol');
    p.append(el.pstate, el.pstart, el.pimport, el.pout, el.enrol);
  }
  function render() {
    const d = S.data; if (!d) return;
    el.gstate.replaceChildren(chip(d.github.connected, 'Connected' + (d.github.login ? ' as ' + d.github.login : ''), d.github.reconnect ? 'Needs reconnecting: paste a new token' : 'Not connected'));
    el.token.hidden = el.gconnect.hidden = d.github.connected; el.gdrop.hidden = !d.github.connected;
    el.ystate.replaceChildren(chip(d.youtube.connected, 'Connected', 'Not connected'), mk('span', 'chint', d.youtube.connected ? '' : WHY[d.youtube.reason] || ''));
    el.pstate.replaceChildren(chip(d.photos.connected, 'Ready', 'Off'), mk('span', 'chint', d.photos.connected ? '' : WHY[d.photos.reason] || ''));
    el.pstart.disabled = el.pimport.disabled = !d.photos.connected || S.busy;
    renderEnrol();
  }
  function renderEnrol() {
    el.enrol.replaceChildren();
    S.unknown.forEach((id, i) => {
      const row = mk('div', 'crow'), name = mk('input', 'cinput'), box = mk('input'), kid = mk('input'), lbl = mk('label', 'chint');
      name.placeholder = 'Name for face ' + (i + 1); name.maxLength = 40; name.setAttribute('aria-label', name.placeholder);
      box.type = 'checkbox'; kid.type = 'checkbox';
      lbl.append(box, ' ', (S.data && S.data.adult) || 'They agree to be recognised.');
      const kl = mk('label', 'chint'); kl.append(kid, ' This is a child (a parent or guardian agrees).');
      const go = mk('button', 'btn', 'Add'); go.type = 'button';
      go.addEventListener('click', () => enrol(id, name.value, box.checked, kid.checked));
      row.append(name, lbl, kl, go); el.enrol.appendChild(row);
    });
  }

  // ---- actions -----------------------------------------------------------------------------
  async function guard(fn, fail) {
    if (S.busy || !hasApi()) return; S.busy = true; render();
    try { await fn(); } catch (e) { say('bad', detailOf(e) || fail); } finally { S.busy = false; render(); }
  }
  const connectGithub = () => guard(async () => {
    const token = el.token.value.trim(); if (!token) { say('bad', 'Paste your GitHub token first.'); return; }
    await api('/v1/connectors/github', { method: 'PUT', body: { token } });
    el.token.value = ''; say('ok', 'GitHub connected.'); await load(true);
  }, 'Couldn\'t connect GitHub. Please try again.');
  const dropGithub = () => guard(async () => { await api('/v1/connectors/github', { method: 'DELETE' }); say('ok', 'GitHub disconnected.'); await load(true); }, 'Couldn\'t disconnect. Please try again.');
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
