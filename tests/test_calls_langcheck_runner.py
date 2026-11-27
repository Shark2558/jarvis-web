# tests/test_calls_langcheck_runner.py — R18 B: the language check end to end on fake options:
# the ₹ estimate first (free inside the allowances, paid refused unless accepted, Sarvam only when
# on, an unknown price only when accepted), hearing on phone-quality clips, the voice round trip
# heard back by another option, speed, the stored results, the owner's score, and selection.
from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from calls_speech_fakes import UID, World, WorldHearing, WorldVoice, billing

from jarvis.calls.langcheck.fleurs import Clip, FleursUnavailable
from jarvis.calls.langcheck.runner import (
    BRAIN_ESTIMATE_S,
    END_OF_TURN_S,
    CheckRefused,
    LanguageCheck,
)
from jarvis.calls.langcheck.select import choose, offered, table
from jarvis.calls.langcheck.sentences import Sentence, english
from jarvis.calls.models import LanguageResult, SpeechOption
from jarvis.calls.prices import speech_prices
from jarvis.calls.speech.build import SpeechOptions
from jarvis.calls.speech.errors import AllowanceUsedUp
from jarvis.calls.speech.meter import SpeechMeter
from jarvis.calls.store import MemoryCallStore
from jarvis.config import Settings

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
TEXTS = [f"वाक्य {i}: दुकान {i + 1}:30 बजे खुलती है।" for i in range(12)] + [
    f"सादा वाक्य {chr(0x915 + i)}" for i in range(8)
]


class Clips:
    def __init__(self, world: World, *, down: bool = False) -> None:
        self.world, self.down, self.asked = world, down, 0

    async def clips(self, lang: str, n: int = 20) -> list[Clip]:
        self.asked += 1
        if self.down:
            raise FleursUnavailable("The test clips could not be fetched from Hugging Face.")
        return [Clip(lang, t, self.world.audio(t)) for t in TEXTS[:n]]


class Sentences:
    async def sentences(self, lang: str) -> list[Sentence]:
        return english()


def setup(
    world: World,
    *,
    hearing: dict[str, WorldHearing] | None = None,
    voices: dict[str, WorldVoice] | None = None,
    sarvam_on: bool = False,
    settings: Settings | None = None,
    clips: Clips | None = None,
) -> tuple[LanguageCheck, MemoryCallStore]:
    s = settings or Settings(_env_file=None)
    store = MemoryCallStore()
    h = hearing if hearing is not None else {
        "google": WorldHearing("google", world), "azure": WorldHearing("azure", world)
    }  # fmt: skip
    v = voices if voices is not None else {
        "google": WorldVoice("google", world), "azure": WorldVoice("azure", world)
    }  # fmt: skip
    check = LanguageCheck(
        speech=SpeechOptions(hearing=h, voices=v, missing={"laptop": "no desk"}),  # type: ignore[arg-type]
        store=store,
        clips=clips or Clips(world),
        sentences=Sentences(),
        meter=SpeechMeter(billing(), UID),
        prices=speech_prices(s, 95.24),
        sarvam_on=sarvam_on,
        clock=world.clock,
        now=lambda: NOW,
    )
    return check, store


# ---- the plan and its ₹ ------------------------------------------------------------------------


async def test_free_options_cost_nothing_and_unbuilt_ones_say_why() -> None:
    check, _ = setup(World())
    plan = await check.plan(["hi-IN"])
    by = {p.option: p for p in plan.pairs}
    assert plan.total_inr == 0.0 and plan.unknown == ()
    assert by["google"].runs and by["azure"].runs
    assert not by["laptop"].runs and by["laptop"].why == "no desk"
    assert by["sarvam"].runs is False and "paid option" in by["sarvam"].why


async def test_google_past_its_free_allowance_is_priced_and_refused_unless_accepted() -> None:
    s = Settings(_env_file=None, voice_stt_free_seconds=100)
    world = World()
    check, _ = setup(world, settings=s)
    plan = await check.plan(["hi-IN"], options=["google"])
    (google,) = plan.pairs
    expected = (20 * 12 + 10 * 3.5 - 100) / 60 * 0.024 * 95.24  # Google alone: judges only itself
    assert google.inr == pytest.approx(expected, abs=0.01)
    with pytest.raises(CheckRefused) as e:
        await check.run(plan)
    assert f"₹{plan.total_inr:.2f}" in str(e.value)
    report = await check.run(plan, accept_inr=plan.total_inr)
    assert len(report.results) == 1


async def test_the_free_allowance_is_spent_across_languages_in_the_plan() -> None:
    s = Settings(_env_file=None, voice_stt_free_seconds=300)
    check, _ = setup(World(), settings=s)
    plan = await check.plan(["hi-IN", "ta-IN"], options=["google"])
    assert plan.pairs[0].inr == 0.0 and (plan.pairs[1].inr or 0) > 0


async def test_azure_without_enough_free_allowance_does_not_run() -> None:
    s = Settings(_env_file=None, voice_azure_f0_stt_free_seconds=60)
    check, _ = setup(World(), settings=s)
    (azure,) = (await check.plan(["hi-IN"], options=["azure"])).pairs
    assert not azure.runs and "free allowance" in azure.why


async def test_an_unknown_price_runs_only_when_accepted() -> None:
    world = World()
    hearing = {"bhashini": WorldHearing("bhashini", world), "azure": WorldHearing("azure", world)}
    voices = {"bhashini": WorldVoice("bhashini", world)}
    check, _ = setup(world, hearing=hearing, voices=voices)  # type: ignore[arg-type]
    plan = await check.plan(["or-IN"], options=["bhashini", "azure"])
    assert [p.option for p in plan.unknown] == ["bhashini"]
    report = await check.run(plan)
    assert "or-IN bhashini" in report.skipped and [r.option for r in report.results] == ["azure"]
    report = await check.run(plan, accept_unknown=True)
    assert {r.option.value for r in report.results} == {"bhashini", "azure"}
    bhashini = next(r for r in report.results if r.option == SpeechOption.BHASHINI)
    assert bhashini.inr_per_minute is None  # never shown as ₹0


async def test_sarvam_runs_only_when_the_owner_turned_it_on() -> None:
    world = World()
    hearing = {"sarvam": WorldHearing("sarvam", world), "azure": WorldHearing("azure", world)}
    voices = {"sarvam": WorldVoice("sarvam", world)}
    check, _ = setup(world, hearing=hearing, voices=voices, sarvam_on=True)  # type: ignore[arg-type]
    (sarvam,) = (await check.plan(["hi-IN"], options=["sarvam"])).pairs
    assert sarvam.runs and sarvam.inr == pytest.approx((275 / 60) * 0.5 + 600 * 0.003, abs=0.01)


async def test_a_hearing_option_s_estimate_counts_judging_the_other_voices() -> None:
    check, _ = setup(World())
    by = {p.option: p for p in (await check.plan(["hi-IN"], options=["google", "azure"])).pairs}
    assert by["google"].hear_seconds == 20 * 12 + 10 * 3.5 + 10 * 3.5  # its own turns + azure's


# ---- the run -----------------------------------------------------------------------------------


async def test_a_clean_language_passes_and_is_stored() -> None:
    world = World()
    check, store = setup(world)
    report = await check.run(await check.plan(["hi-IN"]))
    google = next(r for r in report.results if r.option == SpeechOption.GOOGLE)
    assert google.passed and google.why_failed == ()
    assert (google.hear_facts, google.cer, google.speak_facts) == (1.0, 0.0, 1.0)
    assert google.p50_ms == round((0.2 + END_OF_TURN_S + BRAIN_ESTIMATE_S + 0.3) * 1000)
    assert google.versions["heard_back_by"] == "azure"  # a different option heard it back
    assert google.native_heard is False and google.inr_per_minute == pytest.approx(
        0.024 * 95.24 * 0.5 + 30 / 1e6 * 95.24 * 150, abs=1e-3
    )
    stored = {(r.lang, r.option.value) for r in await store.language_results()}
    assert stored == {("hi-IN", "google"), ("hi-IN", "azure")}


async def test_lost_numbers_fail_hearing_with_plain_words() -> None:
    world = World()
    lossy = WorldHearing("google", world, transform=lambda t: re.sub(r"\d", "", t))
    check, _ = setup(world, hearing={"google": lossy, "azure": WorldHearing("azure", world)})
    report = await check.run(await check.plan(["hi-IN"], options=["google", "azure"]))
    google = next(r for r in report.results if r.option == SpeechOption.GOOGLE)
    assert not google.passed and google.hear_facts == 0.0
    assert any("key facts" in w for w in google.why_failed)


async def test_garbled_text_fails_on_the_character_error_rate() -> None:
    world = World()
    garble = WorldHearing("azure", world, transform=lambda t: t[: len(t) * 3 // 4])
    check, _ = setup(world, hearing={"google": WorldHearing("google", world), "azure": garble})
    report = await check.run(await check.plan(["hi-IN"]))
    azure = next(r for r in report.results if r.option == SpeechOption.AZURE)
    assert not azure.passed and any("character error rate" in w for w in azure.why_failed)


async def test_slow_replies_fail_on_speed() -> None:
    world = World()
    slow = WorldVoice("google", world, latency_s=1.5)
    check, _ = setup(world, voices={"google": slow, "azure": WorldVoice("azure", world)})
    report = await check.run(await check.plan(["hi-IN"]))
    google = next(r for r in report.results if r.option == SpeechOption.GOOGLE)
    assert not google.passed and any("speed" in w for w in google.why_failed)


async def test_no_clips_means_hearing_not_checked_said_plainly() -> None:
    world = World()
    check, _ = setup(world, clips=Clips(world, down=True))
    report = await check.run(await check.plan(["hi-IN"]))
    r = report.results[0]
    assert not r.passed and r.hear_facts is None and r.speak_facts == 1.0
    assert any("could not be fetched" in w for w in r.why_failed)


async def test_one_hearing_option_hears_its_own_voice_back_and_says_so() -> None:
    world = World()
    check, _ = setup(
        world,
        hearing={"google": WorldHearing("google", world)},
        voices={"google": WorldVoice("google", world)},
    )
    (r,) = (await check.run(await check.plan(["hi-IN"]))).results
    assert r.versions["heard_back_by"].startswith("google (the same option")


async def test_a_used_up_free_tier_stops_its_part_at_once() -> None:
    world = World()
    used_up = WorldHearing("azure", world, fail=AllowanceUsedUp("azure", "hearing"))
    check, _ = setup(world, hearing={"google": WorldHearing("google", world), "azure": used_up})
    report = await check.run(await check.plan(["hi-IN"]))
    azure = next(r for r in report.results if r.option == SpeechOption.AZURE)
    assert used_up.calls == 1 and not azure.passed  # never asked again
    assert any("used up" in w for w in azure.why_failed)


async def test_one_check_at_a_time() -> None:
    world = World()
    check, _ = setup(world)
    plan = await check.plan(["hi-IN"])
    async with check._lock:
        with pytest.raises(CheckRefused):
            await check.run(plan)


# ---- the owner's score, selection ------------------------------------------------------------


async def test_the_owner_s_score_decides_and_is_kept_on_a_new_check() -> None:
    world = World()
    check, store = setup(world)
    await check.run(await check.plan(["hi-IN"]))
    low = await check.score("hi-IN", "google", [3, 4, 3])
    assert not low.passed and low.native_heard and low.human_score == pytest.approx(3.33)
    high = await check.score("hi-IN", "google", [4, 5, 4])
    assert high.passed
    await check.run(await check.plan(["hi-IN"]))
    again = next(r for r in await store.language_results() if r.option == SpeechOption.GOOGLE)
    assert again.native_heard and again.human_score == pytest.approx(4.33)
    with pytest.raises(LookupError):
        await check.score("ta-IN", "google", [5])
    with pytest.raises(ValueError):
        await check.score("hi-IN", "google", [])


def result(lang: str, option: str, passed: bool = True, **kw: object) -> LanguageResult:
    fields: dict[str, object] = {
        "hear_facts": 1.0, "cer": 0.05, "speak_facts": 1.0, "p50_ms": 1200, "p90_ms": 2000,
    }  # fmt: skip
    fields.update(kw)
    return LanguageResult(
        lang=lang,
        option=SpeechOption(option),
        checked_at=NOW,
        passed=passed,
        **fields,  # type: ignore[arg-type]
    )


def test_choose_takes_the_first_passing_option_in_the_order() -> None:
    results = [
        result("ml-IN", "azure"),
        result("ml-IN", "google"),
        result("ml-IN", "laptop", False),
    ]
    chosen = choose(results, "ml-IN", sarvam_on=False, allow_balanced=False)
    assert chosen is not None and chosen.option == SpeechOption.GOOGLE


def test_sarvam_and_the_balanced_tier_only_with_his_yes() -> None:
    results = [result("pa-IN", "sarvam"), result("ta-IN", "google", needs_balanced=True)]
    assert choose(results, "pa-IN", sarvam_on=False, allow_balanced=False) is None
    assert choose(results, "pa-IN", sarvam_on=True, allow_balanced=False) is not None
    assert choose(results, "ta-IN", sarvam_on=False, allow_balanced=False) is None
    assert choose(results, "ta-IN", sarvam_on=False, allow_balanced=True) is not None


def test_a_stored_pass_is_re_read_against_the_bars() -> None:
    forged = result("hi-IN", "google", passed=True, cer=0.4)  # "passed", but over the CER bar
    assert choose([forged], "hi-IN", sarvam_on=False, allow_balanced=False) is None


def test_the_table_and_the_offered_languages() -> None:
    results = [
        result("hi-IN", "google"),
        result("or-IN", "azure", False, why_failed=("voice: 70 % of key facts heard",)),
    ]
    rows = {
        r.lang: r
        for r in table(results, ["hi-IN", "or-IN", "as-IN"], sarvam_on=False, allow_balanced=False)
    }
    assert rows["hi-IN"].option == "google" and not rows["hi-IN"].native_heard
    assert rows["or-IN"].option is None and rows["or-IN"].why == (
        "azure: voice: 70 % of key facts heard",
    )
    assert rows["as-IN"].why == ("not checked yet",)
    assert offered(results, sarvam_on=False, allow_balanced=False) == ("hi-IN",)
