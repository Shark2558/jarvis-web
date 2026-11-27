// src/jarvis/api/static/console-calls-form.js -- R18 E: Calls -> New call. A ready card (jarvis.calls.templates: the
// Laundry pickup and the laundry's status, rows 195-197, and an appointment), whose own words the cloud writes from the
// few fields it takes, or a blank card with the fields of plan section 4 step 1 (the number or a saved contact, the
// purpose, what JARVIS may tell them and agree to) and a booking's limits (step 9: up to 6 time windows, the name and
// number to give, the reason, the calendar entry; never a payment). Both take English plus up to 3 of the languages
// that PASSED the language check (5.3), the one it opens in, and the longest the call may last (at most the per-call
// cap). "Make the card" sends A1's body (a PlaceArgs draft, or {template, fields}); the card (console-calls-card.js)
// shows under the form with Call, Edit and Cancel. Edit puts a card's fields back here; saving makes a NEW card
// ({replaces}: a new estimate, a new approval; the old one is cancelled). Only a number's last 4 digits are shown.
// ASCII source; textContent only.
import { MAX_INDIAN, PATHS, api, button, failed, field, input, langName, lastFourOf, mk, option, say, toggle, uid } from './console-calls-api.js';
import { card as checkCard } from './console-calls-shapes.js';
import { render } from './console-calls-card.js';

const NUMBER_HELP = 'An Indian number, or leave it empty and give a saved contact\u2019s name below. JARVIS never calls emergency, premium-rate or international numbers.';
const LINES_HELP = 'One per line.';
const AGREE_HELP = 'One per line. Anything else gets \u201cI will check with you and call back\u201d.';
const NONE_PASSED = 'No Indian language has passed the language check yet: this call is in English. Run the check in Languages.';
const WINDOWS_MAX = 6, LINES_MAX = 10, LINE_MAX = 200;

/** "90000 00001", "090000 00001", "+91 90000 00001" -> "+919000000001"; anything else as typed (the server says why). */
export function e164(typed) {
  const t = String(typed || '').trim(), d = t.replace(/\D/g, '');
  if (!d) return '';
  if (t.startsWith('+')) return '+' + d;
  if (d.length === 10) return '+91' + d;
  if (d.length === 11 && d.startsWith('0')) return '+91' + d.slice(1);
  if (d.length === 12 && d.startsWith('91')) return '+' + d;
  return t;
}
const splitLines = (v) => v.split('\n').map((s) => s.trim()).filter(Boolean);
const wrap = (...kids) => { const d = mk('div', ''); d.append(...kids); return d; };

export function mount(host, ctx) {
  const S = { templates: [], tpl: null, editing: null, busy: false, booking: false, calendar: true, wanted: [], first: 'en-IN' };
  const intro = mk('p', 'sfine', 'Tell JARVIS who to call and why, here or in the chat. Nothing is dialled until you press Call on the card.');
  const tplSel = mk('select', 'bsel cl-wide');
  tplSel.append(new Option('A blank call', ''));
  tplSel.addEventListener('change', () => useTemplate(S.templates.find((t) => t.id === tplSel.value) || null));
  const tplNote = mk('p', 'sfine');
  const number = input('tel', 20); number.inputMode = 'tel';
  const numberNote = mk('small', 'mhelp');
  const who = input('text', 60);
  const purpose = input('textarea', 300); purpose.rows = 2;
  const say1 = input('textarea', 1000); say1.rows = 2;
  const agree = input('textarea', 1000); agree.rows = 2;
  const giveName = input('text', 60), giveNumber = input('tel', 20), reason = input('text', 220), length = input('text', 3);
  const place = input('text', 60), items = input('text', 3), order = input('text', 80);
  giveNumber.inputMode = 'tel'; length.inputMode = 'numeric'; items.inputMode = 'numeric';
  const winBox = mk('div', 'cl-windows');
  const addWin = button('Add a time', 'sact', () => { addWindow(null); const last = winBox.lastElementChild; if (last) last.querySelector('input').focus(); });
  const calSw = toggle('', '', true, (on, set) => { set(on); S.calendar = on; });
  const calRow = option('Add it to my calendar after the call', 'With Undo in the call\u2019s record.', (l, s) => { calSw.el.setAttribute('aria-labelledby', l); if (s) calSw.el.setAttribute('aria-describedby', s); return calSw.el; });
  const F = { // every part that a ready card may leave out
    purpose: field('Purpose', purpose), maySay: field('What JARVIS may tell them', say1, LINES_HELP),
    mayAgree: field('What JARVIS may agree to', agree, AGREE_HELP), place: field('Where (the clinic, the service centre)', place),
    items: field('How many items (optional)', items), order: field('Order number or note (optional)', order),
    windows: wrap(mk('span', 'bl', 'Times it may accept'), mk('small', 'mhelp', 'JARVIS accepts only a slot inside one of these and repeats it back to confirm.'), winBox, rowOf(addWin)),
    giveName: field('Name to give', giveName), giveNumber: field('Number to give (optional)', giveNumber, 'Your call-back number, if they ask.'),
    reason: field('Reason', reason), length: field('The appointment lasts, in minutes', length), calendar: calRow,
    noPay: mk('p', 'sfine', 'No payment: JARVIS never agrees to pay.'),
  };
  const bookBox = mk('div', 'cl-book');
  bookBox.append(F.windows, F.giveName, F.giveNumber, F.reason, F.length, F.calendar, F.noPay);
  const bookSw = toggle('', '', false, (on, set) => { set(on); S.booking = on; shape(); if (on && !winBox.childElementCount) addWindow(null); });
  const bookRow = option('This call books an appointment', 'A pickup, a visit or an appointment, inside your limits.', (l, s) => {
    bookSw.el.setAttribute('aria-labelledby', l); if (s) bookSw.el.setAttribute('aria-describedby', s); return bookSw.el;
  });
  const langBox = mk('fieldset', 'cl-langs');
  langBox.append(mk('legend', 'bl', 'Languages'));
  const langNote = mk('p', 'sfine');
  const opens = mk('select', 'bsel cl-wide');
  const minutes = input('text', 2); minutes.inputMode = 'numeric';
  const err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
  const note = mk('p', 'snote'); note.setAttribute('role', 'status');
  const make = button('Make the card', 'primary sact', () => submit());
  const clear = button('Clear', 'sact', () => reset(true));
  const out = mk('div', 'cl-out');
  const numField = field('Number to call', number, NUMBER_HELP);
  numField.insertBefore(numberNote, number); // under the help line, above the box it is about
  numberNote.id = uid('cln');
  number.setAttribute('aria-describedby', number.getAttribute('aria-describedby') + ' ' + numberNote.id);
  host.append(intro, field('Start from', tplSel), tplNote, numField, field('Who it is (a saved contact, or a name for the card)', who),
    F.place, F.purpose, F.maySay, F.mayAgree, F.items, F.order, bookRow, bookBox, langBox, langNote, field('It opens in', opens),
    field('At most, in minutes', minutes), rowOf(make, clear), err, note, out);

  function rowOf(...b) { const r = mk('div', 'sacts'); r.append(...b); return r; }
  function caps() { const s = ctx.settings(); return (s && s.minutes) || 6; }
  /** What the form shows: a ready card's own fields, or the blank card's (with its booking when switched on). */
  function shape() {
    const t = S.tpl, has = (f) => !!t && t.fields.includes(f);
    F.purpose.hidden = F.maySay.hidden = F.mayAgree.hidden = !!t;
    F.place.hidden = !has('place'); F.items.hidden = !has('items'); F.order.hidden = !has('order');
    bookRow.hidden = !!t;
    const booking = t ? has('windows') || has('give_name') : S.booking;
    bookBox.hidden = !booking;
    F.windows.hidden = t ? !has('windows') : false;
    F.giveNumber.hidden = t ? !has('give_number') : false;
    F.reason.hidden = t ? !has('reason') : false;
    F.length.hidden = t ? !has('duration_minutes') : false;
    F.calendar.hidden = !!t; // a ready card adds its booking to the calendar itself
    tplNote.textContent = t ? 'JARVIS writes this card\u2019s purpose and what it may say and agree to from the fields below.' : '';
  }
  function addWindow(w) {
    if (winBox.childElementCount >= WINDOWS_MAX) return;
    const r = mk('div', 'cl-window');
    const day = input('date', 0), start = input('time', 0), end = input('time', 0);
    day.value = w ? w.day : ''; start.value = w ? w.start : ''; end.value = w ? w.end : '';
    const rm = button('Remove', 'sact', () => { r.remove(); renumber(); addWin.focus(); });
    r.append(field('Day', day), field('From', start), field('Until', end), rowOf(rm));
    winBox.append(r);
    renumber();
  }
  function renumber() {
    [...winBox.children].forEach((r, i) => {
      const l = r.querySelector('label'), [, from, until] = r.querySelectorAll('input');
      if (l) l.textContent = 'Day ' + (i + 1);
      if (from) from.setAttribute('aria-label', 'Time ' + (i + 1) + ': from'); // each window's times, told apart
      if (until) until.setAttribute('aria-label', 'Time ' + (i + 1) + ': until');
      const rm = r.querySelector('.btn');
      if (rm) rm.setAttribute('aria-label', 'Remove time ' + (i + 1));
    });
    addWin.disabled = winBox.childElementCount >= WINDOWS_MAX;
  }
  function windows() {
    return [...winBox.children].map((r) => {
      const [day, start, end] = [...r.querySelectorAll('input')].map((i) => i.value);
      return { day, start, end };
    });
  }
  function passed() { return (ctx.languages() || []).filter((l) => l.status === 'passed' && l.code !== 'en-IN'); }
  function paintLangs(chosen, first) {
    langBox.querySelectorAll('.cl-lang').forEach((n) => n.remove());
    const one = (words, code, on, fixed) => { // the box, then its own label[for] (never wrapped: the label leads)
      const w = mk('div', 'cl-lang'), box = mk('input'), lab = mk('label', '', words);
      box.type = 'checkbox'; box.id = uid('cll'); box.checked = on; box.disabled = !!fixed;
      if (code) { box.value = code; box.addEventListener('change', () => { limit(); paintOpens(opens.value); }); }
      lab.htmlFor = box.id;
      w.append(box, lab);
      langBox.append(w);
    };
    one('English (always)', '', true, true);
    const list = passed();
    list.forEach((l) => one(l.name + (l.native ? '' : ' (not yet heard by a native speaker)'), l.code, chosen.includes(l.code), false));
    langNote.textContent = list.length ? 'English and up to ' + MAX_INDIAN + ' Indian languages. JARVIS switches when they answer in one of them.' : NONE_PASSED;
    limit();
    paintOpens(first);
  }
  function paintOpens(first) {
    const codes = ['en-IN', ...picked()];
    opens.replaceChildren(...codes.map((c) => new Option(langName(c), c)));
    opens.value = codes.includes(first) ? first : 'en-IN';
  }
  function picked() { return [...langBox.querySelectorAll('input[value]')].filter((b) => b.checked).map((b) => b.value); }
  function limit() { const n = picked().length; langBox.querySelectorAll('input[value]').forEach((b) => { b.disabled = !b.checked && n >= MAX_INDIAN; }); }
  function now() { return langBox.querySelector('input[value]') ? [picked(), opens.value] : [S.wanted, S.first]; }
  function fill(v) {
    who.value = v.who || ''; purpose.value = v.purpose || '';
    say1.value = (v.maySay || []).join('\n'); agree.value = (v.mayAgree || []).join('\n');
    place.value = ''; items.value = ''; order.value = '';
    const b = v.booking;
    S.booking = !!b; bookSw.set(S.booking);
    winBox.replaceChildren();
    (b ? b.windows : []).forEach((w) => addWindow(w));
    giveName.value = b ? b.name : ''; reason.value = b ? b.reason : ''; giveNumber.value = '';
    giveNumber.placeholder = b && b.number4 ? 'Ending ' + b.number4 : '';
    length.value = String(b ? b.minutes : 30);
    S.calendar = b ? b.calendar : true; calSw.set(S.calendar);
    number.value = '';
    numberNote.textContent = v.number4 ? 'Leave it empty to call the number ending ' + v.number4 + ' again.' : '';
    minutes.value = String(Math.min(v.maxMinutes || caps(), caps()));
    const ls = v.languages || [];
    S.wanted = ls.filter((l) => l !== 'en-IN'); S.first = ls[0] || 'en-IN'; // kept until the language table arrives
    paintLangs(S.wanted, S.first);
    shape();
  }
  function reset(focus) {
    S.editing = null; S.tpl = null; tplSel.value = ''; fill({}); err.textContent = ''; say(note, ''); make.textContent = 'Make the card';
    if (focus) tplSel.focus();
  }
  function useTemplate(t) {
    S.editing = null; S.tpl = t;
    const laundry = !!t && t.id.startsWith('laundry'); // the laundry's calls open in Malayalam (rows 195-197)
    fill({ languages: (laundry ? ['ml-IN', 'en-IN'] : ['en-IN']).filter((c) => c === 'en-IN' || passed().some((l) => l.code === c)) });
    if (t && t.fields.includes('windows') && t.id !== 'laundry_status') addWindow(null); // a window to fill (the status call's are optional)
    make.textContent = 'Make the card';
  }
  function languages() { const first = opens.value; return [first, ...['en-IN', ...picked()].filter((c) => c !== first)]; }
  function body() {
    const num = number.value.trim() ? e164(number.value) : S.editing && S.editing.number ? S.editing.number : '';
    const max = Number(minutes.value);
    if (S.tpl) {
      const has = (f) => S.tpl.fields.includes(f), f = { languages: languages(), max_minutes: max };
      if (num) f.number = num;
      if (who.value.trim()) f.contact = who.value.trim();
      if (has('windows')) f.windows = windows();
      if (has('give_name')) f.give_name = giveName.value.trim();
      if (has('give_number') && giveNumber.value.trim()) f.give_number = e164(giveNumber.value);
      if (has('reason')) f.reason = reason.value.trim();
      if (has('place')) f.place = place.value.trim();
      if (has('duration_minutes')) f.duration_minutes = Number(length.value);
      if (has('items') && items.value.trim()) f.items = Number(items.value);
      if (has('order') && order.value.trim()) f.order = order.value.trim();
      return { template: S.tpl.id, fields: f };
    }
    const b = { purpose: purpose.value.trim(), may_say: splitLines(say1.value), may_agree: splitLines(agree.value), languages: languages(), max_minutes: max };
    if (num) b.number = num;
    if (who.value.trim()) b.contact = who.value.trim();
    if (S.editing && S.editing.template) b.template = S.editing.template;
    if (S.booking) {
      b.booking = { windows: windows(), give_name: giveName.value.trim(), reason: reason.value.trim(), no_payment: true,
        duration_minutes: Number(length.value), add_to_calendar: S.calendar };
      if (giveNumber.value.trim()) b.booking.give_number = e164(giveNumber.value);
    }
    return b;
  }
  function check(b) {
    const f = b.fields || b, inputs = winBox.querySelectorAll('input');
    if (!f.number && !f.contact) return [number, 'Type the number to call, or a saved contact\u2019s name.'];
    if (f.number && !lastFourOf(f.number)) return [number, 'That doesn\u2019t look like a phone number.'];
    if (!b.fields && !b.purpose) return [purpose, 'Say what the call is for.'];
    for (const [el, ls] of [[say1, b.may_say || []], [agree, b.may_agree || []]]) {
      if (ls.length > LINES_MAX || ls.some((l) => l.length > LINE_MAX)) return [el, 'At most ' + LINES_MAX + ' lines of ' + LINE_MAX + ' characters each.'];
    }
    if (b.fields && 'place' in f && !f.place) return [place, 'Say where the appointment is.'];
    const book = b.booking || (b.fields ? f : null), needWin = b.booking || (b.fields && S.tpl.fields.includes('windows') && S.tpl.id !== 'laundry_status');
    if (book && 'windows' in book) {
      if (needWin && !book.windows.length) return [addWin, 'Add at least one time it may accept.'];
      const bad = book.windows.findIndex((w) => !w.day || !w.start || !w.end || w.end <= w.start);
      if (bad >= 0) return [inputs[bad * 3], 'Time ' + (bad + 1) + ': a day, and an end after the start.'];
    }
    if (book && 'give_name' in book && !book.give_name) return [giveName, 'Give the name JARVIS should give.'];
    if (book && 'reason' in book && !book.reason) return [reason, 'Give the reason.'];
    const d = book && book.duration_minutes;
    if (book && 'duration_minutes' in book && (!Number.isInteger(d) || d < 5 || d > 480)) return [length, 'From 5 to 480 minutes.'];
    const m = f.max_minutes;
    if (!Number.isInteger(m) || m < 1 || m > caps()) return [minutes, 'From 1 to ' + caps() + ' minutes (your cap for one call).'];
    return null;
  }
  async function submit() {
    if (S.busy) return;
    const b = body(), bad = check(b);
    host.querySelectorAll('[aria-invalid]').forEach((i) => i.removeAttribute('aria-invalid'));
    if (bad) { err.textContent = bad[1]; if (bad[0].tagName !== 'BUTTON') bad[0].setAttribute('aria-invalid', 'true'); bad[0].focus(); return; }
    if (S.editing) b.replaces = S.editing.id; // the old card is cancelled by the cloud once the new one is written
    S.busy = true; make.disabled = true; err.textContent = ''; say(note, 'Making the card and its estimate\u2026');
    try {
      const c = checkCard(await api(PATHS.cards, { body: b }));
      if (!c) throw new Error('JARVIS sent a card it couldn\u2019t read. Try again.');
      S.editing = null; make.textContent = 'Make the card';
      show(c);
      say(note, 'Here is the card. Check it, then press Call.', 'ok');
    } catch (e) { say(note, ''); err.textContent = failed(e); }
    finally { S.busy = false; make.disabled = false; }
  }
  function show(c) {
    const drawn = render(c, { ...ctx, edit: (x) => edit(x) });
    out.replaceChildren(drawn.el);
    const go = drawn.el.querySelector('.btn.primary');
    if (go && !go.disabled) go.focus(); else { const t = drawn.el.querySelector('.cl-ctitle'); t.tabIndex = -1; t.focus(); }
  }
  function edit(c) { // a card's fields back in the (blank) form; saving replaces it
    S.tpl = null; tplSel.value = '';
    fill(c);
    S.editing = c;
    make.textContent = 'Save as a new card';
    out.replaceChildren();
    purpose.focus();
  }
  function templates(list) { // the ready cards come with the settings (A1's settings_view)
    S.templates = list;
    list.forEach((t) => { if (![...tplSel.options].some((o) => o.value === t.id)) tplSel.append(new Option(t.title, t.id)); });
  }
  function load() { const s = ctx.settings(); if (s) templates(s.templates); paintLangs(...now()); }
  reset(false);
  return Object.freeze({ load, templates, edit, languagesChanged: () => paintLangs(...now()) });
}
