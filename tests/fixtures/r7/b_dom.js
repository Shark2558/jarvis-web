// tests/fixtures/r7/b_dom.js -- R7 Part B: a small DOM, a fake camera and a network spy, enough to run the console's
// camera door (console-camera.js), the vision engine (console-vision.js) and the Camera panel (console-camera-panel.js)
// in Node (vm), with R5's real voice router (console-voice-commands.js). Used by tests/test_r7_b_dom.py and
// evals/r7/vision.py: behavioural checks, not matches on the source.
// The fake camera's every frame is a PLANTED PIXEL PATTERN (the bytes "R7PLANT" and 0xFF, repeated); the spy records
// every request (JarvisConsole.api, JarvisMobile.api, fetch, XMLHttpRequest, sendBeacon, WebSocket) and every call of
// the one picture door (parts.send), so a scenario can prove that no request body carries a picture.
// Input on stdin: {script, files: {name: source}, ...}. Output on stdout: JSON. ASCII only.
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');

const PLANT = [0x52, 0x37, 0x50, 0x4c, 0x41, 0x4e, 0x54, 0xff];
const W = 64, H = 48;
const settle = () => new Promise((r) => setTimeout(r, 0));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- a DOM ----------------------------------------------------------------------------------------------------------------
class Ev { constructor(type, init) { this.type = type; this.detail = init && init.detail; this.defaultPrevented = false; this.isTrusted = !!(init && init.trusted); this.key = init && init.key; this.storageArea = init && init.storageArea; } preventDefault() { this.defaultPrevented = true; } }
class Target {
  constructor() { this.listeners = {}; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); }
  dispatchEvent(ev) { (this.listeners[ev.type] || []).slice().forEach((fn) => fn(ev)); return !ev.defaultPrevented; }
}
class El extends Target {
  constructor(tag) {
    super();
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.attrs = {}; this._text = '';
    this.className = ''; this.id = ''; this.hidden = false; this.disabled = false; this.value = ''; this.type = ''; this.style = {};
    this.width = 0; this.height = 0; this.files = null;
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = v == null ? '' : String(v); }
  get firstChild() { return this.children[0] || null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; return p.children[p.children.indexOf(this) + 1] || null; }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  append(...nodes) { nodes.forEach((n) => this.appendChild(typeof n === 'string' ? text(n) : n)); }
  appendChild(n) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; this.children.push(n); if (this.tagName === 'SELECT' && !this.value && n.value) this.value = n.value; return n; }
  insertBefore(n, ref) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; this.children.splice(i < 0 ? this.children.length : i, 0, n); return n; }
  removeChild(n) { this.children = this.children.filter((c) => c !== n); n.parentNode = null; return n; }
  replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  click() { if (this.disabled) return; const ev = new Ev('click'); ev.target = this; withTap(() => this.dispatchEvent(ev)); if (this.tagName === 'INPUT' && this.type === 'file') pickers.push(this); }
  focus() { doc.activeElement = this; }
  cloneNode() { return new El(this.tagName); }
  getClientRects() { for (let n = this; n; n = n.parentNode) if (n.hidden) return []; return [{}]; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  matches(sel) { if (sel.startsWith('#')) return this.id === sel.slice(1); if (sel.startsWith('.')) return String(this.className).split(/\s+/).includes(sel.slice(1)); return this.tagName === sel.toUpperCase(); }
  querySelectorAll(sel) { return this.all().filter((n) => n.matches(sel)); }
  querySelector(sel) { return sel.includes(' ') ? null : this.querySelectorAll(sel)[0] || null; }
  getContext() { return this.tagName === 'CANVAS' ? ctx2d(this) : null; }
  toBlob(cb, type) { setTimeout(() => cb(new Blob([Buffer.from(this.px || [])], { type: type || 'image/png' })), 0); }
  play() { return Promise.resolve(); }
  pause() {}
  get videoWidth() { return this.srcObject ? W : 0; }
  get videoHeight() { return this.srcObject ? H : 0; }
}
const text = (t) => { const n = new El('#text'); n._text = String(t); return n; };
function pattern(w, h) { const d = new Uint8ClampedArray(w * h * 4); for (let i = 0; i < d.length; i += 1) d[i] = PLANT[i % PLANT.length]; return d; }
function ctx2d(c) {
  return {
    drawImage(src) { c.px = src && (src.px || (src.srcObject ? pattern(W, H) : null)); },
    getImageData(x, y, w, h) { return { width: w, height: h, data: c.px && c.px.length === w * h * 4 ? c.px : pattern(w, h) }; },
    clearRect() {},
  };
}

const doc = new El('#document');
doc.head = doc.appendChild(new El('head'));
doc.body = doc.appendChild(new El('body'));
doc.readyState = 'complete';
doc.hidden = false;
doc.createElement = (tag) => new El(tag);
doc.createTextNode = (t) => text(t);
doc.getElementById = (id) => doc.all().find((n) => n.id === id) || null;
doc.querySelector = () => null;
const pickers = [];

// ---- the browser around it: storage, activation, the camera, the network spy ---------------------------------------
const store = new Map();
const localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
let tap = false;
function withTap(fn) { const was = tap; tap = true; try { return fn(); } finally { setTimeout(() => { tap = was; }, 0); } }
const cam = { asked: 0, tracks: [] };
const net = [];
const door = [];
function body(b) {
  if (b === undefined || b === null) return '';
  if (typeof b === 'string') return b;
  if (b instanceof Blob || ArrayBuffer.isView(b) || b instanceof ArrayBuffer) return '[binary ' + (b.size || b.byteLength || 0) + ']';
  try { return JSON.stringify(b); } catch (_) { return String(b); }
}
function spy(kind, path, opts) { net.push({ kind, path: String(path), method: (opts && opts.method) || (opts && opts.body !== undefined ? 'POST' : 'GET'), body: body(opts && opts.body), binary: !!(opts && opts.body && typeof opts.body === 'object' && (opts.body instanceof Blob || ArrayBuffer.isView(opts.body))) }); }

function track() {
  const t = new Target();
  t.readyState = 'live'; t.kind = 'video';
  t.stop = () => { t.readyState = 'ended'; };
  cam.tracks.push(t);
  return t;
}
function stream() { const t = track(); return { getTracks: () => [t], px: pattern(W, H) }; }

function sandbox(input) {
  const win = new Target();
  const answers = Object.assign({ '/v1/vision': { part: 'vision', ready: 'ready', sealed: true, keep_days: 90,
    tasks: { text: { installed: true, why: '' }, code: { installed: true, why: '' }, quality: { installed: true, why: '' },
      objects: { installed: false, why: 'not installed' }, pose: { installed: false, why: 'not installed' } } },
  '/v1/vision/results': { kept: { id: 'vr_000000000001' } }, '/v1/vision/results?days=90': { sealed: true, results: [] } }, input.answers || {});
  const signed = { on: input.signed !== false };
  const api = (p, opts) => { spy('api', p, opts); return Promise.resolve(answers[p] || {}); };
  const sendDoor = {
    canAsk: () => (input.sees ? { ok: true, why: '' } : { ok: false, why: 'The brain answering now can’t see pictures.' }),
    ask: (f, t) => { door.push({ how: 'ask', name: f && f.name, text: t }); return Promise.resolve(true); },
    attach: (fs) => { door.push({ how: 'attach', n: fs.length }); return Promise.resolve(fs.length); },
    vault: (f) => { door.push({ how: 'vault', name: f && f.name }); return Promise.resolve(null); },
    sentToday: () => door.length, line: () => 'Pictures sent from this device today: ' + door.length,
  };
  const parts = { send: sendDoor };
  const s = {
    document: doc, localStorage, console, URL, Blob, File, CustomEvent: Ev, Date, Math, JSON, Promise, Object, Array, Set, Map,
    Uint8Array, Uint8ClampedArray, Float32Array, Number, String, Error, Buffer, isNaN, encodeURIComponent,
    setTimeout, clearTimeout, setInterval, clearInterval, performance: { now: () => Date.now() },
    addEventListener: (t, f) => win.addEventListener(t, f), dispatchEvent: (e) => win.dispatchEvent(e),
    navigator: {
      userAgent: 'Mozilla/5.0 (Linux; Android 16)',
      get userActivation() { return { isActive: tap }; },
      mediaDevices: { getUserMedia: (c) => { cam.asked += 1; cam.constraints = c; return Promise.resolve(stream()); } },
      sendBeacon: (p, b) => { spy('beacon', p, { body: b, method: 'POST' }); return true; },
    },
    fetch: (p, o) => { spy('fetch', p, o); return Promise.resolve({ ok: false, status: 404, arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)) }); },
    XMLHttpRequest: function XHR() { this.open = (m, p) => { this.m = m; this.p = p; }; this.send = (b) => spy('xhr', this.p, { body: b, method: this.m }); },
    WebSocket: function WS(p) { spy('websocket', p, {}); this.send = (b) => spy('websocket', p, { body: b, method: 'SEND' }); },
    createImageBitmap: (src) => Promise.resolve({ width: W, height: H, px: pattern(W, H), close() {} }),
    JarvisConsole: { ready: () => (signed.on ? { returning: true } : null), api, brain: () => ({ sees: !!input.sees }) },
    JarvisMobile: { mk: (tag, cls, t) => { const n = new El(tag); if (cls) n.className = cls; if (t !== undefined) n.textContent = t; return n; }, api, parts,
      part: (name, obj) => { if (!parts[name]) parts[name] = obj; return obj; } },
    JarvisChat: { honorific: () => 'Sir', send: (t) => { spy('chat', 'JarvisChat.send', { body: t, method: 'SEND' }); return Promise.resolve(true); } },
    JarvisDeck: { open: () => {} },
  };
  s.window = s; s.self = s; s.globalThis = s;
  vm.createContext(s);
  return { s, win, signed };
}
function load(ctx, name, src) { vm.runInContext("'use strict';(function(){\n" + src + '\n})();', ctx, { filename: name }); }
function voice() { return fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', 'jarvis', 'api', 'static', 'console-voice-commands.js'), 'utf8'); }
function boot(input, names) {
  const box = sandbox(input);
  vm.runInContext(voice(), box.s, { filename: 'console-voice-commands.js' });
  for (const n of names) load(box.s, n, input.files[n]);
  return box;
}
function camState(s) {
  const C = s.JarvisCamera, chip = doc.all().find((n) => String(n.className).includes('cam-chip'));
  return { live: C.live(), locked: C.locked(), chip: !!(chip && !chip.hidden && chip.parentNode), asked: cam.asked,
    liveTracks: cam.tracks.filter((t) => t.readyState === 'live').length, stored: localStorage.getItem('jarvis_cam_off_v1') };
}

// ---- scenarios -------------------------------------------------------------------------------------------------------------
async function camera(input) { // steps: [{op, ...}] -> the state after each
  const { s, win } = boot(input, ['console-camera.js']);
  const C = s.JarvisCamera, out = [];
  for (const st of input.steps || []) {
    let ok = null, code = '';
    try {
      if (st.op === 'lock') C.lock(st.by || 'button');
      else if (st.op === 'unlock') ok = st.tap ? withTap(() => C.unlock('panel')) : C.unlock('panel');
      else if (st.op === 'start') { const p = st.tap ? withTap(() => C.start({})) : C.start({}); await p; ok = true; }
      else if (st.op === 'hide') { doc.hidden = true; doc.dispatchEvent(new Ev('visibilitychange')); doc.hidden = false; }
      else if (st.op === 'chipStop') doc.all().find((n) => String(n.className).includes('cam-chip')).click();
      else if (st.op === 'voice') { const r = await s.JarvisVoiceCommands.handle(st.text, { source: 'voice', state: 'listening' }); ok = r.handled; code = (r.result && r.result.say) || r.id || ''; }
      else if (st.op === 'storage') { store.set('jarvis_cam_off_v1', st.value); if (st.value === null) store.delete('jarvis_cam_off_v1'); win.dispatchEvent(new Ev('storage', { trusted: st.trusted, key: 'jarvis_cam_off_v1', storageArea: localStorage })); }
      else if (st.op === 'frame') ok = !!C.frame();
    } catch (e) { ok = false; code = e.code || String(e.message); }
    await settle();
    out.push(Object.assign({ op: st.op, ok, code }, camState(s)));
  }
  return { steps: out };
}

function kinds(v, seen) { // every value's kind in what a use case received, deeply
  if (v === null || typeof v !== 'object') return [typeof v];
  const tag = Object.prototype.toString.call(v);
  const here = [tag + (Object.isFrozen(v) ? ':frozen' : ':open')];
  return here.concat(...Object.keys(v).map((k) => kinds(v[k], seen)));
}
async function engine(input) {
  const { s } = boot(input, ['console-vision.js']);
  const V = s.JarvisVision, got = [];
  V.register({ id: 'probe', v: 1, input: 'both', run: () => ({ data: input.probe, quality: { light: 0.5, sharp: 0.5 } }), check: (d) => !!d && d.n === 1 });
  V.use({ id: 'watcher', tasks: ['probe', 'quality'], onResult: (r, st) => { got.push({ keys: Object.keys(r).sort(), kinds: kinds(r), r: JSON.parse(JSON.stringify(r)) }); return st; } });
  const canvas = new El('canvas'); canvas.width = W; canvas.height = H; canvas.px = pattern(W, H);
  const results = [];
  for (const id of ['probe', 'quality']) results.push(JSON.parse(JSON.stringify(await V.run(id, canvas))));
  return { tasks: V.tasks(), results, got };
}

async function look(input) { // the Camera panel end to end, with the spy
  const files = ['console-vision.js', 'console-camera.js', 'console-camera-panel.js'];
  const panel = doc.body.appendChild(new El('section')); panel.id = 'p-camera';
  const pbody = panel.appendChild(new El('div')); pbody.id = 'cameraBody';
  const metaEl = panel.appendChild(new El('span')); metaEl.id = 'cameraMeta';
  const form = doc.body.appendChild(new El('form')); const clip = form.appendChild(new El('button')); clip.id = 'attachBtn';
  const { s, signed } = boot(input, files);
  const fire = (name, detail) => doc.dispatchEvent(new Ev(name, { detail }));
  const press = (label) => { const b = doc.all().find((n) => n.tagName === 'BUTTON' && n.textContent === label && !n.hidden && n.getClientRects().length); if (!b) throw new Error('no button ' + label); b.click(); return b; };
  const marks = {};
  const mark = (name) => { marks[name] = { net: net.length, door: door.length }; };
  for (const st of input.steps || []) {
    if (st.op === 'open') fire('jarvis:panel', { id: 'camera', open: true });
    else if (st.op === 'signin') { signed.on = true; fire('jarvis:ready', { returning: true }); }
    else if (st.op === 'task') { const sel = doc.getElementById('camTask'); sel.value = st.task; sel.dispatchEvent(new Ev('change')); }
    else if (st.op === 'press') press(st.label);
    else if (st.op === 'pick') { const p = pickers.pop(); p.files = [new File([Buffer.from(pattern(W, H))], 'label.png', { type: 'image/png' })]; p.dispatchEvent(new Ev('change')); }
    else if (st.op === 'wait') await wait(st.ms || 50);
    else if (st.op === 'mark') mark(st.name);
    else if (st.op === 'close') { panel.hidden = true; fire('jarvis:panel', { id: 'camera', open: false }); }
    for (let i = 0; i < 6; i += 1) await settle();
  }
  const out = doc.all().find((n) => n.className === 'cam-out');
  const buttons = doc.all().filter((n) => n.tagName === 'BUTTON' && !n.hidden && n.getClientRects().length).map((b) => b.textContent);
  const sel = doc.getElementById('camTask');
  const disabled = doc.all().filter((n) => n.tagName === 'BUTTON' && n.disabled).map((b) => b.textContent);
  const notes = doc.all().filter((n) => n.className === 'sfine' && n.textContent).map((n) => n.textContent);
  return { net, door, marks, cam: camState(s), out: out ? out.textContent : '', buttons, disabled, notes, meta: metaEl.textContent,
    options: sel ? sel.options.map((o) => o.textContent) : [],
    sent: (doc.all().find((n) => String(n.textContent).startsWith('Pictures sent')) || { textContent: '' }).textContent };
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const run = { camera, engine, look }[input.script];
  if (!run) throw new Error('unknown scenario ' + input.script);
  const res = await run(input);
  res.plant = { ascii: 'R7PLANT', base64: Buffer.from(PLANT.concat(PLANT)).toString('base64').slice(0, 10), numbers: PLANT.slice(0, 7).join(',') };
  process.stdout.write(JSON.stringify(res));
  process.exit(0); // the camera's idle watch keeps a timer: the scenario is over
}
main().catch((e) => { process.stdout.write(JSON.stringify({ crashed: String((e && e.stack) || e) })); process.exit(0); });
