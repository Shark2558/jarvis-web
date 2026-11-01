// src/jarvis/api/static/console.js — JARVIS web console (no build step; CSP script-src 'self').
// All server text reaches the DOM via textContent or esc(); never raw innerHTML.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
  const ssGet = (k) => { try { return sessionStorage.getItem(k) || ''; } catch (_) { return ''; } };
  const ssSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) {} };
  const compact = () => window.matchMedia('(max-width: 960px)').matches;
  // visual engine (console-fx.js); the console still works if it failed to load
  const FX = window.JarvisFX || { core: (s) => `<span class="core ${s === 'lg' || s === 'sm' ? s : ''}" aria-hidden="true"></span>`,
    setBusy() {}, setAlert() {}, ripple() {}, refresh() {} };

  const state = { sessionId: null, authMode: 'token', token: ssGet('jarvis_token'), honorific: 'Sir',
    brains: [], brain: null, busy: false };

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

  // ---- inspector ----------------------------------------------------------------------------
  function setPanel(open) {
    const app = $('app');
    if (compact()) { app.classList.toggle('sheet-open', open); }
    else { app.classList.toggle('collapsed', !open); lsSet('jarvis_panel', open ? '1' : '0'); }
    $('panelBtn').setAttribute('aria-pressed', String(open));
  }
  function panelOpen() { return compact() ? $('app').classList.contains('sheet-open') : !$('app').classList.contains('collapsed'); }

  function renderApprovals(list) {
    const el = $('approvals');
    $('approvalCount').textContent = list.length ? String(list.length) : '';
    $('panelBtn').classList.toggle('badge', list.length > 0); FX.setAlert(list.length > 0);
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
      card.querySelector('.approve').addEventListener('click', () => decide(id, 'approve', card, sid));
      card.querySelector('.decline').addEventListener('click', () => decide(id, 'decline', card, sid));
    });
    if (!compact() && !panelOpen()) setPanel(true); // something needs the owner: bring it forward
  }
  function renderAudit(data) {
    const ok = $('auditOk');
    ok.textContent = data.verified ? 'Log verified' : 'Log tampered';
    ok.className = 'verified ' + (data.verified ? 'ok' : 'bad');
    const el = $('audit'); const entries = data.entries.slice(-40).reverse();
    if (!entries.length) { el.innerHTML = '<div class="empty">JARVIS hasn\'t used any tools yet.</div>'; return; }
    const cls = o => o === 'executed' ? 'ok' : (o === 'awaiting_confirmation' ? 'warn' : (['denied', 'declined', 'error'].includes(o) ? 'bad' : ''));
    const words = { executed: 'Done', awaiting_confirmation: 'Waiting for you', denied: 'Blocked', declined: 'Declined', error: 'Failed' };
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
  function renderStats(r) {
    $('sBrain').textContent = r.brain ? brainLabel(r.brain) : '—';
    $('sModel').textContent = r.model || '—';
    $('sTurns').textContent = r.turn_count ?? '—';
    $('sCost').textContent = '$' + (r.cost_usd ?? 0).toFixed(r.cost_usd && r.cost_usd < 0.01 ? 4 : 2);
    $('sLat').textContent = r.latency_ms != null ? (r.latency_ms / 1000).toFixed(1) + ' s' : '—';
  }
  // Each refresh costs database reads (free quota: 50k/day), so the panel refreshes only when
  // something in it can have changed: at start, after tool use, approvals, or a decision.
  async function refreshSide() {
    try { renderApprovals(await api('/v1/approvals')); renderAudit(await api('/v1/audit?limit=40')); } catch (_) {}
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
      open.append(b, sm); open.addEventListener('click', () => { if (!state.busy) loadConversation(c.id); });
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
    no.addEventListener('click', () => box.remove());
    yes.addEventListener('click', async () => {
      yes.disabled = no.disabled = true;
      try {
        await api(`/v1/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (id === state.sessionId) newConversation();
        refreshConvos();
      } catch (e) { box.remove(); addMsg('error', 'Couldn\'t delete that conversation. ' + e.message); }
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
    if (shown) addMsg('sys', 'Earlier conversation restored.');
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
  function newConversation() { setSession(null); renderWelcome(); renderStats({}); input.focus(); }

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
    if (b) addMsg('sys', `Now using ${b.label}.` + (b.tools_allowed ? '' : ' Chat only: tools are off, and earlier messages in this conversation are not shared with it.'));
  });

  // ---- actions ------------------------------------------------------------------------------
  function busy(on) {
    state.busy = on; FX.setBusy(on); showTyping(on); syncSend();
  }
  function syncSend() { $('send').disabled = state.busy || !$('input').value.trim(); }
  function handleResponse(r) {
    const fresh = r.session_id !== state.sessionId;
    setSession(r.session_id);
    if (r.brain && r.brain !== state.brain && state.brains.some(b => b.id === r.brain)) { state.brain = r.brain; renderBrains(); }
    const meta = [r.brain ? brainLabel(r.brain) : null, r.model, (r.latency_ms / 1000).toFixed(1) + ' s',
      r.cost_usd > 0 ? '$' + r.cost_usd.toFixed(4) : null, r.tool_calls ? `${r.tool_calls} tool ${r.tool_calls === 1 ? 'call' : 'calls'}` : null];
    addMsg('jarvis', r.reply, meta);
    renderStats(r);
    if (r.tool_calls || (r.pending_approvals || []).length || r.decided) refreshSide();
    if (fresh) refreshConvos(); else bumpCurrentConvo(r.turn_count);
  }
  async function send(text) {
    if (state.busy) return;
    addMsg('user', text); busy(true);
    try { handleResponse(await api('/v1/chat', { body: { message: text, session_id: state.sessionId, brain: state.brain } })); }
    catch (e) { showTyping(false); addMsg('error', 'JARVIS couldn\'t answer. ' + e.message); }
    finally { busy(false); $('input').focus(); }
  }
  async function decide(id, action, card, sid) {
    if (state.busy) return; // one action at a time: a reply may still be arriving
    const target = sid || state.sessionId;
    if (!target) { addMsg('error', 'This approval belongs to a conversation that no longer exists.'); return; }
    card.querySelectorAll('button').forEach(b => { b.disabled = true; });
    if (target !== state.sessionId && !(await loadConversation(target))) { // show it where it belongs
      card.querySelectorAll('button').forEach(b => { b.disabled = false; }); refreshSide(); return;
    }
    busy(true);
    try { handleResponse(Object.assign(await api(`/v1/approvals/${encodeURIComponent(id)}/${action}`, { body: { session_id: target } }), { decided: true })); }
    catch (e) { addMsg('error', `Couldn't ${action}. ` + e.message); refreshSide(); }
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

  // toolbar
  $('newBtn').addEventListener('click', () => { if (!state.busy) newConversation(); });
  $('panelBtn').addEventListener('click', () => setPanel(!panelOpen()));
  $('scrim').addEventListener('click', () => setPanel(false));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && compact() && panelOpen()) setPanel(false); });
  $('logoutBtn').addEventListener('click', async () => { try { await api('/auth/logout', { body: {} }); } catch (_) {} location.reload(); });

  // ---- boot ---------------------------------------------------------------------------------
  async function boot() {
    renderWelcome();
    await loadBrains();
    const saved = lsGet('jarvis_session');
    if (saved) await loadConversation(saved);
    refreshSide(); refreshConvos();
    input.focus();
  }
  (async () => {
    if (!compact() && lsGet('jarvis_panel') !== '0' && window.innerWidth > 1180) setPanel(true);
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
