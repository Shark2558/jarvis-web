# tests/test_telegram_personal_reads.py -- R2 D12 (I1): the vault list, notes and things are a
# SECOND private group on Telegram with its own switch (`allow_personal_reads`, default off). The
# R1 switch (mail, Drive, documents, contacts) never opens it, and it never opens those. Also the
# vault_expiry alert switch (D5: default off) and both through the store, the API and a real turn.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from telegram_fakes import SECRET, TOKEN, UID, Clock, World, build_world, dev_settings, message

from jarvis.api import create_app
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.models import AlertToggles, TelegramLink
from jarvis.telegram.rules import (
    PERSONAL_PATTERNS,
    PERSONAL_REFUSAL,
    PRIVATE_PATTERNS,
    ChannelRules,
)
from jarvis.telegram.store import TelegramStore
from jarvis.tools import Effect, PolicyRule
from jarvis.tools.base import Tool

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
R2_READS = (
    "vault_list",
    "vault_expiring",
    "kb_search",
    "kb_read",
    "belongings_where",
    "belongings_list",
    "belongings_history",
)
R2_WRITES = (
    "vault_set_dates",
    "kb_add_note",
    "kb_save_link",
    "kb_update",
    "kb_remove",
    "belongings_put",
    "belongings_remove",
)


async def _store(*, private: bool = False, personal: bool = False, paired: bool = True) -> Any:
    store = TelegramStore(MemoryDocs(), prefix="t_", clock=Clock())
    if paired:
        code, _ = await store.start_pairing(UID)
        await store.finish_pairing(code, tg_user_id=1, chat_id=1)
        await store.set_settings(UID, allow_private_reads=private, allow_personal_reads=personal)
    return store


def _denied(rules: list[PolicyRule], tool: str, risk: ActionRisk = R1) -> bool:
    return any(r.effect is Effect.DENY and r.matches(tool, {}, risk) for r in rules)


async def _rules(store: TelegramStore) -> list[PolicyRule]:
    with telegram_turn():
        return await ChannelRules(None, store).rules_for(UID)


def test_the_personal_group_is_the_vault_notes_and_things() -> None:
    assert set(PERSONAL_PATTERNS) == {"vault_*", "kb_*", "belongings_*"}
    assert not set(PERSONAL_PATTERNS) & set(PRIVATE_PATTERNS)
    assert "Telegram" in PERSONAL_REFUSAL and "console" in PERSONAL_REFUSAL


@pytest.mark.parametrize("tool", R2_READS)
async def test_r2_reads_are_refused_on_telegram_by_default(tool: str) -> None:
    assert _denied(await _rules(await _store()), tool)
    assert _denied(await _rules(await _store(paired=False)), tool)  # unpaired: closed too


@pytest.mark.parametrize("tool", R2_WRITES)
async def test_r2_writes_are_refused_on_telegram_by_default(tool: str) -> None:
    assert _denied(await _rules(await _store()), tool, R2)


async def test_the_private_switch_does_not_open_the_personal_group() -> None:
    got = await _rules(await _store(private=True))
    assert not _denied(got, "gmail_read")
    assert all(_denied(got, t) for t in R2_READS)


async def test_the_personal_switch_opens_only_the_personal_group() -> None:
    got = await _rules(await _store(personal=True))
    assert not any(_denied(got, t) for t in R2_READS)
    assert not any(_denied(got, t, R2) for t in R2_WRITES)
    assert _denied(got, "gmail_read") and _denied(got, "drive_read")


async def test_both_switches_on_leave_no_deny_rule() -> None:
    got = await _rules(await _store(private=True, personal=True))
    assert not any(r.effect is Effect.DENY for r in got)


async def test_unreadable_settings_keep_the_personal_group_closed() -> None:
    class Broken(TelegramStore):
        async def get(self, uid: str) -> Any:
            raise RuntimeError("firestore down")

    got = await _rules(Broken(MemoryDocs(), prefix="t_", clock=Clock()))
    assert _denied(got, "kb_read") and _denied(got, "vault_list")


async def test_personal_refusal_words_name_the_switch() -> None:
    got = await _rules(await _store())
    rule = next(r for r in got if r.effect is Effect.DENY and r.matches("kb_read", {}, R1))
    assert rule.reason == PERSONAL_REFUSAL and rule.source == "telegram"


def test_old_links_read_as_switched_off() -> None:
    old = TelegramLink.model_validate({"tg_user_id": 1, "chat_id": 1, "paired_at": "x"})
    assert old.allow_personal_reads is False
    assert AlertToggles().vault_expiry is False  # D5: only after he switches it on


async def test_a_kb_read_on_a_telegram_turn_never_runs_until_switched_on() -> None:
    ran: list[str] = []

    def read(_: dict[str, Any]) -> dict[str, Any]:
        ran.append("read")
        return {"text": "the plumber is Ravi"}

    tool = Tool("kb_read", "read a note", {"type": "object", "properties": {}}, R1, read)
    w = build_world(extra_tools=[tool])
    await w.pair()
    w.provider.script_tool_calls([ToolCall(id="c1", name="kb_read", arguments={})], "I can't.")
    await w.send(message(1, "read my note"))
    assert ran == []
    assert w.audited("kb_read")[-1].outcome == "denied"
    await w.store.set_settings(UID, allow_private_reads=True)  # the R1 switch alone: still no
    w.provider.script_tool_calls([ToolCall(id="c2", name="kb_read", arguments={})], "No.")
    await w.send(message(2, "read my note"))
    assert ran == []
    await w.store.set_settings(UID, allow_personal_reads=True)
    w.provider.script_tool_calls([ToolCall(id="c3", name="kb_read", arguments={})], "Here.")
    await w.send(message(3, "read my note"))
    assert ran == ["read"]


# ---- the API ------------------------------------------------------------------------------------


@pytest.fixture
async def api() -> AsyncIterator[tuple[AsyncClient, World]]:
    w = build_world()
    s = dev_settings(telegram_bot_token=SecretStr(TOKEN), telegram_webhook_secret=SecretStr(SECRET))
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), gateway=w.gateway)
    async with app.router.lifespan_context(app):
        app.state.telegram = w.service
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, w


async def test_the_api_shows_and_changes_the_personal_switch_and_the_vault_alert(
    api: tuple[AsyncClient, World],
) -> None:
    c, w = api
    await w.pair()
    view = (await c.get("/v1/telegram")).json()
    assert view["allow_personal_reads"] is False
    assert view["alerts"]["vault_expiry"] is False
    r = await c.put(
        "/v1/telegram/settings",
        json={"allow_personal_reads": True, "alerts": {"vault_expiry": True}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["allow_personal_reads"] is True
    assert r.json()["alerts"]["vault_expiry"] is True
    assert r.json()["allow_private_reads"] is False  # the other switch is untouched
    (entry,) = w.audited("telegram_settings")
    assert "personal reads on" in entry.detail and entry.detail.startswith("private reads off")
    link = await w.store.get(UID)
    assert link is not None and link.allow_personal_reads and not link.allow_private_reads


async def test_the_api_refuses_a_non_boolean_personal_switch(
    api: tuple[AsyncClient, World],
) -> None:
    c, w = api
    await w.pair()
    r = await c.put("/v1/telegram/settings", json={"allow_personal_reads": "yes"})
    assert r.status_code == 422


async def test_a_vault_alert_is_sent_only_once_switched_on(api: tuple[AsyncClient, World]) -> None:
    _, w = api
    await w.pair()
    off = await w.service.alerts.send(UID, "JARVIS: a document expires soon.", kind="vault_expiry")
    assert off.sent is False and "switched off" in off.reason
    await w.store.set_settings(UID, alerts={"vault_expiry": True})
    on = await w.service.alerts.send(UID, "JARVIS: a document expires soon.", kind="vault_expiry")
    assert on.sent is True
