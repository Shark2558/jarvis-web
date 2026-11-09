# scripts/ui_snapshots.py — repeatable screenshots of every console panel, for UI audits.
# ruff: noqa: E501 -- only DOM_CHECKS_JS (a JavaScript string evaluated in the page) has long lines
"""Start the real app (mock brain, in-memory store, bearer-token auth — exactly like
tests/browser/conftest.py `server_url`), sign in like tests/browser/test_console.py `Console.open`,
and capture, for DESKTOP 1440x900 and PHONE 390x844 on the night and day surfaces:

  * the whole viewport and the top bar (`header.topbar`);
  * every panel (`#p-<id>`), plus extra shots when its body scrolls;
  * extra states: Vitals with the "Track a key" form open, Vitals answering 503 (night only).

R4 panels get realistic data from `page.route` fulfilments (MOCKS below). Each panel also gets DOM
checks run in the page (overlapping interactive elements, off-theme fonts, browser-default
controls, run-together text, overflow, contrast, small targets); the findings go to checks.json and
a summary into index.md beside the PNGs.

Usage (from the repo root; Chromium is pre-installed — never `playwright install`):
    /tmp/venv-c/bin/python scripts/ui_snapshots.py --out /home/claude/ui-audit/before
Exit status: 0 when every capture worked and no uncaught page error happened, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, Route, sync_playwright

log = logging.getLogger("ui_snapshots")

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ui-snapshots-token-not-a-secret"
START_TIMEOUT_S = 30
SETTLE_MS = 700  # panelIn (.22s) + rise (.4s) animations, then a margin
WAIT_MS = 5000  # per readiness selector; a miss is logged, never fatal
MAX_SCROLL_SHOTS = 4

VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 900},
    "phone": {"width": 390, "height": 844},
}
SURFACES = ("night", "day")
PANELS = (
    "activity approvals brief chat connectors construct faces history home integrations media "
    "memory notes people privacy things vault vitals voice"
).split()
# A selector that shows the panel has painted its data (best effort).
READY: dict[str, str] = {
    "vitals": "#vitals-board .vt-row",
    "integrations": "#systemsCard .sysrow",
    "connectors": "#p-connectors .crow .chip",
    "people": "#peopleCard h3",
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


# ================================================================================================
# server + browser plumbing
# ================================================================================================
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthy(url: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"jarvis serve exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError("jarvis serve did not become healthy in time")


@contextmanager
def serve() -> Iterator[str]:
    """The real app as a subprocess, with the same env as tests/browser/conftest.py."""
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token",
        "JARVIS_API_TOKEN": TOKEN,
        "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0",
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    cmd = [sys.executable, "-m", "jarvis.cli", "serve", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(url, proc)
    except RuntimeError:
        proc.kill()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(f"server failed to start:\n{err}") from None
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@dataclass
class Run:
    out: Path
    shots: list[tuple[str, str]] = field(default_factory=list)  # (group, file name)
    checks: dict[str, Any] = field(default_factory=dict)
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class Console:
    """One signed-in console page (same steps as tests/browser/test_console.py `Console`)."""

    def __init__(self, browser: Browser, url: str, vp: str, surface: str, run: Run) -> None:
        self.url, self.vp, self.surface, self.run = url, vp, surface, run
        self.tag = f"{vp}-{surface}"
        self.ctx = browser.new_context(viewport=VIEWPORTS[vp], device_scale_factor=1)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: run.page_errors.append(f"[{self.tag}] {e}"))
        self.page.on("console", self._on_console)

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            where = msg.location.get("url", "") if msg.location else ""
            self.run.console_errors.append(f"[{self.tag}] {msg.text} @ {where}")

    def open(self) -> None:
        self.page.goto(self.url + "/")
        self.page.locator("#tokIn, #welcome").first.wait_for()
        gate = self.page.locator("#tokIn")
        if gate.count():
            gate.fill(TOKEN)
            self.page.locator("#tokBtn").click()
        self.page.locator("#welcome").wait_for()
        if self.surface == "day":  # the Appearance menu, as test_switching_night_to_day does
            self.page.locator("#themeBtn").click()
            self.page.locator('label[for="jx-s-day"]').click()
            self.page.keyboard.press("Escape")
        got = self.page.locator("html").get_attribute("data-surface")
        if got != self.surface:
            raise RuntimeError(f"surface is {got!r}, wanted {self.surface!r}")
        self.wait_for("#brainModeBadge:has-text('Brain:')")
        self.page.wait_for_timeout(1200)  # deferred scripts + the 3D module settle

    def wait_for(self, selector: str) -> bool:
        try:
            self.page.locator(selector).first.wait_for(state="attached", timeout=WAIT_MS)
            return True
        except Exception:  # noqa: BLE001 - a missing state is reported, never fatal
            self.run.warnings.append(f"[{self.tag}] not seen within {WAIT_MS} ms: {selector}")
            return False

    def open_panel(self, panel: str, ready: bool = True) -> None:
        tab = self.page.locator(f'.dk[data-open="{panel}"]')
        if self.page.locator(f"#p-{panel}").is_visible():
            pass  # already open (the Conversation, by default): a tab click would toggle it shut
        elif tab.is_visible():
            tab.click()
        else:  # phones: the tabs that don't fit the bar sit behind More (slice 8)
            self.page.locator("#dockMore").click()
            self.page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
        self.page.locator(f"#p-{panel}").wait_for(state="visible")
        if ready and panel in READY:
            self.wait_for(READY[panel])
        self.page.wait_for_timeout(SETTLE_MS)

    def close_panel(self, panel: str) -> None:
        if self.vp == "desktop" and panel != "chat":
            btn = self.page.locator(f"#p-{panel} [data-close]")
            if btn.is_visible():
                btn.click()

    def close(self) -> None:
        self.ctx.close()


# ================================================================================================
# capture
# ================================================================================================
def shoot(c: Console, selector: str | None, name: str, group: str) -> None:
    path = c.run.out / f"{name}.png"
    try:
        if selector is None:
            c.page.screenshot(path=str(path), animations="disabled", caret="hide")
        else:
            c.page.locator(selector).first.screenshot(
                path=str(path), animations="disabled", caret="hide"
            )
        c.run.shots.append((group, path.name))
    except Exception as exc:  # noqa: BLE001 - one failed shot must not stop the run
        c.run.failures.append(f"{name}: {exc}")


def check(c: Console, selector: str, name: str) -> None:
    try:
        c.run.checks[name] = c.page.evaluate(DOM_CHECKS_JS, selector)
    except Exception as exc:  # noqa: BLE001
        c.run.failures.append(f"checks {name}: {exc}")


def shoot_panel(c: Console, panel: str, name: str) -> None:
    """The panel as seen, then one shot per further screenful while its body scrolls."""
    sel = f"#p-{panel}"
    body = c.page.locator(f"{sel} .pbody").first
    if body.count():  # a click (Run, say) may have scrolled it: the first shot is the top
        body.evaluate("b => { b.scrollTop = 0; }")
        c.page.wait_for_timeout(100)
    shoot(c, sel, name, c.tag)
    check(c, sel, name)
    if not body.count():
        return
    dims = body.evaluate("b => [b.scrollHeight, b.clientHeight]")
    step = 0
    while dims[0] > dims[1] + 8 and step < MAX_SCROLL_SHOTS:
        step += 1
        at_end = body.evaluate(
            "(b, s) => { b.scrollTop = s * b.clientHeight * 0.9; "
            "return b.scrollTop + b.clientHeight >= b.scrollHeight - 2; }",
            step,
        )
        c.page.wait_for_timeout(150)
        shoot(c, sel, f"{name}-s{step}", c.tag)
        if at_end:
            break
    body.evaluate("b => { b.scrollTop = 0; }")


def vitals_form(c: Console) -> None:
    """Vitals with its add form open ("Track a key")."""
    c.open_panel("vitals")
    btn = c.page.locator("#vitals-board .vt-head button", has_text="Track a key")
    if not btn.count():
        c.run.failures.append(f"[{c.tag}] Vitals has no 'Track a key' button")
        return
    btn.click()
    c.page.locator("#vitals-board .vt-formbox form").wait_for()
    c.page.locator("#vitals-board .vt-formbox form").evaluate(
        "f => f.scrollIntoView({block: 'start'})"
    )
    c.page.wait_for_timeout(250)
    name = f"{c.tag}-vitals-form"
    shoot(c, "#p-vitals", name, c.tag)
    check(c, "#p-vitals", name)
    shoot(c, "#vitals-board .vt-formbox form", f"{name}-only", c.tag)
    cancel = c.page.locator("#vitals-board .vt-formbox button", has_text="Cancel")
    if cancel.count():
        cancel.click()
    c.close_panel("vitals")


def capture_combo(browser: Browser, url: str, vp: str, surface: str, run: Run) -> None:
    c = Console(browser, url, vp, surface, run)
    try:
        install_mocks(c.page)
        c.open()
        shoot(c, None, f"{c.tag}-page", c.tag)
        shoot(c, "header.topbar", f"{c.tag}-topbar", c.tag)
        check(c, "header.topbar", f"{c.tag}-topbar")
        for panel in PANELS:
            log.info("%s %s", c.tag, panel)
            try:
                c.open_panel(panel)
            except Exception as exc:  # noqa: BLE001
                run.failures.append(f"[{c.tag}] open {panel}: {exc}")
                continue
            if panel == "integrations":  # exercise POST /v1/health/run (mocked) before the shot
                run_btn = c.page.locator("#systemsCard .btn", has_text="Run")
                if run_btn.count():
                    run_btn.click()
                    c.page.wait_for_timeout(400)
            shoot_panel(c, panel, f"{c.tag}-{panel}")
            c.close_panel(panel)
        vitals_form(c)
    finally:
        c.close()


def capture_vitals_503(browser: Browser, url: str, vp: str, run: Run) -> None:
    c = Console(browser, url, vp, "night", run)
    c.tag = f"{vp}-night-503"
    try:
        install_mocks(c.page, vitals_503=True)
        c.open()
        c.open_panel("vitals", ready=False)
        c.wait_for("#vitals-board .vt-state.vt-err")
        shoot_panel(c, "vitals", f"{c.tag}-vitals")
    finally:
        c.close()


def write_index(run: Run) -> None:
    lines = [
        "# UI snapshots",
        "",
        f"Made {time.strftime('%Y-%m-%d %H:%M:%S')} by "
        "scripts/ui_snapshots.py. DOM-check findings per shot: checks.json.",
        "",
    ]
    groups: dict[str, list[str]] = {}
    for group, name in run.shots:
        groups.setdefault(group, []).append(name)
    for group in sorted(groups):
        lines += [f"## {group}", ""] + [f"- [{n}]({n})" for n in groups[group]] + [""]
    lines += [
        "## DOM checks (counts per shot)",
        "",
        "| shot | overlaps | offTheme | systemFont | defaults | runTogether | overflow | "
        "contrast | smallTargets | unlabelled |",
        "|" + "---|" * 10,
    ]
    keys = [
        "overlaps",
        "offTheme",
        "systemFont",
        "defaults",
        "runTogether",
        "overflow",
        "contrast",
        "smallTargets",
        "unlabelled",
    ]
    for name, res in sorted(run.checks.items()):
        if isinstance(res, dict) and not res.get("missing"):
            lines.append(
                f"| {name} | " + " | ".join(str(len(res.get(k) or [])) for k in keys) + " |"
            )
    for title, items in (
        ("Page errors", run.page_errors),
        ("Failures", run.failures),
        ("Warnings", run.warnings),
        ("Console errors", run.console_errors),
    ):
        lines += ["", f"## {title} ({len(items)})", ""] + [f"- {x}" for x in items[:200]]
    (run.out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run.out / "checks.json").write_text(json.dumps(run.checks, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="directory for the PNGs and index.md")
    ap.add_argument("--viewports", default="desktop,phone")
    ap.add_argument("--surfaces", default=",".join(SURFACES))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    run = Run(out=args.out)
    run.out.mkdir(parents=True, exist_ok=True)
    vps = [v for v in args.viewports.split(",") if v in VIEWPORTS]
    surfaces = [s for s in args.surfaces.split(",") if s in SURFACES]
    with serve() as url, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for vp in vps:
                for surface in surfaces:
                    capture_combo(browser, url, vp, surface, run)
                if "night" in surfaces:
                    capture_vitals_503(browser, url, vp, run)
        finally:
            browser.close()
    write_index(run)
    log.info(
        "%d shots, %d page errors, %d failures -> %s",
        len(run.shots),
        len(run.page_errors),
        len(run.failures),
        run.out / "index.md",
    )
    return 1 if run.page_errors or run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
