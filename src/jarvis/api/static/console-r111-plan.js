// src/jarvis/api/static/console-r111-plan.js -- R11.1 Part A (docs/plans/r11-1-observations.md D0,
// D4-D6, D21-A): what the console shows for a calendar batch and a followed plan.
//   Approvals   a calendar_create_events card lists every event it will add, in a scrolling list
//               drawn from the card's own arguments; a series_reschedule card keeps its two head
//               lines and shows every "old date -> new date" line in the same kind of list.
//               Approve and Decline stay the console's own (console-approvals.js).
//   Check-ins   above the Approvals list (GET /v1/series): "Session 7 of 60 ... did it happen?"
//               with Done and Skipped (POST /v1/series/answer), and "Propose new dates" for a plan
//               whose skipped session has no re-plan card waiting (POST /v1/series/replan).
//   Reply card  what an approved batch did (ChatResponse.cards, kind "batch"): JARVIS's own words,
//               "Undo all" (POST /v1/series/batches/<id>/undo: the owner's own press, armed by a
//               first tap, run by a second) and, when some failed, "Retry the N"
//               (POST /v1/series/batches/retry: a card through the same path).
// Loaded by console-r111.js (an ES module). Existing classes and tokens only (D0); every server
// string reaches the page through textContent; ASCII source. A press that leaves a card says so
// with jarvis:approvals-stale (console-approvals.js reloads the Approvals list).
const F = window.JarvisFixes;
const CREATE = 'calendar_create_events', MOVE = 'series_reschedule';
const BATCH = /^b[0-9a-f]{16}$/;
const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/;
const MOVE_LINE = /^\d{1,3}\. \S.{0,60} \u2192 \S.{0,60}$/;
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MAX_EVENTS = 100, MAX_MOVES = 200, MAX_SHOWN = 3;
const ARM_MS = 6000, RELOAD_MS = 60000;
const ITEM_KEYS = ['n', 'summary', 'start', 'end', 'description', 'location', 'reminders_minutes', 'why'];
const DOT = ' \u00b7 ';

const A = () => window.JarvisApprovals || null;
const arr = (v) => (Array.isArray(v) ? v : []);
const hidden = (() => { // the console's one rule for characters that can't be seen (console-text.js)
  const T = window.JarvisText;
  try { return T ? new RegExp(T.INVISIBLE_CLASS, 'gu') : null; } catch (_) { return null; }
})();
/** One line of plain text; a character that can't be seen is shown as [U+XXXX], as cards do. */
function txt(v, max) {
  const s = typeof v === 'string' ? v : '';
  const seen = hidden ? s.replace(hidden, (c) => `[U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}]`) : s;
  return seen.replace(/\s+/g, ' ').trim().slice(0, max || 300);
}
function button(label, cls, onClick) {
  const b = F.mk('button', cls, label);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}
function words(e) {
  const m = e && typeof e.message === 'string' ? txt(e.message, 200) : '';
  return m && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'That couldn\u2019t be done just now, Sir.';
}
const stale = () => document.dispatchEvent(new CustomEvent('jarvis:approvals-stale'));
const openSession = () => { const a = A(); return a && typeof a.session === 'function' ? a.session() || null : null; };

// ---- Approvals: the events a batch adds, the sessions a re-plan moves ---------------------------
/** "Mon 16 Nov 2026" and "19:00" from an ISO time, as it is written (never shifted by a zone). */
function stamp(iso) {
  const m = ISO.exec(typeof iso === 'string' ? iso : '');
  if (!m) return null;
  const day = DAYS[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()], month = MONTHS[+m[2] - 1];
  if (!day || !month) return null;
  return { day: `${day} ${+m[3]} ${month} ${m[1]}`, time: m[4] ? `${m[4]}:${m[5]}` : '' };
}
function eventLine(e) {
  if (!e || typeof e !== 'object') return '(not an event)';
  const title = txt(e.summary, 120) || '(no title)', a = stamp(e.start), b = stamp(e.end);
  if (!a) return title;
  const span = a.time ? `, ${a.time}${b && b.time ? '-' + b.time : ''}` : '';
  const place = txt(e.location, 60);
  return `${a.day}${span}${DOT}${title}${place ? DOT + place : ''}`;
}
function listBox(lines, label) {
  const ol = F.mk('ol', 'plan-list');
  ol.tabIndex = 0; // a keyboard can scroll it
  ol.setAttribute('aria-label', label);
  lines.forEach((line) => ol.append(F.mk('li', '', line)));
  return ol;
}
function decorate() {
  const host = document.getElementById('approvals'), a = A();
  if (!host || !a || typeof a.cards !== 'function') return;
  const cards = arr(a.cards());
  host.querySelectorAll('.approval').forEach((el) => {
    if (el.querySelector('.plan-list')) return;
    const card = cards.find((c) => c && c.id === el.dataset.id);
    const p = el.querySelector('p'), pre = el.querySelector('pre');
    if (!card || !p || !pre) return;
    if (card.tool === CREATE) {
      const events = arr(card.arguments && card.arguments.events).slice(0, MAX_EVENTS);
      const lines = events.map((e, i) => `${i + 1}. ${eventLine(e)}`);
      if (lines.length) pre.before(listBox(lines, `The ${lines.length} events this card adds`));
    } else if (card.tool === MOVE) {
      const all = String(card.summary || '').split('\n').map((l) => txt(l, 200)).filter(Boolean);
      const moves = all.filter((l) => MOVE_LINE.test(l)).slice(0, MAX_MOVES);
      if (!moves.length) return;
      p.textContent = all.filter((l) => !MOVE_LINE.test(l)).join('\n');
      pre.before(listBox(moves, `The ${moves.length} sessions this card moves: the old date, then the new one`));
    }
  });
}

// ---- Check-ins above the Approvals list ---------------------------------------------------------
let box = null, said = null; // made once the console's helpers are there (the last block)
let view = { plans: [], waiting: [] }, loading = null, loadedAt = 0, saidTimer = 0;

function say(text, bad) {
  said.textContent = txt(text, 300);
  said.classList.toggle('bad', !!bad);
  clearTimeout(saidTimer);
  if (said.textContent) saidTimer = setTimeout(() => { said.textContent = ''; render(); }, 20000);
}
async function press(card, path, body, after) {
  card.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    const r = await F.api(path, { body: Object.assign({ session_id: openSession() }, body) });
    say(r && r.message, r && r.refused === true);
    if (r && r.pending === true) stale();
  } catch (e) { say(words(e), true); }
  if (after) after();
  load();
}
function checkCard(w) {
  const card = F.mk('div', 'mcard plan-check');
  card.append(F.mk('p', 'plan-q', txt(w.text, 200)));
  const row = F.mk('div', 'actions');
  const answer = (what) => press(card, '/v1/series/answer', { answer: what, series: w.plan, session: w.session });
  row.append(button('Done', 'btn primary lift', () => answer('done')), button('Skipped', 'btn lift', () => answer('skipped')));
  card.append(row);
  return card;
}
function replanCard(p) {
  const card = F.mk('div', 'mcard plan-check');
  card.append(F.mk('p', 'plan-q', txt(p.replan, 200)));
  const row = F.mk('div', 'actions');
  row.append(button('Propose new dates', 'btn lift', () => press(card, '/v1/series/replan', { series: p.id })));
  card.append(row);
  return card;
}
const isWaiting = (w) => !!w && typeof w === 'object' && typeof w.plan === 'string' && Number.isInteger(w.session) && typeof w.text === 'string' && !!w.text;
const needsDates = (p) => !!p && typeof p === 'object' && typeof p.id === 'string' && typeof p.replan === 'string' && !!p.replan;
function render() {
  const a = A();
  const moving = arr(a && typeof a.cards === 'function' ? a.cards() : []).some((c) => c && c.tool === MOVE);
  box.textContent = '';
  view.waiting.filter(isWaiting).slice(0, MAX_SHOWN).forEach((w) => box.append(checkCard(w)));
  if (!moving) view.plans.filter(needsDates).slice(0, MAX_SHOWN).forEach((p) => box.append(replanCard(p)));
  if (said.textContent) box.append(said);
  box.hidden = !box.childElementCount;
}
function load() {
  if (loading) return loading;
  loading = (async () => {
    try {
      const r = await F.api('/v1/series');
      view = { plans: arr(r && r.plans), waiting: arr(r && r.waiting) };
    } catch (_) { view = { plans: [], waiting: [] }; } // signed out, or plans are off: nothing to show
    loadedAt = Date.now(); loading = null;
    render();
  })();
  return loading;
}
const reload = () => { if (Date.now() - loadedAt > RELOAD_MS) load(); };

// ---- Under a reply: what an approved batch did --------------------------------------------------
function retryItems(c) {
  return arr(c.retry).slice(0, MAX_EVENTS).filter((e) => e && typeof e === 'object' && Number.isInteger(e.n)).map((e) => {
    const out = {};
    ITEM_KEYS.forEach((k) => { if (e[k] !== undefined && e[k] !== null && e[k] !== '') out[k] = e[k]; });
    return out;
  });
}
function batchCard(c) {
  const card = F.mk('section', 'mcard plan-batch');
  card.setAttribute('aria-label', 'What was added to your calendar');
  const note = F.mk('p', 'plan-said');
  note.setAttribute('role', 'status');
  const row = F.mk('div', 'actions');
  const tell = (text, bad) => { note.textContent = txt(text, 300); note.classList.toggle('bad', !!bad); };
  const there = (Number.isInteger(c.created) ? c.created : 0) + (Number.isInteger(c.already) ? c.already : 0);
  if (there > 0) {
    let armed = 0;
    const undo = button('Undo all', 'btn lift', async () => {
      if (!armed) { // the first tap only arms it: one tap never removes a whole batch
        undo.textContent = `Tap again to remove all ${there}`;
        tell(`Tap again to remove all ${there} events of this batch from your calendar.`);
        armed = setTimeout(() => { armed = 0; undo.textContent = 'Undo all'; tell(''); }, ARM_MS);
        return;
      }
      clearTimeout(armed); armed = 0; undo.disabled = true;
      try {
        const r = await F.api(`/v1/series/batches/${encodeURIComponent(c.batch)}/undo`, { body: {} });
        tell(r && r.message, r && r.unavailable === true);
        undo.textContent = 'Undo all';
        if (r && r.unavailable === true) undo.disabled = false; else { stale(); load(); }
      } catch (e) { tell(words(e), true); undo.textContent = 'Undo all'; undo.disabled = false; }
    });
    row.append(undo);
  }
  const items = retryItems(c);
  if (items.length) {
    const again = button(`Retry the ${items.length}`, 'btn lift', async () => {
      again.disabled = true;
      const body = { batch: c.batch, events: items, session_id: openSession() };
      if (txt(c.name, 60)) body.name = txt(c.name, 60);
      try {
        const r = await F.api('/v1/series/batches/retry', { body });
        tell(r && r.pending === true ? `${txt(r.message, 200)} It is waiting in Approvals.` : r && r.message, r && r.refused === true);
        if (r && r.pending === true) stale(); else again.disabled = false;
      } catch (e) { tell(words(e), true); again.disabled = false; }
    });
    row.append(again);
  }
  card.append(F.mk('p', 'plan-q', txt(c.words, 300)));
  if (row.childElementCount) card.append(row);
  card.append(note);
  return card;
}
/** console-media.js hands every reply's cards here; only kind "batch" is this part's. */
function cards(row, list) {
  if (!row || !Array.isArray(list)) return null;
  const mine = list.filter((c) => c && typeof c === 'object' && c.kind === 'batch' && BATCH.test(c.batch || '') && txt(c.words));
  if (!mine.length) return null;
  const wrap = F.mk('div', 'mcards');
  mine.slice(0, MAX_SHOWN).forEach((c) => wrap.append(batchCard(c)));
  row.appendChild(wrap);
  return wrap;
}

if (F) {
  box = F.mk('div', 'plan-checks');
  box.id = 'planChecks'; box.hidden = true;
  said = F.mk('p', 'plan-said');
  said.setAttribute('role', 'status');
  F.part('plan', { cards, decorate, reload: load });
  const host = document.getElementById('approvals');
  if (host && host.parentNode) {
    host.parentNode.insertBefore(box, document.getElementById('approveAll') || host);
    new MutationObserver(() => { decorate(); render(); }).observe(host, { childList: true });
    decorate();
  }
  document.addEventListener('jarvis:ready', () => load());
  document.addEventListener('jarvis:reply', (e) => { if (e.detail && e.detail.tools > 0) load(); });
  document.addEventListener('jarvis:panel', (e) => { if (e.detail && e.detail.id === 'approvals' && e.detail.open) reload(); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') reload(); });
  const con = window.JarvisConsole;
  if (con && typeof con.ready === 'function' && con.ready()) load();
}
