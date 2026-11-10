// src/jarvis/api/static/console-systems-modal.js -- R5.1 D6 (docs/plans/r5-1-observations.md): the
// systems-check pop-up. No build step; CSP script-src 'self'; ASCII source; every server string
// reaches the page through textContent. A native modal <dialog> styled like the console's own
// (.bdialog), built here. Flow: POST /v1/health/run/stream {force: true} (NDJSON: plan, result per
// system, done) -> every system listed with a pending marker -> each row ticks as its result
// arrives (symbol AND word) -> Vitals, what needs attention, the spoken briefing -> JARVIS says the
// briefing through the shared speaker (not when "Speak replies: Never" or no voice) -> "Closing in
// 10 s" once results are in and the speech has ended; any pointer, key or focus inside the dialog
// cancels it ("Kept open"). Falls back to POST /v1/health/run when the stream answers 404 / 405
// or the browser can't stream. Reminders: POST /v1/health/remind {key, when, session_id?}.
//   window.JarvisSystemsCheck = { open({via, opener, closeAfterMs}), matches(text, {typed, named}), canHear(text) }
//   (the last two are console-systems-voice.js's: the phrases, and the echo guard for the pop-up's own speech)
//   listens: document 'jarvis:systems-check' {via}; fires 'jarvis:health' {data} (the done
//   payload, for the Systems card) and 'jarvis:event' log lines.
(() => {
  'use strict';
  if (window.JarvisSystemsCheck) return;
  const CLOSE_AFTER_MS = 10000;
  const MAX_ROWS = 20, TEXT_MAX = 240;
  // no trigger phrase in it: the microphone must never hear this line as the command
  const CLOSING = 'Closing this window, Sir. Whenever you\'d like a fresh check, just ask and I\'ll update the status.';
  const FAILED = 'The check did not complete. Try Run again.';
  const FAILED_LOG = 'Systems check: the check did not complete';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const BUSY = 'Too many checks just now. Wait a moment, then Run again.';
  const WORDS = Object.freeze({ pending: 'Checking', ok: 'OK', degraded: 'Degraded', down: 'Down', skipped: 'Not set up', unknown: 'Not checked' });
  const SEV = Object.freeze({ down: 'Down', degraded: 'Degraded', red: 'Act now', amber: 'Watch' }); // Vitals' own words
  const NBSP = String.fromCharCode(160); // "10 am" never splits over two lines
  const WHENS = Object.freeze([['1h', 'In 1' + NBSP + 'hour'], ['evening', 'This evening'], ['tomorrow', 'Tomorrow 10' + NBSP + 'am']]);
  const SVG = 'http://www.w3.org/2000/svg';
  const ICONS = Object.freeze({ ok: ['m5 10.4 3.3 3.3L15 7'], degraded: ['M10 5.2v6', 'M10 14.6v.2'],
    down: ['m6.2 6.2 7.6 7.6', 'M13.8 6.2l-7.6 7.6'], skipped: ['M6 10h8'], close: ['m5.5 5.5 9 9', 'M14.5 5.5l-9 9'] });
  const S = { dlg: null, ui: {}, rows: new Map(), data: null, phase: 'idle', opener: null, run: 0, ctrl: null,
    closeAfterMs: CLOSE_AFTER_MS, deadline: 0, timer: 0, kept: false,
    reminded: new Set(), reminding: false, progFocus: false };

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = TEXT_MAX) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const motionOff = () => document.documentElement.dataset.motion === 'off' ||
    (!document.documentElement.dataset.motion && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function icon(name) {
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('viewBox', '0 0 20 20'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    (ICONS[name] || []).forEach((d) => { const p = document.createElementNS(SVG, 'path'); p.setAttribute('d', d); s.appendChild(p); });
    return s;
  }

  // ---- the dialog ------------------------------------------------------------------------------
  function button(cls, text, id) { const b = mk('button', cls, text); b.type = 'button'; if (id) b.id = id; return b; }
  function section(cls, title) {
    const s = mk('section', cls); s.hidden = true;
    if (title) s.appendChild(mk('h3', 'scsec', title));
    return s;
  }
  function build() {
    if (S.dlg) return S.dlg;
    const d = mk('dialog', 'bdialog syscheck'); d.id = 'sysCheck';
    d.setAttribute('aria-labelledby', 'sysCheckTitle'); d.setAttribute('aria-describedby', 'sysCheckStatus');
    const head = mk('div', 'schead'), h = mk('h2', '', 'Systems check'); h.id = 'sysCheckTitle';
    const x = button('pbtn scx', '', ''); x.setAttribute('aria-label', 'Close the systems check'); x.appendChild(icon('close'));
    head.append(h, x);
    const status = mk('p', 'scstatus'); status.id = 'sysCheckStatus'; status.setAttribute('role', 'status');
    const bar = mk('div', 'mbar scbar'), fill = mk('i'); bar.appendChild(fill); bar.setAttribute('aria-hidden', 'true');
    const list = mk('ul', 'sclist'); list.setAttribute('aria-label', 'Systems');
    const vit = section('scvit', 'Vitals'), spend = mk('p', 'scspend'); vit.appendChild(spend);
    const att = section('scatt', 'Needs attention'), concerns = mk('ul', 'scconcerns'); att.appendChild(concerns);
    const rem = section('scremind', ''), remHead = mk('div', 'scremhead');
    const said = section('scbrief', 'What JARVIS said'), saidP = mk('p', 'scsaid'); said.appendChild(saidP);
    rem.append(remHead);
    const seg = mk('div', 'seg scwhen'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'When to remind you');
    WHENS.forEach(([when, words]) => { const b = button('seg-opt', words); b.dataset.when = when; b.addEventListener('click', () => remind(when)); seg.appendChild(b); });
    const remNote = mk('p', 'bnote scremnote'); remNote.setAttribute('role', 'status');
    rem.append(seg, remNote);
    const count = mk('p', 'sccount'); count.setAttribute('aria-hidden', 'true'); // the ticking numbers stay silent
    const hear = mk('p', 'sr-only'); hear.setAttribute('aria-live', 'polite'); hear.setAttribute('aria-atomic', 'true');
    const acts = mk('div', 'actions'), again = button('btn lift', 'Run again', 'sysCheckAgain');
    const speakB = button('btn lift', 'Speak again', 'sysCheckSpeak'), close = button('btn primary lift', 'Close', 'sysCheckClose');
    acts.append(again, speakB, close);
    const top = mk('div', 'sctop'), foot = mk('div', 'scfoot'); // both stay in view while the middle scrolls
    top.append(head, status, bar); foot.append(count, hear, acts);
    d.append(top, list, vit, att, rem, said, foot);
    x.addEventListener('click', () => shut('button'));
    close.addEventListener('click', () => shut('button'));
    again.addEventListener('click', () => start(true));
    speakB.addEventListener('click', () => { if (S.data) { SV().unlock(true); say(S.data.spoken, null, true); } }); // asked for: even with "Never"
    d.addEventListener('cancel', (e) => { e.preventDefault(); shut('esc'); });
    d.addEventListener('keydown', onKey);
    ['pointerdown', 'pointermove', 'wheel'].forEach((t) => d.addEventListener(t, onPointer, { passive: true }));
    d.addEventListener('focusin', () => { if (!S.progFocus) keep(); });
    document.body.appendChild(d);
    S.dlg = d;
    S.ui = { status, bar, fill, list, vit, spend, att, concerns, rem, remHead, seg, remNote, said, saidP, count, hear, again, speakB, close };
    return d;
  }
  /** Our own focus move is not the owner doing something. */
  function focusClose() {
    S.progFocus = true;
    try { S.ui.close.focus({ preventScroll: true }); } finally { S.progFocus = false; }
  }
  function inside(e) {
    const r = S.dlg.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  }
  function onPointer(e) {
    if (e.type === 'pointermove' && !e.movementX && !e.movementY) return; // a layout change, not the owner
    if (inside(e)) keep();
  }
  function onKey(e) {
    keep();
    if (e.key !== 'Tab') return;
    const items = [...S.dlg.querySelectorAll('button:not([disabled]), select:not([disabled])')].filter((n) => n.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // ---- rows ------------------------------------------------------------------------------------
  function setRow(key, name, state, reason) {
    let r = S.rows.get(key);
    if (!r) {
      if (S.rows.size >= MAX_ROWS) return;
      const li = mk('li', 'scrow'), ic = mk('span', 'scicon'), body = mk('span', 'scbody');
      const nm = mk('span', 'scname'), why = mk('span', 'screason'), word = mk('span', 'scword');
      li.dataset.key = key; ic.setAttribute('aria-hidden', 'true');
      body.append(nm, why); li.append(ic, body, word); S.ui.list.appendChild(li);
      r = { li, ic, nm, why, word, state: '' };
      S.rows.set(key, r);
    }
    r.nm.textContent = cap(name);
    if (r.state !== state) {
      r.state = state; r.li.dataset.state = state; r.word.textContent = WORDS[state];
      r.ic.replaceChildren(); if (state !== 'pending') r.ic.appendChild(icon(state === 'unknown' ? 'skipped' : state));
    }
    r.why.textContent = state === 'pending' || state === 'skipped' ? '' : reason;
    r.why.hidden = !r.why.textContent;
  }
  function progress() {
    const all = [...S.rows.values()], done = all.filter((r) => r.state !== 'pending').length;
    S.ui.fill.style.width = (all.length ? Math.round((done / all.length) * 100) : 0) + '%';
    if (S.phase === 'checking') S.ui.status.textContent = all.length ? `Checked ${done} of ${all.length} systems...` : 'Starting the systems check...';
  }
  const STATE = (s) => (['ok', 'degraded', 'down', 'skipped'].includes(s) ? s : null); // what the server may say
  function onEvent(ev) {
    const e = obj(ev); if (!e) return;
    if (e.type === 'plan' && Array.isArray(e.systems)) {
      e.systems.slice(0, MAX_ROWS).forEach((s) => { const o = obj(s); const k = o && txt(o.key, 40); if (k) setRow(k, txt(o.name, 60) || k, 'pending', ''); });
    } else if (e.type === 'result') {
      const k = txt(e.key, 40), st = STATE(e.status); if (k && st) setRow(k, txt(e.name, 60) || k, st, txt(e.reason, 160));
    } else if (e.type === 'done') { finish(e); return; } else if (e.type === 'error') { fail(FAILED); return; }
    progress();
  }

  // ---- the run -----------------------------------------------------------------------------------
  function reset() {
    S.rows.clear(); S.data = null; S.reminded.clear(); S.reminding = false;
    const u = S.ui;
    u.list.replaceChildren(); u.concerns.replaceChildren(); u.saidP.textContent = ''; u.spend.textContent = '';
    [u.vit, u.att, u.rem, u.said].forEach((n) => { n.hidden = true; });
    u.remNote.textContent = ''; u.remNote.className = 'bnote scremnote'; u.status.className = 'scstatus';
    u.fill.style.width = '0%'; u.count.textContent = ''; u.hear.textContent = '';
  }
  async function start(force) {
    stopCountdown(); stopSpeech(); S.kept = false;
    if (S.ctrl) { try { S.ctrl.abort(); } catch (_) {} }
    const run = ++S.run, ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    S.ctrl = ctrl; S.phase = 'checking'; S.dlg.dataset.phase = 'checking';
    reset(); progress();
    if (document.activeElement === S.ui.again || document.activeElement === S.ui.speakB) focusClose();
    S.ui.again.disabled = true; S.ui.speakB.disabled = true;
    try {
      if (!(await streamed(run, ctrl, force))) await fallback(run);
      if (run === S.run && S.phase === 'checking') fail(FAILED); // the stream ended without "done"
    } catch (e) {
      if (run !== S.run || (e && e.name === 'AbortError')) return;
      fail(e && e.name === 'TypeError' ? OFFLINE : e && (e.message === 'busy' || e.status === 429) ? BUSY : FAILED);
    }
  }
  /** false when this server or browser can't stream (then /run is asked instead). */
  async function streamed(run, ctrl, force) {
    const chat = window.JarvisChat;
    if (!chat || typeof chat.raw !== 'function' || typeof TextDecoder !== 'function') return false;
    const r = await chat.raw('/v1/health/run/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: !!force }), signal: ctrl ? ctrl.signal : undefined });
    if (r.status === 404 || r.status === 405 || !r.body || typeof r.body.getReader !== 'function') return false;
    if (!r.ok) throw new Error(r.status === 429 ? 'busy' : 'failed');
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (run !== S.run) { try { reader.cancel(); } catch (_) {} return true; }
      buf += dec.decode(value || new Uint8Array(), { stream: !done });
      let at;
      while ((at = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, at).trim(); buf = buf.slice(at + 1); if (line) onLine(line); }
      if (done) { if (buf.trim()) onLine(buf.trim()); return true; }
    }
  }
  function onLine(line) { let ev = null; try { ev = JSON.parse(line); } catch (_) { return; } onEvent(ev); }
  async function fallback(run) {
    const JC = window.JarvisConsole; if (!JC || typeof JC.api !== 'function') throw new Error('failed');
    const d = obj(await JC.api('/v1/health/run', { method: 'POST', body: {} }));
    if (run !== S.run || !d) return;
    const systems = Array.isArray(d.systems) ? d.systems : [];
    onEvent({ type: 'plan', systems });
    for (const s of systems) { if (!motionOff()) await new Promise((ok) => setTimeout(ok, 140)); if (run !== S.run) return; onEvent({ type: 'result', ...obj(s) }); }
    onEvent({ type: 'done', ...d });
  }
  function fail(words) {
    S.phase = 'failed'; S.dlg.dataset.phase = 'failed';
    S.ui.status.textContent = words; S.ui.status.className = 'scstatus bad';
    S.ui.again.disabled = false;
    [...S.rows.values()].forEach((r) => { if (r.state === 'pending') setRow(r.li.dataset.key, r.nm.textContent, 'unknown', ''); });
    stopCountdown(); S.ui.count.textContent = ''; // a failure stays up until the owner closes it or runs again
    log('error', FAILED_LOG);
  }

  // ---- done: vitals, concerns, the briefing ---------------------------------------------------------
  function normal(e) {
    const b = obj(e.briefing) || {};
    const concerns = (Array.isArray(b.concerns) ? b.concerns : []).map(obj).filter(Boolean).slice(0, MAX_ROWS)
      .map((c) => ({ key: txt(c.key, 64), label: txt(c.label, 80), sev: Object.prototype.hasOwnProperty.call(SEV, c.severity) ? c.severity : '',
        impact: txt(c.impact, 200), fix: txt(c.fix, 200) })).filter((c) => c.key && c.label && c.sev);
    const lines = Array.isArray(b.lines) ? b.lines.slice(0, 60).map((l) => txt(l, 1200)).filter(Boolean) : [];
    const spoken = txt(b.spoken, 1200) || txt(e.spoken, 400);
    return { spoken, said: lines.join(' ').slice(0, 6000) || spoken, spend: txt(b.spend, 200), concerns };
  }
  function finish(e) {
    const d = normal(e);
    (Array.isArray(e.systems) ? e.systems : []).forEach((s) => onEvent({ type: 'result', ...obj(s) }));
    [...S.rows.values()].forEach((r) => { if (r.state === 'pending') setRow(r.li.dataset.key, r.nm.textContent, 'skipped', ''); });
    S.data = d; S.phase = 'done'; S.dlg.dataset.phase = 'done';
    const rows = [...S.rows.values()], down = rows.filter((r) => r.state === 'down').length, slow = rows.filter((r) => r.state === 'degraded').length;
    const checked = rows.filter((r) => r.state !== 'skipped').length;
    const bits = [down && `${down} down`, slow && `${slow} degraded`].filter(Boolean);
    S.ui.status.textContent = `Checked ${checked} ${checked === 1 ? 'system' : 'systems'}: ` + (bits.length ? bits.join(', ') + '.' : 'all working.');
    S.ui.status.className = 'scstatus ' + (down ? 'bad' : slow ? 'warn' : 'ok');
    S.ui.fill.style.width = '100%';
    paintVitals(d); paintConcerns(d); paintRemind(d);
    S.ui.saidP.textContent = d.said; S.ui.said.hidden = !d.said;
    S.ui.again.disabled = false; S.ui.speakB.disabled = !d.spoken || !SV().usable(true);
    emit('jarvis:health', { data: e });
    log(down ? 'error' : 'info', d.concerns.length ? `Systems check: ${d.concerns.length} to look at` : 'Systems check: all systems nominal');
    afterResults(d.spoken);
  }
  function paintVitals(d) { S.ui.spend.textContent = d.spend; S.ui.vit.hidden = !d.spend; }
  function paintConcerns(d) {
    S.ui.concerns.replaceChildren();
    d.concerns.forEach((c) => {
      const li = mk('li', 'scconcern'); li.dataset.sev = c.sev;
      const top = mk('div', 'schead2'), word = mk('span', 'v up ' + (c.sev === 'down' || c.sev === 'red' ? 'bad' : 'warn'), SEV[c.sev]);
      top.append(mk('b', '', cap(c.label)), word);
      li.append(top, mk('p', 'scimpact', cap(c.impact) + '.'));
      if (c.fix) li.appendChild(mk('p', 'bfine', c.fix));
      S.ui.concerns.appendChild(li);
    });
    S.ui.att.hidden = !d.concerns.length;
  }
  function paintRemind(d) {
    const u = S.ui; u.remHead.replaceChildren(); u.rem.hidden = !d.concerns.length;
    if (!d.concerns.length) return;
    const label = mk('label', 'k', 'Remind me to fix'); label.htmlFor = 'sysRemKey';
    const sel = mk('select', 'bsel'); sel.id = 'sysRemKey';
    d.concerns.forEach((c) => { const o = mk('option', '', cap(c.label)); o.value = c.key; sel.appendChild(o); });
    sel.addEventListener('change', () => {
      if (S.reminding) return; // an answer is still on its way: its note stays
      u.remNote.textContent = ''; u.remNote.className = 'bnote scremnote'; whenButtons();
    });
    u.remHead.append(label, sel); whenButtons();
  }
  function whenButtons() {
    const sel = document.getElementById('sysRemKey'), done = !!sel && S.reminded.has(sel.value);
    S.ui.seg.querySelectorAll('button').forEach((b) => { b.disabled = S.reminding || done; });
    if (sel) sel.disabled = S.reminding;
  }
  async function remind(when) {
    const sel = document.getElementById('sysRemKey'), JC = window.JarvisConsole;
    if (!sel || !sel.value || !JC || typeof JC.api !== 'function') return;
    if (S.reminding) return;
    const key = sel.value, body = { key, when }, A = window.JarvisApprovals;
    const sid = A && typeof A.session === 'function' ? A.session() : null;
    if (typeof sid === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(sid)) body.session_id = sid;
    const note = S.ui.remNote; S.reminding = true; whenButtons();
    try {
      const r = obj(await JC.api('/v1/health/remind', { method: 'POST', body })) || {};
      const ok = r.outcome === 'executed', waiting = r.outcome === 'awaiting_confirmation';
      note.textContent = txt(r.line, 200) || (ok ? 'Reminder set.' : 'That reminder couldn\'t be set, Sir.');
      note.className = 'bnote scremnote' + (ok ? ' ok' : waiting ? '' : ' bad');
      if (ok || waiting) { S.reminded.add(key); log('info', note.textContent); }
    } catch (e) {
      note.textContent = e && e.name === 'TypeError' ? OFFLINE : 'That reminder couldn\'t be set, Sir.'; note.className = 'bnote scremnote bad';
    }
    S.reminding = false; whenButtons();
  }

  // ---- speech and the countdown -------------------------------------------------------------------
  // ---- speech and the countdown: the words and the speaker are console-systems-voice.js's ---------
  const NO_VOICE = Object.freeze({ matches: () => false, canHear: () => true, say: (_t, then) => { if (then) then(); },
    stop() {}, unlock() {}, hook() {}, usable: () => false, speaking: () => false, voiced: () => false, forget() {} });
  const SV = () => window.JarvisSystemsVoice || NO_VOICE;
  const say = (t, then, asked) => SV().say(t, then, asked), stopSpeech = (hush) => SV().stop(hush);
  function afterResults(spoken) {
    if (spoken) say(spoken, countdown); else countdown();
  }
  const inField = () => { const a = document.activeElement; return !!a && !!S.dlg && S.dlg.contains(a) && /^(SELECT|INPUT|TEXTAREA)$/.test(a.tagName); };
  function countdown() {
    if (!S.dlg || !S.dlg.open || S.kept) return;
    if (inField()) { keep(); return; } // never closes under someone filling in a control
    stopCountdown();
    S.deadline = Date.now() + S.closeAfterMs;
    S.ui.hear.textContent = 'Closing in ' + Math.round(S.closeAfterMs / 1000) + ' seconds \u2014 press any key or click to keep it open';
    const step = () => {
      const left = S.deadline - Date.now();
      if (inField()) { keep(); return; }
      if (left <= 0) { stopCountdown(); shut('timeout'); return; }
      S.ui.count.textContent = `Closing in ${Math.ceil(left / 1000)} s`;
    };
    step(); S.timer = setInterval(step, 250);
  }
  function stopCountdown() { clearInterval(S.timer); S.timer = 0; }
  /** The owner did something inside the dialog, at any point after it opened: no auto-close, for good
   * (until the next run). The "Kept open" words show only if a countdown was on screen. */
  function keep() {
    if (!S.dlg || !S.dlg.open || S.phase === 'idle') return;
    S.kept = true;
    if (!S.timer) return;
    stopCountdown();
    S.ui.count.textContent = 'Kept open. Close it when you\'re done, Sir.';
    S.ui.hear.textContent = 'Kept open.';
  }

  // ---- open / close ---------------------------------------------------------------------------------
  function shut(why) {
    const d = S.dlg; if (!d || !d.open) return;
    try {
      stopCountdown();
      if (why === 'timeout') { S.ui.count.textContent = CLOSING; if (SV().voiced()) say(CLOSING, null); }
      else stopSpeech();
      log('info', CLOSING);
    } catch (_) { /* whatever went wrong, the window still closes */ } finally {
      stopCountdown();
      if (S.ctrl) { try { S.ctrl.abort(); } catch (_) {} S.ctrl = null; }
      S.run++; S.phase = 'idle';
      try { d.close(); } catch (_) { d.removeAttribute('open'); }
      const o = S.opener; S.opener = null;
      try { if (o && document.contains(o) && !o.closest('[hidden]') && typeof o.focus === 'function') o.focus({ preventScroll: true }); } catch (_) {}
    }
  }
  function open(opts) {
    const o = obj(opts) || {};
    const d = build();
    if (typeof d.showModal !== 'function') { log('error', 'This browser can\'t show the systems check.'); return false; }
    const ms = Number(o.closeAfterMs);
    S.closeAfterMs = Number.isFinite(ms) && ms >= 500 && ms <= 600000 ? ms : CLOSE_AFTER_MS;
    SV().forget();
    if (!d.open) {
      const el = o.opener instanceof Element ? o.opener : document.activeElement;
      S.opener = el instanceof HTMLElement && el !== document.body ? el : null;
      d.showModal();
      focusClose();
    }
    SV().hook(); SV().unlock();
    start(true);
    return true;
  }

  document.addEventListener('jarvis:systems-check', (e) => { const d = obj(e && e.detail) || {}; open({ via: txt(d.via, 20) }); });
  window.JarvisSystemsCheck = Object.freeze({ open, matches: (t, o) => SV().matches(t, o), canHear: (t) => SV().canHear(t) });
})();
