// src/jarvis/api/static/console-wardrobe-words.js -- R13 Part D (docs/plans/r13-wardrobe.md D7, D10, INV-05-07, INV-10):
// the plain, non-pixel arithmetic of Camera -> Wardrobe, moved out of console-wardrobe-scan.js (REVIEW-D-1 split) so the
// pixel panel keeps room. Strings and numbers in, plain data out: his own label's piece, the "seen before?" candidates
// from his fingerprints, and a care label's parsed words. No DOM, no canvas, no network, no storage, no clock. The scan
// module imports it on its first press (Start the camera, Choose a photo); tests import this very file. ASCII only.

const LABEL = /^jw1:([a-z2-7]{8})$/;
const LIKELY = 0.8, MAYBE = 0.6, TWINS = 0.03, CANDIDATES = 3;
const PRIVATE_TYPES = ['underpants', 'briefs', 'boxers', 'vest', 'undershirt', 'thermal']; // wardrobe/model.py
const FABRICS13 = ['cotton', 'linen', 'silk', 'wool', 'polyester', 'nylon', 'viscose', 'rayon', 'denim', 'leather', 'elastane', 'spandex', 'khadi'];
const CARE13 = [[/machine\s*wash/, 'machine_wash'], [/hand\s*wash/, 'hand_wash'], [/dry\s*clean/, 'dry_clean', /(?:do\s*not|don.?t)\s*dry\s*clean/],
  [/(?:do\s*not|don.?t)\s*wash/, 'do_not_wash'], [/(?:cold|30\s*\W?\s*c)\s*wash|wash\w*\s*(?:cold|at\s*30)/, 'cold_wash'],
  [/(?:warm|40\s*\W?\s*c)\s*wash|wash\w*\s*(?:warm|at\s*40)/, 'warm_wash'], [/(?:do\s*not|don.?t)\s*bleach|no\s*bleach/, 'do_not_bleach'],
  [/(?:do\s*not|don.?t)\s*tumble/, 'do_not_tumble'], [/tumble\s*dry/, 'tumble_dry', /(?:do\s*not|don.?t)\s*tumble/],
  [/line\s*dry|dry\s*in\s*(?:the\s*)?shade/, 'line_dry'], [/(?:do\s*not|don.?t)\s*iron/, 'do_not_iron'],
  [/iron\s*(?:at\s*)?low|cool\s*iron|low\s*iron/, 'iron_low', /(?:do\s*not|don.?t)\s*iron/],
  [/iron\s*(?:at\s*)?medium|warm\s*iron/, 'iron_medium', /(?:do\s*not|don.?t)\s*iron/],
  [/iron\s*(?:at\s*)?high|hot\s*iron/, 'iron_high', /(?:do\s*not|don.?t)\s*iron/], [/wash\s*dark\s*colou?rs?\s*separately|wash\s*separately/, 'wash_dark_separately']];
const SIZES = /^(?:XXS|XS|S|M|L|XL|XXL|XXXL|[2-6]XL|\d{2}(?:\s*\/\s*\d{2})?)$/;
function labelPiece(value, labels) { // his own label's piece id, or null ("not a JARVIS label": never sent or shown)
  const m = LABEL.exec(String(value || ''));
  if (!m) return null;
  const hit = (Array.isArray(labels) ? labels : []).find((l) => l && l.code === m[1] && typeof l.piece === 'string');
  return hit ? hit.piece : null;
}
function unb64(s) { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i += 1) u[i] = bin.charCodeAt(i); return u; }
function meanOf(vecs) { const m = new Float64Array(vecs[0].length); vecs.forEach((v) => v.forEach((x, i) => { m[i] += x / vecs.length; })); return m; }
function cosine(a, b, mean) {
  let d = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i += 1) { const x = a[i] - (mean ? mean[i] : 0), y = b[i] - (mean ? mean[i] : 0); d += x * y; na += x * x; nb += y * y; }
  return na && nb ? d / Math.sqrt(na * nb) : 0;
}
const band = (s) => (s >= LIKELY ? 'likely' : s >= MAYBE ? 'maybe' : 'new');
function candidates(query, prints, typeOf) { // his saved fingerprints of ONE model, centred by their mean (D7)
  if (!query || !prints.length) return { top: [], twins: false };
  const mean = prints.length >= 2 ? meanOf(prints.map((p) => p.v)) : null, best = new Map();
  prints.forEach((p) => { const s = cosine(query, p.v, mean); if (!best.has(p.piece) || s > best.get(p.piece)) best.set(p.piece, s); });
  const top = [...best].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, CANDIDATES)
    .map(([piece, s]) => ({ piece, score: Math.round(s * 1000) / 1000, band: band(s) }));
  const twins = top.length > 1 && top[0].band !== 'new' && top[0].score - top[1].score <= TWINS && typeOf(top[0].piece) === typeOf(top[1].piece);
  return { top, twins };
}
function parseLabel(text) { // only parsed forms (D7, INV-10): never the text itself; each stays unverified
  const t = String(text || '').slice(0, 2000), lower = t.toLowerCase();
  let size = null;
  const said = /\bsize\s*[:.]?\s*([0-9a-z][0-9a-z /.-]{0,11})/i.exec(t);
  const cand = said ? said[1].split(/\n/)[0].trim().toUpperCase() : (t.split(/\n/).map((x) => x.trim().toUpperCase()).find((x) => SIZES.test(x)) || null);
  if (cand && /^[0-9A-Z /.-]{1,12}$/.test(cand)) size = cand;
  const fabric = [], seenF = new Set(), re = /(\d{1,3})\s*%\s*([a-z]+)/g;
  let m;
  while ((m = re.exec(lower)) !== null) { const pct = Number(m[1]); if (FABRICS13.includes(m[2]) && pct <= 100 && !seenF.has(m[2])) { seenF.add(m[2]); fabric.push({ name: m[2], pct }); } }
  const flat = lower.replace(/\s+/g, ' '), care = [];
  CARE13.forEach(([rx, word, unless]) => { if (rx.test(flat) && !(unless && unless.test(flat)) && !care.includes(word)) care.push(word); });
  return { size, fabric, care };
}

export { LABEL, LIKELY, MAYBE, TWINS, CANDIDATES, PRIVATE_TYPES, FABRICS13, CARE13, SIZES, labelPiece, unb64, meanOf, cosine,
  band, candidates, parseLabel };
