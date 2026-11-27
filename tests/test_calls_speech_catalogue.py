# tests/test_calls_speech_catalogue.py — R18 B: the call languages and the options that list them
# (plan 5.2), the check's default set (English + the 12 major Indian languages) and the order.
from __future__ import annotations

import pytest

from jarvis.calls.speech.catalogue import (
    DEFAULT_CHECK,
    LANGUAGES,
    OPTION_ORDER,
    PAID_OPTIONS,
    google_voice,
    hears,
    language,
    speaks,
)


def test_the_order_is_laptop_google_azure_bhashini_then_paid_sarvam() -> None:
    assert OPTION_ORDER == ("laptop", "google", "azure", "bhashini", "sarvam")
    assert PAID_OPTIONS == frozenset({"sarvam"})


def test_the_default_check_is_english_and_the_twelve_major_languages() -> None:
    assert DEFAULT_CHECK == (
        "en-IN", "hi-IN", "bn-IN", "mr-IN", "te-IN", "ta-IN", "gu-IN", "kn-IN", "ml-IN",
        "ur-IN", "or-IN", "pa-IN", "as-IN",
    )  # fmt: skip
    assert all(LANGUAGES[c].fleurs for c in DEFAULT_CHECK)  # every one has FLEURS test clips


def test_all_22_scheduled_languages_are_listed() -> None:
    assert len([c for c in LANGUAGES if c != "en-IN"]) == 22


@pytest.mark.parametrize(
    ("code", "hear", "speak"),
    [
        ("en-IN", {"laptop", "google", "azure", "sarvam"}, {"google", "azure", "sarvam"}),
        ("ur-IN", {"laptop", "google", "azure", "bhashini"}, {"google", "azure", "bhashini"}),
        (
            "or-IN",
            {"laptop", "azure", "bhashini", "sarvam"},
            {"laptop", "azure", "bhashini", "sarvam"},
        ),
        ("as-IN", {"laptop", "google", "azure", "bhashini"}, {"laptop", "azure", "bhashini"}),
        ("kok-IN", {"laptop", "bhashini"}, {"laptop", "bhashini"}),
    ],
)
def test_the_listed_options_follow_the_plan(code: str, hear: set[str], speak: set[str]) -> None:
    assert set(LANGUAGES[code].hear) == hear and set(LANGUAGES[code].speak) == speak
    assert all(hears(o, code) for o in hear) and all(speaks(o, code) for o in speak)


def test_every_azure_voice_is_a_stock_neural_voice_of_its_language() -> None:
    for code, lang in LANGUAGES.items():
        if "azure" in lang.speak:
            assert lang.azure_voice and lang.azure_voice.startswith(code + "-")
            assert lang.azure_voice.endswith("Neural")


def test_unknown_languages() -> None:
    assert not hears("google", "xx-YY") and not speaks("azure", "xx-YY")
    with pytest.raises(KeyError):
        language("xx-YY")
    assert google_voice("hi-IN") == "hi-IN-Chirp3-HD-Algieba"
