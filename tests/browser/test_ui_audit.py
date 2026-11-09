# tests/browser/test_ui_audit.py -- R5.1 D11, the visual gate. For EVERY console panel, at DESKTOP and
# PHONE, on Night and Day, with realistic mocked R4 data (ui_checks.py, shared with
# scripts/ui_snapshots.py), the in-page DOM checks must find: no overlapping interactive elements, no
# browser-default controls, theme fonts only, nothing overflowing its panel sideways, every control
# named, no button text on a third line, no page-level horizontal scroll, contrast >= 4.5:1.
# One page per viewport and surface (module-scoped); the panels are opened in turn.
# The release checklist also needs the screenshots to be LOOKED at: scripts/ui_snapshots.py.
# ruff: noqa: E501 -- the labelling and wrapping probes are JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from ui_checks import DOM_CHECKS_JS, PANELS, READY, inject_unlinked_css, install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}
SURFACES = ("night", "day")
SETTLE_MS = 700  # panelIn (.22s) + rise (.4s) animations, then a margin

# Controls (buttons, links) need a visible name; inputs need a label or an aria-label.
NAMELESS_JS = r"""(sel) => {
  const root = document.querySelector(sel);
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('.sr-only') && !e.closest('details:not([open]) > :not(summary)'); };
  const bad = [];
  for (const e of root.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=button]')) {
    if (!vis(e)) continue;
    const lab = (e.getAttribute('aria-label') || '').trim() || (e.getAttribute('aria-labelledby') || '').trim();
    const own = (e.textContent || '').trim();
    const forLab = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
    const wrap = e.closest('label');
    if (e.matches('button, a[href], [role=button]')) { if (!lab && !own && !(e.title || '').trim()) bad.push('unnamed ' + e.tagName + '#' + e.id + '.' + e.className); }
    else if (!lab && !forLab && !wrap) bad.push('no label ' + e.tagName + '#' + e.id + '.' + e.className + ' ph=' + (e.placeholder || ''));
  }
  return bad;
}"""
# A button whose text runs onto a third line.
WRAP_JS = r"""(sel) => {
  const out = [];
  for (const b of document.querySelectorAll(sel + ' button:not(.dsc):not(.bsw), ' + sel + ' .btn')) {
    const r = b.getBoundingClientRect(); if (r.width < 2 || !(b.textContent || '').trim()) continue;
    const rg = document.createRange(); rg.selectNodeContents(b);
    const tops = new Set([...rg.getClientRects()].filter((q) => q.width > 1).map((q) => Math.round(q.top / 4)));
    if (tops.size > 2) out.push((b.textContent || '').trim().slice(0, 30) + ' lines=' + tops.size);
  }
  return out;
}"""


class Rig:
    """One signed-in page per (viewport, surface), created on first use."""

    def __init__(self, browser: Any, url: str, token: str) -> None:
        self.browser, self.url, self.token = browser, url, token
        self.pages: dict[tuple[str, str], Console] = {}

    def get(self, vp: str, surface: str) -> Console:
        key = (vp, surface)
        if key not in self.pages:
            c = Console(self.browser, self.url, self.token, VIEWPORTS[vp])
            install_mocks(c.page)
            c.open()
            inject_unlinked_css(c.page)
            if surface == "day":
                c.page.locator("#themeBtn").click()
                c.page.locator('label[for="jx-s-day"]').click()
                c.page.keyboard.press("Escape")
            assert c.page.locator("html").get_attribute("data-surface") == surface
            c.page.wait_for_timeout(1200)  # deferred scripts and the 3D module settle
            self.pages[key] = c
        return self.pages[key]

    def close(self) -> None:
        for c in self.pages.values():
            c.close()


@pytest.fixture(scope="module")
def rig(server_url: str, token: str) -> Iterator[Rig]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        r = Rig(b, server_url, token)
        yield r
        r.close()
        b.close()


def _open(c: Console, panel: str) -> None:
    tab = c.page.locator(f'.dk[data-open="{panel}"]')
    if c.page.locator(f"#p-{panel}").is_visible():
        pass  # already open (the Conversation, by default): a tab click would toggle it shut
    elif tab.is_visible():
        tab.click()
    else:  # phones: the tabs that do not fit the bar sit behind More
        c.page.locator("#dockMore").click()
        c.page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
    c.page.locator(f"#p-{panel}").wait_for(state="visible")
    if panel in READY:
        try:
            c.page.locator(READY[panel]).first.wait_for(state="attached", timeout=4000)
        except Exception:  # noqa: BLE001 - a panel without its data is judged as it stands
            pass
    c.page.wait_for_timeout(SETTLE_MS)
    body = c.page.locator(f"#p-{panel} .pbody").first
    if body.count():
        body.evaluate("b => { b.scrollTop = 0; }")


def _close(c: Console, panel: str, vp: str) -> None:
    if vp == "desktop" and panel != "chat":
        btn = c.page.locator(f"#p-{panel} [data-close]")
        if btn.is_visible():
            btn.click()


def _fmt(items: list[Any]) -> str:
    return "\n  ".join(json.dumps(i, ensure_ascii=False)[:230] for i in items[:8])


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
@pytest.mark.parametrize("panel", PANELS)
def test_panel_passes_the_visual_gate(rig: Rig, panel: str, vp: str, surface: str) -> None:
    c = rig.get(vp, surface)
    _open(c, panel)
    sel = f"#p-{panel}"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    nameless = c.page.evaluate(NAMELESS_JS, sel)
    wraps = c.page.evaluate(WRAP_JS, sel)
    _close(c, panel, vp)
    assert not res.get("missing"), f"{sel} is not in the page"
    # an element escaping its panel sideways, a hard-clipped text or a sideways-scrolling body
    sideways = [
        o
        for o in res["overflow"]
        if o.get("why") or o.get("clipped") == "hard clip" or o.get("dx", 0) > 2
    ]
    # Known false positives of the generic probes: the Send button's accent gradient and a native
    # range slider (its track is drawn by the browser; it is named by aria-labelledby).
    defaults = [
        d for d in res["defaults"] if "button#send" not in d["el"] and "[type=range]" not in d["el"]
    ]
    problems = {
        "overlapping interactive elements": res["overlaps"],
        "off-theme font family": res["offTheme"],
        "browser-default control / heading / list": defaults,
        "overflows its panel sideways": sideways,
        "control without a label or name": nameless,
        "button text on a third line": wraps,
        "page-level horizontal scroll": [res["hscroll"]] if res["hscroll"] else [],
        "text contrast below 4.5:1": res["contrast"],
    }
    failed = {k: v for k, v in problems.items() if v}
    assert not failed, f"{panel} {vp} {surface}:\n" + "\n".join(
        f"- {k} ({len(v)}):\n  {_fmt(v)}" for k, v in failed.items()
    )
