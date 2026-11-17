// src/jarvis/api/static/console-tryon-me.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D11-D13, D22; AVT-12): "See it
// on me", for a garment he is thinking of BUYING, in Helpers -> Wardrobe -> Try it on.
//   draw(host, o)   o = {H, api, door, btn, look, photosOf}: his photo (checked on this device by './console-tryon-photo.js',
//                   sent only by the door's person()), the new garment's photo (a file, or a picture shared in: take()),
//                   its type and colour from fixed lists (never free text; no web address: JARVIS fetches none), the
//                   pairing with up to two of his own non-private pieces (GET /v1/seeme/pair; swap or untick), his
//                   typed YES (a .bdialog: ConsentView's words, POST /v1/seeme/consent {typed, template_version}), the
//                   estimate in rupees with GST and the .bdialog confirm (Make the picture sends {garment, pieces,
//                   confirm_cost, inr_shown, request_id}; Cancel sends NOTHING), the progress, the picture with its words
//                   ("Generated 2D style preview ...", the made-at time, the rupees, the new garment "not in your
//                   wardrobe", his pieces sent and not, Content Credentials), Keep and delete; his garment photos listed.
//   take(file)      a picture shared into the app: it waits here for his type and colour (this sends nothing)
//   refresh()       re-read GET /v1/seeme (after Privacy's delete)
// The garment is never added to his wardrobe here. Refusals branch on err.code (Refusal's `error`). The door is the only
// caller of the photo, picture and garment routes: its make, keep, forget and garments are proposed for I1
// (INTEGRATION-D "Needs I1"); until they exist this says so and sends nothing. textContent only; no pixel API; ASCII.
const photo = () => import('./console-tryon-photo.js');
// the fixed lists: wardrobe/tryon/model.py NEW_TYPES and wardrobe/model.py COLOURS (tests/test_r131_d_static.py pins both)
export const NEW_TYPES = Object.freeze(['shirt', 't_shirt', 'polo', 'top', 'kurta', 'trousers', 'chinos', 'jeans', 'joggers', 'pyjama',
  'shorts', 'mundu', 'dhoti', 'blazer', 'jacket', 'coat', 'hoodie', 'sweater', 'rainwear', 'festive_layer']);
export const COLOURS = Object.freeze(['black', 'white', 'grey', 'charcoal', 'navy', 'blue', 'light_blue', 'green', 'olive', 'yellow',
  'orange', 'red', 'maroon', 'pink', 'purple', 'brown', 'beige', 'khaki', 'multicolour']);
const SENDABLE = ['top', 'bottom', 'outer'], PAIR_MAX = 2;
const INTRO = 'For a garment you are thinking of buying: JARVIS pictures you in it with up to two pieces you own. About \u20b99 a picture with GST, shown before each one. The garment is never added to your wardrobe.';
const ADVICE = 'One full-length photo of you: standing, head to feet, a plain background, fitted everyday clothes, good light. It is kept sealed by JARVIS until you delete it.';
const MAKING = 'Making your picture\u2026 this can take up to two minutes.';
const LATER = 'This arrives with the next JARVIS update.';
const M = { host: null, o: null, view: null, garments: [], garment: null, file: null, url: '', pair: null, mine: [], est: null, pic: null, picUrl: '',
  busy: false, dlg: null, note: null, me: '' };

const H = () => M.o.H;
const txt = (v, n = 200) => H().txt(String(v == null ? '' : v), n);
const word = (w) => (w === 't_shirt' ? 'T-shirt' : String(w).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()));
const rupees = (n) => '\u20b9' + (Math.round(Number(n) * 100) / 100).toFixed(2);
const when = (iso) => (window.JarvisMobile && window.JarvisMobile.when ? window.JarvisMobile.when(iso, true) : String(iso || '').slice(0, 16).replace('T', ' '));
const door = () => M.o.door();
const has = (fn) => { const d = door(); return !!(d && typeof d[fn] === 'function'); };
const say = (kind, text) => H().note(M.note, kind, text);
function failed(e) {
  if (e && e.status === 401) return;
  say('bad', e && e.name === 'TypeError' ? 'Can\u2019t reach JARVIS. Check your connection.' : txt((e && e.message) || 'That didn\u2019t work.', 240));
}
function requestId() { const b = new Uint8Array(8); crypto.getRandomValues(b); return 'tq_' + Array.from(b, (x) => x.toString(16).padStart(2, '0')).join(''); }
function select(list, value, label) {
  const s = H().mk('select', 'minput');
  s.setAttribute('aria-label', label);
  list.forEach(([v, t]) => { const o = H().mk('option', '', t); o.value = v; s.append(o); });
  s.value = value;
  return s;
}
function field(label, control) { const f = H().mk('label', 'hp-field'); f.append(H().mk('span', 'snote', label), control); return f; }
function dataUrl(file) { return new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(String(f.result)); f.onerror = () => ok(''); f.readAsDataURL(file); }); }
function image(cls, url, alt) { const i = H().mk('img', cls); i.alt = alt; if (/^data:image\/(png|jpeg);base64,/.test(url)) i.src = url; return i; }

// ---- the server -------------------------------------------------------------------------------------------------------
async function read() {
  try { M.view = await M.o.api('/v1/seeme'); } catch (e) { M.view = null; if (e && e.status !== 401) M.why = e && e.status === 404 ? 'See it on me isn\u2019t on this server.' : txt(e && e.message, 200); }
  M.garments = [];
  if (M.view && M.view.on && has('garments')) { try { M.garments = (await door().garments()).garments || []; } catch (_) { M.garments = []; } }
  if (M.garment && !M.garments.some((g) => g.id === M.garment.id)) { M.garment = null; M.pair = null; M.mine = []; }
}
export async function refresh() { await read(); render(); }

// ---- drawing ------------------------------------------------------------------------------------------------------------
export function draw(host, o) {
  M.host = host; M.o = o;
  M.note = H().mk('p', 'sfine hp-note'); M.note.setAttribute('role', 'status');
  host.classList.add('tr-me');
  host.replaceChildren(H().mk('p', 'sfine', INTRO), H().empty('Loading See it on me\u2026'));
  refresh();
}
function render() {
  const h = H(), v = M.view, out = [h.mk('p', 'sfine', INTRO)];
  if (!v) { M.host.replaceChildren(...out, h.empty(M.why || 'See it on me couldn\u2019t load.')); return; }
  if (v.notice) out.push(h.mk('p', 'snote warn', txt(v.notice, 200)));
  if (!v.on) { out.push(h.mk('p', 'snote warn', txt(v.why || 'See it on me is off.', 200))); M.host.replaceChildren(...out, ...pictures()); return; }
  out.push(...mine(), ...garmentRows(), ...pairing(), M.note, ...result(), ...pictures());
  M.host.replaceChildren(...out);
}
function mine() { // his photo: kept sealed on his server; checked on this device before it is sent
  const h = H(), p = M.view.photo || {}, out = [];
  const acts = p.kept ? [M.o.btn('Show it', showMine), M.o.btn('Delete my photo and my YES', dropMine)] : [];
  out.push(h.row('Your photo', p.kept ? 'Kept, sealed, since ' + when(p.at) + ' \u00b7 ' + Math.round((p.bytes || 0) / 1024) + ' KB' : 'No photo yet.', acts));
  if (M.me) out.push(image('tr-pic', M.me, 'Your photo'));
  const input = h.mk('input', 'minput');
  input.type = 'file'; input.accept = 'image/jpeg,image/png'; input.id = 'trMyPhoto';
  input.addEventListener('change', () => { const f = input.files && input.files[0]; input.value = ''; if (f) sendMine(f); });
  out.push(field(p.kept ? 'Replace your photo' : 'Take or choose a photo of you', input), h.mk('p', 'sfine', ADVICE));
  const P = M.photoWords || {};
  out.push(h.mk('p', 'sfine', P.ages || 'JARVIS can\u2019t tell an adult from a child: use only your own photo.'));
  const c = M.view.consent || {};
  out.push(h.mk('p', 'sfine', c.current ? 'Your YES was given ' + when(c.at) + '.' : 'You type YES before your first picture, after reading what is sent and to whom.'));
  return out;
}
function garmentRows() { // the new garment: its photo, its type and colour from lists; then the list of those kept
  const h = H(), out = [h.mk('p', 'snote', 'Add a garment you\u2019re thinking of buying')];
  const input = h.mk('input', 'minput');
  input.type = 'file'; input.accept = 'image/jpeg,image/png'; input.id = 'trGarment';
  input.addEventListener('change', () => { const f = input.files && input.files[0]; input.value = ''; if (f) take(f); });
  out.push(field('A photo of the garment: a shop photo, a website picture or a screenshot', input));
  if (M.file) {
    const grid = h.mk('div', 'hp-grid');
    M.type = M.type || 'shirt'; M.colour = M.colour || 'navy';
    const t = select(NEW_TYPES.map((x) => [x, word(x)]), M.type, 'What it is'), c = select(COLOURS.map((x) => [x, word(x)]), M.colour, 'Its colour');
    t.addEventListener('change', () => { M.type = t.value; }); c.addEventListener('change', () => { M.colour = c.value; });
    grid.append(field('What it is', t), field('Its colour', c));
    const acts = h.mk('div', 'sacts');
    acts.append(M.o.btn('Check and add this garment', addGarment), M.o.btn('Cancel', () => { M.file = null; M.url = ''; render(); }));
    out.push(image('tr-garment', M.url, 'The garment you chose'), grid, acts);
  }
  if (!has('garments')) out.push(h.mk('p', 'sfine', 'Your garment photos will be listed here. ' + LATER));
  M.garments.forEach((g) => out.push(h.row(txt(g.words, 120), 'Added ' + when(g.at) + (g.until ? ' \u00b7 kept until ' + when(g.until) : ' \u00b7 kept while a kept picture shows it'),
    [M.o.btn(M.garment && M.garment.id === g.id ? 'Chosen' : 'Use this one', () => choose(g)), M.o.btn('Delete', () => forget(g.id))])));
  return out;
}
function candidates(slot) { // his non-private pieces in that slot, from the look's own options (the server's words)
  const look = M.o.look(), s = look && (look.slots || []).find((x) => x.slot === slot && !x.private);
  if (!s) return [];
  const list = [[s.piece, s.words]].concat((s.options || []).map((x) => [x.piece, x.words]));
  return list.filter(([p], i) => p && list.findIndex(([q]) => q === p) === i);
}
function pairing() { // up to two of his pieces with it: R13's pick, which he may swap or untick
  if (!M.garment) return [];
  const h = H(), out = [h.mk('p', 'snote', txt(M.garment.words, 120))];
  if (M.pair && M.pair.words) out.push(h.mk('p', 'sfine', txt(M.pair.words, 200)));
  SENDABLE.filter((slot) => slot !== M.garment.slot).forEach((slot) => {
    const got = M.mine.find((x) => x.slot === slot), list = candidates(slot);
    if (!got && !list.length) return;
    const tick = h.mk('input', ''), f = h.mk('label', 'hp-field wd-tick');
    tick.type = 'checkbox'; tick.checked = !!(got && got.on); tick.dataset.slot = slot;
    tick.addEventListener('change', () => toggle(slot, tick));
    f.append(h.mk('span', 'snote', 'With your ' + ({ top: 'top', bottom: 'bottom', outer: 'outer layer' })[slot] + ': ' + txt(got ? got.words : (list[0] || [])[1], 60)), tick);
    out.push(f);
    if (list.length > 1) {
      const pick = select(list.map(([p, w]) => [p, txt(w, 60)]), got ? got.piece : list[0][0], 'Another of your pieces for this');
      pick.addEventListener('change', () => swapMine(slot, pick.value, list));
      out.push(field('Or another of yours', pick));
    }
  });
  ((M.pair && M.pair.not_sent) || []).forEach((n) => out.push(h.mk('p', 'sfine', 'Not in the picture: ' + txt(n.words, 80))));
  const go = M.o.btn('See it on me', press, 'primary');
  if (!M.view.photo || !M.view.photo.kept) { go.setAttribute('aria-disabled', 'true'); out.push(h.mk('p', 'sfine', 'Add your photo first.')); }
  const acts = h.mk('div', 'sacts'); acts.append(go);
  out.push(acts, h.mk('p', 'sfine', 'Its price is shown before anything is sent. ' + rupees(M.view.typical_inr) + ' with GST is typical; this month ' + rupees((M.view.month || {}).spent_inr || 0) + ' of ' + rupees((M.view.month || {}).cap_inr || 0) + ' is used.'));
  return out;
}
function toggle(slot, tick) {
  const on = M.mine.filter((x) => x.on && x.slot !== slot).length;
  if (tick.checked && on >= PAIR_MAX) { tick.checked = false; say('bad', 'At most two of your pieces go with it.'); return; }
  const got = M.mine.find((x) => x.slot === slot), first = candidates(slot)[0];
  if (got) got.on = tick.checked; else if (first) M.mine.push({ slot, piece: first[0], words: first[1], on: tick.checked });
  render();
}
function swapMine(slot, piece, list) {
  const w = (list.find(([p]) => p === piece) || [piece, ''])[1], rest = M.mine.filter((x) => x.slot !== slot);
  M.mine = rest.concat([{ slot, piece, words: w, on: true }]).slice(-Math.max(PAIR_MAX, rest.length + 1));
  if (M.mine.filter((x) => x.on).length > PAIR_MAX) M.mine.find((x) => x.on && x.slot !== slot).on = false;
  render();
}
function result() { // the picture just made: its label, time, rupees, the new garment and what was sent
  const h = H(), p = M.pic;
  if (!p) return [];
  const out = [image('tr-pic', M.picUrl, txt(p.label, 120)), h.mk('p', 'snote', txt(p.label, 120))];
  out.push(h.mk('p', 'sfine', 'Made ' + when(p.made_at) + ' \u00b7 ' + rupees(p.inr) + ' with GST \u00b7 ' + txt(p.garment && p.garment.words, 120)));
  out.push(h.mk('p', 'sfine', p.sent && p.sent.length ? 'Your pieces in it: ' + p.sent.map((s) => txt(s.words, 60)).join(', ') + '.' : 'None of your pieces is in it.'));
  (p.not_sent || []).forEach((n) => out.push(h.mk('p', 'sfine', 'Not in the picture: ' + txt(n.words, 80))));
  out.push(h.mk('p', 'sfine', txt(p.credentials || 'Google adds Content Credentials (C2PA)', 120)));
  const acts = h.mk('div', 'sacts');
  acts.append(M.o.btn(p.kept ? 'Don\u2019t keep' : 'Keep', () => keep(p, !p.kept)), M.o.btn('Delete', () => forget(p.id)), M.o.btn('Close', () => { M.pic = null; M.picUrl = ''; render(); }));
  out.push(acts);
  return out;
}
function pictures() {
  const h = H(), list = (M.view && M.view.pictures) || [];
  return list.filter((p) => !M.pic || p.id !== M.pic.id).map((p) => h.row(txt(p.garment && p.garment.words, 120),
    'Made ' + when(p.made_at) + ' \u00b7 ' + rupees(p.inr) + (p.kept ? ' \u00b7 kept' : p.until ? ' \u00b7 until ' + when(p.until) : ''),
    [M.o.btn('Show', () => showPicture(p)), M.o.btn('Delete', () => forget(p.id))]));
}

// ---- his photo ----------------------------------------------------------------------------------------------------------
async function sendMine(file) {
  say('', 'Checking the photo on this device\u2026');
  let P = null;
  try { P = await photo(); M.photoWords = P.WORDS; } catch (_) { say('bad', 'The photo check isn\u2019t available on this device, so nothing was sent.'); return; }
  const r = await P.person(file, M.view.photo_max_kb);
  if (!r.ok || !r.sent) { say('bad', r.words); return; }
  await read(); render();
  say(r.advice ? '' : 'ok', 'Your photo is kept, sealed. ' + (r.advice || r.words));
}
async function showMine() { try { M.me = await door().myPhoto(); } catch (e) { failed(e); } render(); }
async function dropMine() { await forget('photo'); M.me = ''; }

// ---- the new garment ------------------------------------------------------------------------------------------------------
export async function take(file) { // shared in or chosen: shown with the lists; nothing is sent until he presses
  if (!(file instanceof Blob)) return;
  M.file = file; M.url = await dataUrl(file);
  if (M.host && M.view) { render(); say('', 'Say what it is and its colour, then press Check and add this garment.'); }
}
async function addGarment() {
  if (M.busy || !M.file) return;
  if (!NEW_TYPES.includes(M.type) || !COLOURS.includes(M.colour)) { say('bad', 'Choose what it is and its colour from the lists.'); return; }
  M.busy = true; say('', 'Checking the photo on this device\u2026');
  try {
    const P = await photo(), r = await P.garment(M.file);
    if (!r.ok) { say('bad', r.words); return; }
    const g = await door().garment(M.file, { type: M.type, colour: M.colour, maxKb: M.view.photo_max_kb });
    M.file = null; M.url = '';
    await read(); await choose(g);
    say('ok', 'Added: ' + txt(g.words, 120) + '. It is never added to your wardrobe.');
  } catch (e) { failed(e); } finally { M.busy = false; }
}
async function choose(g) {
  M.garment = g; M.pair = null; M.mine = [];
  try { M.pair = await M.o.api('/v1/seeme/pair?garment=' + encodeURIComponent(g.id)); } catch (e) { failed(e); }
  const look = M.o.look();
  M.mine = ((M.pair && M.pair.pieces) || []).slice(0, PAIR_MAX).map((p) => {
    const s = look && (look.slots || []).find((x) => SENDABLE.includes(x.slot) && (x.piece === p.piece || (x.options || []).some((o) => o.piece === p.piece)));
    return { slot: s ? s.slot : '', piece: p.piece, words: p.words, on: true };
  });
  render();
}

// ---- the press: YES once, the estimate, the confirm, the picture -----------------------------------------------------------------
function dialog() {
  if (M.dlg) return M.dlg;
  const d = document.createElement('dialog');
  d.className = 'bdialog tr-dlg';
  d.addEventListener('cancel', (e) => { e.preventDefault(); d.close(); });
  document.body.append(d);
  M.dlg = d;
  return d;
}
function ask(title, lines, buttons, input) { // a .bdialog: resolves with the button's value; Escape and Cancel give null
  const d = dialog();
  return new Promise((resolve) => {
    const done = (v) => { if (d.open) d.close(); resolve(v); };
    const acts = H().mk('div', 'sacts actions');
    buttons.forEach(([label, value, cls]) => acts.append(M.o.btn(label, () => done(value === 'typed' ? input.value : value), cls)));
    d.replaceChildren(H().mk('h2', '', title), ...lines.map((l) => (l instanceof Node ? l : H().mk('p', '', txt(l, 300)))), ...(input ? [input] : []), acts);
    d.addEventListener('close', () => resolve(null), { once: true });
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
    (input || acts.firstChild).focus();
  });
}
async function consent() {
  const c = M.view.consent || {}, input = H().mk('input', 'minput');
  input.type = 'text'; input.autocomplete = 'off'; input.setAttribute('aria-label', 'Type YES to agree');
  const lines = (c.words || []).concat(['Type YES to agree. Anything else changes nothing.']);
  const typed = await ask('Before your first picture', lines, [['Cancel', null], ['Agree', 'typed', 'primary']], input);
  if (typed === null) return false;
  try { M.view = Object.assign({}, M.view, { consent: await M.o.api('/v1/seeme/consent', { body: { typed, template_version: c.version || '' } }) }); return !!M.view.consent.current; } catch (e) { failed(e); return false; }
}
function sentPieces() { return M.mine.filter((x) => x.on && x.piece).map((x) => x.piece).slice(0, PAIR_MAX); }
async function press() {
  if (M.busy || !M.garment) return;
  if (!has('make')) { say('bad', LATER); return; }
  if (!(M.view.consent && M.view.consent.current) && !(await consent())) return;
  const pieces = sentPieces();
  let est = null;
  try { est = await M.o.api('/v1/seeme/estimate?garment=' + encodeURIComponent(M.garment.id) + '&pieces=' + encodeURIComponent(pieces.join(','))); } catch (e) { failed(e); return; }
  const list = H().mk('ul', '');
  ['Sent: your photo, ' + txt(M.garment.words, 100)].concat((est.sent || []).map((s) => 'and your ' + txt(s.words, 60)))
    .concat((est.not_sent || []).map((n) => 'Not in the picture: ' + txt(n.words, 60))).forEach((t) => list.append(H().mk('li', '', t)));
  const money = rupees(est.typical_inr) + ' with GST is typical; at most ' + rupees(est.hold_inr) + ' is held until Google says what it cost.';
  const go = await ask('Make 1 picture?', [txt(est.words, 300), list, money], [['Cancel', false], ['Make the picture', true, 'primary']]);
  if (go !== true) { say('', 'Nothing was sent.'); return; }
  await make(pieces, est);
}
async function make(pieces, est) {
  M.busy = true; say('', MAKING);
  try {
    M.pic = await door().make({ garment: M.garment.id, pieces, confirm_cost: true, inr_shown: est.typical_inr, request_id: requestId() });
    try { M.picUrl = await door().picture(M.pic.id); } catch (_) { M.picUrl = ''; }
    await read(); render(); say('ok', 'Here it is. It is kept 30 days unless you press Keep.');
  } catch (e) {
    if (e && e.code === 'consent_needed') { M.view.consent = Object.assign({}, M.view.consent, { current: false }); say('bad', txt(e.message, 200)); }
    else if (e && e.code === 'price_changed') say('bad', 'The price changed: press See it on me to see it again. Nothing was sent.');
    else failed(e);
  } finally { M.busy = false; }
}
async function showPicture(p) { M.pic = p; try { M.picUrl = await door().picture(p.id); } catch (e) { failed(e); } render(); }
async function keep(p, on) {
  if (!has('keep')) { say('bad', LATER); return; }
  try { M.pic = await door().keep(p.id, on); await read(); render(); } catch (e) { failed(e); }
}
async function forget(id) {
  if (!has('forget')) { say('bad', LATER); return; }
  try {
    const r = await door().forget(id);
    if (M.pic && M.pic.id === id) { M.pic = null; M.picUrl = ''; }
    if (M.garment && M.garment.id === id) { M.garment = null; M.pair = null; M.mine = []; }
    await read(); render(); say('ok', txt((r && r.message) || 'Deleted.', 120));
  } catch (e) { failed(e); }
}
