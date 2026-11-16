// src/jarvis/api/static/console-wardrobe-pieces.js -- R13 Part D (docs/plans/r13-wardrobe.md D1, D10, INV-02, INV-11-14,
// LND-15): Helpers -> Wardrobe -> Pieces, loaded by console-helpers-wardrobe.js. Counts by category (owned and ready,
// laundry still owned, checks apart, the places without a first scan), the private basics behind "Show private basics",
// a search over his own list, each piece's state and place with its steps (to laundry, archive and remove go through
// the gateway: archive is always a card, remove waits 30 days in Recently deleted), a piece's latest verified history,
// pairs and sets with the half or part that is out, and his places. The same rules as its tab: the frame's builders
// and existing classes, textContent only, the shapes of jarvis.wardrobe.http, ASCII source.
const CATEGORY_WORDS = { tops: 'Tops', bottoms: 'Bottoms', base: 'Base layers and socks', outerwear: 'Outerwear',
  traditional: 'Traditional and festive', footwear: 'Footwear', accessories: 'Accessories', activity: 'Activity and other' };
const KIND_WORDS = { registered: 'Added', seen: 'Seen', wear_started: 'Wearing', wear_done: 'Worn', deposited: 'Into the basket',
  lifted: 'Lifted out of the basket', load_started: 'Washing', dried: 'Drying', needs_prep: 'Needs pressing', returned: 'Back clean',
  sent_out: 'Sent to the laundry shop', received: 'Back from the laundry shop', damaged: 'Needs repair', repaired: 'Repaired',
  held: 'Held for a check', released: 'Released after a check', missing: 'Missing', found: 'Found', archived: 'Archived',
  restored: 'Restored', merged: 'Merged', corrected: 'Corrected', blind: 'Moved without a scan' };
const MARK_WORDS = { applied: '', duplicate: 'already so', superseded: 'older than a later scan', conflict: 'did not fit: in review',
  held: 'held for a check', voided: 'corrected', known: 'a repeat' };
const PLACE_WORDS = { storage: 'Storage', intake: 'Where new pieces come in', basket: 'Laundry basket', return: 'Where clean pieces come back', travel: 'Travel', out: 'Out of the house' };
const SHOWN = 40;
const S = { query: '', open: '', detail: null };

function counts(H, v) {
  const c = v.counts || {}, out = [];
  out.push(H.row((c.owned || 0) + ' pieces, ' + (c.ready || 0) + ' ready', (c.review ? c.review + ' wait for a quick check. ' : '') + 'Pieces in the laundry are still yours and counted.'));
  (c.by_category || []).forEach((r) => out.push(H.row(CATEGORY_WORDS[r.category] || r.category, r.owned + ' owned, ' + r.ready + ' ready')));
  if (c.pairs) out.push(H.row('Pairs', c.pairs_complete + ' of ' + c.pairs + ' complete'));
  if (c.sets) out.push(H.row('Sets', c.sets_complete + ' of ' + c.sets + ' complete'));
  if (c.places_without_baseline) out.push(H.mk('p', 'sfine', c.places_without_baseline + ' of your places have no first scan yet, so their pieces may be missing here.'));
  return out;
}
function privateRow(H, v, x) {
  const n = v.private_hidden || 0;
  const sub = x.priv ? 'Shown here only. Everywhere else they are \u201ca private basic\u201d.' : n + (n === 1 ? ' piece is' : ' pieces are') + ' hidden: shown only here, after a tap.';
  return H.row('Private basics', sub, [H.toggle('Show private basics', x.priv, (on) => x.show(on))]);
}
function matches(p, q) { return !q || [p.label, p.type, p.colour, p.pattern, p.place_words, p.state_words].join(' ').toLowerCase().replace(/_/g, ' ').includes(q); }
function pieceRow(H, p, x) {
  const sub = [p.state_words, p.place_words, p.hold ? 'held for a check' : '', p.expected_back ? 'due back ' + x.when(p.expected_back) : '',
    p.wears ? 'worn ' + p.wears + (p.wears === 1 ? ' time' : ' times') : '', p.photos && p.photos.length ? p.photos.length + ' photo' + (p.photos.length === 1 ? '' : 's') : ''].filter(Boolean).join(' \u00b7 ');
  const acts = [x.btn('Details', () => { S.open = S.open === p.id ? '' : p.id; S.detail = null; redraw(x); if (S.open) details(x, p.id); })];
  if (p.state === 'ready' || p.state === 'in_use') acts.push(x.btn('To laundry', () => x.tool('laundry_move', { step: 'basket', pieces: [p.id] }, 'In the basket.')));
  const box = H.mk('div', '');
  box.append(H.row(x.nameOf(p.id), sub), x.acts(...acts));
  if (S.open === p.id) box.append(...detailRows(H, p, x));
  return box;
}
function detailRows(H, p, x) {
  const out = [];
  const d = S.detail;
  if (!d) out.push(H.mk('p', 'snote', 'Loading\u2026'));
  else if (d.failed) out.push(H.mk('p', 'snote bad', 'Couldn\u2019t load its history.'));
  else {
    if (d.step) out.push(H.mk('p', 'sfine', 'Now: ' + H.txt(d.step, 120)));
    (d.history || []).slice(-6).reverse().forEach((e) => {
      const mark = MARK_WORDS[e.mark] || '';
      out.push(H.row((KIND_WORDS[e.kind] || 'A change') + (e.place_words ? ': ' + H.txt(e.place_words, 40) : ''), [x.when(e.at, true), e.verified ? '' : 'unverified', mark].filter(Boolean).join(' \u00b7 ')));
    });
  }
  out.push(x.acts(
    x.btn(p.state === 'archived' ? 'Restore' : 'Archive', () => x.tool('wardrobe_retire', { piece: p.id, action: p.state === 'archived' ? 'restore' : 'archive' })),
    x.btn('Remove', () => x.tool('wardrobe_remove', { piece: p.id }, 'Removed: it waits 30 days in Recently deleted.')),
  ));
  return out;
}
async function details(x, id) {
  try { S.detail = await x.detail(id); } catch (_) { S.detail = { failed: true }; }
  if (S.open === id) redraw(x);
}
let last = null;
function redraw(x) { if (last) draw(last, x); }
function pairRows(H, v, x) {
  const out = [];
  (v.pairs || []).forEach((p) => out.push(H.row('Pair: ' + p.pieces.map(x.nameOf).join(' and '), p.wearable ? 'Complete and ready' : (p.missing || []).map(x.nameOf).join(', ') + ' is not ready, so the pair waits')));
  (v.sets || []).forEach((s) => out.push(H.row('Set: ' + (H.txt(s.label, 40) || s.parts.length + ' parts'), s.wearable ? 'Complete and ready' : (s.alone || []).length ? 'Not complete; ' + s.alone.map(x.nameOf).join(', ') + ' can go alone' : 'Not complete')));
  return out;
}
function placeRows(H, v, x) {
  return (v.places || []).map((p) => H.row(H.txt(p.label, 40), (PLACE_WORDS[p.kind] || '') + (p.baseline_at ? ' \u00b7 first scan ' + x.when(p.baseline_at) : ' \u00b7 no first scan yet')));
}

/** Draw the Pieces section into `host` from the tab's context (its builders, view and steps). */
export function draw(host, x) {
  const H = x.H, v = x.view;
  last = host;
  host.replaceChildren(H.mk('h3', 'hp-h', 'Pieces'));
  if (!v) { host.append(H.empty('Your pieces will show here.')); return; }
  host.append(...counts(H, v), privateRow(H, v, x));
  const input = H.mk('input', 'minput');
  input.type = 'search'; input.maxLength = 60; input.autocomplete = 'off'; input.value = S.query;
  const list = H.mk('div', '');
  const paint = () => {
    const q = S.query.trim().toLowerCase(), found = (v.pieces || []).filter((p) => matches(p, q));
    list.replaceChildren(...found.slice(0, SHOWN).map((p) => pieceRow(H, p, x)));
    if (!found.length) list.append(H.empty(q ? 'Nothing in your wardrobe by that name.' : 'No pieces yet. Add them in Camera, Wardrobe.'));
    if (found.length > SHOWN) list.append(H.mk('p', 'sfine', 'And ' + (found.length - SHOWN) + ' more: search to find one.'));
  };
  input.addEventListener('input', () => { S.query = input.value; paint(); });
  host.append(x.field('Find a piece', input), list);
  paint();
  const pairs = pairRows(H, v, x), places = placeRows(H, v, x);
  if (pairs.length) host.append(H.mk('h3', 'hp-h', 'Pairs and sets'), ...pairs);
  if (places.length) host.append(H.mk('h3', 'hp-h', 'Places'), ...places);
}

export const WORDS = Object.freeze({ CATEGORY_WORDS, KIND_WORDS, MARK_WORDS, PLACE_WORDS });
