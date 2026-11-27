# src/jarvis/api/calls_ws.py
"""R18 A2: the two call sockets behind I0's routes (`app.state.calls_sockets`, `CallsSockets`).

`GET /v1/calls/desk/ws`, the call desk (one per owner; Layer 6). Checked BEFORE `accept`, with
nothing read: no query string; exactly one `X-Jarvis-Home` header in the v1 shape signed with the
desk's UP key over `GET /v1/calls/desk/ws` and an empty body (`jarvis.home.signing`: the desk id
known, |now - t| <= 60 s, the nonce not seen in 5 minutes, `hmac.compare_digest`, then the nonce
remembered). Any failure: closed 4401 before the handshake completes, logged by check name only.
Then the desk has `HELLO_S` to say `hello`; after it, desk messages and 0x01 audio flow to the
owner's call (`CallHub`), at most `AUDIO_FRAMES_PER_S` frames a second (a flood is dropped), and
`MAX_BAD` malformed messages close it (4400). The cloud pings every `PING_S`.

`GET /v1/calls/{call_id}/live`, a live listener (Layer 1). I0's route has already checked the
owner (bearer, or his session cookie from JARVIS's own origin); here the call must be his and
running (else 4404). Client messages: `listen {audio}`, `takeover`, `tell {text}` (at most
`TELLS_PER_MINUTE`), `hangup`. `?device=phone` (the console page in the phone's browser) makes a
takeover move the call's sound to the phone (`call.route`). No audio or text is ever logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

from jarvis.calls.hub import CallHub, DeskConnection, DeskRecord, DeskStore
from jarvis.calls.live import LiveListener
from jarvis.calls.protocol import (
    DESK_WS_PATH,
    FRAME_BYTES,
    WS_BAD_MESSAGE,
    WS_GONE,
    WS_UNAUTHORIZED,
    AudioKind,
    DeskError,
    DeskState,
    DtmfDone,
    Hangup,
    HeardText,
    Hello,
    Listen,
    LiveTakeover,
    Mic,
    Ping,
    Played,
    ProtocolError,
    Tell,
    Vad,
    parse_desk,
    parse_live_client,
    unpack_audio,
)
from jarvis.home import signing
from jarvis.logging import get_logger

log = get_logger(__name__)

HELLO_S = 10.0
PING_S = 15.0
MAX_BAD = 20
MAX_BAD_LIVE = 5
AUDIO_FRAMES_PER_S = 150  # 3 x real time: room for a burst after a network stall
TELLS_PER_MINUTE = 10


class _Unauthorized(Exception):
    def __init__(self, check: str) -> None:
        super().__init__(check)
        self.check = check


class CallSockets:
    def __init__(
        self,
        hub: CallHub,
        desks: DeskStore,
        *,
        clock: Callable[[], float] = time.time,
        hello_s: float = HELLO_S,
        ping_s: float = PING_S,
    ) -> None:
        self._hub = hub
        self._desks = desks
        self._clock = clock
        self._nonces = signing.NonceCache()
        self._hello_s = hello_s
        self._ping_s = ping_s

    # ---- the desk ------------------------------------------------------------------------------
    async def _check(self, ws: WebSocket) -> DeskRecord:
        if ws.url.query:
            raise _Unauthorized("query")
        values = ws.headers.getlist(signing.HEADER)
        if len(values) != 1:
            raise _Unauthorized("shape")
        try:
            signed = signing.parse(values[0])
            record = await self._desks.find(signed.home_id)
            if record is None:
                raise signing.SignatureError("shape")
            signing.verify(
                signed,
                record.keys(),
                "up",
                method="GET",
                target=DESK_WS_PATH,
                body=b"",
                now=self._clock(),
                nonces=self._nonces,
            )
        except signing.SignatureError as exc:
            raise _Unauthorized(exc.check) from None
        return record

    async def desk(self, ws: WebSocket) -> None:
        try:
            record = await self._check(ws)
        except _Unauthorized as exc:
            log.info("call desk refused", extra={"check": exc.check})
            await ws.close(code=WS_UNAUTHORIZED)
            return
        except Exception as exc:  # noqa: BLE001 - the store is down: no desk now
            log.error("call desk check failed", extra={"error": type(exc).__name__})
            await ws.close(code=1011)
            return
        await ws.accept()
        conn = DeskConnection(record.uid, ws)
        try:
            hello = await asyncio.wait_for(self._hello(ws), self._hello_s)
        except (TimeoutError, ProtocolError, ConnectionError):
            await conn.close(WS_BAD_MESSAGE)
            return
        conn.hello = hello
        await self._hub.desk_joined(conn)
        log.info("call desk connected", extra={"version": hello.desk_version})
        pinger = asyncio.ensure_future(self._ping(conn))
        try:
            await self._desk_loop(ws, conn)
        finally:
            pinger.cancel()
            self._hub.desk_left(conn)
            conn.open = False
            log.info("call desk disconnected")

    async def _hello(self, ws: WebSocket) -> Hello:
        msg = await ws.receive()
        text = msg.get("text")
        if msg.get("type") == "websocket.disconnect" or not isinstance(text, str):
            raise ConnectionError("no hello")
        first = parse_desk(text)
        if not isinstance(first, Hello):
            raise ProtocolError("the desk's first message is hello")
        return first

    async def _ping(self, conn: DeskConnection) -> None:
        while conn.open:
            await asyncio.sleep(self._ping_s)
            try:
                await conn.send(Ping())
            except ConnectionError:
                return

    async def _desk_loop(self, ws: WebSocket, conn: DeskConnection) -> None:
        bad = 0
        window = (0.0, 0)  # (second started, frames in it)
        while conn.open:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            data, text = msg.get("bytes"), msg.get("text")
            try:
                if isinstance(data, bytes):
                    window = self._audio(conn, data, window)
                elif isinstance(text, str):
                    await self._desk_message(conn, text)
                else:
                    raise ProtocolError("empty message")
            except ProtocolError as exc:
                bad += 1
                log.info("call desk message refused", extra={"why": str(exc)[:80]})
                if bad > MAX_BAD:
                    await conn.close(WS_BAD_MESSAGE)
                    return

    def _audio(
        self, conn: DeskConnection, data: bytes, window: tuple[float, int]
    ) -> tuple[float, int]:
        kind, pcm = unpack_audio(data)
        if kind is not AudioKind.THEM:
            raise ProtocolError("the desk sends only the other person's audio")
        now = time.monotonic()
        started, count = window if now - window[0] < 1.0 else (now, 0)
        count += len(pcm) // FRAME_BYTES
        if count > AUDIO_FRAMES_PER_S:
            return started, count  # a flood: dropped
        session = self._hub.active(conn.uid)
        if session is not None:
            session.on_audio(pcm)
        return started, count

    async def _desk_message(self, conn: DeskConnection, text: str) -> None:
        msg = parse_desk(text)
        if isinstance(msg, Hello):
            conn.hello = msg
            return
        if isinstance(msg, DeskState):
            conn.last_state = msg
            active = self._hub.active(conn.uid)
            if active is not None:
                active.on_desk_state(msg)
            return
        call_id = getattr(msg, "call_id", None)
        session = self._hub.session(conn.uid, call_id) if call_id else None
        if session is None:
            return  # not this owner's running call: ignored
        if isinstance(msg, Vad):
            session.on_vad(msg.speaking)
        elif isinstance(msg, HeardText):
            session.on_heard_text(msg.lang, msg.text, msg.confidence)
        elif isinstance(msg, Played):
            session.on_played(msg.utterance_id)
        elif isinstance(msg, DtmfDone):
            session.on_dtmf_done(msg.digit)
        elif isinstance(msg, Mic):
            session.on_mic(msg.owner_mic)
        elif isinstance(msg, DeskError):
            await session.on_desk_error(msg.code)

    # ---- a live listener ----------------------------------------------------------------------
    async def live(self, ws: WebSocket, uid: str, call_id: str) -> None:
        session = self._hub.session(uid, call_id)
        if session is None or session.state.terminal:
            await ws.close(code=WS_GONE)
            return
        await ws.accept()
        on_phone = ws.query_params.get("device") == "phone"
        listener = LiveListener(ws)
        session.add_listener(listener)
        sender = asyncio.ensure_future(listener.run())
        work: set[asyncio.Task[Any]] = set()
        tells: deque[float] = deque()
        bad = 0
        try:
            while not listener.closed:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                try:
                    if not isinstance(text, str):
                        raise ProtocolError("listeners send JSON text only")
                    cmd = parse_live_client(text)
                except ProtocolError:
                    bad += 1
                    if bad > MAX_BAD_LIVE:
                        listener.close(WS_BAD_MESSAGE)
                    continue
                if isinstance(cmd, Listen):
                    session.set_listening(listener, cmd.audio)
                elif isinstance(cmd, LiveTakeover):
                    _track(work, session.takeover(to_phone=on_phone))
                elif isinstance(cmd, Tell):
                    if _allow(tells):
                        _track(work, session.tell(cmd.text))
                elif isinstance(cmd, Hangup):
                    _track(work, session.hangup())
        finally:
            listener.close(1000)
            session.room.remove(listener)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(sender, 5.0)
            for task in work:
                if not task.done():
                    await asyncio.wait({task}, timeout=1.0)


def _track(work: set[asyncio.Task[Any]], coro: Any) -> None:
    task = asyncio.ensure_future(coro)
    work.add(task)
    task.add_done_callback(work.discard)


def _allow(tells: deque[float]) -> bool:
    now = time.monotonic()
    while tells and now - tells[0] > 60:
        tells.popleft()
    if len(tells) >= TELLS_PER_MINUTE:
        return False
    tells.append(now)
    return True


__all__ = ["AUDIO_FRAMES_PER_S", "HELLO_S", "TELLS_PER_MINUTE", "CallSockets"]
