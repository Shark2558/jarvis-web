# tests/browser/ui_checks.py -- shared by tests/browser/test_ui_audit.py and scripts/ui_snapshots.py:
# the page.route mocks for the R4 panels and the in-page DOM checks (JavaScript string).
# ruff: noqa: E501 -- DOM_CHECKS_JS is JavaScript evaluated in the page
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from book_mocks import status as book_status
from playwright.sync_api import Page, Route

from jarvis import about
from jarvis.health.briefing import compose_briefing
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.probes import BRAIN_NO_CREDIT
from jarvis.health.report import spoken_label, system_row, view
from jarvis.vitals.auto import SPEND_ID
from jarvis.vitals.models import Board, Provider, ProviderView, Spend, group_of
from jarvis.vitals.own import LABELS, OWN_IDS
from jarvis.vitals.service import MANUAL_UNAVAILABLE as MANUAL_NOTE
from jarvis.vitals.words import NO_CREDIT, words_for

PANELS = (
    "activity approvals book brief camera chat connectors construct faces helpers history home "
    "integrations media memory notes people privacy things vault vitals voice"
).split()
# A selector that shows the panel has painted its data (best effort; a miss is never fatal).
READY: dict[str, str] = {
    "vitals": "#vitals-board .vt-row, #vitals-board .trow",
    "integrations": "#systemsCard .sysrow, #systemsCard .event",
    "connectors": "#p-connectors .integ .istate",
    "people": "#peopleCard .pname",
    "book": "#p-book .bk-release",  # R6 I1: the panel with a release and sealed books (book_mocks)
    "helpers": "#p-helpers .hp-tabs .hp-tab",  # R11 I0: the frame and its four tabs
}
NOW = int(time.time())

# ================================================================================================
# MOCKS — page.route fulfilments so the R4 panels show realistic states. Shapes follow the server:
#   /v1/vitals                -> src/jarvis/vitals/api.py + models.py (Board.to_json)
#   /v1/health, /health/run   -> src/jarvis/health/api.py (report.view + briefing)
#   /v1/health/run/stream     -> NDJSON: plan, result per system, done (health/api.py)
#   /v1/connectors            -> src/jarvis/photos/api.py `_status` (console-connectors.js reads it)
#   /v1/settings/brain-mode   -> src/jarvis/people/routes.py (MEANING["ai"])
#   /v1/people/last           -> src/jarvis/people/routes.py `last` ({dossier: _view(d)})
#   /v1/integrations          -> Google linked (the well-styled reference card; test_console LINKED)
#   /v1/book                  -> R6: a release, three sealed books (tests/browser/book_mocks.py)
# ================================================================================================


# The board and the systems check are built with the server's own models and fixed words
# (vitals.models / vitals.words, health.report.view + health.briefing.compose_briefing), so a
# screenshot shows exactly what the routes would answer: impact / fix / group per item,
# manual_unavailable, the R5.1 briefing, and the out-of-credit Claude key (R5.1 I1).
DAY = 86400
TZ = timezone(timedelta(hours=5, minutes=30))


def _at(days: float) -> datetime:
    return datetime.fromtimestamp(NOW + days * DAY, TZ)


def _view(status: str, reason: str = "", percent: float | None = None, **p: Any) -> ProviderView:
    provider = Provider(**p)
    impact, fix = (
        ("", "") if provider.source == "manual" else words_for(provider.id, provider.label, reason)
    )
    group = "bills" if provider.id == SPEND_ID else group_of(provider.kind)
    if provider.id in OWN_IDS:
        group = "allowances" if provider.kind == "quota" else "keys"
    return ProviderView(
        provider=provider,
        status=status,
        percent=percent,
        reason=reason,
        impact=impact,
        fix=fix,
        group=group,
    )  # type: ignore[arg-type]


def _board(*, manual_unavailable: bool = False) -> Board:
    own = [
        _view(
            "red",
            NO_CREDIT,
            id="brain_claude",
            label=LABELS["brain_claude"],
            kind="key",
            source="auto",
        ),
        _view(
            "ok",
            id="brain_gemini",
            label=LABELS["brain_gemini"],
            kind="key",
            source="auto",
            note="The last AI call worked.",
        ),
        _view(
            "ok",
            id="google_link",
            label=LABELS["google_link"],
            kind="key",
            source="auto",
            note="Connected.",
        ),
        _view(
            "ok",
            id="telegram_bot",
            label=LABELS["telegram_bot"],
            kind="key",
            source="auto",
            note="Checked 4 minutes ago.",
        ),
        _view(
            "amber",
            "is at 85% of its limit",
            85.0,
            id="web_credits",
            label=LABELS["web_credits"],
            kind="quota",
            source="auto",
            limit=1000,
            used=850,
            unit="searches",
            reset_at=_at(20),
        ),
        _view(
            "amber",
            "expires in 6 days",
            id="github_token",
            label=LABELS["github_token"],
            kind="key",
            source="auto",
            expires_at=_at(6),
            note="Hourly limit: 4 of 5000 used.",
        ),
        _view(
            "red",
            "is offline: no heartbeat for 14 minutes",
            id="home_link",
            label=LABELS["home_link"],
            kind="key",
            source="auto",
            note="Last heartbeat 14 minutes ago.",
        ),
        _view(
            "amber",
            "is at 82% of its limit",
            82.5,
            id=SPEND_ID,
            label="AI spend this month",
            kind="billing",
            source="auto",
            limit=500,
            used=412.5,
            unit="₹",
            reset_at=_at(20),
        ),
        _view(
            "amber",
            "is at 91% of its limit",
            91.0,
            id="allowance_chirp3",
            label="Voice (Chirp 3 HD)",
            kind="allowance",
            source="auto",
            limit=1_000_000,
            used=910_000,
            unit="characters",
            reset_at=_at(20),
        ),
        _view(
            "ok",
            "",
            12.4,
            id="quota_maps",
            label="Google Maps",
            kind="quota",
            source="auto",
            limit=10000,
            used=1240,
            unit="calls",
            reset_at=_at(20),
        ),
    ]
    manual = (
        []
        if manual_unavailable
        else [
            _view(
                "amber",
                "expires in 9 days",
                id="car-insurance",
                label="Car insurance",
                kind="billing",
                expires_at=_at(9),
                note="Renew with the agent.",
            ),
            _view(
                "ok",
                id="domain",
                label="Domain renewal",
                kind="billing",
                expires_at=_at(200),
            ),
        ]
    )
    return Board(
        items=tuple(own + manual),
        spend=Spend(used_inr=412.5, limit_inr=500, text="₹413 of ₹500 this month"),
        overall="red",
        manual_unavailable=manual_unavailable,
        manual_note=MANUAL_NOTE if manual_unavailable else "",
    )


BOARD = _board()
# R6.1 D4: GET /v1/vitals also carries the "About JARVIS" line's two fields (vitals/api.py)
ABOUT = {"version": about.version(), "build_date": "11 Nov 2026"}
MOCK_VITALS: dict[str, Any] = {**BOARD.to_json(), **ABOUT}
MOCK_VITALS_503 = {"detail": "Vitals is not available on this server."}


def _probe(key: str, label: str, status: str, reason: str) -> ProbeResult:
    return ProbeResult(key=key, label=label, status=status, reason=reason, at=NOW - 90)  # type: ignore[arg-type]


REPORT = HealthReport(
    overall="down",
    at=NOW - 90,
    results=(
        _probe("brain", "the AI brain", "down", BRAIN_NO_CREDIT),
        _probe("docs", "the document store", "ok", "the document store answers"),
        _probe("redis", "Redis", "ok", "Redis answers"),
        _probe("google", "Google", "degraded", "a Google service is switched off"),
        _probe("telegram", "Telegram", "ok", "Telegram answers"),
        _probe("home", "the home bridge", "down", "no heartbeat for 14 minutes"),
        _probe("web", "web search", "ok", "web search answers"),
    ),
)
MOCK_HEALTH: dict[str, Any] = {
    **view(REPORT),
    "briefing": compose_briefing(REPORT, BOARD).to_json(),
}


def stream_body() -> str:
    """POST /v1/health/run/stream: plan, one result per system, then done (health/api.py)."""
    events: list[dict[str, Any]] = [
        {
            "type": "plan",
            "systems": [{"key": r.key, "name": spoken_label(r)} for r in REPORT.results],
        }
    ]
    events += [{"type": "result", **system_row(r)} for r in REPORT.results]
    events.append({"type": "done", **MOCK_HEALTH})
    return "".join(json.dumps(e) + "\n" for e in events)


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


def _usage() -> dict[str, Any]:
    """GET /v1/usage (billing.UsageView): the same month and figures as the board's AI-spend item
    (₹412.50 of ₹500), so the "This month" block in Vitals agrees with it."""
    return {
        "month": datetime.fromtimestamp(NOW, TZ).strftime("%Y-%m"),
        "used_inr": 412.5,
        "limit_inr": 500,
        "remaining_inr": 87.5,
        "percent": 82.5,
        "warn": True,
        "reached": False,
        "calls": 214,
        "by_brain": [
            {"brain": "anthropic", "label": "Claude", "used_inr": 380.25},
            {"brain": "gemini", "label": "Gemini", "used_inr": 32.25},
        ],
        "rate": {
            "inr_per_usd": 88.4,
            "as_of": datetime.fromtimestamp(NOW, TZ).strftime("%Y-%m-%d"),
            "source": "ecb",
        },
    }


MOCK_USAGE: dict[str, Any] = _usage()
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


def _ndjson(route: Route) -> None:
    route.fulfill(status=200, content_type="application/x-ndjson", body=stream_body())


def install_mocks(
    page: Page, *, vitals_503: bool = False, manual_unavailable: bool = False
) -> None:
    vitals = (503, MOCK_VITALS_503) if vitals_503 else (200, MOCK_VITALS)
    if manual_unavailable:
        vitals = (200, {**_board(manual_unavailable=True).to_json(), **ABOUT})
    page.route("**/v1/usage", _get_only(200, MOCK_USAGE))
    page.route("**/v1/vitals", _get_only(*vitals))
    page.route("**/v1/health", _get_only(200, MOCK_HEALTH))
    page.route("**/v1/health/run", _json(200, MOCK_HEALTH))
    page.route("**/v1/health/run/stream", _ndjson)
    page.route("**/v1/connectors", _get_only(200, MOCK_CONNECTORS))
    page.route("**/v1/settings/brain-mode", _get_only(200, MOCK_BRAIN_MODE))
    page.route("**/v1/people/last", _get_only(200, MOCK_PEOPLE_LAST))
    page.route("**/v1/integrations", _get_only(200, MOCK_INTEGRATIONS))
    page.route("**/v1/book", _get_only(200, book_status()))  # R6 I1: the Book panel with data


# Finite CSS animations and transitions are run to their end state before anything is measured: the
# contrast probe multiplies in opacity, and an element caught mid-entry (opacity 0 -> 1) is not a defect.
# Infinite ones (the status dot's breathing) are left alone.
FINISH_ANIMATIONS_JS = """() => {
  // Finishing one transition (a theme token on <html>) sets off others (a tab's own colour
  // transition) at the next style update: flush the style and repeat, a few rounds at most.
  for (let round = 0; round < 4; round++) {
    let finished = 0;
    for (const a of document.getAnimations()) {
      try {
        if (a.playState !== 'finished' && a.effect && a.effect.getComputedTiming().iterations !== Infinity) { a.finish(); finished += 1; }
      } catch (_) { /* a cancelled one */ }
    }
    if (!finished) return;
    void document.documentElement.getBoundingClientRect();
  }
}"""

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
  // visually hidden on purpose: the screen-reader clip pattern on a 1 x 1 px box (e.g. the 320 px
  // dock's icon-only tabs). The same clip on a full-size box is a fault and is still measured.
  const clipped = (s) => s.position === 'absolute' && s.width === '1px' && s.height === '1px'
    && (s.clip === 'rect(0px, 0px, 0px, 0px)' || s.clipPath === 'inset(50%)');
  const vis = (e) => {
    if (inClosedDetails(e) || e.closest('.sr-only')) return false;
    const r = rect(e); if (r.width < 1 || r.height < 1) return false;
    const s = cs(e); return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05 && !clipped(s);
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
                contrast: [], smallTargets: [], unlabelled: [], hitOverlaps: [], hscroll: null };

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
  const tokenBgs = new Set(['var(--well)', 'var(--well-2)', 'var(--tint)', 'var(--panel-solid)', 'var(--accent)', 'var(--amber-tint)', 'var(--bad-tint)', 'transparent', '#B42318'].map(probe));
  tokenBgs.add('rgba(0, 0, 0, 0)');
  const ref = document.querySelector('#status'); if (ref) tokenBgs.add(cs(ref).backgroundColor);   // the status pill the brain pill copies
  // fully (or all but) transparent, in any colour syntax: a hover fade caught a frame early is not a default look
  const clear = (c) => { const m = c.match(/\/ ([0-9.e-]+)\)$/) || c.match(/^rgba\(.*, ([0-9.]+)\)$/); return c === 'transparent' || (!!m && parseFloat(m[1]) < 0.02); };
  for (const e of els) {
    const s = cs(e);
    if (e.matches('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=color]), select, textarea, button')) {
      const bad = [];
      if (s.borderTopStyle === 'inset' || s.borderTopStyle === 'outset') bad.push('border ' + s.borderTopStyle);
      if (!tokenBgs.has(s.backgroundColor) && !clear(s.backgroundColor)) bad.push('bg ' + s.backgroundColor);
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
      if (/\s$/.test(a.textContent) || /^\s/.test(b.textContent)) continue; // a rendered space between them
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

  // 6. contrast of own text against the composited background (gradients ignored). The text's
  // alpha is multiplied by the opacity of the element and every ancestor, so dimmed text counts.
  const effOpacity = (e) => { let o = 1; for (let n = e; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(cs(n).opacity); return o; };
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
    if (e.closest(':disabled, [aria-disabled="true"]')) continue;   // WCAG 1.4.3: a disabled control is exempt (dimmed on purpose)
    const s = cs(e), fg1 = parse(s.color); if (!fg1) continue;
    const fg0 = [fg1[0], fg1[1], fg1[2], fg1[3] * effOpacity(e)];
    const bg = bgOf(e), fg = over(fg0, bg), L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const px = parseFloat(s.fontSize), large = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700);
    const opacity = Math.round(effOpacity(e) * 100) / 100;
    if (ratio < (large ? 3 : 4.5) && out.contrast.length < CAP) out.contrast.push({ el: path(e), text: words(e), ratio: Math.round(ratio * 100) / 100, size: s.fontSize, opacity });
  }

  // 7. targets below 24x24 (WCAG 2.2 web-target-size); 44 on a phone-width viewport
  const min = window.innerWidth < 900 ? 44 : 24;
  for (const e of inter) {
    if (e.matches('input[type=checkbox], input[type=radio]')) continue;
    const r = rect(e);
    // An invisible hit area (a ::before band that makes a small control tappable) counts: the
    // gate measures it, and the overlap probe below keeps it off its neighbours.
    const hit = (() => { const b = getComputedStyle(e, '::before'); return b.content !== 'none' && b.position === 'absolute' ? { w: parseFloat(b.width) || 0, h: parseFloat(b.height) || 0 } : { w: 0, h: 0 }; })();
    const rw = Math.max(r.width, hit.w), rh = Math.max(r.height, hit.h);
    // rounded: a sub-pixel short of the minimum (43.98 px) is the minimum
    if ((Math.round(rw) < min || Math.round(rh) < min) && out.smallTargets.length < CAP) out.smallTargets.push({ el: path(e), text: words(e), w: Math.round(rw), h: Math.round(rh), min });
  }

  // 7b. a hit-area band must not reach another control: the expanded box of a control with a
  // ::before band is compared with every other interactive element
  out.hitOverlaps = [];
  for (const a of inter) {
    const b = getComputedStyle(a, '::before');
    if (b.content === 'none' || b.position !== 'absolute') continue;
    const r = rect(a), ex = Math.max(0, (parseFloat(b.height) - r.height) / 2), ey = Math.max(0, (parseFloat(b.width) - r.width) / 2);
    const box = { l: r.left - ey, r: r.right + ey, t: r.top - ex, b: r.bottom + ex };
    for (const o of inter) {
      if (o === a || o.contains(a) || a.contains(o)) continue;
      const q = rect(o), w = Math.min(box.r, q.right) - Math.max(box.l, q.left), h = Math.min(box.b, q.bottom) - Math.max(box.t, q.top);
      if (w > 1 && h > 1 && out.hitOverlaps.length < CAP) out.hitOverlaps.push({ a: path(a), b: path(o), w: Math.round(w), h: Math.round(h) });
    }
  }

  // 8. controls without a programmatic or visible label (placeholder-only counts as unlabelled)
  for (const e of inter.filter((x) => x.matches('input:not([type=hidden]), select, textarea'))) {
    const hasFor = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
    const wrap = e.closest('label');
    const byIds = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map((i) => document.getElementById(i));
    const labelledBy = byIds.some((n) => n && vis(n) && (n.textContent || '').trim());
    const visible = hasFor || labelledBy || (wrap && own(wrap)) || (wrap && [...wrap.children].some((c) => c !== e && (c.textContent || '').trim()));
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
