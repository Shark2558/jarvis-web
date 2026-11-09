# tests/test_r51b_vitals_own.py -- R5.1 D2: every key and connection JARVIS itself uses is on the
# Vitals board automatically (`source="auto"`), read only from cheap in-process state, stored
# records, the last systems-check report and the web vendor's free usage report (cached 10 min).
# Fixed plain-English reason / impact / fix; never vendor or exception text; never a key value.
from __future__ import annotations

import asyncio
import json

import pytest
from r51b_fakes import (
    SECRET,
    Brain,
    Github,
    Google,
    HealthLast,
    Home,
    HomeSt,
    Meta,
    OwnRig,
    Report,
    Result,
    Usage,
    Web,
    settings,
    with_keys,
)
from vitals_fakes import UID, key

from jarvis.vitals.own import OWN_IDS, QUIET_IDS, OwnSources


def by_id(board, pid):  # type: ignore[no-untyped-def]
    return next((v for v in board.items if v.provider.id == pid), None)


async def view(rig: OwnRig, pid: str):  # type: ignore[no-untyped-def]
    return by_id(await rig.svc.board(UID), pid)


# ---- the AI brains ----
@pytest.mark.parametrize(
    ("state", "status", "reason"),
    [
        ("refused", "red", "was refused"),
        ("busy", "amber", "is busy right now"),
        ("odd", "amber", "answered oddly"),
        ("unreachable", "amber", "could not be reached"),
        ("unknown", "ok", ""),
        ("ok", "ok", ""),
    ],
)
async def test_claude_key_follows_the_routers_own_record(
    state: str, status: str, reason: str
) -> None:
    rig = OwnRig(OwnSources(claude=Brain(state)))

    v = await view(rig, "brain_claude")

    assert v is not None and v.provider.source == "auto" and v.provider.kind == "key"
    assert v.provider.label == "Claude (paid AI) key" and v.group == "keys"
    assert (v.status, v.reason) == (status, reason)
    assert v.impact.startswith("If this stops") and v.fix


async def test_gemini_busy_means_the_free_limit_is_reached() -> None:
    rig = OwnRig(OwnSources(gemini=Brain("busy")))

    v = await view(rig, "brain_gemini")

    assert v.provider.label == "Gemini (free AI) key"
    assert (v.status, v.reason) == ("amber", "has reached its free limit for now")


async def test_unreachable_cloud_with_the_laptop_answering_says_so() -> None:
    rig = OwnRig(OwnSources(claude=Brain("unreachable", on_laptop=True)))

    v = await view(rig, "brain_claude")

    assert v.status == "amber" and "laptop" in v.reason


async def test_a_brain_is_left_out_when_its_key_is_not_configured() -> None:
    rig = OwnRig(OwnSources(claude=Brain(), gemini=Brain()), settings=settings())

    board = await rig.svc.board(UID)

    assert by_id(board, "brain_claude") is None and by_id(board, "brain_gemini") is None


async def test_a_configured_brain_without_a_reader_is_unknown_not_missing() -> None:
    rig = OwnRig(OwnSources())

    v = await view(rig, "brain_claude")

    assert v is not None and v.status == "unknown"


# ---- Google ----
async def test_google_connected_is_ok_and_needs_reconnect_is_red() -> None:
    ok = await view(OwnRig(OwnSources(google=Google())), "google_link")
    bad = await view(OwnRig(OwnSources(google=Google(False, True))), "google_link")

    assert ok.status == "ok" and ok.provider.label == "Google sign-in"
    assert "a@b.c" not in json.dumps(ok.to_json())
    assert (bad.status, bad.reason) == ("red", "needs reconnecting")
    assert "Integrations" in bad.fix


async def test_google_never_connected_is_left_out() -> None:
    rig = OwnRig(OwnSources(google=Google(connected=False)))

    assert await view(rig, "google_link") is None


# ---- Telegram (from the LAST stored systems check; no new call) ----
@pytest.mark.parametrize(
    ("probe", "status"), [("ok", "ok"), ("degraded", "amber"), ("down", "red")]
)
async def test_telegram_reads_the_last_systems_check(probe: str, status: str) -> None:
    last = HealthLast()
    rig = OwnRig(OwnSources(health=last))
    last.report = Report((Result("telegram", probe, rig.epoch - 120),))

    v = await view(rig, "telegram_bot")

    assert v.status == status and v.provider.label == "Telegram bot"
    assert "alerts" in v.impact


async def test_telegram_before_any_systems_check_is_unknown_and_says_run_one() -> None:
    rig = OwnRig(OwnSources(health=HealthLast(None)))

    v = await view(rig, "telegram_bot")

    assert v.status == "unknown" and "systems check" in v.provider.note


async def test_telegram_left_out_of_the_last_check_is_not_set_up() -> None:
    """D4 (Part C): no paired chat means the systems check leaves Telegram out ("not set up")."""
    rig = OwnRig(OwnSources(health=HealthLast(Report((Result("docs", "ok", 0.0),)))))

    assert await view(rig, "telegram_bot") is None


async def test_telegram_without_a_bot_token_is_left_out() -> None:
    report = Report((Result("telegram", "ok", 0.0),))
    rig = OwnRig(OwnSources(health=HealthLast(report)), settings=with_keys(telegram_bot_token=None))

    assert await view(rig, "telegram_bot") is None


# ---- web search credits (the vendor's free usage report, cached 10 minutes) ----
async def test_web_credits_is_a_quota_item_that_resets_next_month() -> None:
    rig = OwnRig(OwnSources(web=Web(Usage(850, 1000))))

    v = await view(rig, "web_credits")

    assert v.provider.kind == "quota" and v.group == "allowances"
    assert (v.provider.used, v.provider.limit, v.provider.unit) == (850, 1000, "credits")
    assert v.status == "amber" and v.percent == 85.0
    reset = v.provider.reset_at
    assert reset is not None and (reset.year, reset.month, reset.day) == (2026, 12, 1)


async def test_web_credits_exhausted_is_red_even_without_a_limit() -> None:
    rig = OwnRig(OwnSources(web=Web(Usage(10, None, exhausted=True))))

    v = await view(rig, "web_credits")

    assert (v.status, v.reason) == ("red", "is used up")


async def test_web_usage_is_cached_for_ten_minutes_per_process() -> None:
    web = Web()
    rig = OwnRig(OwnSources(web=web))

    await rig.svc.board(UID)
    rig.clock.advance(minutes=9)
    await rig.svc.board(UID)
    assert web.calls == 1
    rig.clock.advance(minutes=2)
    await rig.svc.board(UID)
    assert web.calls == 2


async def test_web_usage_failure_is_unknown_and_never_shows_vendor_text() -> None:
    rig = OwnRig(OwnSources(web=Web(boom=True)))

    board = await rig.svc.board(UID)

    assert by_id(board, "web_credits").status == "unknown"
    assert SECRET not in json.dumps(board.to_json())


# ---- GitHub token ----
async def test_github_shows_the_hourly_limit_and_a_non_expiring_token() -> None:
    rig = OwnRig(OwnSources())
    reset = rig.epoch + 1800
    rig = OwnRig(
        OwnSources(github=Github(Meta(rig.epoch - 60, None, 5000, 1250, reset))),
        clock=rig.clock,
    )

    v = await view(rig, "github_token")

    assert v.provider.label == "GitHub token" and v.group == "keys"
    assert (v.provider.used, v.provider.limit, v.provider.unit) == (1250, 5000, "calls this hour")
    assert v.status == "ok" and v.percent == 25.0
    assert v.provider.note == "This token doesn't expire."
    assert v.provider.expires_at is None and v.provider.reset_at is not None


async def test_github_expiry_turns_amber_inside_the_window_and_red_when_past() -> None:
    rig = OwnRig(OwnSources())
    soon = Github(Meta(rig.epoch, rig.epoch + 5 * 86400))
    past = Github(Meta(rig.epoch, rig.epoch - 60))

    amber = await view(OwnRig(OwnSources(github=soon), clock=rig.clock), "github_token")
    red = await view(OwnRig(OwnSources(github=past), clock=rig.clock), "github_token")

    assert amber.status == "amber" and "expires in 5 days" in amber.reason
    assert red.status == "red" and red.reason == "has expired"
    assert "Connectors" in red.fix


async def test_github_rate_window_that_already_reset_shows_no_stale_count() -> None:
    rig = OwnRig(OwnSources())
    meta = Meta(rig.epoch - 7200, None, 5000, 4999, rig.epoch - 3600)
    v = await view(OwnRig(OwnSources(github=Github(meta)), clock=rig.clock), "github_token")

    assert v.status == "ok" and v.provider.used is None and v.provider.limit is None


async def test_github_not_connected_is_left_out_and_unreadable_is_red() -> None:
    gone = OwnRig(OwnSources(github=Github(connected=False)))
    broken = OwnRig(OwnSources(github=Github(connected=False, needs_reconnect=True)))

    assert await view(gone, "github_token") is None
    v = await view(broken, "github_token")
    assert (v.status, v.reason) == ("red", "needs reconnecting")


async def test_github_never_used_since_connecting_is_unknown() -> None:
    v = await view(OwnRig(OwnSources(github=Github(None))), "github_token")

    assert v.status == "unknown" and "next time" in v.provider.note


# ---- home laptop link ----
async def test_home_recent_heartbeat_is_ok_with_its_age() -> None:
    rig = OwnRig(OwnSources())
    home = Home(HomeSt("online", rig.epoch - 125))

    v = await view(OwnRig(OwnSources(home=home), clock=rig.clock), "home_link")

    assert v.status == "ok" and v.provider.label == "Home laptop link"
    assert v.provider.note == "Last heartbeat 2 minutes ago."


@pytest.mark.parametrize(
    ("state", "age_s", "status", "reason"),
    [
        ("offline", 60, "red", "is offline: no heartbeat for 1 minute"),
        ("online", 900, "red", "is offline: no heartbeat for 15 minutes"),
        ("degraded", 30, "amber", "reports a problem"),
    ],
)
async def test_home_offline_is_red_and_degraded_amber(
    state: str, age_s: int, status: str, reason: str
) -> None:
    rig = OwnRig(OwnSources())
    home = Home(HomeSt(state, rig.epoch - age_s))

    v = await view(OwnRig(OwnSources(home=home), clock=rig.clock), "home_link")

    assert (v.status, v.reason) == (status, reason)


async def test_home_never_reported_is_red_and_unlinked_is_left_out() -> None:
    never = await view(OwnRig(OwnSources(home=Home(HomeSt("linked", None)))), "home_link")

    assert (never.status, never.reason) == ("red", "has never reported in")
    assert await view(OwnRig(OwnSources(home=Home(None))), "home_link") is None


# ---- robustness and the fixed words ----
async def test_a_failing_source_is_unknown_and_never_leaks_its_text() -> None:
    own = OwnSources(
        claude=Brain(boom=True),
        google=Google(boom=True),
        health=HealthLast(boom=True),
        web=Web(boom=True),
        home=Home(boom=True),
    )
    board = await OwnRig(own).svc.board(UID)

    text = json.dumps(board.to_json())
    assert SECRET not in text and "vendor said" not in text
    for pid in ("brain_claude", "telegram_bot", "web_credits"):
        assert by_id(board, pid).status == "unknown", pid
    assert board.overall != "red"


async def test_a_slow_source_times_out_as_unknown() -> None:
    class Slow(Web):
        async def usage(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(10)
            return Usage(1, 2)

    import jarvis.vitals.own as own_mod

    rig = OwnRig(OwnSources(web=Slow()))
    old = own_mod.SOURCE_TIMEOUT_S
    own_mod.SOURCE_TIMEOUT_S = 0.05
    try:
        v = await view(rig, "web_credits")
    finally:
        own_mod.SOURCE_TIMEOUT_S = old

    assert v.status == "unknown"


async def test_every_own_item_has_fixed_words_and_is_reserved() -> None:
    rig = OwnRig(OwnSources())
    epoch = rig.epoch
    own = OwnSources(
        claude=Brain(),
        gemini=Brain(),
        google=Google(),
        health=HealthLast(Report((Result("telegram", "ok", epoch),))),
        web=Web(),
        github=Github(Meta(epoch)),
        home=Home(HomeSt("online", epoch)),
    )
    board = await OwnRig(own, clock=rig.clock).svc.board(UID)

    ids = {v.provider.id for v in board.items}
    assert OWN_IDS <= ids
    for v in board.items:
        if v.provider.id in OWN_IDS:
            assert v.provider.source == "auto"
            assert v.impact.startswith("If this ") and v.fix, v.provider.id
            assert v.group in ("keys", "allowances")
    for pid in OWN_IDS:
        with pytest.raises(ValueError):
            await rig.svc.set_key(UID, key(pid))
        assert await rig.svc.delete_key(UID, pid) is False


async def test_systems_watched_elsewhere_never_ring_from_vitals() -> None:
    rig = OwnRig(OwnSources())
    epoch = rig.epoch
    own = OwnSources(
        claude=Brain("refused"),
        default_brain="anthropic",
        google=Google(False, True),
        health=HealthLast(Report((Result("telegram", "down", epoch),))),
        home=Home(HomeSt("offline", epoch - 3600)),
        github=Github(Meta(epoch, epoch - 60)),
    )
    rig = OwnRig(own, clock=rig.clock)

    await rig.svc.check_and_alert(UID, rig.notifier)

    subjects = [s.subject for _, s, _ in rig.notifier.sent]
    assert "github_token" in subjects
    assert not set(subjects) & QUIET_IDS
    assert QUIET_IDS == {"google_link", "telegram_bot", "home_link"}  # + the default brain


async def test_no_key_value_ever_reaches_the_board() -> None:
    rig = OwnRig(OwnSources(claude=Brain("refused"), gemini=Brain()))

    text = json.dumps((await rig.svc.board(UID)).to_json())

    assert SECRET not in text and "AIzaGemini" not in text and "AAbbcc" not in text
