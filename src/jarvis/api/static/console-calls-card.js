// src/jarvis/api/static/console-calls-card.js -- R18 E (docs/plans/r18-calls.md section 4 steps 1-2 and 9; plan 6):
// the call card, the same in the chat (under the reply that made it, ChatResponse.cards kind 'call_card') and in
// Calls -> New call. It names the number (only its last 4 digits), who it is, the purpose, what JARVIS may tell them
// and agree to, a booking's limits (the times it may accept, the name and number to give, the reason, the calendar
// entry; never a payment), the languages (the first is the one it opens in), the longest it may last and its rupee
// estimate, and says plainly when the laptop or the phone is not ready (a Bluetooth headset on the laptop included).
// Call is the owner's approval (R3: a call speaks for him and cannot be undone): one press, a passkey first for a
// number JARVIS has never called (the cloud answers needs_passkey with the approval to sign), never a "don't ask again". Edit puts the card back in
// Calls -> New call; Cancel drops it. Nothing is dialled by this file: the cloud places the call after the approval.
// ASCII source; textContent only.
import { PATHS, api, button, chip, failed, langName, masked, mk, rupees, say, uid, wholeRupees } from './console-calls-api.js';
import { CARD_WORDS, STATE_WORDS, card as checkCard, isLive } from './console-calls-shapes.js';

const NO_PAY = 'No payment: JARVIS never agrees to pay, and never reads out OTPs, card, bank, Aadhaar or PAN numbers.';
const DISCLOSE = 'It says first that it is an AI assistant calling for you, and that the call is recorded.';
const BT = 'A Bluetooth headset is connected to the laptop: Phone Link refuses calls then. Disconnect it, or use the laptop\u2019s speaker or a wired headset.';
const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });

export function slotWords(w) { // {day: "2026-11-28", start: "10:00", end: "12:00"} -> "Sat 28 Nov, 10:00-12:00"
  const [y, m, d] = w.day.split('-').map(Number);
  let day = w.day;
  try { day = DAY.format(new Date(Date.UTC(y, m - 1, d))).replace(',', ''); } catch (_) { /* the date as given */ }
  return day + ', ' + w.start + '\u2013' + w.end;
}
function row(label, value, cls) {
  const r = mk('div', 'cl-kv' + (cls ? ' ' + cls : ''));
  r.append(mk('span', 'k', label));
  if (typeof value === 'string') r.append(mk('span', 'cl-v', value)); else r.append(value);
  return r;
}
function lines(list) {
  const ul = mk('ul', 'blines cl-v');
  list.forEach((t) => ul.append(mk('li', '', t)));
  return ul;
}
const placed = (c) => !!c.callId && (c.status === 'approved' || c.status === 'used');
function chipFor(c) {
  if (c.callState) {
    const s = c.callState;
    return chip(STATE_WORDS[s], s === 'ended' ? 'ok' : isLive(s) ? 'amber' : 'red');
  }
  return chip(CARD_WORDS[c.status], c.status === 'draft' ? 'unknown' : c.status === 'approved' || c.status === 'used' ? 'ok' : 'red');
}
/** What stops the call now: the card's own ready check, and the console's last word from the desk and the phone. */
function problemsOf(c, live) {
  const out = c.ready.problems.slice();
  if (live) {
    if (live.desk.btHeadset && !out.some((p) => /bluetooth/i.test(p))) out.unshift(BT);
    if (!live.desk.connected && !out.length) out.push('The call desk on your laptop isn\u2019t running.');
    if (!live.phone.linked && !out.some((p) => /phone app/i.test(p))) out.push('The JARVIS phone app isn\u2019t linked.');
  }
  if (c.ready.known && !c.ready.ok && !out.length) out.push('The laptop or the phone isn\u2019t ready yet.');
  return out;
}

/** Draws card `c` (checked) into a fresh <section>; `ctx` = {ready(), openLive(id), openRecord(id), edit(card)}. */
export function render(c, ctx) {
  const sec = mk('section', 'mcard cl-card');
  const title = mk('b', 'cl-ctitle', 'Call ' + (c.who ? c.who : masked(c.number4)));
  title.id = uid('clct');
  sec.setAttribute('aria-labelledby', title.id);
  sec.dataset.card = c.id;
  const head = mk('div', 'cl-chead');
  const body = mk('div', 'cl-cbody');
  const ready = mk('div', 'cl-cready');
  const acts = mk('div', 'sacts cl-cacts');
  const note = mk('p', 'snote'); note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite');
  const err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
  sec.append(head, body, ready, acts, note, err);
  const S = { c, busy: false };

  function paintBody() {
    const k = S.c, num = mk('span', 'cl-v cl-num', masked(k.number4));
    num.setAttribute('aria-label', k.number4 ? 'Number ending ' + k.number4.split('').join(' ') : 'A number');
    body.replaceChildren(row('Number', num));
    if (k.passkey) body.append(row('', 'JARVIS hasn\u2019t called this number before: your passkey approves it.', 'cl-fine'));
    body.append(row('Purpose', k.purpose || '\u2014'));
    if (k.maySay.length) body.append(row('May tell them', lines(k.maySay)));
    if (k.mayAgree.length) body.append(row('May agree to', lines(k.mayAgree)));
    const b = k.booking;
    if (b) {
      body.append(row('Times it may accept', b.windows.length ? lines(b.windows.map(slotWords)) : '\u2014'));
      if (b.name) body.append(row('Name to give', b.name));
      if (b.number4) body.append(row('Number to give', mk('span', 'cl-v cl-num', masked(b.number4))));
      if (b.reason) body.append(row('Reason', b.reason));
      body.append(row('Calendar', b.calendar ? 'Adds a ' + b.minutes + '-minute entry after the call, with Undo' : 'Not added'));
    }
    const names = (k.languages.length ? k.languages : ['en-IN']).map((l, i) => langName(l) + (i === 0 && k.languages.length > 1 ? ' (opens)' : ''));
    body.append(row('Languages', names.join(', ')));
    if (k.maxMinutes) body.append(row('At most', k.maxMinutes + (k.maxMinutes === 1 ? ' minute' : ' minutes')));
    body.append(row('Cost', k.estimate === null ? 'Not estimated yet' : rupees(k.estimate) + (k.maxInr ? ' (at most ' + wholeRupees(k.maxInr) + ')' : '')));
    body.append(mk('p', 'sfine', NO_PAY), mk('p', 'sfine', DISCLOSE));
  }
  function paint() {
    const k = S.c, waiting = k.status === 'draft';
    head.replaceChildren(title, chipFor(k));
    ready.replaceChildren();
    const problems = waiting ? problemsOf(k, ctx && ctx.ready ? ctx.ready() : null) : [];
    if (problems.length) {
      const box = mk('div', 'bnote bad');
      box.append(mk('b', '', 'Nothing is dialled until this is fixed:'), lines(problems));
      ready.append(box);
    }
    const list = [];
    if (waiting) {
      const go = button(k.needsKey ? 'Approve with passkey' : 'Call', 'primary sact', () => place(!!k.needsKey));
      go.setAttribute('aria-describedby', title.id);
      go.disabled = S.busy || k.estimate === null || problems.length > 0;
      list.push(go, button('Edit', 'sact', () => { if (ctx && ctx.edit) ctx.edit(S.c); }), button('Cancel', 'sact', () => cancel()));
      list.slice(1).forEach((b) => { b.disabled = S.busy; });
    } else if (placed(k) && (!k.callState || isLive(k.callState))) {
      list.push(button('Open the live call', 'primary sact', () => ctx && ctx.openLive(k.callId)));
    } else if (placed(k)) {
      list.push(button('Open the record', 'sact', () => ctx && ctx.openRecord(k.callId)));
    }
    acts.replaceChildren(...list);
    if (k.why) say(note, k.why);
    sec.setAttribute('aria-busy', S.busy ? 'true' : 'false');
  }
  function set(next) { if (next) { S.c = next; paintBody(); } paint(); }
  async function place(withKey) {
    if (S.busy) return;
    err.textContent = '';
    S.busy = true; paint();
    const body = {};
    try {
      if (withKey) { // his press on Approve with passkey: the check first, while the press counts as his gesture
        body.approval_id = S.c.approvalId;
        body.passkey = await passkey(S.c.approvalId);
      }
      say(note, 'Asking your laptop and phone to get ready\u2026');
      const r = await api(PATHS.cards + '/' + encodeURIComponent(S.c.id) + '/approve', { body });
      if (r && r.status === 'needs_passkey' && typeof r.approval_id === 'string' && /^[A-Za-z0-9_:.-]{1,128}$/.test(r.approval_id)) {
        S.busy = false;
        S.c = { ...S.c, approvalId: r.approval_id, needsKey: true };
        paint();
        say(note, 'Your passkey approves this call. Press Approve with passkey.');
        const go = acts.querySelector('.btn.primary'); if (go) go.focus();
        return;
      }
      const cid = r && typeof r.call_id === 'string' ? r.call_id : '';
      S.busy = false;
      set({ ...S.c, status: 'approved', needsKey: false, callId: cid || S.c.callId });
      say(note, 'Approved. JARVIS is placing the call from your phone.', 'ok');
      if (ctx && S.c.callId) ctx.openLive(S.c.callId);
    } catch (e) {
      S.busy = false;
      say(note, '');
      paint();
      err.textContent = e && e.passkeyMessage ? e.passkeyMessage : failed(e);
    }
  }
  async function cancel() {
    if (S.busy) return;
    S.busy = true; paint();
    try {
      const r = await api(PATHS.cards + '/' + encodeURIComponent(S.c.id) + '/cancel', { body: {} });
      S.busy = false;
      set(checkCard((r && r.card) || r) || { ...S.c, status: 'cancelled' });
      say(note, 'Cancelled. Nothing was dialled.');
    } catch (e) { S.busy = false; paint(); err.textContent = failed(e); }
  }
  paintBody();
  paint();
  return Object.freeze({ el: sec, update: (next) => set(next), card: () => S.c, repaint: paint });
}

function passkey(approvalId) { // the existing passkey door (console-permissions.js): purpose "approve", this call's approval
  const P = window.JarvisPasskey;
  if (!P || typeof P.approve !== 'function') return Promise.reject(new Error('Passkeys are still loading. Try again in a moment.'));
  return P.approve(approvalId).catch((e) => {
    const words = typeof P.message === 'function' ? P.message(e) : 'The passkey check wasn\u2019t completed.';
    throw Object.assign(new Error(words), { passkeyMessage: words });
  });
}

/** The chat: every reply's ChatResponse.cards; the call cards ('call_card') are drawn under the reply, once. */
export function chatCards(row, list, ctx) {
  if (!row || !Array.isArray(list) || row.querySelector('.cl-card')) return [];
  const made = list.filter((x) => x && typeof x === 'object' && x.kind === 'call_card').slice(0, 2).map(checkCard).filter(Boolean);
  if (!made.length) return [];
  const wrap = mk('div', 'mcards cl-cards');
  const drawn = made.map((c) => render(c, ctx));
  drawn.forEach((d) => wrap.append(d.el));
  row.append(wrap);
  return drawn;
}
