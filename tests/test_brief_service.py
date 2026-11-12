# tests/test_brief_service.py — slice 7: BriefService.today/generate/tick end to end (fakes only)
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes
from email.policy import default as default_policy
from typing import Any

import pytest
from brief_fakes import (
    OWNER_UID,
    BriefGoogle,
    SlowDocs,
    connector,
    mail,
    ms,
    timed,
)

from jarvis.brief.models import BriefData, InboxState, SettingsPatch
from jarvis.brief.service import BriefLimitReached, BriefService, SettingsRejected
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ActionRisk, InMemoryApprovalStore, PendingAction
from jarvis.llm.base import Completion, LLMTransientError
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

TIERS = {t: f"mock-{t.value}" for t in ModelTier}
NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)  # 07:00 in Asia/Kolkata
DAY = "2027-01-15"


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@dataclass
class Rig:
    svc: BriefService
    fake: BriefGoogle
    docs: MemoryDocs
    audit: AuditLog
    provider: MockProvider
    clock: Clock
    store: BriefStore

    def collects(self) -> int:
        return sum(1 for e in self.audit._entries if e.tool == "morning_brief.collect")


def _registry(provider: MockProvider, *, trains: bool = False) -> BrainRegistry:
    spec = BrainSpec(id="b", label="B", provider=provider, tiers=TIERS, trains_on_content=trains)
    return BrainRegistry([spec], default_id="b")


async def _rig(
    *,
    linked: bool = True,
    insert: bool = True,
    configured: bool = True,
    trains: bool = False,
    docs: MemoryDocs | None = None,
    ai_cap: int = 6,
    approvals: InMemoryApprovalStore | None = None,
    messages: list[dict[str, Any]] | None = None,
    reads: Any = None,
) -> Rig:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2027-01-15T09:30", "2027-01-15T10:00")],
        messages=[
            mail(
                "m1",
                "Priya <p@x.com>",
                "Budget",
                snippet="please sign",
                internal_ms=ms("2027-01-15T06:40:00+05:30"),
            )
        ]
        if messages is None
        else messages,
    )
    conn = await connector(fake, linked=linked, insert=insert) if configured else None
    docs = docs if docs is not None else MemoryDocs()
    provider, audit, clock = MockProvider(), AuditLog(), Clock(NOW)
    store = BriefStore(docs)
    svc = BriefService(
        store=store,
        google=conn,
        brains=_registry(provider, trains=trains),
        approvals=approvals,
        audit=audit,
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        ai_daily_cap=ai_cap,
        clock=clock,
        reads=reads(conn) if reads is not None else None,
    )
    return Rig(svc, fake, docs, audit, provider, clock, store)


async def _settings(r: Rig, **kw: object) -> None:
    await r.svc.update_settings(OWNER_UID, SettingsPatch(**kw))  # type: ignore[arg-type]


# ---- generate / today ---------------------------------------------------------------------------


async def test_manual_generate_makes_a_ready_brief_with_counts_only_audit() -> None:
    approvals = InMemoryApprovalStore()
    await approvals.put(
        PendingAction(
            tool="gmail_send",
            arguments={},
            summary="x",
            risk=ActionRisk.IRREVERSIBLE,
            scope=f"{OWNER_UID}:s",
        )
    )
    r = await _rig(approvals=approvals)
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert view.status == "ready" and view.brief is not None
    b = view.brief
    assert b.trigger == "manual" and b.data is not None and b.ai is None and b.ai_note is None
    assert b.data.calendar.today[0].title == "Standup" and b.data.jarvis.approvals_waiting == 1
    assert "“Standup”" in b.text and "“Priya” <p@x.com> — “Budget”" in b.text
    assert b.generations_left == 5 and b.inbox.status == "off" and b.created_at == NOW
    (entry,) = [e for e in r.audit._entries if e.tool == "morning_brief.collect"]
    assert entry.agent == "morning_brief" and entry.risk is ActionRisk.READ_ONLY
    assert entry.outcome == "executed" and "events=1" in entry.detail and "unread=1" in entry.detail
    for secret in ("Standup", "Budget", "p@x.com", "please sign"):
        assert secret not in entry.model_dump_json()
    assert {q.method for q in r.fake.requests} == {"GET"}  # nothing written to Google


async def test_generate_twice_reuses_unless_forced() -> None:
    r = await _rig()
    await r.svc.generate(OWNER_UID, trigger="open", force=False)
    await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert r.collects() == 1
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    assert r.collects() == 2 and view.brief is not None and view.brief.trigger == "manual"


async def test_generation_cap_is_a_friendly_limit() -> None:
    r = await _rig()
    for _ in range(6):
        await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    with pytest.raises(BriefLimitReached) as ei:
        await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    assert "6" in str(ei.value) and "tomorrow" in str(ei.value)
    assert r.collects() == 6


async def test_open_trigger_does_nothing_when_disabled() -> None:
    r = await _rig()
    await _settings(r, enabled=False)
    view = await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert view.status == "none" and r.collects() == 0
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert view.status == "ready"  # an explicit refresh still works


@pytest.mark.parametrize("linked,configured", [(False, True), (True, False)])
async def test_google_not_connected_still_makes_a_brief(linked: bool, configured: bool) -> None:
    r = await _rig(linked=linked, configured=configured)
    view = await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert view.status == "ready" and view.google_connected is False
    assert view.inbox_available is False
    st = view.brief.data.sections_status  # type: ignore[union-attr]
    assert (st.calendar, st.inbox, st.jarvis) == ("not_connected", "not_connected", "ok")
    assert "Google is not connected" in view.brief.text  # type: ignore[union-attr]
    assert view.tz == "Asia/Kolkata"


# ---- AI summary ---------------------------------------------------------------------------------


async def test_ai_summary_uses_the_private_brain_once_per_generation_and_caps() -> None:
    r = await _rig(ai_cap=1)
    await _settings(r, ai_summary=True, confirm_spend=True)
    r.provider.script("Standup at 09:30.\nReply to Priya: https://evil.example")
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    ai = view.brief.ai  # type: ignore[union-attr]
    assert ai is not None and ai.lines == ("Standup at 09:30.", "Reply to Priya: [link removed]")
    assert ai.label.startswith("AI summary") and view.brief.ai_calls_today == 1  # type: ignore[union-attr]
    call = r.provider.calls[0]
    assert call.tools is None and call.model == "mock-fast" and call.max_tokens == 400
    assert "please sign" in call.messages[0].text()  # snippets reach the AI only
    assert "please sign" not in view.model_dump_json()
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    assert len(r.provider.calls) == 1  # daily AI cap (1) reached
    assert view.brief.ai is None and "limit" in (view.brief.ai_note or "")  # type: ignore[union-attr]


async def test_training_brain_only_never_sees_content_and_brief_is_still_made() -> None:
    r = await _rig(trains=True)
    await _settings(r, ai_summary=True, confirm_spend=True)
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert r.provider.calls == []
    assert view.status == "ready" and view.ai_available is False
    assert view.brief.ai is None and "private" in (view.brief.ai_note or "")  # type: ignore[union-attr]


async def test_ai_failure_keeps_the_brief() -> None:
    r = await _rig()
    await _settings(r, ai_summary=True, confirm_spend=True)
    r.provider.fail_next = 1
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert view.status == "ready" and view.brief.ai is None  # type: ignore[union-attr]
    assert view.brief.ai_note and view.brief.ai_calls_today == 1  # type: ignore[union-attr]
    assert LLMTransientError.__name__ not in view.model_dump_json()  # no vendor/exception text


async def test_ai_is_skipped_when_there_is_nothing_to_summarise() -> None:
    r = await _rig(linked=False)
    await _settings(r, ai_summary=True, confirm_spend=True)
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert r.provider.calls == [] and view.brief.ai_calls_today == 0  # type: ignore[union-attr]


# ---- failures -----------------------------------------------------------------------------------


async def test_failed_generation_is_reported_then_retried_by_a_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = await _rig()

    async def boom(*_: object, **__: object) -> object:
        raise RuntimeError("secret vendor detail")

    monkeypatch.setattr(r.svc._collector, "collect", boom)
    view = await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert view.status == "failed" and view.brief is not None
    assert view.brief.error and "secret" not in view.brief.error
    monkeypatch.undo()
    res = await r.svc.tick()
    assert res.generated == 1 and (await r.svc.today(OWNER_UID)).status == "ready"


async def test_failed_refresh_keeps_the_earlier_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _rig()
    await r.svc.generate(OWNER_UID, trigger="open", force=False)

    async def boom(*_: object, **__: object) -> object:
        raise RuntimeError("down")

    monkeypatch.setattr(r.svc._collector, "collect", boom)
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    assert view.status == "ready" and view.brief is not None and view.brief.data is not None
    assert view.brief.error and "earlier" in view.brief.error


# ---- tick ---------------------------------------------------------------------------------------


async def test_quiet_ticks_cost_at_most_two_reads_and_no_google_calls() -> None:
    r = await _rig()
    r.clock.at = NOW - timedelta(minutes=1)  # 06:59 local
    r.docs.reads = 0
    res = await r.svc.tick()
    assert (res.checked, res.generated, res.delivered) == (1, 0, 0)
    assert r.docs.reads <= 2 and r.fake.requests == []
    r.clock.at = NOW
    await r.svc.tick()  # makes it
    r.docs.reads, r.fake.requests[:] = 0, []
    r.clock.at = NOW + timedelta(minutes=30)
    res = await r.svc.tick()
    assert res.generated == 0 and r.docs.reads <= 2 and r.fake.requests == []


async def test_tick_generates_and_delivers_once() -> None:
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (1, 1) and len(r.fake.inserts) == 1
    r.clock.at = NOW + timedelta(minutes=30)
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (0, 0) and len(r.fake.inserts) == 1
    view = await r.svc.today(OWNER_UID)
    assert view.brief is not None and view.brief.trigger == "scheduled"
    assert view.brief.inbox.status == "delivered"
    assert "Standup" in r.fake.inserted_raw().decode()


async def test_inbox_off_means_no_insert() -> None:
    r = await _rig()
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (1, 0) and r.fake.inserts == []


async def test_a_brief_made_on_open_is_delivered_at_its_time() -> None:
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.clock.at = NOW - timedelta(minutes=20)
    await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert (await r.svc.tick()).delivered == 0  # before its time
    r.clock.at = NOW
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (0, 1) and r.collects() == 1


async def test_concurrent_ticks_make_one_brief_and_one_insert() -> None:
    r = await _rig(docs=SlowDocs())
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.delay_s = 0.005
    results = await asyncio.gather(*(r.svc.tick() for _ in range(4)))
    assert sum(x.generated for x in results) == 1 and r.collects() == 1
    assert sum(x.delivered for x in results) == 1 and len(r.fake.inserts) == 1


async def test_tick_racing_a_manual_generate() -> None:
    r = await _rig(docs=SlowDocs())
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.delay_s = 0.005
    await asyncio.gather(
        r.svc.tick(), r.svc.generate(OWNER_UID, trigger="manual", force=False), r.svc.tick()
    )
    assert r.collects() == 1
    r.clock.at = NOW + timedelta(minutes=30)  # the next tick delivers if the race left it
    await r.svc.tick()
    assert len(r.fake.inserts) == 1 and r.collects() == 1


async def test_failed_insert_is_never_retried_by_later_ticks() -> None:
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.fail["insert"] = 500
    await r.svc.tick()
    r.fake.fail.clear()
    r.clock.at = NOW + timedelta(minutes=30)
    await r.svc.tick()
    assert len([q for q in r.fake.requests if q.method == "POST"]) == 1
    assert (await r.svc.today(OWNER_UID)).brief.inbox.status == "failed"  # type: ignore[union-attr]


async def test_retention_prunes_older_briefs() -> None:
    r = await _rig()
    for d in range(1, 15):
        day = date(2027, 1, d).isoformat()
        c = await r.store.claim(
            OWNER_UID,
            day,
            tz="Asia/Kolkata",
            trigger="scheduled",
            force=False,
            now=NOW,
            max_generations=6,
        )
        await r.store.finish(c.record.model_copy(update={"status": "ready"}))
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    left = sorted(p.rsplit("_", 1)[1] for p in r.docs._data if p.startswith("jarvis_briefs/"))
    assert left == [f"2027-01-{d:02d}" for d in range(9, 16)]


async def test_calendar_time_zone_is_cached_for_ticks() -> None:
    r = await _rig()
    r.fake.tz = "Europe/London"
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert view.tz == "Europe/London" and view.date == "2027-01-15"
    assert (await r.store.get_settings(OWNER_UID)).tz == "Europe/London"
    assert (await r.svc.today(OWNER_UID)).tz == "Europe/London"


# ---- today view states ------------------------------------------------------------------------


async def test_today_without_a_brief() -> None:
    r = await _rig()
    view = await r.svc.today(OWNER_UID)
    assert view.status == "none" and view.brief is None and view.date == DAY
    assert view.due_at is not None and view.due_at.isoformat() == "2027-01-15T07:00:00+05:30"
    assert view.google_connected and view.inbox_available and view.ai_available
    assert "cost is unknown" in view.ai_cost_note  # mock-fast is not in the price table (F4)
    await _settings(r, enabled=False)
    assert (await r.svc.today(OWNER_UID)).due_at is None


def test_cost_note_uses_the_fast_model_price() -> None:
    tiers = {**TIERS, ModelTier.FAST: "claude-haiku-5-5"}
    spec = BrainSpec(id="anthropic", label="Claude", provider=MockProvider(), tiers=tiers)
    svc = BriefService(
        store=BriefStore(MemoryDocs()),
        google=None,
        approvals=None,
        brains=BrainRegistry([spec], default_id="anthropic"),
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
    )
    note = svc.cost_note()
    # rupees only (slice 7b): ≈ $0.034 a month × 95.24 = ₹3; no dollar figure anywhere
    assert note.startswith("About ₹3 a month for one short summary a day on the fast model")
    assert "at most 6 a day" in note and "$" not in note
    trains = BrainSpec(
        id="g", label="G", provider=MockProvider(), tiers=tiers, trains_on_content=True
    )
    svc2 = BriefService(
        store=BriefStore(MemoryDocs()),
        google=None,
        approvals=None,
        brains=BrainRegistry([trains], default_id="g"),
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
    )
    assert "No private AI brain" in svc2.cost_note()


async def test_stale_marks_are_reported_honestly() -> None:
    r = await _rig()
    c = await r.store.claim(
        OWNER_UID,
        DAY,
        tz="Asia/Kolkata",
        trigger="scheduled",
        force=False,
        now=NOW,
        max_generations=6,
    )
    r.clock.at = NOW + timedelta(minutes=11)
    view = await r.svc.today(OWNER_UID)
    assert view.status == "failed" and view.brief is not None and view.brief.error
    await r.store.finish(
        c.record.model_copy(
            update={"status": "ready", "data": BriefData(date=DAY, tz="Asia/Kolkata")}
        )
    )
    await r.store.begin_inbox(OWNER_UID, DAY, NOW)
    assert (await r.svc.today(OWNER_UID)).brief.inbox.status == "unknown"  # type: ignore[union-attr]
    r.clock.at = NOW + timedelta(minutes=5)
    assert (await r.svc.today(OWNER_UID)).brief.inbox.status == "sending"  # type: ignore[union-attr]


async def test_mark_seen() -> None:
    r = await _rig()
    assert await r.svc.mark_seen(OWNER_UID, DAY) is None
    await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert await r.svc.mark_seen(OWNER_UID, DAY) == NOW
    assert (await r.svc.today(OWNER_UID)).brief.seen_at == NOW  # type: ignore[union-attr]


# ---- settings ---------------------------------------------------------------------------------


async def test_settings_need_confirmations_valid_time_and_the_insert_scope() -> None:
    r = await _rig()
    with pytest.raises(SettingsRejected, match="cost"):
        await _settings(r, ai_summary=True)
    with pytest.raises(SettingsRejected, match="inbox"):
        await _settings(r, inbox_delivery=True)
    with pytest.raises(SettingsRejected, match="04:00"):
        await _settings(r, time="12:00")
    s = await r.svc.update_settings(
        OWNER_UID, SettingsPatch(ai_summary=True, confirm_spend=True, time="06:30")
    )
    assert s.ai_summary and s.time == "06:30" and s.updated_at == NOW
    # already on: repeating the flag needs no new confirmation
    assert (await r.svc.update_settings(OWNER_UID, SettingsPatch(ai_summary=True))).ai_summary
    no_scope = await _rig(insert=False)
    with pytest.raises(SettingsRejected, match="Reconnect Google"):
        await _settings(no_scope, inbox_delivery=True, confirm_inbox=True)
    off = await r.svc.update_settings(OWNER_UID, SettingsPatch(ai_summary=False))
    assert off.ai_summary is False


async def test_inbox_state_view_default() -> None:
    assert InboxState().model_dump()["status"] == "off"


# ---- security review 2026-11-01 ---------------------------------------------------------------


def _inserted_text(fake: BriefGoogle, i: int = 0) -> str:
    msg = message_from_bytes(fake.inserted_raw(i), policy=default_policy)
    return msg.get_content().replace("\r\n", "\n")  # type: ignore[attr-defined]


async def test_a_stale_claim_loser_delivers_nothing_and_the_inbox_gets_the_stored_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 (p_race.py): tick A reads OLD data and stalls past the stale-claim limit; B retakes
    the claim and stores NEW. A's finish is refused, so A must not count a brief as made, must
    not deliver its own older text, and its AI call still counts against the daily budget."""
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True, ai_summary=True, confirm_spend=True)
    r.fake.events = [timed("e1", "OLD EVENT", "2027-01-15T09:30", "2027-01-15T10:00")]
    gate, started = asyncio.Event(), asyncio.Event()
    real = r.svc._collector.collect
    calls = 0

    async def slow_first(uid: str, tz: object, day: object) -> object:
        nonlocal calls
        calls += 1
        got = await real(uid, tz, day)  # type: ignore[arg-type]
        if calls == 1:
            started.set()
            await gate.wait()
        return got

    monkeypatch.setattr(r.svc._collector, "collect", slow_first)
    a = asyncio.create_task(r.svc.tick())
    await started.wait()
    r.clock.at = NOW + timedelta(minutes=11)  # A's claim is now stale
    r.fake.events = [timed("e1", "NEW EVENT", "2027-01-15T09:30", "2027-01-15T10:00")]
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)  # B retakes and finishes
    gate.set()
    res = await a
    assert (res.generated, res.delivered) == (0, 0) and r.fake.inserts == []
    stored = await r.store.get_brief(OWNER_UID, DAY)
    assert stored is not None and "NEW EVENT" in stored.text and "OLD EVENT" not in stored.text
    assert len(r.provider.calls) == 2 and stored.ai_calls_today == 2  # cost honesty
    r.clock.at = NOW + timedelta(minutes=30)
    assert (await r.svc.tick()).delivered == 1
    stored = await r.store.get_brief(OWNER_UID, DAY)
    assert stored is not None and _inserted_text(r.fake) == stored.text
    assert "NEW EVENT" in _inserted_text(r.fake)


async def test_a_503_at_the_first_tick_is_retried_before_the_inbox_gets_it() -> None:
    """F3: calendar unavailable at 07:00 → no delivery yet; Google is back at 07:30 → the
    retry makes the full brief and exactly that is put in the inbox, once."""
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.fail["events"] = 503
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (1, 0) and r.fake.inserts == []
    view = await r.svc.today(OWNER_UID)
    assert view.brief is not None and view.brief.data is not None
    assert view.brief.data.sections_status.calendar == "unavailable"
    assert view.brief.inbox.status == "off"
    r.fake.fail.clear()
    r.clock.at = NOW + timedelta(minutes=30)
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (1, 1)
    stored = await r.store.get_brief(OWNER_UID, DAY)
    assert stored is not None and "“Standup”" in stored.text
    assert "could not be read" not in stored.text and stored.retries == 1
    assert len(r.fake.inserts) == 1 and _inserted_text(r.fake) == stored.text
    r.clock.at = NOW + timedelta(minutes=60)
    assert (await r.svc.tick()).generated == 0 and r.collects() == 2


async def test_a_persistent_outage_is_delivered_once_after_two_retries_with_the_note() -> None:
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.fail["list"] = 503
    got = []
    for minutes in (0, 30, 60, 90, 120):
        r.clock.at = NOW + timedelta(minutes=minutes)
        res = await r.svc.tick()
        got.append((res.generated, res.delivered))
    assert got == [(1, 0), (1, 0), (1, 1), (0, 0), (0, 0)]
    stored = await r.store.get_brief(OWNER_UID, DAY)
    assert stored is not None and (stored.generations, stored.retries) == (3, 2)
    assert len(r.fake.inserts) == 1
    assert "Your inbox could not be read just now." in _inserted_text(r.fake)


async def test_a_partial_brief_is_delivered_at_the_last_tick_of_the_window() -> None:
    """F3: an 11:00 brief has one more scheduler wake-up (11:30); it must not wait past it."""
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True, time="11:00")
    r.fake.fail["list"] = 503
    r.clock.at = NOW + timedelta(hours=4)  # 11:00 local
    assert (await r.svc.tick()).delivered == 0
    r.clock.at = NOW + timedelta(hours=4, minutes=30)  # 11:30: the last tick
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (1, 1) and len(r.fake.inserts) == 1


async def test_a_partial_brief_past_the_generation_cap_is_delivered_without_retrying() -> None:
    r = await _rig()
    await _settings(r, inbox_delivery=True, confirm_inbox=True)
    r.fake.fail["list"] = 503
    r.clock.at = NOW - timedelta(minutes=20)  # before its time: no tick delivers yet
    for _ in range(6):
        await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    r.clock.at = NOW
    res = await r.svc.tick()
    assert (res.generated, res.delivered) == (0, 1) and r.collects() == 6


async def test_not_connected_is_not_retried() -> None:
    r = await _rig(linked=False)
    assert (await r.svc.tick()).generated == 1
    r.clock.at = NOW + timedelta(minutes=30)
    assert (await r.svc.tick()).generated == 0 and r.collects() == 1


async def test_the_ai_call_is_audited_before_it_happens_with_model_and_size_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F4: an append-only `morning_brief.summarize` entry (R2) BEFORE the model call — model
    id and input size, no content — and the cost after it."""
    r = await _rig()
    await _settings(r, ai_summary=True, confirm_spend=True)
    order: list[tuple[str, str, int]] = []
    args: list[dict[str, object]] = []
    real = r.audit.append

    async def spy(**kw: object) -> object:
        order.append((str(kw["tool"]), str(kw["outcome"]), len(r.provider.calls)))
        if kw["tool"] == "morning_brief.summarize":
            args.append(dict(kw["args"]))  # type: ignore[call-overload]
        return await real(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(r.audit, "append", spy)
    r.provider.script("Standup at 09:30.")
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    ai = [o for o in order if o[0] == "morning_brief.summarize"]
    assert ai == [
        ("morning_brief.summarize", "executing", 0),
        ("morning_brief.summarize", "executed", 1),
    ]
    before, after = [e for e in r.audit._entries if e.tool == "morning_brief.summarize"]
    assert before.agent == "morning_brief" and before.risk is ActionRisk.REVERSIBLE
    n = len(r.provider.calls[0].messages[0].text())
    assert args[0] == {"date": DAY, "trigger": "manual", "model": "mock-fast", "input_chars": n}
    assert before.detail == f"model=mock-fast input_chars={n}"  # readable in the trail
    assert after.detail.startswith("model=mock-fast cost_usd=unknown")  # mock-fast: no price
    dumped = json.dumps([e.model_dump(mode="json") for e in r.audit._entries])
    for secret in ("Standup", "Budget", "please sign", "p@x.com", "Priya"):
        assert secret not in dumped


async def test_a_failed_ai_call_is_audited_as_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _rig()
    await _settings(r, ai_summary=True, confirm_spend=True)
    r.provider.fail_next = 1
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    outcomes = [e.outcome for e in r.audit._entries if e.tool == "morning_brief.summarize"]
    assert outcomes == ["executing", "error"]


async def test_no_audit_record_means_no_ai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    r = await _rig()
    await _settings(r, ai_summary=True, confirm_spend=True)
    real = r.audit.append

    async def dead(**kw: object) -> object:
        if kw["tool"] == "morning_brief.summarize":
            raise RuntimeError("audit down")
        return await real(**kw)  # type: ignore[arg-type]

    monkeypatch.setattr(r.audit, "append", dead)
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    assert r.provider.calls == [] and view.brief is not None
    assert view.brief.ai is None and view.brief.ai_note and view.brief.ai_calls_today == 0


async def test_consent_texts_say_what_is_sent_and_an_unpriced_brain_is_not_free() -> None:
    """F4: the confirm message and the cost note say, in plain words, that today's calendar
    titles and mail senders/subjects/previews go to the AI; a model missing from the price
    table is 'cost unknown', never 'No charge'."""
    r = await _rig()
    with pytest.raises(SettingsRejected) as ei:
        await _settings(r, ai_summary=True)
    note = (await r.svc.today(OWNER_UID)).ai_cost_note
    for text in (str(ei.value), note):
        assert "calendar titles" in text and "senders, subjects and previews" in text
    assert "cost" in str(ei.value)
    assert "No charge" not in note and "unknown" in note and len(note) <= 300
    assert "$" not in note and "$" not in str(ei.value)


def _svc_with(fast_model: str, *, brain_id: str = "anthropic") -> BriefService:
    tiers = {**TIERS, ModelTier.FAST: fast_model}
    spec = BrainSpec(id=brain_id, label="Claude", provider=MockProvider(), tiers=tiers)
    return BriefService(
        store=BriefStore(MemoryDocs()),
        google=None,
        approvals=None,
        brains=BrainRegistry([spec], default_id=brain_id),
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
    )


async def test_consent_texts_name_anthropics_claude_and_a_free_model_says_so() -> None:
    svc = _svc_with("claude-haiku-5-5")
    note = svc.cost_note()
    assert "Anthropic's Claude" in note and "calendar titles" in note and len(note) <= 300
    assert "₹" in note and "$" not in note
    with pytest.raises(SettingsRejected, match="Anthropic's Claude"):
        await svc.update_settings(OWNER_UID, SettingsPatch(ai_summary=True))
    assert _svc_with("mock").cost_note().startswith("No charge")  # priced at $0 in the table


async def test_open_with_todays_brief_or_the_cap_makes_no_google_calls() -> None:
    """F10: the calendar time-zone GET is skipped when nothing would be made (cached zone)."""
    r = await _rig()
    await r.svc.generate(OWNER_UID, trigger="open", force=False)
    r.fake.requests.clear()
    view = await r.svc.generate(OWNER_UID, trigger="open", force=False)
    assert view.status == "ready" and r.fake.requests == []
    for _ in range(5):
        await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    r.fake.requests.clear()
    with pytest.raises(BriefLimitReached):
        await r.svc.generate(OWNER_UID, trigger="manual", force=True)
    assert r.fake.requests == []


# ---- R1 I1: the brief-ready hook ----------------------------------------------------------------


async def test_ready_hook_hears_a_scheduled_brief_once() -> None:
    r = await _rig()
    told: list[str] = []

    async def hook(uid: str) -> None:
        told.append(uid)

    r.svc.ready_hook = hook
    await r.svc.tick()
    r.clock.at = NOW + timedelta(minutes=30)
    await r.svc.tick()  # nothing new made: no second alert
    assert told == [OWNER_UID]


async def test_a_failing_ready_hook_never_blocks_the_brief() -> None:
    r = await _rig()

    async def hook(uid: str) -> None:
        raise RuntimeError("telegram down")

    r.svc.ready_hook = hook
    res = await r.svc.tick()
    assert res.generated == 1 and (await r.svc.today(OWNER_UID)).status == "ready"


# ---- R1 fix-4 M9: the audit names the new reads and the laptop ---------------------------------


async def test_the_collect_audit_names_the_deliveries_and_family_reads() -> None:
    r = await _rig()
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    (entry,) = [e for e in r.audit._entries if e.tool == "morning_brief.collect"]
    assert "deliveries=off/0" in entry.detail and "family=off/0" in entry.detail


async def test_an_ai_summary_answered_by_the_laptop_is_audited_as_offline() -> None:
    r = await _rig()
    await _settings(r, ai_summary=True, confirm_spend=True)
    real = r.provider.complete

    async def laptop(**kw: Any) -> Completion:
        done = await real(**kw)
        return done.model_copy(update={"model": "qwen2.5:7b", "offline": True})

    r.provider.complete = laptop  # type: ignore[method-assign]
    await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    done = [e for e in r.audit._entries if e.tool == "morning_brief.summarize"]
    assert done[-1].outcome == "executed"
    assert "offline=true" in done[-1].detail and "model=qwen2.5:7b" in done[-1].detail
    assert "unknown" not in done[-1].detail


# ---- R11.1 I1 gate (INTEGRATION-A 3.4): the real brief reads the whole inbox, as his row says ---
def _mail_row(effect: Any) -> Any:
    """BackgroundReads over a gateway whose only tool is gmail_inbox_summary, with his "Search
    and read email" row set to `effect` (None: the default)."""
    from jarvis.core.guardrails import ConfirmationGate
    from jarvis.tools.background import BackgroundReads
    from jarvis.tools.gateway import Gateway
    from jarvis.tools.gmail_digest import inbox_tools
    from jarvis.tools.policy import Policy, PolicyRule
    from jarvis.tools.registry import ToolRegistry

    def reads(conn: Any) -> Any:
        reg = ToolRegistry()
        for t in inbox_tools(lambda: conn, max_reads=30):
            reg.register(t)
        rules = (
            [PolicyRule(tool_pattern="gmail_*", effect=effect, source="owner")] if effect else []
        )

        class Rows:
            async def rules_for(self, user_id: str) -> list[Any]:
                return rules

        gw = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=Rows()
        )
        return BackgroundReads.of(gw)

    return reads


@pytest.mark.parametrize("effect", ["deny", "ask"])
async def test_r111_never_or_ask_first_on_the_mail_row_means_the_brief_reads_no_mail(
    effect: str,
) -> None:
    from jarvis.tools.policy import Effect

    r = await _rig(reads=_mail_row(Effect(effect)))
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    b = view.brief
    assert b is not None and b.data is not None
    assert [q for q in r.fake.requests if "/gmail/" in q.url.path and q.method == "GET"] == []
    # I1 code review M4: his row, not a fault: paused by his Permissions
    assert b.data.sections_status.inbox == "paused" and "Budget" not in b.text
    assert b.data.calendar.today[0].title == "Standup"  # the other sections are untouched


async def test_r111_an_allowed_read_brings_the_groups_withheld_and_about_n_to_the_brief() -> None:
    from jarvis.tools.policy import Effect

    otp = mail(
        "m2",
        "Bank <alerts@bank.example>",
        "482913 is your one-time password",
        snippet="Use OTP 482913 to sign in.",
        internal_ms=ms("2027-01-15T06:50:00+05:30"),
    )
    people = mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2027-01-15T06:40:00+05:30"))
    r = await _rig(messages=[people, otp], reads=_mail_row(Effect.ALLOW))
    view = await r.svc.generate(OWNER_UID, trigger="manual", force=False)
    b = view.brief
    assert b is not None and b.data is not None
    box = b.data.inbox
    assert box.exact is False and box.withheld == 1 and box.failed == 0  # no INBOX label here
    assert [(g.key, g.unread) for g in box.groups if g.unread] == [("people", 1)]
    assert "INBOX · about 2 unread (showing 1)" in b.text
    assert "Gmail didn't give its own count just now: the number is an estimate." in b.text
    assert "1 from people" in b.text and "1 more looks like a code or a bank message" in b.text
    assert "482913" not in b.text and "one-time password" not in b.text


async def test_r111_the_app_s_brief_reads_mail_through_the_governed_path(
    settings: Any,
) -> None:
    from jarvis.api import create_app
    from jarvis.memory.inmemory import InMemorySessionStore

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        collector = app.state.brief._collector  # noqa: SLF001 - the wiring itself is the gate
        assert collector._reads is not None  # noqa: SLF001
        assert collector._max_reads == settings.mail_summary_max_reads  # noqa: SLF001
