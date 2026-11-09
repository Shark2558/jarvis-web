// src/jarvis/api/static/console-voice-micoff.js - R5 D11 (docs/plans/r5-voice.md): the mic-off controls
// around the hard lock in console-voice-capture.js. No build step; CSP script-src 'self'; textContent only.
//   #micOffBtn         shown while the microphone is open (a voice conversation, or "Hey Jarvis" standby);
//                      a click locks the microphone ("button").
//   Ctrl + Shift + Space  toggles: lock ("shortcut"), or unlock. Both carry a real key press, which is the
//                      user activation the lock asks for. (Ctrl + Space, without Shift, is the mic button's.)
//   #micBtn while locked  a tap unlocks (user activation) and starts listening: console-voice-mic.js press().
//   Announcements      the live region says "Microphone off" / "Microphone on"; a line explains how to switch on.
// Nothing here can unlock the microphone without a click, tap or key press: A.unlock() refuses otherwise.
(() => {
  'use strict';
  const A = window.JarvisAudio;
  const $ = (id) => document.getElementById(id);
  const offBtn = $('micOffBtn'), micBtn = $('micBtn'), liveEl = $('voiceLive'), lineEl = $('voiceLine');
  if (!A || !micBtn) return;
  const OFF_LINE = 'Microphone off. Tap the mic (or press Ctrl + Shift + Space) to switch it on.';
  const honorific = () => { try { return (window.JarvisChat && window.JarvisChat.honorific && window.JarvisChat.honorific()) || 'Sir'; } catch (_) { return 'Sir'; } };
  const LOST_LINE = () => `The mic is off, but it won't stay off after a reload — your browser blocked storage, ${honorific()}.`;
  const OPEN_STATES = new Set(['on', 'paused', 'resume', 'loading']);
  const S = { conversation: false, wake: false };
  const line = (t) => { if (lineEl) lineEl.textContent = t; };
  const live = (t) => { if (liveEl) liveEl.textContent = t; };

  function paint() {
    if (!offBtn) return;
    offBtn.hidden = A.locked() || !(S.conversation || S.wake);
  }
  document.addEventListener('jarvis:voice-loop', (e) => { S.conversation = !!(e.detail && e.detail.conversation); paint(); });
  document.addEventListener('jarvis:wake', (e) => { S.wake = !!(e.detail && OPEN_STATES.has(e.detail.state)); paint(); });
  A.onLock(({ locked, by, persisted }) => {
    paint();
    if (locked && persisted === false) { live('Microphone off'); line(LOST_LINE()); return; }
    if (locked) { live('Microphone off'); if (by !== 'voice') line(OFF_LINE); } else { live('Microphone on'); line(''); }
  });

  if (offBtn) offBtn.addEventListener('click', () => A.lock('button'));
  document.addEventListener('keydown', (e) => {
    if (!e.isTrusted || e.isComposing || !e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey) return;
    if (!(e.code === 'Space' || e.key === ' ')) return;
    e.preventDefault();
    if (e.repeat) return;
    if (A.locked()) A.unlock('shortcut'); else A.lock('shortcut');
  }, true);
})();
