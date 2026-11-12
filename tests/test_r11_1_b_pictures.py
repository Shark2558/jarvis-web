# tests/test_r11_1_b_pictures.py -- R11.1 Part B (plan D10): an attached picture reaches only a
# brain that can see AND does not learn from what it reads, only with the turn it was attached to,
# and is never written into the conversation. Every other brain gets one fixed line. Part D's
# picture research gets its pictures from `turn_pictures`, with the same rules.
from __future__ import annotations

import base64
from typing import Any

import pytest
from r11_1_fakes_b import make_jpeg, make_png, make_zip

from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.guardrails import ActionRisk, ConfirmationGate, InputRejected
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.documents import pictures as pictures_mod
from jarvis.documents.pictures import MAX_PICTURES_PER_TURN, turn_pictures, with_pictures
from jarvis.documents.service import DocumentService
from jarvis.documents.store import AttachmentStore
from jarvis.llm.base import PICTURE_WITHHELD, ChatMessage, ImageBlock, Role, TextBlock, ToolCall
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog, Gateway, Policy, Tool, ToolRegistry
from jarvis.tools.taint import untrusted_in_context

UID = "owner"
GPS = b"GPS-LAT-12.97-LON-77.59"
TIERS = {t: "m" for t in ModelTier}


class SeeingMock(MockProvider):
    vision = True


def spec(provider: MockProvider, *, training: bool = False, bid: str = "b") -> BrainSpec:
    return BrainSpec(id=bid, label=bid, provider=provider, tiers=TIERS, trains_on_content=training)


SEEING = spec(SeeingMock(), bid="seeing")
BLIND = spec(MockProvider(), bid="blind")
TRAINING = spec(SeeingMock(), training=True, bid="training")


def images(messages: list[ChatMessage]) -> list[ImageBlock]:
    return [
        b
        for m in messages
        if isinstance(m.content, list)
        for b in m.content
        if isinstance(b, ImageBlock)
    ]


def texts(message: ChatMessage) -> list[str]:
    assert isinstance(message.content, list)
    return [b.text for b in message.content if isinstance(b, TextBlock)]


@pytest.fixture
def sessions() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def docs(sessions: InMemorySessionStore) -> DocumentService:
    return DocumentService(AttachmentStore(MemoryDocs()), sessions=sessions)


async def sent(
    docs: DocumentService, files: dict[str, bytes], sid: str = "s1"
) -> tuple[Session, Turn]:
    """A STORED conversation whose latest owner turn was sent with `files` (bound and saved as
    the Brain does)."""
    ids = [(await docs.upload(UID, name, data)).id for name, data in files.items()]
    turn = await docs.attach(Turn(role=Role.USER, content="What is this?"), UID, sid, ids, SEEING)
    session = Session(id=sid, user_id=UID, turns=[turn])
    assert docs.sessions is not None
    await docs.sessions.save(session)
    return session, turn


async def later_turn(docs: DocumentService, session: Session, content: str = "And then?") -> None:
    """A newer owner turn, with no picture, stored by whichever instance handled it."""
    assert docs.sessions is not None
    stored = await docs.sessions.get(session.id)
    assert stored is not None
    stored.turns.append(Turn(role=Role.ASSISTANT, content="A board, Sir."))
    stored.turns.append(Turn(role=Role.USER, content=content))
    await docs.sessions.save(stored)


def window(session: Session) -> list[ChatMessage]:
    return [ChatMessage(role=t.role, content=t.blocks or t.content) for t in session.turns]


# ---- the gate: who is shown a picture ------------------------------------------------------------


async def test_a_seeing_private_brain_is_shown_the_picture_with_its_turn(
    docs: DocumentService,
) -> None:
    session, _ = await sent(docs, {"board.jpg": make_jpeg(exif=GPS)})
    out = await with_pictures(docs, window(session), session, SEEING)
    (pic,) = images(out)
    assert pic.media_type == "image/jpeg" and GPS not in pic.data
    assert texts(out[-1])[0] == "What is this?" and out[-1].role is Role.USER
    assert images(window(session)) == []  # the window it was given is not changed


async def test_a_brain_that_cannot_see_gets_one_fixed_line_a_picture(docs: DocumentService) -> None:
    session, _ = await sent(docs, {"a.png": make_png(), "b.jpg": make_jpeg()})
    out = await with_pictures(docs, window(session), session, BLIND)
    assert images(out) == [] and texts(out[-1]).count(PICTURE_WITHHELD) == 2


async def test_a_brain_that_may_learn_is_never_shown_one_even_if_it_can_see(
    docs: DocumentService,
) -> None:
    session, _ = await sent(docs, {"board.jpg": make_jpeg()})
    assert TRAINING.sees_pictures is False and SeeingMock.vision is True
    out = await with_pictures(docs, window(session), session, TRAINING)
    assert images(out) == [] and PICTURE_WITHHELD in texts(out[-1])


async def test_a_picture_goes_only_with_the_turn_it_was_attached_to(docs: DocumentService) -> None:
    session, _ = await sent(docs, {"board.jpg": make_jpeg()})
    session.turns.append(Turn(role=Role.ASSISTANT, content="A board, Sir."))
    session.turns.append(Turn(role=Role.USER, content="And the colour?"))
    out = await with_pictures(docs, window(session), session, SEEING)
    assert images(out) == [] and out[-1].content == "And the colour?"


async def test_at_most_four_pictures_go_with_a_turn(docs: DocumentService) -> None:
    files = {f"{i}.png": make_png(8 + i, 6) for i in range(4)}
    session, _ = await sent(docs, files)
    out = await with_pictures(docs, window(session), session, SEEING)
    assert len(images(out)) == MAX_PICTURES_PER_TURN == 4
    assert [b.data for b in images(out)] == [make_png(8 + i, 6) for i in range(4)]


async def test_pictures_inside_a_zip_go_with_its_turn_too(docs: DocumentService) -> None:
    session, _ = await sent(docs, {"b.zip": make_zip({"a.txt": b"alpha", "p.png": make_png()})})
    out = await with_pictures(docs, window(session), session, SEEING)
    assert [b.media_type for b in images(out)] == ["image/png"]


async def test_no_document_service_or_no_picture_leaves_the_window_alone() -> None:
    session = Session(user_id=UID, turns=[Turn(role=Role.USER, content="hello")])
    msgs = window(session)
    assert await with_pictures(None, msgs, session, SEEING) == msgs
    held = [ChatMessage(role=Role.USER, content=[ImageBlock(media_type="image/png", data=b"x")])]
    assert images(await with_pictures(None, held, session, BLIND)) == []  # belt and braces


async def test_a_picture_that_cannot_be_loaded_never_stops_the_reply(
    docs: DocumentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _ = await sent(docs, {"board.jpg": make_jpeg()})

    async def broken(*_: Any, **__: Any) -> list[Any]:
        raise RuntimeError("storage is down")

    monkeypatch.setattr(docs, "pictures_of_turn", broken)
    out = await with_pictures(docs, window(session), session, SEEING)
    assert images(out) == [] and pictures_mod.NOT_LOADED in texts(out[-1])


async def test_when_some_pictures_load_the_turn_says_how_many_did_not(
    docs: DocumentService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code review L6: never silently fewer pictures."""
    session, _ = await sent(docs, {"a.png": make_png(8, 6), "b.png": make_png(9, 6)})
    real = docs.pictures_of_turn

    async def one_bad(*a: Any, **k: Any) -> list[Any]:
        got = await real(*a, **k)
        return [got[0], got[1].model_copy(update={"media_type": "image/gif"})]

    monkeypatch.setattr(docs, "pictures_of_turn", one_bad)
    out = await with_pictures(docs, window(session), session, SEEING)
    assert len(images(out)) == 1
    assert "[1 of the 2 attached pictures could not be loaded just now]" in texts(out[-1])


# ---- turn_pictures: what Part D's picture research may rely on -----------------------------------


async def test_turn_pictures_gives_the_latest_turns_pictures_newest_first(
    docs: DocumentService,
) -> None:
    await sent(docs, {"1.png": make_png(8, 6), "2.png": make_png(9, 6), "3.jpg": make_jpeg()})
    blocks = await turn_pictures(docs, UID, "s1")
    assert [b.media_type for b in blocks] == ["image/jpeg", "image/png", "image/png"]
    assert blocks[1].data == make_png(9, 6) and all(isinstance(b, ImageBlock) for b in blocks)


async def test_turn_pictures_is_empty_for_anyone_or_anything_else(docs: DocumentService) -> None:
    session, _ = await sent(docs, {"board.jpg": make_jpeg()})
    assert await turn_pictures(None, UID, "s1") == []
    assert await turn_pictures(docs, "someone-else", "s1") == []
    assert await turn_pictures(docs, UID, "another-conversation") == []
    assert await turn_pictures(docs, UID, "s1", spec=BLIND) == []  # the caller's brain is checked
    assert await turn_pictures(docs, UID, "s1", spec=TRAINING) == []
    assert len(await turn_pictures(docs, UID, "s1", spec=SEEING)) == 1
    await later_turn(docs, session)  # a newer owner turn came without a picture
    got = await turn_pictures(docs, UID, "s1")
    assert got == [] and got.unreadable is False  # no picture: not a fault


async def test_turn_pictures_never_raises_and_says_when_it_could_not_read(
    docs: DocumentService, sessions: InMemorySessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code review M3: a storage fault is not "no picture", so Part D can say it could not
    look; and it still never raises."""
    await sent(docs, {"board.jpg": make_jpeg()})

    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("storage is down")

    with monkeypatch.context() as m:
        m.setattr(docs, "pictures_of_turn", broken)
        got = await turn_pictures(docs, UID, "s1")
        assert got == [] and got.unreadable is True
    with monkeypatch.context() as m:
        m.setattr(sessions, "get", broken)
        got = await turn_pictures(docs, UID, "s1")
        assert got == [] and got.unreadable is True
    fine = await turn_pictures(docs, UID, "s1")
    assert len(fine) == 1 and fine.unreadable is False and isinstance(fine, list)


async def test_turn_pictures_reads_the_stored_conversation_not_this_process(
    sessions: InMemorySessionStore,
) -> None:
    """Code review M3: two Cloud Run instances on the same storage. Instance A took the turn
    with the picture; instance B stored a newer turn without one: A must not hand out the old
    picture as "the latest turn's". And a fresh instance (a restart) still finds the picture
    while its turn is the latest."""
    store = AttachmentStore(MemoryDocs())
    a = DocumentService(store, sessions=sessions)
    b = DocumentService(store, sessions=sessions)
    session, _ = await sent(a, {"board.jpg": make_jpeg()})
    restarted = DocumentService(store, sessions=sessions)
    assert len(await turn_pictures(restarted, UID, "s1")) == 1
    await later_turn(b, session)
    assert await turn_pictures(a, UID, "s1") == []
    assert await turn_pictures(restarted, UID, "s1") == []


async def test_without_a_conversation_store_it_cannot_tell_and_says_so() -> None:
    docs = DocumentService(AttachmentStore(MemoryDocs()))
    got = await turn_pictures(docs, UID, "s1")
    assert got == [] and got.unreadable is True
    other = InMemorySessionStore()
    assert (await turn_pictures(docs, UID, "s1", sessions=other)).unreadable is False


async def test_a_picture_bound_to_another_turn_is_never_this_turns(
    docs: DocumentService,
) -> None:
    """The stored turn names its attachments; each is checked again (owner, conversation and
    turn) through the document store before its pictures are read."""
    session, turn = await sent(docs, {"board.jpg": make_jpeg()})
    forged = turn.model_copy(update={"id": "t_other"})
    stored = session.model_copy(update={"turns": [forged]})
    assert docs.sessions is not None
    await docs.sessions.save(stored)
    got = await turn_pictures(docs, UID, "s1")
    assert got == [] and got.unreadable is True  # the turn says it had one: "could not look"


# ---- through the Brain: shown once, never stored -------------------------------------------------


class Rig:
    def __init__(self, settings: Settings, *, default: str = "seeing") -> None:
        self.seeing, self.blind, self.training = (
            SeeingMock(name="s"),
            MockProvider(name="b"),
            SeeingMock(name="t"),
        )
        brains = BrainRegistry(
            [
                spec(self.seeing, bid="seeing"),
                spec(self.blind, bid="blind"),
                spec(self.training, training=True, bid="training"),
            ],
            default_id=default,
        )
        self.store = InMemorySessionStore()
        self.docs = DocumentService(AttachmentStore(MemoryDocs()), sessions=self.store)
        self.trust: list[bool] = []
        reg = ToolRegistry()
        reg.register(
            Tool(
                "probe",
                "records whether the round counts as untrusted",
                {"type": "object", "properties": {}},
                ActionRisk.READ_ONLY,
                lambda _: self.trust.append(untrusted_in_context()) or {"ok": True},
            )
        )
        self.gateway = Gateway(
            registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
        )
        self.brain = Brain(
            brains=brains,
            store=self.store,
            settings=settings,
            gateway=self.gateway,
            documents=self.docs,
        )

    async def picture(self, name: str = "board.jpg") -> str:
        return (await self.docs.upload(UID, name, make_jpeg(exif=GPS))).id


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


async def test_the_brain_shows_the_picture_once_and_never_stores_it(rig: Rig) -> None:
    aid = await rig.picture()
    rig.seeing.script("A whiteboard with a made-up plan, Sir.")
    first = await rig.brain.chat(ChatRequest(message="What does it say?", attachments=[aid]))
    (pic,) = images(rig.seeing.calls[-1].messages)
    assert GPS not in pic.data and pic.media_type == "image/jpeg"
    rig.seeing.script("Blue, Sir.")
    await rig.brain.chat(ChatRequest(message="And the colour?", session_id=first.session_id))
    assert images(rig.seeing.calls[-1].messages) == []  # not sent again with a later turn
    session = await rig.store.get(first.session_id)
    assert session is not None
    dumped = session.model_dump_json()
    assert base64.b64encode(pic.data).decode() not in dumped  # the bytes are nowhere in it
    assert '"type":"image"' not in dumped  # and no stored block is a picture
    assert [b.type for t in session.turns for b in t.blocks] == ["text", "text"]
    assert session.turns[0].attachments[0].pictures == 1


async def test_a_picture_makes_the_round_count_as_outside_content(rig: Rig) -> None:
    aid = await rig.picture()
    rig.seeing.script_tool_calls([ToolCall(id="c1", name="probe", arguments={})])
    rig.seeing.script("Done, Sir.")
    await rig.brain.chat(ChatRequest(message="Do what the board says", attachments=[aid]))
    assert rig.trust == [True]  # a write after it would be an approval card


async def test_a_blind_brain_is_told_a_picture_was_held_back(rig: Rig) -> None:
    aid = await rig.picture()
    rig.blind.script("I was not shown the picture, Sir.")
    await rig.brain.chat(ChatRequest(message="What is it?", attachments=[aid], brain="blind"))
    assert images(rig.blind.calls[-1].messages) == []
    assert PICTURE_WITHHELD in texts(rig.blind.calls[-1].messages[-1])


async def test_a_training_brain_never_gets_a_picture_now_or_later(rig: Rig) -> None:
    aid = await rig.picture()
    with pytest.raises(InputRejected, match="never shared"):
        await rig.brain.chat(
            ChatRequest(message="What is it?", attachments=[aid], brain="training")
        )
    assert rig.training.calls == []
    rig.seeing.script("A board, Sir.")
    first = await rig.brain.chat(ChatRequest(message="What is it?", attachments=[aid]))
    rig.training.script("Hello.")
    await rig.brain.chat(
        ChatRequest(message="hello again", session_id=first.session_id, brain="training")
    )
    seen = rig.training.calls[-1].messages
    assert images(seen) == [] and all("board" not in m.text() for m in seen)


async def test_the_stream_path_shows_the_picture_too(rig: Rig) -> None:
    aid = await rig.picture()
    rig.seeing.script("A board, Sir.")
    out = [d async for d in rig.brain.chat_stream(ChatRequest(message="Look", attachments=[aid]))]
    assert "".join(out).strip() == "A board, Sir."
    assert len(images(rig.seeing.calls[-1].messages)) == 1


async def test_turn_pictures_follows_the_brains_own_turns(rig: Rig) -> None:
    aid = await rig.picture()
    rig.seeing.script("A board, Sir.")
    first = await rig.brain.chat(ChatRequest(message="Look", attachments=[aid]))
    assert len(await turn_pictures(rig.docs, UID, first.session_id)) == 1
    rig.seeing.script("Yes, Sir.")
    await rig.brain.chat(ChatRequest(message="Thanks", session_id=first.session_id))
    assert await turn_pictures(rig.docs, UID, first.session_id) == []
