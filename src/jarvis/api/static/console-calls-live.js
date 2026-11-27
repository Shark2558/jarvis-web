// src/jarvis/api/static/console-calls-live.js -- R18 E (docs/plans/r18-calls.md section 4 step 7, row 396): the live
// call, in the Calls panel on the laptop or in the phone's browser. One WebSocket (GET /api/calls/{id}/live, the owner's
// session): the server sends `caption {who, lang, text, english}` and `state {...}` as JSON and, while he listens, the
// mixed audio as binary 0x03 messages (16 kHz PCM16); this page sends `listen {audio}`, `takeover`, `tell {text}` and
// `hangup`, and nothing else. The controls:
//   Listen live / Captions only   both sides' audio and the English captions, or the captions alone (less data); the
//                                 sound starts only from his press and stops when the panel closes
//   Take over                     JARVIS says its handover line and goes quiet; his microphone comes back at the laptop
//   Tell JARVIS                   a typed instruction the other person does not hear
//   Hang up                       at any moment, one press
// Captions are the other person's words (untrusted): textContent, their own direction and language. ASCII source.
import { PATHS, api, button, choice, chip, duration, failed, input, langName, masked, mk, rupees, say, uid } from './console-calls-api.js';
import { END_WORDS, STATE_WORDS, caption as checkCaption, isLive, liveState, record as checkRecord } from './console-calls-shapes.js';
import { canListen, listener } from './console-calls-audio.js';
import { lineEl } from './console-calls-list.js';

const MAX_LINES = 200;
const MAX_TEXT = 16 * 1024;
const RETRY_MS = [1000, 2000, 4000, 8000, 8000];
const TELL_MAX = 500; // jarvis.calls.protocol.TELL_MAX
// the server's close codes (jarvis.calls.protocol): no point in trying again
const CLOSED = { 4400: 'The live view sent something the call didn\u2019t take. Close it and open it again.',
  4401: 'Sign in again to see this call.', 4404: 'This call has ended.', 4501: 'The live view isn\u2019t ready on this JARVIS yet.' };
const TAKEN = 'You are on the call. At the laptop your own microphone is back. On the phone, if the sound stays on the laptop, tap Phone on its call screen.';

export function mount(host, ctx) {
  const S = { id: '', ws: null, tries: 0, timer: 0, tick: 0, audio: false, state: '', lang: '', seconds: 0, at: 0, cost: null,
    taken: false, ended: false, recording: true, who: '', number4: '', stick: true };
  const ear = listener();
  const view = mk('section', 'cl-live'); view.hidden = true;
  const h = mk('h3', 'cl-rtitle', 'Live call'); h.id = uid('cllh'); h.tabIndex = -1;
  view.setAttribute('aria-labelledby', h.id);
  const head = mk('div', 'cl-chead');
  const stateChip = chip('Connecting', 'amber');
  head.append(h, stateChip);
  const whoLine = mk('p', 'snote cl-who');
  const facts = mk('p', 'sfine cl-facts'); facts.setAttribute('aria-live', 'off');
  const conn = mk('p', 'snote'); conn.setAttribute('role', 'status');
  const segLabel = mk('span', 'k', 'Hear the call'); segLabel.id = uid('clhl');
  const seg = choice('clhear', segLabel.id, [['live', 'Listen live'], ['captions', 'Captions only']], 'captions', (v) => hear(v === 'live'));
  const segWrap = mk('div', 'cl-hear');
  segWrap.append(segLabel, seg);
  const hearNote = mk('p', 'sfine', canListen() ? 'Listen live plays both sides here. Captions only uses less data.' : 'This browser can\u2019t play the call: captions only.');
  const log = mk('div', 'cl-captions');
  log.setAttribute('role', 'log'); log.setAttribute('aria-live', 'polite'); log.setAttribute('aria-label', 'Captions, with English');
  log.tabIndex = 0;
  log.addEventListener('scroll', () => { S.stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 8; });
  const tell = input('text', TELL_MAX);
  const tellForm = mk('form', 'cl-tell');
  tellForm.noValidate = true;
  const tellLabel = mk('label', 'bl', 'Tell JARVIS'); tellLabel.htmlFor = tell.id = uid('cltell');
  const tellHelp = mk('small', 'mhelp', 'The other person doesn\u2019t hear this. JARVIS follows it within the card\u2019s limits.');
  tellHelp.id = uid('cltellh'); tell.setAttribute('aria-describedby', tellHelp.id);
  const tellSend = mk('button', 'btn primary lift sact', 'Send'); tellSend.type = 'submit';
  const tellRow = mk('div', 'lrow'); tellRow.append(tell, tellSend);
  tellForm.append(tellLabel, tellHelp, tellRow);
  tellForm.addEventListener('submit', (e) => { e.preventDefault(); sendTell(); });
  const takeBtn = button('Take over', 'sact', () => takeover());
  const hangBtn = button('Hang up', 'danger sact', () => hangup());
  const acts = mk('div', 'sacts cl-live-acts'); acts.append(takeBtn, hangBtn);
  const takenNote = mk('p', 'bnote'); takenNote.setAttribute('role', 'status');
  const recNote = mk('p', 'sfine'); recNote.setAttribute('role', 'status');
  const endActs = mk('div', 'sacts');
  const err = mk('p', 'lerr'); err.setAttribute('role', 'alert');
  view.append(head, whoLine, facts, recNote, conn, segWrap, hearNote, log, tellForm, acts, takenNote, endActs, err);
  host.append(view);

  function paint() {
    const st = S.state;
    stateChip.textContent = S.ended ? 'Ended' : STATE_WORDS[st] || 'Connecting';
    stateChip.dataset.status = S.ended ? 'ok' : st === 'taken_over' ? 'ok' : 'amber';
    whoLine.textContent = [S.who, S.number4 ? masked(S.number4) : ''].filter(Boolean).join(' \u00b7 ');
    paintFacts();
    const on = !S.ended && !!S.ws;
    [takeBtn, hangBtn, tellSend, tell].forEach((b) => { b.disabled = !on; });
    takeBtn.disabled = !on || S.taken;
    takeBtn.textContent = S.taken ? 'You have the call' : 'Take over';
    seg.querySelectorAll('input').forEach((i) => { i.disabled = S.ended; i.checked = (i.value === 'live') === S.audio; });
    takenNote.textContent = S.taken && !S.ended ? TAKEN : '';
    recNote.textContent = S.recording || S.ended ? '' : 'Recording stopped: they asked not to be recorded. Only notes are kept for the summary.';
    endActs.replaceChildren();
    if (S.ended) endActs.append(button('Open the record', 'primary sact', () => ctx.openRecord(S.id)), button('Close', 'sact', () => close(true)));
  }
  function paintFacts() {
    const secs = S.seconds + (S.at && isLive(S.state) ? Math.floor((Date.now() - S.at) / 1000) : 0);
    facts.textContent = [S.lang ? langName(S.lang) : '', duration(secs), S.cost !== null ? rupees(S.cost) : ''].filter(Boolean).join(' \u00b7 ');
  }
  function add(l) {
    log.append(lineEl(l));
    while (log.childElementCount > MAX_LINES) log.firstElementChild.remove();
    if (S.stick) log.scrollTop = log.scrollHeight;
  }

  // ---- the socket ---------------------------------------------------------------------------------------------------
  function url() { return (location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host + PATHS.live(S.id); }
  function connect() {
    clearTimeout(S.timer);
    if (!S.id || S.ended) return;
    let ws;
    try { ws = new WebSocket(url()); } catch (e) { say(conn, failed(e), 'bad'); return; }
    ws.binaryType = 'arraybuffer';
    S.ws = ws;
    say(conn, S.tries ? 'Connecting again\u2026' : 'Connecting to the call\u2026');
    ws.onopen = () => { if (S.ws !== ws) return; S.tries = 0; say(conn, ''); send({ type: 'listen', audio: S.audio }); paint(); };
    ws.onmessage = (e) => { if (S.ws === ws) receive(e.data); };
    ws.onclose = (ev) => {
      if (S.ws !== ws) return;
      S.ws = null;
      paint();
      if (S.ended || !S.id) return;
      if (CLOSED[ev.code]) { if (ev.code === 4404) end(CLOSED[ev.code]); else say(conn, CLOSED[ev.code], 'bad'); paint(); return; }
      if (S.tries >= RETRY_MS.length) { say(conn, 'The live view lost the call. It goes on; press Live in the list to look again.', 'bad'); return; }
      say(conn, 'Connection lost. Connecting again\u2026', 'bad');
      S.timer = setTimeout(connect, RETRY_MS[S.tries++]);
    };
  }
  function send(msg) {
    if (!S.ws || S.ws.readyState !== 1) return false;
    S.ws.send(JSON.stringify(msg));
    return true;
  }
  function receive(data) {
    if (data instanceof ArrayBuffer) { if (S.audio) ear.feed(data); return; }
    if (typeof data !== 'string' || data.length > MAX_TEXT) return;
    let m = null;
    try { m = JSON.parse(data); } catch (_) { return; }
    if (!m || typeof m !== 'object') return;
    if (m.type === 'caption') { const l = checkCaption(m); if (l) add(l); return; }
    if (m.type === 'state') {
      const s = liveState(m);
      if (s.state) S.state = s.state;
      if (s.lang) S.lang = s.lang;
      if (s.seconds !== null) { S.seconds = s.seconds; S.at = Date.now(); }
      if (s.cost !== null) S.cost = s.cost;
      if (s.taken || s.state === 'taken_over') S.taken = true;
      S.recording = s.recording;
      if (s.state && !isLive(s.state)) end(s.end ? END_WORDS[s.end] : '');
      paint();
    }
  }
  function end(words) {
    S.ended = true;
    ear.stop(); S.audio = false;
    clearInterval(S.tick);
    say(conn, words || 'The call ended. Its summary is on its way to the record.');
    if (S.ws) { const ws = S.ws; S.ws = null; try { ws.close(1000); } catch (_) { /* gone */ } }
    ctx.ended(S.id);
  }

  // ---- his controls -------------------------------------------------------------------------------------------------
  async function hear(live) {
    err.textContent = '';
    if (!live) { S.audio = false; ear.stop(); send({ type: 'listen', audio: false }); paint(); return; }
    try {
      await ear.start(); // from his press: the browser lets the sound start
      S.audio = true;
      send({ type: 'listen', audio: true });
    } catch (e) { S.audio = false; err.textContent = e.message || failed(e); }
    paint();
  }
  function takeover() {
    if (S.taken || !send({ type: 'takeover' })) return;
    S.taken = true; paint();
    hangBtn.focus(); // Take over is now disabled: the keyboard stays on the call's controls
  }
  function hangup() { if (send({ type: 'hangup' })) { say(conn, 'Hanging up\u2026'); hangBtn.disabled = true; } }
  function sendTell() {
    const text = tell.value.trim();
    if (!text) { err.textContent = 'Type what JARVIS should do.'; tell.focus(); return; }
    if (!send({ type: 'tell', text: text.slice(0, TELL_MAX) })) { err.textContent = 'The live view isn\u2019t connected. Try again in a moment.'; return; }
    err.textContent = '';
    add({ who: 'note', lang: '', text: 'You to JARVIS: ' + text, english: '' });
    tell.value = '';
    tell.focus();
  }

  // ---- open / close ----------------------------------------------------------------------------------------------
  function open(callId, about) {
    if (S.id === callId && !view.hidden && !S.ended) { h.focus(); return; }
    close(false);
    Object.assign(S, { id: callId, tries: 0, audio: false, state: (about && about.state) || '', lang: '', seconds: 0, at: 0,
      cost: null, taken: false, ended: false, recording: true, stick: true, who: (about && about.who) || '', number4: (about && about.number4) || '' });
    log.replaceChildren();
    err.textContent = ''; takenNote.textContent = '';
    view.hidden = false;
    paint();
    connect();
    S.tick = setInterval(paintFacts, 1000);
    h.focus();
    if (!S.who && !S.number4) whoIs(callId); // opened from the status alone: who it is comes with the record
  }
  async function whoIs(callId) {
    try {
      const r = checkRecord(await api(PATHS.records + '/' + encodeURIComponent(callId)));
      if (r && S.id === callId) { S.who = r.who; S.number4 = r.number4; paint(); }
    } catch (_) { /* the call is still being made: its name shows once the list has it */ }
  }
  function close(focusBack) {
    clearTimeout(S.timer); clearInterval(S.tick);
    ear.stop(); S.audio = false;
    if (S.ws) { const ws = S.ws; S.ws = null; try { ws.close(1000); } catch (_) { /* gone */ } }
    const was = S.id;
    S.id = '';
    view.hidden = true;
    if (focusBack && was) ctx.closedLive();
  }
  return Object.freeze({ open, close, id: () => S.id, shown: () => !view.hidden, stopSound: () => { if (S.audio) hear(false); } });
}
