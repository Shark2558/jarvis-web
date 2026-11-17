// src/jarvis/api/static/console-tryon.js -- R13.1 Part D (plan r13-1-try-on.md D1, D4, D7-D9, D16, D21): Helpers ->
// Wardrobe -> "Try it on", and the try-on card under a "what should I wear?" reply.
//   mount(host, ctx)  mounted ONCE by console-helpers-wardrobe.js; opens dressed by itself in the first look "Today and
//                     tomorrow" shows (a plan's, else ?day=). open(plan): a plan's "Show in 3D" ('jarvis:tryon-open')
//   inline(el, card)  row 388: a reply's checked 'tryon' card; the figure wears exactly its pieces (?pieces=slot:wi_...)
//   garment(file)     D22: a picture shared in opens See it on me with it (this call sends nothing)
//   state()           'on' | 'off' | 'unknown': Try-on on this server, as GET /v1/tryon last said; 'jarvis:tryon-state'
//                     fires when it changes (R13's plan rows draw Show in 3D only while it is 'on', review D-1 M7)
// A viewer (the section's, a card's) holds one look on B's stage, through the engine contract only, with its controls
// and its list ('./console-tryon-list.js'), the checklist by itself when 3D can't run (Retry 3D once a page). ONE stage
// on the page: the viewer taking it gives the other's back; a hidden viewer (its tab, the page) gives it back too.
// The section's forms (measurements, shapes, OPS-05) are './console-tryon-form.js'. Every change goes to the server;
// nothing is kept on this device; no pixel API (B's snapshot draws the caption).
import { COVERED, WHY, caption, cardQuery, chosen, covered, crop, dropCrops, figure, items, pairs, planTitle, query, same, tomorrowIso, when }
  from './console-tryon-list.js';
import * as F from './console-tryon-form.js';

const engine3d = () => import('./console-tryon-3d.js'), seeMe = () => import('./console-tryon-me.js');
const GL = ['no-webgl2', 'lost', 'asset', 'timeout'], RETRY = ['lost', 'asset', 'timeout', 'engine'];
const PREPARING = 'Preparing the 3D view\u2026';
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const NO_PLAN = 'This look has no plan yet: ask JARVIS what to wear, or plan it in Today and tomorrow.';
const FIRST_RENDER_MS = 10000, FILES_MS = 30000, WATCH_MS = 250, UNDO_MAX = 20, EVENING = 18, PLAN = /^op_[0-9a-f]{8}$/; // a saved plan's id (R13's 'suggestion' row is none)
const LAYERS = [['all', 'All layers'], ['no_outer', 'Without the outer layer'], ['base', 'Base layer only']];
const VIEWS = [['front', 'Front'], ['side', 'Side'], ['back', 'Back']];
const S = { H: null, ctx: null, host: null, off: false, tryon: null, outfits: null, photos: null, sec: null, card: null, holder: null,
  retried: false, file: null, me: null, el: {}, views: new Set(), priv: false, next: null };

const H = () => S.H || (S.H = window.JarvisHelpers || null);
const api = (path, opts) => window.JarvisConsole.api(path, opts);
const door = () => { const M = window.JarvisMobile; return M && M.parts && M.parts.send ? M.parts.send : null; };
const reading = (fn) => (id) => crop(id, (x) => { const d = door(); return d && typeof d[fn] === 'function' ? d[fn](x) : Promise.reject(new Error('no door')); });
const thumb = reading('thumb'); // a crop read once a page (M2): no fetch, no alt text on a control press
const txt = (v, n = 200) => (H() ? H().txt(String(v == null ? '' : v), n) : String(v == null ? '' : v).slice(0, n));
const body = () => (S.tryon && S.tryon.body ? S.tryon.body.draft || S.tryon.body.current : null);
const assets = () => (S.tryon && S.tryon.assets) || [];
function btn(label, onClick, cls, key) { // key: the control's own name, kept when its words turn (M5)
  const b = H().mk('button', 'btn sact' + (cls ? ' ' + cls : ''), label);
  b.type = 'button'; b.dataset.k = key || label;
  b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(b); });
  return b;
}
const pressed = (b, on) => { b.setAttribute('aria-pressed', on ? 'true' : 'false'); if (on) b.classList.add('primary'); return b; };
const off = (b, on) => { if (on) b.setAttribute('aria-disabled', 'true'); return b; };
function say(v, kind, text) { if (v && v.el) { H().note(v.el.status, kind, text); v.el.status.classList.add('tr-status'); } } // its place class kept (L3)
function failed(v, e) {
  if (e && e.status === 401) return;
  say(v, 'bad', e && e.name === 'TypeError' ? OFFLINE : txt((e && e.message) || 'That didn\u2019t work.', 240));
}

// ---- the server's look ------------------------------------------------------------------------------------------
async function lookOf(v, q) { // a fresh read: readiness comes from the server, never the render; covered slots kept
  const look = await api('/v1/tryon/look?' + q), mine = new Map((v.covered || []).map((c) => [c.slot, c]));
  const slots = (Array.isArray(look.slots) ? look.slots : []).map((s) => (s.private && mine.has(s.slot) // his own tap (R13 D10)
    ? Object.assign({}, s, { piece: mine.get(s.slot).piece || null }) : s));
  return Object.assign({}, look, { slots: slots.concat([...mine.values()].filter((c) => !slots.some((s) => s.slot === c.slot))) });
}
async function photosOf() { // the views' crop ids, for the reference cards (R13's own read of his wardrobe)
  if (S.photos) return S.photos;
  try { const w = await api('/v1/wardrobe'); S.photos = new Map((w.pieces || []).map((p) => [p.id, Array.isArray(p.photos) ? p.photos : []])); }
  catch (_) { S.photos = new Map(); }
  return S.photos;
}
export const state = () => (S.off ? 'off' : S.tryon ? 'on' : 'unknown');
async function readTryon() {
  const was = state();
  try { S.tryon = await api('/v1/tryon'); S.off = false; } catch (e) {
    if (e && (e.status === 404 || e.code === 'off')) S.off = true; // A's 503 'off' is off; other 503s are for now (L4)
    S.tryon = null;
    throw e;
  } finally { if (state() !== was) document.dispatchEvent(new CustomEvent('jarvis:tryon-state', { detail: { state: state() } })); }
  return S.tryon;
}

// ---- one viewer ------------------------------------------------------------------------------------------------------
const PARTS = [['head', 'div', 'tr-head'], ['status', 'p', 'sfine tr-status'], ['stage', 'div', 'tr-stage'], ['tools', 'div', 'sacts tr-tools'],
  ['style', 'div', 'sacts tr-style'], ['acts', 'div', 'sacts tr-acts'], ['extra', 'div', 'tr-extra'], ['list', 'div', 'tr-list']];
function viewer(root, kind) {
  const h = H(), el = {}, view = h.mk('div', 'tr-view');
  PARTS.forEach(([k, tag, cls]) => { el[k] = h.mk(tag, cls); });
  el.status.setAttribute('role', 'status');
  view.append(...PARTS.map(([k]) => el[k]));
  root.append(view);
  const v = { kind, view, el, look: null, second: null, titles: [], covered: [], plan: null, src: '', starts: '', planPairs: [],
    opts: { tucked: false, open: true, layers: 'all', view: 'front' }, undo: [], stage: null, mode: '3d', why: '', open: null,
    spin: false, still: false, watch: 0, comparing: false, resume: false, forced: '' };
  S.views.add(v); // its tab hidden (0 x 0: another Helpers tab, the panel shut): the context goes back
  v.ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => (view.offsetParent === null ? pause(v) : wake(v))) : null;
  if (v.ro) v.ro.observe(view);
  return v;
}
async function show(v, look, o) { // a new look in this viewer, then the figure (or the checklist)
  v.look = look; v.second = null; v.comparing = false; v.undo = []; v.open = null;
  v.plan = (o && o.plan) || look.plan || null; v.starts = (o && o.starts) || ''; v.src = (o && o.src) || '';
  v.titles = [txt((o && o.title) || 'This look', 80)];
  v.covered = covered(look, S.priv);
  v.planPairs = pairs(look);
  v.opts = { tucked: !!look.tucked, open: look.open !== false, layers: look.layers || 'all', view: v.opts.view || 'front' };
  await photosOf();
  if (v.mode === '3d' || v.why === 'elsewhere' || v.why === 'nofigure' || v.why === 'paused') await to3d(v); else draw(v);
}
async function privy(v, on) { // R13 D10: his own checklist names a private basic only behind his tap; the figure never does
  S.priv = !!on;
  if (S.ctx && typeof S.ctx.show === 'function') S.ctx.show(S.priv); // R13's own words for it (nameOf) follow the same tap
  if (S.priv && v.src) { try { v.covered = covered(await api('/v1/tryon/look?' + v.src + '&private=1'), S.priv); } catch (e) { failed(v, e); } }
  if (!S.priv) v.covered = v.covered.map((c) => Object.assign({}, c, { piece: null }));
  v.look = Object.assign({}, v.look, { slots: (v.look.slots || []).filter((s) => !s.private).concat(v.covered) });
  draw(v);
}
async function refresh(v) { // a fresh load: the same picks re-read, or the plan's own when he hasn't changed it (L5)
  await photosOf();
  try {
    const own = !!v.src && same(pairs(v.look), v.planPairs);
    v.look = await lookOf(v, own ? v.src : query(pairs(v.look), v.plan, v.look));
    if (own) v.planPairs = pairs(v.look); // what the plan holds now
    if (v.second) v.second = await lookOf({ covered: v.covered, plan: null }, query(pairs(v.second), v.second.plan, v.second));
  } catch (e) { failed(v, e); }
  draw(v); paint(v);
}
// ---- the stage (B's engine, through its contract only) ------------------------------------------------------------------
async function to3d(v) {
  if (!v.look) return;
  if (!body()) { toList(v, 'nofigure'); return; }
  if (S.holder && S.holder !== v) release(S.holder);
  S.holder = v; v.mode = '3d'; v.why = ''; v.resume = false;
  draw(v);
  if (v.stage) { paint(v, true); return; } // a new look on the same stage: one WebGL context, never two
  say(v, '', PREPARING);
  let E = null;
  try { const m = await engine3d(); E = window.JarvisTryOn3D || (m && m.default) || null; } catch (_) { E = null; }
  if (S.holder !== v || v.mode !== '3d') return;
  if (!E || typeof E.mount !== 'function' || typeof E.supported !== 'function') { toList(v, 'engine'); return; }
  if (!E.supported()) { toList(v, 'no-webgl2'); return; }
  try { v.stage = E.mount(v.el.stage, { release: (S.tryon && S.tryon.release) || 'm1', onLost: (why) => lost(v, why) }); } catch (e) {
    v.stage = null; toList(v, e && GL.includes(e.code) ? e.code : /check|sum|file/i.test(String(e && e.message)) ? 'asset' : 'engine'); return;
  }
  paint(v, true);
  if (document.hidden || v.view.offsetParent === null) pause(v); // hidden while the engine loaded: given back at once (L6)
}
function paint(v, first) {
  if (!v.stage || v.mode !== '3d') return;
  const figs = [v.look].concat(v.second ? [v.second] : []).map((l) => figure(l, v.opts, body(), assets()));
  let a = null;
  try { a = v.stage.show(figs, Object.assign({}, v.opts)); } catch (e) { toList(v, e && GL.includes(e.code) ? e.code : 'engine'); return; }
  const was = v.forced; // B drew the top tucked though he asked otherwise (a shirt over a wrap): said, Tuck not offered
  v.forced = a && a.forced && a.forced.top === 'tucked' ? 'tucked' : '';
  if (v.forced !== was) draw(v);
  if (first) watch(v);
}
function watch(v) { // the first frame within 10 s, else the checklist (D8); while B says its files are still on their way
  const start = Date.now(); // (state 'loading': up to 30 s on a phone link, then B's own 10 s and onLost) it waits for B
  clearTimeout(v.watch);
  const tick = () => {
    if (!v.stage || v.mode !== '3d') return;
    let st = null;
    try { st = v.stage.stats(); } catch (_) { st = null; }
    if (st && Number(st.triangles) > 0) { say(v, '', ''); return; }
    const files = st && st.state === 'loading', late = Date.now() - start >= FIRST_RENDER_MS;
    if (Date.now() - start >= FIRST_RENDER_MS + (files ? FILES_MS : 0)) { toList(v, 'timeout'); return; }
    if (late && files) say(v, '', 'Still preparing the 3D view: its files are on their way\u2026');
    v.watch = setTimeout(tick, WATCH_MS);
  };
  v.watch = setTimeout(tick, 0);
}
function dispose(v) {
  clearTimeout(v.watch);
  if (v.stage) { const st = v.stage; v.stage = null; try { st.dispose(); } catch (_) {} }
  if (S.holder === v) S.holder = null;
}
function toList(v, why) { dispose(v); v.mode = 'list'; v.why = why || 'list'; draw(v); }
function lost(v, why) { if (v.mode === '3d') toList(v, GL.includes(why) ? why : 'lost'); }
function release(v) { toList(v, 'elsewhere'); }
function retry(v) { S.retried = true; to3d(v); }
// hidden (its tab, or the page): the one WebGL context is given back; it comes back by itself when shown again
function pause(v) { if (v && v.stage) { toList(v, 'paused'); v.resume = true; } }
function wake(v) {
  if (!v.resume || S.gone || document.hidden || !v.view.isConnected || v.view.offsetParent === null) return;
  if (S.holder) { v.resume = false; v.why = 'elsewhere'; draw(v); } else to3d(v);
}
function rest(hidden) { if (hidden) pause(S.holder); else S.views.forEach(wake); }

// ---- drawing a viewer ---------------------------------------------------------------------------------------------
function keeping(v, redraw) { // the pressed control keeps the keyboard focus, or the one now in its place (M5)
  const a = document.activeElement, at = a && a.dataset && v.view.contains(a) ? a : null;
  const part = at && PARTS.map(([k]) => v.el[k]).find((x) => x.contains(at));
  redraw();
  if (!at || (at.isConnected && document.activeElement === at)) return;
  const all = [...v.view.querySelectorAll('button')], by = (k) => k && all.find((b) => b.dataset.k === k);
  const next = by(at.dataset.k) || by(at.dataset.kf) || (part && part.querySelector('button'));
  if (next) next.focus();
}
function draw(v) { keeping(v, () => render(v)); }
function render(v) { // a card (row 388) is compact: the figure, its pieces in one line, a small set of controls (H1)
  const h = H(), el = v.el, three = v.mode === '3d', card = v.kind === 'card';
  v.view.dataset.mode = v.mode; v.view.dataset.why = v.why === 'list' ? '' : v.why;
  const b = body(), est = S.tryon && S.tryon.words ? txt(S.tryon.words, 120) : '';
  const sub = card ? '' : [b ? est || 'Estimated from your measurements' : '', 'every shape is approximate'].filter(Boolean).join(' \u00b7 ');
  el.head.replaceChildren(h.row(v.titles[0] || 'This look', sub));
  const why = v.why === 'nofigure' && v.kind === 'section' ? txt((S.tryon && S.tryon.words) || WHY.nofigure, 160) : WHY[v.why];
  if (!three && why) say(v, ['elsewhere', 'nofigure', 'paused'].includes(v.why) ? '' : 'bad', why);
  el.stage.hidden = !three; el.tools.hidden = !three || card; el.style.hidden = !three || card;
  el.tools.replaceChildren(...(three && !card ? tools(v) : []));
  el.style.replaceChildren(...(three && !card ? style(v) : []));
  el.acts.replaceChildren(...(card ? cardActs(v) : acts(v)));
  el.extra.replaceChildren(...(card ? [] : extra(v)));
  const looks = [v.look].concat(v.second ? [v.second] : []).filter(Boolean).map((l) => chosen(l, assets()));
  if (!v.look) { el.list.replaceChildren(...(el.status.textContent ? [] : [h.empty('Loading the look\u2026')])); return; } // never beside its error (L12)
  items(el.list, looks, { H: h, btn, compact: card, summary: card && three, priv: !card && S.priv, nameOf: S.ctx && S.ctx.nameOf, open: v.open, layers: 'all', titles: v.second ? v.titles : null,
    photosOf: (id) => (S.photos && S.photos.get(id)) || [], thumb,
    toCamera: () => { if (window.JarvisDeck) window.JarvisDeck.open('camera', { focus: true }); },
    onChange: (key) => { v.open = key; draw(v); }, onPick: (slot, piece) => swap(v, 0, slot, piece),
    onPick2: (slot, piece) => swap(v, 1, slot, piece), onRemove: (slot) => swap(v, 0, slot, null) });
  if (card && three && tuckedIn(v)) el.list.append(h.mk('p', 'sfine tr-forced', tuckedIn(v)));
  if (v.kind === 'section' && v.src && v.covered.length) el.list.prepend(h.row('Private basics', S.priv ? 'Named in this list only: the figure stays covered.' // R13 D10's own row
    : 'Covered here and on the figure.', [h.toggle('Show private basics', S.priv, (on) => privy(v, on))]));
}
function tools(v) {
  const out = VIEWS.map(([id, label]) => pressed(btn(label, () => turn(v, id)), v.opts.view === id));
  out.push(pressed(btn('Turn around', () => spin(v)), v.spin));
  out.push(btn('Closer look', () => { if (v.stage) v.stage.closer(); }), btn('Zoom in', () => { if (v.stage) v.stage.zoom(1); }),
    btn('Zoom out', () => { if (v.stage) v.stage.zoom(-1); }));
  if (typeof v.el.stage.requestFullscreen === 'function') out.push(btn('Full screen', () => { v.el.stage.requestFullscreen().catch(() => {}); }));
  if (v.still) out.push(H().mk('p', 'sfine', 'Motion is off: the figure stays still. Use Front, Side and Back.'));
  return out;
}
function spin(v) { // Motion Off: Turn around stays still (L7), and says so
  const was = v.spin;
  v.still = !!(window.JarvisFX && window.JarvisFX.motion() === 'off');
  v.spin = !v.still && !was;
  if (v.stage && v.spin !== was) v.stage.spin(v.spin);
  if (v.still && v.kind === 'card') say(v, '', 'Motion is off: the figure stays still. Drag it to turn it.');
  controls(v);
}
function turn(v, id) { v.opts = Object.assign({}, v.opts, { view: id }); if (v.stage) v.stage.view(id); controls(v); }
function controls(v) { // a view or Turn around redraws its own buttons only: the list and its image cards stay (M2)
  keeping(v, () => (v.kind === 'card' ? v.el.acts.replaceChildren(...cardActs(v)) : v.el.tools.replaceChildren(...tools(v))));
}
function tuckedIn(v) { // INTEGRATION-B section 8: show() answered forced {top: 'tucked'}
  const b = v.forced && ((v.look && v.look.slots) || []).find((s) => s.slot === 'bottom' && !s.private);
  return b ? 'Drawn tucked into the ' + txt(b.words, 40) + ': the figure can only show it this way.' : '';
}
function style(v) {
  const out = [], top = (v.look && v.look.slots || []).find((s) => s.slot === 'top' && !s.private);
  const outer = (v.look && v.look.slots || []).find((s) => s.slot === 'outer' && !s.private);
  if (tuckedIn(v)) out.push(H().mk('p', 'sfine tr-forced', tuckedIn(v)));
  else if (top && (top.variants || []).includes('tucked')) out.push(btn(v.opts.tucked ? 'Untuck' : 'Tuck in', () => restyle(v, { tucked: !v.opts.tucked }), '', 'tuck'));
  else if (top && top.template === 'kurta') out.push(H().mk('p', 'sfine', 'A kurta is worn out.'));
  if (outer && (outer.variants || []).includes('open')) out.push(btn(v.opts.open ? 'Close the jacket' : 'Open the jacket', () => restyle(v, { open: !v.opts.open }), '', 'open'));
  LAYERS.forEach(([id, label]) => out.push(pressed(btn(label, () => restyle(v, { layers: id })), v.opts.layers === id)));
  return out;
}
function restyle(v, patch) { remember(v); v.opts = Object.assign({}, v.opts, patch); draw(v); paint(v); }
function modes(v) { // the checklist one press away; back to 3D, the stage taken back, or Retry 3D once a page
  if (v.mode === '3d') return [btn('Show as a list', () => toList(v, 'list'), '', 'mode')];
  if (v.why === 'list') return [btn('Show in 3D', () => to3d(v), '', 'mode')];
  if (v.why === 'elsewhere' || v.why === 'paused') return [btn('Show it here', () => to3d(v), '', 'mode')];
  return RETRY.includes(v.why) && !S.retried ? [btn('Retry 3D', () => retry(v), '', 'mode')] : [];
}
function cardActs(v) { // row 388's card: a small set; layers, tuck, swap and compare are in the full view in Helpers
  const out = (v.mode === '3d' ? [pressed(btn('Turn around', () => spin(v)), v.spin)] : []).concat(modes(v));
  out.push(btn('Open in Helpers', () => full(v)));
  if (v.plan) out.push(btn('Wearing it', () => wearing(v)));
  return out;
}
function acts(v) {
  const out = modes(v);
  out.push(off(btn('Undo', () => undo(v)), !v.undo.length));
  out.push(btn(v.comparing ? 'Stop comparing' : 'Compare', () => (v.comparing ? stopCompare(v) : chooser(v)), '', 'compare'));
  if (v.mode === '3d') out.push(btn('Save a picture of this look', () => picture(v)));
  if (v.plan) out.push(btn('Use this look', () => confirm(v)), btn('Wearing it', () => wearing(v)));
  return out;
}

// ---- swap, remove, undo (page memory only) -----------------------------------------------------------------------------
function remember(v) {
  v.undo.push({ first: pairs(v.look), second: v.second ? pairs(v.second) : null, opts: Object.assign({}, v.opts) });
  if (v.undo.length > UNDO_MAX) v.undo.shift();
}
async function swap(v, which, slot, piece) { // piece null: Remove (outer, belt, watch, socks)
  const look = which ? v.second : v.look;
  if (!look) return;
  remember(v);
  const list = pairs(look).filter((p) => p.slot !== slot).concat(piece ? [{ slot, piece }] : []);
  const order = (look.slots || []).map((s) => s.slot);
  list.sort((a, b) => order.indexOf(a.slot) - order.indexOf(b.slot));
  try {
    const fresh = await lookOf(which ? { covered: v.covered, plan: null } : v, query(list, which ? look.plan : v.plan, look)); // its own day (H1)
    if (which) v.second = fresh; else v.look = fresh;
  } catch (e) { v.undo.pop(); failed(v, e); return; }
  v.open = null; draw(v); paint(v);
}
async function undo(v) { // a pick no longer eligible comes back as a draft: the server's fresh readiness says so
  const last = v.undo.pop();
  if (!last) return;
  try {
    v.look = await lookOf(v, query(last.first, v.plan, v.look));
    if (last.second && v.second) v.second = await lookOf({ covered: v.covered, plan: null }, query(last.second, v.second.plan, v.second));
  } catch (e) { failed(v, e); }
  v.opts = last.opts; draw(v); paint(v);
}

// ---- a plan: Use this look (A's confirm), Wearing it (R13's tool; the confirm first after a swap, L10) -----------------
function told(v, r, done) { // R13's answer in this viewer: done, waiting for his OK, or refused in R13's own words (H2)
  const ok = !!(r && r.status === 'executed');
  if (r && r.status === 'needs_approval') say(v, '', 'That needs your OK: the card is waiting in the chat.');
  else say(v, ok ? 'ok' : 'bad', txt((r && r.message) || (ok ? done : 'That didn\u2019t work.'), 200));
  return ok;
}
async function confirm(v) {
  if (!v.plan) { say(v, 'bad', NO_PLAN); return false; }
  const chat = window.JarvisChat, session = chat && typeof chat.session === 'function' ? chat.session() : null;
  try {
    const r = await api('/v1/tryon/confirm', { body: { plan: v.plan, slots: pairs(v.look), session_id: session || null } });
    if (!told(v, r, 'Done.')) return false;
    v.planPairs = pairs(v.look);
    return true;
  } catch (e) { failed(v, e); return false; }
}
async function wearing(v) { // R13's wear_log, its answer said here; then R13's tab re-reads its plans and laundry
  if (!v.plan) { say(v, 'bad', NO_PLAN); return; }
  if (!same(pairs(v.look), v.planPairs) && !(await confirm(v))) return;
  try { told(v, await api('/v1/wardrobe/tools/wear_log', { body: { arguments: { action: 'start', plan: v.plan } } }), 'Enjoy the day.'); }
  catch (e) { failed(v, e); }
  if (S.ctx && H() && typeof H().reload === 'function') H().reload();
}

// ---- compare two looks (one show() with two figures), saved comparisons ---------------------------------------------
async function outfits() {
  if (!S.outfits) { try { S.outfits = await api('/v1/outfits'); } catch (_) { S.outfits = { today: [], tomorrow: [] }; } }
  return S.outfits;
}
async function chooser(v) {
  const o = await outfits(), out = [H().mk('p', 'snote', 'Compare this look with:')];
  [['Today', o.today], ['Tomorrow', o.tomorrow]].forEach(([day, list]) => (list || []).forEach((p) => {
    if (p.id !== v.plan && !p.cancelled) out.push(btn(planTitle(day, p), () => compare(v, PLAN.test(p.id) ? 'plan=' + encodeURIComponent(p.id) : 'day=' + day.toLowerCase(), planTitle(day, p)))); // R13's suggestion: by its day
  }));
  const day = v.look && v.look.day === tomorrowIso() ? 'tomorrow' : 'today';
  out.push(btn('Another idea for this day', () => compare(v, 'day=' + day + '&alt=1', 'Another idea')), btn('Cancel', () => { v.choosing = null; draw(v); }));
  v.choosing = out; draw(v);
}
async function compare(v, q, title) {
  try { v.second = await lookOf({ covered: v.covered }, q); } catch (e) { failed(v, e); return; }
  v.choosing = null; v.comparing = true; v.titles = [v.titles[0], txt(title, 80)];
  draw(v); paint(v);
}
function stopCompare(v) { v.second = null; v.comparing = false; v.titles = [v.titles[0]]; draw(v); paint(v); }
function extra(v) {
  if (v.choosing) { const box = H().mk('div', 'sacts'); box.append(...v.choosing); return [box]; }
  if (v.shot) return v.shot;
  if (!v.comparing) return [];
  const box = H().mk('div', 'sacts');
  box.append(btn('Save this comparison', () => saveCompare(v)));
  return [box];
}
const saved = (look, o) => ({ plan: look.plan || null, slots: pairs(look), tucked: !!o.tucked, open: o.open !== false, layers: o.layers || 'all' });
async function saveCompare(v) {
  try {
    await api('/v1/tryon/saved', { body: { looks: [saved(v.look, v.opts), saved(v.second, v.opts)] } });
    say(v, 'ok', 'Saved this comparison: it is re-checked each time you open it.');
    await savedList();
  } catch (e) { failed(v, e); }
}
async function savedList() {
  const box = S.el.saved;
  if (!box) return;
  let list = [];
  try { list = (await api('/v1/tryon/saved')).saved || []; } catch (_) { list = []; }
  if (!list.length) { box.replaceChildren(H().mk('p', 'sfine', 'No saved comparisons yet.')); return; }
  box.replaceChildren(...list.map((s) => H().row('A saved comparison' + (s.draft ? ' \u00b7 Draft' : ''), when(s.at) + (s.draft ? ' \u00b7 a piece in it isn\u2019t ready now' : ''),
    [btn('Open', () => openSaved(s)), btn('Delete', () => dropSaved(s.id))])));
}
async function openSaved(s) {
  const v = S.sec, looks = (s.looks || []).map((x) => x.look);
  if (!v || !looks.length) return;
  try {
    const first = await lookOf(v, query(looks[0].slots, looks[0].plan));
    await show(v, first, { plan: looks[0].plan, title: 'A saved comparison' + (s.draft ? ' (Draft)' : '') });
    if (looks[1]) { v.second = await lookOf({ covered: v.covered }, query(looks[1].slots)); v.comparing = true; v.titles = [v.titles[0], 'The other look']; }
    v.opts = Object.assign({}, v.opts, { tucked: !!looks[0].tucked, open: looks[0].open !== false, layers: looks[0].layers || 'all' });
    draw(v); paint(v);
  } catch (e) { failed(v, e); }
}
async function dropSaved(id) { try { await api('/v1/tryon/saved/' + encodeURIComponent(id), { method: 'DELETE' }); } catch (e) { failed(S.sec, e); } await savedList(); }

// ---- Save a picture of this look (D9: B draws it; the caption's fixed words come from here) ---------------------------------
async function picture(v) {
  if (!v.stage) return;
  const own = !!(S.el.own && S.el.own.checked);
  const lines = caption(v.look, { starts: v.starts, layers: v.opts.layers, own, nameOf: S.ctx && S.ctx.nameOf });
  let blob = null;
  try { blob = await v.stage.snapshot({ caption: lines }); } catch (_) { blob = null; }
  if (!(blob instanceof Blob)) { say(v, 'bad', 'The picture couldn\u2019t be made on this device.'); return; }
  const url = await new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(String(f.result)); f.onerror = () => ok(''); f.readAsDataURL(blob); });
  const img = H().mk('img', 'tr-shot');
  img.alt = 'This look as a picture: ' + lines.join('. ');
  if (/^data:image\/png;base64,/.test(url)) img.src = url;
  const row = H().mk('div', 'sacts');
  row.append(btn('Save to Downloads', () => download(blob, 'jarvis-look-' + String((v.look && v.look.day) || 'today') + '.png')), btn('Close', () => { v.shot = null; draw(v); }));
  v.shot = [img, H().mk('p', 'sfine', 'Made on this device with only these words: ' + lines.join(' / ') + '. JARVIS sends it nowhere.'), row];
  draw(v);
}
function download(blob, file) { // our own bytes as a blob: URL for the download (as the label sheet); never shown in an <img>
  const url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = file; a.rel = 'noopener'; a.hidden = true; document.body.append(a); a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1500);
}

// ---- the section: measurements (D4), shapes (AVT-05), OPS-05 (./console-tryon-form.js) ---------------------------------
const kit = () => ({ H: H(), api, btn, txt, failed: (e) => failed(S.sec, e), tryon: () => S.tryon, look: () => (S.sec && S.sec.look) || null,
  el: S.el, readTryon, redraw: redrawFigures, reload });
const form = () => F.form(kit()), shapes = () => F.shapes(kit()), deleteAll = () => F.deleteAll(kit());
function redrawFigures() { // a new version: every open look redraws, its pieces unchanged (AVT-03)
  form();
  S.views.forEach((v) => { if (!v.look) return; if (v.stage) { draw(v); paint(v); } else if (v.why === 'nofigure') to3d(v); else draw(v); });
}
async function reload() { // after Privacy's delete: the figure, the looks and See it on me as the server has them now
  S.photos = null; dropCrops();
  try { await readTryon(); } catch (_) { S.tryon = null; }
  form(); await first(); savedList();
  if (S.me && S.el.me) S.me.refresh();
}

// ---- the section, mounted ONCE -------------------------------------------------------------------------------------------
async function first() { // the first look "Today and tomorrow" shows: a plan's, else R13's suggestion for the day
  const v = S.sec;
  if (!v) return;
  S.outfits = null;
  const o = await outfits();
  const plan = [['Today', o.today], ['Tomorrow', o.tomorrow]].map(([d, l]) => [d, (l || []).find((p) => !p.cancelled && !p.worn && PLAN.test(p.id))]) // R13's
    .find(([, p]) => p); // 'suggestion' row is no plan; a plan he has put on is behind him (review I1 M2)
  const q = plan ? 'plan=' + encodeURIComponent(plan[1].id) : 'day=' + (new Date().getHours() >= EVENING ? 'tomorrow' : 'today');
  try {
    const look = await api('/v1/tryon/look?' + q + (S.priv ? '&private=1' : ''));
    await show(v, look, plan ? { plan: plan[1].id, starts: plan[1].starts, title: planTitle(plan[0], plan[1]), src: q }
      : { title: 'Suggested for ' + (q.includes('tomorrow') ? 'tomorrow' : 'today'), src: q });
  } catch (e) { failed(v, e); draw(v); }
  shapes();
}
function section() {
  const h = H(), host = S.host;
  S.el = { me: h.mk('div', 'tr-me'), saved: h.mk('div', 'tr-saved'), form: h.mk('div', 'hp-form'), shapes: h.mk('div', 'tr-shapes'), own: h.mk('input', '') };
  S.el.own.type = 'checkbox'; S.el.own.id = 'trOwnLabels';
  const tick = h.mk('label', 'hp-field wd-tick');
  tick.append(h.mk('span', 'snote', 'Use my own labels in a saved picture'), S.el.own);
  const root = h.mk('div', '');
  host.replaceChildren(h.mk('h3', 'hp-h', 'Try it on'), root);
  S.sec = viewer(root, 'section');
  host.append(tick, h.mk('h3', 'hp-h', 'Saved comparisons'), S.el.saved, h.mk('h3', 'hp-h', 'Your measurements'), S.el.form,
    h.mk('h3', 'hp-h', 'See it on me'), S.el.me, h.mk('h3', 'hp-h', 'Try-on settings'), S.el.shapes,
    h.row('Delete all my try-on data', 'Your figure, measurements, photo, YES, pictures and garment photos, with your passkey. Your wardrobe stays as it is.', [btn('Delete all my try-on data', deleteAll)]));
}
export function mount(el, ctx) {
  S.host = el; S.ctx = ctx || null; S.H = (ctx && ctx.H) || window.JarvisHelpers;
  if (!S.host || !H()) return;
  S.host.classList.add('tr-sec');
  S.host.replaceChildren(H().mk('h3', 'hp-h', 'Try it on'), H().empty('Loading Try it on\u2026'));
  start().catch(() => {});
}
async function start() {
  try { await readTryon(); } catch (e) {
    if (S.off) { S.host.hidden = true; S.host.replaceChildren(); return; } // Try-on is off: the tab stays R13's
    const again = btn('Try again', () => mount(S.host, S.ctx));
    S.host.replaceChildren(H().mk('h3', 'hp-h', 'Try it on'), H().row(e && e.name === 'TypeError' ? OFFLINE : 'Try it on can\u2019t load right now.', '', [again]));
    return;
  }
  section(); form();
  await first();
  savedList();
  if (S.next) { const go = S.next; S.next = null; await go(); } // a press made while the section loaded
  try {
    S.me = await seeMe();
    S.me.draw(S.el.me, { H: H(), api, door, btn, thumb, look: () => (S.sec && S.sec.look) || null, photosOf: (id) => (S.photos && S.photos.get(id)) || [] });
    if (S.file) { S.me.take(S.file); S.file = null; }
  }
  catch (_) { S.el.me.replaceChildren(H().empty('See it on me couldn\u2019t load.')); }
}
export async function open(plan) {
  const v = S.sec;
  if (typeof plan !== 'string' || !PLAN.test(plan)) return; // a saved plan's id only
  if (S.off) { S.host.hidden = false; S.host.replaceChildren(H().mk('h3', 'hp-h', 'Try it on'), H().empty('Try it on is off on this server.')); return; }
  if (!v || !v.look) { S.next = () => open(plan); return; } // pressed while the section loads: opened right after
  const o = await outfits(), found = [['Today', o.today], ['Tomorrow', o.tomorrow]].map(([d, l]) => [d, (l || []).find((p) => p.id === plan)]).find(([, p]) => p);
  try {
    const src = 'plan=' + encodeURIComponent(plan), look = await api('/v1/tryon/look?' + src + (S.priv ? '&private=1' : ''));
    await show(v, look, { plan, starts: found ? found[1].starts : '', title: found ? planTitle(found[0], found[1]) : 'This plan', src });
  } catch (e) { failed(v, e); }
  shapes();
}
export function inline(el, card) { // resolves once the card is drawn
  S.H = S.H || window.JarvisHelpers;
  if (!el || !card || !H()) return Promise.resolve();
  if (S.card && S.card.stage) release(S.card); // an earlier reply's card gives the stage back (Show it here takes it again)
  S.views.forEach((x) => { if (x.kind === 'card' && !x.view.isConnected) { dispose(x); if (x.ro) x.ro.disconnect(); S.views.delete(x); } }); // its row left (L3)
  S.card = viewer(el, 'card');
  return dressed(S.card, card).catch(() => {});
}
async function dressed(v, card) { // exactly the card's pieces, by ids (A's ?pieces=), on ITS day and code (review I1 H1);
  v.covered = (card.slots || []).filter((s) => s.private).map((s) => ({ slot: s.slot, private: true, words: COVERED, readiness: '' }));
  v.plan = card.plan || null; // its covered slots stay covered (sent as "slot:", read so by A)
  try { if (!S.tryon) await readTryon(); } catch (e) { // his figure can't be read: the look needs none of it (M3)
    if (S.off || (e && e.status === 401)) { failed(v, e); draw(v); return; } // Try-on off: A's own words, nothing else
    v.mode = 'list'; v.why = 'figure';
  }
  try {
    const look = await lookOf(v, cardQuery(card));
    const code = String(card.code || '').replace(/_/g, ' ');
    await show(v, look, { plan: card.plan, title: 'Your look' + (code ? ' \u00b7 ' + code : '') });
  } catch (e) { failed(v, e); draw(v); }
}
export function garment(file) { return handOver(file); } // D22 (I0's seam pins this line)
async function handOver(file) { // the picture waits for See it on me ({ok: true}); sends nothing. Else {ok: false, code, why}:
  if (!(file instanceof Blob)) return { ok: false, code: 'file' }; // the card module says it (review D-1 M6)
  if (state() === 'unknown') { try { await readTryon(); } catch (_) { /* state() says it */ } }
  if (state() !== 'on') return { ok: false, code: S.off ? 'tryon_off' : 'tryon_down' };
  let me = null;
  try { me = await api('/v1/seeme'); } catch (e) { return { ok: false, code: e && e.name === 'TypeError' ? 'offline' : 'seeme_down' }; }
  if (!me || !me.on) return { ok: false, code: 'seeme_off', why: me && me.why ? txt(me.why, 160) : '' };
  if (S.me && S.el.me && document.contains(S.el.me)) S.me.take(file); else S.file = file;
  helpers(() => S.el.me);
  return { ok: true };
}
function helpers(at) { // Helpers -> Wardrobe opened for him, scrolled to Try it on (or See it on me)
  if (window.JarvisDeck) window.JarvisDeck.open('helpers', { focus: true });
  const tab = document.getElementById('hpt-wardrobe');
  if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
  setTimeout(() => { const el = at(); if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start' }); }, 0);
}
function full(v) { // a card's look in full (layers, tuck, swap, compare): the section shows it and takes the one stage
  const go = () => (v.plan ? open(v.plan) : show(S.sec, v.look, { title: v.titles[0] }));
  if (S.sec && S.sec.look) go(); else S.next = go;
  helpers(() => S.host);
}
document.addEventListener('jarvis:tryon-open', (e) => open((e.detail || {}).plan));
document.addEventListener('jarvis:wardrobe-fresh', () => { S.photos = null; dropCrops(); if (S.sec && S.sec.look) refresh(S.sec); });
document.addEventListener('visibilitychange', () => rest(document.hidden));
window.addEventListener('pagehide', () => { S.gone = true; rest(true); });
window.addEventListener('pageshow', () => { S.gone = false; rest(false); }); // back from the cache: the figure returns
document.addEventListener('jarvis:theme', () => { if (S.holder) paint(S.holder); });
