// src/jarvis/api/static/console-calls-list.js -- R18 E (docs/plans/r18-calls.md section 4 step 8): Calls -> Calls.
// Today's calls and the last week's, each with its state in words, its languages, its rupees and how long it lasted;
// Open shows its record: the English summary, the calendar entry a booking added (with Undo), the transcript in the
// other person's language and in English, the audio recording (console-calls-audio.js; or why there is none: they
// asked not to be recorded), when it will be deleted, Keep and Delete (Delete asks first: it cannot be undone).
// What the other person said is their words: shown with textContent, in its own direction (dir=auto) and language.
// ASCII source.
import { PATHS, api, button, chip, duration, failed, isToday, langName, masked, mk, rupees, say, when } from './console-calls-api.js';
import { END_WORDS, STATE_WORDS, isLive, record as checkRecord, whoWord } from './console-calls-shapes.js';
import { player } from './console-calls-audio.js';

const LIMIT = 50;
const EMPTY = 'No calls yet. Ask JARVIS in the chat to call someone, or make a card in New call.';

export function mount(host, ctx) {
  const S = { rows: [], open: null, player: null, busy: false };
  const listView = mk('div', 'cl-list');
  const state = mk('p', 'snote'); state.setAttribute('role', 'status');
  const today = mk('section', 'hp-sec'), earlier = mk('section', 'hp-sec');
  const recView = mk('div', 'cl-record'); recView.hidden = true;
  listView.append(state, today, earlier);
  host.append(listView, recView);

  const statusOf = (s) => (s === 'ended' ? 'ok' : ['failed', 'refused', 'no_answer'].includes(s) ? 'red' : isLive(s) ? 'amber' : 'unknown');
  function title(r) { return (r.direction === 'incoming' ? 'From ' : '') + (r.who || masked(r.number4)); }
  function facts(r) {
    return [when(r.at), r.seconds !== null ? duration(r.seconds) : '', r.languages.map((l) => langName(l)).join(', '),
      r.cost !== null ? rupees(r.cost) : ''].filter(Boolean).join(' \u00b7 ');
  }
  function item(r) {
    const row = mk('div', 'hp-row'), t = mk('div', 'hp-txt'), a = mk('div', 'hp-acts');
    const head = mk('b', '', title(r));
    t.append(head, mk('small', '', facts(r)));
    if (r.purpose) t.append(mk('small', '', r.purpose));
    const live = isLive(r.state);
    const open = button(live ? 'Live' : 'Open', live ? 'primary' : '', () => (live ? ctx.openLive(r.id) : show(r.id)));
    open.setAttribute('aria-label', (live ? 'Open the live call: ' : 'Open the record of ') + title(r));
    a.append(chip(STATE_WORDS[r.state] || 'Ended', statusOf(r.state)), open);
    row.append(t, a);
    return row;
  }
  function section(el, name, rows) {
    el.replaceChildren();
    el.hidden = !rows.length;
    if (!rows.length) return;
    const h = mk('h3', 'hp-h', name);
    el.append(h, ...rows.map(item));
  }
  function paintList() {
    section(today, 'Today', S.rows.filter((r) => isToday(r.at)));
    section(earlier, 'Earlier this week', S.rows.filter((r) => !isToday(r.at)));
    if (!S.rows.length && !S.busy) say(state, EMPTY);
  }
  async function load() {
    if (S.busy) return;
    S.busy = true;
    if (!S.rows.length) say(state, 'Loading your calls\u2026');
    try {
      const r = await api(PATHS.records + '?limit=' + LIMIT);
      S.rows = (r && Array.isArray(r.records) ? r.records : []).slice(0, 100).map(checkRecord).filter(Boolean);
      say(state, '');
    } catch (e) { say(state, failed(e), 'bad'); }
    S.busy = false;
    paintList();
  }

  // ---- one call's record ------------------------------------------------------------------------------------------
  function back() {
    if (S.player) S.player.stop();
    S.player = null; S.open = null;
    recView.hidden = true; recView.replaceChildren(); listView.hidden = false;
    const first = listView.querySelector('button');
    if (first) first.focus();
    load();
  }
  async function show(rid) {
    listView.hidden = true; recView.hidden = false;
    const note = mk('p', 'snote', 'Loading the record\u2026'); note.setAttribute('role', 'status');
    const backBtn = button('Back to calls', 'sact', back);
    recView.replaceChildren(backBtn, note);
    backBtn.focus();
    try {
      const r = checkRecord(await api(PATHS.records + '/' + encodeURIComponent(rid)));
      if (!r) throw new Error('JARVIS sent a record it couldn\u2019t read.');
      S.open = r;
      paintRecord(r, backBtn);
    } catch (e) { say(note, failed(e), 'bad'); }
  }
  function paintRecord(r, backBtn) {
    if (S.player) S.player.stop();
    const h = mk('h3', 'cl-rtitle', title(r)); h.tabIndex = -1;
    const meta = mk('p', 'sfine', [facts(r), r.direction === 'incoming' ? 'Answered for you' : 'Placed for you', STATE_WORDS[r.state] || ''].filter(Boolean).join(' \u00b7 '));
    const parts = [backBtn, h, meta];
    if (r.purpose) parts.push(mk('p', 'snote', r.purpose));
    if (r.end) parts.push(mk('p', 'sfine', END_WORDS[r.end]));
    const sum = mk('section', 'bsec');
    sum.append(mk('h3', '', 'Summary (English)'), mk('p', 'cl-text', r.summary || 'No summary yet.'));
    parts.push(sum);
    if (r.event) parts.push(eventBox(r));
    const tr = mk('section', 'bsec');
    tr.append(mk('h3', '', 'Transcript'));
    const log = mk('div', 'cl-transcript');
    if (!r.transcript.length) log.append(mk('p', 'sfine', 'No transcript.'));
    r.transcript.forEach((l) => log.append(lineEl(l)));
    tr.append(log);
    parts.push(tr);
    const au = mk('section', 'bsec');
    au.append(mk('h3', '', 'Recording'));
    if (r.audio) S.player = player(au, PATHS.records + '/' + encodeURIComponent(r.id) + '/audio', r.seconds);
    else au.append(mk('p', 'sfine', r.objected ? 'They asked not to be recorded: the audio was deleted, and only notes were kept for the summary.'
      : !r.recorded ? 'The audio was not recorded for this call.' : 'No recording is kept for this call.'));
    parts.push(au, keepBox(r));
    recView.replaceChildren(...parts);
  }
  function eventBox(r) {
    const box = mk('div', 'bnote');
    if (r.event.undone) { box.textContent = 'The calendar entry this call added was removed.'; return box; }
    const what = [r.event.title, r.event.when].filter(Boolean).join(', ');
    box.append(mk('span', '', 'Added to your calendar' + (what ? ': ' + what : '') + '. '));
    const undo = button('Undo', 'bact', async (b) => {
      b.disabled = true;
      try {
        await api(PATHS.records + '/' + encodeURIComponent(r.id) + '/undo-booking', { body: {} });
        box.replaceChildren(mk('span', '', 'Removed from your calendar.'));
      } catch (e) { b.disabled = false; box.append(mk('span', 'lerr', ' ' + failed(e))); }
    });
    undo.setAttribute('aria-label', 'Undo: remove the calendar entry this call added');
    box.append(undo);
    return box;
  }
  function keepBox(r) {
    const sec = mk('section', 'bsec');
    sec.append(mk('h3', '', 'Keep or delete'));
    const until = when(r.deleteAfter);
    const line = mk('p', 'sfine', r.keep ? 'Kept: it stays until you delete it.' : until ? 'Deleted by itself on ' + until + ', unless you keep it.' : '');
    const acts = mk('div', 'sacts'), err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
    acts.append(button(r.keep ? 'Stop keeping' : 'Keep this call', 'sact', (b) => keep(r, !r.keep, b, err)));
    const del = button('Delete', 'sact', () => askDelete(r, sec, del, err));
    acts.append(del);
    sec.append(line, acts, err);
    return sec;
  }
  async function keep(r, on, b, err) {
    b.disabled = true; err.textContent = '';
    try {
      const got = checkRecord(await api(PATHS.records + '/' + encodeURIComponent(r.id) + '/keep', { body: { keep: on } }));
      const next = got && got.id === r.id ? { ...r, keep: got.keep, deleteAfter: got.deleteAfter || r.deleteAfter } : { ...r, keep: on };
      S.open = next;
      paintRecord(next, recView.querySelector('button'));
      const t = recView.querySelector('.cl-rtitle'); if (t) t.focus();
    } catch (e) { b.disabled = false; err.textContent = failed(e); }
  }
  function askDelete(r, sec, trigger, err) { // two steps, like Integrations -> Disconnect
    if (sec.querySelector('.confirm')) return;
    const box = mk('div', 'confirm'); box.setAttribute('role', 'group');
    const words = mk('span', '', 'Delete this call\u2019s recording, transcript and summary? This can\u2019t be undone.');
    const no = button('Keep', '', () => { box.remove(); trigger.focus(); });
    const yes = button('Delete', 'danger', async () => {
      yes.disabled = true; no.disabled = true;
      try { await api(PATHS.records + '/' + encodeURIComponent(r.id), { method: 'DELETE' }); S.rows = S.rows.filter((x) => x.id !== r.id); back(); }
      catch (e) { yes.disabled = false; no.disabled = false; err.textContent = failed(e); }
    });
    box.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); no.click(); } });
    box.append(words, no, yes);
    sec.append(box);
    no.focus();
  }
  paintList();
  return Object.freeze({ load, show, back, stop: () => { if (S.player) S.player.stop(); }, rows: () => S.rows });
}

/** One transcript or caption line: who, the words as said (their language, their direction), the English under it. */
export function lineEl(l) {
  const p = mk('div', 'cl-line');
  p.dataset.who = l.who;
  const said = mk('p', 'cl-said');
  said.append(mk('b', '', whoWord(l.who) + ': '));
  const t = mk('span', '', l.text);
  t.dir = 'auto';
  if (l.lang) t.lang = l.lang.split('-')[0];
  said.append(t);
  p.append(said);
  if (l.english && l.english !== l.text) {
    const en = mk('p', 'cl-en', 'In English: ' + l.english);
    en.lang = 'en';
    p.append(en);
  }
  return p;
}
