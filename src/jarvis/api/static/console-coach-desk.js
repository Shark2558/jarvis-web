// src/jarvis/api/static/console-coach-desk.js -- R8 builder C (docs/plans/r8-vision.md 4.3, 4.5a, 4.7, 4.10; D3, D6, D10,
// D12; ADR-47, ADR-52): Camera -> Desk, a pixel pane (tests/test_r13_seams.py PANELS) mounted through the Camera panel's
// mode hook: window.JarvisCameraModes.register('desk', {mount(host, P), stop()}). What it holds, top to bottom:
//   the promise   who is followed (the tracking target, D6) and that only counts and times are kept
//   Posture       the HOME camera's coach (D3): it runs on the home laptop; this pane only shows its newest view
//                 (GET /v1/coach/live?use=posture, every 5 s while the pane is open) and his day's tiles
//   Your day      the day strip (GET /v1/coach/day): desk, away, phone, eating, off; the totals, the longest sitting
//                 stretch and screen time from ActivityWatch (per-program minutes, never a window title)
//   Sessions      the WEBCAM's coaches (builder D's use cases): a tap starts the camera (JarvisCamera, its one door), a
//                 look with JarvisVision.live(tasks, {uses: [id], rate, target}) on this device, the view drawn with
//                 console-coach-view.js; Stop (or the chip, "cameras off", closing the pane) ends it and posts each
//                 body's tally (POST /v1/coach/results: counts, times and scores only, never a picture or a point).
//                 "Keep a small window on top" (Chrome's Document Picture-in-Picture, D10): the view, the chip and Stop
//                 in a small window; closing it stops the camera. The camera's switches (GET /v1/camera/spots) are read
//                 when a session starts and every 60 s; a switch read as off stops the look at once.
// Asks the server NOTHING before sign-in (jarvis:ready). Words from the server are shown with textContent. ASCII source.
const USES = Object.freeze({
  'reaction-game': () => import('./console-coach-reaction.js'),
  'breath': () => import('./console-coach-breath.js'),
  'water': () => import('./console-coach-water.js'),
  'hand-rehab': () => import('./console-coach-handrehab.js'),
  'reach-grasp': () => import('./console-coach-reach.js'),
});
const VIEW = () => import('./console-coach-view.js'); // the one view renderer (C)
const GEOM = () => import('./console-coach-geom.js'); // preloaded once: the use cases import it statically
const BP = () => import('./console-coach-bp.js'); // the monitor's reading (D7, D)
const M = window.JarvisMobile;
const P = '/v1/coach';
const SESSIONS = Object.freeze([ // the webcam's sessions, in the mockup's order: [id, name, what it does]
  ['reaction-game', 'Reaction game', 'Touch the lit circles with your hands'],
  ['breath', 'Breathe', 'A paced breath on screen; it follows your shoulders'],
  ['water', 'Water', 'Counts a glass when a cup or bottle reaches your lips'],
  ['hand-rehab', 'Hand exercises', 'Open and close, finger taps, thumb to finger'],
  ['reach-grasp', 'Reach and grasp', 'Reach to the marked spots; each reach is scored'],
]);
const HOME_SESSIONS = Object.freeze([['seated', 'Seated movement'], ['bp-posture', 'Blood-pressure posture']]);
const WORDS = Object.freeze({
  intro: 'Posture and your day come from the home camera, on the home laptop. Short sessions use this laptop\u2019s camera.',
  all: ['Everyone in view is followed,', 'each saved on their own. Nothing is recorded; only counts and times are kept.'],
  me: ['Only you are followed.', 'Nothing is recorded; only counts and times are kept.'],
  person: ['One person is followed.', 'Nothing is recorded; only counts and times are kept.'],
  homeOff: 'The home camera\u2019s coach starts once the home camera is checked and set for the desk (Camera, Cameras).',
  homeAway: 'Not in view of the home camera right now.',
  coachOff: 'The coaches aren\u2019t set up on this server yet.',
  noKey: 'Kept results are off until the server has its token key.',
  nudge: 'The posture nudge is one quiet note after a minute of slouching, at most 3 an hour. Switch it on in Helpers, Nudges.',
  dayNone: 'Nothing yet today. The strip fills in as the home camera sees you at the desk.',
  screenOff: 'Off until ActivityWatch is installed on your laptop. It is free and keeps its data there; JARVIS reads only totals: which program, and for how long.',
  screenAway: 'Couldn\u2019t be read from the laptop just now.',
  safety: 'Practice only, not medical advice. Stop if anything hurts.',
  starting: 'Starting the camera\u2026',
  stopped: 'The session ended. Its counts are kept.',
  stoppedNothing: 'The session ended. Nothing to keep.',
  switchedOff: 'This camera is switched off in Cameras, so the session stopped.',
  blocked: 'The camera wasn\u2019t allowed. Allow it for this site in the browser\u2019s settings, then tap Start again.',
  noPip: 'This browser can\u2019t keep a small window on top. Keep the console visible while a session runs.',
  pipHidden: 'The camera stops if this tab is hidden, unless the small window on top is open: closing it stops the camera.',
  failed: 'That didn\u2019t work. Please try again.',
  onePerson: 'I can recognise one person only on the home camera, Sir; here I follow everyone or you. Say \u201ctrack everyone\u201d or \u201ctrack me\u201d.',
});
const KIND_WORDS = Object.freeze({ desk: 'At the desk', away: 'Away', phone: 'On the phone', eating: 'Eating', off: 'Camera off' });
const LIVE_MS = 5000, DAY_MS = 5 * 60 * 1000, TICK_MS = 250, SPOTS_MS = 60 * 1000, KEEP_MS = 15 * 60 * 1000;
const ALL_DAY = ['water']; // kept every 15 minutes too (plan 4.4)
const S = { host: null, P: null, listing: null, target: null, loop: 0, dayAt: 0, targetAt: 0, run: null, el: {}, gen: 0 };

function mk(tag, cls, text) { return M ? M.mk(tag, cls, text) : document.createElement(tag); }
function api(path, opts) { return M ? M.api(path, opts) : Promise.reject(new Error('The console is still starting.')); }
function signedIn() { return !!(S.P && S.P.signedIn && S.P.signedIn()); }
function chip(status, text) { const c = mk('span', 'vt-chip', text); if (status) c.dataset.status = status; return c; }
function button(text, cls, fn) { return S.P.button(text, cls, fn); }
function hm(seconds) { const m = Math.max(0, Math.round(seconds / 60)), h = Math.floor(m / 60); return h ? h + ' h ' + String(m % 60).padStart(2, '0') + ' m' : (m % 60) + ' m'; }
function hhmm(ts) { const d = new Date(ts * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }
function sessionId() { const b = new Uint8Array(6); crypto.getRandomValues(b); return 'cs_' + [...b].map((x) => x.toString(16).padStart(2, '0')).join(''); }
function said(e) { return e && typeof e.status === 'number' && e.status < 500 && e.message ? e.message : WORDS.failed; }

// ---- the frame -----------------------------------------------------------------------------------------------------
function eye() {
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg'), p = document.createElementNS(NS, 'path'), c = document.createElementNS(NS, 'circle');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2');
  p.setAttribute('d', 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z'); c.setAttribute('cx', '12'); c.setAttribute('cy', '12'); c.setAttribute('r', '3');
  svg.append(p, c);
  return svg;
}
function card(id, title) {
  const sec = mk('section', 'vt-card r8-card'), head = mk('div', 'rhead'), h = mk('h3', 'k nw', title);
  h.id = 'r8-' + id + '-h';
  sec.setAttribute('aria-labelledby', h.id);
  head.append(h);
  sec.append(head);
  return { sec, head };
}
function build(host) {
  const el = S.el;
  el.promise = mk('p', 'r8-promise');
  // Posture (home camera)
  const post = card('posture', 'Posture');
  el.postCard = post.sec; el.postChip = chip('', '\u2014'); post.head.append(el.postChip);
  el.postView = mk('div', 'r8-view'); el.postNote = mk('p', 'sfine', WORDS.homeOff);
  el.tiles = mk('div', 'tiles');
  el.tileUp = tile('\u2014', 'Upright'); el.tileDesk = tile('\u2014', 'At the desk'); el.tileLong = tile('\u2014', 'Longest stretch');
  el.tiles.append(el.tileUp.box, el.tileDesk.box, el.tileLong.box);
  const acts = mk('div', 'sacts');
  acts.append(button('Open Helpers', '', () => { if (window.JarvisDeck) window.JarvisDeck.open('helpers', { focus: true }); }));
  post.sec.append(el.postView, el.postNote, el.tiles, mk('p', 'sfine', WORDS.nudge), acts);
  // Your day
  const day = card('day', 'Your day');
  el.dayChip = chip('', '\u2014'); day.head.append(el.dayChip);
  el.dayBody = mk('div', 'r8-day'); el.dayNote = mk('p', 'sfine', '');
  el.screenH = mk('h4', 'r8-sub-h', 'Screen time'); el.screenBody = mk('div', '');
  day.sec.append(el.dayBody, el.dayNote, el.screenH, el.screenBody);
  // Sessions (webcam)
  const sess = mk('section', 'hp-sec r8-add');
  sess.append(mk('h3', 'hp-h', 'Sessions on this laptop\u2019s camera'));
  el.rows = {};
  SESSIONS.forEach(([id, name, what]) => {
    const r = mk('div', 'hp-row r8-sess'), t = mk('div', 'hp-txt'), a = mk('div', 'hp-acts'), b = mk('b', '', name);
    const start = button('Start', '', () => start_(id));
    start.setAttribute('aria-label', 'Start ' + name);
    t.append(b, mk('small', '', what));
    a.append(start);
    r.append(t, a);
    el.rows[id] = { row: r, start, b };
    sess.append(r);
  });
  el.live = mk('section', 'vt-card r8-card r8-live');
  el.live.hidden = true;
  const lh = mk('div', 'rhead'); el.liveH = mk('h3', 'k nw', 'Session'); el.liveChip = chip('ok', 'Camera on'); lh.append(el.liveH, el.liveChip);
  el.liveView = mk('div', 'r8-view'); el.liveNote = mk('p', 'sfine', ''); el.liveNote.setAttribute('role', 'status');
  const la = mk('div', 'sacts');
  el.stopBtn = button('Stop', 'primary', () => end('button'));
  el.pipBtn = button('Keep a small window on top', '', () => pip());
  la.append(el.stopBtn, el.pipBtn);
  el.live.append(lh, el.liveView, la, el.liveNote);
  el.state = mk('p', 'sfine', ''); el.state.setAttribute('role', 'status');
  // the home camera's other coaches (D's): their state only
  const home = mk('section', 'hp-sec r8-add');
  home.append(mk('h3', 'hp-h', 'On the home camera'));
  el.homeRows = {};
  HOME_SESSIONS.forEach(([id, name]) => {
    const r = mk('div', 'hp-row r8-sess'), t = mk('div', 'hp-txt'), b = mk('b', '', name), c = chip('', 'Not running');
    b.append(c); t.append(b, mk('small', '', 'Runs on the home laptop when the home camera is set for the desk.'));
    r.append(t); home.append(r);
    el.homeRows[id] = c;
  });
  sess.append(el.live, el.state, mk('p', 'sfine', WORDS.safety));
  host.replaceChildren(el.promise, mk('p', 'sfine', WORDS.intro), post.sec, day.sec, sess, home);
  paintPromise();
}
function tile(value, label) { const box = mk('div', 'tile'), b = mk('b', '', value); box.append(b, mk('span', '', label)); return { box, b }; }

function paintPromise() {
  const kind = (S.target && S.target.kind) || 'all', w = WORDS[kind] || WORDS.all, p = S.el.promise;
  if (!p) return;
  p.replaceChildren(eye(), (() => { const s = mk('span', ''); s.append(mk('b', '', w[0]), document.createTextNode(' ' + w[1])); return s; })());
}

// ---- the server's lists (after sign-in) ------------------------------------------------------------------------------
async function loadListing() {
  if (S.listing || !signedIn()) return S.listing;
  try {
    const v = await api(P + '/usecases');
    S.listing = new Map((v && Array.isArray(v.usecases) ? v.usecases : []).map((u) => [u.id, u]));
  } catch (_) { S.listing = null; }
  return S.listing;
}
async function loadTarget() {
  if (!signedIn()) return;
  try { const v = await api(P + '/target'); S.target = v && v.target ? v.target : null; } catch (_) { S.target = null; }
  paintPromise();
}

// ---- Posture: the home laptop's newest view --------------------------------------------------------------------------
async function view() { return VIEW(); }
function mine(bodies) { return bodies.find((b) => b && b.who === 'me') || bodies.find((b) => b && !b.who) || null; }
async function loadHome() {
  if (!signedIn() || !S.host) return;
  const el = S.el, R = await view();
  let v = null, err = null;
  try { v = await api(P + '/live?use=posture'); } catch (e) { err = e; }
  if (err) { // no home views on this server yet (404 coach off, 501 until the home camera's part): ask nothing more
    const off = err.status === 404 ? WORDS.coachOff : WORDS.homeOff;
    R.render(el.postView, []); el.postNote.textContent = off; el.postNote.hidden = false;
    el.postChip.textContent = 'Not running'; delete el.postChip.dataset.status; el.postCard.classList.remove('r8-warn');
    return;
  } else {
    const body = mine(v && Array.isArray(v.bodies) ? v.bodies : []);
    const widgets = body && Array.isArray(body.view) ? body.view : [];
    R.render(el.postView, widgets);
    const slouch = widgets.some((w) => w && (w.kind === 'tip' || (w.kind === 'timer' && w.word === 'slouching')));
    const away = !body || widgets.some((w) => w && w.kind === 'paused');
    el.postChip.textContent = away ? 'Not in view' : slouch ? 'Slouching' : 'Upright';
    if (away) delete el.postChip.dataset.status; else el.postChip.dataset.status = slouch ? 'amber' : 'ok';
    el.postCard.classList.toggle('r8-warn', slouch);
    el.postNote.textContent = away ? WORDS.homeAway : '';
    el.postNote.hidden = !away;
    const up = widgets.find((w) => w && w.kind === 'bar');
    el.tileUp.b.textContent = up && Number.isFinite(Number(up.n)) ? Math.round(Number(up.n)) + ' %' : '\u2014';
  }
  for (const [id] of HOME_SESSIONS) {
    let on = false;
    try { const h = await api(P + '/live?use=' + encodeURIComponent(id)); on = !!(h && Array.isArray(h.bodies) && h.bodies.length); } catch (_) { on = false; }
    const c = el.homeRows[id]; c.textContent = on ? 'Running' : 'Not running';
    if (on) c.dataset.status = 'ok'; else delete c.dataset.status;
  }
}

// ---- Your day ------------------------------------------------------------------------------------------------------------
async function loadDay() {
  if (!signedIn() || !S.host) return;
  const el = S.el;
  let v = null;
  try { v = await api(P + '/day'); } catch (e) {
    el.dayBody.replaceChildren(); el.dayChip.textContent = '\u2014'; delete el.dayChip.dataset.status;
    el.dayNote.textContent = e && e.status === 404 ? WORDS.coachOff : e && e.code === 'not_sealed' ? WORDS.noKey : said(e);
    paintScreen(null);
    return;
  }
  paintDay(v && v.day ? v.day : null);
}
function paintDay(d) {
  const el = S.el;
  const stretches = d && Array.isArray(d.stretches) ? d.stretches.filter((s) => KIND_WORDS[s.kind] && s.end > s.start) : [];
  const totals = (d && d.totals) || {};
  if (!d || !stretches.length) {
    el.dayBody.replaceChildren(); el.dayNote.textContent = WORDS.dayNone; el.dayChip.textContent = '\u2014'; delete el.dayChip.dataset.status;
    el.tileDesk.b.textContent = '\u2014'; el.tileLong.b.textContent = '\u2014';
    paintScreen(d ? d.screen : null);
    return;
  }
  const first = Math.min(...stretches.map((s) => s.start)), last = Math.max(...stretches.map((s) => s.end));
  const h0 = Math.floor((first - d.start) / 3600), h1 = Math.min(24, Math.max(h0 + 1, Math.ceil((last - d.start) / 3600)));
  const a = d.start + h0 * 3600, b = d.start + h1 * 3600, span = b - a;
  const hours = mk('div', 'r8-hours'), strip = mk('div', 'r8-strip'), list = mk('ul', 'r8-totals');
  hours.setAttribute('aria-hidden', 'true');
  const step = Math.max(1, Math.ceil((h1 - h0) / 6));
  for (let h = h0; h <= h1; h += step) { const s = mk('span', '', String(h).padStart(2, '0')); s.style.left = (((h - h0) * 3600) / span * 100).toFixed(2) + '%'; hours.append(s); }
  strip.setAttribute('role', 'img');
  strip.setAttribute('aria-label', 'Your day from ' + hhmm(first) + ' to ' + hhmm(last) + '; the totals are listed below.');
  stretches.forEach((s) => {
    const seg = mk('span', 'r8-seg ' + s.kind);
    seg.style.left = (((s.start - a) / span) * 100).toFixed(3) + '%';
    seg.style.width = (((s.end - s.start) / span) * 100).toFixed(3) + '%';
    strip.append(seg);
  });
  ['desk', 'away', 'phone', 'eating', 'off'].forEach((k) => {
    const n = Number(totals[k]) || 0;
    if (!n) return;
    const li = mk('li', ''), sw = mk('i', 'r8-sw ' + k);
    sw.setAttribute('aria-hidden', 'true');
    li.append(sw, mk('span', '', KIND_WORDS[k]), mk('em', '', hm(n)));
    list.append(li);
  });
  el.dayBody.replaceChildren(hours, strip, list);
  const longest = d.longest && d.longest.end > d.longest.start ? d.longest : null;
  el.dayNote.textContent = longest ? 'Longest sitting stretch: ' + hm(longest.end - longest.start) + ', ' + hhmm(longest.start) + ' to ' + hhmm(longest.end) + '.' : '';
  const live = Date.now() / 1000 - last < 180;
  el.dayChip.textContent = live ? 'Live' : 'Until ' + hhmm(last);
  if (live) el.dayChip.dataset.status = 'ok'; else delete el.dayChip.dataset.status;
  el.tileDesk.b.textContent = hm((Number(totals.desk) || 0) + (Number(totals.phone) || 0) + (Number(totals.eating) || 0));
  el.tileLong.b.textContent = longest ? hm(longest.end - longest.start) : '\u2014';
  paintScreen(d.screen);
}
function paintScreen(sc) {
  const el = S.el, body = el.screenBody;
  if (!sc || sc.state !== 'ok') {
    const p = mk('p', 'sfine', sc && sc.state === 'unreachable' ? WORDS.screenAway : WORDS.screenOff);
    body.replaceChildren(p);
    el.screenH.replaceChildren(document.createTextNode('Screen time '), chip(sc && sc.state === 'unreachable' ? 'amber' : '', 'Off'));
    return;
  }
  const list = mk('ul', 'r8-progs');
  (Array.isArray(sc.programs) ? sc.programs : []).slice(0, 5).forEach((p) => {
    const li = mk('li', '');
    li.append(mk('span', '', String(p.name || '').slice(0, 40)), mk('em', '', hm((Number(p.minutes) || 0) * 60)));
    list.append(li);
  });
  el.screenH.replaceChildren(document.createTextNode('Screen time \u00b7 ' + hm((Number(sc.active_minutes) || 0) * 60)));
  body.replaceChildren(list);
}

// ---- a session on this laptop's camera -----------------------------------------------------------------------------
function cam() { return window.JarvisCamera || null; }
function vis() { return window.JarvisVision || null; }
async function spotsAllow() { // B's switches: the desk webcam (a device camera, browser, at the desk); unknown = allowed
  let v = null;
  try { v = await api('/v1/camera/spots'); } catch (_) { return true; }
  const spots = v && (v.spots || v);
  if (!spots || typeof spots !== 'object') return true;
  if (spots.all_off === true) return false;
  const cams = Array.isArray(spots.cameras) ? spots.cameras : [], rooms = Array.isArray(spots.rooms) ? spots.rooms : [];
  const me = cams.find((c) => c && c.kind === 'device' && c.source === 'browser' && c.spot === 'desk');
  if (!me) return true;
  const room = rooms.find((r) => r && r.id === me.room);
  return me.on !== false && !(room && room.never === true);
}
function paintRows() {
  const busy = !!S.run;
  SESSIONS.forEach(([id]) => {
    const r = S.el.rows[id];
    r.start.setAttribute('aria-disabled', busy ? 'true' : 'false');
    r.start.disabled = busy;
  });
}
async function start_(id) { // only from the Start button's tap: the camera's door checks the tap itself
  const el = S.el, c = cam(), V = vis();
  if (S.run || !signedIn()) return;
  if (S.target && S.target.kind === 'person') { el.state.textContent = WORDS.onePerson; return; } // no face matching here (D6)
  el.state.textContent = WORDS.starting;
  const gen = ++S.gen;
  let live = null;
  try {
    if (!c || !V) throw new Error(WORDS.failed);
    const started = c.start({ facing: 'user' }); // inside the tap, before anything else waits
    const [listing] = await Promise.all([loadListing(), started]);
    const u = listing && listing.get(id);
    if (!u || u.source !== 'browser') throw new Error(WORDS.failed);
    if (!(await spotsAllow())) { c.stop('panel'); el.state.textContent = WORDS.switchedOff; return; }
    await GEOM();
    await USES[id]();
    if (gen !== S.gen || !c.live()) throw new Error('The camera was stopped.');
    V.reset(id);
    const run = { id, sid: sessionId(), name: SESSIONS.find((x) => x[0] === id)[1], look: null, tick: 0, spots: 0, keep: 0, pip: null, ended: false };
    S.run = run;
    live = V.live(u.tasks, { uses: [id], rate: u.rate, target: S.target || { kind: 'all' }, onError: (e) => end('error', e) });
    run.look = live;
    run.tick = setInterval(() => paintRun(run), TICK_MS);
    run.spots = setInterval(async () => { if (!(await spotsAllow())) end('switched'); }, SPOTS_MS);
    if (ALL_DAY.includes(id)) run.keep = setInterval(() => keep(run), KEEP_MS);
    el.liveH.textContent = run.name; el.live.hidden = false; el.pipBtn.hidden = !window.documentPictureInPicture;
    el.liveNote.textContent = window.documentPictureInPicture ? WORDS.pipHidden : WORDS.noPip;
    el.state.textContent = '';
    paintRows();
    paintRun(run);
  } catch (e) {
    if (live) live.end();
    if (c && c.live()) c.stop('panel');
    el.state.textContent = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError') ? WORDS.blocked : (e && e.message) || WORDS.failed;
  }
}
async function paintRun(run) {
  if (S.run !== run || run.ended) return;
  const V = vis(), R = await view();
  if (!V) return;
  const t = V.tally(run.id);
  R.render(S.el.liveView, t && Array.isArray(t.view) ? t.view : []);
}
function tallies(run) { // every body's tally, read at once: counts, times and scores only
  const V = vis();
  if (!V) return [];
  const bodies = V.tracks(run.id), list = bodies.length ? bodies : [{ track: 0, who: 'me' }]; // one state: his own laptop
  return list.slice(0, 4).map((b) => {
    const t = V.tally(run.id, bodies.length ? b.track : undefined);
    return t && t.tally ? { use: run.id, session: run.sid, track: b.track, who: t.who || b.who || '', tally: t.tally } : null;
  }).filter(Boolean);
}
async function post(list) { // POST /v1/coach/results; a dropped or unreachable tally is not retried (never repaired)
  let kept = 0;
  for (const body of list) {
    try { await api(P + '/results', { method: 'POST', body }); kept += 1; } catch (_) { /* said by the count below */ }
  }
  return kept;
}
function keep(run) { return post(tallies(run)); }
async function end(why, err) {
  const run = S.run, el = S.el;
  if (!run || run.ended) return;
  run.ended = true;
  clearInterval(run.tick); clearInterval(run.spots); clearInterval(run.keep);
  if (run.look) run.look.end();
  const list = tallies(run); // read before anything is cleared, then the camera stops at once
  const V = vis(); if (V) V.reset(run.id);
  const c = cam(); if (c && c.live()) c.stop('panel');
  closePip(run);
  S.run = null;
  const kept = await post(list);
  el.live.hidden = true;
  (await view()).render(el.liveView, []);
  el.state.textContent = why === 'switched' ? WORDS.switchedOff : why === 'error' && err && err.message && err.message !== 'The camera was stopped.'
    ? err.message : kept ? WORDS.stopped : WORDS.stoppedNothing;
  paintRows();
}

// ---- the small window (D10, ADR-52) --------------------------------------------------------------------------------------
async function pip() {
  const run = S.run, dpip = window.documentPictureInPicture, el = S.el;
  if (!run || run.pip || !dpip || typeof dpip.requestWindow !== 'function') { el.liveNote.textContent = WORDS.noPip; return; }
  let win = null;
  try { win = await dpip.requestWindow({ width: 360, height: 320 }); } catch (_) { el.liveNote.textContent = WORDS.noPip; return; }
  if (S.run !== run || run.ended) { try { win.close(); } catch (_) {} return; }
  const doc = win.document;
  document.querySelectorAll('link[rel="stylesheet"]').forEach((l) => { const n = doc.createElement('link'); n.rel = 'stylesheet'; n.href = l.href; doc.head.append(n); });
  ['data-surface', 'data-theme', 'data-motion'].forEach((a) => { const v = document.documentElement.getAttribute(a); if (v !== null) doc.documentElement.setAttribute(a, v); });
  const box = doc.createElement('main'), head = doc.createElement('div'), h = doc.createElement('h3'), stop = doc.createElement('button');
  box.className = 'r8-pip'; head.className = 'r8-pip-head'; h.className = 'k nw'; h.textContent = run.name + ' \u00b7 Camera on';
  stop.type = 'button'; stop.className = 'btn sact primary'; stop.textContent = 'Stop'; stop.addEventListener('click', () => end('button'));
  head.append(h, stop);
  const holder = doc.createElement('div'); holder.className = 'r8-view';
  box.append(head, holder);
  doc.body.append(box);
  run.pip = { win, holder, home: el.liveView.parentNode, next: el.liveView.nextSibling };
  holder.append(doc.adoptNode(el.liveView)); // the same view element now draws in the small window
  win.addEventListener('pagehide', () => end('window'), { once: true }); // closing the small window stops the camera
  const C = cam();
  if (C && typeof C.keepWhile === 'function') { try { C.keepWhile(win); } catch (_) {} } // B's door: stay on while it is open
  el.pipBtn.hidden = true;
}
function closePip(run) {
  const p = run && run.pip;
  if (!p) return;
  run.pip = null;
  try { p.home.insertBefore(document.adoptNode(S.el.liveView), p.next && p.next.parentNode === p.home ? p.next : null); } catch (_) {}
  try { if (!p.win.closed) p.win.close(); } catch (_) {}
}

// ---- the mode's life -------------------------------------------------------------------------------------------------------
function shown() { return !!S.host && !document.hidden && S.host.getClientRects().length > 0; } // the Desk tab is on screen
function refresh(force) { // asks the server only while the pane is on screen, after sign-in
  if (!signedIn() || (!force && !shown())) return;
  const now = Date.now();
  if (force || now - S.targetAt > DAY_MS) { S.targetAt = now; loadTarget(); }
  if (force || now - S.dayAt > DAY_MS) { S.dayAt = now; loadDay(); }
  loadHome();
}
function mount(el, helpers) {
  S.host = el; S.P = helpers;
  build(el);
  paintRows();
  clearInterval(S.loop);
  S.loop = setInterval(() => refresh(false), LIVE_MS);
  new MutationObserver(() => { if (!el.hidden) setTimeout(() => refresh(false), 0); }).observe(el, { attributes: true, attributeFilter: ['hidden'] });
}
function stop() { end('panel'); } // the Camera panel closed, hidden, or another pixel tab chosen
document.addEventListener('jarvis:ready', () => { if (S.host) { S.dayAt = 0; S.targetAt = 0; refresh(false); } });
document.addEventListener('jarvis:panel', (e) => { const d = (e && e.detail) || {}; if (d.id === 'camera' && d.open) setTimeout(() => refresh(false), 0); });
document.addEventListener('jarvis:camera', (e) => { const d = (e && e.detail) || {}; if (S.run && !d.live && !S.run.ended) end('camera'); });
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('desk', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { USES, VIEW, GEOM, BP, SESSIONS, refresh };
