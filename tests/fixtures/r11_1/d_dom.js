// tests/fixtures/r11_1/d_dom.js -- R11.1 Part D: a small DOM, enough to run a console panel script in Node
// (vm) and press its buttons. Used by tests/test_r11_1_d_people_dom.py and evals/r11_1/look_more.py (the O8
// case presses "Open next" and counts what opened: a behavioural check, not a match on the source).
// What it records: every link the page followed (a click on an <a href>, as a browser opens it) and every
// window.open call. Input on stdin: {source, dossier, presses, offer}. Output on stdout: JSON. ASCII only.
'use strict';
const vm = require('vm');
const fs = require('fs');

class Ev { constructor(type, init) { this.type = type; this.detail = init && init.detail; this.defaultPrevented = false; } preventDefault() { this.defaultPrevented = true; } }

class Node {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase(); this.children = []; this.parentNode = null; this.listeners = {};
    this.attrs = {}; this.dataset = {}; this.style = {}; this._text = ''; this.className = ''; this.id = '';
    this.hidden = false; this.disabled = false; this.value = ''; this.type = ''; this.href = ''; this.target = ''; this.rel = '';
    const self = this;
    this.classList = { add: (c) => { if (!self.cls().includes(c)) self.className = (self.className + ' ' + c).trim(); },
      remove: (c) => { self.className = self.cls().filter((x) => x !== c).join(' '); }, contains: (c) => self.cls().includes(c) };
  }
  cls() { return String(this.className).split(/\s+/).filter(Boolean); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = v == null ? '' : String(v); }
  get firstChild() { return this.children[0] || null; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(typeof n === 'string' ? text(n) : n)); }
  appendChild(n) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; this.children.push(n); return n; }
  insertBefore(n, ref) { if (n.parentNode) n.parentNode.removeChild(n); n.parentNode = this; const i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, n); return n; }
  removeChild(n) { this.children = this.children.filter((c) => c !== n); n.parentNode = null; return n; }
  replaceChildren(...nodes) { this.textContent = ''; this.append(...nodes); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); }
  dispatchEvent(ev) { (this.listeners[ev.type] || []).slice().forEach((fn) => fn(ev)); return !ev.defaultPrevented; }
  click() {
    if (this.disabled) return;
    const ev = new Ev('click'); ev.target = this;
    this.dispatchEvent(ev);
    if (this.tagName === 'A' && this.href && !ev.defaultPrevented) followed.push({ href: this.href, target: this.target, rel: this.rel });
  }
  focus() { doc.activeElement = this; }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  matches(sel) {
    const not = /^(.*):not\(\.([\w-]+)\)$/.exec(sel);
    if (not) return this.matches(not[1]) && !this.cls().includes(not[2]);
    if (sel.startsWith('#')) return this.id === sel.slice(1);
    if (sel.startsWith('.')) return sel.slice(1).split('.').every((c) => this.cls().includes(c));
    return this.tagName === sel.toUpperCase();
  }
  querySelectorAll(sel) { return this.all().filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const text = (t) => { const n = new Node('#text'); n._text = String(t); return n; };

const followed = [];
const doc = new Node('#document');
doc.body = doc.appendChild(new Node('body'));
doc.readyState = 'complete';
doc.activeElement = null;
doc.createElement = (tag) => new Node(tag);
doc.createElementNS = (_, tag) => new Node(tag);
doc.getElementById = (id) => doc.all().find((n) => n.id === id) || null;

function run(input) {
  const panel = doc.body.appendChild(new Node('section')); panel.id = 'p-people';
  const pbody = panel.appendChild(new Node('div')); pbody.className = 'pbody';
  const asked = [], opens = [], deck = [];
  const answers = { '/v1/settings/brain-mode': { mode: 'ai', meaning: '' }, '/v1/people/last': { dossier: input.dossier || null },
    '/v1/people/research': input.dossier || {} };
  const sandbox = {
    document: doc, CustomEvent: Ev, URL, setTimeout, clearTimeout, console,
    JarvisConsole: { ready: () => true, api: (path, opts) => { asked.push({ path, body: opts && opts.body ? opts.body : null }); return Promise.resolve(answers[path]); } },
    JarvisDeck: { open: (id) => deck.push(id) },
    open: (...args) => { opens.push(args[0]); return null; },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(input.source, sandbox);
  return { sandbox, asked, opens, deck };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { sandbox, asked, opens, deck } = run(input);
  for (let i = 0; i < 5; i += 1) await settle();
  const links = doc.querySelectorAll('.plink').map((a) => ({ href: a.href, target: a.target, rel: a.rel, text: a.textContent }));
  const presses = [];
  for (let i = 0; i < (input.presses || 0); i += 1) {
    const before = followed.length, opensBefore = opens.length, btn = doc.getElementById('peopleOpen');
    if (btn) btn.click();
    presses.push({ followed: followed.slice(before).map((f) => f.href), opened: opens.length - opensBefore,
      button: btn ? btn.textContent : null, disabled: btn ? btn.disabled : null });
  }
  let offer = null;
  if (input.offer !== undefined) {
    const el = sandbox.JarvisPeople ? sandbox.JarvisPeople.offerCard(input.offer) : null;
    offer = { drawn: !!el, text: el ? el.textContent : '', buttons: el ? el.querySelectorAll('button').map((b) => b.textContent) : [] };
    const n = asked.length;
    if (el) el.querySelector('button').click();
    for (let i = 0; i < 5; i += 1) await settle();
    const box = doc.getElementById('peopleName');
    offer.asked = asked.slice(n); offer.deck = deck.slice(); offer.name = box ? box.value : null;
  }
  const states = doc.querySelectorAll('.pstate').map((s) => s.textContent);
  process.stdout.write(JSON.stringify({ links, presses, opens: opens.length, states, offer }));
}
main().catch((e) => { process.stdout.write(JSON.stringify({ crashed: String(e && e.stack || e) })); });
