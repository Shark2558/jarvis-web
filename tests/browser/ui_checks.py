# tests/browser/ui_checks.py -- shared by tests/browser/test_ui_audit.py and scripts/ui_snapshots.py:
# the page.route mocks for the R4 panels and the in-page DOM checks (JavaScript string).
# ruff: noqa: E501 -- DOM_CHECKS_JS is JavaScript evaluated in the page
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Route

PANELS = (
    "activity approvals brief chat connectors construct faces history home integrations media "
    "memory notes people privacy things vault vitals voice"
).split()
# A selector that shows the panel has painted its data (best effort; a miss is never fatal).
READY: dict[str, str] = {
    "vitals": "#vitals-board .vt-row, #vitals-board .trow",
    "integrations": "#systemsCard .sysrow, #systemsCard .event",
    "connectors": "#p-connectors .integ .istate",
    "people": "#peopleCard .pname",
}
NOW = int(time.time())

# ================================================================================================
# MOCKS — page.route fulfilments so the R4 panels show realistic states. Shapes follow the server:
#   /v1/vitals                -> src/jarvis/vitals/api.py + models.py (Board.to_json)
#   /v1/health, /health/run   -> src/jarvis/health/api.py + tools.view
#   /v1/connectors            -> src/jarvis/photos/api.py `_status` (console-connectors.js reads it)
#   /v1/settings/brain-mode   -> src/jarvis/people/routes.py (MEANING["ai"])
#   /v1/people/last           -> src/jarvis/people/routes.py `last` ({dossier: _view(d)})
#   /v1/integrations          -> Google linked (the well-styled reference card; test_console LINKED)
# ================================================================================================


def _vitals_item(**kw: Any) -> dict[str, Any]:
    base = {
        "kind": "key",
        "source": "manual",
        "limit": None,
        "used": None,
        "unit": "",
        "reset_at": None,
        "expires_at": None,
        "note": "",
        "status": "ok",
        "percent": None,
        "reason": "",
    }
    return {**base, **kw}


MOCK_VITALS: dict[str, Any] = {
    "overall": "red",
    "items": [
        _vitals_item(
            id="anthropic",
            label="Anthropic API",
            kind="quota",
            source="auto",
            limit=500,
            used=412,
            unit="₹",
            percent=82.4,
            status="amber",
            reason="is at 82% of its limit",
            reset_at="2026-12-01T00:00:00+05:30",
        ),
        _vitals_item(
            id="openai-key",
            label="OpenAI key",
            kind="key",
            status="red",
            expires_at="2026-11-08T23:59:59+05:30",
            reason="has expired",
            note="Rotate it in the OpenAI dashboard, then update the server env.",
        ),
        _vitals_item(
            id="google-maps",
            label="Google Maps",
            kind="quota",
            source="auto",
            limit=10000,
            used=1240,
            unit="calls",
            percent=12.4,
            status="ok",
            reset_at="2026-12-01T00:00:00+05:30",
        ),
        _vitals_item(
            id="elevenlabs",
            label="ElevenLabs characters",
            kind="allowance",
            limit=100000,
            used=91000,
            unit="chars",
            percent=91,
            status="amber",
            reason="is at 91% of its limit",
            reset_at="2026-11-30T23:59:59+05:30",
        ),
        _vitals_item(
            id="render-bill",
            label="Render hosting",
            kind="billing",
            limit=1500,
            used=1500,
            unit="₹",
            percent=100,
            status="red",
            reason="has reached its limit",
            note="Billed on the 1st of each month.",
        ),
        _vitals_item(
            id="drive-storage",
            label="Google Drive storage",
            kind="storage",
            source="auto",
            limit=15,
            unit="GB",
            status="unknown",
            reason="can't be read now",
        ),
        _vitals_item(
            id="github-pat",
            label="GitHub token",
            kind="key",
            status="amber",
            expires_at="2026-11-20T23:59:59+05:30",
            reason="expires in 10 days",
        ),
    ],
    "spend": {"used_inr": 412.5, "limit_inr": 500, "text": "₹413 of ₹500 this month"},
}
MOCK_VITALS_503 = {"detail": "Vitals is not available on this server."}

MOCK_HEALTH: dict[str, Any] = {
    "overall": "down",
    "spoken": "Four of five systems are fine. The home bridge is down.",
    "checked_at": NOW - 90,
    "systems": [
        {
            "key": "brain",
            "name": "the AI brain",
            "status": "ok",
            "reason": "Answered in 820 ms",
            "at": NOW - 90,
        },
        {"key": "redis", "name": "Redis", "status": "ok", "reason": "Ping 3 ms", "at": NOW - 90},
        {
            "key": "google",
            "name": "Google",
            "status": "degraded",
            "reason": "Calendar answered slowly (2.4 s)",
            "at": NOW - 90,
        },
        {
            "key": "home",
            "name": "the home bridge",
            "status": "down",
            "reason": "No heartbeat for 14 minutes",
            "at": NOW - 90,
        },
        {
            "key": "web",
            "name": "web search",
            "status": "ok",
            "reason": "Search answered in 410 ms",
            "at": NOW - 90,
        },
    ],
}

MOCK_CONNECTORS: dict[str, Any] = {
    "github": {"connected": True, "login": "shark2558"},
    "youtube": {"connected": True, "reason": ""},
    "photos": {"connected": False, "reason": "not_granted"},
    "statements": {
        "adult": "I agree that JARVIS may recognise my face on the home cameras.",
        "child": "As this child's parent or guardian, I agree that JARVIS may recognise them.",
        "version": "fc1",
    },
}

MOCK_BRAIN_MODE = {"mode": "ai", "meaning": "AI on: JARVIS reasons and writes with the model."}

MOCK_PEOPLE_LAST: dict[str, Any] = {
    "dossier": {
        "name": "Satya Nadella",
        "context": "CEO, Microsoft",
        "profiles": [
            {
                "platform": "LinkedIn",
                "url": "https://www.linkedin.com/in/satyanadella",
                "title": "Satya Nadella - Chairman and CEO - Microsoft",
            },
            {
                "platform": "Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Satya_Nadella",
                "title": "Satya Nadella - Wikipedia",
            },
            {"platform": "X", "url": "https://x.com/satyanadella", "title": "@satyanadella"},
        ],
        "findings": [
            {
                "title": "Leadership",
                "domain": "news.microsoft.com",
                "snippet": "Satya Nadella is Chairman and Chief Executive Officer of Microsoft.",
            },
            {
                "title": "Profile",
                "domain": "en.wikipedia.org",
                "snippet": "Indian-American business executive, CEO of Microsoft since 2014.",
            },
        ],
        "summary": "Chairman and CEO of Microsoft since 2014; previously led its cloud and "
        "enterprise group. Public sources describe a focus on cloud and AI.",
        "spoken": "Satya Nadella is the chairman and CEO of Microsoft.",
        "ambiguous": False,
        "no_ai": False,
        "note": "",
    }
}

MOCK_INTEGRATIONS: dict[str, Any] = {
    "google": {
        "connected": True,
        "email": "owner@example.com",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "expires_at": "2026-12-01T12:00:00Z",
        "needs_reconnect": False,
    }
}


def _json(status: int, body: Any) -> Callable[[Route], None]:
    def handler(route: Route) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    return handler


def _get_only(status: int, body: Any) -> Callable[[Route], None]:
    """Fulfil GETs; anything else (a POST to brain-mode, say) goes to the real server."""
    fulfil = _json(status, body)

    def handler(route: Route) -> None:
        if route.request.method == "GET":
            fulfil(route)
        else:
            route.continue_()

    return handler


def install_mocks(page: Page, *, vitals_503: bool = False) -> None:
    vitals = (503, MOCK_VITALS_503) if vitals_503 else (200, MOCK_VITALS)
    page.route("**/v1/vitals", _get_only(*vitals))
    page.route("**/v1/health", _get_only(200, MOCK_HEALTH))
    page.route("**/v1/health/run", _json(200, MOCK_HEALTH))
    page.route("**/v1/connectors", _get_only(200, MOCK_CONNECTORS))
    page.route("**/v1/settings/brain-mode", _get_only(200, MOCK_BRAIN_MODE))
    page.route("**/v1/people/last", _get_only(200, MOCK_PEOPLE_LAST))
    page.route("**/v1/integrations", _get_only(200, MOCK_INTEGRATIONS))


# ================================================================================================
# DOM checks — run in the page against one root element. Pure reads; returns plain JSON.
# ================================================================================================
DOM_CHECKS_JS = r"""
(sel) => {
  const root = document.querySelector(sel);
  if (!root) return { missing: true };
  const CAP = 25;
  const cs = (e) => getComputedStyle(e);
  // rect: the full layout box (checks cover content scrolled out of view too). prect: the box as
  // painted, clipped by every scrolling / overflow-hidden ancestor up to the root, so a row
  // scrolled out of the panel body never "overlaps" the title bar (used by the overlap check).
  const rect = (e) => e.getBoundingClientRect();
  const prect = (e) => {
    const r = e.getBoundingClientRect();
    let L = r.left, T = r.top, R = r.right, B = r.bottom;
    for (let n = e.parentElement; n && n !== document.documentElement; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
        const c = n.getBoundingClientRect();
        L = Math.max(L, c.left); T = Math.max(T, c.top); R = Math.min(R, c.right); B = Math.min(B, c.bottom);
      }
      if (n === root) break;
    }
    return { left: L, top: T, right: R, bottom: B, width: Math.max(0, R - L), height: Math.max(0, B - T) };
  };
  const inClosedDetails = (e) => { const d = e.closest('details:not([open])'); return !!d && !e.closest('summary') && e !== d; };
  const vis = (e) => {
    if (inClosedDetails(e) || e.closest('.sr-only')) return false;
    const r = rect(e); if (r.width < 1 || r.height < 1) return false;
    const s = cs(e); return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05;
  };
  const first = (stack) => (stack || '').split(',')[0].trim().replace(/^["']|["']$/g, '').toLowerCase();
  const rs = cs(document.documentElement);
  const fam = {};
  ['--font', '--tech', '--hud', '--disp', '--mono'].forEach((v) => { fam[v] = first(rs.getPropertyValue(v)); });
  const famName = (f) => { const x = first(f); for (const k in fam) if (fam[k] === x) return k; return x; };
  const desc = (e) => {
    let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id;
    if (e.classList.length) s += '.' + [...e.classList].join('.');
    if (e.tagName === 'INPUT') s += '[type=' + e.type + ']';
    return s;
  };
  const path = (e) => { const p = []; let n = e; while (n && n !== root && p.length < 3) { p.unshift(desc(n)); n = n.parentElement; } return p.join(' > '); };
  const own = (e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').replace(/\s+/g, ' ').trim();
  const words = (e) => (own(e) || e.value || e.placeholder || e.getAttribute('aria-label') || '').slice(0, 48);
  const INTER = 'button, input:not([type=hidden]), select, textarea, a[href], [role=button], summary';
  const els = [...root.querySelectorAll('*')].filter(vis);
  const inter = els.filter((e) => e.matches(INTER));
  const texty = els.filter((e) => own(e) || e.matches(INTER));
  const out = { overlaps: [], offTheme: [], systemFont: [], defaults: [], runTogether: [], overflow: [],
                contrast: [], smallTargets: [], unlabelled: [], hscroll: null };

  // 1. interactive elements overlapping other interactive or text elements
  const seen = new Set();
  for (const a of inter) {
    const ra = prect(a);
    for (const b of texty) {
      if (a === b || a.contains(b) || b.contains(a)) continue;
      const rb = prect(b);
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (w <= 1 || h <= 1) continue;
      const key = [path(a), path(b)].sort().join('|');
      if (seen.has(key)) continue; seen.add(key);
      if (out.overlaps.length < CAP) out.overlaps.push({ a: path(a), aText: words(a), b: path(b), bText: words(b), w: Math.round(w), h: Math.round(h) });
    }
  }

  // 2. fonts: off-theme families, and controls/headings left in the plain body font
  for (const e of texty) {
    const f = cs(e).fontFamily, n = famName(f);
    if (!n.startsWith('--')) { if (out.offTheme.length < CAP) out.offTheme.push({ el: path(e), text: words(e), family: f.slice(0, 60) }); continue; }
    if (n === '--font' && own(e) && e.matches('button, select, label, h1, h2, h3, h4, th, legend') && out.systemFont.length < CAP)
      out.systemFont.push({ el: path(e), text: words(e), size: cs(e).fontSize, weight: cs(e).fontWeight });
  }

  // 3. browser-default looking controls, headings and lists
  const probe = (v) => { const d = document.createElement('i'); d.style.background = v; document.body.appendChild(d); const c = cs(d).backgroundColor; d.remove(); return c; };
  const tokenBgs = new Set(['var(--well)', 'var(--well-2)', 'var(--tint)', 'var(--panel-solid)', 'var(--accent)', 'transparent', '#B42318'].map(probe));
  tokenBgs.add('rgba(0, 0, 0, 0)');
  for (const e of els) {
    const s = cs(e);
    if (e.matches('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=color]), select, textarea, button')) {
      const bad = [];
      if (s.borderTopStyle === 'inset' || s.borderTopStyle === 'outset') bad.push('border ' + s.borderTopStyle);
      if (!tokenBgs.has(s.backgroundColor)) bad.push('bg ' + s.backgroundColor);
      if (parseFloat(s.borderTopLeftRadius) === 0 && s.borderTopStyle !== 'none') bad.push('square corners');
      if (e.tagName === 'BUTTON' && !e.className) bad.push('no class');
      if (bad.length && out.defaults.length < CAP) out.defaults.push({ el: path(e), text: words(e), why: bad.join(', '), h: Math.round(rect(e).height), font: famName(s.fontFamily) + ' ' + s.fontSize });
    } else if (/^H[1-6]$/.test(e.tagName) && Math.abs(parseFloat(s.marginTop) - parseFloat(s.fontSize)) < 0.6 && parseFloat(s.marginTop) > 8) {
      if (out.defaults.length < CAP) out.defaults.push({ el: path(e), text: words(e), why: 'browser-default heading (margin 1em, ' + s.fontSize + ' ' + famName(s.fontFamily) + ')' });
    } else if ((e.tagName === 'UL' || e.tagName === 'OL') && s.listStyleType !== 'none' && parseFloat(s.paddingLeft) >= 39) {
      if (out.defaults.length < CAP) out.defaults.push({ el: path(e), why: 'browser-default list (' + s.listStyleType + ' bullets, ' + s.paddingLeft + ' indent)' });
    }
  }

  // 4. run-together: neighbouring text elements on one line with < 3px between and no space
  for (const p of els) {
    const kids = [...p.childNodes];
    for (let i = 1; i < kids.length; i++) {
      const a = kids[i - 1], b = kids[i];
      if (a.nodeType !== 1 || b.nodeType !== 1 || !vis(a) || !vis(b)) continue;
      if (!(a.textContent || '').trim() || !(b.textContent || '').trim()) continue;
      const ra = rect(a), rb = rect(b);
      const sameLine = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > Math.min(ra.height, rb.height) * 0.5;
      const gap = rb.left - ra.right;
      if (sameLine && gap > -1 && gap < 3 && out.runTogether.length < CAP)
        out.runTogether.push({ parent: path(p), text: (a.textContent.trim().slice(0, 30) + '|' + b.textContent.trim().slice(0, 30)), gap: Math.round(gap * 10) / 10 });
    }
  }

  // 5. overflow: a child escaping a bordered/filled box with visible overflow; clipped text
  const boxy = (s) => parseFloat(s.borderTopWidth) > 0 || (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== 'transparent');
  for (const e of els) {
    const s = cs(e);
    if (boxy(s) && s.overflowX === 'visible' && s.overflowY === 'visible' && e !== root) {
      const r = rect(e);
      for (const c of e.children) {
        if (!vis(c) || cs(c).position === 'absolute' || cs(c).position === 'fixed') continue;
        const k = rect(c), dx = Math.max(r.left - k.left, k.right - r.right), dy = Math.max(r.top - k.top, k.bottom - r.bottom);
        if ((dx > 2 || dy > 2) && out.overflow.length < CAP) out.overflow.push({ box: path(e), child: desc(c), text: words(c), dx: Math.round(dx), dy: Math.round(dy) });
      }
    }
    if (own(e) && (s.overflowX === 'hidden' || s.overflowX === 'clip') && e.scrollWidth > e.clientWidth + 1 && out.overflow.length < CAP)
      out.overflow.push({ box: path(e), text: words(e), clipped: s.textOverflow === 'ellipsis' ? 'ellipsis' : 'hard clip', need: e.scrollWidth, have: e.clientWidth });
  }
  const body = root.querySelector('.pbody') || root;
  if (body.scrollWidth > body.clientWidth + 1) out.overflow.push({ box: desc(body), why: 'horizontal scroll inside the panel', need: body.scrollWidth, have: body.clientWidth });
  out.hscroll = document.documentElement.scrollWidth > window.innerWidth ? [document.documentElement.scrollWidth, window.innerWidth] : null;

  // 6. contrast of own text against the composited background (gradients ignored)
  const parse = (c) => {
    let m = c.match(/rgba?\(([^)]+)\)/);
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = c.match(/color\(srgb ([^)]+)\)/);
    if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return null;
  };
  const over = (top, under) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat([1]); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const pageBg = parse(cs(document.body).backgroundColor) || [0, 0, 0, 1];
  const bgOf = (e) => {
    const stack = []; let n = e;
    while (n && n.nodeType === 1) { const c = parse(cs(n).backgroundColor); if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; } n = n.parentElement; }
    let bg = pageBg; for (let i = stack.length - 1; i >= 0; i--) bg = over(stack[i], bg); return bg;
  };
  for (const e of texty) {
    if (!own(e) || e.matches('input, select, textarea')) continue;
    const s = cs(e), fg0 = parse(s.color); if (!fg0) continue;
    const bg = bgOf(e), fg = over(fg0, bg), L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const px = parseFloat(s.fontSize), large = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700);
    const opacity = parseFloat(s.opacity);
    if (ratio < (large ? 3 : 4.5) && out.contrast.length < CAP) out.contrast.push({ el: path(e), text: words(e), ratio: Math.round(ratio * 100) / 100, size: s.fontSize, opacity });
  }

  // 7. targets below 24x24 (WCAG 2.2 web-target-size); 44 on a phone-width viewport
  const min = window.innerWidth < 900 ? 44 : 24;
  for (const e of inter) {
    if (e.matches('input[type=checkbox], input[type=radio]')) continue;
    const r = rect(e);
    if ((r.width < min || r.height < min) && out.smallTargets.length < CAP) out.smallTargets.push({ el: path(e), text: words(e), w: Math.round(r.width), h: Math.round(r.height), min });
  }

  // 8. controls without a programmatic or visible label (placeholder-only counts as unlabelled)
  for (const e of inter.filter((x) => x.matches('input:not([type=hidden]), select, textarea'))) {
    const hasFor = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
    const wrap = e.closest('label');
    const visible = hasFor || (wrap && own(wrap)) || (wrap && [...wrap.children].some((c) => c !== e && (c.textContent || '').trim()));
    let order = '';
    if (wrap) {
      const txt = [...wrap.childNodes].findIndex((n) => n !== e && (n.textContent || '').trim());
      const pos = [...wrap.childNodes].indexOf(e);
      if (txt > pos) order = 'label text after the control';
      const rw = wrap.querySelector('span'), re = rect(e);
      if (rw && rw !== e) { const rl = rect(rw); if (Math.abs(rl.top - re.top) < 6 && rl.right <= re.left + 2) order = order || 'label inline left of control'; else if (rl.bottom <= re.top + 2) order = order || 'label above control'; }
    }
    if ((!visible || order === 'label text after the control') && out.unlabelled.length < CAP)
      out.unlabelled.push({ el: path(e), placeholder: e.placeholder || '', aria: e.getAttribute('aria-label') || '', visibleLabel: !!visible, order });
  }
  return out;
}
"""


STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"


def _css_handler(body: str) -> Callable[[Route], None]:
    def handler(route: Route) -> None:
        route.fulfill(status=200, content_type="text/css", body=body)

    return handler


def unlinked_css() -> list[str]:
    """Stylesheets in the static folder that console.html does not link yet (the integrator links them)."""
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    return sorted(p.name for p in STATIC.glob("console-*.css") if f"/static/{p.name}" not in html)


def inject_unlinked_css(page: Page) -> list[str]:
    """Serve and apply those stylesheets (the /static allow-list in api/console.py is also the integrator's).

    Once console.html links them, nothing is injected and the page is judged exactly as shipped.
    """
    names = unlinked_css()
    for name in names:
        body = (STATIC / name).read_text(encoding="utf-8")
        page.route(f"**/static/{name}", _css_handler(body))
        page.add_style_tag(url=f"/static/{name}")
    return names
