# tests/test_contacts_review.py — slice 12 C review fixes for contacts_search and the tool contract.
#   S2   contacts_search under "Ask first" makes a card ('Look up “Ravi” in your Contacts'); a
#        template that can't be filled never crashes a reply (Tool.summary); every REAL tool's card
#        text is checked, and the permission rows run against the real registered tools.
#   S6   what a look-up returns is kept only in its conversation and deleted with it.
#   C10  the overall deadline, the warm-up TTL on the injected clock, a failed warm-up.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from people_fakes import PEOPLE_UID, FakePeople, people_connector, person

from jarvis.config import Settings, get_settings
from jarvis.contacts.client import TOO_SLOW, WARM_TTL_S, ContactsClient
from jarvis.contacts.tools import contacts_tools
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.documents.tools import document_tools
from jarvis.integrations.google import GoogleAPIError
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.groups import GROUPS, groups_for, rules_for
from jarvis.recall.tools import memory_tools
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.setup import build_gateway
from jarvis.tools.taint import context_trust
from jarvis.undo.tools import undo_tools
from jarvis.web.tools import web_tools

SCOPE = f"{PEOPLE_UID}:sess_1"
RAVI = person("c1", "Ravi Kumar", phones=["98765 43210"], emails=["ravi@example.com"])
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


class Rules:
    def __init__(self, choices: dict[str, Effect]) -> None:
        self.choices = choices

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return rules_for(self.choices)


async def _real_gateway(fake: FakePeople, choices: dict[str, Effect]) -> Gateway:
    gw = build_gateway(get_settings(), google=await people_connector(fake))
    gw.rules = Rules(choices)
    return gw


# ---- S2: contacts_search under "Ask first" ---------------------------------------------------


async def test_ask_first_on_contacts_makes_a_plain_card_not_a_crash() -> None:
    fake = FakePeople(contacts=[RAVI])
    gw = await _real_gateway(fake, {"contacts": Effect.ASK})
    call = ToolCall(id="c", name="contacts_search", arguments={"name": "Ravi"})
    with context_trust(untrusted=False, owner_text="what's Ravi's number?"):
        out = await gw.execute(call, scope=SCOPE)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION and out.pending is not None
    assert out.pending.summary == "Look up “Ravi” in your Contacts"
    assert fake.requests == []


def test_the_contacts_card_text_is_one_clean_line() -> None:
    (tool,) = contacts_tools(ContactsClient(None))  # type: ignore[arg-type]
    assert tool.summary({"name": "Ra\u202evi\nKumar"}) == "Look up “Ravi Kumar” in your Contacts"


def test_a_template_that_cannot_be_filled_falls_back_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tool = Tool("t_lookup", "x", {"type": "object", "properties": {"name": {}}},
                ActionRisk.READ_ONLY, lambda a: None, summary_template="Find {name}")  # fmt: skip
    with caplog.at_level(logging.WARNING):
        text = tool.summary({"name": "Ravi"})  # `name` twice: TypeError, never raised
    assert text.startswith("t_lookup ") and "Ravi" in text
    assert any("card text" in r.getMessage() for r in caplog.records)
    assert all("Ravi" not in r.getMessage() for r in caplog.records)  # no argument in the log


def _sample(schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    if kind == "integer" or kind == "number":
        return 1
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return "Ravi"


def _every_real_tool(gw: Gateway) -> list[Tool]:
    extra = (
        memory_tools(None)  # type: ignore[arg-type]
        + web_tools(None)  # type: ignore[arg-type]
        + document_tools(None)  # type: ignore[arg-type]
        + undo_tools(None)  # type: ignore[arg-type]
    )
    names = {s.name for s in gw.registry.specs()}
    tools = [t for t in (gw.registry.get(n) for n in sorted(names)) if t is not None]
    return tools + [t for t in extra if t.name not in names]


async def test_every_real_tools_card_text_is_made_without_raising() -> None:
    gw = build_gateway(get_settings(), google=await people_connector(FakePeople()))
    tools = _every_real_tool(gw)
    assert {"contacts_search", "whatsapp_draft", "gmail_send", "memory_save"} <= {
        t.name for t in tools
    }
    for tool in tools:
        props = tool.input_schema.get("properties", {})
        args = {k: _sample(v if isinstance(v, dict) else {}) for k, v in props.items()}
        text = tool.summary(args)
        assert isinstance(text, str) and text, tool.name


# ---- S2: the permission rows against the REAL registered tools -----------------------------------

OUTCOME = {
    Effect.ALLOW: GatewayOutcome.EXECUTED,
    Effect.ASK: GatewayOutcome.AWAITING_CONFIRMATION,
    Effect.DENY: GatewayOutcome.DENIED,
}
REAL_CALLS = {
    "contacts": ("contacts_search", {"name": "Ravi"}),
    "whatsapp": ("whatsapp_draft", {"to": "98765 43210", "text": "Running late"}),
}


@pytest.mark.parametrize(("gid", "effect"), [(g, e) for g in REAL_CALLS for e in Effect])
async def test_each_row_governs_its_real_tool(gid: str, effect: Effect) -> None:
    fake = FakePeople(contacts=[RAVI])
    gw = await _real_gateway(fake, {gid: effect})
    name, args = REAL_CALLS[gid]
    with context_trust(untrusted=False, owner_text="WhatsApp 98765 43210, and find Ravi"):
        out = await gw.execute(ToolCall(id="p", name=name, arguments=args), scope=SCOPE)
    assert out.outcome is OUTCOME[effect], out.error
    if effect is Effect.ASK:
        assert out.pending is not None and out.pending.summary
    if effect is Effect.DENY:
        assert "switched off by the owner in Permissions" in (out.error or "")


async def test_ask_first_on_every_row_makes_a_card_for_every_real_tool_without_raising() -> None:
    """The S2 class of bug: a card that can't be written crashed the whole reply."""
    gw = await _real_gateway(FakePeople(contacts=[RAVI]), {})
    tools = [t for t in _every_real_tool(gw) if groups_for(t.name, t.risk)]
    asked = {g.id: Effect.ASK for g in GROUPS if Effect.ASK in g.choices}
    gw.rules = Rules(asked)
    checked = 0
    for tool in tools:
        if gw.registry.get(tool.name) is None:
            continue  # memory / web / documents need their services to run (cards checked above)
        props = tool.input_schema.get("properties", {})
        args = {k: _sample(v if isinstance(v, dict) else {}) for k, v in props.items()}
        with context_trust(untrusted=False, owner_text="x"):
            out = await gw.execute(ToolCall(id="p", name=tool.name, arguments=args), scope=SCOPE)
        assert out.outcome is not GatewayOutcome.EXECUTED or tool.risk is ActionRisk.READ_ONLY
        checked += 1
    assert checked >= 10


# ---- S6: a look-up is kept only in its conversation, and deleted with it -----------------------


async def test_a_lookup_lives_in_its_conversation_and_is_deleted_with_it(
    settings: Settings,
) -> None:
    from people_fakes import people_connector as connector

    fake = FakePeople(contacts=[RAVI])

    async def no_wait(_: float) -> None:
        return None

    client = ContactsClient(await connector(fake), sleep=no_wait)
    reg = ToolRegistry()
    for t in contacts_tools(client):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    provider = MockProvider()
    provider.script_tool_calls(
        [ToolCall(id="c", name="contacts_search", arguments={"name": "Ravi"})], "+91 98765 43210"
    )
    store = InMemorySessionStore()
    s = settings.model_copy(update={"tools_enabled": True})
    brain = Brain(router=ModelRouter(provider, TIERS), store=store, settings=s, gateway=gw)
    resp = await brain.chat(ChatRequest(message="Ravi's number?", user_id=PEOPLE_UID))
    kept = await store.get(resp.session_id)
    assert kept is not None and "+919876543210" in kept.model_dump_json()  # kept with the chat
    entries = (await gw.audit.tail(10)).entries
    assert all("9876543210" not in e.model_dump_json() for e in entries)  # the audit has no copy
    assert await brain.forget(resp.session_id, user_id=PEOPLE_UID)
    assert await store.get(resp.session_id) is None  # deleted with it


def test_no_wording_claims_jarvis_keeps_no_copy() -> None:
    from pathlib import Path

    import jarvis.contacts.tools as tools_mod

    root = Path(__file__).resolve().parents[1]
    plan = (root / "docs/plans/phase2-slice12-integrations.md").read_text(encoding="utf-8")
    hint = {g.id: g.hint for g in GROUPS}["contacts"]
    for text in (hint, tools_mod.__doc__ or "", plan):
        low = text.lower()
        assert "keeps no copy" not in low and "never stored" not in low
    assert "deleted with it" in hint


# ---- C10: deadline, warm-up TTL, a failed warm-up ---------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_the_overall_deadline_answers_too_slow() -> None:
    fake = FakePeople(contacts=[RAVI], cold_searches=1)
    stuck = asyncio.Event()

    async def hang(_: float) -> None:
        await stuck.wait()  # the cold-cache wait never ends

    client = ContactsClient(await people_connector(fake), sleep=hang, deadline_s=0.05)
    with pytest.raises(GoogleAPIError) as err:
        await client.search(PEOPLE_UID, "Ravi")
    assert str(err.value) == TOO_SLOW and "too long" in TOO_SLOW


async def test_the_warm_up_is_sent_again_after_its_ttl() -> None:
    fake = FakePeople(contacts=[RAVI])
    clock = Clock()

    async def no_wait(_: float) -> None:
        return None

    client = ContactsClient(await people_connector(fake), sleep=no_wait, clock=clock)
    await client.search(PEOPLE_UID, "Ravi")
    clock.now += WARM_TTL_S - 1
    await client.search(PEOPLE_UID, "Ravi")
    assert fake.searches() == ["", "Ravi", "Ravi"]
    clock.now += 2  # past the TTL since the warm-up
    await client.search(PEOPLE_UID, "Ravi")
    assert fake.searches() == ["", "Ravi", "Ravi", "", "Ravi"]


async def test_a_failed_warm_up_still_searches_once() -> None:
    fake = FakePeople(contacts=[RAVI], fail_warm_up=503)

    async def no_wait(_: float) -> None:
        return None

    client = ContactsClient(await people_connector(fake), sleep=no_wait)
    found = await client.search(PEOPLE_UID, "Ravi")
    assert [c.name for c in found.contacts] == ["Ravi Kumar"]
    searched = fake.searches()
    assert searched.count("Ravi") == 1 and searched[-1] == "Ravi"
    fake.fail_warm_up = None
    await client.search(PEOPLE_UID, "Ravi")  # not marked warm: the next search warms up again
    assert fake.searches()[len(searched) :] == ["", "Ravi"]
