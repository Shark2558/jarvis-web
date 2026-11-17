// src/jarvis/api/static/console-tryon-list.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D7, D8, D9; AVT-04, AVT-05,
// AVT-11, AVT-14, AVT-15): the item list of a look, which is also the checklist when 3D can't run, and the share caption.
//   items(host, looks, o)   one look's rows (or two side by side, compare): each slot, its piece's words (a private slot
//                           "Base layer (covered)", or his own words behind Show private basics), its readiness word,
//                           what is approximate, its image cards (the views kept, door.thumb) and the useful view still
//                           missing (a way to Camera); Change opens the slot's options, each with its readiness.
//                           o.compact (row 388's card): one line a piece, no image cards and no Change (the full list
//                           is in Helpers); o.summary: the pieces in ONE line (.tr-sum), as the card shows them in 3D
//   caption(look, o)        the lines for B's snapshot({caption}): the day or the event's time, then each drawn
//                           non-private piece in FIXED words ("Navy shirt \u00b7 Charcoal trousers"), "Base layer
//                           (covered)" for a private slot; his own labels only when he ticked "Use my own labels";
//                           never a piece id
//   draft(look)             "" or the first draft's words: such a look can't be confirmed
//   crop(id, read)          an image card's data: URL, read ONCE a page (page memory only, dropCrops() on a fresh load):
//                           a control press never fetches a card again, and a known card is shown at once (M2)
//   pairs, same, covered, chosen, figure   what a look becomes elsewhere (pure): its {slot, piece} picks, its covered
//                           slots, his shape choices (AVT-05) and the engine contract's figure (a private slot is
//                           {slot, private: true} only)
// The server's words reach the page by textContent only; this module draws no pixels and sends nothing. ASCII source.
export const COVERED = 'Base layer (covered)';
/** Why a viewer shows the checklist (or rests): its words. */
export const WHY = Object.freeze({
  'no-webgl2': 'This device can\u2019t show the 3D view: here is the checklist.',
  asset: 'A file of the 3D figure didn\u2019t load: here is the checklist.',
  lost: 'The 3D view stopped: here is the checklist.',
  timeout: 'The 3D view took too long to draw: here is the checklist.',
  engine: 'The 3D view isn\u2019t available right now: here is the checklist.',
  nofigure: 'No figure yet: type your measurements in Helpers, Wardrobe, Try it on.',
  elsewhere: 'The 3D view is open in another place.',
  paused: 'The 3D view rests while it is out of sight.',
});
export const SLOT_WORDS = Object.freeze({ base: 'Base', underwear: 'Base', top: 'Top', bottom: 'Bottom', outer: 'Outer layer',
  shoes: 'Shoes', belt: 'Belt', watch: 'Watch', socks: 'Socks', extras: 'Extras' });
const VIEW_WORDS = { front: 'Front', back: 'Back', detail: 'Detail' };
export const MEASURE_WORDS = Object.freeze({ height: 'Height', shoulders: 'Shoulder width', chest: 'Chest', waist: 'Waist', hips: 'Hips', inseam: 'Inseam' });
export const SHAPE_WORDS = Object.freeze({ shirt: 'Shirt', tee: 'T-shirt', kurta: 'Kurta', trousers: 'Trousers', shorts: 'Shorts', wrap: 'Mundu or dhoti',
  jacket: 'Jacket', shoe: 'Shoe', sandal: 'Sandal', belt: 'Belt', watch: 'Watch', socks: 'Socks' });
const APPROX = { template: 'Approximate shape', texture: 'texture from its photo, scale approximate', colour: 'colour approximate' };
const ID = /\bw[ih]_[0-9a-f]{12}\b|\bt[gpqc]_[0-9a-f]{6,16}\b/g;
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PER_LINE = 3;

const clean = (v, max = 80) => String(v == null ? '' : v).replace(ID, '').replace(/\s+/g, ' ').trim().slice(0, max);
const upper = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
export const slotWord = (slot) => SLOT_WORDS[slot] || upper(clean(slot, 20).replace(/_/g, ' '));

/** The look's slots as the figure wears them now: the layers chosen. */
export function worn(look, layers) {
  const slots = look && Array.isArray(look.slots) ? look.slots : [];
  if (layers === 'base') return slots.filter((s) => s.private);
  return layers === 'no_outer' ? slots.filter((s) => s.slot !== 'outer') : slots.slice();
}

// ---- what a look becomes elsewhere (pure: no DOM, no server) ----------------------------------------------------------
/** The look's {slot, piece} picks, never a private slot: what a query, a confirm and a saved comparison carry. */
export const pairs = (look) => ((look && look.slots) || []).filter((s) => !s.private && s.piece).map((s) => ({ slot: s.slot, piece: s.piece }));
export const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
/** A look's private slots as a viewer keeps them: covered; his own piece only behind his tap (R13 D10). */
export const covered = (look, priv) => ((look && look.slots) || []).filter((s) => s.private)
  .map((s) => ({ slot: s.slot, private: true, words: COVERED, readiness: s.readiness || '', piece: (priv && s.piece) || null }));
/** His shape choice per piece (AVT-05), as GET /v1/tryon's `assets` reads it back from the server. */
export function chosen(look, assets) {
  const by = new Map((assets || []).map((a) => [a.piece, a]));
  return Object.assign({}, look, { slots: ((look && look.slots) || []).map((s) => {
    const a = !s.private && by.get(s.piece);
    if (!a) return s;
    const only = !!(s.card_only || a.card_only);
    return Object.assign({}, s, { card_only: only, template: only ? null : a.template || s.template || null });
  }) });
}
/** The engine's figure (engine_contract.mjs): the contract's fields only; a private slot is {slot, private: true}. */
export function figure(raw, opts, body, assets) {
  const look = chosen(raw, assets);
  const slots = (look.slots || []).map((s) => {
    if (s.private) return { slot: s.slot, private: true };
    const template = s.card_only ? null : s.template || null;
    const vs = Array.isArray(s.variants) ? s.variants : [];
    const variant = vs.includes('tucked') ? (opts.tucked ? 'tucked' : 'untucked') : vs.includes('open') ? (opts.open ? 'open' : 'closed') : vs[0] || null;
    return { slot: s.slot, piece: s.piece, template, variant, rgb: s.rgb || null, pattern: s.pattern || null, photo: s.photo || null, private: false };
  });
  return { body: { weights: Object.assign({}, body && body.weights), typed: (body && body.typed ? body.typed : []).slice() }, look: { slots } };
}

export function draft(look) {
  const s = ((look && look.slots) || []).find((x) => x && !x.private && x.piece && x.eligible === false);
  return s ? clean(s.readiness, 80) || 'Draft' : '';
}

function words(s, o) { // what a row says for a slot: fixed words, his own only in his own panel
  if (s.private) return o.priv && s.piece && typeof o.nameOf === 'function' ? clean(o.nameOf(s.piece), 60) : COVERED;
  if (o.own && s.piece && typeof o.nameOf === 'function') return clean(o.nameOf(s.piece), 60) || clean(s.words);
  return clean(s.words) || 'A piece';
}
function subline(s) {
  const out = [clean(s.readiness, 60) || (s.private ? '' : 'Readiness unknown')];
  if (s.private) return out.filter(Boolean).join(' \u00b7 ');
  if (s.card_only || !s.template) out.push('Shown as its photo only');
  else (s.approximate || []).forEach((a) => { if (APPROX[a]) out.push(APPROX[a]); });
  if (!s.rgb && s.template && !s.card_only) out.push('no colour set');
  return out.filter(Boolean).join(' \u00b7 ');
}

const CROPS = new Map(); // photo id -> its data: URL, or the read in flight (page memory; nothing kept on the device)
export function crop(id, read) {
  const got = CROPS.get(id);
  if (got) return got;
  const p = Promise.resolve().then(() => read(id)).then((u) => { CROPS.set(id, u); return u; }, (e) => { CROPS.delete(id); throw e; });
  CROPS.set(id, p);
  return p;
}
export const dropCrops = () => CROPS.clear();
/** An <img> for a card: its data: URL at once when known, else when read (until then it shows nothing: the CSS). */
export function shownAs(img, got, failed) {
  const set = (url) => { if (/^data:image\/(png|jpeg);base64,/.test(String(url))) img.src = url; };
  if (typeof got === 'string') set(got); else Promise.resolve(got).then(set).catch(failed || (() => {}));
}
function thumb(H, o, photo, label) { // an image card: the crop through the door, as a data: URL (blob: is not in img-src)
  const fig = H.mk('figure', 'tr-ref');
  const img = H.mk('img', 'tr-thumb');
  img.alt = label + ' photo'; img.dataset.photo = photo; img.width = 56; img.height = 56; img.decoding = 'async';
  fig.append(img, H.mk('figcaption', 'sfine', label));
  if (typeof o.thumb === 'function') shownAs(img, o.thumb(photo), () => fig.append(H.mk('span', 'sfine', 'Photo not shown')));
  return fig;
}
function refs(H, s, o) { // AVT-04: the views kept, each its own card; the useful view still missing, asked for once
  const box = H.mk('div', 'tr-refs');
  const ids = s.piece && typeof o.photosOf === 'function' ? o.photosOf(s.piece) : [];
  const views = Array.isArray(s.views) ? s.views : [];
  if (views.length && ids.length === views.length) views.forEach((v, i) => box.append(thumb(H, o, ids[i], VIEW_WORDS[v] || 'Photo')));
  else if (s.photo) box.append(thumb(H, o, s.photo, VIEW_WORDS[s.texture_view] || 'Photo'));
  else box.append(H.mk('p', 'sfine', 'No photo yet'));
  (s.missing || []).filter((v) => VIEW_WORDS[v]).slice(0, 1).forEach((v) => {
    box.append(H.mk('p', 'snote', 'No ' + v + ' photo of it yet: add one in Camera, Wardrobe.'));
    if (typeof o.toCamera === 'function') box.append(o.btn('Open Camera', () => o.toCamera()));
  });
  return box;
}
function options(H, s, o, n, key) { // Change: the slot's options, each with its FRESH readiness word; Remove where allowed
  const box = H.mk('div', 'sacts tr-opts');
  const pick = n ? o.onPick2 : o.onPick;
  (s.options || []).filter((x) => x && x.piece !== s.piece).slice(0, 12).forEach((x) => {
    box.append(o.btn(clean(x.words, 60) + ' \u00b7 ' + (clean(x.readiness, 60) || 'Readiness unknown'), () => pick(s.slot, x.piece)));
  });
  if (s.removable && !n) box.append(o.btn('Remove', () => o.onRemove(s.slot)));
  box.append(o.btn('Cancel', () => o.onChange(null)));
  box.querySelectorAll('button').forEach((b) => { b.dataset.kf = key; }); // once chosen, the focus goes back to its Change
  if (box.childElementCount === 1) box.prepend(H.mk('p', 'sfine', 'Nothing else of yours fits here.'));
  return box;
}

function row(H, s, o, n) {
  const key = n + ':' + s.slot + ':' + (s.piece || '');
  const can = !s.private && !o.compact && typeof (n ? o.onPick2 : o.onPick) === 'function';
  const r = H.row(slotWord(s.slot) + ': ' + words(s, o), subline(s), can ? [o.btn('Change', () => o.onChange(o.open === key ? null : key), '', 'change:' + n + ':' + s.slot)] : []);
  r.classList.add('tr-item');
  r.dataset.slot = clean(s.slot, 20);
  if (!s.private && s.piece) r.dataset.piece = s.piece;
  if (s.eligible === false && !s.private) r.dataset.draft = '1';
  const out = [r];
  if (!s.private && !o.compact) out.push(refs(H, s, o));
  if (o.open === key && can) out.push(options(H, s, o, n, 'change:' + n + ':' + s.slot));
  return out;
}

/** The rows of one look (or two: compare), each with its title and its draft line. */
export function items(host, looks, o) {
  const H = o.H, list = (Array.isArray(looks) ? looks : [looks]).filter(Boolean);
  if (o.summary && list.length) { // row 388's card in 3D: the pieces in one line, and a draft said
    const d = draft(list[0]), line = H.mk('p', 'sfine tr-sum', clean(names(list[0], {}).join(' \u00b7 '), 400));
    host.replaceChildren(line, ...(d ? [H.mk('p', 'snote warn', d + ': this look can\u2019t be confirmed until it is ready.')] : []));
    return;
  }
  const cols = list.map((look, i) => {
    const col = H.mk('div', 'tr-col');
    col.dataset.look = String(i);
    if (o.titles && o.titles[i]) col.append(H.mk('p', 'snote', clean(o.titles[i], 80)));
    worn(look, o.layers).forEach((s) => col.append(...row(H, s, o, i)));
    const d = draft(look);
    if (d) col.append(H.mk('p', 'snote warn', d + ': this look can\u2019t be confirmed for the event until it is ready.'));
    return col;
  });
  if (cols.length > 1) { const pair = H.mk('div', 'tr-pair'); pair.append(...cols); host.replaceChildren(pair); } else host.replaceChildren(...cols);
}

function dayWords(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return '';
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return DAYS[d.getUTCDay()] + ' ' + (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1];
}
/** The look by its pieces for A's GET /v1/tryon/look ("pieces=slot:wi_...,..."), in a plan's context when one is given. */
export const query = (list, plan) => 'pieces=' + encodeURIComponent(list.map((p) => p.slot + ':' + p.piece).join(','))
  + (plan ? '&plan=' + encodeURIComponent(plan) : '');
/** "Today \u00b7 10:00 \u00b7 business formal": a plan's title. */
export const planTitle = (day, p) => [day, hhmm(p.starts), String(p.dress_code || '').replace(/_/g, ' ')].filter(Boolean).join(' \u00b7 ');
/** Tomorrow's date (yyyy-mm-dd) in this device's own time. */
export const tomorrowIso = () => { const d = new Date(Date.now() + 864e5); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
/** A time in his words (the console's own when()), else the ISO date and time. */
export const when = (iso) => (window.JarvisMobile && window.JarvisMobile.when ? window.JarvisMobile.when(iso, true) : String(iso || '').slice(0, 16).replace('T', ' '));
/** "10:00": an event's start in this device's own time (his zone), or "" */
export function hhmm(iso) {
  const d = typeof iso === 'string' && iso ? new Date(iso) : null;
  return d && !isNaN(d) ? String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') : '';
}
function names(look, opt) { // each worn piece once in fixed words, "Base layer (covered)" for a private slot
  const seen = new Set(), out = [];
  worn(look, opt.layers || 'all').forEach((s) => {
    const own = opt.own && s.piece && typeof opt.nameOf === 'function' ? clean(opt.nameOf(s.piece), 40) : '';
    const w = s.private ? COVERED : upper(own || clean(s.words, 40));
    if (w && !seen.has(w)) { seen.add(w); out.push(w); }
  });
  return out;
}
/** The caption's lines (fixed words only; never an id, never a private piece's own words). */
export function caption(look, o) {
  const opt = o || {}, out = [], list = names(look, opt);
  out.push([dayWords(look && look.day), hhmm(opt.starts)].filter(Boolean).join(' \u00b7 ') || 'This look');
  for (let i = 0; i < list.length; i += PER_LINE) out.push(list.slice(i, i + PER_LINE).join(' \u00b7 '));
  return out.map((x) => clean(x, 120)).filter(Boolean);
}
