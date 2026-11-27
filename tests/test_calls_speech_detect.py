# tests/test_calls_speech_detect.py — R18 B: language detection across the options (the option's
# own detection where it has one, else one try per candidate scored by confidence and script) and
# the in-call decision: stay, switch (allowed and confident), or "not supported".
from __future__ import annotations

from collections.abc import Sequence

import pytest
from calls_speech_fakes import FakeHearing, tone

from jarvis.calls.models import Heard
from jarvis.calls.speech.detect import (
    CONFIDENT,
    NativeDetector,
    TryEachDetector,
    decide,
    detector_for,
    dominant_script,
    script_fits,
)


def test_dominant_script_reads_the_majority_of_letters() -> None:
    assert dominant_script("नमस्ते JARVIS जी") == "DEVANAGARI"
    assert dominant_script("ஆம், நாளை 10 மணிக்கு") == "TAMIL"
    assert dominant_script("ہاں جی") == "ARABIC"
    assert dominant_script("Yes, tomorrow") == "LATIN"
    assert dominant_script("10:30 !") is None


@pytest.mark.parametrize(
    ("text", "lang", "fits"),
    [
        ("হ্যাঁ", "bn-IN", True),
        ("হয়", "as-IN", True),  # Assamese writes in the Bengali script
        ("नमस्ते", "mr-IN", True),
        ("नमस्ते", "ta-IN", False),
        ("ہاں", "ur-IN", True),
        ("", "ml-IN", True),  # nothing to judge
        ("10 30", "kn-IN", True),
    ],
)
def test_script_fits(text: str, lang: str, fits: bool) -> None:
    assert script_fits(text, lang) is fits


async def test_native_detection_trusts_the_option_but_checks_the_script() -> None:
    h = FakeHearing("google", texts={"kn-IN": "ಹೌದು"}, confidence=0.9, detected="kn-IN")
    lang, conf = await NativeDetector(h).detect(tone(1.0), ["en-IN", "kn-IN"])
    assert (lang, conf) == ("kn-IN", 0.9)
    assert h.calls == [(32_000, ("en-IN", "kn-IN"))]  # one request, every candidate

    wrong = FakeHearing("google", texts={"kn-IN": "hello there"}, confidence=0.9, detected="kn-IN")
    lang, conf = await NativeDetector(wrong).detect(tone(1.0), ["en-IN", "kn-IN"])
    assert lang == "kn-IN" and conf < CONFIDENT


class PerLanguage(FakeHearing):
    """Answers each language asked with its own (text, confidence)."""

    def __init__(self, scores: dict[str, tuple[str, float]]) -> None:
        super().__init__("azure")
        self.scores = scores

    async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Heard:
        heard = await super().transcribe(pcm16k, languages)
        text, conf = self.scores[languages[0]]
        return heard.model_copy(update={"text": text, "confidence": conf})


async def test_try_each_picks_the_most_confident_in_its_own_script() -> None:
    h = PerLanguage(
        {
            "en-IN": ("hah con call", 0.62),
            "hi-IN": ("हाँ कल कॉल", 0.81),
            "ta-IN": ("हाँ कल", 0.85),  # Tamil asked, Devanagari came back: the script disagrees
        }
    )
    lang, conf = await TryEachDetector(h).detect(tone(1.0), ["en-IN", "hi-IN", "ta-IN"])
    assert lang == "hi-IN" and conf == pytest.approx(0.81)
    assert [c[1][0] for c in h.calls] == ["en-IN", "hi-IN", "ta-IN"]  # one language each, in turn


async def test_try_each_is_bounded_and_keeps_the_first_on_a_tie() -> None:
    h = PerLanguage({c: ("", 0.5) for c in ("en-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN")})
    lang, _ = await TryEachDetector(h).detect(tone(1.0), list(h.scores))
    assert lang == "en-IN" and len(h.calls) == 4  # English + up to 3 Indian languages a card


def test_each_option_gets_its_strategy() -> None:
    assert isinstance(detector_for(FakeHearing("google")), NativeDetector)
    assert isinstance(detector_for(FakeHearing("sarvam")), NativeDetector)
    for name in ("azure", "bhashini", "laptop"):
        assert isinstance(detector_for(FakeHearing(name)), TryEachDetector)


def test_decide_switches_only_to_an_allowed_language_it_is_sure_of() -> None:
    allowed = ("en-IN", "ml-IN", "ta-IN")
    assert decide("en-IN", "ml-IN", 0.9, allowed).kind == "switch"
    assert decide("en-IN", "ml-IN", 0.9, allowed).lang == "ml-IN"
    assert decide("en-IN", "ml-IN", CONFIDENT - 0.01, allowed).kind == "stay"
    assert decide("ml-IN", "ml-IN", 0.99, allowed).kind == "stay"
    unsupported = decide("en-IN", "bn-IN", 0.9, allowed)
    assert unsupported.kind == "unsupported" and unsupported.lang == "bn-IN"
    assert decide("en-IN", "bn-IN", 0.5, allowed).kind == "stay"
