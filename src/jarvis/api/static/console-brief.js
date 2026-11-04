// src/jarvis/api/static/console-brief.js — the morning Brief panel (slice 7,
// docs/plans/phase4-slice7-morning-brief.md). No build step; CSP script-src 'self'.
// Every string from the server reaches the DOM through textContent, never parsed as markup; a field
// that is missing or of the wrong type hides its line instead of showing a guess. Transport is the
// console's own api() (window.JarvisConsole: cookie + X-Requested-With: JARVIS, or the bearer token;
// 401 → gate). Listens: jarvis:ready (signed in; JarvisConsole.ready() covers arriving after it),
// jarvis:panel (Brief shown / tab switched), jarvis:integrations (Google state + address),
// jarvis:approvals (live count), visibilitychange (a hidden tab is not "looked at").
// Fires: jarvis:event (deck log + radar).
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
  // per-device conveniences only (the settings disclosure); storage may throw or come back empty
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const SETTINGS_OPEN_KEY = 'jarvis_brief_settings_open'; // slice 8 D12: collapsed unless opened here
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });

  const TIMES = [];
  for (let m = 4 * 60; m <= 11 * 60 + 30; m += 30) TIMES.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
  const FIELDS = ['enabled', 'time', 'ai_summary', 'inbox_delivery', 'deliveries', 'family'];
  const POLL_MS = 4000;              // while the server says "generating" (a tick or another tab is on it)
  const POLL_MAX = 15;               // ~1 minute, then the owner presses Refresh
  const STALE_MS = 30 * 60 * 1000;   // coming back to a tab left open overnight re-checks today
  const NOTE_MS = 5000;              // a success line clears itself; errors stay until the next action
  const TIME_SETTLE_MS = 400;        // arrow keys step through the times: save the one the owner stops on
  const AI_LABEL = 'AI summary — written from your calendar and other people\'s emails; may be wrong';
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const TRIGGER_WORDS = { scheduled: 'Scheduled', manual: 'Made by you', open: 'Made on opening' };
  const DELIVERY_WORDS = {
    delivered: ['ok', 'Delivered'],
    sending: ['', 'Delivering', 'Putting it in your inbox now.'],
    failed: ['bad', 'Not delivered', 'Gmail refused the message. The brief is still here.'],
    unknown: ['warn', 'Not confirmed', 'Gmail didn\'t confirm. Check your inbox before refreshing.'],
  };
  // bidi overrides, zero-width and control characters can make text read differently than it is
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

  // ---- small, type-checking helpers: anything unexpected becomes "" / null / [] -------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const txt = (v, max = 200) => (typeof v === 'string' ? v : num(v) !== null ? String(v) : '').replace(INVISIBLE, '').trim().slice(0, max);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  /** map[key] only for the map's own words: a server word such as "__proto__" or "constructor"
   *  must not reach Object.prototype. */
  const own = (map, key) => (Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  /** The server's plain-English `detail` (the api() helper puts it in .message), or "". A bare
   *  code such as "brief_limit" (api() falls back to `error` when there is no detail) is not shown.
   *  The request itself failing (offline, server unreachable) is a TypeError: "Failed to fetch" means
   *  nothing to the owner, so it is said plainly. */
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
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
  const GEAR = ['M8 3.6a4.4 4.4 0 1 1 0 8.8a4.4 4.4 0 1 1 0-8.8z', 'M8 6.1a1.9 1.9 0 1 1 0 3.8a1.9 1.9 0 1 1 0-3.8z',
    'M8 1.3v2.3M8 12.4v2.3M1.3 8h2.3M12.4 8h2.3M3.3 3.3l1.6 1.6M11.1 11.1l1.6 1.6M3.3 12.7l1.6-1.6M11.1 4.9l1.6-1.6'];
  const CHEVRON = ['M4.5 6.5 8 10l3.5-3.5'];
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
    try { return new Intl.DateTimeFormat([], tz ? { ...opts, timeZone: tz } : opts).format(d); }
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
    saving: false, saves: 0, // settings PUTs in flight or waiting their turn
    timeWant: null, timeTimer: 0, timeQueued: false, // the time picked but not saved yet
    asking: false,      // a confirm (or the address lookup before it) is open: one at a time
    autoGenerated: false, autoOpened: false, returning: false,
    seenSent: new Set(), fetchedAt: 0, pollTimer: 0, polls: 0, noteTimer: 0, viewKey: '',
    google: undefined, email: null, approvals: null,
  };
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const settings = () => obj(S.today && S.today.settings) || {};
  const brief = () => obj(S.today && S.today.brief);
  const status = () => (S.today ? txt(S.today.status, 20) : '');
  const unseenReady = () => status() === 'ready' && !!brief() && !brief().seen_at;
  const busy = () => S.generating || status() === 'generating';
  const waiting = () => S.generating || (status() === 'generating' && S.polls < POLL_MAX); // still checking by itself
  const genLeft = () => num(brief() && brief().generations_left); // null = the server didn't say

  // ---- talking to the server ---------------------------------------------------------------------
  async function load() {
    if (!hasApi()) return;
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
    clearTimeout(S.pollTimer); // one poll chain, however many loads overlapped (Retry, Google change)
    if (status() === 'generating' && S.polls < POLL_MAX) {
      S.pollTimer = setTimeout(() => { S.polls++; load(); }, POLL_MS);
    } else if (status() !== 'generating') S.polls = 0;
    maybeAutoOpen();
    if (Deck.isOpen('brief')) shown();
  }
  /** force: make today's brief again (Refresh, Try again). Otherwise trigger "open" (the panel was
   *  opened; the server makes nothing while the brief is off) or "manual" ("Make it now"). */
  async function generate(force, trigger) {
    if (!hasApi() || S.generating || S.today === null) return;
    S.generating = true; clearTimeout(S.pollTimer); flash(null); render();
    let reload = true;
    try {
      const r = obj(await api('/v1/brief/generate', { body: force ? { force: true } : { trigger: trigger || 'manual' } }));
      if (r && typeof r.status === 'string' && 'brief' in r) { // the server answered with today's whole state
        // spread, not Object.assign: a "__proto__" key in the JSON stays a key, never a prototype
        S.today = { ...S.today, ...r }; S.fetchedAt = Date.now(); reload = false;
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
    if (document.hidden || !unseenReady() || !b) return; // a background tab is not "looked at"
    const date = txt(b.date, 10) || txt(S.today.date, 10);
    if (!date || S.seenSent.has(date)) return;
    S.seenSent.add(date);
    // Seen here and now (the badge goes at once). Sent once per page load: if the call fails the
    // server still has it unseen, and the next page load offers it again.
    S.today = { ...S.today, brief: { ...b, seen_at: new Date().toISOString() } };
    syncBadge();
    try { await api('/v1/brief/seen', { body: { date } }); } catch (_) {}
  }

  // Settings are saved one PUT at a time, in order: a change made while another is on its way (a
  // "Switch on" confirmed during a time save) waits its turn instead of being dropped. `patch` may
  // be a function, read when its turn comes: the time picker sends the latest time, not every step.
  let saveChain = Promise.resolve();
  function saveSettings(patch, okText) {
    if (!hasApi()) { flash('bad', 'Couldn\'t save: JARVIS isn\'t ready yet. Please try again.'); return saveChain; }
    S.saves++; S.saving = true; flash(null); render();
    saveChain = saveChain
      .then(() => putSettings(typeof patch === 'function' ? patch() : patch, okText))
      .catch(() => {}) // putSettings says what went wrong; the next save still runs
      .then(() => {
        S.saves--; S.saving = S.saves > 0;
        render();
        if (Deck.isOpen('brief')) shown(); // switching the brief on with none made today makes one now
      });
    return saveChain;
  }
  async function putSettings(patch, okText) {
    if (!patch) return; // nothing left to save by the time its turn came
    try {
      const r = obj(await api('/v1/brief/settings', { method: 'PUT', body: patch }));
      const src = (r && obj(r.settings)) || (r && FIELDS.some(f => f in r) ? r : patch);
      const next = { ...settings() };
      FIELDS.forEach(f => { if (f in src) next[f] = src[f]; });
      S.today = { ...S.today, settings: next };
      flash('ok', typeof okText === 'function' ? okText(next) : okText);
      log('info', 'Brief settings saved');
    } catch (e) { // a refusal (422) explains itself in plain English: show it as it is
      if (e.status !== 401) flash('bad', detailOf(e) || (e.status === 429 ? 'Too many changes just now. Try again in a minute.' : 'Couldn\'t save. Please try again.'));
    } finally { // saved or refused: the picker shows what is really saved, unless a newer pick waits
      if ('time' in patch && S.timeWant === patch.time) S.timeWant = null;
    }
  }
  /** The time picker changed: remember the pick, and save it once the owner stops stepping. */
  function timePicked(value) {
    S.timeWant = value;
    clearTimeout(S.timeTimer);
    S.timeTimer = setTimeout(queueTime, TIME_SETTLE_MS);
  }
  function queueTime() {
    if (S.timeQueued) return; // the save already waiting reads the latest pick when its turn comes
    S.timeQueued = true;
    saveSettings(() => {
      S.timeQueued = false;
      const want = S.timeWant;
      if (!want || want === txt(settings().time, 5)) { S.timeWant = null; return null; } // back where it was
      return { time: want };
    }, (next) => `Brief time set to ${txt(next.time, 5)}.`);
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
    // A hidden tab is not "looked at": nothing is made or marked seen until it is shown again
    // (visibilitychange below calls this once the tab is visible with the panel open).
    if (!S.today || document.hidden) return;
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
      : 'The morning brief is off. Switch it on in Settings below, or make one now.'));
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
    const how = own(TRIGGER_WORDS, txt(b.trigger, 20)) || '';
    if (made || how) head.append(mk('span', 'bmade', [made ? 'Made ' + made : '', how].filter(Boolean).join(' · ')));
    view.append(head);
    const cal = obj(data.calendar), calState = txt(ss.calendar, 20);
    view.append(todaySection(cal, calState));
    const tomorrow = tomorrowSection(cal, calState); if (tomorrow) view.append(tomorrow);
    view.append(inboxSection(obj(data.inbox), txt(ss.inbox, 20), tz));
    const todo = todoSection(obj(data.todo), txt(ss.todo, 20)); if (todo) view.append(todo);
    // R1 D13 / D15 (console-brief-sections.js): Deliveries and Family today, when the brief carries them
    if (window.JarvisBriefSections) window.JarvisBriefSections.render(data).forEach(n => view.append(n));
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
    const rem = e.reminder === true; // slice 11: a reminder JARVIS set pops up at one moment
    const when = e.all_day === true ? 'All day' : rem ? start : [start, end].filter(Boolean).join('–');
    li.append(mk('span', 'btime', when || '—'));
    const what = mk('div', 'bwhat');
    what.append(mk('b', '', txt(e.title, 120) || '(No title)'));
    const people = num(e.attendees) ?? (Array.isArray(e.attendees) ? e.attendees.length : null);
    const bits = [rem ? 'Reminder' : '', early ? 'Began on an earlier day' : '', late ? 'Runs past midnight' : '', txt(e.location, 80),
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
  /** Slice 10 C: Google Tasks due today or overdue (dates, never times). No `todo` and no state = a brief
   *  made before the section existed: nothing shown. not_granted = the optional permission is missing. */
  function todoSection(t, state) {
    if (!t && (!state || state === 'ok')) return null;
    const total = t ? num(t.total) : null, over = t ? num(t.overdue) : null;
    const partial = !!t && t.complete === false; // the server read only part of the list: counts are "at least"
    const least = partial ? 'at least ' : '';
    const s = section('todo', 'To-do', total ? `${least}${total} due` + (over ? ` · ${over} overdue` : '') : '');
    if (state === 'not_granted') {
      const wrap = mk('div', 'bstate');
      wrap.append(mk('p', 'bempty', 'Grant JARVIS access to your to-do list (Integrations) to see it here.'),
        button('briefIntegTodo', 'bact', 'Open Integrations', () => Deck.open('integrations', { focus: true })));
      s.append(wrap); return s;
    }
    if ((state && state !== 'ok') || !t) { s.append(missing(state || 'unavailable', 'to-do list', 'briefIntegTodo')); return s; }
    const items = arr(t.items).map(obj).filter(Boolean);
    const partLine = () => mk('p', 'bfine', 'JARVIS read only part of your to-do list, so there may be more.');
    if (!items.length) { s.append(partial ? partLine() : mk('p', 'bempty', 'Nothing due today or overdue.')); return s; }
    const ul = mk('ul', 'bevents');
    items.forEach(i => {
      const late = i.overdue === true, due = fmtDate(txt(i.due, 10));
      const li = mk('li', 'bev' + (late ? ' overdue' : ''));
      li.append(mk('span', 'btime', late ? (due ? 'Overdue · ' + due : 'Overdue') : 'Today'));
      const what = mk('div', 'bwhat'); what.append(mk('b', '', txt(i.title, 120) || '(No title)'));
      const list = txt(i.list, 60); if (list) what.append(mk('small', '', list));
      li.append(what); ul.append(li);
    });
    s.append(ul);
    if (total !== null && total > items.length) s.append(mk('p', 'bfine', `Showing ${items.length} of ${least}${total}.`));
    if (partial) s.append(partLine());
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
    const words = own(DELIVERY_WORDS, st);
    if (!words) return null;
    const at = st === 'delivered' ? clock(d.at, tz) : '';
    const line = st === 'delivered' ? (at ? `In your inbox since ${at}.` : 'In your inbox.') : words[2];
    const row = mk('div', 'bdeliv' + (words[0] ? ' ' + words[0] : ''));
    row.append(mk('span', 'bk2', 'Gmail'), mk('b', '', words[1]), mk('span', '', line));
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
  // The time picker is built once and updated in place, never rebuilt: rebuilding it under the
  // owner's arrow keys reset it to the saved time and dropped their next steps. It is never
  // disabled while saving either: that would drop keyboard focus.
  // The settings sit behind a "Settings" disclosure (slice 8 D12): collapsed by default, with a
  // one-line summary while closed; open/closed is remembered on this device. Opening is never
  // forced: a confirm started from a switch inside it can only start while it is open.
  let setSec = null, setBtn = null, setSum = null, setBody = null, timeSel = null, timeDesc = null;
  function settingsShell() {
    if (setSec) return setSec;
    setSec = mk('section', 'bset');
    const h = mk('h3', 'dhead');
    setBtn = mk('button', 'dsc'); setBtn.type = 'button'; setBtn.id = 'briefSetBtn';
    setBtn.setAttribute('aria-controls', 'briefSetBody');
    const gear = icon(GEAR), chev = icon(CHEVRON);
    gear.setAttribute('class', 'dgear'); chev.setAttribute('class', 'dchev');
    setSum = mk('span', 'dsum'); setSum.id = 'briefSetSum';
    setBtn.append(gear, mk('span', 'dl', 'Settings'), chev, setSum);
    setBtn.addEventListener('click', () => settingsOpen(setBody.hidden, true));
    h.append(setBtn);
    setSec.setAttribute('aria-labelledby', setBtn.id);
    setBody = mk('div', 'dbody'); setBody.id = 'briefSetBody';
    const row = mk('div', 'bopt'), t = mk('div', 'btxt');
    const l = mk('label', 'bl', 'Time'); l.htmlFor = 'briefTime';
    timeDesc = mk('small', ''); timeDesc.id = 'briefTimeD'; t.append(l, timeDesc);
    timeSel = mk('select', 'bsel'); timeSel.id = 'briefTime'; timeSel.setAttribute('aria-describedby', timeDesc.id);
    timeSel.addEventListener('change', () => timePicked(timeSel.value));
    row.append(t, timeSel);
    setBody.append(row);
    setSec.append(h, setBody);
    settingsOpen(store.get(SETTINGS_OPEN_KEY) === '1', false);
    return setSec;
  }
  function settingsOpen(open, remember) {
    setBody.hidden = !open;
    setSum.hidden = open; // the summary stands in for the rows only while they are hidden
    setBtn.setAttribute('aria-expanded', String(open));
    if (remember) store.set(SETTINGS_OPEN_KEY, open ? '1' : '0');
  }
  /** "07:00 · AI summary on · Inbox copy off" — what the closed settings hold, in one line. */
  function settingsSummary(st) {
    const word = (v) => (v === true ? 'on' : 'off');
    const time = S.timeWant || txt(st.time, 5) || '07:00';
    return [st.enabled === true ? time : 'Brief off', `AI summary ${word(st.ai_summary)}`,
      `Inbox copy ${word(st.inbox_delivery)}`].join(' · ');
  }
  function syncTime(saved, tz) {
    timeDesc.textContent = tz ? `Every morning, ${tz} time.` : 'Every morning, your time.';
    const opts = !saved || TIMES.includes(saved) ? TIMES : TIMES.concat(saved); // show the truth even if off-grid
    const have = [...timeSel.options].map(o => o.value);
    if (have.length !== opts.length || have.some((v, i) => v !== opts[i])) {
      timeSel.replaceChildren(...opts.map(v => { const o = mk('option', '', v); o.value = v; return o; }));
    }
    const value = S.timeWant || saved || '07:00'; // a pick on its way stays on screen
    if (timeSel.value !== value) timeSel.value = value;
  }
  let switchesKey = '';
  function renderSettings() {
    if (!S.today) { setBox.textContent = ''; switchesKey = ''; return; } // nothing to set until the server has answered
    const st = settings(), t = S.today, sec = settingsShell(), timeRowEl = timeSel.parentNode;
    syncTime(txt(st.time, 5), txt(t.tz, 64));
    const sum = settingsSummary(st);
    if (setSum.textContent !== sum) setSum.textContent = sum;
    // the switches are rebuilt only when something they show changed: an unrelated update (the
    // live approvals count, a poll) must not swap a switch out from under a press
    const key = JSON.stringify([st.enabled, st.ai_summary, st.inbox_delivery, t.ai_available, t.inbox_available,
      t.google_connected, S.saving, st.ai_todo_consent, st.deliveries, st.family]);
    if (key === switchesKey && sec.parentNode === setBox) return;
    switchesKey = key;
    const enabled = st.enabled === true;
    const onRow = toggleRow('briefOn', 'Morning brief', enabled, 'Made every morning at the time below.', false,
      () => saveSettings({ enabled: !enabled }, enabled ? 'Morning brief off.' : 'Morning brief on.'));
    const aiOn = st.ai_summary === true, aiOk = t.ai_available !== false;
    const aiRow = toggleRow('briefAi', 'AI summary', aiOn,
      aiOk ? 'Up to five short lines on what matters today, written by Claude.' : 'Not available: needs the Claude brain.',
      !aiOk && !aiOn, askAi);
    // slice 10 C (review M4): switched on before the consent named to-dos → their titles are not sent until
    // the owner confirms again. Only when the server says so explicitly (an older server sends no flag).
    if (aiOn && st.ai_todo_consent === false) {
      aiRow.querySelector('.btxt').append(mk('small', '', 'To-do titles are not sent to Claude until you confirm.'),
        button('briefAiTodo', 'bact', 'Include to-dos', (e) => askAi(e.currentTarget, true)));
    }
    const inOn = st.inbox_delivery === true, inOk = t.inbox_available !== false;
    const why = t.google_connected === false ? 'Connect Google to allow this.' : 'Reconnect Google to allow this.';
    const inRow = toggleRow('briefInbox', 'Put it in my Gmail inbox', inOn,
      inOk ? 'Adds the brief to your own inbox each morning, so it reaches your phone. Nothing is sent to anyone.' : why,
      !inOk && !inOn, askInbox);
    if (!inOk) inRow.querySelector('.btxt').append(button('briefReconnect', 'bact', 'Open Integrations', () => Deck.open('integrations', { focus: true })));
    // the switches are rebuilt around the time row, which stays where it is (moving it drops focus)
    [...setBody.children].forEach(n => { if (n !== timeRowEl) n.remove(); });
    timeRowEl.before(onRow);
    // R1 D13 / D15: switches for the Deliveries and Family today sections (only if the server sends them)
    const secRow = (id, label, field, desc) => (typeof st[field] !== 'boolean' ? null : toggleRow(id, label, st[field], desc, false,
      () => saveSettings({ [field]: !st[field] }, `${label} ${st[field] ? 'off' : 'on'} from the next brief.`)));
    timeRowEl.after(...[aiRow, inRow,
      secRow('briefDeliveries', 'Deliveries', 'deliveries', 'Parcels on the way, found in your order emails. No AI is involved.'),
      secRow('briefFamily', 'Family today', 'family', 'What is on the family calendars you added. No AI is involved.')].filter(Boolean));
    if (sec.parentNode !== setBox) setBox.replaceChildren(sec);
  }
  /** One confirm at a time: a second press while the address is looked up (or a dialog is open)
   *  would open a second dialog whose late "close" cancelled the first. */
  async function asking(fn) {
    if (S.asking) return;
    S.asking = true;
    try { await fn(); } finally { S.asking = false; }
  }
  /** `again`: the AI is on under an earlier consent; this confirms the current text (to-dos included). */
  function askAi(trigger, again) {
    if (settings().ai_summary === true && again !== true) { saveSettings({ ai_summary: false }, 'AI summary off.'); return; }
    asking(async () => {
      const cost = txt(S.today.ai_cost_note, 300);
      const ok = await askConfirm(trigger, again === true ? 'Include your to-dos in the AI summary?' : 'Switch on the AI summary?', [
        { cls: 'strong', parts: ['Uses Claude; never the free brain.'] },
        cost ? { parts: [cost] } : null,
        { parts: ['Each morning Claude reads today\'s calendar, the previews of your unread mail and the titles of your to-dos due today or overdue, then writes up to five short lines. It cannot act on anything, and it may be wrong.'] },
        { parts: ['You can switch it off here at any time.'] },
      ], again === true ? 'Include to-dos' : 'Switch on');
      if (ok) saveSettings({ ai_summary: true, confirm_spend: true }, again === true ? 'To-dos included in the AI summary.' : 'AI summary on.');
    });
  }
  function askInbox(trigger) {
    if (settings().inbox_delivery === true) { saveSettings({ inbox_delivery: false }, 'Inbox delivery off.'); return; }
    asking(async () => {
      const email = await googleEmail();
      const ok = await askConfirm(trigger, 'Put the brief in your Gmail inbox?', [
        { parts: email ? ['Each morning JARVIS adds the brief as one message to the inbox of ', ['b', email], '.']
          : ['Each morning JARVIS adds the brief as one message to your own Gmail inbox.'] },
        { cls: 'strong', parts: ['Nothing is sent to anyone.'] },
        { parts: ['The message only goes into your own mailbox, and you can delete it like any other mail. You can switch this off here at any time.'] },
      ], 'Put it in my inbox');
      if (ok) saveSettings({ inbox_delivery: true, confirm_inbox: true }, 'Inbox delivery on.');
    });
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
    // a close event arrives after the fact: once a newer dialog is open, it is not about that one
    dlg.addEventListener('close', () => { if (settle && !dlg.open) settle(false); });
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
  function signedIn(detail) { S.returning = !!(detail && detail.returning); load(); }
  document.addEventListener('jarvis:ready', (e) => signedIn(e.detail));
  // jarvis:ready fires once per sign-in, and this script can arrive after it (deferred, after
  // console.js; a slow network can hold it back past the config + sign-in round trips): ask too.
  const JC = window.JarvisConsole;
  const signedInAlready = JC && typeof JC.ready === 'function' ? JC.ready() : null;
  if (signedInAlready) signedIn(signedInAlready);
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
    if (document.hidden) return;
    // left open overnight: look again (load → shown); otherwise the open panel is now really seen
    if (S.today !== undefined && !S.generating && Date.now() - S.fetchedAt > STALE_MS) load();
    else if (Deck.isOpen('brief')) shown();
  });
})();
