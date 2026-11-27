# tests/browser/test_r18_review_look.py -- R18 combined review: the visual gate for every screen the
# review added or changed, at the owner's two laptop widths (1920 x 1080 and 2560 x 1440), Night and
# Day, each passing the console's own DOM checks (tests/browser/test_r18_e_look.py's `_gate`: no
# overlaps, theme fonts only, no browser-default controls, nothing overflowing, every control named,
# contrast). The screens: Calls -> Settings (the server's limits and prices, Unlink), Calls ->
# Languages (Score the voice, its box, the estimate's Bhashini words), the Privacy panel's Phone
# calls rows (built by `jarvis.calls.privacy` over test data), the Approvals card of a pending call
# (its arguments as `PendingApproval` shows them: the number masked) and Vitals' calls line.
# Screenshots only when R18_REVIEW_SHOTS names a folder (build/r18-review-shots/, never committed).
# ruff: noqa: E501 -- selectors
from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_r18_e_calls import Calls, until
from test_r18_e_look import _gate

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R18_REVIEW_SHOTS", "")
LAPTOPS = {"1920": {"width": 1920, "height": 1080}, "2560": {"width": 2560, "height": 1440}}
NUMBER = "+919000000001"  # made up


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


def _shot(c: Calls, name: str, panel: str = "#p-calls") -> None:
    if not SHOTS:
        return
    folder = Path(SHOTS)
    folder.mkdir(parents=True, exist_ok=True)
    c.page.screenshot(path=str(folder / f"{name}.png"))
    body = c.page.locator(f"{panel} .pbody").first
    if body.evaluate("b => b.scrollHeight > b.clientHeight + 8"):
        body.evaluate("b => { b.scrollTop = b.scrollHeight; }")
        c.page.wait_for_timeout(150)
        c.page.screenshot(path=str(folder / f"{name}-end.png"))
        body.evaluate("b => { b.scrollTop = 0; }")


def _calls_rows() -> list[dict[str, Any]]:
    """The four Phone calls rows as the real sources describe them over made-up data."""
    from calls_a1_fakes import UID, api, known, rig

    from jarvis.calls.hub import DeskDoorService, DeskStore
    from jarvis.calls.models import CallRecord, Direction
    from jarvis.calls.privacy import calls_privacy_sources
    from jarvis.keyring import Keyring

    class _Hub:
        async def drop_desk(self, uid: str) -> None:
            return None

    async def build() -> list[dict[str, Any]]:
        r = await rig()
        await known(r.store)
        rec = CallRecord(
            id="call_00000000000a", card_id="cc_00000000000a", direction=Direction.OUTGOING,
            number_e164=NUMBER, started_at=datetime(2026, 11, 27, 8, 35, tzinfo=UTC),
        )  # fmt: skip
        await r.store.put_record(UID, rec)
        desks = DeskStore(r.store.docs, Keyring(bytes(range(32))).cipher("calls"), prefix="test_")
        await desks.link(UID, "h_0000000a", bytes(32), "18.0.0")
        rows = calls_privacy_sources(r.store, api(r).keeper, desks, DeskDoorService(desks, _Hub()))  # type: ignore[arg-type]
        return [(await row.describe(UID)).model_dump(mode="json") for row in rows]

    with ThreadPoolExecutor(1) as pool:  # Playwright's own loop runs in this thread
        return pool.submit(asyncio.run, build()).result()


def _pending_call() -> list[dict[str, Any]]:
    """A waiting `calls_place` card as GET /v1/approvals answers it (`PendingApproval`)."""
    from jarvis.core.guardrails import ActionRisk, AskReason, PendingAction
    from jarvis.core.models import PendingApproval

    action = PendingAction(
        tool="calls_place",
        arguments={
            "number": NUMBER,
            "purpose": "Book a laundry pickup",
            "languages": ["ml-IN", "en-IN"],
            "max_minutes": 6,
        },
        risk=ActionRisk.IRREVERSIBLE,
        tool_risk=ActionRisk.IRREVERSIBLE,
        reason=AskReason.RISK,
        summary="Call the number ending 0001: Book a laundry pickup · Malayalam, English · up to 6 min · about ₹1.10",
        scope="owner:s_review",
    )
    return [PendingApproval.from_action(action).model_dump(mode="json")]


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(LAPTOPS))
def test_review_every_changed_screen_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Calls(browser, server_url, token, LAPTOPS[vp])
    rows, pending = _calls_rows(), _pending_call()

    def privacy(route: Any) -> None:
        if route.request.method != "GET":
            return route.continue_()
        real = route.fetch().json()
        route.fulfill(json={**real, "categories": [*real["categories"], *rows]})

    c.page.route("**/v1/privacy", privacy)
    c.page.route(
        "**/v1/approvals",
        lambda r: r.fulfill(json=pending) if r.request.method == "GET" else r.continue_(),
    )
    try:
        c.open()
        if surface == "day":
            c.choose_day()
        tag = f"{vp}-{surface}"
        if c.page.locator('.dk[data-open="calls"]').is_visible():
            c.open_panel("calls")
        else:  # 1920: the owner's dock has no Calls tab; Vitals' line and ?open=calls reach it
            c.page.goto(c.url + "/?open=calls")
            c.page.locator("#p-calls").wait_for(state="visible")
        c.page.locator("#p-calls .cl-ready .vt-chip").first.wait_for()
        # Settings: the server's limits and prices, and Unlink
        c.tab("Settings")
        pane = c.pane("settings")
        until(
            c.page,
            lambda: pane.get_by_label("Calls in a month, in rupees").input_value() == "200",
            "settings",
        )
        until(c.page, lambda: "10 calls a day" in c.text("#clp-settings"), "the server's limits")
        _gate(c, "#p-calls", "desktop", f"settings {tag}")
        _shot(c, f"settings-{tag}")
        c.button("Unlink", "#clp-settings").scroll_into_view_if_needed()
        c.button("Unlink", "#clp-settings").click()
        pane.locator(".mbox").wait_for(state="visible")
        _gate(c, "#p-calls", "desktop", f"unlink {tag}")
        _shot(c, f"settings-unlink-{tag}")
        c.button("Not now", "#clp-settings").click()
        # Languages: Score the voice, its box, the estimate's words
        c.tab("Languages")
        langs = c.pane("langs")
        langs.locator(".hp-row").first.wait_for()
        _gate(c, "#p-calls", "desktop", f"languages {tag}")
        _shot(c, f"languages-{tag}")
        langs.get_by_role("button", name="Score the voice: Malayalam").click()
        langs.locator(".cl-score").wait_for(state="visible")
        langs.locator(".cl-score").get_by_role("radiogroup", name="Sample 1").get_by_text(
            "4", exact=True
        ).click()
        _gate(c, "#p-calls", "desktop", f"score {tag}")
        _shot(c, f"languages-score-{tag}")
        c.button("Not now", "#clp-langs .cl-score").click()
        c.button("Run language check", "#clp-langs").click()
        langs.locator(".mbox", has_text="Left out: Bhashini").wait_for(state="visible")
        _gate(c, "#p-calls", "desktop", f"estimate {tag}")
        _shot(c, f"languages-estimate-{tag}")
        c.button("Not now", "#clp-langs").click()
        # Privacy: the Phone calls rows
        c.open_panel("privacy")
        c.page.locator("#p-privacy", has_text="Your calls").wait_for()
        c.page.locator("#p-privacy", has_text="Your calls").get_by_text(
            "Your calls"
        ).first.scroll_into_view_if_needed()
        _gate(c, "#p-privacy", "desktop", f"privacy {tag}")
        _shot(c, f"privacy-calls-{tag}", "#p-privacy")
        assert "Phone calls" in str(c.page.locator("#p-privacy").text_content())
        # Approvals: a waiting call, its number masked
        c.open_panel("approvals")
        card = c.page.locator("#approvals .approval").first
        card.wait_for()
        shown = str(card.text_content())
        assert NUMBER not in shown and "9000000001" not in shown and "…0001" in shown
        _gate(c, "#p-approvals", "desktop", f"approvals {tag}")
        _shot(c, f"approvals-call-{tag}", "#p-approvals")
        # Vitals' calls line
        c.open_panel("vitals")
        until(
            c.page,
            lambda: (c.page.locator("#sCalls").text_content() or "").startswith("≈"),
            "the calls line",
        )
        c.page.locator("#sCalls").scroll_into_view_if_needed()
        _gate(c, "#p-vitals", "desktop", f"vitals {tag}")
        _shot(c, f"vitals-{tag}", "#p-vitals")
        c.clean()
    finally:
        c.close()


def test_review_the_shots_folder_is_never_committed() -> None:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    probe = "build/r18-review-shots/settings-1920-night.png"
    done = subprocess.run(["git", "check-ignore", "-q", probe], cwd=root, check=False)
    assert done.returncode == 0  # git ignores it
