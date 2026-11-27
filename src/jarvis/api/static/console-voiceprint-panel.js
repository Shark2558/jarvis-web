// src/jarvis/api/static/console-voiceprint-panel.js - R5.2 row 84 (docs/plans/r5-2-voice.md 3.5, D6): Voice -> Speaker
// check. Says whether this device knows the owner's voice, records the 1-minute reading (or uses the voice session's
// clips on the laptop), switches the check on or off for this device and forgets the print (after a confirm).
// It renders into JarvisVoice.panelSlot('speaker') when the panel has that slot, otherwise into its own slot right
// after the "Words to recognise" one. No build step; CSP script-src 'self'; textContent only; existing classes only.
// It shows no score and no number of the print, and it approves nothing: the words say so.
(() => {
  'use strict';
  const P = () => window.JarvisVoicePrint || null;
  const V = () => window.JarvisVoice || null;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const PASSAGE = [
    'Good morning, Jarvis. What is on my calendar today? Remind me to call the bank at half past four.',
    'Play some quiet music and turn the lights down a little. How long will it take to reach the airport if I leave at six fifteen?',
    'Read me the headlines, then the weather for the weekend. Add milk, bread, rice and two dozen eggs to the shopping list.',
    'Set a timer for twelve minutes. When is the next train, and is it on time? Stop. Jarvis, wait a moment. Thank you, that is all for now.',
  ];
  const STATUS = {
    unsupported: 'This browser can\'t run the speaker check, so any voice can interrupt JARVIS here, as before.',
    no_model: 'The speaker-check model isn\'t installed on JARVIS yet, so any voice can interrupt him here, as before.',
    loading: 'Loading the speaker check on this device...',
    none: 'Not set up on this device. Read aloud for a minute to make your voice print.',
    off: 'Off on this device. Your voice print is kept; any voice can interrupt JARVIS here until you switch it on.',
    error: 'The speaker check couldn\'t start here, so any voice can interrupt JARVIS, as before. If this stays, forget the voice print and record again.',
  };
  const FAILED = {
    too_little: 'That wasn\'t enough of your voice to make a print. Try again and read the whole passage.',
    mic_off: 'The microphone is off. Switch it on, then try again.',
    mic: 'The microphone didn\'t start. Please try again.',
    model: 'The speaker-check model couldn\'t be loaded on this device.',
    store_failed: 'This browser couldn\'t save the voice print.',
    unsupported: STATUS.unsupported,
  };
  const WEAK = ' It came out weak: record again somewhere quieter for better results.';
  const UI = {};
  let recording = null, confirming = false;

  const day = (iso) => {
    const d = /^\d{4}-\d{2}-\d{2}$/.test(iso || '') ? new Date(iso + 'T12:00:00') : null;
    return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  };
  function readyText(info) {
    const from = info.source === 'session' ? 'your voice session' : 'a minute of reading';
    const when = day(info.made);
    return `On. Only your voice can interrupt JARVIS on this device (voice print made${when ? ' on ' + when : ''} from ${from}).`
      + (info.quality === 'weak' ? WEAK : '');
  }
  function say(text, kind) {
    UI.note.textContent = text;
    UI.note.className = 'bnote' + (kind ? ' ' + kind : '');
  }

  // ---- building -----------------------------------------------------------------------------------------------------
  function button(id, text, onClick, cls) {
    const b = mk('button', cls || 'btn bact', text);
    b.type = 'button'; b.id = id; b.style.marginTop = '0';
    b.addEventListener('click', onClick);
    return b;
  }
  function build(slot) {
    slot.textContent = '';
    const sec = mk('section', 'bsec'), h = mk('h3');
    sec.id = 'vPrint'; sec.setAttribute('aria-labelledby', 'vPrintT');
    h.id = 'vPrintT'; h.append(mk('span', '', 'Speaker check')); sec.append(h);
    sec.append(mk('p', 'bfine vlead',
      'When this is on, only your voice can interrupt JARVIS while he speaks on this device, so a TV or another person '
      + 'can\'t cut him off. Your voice print stays in this browser, encrypted, and is never uploaded. It never approves '
      + 'anything: approvals, passkeys and unlocks still need you on screen.'));
    UI.status = mk('div', 'vstatus'); UI.status.id = 'vPrintStatus'; UI.status.setAttribute('role', 'status');
    UI.statusLine = mk('p', 'vline-s'); UI.status.append(UI.statusLine);
    // the switch: built like the panel's own toggles (console-voice.js)
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('span', 'bl', 'Use my voice print on this device'); l.id = 'vPrintOnL';
    const d = mk('small', '', 'Off: any voice can interrupt JARVIS here, as before. The voice print is kept.'); d.id = 'vPrintOnD';
    t.append(l, d);
    UI.sw = mk('button', 'bsw'); UI.sw.type = 'button'; UI.sw.id = 'vPrintOn';
    UI.sw.setAttribute('aria-pressed', 'false'); UI.sw.setAttribute('aria-labelledby', l.id); UI.sw.setAttribute('aria-describedby', d.id);
    const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
    const st = mk('span', 'st', 'Off'); st.setAttribute('aria-hidden', 'true');
    UI.sw.append(track, st);
    UI.sw.addEventListener('click', toggle);
    row.append(t, UI.sw);
    UI.swRow = row;
    // the actions
    UI.actions = mk('div', 'bopt'); UI.actions.style.flexWrap = 'wrap'; UI.actions.style.justifyContent = 'flex-start';
    UI.record = button('vPrintRecord', 'Record 1 minute', startReading);
    UI.session = button('vPrintSession', 'Use my voice session', useSession);
    UI.forget = button('vPrintForget', 'Forget voice print', askForget);
    UI.actions.append(UI.record, UI.session, UI.forget);
    // the reading
    UI.reading = mk('div', 'vstatus'); UI.reading.id = 'vPrintReading'; UI.reading.hidden = true;
    UI.reading.append(mk('p', 'vline-s', 'Read this aloud at your normal pace, as you would talk to JARVIS. Pauses are fine.'));
    PASSAGE.forEach((line) => UI.reading.append(mk('p', 'vline-s', line)));
    UI.progress = mk('p', 'vline-s ok'); UI.progress.id = 'vPrintProgress';   // not a live region: it ticks every second
    UI.stop = button('vPrintStop', 'Stop and save', () => { if (recording) recording.stop(); });
    UI.reading.append(UI.progress, UI.stop);
    // forgetting asks first
    UI.confirm = mk('div', 'vstatus'); UI.confirm.id = 'vPrintConfirm'; UI.confirm.hidden = true;
    UI.confirm.append(mk('p', 'vline-s warn', 'Forget the voice print on this device? Any voice will be able to interrupt JARVIS here until you make a new one.'));
    const yes = button('vPrintForgetYes', 'Forget voice print', doForget, 'btn danger bact');
    UI.keep = button('vPrintKeep', 'Keep it', () => { confirming = false; render(); UI.forget.focus(); });
    const pair = mk('div', 'bopt'); pair.style.justifyContent = 'flex-start'; pair.style.borderTop = '0';
    pair.append(yes, UI.keep);
    UI.confirm.append(pair);
    UI.note = mk('p', 'bnote'); UI.note.id = 'vPrintNote'; UI.note.setAttribute('role', 'status');
    sec.append(UI.status, UI.swRow, UI.actions, UI.reading, UI.confirm, UI.note);
    slot.append(sec);
    UI.slot = slot;
  }
  function slotFor() {
    const v = V();
    if (!v || typeof v.panelSlot !== 'function') return null;
    const own = v.panelSlot('speaker');
    if (own) return own;
    const after = v.panelSlot('phrases');
    if (!after || !after.parentNode) return null;
    let slot = document.getElementById('vSlotSpeaker');
    if (!slot || slot.parentNode !== after.parentNode) { slot = mk('div', 'vslot'); slot.id = 'vSlotSpeaker'; after.after(slot); }
    return slot;
  }

  // ---- rendering ----------------------------------------------------------------------------------------------------
  function render() {
    const p = P(), slot = slotFor();
    if (!p || !slot) return;
    if (!UI.slot || UI.slot !== slot || !slot.contains(UI.note)) build(slot);
    const st = p.state(), info = p.info(), saved = info.saved === true, on = p.isOn();
    UI.statusLine.textContent = st === 'ready' ? readyText(info) : (STATUS[st] || STATUS.loading);
    UI.statusLine.className = 'vline-s' + (st === 'ready' ? ' ok' : st === 'error' ? ' warn' : '');
    UI.sw.setAttribute('aria-pressed', String(saved && on));
    UI.sw.querySelector('.st').textContent = saved && on ? 'On' : 'Off';
    UI.sw.setAttribute('aria-disabled', String(!saved));
    UI.swRow.hidden = !saved;
    const canRecord = st !== 'unsupported' && st !== 'no_model';
    UI.actions.hidden = !!recording || confirming;
    UI.record.textContent = saved ? 'Record again' : 'Record 1 minute';
    UI.record.disabled = !canRecord;
    UI.record.hidden = !canRecord; // I1: no model yet: the status line says so (no faded button)
    const kept = p.sessionCount();
    UI.session.hidden = !(canRecord && kept >= p.ENROL_MIN);
    UI.forget.hidden = !saved;
    UI.reading.hidden = !recording;
    UI.confirm.hidden = !confirming;
  }

  // ---- actions ------------------------------------------------------------------------------------------------------
  function toggle() {
    const p = P();
    if (!p || p.info().saved !== true) return;
    p.setOn(UI.sw.getAttribute('aria-pressed') !== 'true');
    say('');
    render();
  }
  function shown(result) {
    if (result && result.ok) say(`Voice print saved on this device.${result.quality === 'weak' ? WEAK : ''}`, 'ok');
    else say(FAILED[result && result.reason] || FAILED.model, 'bad');
  }
  function startReading() {
    const p = P();
    if (!p || recording) return;
    say('');
    const seconds = Math.round(p.READ_MS / 1000);
    UI.progress.textContent = `Recording: 0 of ${seconds} seconds.`;
    recording = p.recordReading({
      onProgress: ({ ms, voicedMs }) => {
        const text = `Recording: ${Math.min(seconds, Math.floor(ms / 1000))} of ${seconds} seconds, `
          + `${Math.floor(voicedMs / 1000)} seconds of your voice so far.`;
        if (UI.progress.textContent !== text) UI.progress.textContent = text;
      },
    });
    render();
    UI.stop.focus();
    recording.done.then((result) => {
      recording = null;
      render();
      shown(result);
      UI.record.focus();
    });
  }
  function useSession() {
    const p = P();
    if (!p) return;
    UI.session.disabled = true;
    p.useSession().then((result) => { UI.session.disabled = false; render(); shown(result); });
  }
  function askForget() {
    confirming = true;
    say('');
    render();
    UI.keep.focus();                                             // the safe choice has the focus
  }
  function doForget() {
    const p = P();
    if (!p) return;
    p.forget().then((ok) => {
      confirming = false;
      render();
      say(ok ? 'Voice print forgotten on this device.' : 'This browser couldn\'t forget the voice print. Please try again.', ok ? 'ok' : 'bad');
      UI.record.focus();
    });
  }

  document.addEventListener('jarvis:voice-panel', render);
  document.addEventListener('jarvis:voiceprint', render);
  document.addEventListener('jarvis:ready', render);
  render();
})();
