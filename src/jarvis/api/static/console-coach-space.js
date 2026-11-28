// src/jarvis/api/static/console-coach-space.js -- R8.1 builder E, row 223 (HF-22, the home workout space clearance
// checker; docs/plans/r8-vision.md v8.0.4 section 2.2). Use case `space-check`: `objects` and `pose` at up to 2 a second,
// run once before a session from the Workout pane; it KEEPS NOTHING (jarvis.coach.usecases: no tally). He stands where
// he will exercise; the space is his width plus half his height on each side, from his knees down to the floor. A thing
// from the fixed list below whose box reaches into that space (score 0.4 or more) is in the way; the nearest one is
// named. The verdict waits for three looks and names a thing only when two of the last three saw it.
// A use case, held to the guard (tests/r7_jsguard.py): Results in, {view, tally} out; it imports nothing.
const SEEN = 0.5;
const SCORE = 0.4;
const LOOKS = 3;
const NAMES = Object.freeze({ // the things a person could trip on or knock into, and the word said for each
  chair: 'chair', couch: 'sofa', bed: 'bed', bench: 'bench', dining_table: 'table', potted_plant: 'plant',
  suitcase: 'suitcase', backpack: 'bag', handbag: 'bag', sports_ball: 'ball', bottle: 'bottle', cup: 'cup',
  bowl: 'bowl', wine_glass: 'glass', vase: 'vase', book: 'book', laptop: 'laptop', cell_phone: 'phone',
  remote: 'remote', keyboard: 'keyboard', teddy_bear: 'toy', skateboard: 'skateboard', bicycle: 'bicycle',
  umbrella: 'umbrella', baseball_bat: 'bat', tennis_racket: 'racket', frisbee: 'frisbee', scissors: 'scissors',
  knife: 'knife', dog: 'dog', cat: 'cat', clock: 'clock', toilet: 'toilet',
});
const WORDS = Object.freeze([
  'Clear: nothing in your space to trip on or hit.', 'Not clear: move the', 'Looking around you\u2026',
  'Stand where you will exercise, all of you in view.', 'Nothing here is kept.',
]);

const get = (o, k) => { const e = Object.entries(o || {}).find((x) => x[0] === k); return e ? e[1] : undefined; };
const seen = (p) => !!p && Number.isFinite(p.x) && Number.isFinite(p.y) && !(p.visibility < SEEN);

function spaceOf(points) { // his space: x from .. to, and the floor from his knees down
  const ps = points.filter(seen);
  if (ps.length < 10) return null;
  const xs = ps.map((p) => p.x), ys = ps.map((p) => p.y), h = Math.max(...ys) - Math.min(...ys);
  const knees = [points[25], points[26]].filter(seen), knee = knees.length ? knees.reduce((n, p) => n + p.y, 0) / knees.length : Math.max(...ys) - h / 4;
  return { x0: Math.min(...xs) - h / 2, x1: Math.max(...xs) + h / 2, floor: knee, cx: (Math.min(...xs) + Math.max(...xs)) / 2 };
}

function inWay(things, sp) { // the labels in his space, nearest first
  return things
    .filter((o) => o && get(NAMES, o.label) && o.score >= SCORE && o.box)
    .filter((o) => o.box.x < sp.x1 && o.box.x + o.box.w > sp.x0 && o.box.y + o.box.h >= sp.floor)
    .map((o) => ({ label: o.label, d: Math.abs(o.box.x + o.box.w / 2 - sp.cx) }))
    .sort((a, b) => a.d - b.d)
    .map((o) => o.label);
}

function onResult(r, state) {
  if (!r || !r.ok || !r.data) return state;
  const s = state || { space: null, looks: [] };
  if (r.task === 'pose' && Array.isArray(r.data.points) && r.data.points.length === 33) return Object.assign({}, s, { space: spaceOf(r.data.points) || s.space });
  if (r.task !== 'objects' || !s.space || !Array.isArray(r.data.objects)) return s;
  return Object.assign({}, s, { looks: s.looks.concat([inWay(r.data.objects, s.space)]).slice(-LOOKS) });
}

function verdict(looks) { // '' clear, else the nearest thing two of the last three looks saw
  const last = looks.slice(-LOOKS), seenIn = (x) => last.filter((l) => l.includes(x)).length;
  const firm = last.slice(-1)[0].concat(...last).find((x) => seenIn(x) >= 2);
  return firm || '';
}

function summary(s) {
  const keep = { kind: 'line', text: WORDS[4] };
  if (!s || !s.space) return { view: [{ kind: 'line', text: WORDS[3] }, keep], tally: null };
  if (s.looks.length < LOOKS) return { view: [{ kind: 'line', text: WORDS[2] }, keep], tally: null };
  const v = verdict(s.looks);
  const view = v ? [{ kind: 'tip', text: `${WORDS[1]} ${get(NAMES, v)}.` }] : [{ kind: 'line', text: WORDS[0] }];
  return { view: view.concat([keep]), tally: null };
}

JarvisVision.use({ id: 'space-check', tasks: ['objects', 'pose'], onResult, summary });
