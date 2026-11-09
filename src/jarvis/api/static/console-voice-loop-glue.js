// src/jarvis/api/static/console-voice-loop-glue.js - R5 (docs/plans/r5-voice.md workstream A): the
// listening loop's conversation glue, moved out of console-voice-mic.js to keep that file small.
// window.JarvisLoopGlue.create(host) -> {armBarge, disarmBarge, bargeIn, bargeWake, resumeSpeech,
//   bindCommands, speakWake, checkIn, handover, finishHandover}. `host` is what the loop lends it: its
//   state object S, the services (A, V, Chat, emit, log), and the loop's own functions (setMode, speak,
//   silence, listen, deliver, settle, say, cue, ...). Loaded after barge / commands / conversation / wake
//   and before console-voice-mic.js. No build step; CSP script-src 'self'.
(() => {
  'use strict';
  const RESUME_MS = 10000;         // an empty interruption: JARVIS picks his reply up again within this
  const WAKE_NAME_MS = 400;        // "Jarvis" inside his own words counts only if the gate was open this recently
  const CHECK_ASK_MS = 8000;
  const REASK_MS = 1000, REASK_TRIES = 10;   // a cancelled check-in is asked again once the other question is done
  const FIXED = Object.freeze({ fixed: true });   // fixed lines: their audio is cached per page

  function create(h) {
    const { S, A, V, Chat } = h;

    // ---- speak to interrupt (D7, D9) ----------------------------------------------------------------
    function armBarge() {
      disarmBarge();
      S.barge = window.JarvisBarge.arm({
        said: h.saidText, browserVoice: V.speaker.usingBrowser(),
        handle: (text, ctx) => (h.Cmd() ? h.Cmd().handle(text, ctx) : Promise.resolve({ handled: false })),
        onBarge: bargeIn,
      });
      h.wake().speaking(true);
    }
    function disarmBarge() {
      if (S.barge) { S.barge.disarm(); S.barge = null; }
      const w = h.wake();
      if (w) w.speaking(false);
    }
    /** JARVIS is stopped; remember the unplayed words, then listen (seeded with what was just said). */
    function bargeIn(ev) {
      if (S.mode !== 'speaking' || A.locked()) return;
      const was = S.keep, said = h.saidText();
      S.keep = false;
      const r = h.silence();
      S.rest = ev.handled || !(r.rest && r.rest.length) ? null : r.rest; S.restAt = performance.now(); S.restKeep = was;
      h.emit('jarvis:barge', { how: ev.how, ms: ev.ms || 0 });
      h.log('info', `Interrupted (${Math.round(ev.ms || 0)} ms)`);
      if (ev.handled) { h.settle({ id: 'barge', result: ev.result }); return; }
      if (ev.text) {
        S.rest = null;
        if (h.Cmd() && h.Cmd().normalise(ev.text)) { h.setMode('thinking'); h.deliver(ev.text, { state: 'speaking' }); return; }
      }
      h.listen({ barge: true, soft: true, seed: ev.frames,
        info: ev.how === 'speech' ? { said, peak: ev.peak, margin: window.JarvisBarge.BARGE.SPEAKERS.margin } : null });
    }
    /** "Hey Jarvis" over his speech (the wake model runs while he speaks, D8). */
    function bargeWake() {
      if (S.mode !== 'speaking') return;
      const cur = S.said.length ? S.said[S.said.length - 1].text : '';
      const g = S.barge && S.barge.gate && S.barge.gate();
      if (/jarvis|jervis/i.test(cur) && !(g && S.barge.recentLoud && S.barge.recentLoud(WAKE_NAME_MS))) return;
      const was = S.keep;
      S.keep = false; S.rest = null;
      h.silence();
      S.restKeep = was;
      h.emit('jarvis:barge', { how: 'wake', ms: 0 });
      h.listen({ barge: true, soft: false });
    }
    /** After an empty interruption JARVIS picks up where he was (within 10 s). */
    function resumeSpeech() {
      const rest = S.rest;
      S.rest = null;
      if (!S.handsFree || S.handsFree !== 'barge' || !rest || !rest.length || A.locked()) return false;
      if (performance.now() - S.restAt > RESUME_MS) return false;
      h.setMode('idle');
      h.speak(rest, S.restKeep);
      return true;
    }
    /** The loop's own actions behind the built-in commands (the matchers live in console-voice-commands.js). */
    function bindCommands() {
      const C = h.Cmd();
      if (!C || typeof C.bindLoop !== 'function') return;
      C.bindLoop({
        micOff() {
          h.silence(); S.rest = null; S.keep = false;
          A.lock('voice');                                    // first: nothing hears anything from here on
          h.setMode('idle');
          h.speak([`Microphone off, ${h.honorific()}.`], false, 'speaking', FIXED);
          return { then: 'off' };
        },
        stop(ctx) {
          const st = ctx && ctx.state;
          if (st === 'speaking') { h.silence(); S.rest = null; S.keep = false; return { then: 'listen' }; }
          if (st === 'thinking') { if (Chat.busy()) S.mute = true; return { then: 'listen' }; }
          return { then: S.conv ? 'listen' : 'idle' };
        },
        keyboard() { return { then: 'keyboard' }; },
      });
    }
    const speakWake = () => {
      if (S.mode !== 'speaking' || S.nameOff || !A.isOpen() || A.locked()) return false;
      const p = window.JarvisBarge.policy();
      if (p === 'name') return true;
      return p === 'speech' && V.speaker.usingBrowser() && window.JarvisBarge.kind() === 'speakers'; // no echo reference: the name is the fallback
    };

    // ---- the runaway check-in (D6) --------------------------------------------------------------------
    /** Ask, listen for the answer, hand over unless it is "yes". */
    async function checkIn() {
      const C = h.Cmd();
      S.checking = true;
      const q = `Shall I keep listening, ${h.honorific()}?`;
      await h.loopSay(q, { speak: true, fixed: true });
      if (!S.checking || !S.conv) { S.checking = false; return; }
      h.startClock();
      // only a plain yes answers (strict), and the wait does not run out while an answer is being heard (M2)
      const asked = C ? C.ask(q, { timeoutMs: CHECK_ASK_MS, strict: true, hold: h.answering }) : Promise.resolve('timeout');
      h.listen({ relisten: true });
      const answer = await asked;
      await new Promise(r => setTimeout(r, 60));
      if (!S.checking) return;
      S.checking = false;
      if (answer === 'yes') { h.runaway.answered(true, Date.now()); if (S.conv) { if (S.mode === 'idle') h.resumeListening(); } return; }
      if (answer === 'cancelled') { reask(0); return; }   // another question took its place: the count stays, ask again after it
      handover('checkin');
    }
    function reask(tries) {
      setTimeout(() => {
        if (!S.conv || A.locked() || S.checking || S.handing) return;
        const C = h.Cmd();
        if (C && C.pending() && tries < REASK_TRIES) { reask(tries + 1); return; }
        if (S.mode === 'idle' || h.isListening()) checkIn();
      }, REASK_MS);
    }

    // ---- ending a conversation the owner did not end (D5) -----------------------------------------------
    function handover(reason) {
      if (A.locked() || S.handing || S.mode === 'off') return;
      S.handing = true; S.checking = false;
      clearTimeout(S.relisten); clearTimeout(S.browserTimer);
      S.keep = false; S.rest = null;
      h.stopClock();
      if (h.isListening()) { S.turn++; if (S.rec) { S.cancel = true; const r = S.rec; S.rec = null; try { r.abort(); } catch (_) {} h.restore(); } h.endCapture(); }
      h.silence();
      S.conv = false;
      const hon = h.honorific();
      const stopped = reason === 'mic_ended' ? `The microphone stopped, ${hon}. I'll switch to the keyboard.`
        : reason === 'cloud_down' ? `Cloud listening isn't available, ${hon}. I'll switch to the keyboard.` : '';
      const spoken = stopped || `I'll switch to the keyboard, ${hon}.`;
      const wakeHint = V.device().wake ? ' (or say "Hey Jarvis")' : '';
      h.say(stopped || `Switched to the keyboard. Tap the mic${wakeHint} to talk.`);
      h.cue('handover');
      const d = V.device();
      if (d.speak === 'never' || V.outputEngine() === 'none') { finishHandover(); return; }
      h.speak([spoken], false, 'handover', FIXED);
    }
    function finishHandover() {
      S.handing = false; S.conv = false;
      h.setMode('idle');
      h.releaseMic();
      if (!A.locked()) h.input.focus();
    }

    return { armBarge, disarmBarge, bargeIn, bargeWake, resumeSpeech, bindCommands, speakWake, checkIn, handover, finishHandover };
  }
  window.JarvisLoopGlue = Object.freeze({ create, FIXED });
})();
