"""R18 C: the desk's WebSocket client (signed upgrade, message routing, outbox, reconnect with
backoff, the clock fix on 401, not-linked handling) with a fake connector, and the `websockets`
adapter against a real local server."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from email.utils import formatdate
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from jarvis.calldesk import client as cl
from jarvis.calldesk.credentials import CredentialStore, DeskCredentials, NotLinked, parse_link
from jarvis.calls import protocol as p
from jarvis.home import signing

SEED = bytes(range(32))
HOME = "h_0123abcd"
NOW = 1_800_000_000.0
FRAME = b"\x01\x00" * 320


def _creds() -> DeskCredentials:
    return DeskCredentials(HOME, signing.derive_keys(SEED))


class FakeConn:
    def __init__(self, incoming: list[Any]) -> None:
        self.incoming: asyncio.Queue[Any] = asyncio.Queue()
        for item in incoming:
            self.incoming.put_nowait(item)
        self.sent: list[str | bytes] = []
        self.closed = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        item = await self.incoming.get()
        if isinstance(item, cl.LinkClosed):
            raise item
        return item  # type: ignore[no-any-return]

    async def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.outbox: cl.DeskClient | None = None

    async def connected(self) -> None:
        self.events.append("connected")
        if self.outbox is not None:
            self.outbox.send(p.Hello(desk_version="18.0.0"))

    def disconnected(self) -> None:
        self.events.append("disconnected")

    async def handle(self, msg: Any) -> None:
        self.events.append(msg)
        if isinstance(msg, p.Ping) and self.outbox is not None:
            self.outbox.send_audio(p.pack_audio(p.AudioKind.THEM, FRAME))

    def jarvis_audio(self, pcm: bytes) -> None:
        self.events.append(("audio", len(pcm)))

    async def light_check(self) -> None:
        self.events.append("check")


class Rig:
    def __init__(self, script: list[Callable[[dict[str, str]], Any]], **kw: Any) -> None:
        self.script = list(script)
        self.headers: list[dict[str, str]] = []
        self.delays: list[float] = []
        self.stop = asyncio.Event()
        self.clock = NOW
        self.creds: DeskCredentials | None = _creds()
        self.client = cl.DeskClient(
            "wss://jarvis.example/v1/calls/desk/ws",
            lambda: self.creds,
            self.connect,
            clock=lambda: self.clock,
            sleep=self.sleep,
            rng=lambda: 0.5,
            **kw,
        )
        self.session = FakeSession()
        self.session.outbox = self.client

    async def connect(self, url: str, headers: dict[str, str]) -> cl.Connection:
        self.headers.append(headers)
        if not self.script:
            self.stop.set()
            raise cl.Refused(503)
        step = self.script.pop(0)
        result = step(headers)
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[no-any-return]

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)

    async def run(self) -> None:
        await asyncio.wait_for(self.client.run(self.session, self.stop), 5)


def _conn(*incoming: Any) -> Callable[[dict[str, str]], FakeConn]:
    conn = FakeConn([*incoming, cl.LinkClosed(1000)])
    return lambda headers: conn


def test_ws_url() -> None:
    assert cl.ws_url("https://jarvis.example") == "wss://jarvis.example/v1/calls/desk/ws"
    with pytest.raises(ValueError):
        cl.ws_url("http://jarvis.example")


async def test_the_upgrade_is_signed_with_the_home_up_key() -> None:
    rig = Rig([_conn()])
    await rig.run()
    header = rig.headers[0][signing.HEADER]
    signed = signing.parse(header)
    assert signed.home_id == HOME
    signing.verify(
        signed,
        signing.derive_keys(SEED),
        "up",
        method="GET",
        target=p.DESK_WS_PATH,
        body=b"",
        now=NOW,
        nonces=signing.NonceCache(),
    )


async def test_messages_flow_both_ways_and_bad_ones_are_ignored() -> None:
    holder: dict[str, FakeConn] = {}

    def step(headers: dict[str, str]) -> FakeConn:
        conn = FakeConn(
            [
                p.dump(p.Ping()),
                p.pack_audio(p.AudioKind.JARVIS, FRAME * 2),
                p.pack_audio(p.AudioKind.MIXED, FRAME),  # not for the desk
                "{not json",
                json.dumps({"type": "hello", "desk_version": "1.0.0"}),  # desk -> cloud only
                b"\x02\x00",  # not whole frames
                cl.LinkClosed(1000),
            ]
        )
        holder["conn"] = conn
        return conn

    rig = Rig([step])
    await rig.run()
    events = rig.session.events
    assert events[0] == "connected" and isinstance(events[1], p.Ping)
    assert events[2] == ("audio", 1280) and events[-1] == "disconnected"
    assert len(events) == 4
    sent = holder["conn"].sent
    assert p.parse_desk(sent[0]) == p.Hello(desk_version="18.0.0")
    assert sent[1] == p.pack_audio(p.AudioKind.THEM, FRAME)
    assert holder["conn"].closed


async def test_reconnects_with_a_growing_pause() -> None:
    rig = Rig([_conn(), _conn(), _conn()])
    await rig.run()
    assert rig.delays[:3] == [1.0, 2.0, 5.0]
    assert rig.session.events.count("connected") == 3


async def test_a_minute_online_resets_the_pause() -> None:
    class LongConn(FakeConn):
        async def recv(self) -> str | bytes:
            rig.clock += cl.STABLE_S + 1  # a minute online, then the link drops
            raise cl.LinkClosed(1006)

    def long_conn(headers: dict[str, str]) -> FakeConn:
        return LongConn([])

    rig = Rig([_conn(), long_conn])
    await rig.run()
    assert rig.delays[:2] == [1.0, 1.0]


async def test_jitter_stays_within_a_fifth() -> None:
    rig = Rig([])
    for r, want in ((0.0, 0.8), (1.0, 1.2), (0.5, 1.0)):

        def fixed(r: float = r) -> float:
            return r

        jittered = cl.DeskClient("wss://x", lambda: None, rig.connect, rng=fixed)
        assert jittered._backoff(0) == pytest.approx(want)


async def test_three_refusals_mean_not_linked_and_a_slow_retry() -> None:
    rig = Rig([lambda h: cl.Unauthorized(None)] * 3 + [_conn()])
    await rig.run()
    assert rig.delays[:3] == [1.0, 2.0, cl.NOT_LINKED_RETRY_S]
    assert rig.client.linked  # the fourth try got in


async def test_a_skewed_clock_is_fixed_from_the_date_header_and_retried_at_once() -> None:
    server_now = NOW + 600
    rig = Rig([lambda h: cl.Unauthorized(formatdate(server_now, usegmt=True)), _conn()])
    await rig.run()
    assert len(rig.headers) >= 2 and rig.delays[0] == 1.0  # the retry came before any pause
    assert signing.parse(rig.headers[1][signing.HEADER]).t == int(server_now)
    assert rig.client.offset_s == pytest.approx(600)


async def test_close_codes_choose_the_pause() -> None:
    rig = Rig([_conn_closing(p.WS_NOT_BUILT), _conn_closing(p.WS_UNAUTHORIZED)])
    await rig.run()
    assert rig.delays[:2] == [cl.NOT_BUILT_RETRY_S, cl.NOT_LINKED_RETRY_S]


def _conn_closing(code: int) -> Callable[[dict[str, str]], FakeConn]:
    conn = FakeConn([cl.LinkClosed(code)])
    return lambda headers: conn


async def test_silence_from_the_cloud_means_reconnect() -> None:
    rig = Rig([lambda h: FakeConn([])], idle_timeout_s=0.01)
    await rig.run()
    assert rig.session.events == ["connected", "disconnected"]


async def test_unreachable_cloud_backs_off() -> None:
    rig = Rig([lambda h: OSError("no route"), lambda h: TimeoutError(), _conn()])
    await rig.run()
    assert rig.delays[:2] == [1.0, 2.0]


async def test_no_credentials_waits_and_says_not_linked() -> None:
    rig = Rig([])
    rig.creds = None

    async def sleep(seconds: float) -> None:
        rig.delays.append(seconds)
        rig.stop.set()

    rig.client._sleep = sleep
    await rig.run()
    assert rig.delays == [cl.NOT_LINKED_RETRY_S] and not rig.client.linked


async def test_the_periodic_check_runs_while_connected() -> None:
    conn = FakeConn([])
    rig = Rig([lambda h: conn], check_every_s=0.01)
    task = asyncio.ensure_future(rig.run())
    await asyncio.sleep(0.05)
    conn.incoming.put_nowait(cl.LinkClosed(1000))
    await task
    assert "check" in rig.session.events


async def test_offline_messages_are_dropped_and_a_full_outbox_drops_audio_first() -> None:
    rig = Rig([])
    rig.client.send(p.Hello(desk_version="18.0.0"))  # offline: nothing queued, nothing raised
    rig.client._queue = asyncio.Queue(maxsize=3)
    audio = p.pack_audio(p.AudioKind.THEM, FRAME)
    for _ in range(3):
        rig.client.send_audio(audio)
    rig.client.send_audio(audio)  # full: more audio is dropped
    rig.client.send(p.Vad(call_id="call_0000000000a1", speaking=False))  # control: makes room
    queued = [rig.client._queue.get_nowait() for _ in range(3)]
    assert queued[:2] == [audio, audio] and isinstance(queued[2], str)


async def test_stop_ends_the_loop_and_closes_the_link() -> None:
    conn = FakeConn([])
    rig = Rig([lambda h: conn])
    task = asyncio.ensure_future(rig.run())
    await asyncio.sleep(0.02)
    rig.stop.set()
    await task
    assert conn.closed and rig.session.events[-1] == "disconnected"


# ---- credentials -------------------------------------------------------------------------------


def test_save_and_load_the_desks_link(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "secret.json")
    assert store.load() is None
    store.save(HOME, SEED)
    loaded = store.load()
    assert loaded is not None and loaded.desk_id == HOME
    assert loaded.keys.up == signing.derive_keys(SEED).up
    assert HOME in repr(loaded) and "seed" not in repr(loaded)
    store.forget()
    assert store.load() is None


def test_link_answers_in_either_base64() -> None:
    url = base64.urlsafe_b64encode(SEED).decode().rstrip("=")
    assert parse_link({"desk_id": HOME, "seed": url}) == (HOME, SEED)
    std = base64.b64encode(SEED).decode()
    assert parse_link({"home_id": HOME, "seed": std}) == (HOME, SEED)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"desk_id": "nope", "seed": base64.b64encode(SEED).decode()},
        {"desk_id": HOME, "seed": base64.b64encode(b"short").decode()},
        {"desk_id": HOME, "seed": "!!!"},
        {"desk_id": HOME, "seed": 7},
    ],
)
def test_anything_else_is_not_a_link(data: dict[str, Any]) -> None:
    with pytest.raises(NotLinked):
        parse_link(data)


def test_an_unreadable_secret_means_not_linked(tmp_path: Path) -> None:
    path = tmp_path / "secret.json"
    path.write_text("garbage", encoding="utf-8")
    assert CredentialStore(path).load() is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert CredentialStore(path).load() is None


# ---- the websockets adapter against a real local server ----------------------------------------


async def test_websockets_adapter_round_trip_and_close_codes() -> None:
    pytest.importorskip("websockets")
    from websockets.asyncio.server import serve

    from jarvis.calldesk import wsconn

    seen: dict[str, Any] = {}

    async def handler(ws: Any) -> None:
        seen["header"] = ws.request.headers.get(signing.HEADER)
        seen["agent"] = ws.request.headers.get("User-Agent")
        await ws.send(p.dump(p.Ping()))
        seen["got"] = await ws.recv()
        await ws.send(p.pack_audio(p.AudioKind.JARVIS, FRAME))
        await ws.close(p.WS_NOT_BUILT, "not built")

    def process_request(connection: Any, request: Any) -> Any:
        if request.headers.get(signing.HEADER) is None:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "no\n")
        return None

    async with serve(handler, "127.0.0.1", 0, process_request=process_request) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}/v1/calls/desk/ws"
        conn = await wsconn.connect(url, _creds().upgrade_headers(NOW))
        assert p.parse_cloud_to_desk(await conn.recv()) == p.Ping()
        await conn.send(p.dump(p.Hello(desk_version="18.0.0")))
        assert await conn.recv() == p.pack_audio(p.AudioKind.JARVIS, FRAME)
        with pytest.raises(cl.LinkClosed) as closed:
            await conn.recv()
        assert closed.value.code == p.WS_NOT_BUILT
        await conn.close()
        assert seen["header"].startswith("v1;h=h_0123abcd;")
        assert seen["agent"].startswith("JARVIS-CallDesk/")
        assert p.parse_desk(seen["got"]) == p.Hello(desk_version="18.0.0")
        with pytest.raises(cl.Unauthorized) as refused:
            await wsconn.connect(url, {})
        assert refused.value.date  # the server's Date header, for the clock fix
