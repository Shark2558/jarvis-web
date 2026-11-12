// src/jarvis/api/static/console-helpers.js -- R11 I0 (docs/plans/r11-free-helpers.md D19): the Helpers panel's
// frame. Builds the four sub-tabs inside #p-helpers .pbody (Today = Part A, Home = B, Nudges = C, Kitchen = D),
// shows the clock line from GET /v1/helpers, loads the stylesheet and the four parts' tab modules, and gives the
// parts ONE set of builders so every tab looks the same (existing tokens and components only: .btn, .bsw, .sfine).
// Each tab starts with the frame's own "paused" lines (parts[].paused: fixed templates, e.g. "Breach watching paused:
// your Email permission is set to Ask first."); the part draws below them, in its own box.
// Server strings reach the page through textContent only. No build step; CSP script-src 'self'; ASCII source.
// API for the parts: window.JarvisHelpers = {register(tab, {mount(host, H), refresh?(view)}), api, view, mk, row,
//   toggle, empty, note, section, txt}. A part never edits this file or another part's tab.
(() => {
  'use strict';
  const panel = document.getElementById('p-helpers');
  const host = panel && panel.querySelector('.pbody');
  if (!host) return;
  const TABS = [['today', 'Today'], ['house', 'Home'], ['nudges', 'Nudges'], ['kitchen', 'Kitchen']];
  const TAB_KEY = 'jarvis_helpers_tab';
  const OFFLINE = 'Can\u2019t reach JARVIS. Check your connection.';
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
  };
  const S = { tab: 'today', view: null, parts: {}, mounted: {}, loading: null };
  const strip = (v) => (window.JarvisText ? window.JarvisText.strip(v) : String(v));
  const txt = (v, max = 200) => (typeof v === 'string' ? strip(v).replace(/\s+/g, ' ').trim().slice(0, max) : '');
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const hasApi = () => !!(window.JarvisConsole && typeof window.JarvisConsole.api === 'function');
  const api = (path, opts) => window.JarvisConsole.api(path, opts);

  // ---- shared builders (the parts use only these and the existing components) ----------------------------
  function row(title, sub, actions) {
    const r = mk('div', 'hp-row');
    const t = mk('div', 'hp-txt');
    t.append(mk('b', '', txt(title, 120)));
    if (sub) t.append(mk('small', '', txt(sub, 200)));
    r.append(t);
    const a = mk('div', 'hp-acts');
    (actions || []).forEach((el) => a.append(el));
    if (a.childNodes.length) r.append(a);
    return r;
  }
  function toggle(label, on, change) {
    const b = mk('button', 'bsw');
    b.type = 'button';
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.setAttribute('aria-label', txt(label, 80));
    const track = mk('span', 'track'); track.append(mk('i'));
    const st = mk('span', 'st', on ? 'On' : 'Off');
    b.append(track, st);
    b.addEventListener('click', () => { if (typeof change === 'function') change(b.getAttribute('aria-pressed') !== 'true'); });
    return b;
  }
  const empty = (text) => mk('p', 'sfine hp-empty', txt(text, 240));
  function note(el, kind, text) {
    if (!el) return;
    el.className = 'sfine hp-note' + (kind ? ' ' + kind : '');
    el.textContent = txt(text, 240);
  }
  function section(title) {
    const s = mk('section', 'hp-sec');
    s.append(mk('h3', 'hp-h', txt(title, 60)));
    return s;
  }

  // ---- the tab strip -------------------------------------------------------------------------------------------
  const status = mk('p', 'sfine hp-status');
  const tabsEl = mk('div', 'hp-tabs');
  tabsEl.setAttribute('role', 'tablist');
  tabsEl.setAttribute('aria-label', 'Helpers');
  const panes = {};
  const bodies = {};
  const pauses = {};
  const buttons = {};
  TABS.forEach(([id, label]) => {
    const b = mk('button', 'hp-tab', label);
    b.type = 'button';
    b.id = 'hpt-' + id;
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-controls', 'hpp-' + id);
    b.addEventListener('click', () => choose(id, true));
    buttons[id] = b;
    tabsEl.append(b);
    const p = mk('div', 'hp-pane');
    p.id = 'hpp-' + id;
    p.setAttribute('role', 'tabpanel');
    p.setAttribute('aria-labelledby', b.id);
    p.tabIndex = 0;
    p.hidden = true;
    pauses[id] = mk('div', 'hp-paused');
    pauses[id].setAttribute('role', 'status');
    pauses[id].hidden = true;
    bodies[id] = mk('div', '');
    p.append(pauses[id], bodies[id]);
    panes[id] = p;
  });
  tabsEl.addEventListener('keydown', (e) => {
    const ids = TABS.map(([id]) => id);
    const at = ids.indexOf(S.tab);
    const next = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: ids.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    choose(ids[(next + ids.length) % ids.length], true);
    buttons[S.tab].focus();
  });
  host.append(status, tabsEl, ...TABS.map(([id]) => panes[id]));

  function choose(id, remember) {
    if (!panes[id]) id = 'today';
    S.tab = id;
    TABS.forEach(([t]) => {
      const on = t === id;
      buttons[t].setAttribute('aria-selected', on ? 'true' : 'false');
      buttons[t].tabIndex = on ? 0 : -1;
      panes[t].hidden = !on;
    });
    if (remember) store.set(TAB_KEY, id);
    mount(id);
    const part = S.parts[id];
    if (part && typeof part.refresh === 'function' && S.view) { try { part.refresh(S.view); } catch (_) {} }
  }
  function mount(id) {
    const part = S.parts[id];
    if (!part || S.mounted[id]) return;
    S.mounted[id] = true;
    try { part.mount(bodies[id], H); } catch (_) { bodies[id].append(empty('This tab couldn\u2019t load.')); }
  }
  function register(id, part) {
    if (!panes[id] || !part || typeof part.mount !== 'function' || S.parts[id]) return;
    S.parts[id] = part;
    if (id === S.tab) choose(id, false);
  }

  // ---- the clock line, the paused lines and the shared view (GET /v1/helpers) ---------------------------------
  function pausedLines(v) {
    const by = {};
    ((v && v.enabled !== false && Array.isArray(v.parts)) ? v.parts : []).forEach((p) => { if (p && pauses[p.name]) by[p.name] = p.paused; });
    TABS.forEach(([id]) => {
      const lines = (Array.isArray(by[id]) ? by[id] : []).map((x) => txt(x, 240)).filter(Boolean).slice(0, 3);
      pauses[id].replaceChildren(...lines.map((x) => mk('p', 'sfine', x)));
      pauses[id].hidden = !lines.length;
    });
  }
  function clockLine(v) {
    const meta = document.getElementById('helpersMeta');
    if (!v || v.enabled === false) {
      status.textContent = 'The helpers are off on this server.';
      if (meta) meta.textContent = 'Off';
      return;
    }
    const c = v.clock || {};
    const at = typeof c.last_run === 'string' ? new Date(c.last_run) : null;
    const hhmm = at && !isNaN(at) ? at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    status.textContent = c.stale
      ? 'Your 5-minute clock isn\u2019t running: reminders come only between 04:00 and 11:30.' + (hhmm ? ' Last run ' + hhmm + '.' : '')
      : 'Reminders are checked every 5 minutes. Last run ' + hhmm + '.';
    status.classList.toggle('warn', !!c.stale);
    if (meta) meta.textContent = c.stale ? 'Clock stopped' : 'Clock ' + hhmm;
  }
  async function load() {
    if (!hasApi()) return;
    if (S.loading) return S.loading;
    S.loading = (async () => {
      try {
        S.view = await api('/v1/helpers');
        clockLine(S.view);
        pausedLines(S.view);
        const part = S.parts[S.tab];
        if (part && typeof part.refresh === 'function') { try { part.refresh(S.view); } catch (_) {} }
      } catch (e) {
        status.textContent = e && e.name === 'TypeError' ? OFFLINE : 'Couldn\u2019t load the helpers.';
      } finally { S.loading = null; }
    })();
    return S.loading;
  }

  const H = { register, api, view: () => S.view, reload: load, mk, row, toggle, empty, note, section, txt };
  window.JarvisHelpers = H;
  choose(store.get(TAB_KEY) || 'today', false);

  // the stylesheet and the four parts' tabs (ES modules), loaded by this file only
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = '/static/console-helpers.css';
  document.head.append(css);
  const failed = (id) => () => { if (!S.parts[id]) bodies[id].append(empty('This tab couldn\u2019t load.')); };
  import('./console-helpers-today.js').catch(failed('today'));
  import('./console-helpers-house.js').catch(failed('house'));
  import('./console-helpers-nudges.js').catch(failed('nudges'));
  import('./console-helpers-kitchen.js').catch(failed('kitchen'));

  document.addEventListener('jarvis:panel', (e) => {
    const d = e.detail || {};
    if (d.id === 'helpers' && d.open) load();
  });
})();

// R11 I1 (plan D7, INTEGRATION-A 3.3): a UPI payment he approved, ONCE, under the approval's reply (kind 'upi' in
// ChatResponse.cards: the upi://pay link, its QR, code's own words). Checked field by field; textContent only; the
// QR is an SVG data URI (CSP img-src data:). Nothing is stored; the box goes away on Done or after 10 minutes.
// window.JarvisUpi = {card(cards) -> {link, qr, full} | null, render(row, cards)}; console.js calls render.
(() => {
  'use strict';
  const LINK = /^upi:\/\/pay\?[A-Za-z0-9%@._~=&-]{1,1000}$/;
  const QR = /^data:image\/svg\+xml;charset=utf-8,/;
  const SHOW_MS = 10 * 60 * 1000;
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };
  const words = (v) => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().slice(0, 300) : '');
  function card(cards) {
    const c = (Array.isArray(cards) ? cards : []).find((x) => x && x.kind === 'upi');
    if (!c || !LINK.test(String(c.link || '')) || !QR.test(String(c.qr || '')) || String(c.qr).length > 20000 || !words(c.words)) return null;
    return { link: c.link, qr: c.qr, full: words(c.words) };
  }
  function button(text, cls, onClick) {
    const b = mk('button', 'btn bact' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }
  function render(row, cards) {
    const p = card(cards);
    if (!row || !p) return null;
    const box = mk('div', 'fform');
    box.append(mk('p', 'sfine', p.full));
    const img = mk('img', '');
    img.alt = 'QR code of this UPI payment';
    img.width = 180; img.height = 180;
    img.src = p.qr;
    const acts = mk('div', 'hp-acts hp-wrap');
    acts.append(button('Open in UPI app', 'primary', () => { window.location.assign(p.link); }), button('Done', '', () => box.remove()));
    box.append(img, acts);
    row.append(box);
    setTimeout(() => box.remove(), SHOW_MS);
    return box;
  }
  window.JarvisUpi = Object.freeze({ card, render });
})();
