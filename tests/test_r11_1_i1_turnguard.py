# tests/test_r11_1_i1_turnguard.py -- R11.1 I1 reviews (security H1, M2, M3; code M3): which
# check the turn guard uses on a picture turn, and every outward free-text tool behind it. The
# only `has_person` signal on the main brain's turn is the conversation's last picture research:
# LIGHT only when it looked at the ONLY picture of THIS message (the same message key) and saw
# nobody; anything else (no research, an older picture, two pictures, a person, a fault) is
# STRICT. YouTube, Maps (search and route) and people research's context are outward words too,
# refused in fixed words before any vendor is asked. Everybody named is made up.
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from media_fakes import KEY, FakeGoogleKeyAPIs
from pydantic import SecretStr
from research_fakes import FakeModel, FakeSearcher, fixed_mode

from jarvis.core.guardrails import ConfirmationGate
from jarvis.documents.pictures import TurnPictures, message_key
from jarvis.integrations.google_key import GoogleKeyClient
from jarvis.llm.base import ImageBlock, ToolCall
from jarvis.media.service import YouTubeService
from jarvis.media.tools import youtube_tools
from jarvis.people.research import PeopleService
from jarvis.people.tools import RESEARCH_PERSON, PeopleDeps, people_tools
from jarvis.picture.research import Report
from jarvis.picture.turnguard import ALLOWED, WEB_REFUSED, DocumentTurns, Refused, TurnGuard
from jarvis.places.service import MapsService
from jarvis.places.store import MapsPlaces
from jarvis.places.tools import maps_tools
from jarvis.quota.ledger import QuotaLedger
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.context import tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust

UID, SID = "u_owner", "sess_1"
FACE = "Meenu Examplewala"  # a made-up person a model "recognised" from a face
KEY_OF_THIS = f"{SID}:this-message"
ORDINARY = "Kerala monsoon forecast"  # an untyped place name: light lets it go, strict does not


@dataclass
class Port:
    """The two ports, as `DocumentTurns` answers them: a picture with the latest message, and
    the key of that message's pictures (or a fault)."""

    carried_answer: str = "yes"
    key: str | None = KEY_OF_THIS
    fails: bool = False

    async def carried(self, uid: str, session_id: str) -> str:
        return self.carried_answer

    async def message(self, uid: str, session_id: str) -> str | None:
        if self.fails:
            raise RuntimeError("store down: a picture of u_owner")
        return self.key


def _seen(*, person: bool = False, pictures: int = 1, key: str = KEY_OF_THIS) -> Report:
    return Report("done", "A packet.", person=person, pictures=pictures, key=key)


def _guard(port: Port, report: Report | None, keys: bool = True) -> TurnGuard:
    return TurnGuard(port, lambda uid, sid: report, keys=port if keys else None)


@contextmanager
def turn(typed: str = "what is this?") -> Iterator[None]:
    with tool_context(f"{UID}:{SID}"), context_trust(untrusted=False, owner_text=typed):
        yield


# ---- which check: the only has_person signal is a report of THIS message's only picture -------
async def test_light_only_when_this_message_s_only_picture_was_seen_without_a_person() -> None:
    with turn():
        assert await _guard(Port(), _seen()).query(ORDINARY) == ALLOWED
        assert await _guard(Port(), _seen()).query(FACE.lower()) == Refused(WEB_REFUSED)


@pytest.mark.parametrize(
    ("why", "port", "report", "keys"),
    [
        ("nobody looked at the picture", Port(), None, True),
        ("it showed a person", Port(), _seen(person=True), True),
        ("an older message's picture", Port(), _seen(key=f"{SID}:an-older-one"), True),
        ("one of two pictures", Port(), _seen(pictures=2), True),
        ("a report with no key", Port(), _seen(key=""), True),
        ("no key port", Port(), _seen(), False),
        ("the key can't be read", Port(key=None), _seen(), True),
        ("the picture turn is unknown", Port(carried_answer="unknown"), None, True),
    ],
)
async def test_anything_else_is_strict(
    why: str, port: Port, report: Report | None, keys: bool
) -> None:
    with turn():
        assert await _guard(port, report, keys).query(ORDINARY) == Refused(WEB_REFUSED), why


async def test_a_fault_reading_the_key_is_strict_and_logs_no_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    with turn():
        got = await _guard(Port(fails=True), _seen()).query(ORDINARY)
    assert got == Refused(WEB_REFUSED)
    assert "picture message unknown" in caplog.text and "u_owner" not in caplog.text


async def test_a_turn_without_a_picture_is_unchanged_in_every_mode() -> None:
    with turn():
        assert await _guard(Port(carried_answer="no"), None).query(f"{FACE} biography") == ALLOWED


async def test_strict_lets_his_words_and_the_picture_s_words_go_out() -> None:
    shown = Report("done", "x", text=("PARLE-G",), pictures=1, person=True, key=KEY_OF_THIS)
    with turn("what does this packet cost in kochi?"):
        guard = _guard(Port(), shown)
        assert await guard.query("Parle-G packet price in Kochi") == ALLOWED
        assert await guard.query("Parle-G packet price in Thrissur") == Refused(WEB_REFUSED)


async def test_a_name_split_across_two_queries_of_one_turn_goes_out_in_neither() -> None:
    with turn():
        guard = _guard(Port(), None)
        first = await guard.query("Meenu weather")
        second = await guard.query("Examplewala news")
    assert first == second == Refused(WEB_REFUSED)


# ---- the port's message key: the same as picture research's -----------------------------------
def _shot(data: bytes = b"\x89PNG-one") -> ImageBlock:
    return ImageBlock(media_type="image/png", data=data)


async def test_the_port_gives_the_key_picture_research_gives_and_none_when_it_cannot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.picture.turnguard as tg

    answers: list[Any] = [
        TurnPictures([_shot()]),
        TurnPictures(),
        TurnPictures([_shot()], unreadable=True),
        RuntimeError("store down"),
    ]

    async def pictures(docs: Any, uid: str, sid: str, **_kw: Any) -> Any:
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(tg, "turn_pictures", pictures)
    port = DocumentTurns(lambda: object())
    assert await port.message(UID, SID) == message_key(SID, [_shot()])
    assert [await port.message(UID, SID) for _ in range(3)] == [None, None, None]
    assert await DocumentTurns(lambda: None).message(UID, SID) is None


# ---- YouTube and Maps: outward words, behind the same guard ---------------------------------
class _Rows:
    def __init__(self, effect: Effect) -> None:
        self.effect = effect

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern="*", effect=self.effect, source="owner")]


def _media(guard: TurnGuard, rows: Effect | None = None) -> tuple[Gateway, FakeGoogleKeyAPIs]:
    fake = FakeGoogleKeyAPIs()
    client = GoogleKeyClient(SecretStr(KEY), http=fake.client())
    docs = MemoryDocs()
    ledger = QuotaLedger(docs)
    reg = ToolRegistry()
    for t in maps_tools(MapsService(client, ledger, MapsPlaces(docs)), guard) + youtube_tools(
        YouTubeService(client, ledger), guard
    ):
        reg.register(t)
    gw = Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=AuditLog(),
        rules=_Rows(rows) if rows is not None else None,
    )
    return gw, fake


CALLS = [
    ("youtube_search", {"query": f"{FACE} interview"}),
    ("youtube_search", {"query": FACE.lower()}),
    ("maps_search", {"query": f"{FACE} house"}),
    ("maps_search", {"query": "cafes", "near": f"{FACE}'s office"}),
    ("maps_route", {"from": "Kochi", "to": f"{FACE} residence"}),
]


@pytest.mark.parametrize(("tool", "args"), CALLS)
async def test_on_a_picture_turn_youtube_and_maps_send_no_name_from_a_face(
    tool: str, args: dict[str, Any]
) -> None:
    gw, fake = _media(_guard(Port(), None))
    with context_trust(untrusted=False, owner_text="who is this?"):
        res = await gw.execute(ToolCall(id="m1", name=tool, arguments=args), scope=f"{UID}:{SID}")
    assert res.outcome is GatewayOutcome.ERROR and WEB_REFUSED in (res.error or ""), res
    assert fake.requests == []


@pytest.mark.parametrize(("tool", "args"), CALLS)
async def test_with_ask_first_a_refused_one_never_becomes_a_card(
    tool: str, args: dict[str, Any]
) -> None:
    gw, fake = _media(_guard(Port(), None), rows=Effect.ASK)
    with context_trust(untrusted=False, owner_text="who is this?"):
        res = await gw.execute(ToolCall(id="m1", name=tool, arguments=args), scope=f"{UID}:{SID}")
    assert res.pending is None and WEB_REFUSED in (res.error or "") and fake.requests == []


@pytest.mark.parametrize(("tool", "args"), CALLS)
async def test_the_run_alone_still_refuses_when_no_look_up_ran(
    tool: str, args: dict[str, Any]
) -> None:
    from dataclasses import replace

    gw, fake = _media(_guard(Port(), None))
    found = gw.registry.get(tool)
    assert found is not None and found.preview is not None  # the look-up is wired
    alone = ToolRegistry()
    alone.register(replace(found, preview=None))  # as when an approved card runs later
    gw = Gateway(registry=alone, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    with context_trust(untrusted=False, owner_text="who is this?"):
        res = await gw.execute(ToolCall(id="m1", name=tool, arguments=args), scope=f"{UID}:{SID}")
    assert res.result == {"refused": True, "message": WEB_REFUSED, "spoken": WEB_REFUSED}
    assert fake.requests == []


@pytest.mark.parametrize(("tool", "args"), CALLS)
async def test_without_a_picture_they_go_out_unchanged(tool: str, args: dict[str, Any]) -> None:
    gw, fake = _media(_guard(Port(carried_answer="no"), None))
    with context_trust(untrusted=False, owner_text="who is this?"):
        res = await gw.execute(ToolCall(id="m1", name=tool, arguments=args), scope=f"{UID}:{SID}")
    assert res.outcome is GatewayOutcome.EXECUTED, res
    assert fake.requests


async def test_a_route_from_his_saved_home_needs_no_typed_word_for_home() -> None:
    gw, fake = _media(_guard(Port(), None))
    call = ToolCall(id="m1", name="maps_route", arguments={"from": "home", "to": "Kochi airport"})
    with context_trust(untrusted=False, owner_text="how long to kochi airport?"):
        res = await gw.execute(call, scope=f"{UID}:{SID}")
    assert WEB_REFUSED not in str(res.result) and WEB_REFUSED not in (res.error or "")


async def test_unwired_youtube_and_maps_fail_closed_inside_a_brain_turn() -> None:
    gw, fake = _media(None)  # type: ignore[arg-type]
    with context_trust(untrusted=False, owner_text="play something"):
        res = await gw.execute(
            ToolCall(id="m1", name="youtube_search", arguments={"query": FACE}),
            scope=f"{UID}:{SID}",
        )
    assert WEB_REFUSED in (res.error or "") and fake.requests == []


# ---- people research's context: searched with the name, so outward words too -----------------
async def test_research_person_s_context_carries_no_name_from_a_face() -> None:
    searcher = FakeSearcher([])
    svc = PeopleService(searcher, FakeModel(), mode=fixed_mode("ai"))
    reg = ToolRegistry()
    for t in people_tools(PeopleDeps(svc, pictures=_guard(Port(), None))):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    args = {"name": "Lekha Examplekar", "context": f"wife of {FACE}"}
    with context_trust(untrusted=False, owner_text="who is Lekha Examplekar?"):
        res = await gw.execute(
            ToolCall(id="p1", name=RESEARCH_PERSON, arguments=args), scope=f"{UID}:{SID}"
        )
    assert res.result == {"refused": True, "message": WEB_REFUSED, "spoken": WEB_REFUSED}
    assert searcher.queries == []
