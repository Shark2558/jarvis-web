// src/jarvis/api/static/console-voice-session.js -- R5.2 V3 (docs/plans/r5-2-voice.md 3.3, D4;
// I0 seams /v1/voice/profile): Voice -> "Your voice" and the 20-minute voice session pop-up.
// Loaded by console-r7.js (one line, with its stylesheet console-voice-session.css); it puts its
// section after the Voice panel's slots, so neither console.html nor console-voice.js changes. The console's look is kept: existing classes and tokens only.
//   The section: where the session stands, the engines ranked for his voice, the chosen one, the
//   corrections switch, Start / Continue, Check again, Delete my recordings (a confirm first).
//   The pop-up: about 120 short lines in 4 blocks with a break after each; Record (stops by itself
//   when he pauses), Redo, Skip. Each clip goes to POST .../session/clips as a WAV (window.JarvisWav)
//   and on to his laptop; for a comparison line this browser's own listening may hear it too (his
//   choice, said plainly: in Chrome that audio goes to the browser's maker) and its words go with
//   the clip. The rupee question (402 needs_yes) is answered by typing YES, or by going on without
//   Google; a clip refused for it is sent again after his answer. Then Score -> the results.
// Audio stays in this page's memory only until its clip is sent; nothing is stored here but this
// device's browser-listening choice. While the pop-up is open a voice conversation is ended and
// "Hey Jarvis" is paused (the session says it 30 times). No build step; CSP script-src 'self';
// textContent only; the console's api() is the only transport.
const PREFIX = '/v1/voice/profile';
const PID = /^[a-z][a-z0-9_]{0,31}$/;
const BROWSER_KEY = 'jarvis_voice_session_browser_v1';
const VAD = { endSilenceMs: 1100, noSpeechMs: 7000, maxMs: 19000 };
const FINAL_WAIT_MS = 1500;   // the browser's last words arrive a little after the audio ends
const POLL_MS = 3000;
const BLOCK_TITLES = ['', 'Commands', 'Your words, places and names', 'Numbers and times', 'Everyday requests'];
const STEP_TITLES = ['', 'Commands', 'Words', 'Numbers', 'Requests'];
const KINDS = { command: 'Command', words: 'Your word', places: 'Place or name', numbers: 'Numbers and times', wake: 'Hey Jarvis' };
const STATES = { none: '', recording: 'In progress', scoring: 'Scoring', done: 'Done', failed: 'Needs a look' };
const MIC_OFF = 'The microphone is switched off. Switch it on with the mic button, then press Record.';
const NOTHING = 'JARVIS didn\'t hear anything. Press Record and read the line aloud.';
const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
const LEAD = 'Read about 120 short lines aloud: 20 minutes, with a break after each block. JARVIS then '
  + 'tries every listening engine on your voice, keeps the one that understands you best and learns '
  + 'your usual mishearings (never numbers, money or codes). The recordings stay on your laptop, '
  + 'encrypted, until you delete them.';
const BROWSER_HELP = 'For the comparison lines only. In Chrome, this browser\'s listening sends the audio to '
  + 'the browser\'s maker; off, the comparison is Google and the laptop.';

const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
const arr = (v) => (Array.isArray(v) ? v : []);
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const txt = (v, max = 400) => (typeof v === 'string' ? v.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').trim().slice(0, max) : '');
const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
const store = { get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} } };
function api(path, opts) {
  const con = window.JarvisConsole;
  if (!con || typeof con.api !== 'function') return Promise.reject(new Error('The console is still starting.'));
  return con.api(path, opts);
}
function words(e, fallback) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const t = e && typeof e.message === 'string' ? txt(e.message, 400) : '';
  return t && !/^[a-z0-9_.-]+$/i.test(t) ? t : fallback || 'Please try again.';
}
const pct = (v) => (num(v) === null ? '' : v.toFixed(1).replace(/\.0$/, '') + ' %');

// ---- what the server sends, checked field by field ------------------------------------------------
function normProfile(o) {
  const p = obj(o);
  if (!p) return null;
  const rank = arr(p.ranking).map(obj).filter(Boolean).map((r) => ({ label: txt(r.label, 60), wer: num(r.wer_pct), commands: num(r.commands_pct),
    prompts: num(r.prompts) || 0, chosen: r.chosen === true, laptop: r.on_laptop === true, engine: txt(r.engine, 40) }));
  return { state: txt(p.state, 20), chosen: txt(p.chosen, 40), chosenLabel: txt(p.chosen_label, 60), ranking: rank,
    corrections: arr(p.corrections).length, correctionsOn: p.corrections_on !== false, clips: num(p.clips) || 0,
    order: arr(p.order_labels).map((l) => txt(l, 60)).filter(Boolean), bar: p.meets_bar === true ? true : p.meets_bar === false ? false : null };
}
function normSession(o) {
  const s = obj(o);
  if (!s) return null;
  const prompts = arr(s.prompts).map(obj).filter((p) => p && typeof p.id === 'string' && PID.test(p.id)).map((p) => ({
    id: p.id, block: num(p.block) || 1, kind: txt(p.kind, 20), text: txt(p.text, 160), how: txt(p.how, 60), compare: p.compare === true, wake: p.wake === true }));
  const c = obj(s.compare);
  return { state: txt(s.state, 20) || 'none', prompts, done: new Set(arr(s.done).filter((d) => typeof d === 'string')),
    compare: c ? { mode: txt(c.mode, 20), words: txt(c.words, 400) } : null, reason: txt(s.reason, 300),
    added: arr(s.words_added).map((w) => txt(w, 40)).filter(Boolean) };
}

// ---- the section in the Voice panel ------------------------------------------------------------------
const P = { profile: undefined, session: undefined, error: '', busy: false, loading: null, ui: null };

function load() {
  if (P.loading) return P.loading;
  P.loading = (async () => {
    try {
      const [p, s] = await Promise.all([api(PREFIX), api(PREFIX + '/session')]);
      P.profile = normProfile(p); P.session = normSession(s); P.error = '';
    } catch (e) {
      if (e && e.status === 401) return;
      P.error = words(e, 'Couldn\'t load your voice profile.');
    } finally { P.loading = null; render(); }
  })();
  render();
  return P.loading;
}

function buildSection() {
  const after = document.getElementById('vSlotPace');
  if (!after) return null;
  let slot = document.getElementById('vSlotProfile');
  if (slot && P.ui && slot.contains(P.ui.sec)) return P.ui;
  if (!slot) { slot = mk('div', 'vslot'); slot.id = 'vSlotProfile'; after.after(slot); }
  slot.textContent = '';
  const sec = mk('section', 'bsec'), h = mk('h3');
  sec.setAttribute('aria-labelledby', 'vProfileT'); h.id = 'vProfileT'; h.append(mk('span', '', 'Your voice')); sec.append(h);
  const ui = { sec, status: mk('div', 'vstatus'), rank: mk('div', 'vlist vs-rank'), acts: mk('div', 'actions'), note: mk('p', 'bnote') };
  ui.status.id = 'vProfileStatus'; ui.rank.id = 'vProfileRank'; ui.note.id = 'vProfileNote'; ui.note.setAttribute('role', 'status');
  ui.start = button('btn lift bact primary', 'Start the voice session', 'vProfileStart', () => openSession(ui.start));
  ui.check = button('btn lift bact', 'Check again', 'vProfileCheck', recheck);
  ui.del = button('btn lift bact danger', 'Delete my recordings', 'vProfileDelete', () => confirmDelete(ui.del));
  // R5.2 I1: his own "Hey Jarvis" from the session's clips (V4's console-wakeword-own.js trains it on the laptop)
  ui.train = button('btn lift bact', 'Train my Hey Jarvis', 'vProfileTrain', () => trainWake('verifier'));
  ui.own = button('btn lift bact', 'Train my own wake word (2 to 3 hours)', 'vProfileOwn', () => trainWake('owned'));
  ui.acts.append(ui.start, ui.check, ui.train, ui.own, ui.del);
  ui.corr = toggle('vProfileCorr', 'Correct my usual mishearings', '', (on) => saveProfile({ corrections_on: on }));
  sec.append(mk('p', 'bfine vlead', LEAD), ui.status, ui.rank, ui.corr.row, ui.acts, ui.note);
  slot.append(sec);
  P.ui = ui;
  return ui;
}
function button(cls, label, id, onClick) {
  const b = mk('button', cls, label); b.type = 'button'; if (id) b.id = id;
  b.addEventListener('click', onClick);
  return b;
}
function toggle(id, label, help, onPress) {
  const row = mk('div', 'bopt'), t = mk('div', 'btxt'), l = mk('span', 'bl', label), d = mk('small', '', help);
  l.id = id + 'L'; d.id = id + 'D'; t.append(l, d);
  const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
  b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-labelledby', l.id); b.setAttribute('aria-describedby', d.id);
  const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
  const st = mk('span', 'st', 'Off'); st.setAttribute('aria-hidden', 'true');
  b.append(track, st);
  b.addEventListener('click', () => onPress(b.getAttribute('aria-pressed') !== 'true'));
  row.append(t, b);
  return { row, button: b, help: d, set(on) { b.setAttribute('aria-pressed', String(on)); st.textContent = on ? 'On' : 'Off'; } };
}
function line(kind, text) { return mk('p', 'vline-s' + (kind ? ' ' + kind : ''), text); }

function render() {
  const ui = buildSection();
  if (!ui) return;
  const p = P.profile, s = P.session;
  ui.status.textContent = ''; ui.rank.textContent = '';
  if (P.profile === undefined && !P.error) ui.status.append(line('', P.loading ? 'Loading your voice profile…' : 'Your voice profile loads when this panel opens.'));
  if (P.error) ui.status.append(line('warn', P.error));
  if (p && s) {
    const done = s.done.size, total = s.prompts.length;
    if (s.state === 'recording') ui.status.append(line('', `Voice session in progress: ${done} of ${total} lines recorded.`));
    else if (s.state === 'scoring') ui.status.append(line('', 'Your laptop is scoring your recordings.'));
    else if (s.state === 'failed') ui.status.append(line('warn', s.reason || 'The last session could not be scored.'));
    if (p.chosen) {
      ui.status.append(line('ok', `Best for your voice: ${p.chosenLabel}.`));
      p.ranking.forEach((r) => ui.rank.append(rankRow(r)));
    } else if (s.state === 'none') ui.status.append(line('', 'No voice session yet. JARVIS listens with: ' + (p.order.join(', then ') || 'the usual engines') + '.'));
    if (p.bar === false) ui.status.append(line('warn', 'The chosen engine is more than 2 points behind the best cloud engine on your voice.'));
  }
  ui.status.hidden = !ui.status.childElementCount; ui.rank.hidden = !ui.rank.childElementCount;
  const state = s ? s.state : 'none';
  ui.start.textContent = state === 'recording' ? 'Continue the voice session' : p && p.chosen ? 'Record a new session' : 'Start the voice session';
  ui.start.disabled = P.busy || !p || state === 'scoring';
  ui.check.hidden = !(p && p.clips > 0 && (state === 'done' || state === 'failed'));
  ui.del.hidden = !(p && p.clips > 0);
  const W = window.JarvisWakeOwn;
  ui.train.hidden = ui.own.hidden = !(W && typeof W.train === 'function' && p && p.clips > 0 && state === 'done');
  ui.check.disabled = ui.del.disabled = ui.train.disabled = ui.own.disabled = P.busy;
  ui.corr.row.hidden = !(p && p.corrections > 0);
  if (p) { ui.corr.set(p.correctionsOn); ui.corr.help.textContent = `${p.corrections} learned from your session. Applied after listening; never to numbers, money or codes.`; }
}
function rankRow(r) {
  const row = mk('div', 'bopt'), t = mk('div', 'btxt');
  t.append(mk('span', 'bl', r.label), mk('small', '', `Word error ${pct(r.wer)} · commands right ${pct(r.commands)} · ${r.prompts} lines`));
  row.append(t);
  if (r.chosen) row.append(mk('span', 'vchip on', 'Chosen'));
  return row;
}
function say(text, kind) { if (!P.ui) return; P.ui.note.textContent = text || ''; P.ui.note.className = 'bnote' + (kind ? ' ' + kind : ''); }

async function saveProfile(body) {
  P.busy = true; render();
  try { P.profile = normProfile(await api(PREFIX, { method: 'PUT', body })); say('Saved.', 'ok'); } catch (e) { if (e.status !== 401) say('Couldn\'t save. ' + words(e), 'bad'); } finally { P.busy = false; render(); }
}
async function trainWake(artifact) {
  const W = window.JarvisWakeOwn;
  if (!W || typeof W.train !== 'function' || P.busy) return;
  P.busy = true; render();
  try {
    await W.train(artifact);
    say(artifact === 'owned'
      ? 'Your laptop is training your own wake word: 2 to 3 hours, and its speech waits meanwhile (Google listens). It replaces today\'s only if it does better.'
      : 'Your laptop is training your Hey Jarvis check from your session: a few minutes. It is used once it passes its tests.', 'ok');
  } catch (e) { if (e.status !== 401) say(words(e, 'The laptop couldn\'t start the training.'), 'bad'); } finally { P.busy = false; render(); }
}
async function recheck() {
  P.busy = true; say('Checking your recordings again on the laptop…'); render();
  try {
    const r = obj(await api(PREFIX + '/recheck', { method: 'POST', body: {} }));
    await load();
    say(r && r.state === 'scoring' ? 'The laptop is scoring your recordings again. This takes a few minutes.' : 'Checked again.', 'ok');
  } catch (e) { if (e.status !== 401) say(words(e), 'bad'); } finally { P.busy = false; render(); }
}

// "Delete my recordings": a confirm dialog, then POST .../recordings/delete {confirm: "DELETE"}
let delDlg = null;
function confirmDelete(opener) {
  if (!delDlg) {
    delDlg = mk('dialog', 'bdialog'); delDlg.id = 'vsDelete'; delDlg.setAttribute('aria-labelledby', 'vsDeleteT');
    const h = mk('h2', '', 'Delete your recordings?'); h.id = 'vsDeleteT';
    const p1 = mk('p', 'strong'), p2 = mk('p', '', 'Your voice profile stays (the chosen engine and the corrections). The wake-word files made from the recordings stay too; delete them in Privacy.');
    p1.id = 'vsDeleteText';
    const acts = mk('div', 'actions');
    const keep = button('btn', 'Keep them', 'vsDeleteKeep', () => delDlg.close());
    const go = button('btn danger', 'Delete recordings', 'vsDeleteGo', async () => { delDlg.close(); await doDelete(); });
    acts.append(keep, go); delDlg.append(h, p1, p2, acts); document.body.append(delDlg);
    delDlg.addEventListener('close', () => { if (delDlg.opener && delDlg.opener.isConnected) delDlg.opener.focus(); });
  }
  const n = P.profile ? P.profile.clips : 0;
  delDlg.querySelector('#vsDeleteText').textContent = `This deletes the ${n} recording${n === 1 ? '' : 's'} of your voice from your laptop, and the words the engines heard for them. It can't be undone.`;
  delDlg.opener = opener; delDlg.showModal(); delDlg.querySelector('#vsDeleteKeep').focus();
}
async function doDelete() {
  P.busy = true; render();
  try { const r = obj(await api(PREFIX + '/recordings/delete', { method: 'POST', body: { confirm: 'DELETE' } })); say(txt(r && r.words, 200) || 'Deleted.', 'ok'); await load(); } catch (e) { if (e.status !== 401) say(words(e), 'bad'); } finally { P.busy = false; render(); }
}

// ---- the voice session pop-up -----------------------------------------------------------------------
const D = { dlg: null, ui: null, s: null, idx: 0, phase: 'intro', rec: null, pending: null, opener: null, wake: false, poll: 0, seq: 0 };
const useBrowser = () => store.get(BROWSER_KEY) !== 'off';

function buildDialog() {
  if (D.dlg) return D.dlg;
  const d = mk('dialog', 'bdialog vsess'); d.id = 'vsDlg';
  d.setAttribute('aria-labelledby', 'vsTitle'); d.setAttribute('aria-describedby', 'vsStatus');
  const top = mk('div', 'vs-top'), head = mk('div', 'vs-head'), h = mk('h2', '', 'Your voice'); h.id = 'vsTitle';
  const x = button('pbtn vs-x', '', 'vsClose', () => d.close()); x.setAttribute('aria-label', 'Close the voice session');
  x.append(closeIcon());
  head.append(h, x);
  const status = mk('p', 'vs-status'); status.id = 'vsStatus'; status.setAttribute('role', 'status');
  const bar = mk('div', 'mbar vs-bar'), fill = mk('i'); bar.append(fill); bar.setAttribute('aria-hidden', 'true');
  const steps = mk('ol', 'vs-steps'); steps.setAttribute('aria-label', 'Blocks');
  top.append(head, status, bar, steps);
  const body = mk('div', 'vs-body'); body.id = 'vsBody';
  const note = mk('p', 'bnote'); note.id = 'vsNote'; note.setAttribute('role', 'alert');
  d.append(top, body, note);
  d.addEventListener('close', onClose);
  document.body.append(d);
  D.dlg = d; D.ui = { status, fill, steps, body, note };
  return d;
}
function closeIcon() {
  const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), p = document.createElementNS(NS, 'path');
  s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('aria-hidden', 'true');
  p.setAttribute('d', 'm5.5 5.5 9 9M14.5 5.5l-9 9'); s.append(p);
  return s;
}
function note(text, kind) { D.ui.note.textContent = text || ''; D.ui.note.className = 'bnote' + (kind ? ' ' + kind : ''); }

async function openSession(opener) {
  buildDialog();
  D.opener = opener; D.seq += 1; note('');
  endLoop(); pauseWake();
  D.dlg.showModal();
  D.phase = 'loading'; draw();
  try { D.s = normSession(await api(PREFIX + '/session')); } catch (e) { D.s = null; if (e.status !== 401) note(words(e), 'bad'); }
  if (!D.s) { D.phase = 'intro'; D.s = { state: 'none', prompts: [], done: new Set(), compare: null, reason: '', added: [] }; }
  else if (D.s.state === 'recording') { D.idx = nextIndex(-1); D.phase = D.idx < 0 ? 'end' : 'record'; }
  else if (D.s.state === 'scoring') { D.phase = 'scoring'; poll(); }
  else D.phase = 'intro';
  draw();
}
function onClose() {
  stopRecording(true);
  clearTimeout(D.poll); D.poll = 0; D.pending = null; D.seq += 1;
  const A = window.JarvisAudio; try { if (A && A.isOpen()) A.close(); } catch (_) {}
  resumeWake();
  load();
  if (D.opener && D.opener.isConnected) D.opener.focus();
}
function endLoop() { const L = window.JarvisVoiceLoop; try { if (L && typeof L.end === 'function') L.end('session'); } catch (_) {} }
function pauseWake() { const W = window.JarvisWake; D.wake = false; try { if (W && W.state === 'listening') { W.pause(); D.wake = true; } } catch (_) {} }
function resumeWake() { const W = window.JarvisWake; try { if (D.wake && W) W.resume(); } catch (_) {} D.wake = false; }

function nextIndex(from) {
  const ps = D.s.prompts;
  for (let i = from + 1; i < ps.length; i++) if (!D.s.done.has(ps[i].id)) return i;
  for (let i = 0; i <= from && i < ps.length; i++) if (!D.s.done.has(ps[i].id)) return i;
  return -1;
}

// ---- drawing each step of the pop-up --------------------------------------------------------------
function draw() {
  const ui = D.ui, s = D.s, ps = s ? s.prompts : [], done = s ? s.done.size : 0, cur = ps[D.idx];
  ui.steps.textContent = '';
  for (let b = 1; b <= 4; b++) {
    const mine = ps.filter((p) => p.block === b), got = mine.filter((p) => s.done.has(p.id)).length;
    const li = mk('li'); li.title = BLOCK_TITLES[b]; li.append(mk('span', 'k', `${b} · ${STEP_TITLES[b]}`), mk('b', '', mine.length ? `${got} of ${mine.length}${got === mine.length ? ' · done' : ''}` : '5 min'));
    if (mine.length && got === mine.length) li.dataset.done = 'true';
    if (cur && cur.block === b && (D.phase === 'record' || D.phase === 'ask')) li.setAttribute('aria-current', 'step');
    ui.steps.append(li);
  }
  ui.fill.style.width = ps.length ? `${Math.round((done / ps.length) * 100)}%` : '0%';
  ui.status.textContent = statusText(cur, done, ps.length);
  ui.body.textContent = '';
  const step = { loading: () => ui.body.append(mk('p', 'vs-text', 'Loading the session…')), intro: drawIntro, record: drawRecord, ask: drawAsk,
    pause: drawBreak, end: drawEnd, scoring: drawScoring, results: drawResults }[D.phase];
  if (step) step();
}
function statusText(cur, done, total) {
  if (D.phase === 'record' && cur) return `Block ${cur.block} of 4 · ${BLOCK_TITLES[cur.block]} · ${done} of ${total} recorded`;
  if (D.phase === 'pause') return `${done} of ${total} recorded · a short break`;
  if (D.phase === 'scoring') return 'Your laptop is listening to your recordings…';
  if (D.phase === 'results') return 'Your voice: the results';
  if (D.phase === 'ask') return 'One question before the next line';
  return total ? `${done} of ${total} recorded` : 'About 20 minutes, with breaks';
}
function actions(...btns) { const a = mk('div', 'actions'); a.append(...btns); D.ui.body.append(a); return a; }
function field(id, label, input) { const f = mk('div', 'vs-field'), l = mk('label', '', label); l.htmlFor = id; input.id = id; f.append(l, input); return f; }

function drawIntro() {
  const b = D.ui.body, s = D.s;
  b.append(mk('p', 'vs-text', LEAD));
  if (s.state === 'done' || s.state === 'failed') b.append(mk('p', 'vs-text', 'A new session replaces the recordings of the last one on your laptop. Your current results stay until the new ones are ready.'));
  const words = mk('input', 'minput'); words.type = 'text'; words.autocomplete = 'off'; words.spellcheck = false; words.maxLength = 600;
  b.append(field('vsWords', 'Names and places you use (optional)', words));
  b.append(mk('p', 'vs-hint', 'Separate them with commas, up to 20. They are read in block 2 and join your words to recognise.'));
  const sw = toggle('vsBrowser', 'Include this browser\'s listening', BROWSER_HELP, (on) => { store.set(BROWSER_KEY, on ? 'on' : 'off'); sw.set(on); });
  sw.set(useBrowser()); b.append(sw.row);
  getPreview().then((c) => { if (c && D.phase === 'intro') { const n = mk('p', 'bnote' + (c.mode === 'needs_yes' ? ' vs-ask' : ''), c.words); b.insertBefore(n, b.querySelector('.actions')); } });
  const go = button('btn primary', 'Start', 'vsStart', () => start({ words: splitWords(words.value) }));
  actions(go, button('btn', 'Not now', 'vsLater', () => D.dlg.close()));
  go.focus();
}
async function getPreview() { try { const s = normSession(await api(PREFIX + '/session')); return s && s.compare; } catch (_) { return null; } }
function splitWords(raw) { return String(raw || '').split(',').map((w) => w.trim()).filter(Boolean).slice(0, 20); }

async function start(body, then) {
  note('');
  const seq = D.seq;
  try {
    const s = normSession(await api(PREFIX + '/session/start', { method: 'POST', body }));
    if (seq !== D.seq || !s) return;
    D.s = s; D.idx = nextIndex(-1); D.phase = D.idx < 0 ? 'end' : 'record'; draw();
    if (then) then();
  } catch (e) {
    if (seq !== D.seq || e.status === 401) return;
    if (e.status === 402 && e.code === 'needs_yes') { D.ask = { words: words(e), body }; D.phase = 'ask'; draw(); return; }
    note(words(e), 'bad');
  }
}
function drawAsk() {
  const b = D.ui.body, ask = D.ask || { words: '' };
  b.append(mk('p', 'bnote vs-ask', ask.words));
  const yes = mk('input', 'minput vs-yes'); yes.type = 'text'; yes.autocomplete = 'off'; yes.spellcheck = false; yes.maxLength = 3;
  b.append(field('vsYes', 'Type YES to include Google', yes));
  const resend = () => { const p = D.pending; D.pending = null; if (p) send(p); };
  const inc = button('btn primary', 'Include Google', 'vsYesGo', () => {
    if (yes.value.trim() !== 'YES') { note('Type YES in capitals to include Google, or go on without it.', 'bad'); yes.focus(); return; }
    start(Object.assign({}, ask.body || {}, { yes: 'YES' }), resend);
  });
  const skip = button('btn', 'Go on without Google', 'vsYesSkip', () => start(Object.assign({}, ask.body || {}, { compare: false }), resend));
  yes.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); inc.click(); } });
  actions(inc, skip);
  yes.focus();
}

function drawRecord() {
  const b = D.ui.body, p = D.s.prompts[D.idx];
  if (!p) { D.phase = 'end'; draw(); return; }
  const card = mk('div', 'vs-card'), k = mk('p', 'k');
  k.append(mk('span', '', `Line ${D.idx + 1} of ${D.s.prompts.length} · ${KINDS[p.kind] || ''}`));
  if (p.compare) k.append(mk('span', 'acc', '· For the comparison'));
  const said = mk('p', 'vs-line', p.wake ? '“' + p.text + '”' : p.text); said.id = 'vsLine';
  const how = mk('p', 'vs-how', p.how ? 'Say it ' + p.how + '.' : '');
  const level = mk('div', 'mbar vs-level'), fill = mk('i'); level.append(fill); level.setAttribute('aria-hidden', 'true');
  card.append(k, said, how, level);
  b.append(card, mk('p', 'vs-hint', 'Press Record, read the line, then pause: JARVIS stops by itself. Space or Enter on the button works too.'));
  const rec = button('btn primary', 'Record', 'vsRecord', () => (D.rec ? stopRecording(false) : record(p, fill)));
  rec.setAttribute('aria-pressed', 'false');
  const redo = button('btn', 'Redo last', 'vsRedo', redoLast);
  redo.disabled = !D.s.done.size;
  const skip = button('btn', 'Skip', 'vsSkip', () => { stopRecording(true); D.idx = nextIndex(D.idx); if (D.idx < 0) D.phase = 'end'; draw(); });
  actions(rec, redo, skip);
  D.ui.rec = rec; D.ui.level = fill;
  rec.focus();
}
function redoLast() {
  stopRecording(true);
  const ps = D.s.prompts, last = D.last && ps.findIndex((p) => p.id === D.last);
  D.idx = last >= 0 ? last : Math.max(0, D.idx - 1); D.phase = 'record'; draw();
}

// ---- one recording ------------------------------------------------------------------------------
async function record(p, fill) {
  const A = window.JarvisAudio, Vad = window.JarvisVad, Wav = window.JarvisWav;
  note('');
  if (!A || !Vad || !Wav || !A.supported()) { note('This browser can\'t record audio here.', 'bad'); return; }
  if (A.locked()) { note(MIC_OFF, 'bad'); return; }
  pauseWake();
  try { await A.open(); } catch (e) { note(e && e.code === 'mic_off' ? MIC_OFF : A.words(e && e.code), 'bad'); return; }
  const vad = Vad.create(VAD), r = { p, vad, unsub: null, heard: null, recog: null, done: false };
  D.rec = r;
  D.ui.rec.textContent = 'Stop'; D.ui.rec.setAttribute('aria-pressed', 'true');
  r.unsub = A.subscribe((frame) => {
    if (r.done) return;
    try { fill.style.width = Math.min(100, Math.round(A.level() * 300)) + '%'; } catch (_) {}
    const ev = vad.push(frame);
    if (!ev) return;
    if (ev.type === 'start') note('Listening…');
    else if (ev.type === 'timeout') { finish(r, null); note(NOTHING, 'bad'); }
    else finish(r, ev.frames);
  });
  if (p.compare && useBrowser()) r.recog = listen(r);
}
function listen(r) {
  const A = window.JarvisAudio, V = window.JarvisVoice;
  if (!A || typeof A.canRecognise !== 'function' || !A.canRecognise()) return null;
  try {
    const rec = A.recognizer();
    rec.lang = V && typeof V.language === 'function' ? V.language() : 'en-IN';
    rec.continuous = false; rec.interimResults = false; rec.maxAlternatives = 1;
    r.heard = '';
    rec.onresult = (ev) => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) r.heard = (r.heard + ' ' + ev.results[i][0].transcript).trim(); };
    rec.onerror = () => {};
    const ended = new Promise((res) => { rec.onend = res; });
    rec.start();
    return { rec, ended };
  } catch (_) { r.heard = null; return null; }
}
function stopRecording(drop) {
  const r = D.rec;
  if (!r) return;
  if (drop) { r.done = true; release(r); D.rec = null; return; }
  const frames = r.vad.frames();
  if (!frames.length) note(NOTHING, 'bad');
  finish(r, frames);
}
function release(r) {
  if (r.unsub) { try { r.unsub(); } catch (_) {} r.unsub = null; }
  if (r.recog) { try { r.recog.rec.abort(); } catch (_) {} }
  if (D.ui.rec) { D.ui.rec.textContent = 'Record'; D.ui.rec.setAttribute('aria-pressed', 'false'); }
  if (D.ui.level) D.ui.level.style.width = '0%';
}
async function finish(r, frames) {
  if (r.done) return;
  r.done = true;
  if (r.unsub) { try { r.unsub(); } catch (_) {} r.unsub = null; }
  if (D.ui.rec) { D.ui.rec.textContent = 'Record'; D.ui.rec.setAttribute('aria-pressed', 'false'); }
  D.rec = null;
  if (r.recog) { try { r.recog.rec.stop(); } catch (_) {} await Promise.race([r.recog.ended, new Promise((res) => setTimeout(res, FINAL_WAIT_MS))]); }
  if (!frames || !frames.length) { if (r.recog) try { r.recog.rec.abort(); } catch (_) {} return; }
  offerPrint(frames);
  const body = { audio: base64(window.JarvisWav.encode(frames)) };
  if (r.heard !== null && r.recog) body.browser_heard = r.heard.slice(0, 2000);
  await send({ id: r.p.id, body });
}
// R5.2 I1 (V5's seam): the clip's 16 kHz PCM to the speaker check on this device; it keeps only an
// embedding in memory until he taps "Use my voice session" there. Nothing is sent or stored here.
function offerPrint(frames) {
  const VP = window.JarvisVoicePrint;
  if (!VP || typeof VP.offerSessionClip !== 'function') return;
  const list = Array.from(frames).filter((f) => f instanceof Int16Array);
  const pcm = new Int16Array(list.reduce((n, f) => n + f.length, 0));
  let at = 0;
  list.forEach((f) => { pcm.set(f, at); at += f.length; });
  try { VP.offerSessionClip(pcm); } catch (_) {}
}
function base64(buf) {
  const bytes = new Uint8Array(buf);
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(out);
}
async function send(clip) {
  if (!PID.test(clip.id)) return;
  const seq = D.seq;
  note('Sending to your laptop…');
  try {
    const r = obj(await api(`${PREFIX}/session/clips/${clip.id}`, { method: 'PUT', body: clip.body }));
    if (seq !== D.seq) return;
    note('');
    D.s.done.add(clip.id); D.last = clip.id;
    if (r && r.compare === 'needs_yes') note('This month\'s free Google minutes just ran out: JARVIS asks before the next comparison line.', '');
    advance(clip.id);
  } catch (e) {
    if (seq !== D.seq || e.status === 401) return;
    if (e.status === 402 && e.code === 'needs_yes') { note(''); D.pending = clip; D.ask = { words: words(e), body: {} }; D.phase = 'ask'; draw(); return; }
    note(words(e, 'Couldn\'t send that recording. Press Record to try again.'), 'bad');
  }
}
function advance(id) {
  const ps = D.s.prompts, at = ps.findIndex((p) => p.id === id), block = at >= 0 ? ps[at].block : 1;
  D.idx = nextIndex(at);
  if (D.idx < 0) D.phase = 'end';
  else if (ps[D.idx].block !== block && ps.filter((p) => p.block === block).every((p) => D.s.done.has(p.id))) D.phase = 'pause';
  else D.phase = 'record';
  draw();
}
function drawBreak() {
  const p = D.s.prompts[D.idx], prev = p ? p.block - 1 : 4;
  D.ui.body.append(mk('p', 'vs-text', `Block ${prev} done. Take a short break: water, a stretch.`), mk('p', 'vs-text', p ? `Next: ${BLOCK_TITLES[p.block]}, about 5 minutes.` : ''));
  const go = button('btn primary', 'Continue', 'vsContinue', () => { D.phase = 'record'; draw(); });
  actions(go, button('btn', 'Stop for now', 'vsLater', () => D.dlg.close()));
  go.focus();
}
function drawEnd() {
  const s = D.s, left = s.prompts.length - s.done.size;
  D.ui.body.append(mk('p', 'vs-text', left ? `${s.done.size} of ${s.prompts.length} lines recorded (${left} skipped).` : 'Every line is recorded. Thank you, Sir.'),
    mk('p', 'vs-text', 'Scoring runs on your laptop and takes a few minutes. You can close this window meanwhile.'));
  const go = button('btn primary', 'Score my voice', 'vsScore', score);
  const btns = [go];
  if (left) btns.push(button('btn', 'Record the skipped lines', 'vsSkipped', () => { D.idx = nextIndex(-1); D.phase = 'record'; draw(); }));
  actions(...btns);
  go.focus();
}
async function score() {
  note('');
  try { const r = obj(await api(PREFIX + '/session/score', { method: 'POST', body: {} })); showResults(r); } catch (e) { if (e.status !== 401) note(words(e), 'bad'); }
}
function showResults(r) {
  if (!r) return;
  if (r.state === 'scoring') { D.phase = 'scoring'; D.job = obj(r.job); draw(); poll(); return; }
  D.result = r; D.phase = 'results'; draw();
}
function poll() {
  clearTimeout(D.poll);
  const seq = D.seq;
  D.poll = setTimeout(async () => {
    try { const r = obj(await api(PREFIX + '/session/results')); if (seq === D.seq) showResults(r); } catch (e) { if (seq === D.seq && e.status !== 401) { note(words(e), 'bad'); poll(); } }
  }, POLL_MS);
}
function drawScoring() {
  const job = D.job, bar = mk('div', 'mbar'), fill = mk('i');
  fill.style.width = job && num(job.progress) !== null ? Math.round(job.progress * 100) + '%' : '8%';
  bar.append(fill); bar.setAttribute('aria-hidden', 'true');
  D.ui.body.append(mk('p', 'vs-text', 'Your laptop is listening to each comparison line with its engines. The results appear here; you can close this window and come back.'), bar);
  actions(button('btn', 'Close', 'vsLater', () => D.dlg.close()));
}
function drawResults() {
  const r = D.result || {}, p = normProfile(r.profile), b = D.ui.body;
  if (r.state === 'failed' || !p || !p.chosen) { b.append(mk('p', 'bnote bad', txt(r.reason, 300) || 'The session could not be scored.')); actions(button('btn primary', 'Close', 'vsDone', () => D.dlg.close())); return; }
  b.append(mk('p', 'vs-text', 'JARVIS now listens to you with '), mk('p', 'vs-line', p.chosenLabel));
  const list = mk('div', 'vlist vs-rank'); p.ranking.forEach((x) => list.append(rankRow(x))); b.append(list);
  const best = p.ranking[0], mine = p.ranking.find((x) => x.chosen);
  if (best && mine && !best.chosen && mine.laptop) b.append(mk('p', 'vs-words', `Chosen over ${best.label}: it is within 2 points of it, costs nothing and your audio stays on your laptop.`));
  const added = arr(r.words_added).map((w) => txt(w, 40)).filter(Boolean);
  const learned = [p.corrections ? `${p.corrections} usual mishearing${p.corrections === 1 ? '' : 's'} learned (never numbers, money or codes).` : 'No repeating mishearings to correct.'];
  if (added.length) learned.push(`New words to recognise: ${added.join(', ')}.`);
  b.append(mk('p', 'vs-words', learned.join(' ')));
  const done = button('btn primary', 'Done', 'vsDone', () => D.dlg.close());
  actions(done); done.focus();
}

// ---- wiring --------------------------------------------------------------------------------------
document.addEventListener('jarvis:voice-panel', () => { render(); load(); });
document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'voice' && d.open) { render(); load(); } });
if (document.getElementById('vSlotPace')) { render(); load(); }
emit('jarvis:voice-session', { ready: true });
window.JarvisVoiceSession = Object.freeze({ open: (opener) => openSession(opener || null), refresh: load });
