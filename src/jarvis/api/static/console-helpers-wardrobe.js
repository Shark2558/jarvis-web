// src/jarvis/api/static/console-helpers-wardrobe.js -- R13 Part D (docs/plans/r13-wardrobe.md D1, D10, D13, D17): Helpers ->
// Wardrobe, the sixth sub-tab (console-only: helpers/kinds.py TABS stays the five). Sections:
//   Needs a check        B's review queue: which piece went in, "there was no deposit"
//   Today and tomorrow   C's plans with their reasons, gaps and the weather's assumption; "Wearing it", "Done for today"
//   Laundry              B's basket, loads, drying, prep and outside batches; a step per piece
//   Pieces               console-wardrobe-pieces.js: search, counts, pairs and sets, places, private basics behind a tap
//   Labels               the sheet of 24 QR labels (a download), and which label is on which piece
//   Settings             the calendar and its fields, the evening alert, auto-swap, AI tagging, backup and restore
// Built only from window.JarvisHelpers' builders (row, toggle, section, note, empty) and existing classes, so the look
// does not change. The routes and shapes are jarvis.wardrobe.http's; every change goes through
// POST /v1/wardrobe/tools/{tool} (the gateway: its rows, cards and audit) except the settings (C's PUT /v1/outfits/settings,
// A's PUT /v1/wardrobe/settings: never a tool the model can call), labels (POST /v1/wardrobe/labels) and the backup file. A calendar's title is shown while he looks and never stored.
// textContent only; nothing asked before sign-in; ASCII source.
const H = window.JarvisHelpers;
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const KEY_NOTE = 'The backup opens only on this JARVIS with today\u2019s key: after a key change older files can\u2019t be read.';
const SLOTS = { base: 'Base', top: 'Top', bottom: 'Bottom', outer: 'Outer', socks: 'Socks', shoes: 'Shoes', belt: 'Belt', watch: 'Watch', extras: 'Extras' };
const UI = { host: null, note: null, secs: {}, view: null, laundry: null, review: null, outfits: null, cal: null, busy: false, loading: null, priv: false, file: null, check: null, pieces: null };
const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
const when = (iso, t) => (window.JarvisMobile && window.JarvisMobile.when ? window.JarvisMobile.when(iso, t) : '');
const say = (kind, text) => H.note(UI.note, kind, text);

function btn(label, onClick, cls) {
  const b = H.mk('button', 'btn sact' + (cls ? ' ' + cls : ''), label);
  b.type = 'button';
  b.addEventListener('click', () => { if (!UI.busy) onClick(b); });
  return b;
}
function acts(...els) { const a = H.mk('div', 'sacts'); els.filter(Boolean).forEach((e) => a.append(e)); return a; }
function field(label, control) { const l = H.mk('label', 'hp-field'); l.append(H.mk('span', 'snote', label), control); return l; }
function select(options, value) {
  const s = H.mk('select', 'minput');
  options.forEach(([v, t]) => { const o = H.mk('option', '', t); o.value = String(v); s.append(o); });
  s.value = String(value);
  return s;
}
function failed(e) {
  if (e && e.status === 401) return;
  say('bad', e && e.name === 'TypeError' ? OFFLINE : H.txt((e && e.message) || 'That didn\u2019t work.', 200));
}
function pieceOf(id) { return ((UI.view && UI.view.pieces) || []).find((p) => p.id === id) || null; }
function nameOf(id) { // his own words in his own console; a private piece only once he has tapped to show them
  const p = pieceOf(id);
  if (!p) return UI.view && UI.view.private_hidden ? privateWords(id) : 'A piece'; // only private pieces are left out
  if (p.private && !UI.priv) return privateWords(id);
  return H.txt(p.label || [p.colour, p.type].filter(Boolean).join(' ').replace(/_/g, ' '), 60) || 'A piece';
}
function privateWords(id) { // D10's own form: his printed label's number tells two copies apart
  const l = ((UI.view && UI.view.labels) || []).find((x) => x.piece === id);
  return 'A private basic' + (l ? ' (No. ' + l.number + ')' : '');
}
const placeOf = (id) => { const p = ((UI.view && UI.view.places) || []).find((x) => x.id === id); return p ? p.label : ''; };

// ---- the server ------------------------------------------------------------------------------------------------------
async function get(path) { try { return await H.api(path); } catch (e) { if (e && e.status === 401) throw e; return { failed: true, words: e && e.name === 'TypeError' ? OFFLINE : 'Couldn\u2019t load this part.' }; } }
async function load() {
  if (!signedIn() || !UI.host) return null;
  if (UI.loading) return UI.loading;
  UI.loading = (async () => {
    try {
      const [view, laundry, review, outfits] = await Promise.all([get('/v1/wardrobe' + (UI.priv ? '?private=1' : '')),
        get('/v1/laundry'), get('/v1/laundry/review'), get('/v1/outfits')]);
      Object.assign(UI, { view: view.failed ? null : view, laundry, review, outfits });
      if (view.failed) say('bad', view.words);
      draw();
    } catch (e) { failed(e); } finally { UI.loading = null; }
  })();
  return UI.loading;
}
async function tool(name, args, done) { // the panel's change through the gateway (D1): the same cards and audit
  UI.busy = true;
  try {
    const r = await H.api('/v1/wardrobe/tools/' + name, { body: { arguments: args } });
    if (r && r.status === 'needs_approval') say('', 'That needs your OK: the card is waiting in the chat.');
    else if (r && r.status === 'executed') say('ok', H.txt(r.message || done || 'Done.', 200));
    else say('bad', H.txt((r && r.message) || 'That didn\u2019t work.', 200));
  } catch (e) { failed(e); } finally { UI.busy = false; }
  await load();
}

// ---- the sections ------------------------------------------------------------------------------------------------------
function draw() {
  const s = UI.secs;
  s.review.replaceChildren(H.mk('h3', 'hp-h', 'Needs a check'), ...reviewRows());
  s.plans.replaceChildren(H.mk('h3', 'hp-h', 'Today and tomorrow'), ...planRows());
  s.laundry.replaceChildren(H.mk('h3', 'hp-h', 'Laundry'), ...laundryRows());
  s.labels.replaceChildren(H.mk('h3', 'hp-h', 'Labels'), ...labelRows());
  s.settings.replaceChildren(H.mk('h3', 'hp-h', 'Settings'), ...settingRows());
  if (UI.pieces) UI.pieces.draw(s.pieces, ctx());
  else s.pieces.replaceChildren(H.mk('h3', 'hp-h', 'Pieces'), H.empty(UI.view ? 'Loading your pieces\u2026' : 'Your pieces will show here.'));
}
function down(v) { return !v || v.failed ? [H.empty((v && v.words) || 'Not available yet.')] : null; }
function reviewRows() {
  const bad = down(UI.review);
  if (bad) return bad;
  const entries = Array.isArray(UI.review.entries) ? UI.review.entries : [];
  if (!entries.length) return [H.empty('Nothing waits for a check.')];
  return entries.map((e) => {
    const picks = (e.candidates || []).map((id) => btn('This one: ' + nameOf(id), () => tool('laundry_review', { action: 'resolve', entry: e.id, piece: id })));
    if (e.kind === 'hold' || e.kind === 'pending_deposit') picks.push(btn('There was no deposit', () => tool('laundry_review', { action: 'resolve', entry: e.id, none: true })));
    const hidden = (e.candidates || []).some((id) => !pieceOf(id)) && !UI.priv;
    const box = H.mk('div', '');
    box.append(H.row(e.words, (e.pieces || []).map(nameOf).join(', ') + (e.opened_at ? ' \u00b7 since ' + when(e.opened_at, true) : '')), acts(...picks));
    if (hidden) box.append(H.mk('p', 'sfine', 'To tell private basics apart, tap Show private basics in Pieces.'));
    return box;
  });
}
function planRows() {
  const bad = down(UI.outfits);
  if (bad) return bad;
  const o = UI.outfits, out = [];
  if (o.weather) out.push(H.mk('p', 'sfine', H.txt(o.weather, 200)));
  [['Today', o.today], ['Tomorrow', o.tomorrow]].forEach(([day, plans]) => (plans || []).forEach((p) => out.push(...plan(day, p))));
  if (out.length <= 1) out.push(H.empty('No plan yet. Ask \u201cwhat should I wear tomorrow\u201d, or pick a calendar in Settings.'));
  return out;
}
function plan(day, p) {
  const head = [day, p.starts ? when(p.starts, true).split(', ').pop() : '', String(p.dress_code || '').replace(/_/g, ' ')].filter(Boolean).join(' \u00b7 ');
  const flags = [p.cancelled ? 'event cancelled: kept as a draft' : '', p.tentative ? 'dress code tentative' : '', p.manual ? 'planned by hand' : ''].filter(Boolean).join(', ');
  const box = H.mk('div', 'wd-plan');
  box.append(H.row(head, flags));
  ((p.look && p.look.pieces) || []).forEach((s) => box.append(H.row((SLOTS[s.slot] || H.txt(s.slot, 20)) + ': ' + (s.piece ? nameOf(s.piece) : H.txt(s.words, 80)), s.locked ? 'Locked' : '')));
  const why = [].concat((p.look && p.look.reasons) || [], (p.look && p.look.compromises) || []);
  if (why.length) box.append(H.mk('p', 'sfine', why.map((x) => H.txt(x, 160)).join('. ') + '.'));
  [].concat((p.look && p.look.gaps) || [], p.needs || []).forEach((g) => box.append(H.mk('p', 'snote warn', H.txt(g, 160))));
  if (!p.cancelled) box.append(acts(btn('Wearing it', () => tool('wear_log', { action: 'start', plan: p.id }, 'Enjoy the day.')), btn('Done for today', () => tool('wear_log', { action: 'done', plan: p.id }))));
  return [box];
}
function laundryRows() {
  const bad = down(UI.laundry);
  if (bad) return bad;
  const l = UI.laundry, out = [];
  const step = (ids, title, sub, label, args) => { if (!(ids || []).length) return; out.push(H.row(title + ' (' + ids.length + ')', ids.map(nameOf).join(', ') + (sub ? ' \u00b7 ' + sub : '')), acts(btn(label, () => tool('laundry_move', Object.assign({ pieces: ids }, args))))); };
  step(l.basket, 'In the basket', '', 'Start a wash with these', { step: 'washing' });
  (l.loads || []).forEach((ld) => step(ld.pieces, 'A wash load', String(ld.step || '').replace(/_/g, ' '), 'Now drying', { step: 'drying', load: ld.id }));
  step(l.drying, 'Drying', '', 'Back clean', { step: 'ready' });
  step(l.prep, 'Needs pressing', '', 'Pressed and back', { step: 'ready' });
  (l.batches || []).forEach((b) => {
    const flags = [b.due ? 'due ' + when(b.due) : '', b.overdue ? 'overdue' : '', b.short ? 'came back short' : ''].filter(Boolean).join(', ');
    out.push(H.row(H.txt(b.shop, 40) + (b.bag ? ' \u00b7 bag ' + H.txt(b.bag, 24) : ''), (b.pieces || []).length + ' pieces, ' + (b.back || []).length + ' back' + (flags ? ' \u00b7 ' + flags : '')));
    const out1 = (b.pieces || []).filter((id) => !(b.back || []).includes(id));
    if (out1.length) out.push(acts(...out1.map((id) => btn('Received: ' + nameOf(id), () => tool('laundry_send_out', { action: 'receive', batch: b.id, pieces: [id] })))));
  });
  if (!out.length) out.push(H.empty('Nothing in the laundry.'));
  out.push(H.mk('p', 'sfine', 'JARVIS prepares the laundry and reminds you; it never orders, pays, calls or sends a message.'));
  return out;
}
function labelRows() {
  const v = UI.view;
  if (!v) return [H.empty('Your labels will show here.')];
  const labels = v.labels || [], free = labels.filter((l) => !l.piece);
  const out = [H.row('A sheet of 24 QR labels', 'Numbers and codes only: stick one on each of two identical pieces.', [btn('Download the sheet', sheet)])];
  out.push(H.mk('p', 'sfine', labels.length ? labels.length + ' labels, ' + free.length + ' not on a piece yet.' : 'No labels printed yet.'));
  const pieces = (v.pieces || []).filter((p) => !p.label_code).map((p) => [p.id, nameOf(p.id)]);
  if (free.length && pieces.length) {
    const lab = select(free.map((l) => [l.code, 'No. ' + l.number]), free[0].code), pc = select(pieces, pieces[0][0]);
    const grid = H.mk('div', 'hp-grid');
    grid.append(field('Label', lab), field('Piece', pc));
    out.push(grid, acts(btn('Put this label on it', () => assign(lab.value, pc.value))));
  }
  return out;
}
async function assign(code, piece) {
  UI.busy = true;
  try { await H.api('/v1/wardrobe/labels', { body: { code, piece } }); say('ok', 'The label is on it.'); } catch (e) { failed(e); } finally { UI.busy = false; }
  await load();
}
function save(blob, file) { // our own bytes as a blob: URL (never server text in a link)
  const url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = file; a.rel = 'noopener'; a.hidden = true; document.body.append(a); a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1500);
}
async function rawGet(path, file, words) {
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function') { say('bad', 'Downloads are not available in this page.'); return; }
  UI.busy = true;
  try {
    const r = await chat.raw(path);
    if (!r.ok) throw new Error('The download did not work. Please try again.');
    save(await r.blob(), file);
    say('ok', words);
  } catch (e) { failed(e); } finally { UI.busy = false; }
}
const sheet = () => rawGet('/v1/wardrobe/labels.svg', 'jarvis-wardrobe-labels.svg', 'Saved the label sheet to your Downloads. Print it at 100 %.');

// ---- settings: the calendar (C's), AI tagging (A's), backup and restore ---------------------------------------------------
function settingRows() {
  const v = UI.view, set = (v && v.settings) || {}, out = [];
  out.push(H.row('Outfits from a calendar', set.calendar_chosen ? 'One calendar is chosen: plans are made from its events.' : 'None: plan by hand, or choose one calendar.', [btn('Choose a calendar', calendars)]));
  if (UI.cal) out.push(UI.cal);
  const outfit = (patch) => putSettings(Object.assign({ calendar: undefined, fields: set.fields || ['title'], lead_h: set.lead_h || 12, plan_alerts: set.plan_alerts !== false, auto_swap: !!set.auto_swap }, patch));
  const has = (f) => (set.fields || ['title']).includes(f);
  out.push(H.row('Use the event\u2019s title', 'Matched to dress codes in code only; never stored, sent or logged.', [H.toggle('Use the event title', has('title'), (on) => outfit({ fields: fieldsWith('title', on, set) }))]));
  out.push(H.row('Use the event\u2019s location', 'Indoor or outdoor, for the weather. Off unless you switch it on.', [H.toggle('Use the event location', has('location'), (on) => outfit({ fields: fieldsWith('location', on, set) }))]));
  out.push(H.row('Tomorrow\u2019s outfit, the evening before', 'An alert at 20:00 for an event on your calendar.', [H.toggle('Evening outfit alert', set.plan_alerts !== false, (on) => outfit({ plan_alerts: on }))]));
  out.push(H.row('Swap a planned piece by itself', 'Off: JARVIS suggests a ready one and you tap.', [H.toggle('Auto-swap', !!set.auto_swap, (on) => outfit({ auto_swap: on }))]));
  out.push(H.row('AI tagging', 'Off. When on: only for a saved piece that is not private, after the photo check, at most \u20b9' + (set.tag_cap_inr || 30) + ' a month; \u20b9' + Number(set.tag_month_inr || 0).toFixed(2) + ' this month.',
    [H.toggle('AI tagging', !!set.ai_tagging, (on) => wardrobeSettings({ ai_tagging: on }))]));
  const photos = H.mk('input', '');
  photos.type = 'checkbox'; photos.id = 'wdBackupPhotos';
  const tick = H.mk('label', 'hp-field wd-tick');
  tick.append(H.mk('span', 'snote', 'Include photos'), photos); // its words before the box (the visual gate)
  out.push(H.row('A sealed wardrobe backup', 'Up to 25 MB. ' + KEY_NOTE, [btn('Download', () => rawGet('/v1/wardrobe/backup' + (photos.checked ? '?photos=1' : ''), 'jarvis-wardrobe.backup', 'Saved the sealed backup to your Downloads.'))]), tick);
  out.push(...restoreRows());
  return out;
}
function fieldsWith(f, on, set) { const now = new Set(set.fields || ['title']); if (on) now.add(f); else now.delete(f); return ['title', 'location'].filter((x) => now.has(x)); }
async function wardrobeSettings(body) { // A's own settings: owner-only, never a tool the model can call (M6; I1 adds the route)
  UI.busy = true;
  try { await H.api('/v1/wardrobe/settings', { method: 'PUT', body }); say('ok', 'Saved.'); } catch (e) {
    if (e && (e.status === 404 || e.status === 405)) say('bad', 'This switch arrives with the next JARVIS update.'); else failed(e);
  } finally { UI.busy = false; }
  await load();
}
async function putSettings(body) {
  UI.busy = true;
  const b = Object.assign({}, body);
  if (b.calendar === undefined) delete b.calendar;
  try { await H.api('/v1/outfits/settings', { method: 'PUT', body: b }); say('ok', 'Saved.'); } catch (e) { failed(e); } finally { UI.busy = false; }
  await load();
}
async function calendars() { // a governed read (the Calendar row's Allow only); titles live, never kept
  const box = H.mk('div', 'hp-form');
  UI.cal = box;
  box.append(H.mk('p', 'snote', 'Asking Google for your calendars\u2026'));
  draw();
  const c = await get('/v1/outfits/calendars');
  if (c.failed || c.why || !(c.calendars || []).length) { box.replaceChildren(H.mk('p', 'snote warn', H.txt(c.why || c.words || 'No calendar to choose.', 200))); return; }
  const pick = select([['', 'None: plan by hand'], ...c.calendars.map((x) => [x.id_ref, H.txt(x.title, 60) + (x.primary ? ' (your main one)' : '')])], '');
  box.replaceChildren(field('Make plans from', pick), acts(btn('Use this calendar', () => { UI.cal = null; putSettings({ calendar: pick.value || null, fields: ((UI.view && UI.view.settings) || {}).fields || ['title'] }); }), btn('Cancel', () => { UI.cal = null; draw(); })));
}
function restoreRows() {
  const file = H.mk('input', 'minput');
  file.type = 'file'; file.accept = '.backup,application/octet-stream';
  file.addEventListener('change', () => { UI.file = file.files && file.files[0]; UI.check = null; if (UI.file) restoreCheck(); });
  const out = [field('Restore from a backup file', file)];
  const c = UI.check;
  if (c) {
    const n = c.counts || {};
    out.push(H.row('What this backup would do', 'Add ' + (n.added || 0) + ', already here ' + (n.already_there || 0) + ', older than yours ' + (n.superseded || 0) + ', back from Recently deleted ' + (n.back_from_bin || 0) + ', purged since ' + (n.purged_since || 0) + '. ' + H.txt(c.message, 120)));
    out.push(acts(btn('Restore', restore, 'primary'), btn('Cancel', () => { UI.check = null; UI.file = null; draw(); })));
  }
  return out;
}
async function restoreCheck() { // confirm before commit: the check writes nothing
  const chat = window.JarvisChat;
  if (!chat || typeof chat.raw !== 'function' || !UI.file) return;
  UI.busy = true;
  try {
    const r = await chat.raw('/v1/wardrobe/restore/check', { method: 'POST', body: UI.file, headers: { 'Content-Type': 'application/octet-stream' } });
    const j = await r.json().catch(() => null);
    if (!r.ok) throw new Error((j && typeof j.detail === 'string' && j.detail) || 'That file can\u2019t be restored.');
    UI.check = j;
    say('', 'Checked: nothing is changed until you press Restore.');
  } catch (e) { failed(e); } finally { UI.busy = false; }
  draw();
}
async function restore() {
  const chat = window.JarvisChat, c = UI.check;
  if (!chat || !c || !UI.file) return;
  UI.busy = true;
  try {
    const r = await chat.raw('/v1/wardrobe/restore?token=' + encodeURIComponent(c.token), { method: 'POST', body: UI.file, headers: { 'Content-Type': 'application/octet-stream' } });
    const j = await r.json().catch(() => null);
    if (!r.ok) throw new Error((j && typeof j.detail === 'string' && j.detail) || 'The restore did not work.');
    say('ok', H.txt((j && j.message) || 'Restored.', 200));
  } catch (e) { failed(e); } finally { UI.busy = false; UI.check = null; UI.file = null; }
  await load();
}

// ---- the tab ------------------------------------------------------------------------------------------------------------
function ctx() {
  return { H, view: UI.view, priv: UI.priv, nameOf, placeOf, tool, btn, acts, field, select, when,
    show(on) { UI.priv = !!on; load(); }, detail: (id) => H.api('/v1/wardrobe/pieces/' + encodeURIComponent(id)) };
}
function mount(host) {
  UI.host = host;
  UI.note = H.mk('p', 'sfine hp-note');
  UI.note.setAttribute('role', 'status');
  ['review', 'plans', 'laundry', 'pieces', 'labels', 'settings'].forEach((k) => { UI.secs[k] = H.section(''); UI.secs[k].replaceChildren(); });
  host.append(UI.note, ...['review', 'plans', 'laundry', 'pieces', 'labels', 'settings'].map((k) => UI.secs[k]));
  draw();
  if (signedIn()) load(); else say('', 'Sign in to see your wardrobe.');
}
if (H) {
  H.register('wardrobe', { mount, refresh() { if (UI.host && signedIn() && !UI.busy) load(); } });
  document.addEventListener('jarvis:ready', () => { if (UI.host) load(); });
}
import('./console-wardrobe-pieces.js').then((m) => { UI.pieces = m; if (UI.host) draw(); }).catch(() => { if (UI.secs.pieces) UI.secs.pieces.append(H.empty('This part couldn\u2019t load.')); });
