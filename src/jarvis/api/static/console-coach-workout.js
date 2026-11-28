// src/jarvis/api/static/console-coach-workout.js -- R8.1 builder E (docs/plans/r8-vision.md v8.0.4 2.2, 4.3, 4.8, 6;
// D6; the approved mockup docs/plans/r8-mockups/workout-phone.html): Camera -> Workout, a pixel pane mounted through
// the Camera panel's mode hook (window.JarvisCameraModes.register('workout', {mount, stop})). On the tripod phone:
//   the picker    "Before your first session" (place the phone, clear the space: both a short look with
//                 `space-check`, row 223, which keeps nothing), then the sessions by kind (Strength, Flow, Dynamic,
//                 More); a handstand needs "a wall" or "a spotter" picked, a partner stretch the partner's agreement
//   a session     from a tap only: the camera (console-camera.js, which keeps the screen awake while live), the
//                 switches in Cameras (B), then JarvisVision.live(tasks, {uses, rate, target}) with the session's use
//                 cases; on a phone it fills the screen. Each use case's view (fixed widgets only) is laid out big:
//                 counts and times as tiles readable from 2-3 m, a score as a meter, a form tip as a card, a checklist
//                 or a pause in the view box; a pacer or targets go to C's renderer (console-coach-view.js). The
//                 browser's own voice says each new count and tip (no cloud, Rs 0; Voice off to mute). Pause stops the
//                 camera and keeps the counts; Resume needs a tap. Stop (or Back) keeps each body's tally (POST
//                 /v1/coach/results: counts, times and scores only; D6: everyone in view, a stranger as a guest).
//   band (219)    he taps the band's anchor on the picture once; every half second the pane compares that small area
//                 with how it looked (16 brightness numbers, in memory only, never kept or sent) and says at once when
//                 it is out of sight. The picture shows only for that tap; a session shows no picture at all.
// The safety line "Stop if anything hurts." is on every screen; a battery at 20 % or less says so (risk 11).
// R8.1 I1 join (docs/plans/r8-integration/R81-I1-NOTES.md):
//   setup         each session's choices go to its use cases only through live(..., {setup}) (S2's contract line from
//                 R8's join: r.setup on every Result): the wall or spotter (handstand never starts without it), the
//                 agility marks he taps on the picture, his boxing stance (optional), the partner's agreement
//                 ({consent: true, consent_at}; that session follows everyone and keeps only his own tallies, as `me`),
//                 the walk test's typed course length, and for tai-chi and dance his recorded routine (or "record")
//   recordings    a tally carrying `record` is his routine: its chunks are joined and PUT to /v1/coach/routines/{rid}
//                 (joint angles only); it is never posted as a result
//   body lines    the approved mockup's "Body lines only": the pane names its own reader, `body-lines`, in each look;
//                 the driver hands it the bodies the tracking target picks and it keeps only the newest points of each
//                 in this page's memory to draw them as SVG strokes. Never kept, never sent, never in a tally.
// Never a picture, a point or a box leaves this phone. ASCII; textContent only.
const M = window.JarvisMobile;
const P = '/v1/coach';
const USES = Object.freeze({
  'reps': () => import('./console-coach-reps.js'),
  'warm-up': () => import('./console-coach-warmup.js'),
  'band': () => import('./console-coach-band.js'),
  'form': () => import('./console-coach-form.js'),
  'yoga': () => import('./console-coach-yoga.js'),
  'plank': () => import('./console-coach-plank.js'),
  'space-check': () => import('./console-coach-space.js'),
  'balance': () => import('./console-coach-balance.js'),
  'boxing': () => import('./console-coach-boxing.js'),
  'agility': () => import('./console-coach-agility.js'),
  'pilates': () => import('./console-coach-pilates.js'),
  'tai-chi': () => import('./console-coach-taichi.js'),
  'jump': () => import('./console-coach-jump.js'),
  'dance': () => import('./console-coach-dance.js'),
  'handstand': () => import('./console-coach-handstand.js'),
  'kettlebell': () => import('./console-coach-kettlebell.js'),
  'partner-stretch': () => import('./console-coach-partner.js'),
  'walk-test': () => import('./console-coach-walk.js'),
  'sit-to-stand': () => import('./console-coach-sitstand.js'),
  'meal': () => import('./console-coach-meal.js'),
});
const VIEW = () => import('./console-coach-view.js'); // C's renderer: the pacer and targets widgets
const GEOM = () => import('./console-coach-geom.js'); // preloaded once: the use cases import it statically
const GROUPS = Object.freeze([['strength', 'Strength'], ['flow', 'Flow'], ['dynamic', 'Dynamic'], ['more', 'More']]);
const S_ = (id, name, what, uses, group, extra) => Object.freeze(Object.assign({ id, name, what, uses: Object.freeze(uses), group }, extra || {}));
const SESSIONS = Object.freeze([
  S_('warm-up', 'Warm-up', 'Six moves to tick before you start', ['warm-up'], 'strength'),
  S_('squats', 'Squats', 'Reps, tempo and form tips', ['reps', 'form'], 'strength'),
  S_('push-ups', 'Push-ups', 'Reps and form tips \u00b7 side or front view', ['reps', 'form'], 'strength'),
  S_('reps', 'Lunges, curls, presses, jacks', 'Reps and tempo \u00b7 found from your moves', ['reps'], 'strength'),
  S_('plank', 'Plank', 'Hold time and a straight line \u00b7 side view', ['plank'], 'strength'),
  S_('band', 'Band work', 'Reps, with the band\u2019s anchor in view \u00b7 your band', ['band'], 'strength', { anchor: true }),
  S_('kettlebell', 'Kettlebell swing', 'Hip hinge and swing path \u00b7 your kettlebell', ['kettlebell'], 'strength'),
  S_('yoga', 'Yoga and mobility', 'Poses recognised and held', ['yoga'], 'flow'),
  S_('balance', 'Single-leg balance', 'Hold time and sway', ['balance'], 'flow'),
  S_('pilates', 'Pilates', 'The sequence, step by step', ['pilates'], 'flow'),
  S_('tai-chi', 'Tai chi', 'Your form against your recording', ['tai-chi'], 'flow', { confirm: 'routine', routine: 'tai-chi-1' }),
  S_('dance', 'Dance', 'In time with a routine you record', ['dance'], 'flow', { confirm: 'routine', routine: 'dance-1' }),
  S_('boxing', 'Shadowboxing', 'Punches and combinations', ['boxing'], 'dynamic', { confirm: 'stance' }),
  S_('agility', 'Agility', 'Split times between your marks', ['agility'], 'dynamic', { marks: true }),
  S_('jump', 'Jumps', 'Height and landings', ['jump'], 'dynamic'),
  S_('handstand', 'Handstand', 'Hold time and drift \u00b7 a wall or a spotter only', ['handstand'], 'dynamic', { confirm: 'support' }),
  S_('partner-stretch', 'Partner stretch', 'Your ranges and holds \u00b7 your partner agrees first', ['partner-stretch'], 'more', { confirm: 'partner', own: true, noLines: true }),
  S_('walk-test', 'Six-minute walk', 'Laps and turns \u00b7 practice, not a clinical test', ['walk-test'], 'more', { confirm: 'course' }),
  S_('sit-to-stand', 'Sit to stand', '30 seconds and five times \u00b7 practice only', ['sit-to-stand'], 'more'),
  S_('meal', 'Meal pace', 'Bites and meal length \u00b7 the phone at the table', ['meal'], 'more'),
]);
const WORDS = Object.freeze({
  intro: 'Place the phone 2 to 3 metres away. Counts and tips are worked out on this phone; only the numbers are kept.',
  first: 'Before your first session', steps: '2 steps',
  place: 'Place the phone', placeWhy: '2 to 3 metres away, at hip height, your whole body in view.', placeBtn: 'Check my position',
  clear: 'Clear the space', clearWhy: 'JARVIS looks for things on the floor you could trip on.', clearBtn: 'Check the space',
  inView: 'All of you is in view.', notInView: 'I can\u2019t see all of you. Step back or tilt the phone.',
  looking: 'Looking on this phone\u2026', start: 'Start', kinds: 'Kind of exercise',
  hurts: 'Stop if anything hurts.', handstand: 'Handstands only with a wall or a spotter.',
  practice: 'Practice only, not medical advice.',
  all: ['Everyone in view is followed,', 'each saved on their own. Nothing is recorded; only counts and times are kept.'],
  me: ['Only you are followed.', 'Nothing is recorded; only counts and times are kept.'],
  person: ['One person is followed.', 'Nothing is recorded; only counts and times are kept.'],
  onePerson: 'Following one named person needs the home camera. Say \u201cJarvis, track everyone\u201d or \u201ctrack me\u201d to use this phone.',
  support: 'Is there a wall behind you or a spotter with you?', wall: 'A wall behind me', spotter: 'A spotter with me',
  partner: 'Your partner agrees to this session. Only your counts are kept.', partnerYes: 'My partner agrees: start',
  back: 'Back', pause: 'Pause', resume: 'Resume', stop: 'Stop', voiceOn: 'Voice on', voiceOff: 'Voice off',
  cap: 'No picture is shown or kept: it stays on this phone', inViewN: (n) => (n === 1 ? '1 person in view' : n + ' people in view'),
  nobody: 'Step into view: all of you.',
  paused: ['Camera off. Counting is paused.', 'Your counts so far are kept.', 'Tap Resume to start the camera again. Only a tap starts it.'],
  stopped: 'The session ended. Its counts are kept.', stoppedNothing: 'The session ended. Nothing to keep.',
  switchedOff: 'This phone\u2019s camera is switched off in Cameras, so nothing started.',
  blocked: 'The browser blocked the camera for JARVIS. Tap the icon left of the address, then Permissions, Camera, Allow. Then tap Try again.',
  failed: 'That didn\u2019t work. Please try again.', starting: 'Starting the camera\u2026',
  anchorAsk: 'Tap the band\u2019s anchor on the picture.', anchorSet: 'Anchor marked.',
  anchorGone: 'I can\u2019t see the band\u2019s anchor. Move so the phone sees it.',
  battery: (p) => 'Battery at ' + p + ' %. Plug the phone in, or stop soon.',
  // R8.1 I1: the setups and the body lines
  stance: 'Which foot is in front when you box? Only used when the phone can\u2019t tell.',
  orthodox: 'Left foot forward', southpaw: 'Right foot forward', skip: 'Skip',
  course: 'How long is your walking course, end to end?', courseField: 'Course length in metres (1 to 100)',
  courseStart: 'Start the walk', courseBad: 'Type a length from 1 to 100 metres.',
  routineLooking: 'Looking for your recording\u2026',
  routineHave: { 'tai-chi': 'Follow the form you recorded, or record it again.', dance: 'Dance with the routine you recorded, or record it again.' },
  routineNone: { 'tai-chi': 'First record your form: move through it once, then press Stop.', dance: 'First record your routine: dance it once, then press Stop.' },
  routineLimit: 'A recording stops at 5 minutes. Only joint angles are kept, never a picture.',
  follow: 'Follow my recording', record: 'Record it again', recordFirst: 'Record it now',
  routineSaved: 'The session ended. Your recording is kept (joint angles only).',
  routineFailed: 'The session ended, but your recording couldn\u2019t be kept. Please record it again.',
  marksAsk: 'Tap each mark on the picture in the order you\u2019ll run them: 2 to 12. Tap a mark again to come back to it.',
  marksN: (n) => (n === 1 ? '1 mark' : n + ' marks'), marksDone: 'Done: start', marksUndo: 'Undo',
  linesCap: 'Body lines only \u00b7 the picture stays on this phone',
});
const TICK_MS = 250, SPOTS_MS = 60000, CHECK_S = 4, ANCHOR_MS = 500, ANCHOR_BOX = 0.06, MOVED = 0.12, LOW_BATTERY = 0.2;
const COURSE_MIN = 1, COURSE_MAX = 100, MARKS_MIN = 2, MARKS_MAX = 12, CHUNK = 100;
const ROUTINE_ID = /^(?:dance-(?:[1-9]|1[0-9]|20)|tai-chi-[1-9])$/; // jarvis.coach.store's ids, posture never from here
const ROUTINE_KINDS = Object.freeze(['dance', 'tai-chi']);
const S = { el: null, mk: null, button: null, field: null, signedIn: () => false, run: null, gen: 0, target: null, listing: null, group: 'strength', voice: true };

function api(path, opts) { return M ? M.api(path, opts) : Promise.reject(new Error('The console is still starting.')); }
function cam() { return window.JarvisCamera || null; }
function vis() { return window.JarvisVision || null; }
function sessionId() { const b = new Uint8Array(6); crypto.getRandomValues(b); return 'cs_' + [...b].map((x) => x.toString(16).padStart(2, '0')).join(''); }
const mk = (tag, cls, text) => S.mk(tag, cls, text);

// ---- the band's anchor (pure: tested in tests/browser/test_r81_workout_pane.py) -------------------------------------
/** 16 brightness numbers (0..1, a 4 x 4 grid) of the area around (x, y) in an ImageData-like {data, width, height}. */
export function fingerprint(img) {
  const cells = new Array(16).fill(0), counts = new Array(16).fill(0);
  if (!img || !img.data || !img.width || !img.height) return null;
  for (let y = 0; y < img.height; y += 1) {
    for (let x = 0; x < img.width; x += 1) {
      const i = (y * img.width + x) * 4, c = Math.min(3, Math.floor(4 * y / img.height)) * 4 + Math.min(3, Math.floor(4 * x / img.width));
      cells[c] += (0.299 * img.data[i] + 0.587 * img.data[i + 1] + 0.114 * img.data[i + 2]) / 255;
      counts[c] += 1;
    }
  }
  return cells.map((v, k) => (counts[k] ? v / counts[k] : 0));
}
/** True when the anchor's area no longer looks as it did when he marked it (covered, or the phone moved). */
export function anchorMoved(before, now) {
  if (!Array.isArray(before) || !Array.isArray(now) || before.length !== 16 || now.length !== 16) return true;
  return before.reduce((n, v, k) => n + Math.abs(v - now[k]), 0) / 16 > MOVED;
}
function grab(view, at) { // the anchor's area of the picture now, as 16 numbers; the pixels are dropped at once
  const canvas = view && typeof view.frame === 'function' ? view.frame() : null;
  if (!canvas || !at) return null;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const w = Math.max(4, Math.round(canvas.width * ANCHOR_BOX * 2)), h = Math.max(4, Math.round(canvas.height * ANCHOR_BOX * 2));
  const x = Math.max(0, Math.min(canvas.width - w, Math.round(at.x * canvas.width - w / 2)));
  const y = Math.max(0, Math.min(canvas.height - h, Math.round(at.y * canvas.height - h / 2)));
  try { return fingerprint(ctx.getImageData(x, y, w, h)); } catch (_) { return null; }
}
/** Where he tapped on the video, as 0..1 of the camera's own frame (object-fit: contain may leave bars); null on a bar. */
function tapAt(video, ev) {
  const r = video.getBoundingClientRect(), bw = r.width || 1, bh = r.height || 1;
  const vw = video.videoWidth || bw, vh = video.videoHeight || bh, k = Math.min(bw / vw, bh / vh), w = vw * k, h = vh * k;
  const x = (ev.clientX - r.left - (bw - w) / 2) / (w || 1), y = (ev.clientY - r.top - (bh - h) / 2) / (h || 1);
  const r3 = (v) => Math.round(v * 1000) / 1000;
  return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? { x: r3(x), y: r3(y) } : null;
}

// ---- the body lines (the approved mockup: "Body lines only - the picture stays on this phone") -------------------
// The pane's own one-body reader, named in each look: it keeps the newest points of each body the target picks in this
// page's memory (L.bodies) and draws them; its summary is empty, so nothing of it can be kept, posted or spoken.
const LINES_ID = 'body-lines';
const LINE_MS = 1000; // a body not seen for a second is no longer drawn
const LINE_SEEN = 0.5;
const BONES = Object.freeze([[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25],
  [25, 27], [27, 31], [24, 26], [26, 28], [28, 32]]);
const JOINTS = Object.freeze([11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]);
const SVG = 'http://www.w3.org/2000/svg';
const L = { on: false, bodies: new Map(), frame: 0, mirror: true };
/** One body's strokes in a box 1000 high and 1000 x aspect wide (x scaled by the frame's aspect, mirrored for the
 *  front camera): bones and joints seen well, the head round the nose. Pure: tested in test_r81_workout_pane.py. */
export function bodyLines(points, aspect, mirror) {
  if (!Array.isArray(points) || points.length !== 33) return null;
  const k = Number.isFinite(aspect) && aspect >= 0.2 && aspect <= 5 ? aspect : 1, w = 1000 * k;
  const good = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < LINE_SEEN);
  const at = (i) => { const p = points[i]; return good(p) ? [Math.round((mirror ? 1 - p.x : p.x) * w), Math.round(p.y * 1000)] : null; };
  const bones = BONES.map(([a, b]) => [at(a), at(b)]).filter(([a, b]) => a && b).map(([a, b]) => [...a, ...b]);
  const joints = JOINTS.map(at).filter(Boolean);
  const nose = at(0), sh = at(11) && at(12) ? [(at(11)[0] + at(12)[0]) / 2, (at(11)[1] + at(12)[1]) / 2] : null;
  const head = nose && sh ? [nose[0], nose[1], Math.max(18, Math.round(0.45 * Math.hypot(nose[0] - sh[0], nose[1] - sh[1])))] : null;
  return bones.length ? { w: Math.round(w), h: 1000, bones, joints, head } : null;
}
/** The reader's onResult: the newest points of this body, in memory only (exported for the browser test's stand-in). */
export function takeLines(r, state) {
  if (!L.on || !r || !r.ok || !r.data || !Array.isArray(r.data.points)) return state;
  L.bodies.set(Number.isInteger(r.track) ? r.track : 0, { points: r.data.points, aspect: r.aspect, at: performance.now() });
  if (!L.frame) L.frame = requestAnimationFrame(drawLines);
  return state;
}
function linesUse() { // once; a stand-in registered first (the browser test) takes its place
  const V = vis();
  if (V) V.use({ id: LINES_ID, tasks: ['pose'], onResult: takeLines, summary: () => ({ view: [], tally: null }) });
}
function svgEl(tag, cls, attrs) {
  const n = document.createElementNS(SVG, tag);
  if (cls) n.setAttribute('class', cls);
  Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, String(v)));
  return n;
}
function fresh(now) { // a body not seen for LINE_MS is no longer drawn; -> how many are
  [...L.bodies.keys()].forEach((k) => { if (now - L.bodies.get(k).at > LINE_MS) L.bodies.delete(k); });
  return L.bodies.size;
}
function drawLines() {
  L.frame = 0;
  const fig = S.el && S.el.fig, now = performance.now();
  if (!fig || !L.on) return;
  fresh(now);
  const shapes = [...L.bodies.values()].map((b) => bodyLines(b.points, b.aspect, L.mirror)).filter(Boolean);
  const w = Math.max(1000, ...shapes.map((s) => s.w));
  fig.setAttribute('viewBox', '0 0 ' + w + ' 1000');
  fig.replaceChildren(...shapes.flatMap((s) => {
    const dx = Math.round((w - s.w) / 2), d = s.bones.map(([a, b, c, e]) => 'M' + (a + dx) + ' ' + b + 'L' + (c + dx) + ' ' + e).join('');
    const out = [svgEl('path', 'bone', { d })];
    if (s.head) out.push(svgEl('circle', 'head', { cx: s.head[0] + dx, cy: s.head[1], r: s.head[2] }));
    return out.concat(s.joints.map(([x, y]) => svgEl('circle', 'joint', { cx: x + dx, cy: y, r: 14 })));
  }));
}
function linesOff() { // the points go with the look; the view falls back to its words
  L.on = false; L.bodies.clear();
  if (L.frame) cancelAnimationFrame(L.frame);
  L.frame = 0;
  if (!S.el || !S.el.fig) return;
  S.el.fig.replaceChildren();
  S.el.view.classList.remove('figs');
  S.el.view.removeAttribute('aria-label');
  S.el.cap.textContent = WORDS.cap;
}

// ---- server lists, switches and the target ---------------------------------------------------------------------------
async function loadListing() {
  if (S.listing) return S.listing;
  const v = await api(P + '/usecases');
  const list = v && Array.isArray(v.usecases) ? v.usecases : [];
  S.listing = new Map(list.filter((u) => u && typeof u.id === 'string').map((u) => [u.id, u]));
  return S.listing;
}
async function loadTarget() {
  try { const v = await api(P + '/target'); S.target = v && v.target ? v.target : null; } catch (_) { S.target = null; }
  paintPromise();
}
async function spotsAllow() { // B's switches for this phone at the workout spot; unknown = allowed
  let v = null;
  try { v = await api('/v1/camera/spots'); } catch (_) { return true; }
  const spots = v && (v.spots || v);
  if (!spots || typeof spots !== 'object') return true;
  if (spots.all_off === true) return false;
  const cams = Array.isArray(spots.cameras) ? spots.cameras : [], rooms = Array.isArray(spots.rooms) ? spots.rooms : [];
  const me = cams.find((c) => c && c.kind === 'device' && c.source === 'phone' && c.spot === 'workout');
  if (!me) return true;
  const room = rooms.find((r) => r && r.id === me.room);
  return me.on !== false && !(room && room.never === true);
}

// ---- the frame ---------------------------------------------------------------------------------------------------------
function promiseEl() {
  const p = mk('p', 'r8-promise'), span = mk('span', ''), b = mk('b', '');
  span.append(b, mk('span', ''));
  p.append(span);
  return p;
}
function paintPromise() {
  const kind = S.target && ['me', 'person'].includes(S.target.kind) ? S.target.kind : 'all';
  const w = WORDS[kind];
  (S.el ? S.el.promises : []).forEach((p) => { const s = p.firstChild; s.firstChild.textContent = w[0]; s.lastChild.textContent = ' ' + w[1]; });
}
function safeEl(extra) {
  const p = mk('p', 'r8-safe'), b = mk('b', '', WORDS.hurts);
  p.append(b, document.createTextNode(' ' + (extra || WORDS.practice)));
  return p;
}
function stepEl(title, why, label, fn) {
  const li = mk('li', ''), acts = mk('div', 'sacts'), out = mk('p', 'sfine');
  out.setAttribute('role', 'status');
  acts.append(S.button(label, '', fn));
  li.append(mk('b', '', title), mk('small', '', why), acts, out);
  return { li, out };
}
function buildPicker(host) {
  const el = S.el, card = mk('div', 'vt-card r8-card'), head = mk('div', 'rhead'), ol = mk('ol', 'r8-steps');
  head.append(mk('h3', 'k nw', WORDS.first), mk('span', 'vt-chip', WORDS.steps));
  el.place = stepEl(WORDS.place, WORDS.placeWhy, WORDS.placeBtn, () => check('place'));
  el.clear = stepEl(WORDS.clear, WORDS.clearWhy, WORDS.clearBtn, () => check('clear'));
  ol.append(el.place.li, el.clear.li);
  card.append(head, ol);
  const pick = mk('div', 'r8-pick'), fs = mk('fieldset', 'r8-kinds'), seg = mk('div', 'seg');
  fs.append(mk('legend', 'sr-only', WORDS.kinds), seg);
  GROUPS.forEach(([id, label]) => {
    const input = mk('input', 'opt-in'), lab = mk('label', 'seg-opt', label);
    input.type = 'radio'; input.name = 'r8-wo-kind'; input.id = 'r8-wo-' + id; input.checked = id === S.group;
    lab.htmlFor = input.id;
    input.addEventListener('change', () => { S.group = id; paintRows(); });
    seg.append(input, lab);
  });
  el.rows = mk('div', 'r8-rows');
  el.confirm = mk('div', 'vt-card r8-card r8-confirm');
  el.confirm.hidden = true;
  el.state = mk('p', 'snote');
  el.state.setAttribute('role', 'status');
  pick.append(fs, el.rows);
  const promise = promiseEl();
  el.promises.push(promise);
  host.append(promise, card, pick, el.confirm, el.state, safeEl(WORDS.handstand));
}
function paintRows() {
  const el = S.el;
  el.rows.replaceChildren(...SESSIONS.filter((x) => x.group === S.group).map((x) => {
    const row = mk('div', 'hp-row'), txt = mk('div', 'hp-txt'), acts = mk('div', 'hp-acts');
    txt.append(mk('b', '', x.name), mk('small', '', x.what));
    const b = S.button(WORDS.start, '', () => ask(x));
    b.setAttribute('aria-label', WORDS.start + ' ' + x.name);
    b.disabled = !!S.run;
    acts.append(b);
    row.append(txt, acts);
    return row;
  }));
}
function buildRun(host) {
  const el = S.el, run = mk('div', 'r8-run'), head = mk('div', 'r8-head');
  el.back = S.button(WORDS.back, 'lift r8-back', () => end('stop'));
  el.title = mk('h3', 'r8-title', '');
  el.voice = S.button(WORDS.voiceOn, 'lift r8-voice', () => { S.voice = !S.voice; paintVoice(); });
  head.append(el.back, el.title, el.voice);
  el.view = mk('div', 'r8-view hud');
  el.view.setAttribute('role', 'status');
  el.mid = mk('div', 'r8-viewmid');
  el.cap = mk('p', 'r8-viewcap', WORDS.cap);
  el.fig = svgEl('svg', 'r8-body', { viewBox: '0 0 1000 1000', preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true', focusable: 'false' });
  el.view.append(el.fig, el.mid, el.cap);
  el.nums = mk('div', 'r8-nums');
  el.nums.setAttribute('role', 'status');
  el.nums.setAttribute('aria-live', 'polite');
  el.meters = mk('div', 'r8-meters');
  el.tip = mk('div', 'r8-tip');
  el.lines = mk('ul', 'r8-lines');
  el.note = mk('p', 'snote');
  el.note.setAttribute('role', 'status');
  const ctl = mk('div', 'r8-ctl');
  el.pause = S.button(WORDS.pause, 'lift', () => (S.run && S.run.paused ? resume() : pause()));
  el.stop = S.button(WORDS.stop, 'lift danger', () => end('stop'));
  ctl.append(el.pause, el.stop);
  const promise = promiseEl();
  el.promises.push(promise);
  run.append(head, el.view, el.nums, el.meters, el.tip, el.lines, el.note, ctl, safeEl(WORDS.handstand), promise);
  run.hidden = true;
  el.run = run;
  host.append(run);
}
function paintVoice() {
  const b = S.el && S.el.voice;
  if (!b) return;
  b.textContent = S.voice ? WORDS.voiceOn : WORDS.voiceOff;
  b.setAttribute('aria-pressed', S.voice ? 'true' : 'false');
  if (!S.voice && window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (_) {} }
}

// ---- drawing a view (the fixed widgets only, laid out for 2-3 m) --------------------------------------------------------
const SAID = new Set([WORDS.hurts]); // lines the pane already shows
const two = (n) => (n < 10 ? '0' : '') + n;
const clockOf = (s) => { const v = Math.max(0, Math.round(Number(s) || 0)); return two(Math.floor(v / 60)) + ':' + two(v % 60); };
function tile(n, word, main) {
  const t = mk('div', 'r8-num' + (main ? ' reps' : '')), b = mk('b', '', n);
  t.append(mk('span', 'k', word || ''), b);
  return t;
}
function meter(w) {
  const n = Math.max(0, Math.min(100, Math.round(Number(w.n) || 0))), box = mk('div', 'r8-tempo'), head = mk('div', 'rhead');
  const bar = mk('div', 'mbar'), fill = mk('i', '');
  head.append(mk('span', 'k nw', String(w.word || '').slice(0, 60)), mk('span', 'k', n + ' %'));
  fill.style.width = n + '%';
  bar.setAttribute('role', 'meter'); bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100');
  bar.setAttribute('aria-valuenow', String(n)); bar.setAttribute('aria-label', String(w.word || 'Score').slice(0, 60));
  bar.append(fill);
  box.append(head, bar);
  return box;
}
function checks(w) {
  const ul = mk('ul', 'r8-checks');
  (Array.isArray(w.items) ? w.items : []).slice(0, 10).forEach((it) => {
    if (!it || typeof it.text !== 'string') return;
    const state = it.ok === true ? 'ok' : it.ok === false ? 'warn' : 'wait', li = mk('li', state);
    li.append(mk('i', 'r8-mark', it.ok === true ? '\u2713' : it.ok === false ? '!' : '\u2026'), mk('span', '', it.text.slice(0, 120)),
      mk('em', '', it.ok === true ? 'Done' : it.ok === false ? 'Not yet' : 'To do'));
    ul.append(li);
  });
  return ul;
}
async function draw(view, seen) {
  const el = S.el, of = (k) => view.filter((w) => w && w.kind === k);
  const nums = [...of('big').map((w) => tile(String(w.n), w.word, true)), ...of('timer').map((w) => tile(clockOf(w.s), w.word, false))];
  nums.slice(1).forEach((t) => t.classList.remove('reps'));
  el.nums.replaceChildren(...nums.slice(0, 3));
  el.meters.replaceChildren(...of('bar').slice(0, 2).map(meter));
  const tip = of('tip')[0], paused = of('paused')[0];
  el.tip.className = tip ? 'r8-tip r8-warn' : 'r8-tip';
  el.tip.setAttribute('role', tip ? 'alert' : 'status');
  el.tip.replaceChildren(...(tip ? [mk('p', '', String(tip.text).slice(0, 120))] : []));
  el.tip.hidden = !tip;
  el.lines.replaceChildren(...of('line').filter((w) => !SAID.has(w.text)).slice(0, 5).map((w) => mk('li', '', String(w.text).slice(0, 120))));
  const mid = [];
  if (paused) mid.push(mk('p', 'r8-lead', String(paused.why || '').slice(0, 120)));
  of('checklist').slice(0, 1).forEach((w) => mid.push(checks(w)));
  const extra = of('pacer').concat(of('targets'));
  if (extra.length) { const box = mk('div', 'r8-extra'); try { (await VIEW()).render(box, extra); } catch (_) {} mid.push(box); }
  const figs = !mid.length && !!seen && !!S.run && !S.run.sess.noLines && L.on && fresh(performance.now()) > 0; // R8.1 I1
  if (!mid.length && !figs) mid.push(mk('p', 'r8-lead', seen ? WORDS.inViewN(seen) : WORDS.nobody));
  el.mid.replaceChildren(...mid);
  el.view.classList.toggle('figs', figs);
  if (figs) el.view.setAttribute('aria-label', WORDS.linesCap + ': ' + WORDS.inViewN(seen));
  else el.view.removeAttribute('aria-label');
  el.cap.textContent = figs ? WORDS.linesCap : WORDS.cap;
  if (figs && !L.frame) L.frame = requestAnimationFrame(drawLines);
}
function speak(text) {
  const ss = window.speechSynthesis;
  if (!S.voice || !ss || typeof window.SpeechSynthesisUtterance !== 'function') return;
  try { ss.cancel(); ss.speak(new window.SpeechSynthesisUtterance(String(text).slice(0, 120))); } catch (_) {}
}

// ---- a session ---------------------------------------------------------------------------------------------------------
function full(on) {
  const panel = document.getElementById('p-camera');
  if (panel) panel.classList.toggle('r8-full', !!on);
  S.el.pick.hidden = !!on;
  S.el.run.hidden = !on;
}
function ask(sess) { // a session that needs a line confirmed shows it first; nothing starts until it is picked
  if (!sess.confirm) { start(sess, null); return; }
  if (sess.confirm === 'routine') { askRoutine(sess); return; }
  const go = (setup) => () => start(sess, setup), b = (label, setup, cls) => S.button(label, cls === undefined ? 'primary' : cls, go(setup));
  if (sess.confirm === 'support') confirmCard(WORDS.support, [b(WORDS.wall, { support: 'wall' }), b(WORDS.spotter, { support: 'spotter' })]);
  else if (sess.confirm === 'stance') confirmCard(WORDS.stance, [b(WORDS.orthodox, { stance: 'orthodox' }), b(WORDS.southpaw, { stance: 'southpaw' }), b(WORDS.skip, null, '')]);
  else if (sess.confirm === 'course') askCourse(sess);
  else confirmCard(WORDS.partner, [S.button(WORDS.partnerYes, 'primary', () => start(sess, { consent: true, consent_at: Math.floor(Date.now() / 1000) }))]);
}
function confirmCard(lead, buttons, extra) {
  const el = S.el, acts = mk('div', 'sacts');
  acts.append(...buttons);
  el.confirm.replaceChildren(mk('p', 'r8-lead', lead), ...(extra || []), acts);
  el.confirm.hidden = false;
}
function askCourse(sess) { // the walk test counts nothing without the course length he types (H: course_m 1..100)
  const i = mk('input', 'minput'), note = mk('p', 'snote');
  i.type = 'number'; i.inputMode = 'decimal'; i.min = String(COURSE_MIN); i.max = String(COURSE_MAX); i.step = '0.5';
  i.autocomplete = 'off';
  note.setAttribute('role', 'status');
  const goWalk = () => {
    const n = Number(i.value);
    if (!(Number.isFinite(n) && n >= COURSE_MIN && n <= COURSE_MAX)) { note.textContent = WORDS.courseBad; i.focus(); return; }
    start(sess, { course_m: Math.round(n * 10) / 10 });
  };
  i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') goWalk(); });
  confirmCard(WORDS.course, [S.button(WORDS.courseStart, 'primary', goWalk)], [S.field(WORDS.courseField, i), note]);
}
function chunked(rows) { return Array.from({ length: Math.ceil(rows.length / CHUNK) }, (_, k) => rows.slice(k * CHUNK, (k + 1) * CHUNK)); }
async function askRoutine(sess) { // tai-chi and dance follow his recording (F: setup.chunks), or record it (setup.record)
  const el = S.el, n = Number(sess.routine.split('-').pop()) || 1, kind = sess.uses[0];
  if (!S.signedIn()) return;
  confirmCard(WORDS.routineLooking, []);
  let got = null;
  try { got = await api(P + '/routines/' + sess.routine); } catch (e) {
    if (!(e && e.status === 404)) { el.confirm.hidden = true; el.state.textContent = failWords(e); return; }
  }
  const rows = got && got.routine && Array.isArray(got.routine.angles) ? got.routine.angles : null;
  const record = S.button(rows ? WORDS.record : WORDS.recordFirst, rows ? '' : 'primary', () => start(sess, { routine: n, record: true }));
  const follow = rows ? [S.button(WORDS.follow, 'primary', () => start(sess, { routine: n, chunks: chunked(rows) }))] : [];
  confirmCard((rows ? WORDS.routineHave : WORDS.routineNone)[kind], [...follow, record], [mk('p', 'snote', WORDS.routineLimit)]);
}
async function prepare(uses) { // the camera (inside the tap), the registry, the switches, the modules
  const c = cam(), V = vis();
  if (!c || !V) throw new Error(WORDS.failed);
  const started = c.start({ facing: 'user' }); // the tripod phone faces him: its screen is his scoreboard
  const [listing, view] = await Promise.all([loadListing(), started]);
  const us = uses.map((id) => listing.get(id));
  if (us.some((u) => !u || u.source !== 'phone' || u.spot === 'desk')) throw new Error(WORDS.failed);
  if (!(await spotsAllow())) { c.stop('panel'); const e = new Error(WORDS.switchedOff); e.quiet = true; throw e; }
  await GEOM();
  await Promise.all(uses.map((id) => USES[id]()));
  const tasks = [...new Set(us.flatMap((u) => (Array.isArray(u.tasks) ? u.tasks : [])))];
  return { view, tasks, rate: Math.max(...us.map((u) => Number(u.rate) || 1)) };
}
function failWords(e) {
  return e && (e.name === 'NotAllowedError' || e.name === 'SecurityError') ? WORDS.blocked : (e && e.message) || WORDS.failed;
}
async function start(sess, setup) { // only from a tap; `setup` is the session's choices (plain data) or null
  const el = S.el;
  if (S.run || !S.signedIn()) return;
  el.confirm.hidden = true;
  if (S.target && S.target.kind === 'person') { el.state.textContent = WORDS.onePerson; return; }
  el.state.textContent = WORDS.starting;
  const gen = ++S.gen;
  try {
    const got = await prepare(sess.uses);
    if (gen !== S.gen || !cam().live()) throw new Error('The camera was stopped.');
    sess.uses.forEach((id) => vis().reset(id));
    vis().reset(LINES_ID);
    S.run = { sess, setup: setup && typeof setup === 'object' ? Object.freeze(Object.assign({}, setup)) : null, sid: sessionId(),
      view: got.view, tasks: got.tasks, rate: got.rate, look: null, tick: 0, spots: 0, paused: false, ended: false,
      said: { n: -1, tip: '' }, anchor: null, anchorTick: 0, anchorPrompts: 0, anchorOut: false, nobodySince: 0, routine: '' };
    el.title.textContent = sess.name;
    el.state.textContent = '';
    full(true);
    paintRows();
    battery();
    if (sess.anchor) { askAnchor(S.run); return; }
    if (sess.marks) { askMarks(S.run); return; }
    look(S.run);
  } catch (e) {
    const c = cam(); if (c && c.live()) c.stop('panel');
    el.state.textContent = failWords(e);
  }
}
function look(run) { // the driver, from the camera that a tap started; the session's setup rides on every Result
  const V = vis(), lines = !run.sess.noLines;
  if (lines) { linesUse(); L.on = true; L.mirror = !cam() || typeof cam().facing !== 'function' || cam().facing() === 'user'; }
  const target = run.sess.own ? { kind: 'all' } : (S.target || { kind: 'all' }); // the partner stretch tells him apart itself
  const opts = { uses: run.sess.uses.concat(lines ? [LINES_ID] : []), rate: run.rate, target, onError: (e) => halted(run, e) };
  if (run.setup) opts.setup = run.setup;
  run.look = V.live(run.tasks, opts);
  run.tick = setInterval(() => paint(run), TICK_MS);
  run.spots = setInterval(async () => { if (!(await spotsAllow())) end('switched'); }, SPOTS_MS);
  if (run.anchor) run.anchorTick = setInterval(() => watchAnchor(run), ANCHOR_MS);
  paint(run);
}
function askAnchor(run) { // the one moment the picture shows: he taps the band's anchor
  const el = S.el, video = run.view && run.view.video;
  if (!video) { look(run); return; }
  video.className = 'cam-view r8-anchorpick';
  el.mid.replaceChildren(mk('p', 'r8-lead', WORDS.anchorAsk), video);
  const onTap = (ev) => {
    const at = tapAt(video, ev);
    if (!at) return; // a tap on a bar beside the picture: wait for one on it
    video.removeEventListener('click', onTap);
    run.anchor = at;
    run.anchorPrint = grab(run.view, run.anchor);
    video.remove();
    el.note.textContent = WORDS.anchorSet;
    if (S.run === run && !run.ended) look(run);
  };
  video.addEventListener('click', onTap);
}
function askMarks(run) { // agility (G): he taps 2 to 12 marks on the picture; they go to the use case as setup.marks
  const el = S.el, video = run.view && run.view.video;
  if (!video) { look(run); return; }
  const marks = [], box = mk('div', 'r8-markpick'), dots = mk('div', 'r8-dots'), count = mk('p', 'snote');
  const acts = mk('div', 'sacts'), undo = S.button(WORDS.marksUndo, '', () => { marks.pop(); paintMarks(); });
  count.setAttribute('role', 'status');
  const done = S.button(WORDS.marksDone, 'primary', () => {
    if (marks.length < MARKS_MIN || S.run !== run || run.ended) return;
    run.setup = Object.freeze(Object.assign({}, run.setup || {}, { marks: Object.freeze(marks.map((m) => Object.freeze(Object.assign({}, m)))) }));
    box.remove();
    look(run);
  });
  const paintMarks = () => {
    const r = video.getBoundingClientRect(), vw = video.videoWidth || r.width || 1, vh = video.videoHeight || r.height || 1;
    const k = Math.min((r.width || 1) / vw, (r.height || 1) / vh), w = vw * k, h = vh * k;
    dots.replaceChildren(...marks.map((m, i) => { const d = mk('span', 'r8-dot', String(i + 1)); d.style.left = Math.round((r.width - w) / 2 + m.x * w) + 'px'; d.style.top = Math.round((r.height - h) / 2 + m.y * h) + 'px'; return d; }));
    count.textContent = WORDS.marksN(marks.length);
    done.disabled = marks.length < MARKS_MIN;
    undo.disabled = !marks.length;
  };
  video.className = 'cam-view r8-anchorpick';
  video.addEventListener('click', (ev) => { const at = tapAt(video, ev); if (at && marks.length < MARKS_MAX) { marks.push(at); paintMarks(); } });
  acts.append(undo, done);
  const pic = mk('div', 'r8-markpic');
  pic.append(video, dots);
  box.append(mk('p', 'r8-lead', WORDS.marksAsk), pic, count, acts);
  el.mid.replaceChildren(box);
  paintMarks();
}
function watchAnchor(run) {
  if (S.run !== run || run.paused || !run.anchorPrint) return;
  const now = grab(run.view, run.anchor), out = !now || anchorMoved(run.anchorPrint, now);
  if (out && !run.anchorOut) { run.anchorPrompts += 1; speak(WORDS.anchorGone); }
  run.anchorOut = out;
}
function paint(run) {
  if (S.run !== run || run.ended || run.paused) return;
  const V = vis(), view = [];
  run.sess.uses.forEach((id, k) => { const t = V.tally(id); (t && Array.isArray(t.view) ? t.view : []).forEach((w) => { if (k === 0 || ['tip', 'line', 'paused'].includes(w.kind)) view.push(w); }); });
  if (run.anchorOut) view.unshift({ kind: 'paused', why: WORDS.anchorGone });
  const seen = run.look ? run.look.tracks().length : 0;
  draw(view, seen);
  const big = view.find((w) => w.kind === 'big'), tip = view.find((w) => w.kind === 'tip');
  if (big && Number.isFinite(big.n) && big.n > run.said.n && run.said.n >= 0) speak(String(big.n));
  if (big && Number.isFinite(big.n)) run.said.n = big.n;
  if (tip && tip.text !== run.said.tip) speak(tip.text);
  run.said.tip = tip ? tip.text : '';
}
function quiet(run) {
  clearInterval(run.tick); clearInterval(run.spots); clearInterval(run.anchorTick);
  if (run.look) run.look.end();
  run.look = null;
  linesOff(); // the body lines' points go with the look
}
function halted(run, e) { // the camera stopped under the look (cameras off, the page hidden): paused, counts kept
  if (S.run !== run || run.ended) return;
  quiet(run);
  run.paused = true;
  paintPaused(e && e.message && e.message !== 'The camera was stopped.' ? failWords(e) : '');
}
function pause() {
  const run = S.run;
  if (!run || run.paused) return;
  quiet(run);
  run.paused = true;
  const c = cam(); if (c && c.live()) c.stop('panel');
  paintPaused('');
}
function paintPaused(why) {
  const el = S.el;
  el.mid.replaceChildren(...WORDS.paused.map((t, i) => mk('p', i ? '' : 'r8-lead', t)));
  el.note.textContent = why;
  el.pause.textContent = WORDS.resume;
  el.pause.classList.add('primary');
}
async function resume() { // a tap again: the camera, then the look on the same states (the counts go on)
  const run = S.run, c = cam();
  if (!run || !run.paused || !c) return;
  try {
    run.view = await c.start({ facing: 'user' });
    if (!(await spotsAllow())) { c.stop('panel'); S.el.note.textContent = WORDS.switchedOff; return; }
  } catch (e) { S.el.note.textContent = failWords(e); return; }
  run.paused = false;
  S.el.pause.textContent = WORDS.pause;
  S.el.pause.classList.remove('primary');
  S.el.note.textContent = '';
  look(run);
}
/** A recorded routine (F's `tally.record`: {rid, kind, chunks}) as the store's body {kind, angles}, or null. Pure. */
export function routineBody(rec) {
  if (!rec || typeof rec !== 'object' || !ROUTINE_ID.test(String(rec.rid)) || !ROUTINE_KINDS.includes(rec.kind)) return null;
  if (!String(rec.rid).startsWith(rec.kind + '-') || !Array.isArray(rec.chunks)) return null;
  const angles = rec.chunks.flat();
  return angles.length && angles.every((row) => Array.isArray(row)) ? { rid: rec.rid, body: { kind: rec.kind, angles } } : null;
}
async function keepRoutine(run, rec) { // his routine: PUT to coach_routines (joint angles only), never posted as a result
  const got = routineBody(rec);
  if (!got || run.routine) return false;
  run.routine = 'failed';
  try { await api(P + '/routines/' + got.rid, { method: 'PUT', body: got.body }); run.routine = 'kept'; return true; } catch (_) { return false; }
}
async function keep(run) { // each body's tally of each use case: counts, times and scores only
  const V = vis();
  let kept = 0;
  for (const id of run.sess.uses) {
    const bodies = V.tracks(id), list = bodies.length ? bodies : [{ track: 0, who: 'me' }];
    for (const b of list.slice(0, 4)) {
      const t = V.tally(id, bodies.length ? b.track : undefined);
      if (!t || !t.tally) continue;
      if (t.tally.record) { if (await keepRoutine(run, t.tally.record)) kept += 1; continue; }
      const tally = id === 'band' ? Object.assign({}, t.tally, { prompts: Math.min(500, (t.tally.prompts || 0) + run.anchorPrompts) }) : t.tally;
      const who = run.sess.own ? 'me' : t.who || b.who || ''; // the partner stretch keeps only his own (H), as `me`
      try { await api(P + '/results', { method: 'POST', body: { use: id, session: run.sid, track: b.track, who, tally } }); kept += 1; } catch (_) { /* dropped or unreachable: never repaired */ }
    }
  }
  return kept;
}
async function end(why) {
  const run = S.run, el = S.el;
  if (!run || run.ended) return;
  run.ended = true;
  quiet(run);
  const kept = await keep(run);
  run.sess.uses.forEach((id) => vis().reset(id));
  vis().reset(LINES_ID);
  const c = cam(); if (c && c.live()) c.stop('panel');
  if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (_) {} }
  S.run = null;
  full(false);
  el.pause.textContent = WORDS.pause; el.pause.classList.remove('primary'); el.note.textContent = '';
  const ended = run.routine === 'kept' ? WORDS.routineSaved : run.routine === 'failed' ? WORDS.routineFailed : kept ? WORDS.stopped : WORDS.stoppedNothing;
  el.state.textContent = why === 'switched' ? WORDS.switchedOff : ended;
  paintRows();
}
async function battery() {
  if (typeof navigator.getBattery !== 'function') return;
  try {
    const b = await navigator.getBattery();
    if (S.run && !b.charging && b.level <= LOW_BATTERY) S.el.note.textContent = WORDS.battery(Math.round(b.level * 100));
  } catch (_) { /* no battery reading: nothing to say */ }
}

// ---- the two setup checks: a short look with space-check, nothing kept ------------------------------------------------
async function check(which) {
  const el = S.el, out = (which === 'place' ? el.place : el.clear).out;
  if (S.run || !S.signedIn()) return;
  out.textContent = WORDS.looking;
  const gen = ++S.gen;
  let live = null;
  try {
    const got = await prepare(['space-check']);
    vis().reset('space-check');
    live = vis().live(got.tasks, { uses: ['space-check'], rate: got.rate, target: { kind: 'all' }, onError: () => {} });
    await new Promise((r) => setTimeout(r, CHECK_S * 1000));
    if (gen !== S.gen) return;
    const t = vis().tally('space-check'), lines = (t && t.view ? t.view : []).map((w) => w.text || '');
    const placed = live.tracks().length > 0 && !lines.some((x) => x.startsWith('Stand where'));
    out.textContent = which === 'place' ? (placed ? WORDS.inView : WORDS.notInView)
      : (lines.find((x) => x.startsWith('Clear') || x.startsWith('Not clear')) || WORDS.notInView);
  } catch (e) {
    out.textContent = failWords(e);
  } finally {
    if (live) live.end();
    const V = vis(); if (V) V.reset('space-check');
    const c = cam(); if (c && c.live() && !S.run) c.stop('panel');
  }
}

// ---- the mode ----------------------------------------------------------------------------------------------------------
function mount(host, P_) {
  S.mk = P_.mk; S.button = P_.button; S.field = P_.field; S.signedIn = P_.signedIn;
  S.el = { promises: [] };
  const root = mk('div', 'r8-wo'), pick = mk('div', 'r8-picker');
  pick.append(mk('p', 'sfine', WORDS.intro));
  S.el.pick = pick;
  buildPicker(pick);
  root.append(pick);
  buildRun(root);
  host.replaceChildren(root);
  paintRows();
  paintVoice();
  paintPromise();
  document.addEventListener('jarvis:ready', loadTarget);
  if (S.signedIn()) loadTarget();
}
function stop() { if (S.run) end('stop'); else { S.gen += 1; } }
function join() { const modes = window.JarvisCameraModes; return !!(modes && modes.register('workout', { mount, stop })); }
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
export { USES, VIEW, GEOM, SESSIONS, LINES_ID };
