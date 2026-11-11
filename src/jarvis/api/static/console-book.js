// src/jarvis/api/static/console-book.js -- R6 D8, D16 (docs/plans/r6-build-book.md): the Book panel (#p-book in console.html):
// status, Open (passkey + a fresh Google sign-in), the sections reader, older releases, the code
// download, Book settings.
// Open: a sign-in older than 5 minutes first goes to Google (/auth/login?reauth=1, the choice kept in this tab's
// sessionStorage 'jarvis_book_pending'), and on /?reauth=done the panel resumes: one tap for the passkey, bound to the
// audience (JarvisPasskey.prove('book_open', audience)). No passkey in force -> the server refuses; the panel never
// falls back to the sign-in alone. A guest open goes straight to the show (/book/show) with the token in THIS tab's
// sessionStorage only; an owner open keeps the token in memory for the reader (sections of each kept release, the code
// download by a 60 s single-use ticket) and the show. Every book route gets the token as X-Jarvis-Book.
// Transport: window.JarvisConsole.api (cookie + X-Requested-With, or the bearer token); bytes by JarvisChat.raw.
// Server text reaches the page through textContent only. No build step; CSP script-src 'self'; ASCII source; <= 400 lines.
// API: GET /v1/book; POST /v1/book/open {proof?, audience}; GET /v1/book/sections; GET /v1/book/releases/{rid}/sections;
//   POST /v1/book/releases/{rid}/ticket; GET /v1/book/download/{ticket}; POST /v1/book/show/beat; POST /v1/book/close;
//   GET|PUT /v1/book/settings.
(() => {
  'use strict';
  const panel = document.getElementById('p-book');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const RID = /^[0-9a-f]{7}$/, LABEL = /^R\d{1,3}(\.\d{1,2})?$/, TICKET = /^[A-Za-z0-9_-]{8,128}$/;
  const VER = /^v\d{1,3}\.\d{1,3}\.\d{1,4}$/; // R6.1 decision 3: a release's version, shown next to its id
  const PENDING = 'jarvis_book_pending', SHOW_TOKEN = 'jarvis_book_token', SHOW_SESSION = 'jarvis_book_session';
  const HEADER = 'X-Jarvis-Book', PENDING_MS = 10 * 60 * 1000, BEAT_MS = 60 * 1000, SEAL_RETRY_MS = 8000, SEAL_TRIES = 6;
  const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const Deck = window.JarvisDeck || { open() {}, isOpen: () => false };
  const S = { data: undefined, error: '', busy: false, token: '', session: null, reading: '', resume: null, setup: false,
    tries: 0, loading: null, focus: null };
  let beatTimer = 0, sealTimer = 0, endTimer = 0, noteEl = null, dialog = null, setBox = null, readerBox = null, readerKey = '';
  // ?reauth=done|stale as this page was LOADED: Permissions may already have replaced the address by the time this runs
  const back = (() => {
    try {
      const nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      return new URL(nav && nav.name ? nav.name : window.location.href).searchParams.get('reauth') || '';
    } catch (_) { return ''; }
  })();

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const booked = (opts = {}) => Object.assign({}, opts, { headers: Object.assign({}, opts.headers || {}, { [HEADER]: S.token }) });
  const ss = {
    get(k) { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (_) {} },
    del(k) { try { sessionStorage.removeItem(k); } catch (_) {} },
  };
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    if (e && e.passkeyMessage) return e.passkeyMessage;
    const m = e && typeof e.message === 'string' ? txt(e.message, 300) : '';
    return m && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  function say(kind, words) { if (!noteEl) return; noteEl.className = 'bnote bk-note' + (kind ? ' ' + kind : ''); noteEl.textContent = words || ''; }
  function when(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(d); } catch (_) { return ''; }
  }
  function clock(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], { hour: 'numeric', minute: '2-digit' }).format(d); } catch (_) { return ''; }
  }
  const mb = (v) => (Math.round(num(v) * 10) / 10).toString() + ' MB';

  // ---- what GET /v1/book sends, checked field by field ---------------------------------------
  function rel(v) {
    const r = obj(v);
    return r && RID.test(r.id || '') ? { id: r.id, label: LABEL.test(r.label || '') ? r.label : '', version: VER.test(r.version || '') ? r.version : '',
      at: txt(r.sealed_at || r.committed_at, 40), mb: num(r.mb) } : null;
  }
  function normal(raw) {
    const d = obj(raw);
    if (!d) return null;
    const open = obj(d.open) || {}, last = obj(d.last_closed), talk = obj(d.talk) || {};
    return { available: d.available === true, reason: txt(d.reason, 300), sealing: d.reason === 'sealing' || d.sealing === true,
      release: rel(d.release), sealed: arr(d.sealed).map(rel).filter(Boolean).slice(0, 10), kept: num(d.kept),
      used: num(d.used_mb), limit: num(d.limit_mb), lock: !!(obj(d.lock) || {}).on, talk: { on: talk.on === true, why: txt(talk.why, 200) },
      last: last && when(last.last_closed_at) ? { at: when(last.last_closed_at), told: last.notified === true } : null, // D14: what stays
      ready: open.passkey_ready === true, fresh: num(open.fresh_left_s) };
  }
  const name = (r) => (r.label ? r.label + ' \u00b7 ' : '') + (r.version ? r.version + ' \u00b7 ' : '') + r.id; // R6 rows: no version

  // ---- a confirm dialog (the console's .bdialog, native modal: Esc and focus handled by the browser)
  function ask(title, lines, buttons) {
    if (!dialog) { dialog = mk('dialog', 'bdialog'); dialog.setAttribute('role', 'alertdialog'); dialog.id = 'bookDialog'; document.body.append(dialog); }
    dialog.textContent = '';
    const h = mk('h2', '', title); h.id = 'bookDialogTitle'; dialog.setAttribute('aria-labelledby', h.id); dialog.append(h);
    lines.forEach((l) => dialog.append(mk('p', '', l)));
    const row = mk('div', 'actions');
    return new Promise((resolve) => {
      const done = (id) => { if (dialog.open) dialog.close(); resolve(id); };
      buttons.forEach((b) => { const btn = mk('button', 'btn lift' + (b.kind ? ' ' + b.kind : ''), b.label); btn.type = 'button'; btn.addEventListener('click', () => done(b.id)); row.append(btn); });
      dialog.append(row);
      dialog.oncancel = () => resolve('');
      try { dialog.showModal(); } catch (_) { dialog.setAttribute('open', ''); }
      const safe = row.querySelector('.btn:not(.primary)'); if (safe) safe.focus();
    });
  }

  // ---- views ---------------------------------------------------------------------------------
  function releaseCard(d) {
    const r = d.release, sealed = !!r && d.sealed.some((s) => s.id === r.id);
    const card = mk('div', 'integ bk-release'), head = mk('div', 'ihead'), body = mk('div', 'ibody');
    card.dataset.state = sealed ? 'linked' : 'reconnect';
    head.append(mk('b', '', r ? name(r) : 'No release'), mk('span', 'istate', S.token ? 'Open' : sealed ? 'Sealed' : d.sealing ? 'Sealing' : 'Not sealed'));
    body.append(mk('p', '', sealed ? 'This release\u2019s book and code are sealed in your vault.'
      : d.sealing ? 'Sealing this release\u2026' : 'This release is not sealed yet.'));
    if (S.session && clock(S.session.until)) body.append(mk('p', 'fine', 'This session ends at ' + clock(S.session.until) + '.'));
    card.append(head, body); return card;
  }
  function sealedList(d) {
    const sec = mk('div', 'bsec'), h = mk('h3', '', 'Kept releases'), ul = mk('ul', 'bk-sealed');
    h.append(mk('span', 'bcount', d.sealed.length + ' of ' + (d.kept || 3)));
    d.sealed.forEach((s) => {
      const li = mk('li', 'bk-row'), t = mk('span', 'bk-rtxt');
      t.append(mk('b', '', name(s)), mk('small', '', [s.at ? 'Sealed ' + when(s.at) : '', mb(s.mb)].filter(Boolean).join(' \u00b7 ')));
      li.append(t);
      if (S.token) {
        const acts = mk('span', 'bk-racts');
        acts.append(button('Read', '', () => readRelease(s)), button('Download code', '', () => download(s)));
        li.append(acts);
      }
      ul.append(li);
    });
    if (!d.sealed.length) ul.append(mk('li', 'bempty', 'No release is sealed yet.'));
    sec.append(h, ul); return sec;
  }
  function tiles(d) {
    const t = mk('div', 'tiles bk-tiles');
    [[mb(d.used), 'Used'], [mb(d.limit), 'Limit'], [String(d.sealed.length), 'Kept']].forEach(([v, k]) => {
      const tile = mk('div', 'tile'); tile.append(mk('b', '', v), mk('span', '', k)); t.append(tile);
    });
    return t;
  }
  function button(label, kind, fn) {
    const b = mk('button', 'btn lift' + (kind ? ' ' + kind : ''), label); b.type = 'button'; b.disabled = S.busy;
    b.addEventListener('click', fn); return b;
  }
  function opens(d) {
    const box = mk('div', 'bk-opens');
    if (S.resume) {
      const r = mk('div', 'iopt bk-resume');
      r.append(mk('span', '', 'Signed in again. Use your passkey to open the book' + (S.resume.audience === 'guest' ? ' for a guest.' : '.')));
      const acts = mk('span', 'bk-racts');
      acts.append(button('Cancel', '', () => { ss.del(PENDING); S.resume = null; render(); }), button('Use my passkey', 'primary', () => {
        const a = S.resume.audience; ss.del(PENDING); S.resume = null; proveAndOpen(a);
      }));
      r.append(acts); box.append(r); return box;
    }
    const acts = mk('div', 'actions');
    acts.append(button('Open for me', 'primary', () => start('owner')), button('Show a guest', '', () => start('guest')));
    box.append(acts, mk('p', 'bfine', 'Opening takes your passkey and a Google sign-in from the last 5 minutes.'));
    if (S.setup) box.append(button('Set up a passkey', '', () => Deck.open('approvals', { focus: true })));
    box.append(mk('p', 'bfine', d.talk.on ? 'Questions after the show: on.' : 'Questions after the show: off' + (d.talk.why ? ' (' + d.talk.why + ')' : '') + '.'));
    return box;
  }
  function sessionBar() {
    const acts = mk('div', 'actions bk-session');
    acts.append(button('Start the show', 'primary', () => toShow(S.token, S.session)), button('End session', '', () => end(true)));
    return acts;
  }
  /** The focused control as text + its place among controls with the same text (a re-render rebuilds them). */
  function focusKey() {
    const a = document.activeElement;
    if (!a || !host.contains(a) || a.tagName !== 'BUTTON') return a === document.body ? S.focus : null;
    const twins = [...host.querySelectorAll('button')].filter((b) => b.textContent === a.textContent);
    return { text: a.textContent, n: twins.indexOf(a) };
  }
  function refocus(k) {
    S.focus = null;
    if (!k) return;
    const b = [...host.querySelectorAll('button')].filter((x) => x.textContent === k.text)[k.n];
    if (b && !b.disabled) b.focus(); else if (b) S.focus = k; // disabled while busy: the next render puts it back
  }
  function render() {
    const keep = focusKey();
    paint();
    refocus(keep);
  }
  function paint() {
    host.textContent = '';
    noteEl = noteEl || mk('p', 'bnote bk-note'); noteEl.setAttribute('role', 'status');
    const d = S.data;
    if (!d) { host.append(noteEl); if (!noteEl.textContent) say('', S.error || 'Reading the build book\u2026'); return; }
    host.append(releaseCard(d));
    if (d.lock) {
      const l = mk('div', 'iopt bk-lock'); l.append(mk('span', '', 'A guest show is holding your consoles. Resume it from the show with your passkey.'),
        button('Go to the show', '', () => window.location.assign('/book/show')));
      host.append(l);
    }
    host.append(S.token ? sessionBar() : opens(d), noteEl);
    if (S.token) host.append(reader());
    host.append(sealedList(d), tiles(d));
    if (d.last) host.append(mk('p', 'bnote bk-last', 'Last session closed ' + d.last.at + '; its conversation was deleted'
      + (d.last.told ? ' and you were told.' : '.')));
    const R = window.JarvisBookReader;
    if (R && !setBox) setBox = R.settings(mk('div'), { load: () => api('/v1/book/settings'), ask,
      save: (patch) => api('/v1/book/settings', { method: 'PUT', body: patch }).catch((e) => { throw new Error(detailOf(e) || 'Couldn\u2019t save.'); }) });
    if (setBox) host.append(setBox);
  }
  /** The reader keeps its element (and what is expanded) until the session or the release read changes. */
  function reader() {
    const key = S.token + '|' + S.reading;
    if (readerBox && readerKey === key) return readerBox;
    readerKey = key; readerBox = mk('div', 'bk-reader'); readerBox.id = 'bkReader'; paintReader(readerBox);
    return readerBox;
  }

  // ---- load ------------------------------------------------------------------------------------
  async function load() {
    if (!hasApi()) return;
    if (S.loading) return S.loading;
    S.loading = (async () => {
      try {
        const d = normal(await api('/v1/book'));
        S.data = d && d.available ? d : null;
        S.error = d && !d.available ? d.reason || 'This server has no build book.' : d ? '' : 'The build book answered in a shape this page doesn\u2019t know.';
        if (d && d.sealing && S.tries < SEAL_TRIES) { S.tries += 1; clearTimeout(sealTimer); sealTimer = setTimeout(load, SEAL_RETRY_MS); }
      } catch (e) {
        if (e && e.status === 401) return;
        S.data = null; S.error = e && e.status === 404 ? 'Not available in this setup.' : detailOf(e) || 'Couldn\u2019t read the build book.';
      } finally { S.loading = null; }
      if (!S.data) say(S.error && !/^Reading/.test(S.error) ? 'bad' : '', S.error);
      else if (noteEl && /^Reading/.test(noteEl.textContent)) say('', ''); // loaded: the waiting words go
      render();
    })();
    return S.loading;
  }

  // ---- open: passkey + a fresh Google sign-in (D8) ---------------------------------------------
  function start(audience) {
    if (S.busy || !S.data) return;
    S.setup = false;
    if (S.data.ready && S.data.fresh <= 5) { hop(audience, ''); return; }
    proveAndOpen(audience);
  }
  async function hop(audience, detail) {
    const go = await ask('Sign in with Google again', [detail || 'Opening the build book needs a Google sign-in from the last 5 minutes, then your passkey.',
      'You come back to this panel afterwards.'], [{ id: '', label: 'Not now' }, { id: 'go', label: 'Sign in with Google', kind: 'primary' }]);
    if (go !== 'go') return;
    ss.set(PENDING, JSON.stringify({ audience, at: Date.now() }));
    window.location.assign('/auth/login?reauth=1');
  }
  async function proveAndOpen(audience) {
    if (S.busy) return;
    S.busy = true; say('', S.data && S.data.ready ? 'Waiting for your passkey\u2026' : 'Opening\u2026'); render();
    try {
      const body = { audience };
      if (S.data && S.data.ready) {
        const P = window.JarvisPasskey;
        if (!P || typeof P.prove !== 'function') throw new Error('Passkeys are not available in this page.');
        body.proof = await P.prove('book_open', audience);
      }
      const r = obj(await api('/v1/book/open', { method: 'POST', body }));
      if (!r || typeof r.token !== 'string' || !r.token) throw new Error('The build book did not open. Please try again.');
      S.busy = false; opened(r);
    } catch (e) { S.busy = false; failed(e, audience); }
    render();
  }
  function failed(e, audience) {
    if (e && e.status === 401) return;
    const code = e && e.code;
    if (code === 'reauth_required') { say('', ''); hop(audience, detailOf(e)); return; }
    if (code === 'passkey_setup_needed') { S.setup = true; say('bad', detailOf(e) || 'Set up a passkey in Approvals \u2192 Permissions first.'); return; }
    say('bad', detailOf(e) || 'The build book did not open. Please try again.');
  }
  function opened(r) {
    const session = { session_id: txt(r.session_id, 40), until: txt(r.until, 40), audience: r.audience === 'guest' ? 'guest' : 'owner' };
    if (session.audience === 'guest') { toShow(r.token, session); return; }
    S.token = r.token; S.session = session; S.reading = '';
    say('ok', 'Open. Read it here or start the show.');
    clearInterval(beatTimer); beatTimer = setInterval(beat, BEAT_MS);
    const left = Date.parse(session.until) - Date.now();
    clearTimeout(endTimer); if (left > 0) endTimer = setTimeout(() => forget('The session reached its time limit and closed.'), left);
  }
  /** The show runs in this tab: the token moves to this tab's sessionStorage, nowhere else. A guest's show replaces
   *  the console page, so it is no Back entry (a back/forward-cache view would skip the lock). */
  function toShow(token, session) {
    ss.set(SHOW_TOKEN, token); ss.set(SHOW_SESSION, JSON.stringify(session || {}));
    S.token = ''; clearInterval(beatTimer); clearTimeout(endTimer);
    if (!session || session.audience !== 'guest') { window.location.assign('/book/show'); return; }
    try { const ch = new BroadcastChannel('jarvis-book'); ch.postMessage({ type: 'guest-show' }); ch.close(); } catch (_) {} // D10: open console tabs hop now
    window.location.replace('/book/show');
  }

  // ---- the owner's open session: reader, older releases, download, beat, end -----------------
  async function paintReader(box) {
    const R = window.JarvisBookReader, rid = S.reading;
    const cur = S.data && S.data.release, label = rid ? (S.data.sealed.find((s) => s.id === rid) || { id: rid, label: '' }) : cur;
    const head = mk('div', 'rhead bk-rhead');
    head.append(mk('span', 'k', 'Reading ' + (label ? name(label) : 'this release')));
    if (rid) head.append(button('Back to this release', '', () => { S.reading = ''; render(); }));
    const list = mk('div', 'bk-sections'); list.append(mk('p', 'bempty', 'Opening the sections\u2026'));
    box.append(head, list);
    try {
      const path = rid ? '/v1/book/releases/' + rid + '/sections' : '/v1/book/sections';
      const got = await api(path, booked());
      if (!R || !R.sections(list, got)) list.replaceChildren(mk('p', 'bempty', 'No sections came back.'));
    } catch (e) { if (!gone(e)) list.replaceChildren(mk('p', 'bempty', detailOf(e) || 'Couldn\u2019t read the sections.')); }
  }
  function readRelease(s) { S.reading = s.id === (S.data.release || {}).id ? '' : s.id; render(); }
  async function download(s) {
    if (S.busy) return;
    S.busy = true; say('', 'Fetching the sealed code of ' + name(s) + '\u2026'); render();
    try {
      const t = obj(await api('/v1/book/releases/' + s.id + '/ticket', booked({ method: 'POST' })));
      if (!t || !TICKET.test(t.ticket || '')) throw new Error('The download could not start.');
      const chat = window.JarvisChat;
      if (!chat || typeof chat.raw !== 'function') throw new Error('Downloads are not available in this page.');
      const r = await chat.raw('/v1/book/download/' + encodeURIComponent(t.ticket));
      if (!r.ok) throw new Error('The download did not work. Please try again.');
      const cd = r.headers.get('Content-Disposition') || '', m = /filename="([A-Za-z0-9._-]{1,80})"/.exec(cd);
      save(await r.blob(), m ? m[1] : 'JARVIS-source-' + s.id + '.zip');
      say('ok', 'Saved the code of ' + name(s) + ' to your Downloads. It is no longer encrypted there.');
    } catch (e) { if (!gone(e)) say('bad', detailOf(e) || 'The download did not work.'); }
    S.busy = false; render();
  }
  function save(blob, file) { // our own bytes, as a blob: URL (never server text in a link)
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = file; a.rel = 'noopener'; a.hidden = true; document.body.append(a); a.click();
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1500);
  }
  function gone(e) { if (e && (e.status === 401 || e.status === 410)) { forget('The book session ended.'); return true; } return false; }
  async function beat() {
    if (!S.token || document.hidden) return;
    try { await api('/v1/book/show/beat', booked({ method: 'POST' })); } catch (e) { gone(e); }
  }
  function forget(words) {
    S.token = ''; S.session = null; S.reading = ''; clearInterval(beatTimer); clearTimeout(endTimer);
    if (words) say('', words);
    render();
  }
  async function end(confirmFirst) {
    if (!S.token) return;
    if (confirmFirst) {
      const go = await ask('End the session?', ['Its conversation will be deleted.'], [{ id: '', label: 'Keep it open' }, { id: 'go', label: 'End', kind: 'primary' }]);
      if (go !== 'go') return;
    }
    const opts = booked({ method: 'POST' });
    forget('');
    try { await api('/v1/book/close', opts); say('ok', 'Session ended. Its conversation was deleted.'); } catch (e) { say('bad', detailOf(e) || 'Couldn\u2019t end the session; it ends by itself in 10 minutes.'); }
    load();
  }

  // ---- wiring ------------------------------------------------------------------------------------
  function pending() {
    try {
      const p = JSON.parse(ss.get(PENDING) || 'null');
      return p && (p.audience === 'owner' || p.audience === 'guest') && Date.now() - num(p.at) < PENDING_MS ? { audience: p.audience } : null;
    } catch (_) { return null; }
  }
  function ready() {
    const p = pending();
    if (!p) { ss.del(PENDING); if (Deck.isOpen('book')) load(); return; }
    if (back === 'done') S.resume = p;
    else { ss.del(PENDING); if (back === 'stale') say('bad', 'Google didn\u2019t ask you to sign in again, so the book did not open. Sign out of Google in this browser, then try again.'); }
    if (!back) return;
    try { if (window.location.search) history.replaceState(null, '', window.location.pathname); } catch (_) {}
    Deck.open('book', { focus: true }); load();
  }
  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id !== 'book') return;
    if (d.open) load(); else if (S.token) end(false);
  });
  document.addEventListener('jarvis:ready', ready);
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) ready();
  render();
})();
