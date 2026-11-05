# tests/test_r1_seams.py
"""R1 I0 seams: the shared hooks the four R1 workstreams build on (docs/plans/r1-free-tools.md).

Channel and offline context, the alerts port, the model fields, the /v1/chat refusal of
`channel="telegram"`, `LLMUnreachable`, `Tool.spoken_ok`, gateway observers, `observe_declined`,
the brain's offline wiring, the Telegram trailer placeholder, settings and the three new rows.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from jarvis.alerts import AlertResult, AlertSink, NoAlerts
from jarvis.config import Settings
from jarvis.core import channel
from jarvis.core import prompts as prompts_mod
from jarvis.core.brain import Brain
from jarvis.core.brain_decisions import Outcome, response
from jarvis.core.guardrails import ActionRisk, AskReason, ConfirmationGate
from jarvis.core.models import ChatRequest, ChatResponse, Session, Turn
from jarvis.llm.base import (
    Completion,
    LLMTransientError,
    Role,
    ToolCall,
    Usage,
)
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.permissions.groups import GROUPS, get_group, groups_for, validate_choices
from jarvis.tools import AuditLog, Effect, Gateway, GatewayOutcome, Policy, PolicyRule, Tool
from jarvis.tools.audit import AuditEntry
from jarvis.tools.observers import GatewayEvent, notify
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
SCOPE = "owner@example.com:sess_1"
ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
CSRF = {"X-Requested-With": "JARVIS"}


@pytest.fixture(autouse=True)
def _clean_offline_marker() -> None:
    channel.reset_offline()


# ---- core/channel.py ---------------------------------------------------------------------


def test_telegram_turn_is_scoped() -> None:
    assert channel.on_telegram() is False
    with channel.telegram_turn():
        assert channel.on_telegram() is True
        with channel.telegram_turn():
            assert channel.on_telegram() is True
        assert channel.on_telegram() is True
    assert channel.on_telegram() is False


def test_telegram_turn_resets_after_an_error() -> None:
    with pytest.raises(RuntimeError), channel.telegram_turn():
        raise RuntimeError("boom")
    assert channel.on_telegram() is False


def test_offline_marker_set_read_and_reset() -> None:
    channel.reset_offline()
    assert channel.answered_offline() is False
    channel.mark_offline()
    assert channel.answered_offline() is True
    channel.reset_offline()
    assert channel.answered_offline() is False


def test_marking_without_a_reset_still_works() -> None:
    async def fresh() -> bool:
        channel.mark_offline()
        return channel.answered_offline()

    assert asyncio.run(fresh()) is True


async def test_offline_mark_made_in_a_child_task_is_seen_by_the_parent() -> None:
    channel.reset_offline()
    await asyncio.create_task(asyncio.sleep(0, result=channel.mark_offline()))
    assert channel.answered_offline() is True

    async def child() -> None:
        channel.mark_offline()

    channel.reset_offline()
    await asyncio.create_task(child())
    assert channel.answered_offline() is True
    channel.reset_offline()


async def test_requests_do_not_share_the_offline_marker() -> None:
    async def request(offline: bool) -> bool:
        channel.reset_offline()
        if offline:
            channel.mark_offline()
        await asyncio.sleep(0)
        return channel.answered_offline()

    assert await asyncio.gather(request(True), request(False)) == [True, False]


# ---- alerts.py ---------------------------------------------------------------------------


async def test_no_alerts_sends_nothing_and_says_why() -> None:
    sink: AlertSink = NoAlerts()
    res = await sink.send("owner", "hello", kind="test")
    assert res == AlertResult(sent=False, reason="not set up")
    assert isinstance(sink, AlertSink)


async def test_no_alerts_reason_can_be_given() -> None:
    res = await NoAlerts("not paired").send("owner", "x", kind="approval_waiting")
    assert res.sent is False and res.reason == "not paired"


def test_alert_result_defaults() -> None:
    assert AlertResult(sent=True).reason == ""


# ---- models ------------------------------------------------------------------------------


def test_channel_accepts_telegram_on_request_and_turn() -> None:
    assert ChatRequest(message="hi", channel="telegram").channel == "telegram"
    assert Turn(role=Role.USER, content="hi", channel="telegram").channel == "telegram"
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", channel="whatsapp")  # type: ignore[arg-type]


def test_offline_fields_default_false() -> None:
    assert Turn(role=Role.ASSISTANT, content="x").offline is False
    assert Turn(role=Role.ASSISTANT, content="x", offline=True).offline is True
    resp = ChatResponse(
        session_id="s", reply="r", trace_id="t", model="m", usage=Usage(), cost_usd=0, latency_ms=0,
        turn_count=1,
    )  # fmt: skip
    assert resp.offline is False


async def test_http_chat_refuses_the_telegram_channel(client: AsyncClient) -> None:
    r = await client.post("/v1/chat", json={"message": "hi", "channel": "telegram"}, headers=CSRF)
    assert r.status_code == 422
    r2 = await client.post(
        "/v1/chat/stream", json={"message": "hi", "channel": "telegram"}, headers=CSRF
    )
    assert r2.status_code == 422


async def test_http_chat_still_takes_text_and_voice(
    client: AsyncClient, provider: MockProvider
) -> None:
    for ch in ("text", "voice"):
        r = await client.post("/v1/chat", json={"message": "hi", "channel": ch}, headers=CSRF)
        assert r.status_code == 200, r.text
        assert r.json()["offline"] is False


# ---- llm/base.py -------------------------------------------------------------------------


def test_llm_unreachable_is_a_transient_error() -> None:
    from jarvis.llm.base import LLMUnreachable

    assert issubclass(LLMUnreachable, LLMTransientError)
    assert LLMUnreachable is not LLMTransientError


def test_completion_offline_defaults_false() -> None:
    c = Completion(text="x", model="m", provider="p", usage=Usage(), latency_ms=1)
    assert c.offline is False
    assert c.model_copy(update={"offline": True}).offline is True


# ---- config ------------------------------------------------------------------------------


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_new_settings_defaults() -> None:
    s = _settings()
    assert s.telegram_bot_token is None and s.telegram_webhook_secret is None
    assert s.local_brain_timeout_s == 90
    assert s.activity_retention_days == 7


def test_telegram_secrets_are_secret_str() -> None:
    s = _settings(telegram_bot_token="123:abc", telegram_webhook_secret="s3cret")
    assert "123:abc" not in repr(s) and "s3cret" not in repr(s)
    assert s.telegram_bot_token is not None
    assert s.telegram_bot_token.get_secret_value() == "123:abc"


@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("local_brain_timeout_s", (5, 300), (4, 301)),
        ("activity_retention_days", (1, 30), (0, 31)),
    ],
)
def test_new_settings_bounds(field: str, good: tuple[int, int], bad: tuple[int, int]) -> None:
    for v in good:
        assert getattr(_settings(**{field: v}), field) == v
    for v in bad:
        with pytest.raises(ValidationError):
            _settings(**{field: v})


# ---- permissions rows --------------------------------------------------------------------


def test_three_new_rows_follow_the_todo_rows() -> None:
    ids = [g.id for g in GROUPS]
    assert len(ids) == 28  # 23 on R1 + the five R2 rows (Vault, Notes, Things)
    assert ids.index("groceries") == ids.index("todo_delete") + 1
    assert ids[ids.index("groceries") : ids.index("groceries") + 3] == [
        "groceries",
        "family_read",
        "family_change",
    ]


def test_new_rows_texts_and_risks() -> None:
    g, fr, fc = (get_group(i) for i in ("groceries", "family_read", "family_change"))
    assert g and fr and fc
    assert (g.section, g.label, g.risk) == ("Groceries", "Keep your grocery list", R2)
    assert (fr.section, fr.label, fr.risk) == ("Family", "Look at family calendars", R1)
    assert (fc.section, fc.risk) == ("Family", R3)
    assert fc.label == "Add events to a family member's calendar"
    assert fc.hint.startswith("They see it, and Google may email them.")
    assert fc.choices == (Effect.ASK, Effect.DENY) and fc.default is Effect.ASK
    assert "without a card" in g.hint


@pytest.mark.parametrize(
    ("tool", "risk", "row"),
    [
        ("grocery_list", R1, "groceries"),
        ("grocery_add", R2, "groceries"),
        ("grocery_remove", R2, "groceries"),
        ("family_calendar_events", R1, "family_read"),
        ("family_free_slots", R1, "family_read"),
        ("family_event_add", R3, "family_change"),
    ],
)
def test_new_tools_fall_into_their_rows(tool: str, risk: ActionRisk, row: str) -> None:
    assert [g.id for g in groups_for(tool, risk)] == [row]


def test_family_read_never_covers_the_r3_add_and_vice_versa() -> None:
    assert "family_read" not in [g.id for g in groups_for("family_event_add", R3)]
    assert "family_change" not in [g.id for g in groups_for("family_free_slots", R1)]


def test_family_change_offers_no_allow() -> None:
    with pytest.raises(Exception, match="can't be set to Allow"):
        validate_choices({"family_change": "allow"})
    assert validate_choices({"groceries": "allow", "family_read": "deny"})


# ---- prompts -----------------------------------------------------------------------------


def test_telegram_trailer_carries_the_rule_and_others_do_not() -> None:
    kw: dict[str, Any] = {"tz": "Asia/Kolkata", "session_id": "s", "turn_index": 1}
    tele = prompts_mod.build_trailer(channel="telegram", **kw)
    assert prompts_mod.TELEGRAM_RULE in tele and prompts_mod.VOICE_RULE not in tele
    for ch in ("text", "voice"):
        assert prompts_mod.TELEGRAM_RULE not in prompts_mod.build_trailer(channel=ch, **kw)  # type: ignore[arg-type]
    assert "TELEGRAM_RULE" in prompts_mod.__all__


def test_persona_version_is_p4_6() -> None:
    assert prompts_mod.PERSONA_VERSION == "p4.7"


# ---- tools/base.py + observers -----------------------------------------------------------


def _tool(name: str = "note_add", risk: ActionRisk = R2, **kw: Any) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        if args.get("boom"):
            raise RuntimeError("bad things for bob@example.com")
        return {"ok": True, "undo_id": "del_1"}

    return Tool(
        name, "d", {"type": "object", "properties": {"text": {"type": "string"}, "boom": {}}},
        risk, run, summarize=lambda a: f"Note: {a.get('text', '')}", **kw,
    )  # fmt: skip


def _gw(*tools: Tool, rules: list[PolicyRule] | None = None) -> tuple[Gateway, AuditLog]:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    audit = AuditLog()
    return Gateway(registry=reg, policy=Policy(rules), gate=ConfirmationGate(), audit=audit), audit


class Recorder:
    def __init__(self) -> None:
        self.events: list[GatewayEvent] = []

    async def on_event(self, event: GatewayEvent) -> None:
        self.events.append(event)


class Exploding:
    async def on_event(self, event: GatewayEvent) -> None:
        raise RuntimeError("observer down")


def test_spoken_ok_defaults_false() -> None:
    assert _tool().spoken_ok is False
    assert _tool(spoken_ok=True).spoken_ok is True


async def test_notify_calls_every_observer_and_never_raises() -> None:
    rec = Recorder()
    ev = GatewayEvent(
        outcome="executed", tool="t", agent="core", risk=R1, args={}, scope=None, entry=None
    )
    await notify([Exploding(), rec], ev)
    assert rec.events == [ev]
    await notify([], ev)


async def test_notify_survives_cancellation_free_failures_of_any_kind() -> None:
    class Odd:
        def on_event(self, event: GatewayEvent) -> None:  # not even a coroutine
            raise ValueError("x")

    await notify([Odd()], GatewayEvent("error", "t", "core", R1, {}, None, None))


async def test_an_executed_call_notifies_with_entry_and_result() -> None:
    gw, audit = _gw(_tool("note_list", R1))
    rec = Recorder()
    gw.observers = [rec]
    res = await gw.execute(ToolCall(id="1", name="note_list", arguments={"text": "a"}), scope=SCOPE)
    assert res.outcome is GatewayOutcome.EXECUTED
    (ev,) = rec.events
    assert (ev.outcome, ev.tool, ev.agent, ev.risk, ev.scope) == (
        "executed", "note_list", "core", R1, SCOPE,
    )  # fmt: skip
    assert ev.args == {"text": "a"} and ev.result is res
    assert isinstance(ev.entry, AuditEntry) and ev.entry.seq == (await audit.tail(1)).entries[0].seq
    assert ev.entry.outcome == "executed"


async def test_a_raising_tool_notifies_error_with_the_failed_result() -> None:
    gw, _ = _gw(_tool())
    rec = Recorder()
    gw.observers = [rec]
    res = await gw.execute(ToolCall(id="1", name="note_add", arguments={"boom": True}), scope=SCOPE)
    assert res.outcome is GatewayOutcome.ERROR and res.raised
    (ev,) = rec.events
    assert ev.outcome == "error" and ev.result is res and ev.entry is not None


async def test_unknown_tool_and_bad_arguments_notify_error() -> None:
    gw, _ = _gw(_tool())
    rec = Recorder()
    gw.observers = [rec]
    await gw.execute(ToolCall(id="1", name="nope", arguments={}), scope=SCOPE)
    await gw.execute(ToolCall(id="2", name="note_add", arguments={"zzz": 1}), scope=SCOPE)
    assert [(e.outcome, e.tool) for e in rec.events] == [("error", "nope"), ("error", "note_add")]
    assert rec.events[0].agent == "gateway" and rec.events[0].entry is not None


async def test_a_card_notifies_awaiting_and_an_approval_notifies_executed() -> None:
    gw, _ = _gw(_tool("note_send", R3))
    rec = Recorder()
    gw.observers = [rec]
    call = ToolCall(id="1", name="note_send", arguments={"text": "x"})
    first = await gw.execute(call, scope=SCOPE)
    assert first.outcome is GatewayOutcome.AWAITING_CONFIRMATION and first.pending
    assert [e.outcome for e in rec.events] == ["awaiting_confirmation"]
    assert rec.events[0].result.pending == first.pending and rec.events[0].entry is not None
    done = await gw.execute(call, scope=SCOPE, confirmation_id=first.pending.id)
    assert done.outcome is GatewayOutcome.EXECUTED
    assert [e.outcome for e in rec.events] == ["awaiting_confirmation", "executed"]


async def test_a_denied_call_notifies_denied_with_the_rule_source() -> None:
    deny = PolicyRule(tool_pattern="note_*", effect=Effect.DENY, source="owner:x", reason="no")
    gw, _ = _gw(_tool(), rules=[deny])
    rec = Recorder()
    gw.observers = [rec]
    res = await gw.execute(ToolCall(id="1", name="note_add", arguments={}), scope=SCOPE)
    assert res.outcome is GatewayOutcome.DENIED
    (ev,) = rec.events
    assert ev.outcome == "denied" and ev.entry is not None and ev.entry.detail == "policy:owner:x"
    assert ev.result is res


async def test_a_failing_observer_never_fails_the_call() -> None:
    gw, audit = _gw(_tool("note_list", R1))
    rec = Recorder()
    gw.observers = [Exploding(), rec]
    res = await gw.execute(ToolCall(id="1", name="note_list", arguments={}), scope=SCOPE)
    assert res.outcome is GatewayOutcome.EXECUTED and len(rec.events) == 1
    assert (await audit.tail(5)).entries


async def test_observers_default_to_none_and_a_gateway_works_without() -> None:
    gw, _ = _gw(_tool("note_list", R1))
    assert gw.observers == []
    res = await gw.execute(ToolCall(id="1", name="note_list", arguments={}), scope=SCOPE)
    assert res.outcome is GatewayOutcome.EXECUTED


async def test_audit_after_run_returns_the_entry_or_none_when_audit_is_down() -> None:
    gw, audit = _gw(_tool())
    tool = gw.registry.get("note_add")
    assert tool is not None
    call = ToolCall(id="1", name="note_add", arguments={})
    entry = await gw._audit_after_run(tool, call, R2, "executed", "", SCOPE)
    assert isinstance(entry, AuditEntry) and entry.outcome == "executed"

    async def down(**kw: Any) -> AuditEntry:
        raise RuntimeError("audit down")

    audit.append = down  # type: ignore[method-assign]
    rec = Recorder()
    gw.observers = [rec]
    assert await gw._audit_after_run(tool, call, R2, "executed", "", SCOPE) is None
    assert rec.events and rec.events[0].entry is None  # the tool ran; observers still hear of it


async def test_observe_declined_notifies_with_the_entry() -> None:
    from jarvis.core.guardrails import PendingAction

    gw, audit = _gw(_tool())
    rec = Recorder()
    gw.observers = [rec]
    action = PendingAction(
        tool="note_add", arguments={"text": "a"}, risk=R3, summary="Note: a", scope=SCOPE,
        tool_risk=R2,
    )  # fmt: skip
    entry = await audit.append(
        agent="core", tool="note_add", risk=R3, outcome="declined", args={"text": "a"}
    )
    await gw.observe_declined(action, entry)
    (ev,) = rec.events
    assert (ev.outcome, ev.tool, ev.scope, ev.risk, ev.args) == (
        "declined", "note_add", SCOPE, R2, {"text": "a"},
    )  # fmt: skip
    assert ev.entry is entry and ev.result is None and ev.agent == "core"


async def test_brain_decline_notifies_observers(brain: Brain, provider: MockProvider) -> None:
    gw = brain.gateway
    assert gw is not None
    rec = Recorder()
    gw.observers = [rec]
    provider.script_tool_calls(
        [ToolCall(id="c1", name="send_message", arguments={"to": "a@b.co", "body": "hi"})], "ok"
    )
    resp = await brain.chat(ChatRequest(message="send it"))
    (card,) = resp.pending_approvals
    await brain.decline(card.id, session_id=resp.session_id)
    assert [e.outcome for e in rec.events] == ["awaiting_confirmation", "declined"]
    assert rec.events[-1].entry is not None and rec.events[-1].entry.outcome == "declined"


# ---- spoken_ok (D14) ---------------------------------------------------------------------


async def _run(gw: Gateway, name: str = "note_add") -> Any:
    return await gw.execute(ToolCall(id="1", name=name, arguments={"text": "milk"}), scope=SCOPE)


async def test_a_spoken_ok_write_runs_on_a_clean_spoken_turn() -> None:
    gw, _ = _gw(_tool(spoken_ok=True))
    with context_trust(untrusted=False, spoken=True):
        assert (await _run(gw)).outcome is GatewayOutcome.EXECUTED


async def test_a_plain_write_still_asks_on_a_spoken_turn() -> None:
    gw, _ = _gw(_tool())
    with context_trust(untrusted=False, spoken=True):
        res = await _run(gw)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending and res.pending.reason is AskReason.SPOKEN


async def test_a_spoken_ok_write_asks_after_content_was_read() -> None:
    gw, _ = _gw(_tool(spoken_ok=True))
    with context_trust(untrusted=True, spoken=True):  # mail / web / a document in the round
        res = await _run(gw)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending and res.pending.reason is AskReason.UNTRUSTED_CONTEXT


async def test_a_spoken_ok_write_asks_after_content_on_a_typed_turn() -> None:
    gw, _ = _gw(_tool(spoken_ok=True))
    with context_trust(untrusted=True, spoken=False):
        res = await _run(gw)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION


async def test_a_spoken_ok_write_runs_on_a_clean_typed_turn() -> None:
    gw, _ = _gw(_tool(spoken_ok=True))
    with context_trust(untrusted=False, spoken=False):
        assert (await _run(gw)).outcome is GatewayOutcome.EXECUTED


async def test_spoken_ok_never_relaxes_ask_first_never_or_an_ask_when_tool() -> None:
    ask = PolicyRule(tool_pattern="note_*", effect=Effect.ASK, source="owner:x")
    gw, _ = _gw(_tool(spoken_ok=True), rules=[ask])
    with context_trust(untrusted=False, spoken=True):
        res = await _run(gw)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending and res.pending.reason is AskReason.OWNER_RULE

    deny = PolicyRule(tool_pattern="note_*", effect=Effect.DENY, source="owner:x")
    gw2, _ = _gw(_tool(spoken_ok=True), rules=[deny])
    with context_trust(untrusted=False, spoken=True):
        assert (await _run(gw2)).outcome is GatewayOutcome.DENIED

    gw3, _ = _gw(_tool(spoken_ok=True, ask_when=lambda a: True))
    with context_trust(untrusted=False, spoken=True):
        assert (await _run(gw3)).outcome is GatewayOutcome.AWAITING_CONFIRMATION


async def test_spoken_ok_never_lets_an_irreversible_call_run() -> None:
    gw, _ = _gw(_tool("note_send", R3, spoken_ok=True))
    with context_trust(untrusted=False, spoken=True):
        res = await _run(gw, "note_send")
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending and res.pending.reason is AskReason.RISK


async def test_an_approval_token_is_still_spent_for_a_spoken_ok_tool() -> None:
    gw, _ = _gw(_tool(spoken_ok=True))
    with context_trust(untrusted=True, spoken=True):
        first = await _run(gw)
    assert first.pending
    done = await gw.execute(
        ToolCall(id="1", name="note_add", arguments={"text": "milk"}),
        scope=SCOPE,
        confirmation_id=first.pending.id,
    )
    assert done.outcome is GatewayOutcome.EXECUTED
    assert not await gw.pending()


# ---- brain / decisions offline wiring ----------------------------------------------------


class OfflineProvider(MockProvider):
    """Answers like the fallback brain: the completion says so and the marker is set."""

    async def complete(self, **kw: Any) -> Completion:
        done = await super().complete(**kw)
        channel.mark_offline()
        return done.model_copy(update={"offline": True})


def _brain_with(provider: MockProvider, brain: Brain) -> Brain:
    tiers = {t: f"mock-{t.value}" for t in ModelTier}
    return Brain(
        router=ModelRouter(provider, tiers),
        store=brain.store,
        settings=brain.s,
        gateway=brain.gateway,
    )


async def test_an_offline_answer_is_marked_on_the_turn_and_the_response(
    brain: Brain, store: Any
) -> None:
    off = _brain_with(OfflineProvider(), brain)
    resp = await off.chat(ChatRequest(message="hi"))
    assert resp.offline is True
    sess = await store.get(resp.session_id)
    assert [t.offline for t in sess.turns] == [False, True]  # the owner's message is not offline


async def test_a_normal_answer_is_not_marked_offline(brain: Brain, store: Any) -> None:
    resp = await brain.chat(ChatRequest(message="hi"))
    assert resp.offline is False
    assert not any(t.offline for t in (await store.get(resp.session_id)).turns)


async def test_an_offline_mark_does_not_leak_into_the_next_turn(brain: Brain) -> None:
    await _brain_with(OfflineProvider(), brain).chat(ChatRequest(message="hi"))
    assert channel.answered_offline() is True
    again = await brain.chat(ChatRequest(message="and again"))  # cloud answers: reset first
    assert again.offline is False


async def test_the_stream_resets_the_marker_and_a_marked_stream_stores_an_offline_turn(
    brain: Brain, store: Any
) -> None:
    channel.mark_offline()
    assert [d async for d in brain.chat_stream(ChatRequest(message="stream"))]
    assert channel.answered_offline() is False  # reset at the start of the stream
    (summary,) = await store.list_for_user("owner")
    assert (await store.get(summary.id)).turns[-1].offline is False

    class Marking(MockProvider):
        async def stream(self, **kw: Any) -> Any:
            channel.mark_offline()
            async for d in super().stream(**kw):
                yield d

    off = _brain_with(Marking(), brain)
    assert [d async for d in off.chat_stream(ChatRequest(message="again"))]
    marked = []
    for sm in await store.list_for_user("owner"):
        marked += [t.offline for t in (await store.get(sm.id)).turns]
    assert True in marked


def test_decision_responses_carry_offline() -> None:
    sess = Session(user_id="owner")
    kw: dict[str, Any] = {"model": "m", "provider": "p", "usage": Usage(), "latency_ms": 1}
    out = Outcome("fb", [], False)
    off = response(sess, "b", "r", Completion(text="x", offline=True, **kw), "t", out, (0.0, 0.0))
    on = response(sess, "b", "r", Completion(text="x", **kw), "t", out, (0.0, 0.0))
    assert off.offline is True and on.offline is False
    assert response(sess, "b", "r", None, "t", out, (0.0, 0.0)).offline is False


# ---- size guards -------------------------------------------------------------------------


def test_file_size_guards() -> None:
    assert len((ROOT / "core" / "brain.py").read_text().splitlines()) < 800
    assert len((ROOT / "tools" / "gateway.py").read_text().splitlines()) <= 760


# ---- R1 fix-4 M4: a hung observer never stalls a tool call ---------------------------------


class Hung:
    async def on_event(self, event: GatewayEvent) -> None:
        await asyncio.sleep(3600)


def test_the_observer_timeout_is_two_seconds() -> None:
    from jarvis.tools import observers

    assert observers.OBSERVER_TIMEOUT_S == 2.0


async def test_a_hung_observer_is_cut_off_logged_and_the_call_still_audited(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from jarvis.tools import observers

    monkeypatch.setattr(observers, "OBSERVER_TIMEOUT_S", 0.05)
    gw, audit = _gw(_tool("note_list", R1))
    rec = Recorder()
    gw.observers = [Hung(), rec]
    call = ToolCall(id="1", name="note_list", arguments={"text": "secret"})
    with caplog.at_level("WARNING"):
        res = await asyncio.wait_for(gw.execute(call, scope=SCOPE), timeout=1.0)
    assert res.outcome is GatewayOutcome.EXECUTED
    assert len((await audit.tail(5)).entries) == 1
    assert len(rec.events) == 1  # the next observer still ran
    assert any("timed out" in r.getMessage() for r in caplog.records)
    assert "secret" not in caplog.text
