// src/jarvis/api/static/console-permissions.js — Approvals → Permissions (slice 10 D,
// docs/plans/phase2-slice10-tools-wave.md §D). No build step; CSP script-src 'self'; no library:
// passkeys use the browser's own navigator.credentials. Every server string reaches the page through
// textContent (never parsed as markup); a field of the wrong type is dropped, never guessed.
// Transport is the console's api() (window.JarvisConsole: cookie + X-Requested-With, or the bearer
// token; 401 → gate). Loads only when the Approvals panel opens or the section is expanded.
// API: GET/PUT /v1/permissions; POST /v1/passkeys/challenge {purpose, approval_id?, credential_id?};
// POST /v1/passkeys/register/options {proof?}; POST /v1/passkeys/register {challenge_id, credential,
// label}; POST /v1/passkeys/{id}/remove {proof}; POST /v1/passkeys/reset; POST /v1/passkeys/reset/cancel
// {proof}. Re-sign-in: /auth/login?reauth=1 → /?reauth=done (or =stale: Google didn't ask again).
// Lowering protection always takes a passkey; a fresh Google sign-in only sets up the FIRST passkey or
// starts the 24-hour reset, which shows as a banner at the top of the Approvals panel until it's over.
// Exposes window.JarvisPasskey {supported(), approve(approvalId) → proof, message(err)} for the
// approval cards in console.js ("Approve with passkey").
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const btn = $('permSetBtn'), body = $('permSetBody'), sum = $('permSum');
  const noteEl = $('permNote'), groupsEl = $('permGroups'), box = $('pskBox'), banner = $('permBanner');
  const Deck = window.JarvisDeck || { open() {}, isOpen: () => false };
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const OPEN_KEY = 'jarvis_permissions_open';
  const STALE_MS = 60 * 1000;
  const WORDS = { allow: 'Allow', ask: 'Ask first', deny: 'Never' };
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const NOT_SUPPORTED = 'Passkeys are not supported in this browser. Try an up-to-date Chrome, Edge, Safari or Firefox.';
  const CANCELLED = 'Cancelled. Nothing was changed.';
  const TIMED_OUT = 'The passkey prompt timed out. Nothing was changed.';
  const WRONG_SITE = 'This page\'s address doesn\'t match the passkey\'s site. Open JARVIS at its usual address.';
  const ALREADY = 'That passkey is already set up on this device.';
  const FAILED = 'The passkey check didn\'t work. Please try again.';

  // ---- small, type-checking helpers -----------------------------------------------------------
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (v, max = 200) => (typeof v === 'string' ? v.replace(INVISIBLE, '').trim().slice(0, max) : '');
  const own = (map, key) => (typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined);
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && window.JarvisConsole.api);
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  function detailOf(e) {
    if (e && e.passkeyMessage) return e.passkeyMessage;
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? e.message.replace(INVISIBLE, '').trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }
  const errText = (e) => detailOf(e) || 'Please try again.';
  function day(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', year: 'numeric' }).format(d); } catch (_) { return ''; }
  }

  // ---- WebAuthn: base64url ⇄ bytes and the browser's own ceremony -------------------------------
  const supported = () => typeof window.PublicKeyCredential === 'function' && !!navigator.credentials &&
    typeof navigator.credentials.get === 'function' && typeof navigator.credentials.create === 'function';
  function toBuf(s) {
    const b = atob(String(s).replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (String(s).length % 4)) % 4));
    const u = new Uint8Array(b.length);
    for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    return u.buffer;
  }
  function toB64u(buf) {
    const u = new Uint8Array(buf); let s = '';
    for (let i = 0; i < u.length; i++) s += String.fromCharCode(u[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  const descriptors = (list) => arr(list).map(c => ({ type: 'public-key', id: toBuf(c.id), transports: arr(c.transports) }));
  function plain(message) { const e = new Error(message); e.passkeyMessage = message; return e; }
  /** DOMException → plain words. NotAllowedError means "cancelled" or "timed out": told apart by time. */
  function friendly(e, startedMs, timeoutMs) {
    const name = e && e.name;
    if (name === 'NotAllowedError') return Date.now() - startedMs >= (timeoutMs || 120000) - 1500 ? TIMED_OUT : CANCELLED;
    if (name === 'AbortError') return CANCELLED;
    if (name === 'SecurityError') return WRONG_SITE;
    if (name === 'NotSupportedError') return NOT_SUPPORTED;
    if (name === 'InvalidStateError') return ALREADY;
    return FAILED;
  }
  async function ceremony(kind, publicKey, timeoutMs) {
    const t0 = Date.now();
    let cred;
    try { cred = await navigator.credentials[kind]({ publicKey }); }
    catch (e) { throw plain(friendly(e, t0, timeoutMs)); }
    if (!cred) throw plain(CANCELLED);
    return cred;
  }
  /** A passkey check for one purpose: the server's challenge, signed on this device. */
  async function prove(req) {
    if (!supported()) throw plain(NOT_SUPPORTED);
    const ch = obj(await api('/v1/passkeys/challenge', { body: req })) || {};
    const pk = obj(ch.public_key);
    if (!pk || typeof ch.challenge_id !== 'string') throw plain(FAILED);
    const cred = await ceremony('get', { challenge: toBuf(pk.challenge), rpId: pk.rpId, timeout: pk.timeout,
      userVerification: 'required', allowCredentials: descriptors(pk.allowCredentials) }, pk.timeout);
    const r = cred.response;
    return { challenge_id: ch.challenge_id, credential: { id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
      response: { clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData),
        signature: toB64u(r.signature), userHandle: r.userHandle ? toB64u(r.userHandle) : null } } };
  }
  async function createPasskey(proof, label) {
    if (!supported()) throw plain(NOT_SUPPORTED);
    const o = obj(await api('/v1/passkeys/register/options', { body: proof ? { proof } : {} })) || {};
    const pk = obj(o.public_key), user = obj(pk && pk.user);
    if (!pk || !user || typeof o.challenge_id !== 'string') throw plain(FAILED);
    const cred = await ceremony('create', { rp: pk.rp, user: { id: toBuf(user.id), name: user.name, displayName: user.displayName },
      challenge: toBuf(pk.challenge), pubKeyCredParams: arr(pk.pubKeyCredParams), timeout: pk.timeout,
      excludeCredentials: descriptors(pk.excludeCredentials), authenticatorSelection: pk.authenticatorSelection,
      attestation: 'none' }, pk.timeout);
    const r = cred.response;
    const transports = typeof r.getTransports === 'function' ? arr(r.getTransports()).filter(t => typeof t === 'string') : [];
    return api('/v1/passkeys/register', { body: { challenge_id: o.challenge_id, label, credential: { id: cred.id,
      rawId: toB64u(cred.rawId), type: cred.type, response: { clientDataJSON: toB64u(r.clientDataJSON),
        attestationObject: toB64u(r.attestationObject), transports } } } });
  }
  window.JarvisPasskey = Object.freeze({
    supported,
    approve: (approvalId) => prove({ purpose: 'approve', approval_id: String(approvalId) }),
    message: (e) => errText(e),
  });

  // ---- what the server sends, checked field by field --------------------------------------------
  function normal(v) {
    const o = obj(v);
    if (!o) return null;
    const groups = arr(o.groups).map(g => {
      const x = obj(g); if (!x || typeof x.id !== 'string') return null;
      const choices = arr(x.choices).filter(c => own(WORDS, c));
      const effect = own(WORDS, x.effect) ? x.effect : (own(WORDS, x.default) ? x.default : 'ask');
      // R1 D9: no row ever vanishes. Choices this page doesn't know -> the row stays, read-only.
      return { id: txt(x.id, 40), section: txt(x.section, 40), label: txt(x.label, 80) || txt(x.id, 40), hint: txt(x.hint, 200),
        irreversible: x.irreversible === true, choices, readonly: choices.length === 0, effect, dflt: own(WORDS, x.default) ? x.default : effect,
        available: x.available !== false, note: txt(x.note, 200) };
    }).filter(Boolean);
    const passkeys = arr(o.passkeys).map(p => {
      const x = obj(p); const id = x && typeof x.id === 'string' && x.id.length <= 1400 ? x.id : '';
      return id ? { id, label: txt(x.label, 40) || 'Passkey', created: day(x.created_at), used: day(x.last_used_at),
        recovery: x.via_recovery === true } : null;
    }).filter(Boolean);
    const fresh = typeof o.fresh_sign_in_s === 'number' && Number.isFinite(o.fresh_sign_in_s) ? Math.max(0, o.fresh_sign_in_s) : 0;
    const reset = obj(o.reset), resetAt = reset ? moment(reset.effective_at) : '';
    return { groups, passkeys, require: o.require_passkey === true, available: o.passkeys_available === true,
      why: txt(o.passkeys_note, 300), error: txt(o.passkeys_error, 300), reset: resetAt ? { at: resetAt } : null,
      canReauth: o.can_reauth === true, fresh, max: typeof o.max_passkeys === 'number' ? o.max_passkeys : 10 };
  }
  /** "2 Nov, 9:00 am" in the owner's own time and language. */
  function moment(iso) {
    const d = new Date(txt(iso, 40) || NaN);
    if (isNaN(d)) return '';
    try { return new Intl.DateTimeFormat([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(d); } catch (_) { return ''; }
  }

  // ---- state ------------------------------------------------------------------------------------
  const S = { data: undefined, error: '', seq: 0, fetchedAt: 0, busy: false, confirm: null, confirmReset: false, signedIn: false };
  const freshLeft = () => (S.data ? S.data.fresh - (Date.now() - S.fetchedAt) / 1000 : 0);
  function note(kind, text) { if (!noteEl) return; noteEl.className = 'bnote' + (kind ? ' ' + kind : ''); noteEl.textContent = text || ''; }

  async function load() {
    if (!hasApi() || !S.signedIn) return;
    const seq = ++S.seq;
    if (groupsEl) groupsEl.setAttribute('aria-busy', 'true');
    try {
      const d = normal(await api('/v1/permissions'));
      if (seq !== S.seq) return;
      S.data = d; S.error = d ? '' : 'Permissions came back in a shape this page doesn\'t know.'; S.fetchedAt = Date.now();
    } catch (e) {
      if (seq !== S.seq || e.status === 401) return;
      S.error = e.status === 404 ? 'Not available in this setup.' : 'Couldn\'t load permissions. ' + errText(e);
    } finally { if (seq === S.seq && groupsEl) groupsEl.setAttribute('aria-busy', 'false'); }
    render();
  }
  function stale() { return S.data === undefined || Date.now() - S.fetchedAt > STALE_MS; }

  function summary() {
    if (!sum) return;
    const d = S.data;
    if (!d) { sum.textContent = S.error ? 'Couldn\'t load' : ''; return; }
    const never = d.groups.filter(g => g.effect === 'deny').length;
    const asks = d.groups.filter(g => g.effect === 'ask' && g.dflt !== 'ask').length;
    const parts = [];
    if (never) parts.push(`${never} switched off`);
    if (asks) parts.push(`${asks} ${asks === 1 ? 'asks' : 'ask'} first`);
    const rules = parts.length ? parts.join(', ') : 'Defaults';
    const pk = !d.available ? 'Passkey not available' : d.require ? `Passkey on (${d.passkeys.length})` : 'Passkey off';
    sum.textContent = `${rules} · ${pk}`;
  }

  // ---- groups: one segmented control each (native radios: arrows move, Space picks) -------------
  let uid = 0;
  function groupRow(g) {
    const n = ++uid, row = mk('div', 'pgrp'), t = mk('div', 'btxt');
    const l = mk('span', 'bl', g.label); l.id = `pg${n}`;
    const h = mk('small', '', g.hint); h.id = `pgh${n}`;
    t.append(l, h);
    row.dataset.group = g.id;
    if (g.note) t.appendChild(mk('small', 'pgnote', g.note)); // R1 D9: what isn't connected yet; the control stays usable
    if (g.readonly) {
      t.appendChild(mk('small', 'pgnote pgro', 'Reload the page to change this'));
      row.appendChild(t);
      return row;
    }
    const seg = mk('div', 'seg' + (g.choices.length === 2 ? ' two' : ''));
    seg.setAttribute('role', 'radiogroup'); seg.setAttribute('aria-labelledby', l.id); seg.setAttribute('aria-describedby', h.id);
    g.choices.forEach(c => {
      const w = mk('span', 'seg-wrap'), inp = mk('input', 'opt-in'), lab = mk('label', 'seg-opt' + (c === 'deny' ? ' never' : ''), WORDS[c]);
      inp.type = 'radio'; inp.name = `pg${n}`; inp.id = `pg${n}-${c}`; inp.value = c; inp.checked = g.effect === c; inp.disabled = S.busy;
      lab.htmlFor = inp.id;
      inp.addEventListener('change', () => { if (inp.checked) choose(g, c); });
      w.append(inp, lab); seg.appendChild(w);
    });
    row.append(t, seg);
    return row;
  }
  async function choose(g, effect) {
    if (S.busy) return;
    S.busy = true;
    try {
      S.data = normal(await api('/v1/permissions', { method: 'PUT', body: { groups: { [g.id]: effect } } })) || S.data;
      S.fetchedAt = Date.now();
      note('ok', `${g.label}: ${WORDS[effect]}.`);
      log('info', `Permission · ${g.label}: ${WORDS[effect]}`);
    } catch (e) { note('bad', errText(e)); }
    finally { S.busy = false; render(); }
  }

  // ---- passkeys -----------------------------------------------------------------------------------
  // Every change that lowers protection is confirmed with a passkey (no sign-in shortcut). A fresh
  // Google sign-in only sets up the FIRST passkey, or starts the 24-hour reset of all of them.
  async function act(fn, ok) {
    if (S.busy) return;
    S.busy = true; note('', ''); render();
    try { const v = normal(await fn()); if (v) { S.data = v; S.fetchedAt = Date.now(); } note('ok', ok); log('info', ok); }
    catch (e) { note('bad', errText(e)); }
    finally { S.busy = false; S.confirm = null; S.confirmReset = false; render(); }
  }
  const addPasskey = (label) => act(async () => createPasskey(S.data.passkeys.length ? await prove({ purpose: 'add' }) : null, label),
    'Passkey set up. Approving anything that can\'t be undone now asks for it.');
  const removePasskey = (p) => act(async () => api(`/v1/passkeys/${encodeURIComponent(p.id)}/remove`,
    { body: { proof: await prove({ purpose: 'remove', credential_id: p.id }) } }), `Removed “${p.label}”.`);
  const setRequire = (on) => act(async () => api('/v1/permissions', { method: 'PUT',
    body: on ? { require_passkey: true } : { require_passkey: false, proof: await prove({ purpose: 'disable' }) } }),
  on ? 'Passkey needed for actions that can\'t be undone.' : 'Passkey no longer needed. Approvals still ask first.');
  const startReset = () => act(() => api('/v1/passkeys/reset', { body: {} }),
    'Reset started: every passkey will be removed in 24 hours. Any passkey can still cancel it.');
  const cancelReset = () => act(async () => api('/v1/passkeys/reset/cancel', { body: { proof: await prove({ purpose: 'cancel_reset' }) } }),
    'Reset cancelled. Your passkeys stay.');
  function reauth() { try { window.location.assign('/auth/login?reauth=1'); } catch (_) {} }

  function button(text, cls, onClick) {
    const b = mk('button', 'btn lift bact' + (cls ? ' ' + cls : ''), text); b.type = 'button';
    if (S.busy) b.setAttribute('aria-disabled', 'true');
    b.addEventListener('click', () => { if (!S.busy) onClick(b); });
    return b;
  }
  function passkeyRow(p) {
    const li = mk('li', 'pskrow'), t = mk('div', 'btxt');
    t.append(mk('span', 'bl', p.label), mk('small', '', [p.created && `Added ${p.created}`, p.used && `last used ${p.used}`].filter(Boolean).join(' · ')));
    if (p.recovery) t.appendChild(mk('small', 'pskflag', 'Set up after a reset by Google sign-in. Not you? Remove it.'));
    li.appendChild(t);
    if (S.confirm === p.id) {
      const c = mk('div', 'pskconfirm'); c.setAttribute('role', 'group'); c.setAttribute('aria-label', `Remove ${p.label}`);
      c.appendChild(mk('p', '', `Remove “${p.label}”? You'll confirm with one of your passkeys.`));
      const keep = button('Keep', '', () => { S.confirm = null; render(); });
      c.append(keep, button('Remove', 'mdanger', () => removePasskey(p)));
      li.appendChild(c);
      setTimeout(() => keep.focus(), 0);
    } else li.appendChild(button('Remove', 'mdanger', () => { S.confirm = p.id; render(); }));
    return li;
  }
  function renderPasskeys() {
    if (!box) return;
    box.replaceChildren();
    const d = S.data;
    if (!d.available) { box.appendChild(mk('p', 'bfine', d.why || 'Passkeys are off on this server.')); return; }
    box.appendChild(mk('p', 'bfine', 'With a passkey (Windows Hello, your phone\'s fingerprint or face, or a security key), approving anything that can\'t be undone — sending email, deleting — needs you, not just this browser.'));
    if (d.error) box.appendChild(mk('p', 'lerr', d.error));
    if (d.reset) {
      const r = mk('div', 'pskconfirm pskreset'); r.setAttribute('role', 'group'); r.setAttribute('aria-label', 'Passkey reset pending');
      r.appendChild(mk('p', '', `Every passkey will be removed on ${d.reset.at}. This was asked for with a Google sign-in. Not you? Cancel it with one of your passkeys, then secure your Google account.`));
      if (d.passkeys.length) { const c = button('Cancel reset', 'primary', cancelReset); c.id = 'pskCancelReset'; r.appendChild(c); }
      box.appendChild(r);
    }
    const opt = mk('div', 'bopt'), t = mk('div', 'btxt'), l = mk('span', 'bl', 'Require passkey for irreversible actions');
    l.id = 'pskReqL'; t.appendChild(l);
    t.appendChild(mk('small', '', d.passkeys.length ? 'Turning this off needs your passkey.' : 'Set up a passkey first.'));
    const sw = mk('button', 'bsw'); sw.type = 'button'; sw.id = 'pskReq';
    sw.setAttribute('aria-pressed', String(d.require)); sw.setAttribute('aria-labelledby', l.id);
    const track = mk('span', 'track'); track.setAttribute('aria-hidden', 'true'); track.appendChild(mk('i'));
    const st = mk('span', 'st', d.require ? 'On' : 'Off'); st.setAttribute('aria-hidden', 'true');
    sw.append(track, st);
    if (S.busy || !d.passkeys.length) sw.setAttribute('aria-disabled', 'true');
    sw.addEventListener('click', () => { if (!S.busy && d.passkeys.length) setRequire(!d.require); });
    opt.append(t, sw); box.appendChild(opt);
    if (d.passkeys.length) { const ul = mk('ul', 'psklist'); d.passkeys.forEach(p => ul.appendChild(passkeyRow(p))); box.appendChild(ul); }
    if (!supported()) box.appendChild(mk('p', 'lerr', NOT_SUPPORTED));
    else if (!d.passkeys.length && !d.error && freshLeft() <= 5) {
      box.appendChild(mk('p', 'bfine', 'Your first passkey needs a fresh Google sign-in in this browser (it counts for 5 minutes).'));
      const go = button('Sign in with Google again', 'primary', reauth); go.id = 'pskReauth'; box.appendChild(go);
    } else if (!d.error && d.passkeys.length < d.max) {
      const add = mk('form', 'pskadd'), lab = mk('label', 'sr-only', 'Name for the new passkey'), inp = mk('input', 'minput');
      inp.id = 'pskLabel'; inp.maxLength = 40; inp.placeholder = 'Name, e.g. Laptop'; inp.autocomplete = 'off'; lab.htmlFor = inp.id;
      const go = mk('button', 'btn primary lift bact', d.passkeys.length ? 'Add another passkey' : 'Set up a passkey');
      go.type = 'submit'; go.id = 'pskAdd'; if (S.busy) go.setAttribute('aria-disabled', 'true');
      add.addEventListener('submit', (ev) => { ev.preventDefault(); if (!S.busy) addPasskey(inp.value.trim()); });
      add.append(lab, inp, go); box.appendChild(add);
    }
    if (d.canReauth && (d.passkeys.length || d.error) && !d.reset) box.appendChild(recovery());
  }
  /** Lost every passkey: a Google sign-in can only START a reset, which happens 24 hours later. */
  function recovery() {
    const r = mk('div', 'pskrec');
    r.appendChild(mk('p', 'bfine', 'Lost all your passkeys? Sign in with Google again to start a reset: every passkey is removed after 24 hours, a notice goes to your Gmail inbox, and any passkey can cancel it.'));
    if (freshLeft() <= 5) { r.appendChild(button('Sign in again', '', reauth)); return r; }
    if (!S.confirmReset) {
      const go = button('Start 24-hour reset', 'mdanger', () => { S.confirmReset = true; render(); }); go.id = 'pskReset';
      r.appendChild(go); return r;
    }
    const c = mk('div', 'pskconfirm'); c.setAttribute('role', 'group'); c.setAttribute('aria-label', 'Start passkey reset');
    c.appendChild(mk('p', '', 'Remove every passkey in 24 hours? Until then nothing changes, and approving anything that can\'t be undone still needs a passkey.'));
    const keep = button('Keep', '', () => { S.confirmReset = false; render(); });
    const yes = button('Start reset', 'mdanger', startReset); yes.id = 'pskResetYes';
    c.append(keep, yes); r.appendChild(c);
    setTimeout(() => keep.focus(), 0);
    return r;
  }
  /** A pending reset shows at the top of the Approvals panel, whether Permissions is open or not. */
  function renderBanner() {
    if (!banner) return;
    const at = S.data && S.data.reset ? S.data.reset.at : '';
    banner.hidden = !at;
    banner.replaceChildren();
    if (!at) return;
    banner.appendChild(mk('p', '', `Passkey reset pending: every passkey will be removed on ${at}. Not you? Cancel it with one of your passkeys.`));
    banner.appendChild(button('Review', '', () => expand(true, true)));
  }
  function render() {
    summary();
    renderBanner();
    if (!groupsEl || body.hidden) return;
    groupsEl.replaceChildren();
    if (S.data === undefined && !S.error) { groupsEl.appendChild(mk('div', 'empty', 'Loading permissions…')); return; }
    if (!S.data) {
      groupsEl.appendChild(mk('div', 'empty', S.error));
      const retry = button('Retry', 'retry', () => load()); groupsEl.appendChild(retry);
      if (box) box.replaceChildren();
      return;
    }
    let section = '';
    S.data.groups.forEach(g => {
      if (g.section !== section) { section = g.section; groupsEl.appendChild(mk('h4', 'pgsec', section)); }
      groupsEl.appendChild(groupRow(g));
    });
    renderPasskeys();
  }

  // ---- disclosure, panel, sign-in ------------------------------------------------------------------
  function expand(open, remember) {
    body.hidden = !open;
    if (sum) sum.hidden = open;
    btn.setAttribute('aria-expanded', String(open));
    if (remember) store.set(OPEN_KEY, open ? '1' : '0');
    if (open && stale()) load(); else render();
  }
  btn.addEventListener('click', () => expand(body.hidden, true));
  function afterReauth() {
    let q; try { q = new URLSearchParams(window.location.search); } catch (_) { return; }
    const how = q.get('reauth');
    if (how !== 'done' && how !== 'stale') return;
    try { history.replaceState(null, '', window.location.pathname); } catch (_) {}
    Deck.open('approvals', { focus: true });
    expand(true, false);
    if (how === 'done') note('ok', 'Signed in again. For the next 5 minutes you can set up your first passkey or start a passkey reset here.');
    else note('bad', 'Google didn\'t ask you to sign in again, so this didn\'t count. Sign out of Google in this browser, then try again.');
  }
  async function ready() {
    S.signedIn = true; S.data = undefined; S.error = '';
    expand(store.get(OPEN_KEY) === '1', false);
    afterReauth();
    if (stale()) await load(); // once per sign-in: a pending passkey reset must be seen
    if (S.data && S.data.reset) Deck.open('approvals', { focus: false });
  }
  document.addEventListener('jarvis:ready', ready);
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'approvals' && d.open && stale()) load(); });
  const JC = window.JarvisConsole;
  if (JC && typeof JC.ready === 'function' && JC.ready()) ready();
})();
