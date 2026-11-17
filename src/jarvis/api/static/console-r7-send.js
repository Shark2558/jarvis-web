// src/jarvis/api/static/console-r7-send.js -- R7 I0 (docs/plans/r7-mobile.md D12, D15, seam 25): the ONE door a
// picture takes to the server from the share tray (Part A) and the Camera panel (Part B). Neither builds its own.
//   canAsk() -> {ok, why}       "Ask the AI about this photo" is offered only when the brain answering now sees
//                               pictures (JarvisConsole.brain().sees); otherwise `why` is the line to show
//   ask(file, text) -> Promise<bool>   attach the picture and send `text` with it (R11.1's picture path; the cost
//                               line comes from R11.1's cost() inside JarvisChat.send); refused (false) when the
//                               brain can't see, nothing sent
//   attach(files) -> Promise<n> the paperclip's own path: JarvisAttach.add(files), each picture first redrawn
//   vault(file) -> Promise<item|null>  the usual vault proposal (POST /v1/vault/upload), for him to confirm
//   sentToday() -> n            pictures this device sent today; line() -> "Pictures sent from this device today: n"
//   wardrobe(blob, {piece, view}), tag(blob, {piece}) -> Promise<json>   R13 D9: Camera -> Wardrobe's only two ways
//                               to send a picture: a saved piece's crop (POST /v1/wardrobe/photos) and its AI tag
//   person(blob, {maxKb}) -> Promise<json>   R13.1 D12: his photo for See it on me (POST /v1/seeme/photo), redrawn down
//                               to maxKb (GET /v1/seeme's photo_max_kb); picture(id), myPhoto() -> data: URLs, read back
//   garment(blob, {type, colour, maxKb}), garmentPhoto(id)   R13.1 D22: a garment he may buy (POST /v1/seeme/garments)
// Every picture is first redrawn on this device by R11.1's shrink (JarvisFixes.parts.files.shrink): JPEG of at
// most 1,568 px, so a WebP or a full-size photo is never sent as it is; one the browser can't read is refused in
// plain words. The counter lives only in this browser (localStorage, per day). Nothing here runs before a press.
const M = window.JarvisMobile;
const KEY = 'jarvis_r7_sent_v1';
const CANT_SEE = 'The brain answering now can’t see pictures.';
const UNREADABLE = 'This picture can’t be read here. Try a JPEG or PNG.';
const UNPREPARED = 'That picture could not be prepared on this device, so it was not sent, Sir.';
const NOT_READY = 'JARVIS is still starting. Try again in a moment.';
const PICTURE_TYPES = ['image/jpeg', 'image/png'];
const WAIT_MS = 60000;

const today = () => new Date().toISOString().slice(0, 10);
function readCount() {
  try {
    const o = JSON.parse(localStorage.getItem(KEY) || 'null');
    return o && o.day === today() && Number.isInteger(o.n) && o.n >= 0 ? o.n : 0;
  } catch (_) { return 0; }
}
function bump(by) {
  const n = readCount() + by;
  try { localStorage.setItem(KEY, JSON.stringify({ day: today(), n })); } catch (_) {}
  document.dispatchEvent(new CustomEvent('jarvis:pictures-sent', { detail: { n } }));
  return n;
}
const isPicture = (f) => !!f && (/^image\//.test(f.type || '') || /\.(png|jpe?g|webp)$/i.test(f.name || ''));

/** A picture redrawn on this device (R11.1's shrink), or a plain refusal. Other files pass unchanged. */
async function prepared(file, opts) {
  if (!isPicture(file)) return file;
  const F = window.JarvisFixes && window.JarvisFixes.parts && window.JarvisFixes.parts.files;
  if (!F || typeof F.shrink !== 'function') throw new Error(NOT_READY);
  let small = null;
  try { small = await F.shrink(file, opts); } catch (_) { small = null; }
  if (!small || small === file) throw new Error(UNPREPARED); // not redrawn (null, or the very same file): never sent as it is
  if (!PICTURE_TYPES.includes(small.type) || !/\.(png|jpe?g)$/i.test(small.name || '')) throw new Error(UNREADABLE);
  return small;
}

function canAsk() {
  const con = window.JarvisConsole, brain = con && typeof con.brain === 'function' ? con.brain() : null;
  return brain && brain.sees === true ? { ok: true, why: '' } : { ok: false, why: CANT_SEE };
}

async function attach(files) {
  const A = window.JarvisAttach;
  if (!A || typeof A.add !== 'function') throw new Error(NOT_READY);
  const ready = [];
  for (const f of Array.from(files || [])) ready.push(await prepared(f));
  if (!ready.length) return 0;
  A.add(ready);
  const pictures = ready.filter(isPicture).length;
  if (pictures) bump(pictures);
  return ready.length;
}

function settled() {
  const A = window.JarvisAttach, until = Date.now() + WAIT_MS;
  return new Promise((resolve) => {
    const tick = () => (!A.busy() || Date.now() > until ? resolve(!A.busy()) : setTimeout(tick, 250));
    tick();
  });
}

async function ask(file, text) {
  if (!canAsk().ok) return false; // refused before anything leaves the device
  const C = window.JarvisChat;
  if (!C || typeof C.send !== 'function' || typeof text !== 'string' || !text.trim()) return false;
  await attach([file]);
  if (!(await settled())) return false;
  return C.send(text.trim());
}

async function vault(file) {
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
  const doc = await prepared(file);
  const r = await chat.raw('/v1/vault/upload', { method: 'POST', body: doc, headers: { 'Content-Type': doc.type || 'application/octet-stream' } });
  let j = null;
  try { j = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((j && typeof j.detail === 'string' && j.detail) || 'The upload did not work. Please try again.');
  if (isPicture(doc)) bump(1);
  if (window.JarvisVault && typeof window.JarvisVault.refresh === 'function') window.JarvisVault.refresh();
  if (window.JarvisDeck && typeof window.JarvisDeck.open === 'function') window.JarvisDeck.open('vault', { focus: true });
  return j && j.item ? j.item : null;
}

// R13 I0 (docs/plans/r13-wardrobe.md D9): redrawn and counted like every picture; piece and view checked first.
const PIECE = /^wi_[0-9a-f]{12}$/;
const VIEWS = ['front', 'back', 'detail'];
const NOT_A_PIECE = 'That photo is not for a saved piece, so it was not sent, Sir.';
async function postPicture(path, blob, opts) {
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
  const file = blob instanceof File ? blob : new File([blob], 'piece.jpg', { type: 'image/jpeg' });
  const doc = await prepared(file, opts);
  if (doc.type !== 'image/jpeg') throw new Error(UNREADABLE);
  if (opts && opts.maxKb > 0 && doc.size > opts.maxKb * 1024) throw new Error(TOO_DETAILED); // nothing sent (M7)
  const r = await chat.raw(path, { method: 'POST', body: doc, headers: { 'Content-Type': 'image/jpeg' } });
  let j = null;
  try { j = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((j && typeof j.detail === 'string' && j.detail) || 'The upload did not work. Please try again.');
  bump(1);
  return j;
}
function wardrobe(blob, meta) {
  const m = meta || {};
  if (!PIECE.test(String(m.piece || '')) || !VIEWS.includes(m.view)) return Promise.reject(new Error(NOT_A_PIECE));
  return postPicture('/v1/wardrobe/photos?piece=' + m.piece + '&view=' + m.view, blob);
}
function tag(blob, meta) {
  const m = meta || {};
  if (!PIECE.test(String(m.piece || ''))) return Promise.reject(new Error(NOT_A_PIECE));
  return postPicture('/v1/wardrobe/tag?piece=' + m.piece, blob);
}

const PHOTO = /^wh_[0-9a-f]{12}$/;
async function dataUrl(path) { // a picture read back, as a data: URL for an <img> (blob: is not in img-src)
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
  const r = await chat.raw(path);
  if (!r.ok) throw new Error('That photo could not be shown.');
  const b = await r.blob();
  return new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(String(f.result)); f.onerror = no; f.readAsDataURL(b); });
}
async function thumb(id) { // a saved crop
  if (!PHOTO.test(String(id || ''))) throw new Error(NOT_READY);
  return dataUrl('/v1/wardrobe/photos/' + id);
}
// R13.1 I0 (D12, D22, M7): his photo, and a new garment's photo (never a wardrobe piece): JPEG and at most maxKb, else nothing is sent.
const TOO_DETAILED = 'This photo is too detailed to send: try a plainer background.';
const WORD = /^[a-z_]{2,20}$/, no = () => Promise.reject(new Error(NOT_READY));
const jpegTo = (path, blob, kb) => (Number(kb) >= 100 && Number(kb) <= 740 ? postPicture(path, blob, { maxKb: Number(kb), jpeg: true }) : no());
const person = (blob, meta) => jpegTo('/v1/seeme/photo', blob, (meta || {}).maxKb);
const garment = (blob, m) => (m && WORD.test(String(m.type)) && WORD.test(String(m.colour)) ? jpegTo('/v1/seeme/garments?type=' + m.type + '&colour=' + m.colour, blob, m.maxKb) : no());
const readBack = (re, path) => (id) => (re.test(String(id || '')) ? dataUrl(path + id) : no());
const picture = readBack(/^tp_[0-9a-f]{12}$/, '/v1/seeme/pictures/'), garmentPhoto = readBack(/^tg_[0-9a-f]{12}$/, '/v1/seeme/garments/');
const myPhoto = () => dataUrl('/v1/seeme/photo');
async function drop(id) { // one photo, deleted
  const chat = window.JarvisChat;
  if (!PHOTO.test(String(id || '')) || !chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
  const r = await chat.raw('/v1/wardrobe/photos/' + id, { method: 'DELETE' });
  if (!r.ok) throw new Error('That photo could not be deleted.');
}
const line = () => 'Pictures sent from this device today: ' + readCount();

if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto, sentToday: readCount, line }));
