// src/jarvis/api/static/console-tryon-photo.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D12, D22): the THIRD pixel
// panel (tests/test_r13_seams.py PANELS), the scan module's rules: no fetch, XHR, sendBeacon, WebSocket, storage or
// innerHTML; JarvisConsole.api only to /v1/seeme...; his photo's bytes leave only through the door's person(); ASCII.
//   person(file, maxKb)  his photo for See it on me: R13's person (SSD >= 0.5) and face (UltraFace >= 0.7) tasks run on ONE
//                        bitmap of it, on this device; exactly one person and at most one face pass, then door.person(blob,
//                        {maxKb}) sends it (the door redraws it down to maxKb, else says it is too detailed and sends
//                        nothing). None or several people: "This photo should show only you". A person box under 60 % of
//                        the height: advice to step back (not a refusal). The tasks not installed: no photo is sent.
//   garment(file)        a garment he is thinking of buying: the same tasks on the whole photo and on four overlapping
//                        two-thirds of it (a small face); ANY face refuses it (no one else's face goes to Google); the
//                        tasks not installed refuse it too. It sends nothing: See it on me sends it after this says yes.
//   decide(kind, runs)   the decision alone, on the tasks' answers ({person, face} per part), for tests on recorded outputs
// JARVIS can't tell an adult from a child: the words say so. Nothing is kept: the bitmap and canvases are freed.
export const WORDS = Object.freeze({
  only: 'This photo should show only you.',
  back: 'Step back so your whole body is in the picture.',
  face: 'This photo shows a person: crop it to the garment, or use a photo of the garment alone.',
  missing: 'The photo check isn\u2019t available on this device, so nothing was sent.',
  unreadable: 'This picture can\u2019t be read here. Try a JPEG or PNG.',
  ages: 'JARVIS can\u2019t tell an adult from a child: use only your own photo. Google\u2019s own rules on pictures of people apply.',
  ok: 'Checked on this device: one person.',
  clean: 'Checked on this device: no person in it.',
});
const PERSON_TALL = 0.6, SIDE = 1600;
const Vis = () => window.JarvisVision || null;
const found = (r) => (r && r.ok && r.data && Number.isInteger(r.data.count) ? r.data : null);

/** The decision on the tasks' answers: {ok, words, advice}. A part whose tasks did not both run refuses. */
export function decide(kind, runs) {
  const list = Array.isArray(runs) ? runs : [];
  if (!list.length || list.some((r) => !found(r.person) || !found(r.face))) return { ok: false, words: WORDS.missing, advice: '' };
  if (kind === 'garment') {
    return list.some((r) => found(r.face).count > 0) ? { ok: false, words: WORDS.face, advice: '' } : { ok: true, words: WORDS.clean, advice: '' };
  }
  const p = found(list[0].person), f = found(list[0].face);
  if (p.count !== 1 || f.count > 1) return { ok: false, words: WORDS.only, advice: '' };
  const tall = Math.max(0, ...p.boxes.map((b) => Number(b.h) || 0));
  return { ok: true, words: WORDS.ok, advice: tall < PERSON_TALL ? WORDS.back : '' };
}

async function bitmapOf(file) { // ONE bitmap, redrawn once on this device: the checks look at exactly it
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, SIDE / Math.max(bmp.width, bmp.height)), cv = document.createElement('canvas');
  cv.width = Math.max(1, Math.round(bmp.width * k)); cv.height = Math.max(1, Math.round(bmp.height * k));
  cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
  bmp.close();
  return cv;
}
function parts(cv) { // the whole, and four overlapping two-thirds (a small face near full size, R13's H2)
  const w = cv.width, h = cv.height, tw = Math.ceil(w * 2 / 3), th = Math.ceil(h * 2 / 3), out = [cv];
  [[0, 0], [w - tw, 0], [0, h - th], [w - tw, h - th]].forEach(([x, y]) => {
    const t = document.createElement('canvas'); t.width = tw; t.height = th;
    t.getContext('2d').drawImage(cv, x, y, tw, th, 0, 0, tw, th);
    out.push(t);
  });
  return out;
}
async function runs(list) {
  const V = Vis(), out = [];
  if (!V || typeof V.run !== 'function') return [{ person: null, face: null }];
  for (const cv of list) {
    let person = null, face = null;
    try { person = await V.run('person', cv); face = await V.run('face', cv); } catch (_) { person = person || null; face = null; }
    out.push({ person, face });
    if (!found(person) || !found(face)) break;
  }
  return out;
}
function free(list) { list.forEach((c) => { c.width = 0; c.height = 0; }); }

async function look(file, kind) {
  if (!(file instanceof Blob) || !/^image\/(jpeg|png)$/.test(file.type || '')) return { ok: false, words: WORDS.unreadable, advice: '' };
  let cv = null;
  try { cv = await bitmapOf(file); } catch (_) { return { ok: false, words: WORDS.unreadable, advice: '' }; }
  const list = kind === 'garment' ? parts(cv) : [cv];
  try { return decide(kind, await runs(list)); } finally { free(list); }
}

/** His photo: checked here, then sent through the door only (the door redraws it down to maxKb). */
export async function person(file, maxKb) {
  const verdict = await look(file, 'me');
  if (!verdict.ok) return Object.assign({ sent: null }, verdict);
  const M = window.JarvisMobile, door = M && M.parts && M.parts.send;
  if (!door || typeof door.person !== 'function') return { ok: false, words: 'JARVIS is still starting. Try again in a moment.', advice: '', sent: null };
  try { return Object.assign({ sent: await door.person(file, { maxKb }) }, verdict); } catch (e) {
    return { ok: false, words: String((e && e.message) || 'The photo was not sent.').slice(0, 200), advice: verdict.advice, sent: null };
  }
}

/** A garment's photo: checked here; See it on me sends it only when this says ok. */
export function garment(file) { return look(file, 'garment'); }
