// src/jarvis/api/static/console-approve-all.js — "Approve all (n)" above the Approvals list (slice 11
// D6, docs/plans/phase2-slice11-full-control.md). No build step; CSP script-src 'self'; no library.
// Every server string reaches the page through textContent. Transport and the reply are the
// console's own (window.JarvisConsole.api, and window.JarvisApprovals.decide — one action at a time,
// the reply shown in its conversation, like a single card). API: POST /v1/approvals/approve-all
// {session_id, ids}.
// Only cards whose call can be undone count (tool_risk 'reversible' or 'read_only'; a card of unknown
// risk never does) and only one conversation's cards (the API approves one conversation at a time):
// the open conversation when it has 2 or more waiting, else the first one listed that does. Cards
// that can't be undone keep their own Approve (with passkey) — the server skips them as well.
(() => {
  'use strict';
  const MIN = 2;
  const BATCH = new Set(['reversible', 'read_only']);
  const list = document.getElementById('approvals');
  if (!list || !list.parentNode) return;
  const C = () => window.JarvisConsole || null;
  const A = () => window.JarvisApprovals || null;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };

  const bar = mk('div', 'apall'); bar.id = 'approveAll'; bar.hidden = true;
  const btn = mk('button', 'btn primary lift'); btn.type = 'button'; btn.id = 'approveAllBtn';
  const hint = mk('p', 'apall-hint'); hint.id = 'approveAllHint';
  btn.setAttribute('aria-describedby', hint.id);
  bar.append(btn, hint);
  list.parentNode.insertBefore(bar, list);
  let target = null; // {sid, ids} the button approves now

  const undoable = (a) => !!a && typeof a.id === 'string' && typeof a.session_id === 'string' &&
    a.session_id !== '' && BATCH.has(a.tool_risk);

  /** The conversation the button acts on, and its cards that can be undone (in list order). */
  function pick(cards) {
    const by = new Map();
    cards.filter(undoable).forEach(a => { if (!by.has(a.session_id)) by.set(a.session_id, []); by.get(a.session_id).push(a.id); });
    const h = A();
    const open = h && typeof h.session === 'function' ? h.session() : null;
    if (open && (by.get(open) || []).length >= MIN) return { sid: open, ids: by.get(open), here: true };
    for (const [sid, ids] of by) if (ids.length >= MIN) return { sid, ids, here: sid === open };
    return null;
  }

  function render(cards) {
    const all = Array.isArray(cards) ? cards : [];
    target = pick(all);
    bar.hidden = !target;
    if (!target) return;
    const n = target.ids.length;
    btn.textContent = `Approve all (${n})`;
    btn.disabled = false;
    const stay = all.filter(a => a && a.session_id === target.sid && !undoable(a)).length;
    const keep = stay === 1 ? ' The card that can\'t be undone keeps its own Approve.'
      : stay > 1 ? ' Cards that can\'t be undone keep their own Approve.' : '';
    hint.textContent = `Runs the ${n} actions that can be undone, one by one${target.here ? '' : ' (in another conversation)'}.${keep}`;
  }

  btn.addEventListener('click', async () => {
    const c = C(), h = A();
    if (!c || !h || typeof h.decide !== 'function' || !target || btn.disabled) return;
    const { sid, ids } = target;
    btn.disabled = true;
    const done = await h.decide(sid, () => c.api('/v1/approvals/approve-all', { body: { session_id: sid, ids } }),
      `Approved all · ${ids.length}`, 'Couldn\'t approve all. ');
    if (!done) btn.disabled = false; // busy, or the conversation could not be opened: nothing sent
  });

  document.addEventListener('jarvis:approvals', (e) => render(e.detail && e.detail.cards));
  const h = A();
  if (h && typeof h.cards === 'function') render(h.cards()); // cards rendered before this loaded
})();
