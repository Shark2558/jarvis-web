// src/jarvis/api/static/console-vault-add.js -- R2 D2/D3: adding a document and checking what JARVIS
// found in it. Loaded after console-vault.js, which hands in a small context (ctx) per call. A file
// (PDF, JPEG or PNG, up to 10 MB) goes up as raw bytes; the answer is a PROPOSAL (type, dates, last 4
// read from the file's own text) that counts for nothing until the owner presses "Confirm": until then
// no reminder is set. Every server string reaches the page through textContent or an input's value.
// No build step; CSP script-src 'self'; ASCII source with backslash-u escapes only.
(() => {
  'use strict';
  const MAX_BYTES = 10 * 1024 * 1024;
  const KINDS = [['', 'Let JARVIS guess'], ['passport', 'Passport'], ['driving_licence', 'Driving licence'], ['pan', 'PAN card'],
    ['aadhaar', 'Aadhaar'], ['voter_id', 'Voter ID'], ['vehicle_rc', 'Vehicle registration'], ['vehicle_insurance', 'Vehicle insurance'],
    ['puc', 'PUC certificate'], ['health_insurance', 'Health insurance'], ['life_insurance', 'Life insurance'], ['other_insurance', 'Insurance'],
    ['birth_certificate', 'Birth certificate'], ['certificate', 'Certificate'], ['property', 'Property document'], ['other', 'Other']];
  const ISO = /^\d{4}-\d{2}-\d{2}$/;
  const field = (ctx, label, el, id) => {
    const w = ctx.mk('div', 'vfield'), l = ctx.mk('label', 'dlbl', label); el.id = id; l.htmlFor = id; w.append(l, el); return w;
  };
  const input = (cls, value, max) => { const i = document.createElement('input'); i.className = cls; i.value = value || ''; if (max) i.maxLength = max; i.autocomplete = 'off'; return i; };
  function holderSelect(ctx, current) {
    const s = document.createElement('select'); s.className = 'dinput';
    ((ctx.data() || {}).holders || []).forEach((h) => { const o = ctx.mk('option', '', h.id === 'me' ? 'Me' : h.label); o.value = h.id; s.append(o); });
    s.value = current || 'me'; return s;
  }
  function kindSelect(current, guess) {
    const s = document.createElement('select'); s.className = 'dinput';
    KINDS.filter(([v]) => guess || v).forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = t; s.append(o); });
    s.value = current || ''; return s;
  }
  async function send(file, query) {
    const chat = window.JarvisChat;
    if (!chat || typeof chat.raw !== 'function') throw new Error('Uploading is not available in this page.');
    const qs = Object.entries(query).filter(([, v]) => v).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');
    const r = await chat.raw('/v1/vault/upload' + (qs ? '?' + qs : ''), { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } });
    let j = null;
    try { j = await r.json(); } catch (_) {}
    if (!r.ok) { const e = new Error((j && typeof j.detail === 'string' && j.detail) || 'The upload did not work. Please try again.'); e.status = r.status; throw e; }
    return j;
  }
  function checkFile(file) {
    if (!file) return 'Choose a file first.';
    if (file.size > MAX_BYTES) return 'Files can be up to 10 MB.';
    if (file.size === 0) return 'That file is empty.';
    if (!/^(application\/pdf|image\/jpeg|image\/png)$/.test(file.type)) return 'Use a PDF, JPEG or PNG.';
    return '';
  }
  async function upload(ctx, file, query) {
    const bad = checkFile(file);
    if (bad) { ctx.note('bad', bad); return null; }
    ctx.setBusy(true);
    try {
      const r = await send(file, query);
      await ctx.refresh();
      const it = r && r.item;
      if (r && r.duplicate) { ctx.note('ok', 'That file is already in your vault.'); return null; }
      if (it && typeof it.id === 'string') { ctx.openItem(it.id); ctx.note('ok', 'Added. Check what JARVIS found, then confirm.'); }
      return it;
    } catch (e) {
      if (!(e && e.status === 401)) ctx.note('bad', ctx.detailOf(e) || 'The upload did not work. Please try again.');
      return null;
    } finally { ctx.setBusy(false); }
  }

  function addForm(data, ctx) {
    const f = ctx.mk('form', 'vform');
    f.setAttribute('aria-label', 'Add a document');
    const file = document.createElement('input'); file.type = 'file'; file.accept = 'application/pdf,image/jpeg,image/png'; file.className = 'dinput';
    const kind = kindSelect('', true), who = holderSelect(ctx, 'me');
    const go = ctx.mk('button', 'btn primary lift', 'Add to vault'); go.type = 'submit'; go.disabled = ctx.busy();
    f.append(field(ctx, 'File (PDF, JPEG or PNG, up to 10 MB)', file, 'vaultFile'), field(ctx, 'Kind of document', kind, 'vaultKind'),
      field(ctx, 'Whose is it?', who, 'vaultWho'), go,
      ctx.mk('p', 'vfine', 'JARVIS reads the dates from the file on this server, in memory. Nothing is saved as readable text.'));
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      await upload(ctx, file.files && file.files[0], { type: kind.value, holder: who.value === 'me' ? '' : who.value });
    });
    return f;
  }

  /** "Add the back" for a one-file item (an Aadhaar or licence has two sides). */
  function pickFile(item, ctx) {
    const i = document.createElement('input'); i.type = 'file'; i.accept = 'application/pdf,image/jpeg,image/png'; i.hidden = true;
    document.body.append(i);
    i.addEventListener('change', async () => { const f = i.files && i.files[0]; i.remove(); if (f) await upload(ctx, f, { item: item.id }); });
    i.addEventListener('cancel', () => i.remove());
    i.click();
  }

  function editForm(item, ctx) {
    const f = ctx.mk('form', 'vform');
    f.setAttribute('aria-label', 'Check details');
    const p = item.proposal || {};
    if (!item.confirmed && (p.expires || p.issued || p.last4)) {
      const bits = [];
      if (p.expires) bits.push('expires ' + ctx.niceDate(p.expires));
      if (p.issued) bits.push('issued ' + ctx.niceDate(p.issued));
      if (p.last4) bits.push('ends ' + p.last4);
      f.append(ctx.mk('p', 'vline vfound', 'JARVIS found: ' + bits.join(', ') + '. Fix anything wrong, then confirm.'));
    }
    const kind = kindSelect(item.type, false), who = holderSelect(ctx, item.holderId);
    const title = input('dinput', item.title, 60), l4 = input('dinput', item.last4 || (item.confirmed ? '' : p.last4), 4);
    const exp = input('dinput', item.expires || p.expires, 10), iss = input('dinput', item.issued || p.issued, 10), note = input('dinput', item.note, 300);
    exp.type = 'date'; iss.type = 'date';
    f.append(field(ctx, 'Kind', kind, 'vaultEKind'), field(ctx, 'Whose', who, 'vaultEWho'), field(ctx, 'Name (optional)', title, 'vaultETitle'),
      field(ctx, 'Last 4 characters of the number (optional)', l4, 'vaultELast4'), field(ctx, item.normallyExpires ? 'Expires on' : 'Expires on (if it does)', exp, 'vaultEExp'),
      field(ctx, 'Issued on (optional)', iss, 'vaultEIss'), field(ctx, 'Note (optional)', note, 'vaultENote'));
    const row = ctx.mk('div', 'vacts');
    const ok = ctx.mk('button', 'btn primary lift', item.confirmed ? 'Save' : 'Confirm'); ok.type = 'submit'; ok.disabled = ctx.busy();
    const cancel = ctx.mk('button', 'btn bact', 'Cancel'); cancel.type = 'button'; cancel.addEventListener('click', () => ctx.close());
    row.append(ok, cancel); f.append(row);
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      if ((exp.value && !ISO.test(exp.value)) || (iss.value && !ISO.test(iss.value))) { ctx.note('bad', 'Enter dates as day, month, year.'); return; }
      const patch = { type: kind.value, holder_id: who.value, title: ctx.txt(title.value, 60), last4: ctx.txt(l4.value, 4), note: ctx.txt(note.value, 300), confirm: true };
      if (!patch.title) delete patch.title;
      patch.expires_on = exp.value || null; patch.issued_on = iss.value || null;
      if (!item.expires && !exp.value) delete patch.expires_on;
      if (!item.issued && !iss.value) delete patch.issued_on;
      const r = await ctx.call('/v1/vault/items/' + item.id, { method: 'PATCH', body: patch }, item.confirmed ? 'Saved.' : 'Confirmed. Reminders are on.');
      if (r) ctx.close();
    });
    return f;
  }

  window.JarvisVaultAdd = Object.freeze({ addForm, editForm, pickFile, checkFile });
})();
