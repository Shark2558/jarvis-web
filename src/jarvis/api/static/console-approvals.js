// src/jarvis/api/static/console-approvals.js — an approval card's Approve / Decline and Approve all's
// batch, through one decision path. Moved out of console.js unchanged (slice 11 review), so that file
// stays under its 800-line soft limit. No build step; CSP script-src 'self'; no library.
// Loaded BEFORE console.js, which calls window.JarvisDecisions.make({...}) once with its own pieces
// (transport, busy state, the conversation view): they are never global. Nothing here writes HTML;
// every server string reaches the page through the console's addMsg or textContent.
(() => {
  'use strict';
  /** k: console.js's own {api, isBusy, busy, session, addMsg, note, Deck, loadConversation,
   *  showTyping, handleResponse, limitReached, refreshSide}. */
  function make(k) {
    async function decide(id, action, card, sid, tool, passkey) {
      if (k.isBusy()) return; // one action at a time: a reply may still be arriving
      const target = sid || k.session();
      if (!target) { k.addMsg('error', 'This approval belongs to a conversation that no longer exists.'); return; }
      k.busy(true); // claimed before any await: a second click, a send or History cannot interleave
      card.querySelectorAll('button').forEach(b => { b.disabled = true; });
      const perr = card.querySelector('.perr'); if (perr) perr.textContent = '';
      const body = { session_id: target };
      if (action === 'approve' && passkey) { // first, while the click still counts as the owner's gesture
        const P = window.JarvisPasskey;
        try {
          if (!P) throw new Error('Passkeys are still loading. Try again in a moment.');
          body.passkey = await P.approve(id);
        } catch (e) {
          if (perr) perr.textContent = P ? P.message(e) : e.message;
          k.note('error', 'Passkey check not completed');
          card.querySelectorAll('button').forEach(b => { b.disabled = false; }); k.busy(false); return;
        }
      }
      try {
        const opened = await runDecision(target, () => k.api(`/v1/approvals/${encodeURIComponent(id)}/${action}`, { body }),
          `${action === 'approve' ? 'Approved' : 'Declined'} · ${tool || 'action'}`, `Couldn't ${action}. `);
        if (!opened) card.querySelectorAll('button').forEach(b => { b.disabled = false; });
      } finally { k.busy(false); }
    }
    /** The outcome is a reply, shown in its conversation (caller holds busy); false: not opened, nothing sent. */
    async function runDecision(target, call, noteText, failText) {
      try {
        if (!k.Deck.isOpen('chat')) k.Deck.open('chat', { focus: false }); // the outcome is a reply: show it (phones: switch tab)
        if (target !== k.session()) { // show it in the conversation it belongs to
          if (!(await k.loadConversation(target))) { k.refreshSide(); return false; }
          k.showTyping(true); // loading the transcript cleared the indicator
        }
        k.note('approval', noteText);
        k.handleResponse(Object.assign(await call(), { decided: true }));
      } catch (e) {
        k.showTyping(false);
        if (e.status === 402) k.limitReached(e); else k.addMsg('error', failText + e.message);
        k.refreshSide();
      }
      return true;
    }
    async function decideWith(sid, call, noteText, failText) { // slice 11: Approve all, like one card
      if (k.isBusy() || !sid) return false;
      k.busy(true); try { return await runDecision(sid, call, noteText, failText); } finally { k.busy(false); }
    }
    return Object.freeze({ decide, decideWith });
  }
  window.JarvisDecisions = Object.freeze({ make });
})();
