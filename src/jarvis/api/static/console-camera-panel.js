// src/jarvis/api/static/console-camera-panel.js -- R7 Part B (docs/plans/r7-mobile.md D11-D13): the Camera panel in
// #p-camera .pbody, with three sub-tabs (the Helpers frame's look: .hp-tabs, .hp-pane, .hp-row; nothing new is drawn):
//   Look     pick what to look for (text, a code, light and sharpness; everyday things and body points once their model
//            files arrive), then Choose a photo or Start the camera. The engine (console-vision.js) looks ON THIS DEVICE
//            and shows the result in plain words. Keep sends only that result (POST /v1/vision/results: numbers, labels,
//            read text). A picture leaves the device only by one of three buttons, each saying so, all through I0's one
//            door (window.JarvisMobile.parts.send: Ask, Vault, Attach) that counts "Pictures sent from this device today".
//            "Ask the AI about this photo" is offered only while the brain answering sees pictures and No-AI is off.
//   Results  the results he kept (GET /v1/vision/results), each with Delete
//   Cameras  this device's camera switch (Switch off / Allow: only a tap allows), front or back, the home camera's place
// The camera starts only from a tap (console-camera.js) and stops when this panel closes or is hidden. Asks the server
// NOTHING before sign-in (jarvis:ready). Text a camera read is other people's words: shown with textContent, never obeyed.
// A camera button beside the paperclip opens this panel (it never starts the camera). ASCII source.
const M = window.JarvisMobile;
const panel = document.getElementById('p-camera');
const host = document.getElementById('cameraBody');
const meta = document.getElementById('cameraMeta');
const P = '/v1/vision';
const TABS = [['look', 'Look'], ['results', 'Results'], ['cameras', 'Cameras']];
const TASKS = [['text', 'Read text'], ['code', 'Read a code (QR or barcode)'], ['quality', 'Light and sharpness'],
  ['objects', 'Everyday things'], ['pose', 'Body points']];
const STREAMED = ['objects', 'pose', 'quality']; // live at a capped rate; text and codes are read on demand
const CODE_WORDS = { qr_code: 'QR code', ean_13: 'EAN-13', ean_8: 'EAN-8', upc_a: 'UPC-A', upc_e: 'UPC-E', code_128: 'Code 128',
  code_39: 'Code 39', itf: 'ITF', data_matrix: 'Data Matrix', pdf_417: 'PDF417', aztec: 'Aztec' };
const INTRO = 'JARVIS looks on this device. A picture leaves it only when you press a button that says so.';
const POSE_LIMITS = 'One person, within about 4 metres, head visible. Never for a decision a life depends on, and never to recognise who someone is.';
const NOT_HERE = 'Not installed on this server yet: its model file has not arrived.';
const NO_AI_LINE = 'No-AI mode is on, so no AI looks at pictures now.';
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const ASK_WORDS = 'Ask the AI about this photo (about \u20b90.30)';
const ASK_DEFAULT = 'What can you see in this photo?';
const PHOTO_SIDE = 2000;
const S = { tab: 'look', task: 'text', status: null, view: null, stream: null, photo: null, file: null, result: null, busy: false,
  sendFor: null, asking: false };
const mk = (tag, cls, text) => (M ? M.mk(tag, cls, text) : document.createElement(tag));
const signedIn = () => !!(window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready());
const Cam = () => window.JarvisCamera || null;
const Vis = () => window.JarvisVision || null;
const Door = () => (M && M.parts && M.parts.send) || null;
const pct = (v) => Math.round((Number(v) || 0) * 100) + ' %';

function button(text, cls, fn) {
  const b = mk('button', 'btn sact' + (cls ? ' ' + cls : ''), text);
  b.type = 'button';
  b.addEventListener('click', fn);
  return b;
}
function field(label, control) {
  const l = mk('label', 'hp-field');
  l.append(mk('span', 'snote', label), control);
  return l;
}
function say(el, text, kind) {
  el.className = 'snote' + (kind ? ' ' + kind : '');
  el.textContent = text || '';
}
function failed(e) {
  if (e && e.name === 'TypeError') return OFFLINE;
  const n = e && e.name;
  if (n === 'NotAllowedError' || n === 'SecurityError') return 'The camera wasn\u2019t allowed. Allow it for this site in the browser\u2019s settings, then tap Start again.';
  if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'No camera was found on this device.';
  if (n === 'NotReadableError') return 'The camera is busy in another app.';
  return (e && e.message) || 'That didn\u2019t work.';
}

// ---- the frame: intro, tab strip, three panes -------------------------------------------------------------------------
const tabsEl = mk('div', 'hp-tabs');
tabsEl.setAttribute('role', 'tablist');
tabsEl.setAttribute('aria-label', 'Camera');
const panes = {}, tabBtns = {};
TABS.forEach(([id, label]) => {
  const b = mk('button', 'hp-tab', label);
  b.type = 'button';
  b.id = 'camt-' + id;
  b.setAttribute('role', 'tab');
  b.setAttribute('aria-controls', 'camp-' + id);
  b.addEventListener('click', () => choose(id));
  tabBtns[id] = b;
  tabsEl.append(b);
  const p = mk('div', 'hp-pane');
  p.id = 'camp-' + id;
  p.setAttribute('role', 'tabpanel');
  p.setAttribute('aria-labelledby', b.id);
  p.tabIndex = 0;
  panes[id] = p;
});
tabsEl.addEventListener('keydown', (e) => {
  const ids = TABS.map(([id]) => id), at = ids.indexOf(S.tab);
  const next = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: ids.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  choose(ids[(next + ids.length) % ids.length]);
  tabBtns[S.tab].focus();
});

// Look
const taskSel = mk('select', 'minput');
taskSel.id = 'camTask';
TASKS.forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; taskSel.append(o); });
taskSel.addEventListener('change', () => { S.task = taskSel.value; stopLive(); paintTask(); if (S.photo) lookAt(S.photo); });
const whyEl = mk('p', 'sfine');
const actsEl = mk('div', 'sacts cam-acts');
const stage = mk('div', 'cam-stage');
const stateEl = mk('p', 'snote');
stateEl.setAttribute('role', 'status');
stateEl.setAttribute('aria-live', 'polite');
const outEl = mk('p', 'cam-out');
const keepActs = mk('div', 'sacts');
const sendActs = mk('div', 'sacts cam-send');
const askIn = mk('input', 'minput');
askIn.type = 'text';
askIn.maxLength = 300;
askIn.autocomplete = 'off';
askIn.placeholder = ASK_DEFAULT;
const askField = field('Your question for the AI', askIn);
const seeEl = mk('p', 'sfine');
const sentEl = mk('p', 'sfine');
const outBox = mk('div', 'cam-result');
outBox.append(outEl, keepActs, askField, sendActs, seeEl);
outBox.hidden = true;
panes.look.append(field('What to look for', taskSel), whyEl, actsEl, stage, stateEl, outBox, sentEl);

// Results
const listNote = mk('p', 'sfine', 'Only the results you pressed Keep on, sealed and kept for 90 days. Never a picture.');
const listEl = mk('div', '');
const listState = mk('p', 'snote');
panes.results.append(listNote, listState, listEl);

// Cameras
const camRow = mk('div', 'hp-row');
const camTxt = mk('div', 'hp-txt');
const camTitle = mk('b', '', 'This device\u2019s camera');
const camSub = mk('small', '');
camTxt.append(camTitle, camSub);
const camActs = mk('div', 'hp-acts');
camRow.append(camTxt, camActs);
const facingSel = mk('select', 'minput');
[['environment', 'Back camera'], ['user', 'Front camera']].forEach(([v, t]) => { const o = mk('option', '', t); o.value = v; facingSel.append(o); });
facingSel.addEventListener('change', () => { const c = Cam(); if (c) c.useFacing(facingSel.value); stopLive(); });
const homeSec = mk('section', 'hp-sec');
homeSec.append(mk('h3', 'hp-h', 'Home camera'),
  mk('p', 'sfine', 'The home camera is set in the Home panel. Switching this device\u2019s camera off never disarms it.'),
  (() => { const a = mk('div', 'sacts'); a.append(button('Open Home', '', () => window.JarvisDeck && window.JarvisDeck.open('home', { focus: true }))); return a; })());
const voiceLine = mk('p', 'sfine', 'Say \u201cJarvis, cameras off\u201d to switch this device\u2019s camera off by voice. Only a tap switches it back on.');
const thisSec = mk('section', 'hp-sec');
thisSec.append(mk('h3', 'hp-h', 'This device'), camRow, field('Camera to use', facingSel));
panes.cameras.append(thisSec, homeSec, voiceLine);
if (host) host.append(mk('p', 'sfine', INTRO), tabsEl, ...TABS.map(([id]) => panes[id]));

function choose(id) {
  S.tab = panes[id] ? id : 'look';
  TABS.forEach(([t]) => {
    const on = t === S.tab;
    tabBtns[t].setAttribute('aria-selected', on ? 'true' : 'false');
    tabBtns[t].tabIndex = on ? 0 : -1;
    panes[t].hidden = !on;
  });
  if (S.tab === 'results') loadResults();
}

// ---- what can run here ----------------------------------------------------------------------------------------------
function whyNot(task) {
  const st = S.status && S.status.tasks && S.status.tasks[task];
  if (st && st.installed === false) return NOT_HERE;
  const t = Vis() ? Vis().tasks().find((x) => x.id === task) : null;
  return t && t.why ? (t.why === 'not installed' ? NOT_HERE : t.why) : '';
}
function paintTask() {
  TASKS.forEach(([v, t], i) => {
    const not = whyNot(v) === NOT_HERE;
    taskSel.options[i].textContent = not ? t + ' (not installed)' : t;
  });
  const why = whyNot(S.task);
  whyEl.textContent = why || (S.task === 'pose' ? POSE_LIMITS : '');
  paintActs();
}
function paintActs() {
  const c = Cam(), live = !!(c && c.live()), blocked = whyNot(S.task) === NOT_HERE;
  const looks = (b) => { b.disabled = blocked; return b; }; // a task that is not installed can't look
  const acts = [];
  if (live) {
    if (!STREAMED.includes(S.task)) acts.push(looks(button('Read now', 'primary', readNow)));
    acts.push(looks(button('Take a photo', '', takePhoto)), button('Stop', '', () => { stopLive(); say(stateEl, 'The camera is off.'); }));
  } else {
    acts.push(looks(button('Choose a photo', '', choosePhoto)));
    acts.push(c && c.locked() ? button('Allow the camera', '', allow) : looks(button('Start the camera', 'primary', startLive)));
    if (S.photo) acts.push(button('Clear', '', clear));
  }
  actsEl.replaceChildren(...acts);
  paintMeta();
}
function paintMeta() {
  const c = Cam();
  const word = !c ? 'Off' : c.live() ? 'On' : c.locked() ? 'Switched off' : 'Off';
  if (meta) meta.textContent = word;
  camSub.textContent = c && c.locked()
    ? 'Switched off for JARVIS on this device. Only a tap switches it on again.'
    : 'Allowed. It starts only when you tap Start the camera, and stops when you leave.';
  camActs.replaceChildren(c && c.locked() ? button('Allow', '', allow) : button('Switch off', '', () => { const k = Cam(); if (k) k.lock('panel'); }));
}
function allow() {
  const c = Cam();
  if (c && !c.unlock('panel')) say(stateEl, 'Tap Allow to switch the camera on.');
}

// ---- looking: a photo, or the live picture ----------------------------------------------------------------------------
function clear() {
  if (S.photo) { S.photo.width = 0; S.photo.height = 0; }
  S.photo = null; S.file = null; S.result = null; S.sendFor = null;
  stage.replaceChildren();
  outBox.hidden = true;
  paintActs();
}
async function choosePhoto() {
  const c = Cam();
  if (!c) return;
  stopLive();
  let file = null;
  try { file = await c.photo(); } catch (e) { say(stateEl, failed(e), 'bad'); return; }
  if (!file) return;
  if (!/^image\//.test(file.type || '')) { say(stateEl, 'That is not a picture. Choose a JPEG or PNG photo.', 'bad'); return; }
  let bmp = null;
  try { bmp = await createImageBitmap(file); } catch (_) { say(stateEl, 'This picture can\u2019t be read here. Try a JPEG or PNG.', 'bad'); return; }
  const k = Math.min(1, PHOTO_SIDE / Math.max(bmp.width, bmp.height));
  const cv = mk('canvas', 'cam-view');
  cv.width = Math.max(1, Math.round(bmp.width * k));
  cv.height = Math.max(1, Math.round(bmp.height * k));
  cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
  bmp.close();
  showPhoto(cv, file);
}
function showPhoto(cv, file) {
  if (S.photo && S.photo !== cv) { S.photo.width = 0; S.photo.height = 0; }
  S.photo = cv; S.file = file || null;
  cv.setAttribute('role', 'img');
  cv.setAttribute('aria-label', 'The photo, on this device only');
  stage.replaceChildren(cv);
  lookAt(cv);
}
async function lookAt(source) {
  const V = Vis();
  if (!V || S.busy) return;
  S.busy = true;
  say(stateEl, 'Looking on this device\u2026');
  try { show(await V.run(S.task, source), !!S.photo); say(stateEl, ''); } catch (e) { say(stateEl, failed(e), 'bad'); paintTask(); } finally { S.busy = false; }
}
async function startLive() {
  const c = Cam();
  if (!c) return;
  clear();
  try { S.view = await c.start({ facing: facingSel.value }); } catch (e) { say(stateEl, failed(e), 'bad'); paintActs(); return; }
  S.view.video.className = 'cam-view';
  stage.replaceChildren(S.view.video);
  say(stateEl, 'The camera is on. Nothing leaves this device while you look.');
  if (STREAMED.includes(S.task) && Vis()) S.stream = Vis().stream(S.task, { frame: () => S.view && S.view.frame() }, (r) => show(r, false));
  paintActs();
}
function stopLive() {
  if (S.stream) { S.stream.stop(); S.stream = null; }
  const c = Cam();
  if (c && c.live()) c.stop('panel');
  if (S.view) { S.view = null; if (!S.photo) stage.replaceChildren(); }
  paintActs();
}
async function readNow() {
  const f = S.view && S.view.frame();
  if (f) await lookAt(f);
}
function takePhoto() {
  const f = S.view && S.view.frame();
  if (!f) return;
  const cv = mk('canvas', 'cam-view');
  cv.width = f.width; cv.height = f.height;
  cv.getContext('2d').drawImage(f, 0, 0);
  stopLive();
  showPhoto(cv, null);
}

// ---- the result, Keep, and the three buttons that send a picture ----------------------------------------------------------
function words(r) {
  if (!r || !r.ok) return 'Nothing could be read from this picture.';
  const d = r.data;
  if (r.task === 'text') return d.text || 'No text found.';
  if (r.task === 'code') return d.codes.length ? d.codes.map((c) => (CODE_WORDS[c.format] || 'Code') + ': ' + c.value).join('\n') : 'No code found.';
  if (r.task === 'objects') return d.objects.length ? d.objects.map((o) => o.label.replace(/_/g, ' ') + ' (' + pct(o.score) + ')').join(', ') : 'None of the 80 everyday things found.';
  if (r.task === 'pose') return d.points.length ? d.points.length + ' body points found.' : 'Nobody in view.';
  return 'Light ' + pct(d.light) + ', sharpness ' + pct(d.sharp) + '.';
}
function hint(r) {
  const q = (r && r.quality) || {};
  if (q.light < 0.2) return ' It looks too dark.';
  return q.sharp < 0.08 ? ' It looks blurred.' : '';
}
const keepBtn = button('Keep', '', keep);
keepActs.append(keepBtn);
function show(r, photo) { // live results arrive several times a second: only the words change
  S.result = r;
  outEl.textContent = words(r) + (r && r.ok ? hint(r) : '');
  keepBtn.hidden = !(r && r.ok);
  if (S.sendFor !== photo) paintSend(photo);
  outBox.hidden = false;
}
function paintSend(photo) {
  S.sendFor = photo;
  const door = Door();
  const noAi = !!(window.JarvisBrainMode && window.JarvisBrainMode.get() === 'none');
  const can = door ? door.canAsk() : { ok: false, why: 'JARVIS is still starting. Try again in a moment.' };
  const acts = [];
  if (photo && door) {
    if (can.ok && !noAi) acts.push(button(ASK_WORDS, '', () => send('ask')));
    acts.push(button('Add to my vault', '', () => send('vault')), button('Attach to my message', '', () => send('attach')));
  }
  askField.hidden = !(photo && can.ok && !noAi);
  sendActs.replaceChildren(...acts);
  seeEl.textContent = photo ? (noAi ? NO_AI_LINE : can.ok ? '' : can.why) : '';
  sentLine();
}
function sentLine() { const d = Door(); sentEl.textContent = d ? d.line() : ''; }
async function keep() {
  if (!S.result || !signedIn()) return;
  try {
    await M.api(P + '/results', { body: S.result });
    say(stateEl, 'Kept. You will find it in Results.', 'ok');
  } catch (e) { say(stateEl, failed(e), 'bad'); }
}
async function pictureFile() {
  if (S.file) return S.file;
  const cv = S.photo;
  const blob = cv ? await new Promise((r) => cv.toBlob(r, 'image/jpeg', 0.9)) : null;
  return blob ? new File([blob], 'camera-photo.jpg', { type: 'image/jpeg' }) : null;
}
async function send(how) { // only from one of the three buttons; the one door counts it
  const door = Door();
  const file = door && signedIn() ? await pictureFile() : null;
  if (!file) return;
  try {
    if (how === 'ask') {
      const ok = await door.ask(file, askIn.value.trim() || ASK_DEFAULT);
      say(stateEl, ok ? 'Sent to the AI with your question.' : 'Nothing was sent: ' + door.canAsk().why, ok ? 'ok' : 'bad');
      if (ok && window.JarvisDeck) window.JarvisDeck.open('chat', { focus: false });
    } else if (how === 'vault') {
      await door.vault(file);
      say(stateEl, 'Sent to your vault as a proposal for you to confirm.', 'ok');
    } else {
      await door.attach([file]);
      say(stateEl, 'Attached to your next message.', 'ok');
      if (window.JarvisDeck) window.JarvisDeck.open('chat', { focus: true });
    }
  } catch (e) { say(stateEl, failed(e), 'bad'); }
  sentLine();
}

// ---- Results ---------------------------------------------------------------------------------------------------------------
const TASK_WORD = Object.fromEntries(TASKS.map(([v, t]) => [v, t]));
async function loadResults() {
  if (!signedIn() || !M) return;
  say(listState, 'Loading\u2026');
  let v = null;
  try { v = await M.api(P + '/results?days=90'); } catch (e) { say(listState, failed(e), 'bad'); return; }
  const rows = (v && Array.isArray(v.results) ? v.results : []).map((k) => {
    const r = mk('div', 'hp-row'), t = mk('div', 'hp-txt'), a = mk('div', 'hp-acts');
    const at = new Date(String(k.kept_at || ''));
    t.append(mk('b', '', (TASK_WORD[k.task] || 'Result') + (isNaN(at) ? '' : ' \u00b7 ' + at.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))),
      mk('small', '', words(k).slice(0, 300)));
    const del = button('Delete', '', () => forget(k.id));
    del.setAttribute('aria-label', 'Delete this kept result');
    a.append(del);
    r.append(t, a);
    return r;
  });
  listEl.replaceChildren(...rows);
  say(listState, v && v.sealed === false ? String(v.detail || '') : rows.length ? '' : 'Nothing kept yet. Press Keep after a look to keep its result.');
}
async function forget(id) {
  try { await M.api(P + '/results/' + encodeURIComponent(id), { method: 'DELETE' }); } catch (e) { say(listState, failed(e), 'bad'); return; }
  loadResults();
}

// ---- the server's word on what can run (after sign-in, when the panel opens) ------------------------------------------------
async function loadStatus() {
  if (!signedIn() || !M || S.status || S.asking) return;
  S.asking = true;
  try { S.status = await M.api(P); } catch (_) { S.status = null; } finally { S.asking = false; }
  paintTask();
}
function hidden() { return !panel || panel.hidden || !panel.getClientRects().length; }
document.addEventListener('jarvis:panel', (e) => {
  const d = (e && e.detail) || {};
  if (d.id === 'camera' && d.open) { loadStatus(); if (S.tab === 'results') loadResults(); }
  setTimeout(() => { if (hidden()) { stopLive(); clear(); } }, 0); // closed, or hidden behind another tab on a phone
});
document.addEventListener('jarvis:ready', () => { if (!hidden()) loadStatus(); });
document.addEventListener('jarvis:camera', () => { if (!(Cam() && Cam().live())) { S.stream = null; S.view = null; } paintActs(); });
document.addEventListener('jarvis:pictures-sent', sentLine);
document.addEventListener('jarvis:brain', () => { if (!outBox.hidden) paintSend(!!S.photo); });
document.addEventListener('jarvis:brainmode', () => { if (!outBox.hidden) paintSend(!!S.photo); });

// ---- a camera button beside the paperclip: it opens this panel, never the camera ------------------------------------------
const clip = document.getElementById('attachBtn');
if (clip && clip.parentNode && !document.getElementById('cameraBtn')) {
  const b = mk('button', 'clip lift');
  b.type = 'button';
  b.id = 'cameraBtn';
  b.title = 'Look with the camera, on this device';
  b.setAttribute('aria-label', 'Open the camera panel');
  const icon = document.querySelector('#dock [data-open="camera"] svg');
  if (icon) b.append(icon.cloneNode(true));
  b.addEventListener('click', () => { if (window.JarvisDeck) window.JarvisDeck.open('camera', { focus: true }); });
  clip.parentNode.insertBefore(b, clip.nextSibling);
}

choose('look');
paintTask();
if (signedIn() && !hidden()) loadStatus();
const api = Object.freeze({ choose, tab: () => S.tab, result: () => S.result });
if (M) M.part('panel', api);
