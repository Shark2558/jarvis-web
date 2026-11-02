// src/jarvis/api/static/console-approve-all.js — "Approve all (n)" above the Approvals list (slice 11
// D6, docs/plans/phase2-slice11-full-control.md). No build step; CSP script-src 'self'; no library.
// Every server string reaches the page through textContent. Transport and the reply are the
// console's own (window.JarvisConsole.api, and window.JarvisApprovals.decide — one action at a time,
// the reply shown in its conversation, like a single card). API: POST /v1/approvals/approve-all
// {session_id, ids}.
// Only cards whose call can be undone count (tool_risk 'reversible' or 'read_only'; a card of unknown
// risk never does) AND that the server marks bulk_ok (review MEDIUM-1: never a draft to an address
// the owner did not type, never a memory write; a card without the flag never counts), and only one
// conversation's cards (the API approves one conversation at a time): the open conversation when it
// has 2 or more waiting, else the first one listed that does. The other cards keep their own Approve
// ("N need you one by one") — the server refuses them as well.
// The batch sent is exactly the one on the button: it is frozen when shown, and when it changes the
// button is disabled for SETTLE_MS with its new label, so a tap can't land on a batch not yet seen.
(() => {
  'use strict';
  const MIN = 2;
  const SETTLE_MS = 1500;
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
  let target = null; // frozen {sid, ids, here}: exactly what the button shows and sends
  let settle = 0; // the timer that re-enables the button once a changed batch has been shown
  let sending = false;

  const bulk = (a) => !!a && typeof a.id === 'string' && typeof a.session_id === 'string' &&
    a.session_id !== '' && BATCH.has(a.tool_risk) && a.bulk_ok === true;
  const same = (x, y) => !!x && !!y && x.sid === y.sid && x.ids.length === y.ids.length &&
    x.ids.every((id, i) => id === y.ids[i]);

  /** The conversation the button acts on, and its cards Approve all may run (in list order). */
  function pick(cards) {
    const by = new Map();
    cards.filter(bulk).forEach(a => { if (!by.has(a.session_id)) by.set(a.session_id, []); by.get(a.session_id).push(a.id); });
    const h = A();
    const open = h && typeof h.session === 'function' ? h.session() : null;
    if (open && (by.get(open) || []).length >= MIN) return { sid: open, ids: by.get(open), here: true };
    for (const [sid, ids] of by) if (ids.length >= MIN) return { sid, ids, here: sid === open };
    return null;
  }

  /** The batch changed under the owner's eyes: show it first, allow the tap a moment later. */
  function hold() {
    btn.disabled = true;
    clearTimeout(settle);
    settle = setTimeout(() => { settle = 0; if (!sending) btn.disabled = false; }, SETTLE_MS);
  }

  function render(cards) {
    const all = Array.isArray(cards) ? cards : [];
    const next = pick(all);
    const changed = !same(target, next);
    target = next ? Object.freeze({ sid: next.sid, ids: Object.freeze(next.ids.slice()), here: next.here }) : null;
    bar.hidden = !target;
    if (!target) { clearTimeout(settle); settle = 0; return; }
    const n = target.ids.length;
    btn.textContent = `Approve all (${n})`;
    const stay = all.filter(a => a && a.session_id === target.sid && !bulk(a)).length;
    const keep = stay === 1 ? ' 1 needs you one by one.' : stay > 1 ? ` ${stay} need you one by one.` : '';
    hint.textContent = `Runs the ${n} actions that can be undone, in order${target.here ? '' : ' (in another conversation)'}.${keep}`;
    if (changed) hold(); else if (!settle && !sending) btn.disabled = false;
  }

  btn.addEventListener('click', async () => {
    const c = C(), h = A();
    if (!c || !h || typeof h.decide !== 'function' || !target || btn.disabled) return;
    const { sid, ids } = target; // frozen: the batch on the button, nothing added since
    btn.disabled = true; sending = true;
    let done = false;
    try {
      done = await h.decide(sid, () => c.api('/v1/approvals/approve-all', { body: { session_id: sid, ids } }),
        `Approved all · ${ids.length}`, 'Couldn\'t approve all. ');
    } finally { sending = false; }
    if (!done && !settle) btn.disabled = false; // busy, or the conversation could not be opened: nothing sent
  });

  document.addEventListener('jarvis:approvals', (e) => render(e.detail && e.detail.cards));
  const h = A();
  if (h && typeof h.cards === 'function') render(h.cards()); // cards rendered before this loaded
})();
