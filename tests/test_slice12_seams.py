# tests/test_slice12_seams.py — final review: the seams between the slice 12 branches through the
# REAL Brain, gateway and tools (Maps on the fake Google key APIs, whatsapp_draft as built by
# `build_gateway`). One reply carries a Maps card and a WhatsApp draft side by side; Approve all
# runs a Maps "Ask first" card and a WhatsApp "Ask first" card together and the batch's reply
# carries both cards; a draft after a Maps result in a LATER round asks first (place names are
# other people's words), while a draft in the SAME round as the search does not.
from __future__ import annotations

from typing import Any

from media_fakes import KEY, PLACES_URL, FakeGoogleKeyAPIs
from pydantic import SecretStr

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import AskReason, ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.groups import rules_for
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.policy import Effect, PolicyRule
from jarvis.tools.setup import build_gateway
from jarvis.whatsapp.draft import wa_link

TIERS = {t: f"mock-{t.value}" for t in ModelTier}
UID = "u_owner"
NUMBER = "+91 98765 43210"
MESSAGE = f"find a cafe and WhatsApp {NUMBER} to meet there"


class Rules:
    def __init__(self, choices: dict[str, Effect]) -> None:
        self.choices = choices

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return rules_for(self.choices)


def _rig(choices: dict[str, Effect] | None = None) -> tuple[Brain, MockProvider, FakeGoogleKeyAPIs]:
    fake = FakeGoogleKeyAPIs()
    docs = MemoryDocs()
    client = GoogleKeyClient(SecretStr(KEY), http=fake.client())
    ledger = QuotaLedger(docs)
    media = MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, MapsPlaces(docs)),
        youtube=YouTubeService(client, ledger),
    )
    s = Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )
    gw = build_gateway(s, media=media)
    gw.gate = ConfirmationGate()
    gw.rules = Rules(choices or {})
    provider = MockProvider()
    brains = BrainRegistry(
        [BrainSpec(id="mock", label="Mock", provider=provider, tiers=TIERS)], default_id="mock"
    )
    brain = Brain(brains=brains, store=InMemorySessionStore(), settings=s, gateway=gw)
    return brain, provider, fake


def _search() -> ToolCall:
    return ToolCall(id="m", name="maps_search", arguments={"query": "cafe"})


def _draft(text: str = "meet at Cafe 1") -> ToolCall:
    return ToolCall(id="w", name="whatsapp_draft", arguments={"to": NUMBER, "text": text})


def _kinds(resp: Any) -> list[str]:
    return [c.kind for c in resp.cards]


async def test_a_maps_card_and_a_whatsapp_draft_ride_on_one_reply() -> None:
    brain, provider, fake = _rig()
    provider.script_tool_calls([_search(), _draft()])
    provider.script("Here are cafés, and your message is ready.")
    resp = await brain.chat(ChatRequest(message=MESSAGE, user_id=UID))
    assert resp.pending_approvals == []
    assert _kinds(resp) == ["places", "whatsapp"]
    places, draft = resp.cards
    assert places.attribution == "Google Maps" and places.items  # type: ignore[union-attr]
    assert draft.link == wa_link("+919876543210", "meet at Cafe 1")  # type: ignore[union-attr]
    assert draft.warning == ""  # type: ignore[union-attr]  # the owner typed the number
    assert len(fake.sent(PLACES_URL)) == 1


async def test_a_draft_after_a_maps_result_in_a_later_round_asks_first() -> None:
    brain, provider, _ = _rig()
    provider.script_tool_calls([_search()])
    provider.script_tool_calls([_draft()])
    provider.script("The cafés are below; the message waits for you.")
    resp = await brain.chat(ChatRequest(message=MESSAGE, user_id=UID))
    assert _kinds(resp) == ["places"]
    (card,) = resp.pending_approvals
    assert card.tool == "whatsapp_draft" and card.reason == AskReason.DRAFT_RECIPIENT.value
    assert card.bulk_ok is False  # one by one: a place name may have steered it


async def test_approve_all_runs_a_maps_and_a_whatsapp_ask_first_card_together() -> None:
    brain, provider, fake = _rig({"maps": Effect.ASK, "whatsapp": Effect.ASK})
    provider.script_tool_calls([_search(), _draft()])
    provider.script("Two approvals are waiting.")
    first = await brain.chat(ChatRequest(message=MESSAGE, user_id=UID))
    assert first.cards == [] and fake.requests == []
    held = {p.tool: p for p in first.pending_approvals}
    assert set(held) == {"maps_search", "whatsapp_draft"}
    assert all(p.bulk_ok and p.reason == AskReason.OWNER_RULE.value for p in held.values())
    provider.script("Both done.")
    ids = [p.id for p in first.pending_approvals]
    done = await brain.approve_all(ids, session_id=first.session_id, user_id=UID)
    assert [r.status.value for r in done.results] == ["done", "done"]
    assert sorted(_kinds(done)) == ["places", "whatsapp"]
    assert len(fake.sent(PLACES_URL)) == 1
    again = await brain.approve_all(ids, session_id=first.session_id, user_id=UID)
    assert {r.status.value for r in again.results} == {"not_found"}  # each ran once
