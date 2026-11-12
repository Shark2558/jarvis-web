// src/jarvis/api/static/console-media.js -- slice 12 D3/D4 (docs/plans/phase2-slice12-integrations.md):
// the Maps and YouTube cards under a reply, the Media panel's player, the Vitals lines "Maps: N of
// 31,500 searches this month" / "YouTube searches today: N of 90", and Integrations -> Maps (Home /
// Work). No build step; CSP script-src 'self'; every server string reaches the DOM through
// textContent or a checked attribute, never markup.
//   window.JarvisMedia  cards(row, cards) -> renders ChatResponse.cards under a reply (console.js):
//     places   name, address, status, "Open in Google Maps" (an https Google Maps link only), and
//              a "Google Maps" attribution line on the card
//     route    from -> to, minutes, km, "Open in Google Maps" (directions), "Google Maps" line
//     videos   title, channel, length and a Play button per video, a "YouTube" line
//   Play: the ONLY way a video starts. It opens the Media panel and makes the player there -- an
//   iframe on https://www.youtube-nocookie.com/embed/<id> -- at that moment (autoplay=1 is set only
//   on the iframe created by the owner's click, so playback starts from the owner's own gesture).
//   Nothing creates an iframe before a Play click; Stop removes it again. A video id must match
//   /^[A-Za-z0-9_-]{11}$/ or there is no Play button.
//   Vitals: GET /v1/quota -> {configured:false} | {configured, pricing, maps_search, maps_route,
//   maps_route_2w, maps_route_walk, youtube_search...} (a paused two-wheeler / walking SKU is named).
//   Integrations: GET /v1/maps/places -> {configured, home, work}; PUT saves both (<= 200 characters).
//   Hidden while jarvis:integrations says maps: false (no key here, or the Maps row is Never; final
//   review): not asked, no error and no Retry. Invisible characters go by window.JarvisText
//   (console-text.js: keeps ZWNJ / ZWJ).
// Review fixes: FE-3 keyboard focus lands on a control after every re-render; FE-4 the video stops
// whenever the Media panel is no longer shown (phones, reset layout, a desktop close); FE-5 no
// prototype key is ever a mode; FE-6 names and addresses are bidi-isolated (<bdi>); FE-10 ASCII
// source with backslash-u escapes only; FE-11 a failing Maps check says so, with Retry.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const C = () => window.JarvisConsole || null;
  const Deck = () => window.JarvisDeck || null;
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
  const PLACE_ID = /^[A-Za-z0-9_-]{1,256}$/;
  const EMBED = 'https://www.youtube-nocookie.com/embed/';
  const MAPS_HOSTS = new Set(['maps.google.com', 'maps.app.goo.gl']);
  const MAPS_UNDER = new Set(['www.google.com', 'google.com']);
  const MAX_CARDS = 8, MAX_ITEMS = 20, TEXT_MAX = 300, PLACE_MAX = 200, MAX_URL = 2048;
  const MAPS_ATTR = 'Google Maps', YT_ATTR = 'YouTube';
  const MEDIA_KINDS = new Set(['places', 'route', 'videos']);
  const REL = 'noopener noreferrer';
  const MODES = new Map([['drive', 'by car'], ['two_wheeler', 'by two-wheeler'], ['walk', 'on foot']]);
  const DOT = ' \u00b7 ', NONE = '\u2014';
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  /** A <tag> holding `text` in a <bdi>: a right-to-left name can't reorder the words around it. */
  const iso = (tag, cls, text) => { const n = mk(tag, cls); n.appendChild(mk('bdi', '', text)); return n; };
  const txt = (v, max = TEXT_MAX) => (typeof v === 'string' ? window.JarvisText.strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const nat = (v, max) => (Number.isFinite(v) && v >= 0 && v <= max ? v : null);
  const fmt = (n) => { try { return Number(n).toLocaleString('en-IN'); } catch (_) { return String(n); } };

  /** An https Google Maps address (no user info, no port), or null. */
  function mapsUrl(raw) {
    if (typeof raw !== 'string' || !raw || raw.length > MAX_URL || /\s/.test(raw)) return null;
    let u; try { u = new URL(raw); } catch (_) { return null; }
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return null;
    if (MAPS_HOSTS.has(u.hostname)) return u.href;
    if (MAPS_UNDER.has(u.hostname) && (u.pathname === '/maps' || u.pathname.startsWith('/maps/'))) return u.href;
    return null;
  }

  function mapsLink(href, label) {
    const a = mk('a', 'mlink', 'Open in Google Maps');
    a.href = href; a.target = '_blank'; a.rel = REL;
    a.setAttribute('aria-label', `Open ${label} in Google Maps (opens in a new tab)`);
    return a;
  }
  function attribution(word) { const p = mk('p', 'mattr', word); p.setAttribute('translate', 'no'); return p; }

  // ---- cards ---------------------------------------------------------------------------------
  function placesCard(c) {
    const items = (Array.isArray(c.items) ? c.items : []).slice(0, MAX_ITEMS).map((p) => {
      if (!p || typeof p !== 'object' || typeof p.place_id !== 'string' || !PLACE_ID.test(p.place_id)) return null;
      const href = mapsUrl(p.url); if (!href) return null;
      return { name: txt(p.name) || '(no name)', address: txt(p.address), href,
        status: p.status === 'temporarily closed' || p.status === 'permanently closed' ? p.status : '' };
    }).filter(Boolean);
    const box = mk('section', 'mcard mplaces'); box.setAttribute('aria-label', 'Places from Google Maps');
    if (!items.length) box.appendChild(mk('p', 'mempty', 'No place found.'));
    const list = mk('ol', 'mlist');
    items.forEach((p) => {
      const li = mk('li', 'mitem');
      const t = mk('div', 'mtxt'); t.append(iso('b', '', p.name));
      if (p.address) t.append(iso('span', 'maddr', p.address));
      if (p.status) t.append(mk('span', 'mstatus', p.status));
      li.append(t, mapsLink(p.href, p.name));
      list.appendChild(li);
    });
    if (items.length) box.appendChild(list);
    box.appendChild(attribution(MAPS_ATTR));
    return box;
  }

  function routeCard(c) {
    const href = mapsUrl(c.url);
    const mins = nat(c.duration_minutes, 100000), km = nat(c.distance_km, 100000);
    const mode = typeof c.mode === 'string' ? MODES.get(c.mode) : undefined; // FE-5: own keys only
    if (!href || mins === null || km === null || !mode) return null;
    const from = txt(c.origin, PLACE_MAX) || 'Start', to = txt(c.destination, PLACE_MAX) || 'Destination';
    const box = mk('section', 'mcard mroute'); box.setAttribute('aria-label', 'Route from Google Maps');
    const head = mk('p', 'mrhead'); head.append(mk('bdi', 'mend', from), mk('span', 'marrow', ' \u2192 '), mk('bdi', 'mend', to));
    const h = Math.floor(mins / 60), m = mins % 60;
    const time = h ? `${h} h ${m} min` : `${m} min`;
    const fig = mk('p', 'mrfig'); fig.append(mk('b', '', time), mk('span', '', `${DOT}${km} km ${mode}` + (c.traffic === true ? DOT + 'with current traffic' : '')));
    box.append(head, fig, mapsLink(href, `the route from ${from} to ${to}`), attribution(MAPS_ATTR));
    return box;
  }

  function videoItems(c) {
    return (Array.isArray(c.items) ? c.items : []).slice(0, MAX_ITEMS).map((v) => {
      if (!v || typeof v !== 'object' || typeof v.id !== 'string' || !VIDEO_ID.test(v.id)) return null;
      return { id: v.id, title: txt(v.title) || '(no title)', channel: txt(v.channel),
        duration: typeof v.duration === 'string' && /^\d{1,3}(:\d{2}){1,2}$/.test(v.duration) ? v.duration : '',
        embeddable: v.embeddable !== false, live: v.live === true };
    }).filter(Boolean);
  }

  function videosCard(c) {
    const items = videoItems(c);
    const box = mk('section', 'mcard mvideos'); box.setAttribute('aria-label', 'Videos from YouTube');
    const title = txt(c.title); if (title) box.appendChild(mk('p', 'mvtitle', title));
    if (!items.length) box.appendChild(mk('p', 'mempty', 'No video found.'));
    const list = mk('ol', 'mlist');
    items.forEach((v) => {
      const li = mk('li', 'mitem');
      const t = mk('div', 'mtxt'); t.append(iso('b', '', v.title));
      const when = v.live ? 'live' : v.duration;
      if (v.channel || when) {
        const sub = mk('span', 'maddr');
        if (v.channel) sub.appendChild(mk('bdi', '', v.channel));
        if (when) sub.append((v.channel ? DOT : '') + when);
        t.append(sub);
      }
      li.appendChild(t);
      if (v.embeddable) {
        const b = mk('button', 'btn lift mplay', 'Play'); b.type = 'button';
        b.setAttribute('aria-label', `Play ${v.title} in the Media panel`);
        b.addEventListener('click', () => play(v, items, 'card'));
        li.appendChild(b);
      } else li.appendChild(mk('span', 'mstatus', 'Can only be played on YouTube'));
      list.appendChild(li);
    });
    if (items.length) box.appendChild(list);
    box.appendChild(attribution(YT_ATTR));
    return box;
  }

  function cards(row, list) {
    if (!row || !Array.isArray(list) || !list.length) return null;
    // R11.1 A: what a calendar batch did ("Undo all", "Retry"): console-r111-plan.js draws its own kind
    const plan = window.JarvisFixes && window.JarvisFixes.parts ? window.JarvisFixes.parts.plan : null;
    if (plan && typeof plan.cards === 'function') plan.cards(row, list);
    const wrap = mk('div', 'mcards');
    // ChatResponse.cards also carries other kinds (a WhatsApp draft: console-whatsapp.js): only
    // this module's kinds count towards its cap
    const mine = list.filter((c) => c && typeof c === 'object' && MEDIA_KINDS.has(c.kind));
    mine.slice(0, MAX_CARDS).forEach((c) => {
      let el = null;
      if (c.kind === 'places' && c.attribution === MAPS_ATTR) el = placesCard(c);
      else if (c.kind === 'route' && c.attribution === MAPS_ATTR) el = routeCard(c);
      else if (c.kind === 'videos' && c.attribution === YT_ATTR) el = videosCard(c);
      if (el) wrap.appendChild(el);
    });
    if (!wrap.childElementCount) return null;
    row.appendChild(wrap);
    return wrap;
  }

  // ---- the player: made only by the owner's click on Play --------------------------------------
  let current = null;
  function setNote(text) { const n = $('mediaNote'); if (n) n.textContent = text || ''; }

  /** Removes the player. `focus`: the owner pressed Stop, so keyboard focus goes to the panel's
   *  heading (the Stop button is gone); a stop because the panel was hidden moves no focus. */
  function stop(focus) {
    const stage = $('mediaStage'), now = $('mediaNow');
    if (stage) { stage.querySelectorAll('iframe').forEach((f) => f.remove()); const e = $('mediaEmpty'); if (e) e.hidden = false; }
    if (now) { now.textContent = ''; now.hidden = true; }
    current = null; setNote('Stopped.');
    if (focus === true) { const h = $('t-media'); if (h) h.focus({ preventScroll: true }); }
  }
  const playing = () => !!current || !!document.querySelector('#mediaStage iframe');
  /** FE-4: the video stops whenever the Media panel is no longer shown, on phones too (a phone's
   *  other tab, reset layout and a phone/desktop switch hide it without a jarvis:panel close). */
  function stopIfHidden() {
    const D = Deck();
    if (playing() && D && typeof D.isOpen === 'function' && !D.isOpen('media')) stop(false);
  }

  function queue(items) {
    const q = $('mediaQueue'); if (!q) return;
    q.textContent = '';
    items.forEach((v) => {
      const li = mk('li', current && current.id === v.id ? 'on' : '');
      const b = mk('button', 'mqbtn'); b.type = 'button'; b.appendChild(mk('bdi', '', v.title));
      if (current && current.id === v.id) b.setAttribute('aria-current', 'true');
      b.setAttribute('aria-label', `Play ${v.title}`);
      b.addEventListener('click', () => play(v, items, 'queue'));
      li.appendChild(b); q.appendChild(li);
    });
  }

  /** `from`: 'card' (a reply's Play button) or 'queue' (the panel's list), for keyboard focus. */
  function play(v, items, from) {
    if (!v || !VIDEO_ID.test(v.id)) return;
    const stage = $('mediaStage'), now = $('mediaNow');
    if (!stage) return;
    // a phone shows one panel: the card's Play button is hidden with the chat, so focus moves in
    const D = Deck();
    if (D) D.open('media', { focus: from === 'card' && typeof D.isPhone === 'function' && D.isPhone() });
    stage.querySelectorAll('iframe').forEach((f) => f.remove());
    const e = $('mediaEmpty'); if (e) e.hidden = true;
    const f = document.createElement('iframe');
    f.className = 'mframe';
    // the owner pressed Play: start it (the click is the user gesture); youtube-nocookie only
    f.src = `${EMBED}${encodeURIComponent(v.id)}?autoplay=1&rel=0&playsinline=1&modestbranding=1`;
    f.title = `YouTube video: ${v.title}`;
    f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    f.referrerPolicy = 'strict-origin-when-cross-origin';
    f.setAttribute('allowfullscreen', '');
    f.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox');
    stage.appendChild(f);
    current = v;
    if (now) {
      now.textContent = ''; now.hidden = false;
      const t = mk('div', 'mtxt'); t.append(iso('b', '', v.title));
      if (v.channel) t.append(iso('span', 'maddr', v.channel));
      const s = mk('button', 'btn lift', 'Stop'); s.type = 'button'; s.id = 'mediaStop';
      s.addEventListener('click', () => stop(true));
      now.append(t, s);
    }
    queue(Array.isArray(items) ? items : [v]);
    setNote(`Playing: ${v.title}`);
    if (from === 'queue') { // the list was redrawn: focus the item now playing
      const b = document.querySelector('#mediaQueue .mqbtn[aria-current="true"]');
      if (b) b.focus({ preventScroll: true });
    }
  }

  // ---- Vitals ----------------------------------------------------------------------------------
  function count(x) {
    if (!x || typeof x !== 'object') return null;
    if (x.unreadable === true) return 'unreadable';
    const used = Number.isInteger(x.used) && x.used >= 0 ? x.used : null;
    const limit = Number.isInteger(x.limit) && x.limit > 0 ? x.limit : null;
    return used === null || limit === null ? null : { used, limit, reached: x.reached === true };
  }
  const of = (c) => `${fmt(c.used)} of ${fmt(c.limit)}`;
  /** {maps, yt}: the two Vitals values, and {mapsSaid, ytSaid}: the same as whole sentences
   *  ("Maps: N of 31,500 searches / N of 31,500 routes this month", "YouTube searches today: N of 90"). */
  function lines(r) {
    const none = { maps: NONE, yt: NONE, mapsSaid: '', ytSaid: '' };
    if (!r || typeof r !== 'object') return none;
    if (r.configured !== true) return { maps: 'Not set up', yt: 'Not set up', mapsSaid: 'Maps: not set up', ytSaid: 'YouTube: not set up' };
    const s = count(r.maps_search), rt = count(r.maps_route), y = count(r.youtube_search);
    let maps = NONE, yt = NONE;
    if (s === 'unreadable' || rt === 'unreadable') maps = 'Count unavailable';
    else if (s && rt) maps = `${of(s)} searches / ${of(rt)} routes this month` + (s.reached || rt.reached ? DOT + 'paused' : '');
    else if (s) maps = `${of(s)} searches this month` + (s.reached ? DOT + 'paused' : '');
    // two-wheeler and walking routes have their own (smaller / larger) free allowances
    const other = [[count(r.maps_route_2w), 'two-wheeler'], [count(r.maps_route_walk), 'walking']];
    if (s && s !== 'unreadable') maps += other.filter(([c]) => c && c.reached).map(([, w]) => `${DOT}${w} paused`).join('');
    if (y === 'unreadable') yt = 'Count unavailable';
    else if (y) yt = `${of(y)} searches today` + (y.reached ? DOT + 'paused until midnight Pacific' : '');
    return { maps, yt, mapsSaid: `Maps: ${maps}`, ytSaid: y && y !== 'unreadable' ? `YouTube searches today: ${of(y)}` : `YouTube: ${yt}` };
  }
  let loading = false;
  async function refresh() {
    const m = $('sMaps'), y = $('sYouTube'), c = C();
    if (!m || !y || !c || typeof c.api !== 'function' || loading) return;
    loading = true;
    try {
      const r = await c.api('/v1/quota');
      const l = lines(r);
      m.textContent = l.maps; y.textContent = l.yt;
      const tip = r && r.configured === true
        ? 'Free Google allowance. JARVIS stops at 90 % of it, before anything is charged.'
        : 'Maps and YouTube are not set up: no Google API key on this server.';
      m.title = tip; y.title = tip;
      if (l.mapsSaid) m.setAttribute('aria-label', l.mapsSaid);
      if (l.ytSaid) y.setAttribute('aria-label', l.ytSaid);
    } catch (e) {
      if (!e || e.status !== 401) { m.textContent = e && e.status === 404 ? 'Not available' : NONE; y.textContent = m.textContent; }
    } finally { loading = false; }
  }

  // ---- Integrations -> Maps: Home and Work ------------------------------------------------------
  // error: '' or the words for a failed GET (FE-11: said, with Retry; never a silently hidden section)
  // off: jarvis:integrations said maps: false (final review): hidden, not asked
  const places = { configured: false, home: null, work: null, open: false, off: false, error: '' };
  function placesForm(sec) {
    const form = mk('form', 'mform'); form.noValidate = true;
    const field = (id, label, value) => {
      const l = mk('label', 'bl', label); l.htmlFor = id;
      const i = mk('input'); i.id = id; i.type = 'text'; i.maxLength = PLACE_MAX; i.autocomplete = 'off';
      i.value = value || ''; i.placeholder = label === 'Home' ? 'e.g. Kowdiar, Thiruvananthapuram' : 'e.g. Technopark Phase 3';
      return [l, i];
    };
    const [hl, hi] = field('mapsHome', 'Home', places.home);
    const [wl, wi] = field('mapsWork', 'Work', places.work);
    const err = mk('p', 'lerr'); err.id = 'mapsErr'; err.setAttribute('role', 'alert');
    const save = mk('button', 'btn primary lift', 'Save'); save.type = 'submit';
    form.append(hl, hi, wl, wi, mk('p', 'fine', 'An area, a street or a landmark \u2014 no phone numbers. Sent to Google only when you ask for a travel time.'), err, save);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault(); err.textContent = '';
      const c = C(); if (!c) return;
      save.disabled = true;
      try {
        const r = await c.api('/v1/maps/places', { method: 'PUT', body: { home: hi.value.trim() || null, work: wi.value.trim() || null } });
        places.home = typeof r.home === 'string' ? r.home : null; places.work = typeof r.work === 'string' ? r.work : null;
        renderPlaces(sec, 'Saved.', 'mapsEdit'); // the form is gone: focus its button (FE-3)
      } catch (e) {
        err.textContent = e && e.status !== 401 ? String(e.message || 'Could not save.') : '';
      } finally {
        save.disabled = false; // a disabled button loses focus: give it back when the form stays
        if (save.isConnected && (!document.activeElement || document.activeElement === document.body)) save.focus({ preventScroll: true });
      }
    });
    return form;
  }
  /** Draws Integrations -> Maps. `focusId`: the control that takes keyboard focus once it is
   *  redrawn (FE-3: the one pressed is gone, so focus would otherwise fall to the page). */
  function renderPlaces(sec, said, focusId) {
    sec.textContent = '';
    delete sec.dataset.state;
    if (places.off) { sec.hidden = true; return; } // Never in Permissions, or no key: not shown
    if (places.error) { renderPlacesError(sec); return; }
    if (!places.configured) { sec.hidden = true; return; }
    sec.hidden = false;
    const head = mk('div', 'ihead'); const h = mk('b', '', 'Maps'); h.id = 'mapsT';
    head.append(h, mk('span', 'istate', 'Ready'));
    const body = mk('div', 'ibody');
    body.append(mk('p', '', 'Place search and travel times with traffic, from Google Maps. Your Home and Work let you ask "how long to work?"'));
    const kv = (k, v) => { const p = mk('p', 'who'); p.append(mk('span', '', `${k}: `), v ? iso('b', '', v) : mk('b', '', 'not set')); return p; };
    body.append(kv('Home', places.home), kv('Work', places.work));
    const btn = mk('button', 'btn lift', places.open ? 'Close' : 'Set Home and Work'); btn.type = 'button'; btn.id = 'mapsEdit';
    btn.setAttribute('aria-expanded', String(places.open));
    btn.addEventListener('click', () => { places.open = !places.open; renderPlaces(sec, '', places.open ? 'mapsHome' : 'mapsEdit'); });
    sec.append(head, body, btn);
    if (places.open) sec.appendChild(placesForm(sec));
    if (said) { const n = mk('div', 'inote ok', said); n.setAttribute('role', 'status'); sec.appendChild(n); }
    const f = focusId ? $(focusId) : null; if (f) f.focus({ preventScroll: true });
  }
  function renderPlacesError(sec) {
    sec.hidden = false; sec.dataset.state = 'error';
    const head = mk('div', 'ihead'); const h = mk('b', '', 'Maps'); h.id = 'mapsT';
    head.append(h, mk('span', 'istate', 'Unknown'));
    const body = mk('div', 'ibody');
    body.appendChild(mk('p', 'warn', 'Couldn\'t check Maps. ' + places.error));
    const r = mk('button', 'btn lift', 'Retry'); r.type = 'button'; r.id = 'mapsRetry';
    r.addEventListener('click', () => { r.disabled = true; loadPlaces(true); });
    sec.append(head, body, r);
  }
  /** A thrown api() error as plain words (never a code or an object), or a fixed fallback. */
  function errWords(e) {
    if (e && e.name === 'TypeError') return 'Can\'t reach JARVIS. Check your connection.';
    const m = e && typeof e.message === 'string' ? txt(e.message) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : 'Please try again.';
  }
  let placesLoading = null;
  /** GET /v1/maps/places. `retry`: the owner pressed Retry, so focus lands on what replaces it. */
  function loadPlaces(retry) {
    const sec = $('integMaps'), c = C();
    if (!sec || !c || typeof c.api !== 'function') return Promise.resolve();
    if (places.off) { renderPlaces(sec); return Promise.resolve(); } // Never in Permissions: not asked
    if (placesLoading) return placesLoading;
    placesLoading = (async () => {
      try {
        const r = await c.api('/v1/maps/places');
        places.error = '';
        places.configured = !!r && r.configured === true;
        places.home = r && typeof r.home === 'string' ? r.home : null;
        places.work = r && typeof r.work === 'string' ? r.work : null;
      } catch (e) {
        if (e && e.status === 401) { placesLoading = null; return; }
        // a server without the route has no Maps here: nothing to say; anything else is said
        if (e && e.status === 404) { places.error = ''; places.configured = false; } else places.error = errWords(e);
      }
      placesLoading = null;
      // a load that answers while Set Home and Work is open never redraws it: a redraw wiped what
      // the owner was typing and moved the focus (3 Nov browser run); Save and Close redraw it
      const hi = $('mapsHome');
      if (places.open && hi && sec.contains(hi) && !places.error && places.configured && !places.off) return;
      renderPlaces(sec, '', retry === true ? (places.error ? 'mapsRetry' : 'mapsEdit') : '');
    })();
    return placesLoading;
  }

  document.addEventListener('jarvis:ready', () => { refresh(); loadPlaces(); });
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id === 'vitals' && d.open) refresh();
    if (d.id === 'integrations' && d.open) loadPlaces();
    stopIfHidden(); // FE-4: any panel change (a phone's other tab, a close) that hides Media stops it
  });
  // reset layout and a phone/desktop switch change what is shown without a jarvis:panel event
  document.addEventListener('jarvis:reset-layout', () => setTimeout(stopIfHidden, 0));
  try { window.matchMedia('(max-width: 899px)').addEventListener('change', () => setTimeout(stopIfHidden, 0)); } catch (_) {}
  document.addEventListener('jarvis:reply', (e) => { const d = e.detail || {}; if (d.tools > 0) refresh(); });
  // /v1/integrations maps_available (a server without the field says nothing: shown as before)
  document.addEventListener('jarvis:integrations', (e) => {
    const d = e.detail || {};
    if (typeof d.maps !== 'boolean' || places.off === !d.maps) return;
    places.off = !d.maps; places.open = false;
    loadPlaces();
  });
  if (C() && typeof C().ready === 'function' && C().ready()) { refresh(); loadPlaces(); }

  window.JarvisMedia = Object.freeze({ cards, mapsUrl, lines, stop: () => stop(false) });
})();
