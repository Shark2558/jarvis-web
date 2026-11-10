// src/jarvis/api/static/console.js — JARVIS web console (no build step; CSP script-src 'self').
// Talks to the API (chat, brains, approvals, audit, conversations) and renders the panels' content.
// All server text reaches the DOM via textContent or esc(); never raw innerHTML.
// The Command Deck (console-deck.js) shows vitals from the events this file fires:
//   jarvis:vitals {turns, brain, model, cost (₹, this conversation), rttMs?}
//   jarvis:approvals {count, fresh}                    jarvis:audit {verified, count}
//   jarvis:event {kind, text, at, live?}               jarvis:integrations {google, email}
//   jarvis:ready {returning} (signed in, booting)      jarvis:reply {refused?} (spend may have
//                                                      changed: console-usage.js reloads it)
// Costs are shown in rupees only ("≈ ₹", JarvisDeck.rupees): the API sends *_inr beside *_usd.
// console-brief.js uses the same transport through window.JarvisConsole.api, and asks
// window.JarvisConsole.ready() when it starts in case it arrived after jarvis:ready.
// Slice 8: jarvis:brain {id, label, trains, tools} (also JarvisConsole.brain()) for the Memory
// panel; a reply's `memory_used: [{id, text}]` becomes a "Used N memories" chip (text only).
// Slice 9 (voice): window.JarvisChat {send(text, {channel}), busy(), honorific(), raw(path, opts)};
// jarvis:turn {channel} / jarvis:turn-end {channel, ok} around a turn, jarvis:answer {channel, text,
// approvals} after a reply, jarvis:switch when the owner starts or opens another conversation.
// Slice 10 B: a reply's (or restored turn's) `sources` → the Sources row (console-web.js, JarvisSources).
// Slice 10 (console-attach.js): files waiting in window.JarvisAttach go with the next message as
// `attachments: [id]`; jarvis:attach re-checks the Send button (disabled while one is uploading).
// Slice 11 (console-approve-all.js): jarvis:approvals also carries `cards`; window.JarvisApprovals.
// Slice 11 review: the approvals decision path (decide / runDecision) is console-approvals.js.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // An approval card must read exactly as it is: bidi overrides, zero-width and control
  // characters (which can turn "exe.gpj" into "jpg.exe" on screen) are shown as visible
  // [U+202E] markers. The server already strips them from summaries; this also covers the
  // raw arguments.
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  // Memory text keeps ZWNJ/ZWJ (U+200C/U+200D), which Indic scripts and emoji need.
  const INVISIBLE_KEEP_JOINERS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const visible = (s) => String(s).replace(INVISIBLE, (c) => `[U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}]`);
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  const ssGet = (k) => { try { return sessionStorage.getItem(k) || ''; } catch (_) { return ''; } };
  const ssSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) {} };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const note = (kind, text, at, live) => emit('jarvis:event', { kind, text, at: at ?? Date.now(), live: live !== false });
  // visual engine (console-fx.js) and deck (console-deck.js); the console still works without them
  const FX = window.JarvisFX || { core: (s) => `<span class="core ${s === 'lg' || s === 'sm' ? s : ''}" aria-hidden="true"></span>`,
    setBusy() {}, setAlert() {}, ripple() {}, refresh() {} };
  const Deck = window.JarvisDeck || { open() {}, close() {}, isOpen: () => true, isPhone: () => false };
  const rupees = (v) => (typeof Deck.rupees === 'function' ? Deck.rupees(v) : ''); // never a dollar sign
  const LIMIT_FALLBACK = 'This month\'s AI spending limit is used up. Raise it in Vitals, or switch to the free brain.';
  const CONFLICT_FALLBACK = 'This conversation changed in another window — reloaded. Check whether your message is there before sending it again.';

  const state = { sessionId: null, authMode: 'token', token: ssGet('jarvis_token'), honorific: 'Sir',
    brains: [], brain: null, busy: false, seenApprovals: null, seenAudit: new Set() };
  let readyDetail = null; // the last jarvis:ready detail (frozen); null while signed out
  let lastCards = []; // the approval cards last rendered
  let brainDetail = null; // the brain answering now (frozen): {id, label, trains, tools}; null until known

  const SUGGESTIONS = [
    'What can you help me with?',
    "What's on my calendar today?",
    'List my open tasks',
    'Draft a polite follow-up message',
  ];

  // ---- transport: cookie + anti-CSRF header, or bearer token in token mode ------------------
  // Only this server's own paths: one leading "/". "//host" and "/\host" are read by browsers as
  // another host, and a relative path depends on the page address; none of them ever gets the token.
  const OWN_PATH = /^\/(?![/\\])/;
  // R6 D10: while a guest watches the build book, every console of the owner is held: the server
  // answers 423 (show_locked) and this console goes to the show, the one page it may open until
  // the owner's passkey resumes it.
  const SHOW_PAGE = '/book/show';
  function toShow() {
    try { window.location.replace(SHOW_PAGE); } catch (_) {}
    const err = new Error('JARVIS is showing the build book.'); err.status = 423; err.code = 'show_locked'; return err;
  }
  async function api(path, opts = {}) {
    if (typeof path !== 'string' || !OWN_PATH.test(path)) throw new Error('Not a JARVIS API path.');
    const headers = Object.assign({ 'X-Requested-With': 'JARVIS' }, opts.headers || {});
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (state.authMode === 'token' && state.token) headers['Authorization'] = 'Bearer ' + state.token;
    const r = await fetch(path, { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
      headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined, credentials: 'same-origin' });
    if (r.status === 423) throw toShow();
    if (r.status === 401) { // every non-2xx error carries .status: callers leave a 401 to the gate
      showGate(); const err = new Error('Sign in required.'); err.status = 401; throw err;
    }
    if (!r.ok) {
      let detail = r.statusText, code = '';
      try { // the app's shape: {error: code, detail: plain words}; err.code carries the code
        const j = await r.json(), d = j.detail;
        code = typeof j.error === 'string' ? j.error : '';
        if (d && typeof d === 'object' && !Array.isArray(d)) { // tolerate {detail: {code, message}}
          code = code || (typeof d.code === 'string' ? d.code : '');
          detail = typeof d.message === 'string' && d.message ? d.message : code || detail;
        } else detail = d || j.error || detail;
      } catch (_) {}
      const err = new Error(detail); err.status = r.status; if (code) err.code = code; throw err;
    }
    return r.status === 204 ? null : r.json();
  }
  /** Same transport for bytes (voice: audio/wav up, audio/mpeg down). The caller reads the
   *  Response; a 401 still goes to the sign-in gate. The token never leaves this file. */
  async function raw(path, opts = {}) {
    if (typeof path !== 'string' || !OWN_PATH.test(path)) throw new Error('Not a JARVIS API path.');
    const headers = Object.assign({}, opts.headers || {}, { 'X-Requested-With': 'JARVIS' });
    if (state.authMode === 'token' && state.token) headers['Authorization'] = 'Bearer ' + state.token;
    const r = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body, signal: opts.signal, credentials: 'same-origin' });
    if (r.status === 423) throw toShow();
    if (r.status === 401) { showGate(); const err = new Error('Sign in required.'); err.status = 401; throw err; }
    return r;
  }

  // ---- sign-in gate -------------------------------------------------------------------------
  const LOCK = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="4" y="9" width="12" height="8" rx="2.2"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/></svg>';
  function showGate() {
    readyDetail = null; // signed out: a panel script arriving now waits for the next jarvis:ready
    const box = $('gateBox');
    const head = FX.core('lg') + '<h2 id="gateTitle">JARVIS</h2>';
    if (state.authMode === 'google') {
      box.innerHTML = head + '<p>Your private assistant. Sign in with the Google account registered as the owner.</p>' +
        `<button class="cta lift" id="gBtn">${LOCK}Sign in with Google</button>` +
        '<div class="fine">Any other account is refused.</div>';
      $('gBtn').addEventListener('click', () => { location.href = '/auth/login'; });
    } else {
      box.innerHTML = head + '<p>Enter the access token for this server.</p>' +
        '<input id="tokIn" type="password" placeholder="Access token" autocomplete="current-password" aria-label="Access token">' +
        `<button class="cta lift" id="tokBtn">${LOCK}Continue</button>`;
      const go = () => { state.token = $('tokIn').value.trim(); if (!state.token) return; ssSet('jarvis_token', state.token); hideGate(); boot(); };
      $('tokBtn').addEventListener('click', go);
      $('tokIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      setTimeout(() => $('tokIn').focus(), 50);
    }
    $('gate').classList.add('show'); FX.refresh();
  }
  function hideGate() { $('gate').classList.remove('show'); FX.refresh(); }

  // ---- conversation -------------------------------------------------------------------------
  function greeting() {
    const h = new Date().getHours();
    return `Good ${h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'}, ${state.honorific}.`;
  }
  function renderWelcome() {
    const log = $('log'); log.innerHTML = '';
    const w = document.createElement('div'); w.className = 'welcome'; w.id = 'welcome';
    w.innerHTML = FX.core('lg') + '<h1></h1><p>How can I help?</p><div class="chips"></div>';
    w.querySelector('h1').textContent = greeting();
    const chips = w.querySelector('.chips');
    SUGGESTIONS.forEach(s => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'chip lift'; b.textContent = s;
      b.addEventListener('click', () => send(s)); chips.appendChild(b);
    });
    log.appendChild(w); FX.refresh();
  }
  function clearWelcome() { const w = $('welcome'); if (w) { w.remove(); FX.refresh(); } }
  function scrollDown() { const s = $('scroll'); s.scrollTop = s.scrollHeight; }

  function addMsg(role, text, metaParts) {
    clearWelcome();
    if (role === 'sys' || role === 'error' || role === 'limit') { // limit: the monthly spending limit said no
      const d = document.createElement('div'); d.className = 'sys' + (role === 'error' ? ' error' : role === 'limit' ? ' limit' : '');
      d.setAttribute('role', role === 'error' ? 'alert' : 'status'); d.textContent = text;
      $('log').appendChild(d); scrollDown(); return;
    }
    const row = document.createElement('div'); row.className = 'row ' + role;
    const b = document.createElement('div'); b.className = 'bubble';
    b.textContent = text; row.appendChild(b);
    if (metaParts && metaParts.length) {
      const m = document.createElement('div'); m.className = 'meta';
      metaParts.filter(Boolean).forEach(p => { const s = document.createElement('span'); s.textContent = p; m.appendChild(s); });
      row.appendChild(m);
    }
    $('log').appendChild(row); scrollDown();
    return row;
  }

  // ---- "Used N memories" (slice 8 D10): what JARVIS sent about the owner with this reply ---------
  // The texts are the owner's own notes, but still untrusted data: textContent only, capped.
  let usedSeq = 0;
  function memoriesUsed(list) {
    return (Array.isArray(list) ? list : []).slice(0, 50)
      .map(m => (m && typeof m === 'object' && typeof m.text === 'string' ? m.text.replace(INVISIBLE_KEEP_JOINERS, '').trim().slice(0, 400) : ''))
      .filter(Boolean);
  }
  function svgIcon(paths) {
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 20 20'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.6'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
    paths.forEach(d => { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p); });
    return svg;
  }
  const MEMORY_PATHS = ['M5 3.5h9a1.5 1.5 0 0 1 1.5 1.5v11.5H6.5A1.5 1.5 0 0 1 5 15z', 'M5 15a1.5 1.5 0 0 1 1.5-1.5h9', 'M8.5 3.5v5l1.75-1.3L12 8.5v-5'];
  function memoryChip(row, texts) {
    let meta = row.querySelector('.meta');
    if (!meta) { meta = document.createElement('div'); meta.className = 'meta'; row.appendChild(meta); }
    const listId = 'mused-' + (++usedSeq);
    const chip = document.createElement('button'); chip.type = 'button'; chip.className = 'mchip';
    chip.setAttribute('aria-expanded', 'false'); chip.setAttribute('aria-controls', listId);
    const words = document.createElement('span');
    words.textContent = `Used ${texts.length} ${texts.length === 1 ? 'memory' : 'memories'}`;
    chip.append(svgIcon(MEMORY_PATHS), words);
    const box = document.createElement('div'); box.className = 'mused'; box.id = listId; box.hidden = true;
    const ul = document.createElement('ul');
    texts.forEach(t => { const li = document.createElement('li'); li.textContent = t; ul.appendChild(li); });
    const manage = document.createElement('button'); manage.type = 'button'; manage.className = 'mopen'; manage.textContent = 'Open Memory';
    manage.addEventListener('click', () => Deck.open('memory', { focus: true }));
    box.append(ul, manage);
    chip.addEventListener('click', () => {
      const show = box.hidden;
      box.hidden = !show; chip.setAttribute('aria-expanded', String(show));
    });
    meta.appendChild(chip); row.appendChild(box);
  }
  function showTyping(on) {
    const t = $('typing');
    if (on && !t) {
      const row = document.createElement('div'); row.className = 'row jarvis'; row.id = 'typing';
      row.innerHTML = '<div class="bubble typing" role="status" aria-label="JARVIS is thinking">' +
        '<span class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><span class="lbl" aria-hidden="true">Processing</span></div>';
      $('log').appendChild(row); scrollDown();
    } else if (!on && t) { t.remove(); }
  }

  // ---- approvals, activity, vitals ----------------------------------------------------------
  /** A card's summary as one paragraph. Security review SEC-5: a WhatsApp draft's quoted text gets
   *  its own paragraph with dir="auto" (a right-to-left draft reads in its own direction); the head
   *  lines and every other card stay as they were. */
  function summaryHtml(a) {
    const wa = a.tool === 'whatsapp_draft' && window.JarvisWhatsApp ? window.JarvisWhatsApp.quoteParts(a.summary) : null;
    if (!wa) return `<p>${esc(visible(a.summary))}</p>`;
    return `<p>${esc(visible(wa.head))}</p><p class="waquote" dir="auto">${esc(visible(wa.quote))}</p>`;
  }
  function renderApprovals(list) {
    const el = $('approvals');
    $('approvalCount').textContent = list.length ? `${list.length} waiting` : '';
    FX.setAlert(list.length > 0);
    const ids = new Set(list.map(a => a.id));
    const fresh = list.filter(a => !state.seenApprovals || !state.seenApprovals.has(a.id));
    const first = state.seenApprovals === null;
    state.seenApprovals = ids;
    fresh.forEach(a => note('approval', `Approval waiting · ${String(a.tool).replace(/_/g, ' ')}`));
    lastCards = list; // slice 11: console-approve-all.js offers "Approve all (n)" over them
    emit('jarvis:approvals', { count: list.length, fresh: fresh.length > 0 || (first && list.length > 0), cards: list });
    if (!list.length) { el.innerHTML = '<div class="empty">Nothing waiting.</div>'; return; }
    // slice 10 D: a card whose action can't be undone, while the owner requires a passkey, is approved
    // with one (console-permissions.js runs the browser's own WebAuthn prompt)
    el.innerHTML = list.map(a => `
      <div class="approval" data-id="${esc(a.id)}" data-sid="${esc(a.session_id || '')}" data-passkey="${a.passkey_required === true ? '1' : ''}">
        <div class="title">${esc(a.tool.replace(/_/g, ' '))} <span class="tag">${esc(a.risk)}</span></div>
        ${summaryHtml(a)}
        <pre>${esc(visible(JSON.stringify(a.arguments, null, 2)))}</pre>
        <div class="actions"><button class="btn primary approve lift">${a.passkey_required === true ? 'Approve with passkey' : 'Approve'}</button><button class="btn decline lift">Decline</button></div>
        <p class="perr" role="alert"></p>
      </div>`).join('');
    el.querySelectorAll('.approval').forEach(card => {
      const id = card.dataset.id; const sid = card.dataset.sid || null;
      const tool = card.querySelector('.title').firstChild.textContent.trim();
      card.querySelector('.approve').addEventListener('click', () => decide(id, 'approve', card, sid, tool, card.dataset.passkey === '1'));
      card.querySelector('.decline').addEventListener('click', () => decide(id, 'decline', card, sid, tool));
    });
  }
  const AUDIT_WORDS = { executed: 'Done', awaiting_confirmation: 'Waiting for you', denied: 'Blocked', declined: 'Declined', error: 'Failed' };
  function renderAudit(data) {
    const ok = $('auditOk');
    ok.textContent = data.verified ? 'Log verified' : 'Log tampered';
    ok.className = 'verified ' + (data.verified ? 'ok' : 'bad');
    $('auditMeta').textContent = data.entries.length ? `${data.entries.length} ${data.entries.length === 1 ? 'entry' : 'entries'}` : '';
    emit('jarvis:audit', { verified: !!data.verified, count: data.entries.length });
    data.entries.forEach(e => { // each audit entry becomes one real event (radar + ruler), once
      const key = `${e.at}|${e.tool}|${e.outcome}`; if (state.seenAudit.has(key)) return;
      state.seenAudit.add(key);
      const at = Date.parse(e.at || '');
      note(e.outcome === 'awaiting_confirmation' ? 'approval' : e.outcome === 'error' ? 'error' : 'tool',
        `${String(e.tool).replace(/_/g, ' ')} · ${AUDIT_WORDS[e.outcome] || e.outcome}`, Number.isFinite(at) ? at : Date.now(), false);
    });
    const el = $('audit'); const entries = data.entries.slice(-40).reverse();
    if (!entries.length) { el.innerHTML = '<div class="empty">JARVIS hasn\'t used any tools yet.</div>'; return; }
    const cls = o => o === 'executed' ? 'ok' : (o === 'awaiting_confirmation' ? 'warn' : (['denied', 'declined', 'error'].includes(o) ? 'bad' : ''));
    const words = AUDIT_WORDS;
    el.innerHTML = '<div class="list">' + entries.map(e => `
      <div class="event"><span class="dot ${cls(e.outcome)}"></span>
        <span class="what">${esc(String(e.tool).replace(/_/g, ' '))}<small>${esc(words[e.outcome] || e.outcome)}</small></span>
        <time>${esc(localTime(e.at))}</time></div>`).join('') + '</div>';
  }
  function localTime(iso) {
    const d = new Date(iso || '');
    return isNaN(d) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  function brainLabel(id) { const b = state.brains.find(x => x.id === id); return b ? b.label : id; }
  function renderStats(r, rttMs) {
    const d = { brain: r.brain ? brainLabel(r.brain) : (currentBrain() ? currentBrain().label : null), model: r.model || null,
      turns: Number.isFinite(r.turn_count) ? r.turn_count : 0, cost: Number.isFinite(r.total_cost_inr) ? r.total_cost_inr : 0 };
    if (Number.isFinite(rttMs)) d.rttMs = rttMs;
    emit('jarvis:vitals', d);
  }
  // Each refresh costs database reads (free quota: 50k/day), so the panel refreshes only when
  // something in it can have changed: at start, after tool use, approvals, or a decision.
  // Approvals and the audit log load independently; a failure shows "—" (never a fake 0), says so
  // on the deck's log line, and offers Retry. A 401 is the sign-in gate's job, not an error here.
  async function refreshSide() {
    try { renderApprovals(await api('/v1/approvals')); }
    catch (e) { if (e.status !== 401) sideFailed('approvals', e); }
    try { renderAudit(await api('/v1/audit?limit=40')); }
    catch (e) { if (e.status !== 401) sideFailed('audit', e); }
  }
  function sideFailed(which, err) {
    const approvals = which === 'approvals';
    const el = $(approvals ? 'approvals' : 'audit');
    el.innerHTML = '';
    const msg = document.createElement('div'); msg.className = 'empty';
    msg.textContent = approvals ? 'Couldn\'t load approvals.' : 'Couldn\'t load the activity log.';
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn lift retry'; retry.textContent = 'Retry';
    retry.addEventListener('click', () => { retry.disabled = true; refreshSide(); });
    el.append(msg, retry);
    if (approvals) { $('approvalCount').textContent = ''; emit('jarvis:approvals', { count: null, fresh: false }); }
    else { const ok = $('auditOk'); ok.textContent = 'Log unavailable'; ok.className = 'verified'; $('auditMeta').textContent = ''; emit('jarvis:audit', { verified: null, count: 0 }); }
    note('error', `${approvals ? 'Approvals' : 'Activity log'} unavailable · ${err && err.message ? err.message : 'error'}`);
  }
  function bumpCurrentConvo(turns) {
    const row = document.querySelector(`.convo[data-id="${CSS.escape(state.sessionId || '')}"] .open small`);
    if (row) row.textContent = `${when(new Date().toISOString())} · ${turns} ${turns === 1 ? 'message' : 'messages'}`;
  }

  // ---- saved conversations (slice 5: they survive JARVIS going to sleep) --------------------
  const TRASH = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h12M8 6V4.5h4V6M6 6l.7 10h6.6L14 6"/></svg>';
  function setSession(id) {
    state.sessionId = id || null;
    if (id) lsSet('jarvis_session', id); else { try { localStorage.removeItem('jarvis_session'); } catch (_) {} }
    document.querySelectorAll('.convo').forEach(r => r.classList.toggle('current', r.dataset.id === state.sessionId));
  }
  function when(iso) {
    const d = new Date(iso || ''); if (isNaN(d)) return '';
    const today = new Date().toDateString() === d.toDateString();
    return today ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }
  async function refreshConvos() {
    let list = [];
    try { list = await api('/v1/sessions?limit=30'); } catch (_) { return; }
    const el = $('convos');
    $('convoCount').textContent = list.length ? String(list.length) : '';
    if (!list.length) { el.innerHTML = '<div class="empty">No saved conversations yet.</div>'; return; }
    el.innerHTML = '';
    list.forEach(c => {
      const row = document.createElement('div'); row.className = 'convo'; row.dataset.id = c.id;
      row.classList.toggle('current', c.id === state.sessionId);
      const open = document.createElement('button'); open.type = 'button'; open.className = 'open';
      const b = document.createElement('b'); b.textContent = c.title || 'Untitled conversation';
      const sm = document.createElement('small'); sm.textContent = `${when(c.updated_at)} · ${c.turn_count} ${c.turn_count === 1 ? 'message' : 'messages'}`;
      open.append(b, sm); open.addEventListener('click', () => openConversation(c.id));
      const del = document.createElement('button'); del.type = 'button'; del.className = 'icon-btn del';
      del.innerHTML = TRASH; del.setAttribute('aria-label', 'Delete conversation: ' + (c.title || 'Untitled'));
      del.addEventListener('click', () => askDelete(row, c.id));
      row.append(open, del); el.appendChild(row);
    });
  }
  function askDelete(row, id) {
    if (row.querySelector('.confirm')) return;
    const box = document.createElement('div'); box.className = 'confirm'; box.setAttribute('role', 'alert');
    const t = document.createElement('span'); t.textContent = 'Delete for good? This cannot be undone.';
    const yes = document.createElement('button'); yes.type = 'button'; yes.className = 'btn danger lift'; yes.textContent = 'Delete';
    const no = document.createElement('button'); no.type = 'button'; no.className = 'btn lift'; no.textContent = 'Keep';
    const del = row.querySelector('.del');
    const keep = () => { box.remove(); if (del) del.focus(); };
    no.addEventListener('click', keep);
    box.addEventListener('keydown', (e) => { // Esc here means Keep; it must not close the History panel
      if (e.key !== 'Escape' || e.isComposing) return;
      e.preventDefault(); e.stopPropagation(); keep();
    });
    yes.addEventListener('click', async () => {
      const active = id === state.sessionId;
      if (active && state.busy) { t.textContent = 'JARVIS is still answering here. Delete once the reply has arrived.'; return; }
      yes.disabled = no.disabled = true;
      if (active) busy(true, false); // nothing may write to the conversation while it is being deleted
      try {
        await api(`/v1/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (active) { busy(false); newConversation(); }
        note('info', 'Conversation deleted');
        refreshConvos();
      } catch (e) { box.remove(); addMsg('error', 'Couldn\'t delete that conversation. ' + e.message); }
      finally { if (active && state.busy) busy(false); }
    });
    box.append(t, no, yes); row.appendChild(box); no.focus();
  }
  /** Final review: the WhatsApp drafts GET /v1/sessions/{id} rebuilt, by the reply (turn index)
   *  they belong under. console-whatsapp.js checks every field again; Maps / YouTube never come back. */
  function draftsByTurn(sess) {
    const by = new Map();
    (Array.isArray(sess.drafts) ? sess.drafts : []).forEach(d => {
      if (!d || !Number.isInteger(d.turn) || !d.card || typeof d.card !== 'object') return;
      if (!by.has(d.turn)) by.set(d.turn, []);
      by.get(d.turn).push(d.card);
    });
    return by;
  }
  function renderTranscript(sess) {
    renderWelcome();
    let shown = 0; let last = null;
    const drafts = draftsByTurn(sess);
    sess.turns.forEach((t, i) => {
      if (!t.content || !t.content.trim()) return; // tool exchanges have no text of their own
      if (t.role === 'user') { const row = addMsg('user', t.content); if (Attach()) Attach().show(row, t.attachments); }
      else {
        const row = addMsg('jarvis', t.content, [t.model]); if (window.JarvisSources) window.JarvisSources.render(row, t.sources); last = t;
        if (window.JarvisWhatsApp && drafts.has(i)) window.JarvisWhatsApp.render(row, drafts.get(i));
      }
      shown++;
    });
    if (shown) { addMsg('sys', 'Earlier conversation restored.'); note('info', 'Conversation restored'); }
    else renderWelcome();
    renderStats({ brain: (sess.metadata || {}).brain, model: last ? last.model : null,
      turn_count: sess.turns.length, total_cost_inr: sess.total_cost_inr, latency_ms: null });
    const b = (sess.metadata || {}).brain;
    if (b && state.brains.some(x => x.id === b) && b !== state.brain) { state.brain = b; renderBrains(); }
  }
  async function loadConversation(id) {
    try {
      const sess = await api(`/v1/sessions/${encodeURIComponent(id)}`);
      setSession(sess.id); renderTranscript(sess); return true;
    } catch (e) {
      // forget the remembered conversation only if it is really gone (not on a cold-start 503)
      if (e.status === 404 && (id === state.sessionId || id === lsGet('jarvis_session'))) setSession(null);
      else if (e.status !== 404 && e.status !== 401) addMsg('error', 'Couldn\'t open that conversation. ' + e.message);
      return false;
    }
  }
  /** Open a saved conversation while holding the console, so a send cannot interleave. */
  async function openConversation(id) {
    if (state.busy) return;
    emit('jarvis:switch', {}); // the voice module stops speaking and listening
    busy(true, false);
    try { await loadConversation(id); } finally { busy(false); }
  }
  function newConversation() { emit('jarvis:switch', {}); setSession(null); renderWelcome(); renderStats({}); input.focus(); }
  function startNew() { if (state.busy) return; newConversation(); Deck.open('chat', { focus: true }); note('info', 'New conversation'); }

  // ---- brain selector -----------------------------------------------------------------------
  function currentBrain() { return state.brains.find(b => b.id === state.brain) || state.brains.find(b => b.default) || null; }
  function renderBanner(fallback) {
    const b = currentBrain();
    const text = b ? (b.warning || '') : (fallback || '');
    $('bannerText').textContent = text;
    $('banner').classList.toggle('show', !!text);
    $('brainSel').classList.toggle('training', !!(b && b.trains_on_content));
    // the Memory panel says when memory is kept away from this brain (slice 8 D6)
    const next = b ? Object.freeze({ id: String(b.id), label: String(b.label || b.id),
      trains: b.trains_on_content === true, tools: b.tools_allowed !== false }) : null;
    const same = (x, y) => (x && y ? x.id === y.id && x.trains === y.trains && x.tools === y.tools : x === y);
    if (!same(next, brainDetail)) { brainDetail = next; emit('jarvis:brain', brainDetail); }
  }
  function renderBrains() {
    const sel = $('brainSel');
    sel.innerHTML = state.brains.map(b => `<option value="${esc(b.id)}">${esc(b.label)}</option>`).join('');
    const b = currentBrain(); if (b) { sel.value = b.id; state.brain = b.id; }
    sel.disabled = state.brains.length < 2;
    sel.title = state.brains.length < 2 ? 'Only one brain is set up. Add more by re-running the deploy script.' : 'Switch the AI for this conversation';
    renderBanner();
  }
  async function loadBrains() {
    try {
      state.brains = await api('/v1/brains');
      const saved = lsGet('jarvis_brain');
      state.brain = state.brains.some(b => b.id === saved) ? saved : null;
      renderBrains();
    } catch (_) {}
  }
  $('brainSel').addEventListener('change', () => {
    state.brain = $('brainSel').value; lsSet('jarvis_brain', state.brain); renderBanner();
    const b = currentBrain();
    if (b) {
      addMsg('sys', `Now using ${b.label}.` + (b.tools_allowed ? '' : ' Chat only: tools are off, and earlier messages in this conversation are not shared with it.'));
      note('info', `Brain · ${b.label}`); emit('jarvis:vitals', { brain: b.label });
    }
  });

  // ---- actions ------------------------------------------------------------------------------
  /** One action at a time. `thinking` shows the typing indicator and the Thinking state; loading
   *  or deleting a conversation only holds the console. */
  function busy(on, thinking = true) {
    state.busy = on;
    const show = on && thinking;
    FX.setBusy(show); showTyping(show); syncSend();
  }
  /** After a reply, return focus to the composer only if the owner was there (or nowhere). */
  function refocus() {
    const a = document.activeElement, chat = $('p-chat');
    if (!a || a === document.body || (chat && chat.contains(a))) input.focus();
  }
  const Attach = () => window.JarvisAttach || null; // console-attach.js (loads after this file)
  function syncSend() { $('send').disabled = state.busy || !$('input').value.trim() || !!(Attach() && Attach().busy()); }
  document.addEventListener('jarvis:attach', () => syncSend());
  function handleResponse(r, rttMs, channel) {
    const fresh = r.session_id !== state.sessionId;
    setSession(r.session_id);
    if (r.brain && r.brain !== state.brain && state.brains.some(b => b.id === r.brain)) { state.brain = r.brain; renderBrains(); }
    const meta = [r.brain ? brainLabel(r.brain) : null, r.model, (r.latency_ms / 1000).toFixed(1) + ' s',
      r.cost_inr > 0 ? rupees(r.cost_inr) : null, r.tool_calls ? `${r.tool_calls} tool ${r.tool_calls === 1 ? 'call' : 'calls'}` : null];
    const row = addMsg('jarvis', r.reply, meta);
    const used = memoriesUsed(r.memory_used);
    if (used.length) memoryChip(row, used);
    if (window.JarvisSources) window.JarvisSources.render(row, r.sources);
    if (window.JarvisOffline) window.JarvisOffline.mark(row, r); // R1 C: answered by the laptop
    if (window.JarvisDeleted) window.JarvisDeleted.chips(row, r.undo); // slice 11: Undo chips
    // slice 12: one ChatResponse.cards list; each module renders its own kinds and skips the rest
    if (window.JarvisMedia) window.JarvisMedia.cards(row, r.cards); // places / route / videos
    if (window.JarvisWhatsApp) window.JarvisWhatsApp.render(row, r.cards); // whatsapp drafts
    renderStats(r, rttMs);
    emit('jarvis:reply', { refused: false, tools: Number.isFinite(r.tool_calls) ? r.tool_calls : 0 });
    // slice 9: the voice module speaks it (per "Speak replies"); an approval left waiting after a
    // spoken turn gets the fixed line instead, never the reply's own words (D11)
    emit('jarvis:answer', { channel: channel === 'voice' ? 'voice' : 'text', text: typeof r.reply === 'string' ? r.reply : '',
      approvals: Array.isArray(r.pending_approvals) ? r.pending_approvals.length : 0 });
    note('reply', Number.isFinite(rttMs) ? `Reply · ${Math.round(rttMs)} ms` : 'Reply');
    if (r.tool_calls || (r.pending_approvals || []).length || r.decided) refreshSide();
    if (fresh) refreshConvos(); else bumpCurrentConvo(r.turn_count);
  }
  /** One turn. `opts.channel: 'voice'` (slice 9 D7): the words were spoken, so the server shapes a
   *  reply for the ear; jarvis:turn / jarvis:turn-end tell the voice module (barge-in, states). */
  async function send(text, opts = {}) {
    if (state.busy) return false;
    const channel = opts.channel === 'voice' ? 'voice' : 'text';
    const files = Attach() && !Attach().busy() ? Attach().ready() : [];
    const sent = addMsg('user', text, channel === 'voice' ? ['Spoken'] : null); busy(true); note('send', channel === 'voice' ? 'Spoken message sent' : 'Message sent');
    if (files.length) Attach().show(sent, files);
    emit('jarvis:turn', { channel });
    let ok = false;
    try {
      const t0 = performance.now(); // reply latency as the owner feels it: the whole round trip
      const body = { message: text, session_id: state.sessionId, brain: state.brain };
      if (channel === 'voice') body.channel = 'voice';
      if (files.length) body.attachments = files.map(f => f.id);
      const r = await api('/v1/chat', { body });
      if (files.length) Attach().clear();
      handleResponse(r, performance.now() - t0, channel);
      ok = true;
    } catch (e) {
      showTyping(false);
      // refused before anything was stored (a file kept from this brain, the spending limit): the
      // files stay attached for another try; any other failure may have stored the message with them
      if (files.length && e.code !== 'input_rejected' && e.status !== 402) Attach().clear();
      if (e.status === 402) limitReached(e);
      else if (isConflict(e)) await conflictReload(e);
      else { addMsg('error', 'JARVIS couldn\'t answer. ' + e.message); note('error', 'Reply failed'); }
    }
    finally { busy(false); refocus(); emit('jarvis:turn-end', { channel, ok }); }
    return ok;
  }
  /** 409 session_conflict (slice 10): another window saved this conversation first. Show what the
   *  server holds now (the owner's message is there if it was kept), then the server's own plain
   *  line saying whether it was. Never resent automatically: that could store it twice. */
  function isConflict(e) { return !!e && e.status === 409 && e.code === 'session_conflict'; }
  async function conflictReload(e) {
    if (state.sessionId) await loadConversation(state.sessionId);
    const m = e && typeof e.message === 'string' ? e.message.trim() : '';
    addMsg('sys', m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : CONFLICT_FALLBACK);
    note('info', 'Conversation reloaded');
  }
  /** 402 budget_reached: not a crash, a JARVIS note in the conversation with the server's own
   *  words (rupees); Vitals reloads the month so its bar shows the limit reached. */
  function limitReached(e) {
    const m = e && typeof e.message === 'string' ? e.message.trim() : '';
    addMsg('limit', m && m.length <= 300 && !/^[a-z0-9_.-]+$/i.test(m) ? m : LIMIT_FALLBACK);
    note('info', 'Monthly limit reached');
    emit('jarvis:reply', { refused: true });
  }
  // Approve / Decline on a card, and Approve all: console-approvals.js (loaded first) gets the console's
  // own pieces here, once; without it the buttons do nothing rather than break the console.
  const Decisions = window.JarvisDecisions ? window.JarvisDecisions.make({ api, isBusy: () => state.busy, busy,
    session: () => state.sessionId, addMsg, note, Deck, loadConversation, showTyping, handleResponse, limitReached,
    refreshSide }) : { decide: async () => {}, decideWith: async () => false };
  const decide = Decisions.decide, decideWith = Decisions.decideWith;

  // composer
  const input = $('input');
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px'; }
  input.addEventListener('input', () => { autosize(); syncSend(); });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); $('form').requestSubmit(); }
  });
  $('form').addEventListener('submit', (ev) => {
    ev.preventDefault(); const t = input.value.trim(); if (!t || state.busy) return;
    const SC = window.JarvisSystemsCheck; // R5.1 D6: typed or dictated "run a systems check" -> the pop-up, no AI call
    if (SC && SC.matches(t, { typed: true })) { // typed mode: the WHOLE message must be the phrase
      delete input.dataset.channel; input.value = ''; autosize(); syncSend();
      SC.open({ via: 'typed', opener: $('send') }); return;
    }
    const channel = input.dataset.channel === 'voice' ? 'voice' : 'text'; // dictated, then checked by the owner
    delete input.dataset.channel;
    FX.ripple($('send')); input.value = ''; autosize(); syncSend(); send(t, { channel });
  });

  // top bar + panel actions
  $('newBtn').addEventListener('click', startNew);
  $('logoutBtn').addEventListener('click', async () => { try { await api('/auth/logout', { body: {} }); } catch (_) {} location.reload(); });
  // One transport (auth, CSRF header, 401 → gate) for every panel. jarvis:ready fires once per
  // sign-in; a panel script that arrives after it (deferred scripts can be held back by a slow
  // network) asks ready() when it starts: the last jarvis:ready detail, or null until signed in.
  window.JarvisConsole = Object.freeze({ api, ready: () => readyDetail, brain: () => brainDetail });
  // slice 11 (console-approve-all.js): the open conversation, the cards last rendered, a decision
  window.JarvisApprovals = Object.freeze({ session: () => state.sessionId, cards: () => lastCards, decide: decideWith });
  // slice 9 voice (console-voice*.js): send a spoken message, the bytes transport, the console's state
  window.JarvisChat = Object.freeze({
    send: (text, opts) => (typeof text === 'string' && text.trim() && !state.busy ? send(text.trim(), opts || {}) : Promise.resolve(false)),
    busy: () => state.busy,
    honorific: () => state.honorific,
    raw,
  });

  // ---- boot ---------------------------------------------------------------------------------
  async function boot() {
    renderWelcome();
    const integrations = window.JarvisIntegrations || null; // slice 12 review C5: console-integrations.js
    const backFromGoogle = integrations ? integrations.afterConnectRedirect() : false;
    readyDetail = Object.freeze({ returning: backFromGoogle });
    emit('jarvis:ready', readyDetail);
    await loadBrains();
    const saved = lsGet('jarvis_session');
    if (saved) { busy(true, false); try { await loadConversation(saved); } finally { busy(false); } }
    refreshSide(); refreshConvos();
    const linkCheck = integrations ? integrations.refresh() : Promise.resolve();
    if (backFromGoogle) linkCheck.then(() => Deck.open('integrations', { focus: true })); else input.focus();
  }
  // R2: a button with data-goto="<panel>" (Memory -> Privacy, Permissions -> Privacy) opens that panel
  document.addEventListener('click', (e) => {
    const b = e.target instanceof Element ? e.target.closest('[data-goto]') : null;
    if (b && /^[a-z]{2,20}$/.test(b.dataset.goto || '')) Deck.open(b.dataset.goto, { focus: true });
  });
  (async () => {
    let fallbackWarning = '';
    try {
      const c = await (await fetch('/console/config')).json();
      state.authMode = c.auth_mode; state.honorific = c.honorific || 'Sir'; fallbackWarning = c.privacy_warning || '';
    } catch (_) {}
    renderBanner(fallbackWarning);
    if (state.authMode === 'google') {
      const r = await fetch('/auth/me', { credentials: 'same-origin' });
      if (r.status === 423) { toShow(); return; }
      if (r.status !== 200) { showGate(); return; }
      const me = await r.json();
      const who = $('who'); who.textContent = (me.email || '?').charAt(0).toUpperCase(); who.title = me.email; who.hidden = false;
      $('logoutBtn').hidden = false;
    } else if (!state.token) { showGate(); return; }
    boot();
  })();
})();
