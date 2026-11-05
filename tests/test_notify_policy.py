# tests/test_notify_policy.py -- R3 D10: the pure alert policy, rule by rule, in order.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.notify.models import NotifySettings, QuietHours, Vip
from jarvis.notify.policy import decide
from jarvis.notify.ports import DEFAULT_URGENCY, Signal
from jarvis.notify.quiet import in_quiet
from jarvis.notify.terms import emergency

# 2027-01-15 in Asia/Kolkata (UTC+5:30)
NOON = datetime(2027, 1, 15, 6, 30, tzinfo=UTC)  # 12:00 local
MIDNIGHT = datetime(2027, 1, 14, 19, 0, tzinfo=UTC)  # 00:30 local
LATE = datetime(2027, 1, 15, 17, 30, tzinfo=UTC)  # 23:00 local sharp
EDGE_END = datetime(2027, 1, 15, 1, 0, tzinfo=UTC)  # 06:30 local sharp


def sig(kind: str, **kw: object) -> Signal:
    return Signal(source="home", kind=kind, **kw)  # type: ignore[arg-type]


def act(kind: str, now: datetime = NOON, settings: NotifySettings | None = None, **kw: object):
    d = decide(sig(kind, **kw), settings or NotifySettings(), now)
    return d.action, d.reason


def test_a_test_rings_whatever_its_level_or_the_hour() -> None:
    assert act("test", MIDNIGHT) == ("ring", "test")
    off = NotifySettings.model_construct(kinds={"test": "off"})
    assert decide(sig("test"), off, MIDNIGHT).action == "ring"


def test_a_kind_switched_off_is_dropped_and_feed_is_feed_only() -> None:
    s = NotifySettings(kinds={"home_package": "off", "home_online": "feed"})
    assert act("home_package", settings=s) == ("drop", "switched_off")
    assert act("home_online", settings=s) == ("drop", "feed_only")


def test_burglar_alerts_cannot_be_switched_off() -> None:
    s = NotifySettings.model_construct(
        kinds={"home_intruder": "off", "home_hazard": "off", "home_summary": "off"},
        quiet=QuietHours(),
        tz="Asia/Kolkata",
        vip=(),
        ring_for="urgent",
    )
    for kind in ("home_intruder", "home_hazard", "home_summary"):
        assert decide(sig(kind), s, NOON).action == "ring"


def test_switch_off_beats_emergency_text() -> None:
    s = NotifySettings(kinds={"brief_ready": "off"})
    assert act("brief_ready", settings=s, text="fire") == ("drop", "switched_off")


def test_a_hazard_rings_through_quiet_hours() -> None:
    assert act("home_hazard", MIDNIGHT) == ("ring", "emergency")


def test_emergency_words_ring_an_important_alert_in_quiet_hours() -> None:
    assert act("approval_waiting", MIDNIGHT, text="there is a fire") == ("ring", "emergency")
    assert act("approval_waiting", MIDNIGHT, text="my firewall") == ("hold", "quiet_hours")


def test_an_armed_intruder_rings_in_quiet_hours() -> None:
    assert act("home_intruder", MIDNIGHT) == ("ring", "intruder")


def test_the_storm_summary_is_urgent() -> None:
    assert act("home_summary", MIDNIGHT) == ("ring", "urgent")


def test_a_face_vip_rings_in_quiet_hours() -> None:
    assert act(
        "home_greeting", MIDNIGHT, vip=True, settings=NotifySettings(kinds={"home_greeting": "on"})
    ) == (
        "ring",
        "vip",
    )


def test_a_listed_reference_is_a_vip() -> None:
    s = NotifySettings(vip=(Vip(id="v_0123abcd", kind="phone", ref="+911234567890"),))
    assert act("approval_waiting", MIDNIGHT, settings=s, person_ref="+911234567890") == (
        "ring",
        "vip",
    )
    assert act("approval_waiting", MIDNIGHT, settings=s, person_ref="other") == (
        "hold",
        "quiet_hours",
    )


def test_a_child_is_never_a_vip_ring() -> None:
    s = NotifySettings(kinds={"home_greeting": "on"})
    assert act("home_greeting", MIDNIGHT, settings=s, vip=True, child=True) == ("drop", "feed_only")


def test_quiet_hours_hold_important_and_feed_only_info() -> None:
    assert act("home_package", MIDNIGHT) == ("hold", "quiet_hours")
    assert act("home_online", MIDNIGHT) == ("drop", "feed_only")


def test_quiet_hours_across_midnight_and_their_edges() -> None:
    q = QuietHours()
    tz = "Asia/Kolkata"
    assert in_quiet(LATE, q, tz) is True  # 23:00 is in
    assert in_quiet(MIDNIGHT, q, tz) is True
    assert in_quiet(EDGE_END, q, tz) is False  # 06:30 is out
    assert in_quiet(NOON, q, tz) is False
    assert in_quiet(MIDNIGHT, QuietHours(on=False), tz) is False
    assert in_quiet(MIDNIGHT, QuietHours(start="01:00", end="01:00"), tz) is False


def test_a_same_day_window_and_the_owner_zone() -> None:
    q = QuietHours(start="13:00", end="15:00")
    assert in_quiet(datetime(2027, 1, 15, 8, 0, tzinfo=UTC), q, "Asia/Kolkata") is True  # 13:30
    assert in_quiet(datetime(2027, 1, 15, 8, 0, tzinfo=UTC), q, "UTC") is False
    assert in_quiet(datetime(2027, 1, 15, 8, 0), q, "Asia/Kolkata") is True  # naive is UTC
    assert in_quiet(datetime(2027, 1, 15, 8, 0, tzinfo=UTC), q, "No/Such") is True  # fallback zone


def test_quiet_hours_off_means_important_acts_normally() -> None:
    s = NotifySettings(quiet=QuietHours(on=False))
    assert act("home_package", MIDNIGHT, s) == ("silent", "only_urgent_rings")


def test_only_urgent_rings_by_default_and_important_rings_when_asked() -> None:
    assert act("home_package") == ("silent", "only_urgent_rings")
    assert act("home_package", settings=NotifySettings(ring_for="important")) == (
        "ring",
        "important",
    )


def test_info_is_silent_by_day() -> None:
    assert act("home_online") == ("silent", "info")
    assert act("brief_ready") == ("silent", "info")


def test_greeting_is_feed_only_until_the_owner_switches_it_on() -> None:
    assert act("home_greeting") == ("drop", "feed_only")
    assert act("home_greeting", settings=NotifySettings(kinds={"home_greeting": "on"})) == (
        "silent",
        "info",
    )


def test_r1_and_r2_kinds_go_through_the_policy() -> None:
    assert act("approval_waiting", MIDNIGHT) == ("hold", "quiet_hours")
    assert act("vault_expiry", MIDNIGHT) == ("hold", "quiet_hours")


def test_every_kind_gets_a_decision() -> None:
    for kind in DEFAULT_URGENCY:
        assert decide(sig(kind), NotifySettings(), NOON).action in {"ring", "silent", "drop"}


def test_settings_validation() -> None:
    with pytest.raises(ValidationError):
        NotifySettings(kinds={"nonsense": "on"})
    with pytest.raises(ValidationError):
        QuietHours(start="25:00")
    with pytest.raises(ValidationError):
        NotifySettings(vip=tuple(Vip(id=f"v_{i:08x}", kind="phone", ref=str(i)) for i in range(21)))
    assert "tz" not in NotifySettings().model_dump()


def test_the_policy_object_matches_the_port() -> None:
    from jarvis.notify.policy import Policy
    from jarvis.notify.ports import NotifyPolicy

    assert isinstance(Policy(), NotifyPolicy)


@pytest.mark.parametrize(
    "text",
    [
        "Fire!",
        "FIRE in the kitchen",
        "please help",
        "gas   leak near the stove",
        "aag lag gayi",
        "bachao",
        "chor aaya",
        "ambulance bulao",
        "\u0906\u0917 \u0932\u0917\u0940",
        "\u092c\u091a\u093e\u0913!",
        "\u0d24\u0d40 \u0d2a\u0d3f\u0d1f\u0d3f\u0d1a\u0d4d\u0d1a\u0d41",
        "\u0d30\u0d15\u0d4d\u0d37\u0d3f\u0d15\u0d4d\u0d15\u0d23\u0d47",
        "\u0d15\u0d33\u0d4d\u0d33\u0d7b \u0d35\u0d28\u0d4d\u0d28\u0d41",
        "\u0b28\u0b3f\u0b06\u0b01 \u0b32\u0b3e\u0b17\u0b3f\u0b32\u0b3e",
        "\u0b2c\u0b1e\u0b4d\u0b1a\u0b3e\u0b05",
        "\u0b1a\u0b4b\u0b30",
        "there was an accident",
        "smoke, flood",
    ],
)
def test_emergency_words_match(text: str) -> None:
    assert emergency(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "firewall",
        "bonfire",
        "helpful",
        "",
        None,
        "the hospitality desk",
        "chore",
        "aagaz",
        "smoked salmon",
    ],
)
def test_word_boundaries_hold(text: str | None) -> None:
    assert emergency(text) is False


def test_decomposed_input_still_matches() -> None:
    import unicodedata

    assert emergency(unicodedata.normalize("NFD", "\u0d15\u0d33\u0d4d\u0d33\u0d7b")) is True


# ---- integrated review H5: a laptop or arming problem is never held through the night ---------


@pytest.mark.parametrize("kind", ["home_offline", "home_arm_failed"])
def test_laptop_off_and_arming_problems_ring_through_quiet_hours(kind: str) -> None:
    night = NotifySettings(quiet=QuietHours(on=True, start="22:00", end="07:00"))
    two_am = datetime(2027, 1, 14, 20, 30, tzinfo=UTC)  # 02:00 local
    assert DEFAULT_URGENCY[kind] == "urgent"
    assert act(kind, two_am, night) == ("ring", "urgent")
