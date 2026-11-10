# tests/test_r51c_briefing.py -- R5.1 D5 (docs/plans/r5-1-observations.md): the spoken systems
# briefing is FIXED templates, never model text. It names every system checked and what is
# broken with what that breaks, then vitals (AI spend in rupees and percent, allowances >= 80 %,
# every amber/red item with its consequence), and ends with one question or "All systems nominal".
# Never a probe's reason, never a key value, rupees only, about 60 s of speech (<= 900 chars).
from __future__ import annotations

from r51c_fakes import board, view

from jarvis.health.briefing import (
    MAX_SPOKEN,
    NOMINAL_CLOSE,
    REMIND_CLOSE,
    VITALS_UNREADABLE,
    Briefing,
    compose_briefing,
)
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.report import rollup


def res(key: str, status: str = "ok", label: str = "", reason: str = "fine") -> ProbeResult:
    return ProbeResult(key=key, label=label or key, status=status, reason=reason, at=1.0)  # type: ignore[arg-type]


def report(*items: ProbeResult) -> HealthReport:
    return HealthReport(overall=rollup(items), results=tuple(items), at=1.0)


ALL_OK = report(res("brain"), res("google"), res("redis"))


def test_all_ok_without_vitals_is_the_short_nominal_briefing() -> None:
    b = compose_briefing(ALL_OK, None)
    assert isinstance(b, Briefing)
    assert b.spoken == (
        "Systems check complete, Sir. I checked 3 systems: the AI brain, Google and Redis. "
        "All of them are working. All systems nominal, Sir."
    )
    assert b.concerns == ()
    assert b.lines[-1] == NOMINAL_CLOSE


def test_a_down_system_is_named_with_what_it_breaks_and_a_question_closes() -> None:
    r = report(res("brain"), res("google"), res("telegram", "down", reason="HTTP 401 from vendor"))
    b = compose_briefing(r, None)
    assert b.spoken == (
        "Systems check complete, Sir. I checked 3 systems: the AI brain, Google and Telegram. "
        "The AI brain and Google are working. "
        "Telegram is not answering — alerts and Telegram chat won't reach you. "
        "Shall I set a reminder to fix this?"
    )
    (c,) = b.concerns
    assert (c.key, c.label, c.severity) == ("telegram", "Telegram", "down")
    assert c.impact == "alerts and Telegram chat won't reach you"
    assert c.fix  # a fixed hint on screen
    assert b.lines[-1] == REMIND_CLOSE


def test_degraded_and_down_are_both_named_in_report_order() -> None:
    r = report(res("home", "down"), res("web", "degraded"), res("docs"))
    b = compose_briefing(r, None)
    assert "The document store is working." in b.spoken
    assert "The home bridge is not answering — the camera alarm and home devices are off." in (
        b.spoken
    )
    assert "Web search is degraded — web search stops." in b.spoken
    assert [c.key for c in b.concerns] == ["home", "web"]
    assert [c.severity for c in b.concerns] == ["down", "degraded"]


def test_nothing_working_skips_the_working_sentence() -> None:
    b = compose_briefing(report(res("redis", "down")), None)
    assert "working" not in b.spoken
    assert "I checked 1 system: Redis." in b.spoken


def test_every_fixed_impact_is_known() -> None:
    keys = ("brain", "docs", "google", "telegram", "home", "redis", "web")
    b = compose_briefing(report(*(res(k, "down") for k in keys)), None)
    impacts = {c.key: c.impact for c in b.concerns}
    assert impacts == {
        "brain": "JARVIS can't think; offline mode or No-AI answers only",
        "docs": "JARVIS can't save or read your data",
        "google": "calendar, email, reminders and Drive stop working",
        "telegram": "alerts and Telegram chat won't reach you",
        "home": "the camera alarm and home devices are off",
        "redis": "sessions may be lost on restart",
        "web": "web search stops",
    }


def test_the_probe_reason_and_a_forged_label_never_reach_the_spoken_line() -> None:
    forged = res("telegram", "down", label="sk-ant-api03-SECRET", reason="vendor said sk-live-9")
    other = res("x-custom", "down", label="the custom bridge", reason="Vendor text: 500 boom")
    b = compose_briefing(report(forged, other), None)
    assert "sk-" not in b.spoken and "Vendor" not in b.spoken and "boom" not in b.spoken
    assert "sk-" not in " ".join(b.lines)
    assert "Telegram is not answering" in b.spoken
    assert "The custom bridge is not answering — it may not work until it's fixed." in b.spoken


# ---- vitals --------------------------------------------------------------------------------------
def test_spend_is_said_in_rupees_with_the_percentage() -> None:
    b = compose_briefing(ALL_OK, board(used=120, limit=500))
    assert "AI spend is ₹120 of ₹500 this month (24 percent)." in b.spoken
    assert "$" not in b.spoken and "USD" not in b.spoken and "dollar" not in b.spoken.lower()
    assert b.spoken.endswith(NOMINAL_CLOSE)


def test_spend_without_a_limit_says_so() -> None:
    b = compose_briefing(ALL_OK, board(used=1234.5, limit=None))
    assert "AI spend is ₹1,234.50 this month, no limit set." in b.spoken


def test_the_spend_sentence_is_kept_apart_for_the_screen() -> None:
    assert compose_briefing(ALL_OK, board(used=120, limit=500)).spend == (
        "AI spend is ₹120 of ₹500 this month (24 percent)."
    )
    unreadable = compose_briefing(ALL_OK, None, vitals_unreadable=True)
    assert unreadable.spend == "Vitals can't be read just now."


def test_spend_near_the_limit_is_a_concern_once() -> None:
    spend = view("ai_spend", "AI spend this month", "amber", kind="billing", percent=90.0,
                 reason="is at 90% of its limit")  # fmt: skip
    b = compose_briefing(ALL_OK, board(spend, used=450, limit=500))
    assert (  # R5.1 V1: the limit consequence is its own sentence, only at 80 percent or more
        "AI spend is ₹450 of ₹500 this month (90 percent). At the limit, paid replies pause "
        "and JARVIS uses the free brain." in b.spoken
    )
    assert "if it stops" not in b.spoken and "paid AI replies stop" not in b.spoken
    assert b.spoken.count("AI spend") == 1  # not said again as an amber item
    assert [c.key for c in b.concerns] == ["vitals.ai_spend"]
    assert b.concerns[0].severity == "amber"
    assert b.spoken.endswith(REMIND_CLOSE)


def test_allowances_at_or_over_80_percent_are_named() -> None:
    low = view("allowance_stt", "Speech to text", "ok", kind="allowance", percent=40.0)
    high = view("allowance_tts", "Voice (Studio)", "amber", kind="allowance", percent=85.4,
                reason="is at 85% of its limit")  # fmt: skip
    b = compose_briefing(ALL_OK, board(low, high))
    assert "Voice (Studio): 85 percent used — its free allowance runs out." in b.spoken
    assert "Speech to text" not in b.spoken
    assert [c.key for c in b.concerns] == ["vitals.allowance_tts"]


def test_amber_and_red_items_are_said_red_first_with_their_consequence() -> None:
    amber = view("github", "GitHub token", "amber", kind="key", reason="expires in 3 days")
    red = view("maps", "Maps quota", "red", kind="quota", reason="has reached its limit")
    unknown = view("photos", "Photos", "unknown", kind="key", reason="can't be read now")
    b = compose_briefing(ALL_OK, board(amber, red, unknown))
    s = b.spoken
    red_at = s.index("Maps quota has reached its limit — that feature stops until it resets.")
    amber_at = s.index("GitHub token expires in 3 days — the service using it stops working.")
    assert red_at < amber_at
    assert "Photos" not in s  # unknown is not a concern
    assert [(c.key, c.severity) for c in b.concerns] == [
        ("vitals.maps", "red"),
        ("vitals.github", "amber"),
    ]


def test_part_b_impact_and_fix_are_used_when_present() -> None:
    item = view("github", "GitHub token", "red", kind="key", reason="has expired",
                impact="code tools stop working", fix="renew the token on GitHub")  # fmt: skip
    b = compose_briefing(ALL_OK, board(item))
    assert "GitHub token has expired — code tools stop working." in b.spoken
    assert b.concerns[0].fix == "renew the token on GitHub"


def test_vitals_that_cannot_be_read_never_fail_the_briefing() -> None:
    b = compose_briefing(ALL_OK, None, vitals_unreadable=True)
    assert VITALS_UNREADABLE in b.spoken
    assert VITALS_UNREADABLE == "Vitals can't be read just now."
    assert b.spoken.endswith(NOMINAL_CLOSE)


def test_no_vitals_service_says_nothing_about_vitals() -> None:
    b = compose_briefing(ALL_OK, None)
    assert "Vitals" not in b.spoken and "AI spend" not in b.spoken


def test_a_board_without_spend_skips_the_spend_sentence() -> None:
    from jarvis.vitals.models import Board

    b = compose_briefing(ALL_OK, Board(items=(), spend=None, overall="ok"))
    assert "AI spend" not in b.spoken


# ---- the cap -----------------------------------------------------------------------------------
def test_a_long_briefing_is_capped_lowest_severity_first_and_points_to_the_screen() -> None:
    ambers = [
        view(f"key{i}", f"Service key number {i}", "amber", reason=f"expires in {i + 2} days")
        for i in range(14)
    ]
    reds = [view(f"red{i}", f"Billing account {i}", "red", kind="billing",
                 reason="has reached its limit") for i in range(3)]  # fmt: skip
    r = report(res("telegram", "down"), res("google", "down"), res("brain"))
    b = compose_briefing(r, board(*ambers, *reds))
    assert len(b.spoken) <= MAX_SPOKEN == 900
    assert "more on screen." in b.spoken
    assert b.spoken.endswith(REMIND_CLOSE)
    # systems faults and red items are kept before amber ones
    assert "Telegram is not answering" in b.spoken and "Google is not answering" in b.spoken
    assert all(f"Billing account {i} has reached its limit" in b.spoken for i in range(3))
    # the screen keeps everything
    assert len(b.concerns) == 2 + 14 + 3
    assert all(any(f"Service key number {i} " in line for line in b.lines) for i in range(14))


def test_the_dropped_count_is_said() -> None:
    ambers = [view(f"k{i}", f"Key with a long descriptive name {i}", "amber",
                   reason="expires in 5 days") for i in range(20)]  # fmt: skip
    b = compose_briefing(ALL_OK, board(*ambers))
    said = sum(1 for i in range(20) if f"Key with a long descriptive name {i} " in b.spoken)
    assert f"And {20 - said} more on screen." in b.spoken


def test_no_systems_still_briefs_vitals() -> None:
    b = compose_briefing(report(), board(used=10, limit=500))
    assert b.spoken.startswith("Systems check complete, Sir. There are no systems to check.")
    assert "AI spend is ₹10 of ₹500 this month (2 percent)." in b.spoken


def test_an_empty_report_says_one_fixed_line_and_never_all_systems_nominal() -> None:
    for b in (compose_briefing(report(), None), compose_briefing(None, None)):
        assert b.spoken == "Systems check complete, Sir. There are no systems to check."
        assert "nominal" not in " ".join(b.lines) and NOMINAL_CLOSE not in b.spoken
    with_vitals = compose_briefing(report(), board(used=10, limit=500))
    assert "no systems" in with_vitals.spoken and "nominal" not in with_vitals.spoken
    assert with_vitals.spoken.endswith("(2 percent).")


def test_to_json_is_plain_data() -> None:
    r = report(res("telegram", "down"))
    data = compose_briefing(r, None).to_json()
    assert set(data) == {"spoken", "lines", "concerns", "spend"}
    assert data["spend"] == ""  # no Vitals here
    assert data["concerns"] == [
        {
            "key": "telegram",
            "label": "Telegram",
            "severity": "down",
            "impact": "alerts and Telegram chat won't reach you",
            "fix": data["concerns"][0]["fix"],
        }
    ]
    assert isinstance(data["lines"], list)


LIMIT_SENTENCE = "At the limit, paid replies pause and JARVIS uses the free brain."


def test_v1_the_spend_sentence_for_82_percent_reads_as_the_owner_asked() -> None:
    b = compose_briefing(ALL_OK, board(used=412.5, limit=500))
    expected = f"AI spend is ₹412.50 of ₹500 this month (82 percent). {LIMIT_SENTENCE}"
    assert expected in b.spoken
    assert b.spend == expected  # the screen says the same


def test_v1_the_limit_sentence_starts_at_exactly_80_percent() -> None:
    at_80 = compose_briefing(ALL_OK, board(used=400, limit=500))
    below = compose_briefing(ALL_OK, board(used=399, limit=500))
    assert LIMIT_SENTENCE in at_80.spoken and "(80 percent)." in at_80.spoken
    assert LIMIT_SENTENCE not in below.spoken and LIMIT_SENTENCE not in below.spend


def test_v1_no_limit_and_zero_limit_never_get_the_limit_sentence() -> None:
    assert LIMIT_SENTENCE not in compose_briefing(ALL_OK, board(used=900, limit=None)).spoken
    assert LIMIT_SENTENCE not in compose_briefing(ALL_OK, board(used=5, limit=0)).spoken
