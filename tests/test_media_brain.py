# tests/test_media_brain.py — slice 12 D3/D4 through the real Brain: a reply that used Maps or
# YouTube carries its cards (ChatResponse.cards) — the links and video ids come from Google's
# answer, never from the model's words — and the stored conversation keeps no card; an approved
# Maps card shows its card too; a training brain gets no Maps / YouTube tools at all.
from __future__ import annotations

import json
from typing import Any

from media_fakes import KEY, FakeGoogleKeyAPIs, video_id
from pydantic import SecretStr

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ConfirmationGate
from jarvis.core.models import ChatRequest
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.media.service import MediaServices, YouTubeService
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.picture.turnguard import TurnGuard
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.setup import build_gateway


class NoPictures:
    """R11.1 I1: the turn guard's port as the app answers it for a turn without a picture
    (unwired, Maps and YouTube count every Brain turn as a picture turn and fail closed)."""

    async def carried(self, uid: str, session_id: str) -> str:
        return "no"


TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def _rig(
    *, trains: bool = False, places: MapsPlaces | None = None
) -> tuple[Brain, MockProvider, InMemorySessionStore, Any]:
    fake = FakeGoogleKeyAPIs()
    docs = MemoryDocs()
    client = GoogleKeyClient(SecretStr(KEY), http=fake.client())
    ledger = QuotaLedger(docs)
    media = MediaServices(
        client=client,
        ledger=ledger,
        maps=MapsService(client, ledger, places or MapsPlaces(docs)),
        youtube=YouTubeService(client, ledger),
    )
    s = Settings(
        _env_file=None,
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
    )
    gw = build_gateway(s, media=media, pictures=TurnGuard(NoPictures()))
    gw.gate = ConfirmationGate()
    provider = MockProvider()
    brains = BrainRegistry(
        [
            BrainSpec(
                id="mock", label="Mock", provider=provider, tiers=TIERS, trains_on_content=trains
            )
        ],
        default_id="mock",
    )
    store = InMemorySessionStore()
    return Brain(brains=brains, store=store, settings=s, gateway=gw), provider, store, fake


async def test_a_reply_that_used_maps_and_youtube_carries_both_cards() -> None:
    brain, provider, store, fake = _rig()
    provider.script_tool_calls([ToolCall(id="a", name="maps_search", arguments={"query": "cafe"})])
    provider.script_tool_calls(
        [ToolCall(id="b", name="youtube_search", arguments={"query": "lofi", "kind": "music"})]
    )
    provider.script("Here are cafés and some music.")
    resp = await brain.chat(ChatRequest(message="cafés and music", user_id="u_owner"))
    kinds = [c.kind for c in resp.cards]
    assert kinds == ["places", "videos"]
    assert resp.cards[0].items[0].url.startswith("https://maps.google.com/")  # type: ignore[union-attr]
    assert resp.cards[1].items[0].id == video_id(1)  # type: ignore[union-attr]
    stored = await store.get(resp.session_id)
    assert stored is not None
    text = stored.model_dump_json()
    assert "maps.google.com" not in text  # cards are never stored
    assert "cards" not in json.loads(text)["turns"][-1]


async def test_a_reply_without_media_tools_has_no_cards() -> None:
    brain, provider, _, _ = _rig()
    provider.script("Hello.")
    resp = await brain.chat(ChatRequest(message="hi", user_id="u_owner"))
    assert resp.cards == []


async def test_an_approved_maps_card_shows_its_place_card_with_the_reply() -> None:
    """The owner may set Maps to Ask first (Permissions): approving the card runs the search, and
    the reply to the approval carries the place card."""
    brain, provider, _, fake = _rig()
    assert brain.gateway is not None
    from jarvis.tools.policy import Effect, PolicyRule

    brain.gateway.policy = brain.gateway.policy.with_rules(
        [PolicyRule(tool_pattern="maps_*", effect=Effect.ASK)]
    )
    provider.script_tool_calls([ToolCall(id="a", name="maps_search", arguments={"query": "cafe"})])
    provider.script("An approval is waiting.")
    resp = await brain.chat(ChatRequest(message="find a cafe", user_id="u_owner"))
    assert resp.cards == [] and fake.requests == []
    pending = resp.pending_approvals[0]
    provider.script("Here they are.")
    done = await brain.approve(pending.id, session_id=resp.session_id, user_id="u_owner")
    assert [c.kind for c in done.cards] == ["places"]


async def test_an_ask_first_maps_search_approved_with_approve_all_shows_its_card() -> None:
    """Approve all runs each card as a single approval does: the place card the search made
    rides on the batch's reply (it was dropped before)."""
    brain, provider, _, fake = _rig()
    assert brain.gateway is not None
    from jarvis.tools.policy import Effect, PolicyRule

    brain.gateway.policy = brain.gateway.policy.with_rules(
        [PolicyRule(tool_pattern="maps_*", effect=Effect.ASK)]
    )
    provider.script_tool_calls([ToolCall(id="a", name="maps_search", arguments={"query": "cafe"})])
    provider.script("An approval is waiting.")
    resp = await brain.chat(ChatRequest(message="find a cafe", user_id="u_owner"))
    assert resp.cards == [] and fake.requests == []
    provider.script("Here they are.")
    ids = [p.id for p in resp.pending_approvals]
    out = await brain.approve_all(ids, session_id=resp.session_id, user_id="u_owner")
    assert [r.status.value for r in out.results] == ["done"]
    assert [c.kind for c in out.cards] == ["places"]
    assert out.cards[0].items[0].url.startswith("https://maps.google.com/")  # type: ignore[union-attr]


async def test_a_training_brain_is_offered_no_maps_or_youtube_tools() -> None:
    brain, provider, _, fake = _rig(trains=True)
    provider.script("I can't look that up here.")
    await brain.chat(ChatRequest(message="find a cafe", user_id="u_owner"))
    offered = provider.calls[-1].tools or []
    assert not [t for t in offered if t.name.startswith(("maps_", "youtube_"))]
    assert fake.requests == []


# ---- final review fix 8: a spoken "how long to work?" stays one step -------------------------


def _home_rig() -> tuple[Brain, MockProvider, MapsPlaces, Any]:
    places = MapsPlaces(MemoryDocs())  # the maps tools' own Home / Work store
    brain, provider, _, fake = _rig(places=places)
    return brain, provider, places, fake


async def test_a_spoken_travel_time_question_from_home_runs_without_a_card() -> None:
    """D3 / gateway: Home or Work in a route asks first only when the round read other people's
    content (`content_tainted`); a spoken turn alone is the owner asking out loud."""
    brain, provider, places, fake = _home_rig()
    await places.put("u_owner", home="Kowdiar", work="Technopark")
    call = ToolCall(id="r", name="maps_route", arguments={"from": "home", "to": "work"})
    provider.script_tool_calls([call])
    provider.script("About twenty-five minutes.")
    req = ChatRequest(message="how long to work?", user_id="u_owner", channel="voice")
    resp = await brain.chat(req)
    assert resp.pending_approvals == [] and [c.kind for c in resp.cards] == ["route"]
    assert len(fake.requests) == 1


async def test_a_spoken_route_from_home_after_a_place_search_asks_first() -> None:
    brain, provider, places, fake = _home_rig()
    await places.put("u_owner", home="Kowdiar", work="Technopark")
    provider.script_tool_calls([ToolCall(id="s", name="maps_search", arguments={"query": "cafe"})])
    provider.script_tool_calls(
        [ToolCall(id="r", name="maps_route", arguments={"from": "home", "to": "Kovalam"})]
    )
    provider.script("An approval is waiting.")
    msg = "find a cafe and the time from home"
    resp = await brain.chat(ChatRequest(message=msg, user_id="u_owner", channel="voice"))
    assert [p.tool for p in resp.pending_approvals] == ["maps_route"]
    assert len(fake.requests) == 1  # the place search only: Home was not sent
