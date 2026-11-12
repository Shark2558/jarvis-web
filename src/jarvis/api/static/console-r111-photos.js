// src/jarvis/api/static/console-r111-photos.js -- R11.1 Part C (docs/plans/r11-1-observations.md D14, D15, D21-C).
// Two pieces, both inside panels that already exist (their modules made the mount points):
//   Connectors -> the Google Photos card (#photosImport): a running import's progress line, as the server
//     words it ("312 of 2,000 read - 41 faces found - paused: laptop not reachable"), Continue now and Stop.
//     While the Connectors panel is open the import is stepped from here; otherwise the helpers' clock takes
//     a step every 5 minutes. Nothing is named here.
//   Faces (#facesGroups): "Unnamed groups", the groups of faces the home laptop found, each as a number and a
//     photo count. JARVIS never sees a face: to see WHO a group is the owner opens the laptop's own page.
//     Name asks through the Faces panel's own dialog and consent form (JarvisFaces.nameForm: a new person
//     needs the consent statement; someone already added needs nothing more). Forget is DONE only when the
//     laptop said so; until then the page says it is waiting.
// Loaded by console-r111.js (an ES module). Built with window.JarvisFixes (mk, api, part) and the console's
// existing classes; server strings reach the page through textContent only; ASCII source.
// Nothing asks the server anything before sign-in (review C-code H1): every load waits for
// JarvisConsole.ready(), including a panel the deck restored as open from the last visit; jarvis:ready
// starts it once the owner is in.
// API (src/jarvis/api/fix_photos.py): GET /v1/facegroups/groups -> {available, reason?, laptop, heard_at,
// groups:[{id, n, photos, first, last}], strays, named, engine_ready, folder, read, keep_days, names_waiting,
// forgets_waiting, local_url, skipped, store_ok, names_lost, min_photos}; POST .../groups/{id}/name {person_id} | {name, relation, child, vip, given_by,
// consent_version, confirm} -> {person_id, at_home, contact_matched}; POST .../groups/{id}/forget -> {done,
// forgotten, left}; GET /v1/facegroups/import, POST .../import/step, DELETE .../import -> {status, photos,
// total, faces_found, unknown, skipped, over, line, recognised:[{name, child}]}.
const F = window.JarvisFixes;
const BASE = '/v1/facegroups';
const GROUP = /^c_[0-9a-f]{8,16}$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const STEP_MS = 5000, PAUSED_MS = 30000, STALE_MS = 60000, MAX_ROWS = 100;
const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
const LOCAL = 'http://localhost:8098/faces';
const CHILD = 'a child from your family';
const PAUSED = ['laptop_offline', 'kit_old', 'reader_off', 'edge_error', 'timed_out'];
const HINTS = {
  reading: 'It carries on by itself: step by step while this panel is open, and a few photos every 5 minutes in the background.',
  waiting: 'Choose your photos in Google\'s picker, then press Import chosen photos.',
  laptop_offline: 'Your home laptop is off or asleep. The import carries on by itself when it is back.',
  kit_old: 'Your home kit is older than this. Update it on the laptop (the kit\'s README: Updating the kit).',
  reader_off: 'The face reader on your laptop is not ready. Run the kit\'s update step on the laptop.',
  edge_error: 'Your home laptop answered in a way JARVIS could not use. It is tried again.',
  timed_out: 'The last step took too long. It is tried again.',
  expired: 'Google\'s picker session ended. Press Choose photos and pick again to continue; what was read is kept.',
};
const FOLDER = {
  off: 'Watched photo folder: off. To have a folder of photos read on the laptop, set PHOTOS_DIR there (the kit\'s README says how).',
  unreadable: 'Watched photo folder: the laptop can\'t read it. Check the folder still exists, then run the kit\'s photo-folder step again.',
};

const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const count = (v) => (Number.isInteger(v) && v >= 0 ? v : 0);
const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
const many = (n, one, more) => n.toLocaleString('en-IN') + ' ' + (n === 1 ? one : more);
const two = (n) => String(n).padStart(2, '0');
const day = (d) => d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
const seenOn = (secs) => { const d = new Date(secs * 1000); return secs > 0 && !Number.isNaN(d.getTime()) ? day(d) : ''; };
const heardAt = (iso) => { const d = new Date(iso); return iso && !Number.isNaN(d.getTime()) ? day(d) + ', ' + two(d.getHours()) + ':' + two(d.getMinutes()) : ''; };
const isOpen = (panel) => { const D = window.JarvisDeck; return !!(D && typeof D.isOpen === 'function' && D.isOpen(panel)); };
const signedIn = () => { const C = window.JarvisConsole; return !!(C && typeof C.ready === 'function' && C.ready()); };
function detailOf(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
  return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
}

// ---- what the server sent, made safe ---------------------------------------------------------------
function groupsOf(raw) {
  const d = obj(raw);
  if (!d) return null;
  if (d.available !== true) return { available: false, reason: txt(d.reason, 200) || 'Not available on this server.', groups: [] };
  const seen = new Set();
  const groups = arr(d.groups).slice(0, MAX_ROWS).map((g) => {
    const it = obj(g);
    if (!it || typeof it.id !== 'string' || !GROUP.test(it.id) || seen.has(it.id)) return null;
    seen.add(it.id);
    return { id: it.id, n: count(it.n), photos: count(it.photos), first: count(it.first), last: count(it.last) };
  }).filter(Boolean);
  return { available: true, groups, laptop: d.laptop === 'online' ? 'online' : 'offline', heard: txt(d.heard_at, 40),
    strays: count(d.strays), engine: d.engine_ready === true, folder: ['on', 'unreadable'].includes(d.folder) ? d.folder : 'off',
    read: count(d.read), keep: count(d.keep_days) || 90, names: count(d.names_waiting), forgets: count(d.forgets_waiting),
    local: txt(d.local_url, 60) || LOCAL, skipped: count(d.skipped), store: d.store_ok !== false, lost: count(d.names_lost),
    least: count(d.min_photos) || 3 };
}
function importOf(raw) {
  const r = obj(raw) || {};
  return { status: txt(r.status, 20) || 'no_session', photos: count(r.photos), total: count(r.total), faces: count(r.faces_found),
    unknown: Number.isInteger(r.unknown) ? count(r.unknown) : count(r.unknown_faces), over: count(r.over), line: txt(r.line, 200),
    recognised: arr(r.recognised).slice(0, 20).map((p) => (obj(p) && p.child === true ? CHILD : txt(obj(p) && p.name, 40))).filter(Boolean) };
}

if (F) {
  const { mk, api } = F;
  const button = (cls, text, fn) => { const b = mk('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); return b; };

  // ---- Faces: Unnamed groups -----------------------------------------------------------------------
  const G = { data: undefined, loadedAt: 0, busy: false, el: null };
  function sayGroups(kind, text) { G.el.note.className = 'bnote fnote' + (kind === 'bad' ? ' bad' : ''); G.el.note.textContent = text || ''; }
  function buildGroups(host) {
    const head = mk('div', 'rhead'), title = mk('h3', 'k', 'Unnamed groups'), tally = mk('span', 'k');
    title.id = 'fgTitle'; tally.id = 'fgTally'; head.append(title, tally);
    const intro = mk('p', 'bfine'); intro.id = 'fgIntro';
    const note = mk('div', 'bnote fnote'); note.id = 'fgNote'; note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
    const state = mk('div', 'empty'); state.id = 'fgState'; state.setAttribute('role', 'status');
    const list = mk('ul', 'tlist'); list.id = 'fgList'; list.setAttribute('aria-labelledby', 'fgTitle');
    const waits = mk('p', 'bfine'); waits.id = 'fgWaits';
    const folder = mk('p', 'bfine'); folder.id = 'fgFolder';
    host.setAttribute('aria-labelledby', 'fgTitle');
    host.append(head, intro, note, state, list, waits, folder);
    G.el = { tally, intro, note, state, list, waits, folder };
  }
  function groupRow(g) {
    const li = mk('li', 'trow'), main = mk('div', 'ttxt'), acts = mk('div', 'tacts');
    li.dataset.group = g.id;
    main.append(mk('b', 'tname', 'Group ' + g.n), mk('span', 'tplace', many(g.photos, 'photo', 'photos')));
    const seen = [seenOn(g.first) && 'First seen ' + seenOn(g.first), seenOn(g.last) && 'last seen ' + seenOn(g.last)].filter(Boolean).join(' \u00b7 ');
    if (seen) main.appendChild(mk('small', 'tmeta', seen));
    const name = button('btn bact', 'Name', () => nameGroup(g, name)); name.setAttribute('aria-label', 'Name group ' + g.n);
    const forget = button('btn bact', 'Forget', () => forgetGroup(g, forget)); forget.setAttribute('aria-label', 'Forget group ' + g.n);
    acts.append(name, forget); li.append(main, acts);
    return li;
  }
  function renderGroups() {
    const d = G.data, el = G.el;
    if (!el) return;
    [el.list, el.waits, el.folder, el.tally, el.intro].forEach((n) => { n.textContent = ''; });
    if (d === undefined) { el.state.textContent = 'Groups load when this panel opens.'; return; }
    if (!d.available) { el.state.textContent = d.reason; return; }
    el.intro.append('Faces your home laptop found in your photos, one group for each person. JARVIS can\'t see them: to see who a group is, open ',
      mk('code', 'fcode', d.local), ' on your home laptop. A group you don\'t name is forgotten after ' + many(d.keep, 'day', 'days') + '.');
    el.tally.textContent = d.groups.length ? d.groups.length + ' to name' : '';
    let state = '';
    if (d.laptop !== 'online') state = 'Your home laptop isn\'t reachable' + (heardAt(d.heard) ? ': this is what it last said (' + heardAt(d.heard) + ').' : '.');
    else if (!d.store) state = 'The face store on your laptop can\'t be opened right now (its disk may be full). Nothing was deleted; restart the home kit if it stays like this.';
    else if (!d.engine) state = 'The face reader on your laptop is off. Update the home kit on the laptop to switch it on.';
    else if (!d.groups.length) state = 'No groups to name.' + (d.strays ? ' ' + many(d.strays, 'face is', 'faces are') + ' in fewer than ' + many(d.least, 'photo', 'photos') + ' so far.' : '');
    el.state.textContent = state;
    d.groups.forEach((g) => el.list.appendChild(groupRow(g)));
    const waits = [];
    if (d.names) waits.push(many(d.names, 'name waits', 'names wait') + ' for your laptop to be back');
    if (d.forgets) waits.push(many(d.forgets, 'thing to forget waits', 'things to forget wait') + ' for your laptop: not done until it confirms');
    if (d.lost) waits.push(many(d.lost, 'name', 'names') + ' could not be given: the group had gone from your laptop. The person is kept in Faces; name another group as them');
    el.waits.textContent = waits.length ? waits.join('. ') + '.' : '';
    if (d.laptop === 'online') {
      el.folder.textContent = d.folder === 'on' ? 'Watched photo folder: on, ' + many(d.read, 'picture', 'pictures') + ' read so far.'
        + (d.skipped ? ' ' + many(d.skipped, 'file', 'files') + ' could not be read and ' + (d.skipped === 1 ? 'was' : 'were') + ' skipped.' : '') : FOLDER[d.folder];
    }
  }
  async function loadGroups(force) {
    if (!G.el || !signedIn() || (!force && G.data !== undefined && Date.now() - G.loadedAt < STALE_MS)) return;
    try {
      G.data = groupsOf(await api(BASE + '/groups')) || { available: false, reason: 'Not available on this server.', groups: [] };
      G.loadedAt = Date.now();
    } catch (e) {
      if (e && e.status === 401) return;
      sayGroups('bad', detailOf(e) || 'Couldn\'t load the groups. Please try again.');
    }
    renderGroups();
  }
  async function nameGroup(g, trigger) {
    const Faces = window.JarvisFaces;
    if (G.busy || !Faces || typeof Faces.nameForm !== 'function') return;
    const body = await Faces.nameForm('Who is group ' + g.n + '?', 'Name', trigger);
    if (!body) return;
    G.busy = true;
    try {
      const r = obj(await api(BASE + '/groups/' + g.id + '/name', { method: 'POST', body })) || {};
      sayGroups('ok', r.at_home === false ? 'Saved. Your laptop is off or asleep: it is told the name as soon as it is back.'
        : 'Named. New photos and the camera now recognise this person, with nothing more to do.');
      if (typeof Faces.refresh === 'function') Faces.refresh();
      await loadGroups(true);
    } catch (e) { sayGroups('bad', detailOf(e) || 'Couldn\'t name that group. Please try again.'); }
    finally { G.busy = false; }
  }
  async function forgetGroup(g, trigger) {
    const Faces = window.JarvisFaces;
    if (G.busy || !Faces || typeof Faces.confirm !== 'function') return;
    const text = 'Group ' + g.n + ' (' + many(g.photos, 'photo', 'photos') + ') is forgotten on your home laptop: its face crops and face data are deleted there. '
      + 'Your photos themselves are not touched, so a later scan can group them again. This can\'t be undone.';
    if (!(await Faces.confirm('Forget group ' + g.n + '?', 'Forget', text, trigger))) return;
    G.busy = true;
    try {
      const r = obj(await api(BASE + '/groups/' + g.id + '/forget', { method: 'POST', body: {} })) || {};
      sayGroups('ok', r.done === true ? 'Forgotten: your laptop confirmed it.'
        : 'Not done yet: your laptop is off or asleep. The group is forgotten there as soon as it is back.');
      await loadGroups(true);
    } catch (e) { sayGroups('bad', detailOf(e) || 'Couldn\'t forget that group. Please try again.'); }
    finally { G.busy = false; }
  }

  // ---- Connectors: the import's progress line ------------------------------------------------------
  const J = { data: null, el: null, busy: false, timer: 0, auto: true, asking: false, problem: '' };
  function buildJob(host) {
    const line = mk('p', 'bfine cout'); line.id = 'photosLine';
    const hint = mk('p', 'bfine'); hint.id = 'photosHint'; hint.setAttribute('role', 'status');
    const acts = mk('div', 'actions'), confirm = mk('div', 'confirm');
    const go = button('btn lift', 'Continue now', () => stepJob(true));
    const stop = button('btn lift', 'Stop import', () => { J.asking = true; renderJob(); keep.focus(); });
    const faces = button('btn lift', 'Open Faces', () => { const D = window.JarvisDeck; if (D && typeof D.open === 'function') D.open('faces', { focus: true }); });
    const keep = button('btn lift', 'Keep importing', () => { J.asking = false; renderJob(); stop.focus(); });
    const yes = button('btn danger lift', 'Stop', stopJob);
    confirm.setAttribute('role', 'group'); confirm.setAttribute('aria-label', 'Confirm stopping the import');
    confirm.append(mk('span', '', 'Stop the import? What was read is kept; to read the rest you pick again.'), keep, yes);
    acts.append(go, stop, faces);
    host.append(line, hint, acts, confirm);
    J.el = { host, line, hint, acts, confirm, go, stop, faces, keep, yes };
  }
  function hintOf(d) {
    const parts = [J.problem || HINTS[d.status] || ''];
    if (d.recognised.length) parts.push('Recognised: ' + d.recognised.join(', ') + '.');
    if (d.over) parts.push(many(d.over, 'picked photo was', 'picked photos were') + ' over your limit and not imported.');
    if (d.unknown && (d.status === 'done' || d.status === 'reading')) {
      parts.push(many(d.unknown, 'face', 'faces') + ' JARVIS doesn\'t know. A face that is in ' + many(G.data && G.data.least ? G.data.least : 3, 'photo', 'photos')
        + ' or more appears in Faces, under Unnamed groups, where you can name it.');
    }
    return parts.filter(Boolean).join(' ');
  }
  function renderJob() {
    const d = J.data, el = J.el;
    if (!el) return;
    const on = !!d && d.status !== 'no_session';
    el.host.hidden = !on;
    if (!on) return;
    const running = d.status === 'reading' || PAUSED.includes(d.status);
    el.line.textContent = d.line || (d.status === 'waiting' ? 'Waiting for you to choose photos.' : '');
    el.hint.textContent = hintOf(d);
    el.go.hidden = !running;
    el.stop.hidden = !(running || d.status === 'waiting' || d.status === 'expired');
    el.faces.hidden = !d.unknown;
    el.acts.hidden = J.asking || (el.go.hidden && el.stop.hidden && el.faces.hidden);
    el.confirm.hidden = !J.asking;
    el.go.disabled = el.stop.disabled = el.yes.disabled = J.busy;
  }
  function schedule() {
    clearTimeout(J.timer); J.timer = 0;
    if (!J.data || !J.auto || J.asking || document.hidden || !isOpen('connectors') || !signedIn()) return;
    if (J.data.status === 'reading') J.timer = setTimeout(() => stepJob(false), STEP_MS);
    else if (PAUSED.includes(J.data.status)) J.timer = setTimeout(readJob, PAUSED_MS);   // the clock retries; show it
  }
  function showImport(raw) { J.data = importOf(raw); J.auto = true; J.asking = false; J.problem = ''; renderJob(); schedule(); }
  async function call(path, opts, byHand, fail) {
    if (J.busy || !J.el || !signedIn()) return;
    J.busy = true; J.problem = ''; renderJob();
    try { J.data = importOf(await api(BASE + path, opts)); J.auto = true; } catch (e) {
      J.auto = false;   // never loop on an error: the owner presses Continue, or the clock carries on
      if (e && e.status === 401) return;
      J.problem = byHand ? detailOf(e) || fail : (J.data ? 'Stepping from this panel paused after a problem. The import still carries on in the background; press Continue now to go on here.' : '');
    } finally { J.busy = false; renderJob(); schedule(); }
  }
  const readJob = () => call('/import', undefined, false, '');
  const stepJob = (byHand) => call('/import/step', { method: 'POST', body: {} }, byHand, 'Couldn\'t continue. Please try again.');
  const stopJob = () => { J.asking = false; return call('/import', { method: 'DELETE' }, true, 'Couldn\'t stop the import. Please try again.'); };

  // ---- wiring ----------------------------------------------------------------------------------------
  function start() {
    const groups = document.getElementById('facesGroups'), job = document.getElementById('photosImport');
    if (groups && !G.el) buildGroups(groups);
    if (job && !J.el) buildJob(job);
    renderGroups(); renderJob();
    if (!signedIn()) return;   // the deck may have restored these panels as open: wait for jarvis:ready
    if (isOpen('faces')) loadGroups(false);
    if (isOpen('connectors')) readJob();
  }
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (!signedIn()) return;
    if (d.id === 'faces' && d.open) loadGroups(false);
    if (d.id === 'connectors') { if (d.open) readJob(); else schedule(); }
  });
  document.addEventListener('jarvis:ready', start);
  document.addEventListener('visibilitychange', schedule);
  start();
  F.part('photos', { groupsOf, importOf, showImport, refresh: () => loadGroups(true) });
}
