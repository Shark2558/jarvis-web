(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = { sessionId: null, authMode: 'token', token: sessionStorage.getItem('jarvis_token') || '', honorific: 'Sir' };

  // ---- transport: cookie + anti-CSRF header, or bearer token for token mode ---------------
  async function api(path, opts = {}) {
    const headers = Object.assign({ 'X-Requested-With': 'JARVIS' }, opts.headers || {});
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (state.authMode === 'token' && state.token) headers['Authorization'] = 'Bearer ' + state.token;
    const r = await fetch(path, { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
      headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined, credentials: 'same-origin' });
    if (r.status === 401) { showGate(); throw new Error('sign in required'); }
    if (!r.ok) {
      let detail = r.statusText;
      try { const j = await r.json(); detail = j.detail || j.error || detail; } catch (_) {}
      throw new Error(detail);
    }
    return r.status === 204 ? null : r.json();
  }

  // ---- sign-in gate ----------------------------------------------------------------------
  function showGate() {
    const box = $('gateBox');
    if (state.authMode === 'google') {
      box.innerHTML = '<h2 style="margin:0 0 6px">Private system</h2><p style="color:var(--muted)">Sign in with the Google account registered as owner.</p>' +
        '<button class="primary" id="gBtn">Sign in with Google</button>';
      $('gBtn').onclick = () => { location.href = '/auth/login'; };
    } else {
      box.innerHTML = '<h2 style="margin:0 0 6px">Access token</h2><p style="color:var(--muted)">Paste the JARVIS_API_TOKEN for this server.</p>' +
        '<input id="tokIn" type="password" placeholder="token"><button class="primary" id="tokBtn">Continue</button>';
      $('tokBtn').onclick = () => { state.token = $('tokIn').value.trim(); sessionStorage.setItem('jarvis_token', state.token); hideGate(); refreshSide(); };
    }
    $('gate').style.display = 'flex';
  }
  function hideGate() { $('gate').style.display = 'none'; }

  // ---- rendering -------------------------------------------------------------------------
  function addMsg(role, text, meta) {
    const d = document.createElement('div'); d.className = 'msg ' + role;
    d.textContent = text;
    if (meta) { const m = document.createElement('div'); m.className = 'meta'; m.textContent = meta; d.appendChild(m); }
    $('log').appendChild(d); $('log').scrollTop = $('log').scrollHeight;
  }
  function renderApprovals(list) {
    const el = $('approvals');
    if (!list.length) { el.innerHTML = '<div class="empty">Nothing pending.</div>'; return; }
    el.innerHTML = list.map(a => `
      <div class="card pending" data-id="${esc(a.id)}">
        <div><span class="tool">${esc(a.tool)}</span> · <span style="color:var(--warn)">${esc(a.risk)}</span></div>
        <div>${esc(a.summary)}</div>
        <div class="args">${esc(JSON.stringify(a.arguments, null, 1))}</div>
        <div class="row"><button class="approve">Approve</button><button class="decline">Decline</button></div>
      </div>`).join('');
    el.querySelectorAll('.card').forEach(card => {
      const id = card.dataset.id;
      card.querySelector('.approve').onclick = () => decide(id, 'approve');
      card.querySelector('.decline').onclick = () => decide(id, 'decline');
    });
  }
  function renderAudit(data) {
    $('auditOk').textContent = data.verified ? '· chain verified' : '· CHAIN BROKEN';
    $('auditOk').style.color = data.verified ? 'var(--ok)' : 'var(--danger)';
    const el = $('audit'); const entries = data.entries.slice(-40).reverse();
    if (!entries.length) { el.innerHTML = '<div class="empty">No tool activity yet.</div>'; return; }
    const cls = o => o === 'executed' ? 'ok' : (o === 'awaiting_confirmation' ? 'warn' : (o === 'denied' || o === 'declined' || o === 'error' ? 'bad' : ''));
    el.innerHTML = entries.map(e => `<div class="audit">${esc(String(e.at || '').slice(11,19))} <span class="${cls(e.outcome)}">${esc(e.outcome)}</span> ${esc(e.tool)}</div>`).join('');
  }
  function renderStats(r) {
    $('sModel').textContent = r.model || '—'; $('sTurns').textContent = r.turn_count ?? '—';
    $('sCost').textContent = (r.cost_usd ?? 0).toFixed(4); $('sLat').textContent = r.latency_ms != null ? r.latency_ms + ' ms' : '—';
  }
  async function refreshSide() {
    try { renderApprovals(await api('/v1/approvals')); renderAudit(await api('/v1/audit?limit=100')); } catch (_) {}
  }

  // ---- actions ---------------------------------------------------------------------------
  function busy(on) { $('orb').classList.toggle('busy', on); $('send').disabled = on; }
  function handleResponse(r) {
    state.sessionId = r.session_id;
    addMsg('jarvis', r.reply, `${r.model} · ${r.latency_ms} ms · $${r.cost_usd.toFixed(4)}` + (r.tool_calls ? ` · ${r.tool_calls} tool call(s)` : ''));
    renderStats(r); refreshSide();
  }
  async function send(text) {
    addMsg('user', text); busy(true);
    try { handleResponse(await api('/v1/chat', { body: { message: text, session_id: state.sessionId } })); }
    catch (e) { addMsg('sys', 'JARVIS could not answer: ' + e.message); }
    finally { busy(false); }
  }
  async function decide(id, action) {
    if (!state.sessionId) { addMsg('sys', 'No active session for this approval.'); return; }
    busy(true);
    try { handleResponse(await api(`/v1/approvals/${encodeURIComponent(id)}/${action}`, { body: { session_id: state.sessionId } })); }
    catch (e) { addMsg('sys', `Could not ${action}: ` + e.message); refreshSide(); }
    finally { busy(false); }
  }

  $('form').addEventListener('submit', (ev) => {
    ev.preventDefault(); const t = $('input').value.trim(); if (!t) return; $('input').value = ''; send(t);
  });
  $('input').addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); $('form').requestSubmit(); } });
  $('newBtn').onclick = () => { state.sessionId = null; $('log').innerHTML = ''; addMsg('sys', 'New session.'); };
  $('logoutBtn').onclick = async () => { try { await api('/auth/logout', { body: {} }); } catch (_) {} location.reload(); };

  // ---- boot ------------------------------------------------------------------------------
  (async () => {
    try { const c = await (await fetch('/console/config')).json(); state.authMode = c.auth_mode; state.honorific = c.honorific || 'Sir'; if (c.privacy_warning) { const b = $('banner'); b.textContent = c.privacy_warning; b.style.display = 'block'; } } catch (_) {}
    if (state.authMode === 'google') {
      const r = await fetch('/auth/me', { credentials: 'same-origin' });
      if (r.status !== 200) { showGate(); return; }
      const me = await r.json(); $('who').textContent = me.email; $('logoutBtn').style.display = '';
    }
    addMsg('sys', `Online. Good ${new Date().getHours() < 12 ? 'morning' : (new Date().getHours() < 18 ? 'afternoon' : 'evening')}, ${state.honorific}.`);
    refreshSide();
  })();
})();
