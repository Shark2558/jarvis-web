// src/jarvis/api/static/console-camera-setup.js -- R8 builder B (docs/plans/r8-vision.md v8.0.4 4.5, 4.6; rows 217, 184,
// 377; the approved mockup docs/plans/r8-mockups/camera-setup.html). Camera -> Cameras, a pixel pane (it runs the setup
// test: tests/test_r13_seams.py PANELS) mounted through the Camera panel's mode hook below the panel's own "This device"
// and "Home camera" sections:
//   Cameras and spots  each camera (this device, his other devices, the home cameras) with its spot and room, its health
//                      (a dot AND words: seen when, how fast) and Switch off / Allow; Add this camera (name, spot, room);
//                      the home kit's cameras not set up yet; Run the setup test (console-vision-check.js, A); Forget
//   Rooms              each room's switch (a room switched off stops every camera in it), "Never use cameras here" (no
//                      look and no coach there, row 184), Add a room, All cameras off (the same as "Jarvis, cameras off")
//   Check a camera     before you buy: what to look for; after: the home laptop's no-cloud check (POST /v1/camera/check)
//                      in two stages, the second after he blocks its internet and restarts it; Add as a home camera
// Every change is PUT /v1/camera/spots with the rev it was read at (another device's change wins and is shown), then
// handed to the camera's door (JarvisCamera.recheck) so THIS device stops at once; other devices read it within a minute.
// Only a tap switches a camera back on; no voice does. The burglar alarm is never changed here. Nothing is recorded: no
// picture leaves the device (the setup test looks on the device and sends three numbers). textContent only; ASCII.
const CHECK = () => import('./console-vision-check.js');
const STYLE = '/static/console-camera-setup.css';
const M = window.JarvisMobile;
const Cam = () => window.JarvisCamera || null;
const SPOTS = '/v1/camera/spots';
const LABEL_ID = /^[a-z0-9_]{1,24}$/;
const POLL_MS = 4000;
const TEST_SECONDS = 20;
const DAY_S = 24 * 3600;
const SPOT_WORDS = [['desk', 'Desk'], ['workout', 'Workout spot'], ['table', 'Table'], ['room', 'The whole room'], ['none', 'No spot']];
const PROMISE = 'Nothing is recorded: no video and no photos. Only counts, times and scores are kept, sealed.';
const VOICE = 'Or say \u201cJarvis, cameras off\u201d. Every camera stops; only a tap starts one again. The burglar alarm is not changed.';
const ROOM_FINE = 'A room switched off stops every camera in it. Only a tap switches it back on.';
const STALE = 'The cameras were changed on another device. This is how they are now.';
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const DIDNT = 'That didn\u2019t work. Please try again.';
const NOT_BUILT = 'Camera setup isn\u2019t switched on on this server yet.';
const BEFORE_BUY = [
  ['RTSP, with a main and a sub-stream', 'It sends video on your own Wi-Fi, in a big and a small size.'],
  ['ONVIF (Profile S)', 'JARVIS can find it and ask where its video is.'],
  ['H.264 video', 'The kind of video the home laptop reads.'],
  ['Works without an account, or \u201clocal only\u201d', 'It keeps working with its cloud app cut off. Setting it up once in its own app is fine.'],
  ['Mains power', 'A battery camera sleeps and can\u2019t be watched all day.'],
];
const S = { host: null, P: null, box: null, view: null, busy: false, note: '', noteKind: '', open: false, check: null, ip: '',
  blocked: false, poll: 0, testing: false, tested: '', loading: false, form: {} }; // form: what he typed, kept across repaints
const mk = (tag, cls, text) => (M ? M.mk(tag, cls, text) : document.createElement(tag));
const signedIn = () => !!(S.P && S.P.signedIn());
const api = (path, opts) => (M && typeof M.api === 'function' ? M.api(path, opts) : Promise.reject(new Error('offline')));
const myId = () => { const C = Cam(); return C && typeof C.spot === 'function' ? C.spot() : ''; };
const onPhone = () => /Android|iPhone|iPad|Mobile/i.test(String(navigator.userAgent || ''));

function failed(e) {
  if (e && e.status === 404) return NOT_BUILT;
  if (e && e.status === 501) return NOT_BUILT;
  if (e && typeof e.status === 'number') return e.status >= 500 || !e.message ? 'JARVIS couldn\u2019t do that just now. Try again in a moment.' : String(e.message);
  return navigator.onLine === false ? OFFLINE : DIDNT;
}
function button(text, cls, fn, key) {
  const b = S.P.button(text, cls, fn);
  if (key) b.setAttribute('data-k', key);
  return b;
}
function chip(status, word) {
  const c = mk('span', 'vt-chip', word);
  if (status) c.setAttribute('data-status', status);
  return c;
}
function slug(text, taken) {
  const base = String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 20) || 'camera';
  let id = base, n = 2;
  while (taken.has(id)) { id = base.slice(0, 20) + '_' + n; n += 1; }
  return id;
}
const clean = (t) => String(t || '').replace(/[<>\u0000-\u001f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 40);

// ---- reading and changing the set ------------------------------------------------------------------------------------
async function load() {
  if (!S.box || !signedIn() || S.loading) return;
  S.loading = true;
  try { S.view = await api(SPOTS); S.note = ''; }
  catch (e) { S.view = null; S.note = failed(e); S.noteKind = 'bad'; }
  finally { S.loading = false; }
  render();
}
function plain(v) {
  return { rev: v.rev, all_off: !!v.all_off, cameras: (v.cameras || []).map((c) => Object.assign({}, c)),
    rooms: (v.rooms || []).map((r) => Object.assign({}, r)) };
}
/** PUT the set fn(current) returns; this device's door hears the answer at once. */
async function change(fn, done) {
  if (S.busy || !S.view) return;
  S.busy = true;
  try {
    const v = await api(SPOTS, { method: 'PUT', body: fn(plain(S.view)) });
    S.view = Object.assign({}, S.view, v);
    S.note = '';
    const C = Cam();
    if (C && typeof C.recheck === 'function') C.recheck(v);
    if (typeof done === 'function') done(v);
  } catch (e) {
    if (e && e.status === 409) { S.busy = false; await load(); S.note = STALE; S.noteKind = ''; render(); return; }
    S.note = failed(e); S.noteKind = 'bad';
  } finally { S.busy = false; }
  render();
}
const setCamera = (id, over) => change((s) => Object.assign(s, { cameras: s.cameras.map((c) => (c.id === id ? Object.assign(c, over) : c)) }));
const setRoom = (id, over) => change((s) => Object.assign(s, { rooms: s.rooms.map((r) => (r.id === id ? Object.assign(r, over) : r)) }));
function forget(id) {
  change((s) => Object.assign(s, { cameras: s.cameras.filter((c) => c.id !== id) }), () => { const C = Cam(); if (id === myId() && C) C.useSpot(''); });
}
function allowAll() { // a tap: the server's "every camera off" ends, and this device's own lock with it
  const C = Cam();
  if (C && C.locked()) C.unlock('panel');
  change((s) => Object.assign(s, { all_off: false }));
}
async function allOff() {
  const C = Cam();
  if (!C || typeof C.allOff !== 'function') return;
  const r = await C.allOff('button');
  S.note = r.server ? 'Every camera is off.' + (r.armed ? ' The burglar alarm is still armed; Disarm is in Home.' : '') : 'This device\u2019s camera is off. The others couldn\u2019t be reached.';
  S.noteKind = r.server ? 'ok' : 'bad';
  await load();
}
function roomFor(s, typed) { // a room he typed: one he has (by its name), else a new one
  const label = clean(typed);
  if (!label) return { id: null, rooms: s.rooms };
  const have = s.rooms.find((r) => r.label.toLowerCase() === label.toLowerCase());
  if (have) return { id: have.id, rooms: s.rooms };
  const id = slug(label, new Set(s.rooms.map((r) => r.id)));
  return { id, rooms: s.rooms.concat([{ id, label, on: true, never: false }]) };
}
function addCamera(fields, kind) {
  let made = '';
  change((s) => {
    const room = roomFor(s, fields.room);
    made = fields.id && LABEL_ID.test(fields.id) ? fields.id : slug(fields.label, new Set(s.cameras.map((c) => c.id)));
    const source = kind === 'home' ? 'home' : onPhone() ? 'phone' : 'browser';
    const cam = { id: made, kind, source, label: clean(fields.label) || 'Camera', spot: fields.spot || 'none', room: room.id, on: true };
    return Object.assign(s, { rooms: room.rooms, cameras: s.cameras.filter((c) => c.id !== made).concat([cam]) });
  }, () => { const C = Cam(); if (kind === 'device' && C && made) C.useSpot(made); });
}

// ---- the setup test: a tap-started look on THIS device; three numbers go to the server ------------------------------
async function setupTest() {
  const C = Cam(), id = myId();
  if (!C || !id || S.testing) return;
  S.testing = true; S.tested = 'The setup test is running: sit as you normally do. Nothing is recorded.';
  render();
  try {
    await C.start({});
    const V = window.JarvisVision, pose = V && V.tasks ? V.tasks().find((t) => t.id === 'pose') : null;
    const r = await (await CHECK()).run([pose && !pose.why ? 'pose' : 'quality'], { seconds: TEST_SECONDS });
    const fps = Math.round(Number(r.fps) * 10) / 10, ms = Math.round(Number(r.ms)), core = Math.round(Number(r.core) * 100);
    S.tested = 'Done: ' + fps + ' frames a second, ' + ms + ' ms a look, ' + core + ' % of one core.';
    await api('/v1/camera/health', { method: 'POST', body: { camera: id, fps: Math.min(120, fps), ms: Math.min(60000, ms) } }).catch(() => {});
  } catch (e) {
    const m = String((e && e.message) || '');
    S.tested = /not built/.test(m) ? 'The setup test isn\u2019t ready on this server yet.' : e && e.code ? m : failed(e);
  } finally {
    try { C.stop('panel'); } catch (_) {}
    S.testing = false;
  }
  await load();
}

// ---- the no-cloud check (row 377) --------------------------------------------------------------------------------------
async function runCheck(stage) {
  const ip = String(S.ip || '').trim();
  if (!ip) return;
  clearTimeout(S.poll);
  S.check = { ip, stage, state: 'running', verdict: '', checks: [], missing: '', rounds: 0, rounds_done: 0 };
  render();
  try { S.check = await api('/v1/camera/check', { method: 'POST', body: { action: 'start', ip, stage } }); }
  catch (e) { S.check = { ip, stage, state: 'done', verdict: 'fail', checks: [], missing: failed(e) }; }
  render();
  if (S.check && S.check.state === 'running') S.poll = setTimeout(pollCheck, POLL_MS);
}
async function pollCheck() {
  const c = S.check;
  if (!c || c.state !== 'running' || !S.box) return;
  try { S.check = await api('/v1/camera/check', { method: 'POST', body: { action: 'status', ip: c.ip, stage: c.stage } }); }
  catch (e) { S.check = Object.assign({}, c, { state: 'done', verdict: 'fail', missing: failed(e) }); }
  render();
  if (S.check && S.check.state === 'running') S.poll = setTimeout(pollCheck, POLL_MS);
}

// ---- drawing ---------------------------------------------------------------------------------------------------------
function ago(sec) {
  const m = Math.floor(sec / 60);
  return m < 1 ? 'now' : m < 120 ? m + ' min ago' : Math.floor(m / 60) < 48 ? Math.floor(m / 60) + ' hours ago' : Math.floor(m / 1440) + ' days ago';
}
function health(c) { // [dot, words, chip status, chip word, row status]
  const v = S.view, on = !!(v.allowed && v.allowed[c.id]), h = (v.health && v.health[c.id]) || {};
  if (!on) return ['', c.on ? 'Off: its room or every camera is switched off' : 'Off', '', 'Off', ''];
  if (typeof h.last_seen !== 'number') return ['', c.kind === 'home' ? 'Not seen by the home kit yet' : 'Not seen yet: run its setup test', '', 'Ready', ''];
  const sec = Math.max(0, (Number(v.now) || Date.now() / 1000) - h.last_seen);
  const rate = typeof h.fps === 'number' ? ' \u00b7 ' + h.fps + (h.fps === 1 ? ' frame' : ' frames') + ' a second' : '';
  if (sec >= DAY_S) return ['warn', 'Last seen ' + ago(sec), 'amber', 'Not seen', 'amber'];
  return ['ok', 'Seen ' + ago(sec) + rate, 'ok', 'On', ''];
}
function where(c, mine) {
  const room = (S.view.rooms || []).find((r) => r.id === c.room);
  const spot = (SPOT_WORDS.find(([k]) => k === c.spot) || ['', ''])[1];
  const kind = mine ? 'This device' : c.kind === 'home' ? 'Through the home kit' : c.source === 'phone' ? 'A phone' : 'A computer\u2019s camera';
  return [kind, spot && c.spot !== 'none' ? spot + (room ? ', in the ' + room.label.toLowerCase() : '') : room ? 'In the ' + room.label.toLowerCase() : ''].filter(Boolean).join(' \u00b7 ');
}
function cameraRow(c) {
  const mine = c.id === myId(), [dot, words, chipSt, chipWord, status] = health(c);
  const row = mk('div', 'hp-row r8-cam');
  if (status) row.setAttribute('data-status', status);
  const txt = mk('div', 'hp-txt'), name = mk('b', '', c.label);
  name.append(chip(chipSt, chipWord));
  const line = mk('span', 'r8-health'), d = mk('i', 'dot' + (dot ? ' ' + dot : ''));
  d.setAttribute('aria-hidden', 'true');
  line.append(d, mk('span', '', words));
  txt.append(name, mk('span', 'r8-sub', where(c, mine)), line);
  const acts = mk('div', 'hp-acts');
  acts.append(c.on ? button('Switch off', '', () => setCamera(c.id, { on: false }), 'off-' + c.id) : button('Allow', '', () => setCamera(c.id, { on: true }), 'on-' + c.id));
  row.append(txt, acts);
  const why = S.view.why && S.view.why[c.id];
  const wide = mk('div', 'r8-wide');
  if (c.on && why) wide.append(mk('p', 'vt-why', why));
  const more = mk('div', 'sacts');
  if (mine && c.on && !S.view.all_off) more.append(button(S.testing ? 'Testing\u2026' : 'Run the setup test', '', setupTest, 'test'));
  more.append(button('Forget', '', () => forget(c.id), 'forget-' + c.id));
  if (mine && S.tested) wide.append(mk('p', 'sfine', S.tested));
  if (c.kind === 'home') wide.append(mk('p', 'sfine', 'Home kit id: ' + c.id));
  wide.append(more);
  row.append(wide);
  return row;
}
function kept(i, key, value) { // a field keeps what he typed when the pane is drawn again
  i.setAttribute('data-k', 'f-' + key);
  i.value = Object.prototype.hasOwnProperty.call(S.form, key) ? S.form[key] : value || '';
  const save = () => { S.form[key] = i.value; };
  i.addEventListener('input', save);
  i.addEventListener('change', save);
  return i;
}
function input(label, key, value, attrs) {
  const i = mk('input', 'minput');
  i.type = 'text';
  Object.entries(attrs || {}).forEach(([k, v]) => i.setAttribute(k, v));
  return [S.P.field(label, kept(i, key, value)), i];
}
function select(label, key, pairs, value) {
  const s = mk('select', 'minput');
  pairs.forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; s.append(o); });
  return [S.P.field(label, kept(s, key, value)), s];
}
function addThisForm() {
  const li = mk('div', 'r8-form');
  const [nameF, name] = input('Name this camera', 'name', onPhone() ? 'Workout phone' : 'Desk camera', { maxlength: '40', autocomplete: 'off' });
  const [spotF, spot] = select('Spot', 'spot', SPOT_WORDS, onPhone() ? 'workout' : 'desk');
  const [roomF, room] = input('Room (optional)', 'room', '', { maxlength: '40', placeholder: 'Study', autocomplete: 'off' });
  const grid = mk('div', 'r8-grid2');
  grid.append(spotF, roomF);
  li.append(mk('p', 'snote', 'This device\u2019s camera isn\u2019t set up yet. Give it a name, the spot it watches and its room.'), nameF, grid);
  const acts = mk('div', 'sacts');
  acts.append(button('Add this camera', 'primary', () => { addCamera({ label: name.value, spot: spot.value, room: room.value }, 'device'); S.form = {}; }, 'add-this'));
  li.append(acts);
  return li;
}
function homeOffer(h) {
  const row = mk('div', 'hp-row r8-cam'), txt = mk('div', 'hp-txt');
  txt.append(mk('b', '', clean(h.label) || h.id), mk('span', 'r8-sub', 'A camera in the home kit, not set up here yet'));
  const acts = mk('div', 'hp-acts');
  acts.append(button('Add', '', () => addCamera({ id: h.id, label: h.label, spot: 'desk', room: '' }, 'home'), 'home-' + h.id));
  row.append(txt, acts);
  return row;
}
function camerasSection() {
  const sec = mk('section', 'hp-sec r8-add'), v = S.view, mine = myId();
  sec.append(mk('h3', 'hp-h', 'Cameras and spots'));
  (v.cameras || []).forEach((c) => sec.append(cameraRow(c)));
  (v.home || []).forEach((h) => sec.append(homeOffer(h)));
  if (!mine || !(v.cameras || []).some((c) => c.id === mine)) sec.append(addThisForm());
  return sec;
}
function roomSwitch(r) {
  const on = !!r.on && !r.never, b = mk('button', 'bsw');
  b.type = 'button';
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  b.setAttribute('aria-label', r.label + ' cameras');
  b.setAttribute('data-k', 'room-' + r.id);
  const track = mk('span', 'track');
  track.setAttribute('aria-hidden', 'true');
  track.append(mk('i', ''));
  b.append(track, mk('span', 'st', on ? 'On' : 'Off'));
  b.disabled = !!r.never;
  b.addEventListener('click', () => setRoom(r.id, { on: !r.on }));
  return b;
}
function roomRow(r) {
  const row = mk('div', 'bopt'), txt = mk('div', 'btxt');
  const cams = (S.view.cameras || []).filter((c) => c.room === r.id).map((c) => c.label);
  txt.append(mk('span', 'bl', r.label), mk('small', '', cams.length ? cams.join(', ') : 'No camera here'));
  const never = mk('label', 'r8-never'), box = mk('input', '');
  box.type = 'checkbox'; box.checked = !!r.never;
  box.addEventListener('change', () => setRoom(r.id, { never: box.checked }));
  never.append(mk('span', '', 'Never use cameras here'), box); // the words before the box (the visual gate's label rule)
  txt.append(never);
  row.append(txt, roomSwitch(r));
  return row;
}
function roomsSection() {
  const sec = mk('section', 'hp-sec r8-add'), v = S.view;
  sec.append(mk('h3', 'hp-h', 'Rooms'));
  (v.rooms || []).forEach((r) => sec.append(roomRow(r)));
  const [roomF, room] = input('Add a room', 'newroom', '', { maxlength: '40', placeholder: 'Bedroom', autocomplete: 'off' });
  const add = button('Add room', '', () => {
    if (!clean(room.value)) return;
    change((s) => Object.assign(s, { rooms: roomFor(s, room.value).rooms }));
    delete S.form.newroom;
  }, 'add-room');
  const lrow = mk('span', 'lrow');
  lrow.append(roomF, add);
  sec.append(lrow, mk('p', 'sfine', ROOM_FINE));
  const acts = mk('div', 'sacts');
  acts.append(button('All cameras off', '', allOff, 'all-off'));
  sec.append(acts, mk('p', 'sfine', VOICE));
  return sec;
}
const MARKS = { true: ['ok', '\u2713', 'Yes'], false: ['no', '\u2717', 'No'], null: ['wait', '\u2026', 'Later'] };
const CHECK_NAMES = { onvif: 'JARVIS can find and name it (ONVIF)', profiles: 'A main and a sub-stream (Profile S)', rtsp_main: 'Sends video on your Wi-Fi (RTSP, main)',
  rtsp_sub: 'Sends video on your Wi-Fi (RTSP, sub)', h264: 'H.264 video', offline: 'Works with its internet blocked', login: 'Its user name and password' };
function checkItem(cls, mark, title, small, word) {
  const li = mk('li', cls), m = mk('span', 'r8-mark', mark), t = mk('span', '', title);
  m.setAttribute('aria-hidden', 'true');
  if (small) t.append(mk('small', '', small));
  li.append(m, t, mk('em', '', word));
  return li;
}
function resultCard(c) {
  const card = mk('div', 'vt-card r8-card');
  card.setAttribute('role', 'status');
  const head = mk('div', 'rhead');
  const verdict = c.state === 'running' ? ['', 'Checking'] : c.verdict === 'pass' ? ['ok', 'Works'] : c.verdict === 'half' ? ['amber', 'Half way'] : ['red', 'Doesn\u2019t work'];
  head.append(mk('h4', 'k nw', 'Camera at ' + c.ip), chip(verdict[0], verdict[1]));
  const ul = mk('ul', 'r8-checks');
  (c.checks || []).forEach((x) => { const [cls, mark, word] = MARKS[x.ok === true ? 'true' : x.ok === false ? 'false' : 'null']; ul.append(checkItem(cls, mark, CHECK_NAMES[x.id] || x.id, x.ok === true ? '' : x.words, word)); }); // a line that passed says it once
  card.append(head, ul);
  if (c.state === 'running') card.append(mk('p', 'sfine', c.stage === 'offline' ? 'Checking with its internet blocked: round ' + Math.max(1, c.rounds_done) + ' of ' + (c.rounds || 5) + '. About two minutes.' : 'Checking on your Wi-Fi\u2026'));
  else if (c.verdict === 'pass') {
    card.append(mk('p', 'inote', 'Works with JARVIS. No cloud service needed.'));
    const acts = mk('div', 'sacts');
    acts.append(button('Add as a home camera', 'primary', () => addCamera({ label: 'Home camera', spot: 'desk', room: '' }, 'home'), 'add-home'),
      button('Check another', '', () => { S.check = null; S.ip = ''; delete S.form.ip; render(); }, 'another'));
    card.append(acts);
  } else if (c.verdict === 'half') {
    card.append(mk('p', 'bnote', 'Works on your Wi-Fi. Now block its internet in your router and restart the camera, then check again: it passes only if everything still answers.'));
    const tick = mk('label', 'r8-never'), box = mk('input', '');
    box.type = 'checkbox'; box.checked = S.blocked;
    box.addEventListener('change', () => { S.blocked = box.checked; render(); });
    tick.append(mk('span', '', 'I blocked its internet and restarted it'), box);
    const acts = mk('div', 'sacts'), again = button('Check again, internet blocked', 'primary', () => runCheck('offline'), 'offline');
    again.disabled = !S.blocked;
    acts.append(again);
    card.append(tick, acts);
  } else {
    card.append(mk('p', 'inote bad', c.missing || DIDNT));
    const acts = mk('div', 'sacts');
    acts.append(button('Check again', '', () => runCheck('first'), 'again'));
    card.append(acts);
  }
  return card;
}
function checkSection() {
  const set = mk('div', 'bset r8-add'), head = mk('h3', 'dhead'), b = mk('button', 'dsc');
  b.type = 'button';
  b.setAttribute('aria-expanded', S.open ? 'true' : 'false');
  b.setAttribute('aria-controls', 'camChk');
  b.setAttribute('data-k', 'check-open');
  b.append(mk('span', 'dl', 'Check a camera before you buy'), mk('span', 'dsum', S.open ? '' : 'Will it work with JARVIS with no cloud service? What to look for, and a check on your Wi-Fi.'));
  b.addEventListener('click', () => { S.open = !S.open; render(); });
  head.append(b);
  set.append(head);
  if (!S.open) return set;
  const body = mk('div', 'dbody');
  body.id = 'camChk';
  const ul = mk('ul', 'r8-checks');
  BEFORE_BUY.forEach(([t, s]) => ul.append(checkItem('need', '\u25c6', t, s, 'Must')));
  const [ipF, ip] = input('The camera\u2019s address on your Wi-Fi (its own app shows it)', 'ip', S.ip, { inputmode: 'decimal', maxlength: '15', autocomplete: 'off', placeholder: '192.168.1.40' });
  ip.addEventListener('input', () => { S.ip = ip.value; });
  const go = button('Check', 'primary', () => { S.ip = ip.value; S.blocked = false; runCheck('first'); }, 'check');
  const lrow = mk('span', 'lrow');
  lrow.append(ipF, go);
  body.append(mk('p', 'vt-ftitle', 'Before you buy: look for these words in its details'), ul,
    mk('p', 'vt-ftitle', 'Got one? Check it on your Wi-Fi'), lrow,
    mk('p', 'sfine', 'The check runs on your home laptop, on your Wi-Fi. The camera\u2019s password stays on the laptop; JARVIS hears only what worked.'));
  if (S.check) body.append(resultCard(S.check));
  set.append(body);
  return set;
}
function render() {
  if (!S.box) return;
  const focused = document.activeElement && document.activeElement.getAttribute ? document.activeElement.getAttribute('data-k') : null;
  const parts = [mk('p', 'r8-promise', PROMISE)];
  if (S.note) { const n = mk('p', 'bnote' + (S.noteKind ? ' ' + S.noteKind : ''), S.note); n.setAttribute('role', 'status'); parts.push(n); }
  if (!signedIn()) parts.push(mk('p', 'snote', 'Sign in to set up your cameras.'));
  else if (!S.view) parts.push(mk('p', 'snote', S.loading ? 'Reading your cameras\u2026' : ''));
  else {
    if (S.view.all_off) {
      const n = mk('div', 'bnote r8-alloff'), acts = mk('div', 'sacts');
      acts.append(button('Allow cameras again', 'primary', allowAll, 'allow-all'));
      n.append(mk('p', '', 'Every camera is switched off. Only a tap starts them again.'), acts);
      parts.push(n);
    }
    parts.push(camerasSection(), roomsSection());
  }
  parts.push(checkSection());
  S.box.replaceChildren(...parts);
  const again = focused && S.box.querySelector ? [...S.box.querySelectorAll('[data-k]')].find((n) => n.getAttribute('data-k') === focused) : null;
  if (again && typeof again.focus === 'function') again.focus();
}

// ---- the mode -----------------------------------------------------------------------------------------------------------
function style() {
  if (document.querySelector && document.querySelector('link[data-r8-setup]')) return;
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = STYLE;
  css.setAttribute('data-r8-setup', '');
  document.head.append(css);
}
function mount(el, P) {
  S.host = el; S.P = P;
  S.box = mk('div', 'r8-setup');
  el.append(S.box);
  style();
  render();
  load();
}
function stop() {
  clearTimeout(S.poll);
  if (S.testing) { const C = Cam(); try { if (C) C.stop('panel'); } catch (_) {} }
}
document.addEventListener('jarvis:ready', () => load());
document.addEventListener('jarvis:panel', (e) => { if (e && e.detail && e.detail.id === 'camera' && e.detail.open) load(); });
document.addEventListener('click', (e) => { const t = e && e.target; if (t && typeof t.closest === 'function' && t.closest('#camt-cameras')) load(); });
document.addEventListener('jarvis:camera', () => { // the chip changed; never under his typing
  const a = document.activeElement;
  if (S.view && !S.busy && !(a && S.box && S.box.contains(a) && /^(INPUT|SELECT)$/.test(a.tagName))) render();
});
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('cameras', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { CHECK, STYLE };
