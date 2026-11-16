// src/jarvis/api/static/console-wardrobe-scan.js -- R13 Part D (docs/plans/r13-wardrobe.md D5, D7, D9, OPS-01): Camera ->
// Wardrobe, the SECOND named pixel panel (tests/test_r13_seams.py PANELS), mounted into the camera panel's fourth
// sub-tab through window.JarvisCameraModes.register('wardrobe', {mount, stop}). The phone checkpoints:
//   Add pieces    a photo (or a chosen picture) split into a box per piece laid apart; for each: his QR label if
//                 one is read, "seen before?" candidates (the fingerprint is computed and compared ON THIS PHONE,
//                 at most 3, his tap decides), a kind chip and the suggested colour; then, only for a saved piece
//                 that is not private, "Save this photo", "Remember how it looks" and the optional AI tag
//   To laundry    the pieces read or tapped; "Put in laundry" sends deposits (ids only); Cancel sends nothing
//   Back clean    the place it goes to, dry or needs pressing; "Back clean" sends the returns (ids only)
//   Find          what a scan or a typed name finds in his own list: state and place
//   Read a label  size, fabric and care words parsed from the label's text, each UNVERIFIED until he confirms
// The check (D9): the person and face tasks run on THE bitmap the crop is cut from; one hit, or a check that is not
// installed, and that photo keeps and sends nothing (no photo, no fingerprint, no AI tag). A QR read or a match he
// taps sends only ids, so it still makes its event. A crop is at most 512 px, JPEG 0.8, made in memory and handed
// to the one door (door.wardrobe, door.tag); a private piece never gets either, nor a fingerprint.
// Unsent scans wait in this page's memory only ("Not sent yet: keep this page open"); closing the page drops them.
// Rules (the camera panel's): no fetch, XHR, sendBeacon, WebSocket or any storage; M.api only to /v1/wardrobe and
// /v1/laundry paths and never with picture bytes; textContent only; nothing asked before sign-in or a press; ASCII.
const M = window.JarvisMobile;
const Vis = () => window.JarvisVision || null;
const Cam = () => window.JarvisCamera || null;
const Door = () => (M && M.parts && M.parts.send) || null;
const FLOWS = [['add', 'Add pieces'], ['laundry', 'To laundry'], ['clean', 'Back clean'], ['find', 'Find'], ['label', 'Read a label']];
const KINDS = [['shirt', 'Shirt'], ['t_shirt', 'T-shirt'], ['trousers', 'Trousers'], ['jeans', 'Jeans'], ['vest', 'Vest'],
  ['underpants', 'Underpants'], ['sock', 'Sock'], ['dress_shoe', 'Shoe'], ['sneaker', 'Sneaker'], ['sandal', 'Sandal'],
  ['belt', 'Belt'], ['watch', 'Watch'], ['kurta', 'Kurta'], ['blazer', 'Blazer'], ['jacket', 'Jacket'],
  ['rainwear', 'Rainwear'], ['unknown', 'Unknown']];
const PHOTO_SIDE = 512, JPEG_Q = 0.8, LOOK_SIDE = 2000, SPLIT_SIDE = 64, MODEL = 'mnv2-int8-1';
const INTRO = 'JARVIS looks on this phone. A photo of a piece is kept only when you press Save, cropped to the piece, after a check for a person or a face that can miss: look before you save.';
const PERSON = 'This picture shows a person. Lay the piece on a surface or hang it, and take the photo again.';
const NO_CHECK = 'Saving a photo is off on this phone: the check for a person or a face is not installed. Taps and scans still work.';
const CHECKING = 'Checking\u2026';
const UNSENT = 'Not sent yet: keep this page open.';
const FOREIGN = 'A code here is not a JARVIS label, so it was ignored.';
const PRIVATE_NOTE = 'A private piece keeps no photo and no fingerprint.';
const WHOLE = 'JARVIS couldn\u2019t find the piece\u2019s edges: lay it on a plain surface of another colour so the photo can be cropped to it.';
const WHOLE_MAX = 0.85; // a box over this share of the photo is not a crop of a piece (M2)
const TWINS_NOTE = 'Identical copies: read its label or tap which one.';
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const SIGN_IN = 'Sign in first.';
const SAVE_WORDS = 'Save this photo with the piece (sealed; only you)';
// M3: one photo (~750 tokens in, ~120 out) costs about Rs 0.01 with the cheapest seeing brain and 0.51 with the dearest
// (llm/pricing.py at 95.24 a dollar; tests/test_r13_d_scan.py recomputes both). The view's own `tag_estimate_inr`
// (the brain that would answer, A's at I1) is said instead whenever it is there.
const TAG_MOST = 0.51, TAG_RANGE = '\u20b90.01\u2013\u20b90.51, depending on the brain';
const tagWords = (inr) => 'Send this photo to the AI to tag it (about ' + (inr ? '\u20b9' + inr.toFixed(2) : TAG_RANGE) + ')';
const noAi = () => !!(window.JarvisBrainMode && window.JarvisBrainMode.get() === 'none');
const BAND_WORDS = { likely: ' (likely this one)', maybe: ' (maybe)', weak: ' (a weak match)' }; // none: no words (M5)
const banded = (c) => BAND_WORDS[c.band] || '';

/*SCAN-PURE-BEGIN*/
// Plain arithmetic only: tests/test_r13_d_scan.py runs this very text in Node.
const BOXES = 6, FG = 60;
function boxesOf(px, w, h) { // pieces laid apart on a plain surface: what differs from the border's colour, in parts
  const at = (x, y) => (y * w + x) * 4, edge = [[], [], []];
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) if (x < 2 || y < 2 || x >= w - 2 || y >= h - 2) [0, 1, 2].forEach((k) => edge[k].push(px[at(x, y) + k]));
  const bg = edge.map((c) => c.sort((a, b) => a - b)[c.length >> 1] || 0);
  const fg = new Uint8Array(w * h), seen = new Uint8Array(w * h), found = [];
  for (let i = 0; i < w * h; i += 1) fg[i] = Math.abs(px[i * 4] - bg[0]) + Math.abs(px[i * 4 + 1] - bg[1]) + Math.abs(px[i * 4 + 2] - bg[2]) > FG ? 1 : 0;
  const near = fg.slice(); // close gaps of one cell (a light stripe, a fold): one piece stays one box
  for (let i = 0; i < w * h; i += 1) if (!fg[i]) { const x = i % w; near[i] = (x > 0 && fg[i - 1]) || (x < w - 1 && fg[i + 1]) || fg[i - w] || fg[i + w] ? 1 : 0; }
  for (let s = 0; s < w * h; s += 1) {
    if (!near[s] || seen[s]) continue;
    const stack = [s]; let n = 0, x0 = w, y0 = h, x1 = 0, y1 = 0;
    seen[s] = 1;
    while (stack.length) {
      const i = stack.pop(), x = i % w, y = (i - x) / w;
      n += 1; x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      [[x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]].forEach(([u, v]) => { const j = v * w + u; if (u >= 0 && v >= 0 && u < w && v < h && near[j] && !seen[j]) { seen[j] = 1; stack.push(j); } });
    }
    if (n >= Math.max(4, 0.015 * w * h)) found.push({ n, x0, y0, x1, y1 });
  }
  const box = (c) => { const x = Math.max(0, c.x0 - 1) / w, y = Math.max(0, c.y0 - 1) / h; return { x, y, w: Math.min(1, (c.x1 + 2) / w) - x, h: Math.min(1, (c.y1 + 2) / h) - y }; };
  const out = found.sort((a, b) => b.n - a.n).slice(0, BOXES).sort((a, b) => a.x0 - b.x0).map(box);
  return out.length ? out : [{ x: 0, y: 0, w: 1, h: 1 }];
}
/*SCAN-PURE-END*/

const S = { host: null, P: null, flow: 'add', view: null, prints: null, live: null, codes: null, photo: null, seq: 0,
  gate: null, cards: [], found: new Map(), more: 0, moreKind: 'tops', dry: true, place: '', queue: [], device: '', busy: false,
  query: '', skip: new Set() }; // skip: ids sent, cancelled or removed while this camera stays on (M1)
const randomId = (n) => { const a = new Uint8Array(n); crypto.getRandomValues(a); return Array.from(a, (b) => 'abcdefghijklmnopqrstuvwxyz234567'[b % 32]).join(''); };
const say = (el, text, kind) => (S.P ? S.P.say(el, text, kind) : null);
const mk = (tag, cls, text) => S.P.mk(tag, cls, text);
const btn = (text, cls, fn) => S.P.button(text, cls, fn);
const signedIn = () => !!(S.P && S.P.signedIn());
const pieceOf = (id) => ((S.view && Array.isArray(S.view.pieces) ? S.view.pieces : []).find((p) => p.id === id) || null);
const privateType = (t) => !!W && W.PRIVATE_TYPES.includes(t);
function nameOf(id) { // his own words, on his own console; a private piece is said as one
  const p = pieceOf(id);
  if (!p) return 'A piece';
  if (p.private) { const l = ((S.view && S.view.labels) || []).find((x) => x.piece === id); return 'A private basic' + (l ? ' (No. ' + l.number + ')' : ''); }
  return (p.label || (p.colour ? p.colour.replace(/_/g, ' ') + ' ' : '') + p.type.replace(/_/g, ' ')).slice(0, 60);
}
function failed(e) {
  if (e && e.status === 401) return SIGN_IN;
  if (e && typeof e.status === 'number') return e.status >= 500 ? 'JARVIS couldn\u2019t do that just now. Try again in a moment.' : String(e.message || '').slice(0, 200);
  if (e && e.message === 'not installed') return 'Not installed on this server yet.';
  return navigator.onLine === false || (e && e.name === 'TypeError') ? OFFLINE : 'That didn\u2019t work. Please try again.';
}
const pressed = (b, on) => { b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.classList.toggle('primary', on); }; // the existing look
const isNetwork = (e) => !!e && typeof e.status !== 'number' && (navigator.onLine === false || e.name === 'TypeError');
// console-wardrobe-words.js (REVIEW-D-1 split): imported on the first press that needs it (Start the camera, Choose a
// photo), so the page's start never waits for it; a failed import is not kept (the next press tries again)
let W = null, wordsLoad = null;
const words = () => {
  if (!wordsLoad) wordsLoad = import('./console-wardrobe-words.js').then((m) => { W = m; return m; }, (e) => { wordsLoad = null; throw e; });
  return wordsLoad;
};
const NO_PART = 'This part couldn\u2019t load. Reload the page to try again.';

// ---- the frame of the mode ---------------------------------------------------------------------------------------------
const UI = {};
function mount(host, P) {
  S.host = host; S.P = P; S.device = 'ph-' + randomId(12);
  UI.flows = mk('div', 'sacts wd-flows');
  UI.flows.setAttribute('role', 'group');
  UI.flows.setAttribute('aria-label', 'What to do');
  UI.flowBtns = FLOWS.map(([id, label]) => { const b = btn(label, '', () => choose(id)); b.dataset.flow = id; UI.flows.append(b); return b; });
  UI.stage = mk('div', 'cam-stage');
  UI.acts = mk('div', 'sacts cam-acts');
  UI.state = mk('p', 'snote');
  UI.state.setAttribute('role', 'status'); UI.state.setAttribute('aria-live', 'polite');
  UI.body = mk('div', 'wd-scan');
  UI.unsent = mk('div', 'sacts'); UI.unsent.hidden = true;
  UI.sent = mk('p', 'sfine');
  host.replaceChildren(mk('p', 'sfine', INTRO), UI.flows, UI.stage, UI.acts, UI.state, UI.body, UI.unsent, UI.sent);
  choose('add');
}
function choose(id) {
  const next = FLOWS.some(([f]) => f === id) ? id : 'add';
  if (S.live && next !== S.flow) stop(); // M1: another step ends the camera and the label reader
  S.flow = next;
  UI.flowBtns.forEach((b) => pressed(b, b.dataset.flow === S.flow));
  clearList();
  paint();
}
function clearScan() {
  S.seq += 1;
  if (S.photo) { S.photo.width = 0; S.photo.height = 0; }
  S.photo = null; S.gate = null; S.cards = []; S.found = new Map(); S.more = 0; S.foreign = false;
  UI.stage.replaceChildren();
  say(UI.state, '');
}
function clearList() { // M1: while the camera is on, only the list goes; its view and its reader stay
  if (!S.live) { clearScan(); return; }
  S.found.forEach((_, id) => S.skip.add(id)); // sent, cancelled or left: not offered again by this camera
  S.cards = []; S.found = new Map(); S.more = 0; S.foreign = false;
  say(UI.state, '');
}
function paint() { paintActs(); paintBody(); paintUnsent(); }
function paintActs() {
  const c = Cam(), live = !!(c && c.live() && S.live), acts = [];
  if (live) acts.push(btn('Take a photo', 'primary', takePhoto), btn('Stop', '', () => { stop(); say(UI.state, 'The camera is off.'); }));
  else {
    acts.push(btn('Choose a photo', '', choosePhoto));
    acts.push(c && c.locked() ? btn('Allow the camera', '', () => { if (!c.unlock('panel')) say(UI.state, 'Tap Allow to switch the camera on.'); paintActs(); }) : btn('Start the camera', 'primary', startLive));
    if (S.photo || S.found.size) acts.push(btn('Clear', '', () => { clearScan(); paint(); }));
  }
  UI.acts.replaceChildren(...acts);
  const d = Door();
  UI.sent.textContent = d ? d.line() : '';
}

// ---- the camera: a tap starts it, Stop and leaving the tab end it --------------------------------------------------------
async function startLive() {
  const c = Cam();
  if (!c) return;
  clearScan();
  const mine = S.seq, ready = words().catch(() => null);
  let view = null;
  try { view = await c.start({}); } catch (e) { say(UI.state, String((e && e.message) || failed(e)).slice(0, 200), 'bad'); paintActs(); return; }
  if (mine !== S.seq) { c.stop('panel'); return; }
  if (!(await ready)) { c.stop('panel'); say(UI.state, NO_PART, 'bad'); paintActs(); return; }
  S.live = view;
  if (signedIn()) { try { await loadView(); } catch (e) { say(UI.state, failed(e), 'bad'); } } // his labels, before the first read
  if (mine !== S.seq) return;
  view.video.className = 'cam-view';
  UI.stage.replaceChildren(view.video);
  say(UI.state, 'The camera is on. Nothing leaves this phone while you look.');
  if (S.flow !== 'add' && S.flow !== 'label' && Vis()) S.codes = Vis().stream('code', { frame: () => S.live && S.live.frame(), onError: () => { S.codes = null; } }, (r) => readCodes(r));
  paintActs();
}
function stop() { // Stop, another tab, the panel hidden: the camera ends before the next frame; unsent scans stay
  S.seq += 1;
  if (S.codes) { S.codes.stop(); S.codes = null; }
  S.live = null; S.skip = new Set();
  const c = Cam();
  if (c) c.stop('panel');
  if (S.photo) { S.photo.width = 0; S.photo.height = 0; S.photo = null; S.gate = null; }
  if (UI.stage) UI.stage.replaceChildren();
  if (UI.acts) paintActs();
}
function takePhoto() {
  const f = S.live && S.live.frame();
  if (!f) return;
  const cv = mk('canvas', 'cam-view');
  cv.width = f.width; cv.height = f.height;
  cv.getContext('2d').drawImage(f, 0, 0);
  stop();
  analyse(cv);
}
async function choosePhoto() {
  const c = Cam();
  if (!c) return;
  stop();
  const ready = words().catch(() => null); // started now, awaited after the picker: the tap opens the picker
  let file = null;
  try { file = await c.photo(); } catch (e) { say(UI.state, failed(e), 'bad'); return; }
  if (file && !(await ready)) { say(UI.state, NO_PART, 'bad'); return; }
  if (!file || !/^image\//.test(file.type || '')) { if (file) say(UI.state, 'That is not a picture. Choose a JPEG or PNG photo.', 'bad'); return; }
  let bmp = null;
  try { bmp = await createImageBitmap(file); } catch (_) { say(UI.state, 'This picture can\u2019t be read here. Try a JPEG or PNG.', 'bad'); return; }
  const k = Math.min(1, LOOK_SIDE / Math.max(bmp.width, bmp.height)), cv = mk('canvas', 'cam-view');
  cv.width = Math.max(1, Math.round(bmp.width * k)); cv.height = Math.max(1, Math.round(bmp.height * k));
  cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height); // the same redraw and checks as a camera photo
  bmp.close();
  analyse(cv);
}

// ---- one photo: the checks and the crops use THIS bitmap ------------------------------------------------------------------
async function run(task, source, opts) { const V = Vis(); if (!V) throw new Error('not installed'); return V.run(task, source, opts); }
async function check(cv) { // {checked, refused}: both tasks ran on this bitmap and found nobody
  try {
    const [person, face] = [await run('person', cv), await run('face', cv)];
    const ran = person.ok && face.ok;
    return { checked: ran, refused: !ran || person.data.found || face.data.found };
  } catch (_) { return { checked: false, refused: true }; }
}
async function cropChecks(c) { // H2: the crop that would leave, whole and as four overlapping two-thirds (a small face, near full size)
  const w = c.width, h = c.height, tw = Math.ceil(w * 2 / 3), th = Math.ceil(h * 2 / 3), parts = [c];
  [[0, 0], [w - tw, 0], [0, h - th], [w - tw, h - th]].forEach(([x, y]) => { const t = document.createElement('canvas'); t.width = tw; t.height = th; t.getContext('2d').drawImage(c, x, y, tw, th, 0, 0, tw, th); parts.push(t); });
  let gate = { checked: true, refused: false };
  for (const t of parts) { if (!gate.refused) gate = await check(t); if (t !== c) { t.width = 0; t.height = 0; } }
  return gate;
}
async function cropOk(card) { // H2: the bytes that leave are the bytes that were checked (a small face can be large here)
  if (!card.cropCheck) { say(UI.state, CHECKING); card.cropCheck = cropChecks(card.crop); }
  card.cropGate = await card.cropCheck;
  return card.cropGate.checked && !card.cropGate.refused;
}
function crop(cv, b, side) { // the box, in memory, at most `side` px on its long side
  const sx = Math.floor(b.x * cv.width), sy = Math.floor(b.y * cv.height);
  const sw = Math.max(1, Math.round(b.w * cv.width)), sh = Math.max(1, Math.round(b.h * cv.height));
  const k = Math.min(1, side / Math.max(sw, sh)), c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(sw * k)); c.height = Math.max(1, Math.round(sh * k));
  c.getContext('2d').drawImage(cv, sx, sy, sw, sh, 0, 0, c.width, c.height);
  return c;
}
function split(cv) {
  const k = SPLIT_SIDE / Math.max(cv.width, cv.height), w = Math.max(1, Math.round(cv.width * k)), h = Math.max(1, Math.round(cv.height * k));
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const x = c.getContext('2d', { willReadFrequently: true });
  x.drawImage(cv, 0, 0, w, h);
  const boxes = boxesOf(x.getImageData(0, 0, w, h).data, w, h);
  c.width = 0; c.height = 0;
  return boxes;
}
async function analyse(cv) {
  S.seq += 1;
  const mine = S.seq;
  S.photo = cv; S.gate = null; S.cards = [];
  cv.setAttribute('role', 'img');
  cv.setAttribute('aria-label', 'The photo, on this phone only');
  UI.stage.replaceChildren(cv);
  if (!signedIn()) { say(UI.state, SIGN_IN, 'bad'); return; }
  say(UI.state, CHECKING);
  try {
    await loadView();
    if (S.flow === 'label') { await readLabel(cv, mine); return; }
    readCodes(await run('code', cv).catch(() => null));
    if (S.flow === 'add') S.gate = await check(cv);
    if (mine !== S.seq) return;
    const boxes = S.flow === 'find' || S.flow === 'add' || !S.found.size ? split(cv) : [];
    for (const b of boxes) S.cards.push(await cardFor(cv, b));
    if (mine !== S.seq) return;
    const refused = S.gate && S.gate.refused;
    say(UI.state, refused ? (S.gate.checked ? PERSON : NO_CHECK) : S.foreign ? FOREIGN : '', refused ? 'bad' : '');
  } catch (e) { if (mine === S.seq) say(UI.state, failed(e), 'bad'); }
  paint();
}
function readCodes(r) { // his labels become ids; anything else is only counted, never kept, sent or shown
  if (!r || !r.ok) return;
  let foreign = 0;
  r.data.codes.forEach((c) => {
    const id = c.format === 'qr_code' ? W.labelPiece(c.value, S.view && S.view.labels) : null;
    if (id) { if (!S.found.has(id) && !(S.live && S.skip.has(id))) S.found.set(id, { how: 'qr', score: null, at: new Date().toISOString() }); } else foreign += 1;
  });
  if (foreign) { S.foreign = true; say(UI.state, FOREIGN); }
  if (UI.body) paintBody();
}
async function cardFor(cv, b) {
  const piece = crop(cv, b, PHOTO_SIDE), card = { box: b, crop: piece, v: null, cands: { top: [], twins: false }, colour: null, piece: null, kind: '', private: null,
    client: 'wd' + randomId(14), adding: false, // M6: one client id a card: a second press or a retry is the same piece at A
    whole: b.w * b.h > WHOLE_MAX }; // M2: no edges found: taps and matches only, nothing kept or sent
  try {
    const e = await run('embed', piece);
    if (e.ok) { card.v = e.data.v; card.cands = W.candidates(W.unb64(e.data.v), await printsFor(e.data.model), (id) => (pieceOf(id) || {}).type); }
  } catch (_) { /* no fingerprint here: the card offers kinds and taps only */ }
  if (S.flow === 'add') { try { const c = await run('colour', piece); if (c.ok) card.colour = c.data; } catch (_) {} }
  return card; // a label read is offered first, never chosen for him: his tap decides
}

// ---- the server: his list and his fingerprints (after sign-in, on a press) -------------------------------------------------
async function loadView(fresh) {
  if (S.view && !fresh) return S.view;
  S.view = await M.api('/v1/wardrobe?private=1');
  if (!S.place) { const home = (S.view.places || []).find((p) => p.kind === 'storage'); S.place = home ? home.id : ''; }
  return S.view;
}
async function refreshView() { // in the background: only a list that arrived replaces his list
  try { const v = await M.api('/v1/wardrobe?private=1'); if (v && Array.isArray(v.pieces)) S.view = v; } catch (_) { return; }
  if (UI.body) paintBody();
}
async function printsFor(model) {
  if (model !== MODEL && model !== 'mnv2-fp32-1') return [];
  if (!S.prints || S.prints.model !== model) {
    const got = await M.api('/v1/wardrobe/fingerprints?model=' + model);
    S.prints = { model, items: (got && Array.isArray(got.items) ? got.items : []).map((x) => ({ piece: x.piece, v: W.unb64(x.v) })) }; // never another model's
  }
  return S.prints.items;
}

// ---- what each step shows ---------------------------------------------------------------------------------------------
function row(title, sub, actions) {
  const r = mk('div', 'hp-row'), t = mk('div', 'hp-txt'), a = mk('div', 'hp-acts');
  t.append(mk('b', '', title));
  if (sub) t.append(mk('small', '', sub));
  (actions || []).forEach((x) => a.append(x));
  r.append(t); if (a.childNodes.length) r.append(a);
  return r;
}
function select(label, options, value, change) {
  const s = mk('select', 'minput');
  options.forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; s.append(o); });
  s.value = value; s.addEventListener('change', () => change(s.value));
  return S.P.field(label, s);
}
function paintBody() {
  if (!UI.body) return;
  const parts = { add: addBody, laundry: () => listBody('laundry'), clean: () => listBody('clean'), find: findBody, label: () => UI.labelBox || [] }[S.flow]();
  UI.body.replaceChildren(...[].concat(parts));
}
function addBody() {
  if (!S.cards.length) return [mk('p', 'sfine', 'Lay one or more pieces apart on a plain surface, then take a photo or choose one.')];
  return S.cards.map((card, i) => {
    const sec = mk('section', 'hp-sec wd-card');
    sec.append(mk('h3', 'hp-h', 'Piece ' + (i + 1) + ' of ' + S.cards.length));
    if (card.piece) sec.append(...savedActs(card));
    else sec.append(...chooseActs(card));
    return sec;
  });
}
function chooseActs(card) {
  const out = [];
  const label = [...S.found.keys()];
  if (card.cands.twins) out.push(mk('p', 'snote warn', TWINS_NOTE));
  const picks = card.cands.top.map((c, i) => btn('This one: ' + nameOf(c.piece) + banded(c), c.band === 'likely' ? 'primary' : '', () => pick(card, c.piece, i ? 'tap' : 'match', card.cands.top[0].score)));
  label.forEach((id) => picks.unshift(btn('This one: ' + nameOf(id) + ' (label read)', 'primary', () => pick(card, id, 'qr', null))));
  if (picks.length) { const a = mk('div', 'sacts'); a.append(...picks); out.push(a); }
  const chips = mk('div', 'sacts wd-chips');
  chips.setAttribute('role', 'group');
  chips.setAttribute('aria-label', 'What kind of piece');
  KINDS.forEach(([t, w]) => { const b = btn(w, '', () => { card.kind = t; card.private = privateType(t) ? null : false; paintBody(); }); pressed(b, card.kind === t); chips.append(b); });
  out.push(mk('p', 'sfine', card.cands.top.length || label.length ? 'Or a new piece: what kind is it?' : 'A new piece: what kind is it?'), chips);
  if (card.colour) out.push(mk('p', 'sfine', 'Colour: ' + colourWords(card.colour) + ' (suggested)'));
  if (card.kind && card.private === null) {
    const a = mk('div', 'sacts');
    a.append(btn('Make it private', 'primary', () => { card.private = true; paintBody(); }), btn('Keep it visible', '', () => { card.private = false; paintBody(); }));
    out.push(mk('p', 'snote', 'Make it private? A private piece is counted only, never named outside your Wardrobe tab, and keeps no photo.'), a);
  } else if (card.kind) {
    const a = mk('div', 'sacts');
    const add = btn('Save as a new piece', 'primary', () => addPiece(card));
    add.disabled = card.adding;
    a.append(add);
    out.push(a);
  }
  return out;
}
const colourWords = (c) => (c.name === 'multicolour' ? 'multicolour, mostly ' + String(c.second || '').replace(/_/g, ' ') : c.name.replace(/_/g, ' '));
function allowed(card) { // D9: a saved piece that is not private, from a photo AND a crop whose checks found nobody
  const p = pieceOf(card.piece), cut = card.cropGate;
  return !!(p && !p.private && !privateType(p.type) && !card.whole && S.gate && S.gate.checked && !S.gate.refused && !(cut && (!cut.checked || cut.refused))
    && card.crop && card.crop.width && S.photo);
}
function whyNot(card) { // the words for why this card keeps and sends nothing
  if (card && card.whole) return WHOLE;
  const bad = [S.gate, card && card.cropGate].find((g) => g && g.refused);
  return bad && bad.checked ? PERSON : NO_CHECK;
}
const refuse = (card) => { say(UI.state, whyNot(card), 'bad'); paintBody(); };
function savedActs(card) {
  const out = [mk('p', 'snote ok', nameOf(card.piece) + ': this piece.')];
  const p = pieceOf(card.piece);
  if (p && (p.private || privateType(p.type))) { out.push(mk('p', 'sfine', PRIVATE_NOTE)); return out; }
  if (!allowed(card)) { out.push(mk('p', 'sfine', whyNot(card))); return out; }
  card.crop.className = 'wd-crop'; card.crop.setAttribute('role', 'img'); // M2: exactly what Save, Remember or the AI tag use
  card.crop.setAttribute('aria-label', 'The crop of this piece, on this phone only'); out.push(mk('p', 'sfine', 'Save keeps exactly this crop:'), card.crop);
  const a = mk('div', 'sacts');
  a.append(btn(SAVE_WORDS, 'primary', () => savePhoto(card)));
  if (card.v) a.append(btn('Remember how it looks', '', () => remember(card)));
  out.push(a);
  const tag = tagBox(card);
  if (tag) out.push(tag);
  return out;
}
function listBody(kind) {
  const out = [];
  if (kind === 'clean') {
    const places = ((S.view && S.view.places) || []).filter((p) => p.kind !== 'basket').map((p) => [p.id, p.label]);
    if (places.length) out.push(select('Where it goes', places, S.place, (v) => { S.place = v; }));
    const a = mk('div', 'sacts');
    [[true, 'Dry'], [false, 'Needs pressing']].forEach(([v, w]) => { const b = btn(w, '', () => { S.dry = v; paintBody(); }); pressed(b, S.dry === v); a.append(b); });
    out.push(a);
  }
  S.cards.forEach((card) => { if (!card.piece && card.cands.top.length) out.push(...pickRows(card)); });
  const rows = [...S.found.entries()].map(([id, f]) => row(nameOf(id), f.how === 'qr' ? 'Its label was read' : f.how === 'unsure' ? 'One of these: both wait for a quick check' : 'You tapped it',
    [btn('Remove', '', () => { S.found.delete(id); if (S.live) S.skip.add(id); paintBody(); })]));
  out.push(...(rows.length ? rows : [mk('p', 'sfine', 'Start the camera to read their labels, or take a photo.')]));
  if (kind === 'laundry') {
    const n = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((x) => [String(x), x ? String(x) : 'None']);
    out.push(select('And more I couldn\u2019t show', n, String(S.more), (v) => { S.more = Number(v); paintBody(); }));
    if (S.more) out.push(select('What kind', ((S.view && S.view.categories) || ['tops']).map((c) => [c, c]), S.moreKind, (v) => { S.moreKind = v; }));
  }
  const a = mk('div', 'sacts');
  const go = btn(kind === 'laundry' ? 'Put in laundry' : 'Put away clean', 'primary', () => send(kind));
  go.disabled = !S.found.size && !S.more;
  a.append(go, btn('Cancel', '', () => { clearList(); paint(); say(UI.state, 'Nothing was sent.'); }));
  out.push(a);
  return out;
}
function pickRows(card) {
  const out = [];
  if (card.cands.twins) out.push(mk('p', 'snote warn', TWINS_NOTE));
  const a = mk('div', 'sacts');
  card.cands.top.forEach((c, i) => a.append(btn(nameOf(c.piece) + banded(c), '', () => { S.found.set(c.piece, { how: i ? 'tap' : 'match', score: card.cands.top[0].score, at: new Date().toISOString() }); card.piece = c.piece; paintBody(); })));
  if (card.cands.twins) a.append(btn('Not sure which', '', () => { card.cands.top.slice(0, 2).forEach((c) => S.found.set(c.piece, { how: 'unsure', score: c.score, at: new Date().toISOString() })); card.piece = card.cands.top[0].piece; paintBody(); }));
  out.push(a);
  return out;
}
function findBody() {
  const out = [];
  const input = mk('input', 'minput');
  input.type = 'search'; input.maxLength = 60; input.autocomplete = 'off'; input.value = S.query || '';
  input.addEventListener('input', () => { S.query = input.value; paintFound(list); });
  const list = mk('div', '');
  out.push(S.P.field('Or type a name', input), list);
  S.cards.forEach((card) => card.cands.top.forEach((c) => { if (!S.found.has(c.piece)) S.found.set(c.piece, { how: 'match', score: c.score }); }));
  paintFound(list);
  return out;
}
function paintFound(list) {
  const q = String(S.query || '').trim().toLowerCase();
  const ids = q ? ((S.view && S.view.pieces) || []).filter((p) => !p.private && [p.label, p.type, p.colour].join(' ').toLowerCase().replace(/_/g, ' ').includes(q)).slice(0, 5).map((p) => p.id) : [...S.found.keys()];
  list.replaceChildren(...ids.map((id) => { const p = pieceOf(id) || {}; return row(nameOf(id), [p.state_words, p.place_words].filter(Boolean).join(', ')); }));
  if (!ids.length) list.append(mk('p', 'sfine', q ? 'Nothing in your wardrobe by that name.' : 'Take a photo or start the camera.'));
}

// ---- sending: ids only, in memory until it is through ----------------------------------------------------------------------
function event(piece, kind, f, extra) {
  return Object.assign({ client_id: 'wd' + randomId(14), piece, kind, at: (f && f.at) || new Date().toISOString(), source: 'phone', via: S.device,
    how: f && (f.how === 'qr' || f.how === 'tap') ? f.how : 'match', score: f && typeof f.score === 'number' ? f.score : null, verified: !(f && f.how === 'unsure') }, extra || {});
}
async function send(kind) {
  const events = [...S.found.entries()].map(([id, f]) => (kind === 'laundry' ? event(id, 'deposited', f) : event(id, S.dry ? 'returned' : 'needs_prep', f, S.dry && S.place ? { place: S.place } : {})));
  const more = kind === 'laundry' && S.more ? { step: 'basket', more: S.more, category: S.moreKind } : null;
  clearList();
  if (events.length) S.queue.push(...events);
  await flush();
  if (more) await tool('laundry_move', more);
  paint();
}
async function flush() {
  if (!S.queue.length || S.busy || !signedIn()) { paintUnsent(); return; }
  S.busy = true;
  const batch = S.queue.splice(0, 50), sent = new Date().toISOString();
  try {
    const r = await M.api('/v1/wardrobe/scan', { body: { rev_seen: S.view ? S.view.rev : null, events: batch.map((e) => Object.assign({}, e, { sent })) } });
    say(UI.state, String((r && r.message) || 'Saved.') + (r && r.review ? ' ' + r.review + ' to check in Helpers, Wardrobe.' : ''), 'ok');
    if (r && r.view) S.view = r.view; else refreshView(); // H1: his list stays until a fresh one has arrived
  } catch (e) {
    if (isNetwork(e)) S.queue.unshift(...batch); // kept in memory only; said below
    else say(UI.state, failed(e), 'bad');
  } finally { S.busy = false; }
  paintUnsent();
}
function paintUnsent() {
  if (!UI.unsent) return;
  UI.unsent.hidden = !S.queue.length;
  UI.unsent.replaceChildren(...(S.queue.length ? [mk('p', 'snote warn', UNSENT + ' (' + S.queue.length + ')'), btn('Send now', '', flush)] : []));
}
async function tool(name, args, done) { // a result that refused (A's {status: refused | unavailable | ask}) is said, not taken
  const r = await M.api('/v1/wardrobe/tools/' + name, { body: { arguments: args } }).catch((e) => ({ status: 'error', message: failed(e) }));
  const res = (r && r.result) || {}, ok = !!r && r.status === 'executed' && !['refused', 'unavailable', 'ask'].includes(res.status);
  const words = r && r.status === 'needs_approval' ? 'That needs your OK: the card is waiting.' : ok ? done || r.message : res.message || res.question || (r && r.message);
  say(UI.state, String(words || '').slice(0, 200), ok ? 'ok' : 'bad');
  return ok ? res : null;
}
async function pick(card, id, how, score) {
  card.piece = id;
  S.queue.push(event(id, 'seen', { how, score, at: new Date().toISOString() }));
  await flush();
  await loadView();
  paintBody();
}
async function addPiece(card) { // A's shape: {pieces: [...]} -> {ids, new}; the card's client id makes a retry the same piece
  if (card.adding) return;
  card.adding = true; paintBody();
  const one = { type: card.kind, private: !!card.private, client_id: card.client };
  if (card.colour && card.colour.name !== 'multicolour') one.colour = card.colour.name; // a suggestion, never locked
  const got = await tool('wardrobe_add', { pieces: [one] }, 'Added to your wardrobe.');
  const id = got && Array.isArray(got.ids) && typeof got.ids[0] === 'string' ? got.ids[0] : null;
  if (id) { await loadView(true).catch(() => null); card.piece = id; }
  card.adding = false;
  paintBody();
}

// ---- keeping a look: the door only, after the check, never for a private piece --------------------------------------------
const blobOf = (c) => new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', JPEG_Q));
async function savePhoto(card) {
  if (!allowed(card)) { paintBody(); return; }
  if (!(await cropOk(card))) { refuse(card); return; }
  const door = Door(), blob = await blobOf(card.crop);
  if (!door || !blob) return;
  try { await door.wardrobe(blob, { piece: card.piece, view: 'front' }); say(UI.state, 'Saved with the piece, sealed. Only you can see it.', 'ok'); } catch (e) { say(UI.state, String((e && e.message) || failed(e)).slice(0, 200), 'bad'); }
  paintActs();
}
async function remember(card) {
  if (!allowed(card) || !card.v) { paintBody(); return; }
  if (!(await cropOk(card))) { refuse(card); return; }
  try {
    await M.api('/v1/wardrobe/fingerprints', { body: { piece: card.piece, view: 'front', model: MODEL, v: card.v } });
    S.prints = null;
    say(UI.state, 'Remembered: JARVIS will offer this piece when it sees it again.', 'ok');
  } catch (e) { say(UI.state, failed(e), 'bad'); }
}
function tagBox(card) { // optional AI tagging (D7, H2): his setting, the AI on, the rupees shown before the press
  const set = (S.view && S.view.settings) || {};
  if (set.ai_tagging !== true || noAi()) return null;
  const box = mk('div', 'sacts');
  const month = Number(set.tag_month_inr) || 0, cap = Number(set.tag_cap_inr) || 0, own = Number(set.tag_estimate_inr) > 0 ? Number(set.tag_estimate_inr) : 0;
  if (cap <= 0 || month + (own || TAG_MOST) > cap) { box.append(mk('p', 'sfine', 'AI tagging has reached this month\u2019s limit of \u20b9' + cap + '.')); return box; }
  box.append(mk('p', 'sfine', 'AI tagging this month: \u20b9' + month.toFixed(2) + ' of \u20b9' + cap + '.'),
    btn(tagWords(own), '', () => tag(card, box)));
  return box;
}
async function tag(card, box) {
  if (!allowed(card) || noAi()) { paintBody(); return; } // L10: the AI switched off since: nothing is sent
  if (!(await cropOk(card))) { refuse(card); return; }
  const door = Door(), blob = await blobOf(card.crop);
  if (!door || !blob) return;
  try {
    const r = await door.tag(blob, { piece: card.piece });
    const g = (r && r.suggestion) || {};
    const words = [g.type, g.colour, g.pattern].filter((x) => typeof x === 'string').map((x) => x.replace(/_/g, ' ')).join(', ');
    box.replaceChildren(mk('p', 'sfine', 'The AI suggests: ' + (words || 'nothing new') + '. A suggestion only: change it in Helpers, Wardrobe.'));
  } catch (e) { say(UI.state, String((e && e.message) || failed(e)).slice(0, 200), 'bad'); }
  paintActs();
}

// ---- Read a label: parsed words only, each unverified until he confirms ----------------------------------------------------
async function readLabel(cv, mine) {
  const r = await run('text', cv);
  if (mine !== S.seq) return;
  const got = W.parseLabel(r && r.ok ? r.data.text : '');
  const box = mk('section', 'hp-sec');
  box.append(mk('h3', 'hp-h', 'What the label says'));
  const fields = []; // [A's field, his words, its parsed value]: each field is kept or confirmed whole (M6)
  if (got.size) fields.push(['size', 'Size ' + got.size, got.size]);
  if (got.fabric.length) fields.push(['fabric', got.fabric.map((f) => f.pct + '% ' + f.name).join(', '), got.fabric.map((f) => f.name + ' ' + f.pct + '%')]);
  if (got.care.length) fields.push(['care', got.care.map((c) => c.replace(/_/g, ' ')).join(', '), got.care]);
  if (!fields.length) box.append(mk('p', 'sfine', 'No size, fabric or care words could be read. Type them in Helpers, Wardrobe.'));
  const pieces = ((S.view && S.view.pieces) || []).map((p) => [p.id, nameOf(p.id)]);
  let target = pieces.length ? pieces[0][0] : '';
  if (fields.length && pieces.length) box.append(select('Which piece', pieces, target, (v) => { target = v; }));
  fields.forEach(([field, words, value]) => box.append(row(words, 'Unverified: read from the label', [btn('Confirm', '', () => labelEdit(target, { [field]: value }, [field]))])));
  if (fields.length) {
    const a = mk('div', 'sacts');
    a.append(btn('Keep these (unverified)', '', () => labelEdit(target, Object.fromEntries(fields.map(([f, , v]) => [f, v])), [])));
    box.append(a);
  }
  UI.labelBox = box;
  say(UI.state, '');
  paint();
}
function labelEdit(piece, read, verify) { // A: read off a photo (unverified); Confirm says which fields he checked
  if (!piece) return null;
  const args = Object.assign({ piece }, read, { read: true }, verify.length ? { verify } : {});
  return tool('wardrobe_edit', args, verify.length ? 'Confirmed.' : 'Kept, unverified until you confirm.');
}

// ---- joining the camera panel ----------------------------------------------------------------------------------------------
function join() {
  const modes = window.JarvisCameraModes;
  return !!(modes && modes.register('wardrobe', { mount, stop }));
}
if (!join()) document.addEventListener('jarvis:camera-modes', join, { once: true });
document.addEventListener('jarvis:camera', () => { const c = Cam(); if (S.live && !(c && c.live())) { if (S.codes) S.codes.stop(); S.codes = null; S.live = null; S.skip = new Set(); if (UI.stage) UI.stage.replaceChildren(); } if (UI.acts) paintActs(); });
document.addEventListener('jarvis:pictures-sent', () => { const d = Door(); if (UI.sent && d) UI.sent.textContent = d.line(); });
