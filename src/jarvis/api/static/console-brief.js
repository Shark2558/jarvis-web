// src/jarvis/api/static/console-brief.js — the morning Brief panel (slice 7,
// docs/plans/phase4-slice7-morning-brief.md). No build step; CSP script-src 'self'.
// Every string from the server reaches the DOM through textContent (never innerHTML); a field that is
// missing or of the wrong type hides its line instead of showing a guess. Transport is the console's
// own api() (window.JarvisConsole: cookie + X-Requested-With: JARVIS, or the bearer token; 401 → gate).
// Listens: jarvis:ready (signed in), jarvis:panel (Brief shown / tab switched), jarvis:integrations
// (Google state + address), jarvis:approvals (live count). Fires: jarvis:event (deck log + radar).
// API (src/jarvis/api/brief.py): GET /v1/brief/today and POST /v1/brief/generate {force?|trigger?}
// both answer TodayView; PUT /v1/brief/settings answers SettingsView (422/429 carry a plain `detail`);
// POST /v1/brief/seen {date}.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const panel = $('p-brief'), box = $('brief'), setBox = $('briefSettings'), noteEl = $('briefNote');
  const refreshBtn = $('briefRefresh'), metaEl = $('briefMeta'), dlg = $('briefDialog');
  if (!panel || !box || !setBox || !noteEl) return;
  const Deck = window.JarvisDeck || { open() {}, isOpen: () => false, isPhone: () => false };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const TIMES = [];
  for (let m = 4 * 60; m <= 11 * 60 + 30; m += 30) TIMES.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
  const FIELDS = ['enabled', 'time', 'ai_summary', 'inbox_delivery'];
  const POLL_MS = 4000;              // while the server says "generating" (a tick or another tab is on it)
  const POLL_MAX = 15;               // ~1 minute, then the owner presses Refresh
  const STALE_MS = 30 * 60 * 1000;   // coming back to a tab left open overnight re-checks today
  const NOTE_MS = 5000;              // a success line clears itself; errors stay until the next action
  const AI_LABEL = 'AI summary — written from your calendar and other people\'s emails; may be wrong';
  const TRIGGER_WORDS = { scheduled: 'Scheduled', manual: 'Made by you', open: 'Made on opening' };
  // bidi overrides, zero-width and control characters can make text read differently than it is
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- small, type-checking helpers: anything unexpected becomes "" / null / [] -------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 200) => (typeof v === 'string' ? v : num(v) !== null ? String(v) : '').replace(INVISIBLE, '').trim().slice(0, max);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  /** The server's plain-English `detail` (the api() helper puts it in .message), or "". A bare
   *  code such as "brief_limit" (api() falls back to `error` when there is no detail) is not shown. */
  function detailOf(e) {
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  const errText = (e) => detailOf(e) || 'Please try again.';
  function icon(paths) {
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    [['viewBox', '0 0 16 16'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '1.6'], ['stroke-linecap', 'round'],
      ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => svg.setAttribute(k, v));
    paths.forEach(d => { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p); });
    return svg;
  }
  const WARN = ['M8 1.8 14.6 13.5H1.4z', 'M8 6.2v3.3M8 11.6v.1'];
  function button(id, cls, text, onClick) {
    const b = mk('button', 'btn lift ' + cls, text); b.type = 'button'; if (id) b.id = id;
    b.addEventListener('click', onClick); return b;
  }
  /** "Sun 1 Nov" for a YYYY-MM-DD local date (read as a calendar date, never shifted by time zone). */
  function fmtDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return '';
    try {
      return new Intl.DateTimeFormat([], { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
        .format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))).replace(/,/g, '');
    } catch (_) { return iso; }
  }
  /** "07:00" for an instant, in the brief's time zone when the browser knows it. */
  function clock(iso, tz) {
    const d = new Date(txt(iso, 64) || NaN);
    if (isNaN(d)) return '';
    const opts = { hour: '2-digit', minute: '2-digit', hour12: false };
    try { return new Intl.DateTimeFormat([], tz ? Object.assign({ timeZone: tz }, opts) : opts).format(d); }
    catch (_) { return d.toLocaleTimeString([], opts); }
  }
  function mailTime(raw, tz) {
    const d = new Date(txt(raw, 80) || NaN);
    if (isNaN(d)) return '';
    return Date.now() - d.getTime() < 20 * 3600 * 1000 ? clock(d.toISOString(), tz) : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }

  // ---- state ---------------------------------------------------------------------------------------
  const S = {
    today: undefined,   // undefined = not loaded yet, null = this server has no brief (404), else GET /v1/brief/today
    loadError: null,
    generating: false,  // our own POST /v1/brief/generate is in flight
    saving: false,
    autoGenerated: false, autoOpened: false, returning: false,
    seenSent: new Set(), fetchedAt: 0, pollTimer: 0, polls: 0, noteTimer: 0, viewKey: '',
    google: undefined, email: null, approvals: null,
  };
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const ready = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const settings = () => obj(S.today && S.today.settings) || {};
  const brief = () => obj(S.today && S.today.brief);
  const status = () => (S.today ? txt(S.today.status, 20) : '');
  const unseenReady = () => status() === 'ready' && !!brief() && !brief().seen_at;
  const busy = () => S.generating || status() === 'generating';
  const waiting = () => S.generating || (status() === 'generating' && S.polls < POLL_MAX); // still checking by itself
  const genLeft = () => num(brief() && brief().generations_left); // null = the server didn't say

  // ---- talking to the server ---------------------------------------------------------------------
  async function load() {
    if (!ready()) return;
    clearTimeout(S.pollTimer);
    try {
      S.today = obj(await api('/v1/brief/today')) || {};
      S.loadError = null;
    } catch (e) {
      if (e.status === 401) return;          // the sign-in gate takes over
      if (e.status === 404) S.today = null;  // a server without the morning brief
      else S.loadError = errText(e);
    }
    S.fetchedAt = Date.now();
    afterData();
  }
  function afterData() {
    render();
    if (status() === 'generating' && S.polls < POLL_MAX) {
      S.pollTimer = setTimeout(() => { S.polls++; load(); }, POLL_MS);
    } else if (status() !== 'generating') S.polls = 0;
    maybeAutoOpen();
    if (Deck.isOpen('brief')) shown();
  }
  /** force: make today's brief again (Refresh, Try again). Otherwise trigger "open" (the panel was
   *  opened; the server makes nothing while the brief is off) or "manual" ("Make it now"). */
  async function generate(force, trigger) {
    if (!ready() || S.generating || S.today === null) return;
    S.generating = true; clearTimeout(S.pollTimer); flash(null); render();
    let reload = true;
    try {
      const r = obj(await api('/v1/brief/generate', { body: force ? { force: true } : { trigger: trigger || 'manual' } }));
      if (r && typeof r.status === 'string' && 'brief' in r) { // the server answered with today's whole state
        S.today = Object.assign({}, S.today, r); S.fetchedAt = Date.now(); reload = false;
      }
      log('info', force ? 'Brief refreshed' : 'Brief made');
    } catch (e) {
      if (e.status === 401) { S.generating = false; return; }
      reload = false;
      flash('bad', e.status === 429 ? detailOf(e) || 'Brief limit reached for today.' : `Couldn't make the brief. ${errText(e)}`);
      log('error', e.status === 429 ? 'Brief limit reached' : 'Brief not made');
    } finally { S.generating = false; }
    if (reload) await load(); else afterData();
  }
  async function markSeen() {
    const b = brief();
    if (!unseenReady() || !b) return;
    const date = txt(b.date, 10) || txt(S.today.date, 10);
    if (!date || S.seenSent.has(date)) return;
    S.seenSent.add(date);
    // seen here and now (the badge goes at once); if the call fails the next load offers it again
    S.today = Object.assign({}, S.today, { brief: Object.assign({}, b, { seen_at: new Date().toISOString() }) });
    syncBadge();
    try { await api('/v1/brief/seen', { body: { date } }); } catch (_) {}
  }
  async function saveSettings(patch, okText) {
    if (!ready() || S.saving) return;
    S.saving = true; flash(null); render();
    try {
      const r = obj(await api('/v1/brief/settings', { method: 'PUT', body: patch }));
      const src = (r && obj(r.settings)) || (r && FIELDS.some(f => f in r) ? r : patch);
      const next = Object.assign({}, settings());
      FIELDS.forEach(f => { if (f in src) next[f] = src[f]; });
      S.today = Object.assign({}, S.today, { settings: next });
      flash('ok', okText);
      log('info', 'Brief settings saved');
    } catch (e) { // a refusal (422) explains itself in plain English: show it as it is
      if (e.status !== 401) flash('bad', detailOf(e) || (e.status === 429 ? 'Too many changes just now. Try again in a minute.' : 'Couldn\'t save. Please try again.'));
    } finally { S.saving = false; }
    render();
    if (Deck.isOpen('brief')) shown(); // switching the brief on with none made today makes one now
  }
  async function googleEmail() {
    if (S.email) return S.email;
    try {
      const r = obj(await api('/v1/integrations')), g = obj(r && r.google);
      if (g && g.connected) S.email = txt(g.email, 254) || null;
    } catch (_) {} // unknown address: the dialog says "your own Gmail inbox" instead
    return S.email;
  }

  // ---- when the panel is on screen, and the morning auto-open ------------------------------------
  function shown() {
    syncBadge();
    if (!S.today) return;
    if (status() === 'none' && settings().enabled === true && !S.autoGenerated && !S.generating) {
      S.autoGenerated = true; // once per page load: opening the panel makes today's brief (trigger=open)
      generate(false, 'open');
      return;
    }
    markSeen();
  }
  function maybeAutoOpen() {
    syncBadge();
    if (S.autoOpened || !unseenReady()) return;
    S.autoOpened = true;
    // phones: the badge says it (no pulling the owner away from a reply); back from Google: that panel leads
    if (Deck.isPhone() || S.returning || Deck.isOpen('brief')) return;
    log('info', 'Morning brief ready');
    Deck.open('brief', { focus: false }); // fires jarvis:panel → shown() → seen
  }
  function syncBadge() {
    const dot = $('briefBadge'), btn = document.querySelector('.dk[data-open="brief"]');
    const on = unseenReady() && !Deck.isOpen('brief');
    if (dot) dot.hidden = !on;
    if (btn) { if (on) btn.setAttribute('aria-label', 'Brief, new brief ready'); else btn.removeAttribute('aria-label'); }
  }
  function flash(kind, text) {
    clearTimeout(S.noteTimer);
    noteEl.textContent = kind ? text : '';
    noteEl.className = 'bnote' + (kind ? ' ' + kind : '');
    if (kind === 'ok') S.noteTimer = setTimeout(() => flash(null), NOTE_MS);
  }

  // ---- rendering ---------------------------------------------------------------------------------
  function render() {
    const a = document.activeElement, keep = a && a.id && panel.contains(a) ? a.id : null;
    renderMeta(); renderBody(); renderSettings();
    if (refreshBtn) {
      const left = genLeft();
      refreshBtn.setAttribute('aria-disabled', String(!S.today || waiting() || left === 0));
      refreshBtn.setAttribute('aria-label', left === null ? 'Refresh brief' : `Refresh brief, ${left} left today`);
      refreshBtn.hidden = S.today === null;
    }
    box.setAttribute('aria-busy', String(S.today === undefined && !S.loadError ? true : busy()));
    syncBadge();
    const again = keep && $(keep); // re-rendered controls keep their ids: focus stays where it was
    if (again && again !== document.activeElement) again.focus({ preventScroll: true });
  }
  function renderMeta() {
    if (!metaEl) return;
    const st = status(), left = genLeft();
    let text = '', cls = ''; // a ready brief shows its own date in the body; up here, beside Refresh, what is left
    if (S.today === null) text = 'Not available';
    else if (busy()) text = 'Preparing…';
    else if (st === 'ready' && left !== null) {
      text = left ? `${plural(left, 'refresh', 'refreshes')} left today` : 'No refreshes left today';
      cls = left ? '' : 'warn';
    } else if (st === 'failed') { text = 'Didn\'t finish'; cls = 'bad'; }
    else if (st === 'none') text = settings().enabled === true ? (txt(settings().time, 5) ? `Due ${txt(settings().time, 5)}` : 'Not made yet') : 'Off';
    metaEl.textContent = text;
    metaEl.className = 'pmeta' + (cls ? ' ' + cls : '');
  }
  function renderBody() {
    box.textContent = '';
    if (S.today === undefined) {
      if (!S.loadError) { box.appendChild(mk('div', 'empty', 'Checking today\'s brief…')); return; }
      box.append(mk('p', 'bmiss warn', 'Couldn\'t check today\'s brief. ' + S.loadError), button('briefRetry', 'bact', 'Retry', load));
      return;
    }
    if (S.today === null) {
      box.appendChild(mk('div', 'empty', 'Not available in this setup: this server has no morning brief yet.'));
      return;
    }
    if (S.loadError) box.append(mk('p', 'bmiss warn', 'Couldn\'t refresh: showing what was loaded earlier.'));
    const st = status(), b = brief();
    if (busy() && !(st === 'ready' && b)) { box.appendChild(preparing()); return; }
    if (st === 'ready' && b) { box.appendChild(briefView(b)); return; }
    if (st === 'failed') { box.appendChild(failedView()); return; }
    box.appendChild(noneView());
  }
  function preparing() {
    const p = mk('div', 'bprep'); p.setAttribute('role', 'status');
    const wave = mk('span', 'wave'); wave.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 5; i++) wave.appendChild(document.createElement('i'));
    const still = status() === 'generating' && S.polls >= POLL_MAX;
    p.append(wave, mk('span', '', still ? 'Still preparing. Press Refresh to check again.' : 'Preparing your brief…'));
    return p;
  }
  function failedView() {
    const t = S.today, b = brief() || {};
    const why = txt(b.error, 300) || txt(t.error, 300);
    const wrap = mk('div', 'bstate');
    wrap.append(mk('p', 'bmiss warn', 'Today\'s brief didn\'t finish.'));
    if (why) wrap.append(mk('p', 'bfine', why));
    wrap.append(button('briefTryAgain', 'primary bact', 'Try again', () => generate(true)));
    return wrap;
  }
  function noneView() {
    const on = settings().enabled === true, time = txt(settings().time, 5);
    const wrap = mk('div', 'bstate');
    wrap.append(mk('p', 'bempty', on ? `No brief yet today. JARVIS makes it${time ? ' at ' + time : ' each morning'}.`
      : 'The morning brief is off. Switch it on below, or make one now.'));
    wrap.append(button('briefMake', 'primary bact', 'Make it now', () => generate(false, 'manual')));
    return wrap;
  }
  function section(key, title, meta) {
    const s = mk('section', 'bsec'), h = mk('h3', '');
    h.id = 'bsec-' + key; h.append(mk('span', '', title));
    if (meta) h.append(mk('span', 'bcount', '· ' + meta));
    s.setAttribute('aria-labelledby', h.id); s.append(h);
    return s;
  }
  /** One-line replacement for a section Google couldn't fill (not linked, or failing just now). */
  function missing(state, what, id) {
    const wrap = mk('div', 'bstate');
    if (state === 'not_connected') {
      wrap.append(mk('p', 'bempty', `Connect Google to see your ${what} here.`),
        button(id, 'bact', 'Open Integrations', () => Deck.open('integrations', { focus: true })));
    } else wrap.append(mk('p', 'bmiss warn', `Couldn't read your ${what} just now.`));
    return wrap;
  }
  function briefView(b) {
    const key = txt(b.date, 10) + '|' + txt(b.created_at, 40);
    const view = mk('div', 'bview' + (key !== S.viewKey ? ' enter' : ''));
    S.viewKey = key;
    const data = obj(b.data) || {}, ss = obj(data.sections_status) || {}, tz = txt(S.today.tz, 64);
    const head = mk('div', 'bhead');
    head.append(mk('b', 'bdate', fmtDate(txt(b.date, 10) || txt(S.today.date, 10))));
    const made = clock(b.created_at, tz);
    const how = TRIGGER_WORDS[txt(b.trigger, 20)] || '';
    if (made || how) head.append(mk('span', 'bmade', [made ? 'Made ' + made : '', how].filter(Boolean).join(' · ')));
    view.append(head);
    const cal = obj(data.calendar), calState = txt(ss.calendar, 20);
    view.append(todaySection(cal, calState));
    const tomorrow = tomorrowSection(cal, calState); if (tomorrow) view.append(tomorrow);
    view.append(inboxSection(obj(data.inbox), txt(ss.inbox, 20), tz));
    const jarvis = jarvisSection(obj(data.jarvis), txt(ss.jarvis, 20)); if (jarvis) view.append(jarvis);
    const ai = aiSection(b); if (ai) view.append(ai);
    const deliv = deliverySection(b, tz); if (deliv) view.append(deliv);
    return view;
  }
  function eventRow(e) {
    const ov = arr(e.overlaps_with).map(x => txt(x, 120)).filter(Boolean);
    const li = mk('li', 'bev' + (ov.length ? ' clash' : ''));
    const early = e.starts_earlier === true, late = e.ends_later === true; // runs over midnight
    const start = txt(e.start, 5) || (early ? '…' : ''), end = txt(e.end, 5) || (late ? '…' : '');
    const when = e.all_day === true ? 'All day' : [start, end].filter(Boolean).join('–');
    li.append(mk('span', 'btime', when || '—'));
    const what = mk('div', 'bwhat');
    what.append(mk('b', '', txt(e.title, 120) || '(No title)'));
    const people = num(e.attendees) ?? (Array.isArray(e.attendees) ? e.attendees.length : null);
    const bits = [early ? 'Began on an earlier day' : '', late ? 'Runs past midnight' : '', txt(e.location, 80),
      people ? plural(people, 'attendee', 'attendees') : '', e.has_video === true ? 'Video call' : ''].filter(Boolean);
    if (bits.length) what.append(mk('small', '', bits.join(' · ')));
    if (ov.length) { const c = mk('span', 'bclash'); c.append(icon(WARN), mk('span', '', 'Clashes with ' + ov.join(', '))); what.append(c); }
    li.append(what);
    return li;
  }
  function todaySection(cal, state) {
    if (state && state !== 'ok') { const s = section('today', 'Today'); s.append(missing(state, 'calendar', 'briefIntegCal')); return s; }
    if (!cal) { const s = section('today', 'Today'); s.append(mk('p', 'bempty', 'No calendar details in this brief.')); return s; }
    const events = arr(cal.today).map(obj).filter(Boolean);
    const clashes = num(cal.clashes) ?? events.filter(e => arr(e.overlaps_with).length).length;
    const meta = events.length ? plural(events.length, 'event', 'events') + (clashes ? ' · ' + plural(clashes, 'clash', 'clashes') : '') : '';
    const s = section('today', 'Today', meta);
    if (!events.length) s.append(mk('p', 'bempty', 'Nothing on your calendar today.'));
    else { const ul = mk('ul', 'bevents'); events.forEach(e => ul.append(eventRow(e))); s.append(ul); }
    if (Array.isArray(cal.free_blocks)) {
      const free = cal.free_blocks.map(obj).filter(f => f && txt(f.start, 5) && txt(f.end, 5));
      const row = mk('div', 'bfree'); row.append(mk('span', 'bk2', 'Free'));
      if (free.length) {
        const ul = mk('ul', 'bchips');
        free.forEach(f => {
          const chip = mk('li', 'bchip', `${txt(f.start, 5)}–${txt(f.end, 5)}`), mins = num(f.minutes);
          if (mins) chip.title = `${mins} minutes free`;
          ul.append(chip);
        });
        row.append(ul);
      } else row.append(mk('span', 'bempty', 'No free half-hour today.'));
      s.append(row);
    }
    return s;
  }
  function tomorrowSection(cal, state) {
    if ((state && state !== 'ok') || !cal || !('tomorrow_first' in cal)) return null;
    const s = section('tomorrow', 'Tomorrow', 'first thing'), e = obj(cal.tomorrow_first);
    if (!e) s.append(mk('p', 'bempty', 'Nothing timed on your calendar tomorrow.'));
    else { const ul = mk('ul', 'bevents'); ul.append(eventRow(e)); s.append(ul); }
    return s;
  }
  function inboxSection(inbox, state, tz) {
    if (state && state !== 'ok') { const s = section('inbox', 'Inbox'); s.append(missing(state, 'mail', 'briefIntegMail')); return s; }
    if (!inbox) { const s = section('inbox', 'Inbox'); s.append(mk('p', 'bempty', 'No mail details in this brief.')); return s; }
    const total = num(inbox.total), msgs = arr(Array.isArray(inbox.items) ? inbox.items : inbox.messages).map(obj).filter(Boolean);
    const s = section('inbox', 'Inbox', total !== null ? `${total} unread` : '');
    if (!msgs.length) { s.append(mk('p', 'bempty', 'No unread mail in Primary from the last day.')); return s; }
    const ul = mk('ul', 'binbox');
    msgs.forEach(m => {
      const li = mk('li'), from = txt(m.from_name, 80) || txt(m.from_address, 120) || 'Unknown sender';
      const who = mk('b', '', from); const addr = txt(m.from_address, 120); if (addr) who.title = addr;
      li.append(who);
      const at = txt(m.when, 40) || mailTime(m.date, tz); // the server's own "06:42" / "yesterday 21:10"
      if (at) li.append(mk('time', '', at));
      li.append(mk('span', '', txt(m.subject, 120) || '(No subject)'));
      ul.append(li);
    });
    s.append(ul);
    if (total !== null && total > msgs.length) s.append(mk('p', 'bfine', `Showing ${msgs.length} of about ${total}.`));
    return s;
  }
  function jarvisSection(j, state) {
    const live = Number.isFinite(S.approvals) ? S.approvals : null; // the live count beats the 07:00 snapshot
    const count = live ?? num(j && j.approvals_waiting);
    if (count === null && state !== 'unavailable') return null;
    const s = section('jarvis', 'JARVIS');
    if (count === null) { s.append(mk('p', 'bmiss warn', 'Couldn\'t count the approvals waiting.')); return s; }
    if (!count) { s.append(mk('p', 'bempty', 'Nothing waiting for your approval.')); return s; }
    s.append(mk('p', 'bwait', `${plural(count, 'approval', 'approvals')} waiting for you.`),
      button('briefOpenApprovals', 'bact', 'Open Approvals', () => Deck.open('approvals', { focus: true })));
    return s;
  }
  function aiSection(b) {
    const ai = obj(b.ai), lines = arr(ai && ai.lines).map(l => txt(l, 200)).filter(Boolean).slice(0, 5);
    const aiNote = txt(b.ai_note, 300);
    if (!lines.length && !aiNote) return null;
    const s = section('ai', 'What matters today');
    s.classList.add('bai');
    if (lines.length) {
      s.append(mk('p', 'blabel', txt(ai.label, 200) || AI_LABEL)); // the server's label; ours if it sent none
      const ul = mk('ul', 'blines'); lines.forEach(l => ul.append(mk('li', '', l))); s.append(ul);
      const model = txt(ai.model, 60); if (model) s.append(mk('p', 'bfine', 'Model: ' + model));
    }
    if (aiNote) s.append(mk('p', 'bfine', aiNote));
    return s;
  }
  function deliverySection(b, tz) {
    const d = obj(b.inbox), st = d ? txt(d.status, 20) : '';
    const at = d ? clock(d.at, tz) : '';
    const words = {
      delivered: ['ok', 'Delivered', at ? `In your inbox since ${at}.` : 'In your inbox.'],
      sending: ['', 'Delivering', 'Putting it in your inbox now.'],
      failed: ['bad', 'Not delivered', 'Gmail refused the message. The brief is still here.'],
      unknown: ['warn', 'Not confirmed', 'Gmail didn\'t confirm. Check your inbox before refreshing.'],
    }[st];
    if (!words) return null;
    const row = mk('div', 'bdeliv' + (words[0] ? ' ' + words[0] : ''));
    row.append(mk('span', 'bk2', 'Gmail'), mk('b', '', words[1]), mk('span', '', words[2]));
    return row;
  }

  // ---- settings ----------------------------------------------------------------------------------
  function toggleRow(id, label, on, desc, unavailable, onClick) {
    const row = mk('div', 'bopt');
    const t = mk('div', 'btxt'), l = mk('span', 'bl', label), d = mk('small', '', desc);
    l.id = id + 'L'; d.id = id + 'D'; t.append(l, d);
    const b = mk('button', 'bsw'); b.type = 'button'; b.id = id;
    b.setAttribute('aria-pressed', String(on));
    b.setAttribute('aria-labelledby', l.id); b.setAttribute('aria-describedby', d.id);
    if (unavailable || S.saving) b.setAttribute('aria-disabled', 'true');
    const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.append(mk('i'));
    const st = mk('span', 'st', on ? 'On' : 'Off'); st.setAttribute('aria-hidden', 'true');
    b.append(track, st);
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') onClick(b); });
    row.append(t, b);
    return row;
  }
  function timeRow(value, tz) {
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('label', 'bl', 'Time'); l.htmlFor = 'briefTime';
    const d = mk('small', '', tz ? `Every morning, ${tz} time.` : 'Every morning, your time.'); d.id = 'briefTimeD';
    t.append(l, d);
    const sel = mk('select', 'bsel'); sel.id = 'briefTime'; sel.setAttribute('aria-describedby', d.id);
    const opts = TIMES.includes(value) || !value ? TIMES : TIMES.concat(value); // show the truth even if off-grid
    opts.forEach(v => { const o = mk('option', '', v); o.value = v; sel.append(o); });
    sel.value = value || '07:00'; // never disabled while saving: that would drop keyboard focus
    sel.addEventListener('change', () => saveSettings({ time: sel.value }, `Brief time set to ${sel.value}.`));
    row.append(t, sel);
    return row;
  }
  function renderSettings() {
    setBox.textContent = '';
    if (!S.today) return; // nothing to set until the server has answered
    const st = settings(), t = S.today;
    const sec = mk('section', 'bset'), h = mk('h3', '', 'Settings'); h.id = 'briefSetT';
    sec.setAttribute('aria-labelledby', h.id); sec.append(h);
    const enabled = st.enabled === true;
    sec.append(toggleRow('briefOn', 'Morning brief', enabled, 'Made every morning at the time below.', false,
      () => saveSettings({ enabled: !enabled }, enabled ? 'Morning brief off.' : 'Morning brief on.')));
    sec.append(timeRow(txt(st.time, 5), txt(t.tz, 64)));
    const aiOn = st.ai_summary === true, aiOk = t.ai_available !== false;
    sec.append(toggleRow('briefAi', 'AI summary', aiOn,
      aiOk ? 'Up to five short lines on what matters today, written by Claude.' : 'Not available: needs the Claude brain.',
      !aiOk && !aiOn, askAi));
    const inOn = st.inbox_delivery === true, inOk = t.inbox_available !== false;
    const why = t.google_connected === false ? 'Connect Google to allow this.' : 'Reconnect Google to allow this.';
    const row = toggleRow('briefInbox', 'Put it in my Gmail inbox', inOn,
      inOk ? 'Adds the brief to your own inbox each morning, so it reaches your phone. Nothing is sent to anyone.' : why,
      !inOk && !inOn, askInbox);
    if (!inOk) row.querySelector('.btxt').append(button('briefReconnect', 'bact', 'Open Integrations', () => Deck.open('integrations', { focus: true })));
    sec.append(row);
    setBox.append(sec);
  }
  async function askAi(trigger) {
    if (settings().ai_summary === true) { saveSettings({ ai_summary: false }, 'AI summary off.'); return; }
    const cost = txt(S.today.ai_cost_note, 300);
    const ok = await askConfirm(trigger, 'Switch on the AI summary?', [
      { cls: 'strong', parts: ['Uses Claude; never the free brain.'] },
      cost ? { parts: [cost] } : null,
      { parts: ['Each morning Claude reads today\'s calendar and the previews of your unread mail, then writes up to five short lines. It cannot act on anything, and it may be wrong.'] },
      { parts: ['You can switch it off here at any time.'] },
    ], 'Switch on');
    if (ok) saveSettings({ ai_summary: true, confirm_spend: true }, 'AI summary on.');
  }
  async function askInbox(trigger) {
    if (settings().inbox_delivery === true) { saveSettings({ inbox_delivery: false }, 'Inbox delivery off.'); return; }
    const email = await googleEmail();
    const ok = await askConfirm(trigger, 'Put the brief in your Gmail inbox?', [
      { parts: email ? ['Each morning JARVIS adds the brief as one message to the inbox of ', ['b', email], '.']
        : ['Each morning JARVIS adds the brief as one message to your own Gmail inbox.'] },
      { cls: 'strong', parts: ['Nothing is sent to anyone.'] },
      { parts: ['The message only goes into your own mailbox, and you can delete it like any other mail. You can switch this off here at any time.'] },
    ], 'Put it in my inbox');
    if (ok) saveSettings({ inbox_delivery: true, confirm_inbox: true }, 'Inbox delivery on.');
  }

  // ---- confirm dialog: native modal (the rest of the page is inert), Tab stays inside, Esc = Not now
  let settle = null;
  function askConfirm(trigger, title, lines, yesText) {
    if (!dlg || typeof dlg.showModal !== 'function') { flash('bad', 'This browser can\'t show the confirmation, so nothing was switched on.'); return Promise.resolve(false); }
    if (settle) settle(false);
    $('briefDialogTitle').textContent = title;
    const body = $('briefDialogText'); body.textContent = '';
    lines.filter(Boolean).forEach(l => {
      const p = mk('p', l.cls || '');
      l.parts.forEach(part => p.append(Array.isArray(part) ? mk('b', '', part[1]) : document.createTextNode(part)));
      body.append(p);
    });
    $('briefDialogYes').textContent = yesText;
    return new Promise(resolve => {
      settle = (val) => {
        settle = null;
        if (dlg.open) dlg.close();
        const back = trigger && document.contains(trigger) ? trigger : (trigger && trigger.id ? $(trigger.id) : null);
        if (back) back.focus({ preventScroll: true });
        resolve(val);
      };
      dlg.showModal();
      $('briefDialogNo').focus(); // the safe choice is where Enter lands
    });
  }
  if (dlg) {
    $('briefDialogYes').addEventListener('click', () => { if (settle) settle(true); });
    $('briefDialogNo').addEventListener('click', () => { if (settle) settle(false); });
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); if (settle) settle(false); });
    dlg.addEventListener('close', () => { if (settle) settle(false); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (settle) settle(false); return; }
      if (e.key !== 'Tab') return;
      const items = [...dlg.querySelectorAll('button:not([disabled])')];
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  // ---- wiring --------------------------------------------------------------------------------------
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      if (refreshBtn.getAttribute('aria-disabled') === 'true') return;
      if (status() === 'generating') { S.polls = 0; load(); return; } // someone is already making it: look again
      generate(true);
    });
  }
  document.addEventListener('jarvis:ready', (e) => { S.returning = !!(e.detail && e.detail.returning); load(); });
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id === 'brief' && d.open) shown(); else syncBadge(); // phones: another tab hides the Brief
  });
  document.addEventListener('jarvis:integrations', (e) => {
    const d = e.detail || {}, g = d.google || null;
    S.email = d.email ? txt(d.email, 254) || null : null;
    const changed = S.google !== undefined && S.google !== g;
    S.google = g;
    if (changed && S.today) load(); // linked / unlinked / reconnected: what the brief can do changed
  });
  document.addEventListener('jarvis:approvals', (e) => {
    const c = (e.detail || {}).count, next = Number.isFinite(c) ? c : null;
    if (next === S.approvals) return;
    S.approvals = next;
    if (status() === 'ready') render();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && S.today !== undefined && !S.generating && Date.now() - S.fetchedAt > STALE_MS) load();
  });
})();
