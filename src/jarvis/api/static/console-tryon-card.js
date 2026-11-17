// src/jarvis/api/static/console-tryon-card.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D21, row 388; D22).
// When he asks what to wear (typed or spoken), the reply carries ONE card of kind 'tryon' (ChatResponse.cards, made by
// outfit_suggest): {day, plan, code, slots: [{slot, pieces, private}]}, piece ids only, a private slot with none.
// console-media.js hands every reply's cards to window.JarvisTryOnCard.cards(row, list); this module takes the FIRST
// 'tryon' card and, with no extra tap, makes a box under the reply and has console-tryon.js draw the figure dressed in
// exactly those pieces there (inline: the look by ?pieces=, turn, layers, tuck, swap, compare, the checklist), or the
// AVT-15 checklist when 3D can't run. A reply without the card gets nothing. It reads only the card (checked here:
// slot words and wi_ ids, nothing else is passed on) and asks the server for nothing itself; nothing is kept.
// garment(file): a picture shared into the app (the share tray's "See it on me (a garment to buy)") opens Helpers ->
// Wardrobe -> Try it on's See it on me with it, for his type and colour and the device check; this press sends nothing.
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
  wrap.className = 'mcards';
  const sec = document.createElement('section');
  sec.className = 'mcard tr-card';
  sec.setAttribute('aria-label', 'Try it on: this look on your figure');
  wrap.append(sec);
  row.append(wrap);
  return sec;
}

function cards(row, list) {
  if (!row || !Array.isArray(list)) return;
  const card = checked(list.find((c) => c && typeof c === 'object' && c.kind === 'tryon'));
  if (!card || row.querySelector('.tr-card')) return;
  const el = box(row);
  import('./console-tryon.js').then((m) => m.inline(el, card)).catch(() => {
    el.textContent = '';
    const p = document.createElement('p');
    p.className = 'sfine';
    p.textContent = 'The try-on card couldn\u2019t load. The outfit is in Helpers, Wardrobe.';
    el.append(p);
  });
}

async function garment(file) {
  if (!(file instanceof Blob)) return;
  const m = await import('./console-tryon.js');
  m.garment(file);
}

window.JarvisTryOnCard = Object.freeze({ cards, garment });
