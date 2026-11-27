"""R18 A2: live captions (English of each utterance) and the English summary after a call
(BUILD-BRIEF row A2 item 7; docs/plans/r18-calls.md 4.7-4.8)."""

from __future__ import annotations

import json

from jarvis.calls.brain import CallBrief, Line
from jarvis.calls.captions import Captioner, english_of
from jarvis.calls.summary import Summarizer, fallback_summary
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier

TIERS = {t: "mock" for t in ModelTier}
BRIEF = CallBrief(first_name="Asha", purpose="Book a laundry pickup", languages=("en-IN", "ml-IN"))


def _registry(provider: MockProvider) -> BrainRegistry:
    spec = BrainSpec(id="anthropic", label="Claude", provider=provider, tiers=TIERS)
    return BrainRegistry([spec], default_id="anthropic")


async def test_english_lines_need_no_model_call() -> None:
    provider = MockProvider()
    caption = await Captioner(_registry(provider)).english("Hello there", "en-IN")
    assert caption.english == "Hello there"
    assert caption.completion is None
    assert provider.calls == []


async def test_other_languages_are_translated_on_the_fast_tier_as_data() -> None:
    provider = MockProvider()
    provider.script("Tomorrow at ten is fine.")
    caption = await Captioner(_registry(provider)).english("നാളെ പത്തിന് ശരി", "ml-IN")
    assert caption.english == "Tomorrow at ten is fine."
    assert caption.completion is not None
    call = provider.calls[-1]
    assert call.tools is None
    assert "untrusted" in call.system.lower()
    assert "നാളെ" in call.messages[-1].text()


async def test_a_failed_translation_is_an_empty_caption_not_an_error() -> None:
    provider = MockProvider()
    provider.fail_next = 1
    caption = await Captioner(_registry(provider)).english("നാളെ", "ml-IN")
    assert caption.english == ""
    assert caption.failed


async def test_a_translation_is_cut_to_one_short_line() -> None:
    provider = MockProvider()
    provider.script("word " * 400)
    caption = await Captioner(_registry(provider)).english("നാളെ", "ml-IN")
    assert len(caption.english) <= 600


def test_english_of_prefers_the_line_english() -> None:
    assert english_of(Line(who="them", lang="ml-IN", text="നാളെ", english="Tomorrow")) == "Tomorrow"
    assert english_of(Line(who="them", lang="en-IN", text="Tomorrow")) == "Tomorrow"
    assert english_of(Line(who="them", lang="ml-IN", text="നാളെ")) == "[ml-IN] നാളെ"


async def test_summary_reads_the_json_and_sees_the_transcript_as_data() -> None:
    provider = MockProvider()
    provider.script(
        json.dumps(
            {
                "summary": "The laundry will pick up on 28 Nov at 10:00.",
                "agreed": ["Pickup 28 Nov 10:00"],
                "next_steps": ["Keep the clothes ready"],
                "needs_you": [],
            }
        )
    )
    lines = [
        Line(who="jarvis", lang="en-IN", text="Hello, this is JARVIS."),
        Line(who="them", lang="ml-IN", text="ശരി", english="Okay, 10:00 tomorrow."),
    ]
    result = await Summarizer(_registry(provider)).summarize(
        BRIEF, lines, outcome="completed", booking="2026-11-28 10:00", notes=("Ref 45678",)
    )
    assert result.summary.text.startswith("The laundry will pick up")
    assert result.summary.agreed == ["Pickup 28 Nov 10:00"]
    call = provider.calls[-1]
    assert "Okay, 10:00 tomorrow." in call.messages[-1].text()
    assert "Ref 45678" in call.messages[-1].text()
    assert "untrusted" in call.system.lower()


async def test_summary_falls_back_without_the_model() -> None:
    provider = MockProvider()
    provider.script("no json here")
    result = await Summarizer(_registry(provider)).summarize(
        BRIEF, [], outcome="no_answer", booking=None, notes=()
    )
    assert "did not answer" in result.summary.text
    assert result.completion is not None  # still metered


async def test_summary_survives_an_llm_error() -> None:
    provider = MockProvider()
    provider.fail_next = 1
    result = await Summarizer(_registry(provider)).summarize(
        BRIEF, [], outcome="cap_minutes", booking=None, notes=()
    )
    assert "time limit" in result.summary.text
    assert result.completion is None


def test_fallback_summary_names_the_booking() -> None:
    s = fallback_summary(BRIEF, outcome="completed", booking="2026-11-28 10:00", notes=())
    assert "2026-11-28 10:00" in s.text
    assert s.needs_you == []
