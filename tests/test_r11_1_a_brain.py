# tests/test_r11_1_a_brain.py -- R11.1 Part A, O1 through the Brain (plan D1-D3): no reply is the
# filler; an empty or cut-off answer is handled on the normal path, the round-limit summary and
# the stream; the one retry is metered; a fixed line is stored marked and never replayed.
from __future__ import annotations

import pytest
from billing_fakes import UID as BILL_UID
from r11_1_fakes_a import CUT, Said, ScriptedBrain, call

from jarvis.config import Settings
from jarvis.core import finish
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.llm.base import Role
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelRouter, ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway
from jarvis.tools.builtin import InMemoryWorld

OLD = "I have nothing to add, Sir."
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
WORK, PLAIN = 8192, 1024


@pytest.fixture
def mind() -> ScriptedBrain:
    return ScriptedBrain()


@pytest.fixture
def brain(
    settings: Settings, mind: ScriptedBrain, store: InMemorySessionStore, gateway: Gateway
) -> Brain:
    return Brain(router=ModelRouter(mind, TIERS), store=store, settings=settings, gateway=gateway)


def _said(mind: ScriptedBrain) -> str:
    """Everything any model call was sent, as one text."""
    out: list[str] = []
    for c in mind.calls:
        for m in c.messages:
            out.append(m.content if isinstance(m.content, str) else m.text())
    return "\n".join(out)


async def _stored(store: InMemorySessionStore, sid: str) -> list[Turn]:
    session = await store.get(sid)
    assert session is not None
    return session.turns


# ---- the normal path ---------------------------------------------------------------------------
async def test_an_empty_answer_is_the_plain_sentence_never_the_filler(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    mind.say(Said(""))
    resp = await brain.chat(ChatRequest(message="add the sixty sessions"))
    assert resp.reply == finish.EMPTY and OLD not in resp.reply
    assert len(mind.calls) == 1  # empty but finished: no retry
    last = (await _stored(store, resp.session_id))[-1]
    assert last.content == finish.EMPTY and last.tool_derived is True


async def test_a_fixed_line_is_never_sent_back_to_a_model(
    brain: Brain, mind: ScriptedBrain
) -> None:
    mind.say(Said(""), Said("Certainly, Sir."))
    first = await brain.chat(ChatRequest(message="add the sixty sessions"))
    second = await brain.chat(ChatRequest(message="are you there?", session_id=first.session_id))
    assert second.reply == "Certainly, Sir."
    assert "empty answer" not in _said(mind) and OLD not in _said(mind)
    assert [m.role for m in mind.calls[-1].messages] == [Role.USER]
    assert mind.calls[-1].messages[0].content == "add the sixty sessions\n\nare you there?"


async def test_old_filler_turns_of_a_stored_conversation_are_not_replayed(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    session = Session(user_id="owner")
    for role, text in [(Role.USER, "add them"), (Role.ASSISTANT, OLD)] * 3:
        session.append(Turn(role=role, content=text))
    await store.save(session)
    mind.say(Said("On it, Sir."))
    resp = await brain.chat(ChatRequest(message="add them please", session_id=session.id))
    assert resp.reply == "On it, Sir." and OLD not in _said(mind)


async def test_a_cut_off_answer_is_retried_once_and_both_calls_are_paid_for(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    mind.say(Said("", stop=CUT, cost_usd=0.02), Said("Here is the plan, Sir.", cost_usd=0.01))
    resp = await brain.chat(ChatRequest(message="plan my week", user_id=BILL_UID))
    assert resp.reply == "Here is the plan, Sir."
    assert len(mind.calls) == 2
    assert mind.calls[1].messages[-1].content == finish.RETRY
    assert mind.calls[1].max_tokens == WORK
    month = await brain.billing.month(BILL_UID)
    assert month.calls == 2 and month.usd_total == pytest.approx(0.03)  # the retry is metered
    assert resp.cost_usd == pytest.approx(0.03)
    turns = await _stored(store, resp.session_id)
    assert [t.content for t in turns] == ["plan my week", "Here is the plan, Sir."]
    assert finish.RETRY not in "".join(t.content for t in turns)  # the instruction is not history


async def test_cut_off_twice_says_so_and_never_asks_a_third_time(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    mind.say(Said("", stop=CUT), Said("", stop=CUT), Said("unused"))
    resp = await brain.chat(ChatRequest(message="plan my week"))
    assert resp.reply == finish.CUT_OFF and len(mind.calls) == 2
    last = (await _stored(store, resp.session_id))[-1]
    assert last.content == finish.CUT_OFF and last.tool_derived is True


# ---- the tool loop -----------------------------------------------------------------------------
async def test_cards_waiting_and_no_words_says_how_many(
    brain: Brain, mind: ScriptedBrain, world: InMemoryWorld
) -> None:
    mind.say(
        Said(calls=(call("send_message", to="priya@example.com", body="Moving to 3."),)),
        Said(""),
    )
    resp = await brain.chat(ChatRequest(message="tell Priya we move to 3"))
    assert resp.reply == "I've prepared 1 approval for you, Sir."
    assert len(resp.pending_approvals) == 1 and world.sent == []


async def test_steps_ran_and_no_words_points_to_activity(brain: Brain, mind: ScriptedBrain) -> None:
    mind.say(
        Said(calls=(call("get_calendar", 0, day="today"), call("list_tasks", 1))),
        Said(""),
    )
    resp = await brain.chat(ChatRequest(message="what is on today?"))
    assert resp.reply == (
        "I did 2 steps but the AI gave me no words to report them. Activity shows what ran."
    )
    assert resp.tool_calls == 1


async def test_the_round_limit_summary_with_no_words_is_a_plain_sentence(
    brain: Brain, mind: ScriptedBrain
) -> None:
    rounds = brain.s.tool_max_rounds
    mind.say(*(Said(calls=(call("list_tasks", i),)) for i in range(rounds)), Said(""))
    resp = await brain.chat(ChatRequest(message="loop"))
    assert resp.reply == (
        f"I did {rounds} steps but the AI gave me no words to report them. Activity shows what ran."
    )
    assert mind.calls[-1].tools is None and mind.calls[-1].max_tokens == WORK


async def test_calls_from_a_cut_off_answer_never_run(
    brain: Brain, mind: ScriptedBrain, world: InMemoryWorld, store: InMemorySessionStore
) -> None:
    cut = Said(
        "Adding them now.",
        calls=tuple(call("create_reminder", i, text=f"S{i}", when="19:00") for i in range(3)),
        stop=CUT,
    )
    mind.say(cut, Said("That is too many for one answer, Sir; ask me for the first ten."))
    resp = await brain.chat(ChatRequest(message="add sixty reminders"))
    assert world.reminders == []  # a half-written batch is never acted on
    assert resp.reply.startswith("That is too many") and resp.tool_calls == 0
    turns = await _stored(store, resp.session_id)
    assert all(not t.blocks for t in turns)  # the cut-off tool calls are not history either


async def test_the_retry_may_use_a_tool_and_the_loop_goes_on(
    brain: Brain, mind: ScriptedBrain, world: InMemoryWorld
) -> None:
    mind.say(
        Said("", stop=CUT),
        Said(calls=(call("create_reminder", text="Session 1", when="19:00"),)),
        Said("One reminder set, Sir."),
    )
    resp = await brain.chat(ChatRequest(message="remind me"))
    assert resp.reply == "One reminder set, Sir." and len(world.reminders) == 1
    assert mind.calls[1].tools is not None  # the same call again: tools still offered


# ---- the output cap ----------------------------------------------------------------------------
async def test_a_working_turn_gets_the_working_cap_and_plain_chat_the_plain_one(
    brain: Brain, mind: ScriptedBrain, settings: Settings, store: InMemorySessionStore
) -> None:
    await brain.chat(ChatRequest(message="hello"))
    assert mind.calls[-1].max_tokens == WORK  # tools are on: it may need a long tool call
    plain = Brain(router=ModelRouter(mind, TIERS), store=store, settings=settings)
    await plain.chat(ChatRequest(message="hello"))
    assert mind.calls[-1].max_tokens == PLAIN and mind.calls[-1].tools is None


async def test_a_training_brain_and_an_approval_s_narration_keep_the_plain_cap(
    mind: ScriptedBrain,
    settings: Settings,
    store: InMemorySessionStore,
    gateway: Gateway,
    world: InMemoryWorld,
) -> None:
    training = ScriptedBrain()
    brains = BrainRegistry(
        [
            BrainSpec("private", "Private", mind, TIERS),
            BrainSpec("free", "Free", training, TIERS, trains_on_content=True),
        ],
        default_id="private",
    )
    brain = Brain(brains=brains, store=store, settings=settings, gateway=gateway)
    await brain.chat(ChatRequest(message="hello", brain="free"))
    assert training.calls[-1].max_tokens == PLAIN and training.calls[-1].tools is None

    mind.say(Said(calls=(call("send_message", to="a@example.com", body="x"),)), Said("Waiting."))
    asked = await brain.chat(ChatRequest(message="send it"))
    mind.say(Said("Sent, Sir."))
    await brain.approve(asked.pending_approvals[0].id, session_id=asked.session_id)
    assert world.sent and mind.calls[-1].max_tokens == PLAIN  # one sentence of narration


# ---- the stream --------------------------------------------------------------------------------
async def _stream(brain: Brain, text: str, **kw: str) -> str:
    return "".join([d async for d in brain.chat_stream(ChatRequest(message=text, **kw))])


async def test_a_stream_with_words_is_unchanged(brain: Brain, mind: ScriptedBrain) -> None:
    mind.say(Said("Good morning, Sir."))
    assert (await _stream(brain, "hello")).strip() == "Good morning, Sir."
    assert len(mind.calls) == 1


async def test_a_silent_stream_says_why_and_stores_no_empty_reply(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    mind.say(Said(""))
    out = await _stream(brain, "hello")
    assert out == finish.EMPTY and len(mind.calls) == 1
    sid = (await store.list_for_user("owner"))[0].id  # the one conversation of this test
    last = (await _stored(store, sid))[-1]
    assert last.content == finish.EMPTY and last.tool_derived is True


async def test_a_cut_off_silent_stream_is_asked_once_more_and_metered(
    brain: Brain, mind: ScriptedBrain, store: InMemorySessionStore
) -> None:
    mind.say(Said("", stop=CUT), Said("Here it is, Sir.", cost_usd=0.01))
    out = await _stream(brain, "write the long plan", user_id=BILL_UID)
    assert out == "Here it is, Sir." and len(mind.calls) == 2
    assert mind.calls[1].messages[-1].content == finish.RETRY
    assert mind.calls[1].max_tokens == WORK
    # the retry is a metered call like any other (the mock's own stream is priced at nothing)
    assert (await brain.billing.month(BILL_UID)).usd_total == pytest.approx(0.01)
    mind.say(Said("", stop=CUT), Said("", stop=CUT))
    assert await _stream(brain, "again", user_id=BILL_UID) == finish.CUT_OFF


async def test_steps_that_failed_are_said_apart_from_steps_that_ran(
    brain: Brain, mind: ScriptedBrain, world: InMemoryWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(dict):  # type: ignore[type-arg]
        def get(self, *_: object) -> object:
            raise RuntimeError("the calendar fell over")

    monkeypatch.setattr(world, "calendar", Broken())
    mind.say(
        Said(
            calls=(
                call("list_tasks", 0),
                call("get_calendar", 1, day="today"),  # raises while it runs
                call("create_reminder", 2),  # its arguments are refused
            )
        ),
        Said(""),
    )
    resp = await brain.chat(ChatRequest(message="what is on today?"))
    assert resp.reply == (
        "I did 1 step and 2 failed, but the AI gave me no words to report them. "
        "Activity shows what ran."
    )


async def test_a_simply_empty_stream_is_not_asked_again(brain: Brain, mind: ScriptedBrain) -> None:
    """D2 retries only an answer the cap cut off; a stream that ended with no words and was not
    cut off says so at once (`finish.after_stream`)."""
    mind.say(Said(""), Said("never asked"))
    assert await _stream(brain, "hello") == finish.EMPTY and len(mind.calls) == 1


def test_the_brain_s_long_functions_are_split() -> None:
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "core" / "brain.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    long = {
        f.name: (f.end_lineno or 0) - f.lineno + 1
        for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert {k: v for k, v in long.items() if k in {"_chat", "_run_loop", "_chat_stream"}} == {
        k: min(v, 50) for k, v in long.items() if k in {"_chat", "_run_loop", "_chat_stream"}
    }
    assert len(src.read_text(encoding="utf-8").splitlines()) <= 741  # brain.py does not grow
