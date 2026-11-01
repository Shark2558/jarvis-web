// src/jarvis/api/static/console-attach.js — slice 10 E: attach files to the next message.
// The paperclip (#attachBtn → #attachInput) and drag-and-drop onto the Conversation panel add files;
// each is uploaded at once (POST /v1/attachments: the raw bytes + X-Jarvis-Filename) through the
// console's own transport (JarvisChat.raw: auth, X-Requested-With) and shown as a chip — name, size,
// "Reading…" then pages / words — with a Remove button (DELETE for an uploaded one). Limits are
// checked here first (≤ 3 files, ≤ 10 MB, PDF / Word / text / Markdown / CSV) and every refusal is a
// plain line in #attachErr (role=alert). Server text reaches the DOM through textContent only.
// window.JarvisAttach {ready(), busy(), clear(), show(row, refs)} for console.js; it fires
// jarvis:attach {count, busy} whenever the set of files or their state changes.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const MAX_FILES = 3, MAX_BYTES = 10 * 1024 * 1024;
  const EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown', '.csv'];
  const SUPPORTED = 'JARVIS can read PDF, Word (.docx), text (.txt), Markdown (.md) and CSV files.';
  const NS = 'http://www.w3.org/2000/svg';
  const CLIP = 'M14.5 9.5 9 15a3 3 0 0 1-4.2-4.2l6.4-6.4a2 2 0 0 1 2.8 2.8l-6.3 6.3a1 1 0 0 1-1.4-1.4l5.6-5.6';
  const CROSS = 'm5.5 5.5 9 9M14.5 5.5l-9 9';

  const btn = $('attachBtn'), input = $('attachInput'), chips = $('attachChips'), err = $('attachErr');
  const zone = $('p-chat'), text = $('input');
  if (!btn || !input || !chips || !err) return;
  const placeholder = text ? text.getAttribute('placeholder') || '' : '';
  const items = []; // {name, size, file, state: 'reading' | 'ready', id, meta, chip, removed}

  const emit = () => {
    try { document.dispatchEvent(new CustomEvent('jarvis:attach', { detail: { count: items.length, busy: busy() } })); } catch (_) {}
  };
  const busy = () => items.some(i => i.state === 'reading');
  function icon(d) {
    const svg = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.7'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
    const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p);
    return svg;
  }
  function sizeText(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function plural(n, word) { return `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`; }
  function extOf(name) { const i = name.lastIndexOf('.'); return i > 0 ? name.slice(i).toLowerCase() : ''; }
  function say(msg) { err.textContent = msg; err.hidden = !msg; }

  function metaText(it) {
    if (it.state === 'reading') return `${sizeText(it.size)} · Reading…`;
    const m = it.meta || {};
    const parts = [];
    if (Number.isFinite(m.pages) && m.pages > 0) parts.push(plural(m.pages, 'page'));
    else if (Number.isFinite(m.words)) parts.push(plural(m.words, 'word'));
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
      r = await chat.raw('/v1/attachments', { method: 'POST', body: it.file,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Jarvis-Filename': encodeURIComponent(it.name) } });
      try { body = await r.json(); } catch (_) {}
    } catch (e) {
      failed(it, e && e.status === 401 ? 'Sign in again, then attach it.' : 'Couldn\'t upload it. Check the connection and try again.');
      return;
    }
    if (!r.ok || !body || typeof body.id !== 'string') {
      const detail = body && typeof body.detail === 'string' && body.detail.length <= 300 ? body.detail : `Couldn't attach it (error ${r.status}).`;
      failed(it, detail);
      return;
    }
    if (it.removed) { discard(body.id); return; } // removed while it was still uploading
    it.id = body.id; it.meta = body; it.state = 'ready'; it.file = null;
    render(it);
  }
  function add(files) {
    say('');
    for (const file of Array.from(files || [])) {
      const name = String(file.name || 'file');
      if (items.length >= MAX_FILES) { say(`At most ${MAX_FILES} files per message.`); break; }
      if (!EXTENSIONS.includes(extOf(name))) { say(`${name}: ${SUPPORTED}`); continue; }
      if (file.size > MAX_BYTES) { say(`${name} is ${sizeText(file.size)}; the limit is 10 MB per file.`); continue; }
      if (file.size === 0) { say(`${name} is empty.`); continue; }
      const it = { name, size: file.size, file, state: 'reading', id: null, meta: null, chip: null, removed: false };
      items.push(it); render(it); upload(it);
    }
  }

  btn.addEventListener('click', () => { if (!btn.disabled) input.click(); });
  input.addEventListener('change', () => { add(input.files); input.value = ''; });

  // drag-and-drop onto the Conversation panel; a file dropped anywhere else must not navigate away
  const hasFiles = (e) => !!(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'));
  let depth = 0;
  if (zone) {
    zone.addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; zone.classList.add('dropping'); });
    zone.addEventListener('dragover', (e) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    zone.addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('dropping'); });
    zone.addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth = 0; zone.classList.remove('dropping'); add(e.dataTransfer.files);
    });
  }
  window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('drop', (e) => { if (hasFiles(e)) e.preventDefault(); });

  /** Small file tags under a user message (a sent message, or one restored from History). */
  function show(row, refs) {
    const list = (Array.isArray(refs) ? refs : []).slice(0, MAX_FILES)
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
    /** The uploaded files waiting to go with the next message: [{id, name}]. */
    ready: () => items.filter(i => i.state === 'ready' && i.id).map(i => ({ id: i.id, name: i.name })),
    busy,
    /** The message went out with them (or they are gone): forget the chips, delete nothing. */
    clear: () => { items.slice().forEach(i => remove(i, false)); say(''); },
    show,
  });
  sync();
})();
