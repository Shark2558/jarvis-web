// src/jarvis/api/static/console-r111-files.js -- R11.1 Part B (docs/plans/r11-1-observations.md D8-D12):
// what the Conversation panel gains for voice and files. Loaded by console-r111.js (an ES module); built with
// window.JarvisFixes (mk, api, part) and the console's existing classes (.bfine, .bnote, .btn, .clip);
// textContent only; ASCII source; its stylesheet only places things (D0).
//   understand({heard, alternatives, confidence, files, session}) -> {understood, changed, sure, question}
//       POST /v1/input/understand. Any failure answers "as heard": a spoken turn is never blocked by it.
//   heard(row, heard, understood)   the "Heard / Understood as" lines under a spoken message
//   cost({text, files, brain, send, cancel}) -> {wait}   large or complex files: POST /v1/input/estimate and,
//       from 5 rupees up, the line above Send with the two tiers; the owner chooses, then it is sent
//   shrink(file) -> file   a picture made smaller in the browser before upload (longest side and weight from
//       GET /v1/input; a canvas re-draw, which also drops camera and location data)
//   folder(fileList) -> {blob, name, count, left}   a picked folder's readable files as ONE stored zip
//   limits() -> what GET /v1/input said (accept list, files a message, megabytes); console-attach.js is told
//   hints() -> this turn's recognition hints, for console-voice-phrases.js
// It also adds the folder button beside the paperclip (where the browser can pick a folder) and keeps the
// browser recogniser's per-turn hints fresh (GET /v1/input/hints) where it takes hints at all.
const F = window.JarvisFixes;
const $ = (id) => document.getElementById(id);
const TIERS = ['fast', 'balanced', 'strong'];
const ARCHIVES = ['.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.jar', '.iso'];
const PICTURE = /\.(png|jpe?g)$/i;
const JPEG_TRIES = [0.85, 0.7, 0.55, 0.4];
const LARGE = { chars: 40000, sheets: 3, rows: 2000, pictures: 2 };
const UNDERSTAND_WAIT_MS = 8000;
const NS = 'http://www.w3.org/2000/svg';
const FOLDER_ICON = 'M2.8 6.2a1.6 1.6 0 0 1 1.6-1.6h3.3l1.7 1.9h6.2a1.6 1.6 0 0 1 1.6 1.6v6.1a1.6 1.6 0 0 1-1.6 1.6H4.4a1.6 1.6 0 0 1-1.6-1.6z';
let limits = Object.freeze({ accept: ['.pdf', '.docx', '.txt', '.md', '.markdown', '.csv', '.xlsx', '.xlsm', '.xls', '.pptx',
  '.png', '.jpg', '.jpeg', '.zip'], max_files: 10, file_mb: 10, total_mb: 40, folder_max_files: 50, zip_max_files: 50,
picture_max_kb: 900, picture_side: 1568, max_pictures: 4 });
let understandOn = true;

const num = (v) => (Number.isFinite(v) && v > 0 ? v : 0);
const extOf = (name) => { const i = String(name).lastIndexOf('.'); return i > 0 ? String(name).slice(i).toLowerCase() : ''; };
function sizeText(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---- limits: the accept list and the caps come from the server, never from the page ---------------------------
function takeLimits(j) {
  const l = j && j.limits;
  if (!l || !Array.isArray(l.accept) || !l.accept.every(x => typeof x === 'string' && /^\.[a-z0-9]{1,8}$/.test(x))) return;
  const next = { accept: l.accept.slice(0, 40) };
  ['max_files', 'file_mb', 'total_mb', 'folder_max_files', 'zip_max_files', 'picture_max_kb', 'picture_side', 'max_pictures']
    .forEach(k => { next[k] = Number.isInteger(l[k]) && l[k] > 0 ? l[k] : limits[k]; });
  limits = Object.freeze(next);
  understandOn = j.understand !== false;
  const A = window.JarvisAttach;
  if (A && typeof A.configure === 'function') A.configure(limits);
}
async function loadLimits() { try { takeLimits(await F.api('/v1/input')); } catch (_) {} }

// ---- heard / understood as ------------------------------------------------------------------------------------
async function ask(o, heard) {
  const body = { heard: heard.slice(0, 2000) };
  if (Array.isArray(o.alternatives)) body.alternatives = o.alternatives.filter(x => typeof x === 'string' && x.trim()).slice(0, 3).map(x => x.slice(0, 2000));
  if (Array.isArray(o.files)) body.files = o.files.map(f => String((f && f.name) || '').slice(0, 300)).filter(Boolean).slice(0, 20);
  if (typeof o.session === 'string' && o.session) body.session_id = o.session;
  if (Number.isFinite(o.confidence) && o.confidence >= 0 && o.confidence <= 1) body.confidence = o.confidence;
  const r = await F.api('/v1/input/understand', { body });
  if (!r || typeof r.understood !== 'string' || !r.understood.trim()) return null;
  const question = typeof r.question === 'string' && r.question && r.question.length <= 400 ? r.question : null;
  return { understood: r.understood, changed: r.changed === true, sure: r.sure !== false && !question, question };
}
async function understand(o) {
  const heard = String((o && o.heard) || '');
  const same = { understood: heard, changed: false, sure: true, question: null };
  if (!understandOn || !heard.trim()) return same;
  const late = new Promise(resolve => { setTimeout(() => resolve(null), UNDERSTAND_WAIT_MS); });
  try { return (await Promise.race([ask(o || {}, heard), late])) || same; } catch (_) { return same; }
}
function heard(row, said, understood) {
  if (!row || typeof said !== 'string' || !said.trim() || typeof understood !== 'string') return;
  if (row.querySelector('.r111f-heard')) return; // already shown (console.js marks the row; see heardRows)
  const box = F.mk('div', 'r111f-heard');
  box.setAttribute('role', 'note');
  box.append(F.mk('p', 'bfine', 'Heard: ' + said), F.mk('p', 'bfine', 'Understood as: ' + understood));
  row.appendChild(box);
}

/** Rows restored before this module arrived carry data-heard (console.js): give them their lines now. */
function heardRows() {
  document.querySelectorAll('.row.user[data-heard]').forEach((row) => {
    const bubble = row.querySelector('.bubble');
    heard(row, row.dataset.heard, bubble ? bubble.textContent || '' : '');
  });
}

// ---- the rupee estimate before a costly reply -------------------------------------------------------------------
function isLarge(files) {
  let chars = 0, pictures = 0, complex = false;
  files.forEach(f => {
    const m = (f && f.meta) || {};
    chars += num(m.chars); pictures += num(m.pictures);
    if (num(m.sheets) > LARGE.sheets || num(m.rows) > LARGE.rows) complex = true;
  });
  return complex || chars > LARGE.chars || pictures > LARGE.pictures;
}
function hideCost() { const old = $('r111fCost'); if (old) old.remove(); }
function costButton(label, primary, run) {
  const b = F.mk('button', 'btn bact' + (primary ? ' primary' : ''), label);
  b.type = 'button';
  b.addEventListener('click', () => { hideCost(); run(); });
  return b;
}
function showCost(e, o) {
  hideCost();
  const form = $('form');
  if (!form || !form.parentNode) return false;
  const box = F.mk('div', 'bnote r111f-cost'); box.id = 'r111fCost';
  box.setAttribute('role', 'group'); box.setAttribute('aria-label', 'Cost before sending');
  const line = F.mk('p', 'r111f-line', e.line + ' Choose how to send it.'); line.id = 'r111fCostLine';
  const acts = F.mk('div', 'r111f-acts');
  const first = costButton(`Send on the ${e.tier} tier`, e.suggest !== e.stronger_tier, () => o.send({ tier: e.tier }));
  acts.append(first);
  if (e.stronger_tier) acts.append(costButton('Send on the stronger tier', e.suggest === e.stronger_tier, () => o.send({ tier: e.stronger_tier })));
  acts.append(costButton('Cancel', false, () => { if (typeof o.cancel === 'function') o.cancel(); }));
  acts.querySelectorAll('button').forEach(b => b.setAttribute('aria-describedby', 'r111fCostLine'));
  box.append(line, acts);
  form.parentNode.insertBefore(box, form);
  (acts.querySelector('.primary') || first).focus();
  return true;
}
async function cost(o) {
  hideCost();
  if (!o || !Array.isArray(o.files) || !o.files.length || typeof o.send !== 'function' || !isLarge(o.files)) return { wait: false };
  let e = null;
  try {
    e = await F.api('/v1/input/estimate', { body: { attachments: o.files.map(f => f.id), message: String(o.text || '').slice(0, 100000),
      brain: typeof o.brain === 'string' ? o.brain : null } });
  } catch (_) { return { wait: false }; }
  const ok = e && e.show === true && typeof e.line === 'string' && e.line.length <= 200 && e.line.includes('\u20b9') &&
    TIERS.includes(e.tier) && (e.stronger_tier === null || TIERS.includes(e.stronger_tier));
  return { wait: ok ? showCost(e, o) : false };
}

// ---- pictures: made smaller here, before they leave the browser -----------------------------------------------
function drawn(bmp, w, h) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d');
  if (!g) return null;
  g.fillStyle = 'white'; g.fillRect(0, 0, w, h); // a see-through PNG becomes a JPEG on white
  g.drawImage(bmp, 0, 0, w, h);
  return c;
}
async function shrink(file) {
  if (!file || !PICTURE.test(file.name || '') || typeof createImageBitmap !== 'function') return file;
  let bmp = null;
  try { bmp = await createImageBitmap(file); } catch (_) { return file; } // not a picture this browser can read: the server says so
  const side = limits.picture_side, most = limits.picture_max_kb * 1024;
  const scale = Math.min(1, side / Math.max(bmp.width, bmp.height, 1));
  if (scale === 1 && file.size <= most) { if (bmp.close) bmp.close(); return file; } // small enough already
  const c = drawn(bmp, Math.max(1, Math.round(bmp.width * scale)), Math.max(1, Math.round(bmp.height * scale)));
  if (bmp.close) bmp.close();
  if (!c) return file;
  for (const q of JPEG_TRIES) {
    const blob = await new Promise(resolve => c.toBlob(resolve, 'image/jpeg', q));
    if (blob && blob.size <= most) return new File([blob], String(file.name).replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' });
  }
  return file;
}

// ---- a folder: its readable files as one stored (uncompressed) zip ----------------------------------------------
const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
function crc32(u8) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
/** One header: `local` (30 bytes before the data) or central (46 bytes in the directory at the end). */
function zipHeader(local, crc, size, nameLen, offset) {
  const v = new DataView(new ArrayBuffer(local ? 30 : 46)), at = local ? 0 : 2;
  v.setUint32(0, local ? 0x04034b50 : 0x02014b50, true);
  if (!local) v.setUint16(4, 20, true);
  v.setUint16(4 + at, 20, true); v.setUint16(6 + at, 0x0800, true); // UTF-8 names; method 0 = stored
  v.setUint16(12 + at, 0x21, true); // 1 Jan 1980: no real date leaves the computer
  v.setUint32(14 + at, crc, true); v.setUint32(18 + at, size, true); v.setUint32(22 + at, size, true);
  v.setUint16(26 + at, nameLen, true);
  if (!local) v.setUint32(42, offset, true);
  return v.buffer;
}
async function pack(entries) {
  const enc = new TextEncoder(), body = [], dir = [];
  let offset = 0, dirSize = 0;
  for (const e of entries) {
    const data = new Uint8Array(await e.file.arrayBuffer()), name = enc.encode(e.path), crc = crc32(data);
    body.push(zipHeader(true, crc, data.length, name.length, 0), name, data);
    dir.push(zipHeader(false, crc, data.length, name.length, offset), name);
    offset += 30 + name.length + data.length; dirSize += 46 + name.length;
  }
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true);
  end.setUint32(12, dirSize, true); end.setUint32(16, offset, true);
  return new Blob([...body, ...dir, end.buffer], { type: 'application/zip' });
}
function sortFolder(list) {
  const keep = [], left = [];
  for (const f of Array.from(list || [])) {
    const rel = String(f.webkitRelativePath || f.name).split('/').slice(1).join('/') || String(f.name);
    const ext = extOf(f.name);
    if (/(^|\/)\./.test(rel) || /(^|\/)__MACOSX\//.test(rel) || f.name === 'Thumbs.db' || f.size === 0) continue;
    if (ARCHIVES.includes(ext)) left.push(`${f.name} (an archive inside a folder is never opened)`);
    else if (!limits.accept.includes(ext)) left.push(`${f.name} (not a kind JARVIS reads)`);
    else keep.push({ path: rel, file: f });
  }
  keep.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return { keep, left };
}
async function folder(list) {
  const first = Array.from(list || [])[0];
  const name = (first && String(first.webkitRelativePath || '').split('/')[0]) || 'folder';
  const { keep, left } = sortFolder(list);
  if (!keep.length) throw new Error('Nothing in this folder is a kind JARVIS reads.');
  if (keep.length > limits.folder_max_files) throw new Error(`This folder has ${keep.length} files JARVIS could read; it reads up to ${limits.folder_max_files} from one folder.`);
  let total = 0;
  for (const e of keep) {
    const small = await shrink(e.file);
    if (small !== e.file) { e.path = e.path.replace(/\.[^./]+$/, '') + '.jpg'; e.file = small; }
    total += e.file.size;
  }
  if (total > limits.file_mb * 1024 * 1024) throw new Error(`This folder's readable files are ${sizeText(total)} together; one folder may be ${limits.file_mb} MB. Attach fewer files.`);
  return { blob: await pack(keep), name, count: keep.length, left };
}

// ---- the folder button, beside the paperclip ---------------------------------------------------------------------
function folderButton() {
  const clip = $('attachBtn'), input = $('attachInput');
  if (!clip || !input || $('attachFolderBtn') || !('webkitdirectory' in HTMLInputElement.prototype)) return;
  const pick = document.createElement('input');
  pick.type = 'file'; pick.id = 'attachFolderInput'; pick.hidden = true; pick.tabIndex = -1;
  pick.setAttribute('webkitdirectory', ''); pick.setAttribute('aria-label', 'Choose a folder to attach');
  const btn = F.mk('button', 'clip lift r111f-folder');
  btn.type = 'button'; btn.id = 'attachFolderBtn';
  btn.setAttribute('aria-label', 'Attach a folder');
  btn.title = 'Attach a folder: the files in it that JARVIS reads, as one attachment';
  const svg = document.createElementNS(NS, 'svg');
  [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.7'], ['stroke-linecap', 'round'],
    ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
  const path = document.createElementNS(NS, 'path'); path.setAttribute('d', FOLDER_ICON); svg.appendChild(path);
  btn.appendChild(svg);
  btn.addEventListener('click', () => { if (!btn.disabled) pick.click(); });
  pick.addEventListener('change', () => {
    const A = window.JarvisAttach;
    if (A && typeof A.addFolder === 'function' && pick.files && pick.files.length) A.addFolder(pick.files);
    pick.value = '';
  });
  input.after(btn, pick);
  document.addEventListener('jarvis:attach', () => { btn.disabled = clip.disabled; });
}

// ---- per-turn hints for the browser's own recogniser (only where it takes hints) --------------------------------
// console-voice-phrases.js reads hints() when a recogniser starts; nothing is fetched for a browser without hints.
let hintTimer = 0, turnHints = [];
function refreshHints() {
  if (typeof window.SpeechRecognitionPhrase !== 'function') return;
  clearTimeout(hintTimer);
  hintTimer = setTimeout(async () => {
    const C = window.JarvisChat, sid = C && typeof C.session === 'function' ? C.session() : null;
    try {
      const r = await F.api('/v1/input/hints' + (sid ? '?session_id=' + encodeURIComponent(sid) : ''));
      turnHints = r && Array.isArray(r.hints) ? r.hints.filter(h => typeof h === 'string').slice(0, 60) : [];
    } catch (_) {}
  }, 400);
}

if (F) {
  F.part('files', { understand, heard, cost, hideCost, shrink, folder, limits: () => limits, isLarge, hints: () => turnHints.slice() });
  folderButton();
  heardRows();
  const start = () => { loadLimits(); refreshHints(); };
  document.addEventListener('jarvis:ready', start);
  ['jarvis:attach', 'jarvis:reply', 'jarvis:switch'].forEach(name => document.addEventListener(name, refreshHints));
  document.addEventListener('jarvis:switch', hideCost);
  if (window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready()) start();
}
