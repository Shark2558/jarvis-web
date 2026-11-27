# tests/test_calls_speech_meter.py — R18 B: every rupee of a call's speech through jarvis.billing:
# Google on the voice's shared free allowance then priced, Azure F0 held against its allowance
# (it cannot bill: used up is said plainly), Sarvam priced in rupees under the owner's limit.
from __future__ import annotations

import pytest
from calls_speech_fakes import RATE, UID, billing, set_limit

from jarvis.calls.speech.errors import AllowanceUsedUp, OptionUnavailable
from jarvis.calls.speech.meter import CALLS_LABEL, FreeAllowance, SpeechMeter
from jarvis.voice.catalogue import Price

STT = Price("stt_seconds", 0.024 / 60, 60.0)  # the voice's own key: one allowance for both


async def test_google_inside_the_free_allowance_costs_nothing_and_is_counted() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await m.gate("google", STT, 30)
    assert await m.charge(STT, 30) == 0.0
    a = await b.allowance(["stt_seconds"])
    assert a.used("stt_seconds") == 30


async def test_google_prices_only_what_is_past_the_allowance() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await m.charge(STT, 50)
    inr = await m.charge(STT, 20)
    assert inr == pytest.approx(10 * 0.024 / 60 * RATE, rel=1e-6)
    month = await b.month(UID)
    assert month.by_brain_inr[CALLS_LABEL] == pytest.approx(inr, rel=1e-6)


async def test_google_past_the_allowance_at_the_limit_is_refused() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await set_limit(b, UID, 1)
    await m.charge(STT, 60)  # the allowance, used up
    await m.charge(Price("stt_seconds", 1.0, 60.0), 1)  # ₹95: past the ₹1 limit
    with pytest.raises(OptionUnavailable) as e:
        await m.gate("google", STT, 5)
    assert e.value.reason == "budget" and e.value.option == "google"


async def test_a_free_tier_is_held_and_given_back() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    azure = FreeAllowance("azure_stt_seconds", 100.0, "hearing")
    hold = await m.hold("azure", azure, 60)
    assert (await b.allowance(["azure_stt_seconds"])).used("azure_stt_seconds") == 60
    await m.give_back(hold)
    assert (await b.allowance(["azure_stt_seconds"])).used("azure_stt_seconds") == 0
    assert (await b.month(UID)).inr_total == 0  # never priced


async def test_a_used_up_free_tier_says_so_plainly() -> None:
    m = SpeechMeter(billing(), UID)
    azure = FreeAllowance("azure_tts_chars", 100.0, "voice")
    await m.hold("azure", azure, 90)
    with pytest.raises(AllowanceUsedUp) as e:
        await m.hold("azure", azure, 20)
    assert "free allowance for voice is used up" in str(e.value)


async def test_the_free_allowance_left_is_read_for_estimates() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await m.charge(STT, 45)
    assert await m.left("google", "stt_seconds", 60.0) == 15.0
    assert await m.left("google", "stt_seconds", 30.0) == 0.0


async def test_rupee_prices_are_charged_exactly_in_rupees() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await m.gate_inr("sarvam", "sarvam_stt_seconds", 120)
    inr = await m.charge_inr("sarvam_stt_seconds", 120, 30.0 / 3600)
    assert inr == pytest.approx(1.0, abs=1e-5)
    assert (await b.month(UID)).by_brain_inr[CALLS_LABEL] == pytest.approx(1.0, abs=1e-5)


async def test_rupee_prices_at_the_limit_are_refused() -> None:
    b = billing()
    m = SpeechMeter(b, UID)
    await set_limit(b, UID, 1)
    await m.charge_inr("sarvam_tts_chars", 1_000, 0.003 * 400)  # ₹1,200
    with pytest.raises(OptionUnavailable) as e:
        await m.gate_inr("sarvam", "sarvam_tts_chars", 10)
    assert e.value.reason == "budget"


async def test_costs_reach_the_sink() -> None:
    seen: list[tuple[str, float | None]] = []
    m = SpeechMeter(billing(), UID, on_cost=lambda part, inr: seen.append((part, inr)))
    m.report("hearing", 0.5)
    m.report("voice", None)
    assert seen == [("hearing", 0.5), ("voice", None)]
