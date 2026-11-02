# tests/test_draft_recipients.py — slice 11 D7 (a): a Gmail draft addressed to someone the owner
# did not type in THIS message asks first. The rule: every recipient of gmail_create_draft must be
# an address written in the owner's own typed words of the current message (normalised like a
# recipient); otherwise the call becomes an R2 approval card (no passkey). Typed-in-this-message
# drafts still run without a card (unless the round is tainted or spoken, as before); an owner's
# "Allow" never relaxes the rule; outside a turn (an approval being carried out) it does not apply.
from __future__ import annotations

from typing import Any

import httpx
import pytest
from google_fakes import GOOGLE_UID, FakeGoogle

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, AskReason, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.integrations.google import GoogleConnector
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.groups import rules_for
from jarvis.tools.addresses import MAX_TYPED, typed_addresses
from jarvis.tools.audit import AuditLog
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.gmail import gmail_tools
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust, owner_text

GM = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = f"{GOOGLE_UID}:sess_1"
TIERS = {
    ModelTier.FAST: "mock-fast",
    ModelTier.BALANCED: "mock-balanced",
    ModelTier.STRONG: "mock-strong",
}


def _draft(to: str) -> dict[str, Any]:
    return {"to": to, "subject": "Friday", "body": "See you then."}


@pytest.fixture
def gw(connected: GoogleConnector, fake_google: FakeGoogle) -> Gateway:
    fake_google.on(
        "POST", f"{GM}/drafts", httpx.Response(200, json={"id": "d1", "message": {"id": "m"}})
    )
    reg = ToolRegistry()
    for t in gmail_tools(connected):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def _draft_in_turn(gw: Gateway, said: str, to: str, **trust: Any) -> GatewayResult:
    call = ToolCall(id="c", name="gmail_create_draft", arguments=_draft(to))
    with context_trust(untrusted=trust.get("untrusted", False), owner_text=said):
        return await gw.execute(call, scope=SCOPE)


# ---- the owner's typed addresses ------------------------------------------------------------


def test_typed_addresses_are_found_and_normalised_like_recipients() -> None:
    said = (
        "Draft to Ravi@Example.COM, cc <priya@x.co>. Also mailto:ops@team.example.org! "
        "and rémy@café.fr or (lead@corp.example)."
    )
    found = typed_addresses(said)
    assert {"ravi@example.com", "priya@x.co", "ops@team.example.org", "lead@corp.example"} <= found
    assert "ravi@example.com" in typed_addresses("ravi@example.com.")  # trailing full stop
    assert typed_addresses("café.fr@") == frozenset()
    assert "a@xn--caf-dma.fr" in typed_addresses("write to a@café.fr")  # IDN as recipients are


def test_typed_addresses_ignores_text_that_is_not_an_address() -> None:
    assert typed_addresses("") == frozenset()
    assert typed_addresses("meet @ 5 at the cafe, email me later") == frozenset()
    assert typed_addresses('"a,b"@evil.example') == frozenset()  # quoted local parts: never
    assert typed_addresses("x" * 300 + "@example.com") == frozenset()  # too long: not an address


def test_typed_addresses_reads_a_bounded_number() -> None:
    said = " ".join(f"p{i}@example.com" for i in range(MAX_TYPED + 10))
    found = typed_addresses(said)
    assert len(found) == MAX_TYPED and "p0@example.com" in found
    assert f"p{MAX_TYPED + 5}@example.com" not in found


@pytest.mark.parametrize(
    "said",
    [
        "x" * 16_000,  # one long token, no spaces
        "a@" * 8_000,  # @ everywhere, no spaces
        ("y" * 250 + "@ ") * 64,  # tokens at the length limit, each ending in a bare @
        ("ravi@example.com " + "z" * 300 + " ") * 50,  # addresses among over-long tokens
    ],
    ids=["no-spaces", "at-signs", "limit-tokens", "mixed"],
)
def test_typed_addresses_is_linear(said: str) -> None:
    """Slice 11 review LOW-2: the owner's message (up to 16,000 characters) is read in one pass,
    whitespace token by token; a token longer than any address is never scanned."""
    import time

    typed_addresses(said[:100])  # warm the regex and IDNA codecs
    t0 = time.perf_counter()
    typed_addresses(said)
    assert time.perf_counter() - t0 < 0.05


def test_typed_addresses_skips_a_token_longer_than_any_address() -> None:
    ok = "a" * 60 + "@" + "b" * 60 + "." + "c" * 60 + ".example.com"
    assert typed_addresses(f"to {ok}.") == frozenset({ok})
    assert typed_addresses(f"to <{ok}>,{'d' * 120}") == frozenset()  # one token, too long


def test_the_draft_rule_parses_recipients_first_and_reads_the_text_only_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.tools import gmail

    scans: list[str] = []
    real = gmail.typed_addresses
    monkeypatch.setattr(gmail, "typed_addresses", lambda t: scans.append(t) or real(t))
    [tool] = [t for t in gmail_tools(None) if t.name == "gmail_create_draft"]  # type: ignore[arg-type]
    with context_trust(untrusted=False, owner_text="no address in here at all"):
        assert tool.asks(_draft("ravi@example.com")) is True
    with context_trust(untrusted=False, owner_text="write to priya@example.com"):
        assert tool.asks(_draft("ravi@example.com")) is True  # "ravi" was never typed
        assert tool.asks(_draft("not an address")) is True  # unparseable: ask, no scan
    assert scans == []
    with context_trust(untrusted=False, owner_text="write to Ravi@Example.com"):
        assert tool.asks(_draft("ravi@example.com")) is False
    assert scans == ["write to Ravi@Example.com"]


def test_owner_text_is_none_outside_a_turn_and_reset_after() -> None:
    assert owner_text() is None
    with context_trust(untrusted=False, owner_text="hi ravi@example.com"):
        assert owner_text() == "hi ravi@example.com"
    assert owner_text() is None


# ---- the rule, at the gateway ---------------------------------------------------------------


async def test_a_draft_to_an_address_typed_this_message_runs(gw: Gateway) -> None:
    out = await _draft_in_turn(
        gw, "Draft a note to Ravi@Example.com about Friday", "ravi@example.com"
    )
    assert out.outcome is GatewayOutcome.EXECUTED, out.error


async def test_a_draft_to_an_address_the_owner_never_typed_becomes_an_r2_card(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    out = await _draft_in_turn(gw, "Draft a reply to the sender", "attacker@evil.example")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert out.pending is not None and out.pending.tool_risk is ActionRisk.REVERSIBLE
    assert not out.pending.irreversible  # an R2 card: no passkey
    # slice 11 review MEDIUM-1: the owner reviews it on its own card, never with Approve all
    assert out.pending.reason is AskReason.DRAFT_RECIPIENT and out.pending.bulk_ok is False
    assert "attacker@evil.example" in out.pending.summary
    assert fake_google.sent("POST", "/drafts") == []


async def test_one_untyped_recipient_among_typed_ones_is_enough_to_ask(gw: Gateway) -> None:
    out = await _draft_in_turn(
        gw, "draft to ravi@example.com", "ravi@example.com, attacker@evil.example"
    )
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION


async def test_an_untainted_round_still_asks(gw: Gateway) -> None:
    """The case the tainted-round rule does not cover: no outside content this round."""
    out = await _draft_in_turn(gw, "draft the usual note", "ravi@example.com", untrusted=False)
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION


async def test_an_owner_allow_does_not_relax_it(connected: GoogleConnector) -> None:
    class Rules:
        async def rules_for(self, user_id: str) -> list[PolicyRule]:
            return rules_for({"email_draft": Effect.ALLOW})

    reg = ToolRegistry()
    for t in gmail_tools(connected):
        reg.register(t)
    gw = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=Rules()
    )
    out = await _draft_in_turn(gw, "draft something", "someone@else.example")
    assert out.outcome is GatewayOutcome.AWAITING_CONFIRMATION


async def test_an_owner_never_still_wins(connected: GoogleConnector) -> None:
    class Rules:
        async def rules_for(self, user_id: str) -> list[PolicyRule]:
            return rules_for({"email_draft": Effect.DENY})

    reg = ToolRegistry()
    for t in gmail_tools(connected):
        reg.register(t)
    gw = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog(), rules=Rules()
    )
    out = await _draft_in_turn(gw, "draft to x@y.example", "x@y.example")
    assert out.outcome is GatewayOutcome.DENIED


async def test_outside_a_turn_the_rule_does_not_apply(gw: Gateway) -> None:
    call = ToolCall(id="c", name="gmail_create_draft", arguments=_draft("ravi@example.com"))
    out = await gw.execute(call, scope=SCOPE)  # a script / an approval being carried out
    assert out.outcome is GatewayOutcome.EXECUTED


async def test_a_card_made_by_the_rule_is_approved_normally(
    gw: Gateway, fake_google: FakeGoogle
) -> None:
    card = await _draft_in_turn(gw, "reply to them", "attacker@evil.example")
    assert card.pending is not None
    call = ToolCall(id="c", name="gmail_create_draft", arguments=_draft("attacker@evil.example"))
    out = await gw.execute(call, scope=SCOPE, confirmation_id=card.pending.id)
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    assert len(fake_google.sent("POST", "/drafts")) == 1


def test_a_failing_ask_check_asks() -> None:
    def boom(a: dict[str, Any]) -> bool:
        raise ValueError("cannot tell")

    t = Tool("t", "d", {"type": "object"}, ActionRisk.REVERSIBLE, lambda a: None, ask_when=boom)
    assert t.asks({}) is True
    plain = Tool("p", "d", {"type": "object"}, ActionRisk.REVERSIBLE, lambda a: None)
    assert plain.asks({}) is False


# ---- end to end: the owner's own words of THIS message --------------------------------------


@pytest.fixture
def brain(settings: Settings, provider: MockProvider, gw: Gateway) -> Brain:
    return Brain(
        router=ModelRouter(provider, TIERS),
        store=InMemorySessionStore(),
        settings=settings,
        gateway=gw,
        # the Google uid: the connected fake's tokens are stored for it
    )


async def _turn(brain: Brain, provider: MockProvider, said: str, to: str, sid: str | None) -> Any:
    provider.script_tool_calls(
        [ToolCall(id="d", name="gmail_create_draft", arguments=_draft(to))], "Done, Sir."
    )
    return await brain.chat(ChatRequest(message=said, session_id=sid, user_id=GOOGLE_UID))


async def test_brain_typed_this_message_runs_typed_earlier_asks(
    brain: Brain, provider: MockProvider, fake_google: FakeGoogle
) -> None:
    first = await _turn(
        brain, provider, "Draft to ravi@example.com about Friday", "ravi@example.com", None
    )
    assert first.pending_approvals == [] and len(fake_google.sent("POST", "/drafts")) == 1
    again = await _turn(
        brain, provider, "Make it shorter and redo it", "ravi@example.com", first.session_id
    )
    assert [p.tool for p in again.pending_approvals] == ["gmail_create_draft"]
    assert again.pending_approvals[0].tool_risk == "reversible"
    assert len(fake_google.sent("POST", "/drafts")) == 1
