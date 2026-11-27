"""R18 A2: the call hub and its two sockets (BUILD-BRIEF row A2 item 2; I0-SEAMS.md).

The desk socket is checked before `accept` with the home bridge's signing (the desk's own linked
seed); the live socket carries the owner's controls. A fake WebSocket keeps every test on one
event loop. Also: linking the desk, one call at a time, phone events, answering missed calls, and
the billing-backed meter.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Sequence
from typing import Any

import pytest
from calls_a2_fakes import (
    NOW,
    UID,
    card,
    frames,
    phone_event,
    registry,
    rig,
)
from starlette.datastructures import URL, Headers, QueryParams

from jarvis.api.calls_ws import AUDIO_FRAMES_PER_S, TELLS_PER_MINUTE, CallSockets
from jarvis.billing import Billing, BudgetStore, FxRates, UsageMeter
from jarvis.calls.hub import (
    BillingSpend,
    CallHub,
    DeskConnection,
    DeskDoorService,
    DeskStore,
    deps_factory,
)
from jarvis.calls.models import CallSettings, CallState, SpeechOption
from jarvis.calls.ports import CallsRefused
from jarvis.calls.prices import SpeechPrice
from jarvis.calls.protocol import (
    DESK_WS_PATH,
    WS_BAD_MESSAGE,
    WS_GONE,
    WS_UNAUTHORIZED,
    AudioKind,
    pack_audio,
)
from jarvis.home import signing
from jarvis.llm.base import Completion, Usage
from jarvis.storage.docs import MemoryDocs


class Cipher:
    def encrypt(self, plaintext: bytes, *, aad: str) -> str:
        return aad + "|" + bytes(b ^ 0x5A for b in plaintext).hex()

    def decrypt(self, blob: str, *, aad: str) -> bytes:
        head, _, body = blob.partition("|")
        if head != aad:
            raise ValueError("wrong owner")
        return bytes(b ^ 0x5A for b in bytes.fromhex(body))


class FakeWS:
    def __init__(self, headers: Sequence[tuple[str, str]] = (), query: str = "") -> None:
        self.headers = Headers(raw=[(k.lower().encode(), v.encode()) for k, v in headers])
        self.url = URL("ws://jarvis.test" + DESK_WS_PATH + (f"?{query}" if query else ""))
        self.query_params = QueryParams(query)
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.texts: list[dict[str, Any]] = []
        self.binary: list[bytes] = []
        self.accepted = False
        self.closed: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict[str, Any]:
        return await self.inbox.get()

    async def send_text(self, data: str) -> None:
        self.texts.append(json.loads(data))

    async def send_bytes(self, data: bytes) -> None:
        self.binary.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = code
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": code})

    def text(self, msg: dict[str, Any]) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "text": json.dumps(msg)})

    def data(self, raw: bytes) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": raw})

    def types(self) -> list[str]:
        return [str(t.get("type")) for t in self.texts]


class Answering:
    def __init__(self, yes: bool = True) -> None:
        self.yes = yes
        self.asked: list[tuple[str, int]] = []

    async def should_answer(
        self, uid: str, number_e164: str, rings: int, settings: CallSettings
    ) -> bool:
        self.asked.append((number_e164, rings))
        return self.yes


async def spin(n: int = 200) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def linked_world(**kw: Any) -> tuple[Any, CallHub, DeskStore, CallSockets, str, bytes]:
    r = rig(**kw)
    hub = CallHub(deps_factory(r.deps), r.store, answering=Answering(), clock=r.clock)
    desks = DeskStore(MemoryDocs(), Cipher(), clock=lambda: NOW.timestamp())
    door = DeskDoorService(desks, hub, clock=lambda: NOW.timestamp())
    code = (await door.code(UID))["code"]
    got = await door.link({"code": code, "desk_version": "18.0.0"})
    seed = base64.urlsafe_b64decode(got["seed"] + "=")
    sockets = CallSockets(hub, desks, clock=lambda: NOW.timestamp(), hello_s=0.2, ping_s=3600)
    return r, hub, desks, sockets, got["desk_id"], seed


def signed(desk_id: str, seed: bytes, *, target: str = DESK_WS_PATH, nonce: str | None = None):
    header = signing.sign(
        signing.derive_keys(seed),
        "up",
        home_id=desk_id,
        method="GET",
        target=target,
        body=b"",
        now=NOW.timestamp(),
        nonce=nonce,
    )
    return [(signing.HEADER, header)]


async def open_desk(sockets: CallSockets, desk_id: str, seed: bytes) -> tuple[FakeWS, Any]:
    ws = FakeWS(signed(desk_id, seed))
    task = asyncio.create_task(sockets.desk(ws))  # type: ignore[arg-type]
    ws.text({"type": "hello", "desk_version": "18.0.0"})
    ws.text(
        {"type": "state", "ready": True, "bt_headset": False, "cable": True, "phone_link": True}
    )
    await spin()
    return ws, task


# ---- linking the desk --------------------------------------------------------------------------
async def test_a_desk_links_once_with_its_code_and_the_seed_is_sealed() -> None:
    r = rig()
    hub = CallHub(deps_factory(r.deps), r.store)
    docs = MemoryDocs()
    desks = DeskStore(docs, Cipher(), clock=lambda: NOW.timestamp())
    door = DeskDoorService(desks, hub, clock=lambda: NOW.timestamp())
    code = (await door.code(UID))["code"]
    assert len(code) == 9 and code[4] == "-"
    got = await door.link({"code": code.lower(), "desk_version": "18.0.0"})
    assert got["desk_id"].startswith("h_") and got["ws_path"] == DESK_WS_PATH
    stored = await docs.get(f"jarvis_call_desk/{UID}")
    assert stored is not None and got["seed"] not in json.dumps(stored)
    with pytest.raises(CallsRefused) as again:
        await door.link({"code": code, "desk_version": "18.0.0"})
    assert again.value.code == "bad_code"
    rec = await desks.find(got["desk_id"])
    assert rec is not None and rec.uid == UID


@pytest.mark.parametrize(
    "body",
    [{"code": "ZZZZ-ZZZZ", "desk_version": "18.0.0"}, {"code": 5, "desk_version": "18.0.0"}],
)
async def test_a_wrong_code_links_nothing(body: dict[str, Any]) -> None:
    r = rig()
    desks = DeskStore(MemoryDocs(), Cipher())
    door = DeskDoorService(desks, CallHub(deps_factory(r.deps), r.store))
    await door.code(UID)
    with pytest.raises(CallsRefused):
        await door.link(body)
    assert await desks.load(UID) is None


async def test_a_bad_version_is_refused_before_the_code_is_looked_at() -> None:
    r = rig()
    door = DeskDoorService(
        DeskStore(MemoryDocs(), Cipher()), CallHub(deps_factory(r.deps), r.store)
    )
    with pytest.raises(CallsRefused) as bad:
        await door.link({"code": "ABCD-EFGH", "desk_version": "x"})
    assert bad.value.status == 422


async def test_unlink_closes_the_desk_socket() -> None:
    r, hub, desks, sockets, desk_id, seed = await linked_world()
    ws, task = await open_desk(sockets, desk_id, seed)
    assert hub.desk(UID) is not None and hub.desk(UID).is_ready()  # type: ignore[union-attr]
    door = DeskDoorService(desks, hub)
    assert (await door.unlink(UID))["unlinked"] is True
    await asyncio.wait_for(task, 1)
    assert ws.closed == 4401 and hub.desk(UID) is None
    assert await desks.find(desk_id) is None


# ---- the desk socket's checks ------------------------------------------------------------------
async def test_an_unsigned_desk_is_refused_before_accept() -> None:
    _, _, _, sockets, _, _ = await linked_world()
    ws = FakeWS()
    await sockets.desk(ws)  # type: ignore[arg-type]
    assert ws.closed == WS_UNAUTHORIZED and not ws.accepted


async def test_a_desk_signed_with_another_key_is_refused() -> None:
    _, _, _, sockets, desk_id, _ = await linked_world()
    ws = FakeWS(signed(desk_id, b"\x01" * 32))
    await sockets.desk(ws)  # type: ignore[arg-type]
    assert ws.closed == WS_UNAUTHORIZED and not ws.accepted


async def test_a_replayed_handshake_is_refused() -> None:
    _, _, _, sockets, desk_id, seed = await linked_world()
    headers = signed(desk_id, seed)
    first = FakeWS(headers)
    task = asyncio.create_task(sockets.desk(first))  # type: ignore[arg-type]
    await spin(20)
    again = FakeWS(headers)
    await sockets.desk(again)  # type: ignore[arg-type]
    assert again.closed == WS_UNAUTHORIZED
    await first.close(1000)
    await asyncio.wait_for(task, 1)


async def test_a_query_string_is_refused() -> None:
    _, _, _, sockets, desk_id, seed = await linked_world()
    ws = FakeWS(signed(desk_id, seed), query="x=1")
    await sockets.desk(ws)  # type: ignore[arg-type]
    assert ws.closed == WS_UNAUTHORIZED


async def test_a_desk_that_never_says_hello_is_closed() -> None:
    _, hub, _, sockets, desk_id, seed = await linked_world()
    ws = FakeWS(signed(desk_id, seed))
    await asyncio.wait_for(sockets.desk(ws), 2)  # type: ignore[arg-type]
    assert ws.accepted and ws.closed == WS_BAD_MESSAGE and hub.desk(UID) is None


async def test_bad_messages_close_the_desk_after_the_limit() -> None:
    _, hub, _, sockets, desk_id, seed = await linked_world()
    ws, task = await open_desk(sockets, desk_id, seed)
    for _ in range(25):
        ws.inbox.put_nowait({"type": "websocket.receive", "text": "{not json"})
    await asyncio.wait_for(task, 1)
    assert ws.closed == WS_BAD_MESSAGE and hub.desk(UID) is None


async def test_a_newer_desk_socket_replaces_the_older() -> None:
    _, hub, _, sockets, desk_id, seed = await linked_world()
    first, t1 = await open_desk(sockets, desk_id, seed)
    second = FakeWS(signed(desk_id, seed, nonce=signing.new_nonce()))
    t2 = asyncio.create_task(sockets.desk(second))  # type: ignore[arg-type]
    second.text({"type": "hello", "desk_version": "18.0.0"})
    await spin()
    assert first.closed == 4409
    await asyncio.wait_for(t1, 1)
    assert hub.desk(UID) is not None
    await second.close(1000)
    await asyncio.wait_for(t2, 1)


# ---- a whole call through the hub and both sockets ---------------------------------------------
async def test_a_call_through_the_desk_socket_the_phone_and_a_live_listener() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    r.provider.say("Hello, I am calling to book a laundry pickup.")
    r.provider.say("Thank you, goodbye.", action="end")
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    c = card()
    record = await hub.start_outgoing(UID, c, "appr_12345678")
    await spin()
    assert desk.types()[-1] == "prepare"
    desk.text({"type": "mic", "call_id": record.id, "owner_mic": False})
    await spin()
    assert r.phone.types() == ["call.dial"]
    with pytest.raises(CallsRefused) as busy:
        await hub.start_outgoing(UID, c, "appr_12345678")
    assert busy.value.status == 409
    live = FakeWS(query="device=phone")
    live_task = asyncio.create_task(sockets.live(live, UID, record.id))  # type: ignore[arg-type]
    await spin()
    live.text({"type": "listen", "audio": True})
    await hub.phone_event(UID, phone_event("active", record.id))
    await spin(400)
    assert desk.binary and desk.binary[0][0] == AudioKind.JARVIS
    r.speech.hear.script.append(("en-IN", "Okay, thanks."))
    desk.text({"type": "vad", "call_id": record.id, "speaking": True})
    desk.data(pack_audio(AudioKind.THEM, frames(25)))
    desk.text({"type": "vad", "call_id": record.id, "speaking": False})
    await spin(600)
    session = hub.session(UID, record.id)
    if session is not None:
        session.pump_audio()
        await session.done.wait()
    await spin(200)
    assert r.phone.types()[-1] == "call.end"
    assert desk.types()[-1] == "release"
    states = [t for t in live.texts if t.get("type") == "state"]
    assert states[0]["state"] in ("dialing", "preparing")
    assert states[-1]["state"] == "ended"
    assert any(t.get("type") == "caption" and t.get("text") == "Okay, thanks." for t in live.texts)
    await asyncio.wait_for(live_task, 2)
    assert hub.session(UID, record.id) is None and hub.active(UID) is None
    await desk.close(1000)
    await asyncio.wait_for(desk_task, 1)


async def test_live_controls_takeover_on_the_phone_tell_and_hangup() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    r.provider.say("Hello.")
    r.provider.say("Saturday then?")
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    record = await hub.start_outgoing(UID, card(), "appr_12345678")
    await spin()
    desk.text({"type": "mic", "call_id": record.id, "owner_mic": False})
    await spin()
    await hub.phone_event(UID, phone_event("active", record.id))
    await spin(400)
    live = FakeWS(query="device=phone")
    live_task = asyncio.create_task(sockets.live(live, UID, record.id))  # type: ignore[arg-type]
    await spin()
    for _ in range(TELLS_PER_MINUTE + 3):
        live.text({"type": "tell", "text": "Ask for Saturday"})
    await spin(600)
    session = hub.session(UID, record.id)
    assert session is not None and len(session.owner_lines) == TELLS_PER_MINUTE
    live.text({"type": "takeover"})
    await spin(400)
    assert session.state is CallState.TAKEN_OVER
    assert r.phone.sent[-1].type == "call.route"
    live.text({"type": "hangup"})
    await asyncio.wait_for(session.done.wait(), 2)
    await asyncio.wait_for(live_task, 2)
    await desk.close(1000)
    await asyncio.wait_for(desk_task, 1)


async def test_a_listener_for_someone_elses_call_is_gone() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    record = await hub.start_outgoing(UID, card(), "appr_12345678")
    await spin()
    other = FakeWS()
    await sockets.live(other, "u_stranger", record.id)  # type: ignore[arg-type]
    assert other.closed == WS_GONE and not other.accepted
    nobody = FakeWS()
    await sockets.live(nobody, UID, "call_000000000000")  # type: ignore[arg-type]
    assert nobody.closed == WS_GONE
    await hub.aclose()
    await asyncio.wait_for(desk_task, 1)


async def test_bad_live_messages_close_the_listener() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    record = await hub.start_outgoing(UID, card(), "appr_12345678")
    await spin()
    live = FakeWS()
    task = asyncio.create_task(sockets.live(live, UID, record.id))  # type: ignore[arg-type]
    await spin()
    for _ in range(8):
        live.text({"type": "transfer_money"})
    await asyncio.wait_for(task, 2)
    assert live.closed == WS_BAD_MESSAGE
    await hub.aclose()
    await asyncio.wait_for(desk_task, 1)


async def test_audio_floods_are_dropped() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    got: list[int] = []

    class Session:
        def on_audio(self, pcm: bytes) -> None:
            got.append(len(pcm) // 640)

        def on_desk_lost(self) -> None:
            return None

    hub.active = lambda uid: Session()  # type: ignore[assignment,method-assign,return-value]
    for _ in range(5):
        desk.data(pack_audio(AudioKind.THEM, frames(50)))
    await spin()
    assert sum(got) <= AUDIO_FRAMES_PER_S
    desk.data(pack_audio(AudioKind.JARVIS, frames(1)))  # a desk never sends JARVIS's voice
    await spin()
    await desk.close(1000)
    await asyncio.wait_for(desk_task, 1)


async def test_a_desk_lost_mid_call_ends_it_after_the_grace() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    r.provider.say("Hello.")
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    record = await hub.start_outgoing(UID, card(), "appr_12345678")
    await spin()
    desk.text({"type": "mic", "call_id": record.id, "owner_mic": False})
    await spin()
    await hub.phone_event(UID, phone_event("active", record.id))
    await spin(400)
    await desk.close(1000)
    await asyncio.wait_for(desk_task, 1)
    session = hub.session(UID, record.id)
    assert session is not None
    await asyncio.wait_for(session.done.wait(), 2)
    assert session.outcome == "desk_dropped"


# ---- phone events and answering ----------------------------------------------------------------
async def test_a_missed_call_is_answered_only_when_switched_on_and_after_n_rings() -> None:
    r, hub, _, sockets, desk_id, seed = await linked_world()
    policy = Answering(yes=True)
    hub._answering = policy
    desk, desk_task = await open_desk(sockets, desk_id, seed)
    ringing = phone_event("ringing", None, number_e164="+919000000005", rings=6)
    await hub.phone_event(UID, ringing)
    assert hub.active(UID) is None and policy.asked == []  # answering is off by default
    await r.store.save_settings(UID, {"answering_on": True, "answer_after_rings": 5})
    await hub.phone_event(UID, phone_event("ringing", None, number_e164="+919000000005", rings=4))
    assert hub.active(UID) is None
    await hub.phone_event(UID, ringing)
    await spin()
    session = hub.active(UID)
    assert session is not None and session.card is None
    desk.text({"type": "mic", "call_id": session.call_id, "owner_mic": False})
    await spin()
    assert r.phone.types() == ["call.answer"]
    await hub.aclose()
    await asyncio.wait_for(desk_task, 1)


async def test_a_declined_ringing_call_is_asked_about_once() -> None:
    r, hub, _, _, _, _ = await linked_world()
    policy = Answering(yes=False)
    hub._answering = policy
    await r.store.save_settings(UID, {"answering_on": True})
    ring = phone_event("ringing", None, number_e164="+919000000005", rings=5)
    await hub.phone_event(UID, ring)
    await hub.phone_event(UID, ring.model_copy(update={"rings": 6}))
    assert len(policy.asked) == 1 and hub.active(UID) is None
    await hub.phone_event(UID, phone_event("ended", None))
    await hub.phone_event(UID, ring)
    assert len(policy.asked) == 2


async def test_desk_connection_sends_are_framed_and_fail_closed() -> None:
    ws = FakeWS()
    conn = DeskConnection(UID, ws)  # type: ignore[arg-type]
    await conn.send_audio(frames(2))
    assert ws.binary[0][0] == AudioKind.JARVIS and len(ws.binary[0]) == 1 + 1280
    assert not conn.is_ready()

    class Broken(FakeWS):
        async def send_text(self, data: str) -> None:
            raise RuntimeError("gone")

    broken = DeskConnection(UID, Broken())  # type: ignore[arg-type]
    from jarvis.calls.protocol import Ping  # noqa: PLC0415

    with pytest.raises(ConnectionError):
        await broken.send(Ping())
    assert not broken.open


# ---- metering ----------------------------------------------------------------------------------
def _prices(rate: float) -> dict[SpeechOption, SpeechPrice]:
    return {
        SpeechOption.LAPTOP: SpeechPrice(SpeechOption.LAPTOP, 0.0, 0.0, can_bill=False),
        SpeechOption.GOOGLE: SpeechPrice(
            SpeechOption.GOOGLE, 2.29, 2.86, hear_free_seconds=60, voice_free_chars=100
        ),
        SpeechOption.AZURE: SpeechPrice(SpeechOption.AZURE, 0.0, 0.0, can_bill=False),
        SpeechOption.BHASHINI: SpeechPrice(SpeechOption.BHASHINI, None, None),
        SpeechOption.SARVAM: SpeechPrice(SpeechOption.SARVAM, 0.5, 3.0, paid=True),
    }


def _billing() -> tuple[Billing, Any]:
    from calls_a2_fakes import RoutedProvider  # noqa: PLC0415

    brains = registry(RoutedProvider())
    docs = MemoryDocs()
    billing = Billing(
        fx=FxRates(docs=None, http=None, default_rate=95.24),
        meter=UsageMeter(docs, tz="Asia/Kolkata"),
        budgets=BudgetStore(docs),
        brains=brains,
        clock=lambda: NOW,
    )
    return billing, brains


async def test_speech_is_free_inside_the_allowance_and_priced_above_it() -> None:
    billing, brains = _billing()
    spend = BillingSpend(billing, _prices, brains.default)
    assert await spend.speech(UID, "google", "hear", 30) == 0.0
    above = await spend.speech(UID, "google", "hear", 60)  # 30 s over the free 60
    assert above == pytest.approx(2.29 / 2, rel=0.01)
    assert await spend.speech(UID, "laptop", "hear", 600) == 0.0
    assert await spend.speech(UID, "azure", "voice", 10_000) == 0.0
    assert await spend.speech(UID, "sarvam", "hear", 60) == pytest.approx(0.5, rel=0.01)


async def test_an_unknown_speech_price_is_never_free() -> None:
    billing, brains = _billing()
    spend = BillingSpend(billing, _prices, brains.default)
    assert await spend.speech(UID, "bhashini", "hear", 60) > 0
    assert await spend.speech(UID, "nobody", "voice", 1000) > 0


async def test_model_calls_are_metered_and_the_owners_limit_is_checked() -> None:
    billing, brains = _billing()
    spend = BillingSpend(billing, _prices, brains.default)
    done = Completion(
        text="x",
        model="claude-haiku-5-5",
        provider="anthropic",
        usage=Usage(input_tokens=1000, output_tokens=100),
        latency_ms=1,
    )
    inr = await spend.model(UID, "anthropic", done)
    assert inr > 0
    assert await spend.allowed(UID)
    from jarvis.billing.budget import BudgetPatch  # noqa: PLC0415

    await billing.set_limit(UID, BudgetPatch(monthly_limit_inr=1))
    assert await spend.allowed(UID)
    await billing.record(UID, "anthropic", 0.02)  # about ₹1.90
    assert not await spend.allowed(UID)
