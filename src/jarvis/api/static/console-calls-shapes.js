// src/jarvis/api/static/console-calls-shapes.js -- R18 E: what the Calls routes send, checked field by field, in the
// names of jarvis.calls.models (I0: CallCard, CallRecord, CallState, CardStatus, EndReason, CallSettings,
// LanguageResult) and jarvis.calls.protocol (LiveCaption, LiveState). Anything missing or of the wrong type becomes
// '' / null / [] / false, never a guess; a number is kept as its last 4 digits only (whatever the view sends); every
// caption, transcript line and summary is other people's words (untrusted data), shown with textContent, never obeyed.
// ASCII source.
import { arr, int, lang, langName, num, obj, txt } from './console-calls-api.js';

export const CARD_ID = /^cc_[0-9a-f]{12}$/;
export const CALL_ID = /^call_[0-9a-f]{12}$/;
const TEMPLATE_ID = /^[a-z][a-z0-9_]{1,39}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const HHMM = /^\d{2}:\d{2}(:\d{2})?$/;
const cardId = (v) => (typeof v === 'string' && CARD_ID.test(v) ? v : '');
const callId = (v) => (typeof v === 'string' && CALL_ID.test(v) ? v : '');

const CALL_STATES = ['preparing', 'dialing', 'ringing', 'opening', 'talking', 'taken_over', 'wrapping_up', 'ended', 'failed', 'no_answer'];
const LIVE = ['preparing', 'dialing', 'ringing', 'opening', 'talking', 'taken_over', 'wrapping_up'];
const CARD_STATUS = ['draft', 'approved', 'used', 'cancelled', 'expired'];
export const isLive = (state) => LIVE.includes(state);
export const STATE_WORDS = Object.freeze({
  preparing: 'Getting ready', dialing: 'Dialling', ringing: 'Ringing', opening: 'Saying hello', talking: 'On the call',
  taken_over: 'You are on the call', wrapping_up: 'Wrapping up', ended: 'Ended', failed: 'Didn\u2019t go through',
  no_answer: 'No answer',
});
export const CARD_WORDS = Object.freeze({
  draft: 'Waiting for your tap', approved: 'Approved', used: 'Placed', cancelled: 'Cancelled', expired: 'Expired',
});
export const END_WORDS = Object.freeze({
  hung_up: 'They hung up.', done: 'JARVIS said goodbye.', owner_hangup: 'You hung up.',
  cap_inr: 'It reached its rupee cap, so JARVIS said goodbye.', cap_minutes: 'It reached its time cap, so JARVIS said goodbye.',
  no_answer: 'Nobody answered.', not_ready: 'The laptop or the phone wasn\u2019t ready: nothing was dialled.',
  desk_lost: 'The laptop\u2019s call desk dropped out.', phone_lost: 'The phone dropped out.',
  menu_keys: 'It stopped at a phone menu that needed keys.', error: 'Something went wrong on the way.',
});
const WHO = { them: 'Them', jarvis: 'JARVIS', owner: 'You', note: 'Note' };
export const whoWord = (who) => WHO[who] || 'Them';
const OPTIONS = { laptop: 'Laptop models', google: 'Google (free allowance)', azure: 'Azure free tier', bhashini: 'Bhashini',
  sarvam: 'Sarvam (paid)' };
const OPTION_ORDER = ['laptop', 'google', 'azure', 'bhashini', 'sarvam']; // free first, the laptop first (plan 5.3)

const langs = (v, max = 4) => arr(v).map(lang).filter(Boolean).filter((c, i, a) => a.indexOf(c) === i).slice(0, max);
const lines = (v, max = 10, len = 200) => arr(v).map((s) => txt(s, len)).filter(Boolean).slice(0, max);
/** The last 4 digits of whatever the view sends for a number ("number_last4", a masked or a full number). */
function four(o, ...keys) {
  for (const k of keys) {
    const v = o[k];
    if (typeof v !== 'string') continue;
    const d = v.replace(/\D/g, '');
    if (d.length >= 4) return d.slice(-4);
  }
  return '';
}

export function readiness(v) { // GET /v1/calls/status: the desk and the phone as the cloud last heard them
  const o = obj(v) || {}, d = obj(o.desk) || {}, p = obj(o.phone) || {};
  const m = obj(o.month) || {}, t = obj(o.today) || {}, a = obj(o.active);
  return {
    desk: { connected: d.connected === true, ready: d.ready === true, problems: lines(d.problems, 6, 300),
      btHeadset: d.bt_headset === true, cable: d.cable !== false, phoneLink: d.phone_link !== false },
    phone: { linked: p.linked === true },
    month: { used: Math.max(0, num(m.used_inr) || 0), cap: int(m.cap_inr, 0, 100000) },
    today: { calls: int(t.calls, 0, 1000) || 0, max: int(t.max, 1, 1000) },
    active: a && callId(a.call_id) ? { callId: a.call_id, state: CALL_STATES.includes(a.state) ? a.state : 'talking' } : null,
    templates: arr(o.templates).slice(0, 20).map(template).filter(Boolean),
  };
}

function slot(v) {
  const w = obj(v);
  if (!w || !DAY.test(String(w.day || '')) || !HHMM.test(String(w.start || '')) || !HHMM.test(String(w.end || ''))) return null;
  return { day: w.day, start: w.start.slice(0, 5), end: w.end.slice(0, 5) };
}
function booking(v) {
  const b = obj(v);
  if (!b) return null;
  return { windows: arr(b.windows).slice(0, 6).map(slot).filter(Boolean), name: txt(b.give_name, 60),
    number4: four(b, 'give_number_last4', 'give_number_masked', 'give_number'), reason: txt(b.reason, 300),
    minutes: int(b.duration_minutes, 5, 480) || 30, calendar: b.add_to_calendar !== false };
}
export function card(v) {
  const c = obj(v);
  if (!c || !cardId(c.id)) return null;
  const r = obj(c.ready) || {}, lim = obj(c.limits) || {};
  const status = CARD_STATUS.includes(c.status) ? c.status : 'draft';
  return {
    id: c.id, status, callState: CALL_STATES.includes(c.call_state) ? c.call_state : '', callId: callId(c.call_id),
    number4: four(c, 'number_last4', 'number_masked', 'number_e164'), who: txt(c.contact_name, 60),
    purpose: txt(c.purpose, 300), maySay: lines(c.may_say), mayAgree: lines(c.may_agree), booking: booking(c.booking),
    languages: langs(c.languages), template: typeof c.template === 'string' && TEMPLATE_ID.test(c.template) ? c.template : '',
    maxMinutes: int(lim.max_minutes, 1, 30), maxInr: int(lim.max_inr, 1, 200), estimate: num(c.estimate_inr),
    newNumber: c.new_number === true, passkey: c.passkey_required === true || c.new_number === true,
    approvalId: typeof c.approval_id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(c.approval_id) ? c.approval_id : '',
    ready: { known: !!obj(c.ready), ok: r.ok === true, problems: lines(r.problems, 6, 300) }, why: txt(c.refused, 300),
  };
}
export function template(v) {
  const t = obj(v);
  if (!t || typeof t.id !== 'string' || !TEMPLATE_ID.test(t.id)) return null;
  const lim = obj(t.limits) || {};
  return { id: t.id, title: txt(t.title, 80) || t.id, purpose: txt(t.purpose, 300), maySay: lines(t.may_say), mayAgree: lines(t.may_agree),
    booking: booking(t.booking), languages: langs(t.languages), who: txt(t.contact_name, 60), number4: four(t, 'number_last4', 'number_masked'),
    maxMinutes: int(lim.max_minutes, 1, 30) };
}
function line(v) {
  const l = obj(v);
  if (!l) return null;
  const text = txt(l.text, 2000);
  if (!text) return null;
  return { who: WHO[l.who] ? l.who : 'them', lang: lang(l.lang), text, english: txt(l.english, 2000) };
}
export function record(v) {
  const r = obj(v);
  if (!r || !callId(r.id)) return null;
  const ev = obj(r.booking_event);
  return {
    id: r.id, state: CALL_STATES.includes(r.state) ? r.state : 'ended', end: typeof r.end_reason === 'string' && END_WORDS[r.end_reason] ? r.end_reason : '',
    direction: r.direction === 'incoming' ? 'incoming' : 'outgoing', at: txt(r.started_at, 40), seconds: num(r.seconds),
    number4: four(r, 'number_last4', 'number_masked', 'number_e164'), who: txt(r.contact_name, 60), purpose: txt(r.purpose, 300),
    languages: langs(r.languages_used, 4), cost: num(r.cost_inr), summary: txt(r.summary, 4000),
    transcript: arr(r.transcript).slice(0, 2000).map(line).filter(Boolean),
    recorded: r.recorded !== false && r.objected !== true, objected: r.objected === true, audio: r.has_audio === true,
    keep: r.keep === true, deleteAfter: txt(r.delete_after, 40),
    event: ev ? { title: txt(ev.title, 120), when: txt(ev.when, 80), undone: ev.undone === true } : (r.booking_event_ref ? { title: '', when: '', undone: false } : null),
  };
}
/** The language table: one row per language, the option that passed (free first, the laptop first), else the reasons. */
export function languages(v) {
  const o = obj(v) || {}, ch = obj(o.check) || {};
  const byLang = new Map();
  arr(o.results || o.languages).slice(0, 200).forEach((x) => {
    const l = obj(x);
    const code = l && lang(l.lang || l.code);
    if (!code) return;
    const option = typeof l.option === 'string' && OPTIONS[l.option] ? l.option : '';
    const row = { code, name: langName(code, l.name), option, optionWords: OPTIONS[option] || '', passed: l.passed === true,
      running: l.running === true, perMin: num(l.inr_per_minute), why: lines(l.why_failed, 4, 200), native: l.native_heard === true,
      balanced: l.needs_balanced === true, at: txt(l.checked_at, 40) };
    if (!byLang.has(code)) byLang.set(code, []);
    byLang.get(code).push(row);
  });
  const rows = [...byLang.values()].map((opts) => {
    const rank = (r) => OPTION_ORDER.indexOf(r.option) + (r.perMin && r.perMin > 0 ? 10 : 0);
    const passed = opts.filter((r) => r.passed).sort((a, b) => rank(a) - rank(b));
    const best = passed[0] || opts.find((r) => r.running) || opts.slice().sort((a, b) => String(b.at).localeCompare(String(a.at)))[0];
    const status = passed.length ? 'passed' : best.running ? 'running' : best.at ? 'failed' : 'untested';
    return { ...best, status };
  }).sort((a, b) => (a.code === 'en-IN' ? -1 : b.code === 'en-IN' ? 1 : a.name.localeCompare(b.name)));
  return { rows, check: { running: ch.running === true || rows.some((r) => r.status === 'running'), estimate: num(ch.estimate_inr) } };
}
export function settings(v) {
  const o = obj(v) || {};
  const sp = obj(o.speech) || {}, az = obj(sp.azure) || {};
  return {
    month: int(o.month_cap_inr, 0, 3000), call: int(o.call_cap_inr, 1, 200), minutes: int(o.call_max_minutes, 1, 30),
    defaults: langs(o.default_languages, 4).filter((c) => c !== 'en-IN'),
    answering: o.answering_on === true, rings: int(o.answer_after_rings, 2, 15) || 5,
    policy: ['all', 'contacts', 'not_contacts'].includes(o.answer_policy) ? o.answer_policy : 'all',
    retention: int(o.retention_days, 1, 30) || 30, recordAudio: o.record_audio !== false,
    balanced: o.allow_balanced === true, sarvam: o.sarvam_on === true, firstName: txt(o.owner_first_name, 60),
    azure: txt(az.status || o.azure_status, 20),
  };
}
export function caption(v) { return line(v); } // LiveCaption {who, lang, text, english}
export function liveState(v) { // LiveState
  const o = obj(v) || {};
  return { state: CALL_STATES.includes(o.state) ? o.state : '', lang: lang(o.lang), seconds: int(o.seconds, 0, 86400),
    cost: num(o.cost_inr), listening: o.listening === true, taken: o.taken_over === true, recording: o.recording !== false,
    end: typeof o.end_reason === 'string' && END_WORDS[o.end_reason] ? o.end_reason : '' };
}
