# tests/test_telegram_rules.py -- R1 D4: private reads are refused on Telegram unless the owner
# switched them on. ChannelRules wraps the gateway's OwnerRules and appends DENY rules (source
# "telegram") only during a Telegram turn. No gateway change.
from __future__ import annotations

from typing import Any

import pytest
from telegram_fakes import UID, Clock, build_world, message

from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.rules import PRIVATE_PATTERNS, REFUSAL, ChannelRules
from jarvis.telegram.store import TelegramStore
from jarvis.tools import Effect, PolicyRule
from jarvis.tools.base import Tool

R1 = ActionRisk.READ_ONLY


class Inner:
    def __init__(self, rules: list[PolicyRule] | None = None, fail: bool = False) -> None:
        self.rules = rules or []
        self.fail = fail

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.fail:
            raise RuntimeError("down")
        return list(self.rules)


async def _store(*, reads: bool | None = None) -> TelegramStore:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    if reads is not None:
        code, _ = await store.start_pairing(UID)
        await store.finish_pairing(code, tg_user_id=1, chat_id=1)
        await store.set_settings(UID, allow_private_reads=reads)
    return store


def _denied(rules: list[PolicyRule], tool: str) -> bool:
    return any(r.effect is Effect.DENY and r.matches(tool, {}, R1) for r in rules)


async def test_outside_a_telegram_turn_nothing_is_added() -> None:
    own = [PolicyRule(tool_pattern="x_*", effect=Effect.ASK, source="owner")]
    rules = ChannelRules(Inner(own), await _store(reads=False))
    assert await rules.rules_for(UID) == own


@pytest.mark.parametrize(
    "tool",
    ["gmail_search", "gmail_read", "gmail_unread_digest", "drive_list", "drive_read",
     "drive_search", "doc_read", "doc_search", "docs_list", "contacts_search"],
)  # fmt: skip
async def test_private_tools_are_denied_on_telegram_by_default(tool: str) -> None:
    rules = ChannelRules(Inner(), await _store(reads=False))
    with telegram_turn():
        got = await rules.rules_for(UID)
    assert _denied(got, tool)
    assert all(r.source == "telegram" for r in got)


@pytest.mark.parametrize(
    "tool",
    ["gmail_track_packages", "calendar_list_events", "reminder_add", "task_add", "grocery_add",
     "maps_search", "web_search", "memory_save", "whatsapp_draft", "gmail_create_draft"],
)  # fmt: skip
async def test_everyday_tools_stay_allowed(tool: str) -> None:
    rules = ChannelRules(Inner(), await _store(reads=False))
    with telegram_turn():
        got = await rules.rules_for(UID)
    assert not _denied(got, tool)


async def test_the_owner_can_switch_private_reads_on() -> None:
    rules = ChannelRules(Inner(), await _store(reads=True))
    with telegram_turn():
        assert await rules.rules_for(UID) == []


async def test_unpaired_or_unreadable_state_fails_closed() -> None:
    with telegram_turn():
        unpaired = await ChannelRules(Inner(), await _store()).rules_for(UID)
    assert _denied(unpaired, "gmail_read")

    class Broken(TelegramStore):
        async def get(self, uid: str) -> Any:
            raise RuntimeError("firestore down")

    broken = Broken(MemoryDocs(), prefix="t_", clock=Clock())
    with telegram_turn():
        got = await ChannelRules(Inner(), broken).rules_for(UID)
    assert _denied(got, "gmail_search")


async def test_the_inner_rules_come_first_and_their_failure_propagates() -> None:
    own = [PolicyRule(tool_pattern="x_*", effect=Effect.ASK, source="owner")]
    with telegram_turn():
        got = await ChannelRules(Inner(own), await _store(reads=False)).rules_for(UID)
    assert got[0] == own[0] and len(got) > 1
    with pytest.raises(RuntimeError), telegram_turn():
        await ChannelRules(Inner(fail=True), await _store(reads=False)).rules_for(UID)


def test_every_private_family_is_listed() -> None:
    assert {"gmail_search", "gmail_read", "gmail_unread_digest", "drive_*", "doc_*", "docs_*",
            "contacts_*"} <= set(PRIVATE_PATTERNS)  # fmt: skip
    assert "Telegram" in REFUSAL and "console" in REFUSAL


async def test_through_the_gateway_gmail_read_is_refused_on_telegram_but_not_in_the_console() -> (
    None
):
    ran: list[str] = []

    def read(_: dict[str, Any]) -> dict[str, Any]:
        ran.append("read")
        return {"subject": "hello"}

    tool = Tool("gmail_read", "read mail", {"type": "object", "properties": {}}, R1, read)
    w = build_world(extra_tools=[tool])
    w.gateway.rules = ChannelRules(Inner(), w.store)
    await w.pair()
    w.provider.script_tool_calls([ToolCall(id="c1", name="gmail_read", arguments={})], "I can't.")
    await w.send(message(1, "read my latest email"))
    assert ran == []
    denied = w.audited("gmail_read")
    assert denied and denied[-1].outcome == "denied"
    # the same call in the console (no Telegram turn) runs
    w.provider.script_tool_calls([ToolCall(id="c2", name="gmail_read", arguments={})], "Here.")
    from jarvis.core.models import ChatRequest

    await w.brain.chat(ChatRequest(message="read my latest email", user_id=UID))
    assert ran == ["read"]
    # with the switch on, Telegram may read too
    await w.store.set_settings(UID, allow_private_reads=True)
    w.provider.script_tool_calls([ToolCall(id="c3", name="gmail_read", arguments={})], "Here.")
    await w.send(message(2, "read my latest email again"))
    assert ran == ["read", "read"]
