// src/jarvis/api/static/console-attach.js — slice 10 E: attach files to the next message.
// The paperclip (#attachBtn → #attachInput) and drag-and-drop onto the Conversation panel add files;
// each is uploaded at once (POST /v1/attachments: the raw bytes + X-Jarvis-Filename) through the
// console's own transport (JarvisChat.raw: auth, X-Requested-With) and shown as a chip — name, size,
// "Reading…" then pages / words — with a Remove button (DELETE for an uploaded one). Limits are
// checked here first and every refusal is a plain line in #attachErr (role=alert). Server text
// reaches the DOM through textContent only.
// R11.1 (plan D10-D11): the kinds and limits are THIS file's own list (the page's accept attribute and
// the paperclip's tooltip are set from it at start, and again from GET /v1/input when console-r111-files.js
// has it: configure()). Excel, PowerPoint, pictures and zip files are taken; a picture is made smaller in
// the browser first (JarvisFixes.parts.files.shrink); a picked folder goes up as ONE bundle with
// X-Jarvis-Folder: 1 (addFolder). At most 10 files, 40 MB together and 4 pictures a message.
// window.JarvisAttach {ready(), busy(), clear(), show(row, refs), configure(limits), addFolder(files), add(files)}
// for console.js, console-r111-files.js and R7's one picture door (console-r7-send.js: add, I0 seam 25); it fires jarvis:attach {count, busy} whenever the set of
// files or their state changes.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const MB = 1024 * 1024;
  let MAX_FILES = 10, MAX_BYTES = 10 * MB, TOTAL_BYTES = 40 * MB, MAX_PICTURES = 4;
  let EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown', '.csv', '.xlsx', '.xlsm', '.xls', '.pptx', '.png', '.jpg', '.jpeg', '.zip'];
  const SUPPORTED = 'JARVIS can read PDF, Word (.docx), Excel (.xlsx, .xls), PowerPoint (.pptx), text (.txt), Markdown (.md) and CSV files, pictures (.png, .jpg), zip files and folders.';
  const PICTURE = /\.(png|jpe?g)$/i;
  const NS = 'http://www.w3.org/2000/svg';
  const CLIP = 'M14.5 9.5 9 15a3 3 0 0 1-4.2-4.2l6.4-6.4a2 2 0 0 1 2.8 2.8l-6.3 6.3a1 1 0 0 1-1.4-1.4l5.6-5.6';
  const CROSS = 'm5.5 5.5 9 9M14.5 5.5l-9 9';

  const btn = $('attachBtn'), input = $('attachInput'), chips = $('attachChips'), err = $('attachErr');
  const zone = $('p-chat'), text = $('input');
  if (!btn || !input || !chips || !err) return;
  const placeholder = text ? text.getAttribute('placeholder') || '' : '';
  const items = []; // {name, size, file, folder, picture, state: 'reading' | 'ready', id, meta, chip, removed}

  const emit = () => {
    try { document.dispatchEvent(new CustomEvent('jarvis:attach', { detail: { count: items.length, busy: busy() } })); } catch (_) {}
  };
  const busy = () => items.some(i => i.state === 'reading');
  const files = () => (window.JarvisFixes && window.JarvisFixes.parts && window.JarvisFixes.parts.files) || null; // console-r111-files.js
  function icon(d) {
    const svg = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.7'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
    const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p);
    return svg;
  }
  function sizeText(bytes) {
    if (bytes < MB) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / MB).toFixed(1)} MB`;
  }
  function plural(n, word) { return `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`; }
  function extOf(name) { const i = name.lastIndexOf('.'); return i > 0 ? name.slice(i).toLowerCase() : ''; }
  function say(msg) { err.textContent = msg; err.hidden = !msg; }
  const has = (v) => Number.isFinite(v) && v > 0;

  /** What a read file holds, in its own units (the server's counts; R11.1 adds sheets, slides, files, pictures). */
  function countsText(m) {
    if (m.kind === 'image') return ['picture'];
    const parts = [];
    if (has(m.pages)) parts.push(plural(m.pages, 'page'));
    if (has(m.sheets)) parts.push(plural(m.sheets, 'sheet'));
    if (has(m.rows)) parts.push(plural(m.rows, 'row'));
    if (has(m.slides)) parts.push(plural(m.slides, 'slide'));
    if (Number.isFinite(m.files)) parts.push(plural(m.files, 'file') + (has(m.skipped) ? `, ${m.skipped} not read` : ''));
    if (has(m.pictures)) parts.push(plural(m.pictures, 'picture'));
    if (!parts.length && Number.isFinite(m.words)) parts.push(plural(m.words, 'word'));
    return parts;
  }
  function metaText(it) {
    if (it.state === 'reading') return it.size ? `${sizeText(it.size)} \u00b7 Reading\u2026` : 'Reading\u2026';
    const m = it.meta || {};
    const parts = countsText(m);
    parts.push(sizeText(it.size));
    if (m.truncated === true) parts.push('start only');
    return parts.join(' · ');
  }
  function render(it) {
    const chip = it.chip || document.createElement('div');
    chip.className = 'achip'; chip.setAttribute('role', 'listitem'); chip.dataset.state = it.state;
    chip.textContent = '';
    const name = document.createElement('span'); name.className = 'aname'; name.textContent = it.name; name.title = it.name;
    const meta = document.createElement('span'); meta.className = 'ameta'; meta.textContent = metaText(it);
    const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'arm';
    rm.setAttribute('aria-label', 'Remove ' + it.name); rm.title = 'Remove';
    rm.appendChild(icon(CROSS));
    rm.addEventListener('click', () => remove(it, true));
    chip.append(icon(CLIP), name, meta, rm);
    if (!it.chip) { it.chip = chip; chips.appendChild(chip); }
    sync();
  }
  function tooltip() {
    return `Attach PDF, Word, Excel, PowerPoint, text, Markdown, CSV, pictures or a zip (up to ${MAX_FILES} files, ${Math.round(MAX_BYTES / MB)} MB each), or drop them here`;
  }
  function sync() {
    chips.hidden = items.length === 0;
    if (text) text.setAttribute('placeholder', items.length ? (items.length === 1 ? 'Ask about the attached file' : 'Ask about the attached files') : placeholder);
    btn.disabled = items.length >= MAX_FILES;
    emit();
  }
  function discard(id) {
    const C = window.JarvisConsole;
    if (id && C && typeof C.api === 'function') C.api(`/v1/attachments/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => {});
  }
  function remove(it, byOwner) {
    const at = items.indexOf(it);
    if (at === -1) return;
    items.splice(at, 1); it.removed = true;
    if (it.chip) it.chip.remove();
    if (byOwner) { discard(it.id); const next = items[at] || items[at - 1]; (next && next.chip ? next.chip.querySelector('.arm') : btn).focus(); }
    sync();
  }
  function failed(it, why) { remove(it, false); say(`${it.name}: ${why}`); }

  async function upload(it) {
    const chat = window.JarvisChat;
    if (!chat || typeof chat.raw !== 'function') { failed(it, 'Attaching files is not available.'); return; }
    let r, body = null;
    try {
      const headers = { 'Content-Type': 'application/octet-stream', 'X-Jarvis-Filename': encodeURIComponent(it.name) };
      if (it.folder) headers['X-Jarvis-Folder'] = '1';
      r = await chat.raw('/v1/attachments', { method: 'POST', body: it.file, headers });
      try { body = await r.json(); } catch (_) {}
    } catch (e) {
      failed(it, e && e.status === 401 ? 'Sign in again, then attach it.' : 'Couldn\'t upload it. Check the connection and try again.');
      return;
    }
    if (!r.ok || !body || typeof body.id !== 'string') {
      const detail = body && typeof body.detail === 'string' && body.detail.length <= 500 ? body.detail : `Couldn't attach it (error ${r.status}).`;
      failed(it, detail);
      return;
    }
    if (it.removed) { discard(body.id); return; } // removed while it was still uploading
    it.id = body.id; it.meta = body; it.state = 'ready'; it.file = null;
    render(it);
  }
  /** A picture is made smaller in the browser before it leaves (D10); anything else goes as it is. */
  async function prepare(it) {
    const F = files();
    if (it.picture && F && typeof F.shrink === 'function') {
      try {
        const small = await F.shrink(it.file);
        if (small && small !== it.file) { it.file = small; it.size = small.size; it.name = String(small.name || it.name); if (!it.removed) render(it); }
      } catch (_) {}
    }
    if (it.removed) return;
    if (it.file.size > MAX_BYTES) { failed(it, `it is ${sizeText(it.file.size)}; the limit is ${Math.round(MAX_BYTES / MB)} MB per file.`); return; }
    upload(it);
  }
  const waitingBytes = () => items.reduce((sum, i) => sum + i.size, 0);
  const waitingPictures = () => items.reduce((sum, i) => sum + (i.picture ? 1 : i.meta && has(i.meta.pictures) ? i.meta.pictures : 0), 0);
  /** Why this file can't join the ones already waiting ('' when it can). A picture is weighed after it is shrunk. */
  function refusal(name, size, picture) {
    if (items.length >= MAX_FILES) return `At most ${MAX_FILES} files per message.`;
    if (!EXTENSIONS.includes(extOf(name))) return `${name}: ${SUPPORTED}`;
    if (size === 0) return `${name} is empty.`;
    if (picture) return waitingPictures() >= MAX_PICTURES ? `At most ${MAX_PICTURES} pictures per message.` : '';
    if (size > MAX_BYTES) return `${name} is ${sizeText(size)}; the limit is ${Math.round(MAX_BYTES / MB)} MB per file.`;
    if (waitingBytes() + size > TOTAL_BYTES) return `${name} would bring these files over ${Math.round(TOTAL_BYTES / MB)} MB together, the limit for one message.`;
    return '';
  }
  function add(list) {
    say('');
    for (const file of Array.from(list || [])) {
      const name = String(file.name || 'file'), picture = PICTURE.test(name);
      const why = refusal(name, file.size, picture);
      if (why) { say(why); if (items.length >= MAX_FILES) break; continue; }
      const it = { name, size: file.size, file, folder: false, picture, state: 'reading', id: null, meta: null, chip: null, removed: false };
      items.push(it); render(it); prepare(it);
    }
  }
  /** A picked folder (R11.1 D11): its readable files become one bundle and one chip. */
  async function addFolder(list) {
    say('');
    const F = files();
    if (!F || typeof F.folder !== 'function') { say('Attaching a folder is not available.'); return; }
    if (items.length >= MAX_FILES) { say(`At most ${MAX_FILES} files per message.`); return; }
    const first = Array.from(list || [])[0];
    const name = (first && String(first.webkitRelativePath || '').split('/')[0]) || 'folder';
    const it = { name, size: 0, file: null, folder: true, picture: false, state: 'reading', id: null, meta: null, chip: null, removed: false };
    items.push(it); render(it);
    let packed = null;
    try { packed = await F.folder(list); } catch (e) { failed(it, e && typeof e.message === 'string' ? e.message : 'That folder couldn\'t be read.'); return; }
    if (it.removed) return;
    it.file = packed.blob; it.size = packed.blob.size; render(it);
    if (packed.left.length) say(`${name}: left out ${packed.left.slice(0, 5).join('; ')}${packed.left.length > 5 ? `; and ${packed.left.length - 5} more` : ''}.`);
    upload(it);
  }
  /** GET /v1/input's limits (console-r111-files.js passes them on): the server's own list wins over this file's. */
  function configure(l) {
    if (!l || !Array.isArray(l.accept)) return;
    EXTENSIONS = l.accept.filter(x => typeof x === 'string' && /^\.[a-z0-9]{1,8}$/.test(x));
    if (has(l.max_files)) MAX_FILES = l.max_files;
    if (has(l.file_mb)) MAX_BYTES = l.file_mb * MB;
    if (has(l.total_mb)) TOTAL_BYTES = l.total_mb * MB;
    if (has(l.max_pictures)) MAX_PICTURES = l.max_pictures;
    apply();
  }
  /** The page's own accept attribute and tooltip name the old kinds: set both from this file's list. */
  function apply() {
    input.setAttribute('accept', EXTENSIONS.join(','));
    btn.title = tooltip();
    sync();
  }

  btn.addEventListener('click', () => { if (!btn.disabled) input.click(); });
  input.addEventListener('change', () => { add(input.files); input.value = ''; });

  // drag-and-drop onto the Conversation panel; a file dropped anywhere else must not navigate away
  const hasFiles = (e) => !!(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'));
  /** A dropped folder arrives as an entry that is a directory; the folder button packs one properly (R11.1 D11). */
  function droppedFolder(e) {
    return Array.from(e.dataTransfer.items || []).some((i) => {
      try { const entry = typeof i.webkitGetAsEntry === 'function' ? i.webkitGetAsEntry() : null; return !!(entry && entry.isDirectory); } catch (_) { return false; }
    });
  }
  let depth = 0;
  if (zone) {
    zone.addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; zone.classList.add('dropping'); });
    zone.addEventListener('dragover', (e) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    zone.addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('dropping'); });
    zone.addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth = 0; zone.classList.remove('dropping');
      if (droppedFolder(e)) { say('To attach a folder, use the folder button beside the paperclip.'); return; }
      add(e.dataTransfer.files);
    });
  }
  window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('drop', (e) => { if (hasFiles(e)) e.preventDefault(); });

  /** Small file tags under a user message (a sent message, or one restored from History). */
  function show(row, refs) {
    const list = (Array.isArray(refs) ? refs : []).slice(0, 20)
      .map(r => (r && typeof r.name === 'string' ? r.name : '')).filter(Boolean);
    if (!row || !list.length) return;
    let meta = row.querySelector('.meta');
    if (!meta) { meta = document.createElement('div'); meta.className = 'meta'; row.appendChild(meta); }
    list.forEach(n => {
      const tag = document.createElement('span'); tag.className = 'afile'; tag.title = n;
      const label = document.createElement('span'); label.textContent = n;
      tag.append(icon(CLIP), label); meta.appendChild(tag);
    });
  }

  window.JarvisAttach = Object.freeze({
    /** The uploaded files waiting to go with the next message: [{id, name, meta}] (meta: the server's counts). */
    ready: () => items.filter(i => i.state === 'ready' && i.id).map(i => ({ id: i.id, name: i.name, meta: i.meta })),
    busy,
    /** The message went out with them (or they are gone): forget the chips, delete nothing. */
    clear: () => { items.slice().forEach(i => remove(i, false)); say(''); },
    show, configure, addFolder,
    add, // R7 I0 seam 25: the share tray and the Camera panel attach through console-r7-send.js
  });
  apply();
})();
