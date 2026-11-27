// src/jarvis/api/static/console-calls-settings.js -- R18 E (docs/plans/r18-calls.md sections 4, 6, 7; decisions D3,
// D5-D9): Calls -> Settings, the fields of jarvis.calls.models.CallSettings. The caps (a month's rupees for calls, one
// call's rupees, one call's minutes: raising any of them asks first), the fixed limits that keep his number clear of
// spam flags, his first name (said in the opening line), the default languages (up to 3 of those that passed),
// answering the calls he misses (row 104: off until he switches it on and says yes; after how many rings; which
// callers), the records (keep the audio; how many days; lowering it asks first: older calls go), and the paid or
// dearer options (Sarvam, the balanced brain: each only with his yes). Every change is one PUT /v1/calls/settings of
// the changed fields; one he confirmed carries ?confirm=1. ASCII source; textContent only.
import { MAX_INDIAN, PATHS, api, button, choice, failed, field, input, mk, option, say, toggle, uid, wholeRupees } from './console-calls-api.js';
import { settings as checkSettings } from './console-calls-shapes.js';

const POLICIES = [['all', 'Everyone'], ['contacts', 'Saved contacts'], ['not_contacts', 'All but contacts']];
const POLICY_WORDS = { all: 'every caller', contacts: 'saved contacts only', not_contacts: 'everyone except saved contacts' };
const ANSWER_NOTE = 'JARVIS answers only a call you haven\u2019t picked up, says it is your AI assistant, takes a message (name, reason, call-back number) and never agrees to anything. You get the summary.';
const LIMITS = '10 calls a day \u00b7 2 a day to one number \u00b7 3 new numbers a day \u00b7 one redial a day to a number that didn\u2019t answer \u00b7 no calls 21:00\u201308:00 IST. Never emergency, premium-rate or international numbers.';

export function mount(host, ctx) {
  const S = { data: null, busy: false, painted: false };
  const state = mk('p', 'snote'); state.setAttribute('role', 'status'); state.setAttribute('aria-live', 'polite');
  const err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
  const ask = mk('div', 'mbox'); ask.hidden = true; ask.setAttribute('role', 'group');
  const sec = (name, kids) => { const s = mk('section', 'hp-sec'); s.append(mk('h3', 'hp-h', name), ...kids); return s; };
  const row = (...b) => { const r = mk('div', 'sacts'); r.append(...b); return r; };
  const sw = (label, small, fn) => { // an option row with its switch, named by its own label
    const t = toggle('', '', false, fn);
    return { t, row: option(label, small, (l, s) => { t.el.setAttribute('aria-labelledby', l); if (s) t.el.setAttribute('aria-describedby', s); return t.el; }) };
  };
  // money and length
  const month = input('text', 5), call = input('text', 3), minutes = input('text', 2);
  [month, call, minutes].forEach((i) => { i.inputMode = 'numeric'; });
  const capsSave = button('Save the caps', 'sact', () => saveCaps());
  const caps = sec('Money and length', [field('Calls in a month, in rupees', month, 'Inside your monthly limit in Vitals. 0 stops every call.'),
    field('One call, in rupees', call), field('One call, in minutes', minutes), row(capsSave)]);
  const limits = sec('Limits', [mk('p', 'sfine', LIMITS)]);
  // the opening line
  const first = input('text', 60);
  const firstSave = button('Save', 'sact', () => saveName());
  const opening = sec('Opening line', [field('Your first name', first, '\u201cHello, this is JARVIS, an AI assistant calling on behalf of \u2026 This call is recorded.\u201d'), row(firstSave)]);
  // default languages
  const langBox = mk('div', 'cl-langs');
  const langSave = button('Save the languages', 'sact', () => put({ default_languages: ['en-IN', ...picked()] }, 'Default languages saved.'));
  const langs = sec('Default languages', [mk('p', 'sfine', 'Put on every new card, besides English. Up to ' + MAX_INDIAN + ', from the languages that passed.'), langBox, row(langSave)]);
  // answering missed calls (row 104)
  const ans = sw('Answer the calls I miss', 'Off until you switch it on.', (on) => setAnswering(on));
  const rings = input('text', 2); rings.inputMode = 'numeric';
  const ringsSave = button('Save', 'sact', () => saveRings());
  const polLabel = mk('span', 'bl', 'Answer for'); polLabel.id = uid('clpol');
  let pol = choice('clpol', polLabel.id, POLICIES, 'all', (v) => put({ answer_policy: v }, 'Saved.'));
  const polWrap = mk('div', 'cl-hear'); polWrap.append(polLabel, pol);
  const ansMore = mk('div', 'cl-ans');
  ansMore.append(field('After this many rings', rings), row(ringsSave), polWrap);
  const answering = sec('Answering missed calls', [ans.row, mk('p', 'sfine', ANSWER_NOTE), ansMore]);
  // records
  const audio = sw('Keep the call\u2019s audio', 'With the transcript and the summary, sealed in your vault. Stops at once if they object.', (on) => put({ record_audio: on }, on ? 'Audio is kept.' : 'Audio is no longer recorded.'));
  const keep = input('text', 2); keep.inputMode = 'numeric';
  const keepSave = button('Save', 'sact', () => saveRetention());
  const records = sec('Records', [audio.row, field('Keep calls for this many days', keep, 'From 1 to 30. A call you Keep stays until you delete it.'), row(keepSave)]);
  // paid or dearer options
  const sarvam = sw('Sarvam speech (paid)', '\u20b90.50 a minute of hearing and \u20b93 per 1,000 characters of voice. Only for a language the free options fail.', (on) => setPaid('sarvam_on', on));
  const balanced = sw('Languages that need the balanced brain', 'About \u20b92\u20134 a call minute instead of \u20b90.10\u20130.20.', (on) => setPaid('allow_balanced', on));
  const azureEl = mk('p', 'snote');
  const speech = sec('Speech and brain', [azureEl, sarvam.row, balanced.row]);
  host.append(state, caps, limits, opening, langs, answering, records, speech, ask, err);

  const FIELDS = { month_cap_inr: () => { month.value = S.data.month !== null ? String(S.data.month) : ''; },
    call_cap_inr: () => { call.value = S.data.call !== null ? String(S.data.call) : ''; },
    call_max_minutes: () => { minutes.value = S.data.minutes !== null ? String(S.data.minutes) : ''; },
    owner_first_name: () => { first.value = S.data.firstName; }, answer_after_rings: () => { rings.value = String(S.data.rings); },
    retention_days: () => { keep.value = String(S.data.retention); } };
  /** The text boxes take the server's values when they load, and a box only after its own save: never while he types. */
  function fill(keys) { if (S.data) keys.forEach((k) => FIELDS[k] && FIELDS[k]()); }
  function paint() {
    const d = S.data;
    if (!d) return;
    if (!S.painted) { S.painted = true; paintLangs(d.defaults); }
    ans.t.set(d.answering); ansMore.hidden = !d.answering;
    const fresh = choice('clpol', polLabel.id, POLICIES, d.policy, (v) => put({ answer_policy: v }, 'Saved.'));
    pol.replaceWith(fresh); pol = fresh;
    audio.t.set(d.recordAudio);
    sarvam.t.set(d.sarvam); balanced.t.set(d.balanced);
    azureEl.textContent = 'Azure free tier: ' + (d.azure === 'ready' ? 'ready. It stops at its free allowance and can never bill.' : 'not set up. Add its key on the server for 5 free hours a month.');
    [capsSave, firstSave, langSave, ringsSave, keepSave].forEach((b) => { b.disabled = S.busy; });
  }
  function paintLangs(chosen) {
    langBox.replaceChildren();
    const passed = (ctx.languages() || []).filter((l) => l.status === 'passed' && l.code !== 'en-IN');
    langSave.hidden = !passed.length;
    if (!passed.length) { langBox.append(mk('p', 'sfine', 'None has passed the language check yet.')); return; }
    passed.forEach((l) => {
      const w = mk('div', 'cl-lang'), box = mk('input'), lab = mk('label', '', l.name);
      box.type = 'checkbox'; box.id = uid('cld'); box.value = l.code; box.checked = chosen.includes(l.code);
      box.addEventListener('change', limit);
      lab.htmlFor = box.id;
      w.append(box, lab);
      langBox.append(w);
    });
    limit();
  }
  function picked() { return [...langBox.querySelectorAll('input')].filter((b) => b.checked).map((b) => b.value); }
  function limit() { const n = picked().length; langBox.querySelectorAll('input').forEach((b) => { b.disabled = !b.checked && n >= MAX_INDIAN; }); }

  async function put(changes, ok, confirmed) {
    if (S.busy) return false;
    S.busy = true; err.textContent = ''; paint();
    try {
      const d = checkSettings(await api(PATHS.settings + (confirmed ? '?confirm=1' : ''), { method: 'PUT', body: changes }));
      S.data = d; say(state, ok, 'ok');
      fill(Object.keys(changes));
      return true;
    } catch (e) { err.textContent = failed(e); return false; }
    finally { S.busy = false; paint(); }
  }
  function confirmFirst(title, lines, yesWords, then, trigger) { // confirm before commit, here in the panel (Enter lands on Not now)
    const no = button('Not now', 'sact', () => { ask.hidden = true; trigger.focus(); });
    const yes = button(yesWords, 'primary sact', async () => { ask.hidden = true; await then(); trigger.focus(); });
    ask.replaceChildren(mk('p', 'strong', title), ...lines.map((l) => mk('p', '', l)), row(no, yes));
    ask.hidden = false;
    trigger.closest('section').after(ask);
    ask.onkeydown = (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); no.click(); } };
    no.focus();
  }
  const whole = (v, lo, hi) => { const t = String(v || '').replace(/[\u20b9,\s]/g, ''); if (!/^\d{1,6}$/.test(t)) return null; const n = parseInt(t, 10); return n >= lo && n <= hi ? n : null; };
  function saveCaps() {
    const d = S.data; if (!d) return;
    const m = whole(month.value, 0, 3000), c = whole(call.value, 1, 200), mi = whole(minutes.value, 1, 30);
    if (m === null) { err.textContent = 'A month\u2019s cap is a whole number of rupees from \u20b90 to \u20b93,000.'; month.focus(); return; }
    if (c === null) { err.textContent = 'One call\u2019s cap is from \u20b91 to \u20b9200.'; call.focus(); return; }
    if (mi === null) { err.textContent = 'One call lasts from 1 to 30 minutes.'; minutes.focus(); return; }
    const changes = { month_cap_inr: m, call_cap_inr: c, call_max_minutes: mi };
    const up = [d.month !== null && m > d.month ? 'up to ' + wholeRupees(m) + ' a month on calls' : '',
      d.call !== null && c > d.call ? wholeRupees(c) + ' on one call' : '', d.minutes !== null && mi > d.minutes ? mi + ' minutes a call' : ''].filter(Boolean);
    if (!up.length) { put(changes, 'Caps saved.'); return; }
    confirmFirst('Raise the calls caps?', ['JARVIS may then spend ' + up.join(', ') + '.', 'The caps sit inside your monthly limit in Vitals.'],
      'Raise', () => put(changes, 'Caps raised.', true), capsSave);
  }
  function saveName() {
    const n = first.value.trim();
    if (!n) { err.textContent = 'Type your first name: JARVIS says it in its first sentence.'; first.focus(); return; }
    put({ owner_first_name: n }, 'Saved. JARVIS calls on behalf of ' + n + '.');
  }
  function setAnswering(on) {
    if (!S.data) return;
    if (!on) { put({ answering_on: false }, 'JARVIS no longer answers the calls you miss.'); return; }
    confirmFirst('Let JARVIS answer the calls you miss?', [ANSWER_NOTE, 'It answers ' + POLICY_WORDS[S.data.policy] + ', after ' + S.data.rings + ' rings. The laptop and the phone must be ready.'],
      'Switch on', () => put({ answering_on: true }, 'JARVIS answers the calls you miss.', true), ans.t.el);
  }
  function saveRings() {
    const n = whole(rings.value, 2, 15);
    if (n === null) { err.textContent = 'From 2 to 15 rings.'; rings.focus(); return; }
    put({ answer_after_rings: n }, 'Saved.');
  }
  function setPaid(key, on) {
    const t = key === 'sarvam_on' ? sarvam.t : balanced.t;
    if (!on) { put({ [key]: false }, 'Switched off.'); return; }
    const lines = key === 'sarvam_on'
      ? ['Sarvam is paid: \u20b90.50 a minute of their speech and \u20b93 per 1,000 characters of JARVIS\u2019s voice, inside your calls cap.', 'JARVIS still tries the free options first.']
      : ['A language that needs the balanced brain costs about \u20b92\u20134 a call minute, inside your calls cap.', 'Only languages the check marked so use it.'];
    confirmFirst(key === 'sarvam_on' ? 'Switch Sarvam on?' : 'Allow the balanced brain on calls?', lines, 'Switch on',
      () => put({ [key]: true }, 'Switched on.', true), t.el);
  }
  function saveRetention() {
    const d = S.data; if (!d) return;
    const n = whole(keep.value, 1, 30);
    if (n === null) { err.textContent = 'From 1 to 30 days.'; keep.focus(); return; }
    if (n >= d.retention) { put({ retention_days: n }, 'Calls are kept ' + n + ' days.'); return; }
    confirmFirst('Keep calls for ' + n + ' days?', ['Calls older than ' + n + ' days (except the ones you kept) are deleted, with their audio. This can\u2019t be undone.'],
      'Keep ' + n + ' days', () => put({ retention_days: n }, 'Calls are kept ' + n + ' days.', true), keepSave);
  }
  async function load() {
    if (S.busy) return;
    S.busy = true;
    if (!S.data) say(state, 'Loading the settings\u2026');
    try { S.data = checkSettings(await api(PATHS.settings)); say(state, ''); fill(Object.keys(FIELDS)); S.painted = false; } catch (e) { say(state, failed(e), 'bad'); }
    S.busy = false;
    paint();
  }
  return Object.freeze({ load, languagesChanged: () => { if (S.data) paintLangs(picked().length ? picked() : S.data.defaults); }, data: () => S.data });
}
