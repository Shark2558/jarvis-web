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
async function prepared(file) {
  if (!isPicture(file)) return file;
  const F = window.JarvisFixes && window.JarvisFixes.parts && window.JarvisFixes.parts.files;
  if (!F || typeof F.shrink !== 'function') throw new Error(NOT_READY);
  let small = null;
  try { small = await F.shrink(file); } catch (_) { small = null; }
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

const line = () => 'Pictures sent from this device today: ' + readCount();

if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, sentToday: readCount, line }));
