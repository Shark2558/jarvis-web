# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_fixes.py — R5 workstream A, the fixer's regression tests (code + security
# review of r5-a): the Web Speech phrases refusal (V1), the bounds of a hands-free conversation (H1, SH1),
# the check-in (M2), handover races (M1), the mic lock hardening (SM1, SM6), echo guards (SM3, SM4),
# check clips (SM5), and the small ones. Each test names the finding it proves.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import FAKE_RECOGNITION, FakeVoice, _mic_state, _wait
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    FAST_TV,
    SLOW_GUM,
    STALL,
    TONE_MIC,
    _chat_counter,
    _count,
    _line,
    _mic_file,
    _playwright,
    _until,
    browser,
    make,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# V1: a recogniser that, like Chrome 140+ in the cloud mode, refuses to start once it was given phrases.
# The phrases module (part C) is replaced after load by a counter that sets `phrases` on the recogniser.
PHRASE_REFUSING_REC = """
(() => {
  window.__applied = 0; window.__starts = [];
  window.addEventListener('load', () => {
    const Base = window.SpeechRecognition;
    class R2 extends Base {
      start() {
        window.__starts.push((this.phrases || []).length);
        if (this.phrases && this.phrases.length) {
          this.done = true;
          setTimeout(() => { this.onerror && this.onerror({ error: 'phrases-not-supported' }); this.onend && this.onend(); }, 10);
          return;
        }
        super.start();
      }
    }
    window.SpeechRecognition = window.webkitSpeechRecognition = R2;
    window.JarvisVoicePhrases = { apply(rec) { window.__applied++; rec.phrases = [{ phrase: 'Trivandrum' }]; return true; } };
  });
})();
"""


# ================================================================== V1
def test_a_browser_that_refuses_phrases_still_listens_and_is_never_offered_them_again(
    make: Callable[..., Console],
) -> None:
    """V1: phrases-not-supported retries the same turn at once without hints; no error line, no help."""
    c = make(
        device={"engine": "browser", "keepListening": False},
        scripts=(FAKE_RECOGNITION, PHRASE_REFUSING_REC),
    )
    FakeVoice(c.page)
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    c.page.locator(".row.user .bubble", has_text="Remind me about the review.").wait_for()
    assert c.page.evaluate("window.__starts") == [
        1,
        0,
    ]  # refused with phrases, then listened without
    assert c.page.evaluate("window.__applied") == 1
    assert _line(c) == "" and c.page.locator("#micHelp").is_hidden()
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'idle'")
    c.page.evaluate("window.__said = 'Second turn please.'")
    c.page.locator("#micBtn").click()
    c.page.locator(".row.user .bubble", has_text="Second turn please.").wait_for()
    assert (
        c.page.evaluate("window.__applied") == 1
    )  # apply() is never called again this page session
    assert len(chats) == 2 and c.errors == []
