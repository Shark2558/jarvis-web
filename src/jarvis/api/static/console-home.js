// src/jarvis/api/static/console-home.js -- R3 A (docs/plans/r3-home-camera.md D2-D6, D17):
// Integrations -> Home. Built beside #integrations like Telegram. No build step; CSP script-src
// 'self'; ASCII source with backslash-u escapes only; every server string reaches the page through
// textContent (never markup); a field of the wrong type is dropped. Transport is the console's
// api(). Loads when the Integrations panel opens. Device names from Home Assistant are other
// people's words: shown as text only.
// API: GET /v1/home -> {available, linked, state, host, last_seen_at, parts, kit_outdated,
// devices_available}; POST /v1/home/link-code -> {code, expires_in_s}; DELETE /v1/home/link?confirm=1;
// GET /v1/home/kit/info -> {sha256, size, version}; GET /v1/home/kit (zip, a plain link);
// GET /v1/home/devices?catalogue=1 -> {devices:[{entity_id, name, classes, default}]};
// GET /v1/home/devices -> {entities:[{entity_id, label, class}]}; PUT /v1/home/devices {entities}.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STALE_MS = 30 * 1000;
  const POLL_MS = 3000;
  const POLL_MAX_MS = 10 * 60 * 1000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const CODE = /^[0-9A-Za-z-]{4,24}$/;
  const SHA = /^[0-9a-f]{64}$/;
  const STEPS = [
    'Check your laptop: Windows 10 22H2 or Windows 11, plugged in, virtualization enabled.',
    'Download the home kit here and extract it to C:\\ (this makes C:\\JARVIS-Home).',
    'Open PowerShell as administrator, type cd C:\\JARVIS-Home, then powershell -ExecutionPolicy Bypass -File .\\setup-windows.ps1',
    'When Ubuntu opens the first time, choose a user name and a password and write them down.',
    'Say Yes when the script offers to keep the laptop awake when plugged in.',
    'Old phone: install IP Webcam, set a login, mount it facing your own gate and press Start server.',
    'Type the camera address, login and password into the script.',
    'Optional, once the script has finished: create a Home Assistant account and a long-lived token for a non-administrator person, then run setup-windows.ps1 -HaToken and paste it.',
    'Tailscale: when the script asks, allow Funnel in the browser page that opens.',
    'Press Link here and type the code into the script. Wait for Linked.',
    'Frigate: draw a zone named gate over your own gate. Mask the road and your neighbours.',
    'Optional: teach Frigate to tell a parcel on the doorstep.',
    'Optional: add faces from the Faces panel, with the person\'s consent.',
    'Set quiet hours and enable browser notifications in the Alerts panel.',
    'Optional: private camera view on your phone through Tailscale.',
    'Try it: arm Away, walk past the camera, then disarm with your passkey.',
  ];
  const TIERS = {
    read: 'Read only', everyday: 'Everyday', passkey: 'Needs my passkey',
    always_passkey: 'Always my passkey',
  };
  const STATES = {
    not_linked: 'Not linked', linked: 'Linked', online: 'Online', offline: 'Laptop off or asleep',
    unlinked: 'Not linked',
  };
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: false, link: null, timer: 0 };
  let card = null, stateEl = null, bodyEl = null, noteEl = null, dlg = null, settle = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const button = (id, label, cls) => { const b = mk('button', cls || 'btn bact', label); b.type = 'button'; if (id) b.id = id; return b; };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }

  /** GET /v1/home, checked field by field. */
  function normal(raw) {
    const d = obj(raw);
    if (!d || d.available === false) return { available: false, reason: d ? txt(d.reason, 160) : '' };
    const st = typeof d.state === 'string' && STATES[d.state] ? d.state : (d.linked === true ? 'linked' : 'not_linked');
    return {
      available: true,
      linked: d.linked === true,
      state: d.linked === true ? st : 'not_linked',
      host: typeof d.host === 'string' && /^[A-Za-z0-9.-]{1,120}$/.test(d.host) ? d.host : '',
      outdated: d.kit_outdated === true,
      devices: d.devices_available === true,
    };
  }

  // ---- the card -------------------------------------------------------------------------------
  function build() {
    if (card) return true;
    const host = $('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ homelink'); card.id = 'homeSet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'homeHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Home'); title.id = 'homeHead';
    stateEl = mk('span', 'istate', 'Checking\u2026');
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'homeNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'homeBody';
    card.append(head, bodyEl, noteEl);
    const anchor = $('telegramSet') || host;
    anchor.parentNode.insertBefore(card, anchor.nextSibling);
    buildDialog();
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }

  function stepsList() {
    const det = mk('details', 'hsteps'); det.id = 'homeStepsBox';
    det.appendChild(mk('summary', '', 'Setup steps (16)'));
    const ol = mk('ol'); ol.id = 'homeSteps';
    STEPS.forEach((s) => ol.appendChild(mk('li', '', s)));
    det.appendChild(ol);
    return det;
  }
  function kitRow(d) {
    const row = mk('div', 'hkit');
    if (d && d.outdated) row.appendChild(mk('p', 'warn', 'Your home kit is older than this JARVIS. Download it again and run setup-windows.ps1 once more.'));
    const a = mk('a', 'btn bact', 'Download home kit'); a.id = 'homeKit'; a.href = '/v1/home/kit'; a.download = 'JARVIS-Home-kit.zip';
    const sha = mk('p', 'fine hsha'); sha.id = 'homeKitSha';
    row.append(a, sha);
    api('/v1/home/kit/info').then((r) => {
      const o = obj(r);
      if (o && typeof o.sha256 === 'string' && SHA.test(o.sha256)) sha.textContent = 'SHA-256: ' + o.sha256;
    }).catch(() => {});
    return row;
  }

  function renderOff(d) {
    card.dataset.state = 'off'; stateEl.textContent = 'Off';
    bodyEl.appendChild(mk('p', '', d.reason || 'Home is not available on this server yet.'));
  }
  function renderUnlinked(d) {
    card.dataset.state = 'unlinked'; stateEl.textContent = STATES.not_linked;
    bodyEl.append(
      mk('p', '', 'Link your home laptop to see your gate camera and a small set of devices. Video and faces never leave the laptop.'),
      kitRow(d), stepsList());
    const link = button('homeLink', 'Link');
    link.addEventListener('click', () => startLink(link));
    bodyEl.appendChild(link);
  }
  function renderLinked(d) {
    card.dataset.state = d.state; stateEl.textContent = STATES[d.state] || STATES.linked;
    bodyEl.appendChild(mk('p', '', d.state === 'offline'
      ? 'The laptop is off, asleep or offline. JARVIS keeps trying and will tell you.'
      : 'Your home laptop is linked' + (d.host ? ' (' + d.host + ')' : '') + '.'));
    bodyEl.appendChild(kitRow(d));
    const actions = mk('div', 'hactions');
    const dev = button('homeDevices', 'Choose devices');
    dev.disabled = !d.devices;
    dev.addEventListener('click', () => openDevices(dev));
    const re = button('homeRelink', 'Re-link');
    re.addEventListener('click', () => startLink(re));
    const un = button('homeUnlink', 'Unlink');
    un.addEventListener('click', () => askUnlink(un));
    actions.append(dev, re, un);
    bodyEl.append(actions, stepsList());
  }
  function render() {
    if (!build()) return;
    const d = S.data;
    bodyEl.textContent = '';
    if (S.error) {
      card.dataset.state = 'error'; stateEl.textContent = 'Unknown';
      bodyEl.appendChild(mk('p', 'warn', 'Couldn\'t check Home. ' + S.error));
      const r = button('homeRetry', 'Retry');
      r.addEventListener('click', () => { r.disabled = true; load(true); });
      bodyEl.appendChild(r);
      return;
    }
    if (d === undefined) { card.dataset.state = 'loading'; stateEl.textContent = 'Checking\u2026'; bodyEl.appendChild(mk('p', '', 'Checking Home\u2026')); return; }
    if (!d.available) renderOff(d);
    else if (d.linked) renderLinked(d);
    else renderUnlinked(d);
  }

  // ---- the dialog: native modal, Tab stays inside, Esc cancels ---------------------------------
  function buildDialog() {
    dlg = mk('dialog', 'bdialog'); dlg.id = 'homeDialog'; dlg.setAttribute('role', 'alertdialog');
    dlg.setAttribute('aria-labelledby', 'homeDialogTitle'); dlg.setAttribute('aria-describedby', 'homeDialogText');
    const h = mk('h2'); h.id = 'homeDialogTitle';
    const body = mk('div'); body.id = 'homeDialogText';
    const actions = mk('div', 'actions');
    const no = button('homeDialogNo', 'Cancel', 'btn lift');
    const yes = button('homeDialogYes', 'OK', 'btn primary lift');
    actions.append(no, yes);
    dlg.append(h, body, actions);
    document.body.appendChild(dlg);
    yes.addEventListener('click', () => { if (settle) settle(true); });
    no.addEventListener('click', () => { if (settle) settle(false); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('close', () => { if (settle && !dlg.open) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const items = [...dlg.querySelectorAll('button:not([disabled]), a[href], select, input')];
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
  }
  function ask(title, nodes, yes, trigger) {
    if (!dlg || typeof dlg.showModal !== 'function') {
      note('bad', 'This browser can\'t show the confirmation, so nothing was changed.');
      return Promise.resolve(false);
    }
    if (settle) settle(false);
    $('homeDialogTitle').textContent = title;
    const body = $('homeDialogText'); body.textContent = ''; body.append(...nodes);
    const y = $('homeDialogYes'); y.hidden = !yes; if (yes) y.textContent = yes;
    $('homeDialogNo').textContent = yes ? 'Cancel' : 'Close';
    return new Promise((resolve) => {
      settle = (val) => {
        settle = null; stopPoll();
        if (dlg.open) dlg.close();
        if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('homeDialogNo').focus();
    });
  }

  // ---- link -----------------------------------------------------------------------------------
  function stopPoll() { if (S.timer) { clearTimeout(S.timer); S.timer = 0; } S.link = null; }
  async function startLink(trigger) {
    if (!hasApi() || S.busy) return;
    S.busy = true;
    let r = null;
    try {
      r = obj(await api('/v1/home/link-code', { method: 'POST' }));
    } catch (e) {
      if (e && e.status === 401) { S.busy = false; return; }
      note('bad', detailOf(e) || 'Couldn\'t make a code. Please try again.');
    } finally { S.busy = false; }
    if (!r || typeof r.code !== 'string' || !CODE.test(r.code)) return;
    const left = Number.isInteger(r.expires_in_s) && r.expires_in_s > 0 ? r.expires_in_s : 600;
    const status = mk('p', 'fine'); status.id = 'homeWaiting'; status.setAttribute('role', 'status');
    const code = mk('p', 'hcode', r.code); code.id = 'homeCode';
    const stamp = Date.now(); S.link = stamp;
    const show = () => { status.textContent = 'Waiting for the laptop\u2026 ' + Math.max(0, left - Math.floor((Date.now() - stamp) / 1000)) + ' s left'; };
    show();
    const done = ask('Link your laptop', [
      mk('p', '', 'Type this code into the setup script on your laptop. It works once and expires in 10 minutes.'),
      code, status], null, trigger);
    const tick = async () => {
      if (S.link !== stamp) return;
      if (Date.now() - stamp > Math.min(POLL_MAX_MS, left * 1000)) { status.textContent = 'The code expired. Close this and press Link again.'; return; }
      show();
      try {
        const d = normal(await api('/v1/home'));
        if (d.linked) { S.data = d; S.loadedAt = Date.now(); if (settle) settle(true); render(); note('ok', 'Linked.'); return; }
      } catch (e) { if (e && e.status === 401) return; }
      S.timer = setTimeout(tick, POLL_MS);
    };
    S.timer = setTimeout(tick, POLL_MS);
    await done;
  }
  // R3 review S4: while the alarm is on, unlinking switches it off, so it asks what Disarm asks
  // (the passkey for this home and arm rev, or a fresh Google sign-in).
  async function disarmProof() {
    const P = window.JarvisPasskey;
    if (!P || typeof P.supported !== 'function' || !P.supported()) throw new Error('This browser can\'t use passkeys. Disarm in the Home panel first.');
    const a = obj(await api('/v1/home/alarm'));
    const t = a && typeof a.disarm_target === 'string' && /^h_[0-9a-f]{8}:[0-9]{1,12}$/.test(a.disarm_target) ? a.disarm_target : null;
    if (!t) throw new Error('Disarm in the Home panel first, then unlink.');
    return P.prove('home_disarm', t);
  }
  async function askUnlink(trigger) {
    const sure = await ask('Unlink your laptop?', [
      mk('p', '', 'JARVIS will stop talking to your home laptop and forget the link. You can link again at any time.'),
      mk('p', 'bfine', 'If the alarm is on, unlinking switches it off: you will be asked to approve that like Disarm.')], 'Unlink', trigger);
    if (!sure || S.busy) return;
    S.busy = true;
    try {
      try { await api('/v1/home/link?confirm=1', { method: 'DELETE' }); }
      catch (e) {
        if (!e || (e.code !== 'passkey_required' && e.code !== 'passkey_rejected')) throw e;
        await api('/v1/home/link?confirm=1', { method: 'DELETE', body: { proof: await disarmProof() } });
      }
      S.data = normal({ available: true, linked: false }); note('ok', 'Unlinked.');
    } catch (e) {
      if (e && e.code === 'reauth_required') note('bad', 'The alarm is on: disarm it in the Home panel first (it asks you to sign in again), then unlink.');
      else if (!(e && e.status === 401)) note('bad', detailOf(e) || 'Couldn\'t unlink. Please try again.');
    } finally { S.busy = false; render(); }
  }

  // ---- devices --------------------------------------------------------------------------------
  async function openDevices(trigger) {
    if (!hasApi() || S.busy) return;
    let cat, cur;
    try {
      cat = obj(await api('/v1/home/devices?catalogue=1'));
      cur = obj(await api('/v1/home/devices'));
    } catch (e) {
      if (!(e && e.status === 401)) note('bad', detailOf(e) || 'Couldn\'t read your devices. Is the laptop on?');
      return;
    }
    const list = cat && Array.isArray(cat.devices) ? cat.devices : [];
    const have = new Map();
    ((cur && Array.isArray(cur.entities)) ? cur.entities : []).forEach((e) => { if (e && typeof e.entity_id === 'string') have.set(e.entity_id, e); });
    const rows = mk('div', 'hrows'); rows.id = 'homeRows';
    const picks = [];
    list.forEach((it) => {
      if (!it || typeof it.entity_id !== 'string' || !Array.isArray(it.classes)) return;
      const classes = it.classes.filter((c) => typeof c === 'string' && TIERS[c]);
      if (!classes.length) return;
      const row = mk('div', 'hrow');
      const on = mk('input'); on.type = 'checkbox'; on.checked = have.has(it.entity_id);
      on.setAttribute('aria-label', 'Expose ' + txt(it.name || it.entity_id, 60));
      const nm = mk('span', 'hname', txt(it.name, 60) || it.entity_id);
      const sel = mk('select'); sel.setAttribute('aria-label', 'Class of ' + txt(it.name || it.entity_id, 60));
      classes.forEach((c) => { const o = mk('option', '', TIERS[c]); o.value = c; sel.appendChild(o); });
      const prior = have.get(it.entity_id);
      sel.value = prior && classes.includes(prior.class) ? prior.class : classes[0];
      const label = mk('input'); label.type = 'text'; label.maxLength = 40; label.placeholder = 'My name for it';
      label.setAttribute('aria-label', 'My name for ' + txt(it.name || it.entity_id, 60));
      label.value = prior && typeof prior.label === 'string' ? txt(prior.label, 40) : '';
      row.append(on, nm, sel, label);
      rows.appendChild(row);
      picks.push({ id: it.entity_id, on, sel, label });
    });
    if (!picks.length) rows.appendChild(mk('p', '', 'Home Assistant has no devices JARVIS may use.'));
    const sure = await ask('Choose devices', [
      mk('p', '', 'Locks and the alarm always need your passkey. Names come from Home Assistant; give each device your own name.'),
      rows], 'Save', trigger);
    if (!sure) return;
    const entities = picks.filter((p) => p.on.checked).map((p) => ({ entity_id: p.id, class: p.sel.value, label: p.label.value.trim() || null }));
    try {
      await api('/v1/home/devices', { method: 'PUT', body: { entities } });
      note('ok', 'Saved ' + entities.length + ' device' + (entities.length === 1 ? '' : 's') + '.');
    } catch (e) {
      if (!(e && e.status === 401)) note('bad', detailOf(e) || 'Couldn\'t save. Please try again.');
    }
  }

  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try {
        S.data = normal(await api('/v1/home')); S.error = '';
      } catch (e) {
        if (e && e.status === 401) return;
        if (e && e.status === 404) { S.data = { available: false, reason: '' }; S.error = ''; } else { S.error = detailOf(e) || 'Please try again.'; }
      } finally {
        S.loadedAt = Date.now(); S.loading = null; render();
      }
    })();
    return S.loading;
  }

  const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (integOpen()) load(false); });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready() && integOpen()) load(false);

  window.JarvisHome = Object.freeze({ refresh: () => load(true), normal });
})();
