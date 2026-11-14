// src/jarvis/api/static/console-alerts.js -- R3 D10/D11 (docs/plans/r3-home-camera.md):
// Integrations -> Alerts. Quiet hours, "Only urgent things ring", a switch per kind of alert,
// the VIP list, "Say names in alerts", the photo opt-in (with its confirm), and "This device":
// browser notifications by standard Web Push. Built beside #integrations like the Telegram card.
// No build step; CSP script-src 'self'; ASCII source (backslash-u escapes only); every server
// string reaches the page through textContent; a field of the wrong type is dropped. Transport is
// the console's api() (cookie + X-Requested-With, or the bearer token). Loads when the
// Integrations panel opens, never on page load.
// API: GET/PUT /v1/notify/settings, GET/POST /v1/notify/vip, DELETE /v1/notify/vip/{id},
// GET /v1/push/key, GET /v1/push/devices, POST /v1/push/subscribe, DELETE /v1/push/subscribe/{id},
// POST /v1/push/test.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STALE_MS = 30 * 1000;
  const SW_URL = '/static/console-sw.js';
  const SW_SCOPE = '/static/push/';
  const DEVICE_KEY = 'jarvis.push.device';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const KINDS = [
    ['home_intruder', 'Someone at the camera while the alarm is armed'],
    ['home_hazard', 'Smoke, gas or water alarm at home'],
    ['home_summary', 'A summary of many alerts at once'],
    ['home_package', 'A package was left'],
    ['home_offline', 'My home laptop stopped answering'],
    ['home_offline_idle', 'Laptop stopped answering (alarm off)'],
    ['home_arm_failed', 'The alarm could not be armed'],
    ['approval_waiting', 'Something is waiting for my approval'],
    ['vault_expiry', 'A document in my vault is due to expire'],
    ['home_greeting', 'Someone JARVIS recognised arrived'],
    ['home_online', 'My home laptop is back'],
    ['offline_on', 'Offline mode switched on'],
    ['offline_off', 'Offline mode switched off'],
    ['brief_ready', 'My morning brief is ready'],
    ['book_sealed', 'A release\'s build book was sealed in my vault'],
    ['book_seal_failed', 'A release\'s build book could not be sealed'],
    ['book_session_closed', 'A build book session closed'],
    // R11 D5: the helpers (each one also has its own switch in the Helpers panel)
    ['disaster_alert', 'A disaster warning for my area (rings at night)'],
    ['bill_due', 'A bill is due'],
    ['birthday', 'A birthday in my contacts today'],
    ['chore_due', 'A chore on the rota is due'],
    ['maintenance_due', 'Home upkeep is due'],
    ['weather_warning', 'A weather warning for my area'],
    ['breach_notice', 'A data-breach notice arrived in my mail'],
    ['nudge_standup', 'Nudge: time to stand up'],
    ['nudge_hydrate', 'Nudge: drink some water'],
    ['nudge_activity', 'Nudge: a planned activity didn\'t happen'],
    ['nudge_free_time', 'Nudge: an idea for free time'],
    ['nudge_focus', 'Nudge: my top priority now'],
    ['weather_note', 'A minor weather note'],
    ['series_checkin', 'A planned session: did it happen?'],
    ['faces_to_name', 'New faces to name from my photo folder'],
    ['sos_sent', 'An SOS was sent'],
    ['phone_linked', 'A phone was linked to JARVIS'],
    ['sos_contact_left', 'An emergency contact left'],
    ['phone_unlinked', 'A phone was unlinked'],
    ['watch_stale', 'The watch has not synced for a day'],
    // R5.1's two systems rings (their rows were missing) and R14 D6: JARVIS's own health, backups
    ['health_fault', 'One of JARVIS\'s systems is down'],
    ['vitals_critical', 'A key, quota or bill reached its limit'],
    ['job_failing', 'Background jobs keep failing'],
    ['clock_stopped', 'One of JARVIS\'s clocks stopped'],
    ['brief_missed', 'My morning brief was not made'],
    ['errors_piling', 'Errors are piling up'],
    ['spend_spike', 'A day\'s AI spend is far above normal'],
    ['deploy_changed', 'A new version of JARVIS is live'],
    ['backup_problem', 'A backup or the restore drill has a problem'],
    ['selfwatch_ok', 'JARVIS has recovered'],
    ['backup_ok', 'The monthly restore drill passed'],
  ];
  const LEVEL = { urgent: 'Urgent', important: 'Important', info: 'Just so you know' };
  const S = { data: undefined, vip: [], devices: [], error: '', loadedAt: 0, loading: null, busy: false, key: '' };
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
  const HHMM = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

  /** GET /v1/notify/settings, checked field by field. null when the server has it off. */
  function normal(raw) {
    const d = obj(raw);
    if (!d || d.available === false) return null;
    const q = obj(d.quiet) || {};
    const kinds = {};
    const k = obj(d.kinds) || {};
    KINDS.forEach(([id]) => {
      const e = obj(k[id]) || {};
      kinds[id] = {
        switch: e.switch === 'off' || e.switch === 'feed' ? e.switch : 'on',
        level: LEVEL[e.level] ? e.level : 'important',
        fixed: e.fixed === true,
      };
    });
    return {
      quietOn: q.on !== false,
      start: typeof q.start === 'string' && HHMM.test(q.start) ? q.start : '23:00',
      end: typeof q.end === 'string' && HHMM.test(q.end) ? q.end : '06:30',
      onlyUrgent: d.ring_for !== 'important',
      names: d.names_in_alerts === true,
      photo: !!(obj(d.snapshot) && d.snapshot.on === true),
      kinds,
    };
  }
  const vips = (raw) => (Array.isArray(raw && raw.vip) ? raw.vip.map(obj).filter((v) => v && /^v_[0-9a-f]{8}$/.test(v.id)).slice(0, 20)
    .map((v) => ({ id: v.id, kind: v.kind === 'email' ? 'email' : 'phone', hint: txt(v.hint, 60) })) : []);
  const devices = (raw) => (Array.isArray(raw && raw.devices) ? raw.devices.map(obj).filter((v) => v && /^w_[0-9a-f]{8}$/.test(v.id))
    .slice(0, 5).map((v) => ({ id: v.id, name: txt(v.name, 40) || 'Browser' })) : []);

  // ---- the card -------------------------------------------------------------------------------
  function build() {
    if (card) return true;
    const host = $('telegramSet') || $('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ alerts'); card.id = 'alertsSet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'alertsHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Alerts'); title.id = 'alertsHead';
    stateEl = mk('span', 'istate', 'Checking\u2026');
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'alertsNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'alertsBody';
    card.append(head, bodyEl, noteEl);
    host.parentNode.insertBefore(card, host.nextSibling);
    buildDialog();
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }
  function toggleRow(id, label, on, onClick, hint) {
    const row = mk('div', 'trow');
    const t = mk('div', 'btxt'); t.appendChild(mk('b', '', label));
    if (hint) t.appendChild(mk('span', 'fine', hint));
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
    b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', label);
    const track = mk('span', 'track'); track.appendChild(mk('i', ''));
    b.append(track, mk('span', 'st', on ? 'On' : 'Off'));
    if (S.busy) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(!on); });
    row.append(t, b);
    return row;
  }
  function section(title) { const s = mk('div', 'asec'); s.appendChild(mk('h3', '', title)); return s; }

  function quietBlock(d) {
    const s = section('Quiet hours');
    s.appendChild(toggleRow('alertsQuiet', 'Hold calm alerts at night', d.quietOn, (on) => put({ quiet: { on } }, 'Saved.'),
      'Burglar, smoke and gas alarms, and people on your VIP list, still ring.'));
    const row = mk('div', 'arow');
    const from = mk('input'); from.type = 'time'; from.id = 'alertsFrom'; from.value = d.start; from.setAttribute('aria-label', 'Quiet hours start');
    const to = mk('input'); to.type = 'time'; to.id = 'alertsTo'; to.value = d.end; to.setAttribute('aria-label', 'Quiet hours end');
    const save = button('alertsQuietSave', 'Save times');
    save.addEventListener('click', () => {
      if (!HHMM.test(from.value) || !HHMM.test(to.value)) { note('bad', 'Pick both times.'); return; }
      put({ quiet: { start: from.value, end: to.value } }, 'Saved.');
    });
    row.append(mk('span', '', 'From'), from, mk('span', '', 'to'), to, save);
    s.appendChild(row);
    s.appendChild(toggleRow('alertsOnlyUrgent', 'Only urgent things ring', d.onlyUrgent, (on) => put({ ring_for: on ? 'urgent' : 'important' }, 'Saved.'),
      'Everything else arrives silently.'));
    return s;
  }
  function kindsBlock(d) {
    const s = section('Which alerts');
    const list = mk('div', 'akinds'); list.id = 'alertsKinds';
    KINDS.forEach(([id, label]) => {
      const k = d.kinds[id];
      const row = mk('div', 'trow');
      const t = mk('div', 'btxt'); t.appendChild(mk('b', '', label));
      t.appendChild(mk('span', 'fine', LEVEL[k.level] + (k.fixed ? ' - always on' : '')));
      row.appendChild(t);
      if (!k.fixed) {
        const sel = mk('select'); sel.id = 'alertsKind_' + id; sel.setAttribute('aria-label', label);
        [['on', 'Alert me'], ['feed', 'Feed only'], ['off', 'Off']].forEach(([v, l]) => { const o = mk('option', '', l); o.value = v; sel.appendChild(o); });
        sel.value = k.switch;
        sel.addEventListener('change', () => put({ kinds: { [id]: sel.value } }, 'Saved.'));
        row.appendChild(sel);
      }
      list.appendChild(row);
    });
    s.appendChild(list);
    return s;
  }
  function vipBlock() {
    const s = section('People who always ring');
    s.appendChild(mk('p', 'fine', 'People you mark VIP in Faces ring too. Phone numbers and emails are for calls, coming later.'));
    const ul = mk('ul', 'avips'); ul.id = 'alertsVips';
    S.vip.forEach((v) => {
      const li = mk('li');
      const who = (v.kind === 'email' ? 'Email ' : 'Phone ') + (v.hint || '');
      li.appendChild(mk('span', '', who));
      const rm = button('', 'Remove', 'btn bact'); rm.setAttribute('aria-label', 'Remove ' + who);
      rm.addEventListener('click', () => removeVip(v.id));
      li.appendChild(rm);
      ul.appendChild(li);
    });
    s.appendChild(ul);
    const row = mk('div', 'arow');
    const kind = mk('select'); kind.id = 'alertsVipKind'; kind.setAttribute('aria-label', 'Kind');
    [['phone', 'Phone'], ['email', 'Email']].forEach(([v, l]) => { const o = mk('option', '', l); o.value = v; kind.appendChild(o); });
    const ref = mk('input'); ref.type = 'text'; ref.id = 'alertsVipRef'; ref.maxLength = 120; ref.setAttribute('aria-label', 'Phone number or email');
    const add = button('alertsVipAdd', 'Add');
    add.addEventListener('click', () => addVip(kind.value, ref.value));
    row.append(kind, ref, add);
    s.appendChild(row);
    return s;
  }
  function privacyBlock(d) {
    const s = section('Words and pictures');
    s.appendChild(toggleRow('alertsNames', 'Say names in alerts', d.names, (on) => put({ names_in_alerts: on }, 'Saved.'),
      'Off: "a person JARVIS recognised". A child is never named.'));
    s.appendChild(toggleRow('alertsPhoto', 'Send a small photo with burglar alerts', d.photo, askPhoto,
      'Off by default. The photo goes to Telegram only, never to browsers.'));
    return s;
  }
  function deviceBlock() {
    const s = section('This device');
    const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    if (!supported) {
      s.appendChild(mk('p', 'fine', 'This browser can\'t show notifications. On an iPhone they work only for a web app added to the Home Screen.'));
    } else {
      const en = button('alertsEnable', 'Enable browser notifications');
      en.addEventListener('click', () => enable(en));
      s.appendChild(en);
    }
    const ul = mk('ul', 'avips'); ul.id = 'alertsDevices';
    S.devices.forEach((v) => {
      const li = mk('li');
      li.appendChild(mk('span', '', v.name));
      const rm = button('', 'Remove', 'btn bact'); rm.setAttribute('aria-label', 'Remove ' + v.name);
      rm.addEventListener('click', () => removeDevice(v.id));
      li.appendChild(rm);
      ul.appendChild(li);
    });
    s.appendChild(ul);
    const test = button('alertsTest', 'Test (Telegram and this device)');
    test.addEventListener('click', () => testAlert(test));
    s.appendChild(test);
    return s;
  }

  function render() {
    if (!build()) return;
    bodyEl.textContent = '';
    if (S.error) {
      card.dataset.state = 'error'; stateEl.textContent = 'Unknown';
      bodyEl.appendChild(mk('p', 'warn', 'Couldn\'t check your alert settings. ' + S.error));
      const r = button('alertsRetry', 'Retry');
      r.addEventListener('click', () => { r.disabled = true; load(true); });
      bodyEl.appendChild(r);
      return;
    }
    if (S.data === undefined) { card.dataset.state = 'loading'; stateEl.textContent = 'Checking\u2026'; bodyEl.appendChild(mk('p', '', 'Checking your alert settings\u2026')); return; }
    if (S.data === null) {
      card.dataset.state = 'off'; stateEl.textContent = 'Off';
      bodyEl.appendChild(mk('p', '', 'Alerts aren\'t set up on this server yet.'));
      return;
    }
    card.dataset.state = 'ready'; stateEl.textContent = S.data.onlyUrgent ? 'Urgent only' : 'All important';
    bodyEl.append(quietBlock(S.data), kindsBlock(S.data), vipBlock(), privacyBlock(S.data), deviceBlock());
  }

  // ---- the confirm dialog: native modal, Tab stays inside, Esc cancels --------------------------
  function buildDialog() {
    dlg = mk('dialog', 'bdialog'); dlg.id = 'alertsDialog'; dlg.setAttribute('role', 'alertdialog');
    dlg.setAttribute('aria-labelledby', 'alertsDialogTitle'); dlg.setAttribute('aria-describedby', 'alertsDialogText');
    const h = mk('h2'); h.id = 'alertsDialogTitle';
    const body = mk('div'); body.id = 'alertsDialogText';
    const actions = mk('div', 'actions');
    const no = button('alertsDialogNo', 'Cancel', 'btn lift');
    const yes = button('alertsDialogYes', 'OK', 'btn primary lift');
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
      const items = [...dlg.querySelectorAll('button:not([disabled])')];
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
  }
  function ask(title, nodes, yes, trigger) {
    if (!dlg || typeof dlg.showModal !== 'function') { note('bad', 'This browser can\'t show the confirmation, so nothing was changed.'); return Promise.resolve(false); }
    if (settle) settle(false);
    $('alertsDialogTitle').textContent = title;
    const body = $('alertsDialogText'); body.textContent = ''; body.append(...nodes);
    $('alertsDialogYes').textContent = yes;
    return new Promise((resolve) => {
      settle = (val) => {
        settle = null;
        if (dlg.open) dlg.close();
        if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('alertsDialogNo').focus(); // the safe choice is where Enter lands
    });
  }

  // ---- actions --------------------------------------------------------------------------------
  async function call(path, opts, ok) {
    if (!hasApi() || S.busy) return null;
    S.busy = true; render();
    try {
      const r = await api(path, opts);
      if (ok) note('ok', ok);
      return r === undefined ? {} : r;
    } catch (e) {
      if (e && e.status === 401) return null;
      note('bad', detailOf(e) || 'Couldn\'t do that. Please try again.');
      return null;
    } finally {
      S.busy = false; render();
    }
  }
  async function put(body, ok) {
    const r = await call('/v1/notify/settings', { method: 'PUT', body }, ok);
    if (r) { S.data = normal(r); render(); }
  }
  async function askPhoto(on) {
    if (on) {
      const sure = await ask('Send a small photo with burglar alerts?', [
        mk('p', 'strong', 'Telegram keeps chats on its servers; the photo stays there until you delete the message.'),
        mk('p', '', 'Only burglar alerts carry a photo, one small picture, sent to Telegram and nowhere else. JARVIS never stores it. You can switch this off here at any time.')],
      'Switch on', $('alertsPhoto'));
      if (!sure) return;
      put({ snapshot: { on: true, confirm: true } }, 'Photos are on for burglar alerts.');
    } else {
      put({ snapshot: { on: false } }, 'Photos are off.');
    }
  }
  async function addVip(kind, ref) {
    const value = txt(ref, 120);
    if (!value) { note('bad', 'Type a phone number or an email first.'); return; }
    const r = await call('/v1/notify/vip', { method: 'POST', body: { kind, ref: value } }, 'Added.');
    if (r) await loadVip();
    render();
  }
  async function removeVip(id) {
    const r = await call('/v1/notify/vip/' + encodeURIComponent(id), { method: 'DELETE' }, 'Removed.');
    if (r) await loadVip();
    render();
  }
  async function loadVip() { try { S.vip = vips(await api('/v1/notify/vip')); } catch (_) { S.vip = []; } }
  async function loadDevices() { try { S.devices = devices(await api('/v1/push/devices')); } catch (_) { S.devices = []; } }

  const b64url = (s) => {
    const pad = '='.repeat((4 - (s.length % 4)) % 4);
    const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  function deviceName() {
    const ua = navigator.userAgent || '';
    const br = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : 'Browser';
    const os = /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : 'this device';
    return br + ' on ' + os;
  }
  function activated(reg) {
    if (reg.active) return Promise.resolve(reg);
    const w = reg.installing || reg.waiting;
    if (!w) return Promise.reject(new Error('no worker'));
    return new Promise((resolve, reject) => {
      w.addEventListener('statechange', () => { if (w.state === 'activated') resolve(reg); else if (w.state === 'redundant') reject(new Error('redundant')); });
    });
  }
  async function enable(trigger) {
    if (S.busy) return;
    note('', '');
    let perm;
    try { perm = await Notification.requestPermission(); } catch (_) { perm = 'denied'; }
    if (perm !== 'granted') { note('bad', 'Notifications are blocked for this site. Allow them in your browser\'s site settings, then try again.'); return; }
    S.busy = true; render();
    try {
      const k = obj(await api('/v1/push/key'));
      if (!k || k.available === false || typeof k.key !== 'string') throw new Error('Browser notifications aren\'t set up on this server.');
      const reg = await activated(await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE }));
      const old = await reg.pushManager.getSubscription();
      const sub = old || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64url(k.key) });
      const j = sub.toJSON();
      const keys = obj(j.keys) || {};
      const r = obj(await api('/v1/push/subscribe', { method: 'POST', body: { name: deviceName(), endpoint: j.endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } } }));
      if (r && typeof r.id === 'string') { try { localStorage.setItem(DEVICE_KEY, r.id); } catch (_) { /* private mode */ } }
      note('ok', 'Notifications are on for this device.');
      await loadDevices();
    } catch (e) {
      if (!(e && e.status === 401)) note('bad', detailOf(e) || 'Couldn\'t switch notifications on. Please try again.');
    } finally {
      S.busy = false; render();
      if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
    }
  }
  async function removeDevice(id) {
    const r = await call('/v1/push/subscribe/' + encodeURIComponent(id), { method: 'DELETE' }, 'Removed.');
    if (!r) return;
    let mine = null;
    try { mine = localStorage.getItem(DEVICE_KEY); } catch (_) { mine = null; }
    if (mine === id) {
      try {
        const reg = await navigator.serviceWorker.getRegistration(SW_SCOPE);
        const sub = reg ? await reg.pushManager.getSubscription() : null;
        if (sub) await sub.unsubscribe();
        localStorage.removeItem(DEVICE_KEY);
      } catch (_) { /* the server side is already gone */ }
    }
    await loadDevices();
    render();
  }
  async function testAlert(trigger) {
    const r = obj(await call('/v1/push/test', { method: 'POST' }));
    if (!r) return;
    if (r.sent === true) note('ok', 'Test sent' + (r.telegram === true ? ' to Telegram' : '') + (Number.isInteger(r.browsers) && r.browsers > 0 ? (r.telegram === true ? ' and ' : ' to ') + 'this device' : '') + '.');
    else note('bad', 'The test was not sent' + (typeof r.reason === 'string' && r.reason ? ': ' + txt(r.reason, 120) : '.'));
    if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
  }

  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try {
        S.data = normal(await api('/v1/notify/settings')); S.error = '';
        if (S.data) await Promise.all([loadVip(), loadDevices()]);
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
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (integOpen()) load(false); });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready() && integOpen()) load(false);

  window.JarvisAlerts = Object.freeze({ refresh: () => load(true), normal });
})();
