# tests/test_r14_c_ledger.py -- R14 Part C, D8 "Measure first: a token ledger" (plan
# docs/plans/r14-hardening.md): per model call, per owner per day, counts only, at
# `{prefix}token_ledger/{uid}_{yyyymmdd}` (the owner's day, kept 90 days): calls, cold calls,
# input / cache read / cache write / output tokens from the vendor's own Usage, characters by
# part, tools offered, skills opened, and the call's cost split by part. Never a word of text.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from r14_fakes_c import UID, called, owner, specs

from jarvis.billing.ledger import (
    LEDGER_DAYS,
    PARTS,
    TokenLedgerStore,
    ai_parts_note,
    counts_of,
)
from jarvis.llm.base import ChatMessage, Completion, Role, TextBlock, ToolCall, Usage
from jarvis.recall.retrieval import HEADING
from jarvis.skills.ports import LedgerCall
from jarvis.storage.docs import MemoryDocs

SECRET = "PLANTED-SECRET-WORD"
NOW = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)  # 01:30 on the 15th in Kolkata
TRAILER = "Local time: 15 Nov 01:30. Turn 3." + "\n\n" + HEADING + "\n- [f1] (owner) likes tea"


def _completion(
    *, inp: int = 1_000, read: int = 0, write: int = 0, out: int = 200, cost: float = 0.004,
    calls: tuple[ToolCall, ...] = (), model: str = "claude-sonnet-5-5",
) -> Completion:  # fmt: skip
    usage = Usage(
        input_tokens=inp, output_tokens=out, cache_read_tokens=read, cache_write_tokens=write
    )
    return Completion(
        text=f"reply {SECRET}", tool_calls=list(calls), model=model, provider="anthropic",
        usage=usage, latency_ms=5, cost_usd=cost,
    )  # fmt: skip


def _call(completion: Completion | None = None, *, uid: str = UID) -> LedgerCall:
    messages = (
        owner(f"what about {SECRET}?"),
        *called("web_read", url=f"https://example.com/{SECRET}"),
        ChatMessage(role=Role.USER, content=[TextBlock(text="more")]),
    )
    return LedgerCall(
        uid=uid, brain_id="anthropic", system=f"PERSONA {SECRET}" + "p" * 79,
        trailer=TRAILER + SECRET, messages=messages, tools=specs("web_read", "skills_open"),
        completion=completion if completion is not None else _completion(),
    )  # fmt: skip


def _store(docs: MemoryDocs, now: datetime = NOW) -> TokenLedgerStore:
    return TokenLedgerStore(docs, prefix="jarvis_", tz="Asia/Kolkata", clock=lambda: now)


def test_counts_split_the_characters_by_part() -> None:
    got = counts_of(_call())
    assert got.chars["persona"] == len(f"PERSONA {SECRET}") + 79
    assert got.chars["trailer"] == len("Local time: 15 Nov 01:30. Turn 3.")
    assert got.chars["memory"] == len(TRAILER + SECRET) - got.chars["trailer"]
    assert got.chars["tool_results"] == len("[untrusted tool output]\n{}")
    assert got.chars["history"] > len(f"what about {SECRET}?")
    assert got.chars["tools"] > 0 and set(got.chars) == set(PARTS) - {"replies"}
    assert (got.calls, got.cold_calls, got.tools_offered, got.skills_opened) == (1, 1, 2, 0)


def test_the_cost_is_split_by_part_and_the_output_goes_to_replies() -> None:
    got = counts_of(_call(_completion(cost=0.004, out=200)))
    assert got.usd["replies"] == pytest.approx(200 * 10.0 / 1_000_000)
    assert sum(got.usd.values()) == pytest.approx(0.004, abs=1e-8)
    assert all(v >= 0 for v in got.usd.values())


def test_a_cached_call_is_warm_and_skills_opened_are_counted() -> None:
    opened = ToolCall(id="c9", name="skills_open", arguments={"skill": "finance"})
    got = counts_of(_call(_completion(read=900, calls=(opened,))))
    assert got.cold_calls == 0 and got.skills_opened == 1


async def test_a_day_doc_is_written_per_owner_in_his_time_zone_with_counts_only() -> None:
    docs = MemoryDocs()
    store = _store(docs)
    await store.record(_call())
    await store.record(_call(_completion(read=500, write=100)))
    doc = await docs.get(f"jarvis_token_ledger/{UID}_20261115")  # his day, not UTC's
    assert doc is not None and doc["calls"] == 2 and doc["cold_calls"] == 1
    assert doc["tokens"] == {"input": 2_000, "cache_read": 500, "cache_write": 100, "output": 400}
    assert doc["tools_offered"] == 4 and doc["user_id"] == UID
    assert SECRET not in json.dumps(doc, default=str)  # counts only: no prompt, no reply


async def test_a_call_without_a_completion_records_nothing() -> None:
    docs = MemoryDocs()
    await _store(docs).record(_without())
    assert docs.sets == 0


def _without() -> LedgerCall:
    c = _call()
    return LedgerCall(c.uid, c.brain_id, c.system, c.trailer, c.messages, c.tools, None)


async def test_an_unsafe_owner_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await _store(MemoryDocs()).record(_call(uid="../other"))


async def test_days_older_than_ninety_go_when_a_new_day_starts() -> None:
    docs = MemoryDocs()
    for days in (LEDGER_DAYS + 5, LEDGER_DAYS + 1, LEDGER_DAYS - 1):
        await _store(docs, NOW - timedelta(days=days)).record(_call())
    before = {i for i, _ in await docs.query(_store(docs).query_for(UID))}
    assert len(before) == 3
    await _store(docs).record(_call())  # the first call of a new day prunes
    await _store(docs).record(_call())  # a second call of the same day
    after = {i for i, _ in await docs.query(_store(docs).query_for(UID))}
    assert len(after) == 2 and before - after == {
        f"{UID}_{(NOW - timedelta(days=d)).astimezone(_tz()).strftime('%Y%m%d')}"
        for d in (LEDGER_DAYS + 5, LEDGER_DAYS + 1)
    }


def _tz():  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Kolkata")


async def test_the_month_sums_only_this_months_days() -> None:
    docs = MemoryDocs()
    await _store(docs, NOW - timedelta(days=20)).record(_call())  # 26 Oct: last month
    await _store(docs, NOW - timedelta(days=3)).record(_call())
    await _store(docs).record(_call())
    month = await _store(docs).month(UID)
    assert month.month == "2026-11" and month.days == 2 and month.calls == 2
    assert month.usd["replies"] == pytest.approx(2 * 200 * 10.0 / 1_000_000)
    assert month.usd_total == pytest.approx(0.008, abs=1e-8)


async def test_the_vitals_words_say_where_the_money_goes_in_rupees() -> None:
    docs = MemoryDocs()
    for _ in range(3):
        await _store(docs).record(_call(_completion(cost=0.05)))
    month = await _store(docs).month(UID)
    note = ai_parts_note(month, 95.24)
    assert note.startswith("This month ≈ ₹14.29") and "₹" in note and "$" not in note
    assert "3 calls" in note and len(note) <= 300
    assert ai_parts_note(await _store(MemoryDocs()).month(UID), 95.24).startswith("No AI calls")
