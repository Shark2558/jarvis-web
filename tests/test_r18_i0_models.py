# tests/test_r18_i0_models.py -- R18 I0 (docs/plans/r18-calls/BUILD-BRIEF.md "Decisions fixed" and
# "Contracts"): the call card with its booking fields and limits, the call record, the call states,
# Heard, the language-check result, the owner's call settings and every cap and limit as a named
# constant. Fake numbers only (+91 90000 0000x).
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from jarvis.calls import models as m

NUMBER = "+919000000001"
OTHER = "+919000000002"


def _card(**over: object) -> m.CallCard:
    base: dict[str, object] = {
        "number_e164": NUMBER,
        "purpose": "Book a laundry pickup",
        "languages": ("en-IN", "ml-IN"),
    }
    return m.CallCard(**(base | over))


def test_the_brief_caps_and_limits_are_named_constants() -> None:
    assert (m.MONTH_CAP_INR, m.CALL_CAP_INR, m.CALL_MAX_MINUTES) == (200, 20, 6)
    assert (m.CALLS_PER_DAY, m.CALLS_PER_NUMBER_PER_DAY, m.NEW_NUMBERS_PER_DAY) == (10, 2, 3)
    assert m.NO_ANSWER_REDIALS_PER_DAY == 1
    assert (m.QUIET_FROM, m.QUIET_UNTIL, m.QUIET_ZONE) == (time(21), time(8), "Asia/Kolkata")
    assert {"100", "101", "102", "108", "112", "1091", "1098", "181"} <= m.EMERGENCY_NUMBERS
    assert m.PREMIUM_PREFIXES == ("1900",) and m.HOME_COUNTRY_CODE == "+91"
    assert m.APPROVAL_TTL_S == 600 and m.RETENTION_DAYS == 30
    assert m.MAX_INDIAN_LANGUAGES_PER_CARD == 3 and m.ANSWER_AFTER_RINGS == 5


def test_languages_are_bcp47_and_cover_english_and_the_22_scheduled_ones() -> None:
    assert m.ENGLISH == "en-IN" and m.ENGLISH in m.LANGUAGES
    assert len(m.SCHEDULED_LANGUAGES) == 22 and m.ENGLISH not in m.SCHEDULED_LANGUAGES
    assert {"hi-IN", "ml-IN", "ta-IN", "or-IN", "as-IN", "ur-IN"} <= set(m.SCHEDULED_LANGUAGES)
    assert set(m.LANGUAGE_NAMES) == set(m.LANGUAGES)
    assert m.is_language("kok-IN") and not m.is_language("xx-IN") and not m.is_language("en-GB")


def test_a_card_is_frozen_and_carries_booking_and_limits_defaults() -> None:
    card = _card()
    assert card.id.startswith("cc_") and len(card.id) == 15
    assert card.status is m.CardStatus.DRAFT and card.direction is m.Direction.OUTGOING
    assert card.limits == m.CardLimits() and card.limits.max_minutes == m.CALL_MAX_MINUTES
    assert card.limits.max_inr == m.CALL_CAP_INR and card.booking is None
    assert card.estimate_inr is None  # unknown is never ₹0
    assert card.first_language == "en-IN"
    with pytest.raises(ValidationError):
        card.purpose = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad",
    [
        {"number_e164": "9000000001"},  # no +country
        {"number_e164": "+91 90000 00001"},  # spaces: normalise before the card
        {"purpose": ""},
        {"languages": ()},
        {"languages": ("en-IN", "en-IN")},
        {"languages": ("en-IN", "hi-IN", "ml-IN", "ta-IN", "te-IN")},  # English + 4 Indian
        {"languages": ("xx-IN",)},
        {"limits": {"max_minutes": 0}},
        {"limits": {"max_minutes": m.CALL_MAX_MINUTES_CEILING + 1}},
        {"limits": {"max_inr": 0}},
        {"estimate_inr": -1},
        {"extra": "field"},
    ],
)
def test_a_card_refuses_what_the_brief_does_not_allow(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _card(**bad)


def test_booking_windows_are_inside_the_day_and_no_payment_is_fixed() -> None:
    w = m.TimeWindow(day=date(2026, 11, 28), start=time(10), end=time(12))
    b = m.Booking(windows=(w,), give_name="A. Owner", reason="Laundry pickup")
    assert b.no_payment is True and b.add_to_calendar and b.duration_minutes == 30
    card = _card(booking=b, template="laundry_pickup")
    assert card.booking is not None and card.booking.windows[0].start == time(10)
    with pytest.raises(ValidationError):
        m.TimeWindow(day=date(2026, 11, 28), start=time(12), end=time(10))
    with pytest.raises(ValidationError):
        m.Booking(windows=(), give_name="A", reason="r")
    with pytest.raises(ValidationError):
        m.Booking(windows=(w,), give_name="A", reason="r", no_payment=False)
    with pytest.raises(ValidationError):
        m.Booking(windows=(w,), give_name="A", reason="r", give_number="12345")


def test_the_card_digest_binds_number_and_content_but_not_status() -> None:
    card = _card()
    same = card.model_copy(update={"status": m.CardStatus.APPROVED, "estimate_inr": 3.5})
    assert card.digest() == same.digest() and len(card.digest()) == 64
    assert card.digest() != _card(number_e164=OTHER, id=card.id).digest()
    assert card.digest() != card.model_copy(update={"purpose": "Something else"}).digest()
    assert card.digest() != card.model_copy(update={"may_agree": ("pay in advance",)}).digest()


def test_a_record_holds_state_costs_and_vault_refs() -> None:
    at = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)
    rec = m.CallRecord(number_e164=NUMBER, started_at=at, card_id="cc_0123456789ab")
    assert rec.id.startswith("call_") and len(rec.id) == 17
    assert rec.state is m.CallState.PREPARING and not rec.state.terminal
    assert rec.cost_inr == 0 and rec.recorded and not rec.keep
    assert rec.delete_after == at + timedelta(days=m.RETENTION_DAYS)
    done = rec.model_copy(update={"state": m.CallState.ENDED, "end_reason": m.EndReason.HUNG_UP})
    assert done.state.terminal and done.end_reason is m.EndReason.HUNG_UP
    with pytest.raises(ValidationError):
        m.CallRecord(number_e164=NUMBER, started_at=datetime(2026, 11, 27, 5, 0))  # naive time


def test_call_states_cover_the_plans_state_machine() -> None:
    names = {s.value for s in m.CallState}
    assert {"preparing", "dialing", "ringing", "opening", "talking", "taken_over"} <= names
    assert {"wrapping_up", "ended", "failed", "no_answer"} <= names
    assert {s for s in m.CallState if s.terminal} == {
        m.CallState.ENDED,
        m.CallState.FAILED,
        m.CallState.NO_ANSWER,
    }


def test_heard_and_language_results() -> None:
    h = m.Heard(lang="ml-IN", text="naale pathu manikku", confidence=0.82, seconds=1.4)
    assert h.lang == "ml-IN" and 0 <= h.confidence <= 1
    with pytest.raises(ValidationError):
        m.Heard(lang="ml-IN", text="x", confidence=1.2, seconds=1)
    at = datetime(2026, 11, 27, tzinfo=UTC)
    r = m.LanguageResult(lang="hi-IN", option=m.SpeechOption.GOOGLE, checked_at=at)
    assert not r.passed and r.inr_per_minute is None and not r.native_heard
    assert m.LANG_CHECK == m.LangCheckBars()
    bars = m.LANG_CHECK
    assert (bars.hear_facts, bars.max_cer, bars.speak_facts) == (0.90, 0.15, 0.90)
    assert (bars.human_score, bars.p50_ms, bars.p90_ms) == (4, 1500, 2500)
    assert (bars.hear_clips, bars.speak_sentences, bars.human_samples) == (20, 10, 3)


def test_call_settings_defaults_are_the_briefs() -> None:
    s = m.CallSettings()
    assert (s.month_cap_inr, s.call_cap_inr, s.call_max_minutes) == (200, 20, 6)
    assert s.answering_on is False and s.answer_after_rings == 5
    assert s.answer_policy is m.AnswerPolicy.ALL and s.retention_days == 30
    assert s.allow_balanced is False and s.sarvam_on is False and s.record_audio is True
    assert s.default_languages == ("en-IN",)
    with pytest.raises(ValidationError):
        m.CallSettings(call_cap_inr=0)
    with pytest.raises(ValidationError):
        m.CallSettings(month_cap_inr=m.MONTH_CAP_CEILING_INR + 1)


def test_the_opening_line_names_the_owner_and_says_it_is_recorded() -> None:
    line = m.opening_line("Asha")
    assert line == (
        "Hello, this is JARVIS, an AI assistant calling on behalf of Asha. This call is recorded."
    )
    with pytest.raises(ValueError):
        m.opening_line("  ")


def test_ids_are_random_and_patterned() -> None:
    assert m.new_card_id() != m.new_card_id()
    assert m.CARD_ID_RE.fullmatch(m.new_card_id()) and m.CALL_ID_RE.fullmatch(m.new_call_id())
