# tests/test_r11_1_d_turnguard.py -- R11.1 Part D after the security review (H1, M3): on a turn
# whose latest owner message carried a picture, the MAIN brain can't turn a face into a name. A
# person's name is accepted only when the owner typed every word of it in that message; a name
# the picture's own text holds becomes an OFFER he presses; anything else is refused in fixed
# words. A web query on such a turn may carry no name the owner did not type or the picture does
# not show. "Did the message carry a picture?" is asked of Part B's contract through a small port,
# and an unknown answer or a fault counts as YES (fail closed). Everybody named here is made up.
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

import jarvis.picture.turnguard as tg
from jarvis.fixes.ports import FixPart
from jarvis.picture.guard import NO_IDENTIFY, Subject
from jarvis.picture.research import Report
from jarvis.picture.turnguard import (
    ALLOWED,
    OFFER_WORDS,
    WEB_REFUSED,
    Allowed,
    DocumentTurns,
    Offer,
    Refused,
    TurnGuard,
    app_guard,
    check_name,
    check_query,
)
from jarvis.tools.context import tool_context
from jarvis.tools.taint import context_trust

UID, SID = "u_owner", "sess_1"
NAME = "Lekha Examplekar"  # a made-up person
CAPTION = f"MINISTER {NAME.upper()} OPENS THE HARBOUR BRIDGE"


# ---- the pure checks -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "typed",
    [f"Who is {NAME}?", f"who is {NAME.lower()} in this photo", f"look up {NAME.upper()} please"],
)
def test_a_name_he_typed_is_allowed_in_any_letter_case(typed: str) -> None:
    assert check_name(NAME, typed, ()) == ALLOWED


def test_half_a_name_typed_is_not_the_name() -> None:
    assert isinstance(check_name(NAME, "who is Lekha?", ()), Refused)


def test_a_name_the_pictures_text_holds_is_only_an_offer_with_its_line() -> None:
    got = check_name(NAME, "who is this?", ("PORT DAY 2026", CAPTION))

    assert got == Offer(NAME, CAPTION)
    assert got.words() == (
        f"The picture's text names {NAME}. Press 'Look up' to check them with your people research."
    )
    assert OFFER_WORDS.format(name=NAME) == got.words()


@pytest.mark.parametrize("name", [NAME, "Minister Lekha", "the woman in blue", ""])
def test_anything_else_on_a_picture_turn_is_refused_in_fixed_words(name: str) -> None:
    got = check_name(name, "who is this?", ("HARBOUR BRIDGE",))

    assert got == Refused(NO_IDENTIFY)


@pytest.mark.parametrize(
    ("query", "typed", "printed"),
    [
        ("Samsung phone price", "what phone is this?", ("SAMSUNG",)),
        ("Price of Samsung phone in Kochi", "where can I buy this in kochi", ("SAMSUNG",)),
        ("Gateway of India history", "tell me about this", ("Gateway of India monument",)),
        (f"{NAME} minister", f"who is {NAME}, the minister?", ()),
        ("biryani recipe", "how do I make this?", ()),
        ("best time to visit", "when should I go?", ()),
    ],
)
def test_a_query_of_typed_printed_and_plain_words_is_allowed(
    query: str, typed: str, printed: tuple[str, ...]
) -> None:
    assert check_query(query, typed, printed) == ALLOWED


@pytest.mark.parametrize(
    "query",
    [
        f"{NAME} minister",
        f"Is this {NAME}",
        NAME.upper(),
        NAME.lower(),  # a bare name in lower case
        "Kohli",
        "who is the woman in the red sari",
        "actress with short hair",
        "Bill Gates",
    ],
)
def test_a_query_naming_or_describing_a_person_he_did_not_type_is_refused(query: str) -> None:
    assert check_query(query, "who is this?", ("HARBOUR BRIDGE",)) == Refused(WEB_REFUSED)


# ---- the turn ------------------------------------------------------------------------------------
@dataclass
class Turns:
    """The port: what Part B's contract answered for the latest owner message."""

    answer: str = "yes"
    raises: Exception | None = None
    asked: list[tuple[str, str]] = field(default_factory=list)

    async def carried(self, uid: str, session_id: str) -> str:
        self.asked.append((uid, session_id))
        if self.raises is not None:
            raise self.raises
        return self.answer


def _report(*text: str, subjects: tuple[Subject, ...] = ()) -> Report:
    return Report("done", "said", text=tuple(text), subjects=subjects)


@contextmanager
def turn(typed: str | None, scope: str | None = f"{UID}:{SID}") -> Iterator[None]:
    """A tool call inside a Brain turn whose owner typed `typed` (None: outside a turn)."""
    with tool_context(scope), context_trust(untrusted=False, owner_text=typed):
        yield


def _guard(turns: Turns | None, reports: dict[tuple[str, str], Report] | None = None) -> TurnGuard:
    kept = reports or {}
    return TurnGuard(turns, lambda uid, sid: kept.get((uid, sid)))


async def test_outside_a_turn_his_own_press_is_never_second_guessed() -> None:
    turns = Turns()
    with turn(None):
        assert await _guard(turns).name("Anyone Examplewala") == ALLOWED
        assert await _guard(turns).query("Anyone Examplewala") == ALLOWED
    assert turns.asked == []


async def test_a_turn_without_a_picture_is_unchanged() -> None:
    turns = Turns(answer="no")
    with turn("who runs Example Corp?"):
        assert await _guard(turns).name(NAME) == ALLOWED
        assert await _guard(turns).query(f"{NAME} Example Corp") == ALLOWED
    assert turns.asked == [(UID, SID), (UID, SID)]


async def test_a_typed_name_needs_no_question_about_pictures() -> None:
    turns = Turns()
    with turn(f"who is {NAME}?"):
        assert await _guard(turns).name(NAME) == ALLOWED
    assert turns.asked == []


async def test_on_a_picture_turn_the_last_reports_text_makes_an_offer_and_nothing_else() -> None:
    reports = {(UID, SID): _report("PORT DAY 2026", CAPTION)}
    with turn("who is this?"):
        offered = await _guard(Turns(), reports).name(NAME)
        refused = await _guard(Turns(), reports).name("Meenu Examplewala")
    with turn("who is this?", scope=f"{UID}:sess_other"):
        elsewhere = await _guard(Turns(), reports).name(NAME)

    assert offered == Offer(NAME, CAPTION)
    assert refused == Refused(NO_IDENTIFY) and elsewhere == Refused(NO_IDENTIFY)


async def test_a_query_may_use_the_last_reports_text_and_vetted_things() -> None:
    charminar = Subject("landmark", "Charminar monument")
    reports = {(UID, SID): _report("SAMSUNG", subjects=(charminar,))}
    with turn("what is this?"):
        guard = _guard(Turns(), reports)
        assert await guard.query("Samsung phone price") == ALLOWED
        assert await guard.query("Charminar history") == ALLOWED
        assert await guard.query(f"{NAME} Charminar") == Refused(WEB_REFUSED)


@pytest.mark.parametrize(
    "turns",
    [
        Turns(answer="unknown"),
        Turns(raises=RuntimeError("store down: a picture of u_owner")),
        None,  # not wired
    ],
)
async def test_an_unknown_answer_a_fault_or_no_port_counts_as_a_picture_turn(
    turns: Turns | None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    with turn("who runs Example Corp?"):
        got = await _guard(turns).name(NAME)

    assert got == Refused(NO_IDENTIFY)
    assert "store down" not in caplog.text and "u_owner" not in caplog.text


async def test_without_a_tool_context_it_fails_closed() -> None:
    with turn("who runs Example Corp?", scope=None):
        assert await _guard(Turns(answer="no")).name(NAME) == Refused(NO_IDENTIFY)


async def test_the_refusal_and_the_web_refusal_are_plain_results() -> None:
    with turn("who is this?"):
        stop = await _guard(Turns()).query_stop(NAME)
        go = await _guard(Turns()).query_stop("biryani recipe")

    assert stop == {"refused": True, "message": WEB_REFUSED, "spoken": WEB_REFUSED}
    assert go is None and isinstance(ALLOWED, Allowed)


# ---- the port over Part B's contract -------------------------------------------------------------
@pytest.mark.parametrize(
    ("answer", "expected"),
    [(["a picture"], "yes"), ([], "no"), (RuntimeError("fault"), "unknown"), ("odd", "unknown")],
)
async def test_the_document_port_maps_part_bs_answer(
    answer: Any, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[object, str, str]] = []

    async def turn_pictures(docs: object, uid: str, session_id: str, **_kw: Any) -> Any:
        seen.append((docs, uid, session_id))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(tg, "turn_pictures", turn_pictures)
    store = object()

    assert await DocumentTurns(lambda: store).carried(UID, SID) == expected
    assert seen == [(store, UID, SID)]


async def test_with_no_document_store_no_picture_can_have_been_attached() -> None:
    assert await DocumentTurns(lambda: None).carried(UID, SID) == "no"


async def test_the_app_guard_reads_the_store_and_the_last_report_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}

    async def turn_pictures(docs: object, uid: str, session_id: str, **_kw: Any) -> list[str]:
        return ["a picture"] if docs == "the store" else []

    class Service:
        def last(self, uid: str, session_id: str) -> Report | None:
            return _report(CAPTION) if (uid, session_id) == (UID, SID) else None

    monkeypatch.setattr(tg, "turn_pictures", turn_pictures)
    guard = app_guard(state.get)  # built before the app has either
    state["documents"] = "the store"
    state["r111_parts"] = {"look": FixPart("look", services={"research": Service()})}

    with turn("who is this?"):
        assert await guard.name(NAME) == Offer(NAME, CAPTION)
    state["r111_parts"] = {}  # the part left out: no report, still a picture turn
    with turn("who is this?"):
        assert await guard.name(NAME) == Refused(NO_IDENTIFY)


def test_web_search_can_import_the_guard_without_a_cycle() -> None:
    """I1's gate puts one call into `web_search`'s run, so `jarvis.web.tools` will import this
    module: it must not import the web search back (picture.search does), at import time."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    probe = (
        "import sys, jarvis.picture.turnguard; "
        "print(sorted(m for m in sys.modules if m in "
        "('jarvis.web.tools', 'jarvis.picture.research', 'jarvis.picture.search')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(src)},
    )

    assert done.stdout.strip() == "[]"
