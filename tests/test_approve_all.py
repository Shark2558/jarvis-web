# tests/test_approve_all.py — slice 11 D6 "Approve all": the owner approves the waiting cards that
# can be undone with one tap. Only the listed cards of the caller's conversation run, in the
# caller's order, each through the single-approval path (re-checked by the gateway); cards that
# can't be undone (R3, or of unknown risk) never run here — they keep their own approval and
# passkey; one failure doesn't stop the others; one reply for the batch.
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.core.approve_all import MAX_IDS, CardStatus
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, PendingAction
from jarvis.core.models import ChatRequest
from jarvis.llm.base import Role, ToolCall, ToolResultBlock
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.base import Preview
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

TIERS = {
    ModelTier.FAST: "mock-fast",
    ModelTier.BALANCED: "mock-balanced",
    ModelTier.STRONG: "mock-strong",
}
OWNER = "owner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}


def _remind(cid: str, text: str, when: str = "17:00") -> ToolCall:
    return ToolCall(id=cid, name="create_reminder", arguments={"text": text, "when": when})


def _send(cid: str = "s1", body: str = "lunch at one") -> ToolCall:
    args = {"to": "priya@example.com", "body": body}
    return ToolCall(id=cid, name="send_message", arguments=args)


async def _cards(brain: Brain, provider: MockProvider, calls: list[ToolCall], **kw: Any) -> Any:
    """A spoken turn: every write becomes a card (R2 cards need no passkey)."""
    provider.script_tool_calls(calls, "Waiting for you, Sir.")
    req = ChatRequest(message="do all of these", channel="voice", **kw)
    resp = await brain.chat(req)
    assert len(resp.pending_approvals) == len(calls), resp.pending_approvals
    return resp


def _ids(resp: Any) -> list[str]:
    return [p.id for p in resp.pending_approvals]


async def _waiting(brain: Brain) -> set[str]:
    assert brain.gateway is not None
    return {a.id for a in await brain.gateway.pending()}


# ---- the batch ------------------------------------------------------------------------------


async def test_three_reversible_cards_run_and_the_irreversible_one_stays(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await _cards(
        brain, provider, [_remind("r1", "call Ravi"), _remind("r2", "pay rent"),
                          _remind("r3", "book cab"), _send()],
    )  # fmt: skip
    ids = _ids(resp)
    calls_before = len(provider.calls)
    provider.script("All three reminders are set, Sir.")

    out = await brain.approve_all(ids, session_id=resp.session_id)

    assert [r["text"] for r in world.reminders] == ["call Ravi", "pay rent", "book cab"]
    assert world.sent == []  # R3 never runs through Approve all
    assert [r.status for r in out.results] == [
        CardStatus.DONE, CardStatus.DONE, CardStatus.DONE, CardStatus.NEEDS_PASSKEY,
    ]  # fmt: skip
    assert [r.id for r in out.results] == ids
    assert await _waiting(brain) == {ids[3]}  # the send card is still waiting
    assert len(provider.calls) == calls_before + 1  # ONE narration for the whole batch
    assert out.reply.startswith("All three reminders are set, Sir.")
    assert "can't be undone" in out.reply and "own card" in out.reply
    assert out.tool_calls == 3 and out.pending_approvals == []


async def test_the_batch_is_one_reply_turn_after_one_exchange_per_card(
    brain: Brain, provider: MockProvider, store: InMemorySessionStore
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "a"), _remind("r2", "b")])
    before = len((await store.get_or_raise(resp.session_id)).turns)
    provider.script("Both done, Sir.")
    await brain.approve_all(_ids(resp), session_id=resp.session_id)
    turns = (await store.get_or_raise(resp.session_id)).turns[before:]
    # call, result (+ instruction), call, result, narration
    assert [t.role for t in turns] == [Role.ASSISTANT, Role.USER] * 2 + [Role.ASSISTANT]
    assert all(any(isinstance(b, ToolResultBlock) for b in t.blocks) for t in turns[1:4:2])
    assert turns[-1].content == "Both done, Sir." and turns[-1].tool_derived
    instruction = turns[1].blocks[-1].text  # type: ignore[union-attr]
    assert "Approve all" in instruction


async def test_order_is_the_order_the_owner_listed(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "first"), _remind("r2", "second")])
    ids = list(reversed(_ids(resp)))
    out = await brain.approve_all(ids, session_id=resp.session_id)
    assert [r["text"] for r in world.reminders] == ["second", "first"]
    assert [r.id for r in out.results] == ids


async def test_a_card_not_listed_is_never_approved(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    calls = [_remind("r1", "a"), _remind("r2", "b"), _remind("r3", "c")]
    resp = await _cards(brain, provider, calls)
    ids = _ids(resp)
    out = await brain.approve_all(ids[:2], session_id=resp.session_id)
    assert [r["text"] for r in world.reminders] == ["a", "b"]
    assert await _waiting(brain) == {ids[2]}
    assert len(out.results) == 2


async def test_a_card_of_another_conversation_is_not_found_and_not_run(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    mine = await _cards(brain, provider, [_remind("r1", "mine")])
    other = await _cards(brain, provider, [_remind("r2", "other")])
    out = await brain.approve_all([*_ids(mine), *_ids(other)], session_id=mine.session_id)
    assert [r["text"] for r in world.reminders] == ["mine"]
    assert [r.status for r in out.results] == [CardStatus.DONE, CardStatus.NOT_FOUND]
    assert _ids(other)[0] in await _waiting(brain)


async def test_an_unknown_or_already_decided_id_is_reported(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "a"), _remind("r2", "b")])
    ids = _ids(resp)
    await brain.approve(ids[0], session_id=resp.session_id)
    out = await brain.approve_all([ids[0], "no-such-card", ids[1]], session_id=resp.session_id)
    assert [r.status for r in out.results] == [
        CardStatus.NOT_FOUND, CardStatus.NOT_FOUND, CardStatus.DONE,
    ]  # fmt: skip
    assert [r["text"] for r in world.reminders] == ["a", "b"]


async def test_duplicate_ids_are_approved_once(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "once")])
    pid = _ids(resp)[0]
    out = await brain.approve_all([pid, pid, pid], session_id=resp.session_id)
    assert [r["text"] for r in world.reminders] == ["once"]
    assert [r.id for r in out.results] == [pid]


async def test_only_irreversible_cards_means_no_model_call_and_nothing_stored(
    brain: Brain, provider: MockProvider, world: InMemoryWorld, store: InMemorySessionStore
) -> None:
    resp = await _cards(brain, provider, [_send("s1", "one"), _send("s2", "two")])
    before = len((await store.get_or_raise(resp.session_id)).turns)
    calls = len(provider.calls)
    out = await brain.approve_all(_ids(resp), session_id=resp.session_id)
    assert world.sent == []
    assert [r.status for r in out.results] == [CardStatus.NEEDS_PASSKEY] * 2
    assert len(provider.calls) == calls
    assert len((await store.get_or_raise(resp.session_id)).turns) == before
    assert "Nothing was approved" in out.reply and "2 actions" in out.reply
    assert out.tool_calls == 0


async def test_a_card_of_unknown_risk_is_treated_as_irreversible(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await brain.chat(ChatRequest(message="hello"))
    legacy = PendingAction(  # stored before tool_risk existed: fail safe
        tool="create_reminder",
        arguments={"text": "old", "when": "9:00"},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Remind at 9:00: old",
        scope=f"owner:{resp.session_id}",
    )
    assert brain.gateway is not None
    await brain.gateway.gate.store.put(legacy)
    out = await brain.approve_all([legacy.id], session_id=resp.session_id)
    assert out.results[0].status is CardStatus.NEEDS_PASSKEY
    assert world.reminders == [] and legacy.id in await _waiting(brain)


async def test_narration_failure_falls_back_to_one_plain_combined_reply(
    brain: Brain, provider: MockProvider, world: InMemoryWorld
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "call Ravi"), _send()])
    provider.fail_next = 5  # every tier fails after the actions ran
    out = await brain.approve_all(_ids(resp), session_id=resp.session_id)
    assert [r["text"] for r in world.reminders] == ["call Ravi"]
    assert out.reply.startswith("Done, Sir: Remind at 17:00: call Ravi.")
    assert "can't be undone" in out.reply


async def test_unknown_conversation_is_not_found(brain: Brain) -> None:
    from jarvis.memory.base import SessionNotFound

    with pytest.raises(SessionNotFound):
        await brain.approve_all(["x"], session_id="nope")


async def test_a_conversation_that_cannot_record_stops_the_batch(
    brain: Brain,
    provider: MockProvider,
    world: InMemoryWorld,
    store: InMemorySessionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = await _cards(
        brain, provider, [_remind("r1", "a"), _remind("r2", "b"), _remind("r3", "c")]
    )
    ids = _ids(resp)

    async def down(session: Any) -> None:
        raise ConnectionError("firestore unreachable")

    monkeypatch.setattr(store, "save", down)
    provider.script("Done, Sir.")
    out = await brain.approve_all(ids, session_id=resp.session_id)
    # the first ran but could not be recorded: no further tool runs (as in the tool loop)
    assert [r["text"] for r in world.reminders] == ["a"]
    assert [r.status for r in out.results] == [
        CardStatus.DONE, CardStatus.NOT_RUN, CardStatus.NOT_RUN,
    ]  # fmt: skip
    assert "could not record it" in out.reply and "It was done" in out.reply
    assert set(ids[1:]) <= await _waiting(brain)  # still waiting, approvable later


async def test_a_card_that_cannot_be_read_is_reported_and_the_rest_run(
    brain: Brain, provider: MockProvider, world: InMemoryWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "a"), _remind("r2", "b")])
    ids = _ids(resp)
    assert brain.gateway is not None
    gate = brain.gateway.gate
    real = gate.get

    async def flaky(aid: str) -> Any:
        if aid == ids[0]:
            raise ConnectionError("approvals store unreachable")
        return await real(aid)

    monkeypatch.setattr(gate, "get", flaky)
    out = await brain.approve_all(ids, session_id=resp.session_id)
    assert [r.status for r in out.results] == [CardStatus.ERROR, CardStatus.DONE]
    assert [r["text"] for r in world.reminders] == ["b"]
    assert "could not be approved just now" in out.reply


async def test_a_card_decided_meanwhile_is_not_found_and_nothing_runs(
    brain: Brain, provider: MockProvider, world: InMemoryWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = await _cards(brain, provider, [_remind("r1", "a")])
    gw = brain.gateway
    assert gw is not None
    real = gw.execute

    async def raced(call: ToolCall, **kw: Any) -> Any:
        await gw.gate.cancel(kw["confirmation_id"])  # another window declined it first
        return await real(call, **kw)

    monkeypatch.setattr(gw, "execute", raced)
    out = await brain.approve_all(_ids(resp), session_id=resp.session_id)
    assert [r.status for r in out.results] == [CardStatus.NOT_FOUND]
    assert world.reminders == [] and "no longer waiting" in out.reply


# ---- one card failing; a card that changed (rigs with their own tools) ----------------------


class Flaky:
    """A reversible tool that fails for one input, and an event whose guests can appear."""

    def __init__(self) -> None:
        self.done: list[str] = []
        self.guests = False

    def tools(self) -> list[Tool]:
        def note(a: dict[str, Any]) -> dict[str, Any]:
            if a["text"] == "boom":
                raise RuntimeError("the service is down")
            self.done.append(str(a["text"]))
            return {"ok": True}

        async def preview(a: dict[str, Any]) -> Preview:
            risk = ActionRisk.IRREVERSIBLE if self.guests else None
            return Preview(f"Move the dentist to {a['when']}", risk)

        return [
            Tool("note_add", "Add a note.", {"type": "object", "properties": {
                "text": {"type": "string"}}}, ActionRisk.REVERSIBLE, note),
            Tool("event_move", "Move an event.", {"type": "object", "properties": {
                "when": {"type": "string"}}}, ActionRisk.REVERSIBLE,
                lambda a: self.done.append(f"moved {a['when']}"), preview=preview),
        ]  # fmt: skip


@pytest.fixture
def flaky() -> Flaky:
    return Flaky()


@pytest.fixture
def flaky_brain(settings: Settings, provider: MockProvider, flaky: Flaky) -> Brain:
    reg = ToolRegistry()
    for t in flaky.tools():
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return Brain(
        router=ModelRouter(provider, TIERS),
        store=InMemorySessionStore(),
        settings=settings,
        gateway=gw,
    )


async def test_one_failing_card_does_not_stop_the_others(
    flaky_brain: Brain, provider: MockProvider, flaky: Flaky
) -> None:
    calls = [ToolCall(id=f"n{i}", name="note_add", arguments={"text": t})
             for i, t in enumerate(["one", "boom", "three"])]  # fmt: skip
    resp = await _cards(flaky_brain, provider, calls)
    out = await flaky_brain.approve_all(_ids(resp), session_id=resp.session_id)
    assert flaky.done == ["one", "three"]
    assert [r.status for r in out.results] == [
        CardStatus.DONE, CardStatus.FAILED, CardStatus.DONE,
    ]  # fmt: skip
    assert "did not go through" in out.results[1].detail.lower()


async def test_an_exception_while_approving_one_card_is_reported_and_the_rest_run(
    flaky_brain: Brain, provider: MockProvider, flaky: Flaky, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [ToolCall(id=f"n{i}", name="note_add", arguments={"text": t})
             for i, t in enumerate(["one", "two"])]  # fmt: skip
    resp = await _cards(flaky_brain, provider, calls)
    ids = _ids(resp)
    gw = flaky_brain.gateway
    assert gw is not None
    real = gw.execute

    async def broken(call: ToolCall, **kw: Any) -> Any:
        if kw.get("confirmation_id") == ids[0]:
            raise ConnectionError("approvals store unreachable")
        return await real(call, **kw)

    monkeypatch.setattr(gw, "execute", broken)
    out = await flaky_brain.approve_all(ids, session_id=resp.session_id)
    assert flaky.done == ["two"]
    assert [r.status for r in out.results] == [CardStatus.ERROR, CardStatus.DONE]
    assert "nothing was done" in out.results[0].detail.lower()
    assert "unreachable" not in out.results[0].detail  # no raw error text to the owner


async def test_a_card_that_became_irreversible_is_re_proposed_never_run(
    flaky_brain: Brain, provider: MockProvider, flaky: Flaky
) -> None:
    resp = await _cards(
        flaky_brain, provider,
        [ToolCall(id="m1", name="event_move", arguments={"when": "15:00"}),
         ToolCall(id="n1", name="note_add", arguments={"text": "after"})],
    )  # fmt: skip
    flaky.guests = True  # guests appeared after the card was shown
    out = await flaky_brain.approve_all(_ids(resp), session_id=resp.session_id)
    assert flaky.done == ["after"]  # the move never ran
    assert [r.status for r in out.results] == [CardStatus.CHANGED, CardStatus.DONE]
    again = out.results[0].new_approval
    assert again is not None and again.tool_risk == "irreversible"
    assert [p.id for p in out.pending_approvals] == [again.id]
    assert again.id in await _waiting(flaky_brain)


# ---- HTTP: same auth, CSRF and rate limit as a single approve; validation -------------------


async def test_api_approve_all_happy_path(
    client: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    provider.script_tool_calls([_remind("r1", "a"), _remind("r2", "b"), _send()], "Waiting.")
    r = await client.post("/v1/chat", json={"message": "do it", "channel": "voice"})
    body = r.json()
    ids = [p["id"] for p in body["pending_approvals"]]
    provider.script("Done, Sir.")
    r2 = await client.post(
        "/v1/approvals/approve-all",
        # a passkey sent along is ignored: Approve all never carries one
        json={"session_id": body["session_id"], "ids": ids, "passkey": {"challenge_id": "x"}},
    )
    assert r2.status_code == 200, r2.text
    out = r2.json()
    assert [x["status"] for x in out["results"]] == ["done", "done", "needs_passkey"]
    assert out["reply"].startswith("Done, Sir.") and out["session_id"] == body["session_id"]
    assert [m["text"] for m in world.reminders] == ["a", "b"] and world.sent == []
    left = (await client.get("/v1/approvals")).json()
    assert [p["id"] for p in left] == [ids[2]]


@pytest.mark.parametrize(
    "ids", [[], [f"id{i}" for i in range(MAX_IDS + 1)], [""], ["x" * 65]], ids=str
)
async def test_api_rejects_bad_id_lists(client: AsyncClient, ids: list[str]) -> None:
    r = await client.post("/v1/approvals/approve-all", json={"session_id": "s", "ids": ids})
    assert r.status_code == 422


async def test_api_unknown_conversation_is_404(client: AsyncClient) -> None:
    r = await client.post("/v1/approvals/approve-all", json={"session_id": "nope", "ids": ["a"]})
    assert r.status_code == 404


async def test_api_needs_auth_and_the_csrf_header_like_approve(settings: Settings) -> None:
    s = settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
        }
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = {"session_id": "s", "ids": ["a"]}
            r = await c.post("/v1/approvals/approve-all", json=body, headers=CSRF)
            assert r.status_code == 401

            async def google(request: Any) -> dict[str, Any]:
                return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1"}}

            app.state.oauth.google.authorize_access_token = google
            await c.get("/auth/callback?code=abc&state=x")
            r = await c.post("/v1/approvals/approve-all", json=body)
            assert r.status_code == 403 and r.json()["error"] == "csrf"


async def test_api_is_rate_limited_like_approve(settings: Settings) -> None:
    s = settings.model_copy(update={"rate_limit_per_minute": 2})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            codes = [
                (
                    await c.post(
                        "/v1/approvals/approve-all", json={"session_id": "s", "ids": ["a"]}
                    )
                ).status_code
                for _ in range(3)
            ]
    assert codes[-1] == 429


def test_the_world_fixture_tools_are_what_this_file_assumes() -> None:
    names = {t.name: t.risk for t in builtin_tools(InMemoryWorld())}
    assert names["create_reminder"] is ActionRisk.REVERSIBLE
    assert names["send_message"] is ActionRisk.IRREVERSIBLE
