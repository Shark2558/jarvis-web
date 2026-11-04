// src/jarvis/api/static/console-family.js -- R1 D15: Integrations -> Family calendars. The owner lists
// the calendars family members have shared with him (a label he chooses plus the calendar address);
// JARVIS then shows them side by side, finds free time across them, and (only on a passkey card)
// adds an event to one that gave write access. No build step; CSP script-src 'self'; ASCII source
// with backslash-u escapes only; every server string reaches the page through textContent or an
// input's value (never markup); a field of the wrong type is dropped, never guessed. Transport is
// the console's api() (cookie + X-Requested-With, or the bearer token; 401 -> gate).
// API: GET /v1/family -> {configured:false} | {configured, members:[{id, name, calendar_id, access,
// can_write, added_at}], max_members, how_to}; POST /v1/family {name, calendar_id} -> the member, or
// {error, detail}; DELETE /v1/family/{id} -> {removed}. Loads when the Integrations panel opens.
(() => {
  'use strict';
  const MEMBER_ID = /^fam_[0-9a-f]{12}$/;
  const STALE_MS = 30 * 1000;
  const MAX_SHOWN = 20;
  const OFFLINE = 'Can\'t reach JARVIS. Check your connection.';
  const ACCESS = {
    freeBusyReader: 'busy times only',
    reader: 'can see events',
    writer: 'can add events',
    owner: 'can add events',
  };
  const S = { data: undefined, error: '', loadedAt: 0, loading: null, busy: false };
  let card = null, stateEl = null, bodyEl = null, noteEl = null;

  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);
  const emit = (name, detail) => { try { document.dispatchEvent(new CustomEvent(name, { detail })); } catch (_) {} };
  const log = (kind, text) => emit('jarvis:event', { kind, text, at: Date.now(), live: true });
  const quoted = (s) => '\u201c' + s + '\u201d';
  function detailOf(e) {
    if (e && e.name === 'TypeError') return OFFLINE;
    const m = e && typeof e.message === 'string' ? strip(e.message).trim() : '';
    return m && m.length <= 300 && !m.startsWith('[object') && !/^[a-z0-9_.-]+$/i.test(m) ? m : '';
  }

  /** GET /v1/family, checked field by field. null = not set up on this server. */
  function normal(raw) {
    const d = obj(raw);
    if (!d || d.configured !== true) return null;
    const seen = new Set();
    const members = arr(d.members).slice(0, MAX_SHOWN).map((m) => {
      const it = obj(m);
      if (!it || typeof it.id !== 'string' || !MEMBER_ID.test(it.id) || seen.has(it.id)) return null;
      seen.add(it.id);
      return { id: it.id, name: txt(it.name, 40) || '(no name)', address: txt(it.calendar_id, 254),
        access: Object.hasOwn(ACCESS, it.access) ? it.access : 'freeBusyReader' };
    }).filter(Boolean);
    const max = Number.isInteger(d.max_members) && d.max_members > 0 && d.max_members <= 50 ? d.max_members : 8;
    return { members, max, how: txt(d.how_to, 400) };
  }

  function build() {
    if (card) return true;
    const host = document.getElementById('integrations');
    if (!host || !host.parentNode) return false;
    card = mk('section', 'integ family'); card.id = 'familySet'; card.dataset.state = 'loading';
    card.setAttribute('aria-labelledby', 'familyHead');
    const head = mk('div', 'ihead');
    const title = mk('b', '', 'Family calendars'); title.id = 'familyHead';
    stateEl = mk('span', 'istate', 'Checking\u2026');
    head.append(title, stateEl);
    noteEl = mk('div', 'inote'); noteEl.id = 'familyNote'; noteEl.setAttribute('role', 'status'); noteEl.setAttribute('aria-live', 'polite'); noteEl.hidden = true;
    bodyEl = mk('div', 'ibody'); bodyEl.id = 'familyBody';
    card.append(head, bodyEl, noteEl);
    host.parentNode.insertBefore(card, host.nextSibling);
    return true;
  }
  function note(kind, text) {
    if (!noteEl) return;
    noteEl.className = 'inote' + (kind === 'bad' ? ' bad' : '');
    noteEl.textContent = text || '';
    noteEl.hidden = !text;
  }

  function memberRow(m) {
    const li = mk('li', 'fmember'); li.dataset.id = m.id;
    const t = mk('div', 'btxt');
    t.append(mk('b', '', m.name), mk('small', '', m.address + ' \u00b7 ' + ACCESS[m.access]));
    const rm = mk('button', 'btn bact', 'Remove'); rm.type = 'button';
    rm.setAttribute('aria-label', 'Remove ' + m.name);
    rm.addEventListener('click', () => askRemove(li, m, rm));
    li.append(t, rm);
    return li;
  }
  function askRemove(li, m, trigger) {
    if (li.querySelector('.confirm')) return;
    const box = mk('div', 'confirm'); box.setAttribute('role', 'alert');
    const no = mk('button', 'btn lift', 'Keep'); no.type = 'button';
    const yes = mk('button', 'btn danger lift', 'Remove'); yes.type = 'button';
    const keep = () => { box.remove(); trigger.focus(); };
    no.addEventListener('click', keep);
    box.addEventListener('keydown', (e) => { if (e.key !== 'Escape' || e.isComposing) return; e.preventDefault(); keep(); });
    yes.addEventListener('click', () => remove(m));
    box.append(mk('span', '', 'Stop showing ' + quoted(m.name) + '? Their calendar stays theirs; JARVIS just stops reading it.'), no, yes);
    li.append(box); no.focus();
  }
  async function remove(m) {
    if (!hasApi() || S.busy) return;
    S.busy = true; render();
    try {
      await api('/v1/family/' + encodeURIComponent(m.id), { method: 'DELETE' });
      note('ok', quoted(m.name) + ' removed.'); log('info', 'Family calendar removed');
      S.data = normal(await api('/v1/family'));
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t remove it. Please try again.');
    } finally { S.busy = false; S.loadedAt = Date.now(); render(); }
  }

  function addForm(d) {
    const form = mk('form', 'fadd'); form.id = 'familyAdd'; form.noValidate = true;
    const field = (id, label, ph) => {
      const w = mk('div', 'ffield'), l = mk('label', 'dlbl', label); l.htmlFor = id;
      const i = mk('input', 'dinput'); i.id = id; i.type = 'text'; i.placeholder = ph; i.spellcheck = false;
      i.setAttribute('autocomplete', 'off'); i.maxLength = id === 'familyName' ? 40 : 254;
      w.append(l, i); return [w, i];
    };
    const [nw, name] = field('familyName', 'Their name (your label)', 'Anjali');
    const [aw, addr] = field('familyAddr', 'Calendar address', 'anjali@gmail.com');
    const go = mk('button', 'btn primary lift bact', 'Add'); go.type = 'submit'; go.id = 'familyAddBtn';
    if (S.busy) go.disabled = true;
    form.addEventListener('submit', (e) => { e.preventDefault(); add(name.value, addr.value); });
    form.append(nw, aw, go);
    form.append(mk('p', 'fine', 'JARVIS reads only calendars shared with your Google account. The titles it reads go to Claude when you ask about them.'));
    return form;
  }
  async function add(name, address) {
    const n = txt(name, 40), a = txt(address, 254).toLowerCase();
    if (!hasApi() || S.busy) return;
    if (!n || !a) { note('bad', 'Enter a name and the calendar address.'); return; }
    S.busy = true; render();
    try {
      await api('/v1/family', { method: 'POST', body: { name: n, calendar_id: a } });
      note('ok', quoted(n) + ' added.'); log('info', 'Family calendar added');
      S.data = normal(await api('/v1/family'));
    } catch (e) {
      if (e && e.status === 401) return;
      note('bad', detailOf(e) || 'Couldn\'t add it. Please try again.');
    } finally { S.busy = false; S.loadedAt = Date.now(); render(); }
  }

  function render() {
    if (!card) return;
    bodyEl.replaceChildren();
    const d = S.data;
    let st = 'linked', word = 'Ready';
    if (S.error) { st = 'error'; word = 'Unknown'; } else if (d === undefined) { st = 'loading'; word = 'Checking\u2026'; } else if (d === null) { st = 'unavailable'; word = 'Not available'; }
    card.dataset.state = st; stateEl.textContent = word;
    if (st === 'error') { bodyEl.append(mk('p', 'warn', 'Couldn\'t load your family calendars. ' + S.error)); const r = mk('button', 'btn bact', 'Retry'); r.type = 'button'; r.addEventListener('click', () => load(true)); bodyEl.append(r); return; }
    if (st === 'loading') { bodyEl.append(mk('p', '', 'Checking\u2026')); return; }
    if (st === 'unavailable') { bodyEl.append(mk('p', 'fine', 'Not available in this setup. Family calendars need the Google link on this server.')); return; }
    if (!d.members.length) bodyEl.append(mk('p', '', 'No family calendars yet. Add one to see everyone\'s day together and find time that suits all of you.'));
    else { const ul = mk('ul', 'fmembers'); d.members.forEach((m) => ul.append(memberRow(m))); bodyEl.append(ul); }
    if (d.members.length >= d.max) bodyEl.append(mk('p', 'fine', 'You have added the most calendars allowed (' + d.max + '). Remove one to add another.'));
    else bodyEl.append(addForm(d));
    if (d.how) bodyEl.append(mk('p', 'fine fhow', d.how));
  }

  function load(force) {
    if (!hasApi() || !build()) return Promise.resolve();
    if (S.loading) return S.loading;
    if (!force && S.data !== undefined && !S.error && Date.now() - S.loadedAt < STALE_MS) return Promise.resolve();
    S.loading = (async () => {
      try { S.data = normal(await api('/v1/family')); S.error = ''; } catch (e) {
        if (e && e.status === 401) return;
        if (e && e.status === 404) { S.data = null; S.error = ''; } else { S.error = detailOf(e) || 'Please try again.'; }
      } finally { S.loadedAt = Date.now(); S.loading = null; render(); }
    })();
    return S.loading;
  }

  const integOpen = () => !!(window.JarvisDeck && typeof window.JarvisDeck.isOpen === 'function' && window.JarvisDeck.isOpen('integrations'));
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'integrations' && d.open) load(false); });
  document.addEventListener('jarvis:ready', () => { if (integOpen()) load(false); });
  const C = window.JarvisConsole;
  if (C && typeof C.ready === 'function' && C.ready() && integOpen()) load(false);

  window.JarvisFamily = Object.freeze({ refresh: () => load(true), normal });
})();
