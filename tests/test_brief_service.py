# tests/test_brief_service.py — slice 7: BriefService.today/generate/tick end to end (fakes only)
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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
from jarvis.llm.base import LLMTransientError
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
        ],
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
    assert "Standup" in b.text and "Priya <p@x.com> — Budget" in b.text
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
    assert view.ai_cost_note.startswith("No charge")  # the mock model is unpriced
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
    assert "₹3 a month" in note and "$0.034" in note and "at most 6 a day" in note
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
