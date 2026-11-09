# tests/browser/test_ui_audit.py -- R5.1 D11, the visual gate. For EVERY console panel, at DESKTOP and
# PHONE, on Night and Day, with realistic mocked R4 data (ui_checks.py, shared with
# scripts/ui_snapshots.py), the in-page DOM checks must find: no overlapping interactive elements, no
# browser-default controls, theme fonts only, nothing overflowing its panel sideways (a hard-clipped
# text fails; an ellipsis-truncated one is allowed), every control named, no button text on a third
# line, no page-level horizontal scroll, contrast >= 4.5:1 (the text's own opacity and its ancestors'
# are applied; gradients are not), no neighbouring texts run together, no control whose label sits
# after it, no control or heading left in the plain body font, and (phone only) every touch target at
# least 44 px (an invisible ::before hit-area band counts, and must not reach a neighbouring control).
# What "its data painted" means: FOUR panels have a data-specific READY selector (ui_checks.READY:
# vitals, integrations, connectors, people); a miss fails. Every OTHER panel is only required to show
# some text inside its body (an empty panel proves nothing), not its mocked data.
# Beyond the 20 panels the gate also audits (D11 completeness): the top bar, the open brain menu and
# its AI-on confirm, the systems-check pop-up in its done state with concerns, and the Vitals
# "Track something JARVIS can't see" form OPEN. Each is a separate parametrised test below.
# One page per viewport and surface (module-scoped); the panels are opened in turn.
# The release checklist also needs the screenshots to be LOOKED at: scripts/ui_snapshots.py.
# ruff: noqa: E501 -- the labelling and wrapping probes are JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, PANELS, READY, install_mocks

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
# A button whose text runs onto a third line. Not the switch / disclosure chrome (.dsc, .bsw) nor the
# brain menu's rows (.bmopt: a title and a one-line meaning, by design two blocks).
WRAP_JS = r"""(sel) => {
  const out = [];
  for (const b of document.querySelectorAll(sel + ' button:not(.dsc):not(.bsw):not(.bmopt), ' + sel + ' .btn')) {
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


def _open(c: Console, panel: str) -> str | None:
    """Open the panel; the READY selector that never appeared, or None."""
    tab = c.page.locator(f'.dk[data-open="{panel}"]')
    if c.page.locator(f"#p-{panel}").is_visible():
        pass  # already open (the Conversation, by default): a tab click would toggle it shut
    elif tab.is_visible():
        tab.click()
    else:  # phones: the tabs that do not fit the bar sit behind More
        c.page.locator("#dockMore").click()
        c.page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
    c.page.locator(f"#p-{panel}").wait_for(state="visible")
    missing = None
    if panel in READY:
        try:
            c.page.locator(READY[panel]).first.wait_for(state="attached", timeout=4000)
        except Exception:  # noqa: BLE001 - reported: the panel never painted its data
            missing = READY[panel]
    elif not _has_content(c, panel):
        missing = f"#p-{panel} shows no text"
    c.page.wait_for_timeout(SETTLE_MS)
    body = c.page.locator(f"#p-{panel} .pbody").first
    if body.count():
        body.evaluate("b => { b.scrollTop = 0; }")
    return missing


def _has_content(c: Console, panel: str) -> bool:
    """A panel without a data-specific READY selector must at least have painted some text."""
    try:
        c.page.wait_for_function(
            "(sel) => { const e = document.querySelector(sel); return !!e && (e.innerText || '').trim().length > 3; }",
            arg=f"#p-{panel}",
            timeout=4000,
        )
    except Exception:  # noqa: BLE001 - the caller reports it
        return False
    return True


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
    not_ready = _open(c, panel)
    sel = f"#p-{panel}"
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    nameless = c.page.evaluate(NAMELESS_JS, sel)
    wraps = c.page.evaluate(WRAP_JS, sel)
    _close(c, panel, vp)
    assert not res.get("missing"), f"{sel} is not in the page"
    assert not_ready is None, f"{panel} {vp} {surface}: its data never painted ({not_ready})"
    _assert_clean(res, nameless, wraps, vp, f"{panel} {vp} {surface}")


def _problems(
    res: dict[str, Any], nameless: list[Any], wraps: list[Any], vp: str
) -> dict[str, Any]:
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
    return {
        "overlapping interactive elements": res["overlaps"],
        "off-theme font family": res["offTheme"],
        "browser-default control / heading / list": defaults,
        "overflows its panel sideways": sideways,
        "control without a label or name": nameless,
        "button text on a third line": wraps,
        "page-level horizontal scroll": [res["hscroll"]] if res["hscroll"] else [],
        "text contrast below 4.5:1": res["contrast"],
        "neighbouring texts run together": res["runTogether"],
        # D11: a visible label (not after the control) or an aria-label; placeholder-only fails
        "control unlabelled or labelled after it": [
            u
            for u in res["unlabelled"]
            if u.get("order") == "label text after the control"
            or not (u.get("visibleLabel") or u.get("aria"))
        ],
        "control or heading in the plain body font": res["systemFont"],
        "touch target below 44 px on the phone": res["smallTargets"] if vp == "phone" else [],
        "invisible hit area reaches a neighbouring control": res["hitOverlaps"],
    }


def _assert_clean(
    res: dict[str, Any], nameless: list[Any], wraps: list[Any], vp: str, what: str
) -> None:
    failed = {k: v for k, v in _problems(res, nameless, wraps, vp).items() if v}
    assert not failed, f"{what}:\n" + "\n".join(
        f"- {k} ({len(v)}):\n  {_fmt(v)}" for k, v in failed.items()
    )


def _audit(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


# ---- D11 completeness: the surfaces that are not panels -------------------------------------------
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_top_bar_passes_the_visual_gate(rig: Rig, vp: str, surface: str) -> None:
    c = rig.get(vp, surface)
    c.page.locator("#brainModeBadge").wait_for()
    _audit(c, "header.topbar", vp, f"top bar {vp} {surface}")


class FakeBrain:
    """A stateful /v1/settings/brain-mode for the pages of the shared rig (the real server's mode
    is never touched, and the page is put back to AI on at the end)."""

    def __init__(self) -> None:
        self.mode = "ai"

    def __call__(self, route: Any) -> None:
        if route.request.method == "POST":
            self.mode = json.loads(route.request.post_data or "{}")["mode"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"mode": self.mode, "meaning": "x"}),
        )


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_open_brain_menu_and_its_ai_on_confirm_pass_the_visual_gate(
    rig: Rig, vp: str, surface: str
) -> None:
    c = rig.get(vp, surface)
    brain = FakeBrain()
    c.page.route("**/v1/settings/brain-mode", brain)
    try:
        c.page.locator("#brainModeBadge").click()
        c.page.locator("#brainMenu").wait_for(state="visible")
        c.page.wait_for_timeout(SETTLE_MS)
        _audit(c, "#brainMenu", vp, f"brain menu {vp} {surface}")
        c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
        c.page.locator("#brainModeBadge", has_text="No-AI").wait_for()
        c.page.locator("#brainModeBadge").click()
        c.page.locator("#brainMenu .bmopt[data-mode=ai]").click()
        c.page.locator("#brainMenu .bmask").wait_for(state="visible")
        c.page.wait_for_timeout(SETTLE_MS)
        _audit(c, "#brainMenu", vp, f"AI-on confirm {vp} {surface}")
        c.page.get_by_role("button", name="Switch on").click()
        c.page.locator("#brainModeBadge", has_text="AI on").wait_for()
    finally:
        c.page.unroute("**/v1/settings/brain-mode", brain)


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_systems_check_popup_with_concerns_passes_the_visual_gate(
    rig: Rig, vp: str, surface: str
) -> None:
    c = rig.get(vp, surface)
    _open(c, "integrations")
    c.page.locator("#systemsCard .btn", has_text="Run").first.click()
    dialog = c.page.locator("#sysCheck")
    dialog.wait_for(state="visible")
    c.page.locator("#sysCheck .scconcerns li").first.wait_for()
    dialog.click(position={"x": 8, "y": 8})  # a pointer inside cancels the 10 s countdown
    c.page.wait_for_timeout(SETTLE_MS)
    # done state with concerns: the systems AND the vitals items (amber / red) are listed
    kinds = c.page.evaluate(
        "() => [...document.querySelectorAll('#sysCheck .scconcerns li')].map((li) => li.textContent)"
    )
    assert any("GitHub" in k for k in kinds) and any("Voice" in k for k in kinds), kinds
    # measure the whole dialog, not only the screenful that is scrolled into view
    c.page.evaluate("() => { document.getElementById('sysCheck').style.maxHeight = 'none'; }")
    try:
        _audit(c, "#sysCheck", vp, f"systems-check pop-up {vp} {surface}")
    finally:
        c.page.evaluate("() => { document.getElementById('sysCheck').style.maxHeight = ''; }")
        c.page.locator("#sysCheckClose").first.click()
        _close(c, "integrations", vp)


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_vitals_track_form_open_passes_the_visual_gate(rig: Rig, vp: str, surface: str) -> None:
    c = rig.get(vp, surface)
    assert _open(c, "vitals") is None
    toggle = c.page.locator("#vtAddBtn")
    toggle.click()
    c.page.locator("#vtAddBody form").first.wait_for(state="visible")
    c.page.mouse.move(0, 0)  # no hover fade under the pointer while it is measured
    c.page.wait_for_timeout(SETTLE_MS)
    try:
        _audit(c, "#p-vitals", vp, f"Vitals form open {vp} {surface}")
    finally:
        toggle.click()  # closed again
        _close(c, "vitals", vp)
