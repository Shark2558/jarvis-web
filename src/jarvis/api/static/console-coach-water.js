// src/jarvis/api/static/console-coach-water.js -- R8 builder D, row 248 (docs/plans/r8-vision.md v8.0.4 section 2.1):
// the water-intake logger at the desk webcam. Use case `water`: `hands` and `objects` (cup, bottle, wine_glass) at up
// to 2 a second, one state. A sip is a cup (or bottle, or glass) held in a hand and raised to the lips -- its box spans
// the mouth's height, near the mouth -- for at least MIN_DWELL_S, then lowered. The mouth is placed in the `person` box
// the object model also gives (a third of the way down it), or, with no person box, in the frame's upper middle. A
// lowered cup ends a sip at once; a cup the hand hides for a moment (it happens at the lips) gets GRACE_S. A cup moved
// on the desk, a phone raised, a hand to the face with nothing in it, or a cup lifted only to the chest is not a sip.
// Every SIPS_PER_GLASS sips is one glass (a Result's `setup.sips_per_glass`, 4 to 20, if the pane passes one). The pane
// adds each new glass to his water log (POST through jarvis.coach.water's WaterLog) with Undo; this module keeps
// nothing and sends nothing. A use case, held to the guard (tests/r7_jsguard.py); its tally is WaterTally.
// View widgets: big {n, word}, line {text}.
const DRINKS = Object.freeze(['cup', 'bottle', 'wine_glass']);
const SCORE_MIN = 0.4;
const MIN_DWELL_S = 0.5; // at 2 a second: two frames at the lips (a hidden one counts once the cup was seen there)
const MAX_DWELL_S = 30; // longer is not a sip (a cup held up to look at, a long draught is still one)
const GRACE_S = 2.5; // a cup the hand hides at the lips (five frames at 2 a second)
const HANDS_FRESH_S = 3; // a hands Result this recent decides whether a hand holds the cup
const SIPS_PER_GLASS = 8;
const GLASSES_MAX = 30;
const WORDS = Object.freeze({
  glasses: 'glasses',
  how: 'Counted when a cup or bottle reaches your lips.',
  fix: 'A glass is added to your water log; you can undo it.',
});

const clock = (r) => (Number.isFinite(r.t) ? r.t : performance.now() / 1000 - (Number(r.ms) || 0) / 1000);
const best = (things, labels) => things.filter((o) => labels.includes(o.label) && o.score >= SCORE_MIN)
  .reduce((b, o) => (!b || o.score > b.score ? o : b), null);
const grow = (b, m) => ({ x: b.x - m, y: b.y - m, w: b.w + 2 * m, h: b.h + 2 * m });
const meets = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
function handBox(h) {
  const ps = Array.isArray(h.points) ? h.points : [];
  if (!ps.length) return null;
  const xs = ps.map((p) => p.x), ys = ps.map((p) => p.y);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}
function mouthOf(person) {
  if (!person) return { x: 0.5, y: 0.3, span: 0.25 };
  const b = person.box;
  return { x: b.x + b.w / 2, y: b.y + b.h / 3, span: Math.max(0.08, b.w * 0.35) };
}
function atLips(drink, mouth) {
  const b = drink.box;
  const spans = b.y <= mouth.y + 0.04 && b.y + b.h >= mouth.y - 0.04; // the cup's box covers the mouth's height
  return spans && Math.abs(b.x + b.w / 2 - mouth.x) <= b.w / 2 + mouth.span;
}

function perGlass(r) {
  const n = r.setup && Number.isInteger(r.setup.sips_per_glass) ? r.setup.sips_per_glass : SIPS_PER_GLASS;
  return Math.min(20, Math.max(4, n));
}

function end(s, t) { // the cup came down (or stayed hidden): a sip if it was at the lips long enough
  const dwell = Math.max(s.lastIn, s.hiddenTo) - s.since; // a frame the hand hid the cup in, at the lips, counts
  const sip = dwell >= MIN_DWELL_S && dwell <= MAX_DWELL_S;
  return Object.assign({}, s, { up: false, sips: s.sips + (sip ? 1 : 0), endedAt: t });
}

function look(s, r, t) { // one objects Result
  const things = r.ok && r.data && Array.isArray(r.data.objects) ? r.data.objects : [];
  const drink = best(things, DRINKS), person = best(things, ['person']);
  const fresh = s.handsAt !== null && t - s.handsAt <= HANDS_FRESH_S;
  const held = !!drink && (!fresh || s.handBoxes.some((h) => meets(grow(h, 0.04), drink.box)));
  const inLips = !!drink && held && atLips(drink, mouthOf(person));
  if (inLips) return s.up ? Object.assign({}, s, { lastIn: t }) : Object.assign({}, s, { up: true, since: t, lastIn: t, hiddenTo: t });
  if (!s.up) return s;
  if (!drink && t - s.lastIn <= GRACE_S) return Object.assign({}, s, { hiddenTo: t });
  const lowered = !!drink && !atLips(drink, mouthOf(person));
  return lowered || t - s.lastIn > GRACE_S ? end(s, t) : s;
}

function onResult(r, state) {
  if (!r || (r.task !== 'objects' && r.task !== 'hands')) return state;
  const t = clock(r), at = Number.isInteger(r.at) ? r.at : 0;
  const s = Object.assign({}, state || { began: at, at, up: false, since: 0, lastIn: 0, hiddenTo: 0, sips: 0, endedAt: 0,
    handsAt: null, handBoxes: [], per: perGlass(r) }, { at: Math.max((state && state.at) || at, at) });
  if (r.task === 'hands') {
    const hs = r.ok && r.data && Array.isArray(r.data.hands) ? r.data.hands : [];
    return Object.assign({}, s, { handsAt: t, handBoxes: hs.map(handBox).filter((b) => b !== null) });
  }
  return look(s, r, t);
}

function summary(s) {
  if (!s) return { view: [{ kind: 'big', n: 0, word: WORDS.glasses }, { kind: 'line', text: WORDS.how }], tally: null };
  const glasses = Math.min(GLASSES_MAX, Math.floor(s.sips / s.per));
  const view = [
    { kind: 'big', n: glasses, word: WORDS.glasses },
    { kind: 'line', text: `${s.sips} ${s.sips === 1 ? 'sip' : 'sips'}, ${s.per} to a glass` },
    { kind: 'line', text: WORDS.how },
    { kind: 'line', text: WORDS.fix },
  ];
  return { view, tally: { started_at: s.began, ended_at: Math.max(s.began, s.at), sips: Math.min(500, s.sips), glasses } };
}

JarvisVision.use({ id: 'water', tasks: ['hands', 'objects'], onResult, summary });
