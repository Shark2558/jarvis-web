# tests/browser/test_voice_live.py — the console's voice against the REAL /v1/voice backend.
# test_voice.py pins the console's side of the contract with a page.route fake; this file runs the
# real app (voice_live_server.py: only Google's TTS / STT are faked, from tests/voice_fakes.py) so a
# drift between that fake and the real API fails here. Covers: the Voice panel's GET / PUT round
# trip and a preview, then a whole spoken turn — the fake microphone → the real WAV check and
# transcription → the chat with channel "voice" → the reply spoken through the real /speak in
# order — and the allowance counting it, with 0 JS errors and 0 CSP reports.
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP, Console
from test_voice import RECORDER, _speech, _voice_panel, _wait, browser  # noqa: F401

pytestmark = pytest.mark.browser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOKEN = "browser-test-token-not-a-secret"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_url() -> Iterator[str]:
    """The real app with fake Google speech engines (and the mock brain), bearer-token auth."""
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    port = _port()
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
        # One server serves the whole suite from one IP; the app's 120/min per-IP limit (unit-tested
        # in tests/) would turn a fast CI runner's requests into 429s. Per-owner voice limits stay.
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
        "JARVIS_VOICE_CLOUD": "true",
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "voice_live_server.py"), str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise RuntimeError(f"voice live server exited early:\n{err}")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            if time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError("voice live server did not become healthy") from None
            time.sleep(0.2)
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def make(browser: Any, live_url: str) -> Iterator[Callable[..., Console]]:  # noqa: F811
    made: list[Console] = []

    def factory(device: dict[str, Any] | None = None) -> Console:
        c = Console(browser, live_url, TOKEN, DESKTOP)
        c.page.add_init_script(RECORDER)
        if device is not None:
            c.page.add_init_script(
                f"localStorage.setItem('jarvis_voice_device_v1', {json.dumps(json.dumps(device))});"
            )
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _view(c: Console) -> Any:
    return c.page.evaluate(
        "async (t) => (await fetch('/v1/voice',"
        " {headers: {'Authorization': 'Bearer ' + t}})).json()",
        TOKEN,
    )


def test_live_voice_panel_round_trip_and_preview(make: Callable[..., Console]) -> None:
    c = make()
    c.open()
    panel = _voice_panel(c)
    view = _view(c)
    shown = panel.locator("#vVoiceT ~ .vlist .vlab b").all_text_contents()
    assert shown == [v["label"] for v in view["voices"] if v["available"]] and len(shown) >= 2
    assert "Cloud voice ready" in str(panel.locator("#voiceStatus").text_content())
    allowance = str(panel.locator("#vAllow").text_content())
    assert (
        allowance.startswith("This month: ") and "free characters" in allowance and "₹" in allowance
    )
    assert "$" not in str(panel.text_content())
    # the wit level saves through the real PUT and reads back
    panel.locator("label", has_text=view["wit_levels"][2]["label"]).click()
    c.page.locator("#voiceNote.ok").wait_for()
    assert _view(c)["settings"]["wit"] == view["wit_levels"][2]["id"]
    panel.locator("label", has_text=view["wit_levels"][1]["label"]).click()  # back to the default
    for _ in range(50):
        if _view(c)["settings"]["wit"] == view["wit_levels"][1]["id"]:
            break
        c.page.wait_for_timeout(100)
    assert _view(c)["settings"]["wit"] == view["wit_levels"][1]["id"]
    # ▶ Preview: the real /speak answers audio the page decodes and plays
    panel.locator("#vPrev-1").click()
    _wait(c, "() => window.__voice.speech.length >= 1")
    assert c.errors == [] and c.csp_violations() == []


def test_live_spoken_turn_end_to_end(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False})
    c.open()
    before = _view(c)["allowance"]
    c.page.locator("#micBtn").click()
    # the fake microphone's speech → the real server accepts the WAV and "transcribes" it
    c.page.locator(".row.user .bubble", has_text="Turn on the lights.").wait_for(timeout=20000)
    assert "Spoken" in str(c.page.locator(".row.user .meta").text_content())
    _wait(c, "() => window.__voice.speech.length >= 2")
    assert _speech(c) == ["Certainly, Sir.", "You said: Turn on the lights. Then dim them to half."]
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'idle'")
    after = _view(c)["allowance"]
    assert after["tts"]["used_chars"] > before["tts"]["used_chars"]
    assert after["stt"]["used_seconds"] > before["stt"]["used_seconds"]
    assert c.errors == [] and c.csp_violations() == []
