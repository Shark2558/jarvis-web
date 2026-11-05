// src/jarvis/api/static/console-home-panel.js -- R3 B: the Home panel. A large Armed / Disarmed /
// Arming state with Arm (Away / Night) and Disarm, camera chips, a Today / Yesterday feed, a history
// form and the camera and zone names (collapsed). Disarm asks first (focus stays inside the dialog),
// then proves it with the owner's passkey for exactly this home and arm number (window.JarvisPasskey,
// purpose home_disarm); without passkeys the server wants a Google sign-in from the last 5 minutes.
// "Armed" is shown only once the laptop confirmed it; until then the panel says it is waiting.
// Everything the server sends reaches the page through textContent, never as markup. No build step;
// CSP script-src 'self'; ASCII source with backslash-u escapes only. Transport is the console's api().
// Mounts into #p-home .pbody (the panel shell is in console.html). Listens: jarvis:ready, jarvis:panel
// (Home shown), jarvis:reply (a tool may have armed or disarmed).
// API: GET /v1/home/alarm -> {available, armed, mode, confirmed, pending_since, disarm_target,
// dropped_disarmed}; POST /v1/home/arm {mode}; POST /v1/home/disarm {proof?}; GET /v1/home/cameras ->
// {cameras:[{id, label, alarm_zones, package_zone, online, last_event_at}], retention_days, greetings,
// model_note}; PUT /v1/home/cameras; GET /v1/home/feed?day= -> {items:[{at, words, camera, zone, who,
// decision, sent}]}; GET /v1/home/history?what&from&to&camera&who -> {items, more, kept_days, note}.
(() => {
  'use strict';
  const panel = document.getElementById('p-home');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const ID = /^[a-z0-9_]{1,24}$/, TARGET = /^h_[0-9a-f]{8}:[0-9]{1,12}$/;
  const STALE_MS = 30 * 1000, POLL_MS = 3000, POLL_MAX = 100, MAX_ROWS = 100;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const LAPTOP = 'Your home laptop is off or asleep \u2014 the camera can\'t see or alert you.';
  const DECISION = { ring: 'alerted you', silent: 'sent quietly', held: 'held until morning', dropped: 'noted only', failed: 'could not be sent' };
  const S = { alarm: undefined, cams: undefined, feed: undefined, day: 'today', hist: null, loadedAt: 0, busy: false, poll: 0, polls: 0 };
  let el = {}, settle = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const Deck = window.JarvisDeck || { isOpen: () => false };
  const clock = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, text, link) {
    el.note.className = 'bnote hnote' + (kind === 'bad' ? ' bad' : '');
    el.note.textContent = text || '';
    if (link) { const a = mk('a', 'hlink', link.text); a.href = link.href; el.note.append(' ', a); }
  }

  // ---- normalise what the server sent ------------------------------------------------------
  function alarmOf(raw) {
    const d = obj(raw);
    if (!d) return null;
    if (d.available !== true) return { available: false, reason: txt(d.reason, 200) || 'Not available on this server.' };
    const t = typeof d.disarm_target === 'string' && TARGET.test(d.disarm_target) ? d.disarm_target : null;
    return { available: true, armed: d.armed === true, mode: d.mode === 'night' ? 'night' : 'away', confirmed: d.confirmed === true,
      target: t, dropped: Number.isInteger(d.dropped_disarmed) ? d.dropped_disarmed : 0, zones: d.zones_configured !== false };
  }
  function camsOf(raw) {
    const d = obj(raw);
    if (!d || d.available !== true) return { available: false, cams: [], retention: 7, greetings: false, note: '' };
    const cams = arr(d.cameras).slice(0, 8).map((c) => {
      const it = obj(c);
      if (!it || typeof it.id !== 'string' || !ID.test(it.id)) return null;
      return { id: it.id, label: txt(it.label, 30) || it.id, zones: arr(it.alarm_zones).filter((z) => typeof z === 'string' && ID.test(z)),
        pkg: typeof it.package_zone === 'string' && ID.test(it.package_zone) ? it.package_zone : '',
        online: typeof it.online === 'boolean' ? it.online : null, last: typeof it.last_event_at === 'number' ? it.last_event_at : null };
    }).filter(Boolean);
    return { available: true, cams, retention: Number.isInteger(d.retention_days) ? d.retention_days : 7, greetings: d.greetings === true, note: txt(d.model_note, 200) };
  }
  const rowsOf = (raw) => arr(obj(raw) && raw.items).slice(0, MAX_ROWS).map(obj).filter(Boolean);

  // ---- build -------------------------------------------------------------------------------
  function build() {
    const root = mk('div', 'home'); root.id = 'home';
    el.note = mk('div', 'bnote hnote'); el.note.id = 'homeNote'; el.note.setAttribute('role', 'status'); el.note.setAttribute('aria-live', 'polite');
    el.state = mk('div', 'hstate off'); el.state.id = 'homeState'; el.state.setAttribute('role', 'status');
    el.sub = mk('p', 'bfine hsub'); el.sub.id = 'homeSub';
    const acts = mk('div', 'hacts');
    el.away = mk('button', 'btn lift bact', 'Arm (Away)'); el.away.type = 'button'; el.away.id = 'homeArmAway';
    el.night = mk('button', 'btn bact', 'Arm (Night)'); el.night.type = 'button'; el.night.id = 'homeArmNight';
    el.off = mk('button', 'btn bact', 'Disarm'); el.off.type = 'button'; el.off.id = 'homeDisarm';
    el.away.addEventListener('click', () => arm('away')); el.night.addEventListener('click', () => arm('night'));
    el.off.addEventListener('click', () => disarm());
    acts.append(el.away, el.night, el.off);
    el.chips = mk('ul', 'hchips'); el.chips.id = 'homeCams'; el.chips.setAttribute('aria-label', 'Cameras');
    el.tabs = mk('div', 'hdays'); el.tabs.setAttribute('role', 'group'); el.tabs.setAttribute('aria-label', 'Day');
    ['today', 'yesterday'].forEach((d) => {
      const b = mk('button', 'btn bact', d === 'today' ? 'Today' : 'Yesterday'); b.type = 'button'; b.dataset.day = d;
      b.addEventListener('click', () => { S.day = d; loadFeed(); }); el.tabs.appendChild(b);
    });
    el.feed = mk('ul', 'hfeed'); el.feed.id = 'homeFeed'; el.feed.setAttribute('aria-label', 'What the camera noted');
    el.feedEmpty = mk('p', 'empty'); el.feedEmpty.id = 'homeFeedEmpty';
    root.append(el.note, el.state, el.sub, acts, el.chips, mk('h3', 'hh', 'What happened'), el.tabs, el.feedEmpty, el.feed, historyForm(), settings(), dialog(),
      mk('p', 'bfine', 'Works only while your home laptop is on, awake and online. This is a home helper, not a monitored alarm service: a person can be missed.'));
    host.appendChild(root);
  }
  function historyForm() {
    const d = mk('details', 'hbox'); d.id = 'homeHist';
    d.appendChild(mk('summary', '', 'Search the camera history'));
    const f = mk('form', 'hform'); f.id = 'homeHistForm';
    const field = (label, node) => { const l = mk('label', 'hfield'); l.append(mk('span', 'bl', label), node); return l; };
    el.what = mk('select', 'tin'); [['any', 'Anything'], ['person', 'People'], ['car', 'Cars'], ['package', 'Packages']].forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; el.what.appendChild(o); });
    el.hcam = mk('select', 'tin'); el.who = mk('select', 'tin'); [['', 'Anyone'], ['known', 'People JARVIS recognises'], ['unknown', 'Someone JARVIS didn\'t recognise']].forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; el.who.appendChild(o); });
    el.from = mk('input', 'tin'); el.from.type = 'datetime-local'; el.to = mk('input', 'tin'); el.to.type = 'datetime-local';
    const go = mk('button', 'btn lift bact', 'Search'); go.type = 'submit';
    el.hres = mk('ul', 'hfeed'); el.hres.id = 'homeHistResults'; el.hmore = mk('p', 'bfine'); el.hmore.id = 'homeHistNote';
    f.append(field('Looking for', el.what), field('Camera', el.hcam), field('From', el.from), field('To', el.to), field('Who', el.who), go);
    f.addEventListener('submit', (e) => { e.preventDefault(); search(); });
    d.append(f, el.hmore, el.hres);
    return d;
  }
  function settings() {
    const d = mk('details', 'hbox'); d.id = 'homeSettings';
    d.appendChild(mk('summary', '', 'Camera and zone names'));
    d.appendChild(mk('p', 'bfine', 'Draw zones only over your own gate and doorstep. Mask the road and your neighbours\' doors and windows - JARVIS must not watch them.'));
    el.rows = mk('div', 'hrows'); el.rows.id = 'homeCamRows';
    const add = mk('button', 'btn bact', 'Add a camera'); add.type = 'button'; add.addEventListener('click', () => { camRow({ id: '', label: '', zones: [], pkg: '' }, true); });
    el.keep = mk('input', 'tin'); el.keep.type = 'number'; el.keep.min = '1'; el.keep.max = '30'; el.keep.id = 'homeKeep';
    el.greet = mk('input'); el.greet.type = 'checkbox'; el.greet.id = 'homeGreet';
    const gl = mk('label', 'hfield'); gl.append(el.greet, ' Show a line when someone I added arrives');
    const kl = mk('label', 'hfield'); kl.append(mk('span', 'bl', 'Keep recordings at home (days)'), el.keep);
    const save = mk('button', 'btn lift bact', 'Save names'); save.type = 'button'; save.id = 'homeSave'; save.addEventListener('click', saveCams);
    el.model = mk('p', 'bfine'); el.model.id = 'homeModel';
    d.append(el.rows, add, kl, gl, el.model, save);
    return d;
  }
  function dialog() {
    const dlg = mk('dialog', 'bdialog'); dlg.id = 'homeDialog'; dlg.setAttribute('role', 'alertdialog'); dlg.setAttribute('aria-labelledby', 'homeDialogTitle');
    const h = mk('h3', '', 'Switch off the burglar alarm?'); h.id = 'homeDialogTitle';
    el.dtext = mk('p', '', 'The camera at your gate stops alerting you until you arm it again. You will be asked for your passkey.');
    const row = mk('div', 'brow');
    el.dno = mk('button', 'btn', 'Keep it on'); el.dno.type = 'button';
    el.dyes = mk('button', 'btn lift', 'Disarm'); el.dyes.type = 'button';
    row.append(el.dno, el.dyes); dlg.append(h, el.dtext, row);
    el.dno.addEventListener('click', () => settle && settle(false)); el.dyes.addEventListener('click', () => settle && settle(true));
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      if (e.shiftKey && document.activeElement === el.dno) { e.preventDefault(); el.dyes.focus(); }
      else if (!e.shiftKey && document.activeElement === el.dyes) { e.preventDefault(); el.dno.focus(); }
    });
    el.dlg = dlg;
    return dlg;
  }
  function confirmDisarm(trigger) {
    if (typeof el.dlg.showModal !== 'function') return Promise.resolve(false);
    return new Promise((resolve) => {
      settle = (v) => { settle = null; if (el.dlg.open) el.dlg.close(); if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true }); resolve(v); };
      el.dlg.showModal(); el.dno.focus();
    });
  }

  // ---- render ------------------------------------------------------------------------------
  function render() {
    const a = S.alarm;
    el.state.className = 'hstate';
    if (a === undefined) { el.state.textContent = 'Loading\u2026'; el.state.classList.add('off'); }
    else if (!a || !a.available) { el.state.textContent = 'Not available'; el.state.classList.add('off'); el.sub.textContent = (a && a.reason) || ''; }
    else if (a.armed && !a.confirmed) { el.state.textContent = 'Arming\u2026'; el.state.classList.add('wait'); el.sub.textContent = 'Waiting for your laptop to confirm. ' + LAPTOP; }
    else if (a.armed) { el.state.textContent = 'Armed (' + (a.mode === 'night' ? 'Night' : 'Away') + ')'; el.state.classList.add('on'); el.sub.textContent = a.zones ? 'A person at your gate raises an alert within seconds.' : 'JARVIS is not protecting anything yet: no camera has an alarm zone. Choose the gate zone under Cameras.'; }
    else { el.state.textContent = 'Disarmed'; el.state.classList.add('off'); el.sub.textContent = a.dropped ? 'The laptop sent ' + a.dropped + ' alerts while disarmed - download the home kit again.' : 'Nothing is watching the gate for burglars.'; }
    const ok = !!(a && a.available), armed = ok && a.armed;
    [el.away, el.night].forEach((b) => { b.disabled = !ok; });
    el.off.disabled = !armed;
    el.chips.textContent = '';
    const cams = S.cams && S.cams.available ? S.cams.cams : [];
    cams.forEach((c) => {
      const li = mk('li', 'hchip ' + (c.online === true ? 'up' : c.online === false ? 'down' : ''));
      li.append(mk('b', '', c.label), mk('small', '', (c.online === true ? 'online' : c.online === false ? 'offline' : 'not seen yet') + (c.last ? ' \u00b7 last event ' + clock(new Date(c.last * 1000).toISOString()) : '')));
      el.chips.appendChild(li);
    });
    if (S.cams && S.cams.available && !cams.length) el.chips.appendChild(mk('li', 'bfine', 'No camera named yet. Open "Camera and zone names" below.'));
    el.tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.day === S.day)));
    renderFeed(); renderSettings();
  }
  function line(it, withDecision) {
    const li = mk('li', 'hrow');
    li.append(mk('span', 'btime', clock(txt(it.at, 40)) || '\u2014'), mk('span', 'htxt', txt(it.words, 200)));
    if (withDecision && DECISION[it.decision]) li.appendChild(mk('small', 'tmeta', DECISION[it.decision]));
    return li;
  }
  function renderFeed() {
    el.feed.textContent = '';
    if (S.feed === undefined) { el.feedEmpty.textContent = 'The feed loads when this panel opens.'; return; }
    el.feedEmpty.textContent = S.feed.length ? '' : (S.day === 'today' ? 'Nothing noted today.' : 'Nothing noted yesterday.');
    S.feed.forEach((it) => el.feed.appendChild(line(it, true)));
  }
  function renderSettings() {
    const c = S.cams;
    if (!c || !c.available) return;
    el.rows.textContent = '';
    c.cams.forEach((cam) => camRow(cam, false));
    el.keep.value = String(c.retention); el.greet.checked = c.greetings;
    el.model.textContent = c.note;
    el.hcam.textContent = '';
    const any = mk('option', '', 'All cameras'); any.value = ''; el.hcam.appendChild(any);
    c.cams.forEach((cam) => { const o = mk('option', '', cam.label); o.value = cam.id; el.hcam.appendChild(o); });
  }
  function camRow(cam, fresh) {
    const r = mk('div', 'hcam'); r.dataset.fresh = fresh ? '1' : '';
    const f = (label, value, max, cls) => { const i = mk('input', 'tin ' + cls); i.maxLength = max; i.value = value; i.setAttribute('aria-label', label); i.placeholder = label; return i; };
    r.append(f('Camera id (gate)', cam.id, 24, 'cid'), f('Name you like', cam.label === cam.id ? '' : cam.label, 30, 'clabel'),
      f('Alarm zone (gate)', cam.zones.join(', '), 80, 'czones'), f('Doorstep zone (doorstep)', cam.pkg, 24, 'cpkg'));
    if (!fresh) r.querySelector('.cid').readOnly = true;
    el.rows.appendChild(r);
  }

  // ---- actions -----------------------------------------------------------------------------
  async function arm(mode) {
    if (S.busy || !hasApi()) return;
    S.busy = true;
    try { S.alarm = alarmOf(await api('/v1/home/arm', { method: 'POST', body: { mode } })); say('ok', 'Arming. I will show Armed when your laptop confirms.'); poll(); }
    catch (e) { say('bad', detailOf(e) || 'Couldn\'t arm. Please try again.'); }
    finally { S.busy = false; render(); }
  }
  async function prove() {
    const t = S.alarm && S.alarm.target;
    const P = window.JarvisPasskey;
    if (!t || !P || typeof P.supported !== 'function' || !P.supported()) throw Object.assign(new Error('This browser can\'t use passkeys. Try an up-to-date Chrome, Edge, Safari or Firefox.'), { local: true });
    return P.prove('home_disarm', t);
  }
  async function disarm() {
    if (S.busy || !hasApi() || !(await confirmDisarm(el.off))) return;
    S.busy = true;
    try {
      let r;
      try { r = await api('/v1/home/disarm', { method: 'POST', body: {} }); }
      catch (e) {
        if (!e || (e.code !== 'passkey_required' && e.code !== 'passkey_rejected')) throw e;
        r = await api('/v1/home/disarm', { method: 'POST', body: { proof: await prove() } });
      }
      S.alarm = alarmOf(r); say('ok', 'The alarm is off.');
    } catch (e) {
      if (e && e.code === 'reauth_required') say('bad', 'Sign in with Google again to disarm.', { text: 'Sign in again', href: '/auth/login?reauth=1' });
      else if (e && e.code === 'console_only') say('bad', 'Disarming works only from the JARVIS console in your browser.');
      else say('bad', detailOf(e) || 'Couldn\'t disarm. The alarm is still on.');
    } finally { S.busy = false; await loadAlarm(); render(); }
  }
  function poll() {
    clearInterval(S.poll); S.polls = 0;
    S.poll = setInterval(async () => {
      S.polls += 1;
      await loadAlarm(); render();
      if (S.polls >= POLL_MAX || !S.alarm || !S.alarm.available || !S.alarm.armed || S.alarm.confirmed) clearInterval(S.poll);
    }, POLL_MS);
  }
  async function saveCams() {
    const cameras = {};
    for (const r of el.rows.querySelectorAll('.hcam')) {
      const id = r.querySelector('.cid').value.trim();
      if (!id) continue;
      const zones = r.querySelector('.czones').value.split(',').map((z) => z.trim()).filter(Boolean), pkg = r.querySelector('.cpkg').value.trim();
      if (!ID.test(id) || zones.some((z) => !ID.test(z)) || (pkg && !ID.test(pkg))) { say('bad', 'Ids use lower-case letters, digits and _ only (up to 24), for example gate.'); return; }
      cameras[id] = { label: r.querySelector('.clabel').value, alarm_zones: zones, package_zone: pkg || null };
    }
    try {
      S.cams = camsOf(await api('/v1/home/cameras', { method: 'PUT', body: { cameras, retention_days: Number(el.keep.value) || 7, greetings: el.greet.checked } }));
      say('ok', 'Saved.'); render();
    } catch (e) { say('bad', detailOf(e) || 'Couldn\'t save. Please try again.'); }
  }
  async function search() {
    const to = el.to.value ? new Date(el.to.value) : new Date(), from = el.from.value ? new Date(el.from.value) : new Date(to.getTime() - 24 * 3600 * 1000);
    if (Number.isNaN(to.getTime()) || Number.isNaN(from.getTime())) { say('bad', 'Pick a start and an end time.'); return; }
    const q = new URLSearchParams({ what: el.what.value, from: from.toISOString(), to: to.toISOString() });
    if (el.hcam.value) q.set('camera', el.hcam.value);
    if (el.who.value) q.set('who', el.who.value);
    el.hres.textContent = ''; el.hmore.textContent = 'Searching\u2026';
    try {
      const r = obj(await api('/v1/home/history?' + q.toString())) || {};
      const items = rowsOf(r);
      items.forEach((it) => {
        const li = mk('li', 'hrow'), who = it.who === null || it.who === undefined ? '' : ' \u00b7 ' + txt(it.who, 80);
        li.append(mk('span', 'btime', txt(it.at, 40)), mk('span', 'htxt', txt(it.what, 60) + ' at ' + txt(it.camera, 40) + (it.zone ? ' (' + txt(it.zone, 40) + ')' : '') + who + (Number.isInteger(it.seconds) ? ' \u00b7 ' + it.seconds + ' s' : '')));
        el.hres.appendChild(li);
      });
      el.hmore.textContent = txt(r.note, 200) || (items.length ? items.length + (r.more === true ? ' shown, more exist - narrow the time.' : ' found.') : 'Nothing found. Only the last ' + (Number.isInteger(r.kept_days) ? r.kept_days : 7) + ' days are kept.');
    } catch (e) { el.hmore.textContent = ''; say('bad', detailOf(e) || 'Couldn\'t search. Please try again.'); }
  }
  async function loadAlarm() { try { S.alarm = alarmOf(await api('/v1/home/alarm')) || { available: false, reason: 'Not available on this server.' }; } catch (e) { if (e && e.status === 401) return; say('bad', detailOf(e) || 'Couldn\'t read the alarm. Please try again.'); } }
  async function loadFeed() {
    try { S.feed = rowsOf(await api('/v1/home/feed?day=' + S.day)); } catch (e) { if (e && e.status === 401) return; S.feed = []; say('bad', detailOf(e) || 'Couldn\'t load the feed.'); }
    renderFeed(); el.tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.day === S.day)));
  }
  async function load(force) {
    if (!hasApi()) return;
    if (!force && S.alarm !== undefined && Date.now() - S.loadedAt < STALE_MS) return;
    await loadAlarm();
    try { S.cams = camsOf(await api('/v1/home/cameras')); } catch (e) { if (e && e.status === 401) return; S.cams = { available: false, cams: [], retention: 7, greetings: false, note: '' }; }
    await loadFeed();
    S.loadedAt = Date.now(); render();
    if (S.alarm && S.alarm.armed && !S.alarm.confirmed) poll();
  }

  build(); render();
  const shown = () => { if (Deck.isOpen('home')) load(false); };
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'home' && d.open) load(false); });
  document.addEventListener('jarvis:reply', () => { if (Deck.isOpen('home') && S.alarm !== undefined) load(true); else S.loadedAt = 0; });
  document.addEventListener('jarvis:ready', shown);
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready()) shown();
  window.JarvisHomePanel = Object.freeze({ refresh: () => load(true), alarmOf, camsOf });
})();
