# tests/test_r11_1_a_finish.py -- R11.1 Part A, O1 (plan D1-D3): what a reply's words are when the
# model gave none, which answers count as cut off, the one retry, the output cap of a working
# turn, and that no fixed line (or the old filler) is ever part of a model's window.
from __future__ import annotations

import pytest
from r11_1_fakes_a import CUT, call

from jarvis.billing import BudgetReached
from jarvis.config import Settings
from jarvis.core import finish
from jarvis.core.models import Turn
from jarvis.core.window import build_window
from jarvis.llm.base import ChatMessage, Completion, LLMTransientError, Role, Usage
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier

OLD = "I have nothing to add, Sir."
MSGS = [ChatMessage(role=Role.USER, content="add these to my calendar")]


def done(
    text: str = "", *, stop: str = "end_turn", calls: tuple = (), cost: float = 0.0
) -> Completion:
    return Completion(
        text=text,
        tool_calls=list(calls),
        model="m",
        provider="mock",
        usage=Usage(input_tokens=10, output_tokens=5),
        stop_reason=stop,
        latency_ms=3,
        cost_usd=cost,
    )


# ---- the words of a reply ----------------------------------------------------------------------
def test_words_are_the_reply_and_the_old_filler_is_gone() -> None:
    assert finish.reply_text(done("  Done, Sir. ")) == "Done, Sir."
    assert finish.OLD_FILLER == OLD
    assert OLD not in finish.reply_text(done(""))
    assert finish.FILLER == finish.EMPTY and "nothing to add" not in finish.EMPTY


@pytest.mark.parametrize(
    ("stop", "cards", "steps", "want"),
    [
        ("end_turn", 0, 0, finish.EMPTY),
        ("end_turn", 1, 0, "I've prepared 1 approval for you, Sir."),
        ("end_turn", 3, 0, "I've prepared 3 approvals for you, Sir."),
        (
            "end_turn",
            0,
            1,
            "I did 1 step but the AI gave me no words to report it. Activity shows what ran.",
        ),
        (
            "end_turn",
            0,
            4,
            "I did 4 steps but the AI gave me no words to report them. Activity shows what ran.",
        ),
        (CUT, 0, 0, finish.CUT_OFF),
        ("length", 0, 0, finish.CUT_OFF),
    ],
)
def test_no_words_becomes_a_fixed_line_chosen_from_what_happened(
    stop: str, cards: int, steps: int, want: str
) -> None:
    said = finish.reply_text(done("", stop=stop), cards=cards, steps=steps)
    assert said == want and finish.is_fixed(said) and OLD not in said


def test_what_happened_is_never_hidden_by_the_cut_off_line() -> None:
    said = finish.reply_text(done("", stop=CUT), cards=2, steps=3)
    assert said.startswith("I've prepared 2 approvals for you, Sir.")
    assert "I did 3 steps" in said and "cut off" in said and finish.is_fixed(said)
    assert said.count("Sir") == 1  # one sentence addresses him, not three


def test_the_plan_s_exact_sentences() -> None:
    assert finish.CUT_OFF == (
        "My answer was cut off before I could finish, Sir. Ask me for a smaller piece, or raise "
        "the answer length in Settings."
    )
    assert finish.EMPTY == (
        "The AI returned an empty answer, Sir. Please ask again; if it repeats, switch brain in "
        "the top bar."
    )
    assert finish.RETRY == (
        "Answer in words now. If the work needs many tool calls, use the batch tool or say what "
        "remains."
    )


@pytest.mark.parametrize(
    "text",
    [
        "You have a stand-up at 09:30, Sir.",
        "I did 2 steps and here is what I found: nothing.",
        "My answer was cut off",
        "",
        "   ",
    ],
)
def test_a_real_answer_is_not_a_fixed_line(text: str) -> None:
    assert finish.is_fixed(text) is False


# ---- cut short ---------------------------------------------------------------------------------
def test_which_answers_are_unfinished() -> None:
    one = call("calendar_create_event", summary="x")
    assert finish.unfinished(done("", stop=CUT)) is True  # no words at all
    assert finish.unfinished(done("I'll add", stop=CUT, calls=(one,))) is True  # calls half-written
    assert finish.unfinished(done("A long answer that stops mid", stop=CUT)) is False  # words: kept
    assert finish.unfinished(done("")) is False  # empty but finished: no retry, a fixed line
    assert finish.unfinished(done("", calls=(one,), stop="tool_use")) is False


# ---- the one retry -----------------------------------------------------------------------------
class Calls:
    """A model call that answers from a script and records what it was asked."""

    def __init__(self, *answers: Completion | Exception) -> None:
        self.answers = list(answers)
        self.seen: list[tuple[list[ChatMessage], bool]] = []

    async def __call__(self, msgs: list[ChatMessage], working: bool) -> Completion:
        self.seen.append((msgs, working))
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


async def test_a_finished_answer_is_not_asked_twice() -> None:
    ask, tries = Calls(done("Hello, Sir.")), finish.Tries(1)
    out = await finish.asked(ask, MSGS, tries, working=False)
    assert out.text == "Hello, Sir." and len(ask.seen) == 1 and ask.seen[0][1] is False
    assert tries.left == 1


async def test_a_cut_off_answer_is_asked_once_more_with_the_working_cap() -> None:
    ask = Calls(done("", stop=CUT, cost=0.01), done("Here it is, Sir.", cost=0.02))
    tries = finish.Tries(1)
    out = await finish.asked(ask, MSGS, tries, working=False)
    assert out.text == "Here it is, Sir." and tries.left == 0
    (first, w1), (second, w2) = ask.seen
    assert first == MSGS and w1 is False
    assert second[:-1] == MSGS and second[-1] == ChatMessage(role=Role.USER, content=finish.RETRY)
    assert w2 is True  # the retry always gets the working cap
    # both calls were paid for: the conversation's totals carry both
    assert out.cost_usd == pytest.approx(0.03) and out.usage.output_tokens == 10
    assert out.usage.input_tokens == 20 and out.latency_ms == 6


async def test_still_cut_off_after_the_retry_is_nothing_and_never_a_third_call() -> None:
    one = call("calendar_create_event", summary="x")
    ask = Calls(done("", stop=CUT), done("so", stop=CUT, calls=(one,)))
    tries = finish.Tries(1)
    out = await finish.asked(ask, MSGS, tries, working=True)
    assert (out.text, out.tool_calls) == ("", []) and finish.cut_short(out)
    assert len(ask.seen) == 2
    again = await finish.asked(Calls(done("", stop=CUT)), MSGS, tries, working=True)
    assert again.text == "" and finish.cut_short(again)  # no retry is left for this message


async def test_half_written_tool_calls_never_come_back_from_a_cut_off_answer() -> None:
    one = call("calendar_create_event", summary="x")
    ask = Calls(done("", stop=CUT, calls=(one, one)), done("", calls=(one,), stop="tool_use"))
    out = await finish.asked(ask, MSGS, finish.Tries(1), working=True)
    assert out.tool_calls == [one]  # the retry's complete call, not the cut-off pair
    none_left = await finish.asked(
        Calls(done("", stop=CUT, calls=(one,))), MSGS, finish.Tries(0), working=True
    )
    assert none_left.tool_calls == []


@pytest.mark.parametrize(
    "error",
    [LLMTransientError("down"), BudgetReached(limit_inr=100, used_inr=120.0, free_brain=False)],
)
async def test_a_retry_that_cannot_be_made_ends_in_the_cut_off_line(error: Exception) -> None:
    ask = Calls(done("", stop=CUT, cost=0.01), error)
    out = await finish.asked(ask, MSGS, finish.Tries(1), working=True)
    assert out.text == "" and finish.cut_short(out) and out.cost_usd == pytest.approx(0.01)
    assert finish.reply_text(out) == finish.CUT_OFF


# ---- the output cap ----------------------------------------------------------------------------
def test_a_working_turn_may_write_more_and_a_training_brain_never_does() -> None:
    s = Settings(_env_file=None)
    assert finish.output_cap(s, working=False) == 1024
    assert finish.output_cap(s, working=True) == 8192
    private = BrainSpec("a", "A", MockProvider(), {ModelTier.FAST: "m"})
    training = BrainSpec("t", "T", MockProvider(), {ModelTier.FAST: "m"}, trains_on_content=True)
    assert finish.working_turn(private, tools=True, attachments=False) is True
    assert finish.working_turn(private, tools=False, attachments=True) is True
    assert finish.working_turn(private, tools=False, attachments=False) is False
    assert finish.working_turn(training, tools=True, attachments=True) is False


# ---- the window --------------------------------------------------------------------------------
def _t(role: Role, content: str) -> Turn:
    return Turn(role=role, content=content)


def test_a_fixed_line_and_the_old_filler_never_reach_a_model() -> None:
    turns = [
        _t(Role.USER, "add the sixty sessions"),
        _t(Role.ASSISTANT, OLD),  # stored by R11 and earlier
        _t(Role.USER, "hello?"),
        _t(Role.ASSISTANT, finish.EMPTY),
        _t(Role.USER, "again"),
        _t(Role.ASSISTANT, finish.reply_text(done("", stop=CUT), cards=1)),
        _t(Role.USER, "and now"),
        _t(Role.ASSISTANT, "All sixty are waiting on one card, Sir."),
        _t(Role.USER, "thanks"),
    ]
    win = build_window(turns, max_turns=50, max_chars=10_000)
    said = "\n".join(str(m.content) for m in win)
    assert OLD not in said and "empty answer" not in said and "cut off" not in said
    assert [m.role for m in win] == [Role.USER, Role.ASSISTANT, Role.USER]
    assert win[0].content == "add the sixty sessions\n\nhello?\n\nagain\n\nand now"
    assert win[1].content == "All sixty are waiting on one card, Sir."


def test_the_owner_may_say_the_same_words_and_a_dropped_line_costs_no_budget() -> None:
    turns = [
        _t(Role.USER, "u0"),
        _t(Role.ASSISTANT, "a0"),
        _t(Role.USER, OLD),  # his own words stay
        _t(Role.ASSISTANT, finish.EMPTY),
    ]
    win = build_window(turns, max_turns=3, max_chars=10_000)
    assert [m.content for m in win] == ["u0", "a0", OLD]
