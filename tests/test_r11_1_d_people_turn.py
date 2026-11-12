# tests/test_r11_1_d_people_turn.py -- R11.1 Part D after the security review (H1, M3):
# `research_person` on the MAIN brain's path, through a real gateway. On a turn whose latest owner
# message carried a picture the tool researches only a name the owner typed; a name the picture's
# own text holds comes back as an OFFER (fixed words, the caption line, a "Look up" card he
# presses) and nothing is searched; anything else is refused in fixed words. A name that is
# refused never even becomes an approval card ("Ask first"), so no card can show a name taken from
# a face. Outside a picture turn, and for his own press, nothing changes. Everybody named here is
# made up; the public-figure check (people/gate.py) is untouched.
from __future__ import annotations

import typing
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from research_fakes import FakeModel, FakeSearcher, fixed_mode, hit

import jarvis.people.offer as offer_mod
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.people.offer import NOT_SHOWN, show
from jarvis.people.offer_card import PeopleOfferCard
from jarvis.people.research import PeopleService
from jarvis.people.tools import RESEARCH_PERSON, PeopleDeps, people_tools
from jarvis.picture.guard import NO_IDENTIFY
from jarvis.picture.research import Report
from jarvis.picture.turnguard import OFFER_WORDS, TurnGuard
from jarvis.tools import reply_cards
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reply_cards import collecting_cards
from jarvis.tools.taint import context_trust

UID, SID = "u_owner", "sess_1"
NAME = "Lekha Examplekar"  # a made-up public figure
FACE = "Meenu Examplewala"  # a made-up person the model "recognised"
CAPTION = f"MINISTER {NAME.upper()} OPENS THE HARBOUR BRIDGE"
HITS = [
    hit(f"{NAME} - Wikipedia", "https://en.wikipedia.org/wiki/Lekha_Examplekar",
        f"{NAME} is the minister for ports"),
    hit(f"{NAME} - LinkedIn", "https://www.linkedin.com/in/example-person-0001",
        f"{NAME}, minister for ports"),
]  # fmt: skip


class Turns:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def carried(self, uid: str, session_id: str) -> str:
        return self.answer


class Rows:
    def __init__(self, effect: Effect) -> None:
        self.effect = effect

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern="research_*", effect=self.effect, source="owner")]


def _rig(
    picture: bool, report: Report | None = None, rows: Effect | None = None
) -> tuple[Gateway, FakeSearcher]:
    searcher = FakeSearcher(HITS)
    svc = PeopleService(searcher, FakeModel(), mode=fixed_mode("ai"))
    guard = TurnGuard(Turns("yes" if picture else "no"), lambda uid, sid: report)
    registry = ToolRegistry()
    for tool in people_tools(PeopleDeps(svc, pictures=guard)):
        registry.register(tool)
    gw = Gateway(
        registry=registry,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=Rows(rows) if rows is not None else None,
    )
    return gw, searcher


@contextmanager
def typed(words: str) -> Iterator[None]:
    """A Brain turn in which the owner typed `words` (as `Brain._run_calls` sets it)."""
    with context_trust(untrusted=False, owner_text=words):
        yield


async def _research(gw: Gateway, name: str) -> GatewayResult:
    call = ToolCall(id="t1", name=RESEARCH_PERSON, arguments={"name": name})
    return await gw.execute(call, scope=f"{UID}:{SID}")


def _report() -> Report:
    return Report("done", "said", person=True, text=("PORT DAY 2026", CAPTION), named=NAME)


# ---- a picture turn ------------------------------------------------------------------------------
async def test_a_name_from_a_face_is_refused_in_fixed_words_and_nothing_is_searched() -> None:
    gw, searcher = _rig(picture=True)
    with typed("who is this?"):
        res = await _research(gw, FACE)

    assert res.outcome is GatewayOutcome.ERROR and NO_IDENTIFY in (res.error or "")
    assert searcher.queries == [] and FACE not in (res.error or "")


async def test_a_name_he_typed_is_researched_behind_the_unchanged_check() -> None:
    gw, searcher = _rig(picture=True)
    with typed(f"Is this {NAME}, the minister?"):
        res = await _research(gw, NAME)

    assert res.outcome is GatewayOutcome.EXECUTED and res.result["subject"] == "public_figure"
    assert searcher.queries[:1] == [NAME]


async def test_a_name_the_pictures_text_holds_is_only_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reply_cards, "AnyCard", reply_cards.AnyCard | PeopleOfferCard)  # I1's line
    gw, searcher = _rig(picture=True, report=_report())
    cards: list[Any] = []
    with typed("who is this?"), collecting_cards(cards):
        res = await _research(gw, NAME)

    out = res.result
    assert res.outcome is GatewayOutcome.EXECUTED and searcher.queries == []
    assert out["offer"] is True and out["refused"] is False
    assert out["message"] == OFFER_WORDS.format(name=NAME) == out["spoken"]
    assert out["caption"].startswith(FENCE_PREFIX) and CAPTION in out["caption"]
    assert out["card_shown"] is True and "profiles" not in out
    (card,) = cards
    assert card == PeopleOfferCard(name=NAME, caption=CAPTION, words=OFFER_WORDS.format(name=NAME))
    assert card.button == "Look up"


async def test_until_the_card_kind_is_registered_the_offer_says_the_button_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # I1 registered the kind (reply_cards.AnyCard); the path where a reply cannot carry the card
    # is kept honest by taking it out again here
    known = tuple(c for c in typing.get_args(reply_cards.AnyCard) if c is not PeopleOfferCard)
    monkeypatch.setattr(reply_cards, "AnyCard", typing.Union[known])  # noqa: UP007
    gw, searcher = _rig(picture=True, report=_report())
    cards: list[Any] = []
    with typed("who is this?"), collecting_cards(cards):
        res = await _research(gw, NAME)

    assert cards == [] and res.result["card_shown"] is False
    assert res.result["note"] == NOT_SHOWN and searcher.queries == []


async def test_a_turn_without_a_picture_is_unchanged() -> None:
    gw, searcher = _rig(picture=False)
    with typed("who is the minister for ports?"):
        res = await _research(gw, NAME)

    assert res.outcome is GatewayOutcome.EXECUTED and searcher.queries[:1] == [NAME]


async def test_his_own_press_outside_a_turn_is_unchanged() -> None:
    gw, searcher = _rig(picture=True)

    res = await _research(gw, NAME)  # the People panel, or a card he approved

    assert res.outcome is GatewayOutcome.EXECUTED and searcher.queries[:1] == [NAME]


async def test_not_wired_it_fails_closed() -> None:
    svc = PeopleService(FakeSearcher(HITS), FakeModel(), mode=fixed_mode("ai"))
    (research, _) = people_tools(PeopleDeps(svc))  # no guard handed over: every turn is a picture's
    registry = ToolRegistry()
    registry.register(research)
    gw = Gateway(registry=registry, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    with typed("who is the minister for ports?"):
        res = await _research(gw, NAME)

    assert res.outcome is GatewayOutcome.ERROR and NO_IDENTIFY in (res.error or "")


# ---- "Ask first": no card can carry a name taken from a face -------------------------------------
async def test_with_ask_first_a_refused_name_never_becomes_a_card() -> None:
    gw, searcher = _rig(picture=True, rows=Effect.ASK)
    with typed("who is this?"):
        res = await _research(gw, FACE)

    assert res.outcome is GatewayOutcome.ERROR and res.pending is None
    assert await gw.gate.pending() == [] and searcher.queries == []


async def test_with_ask_first_a_typed_name_gets_the_usual_card() -> None:
    gw, _ = _rig(picture=True, rows=Effect.ASK)
    with typed(f"who is {NAME}?"):
        res = await _research(gw, NAME)

    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None
    assert res.pending.summary == f"Research {NAME} from public sources"


async def test_with_ask_first_a_printed_name_is_carded_and_his_approval_researches_it() -> None:
    """The card he approves is his own press, like the offer's button: one approval, then the
    people research behind the unchanged check (the card's words do not change at approval)."""
    gw, searcher = _rig(picture=True, report=_report(), rows=Effect.ASK)
    with typed("who is this?"):
        res = await _research(gw, NAME)
    assert res.pending is not None and searcher.queries == []
    assert res.pending.summary == f"Research {NAME} from public sources"

    call = ToolCall(id="t1", name=RESEARCH_PERSON, arguments={"name": NAME})
    done = await gw.execute(call, confirmation_id=res.pending.id, scope=f"{UID}:{SID}")

    assert done.outcome is GatewayOutcome.EXECUTED and done.result["subject"] == "public_figure"
    assert searcher.queries[:1] == [NAME]


# ---- the card itself -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        {"name": "the woman in blue"},
        {"name": NAME, "button": "Research now"},
        {"name": NAME, "caption": "x" * 201},
        {"name": NAME, "kind": "places"},
    ],
)
def test_the_offer_card_takes_only_a_name_shaped_name_and_its_fixed_button(
    bad: dict[str, Any],
) -> None:
    fields = {"name": NAME, "caption": CAPTION, "words": OFFER_WORDS.format(name=NAME), **bad}
    with pytest.raises(ValueError):
        PeopleOfferCard(**fields)


def test_outside_a_reply_the_card_is_not_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reply_cards, "AnyCard", reply_cards.AnyCard | PeopleOfferCard)
    card = PeopleOfferCard(name=NAME, caption=CAPTION, words=OFFER_WORDS.format(name=NAME))

    assert show(card) is False and offer_mod.kind_known() is True


def test_the_card_can_be_listed_by_reply_cards_without_an_import_cycle() -> None:
    """I1 adds `PeopleOfferCard` to `reply_cards.AnyCard`, so `jarvis.tools.reply_cards` will
    import its module: that module must not import reply_cards (or the offer) back."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    probe = (
        "import sys, jarvis.people.offer_card; "
        "print(sorted(m for m in sys.modules if m in "
        "('jarvis.tools.reply_cards', 'jarvis.people.offer', 'jarvis.people.tools')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(src)},
    )

    assert done.stdout.strip() == "[]"
