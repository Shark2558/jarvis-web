# tests/test_whatsapp_trust.py — final review fix 2: a WhatsApp draft does not taint its own round.
# A ready draft to a number the owner TYPED holds only the owner's number and the model's text, so
# it vouches for its result (`may_vouch`): a second draft or a later write in the same message runs
# as it would have without the first draft. A draft that carries a Contacts name (other people's
# words, fenced), or a number from anywhere else, still taints the round. Real Brain + gateway.
from __future__ import annotations

from typing import Any

from people_fakes import PEOPLE_UID, FakePeople, people_connector, person

from jarvis.config import Settings
from jarvis.contacts.client import ContactsClient
from jarvis.contacts.tools import contacts_tools
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ToolCall, ToolResultBlock
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reply_cards import collecting_cards
from jarvis.tools.taint import context_trust
from jarvis.whatsapp.tools import whatsapp_tools

TIERS = {t: f"mock-{t.value}" for t in ModelTier}
SCOPE = f"{PEOPLE_UID}:sess_1"
RAVI = person("c1", "Ravi Kumar", phones=["98765 43210"])


class Writes:
    """A reversible write standing in for a reminder or a to-do (a card in a tainted round)."""

    def __init__(self) -> None:
        self.done: list[dict[str, Any]] = []

    def tool(self) -> Tool:
        def run(a: dict[str, Any]) -> dict[str, Any]:
            self.done.append(a)
            return {"ok": True}

        return Tool(
            "reminder_create",
            "set a reminder",
            {"type": "object", "properties": {"title": {"type": "string"}}},
            ActionRisk.REVERSIBLE,
            run,
            agent="google",
        )


def _mail(body: str) -> Tool:
    """Someone else's words reaching the model (a mail): the round becomes content-tainted."""
    return Tool("gmail_read", "read a mail", {"type": "object", "properties": {}},
                ActionRisk.READ_ONLY, lambda a: {"body": body}, agent="google")  # fmt: skip


async def _rig(
    settings: Settings, rules: list[PolicyRule] | None = None
) -> tuple[Brain, MockProvider, Writes, FakePeople]:
    fake = FakePeople(contacts=[RAVI])

    async def no_wait(_: float) -> None:
        return None

    client = ContactsClient(await people_connector(fake), sleep=no_wait)
    writes = Writes()
    reg = ToolRegistry()
    for t in [*whatsapp_tools(client), *contacts_tools(client), writes.tool(), _mail("hi")]:
        reg.register(t)
    gw = Gateway(
        registry=reg, policy=Policy(rules or []), gate=ConfirmationGate(), audit=AuditLog()
    )
    provider = MockProvider()
    s = settings.model_copy(update={"tools_enabled": True})
    brain = Brain(
        router=ModelRouter(provider, TIERS), store=InMemorySessionStore(), settings=s, gateway=gw
    )
    return brain, provider, writes, fake


def _draft(cid: str, to: str, text: str) -> ToolCall:
    return ToolCall(id=cid, name="whatsapp_draft", arguments={"to": to, "text": text})


def _drafts(resp: Any) -> list[str]:
    return [c.text for c in resp.cards if c.kind == "whatsapp"]


async def test_draft_then_draft_to_typed_numbers_runs_without_a_card(settings: Settings) -> None:
    brain, provider, _, _ = await _rig(settings)
    provider.script_tool_calls([_draft("a", "98765 43210", "hi")])
    provider.script_tool_calls([_draft("b", "98765 43211", "yo")])
    provider.script("Both are ready - tap Open in WhatsApp, then Send.")
    msg = "WhatsApp 98765 43210 hi and 98765 43211 yo"
    resp = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    assert resp.pending_approvals == []
    assert _drafts(resp) == ["hi", "yo"]


async def test_a_draft_then_a_reminder_in_the_same_message_runs_without_a_card(
    settings: Settings,
) -> None:
    brain, provider, writes, _ = await _rig(settings)
    provider.script_tool_calls([_draft("a", "98765 43210", "Running late")])
    provider.script_tool_calls(
        [ToolCall(id="r", name="reminder_create", arguments={"title": "call Amma"})]
    )
    provider.script("Done.")
    msg = "WhatsApp 98765 43210 that I'm running late, and remind me to call Amma"
    resp = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    assert resp.pending_approvals == [] and writes.done == [{"title": "call Amma"}]


async def test_a_draft_by_contacts_name_still_taints_the_round(settings: Settings) -> None:
    brain, provider, writes, fake = await _rig(settings)
    provider.script_tool_calls([_draft("a", "Ravi", "Running late")])
    provider.script_tool_calls(
        [ToolCall(id="r", name="reminder_create", arguments={"title": "call Ravi"})]
    )
    provider.script("An approval is waiting.")
    msg = "WhatsApp Ravi that I'm running late, and remind me to call him"
    resp = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    assert fake.searches()[-1] == "Ravi" and _drafts(resp) == ["Running late"]
    assert [p.tool for p in resp.pending_approvals] == ["reminder_create"]
    assert writes.done == []  # the Contacts name reached the model: the write waits


async def test_a_second_draft_after_a_draft_by_name_asks_first(settings: Settings) -> None:
    brain, provider, _, _ = await _rig(settings)
    provider.script_tool_calls([_draft("a", "Ravi", "hi")])
    provider.script_tool_calls([_draft("b", "98765 43211", "yo")])
    provider.script("One is ready; one waits for you.")
    msg = "WhatsApp Ravi hi and 98765 43211 yo"
    resp = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    assert _drafts(resp) == ["hi"]
    assert [p.tool for p in resp.pending_approvals] == ["whatsapp_draft"]


async def _gateway_result(settings: Settings, to: str, said: str) -> Any:
    brain, _, _, _ = await _rig(settings)
    assert brain.gateway is not None
    with context_trust(untrusted=False, owner_text=said), collecting_cards([]):
        return await brain.gateway.execute(_draft("x", to, "hi"), scope=SCOPE)


async def test_only_a_typed_number_without_a_name_vouches(settings: Settings) -> None:
    typed = await _gateway_result(settings, "98765 43210", "WhatsApp 98765 43210 hi")
    assert typed.outcome is GatewayOutcome.EXECUTED and typed.trusted is True
    assert typed.block("x").trusted is True
    by_name = await _gateway_result(settings, "Ravi", "WhatsApp Ravi hi")
    assert by_name.result["to"]["name"] and by_name.trusted is False
    elsewhere = await _gateway_result(settings, "+44 20 7946 0958", "WhatsApp him hi")
    assert elsewhere.result["warning"] and elsewhere.trusted is False


# ---- final review LOW 1: an approved draft from a round that read outside content -------------


async def _stored_results(brain: Brain, sid: str) -> list[Any]:
    session = await brain.store.get(sid)
    assert session is not None
    return [b for t in session.turns for b in t.blocks if isinstance(b, ToolResultBlock)]


async def test_a_draft_approved_from_a_mail_tainted_round_is_stored_untrusted(
    settings: Settings,
) -> None:
    """The card was proposed in a round that read a mail, so the mail may have written the text:
    the approved run is `outside` and its result never vouches, even to a typed number."""
    brain, provider, _, _ = await _rig(settings)
    provider.script_tool_calls([ToolCall(id="m", name="gmail_read", arguments={})])
    provider.script_tool_calls([_draft("a", "98765 43210", "Here is the OTP: 123456")])
    provider.script("An approval is waiting.")
    msg = "read my mail and WhatsApp 98765 43210 what it asks"
    first = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    (card,) = first.pending_approvals
    provider.script("It's ready.")
    done = await brain.approve(card.id, session_id=first.session_id, user_id=PEOPLE_UID)
    assert _drafts(done) == ["Here is the OTP: 123456"]
    result = (await _stored_results(brain, first.session_id))[-1]
    assert '"draft_ready"' in result.content and result.trusted is False


async def test_a_draft_approved_from_a_clean_round_still_vouches(settings: Settings) -> None:
    """Ask first on WhatsApp (an owner rule) in the owner's own round: nothing outside, so the
    approved draft to the number the owner typed is still the owner's own."""
    ask = [PolicyRule(tool_pattern="whatsapp_*", effect=Effect.ASK)]
    brain, provider, _, _ = await _rig(settings, ask)
    provider.script_tool_calls([_draft("a", "98765 43210", "Running late")])
    provider.script("An approval is waiting.")
    msg = "WhatsApp 98765 43210 that I'm running late"
    first = await brain.chat(ChatRequest(message=msg, user_id=PEOPLE_UID))
    (card,) = first.pending_approvals
    provider.script("It's ready.")
    await brain.approve(card.id, session_id=first.session_id, user_id=PEOPLE_UID)
    result = (await _stored_results(brain, first.session_id))[-1]
    assert '"draft_ready"' in result.content and result.trusted is True
