// src/jarvis/api/static/console-calls-form.js -- R18 E: Calls -> New call. A ready card (the Laundry ones, rows
// 195-197, among them) or a blank one; the fields of plan section 4 step 1 (the number, who, the purpose, what JARVIS
// may tell them and agree to), a booking's limits (step 9, CallCard.booking: up to 6 time windows, the name and number
// to give, the reason, the calendar entry; never a payment), English plus up to 3 of the languages that PASSED the
// language check (5.3) with the one it opens in, and the longest the call may last (at most the per-call cap).
// "Make the card" asks the cloud for the card and its rupee estimate; the card (console-calls-card.js) shows under the
// form with Call, Edit and Cancel. Edit puts a card's fields back here; saving makes a NEW card (a new estimate, a new
// approval) and cancels the old one. A card's number stays on the server: only its last 4 digits are shown, and a
// number typed here replaces it. ASCII source; textContent only.
import { MAX_INDIAN, PATHS, api, button, failed, field, input, langName, lastFourOf, mk, option, say, toggle, uid } from './console-calls-api.js';
import { card as checkCard, template as checkTemplate } from './console-calls-shapes.js';
import { render } from './console-calls-card.js';

const NUMBER_HELP = 'An Indian number. JARVIS never calls emergency, premium-rate or international numbers.';
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

export function mount(host, ctx) {
  const S = { templates: [], editing: null, busy: false, drawn: null, booking: false, calendar: true, number4: '', loaded: false };
  const intro = mk('p', 'sfine', 'Tell JARVIS who to call and why, here or in the chat. Nothing is dialled until you press Call on the card.');
  const tplSel = mk('select', 'bsel cl-wide');
  tplSel.append(new Option('A blank call', ''));
  tplSel.addEventListener('change', () => useTemplate(S.templates.find((t) => t.id === tplSel.value) || null));
  const number = input('tel', 20); number.inputMode = 'tel';
  const numberNote = mk('small', 'mhelp');
  const who = input('text', 60);
  const purpose = input('textarea', 300); purpose.rows = 2;
  const say1 = input('textarea', 1000); say1.rows = 2;
  const agree = input('textarea', 1000); agree.rows = 2;
  const giveName = input('text', 60), giveNumber = input('tel', 20), reason = input('text', 300), length = input('text', 3);
  giveNumber.inputMode = 'tel'; length.inputMode = 'numeric';
  const winBox = mk('div', 'cl-windows');
  const addWin = button('Add a time', 'sact', () => { addWindow(null); const last = winBox.lastElementChild; if (last) last.querySelector('input').focus(); });
  const calSw = toggle('', '', true, (on, set) => { set(on); S.calendar = on; });
  const calRow = option('Add it to my calendar after the call', 'With Undo in the call\u2019s record.', (l, s) => { calSw.el.setAttribute('aria-labelledby', l); if (s) calSw.el.setAttribute('aria-describedby', s); return calSw.el; });
  const bookBox = mk('div', 'cl-book');
  bookBox.hidden = true;
  const winHead = mk('span', 'bl', 'Times it may accept');
  bookBox.append(winHead, mk('small', 'mhelp', 'JARVIS accepts only a slot inside one of these and repeats it back to confirm.'), winBox, rowOf(addWin),
    field('Name to give', giveName), field('Number to give (optional)', giveNumber, 'Your call-back number, if they ask.'),
    field('Reason', reason), field('The appointment lasts, in minutes', length), calRow, mk('p', 'sfine', 'No payment: JARVIS never agrees to pay.'));
  const bookSw = toggle('', '', false, (on, set) => { set(on); S.booking = on; bookBox.hidden = !on; if (on && !winBox.childElementCount) addWindow(null); });
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
  numField.append(numberNote);
  host.append(intro, field('Start from', tplSel), numField, field('Who it is (optional)', who), field('Purpose', purpose),
    field('What JARVIS may tell them', say1, LINES_HELP), field('What JARVIS may agree to', agree, AGREE_HELP), bookRow, bookBox,
    langBox, langNote, field('It opens in', opens), field('At most, in minutes', minutes), rowOf(make, clear), err, note, out);

  function rowOf(...b) { const r = mk('div', 'sacts'); r.append(...b); return r; }
  function caps() { const s = ctx.settings(); return (s && s.minutes) || 6; }
  function addWindow(w) {
    if (winBox.childElementCount >= WINDOWS_MAX) return;
    const n = winBox.childElementCount + 1;
    const r = mk('div', 'cl-window');
    const day = input('date', 0), start = input('time', 0), end = input('time', 0);
    day.value = w ? w.day : ''; start.value = w ? w.start : ''; end.value = w ? w.end : '';
    const rm = button('Remove', 'sact', () => { r.remove(); renumber(); addWin.focus(); });
    r.append(field('Day ' + n, day), field('From', start), field('Until', end), rowOf(rm));
    winBox.append(r);
    renumber();
  }
  function renumber() {
    [...winBox.children].forEach((r, i) => {
      const l = r.querySelector('label');
      if (l) l.textContent = 'Day ' + (i + 1);
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
  function fill(v) {
    who.value = v.who || ''; purpose.value = v.purpose || '';
    say1.value = (v.maySay || []).join('\n'); agree.value = (v.mayAgree || []).join('\n');
    const b = v.booking;
    S.booking = !!b; bookSw.set(S.booking); bookBox.hidden = !S.booking;
    winBox.replaceChildren();
    (b ? b.windows : []).forEach((w) => addWindow(w));
    if (S.booking && !winBox.childElementCount) addWindow(null);
    giveName.value = b ? b.name : ''; reason.value = b ? b.reason : ''; giveNumber.value = '';
    giveNumber.placeholder = b && b.number4 ? 'Ending ' + b.number4 : '';
    length.value = String(b ? b.minutes : 30);
    S.calendar = b ? b.calendar : true; calSw.set(S.calendar);
    number.value = '';
    S.number4 = v.number4 || '';
    numberNote.textContent = S.number4 ? 'Leave it empty to call the number ending ' + S.number4 + '.' : '';
    minutes.value = String(Math.min(v.maxMinutes || caps(), caps()));
    const ls = v.languages || [];
    paintLangs(ls.filter((l) => l !== 'en-IN'), ls[0] || 'en-IN');
  }
  function reset(focus) {
    S.editing = null; tplSel.value = ''; fill({}); err.textContent = ''; say(note, ''); make.textContent = 'Make the card';
    if (focus) tplSel.focus();
  }
  function useTemplate(t) { S.editing = null; fill(t || {}); make.textContent = 'Make the card'; }
  function body() {
    const first = opens.value, rest = ['en-IN', ...picked()].filter((c) => c !== first);
    const b = {
      contact_name: who.value.trim(), purpose: purpose.value.trim(),
      may_say: splitLines(say1.value), may_agree: splitLines(agree.value),
      languages: [first, ...rest], limits: { max_minutes: Number(minutes.value) },
    };
    if (tplSel.value) b.template = tplSel.value;
    if (number.value.trim()) b.number = e164(number.value);
    if (S.booking) {
      b.booking = { windows: windows(), give_name: giveName.value.trim(), reason: reason.value.trim(), no_payment: true,
        duration_minutes: Number(length.value), add_to_calendar: S.calendar };
      if (giveNumber.value.trim()) b.booking.give_number = e164(giveNumber.value);
    }
    return b;
  }
  function check(b) {
    if (!b.number && !S.number4) return [number, 'Type the number to call.'];
    if (b.number && !lastFourOf(b.number)) return [number, 'That doesn\u2019t look like a phone number.'];
    if (!b.purpose) return [purpose, 'Say what the call is for.'];
    for (const [el, ls] of [[say1, b.may_say], [agree, b.may_agree]]) {
      if (ls.length > LINES_MAX || ls.some((l) => l.length > LINE_MAX)) return [el, 'At most ' + LINES_MAX + ' lines of ' + LINE_MAX + ' characters each.'];
    }
    if (b.booking) {
      const ws = b.booking.windows, inputs = winBox.querySelectorAll('input');
      if (!ws.length) return [addWin, 'Add at least one time it may accept.'];
      const bad = ws.findIndex((w) => !w.day || !w.start || !w.end || w.end <= w.start);
      if (bad >= 0) return [inputs[bad * 3], 'Time ' + (bad + 1) + ': a day, and an end after the start.'];
      if (!b.booking.give_name) return [giveName, 'Give the name JARVIS should book under.'];
      if (!b.booking.reason) return [reason, 'Give the reason for the appointment.'];
      const d = b.booking.duration_minutes;
      if (!Number.isInteger(d) || d < 5 || d > 480) return [length, 'From 5 to 480 minutes.'];
    }
    const m = b.limits.max_minutes;
    if (!Number.isInteger(m) || m < 1 || m > caps()) return [minutes, 'From 1 to ' + caps() + ' minutes (your cap for one call).'];
    return null;
  }
  async function submit() {
    if (S.busy) return;
    const b = body(), bad = check(b);
    host.querySelectorAll('[aria-invalid]').forEach((i) => i.removeAttribute('aria-invalid'));
    if (bad) { err.textContent = bad[1]; if (bad[0].tagName !== 'BUTTON') bad[0].setAttribute('aria-invalid', 'true'); bad[0].focus(); return; }
    S.busy = true; make.disabled = true; err.textContent = ''; say(note, 'Making the card and its estimate\u2026');
    const old = S.editing;
    if (!b.number && old) b.from_card = old.id; // the edited card's number, kept on the server
    try {
      const r = await api(PATHS.cards, { body: b });
      const c = checkCard((r && r.card) || r);
      if (!c) throw new Error('JARVIS sent a card it couldn\u2019t read. Try again.');
      if (old) api(PATHS.cards + '/' + encodeURIComponent(old.id) + '/cancel', { body: {} }).catch(() => {}); // replaced
      S.editing = null; make.textContent = 'Make the card';
      show(c);
      say(note, 'Here is the card. Check it, then press Call.', 'ok');
    } catch (e) { say(note, ''); err.textContent = failed(e); }
    finally { S.busy = false; make.disabled = false; }
  }
  function show(c) {
    S.drawn = render(c, { ...ctx, edit: (x) => edit(x) });
    out.replaceChildren(S.drawn.el);
    const go = S.drawn.el.querySelector('.btn.primary');
    if (go && !go.disabled) go.focus(); else { const t = S.drawn.el.querySelector('.cl-ctitle'); t.tabIndex = -1; t.focus(); }
  }
  function edit(c) { // a card's fields back in the form
    tplSel.value = c.template && S.templates.some((t) => t.id === c.template) ? c.template : '';
    fill(c);
    S.editing = c;
    make.textContent = 'Save as a new card';
    out.replaceChildren();
    purpose.focus();
  }
  async function load() {
    if (S.loaded) { paintLangs(picked(), opens.value); return; }
    const fromStatus = ctx.ready() ? ctx.ready().templates : [];
    try {
      const r = await api(PATHS.templates);
      S.templates = (r && Array.isArray(r.templates) ? r.templates : []).slice(0, 20).map(checkTemplate).filter(Boolean);
    } catch (e) { S.templates = fromStatus; if (!(e && (e.status === 404 || e.status === 501))) say(note, failed(e), 'bad'); }
    S.loaded = true;
    S.templates.forEach((t) => { if (![...tplSel.options].some((o) => o.value === t.id)) tplSel.append(new Option(t.title, t.id)); });
    if (!S.editing) paintLangs(picked(), opens.value);
  }
  reset(false);
  return Object.freeze({ load, edit, languagesChanged: () => paintLangs(picked(), opens.value), useTemplate: (tid) => {
    const t = S.templates.find((x) => x.id === tid); if (t) { tplSel.value = t.id; useTemplate(t); }
  } });
}
