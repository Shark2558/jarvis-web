// tests/fixtures/r13/d_dom.js -- R13 Part D: a small DOM, a fake camera, fake vision answers and spies, enough to run
// Camera -> Wardrobe (console-wardrobe-scan.js) in Node (vm) by BEHAVIOUR. Used by tests/test_r13_d_scan.py and
// evals/r13/phone.py. Every picture is a drawn scene (a plain surface and rectangles): never a photo.
//   stdin  {source?, view, prints?, vision: {person, face, crop_face, codes, embed, colour, text, delay_ms}, missing: [task],
//           signedIn, noAi, offline, steps: [{op: press|select|type|photo|choose|start|stop|wait|vision|online|text}]}
//   stdout {steps: [{op, text, state}], net: [{method, path, body}], door: [{fn, piece, view, w, h}],
//           runs: [{task, src}], camera: {starts, stops, live}, crops: [{w, h, from}], imported: [spec]}
// The spies prove what left the "phone": every M.api request with its body, every door call with the crop's size,
// and which canvas each vision task ran on (the checks and the crop must share ONE bitmap). ASCII only.
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');

// The scan module imports console-wardrobe-words.js on its first press: a vm script's import() needs Node's
// --experimental-vm-modules, so the harness runs itself again with it when started without (stdin passed on).
if (!process.execArgv.includes('--experimental-vm-modules')) {
  const again = require('child_process').spawnSync(process.execPath, ['--no-warnings', '--experimental-vm-modules', __filename],
    { input: fs.readFileSync(0), maxBuffer: 64 * 1024 * 1024 });
  process.stdout.write(again.stdout || '');
  process.stderr.write(again.stderr || '');
  process.exit(again.status === null ? 1 : again.status);
}
const STATIC = path.join(__dirname, '..', '..', '..', 'src', 'jarvis', 'api', 'static');
// a module's own text, imported as the ES module it is (a data: URL is always ESM)
const asModule = (file) => import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(path.join(STATIC, file), 'utf8')).toString('base64'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const settle = async (n = 30) => { for (let i = 0; i < n; i += 1) await new Promise((r) => setImmediate(r)); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let ids = 0;

// ---- a DOM ------------------------------------------------------------------------------------------------------------
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.attrs = {}; this._text = '';
    this.className = ''; this.hidden = false; this.disabled = false; this.value = ''; this.type = ''; this.dataset = {}; this.listeners = {};
    this.width = 0; this.height = 0; this.uid = 'el' + (ids += 1); this.scene = null;
    const el = this;
    this.classList = { toggle(c, on) { const has = el.className.split(' ').filter(Boolean).filter((x) => x !== c); el.className = (on ? [...has, c] : has).join(' '); } };
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = v == null ? '' : String(v); }
  get childNodes() { return this.children; }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }
  append(...nodes) { nodes.forEach((n) => { if (n.parentNode) n.parentNode.children = n.parentNode.children.filter((c) => c !== n); n.parentNode = this; this.children.push(n); if (this.tagName === 'SELECT' && !this.value && n.value) this.value = n.value; }); }
  replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatch(t) { (this.listeners[t] || []).slice().forEach((fn) => fn({ type: t, target: this })); }
  click() { if (!this.disabled) this.dispatch('click'); }
  all() { return [this, ...this.children.flatMap((c) => c.all())]; }
  getContext() { return ctxOf(this); }
  toBlob(cb, type, q) { cb(Object.assign(new Blob([Buffer.from('R13PLANT' + this.width + 'x' + this.height)], { type }), { w: this.width, h: this.height, q, from: this.uid })); }
}
function text(n) { return n.all().filter((e) => !hiddenIn(e)).map((e) => e._text).filter(Boolean).join(' | '); }
function hiddenIn(e) { for (let n = e; n; n = n.parentNode) if (n.hidden) return true; return false; }

// ---- canvases: a scene (a surface colour and rectangles, normalized) that drawImage carries -----------------------------
const out = { steps: [], net: [], door: [], runs: [], camera: { starts: 0, stops: 0, live: false }, crops: [] };
function ctxOf(c) {
  return {
    drawImage(src, ...a) {
      c.scene = src.scene || null;
      if (a.length === 8) out.crops.push({ w: a[6], h: a[7], from: src.uid, sw: a[2], sh: a[3] });
    },
    getImageData(x, y, w, h) {
      const s = c.scene || { bg: [230, 228, 220], rects: [] }, d = new Uint8ClampedArray(w * h * 4);
      for (let j = 0; j < h; j += 1) for (let i = 0; i < w; i += 1) {
        const u = (i + 0.5) / w, v = (j + 0.5) / h, hit = s.rects.find((r) => u >= r.x && u < r.x + r.w && v >= r.y && v < r.y + r.h);
        d.set([...(hit ? hit.rgb : s.bg), 255], (j * w + i) * 4);
      }
      return { data: d, width: w, height: h };
    },
  };
}
const SCENE = input.scene || { bg: [230, 228, 220], rects: [{ x: 0.1, y: 0.2, w: 0.3, h: 0.6, rgb: [28, 36, 78] }] };

// ---- the page's globals ------------------------------------------------------------------------------------------------
const listeners = {};
const document = {
  createElement: (t) => new El(t),
  addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
  dispatchEvent: (e) => { (listeners[e.type] || []).slice().forEach((fn) => fn(e)); return true; },
};
let vision = Object.assign({ person: false, face: false, codes: [], embed: null, colour: { name: 'navy', share: 0.9 }, text: '', delay_ms: 0 }, input.vision || {});
const missing = new Set(input.missing || []);
let offline = !!input.offline;
const ok = (task, data) => Object.freeze({ task, v: 1, ok: true, data, quality: { light: 0.5, sharp: 0.5 } });
const JarvisVision = {
  async run(task, src) {
    out.runs.push({ task, src: src && src.uid });
    if (vision.delay_ms) await wait(vision.delay_ms);
    if (missing.has(task)) throw new Error('not installed');
    if (task === 'person' || task === 'face') { // crop_face: a small face that only the crop (<= 512 px) shows (H2)
      const f = !!vision[task] || (task === 'face' && !!vision.crop_face && !!src && Math.max(src.width, src.height) <= 512);
      return ok(task, { found: f, count: f ? 1 : 0, boxes: f ? [{ x: 0.4, y: 0.1, w: 0.2, h: 0.3 }] : [] });
    }
    if (task === 'code') return ok(task, { codes: vision.codes.map((v) => ({ format: 'qr_code', value: v })) });
    if (task === 'embed') return vision.embed ? ok(task, { v: vision.embed, dims: 1280, model: 'mnv2-int8-1' }) : Object.freeze({ task, ok: false, data: {} });
    if (task === 'colour') return ok(task, vision.colour);
    if (task === 'text') return ok(task, { text: vision.text, confidence: 0.9 });
    throw new Error('That vision task is not installed.');
  },
  stream(task, opts, onResult) { out.streams = (out.streams || 0) + 1; let on = true; const t = setInterval(() => { if (on) JarvisVision.run(task, opts.frame()).then((r) => on && onResult(r)); }, 20); return { stop() { on = false; clearInterval(t); out.streamStops = (out.streamStops || 0) + 1; } }; },
};
const frameCanvas = Object.assign(new El('canvas'), { width: 1280, height: 720, scene: SCENE });
const JarvisCamera = {
  live: () => out.camera.live, locked: () => false, unlock: () => true,
  async start() { out.camera.starts += 1; out.camera.live = true; return { video: new El('video'), frame: () => (out.camera.live ? frameCanvas : null) }; },
  stop() { out.camera.stops += 1; out.camera.live = false; },
  async photo() { return Object.assign(new Blob([Buffer.from('picked')], { type: 'image/png' }), { name: 'p.png' }); },
};
async function api(p, opts) {
  const o = opts || {};
  out.net.push({ method: o.method || (o.body !== undefined ? 'POST' : 'GET'), path: p, body: o.body === undefined ? '' : JSON.stringify(o.body) });
  if (offline && p.startsWith('/v1/wardrobe/scan')) { const e = new TypeError('Failed to fetch'); throw e; }
  const answers = Object.assign({ '/v1/wardrobe?private=1': input.view, '/v1/wardrobe/fingerprints?model=mnv2-int8-1': { model: 'mnv2-int8-1', items: input.prints || [] },
    '/v1/wardrobe/scan': { applied: 1, duplicates: 0, review: 0, already_done: false, marks: {}, message: 'Saved.' } }, input.answers || {});
  if (p.startsWith('/v1/wardrobe/tools/')) return { status: 'executed', message: 'Done, Sir.', result: p.endsWith('wardrobe_add') ? { piece: 'wi_0000000000ff' } : {} };
  if (p === '/v1/wardrobe/fingerprints' && o.body) return { piece: o.body.piece, view: o.body.view, model: o.body.model };
  const a = answers[p];
  if (a === undefined) { const e = new Error('Not found.'); e.status = 404; throw e; }
  return JSON.parse(JSON.stringify(a));
}
const door = {
  line: () => 'Pictures sent from this device today: ' + out.door.length,
  async wardrobe(blob, meta) { out.door.push({ fn: 'wardrobe', piece: meta.piece, view: meta.view, w: blob.w, h: blob.h, from: blob.from }); return { photo: 'wh_00000000000a' }; },
  async tag(blob, meta) { out.door.push({ fn: 'tag', piece: meta.piece, w: blob.w, h: blob.h, from: blob.from }); return { piece: meta.piece, suggestion: { type: 'shirt', colour: 'navy' } }; },
};
let mode = null;
const host = new El('div');
const P = {
  mk: (t, c, x) => { const n = new El(t); if (c) n.className = c; if (x) n.textContent = x; return n; },
  button: (t, c, fn) => { const b = new El('button'); b.className = 'btn sact' + (c ? ' ' + c : ''); b.textContent = t; b.addEventListener('click', fn); return b; },
  field: (label, control) => { const l = new El('label'); const s = new El('span'); s.textContent = label; l.append(s, control); return l; },
  say: (el, t, kind) => { el.className = 'snote' + (kind ? ' ' + kind : ''); el.textContent = t || ''; },
  signedIn: () => input.signedIn !== false,
};
const window = {
  JarvisMobile: { mk: P.mk, api, parts: { send: door } },
  JarvisVision, JarvisCamera,
  JarvisCameraModes: { register(id, m) { if (id !== 'wardrobe' || mode) return false; mode = m; m.mount(host, P); return true; } },
  JarvisBrainMode: { get: () => (input.noAi ? 'none' : 'ai') },
};
const ctx = {
  window, document, navigator: { onLine: true }, crypto: globalThis.crypto, atob, btoa, Blob, File, setTimeout, clearTimeout,
  setInterval, clearInterval, setImmediate, console, Promise, Map, Set, Math, Date, JSON, Number, String, Array, Object, Uint8Array,
  Uint8ClampedArray, Float64Array, Float32Array, RegExp, Error, TypeError, Buffer,
  createImageBitmap: async (f) => ({ width: 1600, height: 1200, scene: SCENE, uid: 'bitmap', close() {} }),
};
ctx.globalThis = ctx;
const source = input.source || fs.readFileSync(path.join(STATIC, 'console-wardrobe-scan.js'), 'utf8');
const imported = []; // which modules the scan module imported, in order
async function importer(spec) { // only its own sibling: anything else is refused
  imported.push(spec);
  if (input.noWords || spec !== './console-wardrobe-words.js') throw new Error('Failed to fetch dynamically imported module: ' + spec);
  return asModule('console-wardrobe-words.js');
}

function find(label, exact = true) {
  return host.all().find((e) => e.tagName === 'BUTTON' && !hiddenIn(e) && !e.disabled && (exact ? e.textContent === label : e.textContent.startsWith(label)));
}
async function step(s) {
  const r = { op: s.op };
  if (s.op === 'press' || s.op === 'pressStart') { const b = find(s.label, s.op === 'press'); r.found = !!b; if (b) b.click(); if (!s.now) await settle(); }
  if (s.op === 'select') { const l = host.all().find((e) => e.tagName === 'LABEL' && e.children[0] && e.children[0].textContent === s.label); const sel = l && l.children[1]; r.found = !!sel; if (sel) { sel.value = s.value; sel.dispatch('change'); } await settle(); }
  if (s.op === 'type') { const i = host.all().find((e) => e.tagName === 'INPUT'); r.found = !!i; if (i) { i.value = s.value; i.dispatch('input'); } await settle(); }
  if (s.op === 'stop') { mode.stop(); await settle(); }
  if (s.op === 'wait') await wait(s.ms || 50);
  if (s.op === 'settle') await settle(s.n || 30);
  if (s.op === 'vision') vision = Object.assign({}, vision, s.vision);
  if (s.op === 'online') offline = !!s.offline; // {op: 'online'} is back online; {offline: true} goes off
  r.text = text(host);
  r.buttons = host.all().filter((e) => e.tagName === 'BUTTON' && !hiddenIn(e)).map((e) => e.textContent);
  out.steps.push(r);
}

(async () => {
  vm.createContext(ctx);
  vm.runInContext(source, ctx, { filename: 'console-wardrobe-scan.js', importModuleDynamically: importer });
  for (const s of input.steps || []) await step(s);
  await settle();
  out.final = text(host);
  out.imported = imported;
  process.stdout.write(JSON.stringify(out), () => process.exit(0)); // a camera left on keeps its timer: end here
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); process.exitCode = 1; });
