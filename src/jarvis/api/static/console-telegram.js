// src/jarvis/api/static/console-telegram.js -- R1 (docs/plans/r1-free-tools.md D1/D2/D4/D6):
// Integrations -> Telegram. Built beside #integrations (console.js redraws that box), so the page
// markup stays untouched; its confirm/pair dialog is built here too. No build step; CSP script-src
// 'self'; ASCII source with backslash-u escapes only; every server string reaches the page through
// textContent (never markup); a field of the wrong type is dropped, never guessed. Transport is the
// console's api() (cookie + X-Requested-With, or the bearer token; 401 -> gate). Loads when the
// Integrations panel opens, never on page load.
// API: GET /v1/telegram -> {configured:false} | {configured, bot_username, paired, paired_at,
// account_hint, webhook:{registered, pending, last_error}, allow_private_reads, allow_personal_reads,
// alerts:{approval_waiting, offline, brief_ready, vault_expiry}}; POST /v1/telegram/pair -> {code, link,
// expires_in_s}; DELETE /v1/telegram/pair; PUT /v1/telegram/settings {allow_private_reads?,
// allow_personal_reads?, alerts?}; POST /v1/telegram/test-alert -> {sent, reason?}.
// Off (no bot token): the section stays visible and says how to switch it on.
// R2 D12: a second switch for the vault list, notes and things, with its own confirm that names
// exactly what it opens (vault metadata, never files; notes, memos and links; where things are kept).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STALE_MS = 30 * 1000;
  const POLL_MS = 3000;
  const POLL_MAX_MS = 10 * 60 * 1000;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const LINK = /^https:\/\/t\.me\/[A-Za-z0-9_]{4,64}\?start=[0-9A-Z]{8}$/;
  const CODE = /^[0-9A-Z]{8}$/;
  const HINT = /^[\u2022]{2}[0-9]{1,6}$/;
  const STEPS = [
    'In Telegram open @BotFather, send /newbot and copy the token it gives you.',
    'In Google Cloud Shell run: bash deploy/cloudrun.sh --telegram and paste the token when asked.',
    'Come back here and press Pair.',
  ];
  const ALERTS = [
    ['approval_waiting', 'Something is waiting for my approval'],
    ['offline', 'Offline mode switches on or off'],
    ['brief_ready', 'My morning brief is ready'],
    ['vault_expiry', 'A document in my vault is due to expire'],
  ];
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: false, pair: null, timer: 0 };
  let card = null, stateEl = null, bodyEl = null, noteEl = null, dlg = null, settle = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }

  /** GET /v1/telegram, checked field by field. {configured:false} when off here. */
  function normal(raw) {
    const d = obj(raw);
    if (!d || d.configured !== true) return { configured: false };
    const wh = obj(d.webhook) || {};
    const al = obj(d.alerts) || {};
    return {
      configured: true,
      bot: typeof d.bot_username === 'string' && /^[A-Za-z0-9_]{4,64}$/.test(d.bot_username) ? d.bot_username : '',
      paired: d.paired === true,
      pending: d.pairing_pending !== false, // a server that does not say is not blamed
      hint: typeof d.account_hint === 'string' && HINT.test(d.account_hint) ? d.account_hint : '',
      reads: d.allow_private_reads === true,
      personal: d.allow_personal_reads === true,
      alerts: { approval_waiting: al.approval_waiting !== false, offline: al.offline !== false, brief_ready: al.brief_ready === true, vault_expiry: al.vault_expiry === true },
      webhook: {
        registered: wh.registered === true ? true : wh.registered === false ? false : null,
        pending: Number.isInteger(wh.pending) && wh.pending >= 0 ? wh.pending : 0,
        error: txt(wh.last_error, 160),
      },
    };
  }

  // ---- the card -------------------------------------------------------------------------------
  function build() {
    if (card) return true;
    const host = $('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ telegram'); card.id = 'telegramSet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'telegramHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Telegram'); title.id = 'telegramHead';
    stateEl = mk('span', 'istate', 'Checking\u2026');
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'telegramNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'telegramBody';
    card.append(head, bodyEl, noteEl);
    host.parentNode.insertBefore(card, host.nextSibling);
    buildDialog();
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }
  const button = (id, label, cls) => { const b = mk('button', cls || 'btn bact', label); b.type = 'button'; if (id) b.id = id; return b; };

  function steps() {
    const ol = mk('ol', 'tsteps'); ol.id = 'telegramSteps';
    STEPS.forEach((s) => ol.appendChild(mk('li', '', s)));
    return ol;
  }
  function toggleRow(id, label, on, onClick, aria) {
    const row = mk('div', 'trow');
    const t = mk('div', 'btxt'); t.appendChild(mk('b', '', label));
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
    b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', aria || label);
    const track = mk('span', 'track'); track.appendChild(mk('i', ''));
    b.append(track, mk('span', 'st', on ? 'On' : 'Off'));
    if (S.busy) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(!on); });
    row.append(t, b);
    return row;
  }

  function renderOff() {
    card.dataset.state = 'off'; stateEl.textContent = 'Off';
    bodyEl.append(
      mk('p', '', 'Telegram is not switched on yet. It lets you chat with JARVIS from your phone and get alerts there. Only the account you pair can talk to it.'),
      steps(),
      mk('p', 'fine', 'Nothing here costs money. Until you do this, nothing is sent to or received from Telegram.'));
  }
  function renderReady(d) {
    card.dataset.state = 'unlinked'; stateEl.textContent = 'Ready to pair';
    bodyEl.appendChild(mk('p', '', d.bot ? `Your bot is @${d.bot}. Press Pair, tap the link on your phone and press Start.` : 'Your bot is ready. Press Pair, tap the link on your phone and press Start.'));
    const pair = button('telegramPair', 'Pair');
    pair.addEventListener('click', () => startPair(pair));
    bodyEl.append(pair, webhookLine(d));
  }
  function webhookLine(d) {
    const w = d.webhook;
    const text = w.registered === false ? 'Webhook: not registered. Run bash deploy/cloudrun.sh --telegram again.'
      : w.registered === null ? 'Webhook: couldn\'t check right now.'
        : w.error ? 'Webhook: registered, but ' + w.error.charAt(0).toLowerCase() + w.error.slice(1)
          : `Webhook: registered${w.pending ? `, ${w.pending} waiting` : ''}.`;
    const p = mk('p', 'fine twebhook', text); p.id = 'telegramWebhook';
    return p;
  }
  function renderPaired(d) {
    card.dataset.state = 'linked'; stateEl.textContent = 'Paired';
    bodyEl.appendChild(mk('p', '', `Paired with your Telegram account ${d.hint || ''}`.trim() + '. Only that account can talk to JARVIS.'));
    bodyEl.appendChild(mk('p', 'fine', 'Telegram keeps bot chats on its servers (not end-to-end encrypted). By default JARVIS will not read email, Drive, documents or contacts there, nor your vault list, notes and things.'));
    bodyEl.appendChild(toggleRow('telegramReads', 'Let Telegram read my email, Drive, documents, contacts, family calendars and deleted events and to-dos', d.reads, askReads, 'Let Telegram read my private data'));
    bodyEl.appendChild(toggleRow('telegramPersonal', 'Let Telegram answer from my vault list, notes and things (never files)', d.personal, askPersonal, 'Let Telegram answer from my vault list, notes and things'));
    const al = mk('div', 'talerts'); al.id = 'telegramAlerts'; al.setAttribute('role', 'group'); al.setAttribute('aria-label', 'Alerts');
    ALERTS.forEach(([key, label]) => al.appendChild(toggleRow('telegramAlert_' + key, label, d.alerts[key], (on) => saveAlert(key, on), 'Alert: ' + label)));
    bodyEl.appendChild(al);
    const actions = mk('div', 'tactions');
    const test = button('telegramTest', 'Test alert');
    test.addEventListener('click', () => testAlert(test));
    const un = button('telegramUnpair', 'Unpair');
    un.addEventListener('click', () => askUnpair(un));
    actions.append(test, un);
    bodyEl.append(actions, webhookLine(d));
  }

  function render() {
    if (!build()) return;
    const d = S.data;
    bodyEl.textContent = '';
    if (S.error) {
      card.dataset.state = 'error'; stateEl.textContent = 'Unknown';
      bodyEl.appendChild(mk('p', 'warn', 'Couldn\'t check Telegram. ' + S.error));
      const r = button('telegramRetry', 'Retry');
      r.addEventListener('click', () => { r.disabled = true; load(true); });
      bodyEl.appendChild(r);
      return;
    }
    if (d === undefined) { card.dataset.state = 'loading'; stateEl.textContent = 'Checking\u2026'; bodyEl.appendChild(mk('p', '', 'Checking Telegram\u2026')); return; }
    if (!d.configured) renderOff();
    else if (d.paired) renderPaired(d);
    else renderReady(d);
  }

  // ---- the dialog (pair + confirms): native modal, Tab stays inside, Esc cancels ---------------
  function buildDialog() {
    dlg = mk('dialog', 'bdialog'); dlg.id = 'telegramDialog'; dlg.setAttribute('role', 'alertdialog');
    dlg.setAttribute('aria-labelledby', 'telegramDialogTitle'); dlg.setAttribute('aria-describedby', 'telegramDialogText');
    const h = mk('h2'); h.id = 'telegramDialogTitle';
    const body = mk('div'); body.id = 'telegramDialogText';
    const actions = mk('div', 'actions');
    const no = button('telegramDialogNo', 'Cancel', 'btn lift');
    const yes = button('telegramDialogYes', 'OK', 'btn primary lift');
    actions.append(no, yes);
    dlg.append(h, body, actions);
    document.body.appendChild(dlg);
    yes.addEventListener('click', () => { if (settle) settle(true); });
    no.addEventListener('click', () => { if (settle) settle(false); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('close', () => { if (settle && !dlg.open) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const items = [...dlg.querySelectorAll('button:not([disabled]), a[href]')];
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    });
  }
  /** Show the dialog; resolves true (OK) / false (Cancel, Esc). `yes` null hides the OK button. */
  function ask(title, nodes, yes, trigger) {
    if (!dlg || typeof dlg.showModal !== 'function') {
      note('bad', 'This browser can\'t show the confirmation, so nothing was changed.');
      return Promise.resolve(false);
    }
    if (settle) settle(false);
    $('telegramDialogTitle').textContent = title;
    const body = $('telegramDialogText'); body.textContent = ''; body.append(...nodes);
    const y = $('telegramDialogYes'); y.hidden = !yes; if (yes) y.textContent = yes;
    $('telegramDialogNo').textContent = yes ? 'Cancel' : 'Close';
    return new Promise((resolve) => {
      settle = (val) => {
        settle = null; stopPoll();
        if (dlg.open) dlg.close();
        if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('telegramDialogNo').focus(); // the safe choice is where Enter lands
    });
  }

  // ---- actions --------------------------------------------------------------------------------
  async function call(path, opts, ok) {
    if (!hasApi() || S.busy) return null;
    S.busy = true; render();
    try {
      const r = await api(path, opts);
      if (ok) note('ok', ok);
      return r === undefined ? {} : r;
    } catch (e) {
      if (e && e.status === 401) return null;
      note('bad', detailOf(e) || 'Couldn\'t do that. Please try again.');
      return null;
    } finally {
      S.busy = false; render();
    }
  }
  async function saveAlert(key, on) {
    const r = await call('/v1/telegram/settings', { method: 'PUT', body: { alerts: { [key]: on } } }, 'Saved.');
    if (r) { S.data = normal(r); render(); }
  }
  async function askReads(on) {
    if (on) {
      const sure = await ask('Let Telegram read your private data?', [
        mk('p', 'strong', 'Telegram keeps bot chats on its servers and they are not end-to-end encrypted.'),
        mk('p', '', 'If you switch this on, JARVIS can read out your email, Drive files, documents, contacts and family calendars in that chat, and list the events and to-dos in Recently deleted. Deleted vault documents, notes and things stay hidden there unless the other switch is on too, and restoring anything from Recently deleted in that chat needs both switches. Anyone with your Telegram account could then see them.'),
        mk('p', '', 'You can switch it off here at any time.')], 'Switch on', $('telegramReads'));
      if (!sure) return;
    }
    const r = await call('/v1/telegram/settings', { method: 'PUT', body: { allow_private_reads: on } },
      on ? 'Telegram may now read your email, Drive, documents, contacts, family calendars and deleted events and to-dos.' : 'Telegram no longer reads your private data.');
    if (r) { S.data = normal(r); render(); log('info', on ? 'Telegram private reads on' : 'Telegram private reads off'); }
  }
  /** R2 D12: the second switch. Its dialog names exactly what it opens, and nothing of the first. */
  async function askPersonal(on) {
    if (on) {
      const sure = await ask('Let Telegram answer from your vault list, notes and things?', [
        mk('p', 'strong', 'Telegram keeps bot chats on its servers and they are not end-to-end encrypted.'),
        mk('p', '', 'If you switch this on, JARVIS can tell you in that chat: your vault list (document types, whose they are, the last 4 characters and the dates, never the files); your notes, voice memos and saved links; and where you keep things. It can also save, change or delete notes and things and change vault dates from there, the same way as in the console. Only with the other switch on too can it list deleted vault documents, notes and things, or restore anything from Recently deleted, in that chat. Anyone with your Telegram account could then see them.'),
        mk('p', '', 'You can switch it off here at any time.')], 'Switch on', $('telegramPersonal'));
      if (!sure) return;
    }
    const r = await call('/v1/telegram/settings', { method: 'PUT', body: { allow_personal_reads: on } },
      on ? 'Telegram may now answer from your vault list, notes and things.' : 'Telegram no longer answers from your vault list, notes and things.');
    if (r) { S.data = normal(r); render(); log('info', on ? 'Telegram vault, notes and things on' : 'Telegram vault, notes and things off'); }
  }
  async function askUnpair(trigger) {
    const sure = await ask('Unpair Telegram?', [
      mk('p', '', 'This Telegram account will stop reaching JARVIS. You can pair again at any time.')], 'Unpair', trigger);
    if (!sure) return;
    const r = await call('/v1/telegram/pair', { method: 'DELETE' }, 'Unpaired.');
    if (r) { S.data = normal(r); render(); log('info', 'Telegram unpaired'); }
  }
  async function testAlert(trigger) {
    const r = await call('/v1/telegram/test-alert', { method: 'POST' });
    if (!r) return;
    if (r.sent === true) note('ok', 'Test alert sent. Check Telegram.');
    else note('bad', 'The test alert was not sent' + (typeof r.reason === 'string' && r.reason ? ': ' + txt(r.reason, 120) + '.' : '.'));
    if (trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
  }

  // ---- pairing --------------------------------------------------------------------------------
  function stopPoll() { if (S.timer) { clearTimeout(S.timer); S.timer = 0; } S.pair = null; }
  async function startPair(trigger) {
    if (!hasApi() || S.busy) return;
    S.busy = true; render();
    let r = null;
    try {
      r = obj(await api('/v1/telegram/pair', { method: 'POST' }));
    } catch (e) {
      if (e && e.status === 401) { S.busy = false; render(); return; }
      note('bad', detailOf(e) || 'Couldn\'t start pairing. Please try again.');
    } finally { S.busy = false; render(); }
    if (!r || typeof r.code !== 'string' || !CODE.test(r.code) || typeof r.link !== 'string' || !LINK.test(r.link)) return;
    const status = mk('p', 'fine'); status.id = 'telegramWaiting'; status.setAttribute('role', 'status');
    status.textContent = 'Waiting for Telegram\u2026';
    const code = mk('p', 'tcode', r.code); code.id = 'telegramCode';
    const a = mk('a', 'btn primary', 'Open Telegram'); a.id = 'telegramLink'; a.href = r.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
    const done = ask('Pair Telegram', [
      mk('p', '', 'Tap the link on your phone and press Start. The code works once and expires in 10 minutes.'),
      a, mk('p', 'fine', 'Or send this to your bot yourself: /start ' + r.code), code, status], null, trigger);
    const stamp = Date.now(); S.pair = stamp;
    const tick = async () => {
      if (S.pair !== stamp) return;
      if (Date.now() - stamp > POLL_MAX_MS) { status.textContent = 'The code expired. Close this and press Pair again.'; return; }
      try {
        const d = normal(await api('/v1/telegram'));
        if (!d.paired && !d.pending) { status.textContent = 'The code expired or was voided. Close this and press Pair again.'; return; }
        if (d.paired) { S.data = d; S.loadedAt = Date.now(); if (settle) settle(true); render(); note('ok', 'Paired. Send your bot a message.'); log('info', 'Telegram paired'); return; }
      } catch (e) { if (e && e.status === 401) return; }
      S.timer = setTimeout(tick, POLL_MS);
    };
    S.timer = setTimeout(tick, POLL_MS);
    await done;
  }

  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try {
        S.data = normal(await api('/v1/telegram')); S.error = '';
      } catch (e) {
        if (e && e.status === 401) return;
        if (e && e.status === 404) { S.data = { configured: false }; S.error = ''; } else { S.error = detailOf(e) || 'Please try again.'; }
      } finally {
        S.loadedAt = Date.now(); S.loading = null; render();
      }
    })();
    return S.loading;
  }

  const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (integOpen()) load(false); });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready() && integOpen()) load(false);

  window.JarvisTelegram = Object.freeze({ refresh: () => load(true), normal });
})();
