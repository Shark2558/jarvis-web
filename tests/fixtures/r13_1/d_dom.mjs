// tests/fixtures/r13_1/d_dom.mjs -- R13.1 Part D: a small DOM and the console's parts, enough to run Part D's REAL
// modules (console-tryon*.js) in Node by BEHAVIOUR against D's fake server (tests/r131_fakes_d.py) over HTTP, with the
// contract-keeping fake engine (d_engine.mjs) as console-tryon-3d.js. Used by evals/r13_1/console.py (no browser: CI's
// plain pytest runs that runner). Everything here is a test stand-in; nothing is shipped.
//   argv[2]  {dir, base, token, scenario, how, control}   dir holds the modules to run (copies, a control may change one)
//   stdout   "R131D-DOM " + {checks: {name: bool}, seen: {...}}
// The spies: every api() call with its body, every door call, the engine's own record (window.__r131d), ctx.tool calls.
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const IN = JSON.parse(process.argv[2]);
const realNow = Date.now.bind(Date);
let skew = 0;
Date.now = () => realNow() + skew; // the 10 s first render is reached by moving the clock, not by waiting
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(check, ms = 8000) { const end = realNow() + ms; while (realNow() < end) { if (check()) return true; await wait(15); } return !!check(); }

// ---- a DOM ------------------------------------------------------------------------------------------------------------
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.attrs = {}; this._text = '';
    this.className = ''; this.hidden = false; this.dataset = {}; this.style = {}; this.on = {}; this.value = ''; this.checked = false;
    const el = this;
    this.classList = { add: (...c) => { el.className = [...new Set(el.className.split(' ').concat(c).filter(Boolean))].join(' '); },
      remove: (c) => { el.className = el.className.split(' ').filter((x) => x && x !== c).join(' '); },
      contains: (c) => el.className.split(' ').includes(c) };
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = v == null ? '' : String(v); }
  get childElementCount() { return this.children.length; }
  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === DOC.documentElement; }
  get offsetParent() { if (!this.isConnected) return null; for (let n = this; n; n = n.parentNode) if (n.hidden) return null; return this.parentNode; }
  append(...nodes) { nodes.forEach((n) => { if (typeof n === 'string') { this._text += n; return; } if (n.parentNode) n.remove(); n.parentNode = this; this.children.push(n); }); }
  prepend(...nodes) { const rest = this.children; this.children = []; this.append(...nodes); this.children.push(...rest); }
  replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); this.parentNode = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'open') this.open = true; }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn, o) { (this.on[t] = this.on[t] || []).push({ fn, once: !!(o && o.once) }); }
  removeEventListener(t, fn) { this.on[t] = (this.on[t] || []).filter((x) => x.fn !== fn); }
  dispatchEvent(e) { const ev = typeof e === 'string' ? { type: e } : e; ev.target = ev.target || this; ev.preventDefault = ev.preventDefault || (() => {});
    const list = (this.on[ev.type] || []).slice(); this.on[ev.type] = (this.on[ev.type] || []).filter((x) => !x.once); list.forEach((x) => x.fn(ev)); return true; }
  click() { this.dispatchEvent({ type: 'click' }); }
  focus() {} scrollIntoView() {}
  all() { return [this, ...this.children.flatMap((c) => c.all())]; }
  querySelector(sel) { return this.all().slice(1).find((e) => matches(e, sel)) || null; }
  querySelectorAll(sel) { return this.all().slice(1).filter((e) => matches(e, sel)); }
  closest(sel) { for (let n = this; n; n = n.parentNode) if (matches(n, sel)) return n; return null; }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  showModal() { this.open = true; } // a <dialog>'s close event is queued, as the browser does
  close() { if (!this.open) return; this.open = false; setTimeout(() => this.dispatchEvent({ type: 'close' }), 0); }
  getContext() { return { fillRect() {}, fillText() {}, drawImage() {}, set fillStyle(_) {}, set font(_) {} }; }
  toBlob(cb, type) { cb(new Blob([Buffer.from('a PNG drawn by the fake engine')], { type })); }
}
function matches(e, sel) {
  if (!(e instanceof El)) return false;
  if (sel.startsWith('.')) return sel.slice(1).split('.').every((c) => e.classList.contains(c));
  if (sel.startsWith('#')) return e.attrs.id === sel.slice(1) || e.id === sel.slice(1);
  return e.tagName === sel.toUpperCase();
}
const DOC = { documentElement: new El('html'), hidden: false, on: {} };
DOC.body = new El('body'); DOC.documentElement.append(DOC.body);
Object.assign(DOC, {
  createElement: (t) => new El(t), createElementNS: (_, t) => new El(t),
  addEventListener: El.prototype.addEventListener, dispatchEvent: El.prototype.dispatchEvent,
  getElementById: (id) => DOC.documentElement.all().find((e) => e.id === id) || null,
  querySelector: (s) => DOC.documentElement.querySelector(s), contains: (n) => DOC.documentElement.contains(n),
});
globalThis.document = DOC;
globalThis.Node = El;
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.MutationObserver = class { observe() {} disconnect() {} };
globalThis.FileReader = class { readAsDataURL(b) { b.arrayBuffer().then((ab) => { this.result = 'data:' + (b.type || 'application/octet-stream') + ';base64,' + Buffer.from(ab).toString('base64'); if (this.onload) this.onload(); }, () => { if (this.onerror) this.onerror(); }); } };
globalThis.CustomEvent = class { constructor(type, o) { this.type = type; this.detail = o && o.detail; } };

// ---- the console's parts (the frame's builders as console-helpers.js makes them; the transport as console.js) ---------------
const seen = { api: [], door: [], tools: [] };
const mk = (tag, cls, text) => { const n = new El(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().slice(0, max) : '');
const H = {
  mk, txt, empty: (t) => mk('p', 'sfine hp-empty', txt(t, 240)),
  row(title, sub, actions) { const r = mk('div', 'hp-row'), t = mk('div', 'hp-txt'); t.append(mk('b', '', txt(title, 120))); if (sub) t.append(mk('small', '', txt(sub, 200)));
    r.append(t); const a = mk('div', 'hp-acts'); (actions || []).forEach((x) => a.append(x)); if (a.children.length) r.append(a); return r; },
  toggle(label, on, change) { const b = mk('button', 'bsw'); b.type = 'button'; b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.setAttribute('aria-label', label);
    b.append(mk('span', 'st', on ? 'On' : 'Off')); b.addEventListener('click', () => change(b.getAttribute('aria-pressed') !== 'true')); return b; },
  note(el, kind, text) { if (!el) return; el.className = 'sfine hp-note' + (kind ? ' ' + kind : ''); el.textContent = txt(text, 240); },
  section(title) { const s = mk('section', 'hp-sec'); s.append(mk('h3', 'hp-h', title)); return s; },
};
async function api(p, opts = {}) {
  const headers = { 'X-Requested-With': 'JARVIS', Authorization: 'Bearer ' + IN.token };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  seen.api.push({ method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), path: p, body: opts.body === undefined ? null : opts.body });
  const r = await fetch(IN.base + p, { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) { let j = {}; try { j = await r.json(); } catch (_) {} const e = new Error(typeof j.detail === 'string' ? j.detail : r.statusText); e.status = r.status; if (j.error) e.code = j.error; throw e; }
  return r.status === 204 ? null : r.json();
}
const call = (fn, ...args) => { seen.door.push({ fn, args }); };
const door = { // the door with INTEGRATION-D's three lines for I1 (make, keep, forget, garments); thumb reads a crop back
  thumb: async (id) => { call('thumb', id); const r = await fetch(IN.base + '/v1/wardrobe/photos/' + id, { headers: { Authorization: 'Bearer ' + IN.token } });
    if (!r.ok) throw new Error('no photo'); return 'data:image/png;base64,' + Buffer.from(await r.arrayBuffer()).toString('base64'); },
  make: (b) => { call('make', b); return api('/v1/seeme/pictures', { body: b }); }, picture: async (id) => { call('picture', id); return 'data:image/png;base64,AAAA'; },
  keep: (id, on) => { call('keep', id, on); return api('/v1/seeme/pictures/' + id + '/keep', { body: { keep: on === true } }); },
  forget: (id) => { call('forget', id); return api('/v1/seeme/' + (id === 'photo' ? 'photo' : (id[1] === 'p' ? 'pictures/' : 'garments/') + id), { method: 'DELETE' }); },
  garments: () => { call('garments'); return api('/v1/seeme/garments'); }, myPhoto: async () => 'data:image/jpeg;base64,AAAA',
};
globalThis.window = { JarvisHelpers: H, JarvisConsole: { api }, JarvisMobile: { parts: { send: door } }, JarvisChat: { session: () => null },
  JarvisFX: { motion: () => 'full', tokens: () => ({}) }, addEventListener() {}, __glFail: IN.how && IN.how !== 'stub' ? IN.how : undefined };
const ctx = { H, priv: false, nameOf: () => 'A piece', show() {}, tool: async (name, args) => { seen.tools.push({ name, args }); } };

// ---- finding and pressing, as he would --------------------------------------------------------------------------------
const within = (root) => root.all();
const buttonIn = (root, label) => within(root).find((e) => e.tagName === 'BUTTON' && e.textContent === label && e.getAttribute('aria-disabled') !== 'true');
async function press(root, label) { // the words on screen say why, when a button isn't there
  if (!(await until(() => buttonIn(root, label)))) throw new Error('no button: ' + label + ' in: ' + root.textContent.slice(0, 400));
  buttonIn(root, label).click();
}
const rowOf = (root, slot, n = 0) => within(root).find((e) => e.classList.contains('tr-col') && e.dataset.look === String(n))?.all().find((e) => e.classList.contains('tr-item') && e.dataset.slot === slot);
const refsAfter = (row) => (row ? row.parentNode.children[row.parentNode.children.indexOf(row) + 1] : null);
const view = (root) => within(root).find((e) => e.classList.contains('tr-view'));
const rec = () => window.__r131d || { shown: [], live: 0, mounts: 0, snapshots: [], views: [] };
const pieces = (fig) => { const o = {}; ((fig && fig.look.slots) || []).forEach((s) => { if (!s.private) (o[s.slot] = o[s.slot] || []).push(s.piece); }); return o; };
const lastFig = (i = 0) => (rec().shown.length ? rec().shown[rec().shown.length - 1].figures[i] : null);
const looks = () => seen.api.filter((c) => c.path.startsWith('/v1/tryon/look'));

const T = IN.t; // the pilot's ids (r131_fakes.T) and the card (r131_fakes_d.CARD), from the eval
async function section() {
  const m = await import(pathToFileURL(path.join(IN.dir, 'console-tryon.js')).href);
  const host = mk('section', 'hp-sec'); DOC.body.append(host);
  m.mount(host, ctx);
  await until(() => view(host) && view(host).dataset.mode && (rec().shown.length || view(host).dataset.mode === 'list'));
  return { m, host };
}
async function card(list) {
  await import(pathToFileURL(path.join(IN.dir, 'console-tryon-card.js')).href);
  const row = mk('div', 'row jarvis'); DOC.body.append(row);
  window.JarvisTryOnCard.cards(row, list);
  await until(() => view(row) && (rec().shown.length || view(row).dataset.mode === 'list'), 4000);
  return row;
}

// ---- the cases ---------------------------------------------------------------------------------------------------------------
const SCENARIOS = {
  async row388() { // the reply's card opens by itself (no press), dressed in exactly its pieces; its private slot covered
    const row = await card(IN.control === 'row388' ? [] : [{ kind: 'places' }, IN.card]);
    await until(() => rec().live === 1 && rec().shown.length > 0);
    const want = {}; IN.card.slots.filter((s) => !s.private).forEach((s) => { want[s.slot] = s.pieces; });
    const base = ((lastFig() && lastFig().look.slots) || []).filter((s) => s.slot === 'base');
    return { opened: rec().mounts === 1 && rec().live === 1, pieces: JSON.stringify(pieces(lastFig())) === JSON.stringify(want),
      covered: JSON.stringify(base) === JSON.stringify([{ slot: 'base', private: true }]) && row.textContent.includes(IN.covered),
      by_ids: looks().length > 0 && looks().every((c) => c.path.includes('pieces=')), no_label: !/vest/i.test(row.textContent) };
  },
  async row388_none() { // a reply without a try-on card draws nothing and asks for nothing
    const row = await card([{ kind: 'places' }]); window.JarvisTryOnCard.cards(row, []); await wait(200);
    return { nothing_drawn: row.children.length === 0 && !window.__r131d, nothing_asked: seen.api.length === 0 };
  },
  async row388_nogl() { // with no WebGL2 the card is the checklist of the same pieces
    const row = await card([IN.card]);
    await until(() => view(row) && view(row).dataset.mode === 'list' && within(row).some((e) => e.dataset.piece));
    const got = {}; within(row).filter((e) => e.classList.contains('tr-item') && e.dataset.piece).forEach((e) => { (got[e.dataset.slot] = got[e.dataset.slot] || []).push(e.dataset.piece); });
    const want = {}; IN.card.slots.filter((s) => !s.private).forEach((s) => { want[s.slot] = s.pieces; });
    return { checklist: view(row).dataset.mode === 'list', same_pieces: JSON.stringify(got) === JSON.stringify(want), covered: row.textContent.includes(IN.covered), no_stage: !window.__r131d || rec().mounts === 0 };
  },
  async avt15() { // a failed render leaves a checklist that can change a piece and confirm through R13's tools
    const { host } = await section();
    if (IN.how === 'timeout') { await until(() => rec().mounts === 1); skew = 10500; }
    await until(() => view(host).dataset.mode === 'list', 6000);
    const outer = rowOf(host, 'outer'), top = rowOf(host, 'top');
    const out = { checklist: view(host).dataset.mode === 'list', why: view(host).dataset.why === (IN.how === 'stub' ? 'engine' : IN.how),
      readiness: !!outer && outer.textContent.includes('charcoal blazer') && outer.textContent.includes('Ready'),
      image_card: !!refsAfter(top) && within(refsAfter(top)).some((e) => e.tagName === 'IMG' && e.dataset.photo) };
    await press(rowOf(host, 'watch'), 'Change'); await press(host, 'brown watch · Ready');
    await until(() => rowOf(host, 'watch') && rowOf(host, 'watch').dataset.piece === T.watch2);
    out.changed = !!rowOf(host, 'watch') && rowOf(host, 'watch').dataset.piece === T.watch2;
    await press(host, 'Wearing it'); await until(() => seen.tools.length > 0);
    const confirm = seen.api.filter((c) => c.path === '/v1/tryon/confirm');
    out.confirmed_first = confirm.length === 1 && confirm[0].body.slots.some((s) => s.slot === 'watch' && s.piece === T.watch2);
    out.worn = JSON.stringify(seen.tools) === JSON.stringify([{ name: 'wear_log', args: { action: 'start', plan: IN.plan } }]);
    return out;
  },
  async avt06() { // the watch swap changes the wrist piece and the slot's thumbnail to W2's
    const { host } = await section();
    const img = () => within(refsAfter(rowOf(host, 'watch')) || mk('div')).find((e) => e.tagName === 'IMG');
    const before = img() && img().dataset.photo;
    await press(rowOf(host, 'watch'), 'Change'); await press(host, 'brown watch · Ready');
    await until(() => rowOf(host, 'watch') && rowOf(host, 'watch').dataset.piece === T.watch2);
    const w = ((lastFig() && lastFig().look.slots) || []).find((s) => s.slot === 'watch') || {};
    return { w1_first: before === IN.photos.w1, thumbnail_w2: !!img() && img().dataset.photo === IN.photos.w2, figure_w2: w.piece === T.watch2 && JSON.stringify(w.rgb) === '[110,75,50]' };
  },
  async avt11() { // a formal and a festive look side by side: one show() with two figures, each list with readiness
    const { host } = await section();
    await press(host, 'Compare'); await press(host, 'Tomorrow · 19:00 · festive');
    await until(() => lastFig(1));
    const cols = within(host).filter((e) => e.classList.contains('tr-col'));
    const ready = cols.map((c) => c.all().filter((e) => e.classList.contains('tr-item') && e.dataset.piece).map((e) => /Ready(?![a-z])/.test(e.textContent)));
    return { two_figures: rec().shown[rec().shown.length - 1].figures.length === 2, two_lists: cols.length === 2,
      each_readiness: ready.length === 2 && ready.every((l) => l.length >= 3 && l.every(Boolean)),
      the_looks: (pieces(lastFig(0)).top || [])[0] === T.striped && (pieces(lastFig(1)).top || [])[0] === T.kurta };
  },
  async avt14() { // the shared picture's caption: fixed words only, passed to B's snapshot(); nothing private, no id
    const { host } = await section();
    await press(host, 'Save a picture of this look'); await until(() => rec().snapshots.length > 0);
    await until(() => within(host).some((e) => e.tagName === 'IMG' && e.classList.contains('tr-shot') && String(e.src || '').startsWith('data:image/png')));
    const cap = (rec().snapshots[0] || {}).caption || [];
    return { caption: JSON.stringify(cap) === JSON.stringify(IN.caption), no_id_or_label: !/wi_|vest/i.test(cap.join(' ')),
      previewed: within(host).some((e) => e.tagName === 'IMG' && e.classList.contains('tr-shot') && String(e.src || '').startsWith('data:image/png')) };
  },
  async avt09() { // a jacket in the laundry is a draft: the server refuses it before any tool; undo brings the blazer back
    const { host } = await section();
    await press(rowOf(host, 'outer'), 'Change'); await press(host, 'navy jacket · Draft: in the laundry');
    await until(() => rowOf(host, 'outer') && rowOf(host, 'outer').dataset.piece === T.rain_jacket);
    const draft = host.textContent.includes('Draft: in the laundry') && host.textContent.includes('can’t be confirmed for the event');
    await press(host, 'Use this look'); await until(() => host.textContent.includes("it can't be confirmed for this event"));
    const refused = host.textContent.includes("it can't be confirmed for this event") && seen.tools.length === 0;
    await press(host, 'Undo'); await until(() => rowOf(host, 'outer') && rowOf(host, 'outer').dataset.piece === T.blazer);
    return { draft, refused, undone: rowOf(host, 'outer').dataset.piece === T.blazer && (pieces(lastFig()).outer || [])[0] === T.blazer };
  },
  async seeme() { // his YES typed once (anything else changes nothing); the rupee confirm's Cancel sends NOTHING; then exactly PictureIn
    const { host } = await section();
    const me = within(host).find((e) => e.classList.contains('tr-me'));
    await press(me, 'Use this one'); await until(() => me.textContent.includes('With your'));
    const dlg = () => DOC.body.children.find((e) => e.tagName === 'DIALOG');
    const typeIn = async (words) => { await press(me, 'See it on me'); await until(() => dlg() && dlg().open); within(dlg()).find((e) => e.tagName === 'INPUT').value = words; await press(dlg(), 'Agree'); };
    await typeIn('yes'); await until(() => me.textContent.includes('Type YES in capitals'));
    const lower_refused = seen.api.filter((c) => c.path === '/v1/seeme/consent').length === 1 && !seen.door.some((d) => d.fn === 'make');
    await typeIn('YES'); await until(() => dlg().open && dlg().textContent.includes('Make 1 picture?'));
    const shown = dlg().textContent.includes('₹8.90 with GST is typical');
    await press(dlg(), 'Cancel'); await until(() => me.textContent.includes('Nothing was sent.'));
    const cancel_sent_nothing = !seen.door.some((d) => d.fn === 'make') && !seen.api.some((c) => c.path === '/v1/seeme/pictures');
    await press(me, 'See it on me'); await until(() => dlg().open && dlg().textContent.includes('Make 1 picture?'));
    await press(dlg(), 'Make the picture'); await until(() => me.textContent.includes('Generated 2D style preview'));
    const made = seen.door.filter((d) => d.fn === 'make').map((d) => d.args[0]);
    const body = made[0] || {};
    return { lower_refused, rupees_shown: shown, cancel_sent_nothing, one_press: made.length === 1,
      picture_in: JSON.stringify(Object.keys(body).sort()) === JSON.stringify(['confirm_cost', 'garment', 'inr_shown', 'pieces', 'request_id'])
        && body.confirm_cost === true && /^tq_[0-9a-f]{16}$/.test(body.request_id) && /^tg_[0-9a-f]{12}$/.test(body.garment),
      labelled: me.textContent.includes(IN.generated) && me.textContent.includes('not in your wardrobe') };
  },
};

let out = null;
try { out = { checks: await SCENARIOS[IN.scenario](), seen: { api: seen.api.length, door: seen.door.map((d) => d.fn), tools: seen.tools.length } }; }
catch (e) { out = { checks: { ran: false }, error: String(e && e.stack || e).slice(0, 600) }; }
console.log('R131D-DOM ' + JSON.stringify(out));
process.exit(0);
