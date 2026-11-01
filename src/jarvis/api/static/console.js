// src/jarvis/api/static/console.js — JARVIS web console (no build step; CSP script-src 'self').
// Talks to the API (chat, brains, approvals, audit, conversations) and renders the panels' content.
// All server text reaches the DOM via textContent or esc(); never raw innerHTML.
// The Command Deck (console-deck.js) shows vitals from the events this file fires:
//   jarvis:vitals {turns, brain, model, cost, rttMs?}  jarvis:approvals {count, fresh}
//   jarvis:audit {verified, count}                     jarvis:event {kind, text, at, live?}
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

  const state = { sessionId: null, authMode: 'token', token: ssGet('jarvis_token'), honorific: 'Sir',
    brains: [], brain: null, busy: false, seenApprovals: null, seenAudit: new Set() };

  const SUGGESTIONS = [
    'What can you help me with?',
    "What's on my calendar today?",
    'List my open tasks',
    'Draft a polite follow-up message',
  ];

  // ---- transport: cookie + anti-CSRF header, or bearer token in token mode ------------------
  async function api(path, opts = {}) {
    const headers = Object.assign({ 'X-Requested-With': 'JARVIS' }, opts.headers || {});
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (state.authMode === 'token' && state.token) headers['Authorization'] = 'Bearer ' + state.token;
    const r = await fetch(path, { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
      headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined, credentials: 'same-origin' });
    if (r.status === 401) { showGate(); throw new Error('Sign in required.'); }
    if (!r.ok) {
      let detail = r.statusText;
      try { const j = await r.json(); detail = j.detail || j.error || detail; } catch (_) {}
      const err = new Error(detail); err.status = r.status; throw err;
    }
    return r.status === 204 ? null : r.json();
  }

  // ---- sign-in gate -------------------------------------------------------------------------
  const LOCK = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="4" y="9" width="12" height="8" rx="2.2"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/></svg>';
  function showGate() {
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
    if (role === 'sys' || role === 'error') {
      const d = document.createElement('div'); d.className = 'sys' + (role === 'error' ? ' error' : '');
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
  function renderApprovals(list) {
    const el = $('approvals');
    $('approvalCount').textContent = list.length ? `${list.length} waiting` : '';
    FX.setAlert(list.length > 0);
    const ids = new Set(list.map(a => a.id));
    const fresh = list.filter(a => !state.seenApprovals || !state.seenApprovals.has(a.id));
    const first = state.seenApprovals === null;
    state.seenApprovals = ids;
    fresh.forEach(a => note('approval', `Approval waiting · ${String(a.tool).replace(/_/g, ' ')}`));
    emit('jarvis:approvals', { count: list.length, fresh: fresh.length > 0 || (first && list.length > 0) });
    if (!list.length) { el.innerHTML = '<div class="empty">Nothing waiting.</div>'; return; }
    el.innerHTML = list.map(a => `
      <div class="approval" data-id="${esc(a.id)}" data-sid="${esc(a.session_id || '')}">
        <div class="title">${esc(a.tool.replace(/_/g, ' '))} <span class="tag">${esc(a.risk)}</span></div>
        <p>${esc(a.summary)}</p>
        <pre>${esc(JSON.stringify(a.arguments, null, 2))}</pre>
        <div class="actions"><button class="btn primary approve lift">Approve</button><button class="btn decline lift">Decline</button></div>
      </div>`).join('');
    el.querySelectorAll('.approval').forEach(card => {
      const id = card.dataset.id; const sid = card.dataset.sid || null;
      const tool = card.querySelector('.title').firstChild.textContent.trim();
      card.querySelector('.approve').addEventListener('click', () => decide(id, 'approve', card, sid, tool));
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
      turns: Number.isFinite(r.turn_count) ? r.turn_count : 0, cost: Number.isFinite(r.cost_usd) ? r.cost_usd : 0 };
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
  function renderTranscript(sess) {
    renderWelcome();
    let shown = 0; let last = null;
    sess.turns.forEach(t => {
      if (!t.content || !t.content.trim()) return; // tool exchanges have no text of their own
      if (t.role === 'user') addMsg('user', t.content);
      else { addMsg('jarvis', t.content, [t.model]); last = t; }
      shown++;
    });
    if (shown) { addMsg('sys', 'Earlier conversation restored.'); note('info', 'Conversation restored'); }
    else renderWelcome();
    renderStats({ brain: (sess.metadata || {}).brain, model: last ? last.model : null,
      turn_count: sess.turns.length, cost_usd: sess.total_cost_usd, latency_ms: null });
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
    busy(true, false);
    try { await loadConversation(id); } finally { busy(false); }
  }
  function newConversation() { setSession(null); renderWelcome(); renderStats({}); input.focus(); }
  function startNew() { if (state.busy) return; newConversation(); Deck.open('chat', { focus: true }); note('info', 'New conversation'); }

  // ---- integrations (slice 6): the Google link that unlocks Calendar + Gmail tools --------------
  // GET /v1/integrations → {google: {connected, email, scopes, expires_at, needs_reconnect}}.
  // A 404 means this server has no connect flow (token-auth setup / older backend): say so, no error.
  const SCOPE_WORDS = { 'calendar.readonly': ['Calendar', 'read'], 'calendar.events': ['Calendar', 'edit'],
    'gmail.readonly': ['Gmail', 'read'], 'gmail.compose': ['Gmail', 'draft'], 'gmail.send': ['Gmail', 'send'] };
  /** "Calendar: read & edit · Gmail: read, draft, send" from the raw scope list (URLs or short names). */
  function scopeSummary(scopes) {
    const by = {}; let other = 0;
    (Array.isArray(scopes) ? scopes : []).forEach(s => {
      const key = String(s).split('/').pop(), w = SCOPE_WORDS[key];
      if (!w) { other++; return; }
      (by[w[0]] = by[w[0]] || []).push(w[1]);
    });
    const parts = Object.keys(by).map(k => `${k}: ${by[k].length === 2 && k === 'Calendar' ? by[k].join(' & ') : by[k].join(', ')}`);
    if (other) parts.push(`${other} other ${other === 1 ? 'permission' : 'permissions'}`);
    return parts.join(' · ');
  }
  function googleState(g) {
    if (!g || !g.connected) return 'unlinked';
    return g.needs_reconnect ? 'reconnect' : 'linked';
  }
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  // data: undefined = still loading, null = route missing (404) → "Not available in this setup"
  const integ = { data: undefined, loaded: false, at: 0, error: null, note: null };
  const INTEG_FRESH_MS = 5000; // reopening the panel re-checks the link unless it was just checked
  const STATE_WORDS = { linked: 'Connected', reconnect: 'Needs reconnecting', unlinked: 'Not connected',
    unavailable: 'Not available', loading: 'Checking…', error: 'Unknown' };
  function integState() {
    if (integ.error) return 'error';
    if (integ.data === undefined) return 'loading';
    return integ.data === null ? 'unavailable' : googleState(integ.data.google);
  }
  function integBody(st, g) {
    const body = mk('div', 'ibody');
    if (st === 'loading') body.appendChild(mk('p', '', 'Checking linked accounts…'));
    else if (st === 'error') body.appendChild(mk('p', 'warn', 'Couldn\'t check the Google link. ' + integ.error));
    else if (st === 'unavailable') body.appendChild(mk('p', '', 'Not available in this setup. Linking a Google account needs Google sign-in on this server.'));
    else if (st === 'unlinked') body.appendChild(mk('p', '', 'Link your Google account so JARVIS can read your calendar, find free time, and search, draft and send mail. Anything that sends or deletes still waits for your approval.'));
    else {
      const who = mk('p', 'who'); who.append(mk('span', '', st === 'linked' ? 'Connected as ' : 'Was connected as '), mk('b', '', g.email || 'unknown account'));
      body.appendChild(who);
      const sc = scopeSummary(g.scopes); if (sc) body.appendChild(mk('p', 'scopes', sc));
      if (st === 'reconnect') body.appendChild(mk('p', 'warn', 'Google stopped accepting the saved link (test-mode links expire after 7 days). Calendar and Gmail tools are paused until you reconnect.'));
      else body.appendChild(mk('p', 'fine', 'Unlocks: calendar list, free slots, create / move / delete events, mail search, read, draft and send.'));
    }
    return body;
  }
  function integActions(st, row) {
    const acts = mk('div', 'actions');
    if (st === 'unlinked' || st === 'reconnect') {
      const b = mk('button', 'btn primary lift', st === 'unlinked' ? 'Connect Google' : 'Reconnect'); b.type = 'button'; b.id = 'googleConnect';
      b.addEventListener('click', () => { note('info', 'Connecting Google…'); window.location.assign('/connect/google'); });
      acts.appendChild(b);
    }
    if (st === 'linked' || st === 'reconnect') {
      const d = mk('button', 'btn lift', 'Disconnect'); d.type = 'button'; d.id = 'googleDisconnect';
      d.addEventListener('click', () => askDisconnect(row, d)); acts.appendChild(d);
    }
    if (st === 'error') {
      const r = mk('button', 'btn lift', 'Retry'); r.type = 'button';
      r.addEventListener('click', () => { r.disabled = true; refreshIntegrations(); }); acts.appendChild(r);
    }
    return acts;
  }
  function renderIntegrations() {
    const box = $('integrations'); box.innerHTML = '';
    const st = integState(), g = integ.data ? integ.data.google : null;
    emit('jarvis:integrations', { google: integ.data ? st : null });
    const meta = $('integMeta');
    meta.textContent = st === 'linked' ? 'Google linked' : st === 'reconnect' ? 'Attention' : '';
    meta.className = 'pmeta' + (st === 'linked' ? ' ok' : st === 'reconnect' ? ' warn' : '');
    const row = mk('div', 'integ'); row.dataset.state = st;
    const head = mk('div', 'ihead'); head.append(mk('b', '', 'Google'), mk('span', 'istate', STATE_WORDS[st]));
    row.append(head, integBody(st, g));
    if (integ.note) { const n = mk('div', 'inote ' + integ.note.kind, integ.note.text); n.setAttribute('role', 'status'); row.appendChild(n); integ.note = null; }
    const acts = integActions(st, row); if (acts.childElementCount) row.appendChild(acts);
    box.appendChild(row);
  }
  function askDisconnect(row, trigger) {
    if (row.querySelector('.confirm')) return;
    const box = mk('div', 'confirm'); box.setAttribute('role', 'alert');
    const t = mk('span', '', 'Disconnect Google? JARVIS forgets the link and the Calendar and Gmail tools stop working until you connect again.');
    const yes = mk('button', 'btn danger lift', 'Disconnect'); yes.type = 'button';
    const no = mk('button', 'btn lift', 'Keep'); no.type = 'button';
    const keep = () => { box.remove(); trigger.focus(); };
    no.addEventListener('click', keep);
    box.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.isComposing) return; e.preventDefault(); e.stopPropagation(); keep(); });
    yes.addEventListener('click', async () => {
      yes.disabled = no.disabled = true;
      try {
        await api('/v1/integrations/google/disconnect', { body: {} });
        integ.note = { kind: 'ok', text: 'Google disconnected.' }; note('info', 'Google disconnected');
      } catch (e) { integ.note = { kind: 'bad', text: 'Couldn\'t disconnect. ' + e.message }; }
      await refreshIntegrations();
    });
    box.append(t, no, yes); row.appendChild(box); no.focus();
  }
  async function refreshIntegrations() {
    integ.error = null;
    try { integ.data = await api('/v1/integrations'); }
    catch (e) {
      if (e.status === 404) integ.data = null;
      else if (e.status !== 401) { integ.data = undefined; integ.error = e.message || 'error'; }
    }
    integ.loaded = true; integ.at = performance.now();
    renderIntegrations();
  }
  /** Back from Google's consent screen: queue the success note and clean the address bar.
   *  Returns true when boot should open the Integrations panel instead of focusing the composer. */
  function afterConnectRedirect() {
    let q; try { q = new URLSearchParams(window.location.search); } catch (_) { return false; }
    if (q.get('connected') !== 'google') return false;
    integ.note = { kind: 'ok', text: 'Google connected. Calendar and Gmail tools are ready.' };
    try { history.replaceState(null, '', window.location.pathname); } catch (_) {}
    note('info', 'Google connected');
    return true;
  }
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id === 'integrations' && d.open && integ.loaded && performance.now() - integ.at > INTEG_FRESH_MS) refreshIntegrations();
  });

  // ---- brain selector -----------------------------------------------------------------------
  function currentBrain() { return state.brains.find(b => b.id === state.brain) || state.brains.find(b => b.default) || null; }
  function renderBanner(fallback) {
    const b = currentBrain();
    const text = b ? (b.warning || '') : (fallback || '');
    $('bannerText').textContent = text;
    $('banner').classList.toggle('show', !!text);
    $('brainSel').classList.toggle('training', !!(b && b.trains_on_content));
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
  function syncSend() { $('send').disabled = state.busy || !$('input').value.trim(); }
  function handleResponse(r, rttMs) {
    const fresh = r.session_id !== state.sessionId;
    setSession(r.session_id);
    if (r.brain && r.brain !== state.brain && state.brains.some(b => b.id === r.brain)) { state.brain = r.brain; renderBrains(); }
    const meta = [r.brain ? brainLabel(r.brain) : null, r.model, (r.latency_ms / 1000).toFixed(1) + ' s',
      r.cost_usd > 0 ? '$' + r.cost_usd.toFixed(4) : null, r.tool_calls ? `${r.tool_calls} tool ${r.tool_calls === 1 ? 'call' : 'calls'}` : null];
    addMsg('jarvis', r.reply, meta);
    renderStats(r, rttMs);
    note('reply', Number.isFinite(rttMs) ? `Reply · ${Math.round(rttMs)} ms` : 'Reply');
    if (r.tool_calls || (r.pending_approvals || []).length || r.decided) refreshSide();
    if (fresh) refreshConvos(); else bumpCurrentConvo(r.turn_count);
  }
  async function send(text) {
    if (state.busy) return;
    addMsg('user', text); busy(true); note('send', 'Message sent');
    try {
      const t0 = performance.now(); // reply latency as the owner feels it: the whole round trip
      const r = await api('/v1/chat', { body: { message: text, session_id: state.sessionId, brain: state.brain } });
      handleResponse(r, performance.now() - t0);
    } catch (e) { showTyping(false); addMsg('error', 'JARVIS couldn\'t answer. ' + e.message); note('error', 'Reply failed'); }
    finally { busy(false); refocus(); }
  }
  async function decide(id, action, card, sid, tool) {
    if (state.busy) return; // one action at a time: a reply may still be arriving
    const target = sid || state.sessionId;
    if (!target) { addMsg('error', 'This approval belongs to a conversation that no longer exists.'); return; }
    busy(true); // claimed before any await: a second click, a send or History cannot interleave
    card.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      if (!Deck.isOpen('chat')) Deck.open('chat', { focus: false }); // the outcome is a reply: show it (phones: switch tab)
      if (target !== state.sessionId) { // show it in the conversation it belongs to
        if (!(await loadConversation(target))) {
          card.querySelectorAll('button').forEach(b => { b.disabled = false; }); refreshSide(); return;
        }
        showTyping(true); // loading the transcript cleared the indicator
      }
      note('approval', `${action === 'approve' ? 'Approved' : 'Declined'} · ${tool || 'action'}`);
      handleResponse(Object.assign(await api(`/v1/approvals/${encodeURIComponent(id)}/${action}`, { body: { session_id: target } }), { decided: true }));
    } catch (e) { showTyping(false); addMsg('error', `Couldn't ${action}. ` + e.message); refreshSide(); }
    finally { busy(false); }
  }

  // composer
  const input = $('input');
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px'; }
  input.addEventListener('input', () => { autosize(); syncSend(); });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); $('form').requestSubmit(); }
  });
  $('form').addEventListener('submit', (ev) => {
    ev.preventDefault(); const t = input.value.trim(); if (!t || state.busy) return;
    FX.ripple($('send')); input.value = ''; autosize(); syncSend(); send(t);
  });

  // top bar + panel actions
  $('newBtn').addEventListener('click', startNew);
  $('logoutBtn').addEventListener('click', async () => { try { await api('/auth/logout', { body: {} }); } catch (_) {} location.reload(); });

  // ---- boot ---------------------------------------------------------------------------------
  async function boot() {
    renderWelcome();
    const justConnected = afterConnectRedirect();
    await loadBrains();
    const saved = lsGet('jarvis_session');
    if (saved) { busy(true, false); try { await loadConversation(saved); } finally { busy(false); } }
    refreshSide(); refreshConvos();
    const linkCheck = refreshIntegrations();
    if (justConnected) linkCheck.then(() => Deck.open('integrations', { focus: true })); else input.focus();
  }
  (async () => {
    let fallbackWarning = '';
    try {
      const c = await (await fetch('/console/config')).json();
      state.authMode = c.auth_mode; state.honorific = c.honorific || 'Sir'; fallbackWarning = c.privacy_warning || '';
    } catch (_) {}
    renderBanner(fallbackWarning);
    if (state.authMode === 'google') {
      const r = await fetch('/auth/me', { credentials: 'same-origin' });
      if (r.status !== 200) { showGate(); return; }
      const me = await r.json();
      const who = $('who'); who.textContent = (me.email || '?').charAt(0).toUpperCase(); who.title = me.email; who.hidden = false;
      $('logoutBtn').hidden = false;
    } else if (!state.token) { showGate(); return; }
    boot();
  })();
})();
