// src/jarvis/api/static/console-tryon.js -- R13.1 Part D (docs/plans/r13-1-try-on.md D1, D4, D7, D8, D9, D16, D21):
// Helpers -> Wardrobe -> "Try it on", and the try-on card under a "what should I wear?" reply.
//   mount(host, ctx)   console-helpers-wardrobe.js mounts the section ONCE (never in its draw()); it opens dressed by
//                      itself in the first look "Today and tomorrow" shows (a plan's, else GET /v1/tryon/look?day=)
//   open(plan)         a plan's "Show in 3D" ('jarvis:tryon-open' {plan}); 'jarvis:wardrobe-fresh' re-reads the look
//   inline(el, card)   row 388: console-tryon-card.js hands over a reply's checked 'tryon' card; the figure under the
//                      reply wears exactly its pieces (GET /v1/tryon/look?pieces=slot:wi_...), a private slot covered
//   garment(file)      D22: a picture shared into the app opens See it on me with it (this call sends nothing)
// A viewer (the section's, the card's) holds one look: the stage of B's engine through its contract only
// (window.JarvisTryOn3D from './console-tryon-3d.js'), its controls (views, Turn around, Closer look, zoom, Full screen;
// tuck, open, layers; swap with each option's readiness, Remove, undo <= 20 in page memory; compare two looks in ONE
// show(); Save this comparison), the item list ('./console-tryon-list.js'), which is the checklist by itself when 3D
// can't run (no WebGL2, an engine or a file that fails, a lost context, a first render over 10 s), with Retry 3D once a
// page. One stage on the page: a viewer that takes it disposes the other's. The section adds the measurements form,
// saved comparisons, See it on me ('./console-tryon-me.js') and Try-on settings (each piece's shape, and "Delete all my
// try-on data": Privacy's own delete). Every change goes to the server (R13's tools for a plan); nothing is kept on this
// device; no pixel API here (the caption is drawn by B's snapshot). textContent only; ASCII source.
import { COVERED, caption, draft, items, slotWord } from './console-tryon-list.js';

const engine3d = () => import('./console-tryon-3d.js');
const seeMe = () => import('./console-tryon-me.js');
const GL = ['no-webgl2', 'lost', 'asset', 'timeout'];
const RETRY = ['lost', 'asset', 'timeout', 'engine'];
const WHY = {
  'no-webgl2': 'This device can\u2019t show the 3D view: here is the checklist.',
  asset: 'A file of the 3D figure didn\u2019t load: here is the checklist.',
  lost: 'The 3D view stopped: here is the checklist.',
  timeout: 'The 3D view took too long to draw: here is the checklist.',
  engine: 'The 3D view isn\u2019t available right now: here is the checklist.',
  nofigure: 'No figure yet: type your measurements in Helpers, Wardrobe, Try it on.',
  elsewhere: 'The 3D view is open in another place.',
  paused: 'The 3D view rests while this page is hidden.',
};
const PREPARING = 'Preparing the 3D view\u2026';
const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
const NO_PLAN = 'This look has no plan yet: ask JARVIS what to wear, or plan it in Today and tomorrow.';
const FIRST_RENDER_MS = 10000, WATCH_MS = 250, UNDO_MAX = 20, EVENING = 18;
const LAYERS = [['all', 'All layers'], ['no_outer', 'Without the outer layer'], ['base', 'Base layer only']];
const VIEWS = [['front', 'Front'], ['side', 'Side'], ['back', 'Back']];
const MEASURE_WORDS = { height: 'Height', shoulders: 'Shoulder width', chest: 'Chest', waist: 'Waist', hips: 'Hips', inseam: 'Inseam' };
const SHAPE_WORDS = { shirt: 'Shirt', tee: 'T-shirt', kurta: 'Kurta', trousers: 'Trousers', shorts: 'Shorts', wrap: 'Mundu or dhoti',
  jacket: 'Jacket', shoe: 'Shoe', sandal: 'Sandal', belt: 'Belt', watch: 'Watch', socks: 'Socks' };
const S = { H: null, ctx: null, host: null, off: false, tryon: null, outfits: null, photos: null, sec: null, card: null, holder: null,
  retried: false, file: null, me: null, el: {} };

const H = () => S.H || (S.H = window.JarvisHelpers || null);
const api = (path, opts) => window.JarvisConsole.api(path, opts);
const door = () => { const M = window.JarvisMobile; return M && M.parts && M.parts.send ? M.parts.send : null; };
const txt = (v, n = 200) => (H() ? H().txt(String(v == null ? '' : v), n) : String(v == null ? '' : v).slice(0, n));
const body = () => (S.tryon && S.tryon.body ? S.tryon.body.draft || S.tryon.body.current : null);
function btn(label, onClick, cls) {
  const b = H().mk('button', 'btn sact' + (cls ? ' ' + cls : ''), label);
  b.type = 'button';
  b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(b); });
  return b;
}
const pressed = (b, on) => { b.setAttribute('aria-pressed', on ? 'true' : 'false'); if (on) b.classList.add('primary'); return b; };
const off = (b, on) => { if (on) b.setAttribute('aria-disabled', 'true'); return b; };
function say(v, kind, text) { if (v && v.el) H().note(v.el.status, kind, text); }
function failed(v, e) {
  if (e && e.status === 401) return;
  say(v, 'bad', e && e.name === 'TypeError' ? OFFLINE : txt((e && e.message) || 'That didn\u2019t work.', 240));
}

// ---- the server's look ------------------------------------------------------------------------------------------
const pairs = (look) => ((look && look.slots) || []).filter((s) => !s.private && s.piece).map((s) => ({ slot: s.slot, piece: s.piece }));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
function query(v, list) {
  const q = list.map((p) => p.slot + ':' + p.piece).join(',');
  return 'pieces=' + encodeURIComponent(q) + (v.plan ? '&plan=' + encodeURIComponent(v.plan) : '');
}
async function lookOf(v, q) { // a fresh read: readiness comes from the server, never the render; covered slots kept
  const look = await api('/v1/tryon/look?' + q);
  const slots = Array.isArray(look.slots) ? look.slots : [];
  const covered = (v.covered || []).filter((c) => !slots.some((s) => s.slot === c.slot));
  return Object.assign({}, look, { slots: slots.concat(covered) });
}
async function photosOf() { // the views' crop ids, for the reference cards (R13's own read of his wardrobe)
  if (S.photos) return S.photos;
  try { const w = await api('/v1/wardrobe'); S.photos = new Map((w.pieces || []).map((p) => [p.id, Array.isArray(p.photos) ? p.photos : []])); }
  catch (_) { S.photos = new Map(); }
  return S.photos;
}
async function readTryon() {
  try { S.tryon = await api('/v1/tryon'); S.off = false; } catch (e) {
    if (e && (e.status === 404 || e.status === 503)) S.off = true;
    S.tryon = null;
    throw e;
  }
  return S.tryon;
}

// ---- one viewer ------------------------------------------------------------------------------------------------------
function viewer(root, kind) {
  const h = H(), el = {};
  ['status', 'head', 'stage', 'tools', 'style', 'acts', 'extra', 'list'].forEach((k) => { el[k] = h.mk(k === 'status' ? 'p' : 'div', ''); });
  el.status.className = 'sfine tr-status'; el.status.setAttribute('role', 'status');
  el.stage.className = 'tr-stage'; el.tools.className = 'sacts tr-tools'; el.style.className = 'sacts tr-style';
  el.acts.className = 'sacts tr-acts'; el.list.className = 'tr-list'; el.extra.className = 'tr-extra';
  const view = h.mk('div', 'tr-view');
  view.append(el.head, el.status, el.stage, el.tools, el.style, el.acts, el.extra, el.list);
  root.append(view);
  return { kind, view, el, look: null, second: null, titles: [], covered: [], plan: null, starts: '', planPairs: [],
    opts: { tucked: false, open: true, layers: 'all', view: 'front' }, undo: [], stage: null, mode: '3d', why: '', open: null,
    spin: false, watch: 0, comparing: false, resume: false };
}
async function show(v, look, o) { // a new look in this viewer, then the figure (or the checklist)
  v.look = look; v.second = null; v.comparing = false; v.undo = []; v.open = null;
  v.plan = (o && o.plan) || look.plan || null; v.starts = (o && o.starts) || '';
  v.titles = [txt((o && o.title) || 'This look', 80)];
  v.covered = (look.slots || []).filter((s) => s.private).map((s) => ({ slot: s.slot, private: true, words: COVERED, readiness: s.readiness || '' }));
  v.planPairs = pairs(look);
  v.opts = { tucked: !!look.tucked, open: look.open !== false, layers: look.layers || 'all', view: v.opts.view || 'front' };
  await photosOf();
  if (v.mode === '3d' || v.why === 'elsewhere' || v.why === 'nofigure' || v.why === 'paused') await to3d(v); else draw(v);
}
async function refresh(v) { // after a swap, an undo, a fresh load: the same picks re-read
  try {
    v.look = await lookOf(v, query(v, pairs(v.look)));
    if (v.second) v.second = await lookOf({ covered: v.covered, plan: null }, query({ plan: null }, pairs(v.second)));
  } catch (e) { failed(v, e); }
  draw(v); paint(v);
}
function figure(look, opts) { // the engine's figure: the contract's fields only; a private slot is {slot, private: true}
  const b = body(), assets = new Map(((S.tryon && S.tryon.assets) || []).map((a) => [a.piece, a]));
  const slots = (look.slots || []).map((s) => {
    if (s.private) return { slot: s.slot, private: true };
    const a = assets.get(s.piece), only = !!(s.card_only || (a && a.card_only));
    const template = only ? null : (a && a.template) || s.template || null;
    const vs = Array.isArray(s.variants) ? s.variants : [];
    const variant = vs.includes('tucked') ? (opts.tucked ? 'tucked' : 'untucked') : vs.includes('open') ? (opts.open ? 'open' : 'closed') : vs[0] || null;
    return { slot: s.slot, piece: s.piece, template, variant, rgb: s.rgb || null, pattern: s.pattern || null, photo: s.photo || null, private: false };
  });
  return { body: { weights: Object.assign({}, b && b.weights), typed: (b && b.typed ? b.typed : []).slice() }, look: { slots } };
}

// ---- the stage (B's engine, through its contract only) ------------------------------------------------------------------
async function to3d(v) {
  if (!v.look) return;
  if (!body()) { toList(v, 'nofigure'); return; }
  if (S.holder && S.holder !== v) release(S.holder);
  S.holder = v; v.mode = '3d'; v.why = ''; v.resume = false;
  draw(v); say(v, '', PREPARING);
  let E = null;
  try { const m = await engine3d(); E = window.JarvisTryOn3D || (m && m.default) || null; } catch (_) { E = null; }
  if (S.holder !== v || v.mode !== '3d') return;
  if (!E || typeof E.mount !== 'function' || typeof E.supported !== 'function') { toList(v, 'engine'); return; }
  if (!E.supported()) { toList(v, 'no-webgl2'); return; }
  try { v.stage = E.mount(v.el.stage, { release: (S.tryon && S.tryon.release) || 'm1', onLost: (why) => lost(v, why) }); } catch (e) {
    v.stage = null; toList(v, e && GL.includes(e.code) ? e.code : /check|sum|file/i.test(String(e && e.message)) ? 'asset' : 'engine'); return;
  }
  paint(v, true);
}
function paint(v, first) {
  if (!v.stage || v.mode !== '3d') return;
  const figs = [figure(v.look, v.opts)].concat(v.second ? [figure(v.second, v.opts)] : []);
  try { v.stage.show(figs, Object.assign({}, v.opts)); } catch (e) { toList(v, e && GL.includes(e.code) ? e.code : 'engine'); return; }
  if (first) watch(v);
}
function watch(v) { // the first frame within 10 s, else the checklist (D8); stats() reports triangles once drawn
  const start = Date.now();
  clearTimeout(v.watch);
  const tick = () => {
    if (!v.stage || v.mode !== '3d') return;
    let st = null;
    try { st = v.stage.stats(); } catch (_) { st = null; }
    if (st && Number(st.triangles) > 0) { say(v, '', ''); return; }
    if (Date.now() - start >= FIRST_RENDER_MS) { toList(v, 'timeout'); return; }
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
function rest(hidden) { // tab hidden or the page going: the one WebGL context is given back; it comes back when shown
  [S.sec, S.card].forEach((v) => {
    if (!v) return;
    if (hidden && v.stage) { dispose(v); v.why = 'paused'; v.resume = true; draw(v); say(v, '', WHY.paused); }
    else if (!hidden && v.resume && !S.holder) to3d(v);
  });
}

// ---- drawing a viewer ---------------------------------------------------------------------------------------------
function draw(v) {
  const h = H(), el = v.el, three = v.mode === '3d';
  v.view.dataset.mode = v.mode; v.view.dataset.why = v.why === 'list' ? '' : v.why;
  const b = body(), est = S.tryon && S.tryon.words ? txt(S.tryon.words, 120) : '';
  el.head.replaceChildren(h.row(v.titles[0] || 'This look', [b ? est || 'Estimated from your measurements' : '', 'every shape is approximate'].filter(Boolean).join(' \u00b7 ')));
  if (!three && WHY[v.why]) say(v, v.why === 'elsewhere' ? '' : 'bad', WHY[v.why]);
  el.stage.hidden = !three; el.tools.hidden = !three; el.style.hidden = !three;
  el.tools.replaceChildren(...(three ? tools(v) : []));
  el.style.replaceChildren(...(three ? style(v) : []));
  el.acts.replaceChildren(...acts(v));
  el.extra.replaceChildren(...extra(v));
  const looks = [v.look].concat(v.second ? [v.second] : []);
  if (!v.look) { el.list.replaceChildren(h.empty('Loading the look\u2026')); return; }
  items(el.list, looks, { H: h, btn, priv: false, nameOf: S.ctx && S.ctx.nameOf, open: v.open, layers: 'all', titles: v.second ? v.titles : null,
    photosOf: (id) => (S.photos && S.photos.get(id)) || [], thumb: (id) => { const d = door(); return d ? d.thumb(id) : Promise.reject(new Error('no door')); },
    toCamera: () => { if (window.JarvisDeck) window.JarvisDeck.open('camera', { focus: true }); },
    onChange: (key) => { v.open = key; draw(v); }, onPick: (slot, piece) => swap(v, 0, slot, piece),
    onPick2: (slot, piece) => swap(v, 1, slot, piece), onRemove: (slot) => remove(v, slot) });
}
function tools(v) {
  const out = VIEWS.map(([id, label]) => pressed(btn(label, () => turn(v, id)), v.opts.view === id));
  out.push(pressed(btn('Turn around', () => { v.spin = !v.spin; if (v.stage) v.stage.spin(v.spin); draw(v); }), v.spin));
  out.push(btn('Closer look', () => { if (v.stage) v.stage.closer(); }), btn('Zoom in', () => { if (v.stage) v.stage.zoom(1); }),
    btn('Zoom out', () => { if (v.stage) v.stage.zoom(-1); }));
  if (typeof v.el.stage.requestFullscreen === 'function') out.push(btn('Full screen', () => { v.el.stage.requestFullscreen().catch(() => {}); }));
  if (v.spin && window.JarvisFX && window.JarvisFX.motion() === 'off') out.push(H().mk('p', 'sfine', 'Motion is off: the figure stays still. Use Front, Side and Back.'));
  return out;
}
function turn(v, id) { v.opts = Object.assign({}, v.opts, { view: id }); if (v.stage) v.stage.view(id); draw(v); }
function style(v) {
  const out = [], top = (v.look && v.look.slots || []).find((s) => s.slot === 'top' && !s.private);
  const outer = (v.look && v.look.slots || []).find((s) => s.slot === 'outer' && !s.private);
  if (top && (top.variants || []).includes('tucked')) out.push(btn(v.opts.tucked ? 'Untuck' : 'Tuck in', () => restyle(v, { tucked: !v.opts.tucked })));
  else if (top && top.template === 'kurta') out.push(H().mk('p', 'sfine', 'A kurta is worn out.'));
  if (outer && (outer.variants || []).includes('open')) out.push(btn(v.opts.open ? 'Close the jacket' : 'Open the jacket', () => restyle(v, { open: !v.opts.open })));
  LAYERS.forEach(([id, label]) => out.push(pressed(btn(label, () => restyle(v, { layers: id })), v.opts.layers === id)));
  return out;
}
function restyle(v, patch) { remember(v); v.opts = Object.assign({}, v.opts, patch); draw(v); paint(v); }
function acts(v) {
  const out = [];
  if (v.mode === '3d') out.push(btn('Show as a list', () => toList(v, 'list')));
  else if (v.why === 'list') out.push(btn('Show in 3D', () => to3d(v)));
  else if (v.why === 'elsewhere' || v.why === 'paused') out.push(btn('Show it here', () => to3d(v)));
  else if (RETRY.includes(v.why) && !S.retried) out.push(btn('Retry 3D', () => retry(v)));
  out.push(off(btn('Undo', () => undo(v)), !v.undo.length));
  out.push(btn(v.comparing ? 'Stop comparing' : 'Compare', () => (v.comparing ? stopCompare(v) : chooser(v))));
  if (v.mode === '3d') out.push(btn('Save a picture of this look', () => picture(v)));
  if (v.plan) out.push(btn('Use this look', () => confirm(v)), btn('Wearing it', () => wearing(v)));
  return out;
}

// ---- swap, remove, undo (page memory only) -----------------------------------------------------------------------------
function remember(v) {
  v.undo.push({ first: pairs(v.look), second: v.second ? pairs(v.second) : null, opts: Object.assign({}, v.opts) });
  if (v.undo.length > UNDO_MAX) v.undo.shift();
}
async function swap(v, which, slot, piece) {
  const look = which ? v.second : v.look;
  if (!look) return;
  remember(v);
  const list = pairs(look).filter((p) => p.slot !== slot).concat([{ slot, piece }]);
  const order = (look.slots || []).map((s) => s.slot);
  list.sort((a, b) => order.indexOf(a.slot) - order.indexOf(b.slot));
  try {
    const fresh = await lookOf(which ? { covered: v.covered, plan: null } : v, query(which ? { plan: null } : v, list));
    if (which) v.second = fresh; else v.look = fresh;
  } catch (e) { v.undo.pop(); failed(v, e); return; }
  v.open = null; draw(v); paint(v);
}
async function remove(v, slot) {
  remember(v);
  try { v.look = await lookOf(v, query(v, pairs(v.look).filter((p) => p.slot !== slot))); } catch (e) { v.undo.pop(); failed(v, e); return; }
  v.open = null; draw(v); paint(v);
}
async function undo(v) { // a pick no longer eligible comes back as a draft: the server's fresh readiness says so
  const last = v.undo.pop();
  if (!last) return;
  try {
    v.look = await lookOf(v, query(v, last.first));
    if (last.second && v.second) v.second = await lookOf({ covered: v.covered, plan: null }, query({ plan: null }, last.second));
  } catch (e) { failed(v, e); }
  v.opts = last.opts; draw(v); paint(v);
}

// ---- a plan: Use this look (A's confirm), Wearing it (R13's tool; the confirm first after a swap, L10) -----------------
async function confirm(v) {
  if (!v.plan) { say(v, 'bad', NO_PLAN); return false; }
  const chat = window.JarvisChat, session = chat && typeof chat.session === 'function' ? chat.session() : null;
  try {
    const r = await api('/v1/tryon/confirm', { body: { plan: v.plan, slots: pairs(v.look), session_id: session || null } });
    if (r && r.status === 'needs_approval') say(v, '', 'That needs your OK: the card is waiting in the chat.');
    else say(v, r && r.status === 'executed' ? 'ok' : 'bad', txt((r && r.message) || 'Done.', 200));
    if (!r || r.status !== 'executed') return false;
    v.planPairs = pairs(v.look);
    return true;
  } catch (e) { failed(v, e); return false; }
}
async function wearing(v) {
  if (!v.plan) { say(v, 'bad', NO_PLAN); return; }
  if (!same(pairs(v.look), v.planPairs) && !(await confirm(v))) return;
  const args = { action: 'start', plan: v.plan };
  if (S.ctx && typeof S.ctx.tool === 'function') { await S.ctx.tool('wear_log', args, 'Enjoy the day.'); say(v, 'ok', 'Enjoy the day.'); return; }
  try {
    const r = await api('/v1/wardrobe/tools/wear_log', { body: { arguments: args } });
    say(v, r && r.status === 'executed' ? 'ok' : 'bad', txt((r && r.message) || 'Enjoy the day.', 200));
  } catch (e) { failed(v, e); }
}

// ---- compare two looks (one show() with two figures), saved comparisons ---------------------------------------------
async function outfits() {
  if (!S.outfits) { try { S.outfits = await api('/v1/outfits'); } catch (_) { S.outfits = { today: [], tomorrow: [] }; } }
  return S.outfits;
}
function planTitle(day, p) {
  const at = /T(\d{2}:\d{2})/.exec(String(p.starts || ''));
  return [day, at ? at[1] : '', String(p.dress_code || '').replace(/_/g, ' ')].filter(Boolean).join(' \u00b7 ');
}
async function chooser(v) {
  const o = await outfits(), out = [H().mk('p', 'snote', 'Compare this look with:')];
  [['Today', o.today], ['Tomorrow', o.tomorrow]].forEach(([day, list]) => (list || []).forEach((p) => {
    if (p.id !== v.plan && !p.cancelled) out.push(btn(planTitle(day, p), () => compare(v, 'plan=' + encodeURIComponent(p.id), planTitle(day, p))));
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
    const first = await lookOf(v, query({ plan: looks[0].plan }, looks[0].slots));
    await show(v, first, { plan: looks[0].plan, title: 'A saved comparison' + (s.draft ? ' (Draft)' : '') });
    if (looks[1]) { v.second = await lookOf({ covered: v.covered }, query({ plan: null }, looks[1].slots)); v.comparing = true; v.titles = [v.titles[0], 'The other look']; }
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

// ---- the section: measurements (D4), shapes (AVT-05), OPS-05 ------------------------------------------------------------
const when = (iso) => (window.JarvisMobile && window.JarvisMobile.when ? window.JarvisMobile.when(iso, true) : String(iso || '').slice(0, 16).replace('T', ' '));
const tomorrowIso = () => { const d = new Date(Date.now() + 864e5); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
function form() {
  const h = H(), box = S.el.form, t = S.tryon;
  if (!box || !t) return;
  const ver = (t.body && (t.body.draft || t.body.current)) || null, typed = new Set((ver && ver.typed) || []);
  const grid = h.mk('div', 'hp-grid tr-form'), err = h.mk('p', 'snote warn');
  err.setAttribute('role', 'alert');
  (t.ranges || []).forEach((r) => {
    const input = h.mk('input', 'minput');
    input.type = 'number'; input.inputMode = 'numeric'; input.min = String(r.low); input.max = String(r.high); input.step = '1';
    input.name = r.measure; input.value = ver ? String(ver[r.measure]) : '';
    input.setAttribute('aria-label', (MEASURE_WORDS[r.measure] || r.measure) + ' in cm');
    const f = h.mk('label', 'hp-field');
    f.append(h.mk('span', 'snote', (MEASURE_WORDS[r.measure] || r.measure) + ' (cm)'), input, h.mk('span', 'sfine', ver && !typed.has(r.measure) ? 'estimated' : ver ? 'typed' : ''));
    input.addEventListener('change', () => typeIn(r, input, err));
    grid.append(f);
  });
  const out = [h.mk('p', 'sfine', txt(t.words || '', 160)), grid, err];
  if (t.body && t.body.draft) {
    out.push(h.mk('p', 'snote', 'The figure shows your new measurements; your looks and saved comparisons keep their pieces.'));
    const a = h.mk('div', 'sacts');
    a.append(btn('Use these measurements', () => bodyStep('/v1/tryon/body/use', 'POST')), btn('Keep the current', () => bodyStep('/v1/tryon/body/draft', 'DELETE')));
    out.push(a);
  }
  box.replaceChildren(...out);
}
async function typeIn(r, input, err) {
  const v = Number(input.value);
  if (!Number.isInteger(v) || v < r.low || v > r.high) { err.textContent = txt(r.words, 120) + '.'; return; }
  err.textContent = '';
  const t = S.tryon, ver = t.body && (t.body.draft || t.body.current), sent = {};
  ((ver && ver.typed) || []).forEach((k) => { sent[k] = ver[k]; });
  sent[r.measure] = v;
  try { t.body = await api('/v1/tryon/body', { method: 'PUT', body: sent }); } catch (e) { err.textContent = txt(e && e.message, 160); return; }
  redrawFigures();
}
async function bodyStep(path, method) {
  try { S.tryon.body = await api(path, { method }); } catch (e) { failed(S.sec, e); }
  redrawFigures();
}
function redrawFigures() { // a new version: every open look redraws, its pieces unchanged (AVT-03)
  form();
  [S.sec, S.card].forEach((v) => { if (!v || !v.look) return; if (v.stage) { draw(v); paint(v); } else if (v.why === 'nofigure') to3d(v); else draw(v); });
}
function shapes() {
  const h = H(), box = S.el.shapes, v = S.sec;
  if (!box) return;
  const assets = new Map(((S.tryon && S.tryon.assets) || []).map((a) => [a.piece, a]));
  const rows = ((v && v.look && v.look.slots) || []).filter((s) => !s.private && s.piece).map((s) => {
    const shapesOf = [...new Set([s.template].concat((s.options || []).map((o) => o.template)).filter(Boolean))];
    const a = assets.get(s.piece), now = a && a.card_only ? '' : (a && a.template) || s.template || '';
    const pick = h.mk('select', 'minput');
    pick.setAttribute('aria-label', 'Shape on the figure for ' + txt(s.words, 60));
    shapesOf.concat(['']).forEach((t) => { const o = h.mk('option', '', t ? (SHAPE_WORDS[t] || t) + ' (approximate)' : 'Image card only'); o.value = t; pick.append(o); });
    pick.value = now;
    pick.addEventListener('change', () => shapeOf(s.piece, pick.value));
    return h.row(slotWord(s.slot) + ': ' + txt(s.words, 60), now ? 'Drawn on an approximate shape; its photo stays beside it.' : 'Shown as its photo only.', [pick]);
  });
  box.replaceChildren(...(rows.length ? rows : [h.mk('p', 'sfine', 'The pieces of the look above will show here.')]));
}
async function shapeOf(piece, template) {
  try {
    await api('/v1/tryon/assets/' + encodeURIComponent(piece), { method: 'PUT', body: { piece, template: template || null, card_only: !template } });
    await readTryon();
  } catch (e) { failed(S.sec, e); return; }
  shapes(); redrawFigures();
}
async function deleteAll() { // OPS-05: Privacy's own delete of tryon_all (its passkey and its words); then everything re-read
  const P = window.JarvisPrivacy;
  if (!P || typeof P.remove !== 'function' || !(await P.remove('tryon_all'))) { failed(S.sec, new Error('Open Privacy to delete your try-on data.')); return; }
  const gone = () => !document.querySelector('.pv-dlg');
  const obs = new MutationObserver(() => { if (gone()) { obs.disconnect(); reload(); } });
  obs.observe(document.body, { childList: true });
}
async function reload() { S.photos = null; try { await readTryon(); } catch (_) { /* said below */ } await first(); if (S.me && S.el.me) S.me.refresh(); }

// ---- the section, mounted ONCE -------------------------------------------------------------------------------------------
async function first() { // the first look "Today and tomorrow" shows: a plan's, else R13's suggestion for the day
  const v = S.sec;
  if (!v) return;
  S.outfits = null;
  const o = await outfits();
  const plan = [['Today', o.today], ['Tomorrow', o.tomorrow]].map(([d, l]) => [d, (l || []).find((p) => !p.cancelled)]).find(([, p]) => p);
  const q = plan ? 'plan=' + encodeURIComponent(plan[1].id) : 'day=' + (new Date().getHours() >= EVENING ? 'tomorrow' : 'today');
  try {
    const look = await api('/v1/tryon/look?' + q);
    await show(v, look, plan ? { plan: plan[1].id, starts: plan[1].starts, title: planTitle(plan[0], plan[1]) } : { title: 'Suggested for ' + (q.includes('tomorrow') ? 'tomorrow' : 'today') });
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
    S.host.replaceChildren(H().mk('h3', 'hp-h', 'Try it on'), H().empty(e && e.name === 'TypeError' ? OFFLINE : 'Try it on couldn\u2019t load.'));
    return;
  }
  section(); form();
  await first();
  savedList();
  if (S.plan) { const p = S.plan; S.plan = null; await open(p); }
  try { S.me = await seeMe(); S.me.draw(S.el.me, { H: H(), api, door, btn, look: () => (S.sec && S.sec.look) || null }); if (S.file) { S.me.take(S.file); S.file = null; } }
  catch (_) { S.el.me.replaceChildren(H().empty('See it on me couldn\u2019t load.')); }
}
export async function open(plan) {
  const v = S.sec;
  if (typeof plan !== 'string' || !plan) return;
  if (!v || !v.look) { S.plan = plan; return; } // pressed while the section loads: opened right after
  if (S.off) { S.host.hidden = false; S.host.replaceChildren(H().mk('h3', 'hp-h', 'Try it on'), H().empty('Try it on is off on this server.')); return; }
  const o = await outfits(), found = [['Today', o.today], ['Tomorrow', o.tomorrow]].map(([d, l]) => [d, (l || []).find((p) => p.id === plan)]).find(([, p]) => p);
  try {
    const look = await api('/v1/tryon/look?plan=' + encodeURIComponent(plan));
    await show(v, look, { plan, starts: found ? found[1].starts : '', title: found ? planTitle(found[0], found[1]) : 'This plan' });
  } catch (e) { failed(v, e); }
  shapes();
}
export function inline(el, card) {
  S.H = S.H || window.JarvisHelpers;
  if (!el || !card || !H()) return;
  if (S.card) dispose(S.card);
  S.card = viewer(el, 'card');
  dressed(S.card, card).catch(() => {});
}
async function dressed(v, card) { // exactly the card's pieces, by ids (A's ?pieces=); its covered slots stay covered
  v.covered = (card.slots || []).filter((s) => s.private).map((s) => ({ slot: s.slot, private: true, words: COVERED, readiness: '' }));
  v.plan = card.plan || null;
  const list = [];
  (card.slots || []).forEach((s) => { if (!s.private) s.pieces.forEach((p) => list.push({ slot: s.slot, piece: p })); });
  try {
    if (!S.tryon) await readTryon();
    const look = await lookOf(v, query(v, list));
    const code = String(card.code || '').replace(/_/g, ' ');
    await show(v, look, { plan: card.plan, title: 'Your look' + (code ? ' \u00b7 ' + code : '') });
  } catch (e) { failed(v, e); draw(v); }
}
export function garment(file) { // D22: the picture waits for See it on me; nothing is sent by this call
  if (!(file instanceof Blob)) return;
  if (S.me && S.el.me && document.contains(S.el.me)) S.me.take(file); else S.file = file;
  if (window.JarvisDeck) window.JarvisDeck.open('helpers', { focus: true });
  const tab = document.getElementById('hpt-wardrobe');
  if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
  setTimeout(() => { if (S.el.me && S.el.me.scrollIntoView) S.el.me.scrollIntoView({ block: 'start' }); }, 0);
}
document.addEventListener('jarvis:tryon-open', (e) => open((e.detail || {}).plan));
document.addEventListener('jarvis:wardrobe-fresh', () => { S.photos = null; if (S.sec && S.sec.look) refresh(S.sec); });
document.addEventListener('visibilitychange', () => rest(document.hidden));
window.addEventListener('pagehide', () => rest(true));
document.addEventListener('jarvis:theme', () => { [S.sec, S.card].forEach((v) => { if (v && v.stage) paint(v); }); });
