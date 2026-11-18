// src/jarvis/api/static/console-tryon-card.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D21, row 388; D22).
// When he asks what to wear (typed or spoken), the reply carries ONE card of kind 'tryon' (ChatResponse.cards, made by
// outfit_suggest): {day, plan, code, slots: [{slot, pieces, private}]}, piece ids only, a private slot with none.
// console-media.js hands every reply's cards to window.JarvisTryOnCard.cards(row, list); this module takes the FIRST
// 'tryon' card and, with no extra tap, makes a box under the reply and has console-tryon.js draw the figure dressed in
// exactly those pieces there (inline: the look by ?pieces=, turn, layers, tuck, swap, compare, the checklist), or the
// AVT-15 checklist when 3D can't run. The card is compact (review D-1 H1): the figure, its pieces in one line and a small
// set of controls, the full view one press away in Helpers; as it lands, the reply's top stays in view (unless he has
// scrolled since), so his reply's words and the whole figure show together. A reply without the card gets nothing. It
// reads only the card (checked here:
// slot words and wi_ ids, nothing else is passed on) and asks the server for nothing itself; nothing is kept.
// garment(file): a picture shared into the app (the share tray's "See it on me (a garment to buy)") opens Helpers ->
// Wardrobe -> Try it on's See it on me with it, for his type and colour and the device check; this press sends nothing.
// When See it on me can't take it (Try-on or See it on me off, not a JPEG or PNG, over 25 MB) it throws the words.
// Loaded at start by console-r7.js. textContent only; ASCII source.
const SLOT = /^[a-z_]{2,20}$/;
const PIECE = /^wi_[0-9a-f]{12}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const PLAN = /^op_[0-9a-f]{8}$/;
const SLOTS_MAX = 12;

/** The card as console-tryon.js may use it, or null: only the fields of TryOnCard, each checked. */
function checked(c) {
  if (!c || typeof c !== 'object' || c.kind !== 'tryon' || !DAY.test(String(c.day || ''))) return null;
  const slots = (Array.isArray(c.slots) ? c.slots : []).slice(0, SLOTS_MAX).map((s) => {
    if (!s || typeof s !== 'object' || !SLOT.test(String(s.slot || ''))) return null;
    if (s.private === true) return { slot: s.slot, pieces: [], private: true };
    const pieces = (Array.isArray(s.pieces) ? s.pieces : []).filter((p) => PIECE.test(String(p))).slice(0, 2);
    return pieces.length ? { slot: s.slot, pieces, private: false } : null;
  }).filter(Boolean);
  if (!slots.some((s) => !s.private)) return null;
  return { kind: 'tryon', day: c.day, plan: PLAN.test(String(c.plan || '')) ? c.plan : null,
    code: /^[a-z_]{0,30}$/.test(String(c.code || '')) ? String(c.code || '') : '', slots };
}

function box(row) { // under the reply, in the media cards' own frame (existing components only)
  const wrap = document.createElement('div');
  wrap.className = 'mcards tr-cards';
  const sec = document.createElement('section');
  sec.className = 'mcard tr-card';
  sec.setAttribute('aria-label', 'Try it on: this look on your figure');
  wrap.append(sec);
  row.append(wrap);
  return sec;
}

const HIS = ['wheel', 'touchstart', 'pointerdown', 'keydown']; // his own ways to move the conversation
function watch(scroller) { // has he moved the conversation himself since the reply landed?
  const his = { moved: false, off: () => {} };
  if (!scroller) return his;
  const mark = () => { his.moved = true; };
  HIS.forEach((t) => scroller.addEventListener(t, mark, { passive: true }));
  his.off = () => HIS.forEach((t) => scroller.removeEventListener(t, mark));
  return his;
}
function inView(row, scroller, his) { // the reply's top kept in view as the card lands (never past the bottom)
  his.off();
  if (!scroller || his.moved) return; // he has moved it since: leave it where he put it
  const top = row.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop = Math.min(scroller.scrollHeight - scroller.clientHeight, scroller.scrollTop + top);
}

function cards(row, list) {
  if (!row || !Array.isArray(list)) return;
  const card = checked(list.find((c) => c && typeof c === 'object' && c.kind === 'tryon'));
  if (!card || row.querySelector('.tr-card')) return;
  const el = box(row), scroller = document.getElementById('scroll'), his = watch(scroller);
  import('./console-tryon.js').then((m) => m.inline(el, card)).then(() => inView(row, scroller, his), () => {
    his.off();
    el.textContent = '';
    const p = document.createElement('p');
    p.className = 'sfine';
    p.textContent = 'The try-on card couldn\u2019t load. The outfit is in Helpers, Wardrobe.';
    el.append(p);
  });
}

const FILE_MAX = 25 * 1024 * 1024; // over this a phone may run out of memory decoding it (review D-1 L7)
const STAYS = ' The picture stays here.';
const CANT = Object.freeze({ // why See it on me can't take a shared picture now, and what he can do
  tryon_off: 'Try it on is off on this JARVIS, so See it on me can\u2019t take this picture. To switch it on, set JARVIS_TRYON_ENABLED=true on the server and restart it.',
  tryon_down: 'Try it on can\u2019t load right now: try again in a moment.',
  seeme_off: 'See it on me is off: switch it on under See it on me settings in Helpers, Wardrobe, Try it on.',
  seeme_down: 'See it on me can\u2019t load right now: try again in a moment.',
  offline: 'Can\u2019t reach JARVIS. Check your connection.',
});
/** Hands a shared picture to See it on me, or throws the words that say why it can't take it (review D-1 M6): the share
 *  tray keeps the picture and shows them, never deleting it in silence. This sends nothing. */
async function garment(file) {
  if (!(file instanceof Blob) || !/^image\/(jpeg|png)$/.test(file.type || '')) throw new Error('See it on me takes a JPEG or PNG photo of the garment.' + STAYS);
  if (file.size > FILE_MAX) throw new Error('This picture is over 25 MB: share a smaller photo of the garment.' + STAYS);
  const m = await import('./console-tryon.js');
  const r = await m.garment(file);
  if (!r || !r.ok) throw new Error(String((r && r.why) || (r && CANT[r.code]) || 'See it on me couldn\u2019t take this picture.').slice(0, 240) + STAYS);
}

window.JarvisTryOnCard = Object.freeze({ cards, garment });
