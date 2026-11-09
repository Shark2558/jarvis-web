// src/jarvis/api/static/console-integrations.js -- the Integrations panel's Google section, moved out
// of console.js (slice 12 review C5; docs/plans/phase2-slice12-integrations.md). No build step; CSP
// script-src 'self'; ASCII source with escapes only; every server string reaches the page through
// textContent, never markup. Loads BEFORE console.js, which boots it:
//   window.JarvisIntegrations  afterConnectRedirect() -> true when back from Google's consent screen
//     (the note is queued, the address bar cleaned); refresh() -> GET /v1/integrations, then render.
//   Transport is the console's own (window.JarvisConsole.api: cookie + X-Requested-With, or the bearer
//   token; 401 -> gate), read when a call is made, so it may arrive later.
//   It fires jarvis:integrations {google, email, drive, maps} and jarvis:event (the activity line).
//   drive / maps (final review): /v1/integrations drive_available / maps_available -- false hides
//   Integrations -> Google Drive / Maps' Home and Work (off here, or the row is Never); null when the
//   server did not say (an older server, or no Google sign-in): shown as before.
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const note = (kind, text, at, live) => emit('jarvis:event', { kind, text, at: at ?? Date.now(), live: live !== false });
  const api = (path, opts) => window.JarvisConsole.api(path, opts);

  // ---- integrations (slice 6): the Google link that unlocks Calendar + Gmail tools --------------
  // GET /v1/integrations -> {google: {connected, email, scopes, expires_at, needs_reconnect}}.
  // A 404 means this server has no connect flow (token-auth setup / older backend): say so, no error.
  // gmail.compose covers drafts AND sending; gmail.send only appears on links made before it was dropped.
  // gmail.insert (slice 7) is optional: it only lets the morning brief be put in the owner's own inbox.
  // tasks (slice 10 C) is optional too: the to-do list. `tasks_granted: false` -> a "Grant" row that re-runs
  // connect with ?add=tasks (only Grant asks for it; Google keeps what was granted: include_granted_scopes).
  // A server without the field shows none. Slice 12 D7: contacts_granted / youtube_granted alike (read only).
  // Review C7: `<name>_available: false` (no such tools on this server -- YouTube needs its API key -- or
  // the owner set the permission row to Never) offers no row and leaves it out of Unlocks; an older
  // server without the field shows the row as before.
  const SCOPE_WORDS = { 'calendar.readonly': ['Calendar', 'read'], 'calendar.events': ['Calendar', 'edit'],
    'gmail.readonly': ['Gmail', 'read'], 'gmail.compose': ['Gmail', 'draft', 'send'], 'gmail.send': ['Gmail', 'send'],
    'gmail.insert': ['Gmail', 'put the morning brief in your inbox (optional)'], tasks: ['To-do list', 'read & edit'],
    'contacts.readonly': ['Contacts', 'read'], 'youtube.readonly': ['YouTube', 'read your playlists'],
    'photospicker.mediaitems.readonly': ['Photos', 'read the photos you pick'] };
  const GRANTS = [ // the optional Grants: [field, ?add= name, button id, row words, what it unlocks, available field]
    ['tasks_granted', 'tasks', 'googleGrantTasks', 'To-do list \u2014 permission needed', 'your to-do list', 'tasks_available'],
    ['contacts_granted', 'contacts', 'googleGrantContacts', 'Contacts \u2014 permission needed', 'your contacts (read only)', 'contacts_available'],
    ['youtube_granted', 'youtube', 'googleGrantYoutube', 'YouTube playlists \u2014 permission needed', 'your YouTube playlists (read only)', 'youtube_available'],
    // R4 C (W8): Google Photos is pick-only (you choose the photos; JARVIS never reads the library)
    ['photos_granted', 'photos', 'googleGrantPhotos', 'Google Photos \u2014 permission needed', 'the photos you pick for Faces (pick-only)', 'photos_available'],
  ];
  /** "Calendar: read & edit - Gmail: read, draft, send" from the raw scope list (URLs or short names). */
  function scopeSummary(scopes) {
    const by = new Map(); let other = 0; // review FE-5: own keys only ('constructor' is no scope)
    (Array.isArray(scopes) ? scopes : []).forEach(s => {
      const key = String(s).split('/').pop(), w = Object.hasOwn(SCOPE_WORDS, key) ? SCOPE_WORDS[key] : null;
      if (!w) { other++; return; }
      if (!by.has(w[0])) by.set(w[0], []);
      const words = by.get(w[0]);
      w.slice(1).forEach(x => { if (!words.includes(x)) words.push(x); });
    });
    const parts = [...by].map(([k, ws]) => `${k}: ${ws.length === 2 && k === 'Calendar' ? ws.join(' & ') : ws.join(', ')}`);
    if (other) parts.push(`${other} other ${other === 1 ? 'permission' : 'permissions'}`);
    return parts.join(' \u00b7 ');
  }
  function googleState(g) {
    if (!g || !g.connected) return 'unlinked';
    return g.needs_reconnect ? 'reconnect' : 'linked';
  }
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  // data: undefined = still loading, null = route missing (404) -> "Not available in this setup"
  const integ = { data: undefined, loaded: false, at: 0, error: null, note: null };
  const INTEG_FRESH_MS = 5000; // reopening the panel re-checks the link unless it was just checked
  const STATE_WORDS = { linked: 'Connected', reconnect: 'Needs reconnecting', unlinked: 'Not connected',
    unavailable: 'Not available', loading: 'Checking\u2026', error: 'Unknown' };
  function integState() {
    if (integ.error) return 'error';
    if (integ.data === undefined) return 'loading';
    return integ.data === null ? 'unavailable' : googleState(integ.data.google);
  }
  function integBody(st, g) {
    const body = mk('div', 'ibody');
    if (st === 'loading') body.appendChild(mk('p', '', 'Checking linked accounts\u2026'));
    else if (st === 'error') body.appendChild(mk('p', 'warn', 'Couldn\'t check the Google link. ' + integ.error));
    else if (st === 'unavailable') body.appendChild(mk('p', '', 'Not available in this setup. Linking a Google account needs Google sign-in on this server.'));
    else if (st === 'unlinked') body.appendChild(mk('p', '', 'Link your Google account so JARVIS can read your calendar, find free time, and search, draft and send mail. Anything that sends or deletes still waits for your approval.'));
    else {
      const who = mk('p', 'who'); who.append(mk('span', '', st === 'linked' ? 'Connected as ' : 'Was connected as '), mk('b', '', g.email || 'unknown account'));
      body.appendChild(who);
      const sc = scopeSummary(g.scopes); if (sc) body.appendChild(mk('p', 'scopes', sc));
      if (st === 'reconnect') body.appendChild(mk('p', 'warn', 'Google stopped accepting the saved link (test-mode links expire after 7 days). Calendar and Gmail tools are paused until you reconnect.'));
      else body.appendChild(mk('p', 'fine', 'Unlocks: calendar list, free slots, create / move / delete events, mail search, read, draft and send'
        + andList(GRANTS.filter(x => g[x[0]] === true && g[x[5]] !== false).map(x => x[4]))));
      if (st === 'linked') GRANTS.filter(x => g[x[0]] === false && g[x[5]] !== false).forEach(x => body.appendChild(grantRow(x)));
    }
    return body;
  }
  const andList = (xs) => (xs.length ? `, and ${xs.length > 1 ? xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1] : xs[0]}.` : '.');
  /** "<what> - permission needed [Grant]": re-runs connect with ?add=<an allow-listed GRANTS name>. */
  function grantRow([, name, id, words]) {
    const row = mk('div', 'iopt'), b = mk('button', 'btn lift', 'Grant');
    b.type = 'button'; b.id = id;
    b.addEventListener('click', () => { note('info', 'Asking Google for permission\u2026'); window.location.assign('/connect/google?add=' + name); });
    row.append(mk('span', '', words), b);
    return row;
  }
  function integActions(st, row) {
    const acts = mk('div', 'actions');
    if (st === 'unlinked' || st === 'reconnect') {
      const b = mk('button', 'btn primary lift', st === 'unlinked' ? 'Connect Google' : 'Reconnect'); b.type = 'button'; b.id = 'googleConnect';
      b.addEventListener('click', () => { note('info', 'Connecting Google\u2026'); window.location.assign('/connect/google'); });
      acts.appendChild(b);
    }
    if (st === 'linked' || st === 'reconnect') {
      const d = mk('button', 'btn lift', 'Disconnect'); d.type = 'button'; d.id = 'googleDisconnect';
      d.addEventListener('click', () => askDisconnect(row, d)); acts.appendChild(d);
    }
    if (st === 'error') {
      const r = mk('button', 'btn lift', 'Retry'); r.type = 'button';
      r.addEventListener('click', () => { r.disabled = true; refreshIntegrations(); }); acts.appendChild(r);
    }
    return acts;
  }
  function renderIntegrations() {
    const box = $('integrations'); box.replaceChildren();
    const st = integState(), g = integ.data ? integ.data.google : null;
    const said = (k) => (integ.data && typeof integ.data[k] === 'boolean' ? integ.data[k] : null);
    emit('jarvis:integrations', { google: integ.data ? st : null, email: g && g.connected && g.email ? String(g.email) : null,
      drive: said('drive_available'), maps: said('maps_available') });
    const meta = $('integMeta');
    meta.textContent = st === 'linked' ? 'Google linked' : st === 'reconnect' ? 'Attention' : '';
    meta.className = 'pmeta' + (st === 'linked' ? ' ok' : st === 'reconnect' ? ' warn' : '');
    const row = mk('div', 'integ'); row.dataset.state = st;
    const head = mk('div', 'ihead'); head.append(mk('b', '', 'Google'), mk('span', 'istate', STATE_WORDS[st]));
    row.append(head, integBody(st, g));
    if (integ.note) { const n = mk('div', 'inote ' + integ.note.kind, integ.note.text); n.setAttribute('role', 'status'); row.appendChild(n); integ.note = null; }
    const acts = integActions(st, row); if (acts.childElementCount) row.appendChild(acts);
    box.appendChild(row);
    renderWhatsapp();
  }
  // R1 D9: an always-present WhatsApp drafts line, whatever the Google link or the Contacts Grant
  // is. Typed numbers need nothing; a name needs the Contacts Grant; the owner's Never is said.
  const wa = { off: null }; // null = not known yet / unreadable
  function whatsappWords() {
    if (wa.off === true) return 'Switched off in Permissions';
    const g = integ.data && integ.data.google;
    return g && g.contacts_granted === true ? 'Ready for typed numbers and, by name, your contacts'
      : 'Ready for typed numbers \u00b7 by name after the Contacts Grant';
  }
  function renderWhatsapp() {
    const box = $('integrations'); if (!box) return;
    let line = $('waLine');
    if (!line) { line = mk('div', 'integ'); line.id = 'waLine'; }
    const head = mk('div', 'ihead'); head.append(mk('b', '', 'WhatsApp drafts'), mk('span', 'istate', whatsappWords()));
    const kids = [head];
    if (wa.off === true) {
      const open = mk('button', 'btn lift', 'Open'); open.type = 'button'; open.id = 'waOpen';
      open.addEventListener('click', () => {
        if (window.JarvisDeck && typeof window.JarvisDeck.open === 'function') window.JarvisDeck.open('approvals');
        const b = $('permSetBtn'); if (b && b.getAttribute('aria-expanded') !== 'true') b.click();
        const r = document.querySelector('#permGroups [data-group="whatsapp"]');
        if (r) r.scrollIntoView({ block: 'nearest' });
      });
      const acts = mk('div', 'actions'); acts.appendChild(open); kids.push(acts);
    }
    line.replaceChildren(...kids);
    box.appendChild(line);
  }
  async function loadWhatsapp() {
    try {
      const p = await api('/v1/permissions');
      const g = p && Array.isArray(p.groups) ? p.groups.find((x) => x && x.id === 'whatsapp') : null;
      wa.off = g ? g.effect === 'deny' : null;
    } catch (_) { wa.off = null; }
    renderWhatsapp();
  }
  function askDisconnect(row, trigger) {
    if (row.querySelector('.confirm')) return;
    const box = mk('div', 'confirm'); box.setAttribute('role', 'alert');
    const t = mk('span', '', 'Disconnect Google? JARVIS forgets the link and the Calendar and Gmail tools stop working until you connect again.');
    const yes = mk('button', 'btn danger lift', 'Disconnect'); yes.type = 'button';
    const no = mk('button', 'btn lift', 'Keep'); no.type = 'button';
    const keep = () => { box.remove(); trigger.focus(); };
    no.addEventListener('click', keep);
    box.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.isComposing) return; e.preventDefault(); e.stopPropagation(); keep(); });
    yes.addEventListener('click', async () => {
      yes.disabled = no.disabled = true;
      try {
        await api('/v1/integrations/google/disconnect', { body: {} });
        integ.note = { kind: 'ok', text: 'Google disconnected.' }; note('info', 'Google disconnected');
      } catch (e) { integ.note = { kind: 'bad', text: 'Couldn\'t disconnect. ' + e.message }; }
      await refreshIntegrations();
    });
    box.append(t, no, yes); row.appendChild(box); no.focus();
  }
  async function refreshIntegrations() {
    integ.error = null;
    try { integ.data = await api('/v1/integrations'); }
    catch (e) {
      if (e.status === 404) integ.data = null;
      else if (e.status !== 401) { integ.data = undefined; integ.error = e.message || 'error'; }
    }
    integ.loaded = true; integ.at = performance.now();
    renderIntegrations();
    loadWhatsapp();
  }
  // /?connect_error=<code> from the callback: a fixed plain-English line per known code; the raw
  // query text is never shown.
  const CONNECT_ERRORS = {
    not_started: 'The Google link wasn\'t started from this browser session (or the signed-in account changed). Press Connect Google to try again.',
    wrong_account: 'Google was linked with a different Google account. Connect again and choose the account you sign in to JARVIS with.',
    oauth_failed: 'Google didn\'t finish linking (cancelled or timed out). Press Connect Google to try again.',
    no_refresh_token: 'Google didn\'t grant lasting access. Try again; if it repeats, remove JARVIS under myaccount.google.com \u2192 Security \u2192 Third-party connections, then connect.',
    missing_scopes: 'Some permissions were left unticked. Connect again and keep every Calendar and Gmail box ticked: JARVIS needs all of them.',
  };
  const CONNECT_ERROR_FALLBACK = 'Google linking didn\'t complete. Press Connect Google to try again.';
  /** Back from Google's consent screen (success or failure): queue the note for the panel and
   *  clean the address bar. Returns true when boot should open the Integrations panel instead of
   *  focusing the composer. */
  function afterConnectRedirect() {
    let q; try { q = new URLSearchParams(window.location.search); } catch (_) { return false; }
    const ok = q.get('connected') === 'google', code = q.get('connect_error');
    if (!ok && code === null) return false;
    if (ok) {
      integ.note = { kind: 'ok', text: 'Google connected. Calendar and Gmail tools are ready.' };
      note('info', 'Google connected');
    } else {
      const known = Object.prototype.hasOwnProperty.call(CONNECT_ERRORS, code);
      integ.note = { kind: 'bad', text: known ? CONNECT_ERRORS[code] : CONNECT_ERROR_FALLBACK };
      note('error', 'Google not connected');
    }
    try { history.replaceState(null, '', window.location.pathname); } catch (_) {}
    return true;
  }
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id === 'integrations' && d.open && integ.loaded && performance.now() - integ.at > INTEG_FRESH_MS) refreshIntegrations();
  });

  window.JarvisIntegrations = Object.freeze({ afterConnectRedirect, refresh: refreshIntegrations, scopeSummary });
})();
