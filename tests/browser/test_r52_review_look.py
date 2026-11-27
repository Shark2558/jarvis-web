# tests/browser/test_r52_review_look.py -- R5.2 combined review: the visual gate for R5.2's new and
# changed screens, at the owner's two laptop widths (1920 x 1080 and 2560 x 1440), Night and Day,
# each through the console's own DOM checks (tests/browser/test_r18_e_look.py's `_gate`: no
# overlaps, theme fonts only, no browser-default controls, nothing overflowing, every control named,
# contrast). The screens: Voice -> "Your voice" after a scored session (the engines ranked, the
# corrections switch, Check again, Delete, the two Train buttons), the speaker check, the voice
# session pop-up (its start and a line to read), the Privacy panel's three voice rows (built by
# `jarvis.voice.session_privacy` over a scored session on the in-memory kit) and Vitals' "Laptop
# speech kit" line (built by `jarvis.vitals.own` over the in-memory kit). The /v1/voice/profile
# routes are V3's browser fake. R18's 1920 px dock is untouched: no tab added, none moved. Shots
# only when R52_REVIEW_SHOTS names a folder (build/r52-review-shots/, never committed).
# ruff: noqa: E501 -- selectors
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_console import Console
from test_r18_e_look import _gate
from test_r52_v3_voice_session import PROMPTS, FakeProfile
from test_voice import speechlike_wav

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R52_REVIEW_SHOTS", "")
LAPTOPS = {"1920": {"width": 1920, "height": 1080}, "2560": {"width": 2560, "height": 1440}}


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mic = tmp_path_factory.mktemp("voice") / "speech.wav"
    speechlike_wav(mic)
    args = [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={mic}",
    ]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


def _run(coro: Any) -> Any:
    with ThreadPoolExecutor(1) as pool:  # Playwright's own loop runs in this thread
        return pool.submit(asyncio.run, coro).result()


def _privacy_rows() -> list[dict[str, Any]]:
    """The three voice rows as the real sources describe them over a scored session."""
    from r52_v3_fakes import UID
    from test_r52_v3_privacy import _scored

    from jarvis.voice.session_privacy import voice_session_sources

    async def build() -> list[dict[str, Any]]:
        sessions, _, _ = await _scored()
        rows = voice_session_sources(sessions)
        return [(await row.describe(UID)).model_dump(mode="json") for row in rows]

    return list(_run(build()))


def _vitals_item() -> dict[str, Any]:
    """Vitals' "Laptop speech kit" item as the real board builds it over the in-memory kit."""
    from r51b_fakes import OwnRig, with_keys

    from jarvis.localspeech import protocol as p
    from jarvis.localspeech.memory import MemoryKit
    from jarvis.vitals.own import OwnSources
    from jarvis.voice.laptop import LaptopVoice

    async def build() -> dict[str, Any]:
        laptop = LaptopVoice(MemoryKit(), health_s=30)
        one_second = b"\x01\x00" * p.SAMPLE_RATE
        await laptop.stt.recognize(one_second, sample_rate=16_000, language="en-IN", phrases=())
        laptop.note_served(p.Kind.TTS, "google")
        board = await OwnRig(OwnSources(voice=laptop), settings=with_keys()).svc.board("u_owner")
        items = board.to_json()["items"]
        return dict(next(i for i in items if i["id"] == "voice_laptop"))

    return dict(_run(build()))


def _shot(c: Console, name: str) -> None:
    if not SHOTS:
        return
    folder = Path(SHOTS)
    folder.mkdir(parents=True, exist_ok=True)
    c.page.screenshot(path=str(folder / f"{name}.png"))


def _scored(fake: FakeProfile) -> None:
    fake.state, fake.scored, fake.done = "done", True, [p["id"] for p in PROMPTS]


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(LAPTOPS))
def test_review_every_new_voice_screen_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Console(browser, server_url, token, LAPTOPS[vp])
    c.page.route(  # the real wake-word detector is tested on its own (it loads its models)
        "**/static/console-wakeword.js",
        lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
    )
    c.page.add_init_script("localStorage.setItem('jarvis_voice_session_browser_v1', 'off');")
    fake = FakeProfile(c.page)
    _scored(fake)
    rows, item = _privacy_rows(), _vitals_item()

    def privacy(route: Any) -> None:
        if route.request.method != "GET":
            return route.continue_()
        real = route.fetch().json()  # the wired app's own voice rows (no kit: empty) replaced
        ours = {r["id"]: r for r in rows}
        kept = [ours.pop(c["id"], c) for c in real["categories"]]
        route.fulfill(json={**real, "categories": [*kept, *ours.values()]})

    def vitals(route: Any) -> None:
        if route.request.method != "GET":
            return route.continue_()
        real = route.fetch().json()
        route.fulfill(json={**real, "items": [*real["items"], item]})

    c.page.route("**/v1/privacy", privacy)
    c.page.route("**/v1/vitals", vitals)
    try:
        c.open()
        if surface == "day":
            c.choose_day()
        tag = f"{vp}-{surface}"
        if vp == "1920":  # R18's dock rule (all of it: test_dock_fit, test_r18_calls_ways_in)
            assert c.page.locator('.dk[data-open="calls"]').is_hidden()
        c.open_panel("voice")
        # Voice -> Your voice, after a scored session (with the Train buttons)
        sec = c.page.locator("#vSlotProfile")
        sec.get_by_text("Best for your voice: Laptop: Whisper small.").wait_for()
        c.page.locator("#vProfileTrain").wait_for(state="visible")
        sec.scroll_into_view_if_needed()
        _gate(c, "#p-voice", "desktop", f"your voice {tag}")  # type: ignore[arg-type]
        _shot(c, f"voice-your-voice-{tag}")
        # the speaker check (no model in the slot: it says so; Record hidden, not faded)
        speaker = c.page.locator("#vSlotSpeaker")
        speaker.get_by_text("Speaker check").first.wait_for()
        speaker.scroll_into_view_if_needed()
        _gate(c, "#p-voice", "desktop", f"speaker check {tag}")  # type: ignore[arg-type]
        _shot(c, f"voice-speaker-check-{tag}")
        # the voice session pop-up: its start, then a line to read
        c.page.locator("#vProfileStart").click()
        dlg = c.page.locator("#vsDlg")
        dlg.wait_for(state="visible")
        c.page.locator("#vsStart").wait_for()
        _gate(c, "#vsDlg", "desktop", f"session start {tag}")  # type: ignore[arg-type]
        _shot(c, f"voice-session-start-{tag}")
        fake.state, fake.scored, fake.done = "recording", False, []
        c.page.locator("#vsStart").click()
        c.page.locator("#vsLine").wait_for()
        _gate(c, "#vsDlg", "desktop", f"session line {tag}")  # type: ignore[arg-type]
        _shot(c, f"voice-session-line-{tag}")
        c.page.keyboard.press("Escape")
        dlg.wait_for(state="hidden")
        # Privacy: the three voice rows
        c.open_panel("privacy")
        row = c.page.locator("#p-privacy", has_text="Voice session recordings")
        row.wait_for()
        row.get_by_text("Your voice profile").first.scroll_into_view_if_needed()
        _gate(c, "#p-privacy", "desktop", f"privacy {tag}")  # type: ignore[arg-type]
        _shot(c, f"privacy-voice-{tag}")
        text = str(c.page.locator("#p-privacy").text_content())
        assert "Wake-word files from your voice" in text and "encrypted by the speech kit" in text
        assert "120 recordings" in text
        # Vitals: the laptop speech kit's line
        c.open_panel("vitals")
        line = c.page.locator("#p-vitals", has_text="Laptop speech kit")
        line.wait_for()
        line.get_by_text("Laptop speech kit").first.scroll_into_view_if_needed()
        _gate(c, "#p-vitals", "desktop", f"vitals {tag}")  # type: ignore[arg-type]
        _shot(c, f"vitals-laptop-line-{tag}")
        assert "₹0 a minute" in str(c.page.locator("#p-vitals").text_content())
        assert json.dumps(item).count("ts.net") == 0  # never the laptop's name
        refused = ("404", "/v1/voice/profile/wakeword")  # V3's fake has no wake-word routes
        assert not [e for e in c.errors if not all(x in e for x in refused)], c.errors
        assert not c.csp_violations()
    finally:
        c.close()


def test_review_the_shots_folder_is_never_committed() -> None:
    import subprocess

    root = Path(__file__).resolve().parents[2]
    probe = "build/r52-review-shots/voice-your-voice-1920-night.png"
    done = subprocess.run(["git", "check-ignore", "-q", probe], cwd=root, check=False)
    assert done.returncode == 0  # git ignores it
