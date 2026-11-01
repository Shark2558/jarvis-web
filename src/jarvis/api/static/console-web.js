// src/jarvis/api/static/console-web.js — slice 10 B (docs/plans/phase2-slice10-tools-wave.md §B):
// the "Sources" row under a reply that cited web results, and the Vitals line "Web search: N of 900
// this month". No build step; CSP script-src 'self'; every server string reaches the DOM through
// textContent or an attribute, never markup.
//   window.JarvisSources  render(row, sources) → the row's Sources element (or null): numbered link
//     chips, https only (anything else is dropped), the host as the browser's URL parser gives it
//     (punycode for an IDN, so a look-alike name can't pass as another), "www." dropped,
//     target=_blank with rel="noopener noreferrer nofollow" and no referrer. console.js calls it for
//     a fresh reply (ChatResponse.sources) and for each restored turn (Turn.sources).
//   Vitals: GET /v1/web/usage → {configured:false} | {configured, used, limit, reached, unreadable};
//     loaded on jarvis:ready, when Vitals opens and after a reply that used tools. ₹0, never a dollar sign.
(() => {
  'use strict';
  const MAX_SOURCES = 20;
  const MAX_URL = 2048;
  const TITLE_MAX = 200;
  const REL = 'noopener noreferrer nofollow';
  const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
  const $ = (id) => document.getElementById(id);

  /** A URL object for an https address without user info, or null. */
  function safeUrl(raw) {
    if (typeof raw !== 'string' || !raw || raw.length > MAX_URL) return null;
    let u;
    try { u = new URL(raw); } catch (_) { return null; }
    if (u.protocol !== 'https:' || u.username || u.password || !u.hostname.includes('.')) return null;
    return u;
  }
  function domainOf(u) { const h = u.hostname; return h.startsWith('www.') ? h.slice(4) : h; }

  /** ChatResponse.sources / Turn.sources, checked field by field; anything odd is dropped. */
  function normal(list) {
    const seen = new Set();
    return (Array.isArray(list) ? list : []).slice(0, MAX_SOURCES).map((s) => {
      if (!s || typeof s !== 'object') return null;
      const n = Number.isInteger(s.n) && s.n > 0 && s.n < 1000 ? s.n : null;
      const u = safeUrl(s.url);
      if (n === null || !u || seen.has(n)) return null;
      seen.add(n);
      const title = typeof s.title === 'string' ? s.title.replace(INVISIBLE, '').replace(/\s+/g, ' ').trim().slice(0, TITLE_MAX) : '';
      return { n, href: u.href, domain: domainOf(u), title };
    }).filter(Boolean).sort((a, b) => a.n - b.n);
  }

  function render(row, list) {
    const items = normal(list);
    if (!row || !items.length) return null;
    const box = document.createElement('div');
    box.className = 'wsources';
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Sources');
    const label = document.createElement('span');
    label.className = 'wslabel';
    label.textContent = 'Sources';
    box.appendChild(label);
    items.forEach((s) => {
      const a = document.createElement('a');
      a.className = 'wsrc';
      a.href = s.href;
      a.target = '_blank';
      a.rel = REL;
      a.referrerPolicy = 'no-referrer';
      a.title = s.title ? `${s.title} · ${s.domain}` : s.domain;
      a.setAttribute('aria-label', `Source ${s.n}: ${s.title || s.domain}, ${s.domain} (opens in a new tab)`);
      const num = document.createElement('b');
      num.textContent = String(s.n);
      const dom = document.createElement('span');
      dom.textContent = s.domain;
      a.append(num, dom);
      box.appendChild(a);
    });
    row.appendChild(box);
    return box;
  }

  // ---- Vitals: "Web search: N of 900 this month" ----------------------------------------------
  function line(r) {
    if (!r || typeof r !== 'object') return '—';
    if (r.configured !== true) return 'Not set up';
    if (r.unreadable === true) return 'Count unavailable';
    const used = Number.isInteger(r.used) && r.used >= 0 ? r.used : null;
    const limit = Number.isInteger(r.limit) && r.limit > 0 ? r.limit : null;
    if (used === null || limit === null) return '—';
    return `${used} of ${limit} this month` + (r.reached === true ? ' · paused until the 1st' : '');
  }
  let loading = false;
  async function refresh() {
    const el = $('sWeb'), C = window.JarvisConsole;
    if (!el || !C || typeof C.api !== 'function' || loading) return;
    loading = true;
    try {
      const r = await C.api('/v1/web/usage');
      el.textContent = line(r);
      el.title = r && r.configured === true
        ? 'Free web searches (Tavily). JARVIS stops at the monthly allowance, before the free credits run out: ₹0.'
        : 'Web search is not set up: no Tavily key on this server.';
    } catch (e) {
      if (!e || e.status !== 401) { el.textContent = e && e.status === 404 ? 'Not available' : '—'; el.title = ''; }
    } finally { loading = false; }
  }
  document.addEventListener('jarvis:ready', () => { refresh(); });
  document.addEventListener('jarvis:panel', (e) => { const d = e.detail || {}; if (d.id === 'vitals' && d.open) refresh(); });
  document.addEventListener('jarvis:reply', (e) => { const d = e.detail || {}; if (d.tools > 0) refresh(); });
  if (window.JarvisConsole && typeof window.JarvisConsole.ready === 'function' && window.JarvisConsole.ready()) refresh();

  window.JarvisSources = Object.freeze({ render, normal, line });
})();
