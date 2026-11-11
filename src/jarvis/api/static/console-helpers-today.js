// src/jarvis/api/static/console-helpers-today.js -- R11 Part A's tab in the Helpers panel
// (docs/plans/r11-free-helpers.md D7-D9, D19): top priority now, what is pending, bills and the prepared UPI
// payment, birthdays. An ES module loaded by console-helpers.js (never linked). It builds with
// window.JarvisHelpers only (H.section / H.row / H.toggle / H.empty / H.note / H.mk / H.api) and the existing
// components (.btn .bact, .bsw, .fform .ffield .tin, .sfine); every server string reaches the page through
// textContent or an input's value, never markup. No new colours, fonts, radii or shadows; ASCII source.
// A UPI ID and a payment are R3 cards made through the gateway in his open conversation: the tab shows the
// waiting card's own words with Approve / Decline (his passkey when one is in force; the server checks it).
// The approved payment (a upi://pay link and its QR) is fetched ONCE, shown in the bill's row, and dropped
// from the page after 10 minutes or on Done. JARVIS never pays: he finishes it in his UPI app with his PIN.
const H = window.JarvisHelpers;
const BASE = '/v1/helpers/today';
const UPI = /^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$/;
const LINK = /^upi:\/\/pay\?[A-Za-z0-9%@._~=&-]{1,1000}$/;
const QR = /^data:image\/svg\+xml;charset=utf-8,/;
const SHOW_MS = 10 * 60 * 1000;
const RUPEE = '\u20b9';
const S = { host: null, view: null, err: '', note: null, adding: false, waiting: {}, shown: {}, editing: null, paying: null, removing: null };

function btn(text, onClick, cls) {
  const b = H.mk('button', 'btn bact' + (cls ? ' ' + cls : ''), text);
  b.type = 'button';
  b.style.marginTop = '0';
  b.addEventListener('click', onClick);
  return b;
}
function input(type, max, label) {
  const i = H.mk('input', 'tin');
  i.type = type;
  if (max) i.maxLength = max;
  i.autocomplete = 'off';
  i.spellcheck = false;
  if (label) i.setAttribute('aria-label', label);
  return i;
}
function field(label, control) {
  const l = H.mk('label', 'ffield');
  l.append(H.mk('span', 'sfine', label), control);
  return l;
}
function plain(e) {
  if (e && e.name === 'TypeError') return 'Can\u2019t reach JARVIS. Check your connection.';
  return H.txt(e && e.message ? e.message : 'That didn\u2019t work.', 240);
}
function session() {
  try { return window.JarvisApprovals ? window.JarvisApprovals.session() : null; } catch (_) { return null; }
}
function say(kind, text) { if (S.note) H.note(S.note, kind, text); }

async function load() {
  try { S.view = await H.api(BASE); S.err = ''; } catch (e) { S.err = plain(e); }
  Object.keys(S.waiting).forEach((id) => { // decided elsewhere (Approvals): drop its card here
    const b = billById(id);
    if (!b || (S.waiting[id].pay && b.ready)) delete S.waiting[id];
  });
  render();
}
async function change(path, opts, okText) {
  try {
    const v = await H.api(BASE + path, opts);
    if (v && v.bills) S.view = v;
    render();
    if (okText) say('ok', okText);
    return true;
  } catch (e) { say('bad', plain(e)); return false; }
}

// ---- top priority and pending ---------------------------------------------------------------------------------
function whenWords(item) { return { overdue: 'Overdue', today: 'Due today', soon: 'Soon', later: 'This week' }[item.urgency] || ''; }
function focusSection(v) {
  const sec = H.section('Top priority now');
  const top = v.top;
  sec.append(top ? H.row(top.label, [H.txt(top.source, 40), whenWords(top)].filter(Boolean).join(' \u00b7 ')) : H.empty('Nothing pending, Sir.'));
  const groups = Array.isArray(v.pending) ? v.pending : [];
  const rest = [];
  groups.forEach((g) => (Array.isArray(g.items) ? g.items : []).forEach((i) => rest.push([g.source, i])));
  if (top && rest.length && rest[0][1].label === top.label) rest.shift(); // the top one is said above
  if (!rest.length) return [sec];
  const more = H.section('Also pending');
  rest.forEach(([src, i]) => more.append(H.row(i.label, [H.txt(src, 40), whenWords(i)].filter(Boolean).join(' \u00b7 '))));
  return [sec, more];
}
function actLine(buttons) { // a bill's actions on their own line under its words, wrapping on a phone
  const line = H.mk('div', 'hp-acts');
  line.style.flexWrap = 'wrap';
  line.style.padding = '0 0 10px';
  buttons.forEach((b) => line.append(b));
  return line;
}

// ---- bills ------------------------------------------------------------------------------------------------------
function billSub(b) {
  const pays = b.upi ? 'pays ' + (b.payee || b.label) + ' (' + b.upi + ')' : 'no UPI ID yet';
  return [b.amount, b.when, pays].filter(Boolean).join(' \u00b7 ');
}
function billRow(b) {
  const acts = [];
  if (b.ready) acts.push(btn('Show payment', () => showPayment(b), 'primary'));
  else if (b.upi) acts.push(btn('Pay', () => askPay(b)));
  acts.push(btn(b.upi ? 'UPI ID' : 'Set UPI ID', () => { S.editing = S.editing === b.id ? null : b.id; render(); }));
  acts.push(btn('Paid', () => change('/bills/' + encodeURIComponent(b.id) + '/paid', { method: 'POST', body: {} }, 'Marked paid, Sir.')));
  acts.push(btn('Remove', () => { S.removing = S.removing === b.id ? null : b.id; render(); }));
  const wrap = H.mk('div', '');
  wrap.dataset.bill = String(b.id);
  wrap.append(H.row(b.label, billSub(b)), actLine(acts));
  if (S.removing === b.id) {
    wrap.append(H.row('Remove the ' + H.txt(b.label, 40) + ' bill?', 'Its reminders stop. JARVIS keeps no copy.'));
    wrap.append(actLine([btn('Remove it', () => removeBill(b), 'danger'), btn('Keep it', () => { S.removing = null; render(); })]));
  }
  if (S.paying === b.id) wrap.append(amountForm(b));
  if (S.editing === b.id) wrap.append(upiForm(b));
  if (S.waiting[b.id]) wrap.append(waitingCard(b, S.waiting[b.id]));
  if (S.shown[b.id]) wrap.append(paymentBox(b, S.shown[b.id]));
  return wrap;
}
function removeBill(b) {
  S.removing = null;
  change('/bills/' + encodeURIComponent(b.id), { method: 'DELETE' }, 'Removed, Sir.');
}
function upiForm(b) {
  const form = H.mk('div', 'fform');
  const upi = input('text', 330); upi.placeholder = 'name@bank'; upi.value = b.upi || '';
  const payee = input('text', 40); payee.value = b.payee || '';
  const ask = btn('Ask to set it', async () => {
    const v = upi.value.trim();
    if (!UPI.test(v)) { say('bad', 'That isn\u2019t a UPI ID (like name@bank), Sir.'); return; }
    await propose(b, '/bills/' + encodeURIComponent(b.id) + '/payee', { upi: v, payee: payee.value.trim() || null });
  });
  form.append(field('UPI ID (type it yourself)', upi), field('Payee name', payee), ask);
  return form;
}
async function propose(b, path, body) {
  const sid = session();
  try {
    const r = await H.api(BASE + path, { body: Object.assign({}, body, { session_id: sid || null }) });
    S.waiting[b.id] = { id: String(r.approval_id || ''), sid, card: H.txt(r.card || '', 300), pay: path.endsWith('/pay') };
    S.editing = null;
    render();
    say('', H.txt(r.detail || 'Approve it, Sir.', 200));
  } catch (e) { say('bad', plain(e)); }
}
function askPay(b) {
  if (b.amount && b.amount.indexOf(RUPEE) !== 0) { S.paying = S.paying === b.id ? null : b.id; render(); return; }
  propose(b, '/bills/' + encodeURIComponent(b.id) + '/pay', {});
}
function amountForm(b) {
  const form = H.mk('div', 'fform');
  const amount = input('text', 30); amount.placeholder = '1240.50';
  const ask = btn('Ask to pay this', () => {
    const v = amount.value.trim();
    if (!/^[0-9][0-9,]{0,14}(\.[0-9]{1,2})?$/.test(v)) { say('bad', 'Rupees, like 1240.50, Sir.'); return; }
    S.paying = null;
    propose(b, '/bills/' + encodeURIComponent(b.id) + '/pay', { amount: v });
  }, 'primary');
  form.append(field('This bill\u2019s amount varies: rupees to pay', amount), ask);
  return form;
}
function waitingCard(b, w) {
  const box = H.mk('div', 'fform');
  box.append(H.mk('p', 'sfine', w.card || 'Waiting for your OK, Sir.'));
  box.append(actLine([btn('Approve', () => decide(b, w, 'approve'), 'primary'), btn('Decline', () => decide(b, w, 'decline'))]));
  return box;
}
async function decide(b, w, action) {
  if (!w.id || !w.sid) { say('bad', 'Approve it in Approvals, Sir.'); return; }
  const url = '/v1/approvals/' + encodeURIComponent(w.id) + '/' + action;
  try {
    try { await H.api(url, { body: { session_id: w.sid } }); }
    catch (e) {
      if (action !== 'approve' || e.status !== 403 || !window.JarvisPasskey) throw e;
      const passkey = await window.JarvisPasskey.approve(w.id); // his passkey rule: checked again by the server
      await H.api(url, { body: { session_id: w.sid, passkey } });
    }
  } catch (e) { say('bad', window.JarvisPasskey && e.status === 403 ? window.JarvisPasskey.message(e) : plain(e)); return; }
  delete S.waiting[b.id];
  await load();
  if (action === 'approve' && w.pay) { const fresh = billById(b.id); if (fresh) await showPayment(fresh); }
  else say('ok', action === 'approve' ? 'Done, Sir.' : 'Nothing was changed, Sir.');
}
function billById(id) {
  const items = S.view && S.view.bills && Array.isArray(S.view.bills.items) ? S.view.bills.items : [];
  return items.find((x) => x.id === id) || null;
}
async function showPayment(b) {
  try {
    const p = await H.api(BASE + '/bills/' + encodeURIComponent(b.id) + '/payment', { body: {} });
    if (!p || !LINK.test(String(p.link || '')) || !QR.test(String(p.qr || ''))) throw new Error('That payment didn\u2019t look right, so it isn\u2019t shown.');
    S.shown[b.id] = { link: p.link, qr: p.qr, words: [p.amount, 'to', p.payee, '(' + p.upi + ')', '\u00b7 note', p.note].map((x) => H.txt(String(x || ''), 60)).join(' ') };
    setTimeout(() => { delete S.shown[b.id]; render(); }, SHOW_MS);
    await load();
  } catch (e) { say('bad', plain(e)); load(); }
}
function paymentBox(b, p) {
  const box = H.mk('div', 'fform');
  box.append(H.mk('p', 'sfine', p.words + '. Check it in your UPI app and enter your PIN there. JARVIS never pays.'));
  const img = H.mk('img', '');
  img.alt = 'QR code of this UPI payment';
  img.width = 180; img.height = 180;
  img.src = p.qr;
  box.append(img);
  box.append(actLine([btn('Open in UPI app', () => { window.location.assign(p.link); }, 'primary'), btn('Done', () => { delete S.shown[b.id]; render(); })]));
  return box;
}
function addForm() {
  const form = H.mk('div', 'fform');
  const label = input('text', 40); label.placeholder = 'Electricity';
  const payee = input('text', 40);
  const amount = input('text', 30); amount.placeholder = '1240 or varies';
  const day = input('number', 2); day.min = '1'; day.max = '31'; day.placeholder = '13';
  const every = H.mk('select', 'tin');
  [['1', 'Every month'], ['3', 'Every 3 months'], ['6', 'Every 6 months'], ['12', 'Every year']].forEach(([v, t]) => {
    const o = H.mk('option', '', t); o.value = v; every.append(o);
  });
  const save = btn('Keep this bill', async () => {
    const body = { label: label.value.trim(), payee: payee.value.trim(), amount: amount.value.trim() || 'varies', day: parseInt(day.value, 10), every_months: parseInt(every.value, 10) };
    if (!body.label || !(body.day >= 1 && body.day <= 31)) { say('bad', 'A name and a day of the month (1 to 31), Sir.'); return; }
    if (await change('/bills', { body }, 'Kept, Sir. Set its UPI ID to pay it from here.')) { S.adding = false; render(); }
  }, 'primary');
  form.append(field('Bill name', label), field('Payee name', payee), field('Amount in rupees', amount), field('Day of the month it is due', day), field('How often', every), save);
  form.append(H.mk('p', 'sfine', 'Never type a card, account or consumer number here: the last 4 digits at most.'));
  return form;
}
function billsSection(v) {
  const sec = H.section('Bills');
  const bills = v.bills || {};
  if (bills.available === false) { sec.append(H.empty(bills.note || 'Bills are off on this server.')); return sec; }
  const items = Array.isArray(bills.items) ? bills.items : [];
  if (!items.length) sec.append(H.empty('No bills yet. Add one and JARVIS reminds you 3 days, 1 day and on the day.'));
  items.forEach((b) => sec.append(billRow(b)));
  const prefs = bills.prefs || {};
  const at = input('time', 5, 'Bill reminders at'); at.value = prefs.bills_at || '09:00';
  const saveAt = btn('Save time', () => change('/prefs', { method: 'PUT', body: { bills_at: at.value } }, 'Saved, Sir.'));
  const timeRow = H.mk('div', 'fform');
  timeRow.append(field('Bill reminders at', at), saveAt);
  sec.append(H.row(S.adding ? 'New bill' : 'Add a bill', 'JARVIS keeps it encrypted and never pays it.', [btn(S.adding ? 'Cancel' : 'Add a bill', () => { S.adding = !S.adding; render(); })]));
  if (S.adding) sec.append(addForm());
  sec.append(timeRow);
  return sec;
}

// ---- birthdays --------------------------------------------------------------------------------------------------
function birthdaysSection(v) {
  const sec = H.section('Birthdays');
  const bd = v.birthdays || {};
  const sw = H.toggle('Birthday reminders', !!bd.on, (on) => change('/prefs', { method: 'PUT', body: { birthdays_on: on } }, on ? 'Birthday reminders on, Sir.' : 'Birthday reminders off, Sir.'));
  sec.append(H.row('Birthday reminders', 'From your Google Contacts at ' + H.txt(bd.at || '08:30', 5) + '. The alert names nobody unless names in alerts is on.', [sw]));
  if (!bd.on) return sec;
  if (bd.state && bd.state !== 'ok') { sec.append(H.empty(bd.note || 'Birthdays can\u2019t be read just now.')); return sec; }
  const today = Array.isArray(bd.today) ? bd.today : [];
  const soon = Array.isArray(bd.soon) ? bd.soon : [];
  if (!today.length && !soon.length) sec.append(H.empty('No birthdays this week.'));
  today.forEach((name) => sec.append(H.row(name, 'Today')));
  soon.forEach((s) => sec.append(H.row(s.name, s.on)));
  return sec;
}

function render() {
  const host = S.host;
  if (!host) return;
  host.textContent = '';
  S.note = H.mk('p', 'sfine hp-note');
  S.note.setAttribute('role', 'status');
  host.append(S.note);
  if (!S.view) { host.append(H.empty(S.err || 'Loading\u2026')); return; }
  const v = S.view;
  focusSection(v).forEach((s) => host.append(s));
  host.append(billsSection(v), birthdaysSection(v));
  if (Array.isArray(v.not_checked) && v.not_checked.length) host.append(H.empty('Not checked just now: ' + v.not_checked.map((x) => H.txt(String(x), 30)).join(', ') + '.'));
}

if (H) {
  H.register('today', {
    // mount runs at page load (before sign-in): it only draws; the data is asked for when the shell has
    // opened the panel and read /v1/helpers (refresh), so a signed-out page never calls the API
    mount(host) { S.host = host; render(); },
    refresh() { if (S.host) load(); },
  });
}
