// src/jarvis/api/static/console-voice-conversation.js - R5 D4-D6 (docs/plans/r5-voice.md): the
// conversation clock and the runaway check-in. No build step; CSP script-src 'self'.
//   window.JarvisConversation
//     create({followUpMs, longPauseMs, onStandby(), onLongPause()}) -> clock
//       clock.replyEnded()   a spoken reply is over: at followUpMs -> onStandby(), at longPauseMs -> onLongPause()
//       clock.heard()        speech started (or anything else that proves the owner is here): both waits stop
//       clock.stop()         the conversation ended: nothing fires
//       clock.waiting()      true between replyEnded() and heard() / stop()
//       clock.sinceReplyMs() ms since the last reply ended (0 when none)
//     runaway(opts) -> tracker for "the room keeps talking" (D6):
//       tracker.turn(gapMs, now)  a hands-free turn began gapMs after JARVIS finished
//       tracker.touch()           a tap or key: the owner is here, the count starts again
//       tracker.due(now)          true at the 8th quick turn inside 4 minutes (and not just after a "yes")
//       tracker.answered(yes, now) a "yes" silences the question for 15 minutes; anything else restarts the count
//     offers(el, ms) -> {offer(text, [{label, run}]) -> remove, clear()}  the suggestion line under the voice line
//     RUNAWAY   the frozen constants.
// Waiting costs nothing: the loop only runs the local VAD until speech starts.
(() => {
  'use strict';
  const RUNAWAY = Object.freeze({ TURNS: 8, QUICK_MS: 1500, WINDOW_MS: 4 * 60 * 1000, QUIET_MS: 15 * 60 * 1000 });

  function create(o) {
    let t1 = 0, t2 = 0, ended = 0, on = false;
    const clear = () => { clearTimeout(t1); clearTimeout(t2); t1 = t2 = 0; on = false; };
    return {
      replyEnded() {
        clear();
        on = true; ended = performance.now();
        t1 = setTimeout(() => { t1 = 0; if (on && typeof o.onStandby === 'function') o.onStandby(); }, Math.max(0, o.followUpMs));
        t2 = setTimeout(() => { t2 = 0; if (on) { clear(); if (typeof o.onLongPause === 'function') o.onLongPause(); } }, Math.max(0, o.longPauseMs));
      },
      heard: clear,
      stop() { clear(); ended = 0; },
      waiting: () => on,
      sinceReplyMs: () => (ended ? performance.now() - ended : 0),
    };
  }

  function runaway() {
    let turns = [], quietUntil = 0;
    return {
      turn(gapMs, now) {
        const at = typeof now === 'number' ? now : Date.now();
        if (typeof gapMs !== 'number' || gapMs > RUNAWAY.QUICK_MS) turns = [];   // a human pace: not a runaway
        turns.push(at);
        turns = turns.filter(x => at - x <= RUNAWAY.WINDOW_MS);
      },
      touch() { turns = []; },
      due(now) {
        const at = typeof now === 'number' ? now : Date.now();
        return turns.length >= RUNAWAY.TURNS && at >= quietUntil;
      },
      answered(yes, now) {
        turns = [];
        if (yes) quietUntil = (typeof now === 'number' ? now : Date.now()) + RUNAWAY.QUIET_MS;
      },
      count: () => turns.length,
    };
  }

  /** The suggestion under the voice line ("{name} connected. [Use it] [Not now]"): buttons for `ms`, textContent only. */
  function offers(el, ms) {
    let timer = 0;
    function clear() {
      clearTimeout(timer); timer = 0;
      if (el) { el.textContent = ''; el.hidden = true; }
    }
    function offer(text, actions) {
      const list = (Array.isArray(actions) ? actions : []).filter(a => a && typeof a.label === 'string' && typeof a.run === 'function').slice(0, 3);
      if (!el || typeof text !== 'string' || !text.trim() || !list.length) return () => {};
      clear();
      const msg = document.createElement('span');
      msg.textContent = text.trim().slice(0, 200);
      el.append(msg);
      list.forEach(a => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'btn lift bact'; b.textContent = a.label.slice(0, 40);
        b.addEventListener('click', () => { clear(); try { a.run(); } catch (_) {} });
        el.append(b);
      });
      el.hidden = false;
      const mine = timer = setTimeout(clear, ms);
      return () => { if (timer === mine) clear(); };
    }
    return { offer, clear };
  }

  window.JarvisConversation = Object.freeze({ create, runaway, offers, RUNAWAY });
})();
