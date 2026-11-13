// src/jarvis/api/static/console-r7-phone.js -- R7 Part C (docs/plans/r7-mobile.md D5, D21): Integrations -> Phone app.
// Link a phone (a passkey check bound to the code's offer, or a fresh Google sign-in when there is no passkey yet), the
// linked phones with what each app may do, Unlink this phone, and Sign out everywhere. Loaded by console-r7.js (an ES
// module); built with window.JarvisMobile (mk, api, part) and the console's own classes (.integ, .ihead, .ibody, .inote,
// .btn, .bdialog); every server string reaches the page through textContent; a field of the wrong type is dropped. It
// asks the server NOTHING before sign-in (jarvis:ready), and nothing until the Integrations panel is open. ASCII only.
// API: GET /v1/phone -> {enabled, max, phones:[{id, model, linked_at, last_seen, app_version, android, can}], code};
// POST /v1/phone/link-code {} -> {code, expires_in_s} | {needs: 'passkey', target}; then {id: target, proof};
// POST /v1/phone/{id}/unlink -> {unlinked}; POST /v1/session/end-all -> {ended, detail}.
const M = window.JarvisMobile;
const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
const CODE = /^[0-9A-Z]{8}$/;
const DEVICE = /^ph_[0-9a-f]{12}$/;
const OFFER = /^pl_[0-9a-f]{12}$/;
const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
const CAN = [['notifications', 'Alerts'], ['health_read', 'Watch data'], ['health_background', 'Watch data in the background'],
  ['location', 'SOS location'], ['folder', 'DigiLocker folder'], ['tile', 'Talk tile']];
const LIMITS = 'A linked phone has its own key, kept in the phone. It can add watch numbers, add a document for you to ' +
  'confirm, and send an SOS. It can never read a conversation, your vault or your mail, and never approve anything.';
const S = { data: undefined, busy: false, loadedAt: 0, signedIn: false, link: 0, timer: 0 };
let card = null, stateEl = null, bodyEl = null, noteEl = null, dlg = null, settle = null;

const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const txt = (v, max = 120) => (typeof v === 'string' ? v.replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g, '').trim().slice(0, max) : '');
const mk = (tag, cls, text) => (M ? M.mk(tag, cls, text) : document.createElement(tag));
const api = (path, opts) => M.api(path, opts);
const button = (id, label, cls) => { const b = mk('button', cls || 'btn bact', label); b.type = 'button'; if (id) b.id = id; return b; };
function detailOf(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
  return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
}
/** GET /v1/phone, checked field by field. */
function normal(raw) {
  const d = obj(raw);
  if (!d || d.enabled !== true) return { enabled: false, phones: [], max: 3, code: null };
  const phones = arr(d.phones).map(obj).filter((p) => p && typeof p.id === 'string' && DEVICE.test(p.id)).map((p) => ({
    id: p.id, model: txt(p.model, 40) || 'Phone', linked: M.when(txt(p.linked_at, 40), false), seen: M.when(txt(p.last_seen, 40), true),
    version: txt(p.app_version, 20), can: CAN.filter(([k]) => obj(p.can) && p.can[k] === true).map(([, w]) => w),
  }));
  const code = obj(d.code), left = code && Number.isInteger(code.seconds_left) ? code.seconds_left : 0;
  return { enabled: true, phones, max: Number.isInteger(d.max) && d.max > 0 ? d.max : 3, code: left > 0 ? left : null };
}

// ---- the card -------------------------------------------------------------------------------------------------------
function build() {
  if (card) return true;
  const host = $('integrations');
  if (!host || !host.parentNode) return false;
  card = mk('section', 'integ phonelink'); card.id = 'phoneSet'; card.dataset.state = 'loading';
  card.setAttribute('aria-labelledby', 'phoneHead');
  const head = mk('div', 'ihead');
  const title = mk('b', '', 'Phone app'); title.id = 'phoneHead';
  stateEl = mk('span', 'istate', 'Checking\u2026');
  head.append(title, stateEl);
  noteEl = mk('div', 'inote'); noteEl.id = 'phoneNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
  bodyEl = mk('div', 'ibody'); bodyEl.id = 'phoneBody';
  card.append(head, bodyEl, noteEl);
  const anchor = $('homeSet') || $('telegramSet') || host;
  anchor.parentNode.insertBefore(card, anchor.nextSibling);
  buildDialog();
  return true;
}
function note(kind, text, link) {
  if (!noteEl) return;
  noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
  noteEl.textContent = text || '';
  if (link) { const a = mk('a', 'btn bact', link.text); a.href = link.href; a.id = 'phoneReauth'; noteEl.append(' ', a); }
  noteEl.hidden = !text;
}
function render() {
  if (!build()) return;
  bodyEl.replaceChildren();
  const d = S.data;
  if (!d) { card.dataset.state = 'error'; stateEl.textContent = 'Couldn\'t check'; bodyEl.append(mk('p', '', 'Couldn\'t load the phone app\'s link.'), retryBtn()); return; }
  if (!d.enabled) { card.dataset.state = 'off'; stateEl.textContent = 'Off'; bodyEl.append(mk('p', '', 'The phone app isn\'t switched on on this server.')); return; }
  const n = d.phones.length;
  card.dataset.state = n ? 'linked' : 'unlinked';
  stateEl.textContent = n ? (n === 1 ? '1 phone linked' : `${n} phones linked`) : 'No phone linked';
  if (!n) bodyEl.append(mk('p', '', 'Link the JARVIS app on your phone once. Then alerts, the Talk tile, your watch, SOS and DigiLocker work from the phone.'));
  const list = mk('ul', 'phones'); list.id = 'phoneList';
  d.phones.forEach((p) => list.append(phoneRow(p)));
  if (n) bodyEl.append(list);
  const acts = mk('div', 'pactions');
  const link = button('phoneLink', 'Link a phone');
  link.disabled = n >= d.max || S.busy;
  link.addEventListener('click', () => startLink(link));
  const out = button('phoneEndAll', 'Sign out everywhere');
  out.disabled = S.busy;
  out.addEventListener('click', () => endAll(out));
  acts.append(link, out);
  bodyEl.append(acts);
  if (n >= d.max) bodyEl.append(mk('p', 'fine', `${d.max} phones are linked, the most JARVIS allows. Unlink one to link another.`));
  bodyEl.append(mk('p', 'fine', LIMITS));
}
function retryBtn() { const b = button('phoneRetry', 'Try again'); b.addEventListener('click', () => load(true)); return b; }
function phoneRow(p) {
  const li = mk('li', 'phone'); li.dataset.id = p.id;
  li.append(mk('b', '', p.model));
  const facts = [p.linked ? 'Linked ' + p.linked : '', p.seen ? 'last seen ' + p.seen : 'not seen yet', p.version ? 'app ' + p.version : ''];
  li.append(mk('p', 'fine', facts.filter(Boolean).join(' \u00b7 ')));
  li.append(mk('p', 'fine', p.can.length ? 'Allowed on the phone: ' + p.can.join(', ') : 'Nothing allowed on the phone yet.'));
  const b = button('', 'Unlink this phone', 'btn bact bdel');
  b.addEventListener('click', () => unlink(p, b));
  li.append(b);
  return li;
}

// ---- the confirm and code dialog --------------------------------------------------------------------------------------
function buildDialog() {
  dlg = mk('dialog', 'bdialog'); dlg.id = 'phoneDialog'; dlg.setAttribute('role', 'alertdialog');
  dlg.setAttribute('aria-labelledby', 'phoneDialogTitle'); dlg.setAttribute('aria-describedby', 'phoneDialogText');
  const h = mk('h2'); h.id = 'phoneDialogTitle';
  const body = mk('div'); body.id = 'phoneDialogText';
  const actions = mk('div', 'actions');
  const no = button('phoneDialogNo', 'Cancel', 'btn lift');
  const yes = button('phoneDialogYes', 'OK', 'btn primary lift');
  actions.append(no, yes);
  dlg.append(h, body, actions);
  document.body.append(dlg);
  dlg.addEventListener('close', () => { if (settle) settle(false); });  // closed from outside (the lock cover): stop the poll
  yes.addEventListener('click', () => { if (settle) settle(true); });
  no.addEventListener('click', () => { if (settle) settle(false); });
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
  dlg.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const items = [...dlg.querySelectorAll('button:not([disabled]), a[href]')];
    if (!items.length) return;
    const a = items[0], z = items[items.length - 1];
    if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
  });
}
function ask(title, nodes, yes, trigger) {
  if (!dlg || typeof dlg.showModal !== 'function') { note('bad', 'This browser can\'t show the confirmation, so nothing was changed.'); return Promise.resolve(false); }
  if (settle) settle(false);
  $('phoneDialogTitle').textContent = title;
  $('phoneDialogText').replaceChildren(...nodes);
  const ok = $('phoneDialogYes'), no = $('phoneDialogNo');
  ok.hidden = !yes; ok.textContent = yes || 'OK'; no.textContent = yes ? 'Cancel' : 'Close';
  dlg.showModal();
  no.focus();
  return new Promise((resolve) => {
    settle = (v) => { settle = null; S.link = 0; clearTimeout(S.timer); if (dlg.open) dlg.close(); if (trigger && trigger.isConnected) trigger.focus(); resolve(v); };
  });
}

// ---- actions ----------------------------------------------------------------------------------------------------------
async function startLink(trigger) {
  if (S.busy) return;
  S.busy = true; note('', '');
  let r = null;
  try {
    r = obj(await api('/v1/phone/link-code', { body: {} }));
    if (r && r.needs === 'passkey') r = await withPasskey(r);
  } catch (e) {
    r = null;
    if (e && e.status === 401) { S.busy = false; return; }
    if (e && e.code === 'reauth_required') note('bad', 'Sign in with Google again first (it counts for 5 minutes), then press Link a phone.', { text: 'Sign in again', href: '/auth/login?reauth=1' });
    else note('bad', detailOf(e) || 'Couldn\'t make a code. Please try again.');
  } finally { S.busy = false; }
  if (!r || typeof r.code !== 'string' || !CODE.test(r.code)) return;
  showCode(r, trigger);
}
async function withPasskey(r) {
  const P = window.JarvisPasskey, target = typeof r.target === 'string' && OFFER.test(r.target) ? r.target : '';
  if (!target) throw new Error('Couldn\'t make a code. Please try again.');
  if (!P || typeof P.supported !== 'function' || !P.supported()) throw new Error('This browser can\'t use passkeys. Link the phone from the laptop where your passkey is.');
  let proof;
  try { proof = await P.prove('phone_link', target); } catch (e) { throw new Error(P.message ? P.message(e) : 'The passkey check didn\'t work.'); }
  return obj(await api('/v1/phone/link-code', { body: { id: target, proof } }));
}
function showCode(r, trigger) {
  const left = Number.isInteger(r.expires_in_s) && r.expires_in_s > 0 ? r.expires_in_s : 600;
  const before = new Set(S.data ? S.data.phones.map((p) => p.id) : []);
  const code = mk('p', 'pcode', r.code.slice(0, 4) + ' ' + r.code.slice(4)); code.id = 'phoneCode';
  const status = mk('p', 'fine'); status.id = 'phoneWaiting'; status.setAttribute('role', 'status');
  const stamp = Date.now(); S.link = stamp;
  const show = () => { status.textContent = 'Waiting for the phone\u2026 ' + Math.max(0, left - Math.floor((Date.now() - stamp) / 1000)) + ' s left'; };
  show();
  const done = ask('Link a phone', [
    mk('p', '', 'Open the JARVIS app on your phone and type these 8 characters. The code works once, for 10 minutes.'),
    code, status], null, trigger);
  const tick = async () => {
    if (S.link !== stamp) return;
    if (Date.now() - stamp > left * 1000) { status.textContent = 'The code expired. Close this and press Link a phone again.'; return; }
    show();
    try {
      const d = normal(await api('/v1/phone'));
      if (d.phones.some((p) => !before.has(p.id))) { S.data = d; S.loadedAt = Date.now(); if (settle) settle(true); render(); note('ok', 'Linked. A notice went to all your alerts, Sir.'); return; }
    } catch (e) { if (e && (e.status === 401 || e.status === 423)) return; }
    S.timer = setTimeout(tick, POLL_MS);
  };
  S.timer = setTimeout(tick, POLL_MS);
  return done;
}
async function unlink(p, trigger) {
  if (S.busy) return;
  const yes = await ask('Unlink this phone?', [mk('p', '', `${p.model} will no longer reach JARVIS: alerts, the watch, SOS and DigiLocker stop on it at once. You can link it again later.`)], 'Unlink', trigger);
  if (!yes) return;
  S.busy = true;
  try {
    await api(`/v1/phone/${p.id}/unlink`, { method: 'POST' });
    note('ok', 'Unlinked. That phone can no longer reach JARVIS.');
  } catch (e) {
    if (e && e.status === 401) return;
    note('bad', detailOf(e) || 'Couldn\'t unlink the phone. Please try again.');
  } finally { S.busy = false; await load(true); }
}
async function endAll(trigger) {
  if (S.busy) return;
  const yes = await ask('Sign out everywhere?', [
    mk('p', '', 'Every other browser and phone signed in to JARVIS is signed out within seconds. This one stays signed in.'),
    mk('p', 'fine', 'If a phone was lost, also unlink it here and remove its passkey in Approvals, then Permissions.')], 'Sign out everywhere', trigger);
  if (!yes) return;
  S.busy = true;
  try {
    const r = obj(await api('/v1/session/end-all', { method: 'POST' }));
    note('ok', (r && txt(r.detail, 200)) || 'Every other device is signed out, Sir.');
  } catch (e) {
    if (e && e.status === 401) return;
    note('bad', detailOf(e) || 'Couldn\'t sign out everywhere. Please try again.');
  } finally { S.busy = false; render(); }
}

// ---- when to load -----------------------------------------------------------------------------------------------------
const integOpen = () => { const p = $('p-integrations'); return !!p && !p.hidden; };
async function load(force) {
  if (!M || !S.signedIn || !build()) return;
  if (!force && S.data !== undefined && Date.now() - S.loadedAt < 30000) return;
  try { S.data = normal(await api('/v1/phone')); S.loadedAt = Date.now(); }
  catch (e) { if (e && (e.status === 401 || e.status === 423)) return; S.data = null; }
  render();
}
function signedIn() { S.signedIn = true; if (integOpen()) load(false); }
document.addEventListener('jarvis:ready', signedIn);
document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
if (window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready()) signedIn();
if (M) M.part('phone', Object.freeze({ refresh: () => load(true) }));
