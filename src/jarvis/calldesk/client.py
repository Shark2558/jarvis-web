# src/jarvis/calldesk/client.py
"""The desk's one WebSocket to JARVIS (R18 build brief, "Desk <-> cloud"; mirrors the home
bridge's `cloud.py`).

- `wss://<JARVIS>/v1/calls/desk/ws`, the upgrade signed with the home link's UP key
  (`credentials`); TLS is checked against Windows' certificate store.
- On connect the session sends `hello` and its `state`; JSON from the cloud is parsed by
  `jarvis.calls.protocol` (anything else is dropped and logged by kind only), 0x02 audio goes to
  the session, and the session's messages and 0x01 audio go out through a bounded queue (audio is
  dropped first when the link is slow). A light check runs every 30 s and sends `state` when
  something changed.
- Reconnects with a growing, jittered pause (1, 2, 5, 10, 30, 60 s; back to 1 s after a minute
  online). A 401 corrects the clock from the cloud's `Date` header and retries at once; three in
  a row mean the home link is gone: the desk says so in its log and tries every 5 minutes. The
  cloud's "not built yet" close (4501) waits a minute. No message for 90 s: reconnect.
- Nothing here logs a message body, audio or a header.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Protocol

from jarvis.calldesk.credentials import DeskCredentials
from jarvis.calls.protocol import (
    DESK_WS_PATH,
    WS_NOT_BUILT,
    WS_UNAUTHORIZED,
    AudioKind,
    CloudToDesk,
    DeskToCloud,
    ProtocolError,
    dump,
    parse_cloud_to_desk,
    unpack_audio,
)

log = logging.getLogger(__name__)

BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
STABLE_S = 60.0
NOT_LINKED_AFTER = 3
NOT_LINKED_RETRY_S = 300.0
NOT_BUILT_RETRY_S = 60.0
IDLE_TIMEOUT_S = 90.0
CHECK_EVERY_S = 30.0
OUTBOX_MAX = 400  # about 8 s of audio messages
_JITTER = 0.2
_SKEW_FIX_S = 20.0


class Unauthorized(Exception):
    """The cloud refused the upgrade (401). `date` is its Date header, if any."""

    def __init__(self, date: str | None = None) -> None:
        super().__init__("unauthorized")
        self.date = date


class Refused(Exception):
    """The upgrade failed with another HTTP status (0: no usable answer)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"refused ({status})")
        self.status = status


class LinkClosed(Exception):
    """The socket closed; `code` is the close code (1006 when it just dropped)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"closed ({code})")
        self.code = code


class Connection(Protocol):
    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes:
        """Raises LinkClosed when the socket is gone."""
        ...

    async def close(self) -> None: ...


Connector = Callable[[str, dict[str, str]], Awaitable[Connection]]


class Session(Protocol):
    async def connected(self) -> None: ...

    def disconnected(self) -> None: ...

    async def handle(self, msg: CloudToDesk) -> None: ...

    def jarvis_audio(self, pcm: bytes) -> None: ...

    async def light_check(self) -> None: ...


def ws_url(jarvis_url: str) -> str:
    """https://host -> wss://host/v1/calls/desk/ws"""
    if not jarvis_url.startswith("https://"):
        raise ValueError("JARVIS's address must be https")
    return "wss://" + jarvis_url.removeprefix("https://").rstrip("/") + DESK_WS_PATH


class DeskClient:
    """Also the session's `Outbox`."""

    def __init__(
        self,
        url: str,
        credentials: Callable[[], DeskCredentials | None],
        connector: Connector,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
        check_every_s: float = CHECK_EVERY_S,
    ) -> None:
        self._url = url
        self._credentials = credentials
        self._connector = connector
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._idle = idle_timeout_s
        self._check_every = check_every_s
        self._queue: asyncio.Queue[str | bytes] | None = None
        self._dropped = 0
        self.offset_s = 0.0
        self.linked = True  # False after NOT_LINKED_AFTER refusals in a row

    # ---- Outbox --------------------------------------------------------------------------------

    def send(self, msg: DeskToCloud) -> None:
        self._put(dump(msg))

    def send_audio(self, message: bytes) -> None:
        self._put(message)

    def _put(self, item: str | bytes) -> None:
        queue = self._queue
        if queue is None:
            return  # offline: the session resends its state on the next connect
        if queue.full():
            if isinstance(item, bytes):
                self._dropped += 1
                return
            self._drop_one_audio(queue)
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1

    @staticmethod
    def _drop_one_audio(queue: asyncio.Queue[str | bytes]) -> None:
        kept: list[str | bytes] = []
        dropped = False
        while not queue.empty():
            item = queue.get_nowait()
            if not dropped and isinstance(item, bytes):
                dropped = True
                continue
            kept.append(item)
        for item in kept:
            queue.put_nowait(item)

    # ---- the connection loop -------------------------------------------------------------------

    async def run(self, session: Session, stop: asyncio.Event) -> None:
        failures = 0
        refused = 0
        while not stop.is_set():
            creds = self._credentials()
            if creds is None:
                self.linked = False
                log.warning("the call desk is not linked: run install-calldesk.ps1 -Link")
                await self._wait(stop, NOT_LINKED_RETRY_S)
                continue
            delay: float
            try:
                conn = await self._open(creds)
            except Unauthorized:
                refused += 1
                self.linked = refused < NOT_LINKED_AFTER
                if not self.linked:
                    log.warning("JARVIS does not know this laptop's link: run install -Link")
                    delay = NOT_LINKED_RETRY_S
                else:
                    delay = self._backoff(failures)
                failures += 1
            except (Refused, LinkClosed, OSError, TimeoutError):
                log.info("JARVIS could not be reached; trying again")
                delay = self._backoff(failures)
                failures += 1
            else:
                refused = 0
                self.linked = True
                started = self._clock()
                code = await self._serve(conn, session, stop)
                if self._clock() - started >= STABLE_S:
                    failures = 0
                delay = self._after_close(code, failures)
                failures += 1
            await self._wait(stop, delay)

    async def _open(self, creds: DeskCredentials) -> Connection:
        try:
            return await self._connector(self._url, creds.upgrade_headers(self._now()))
        except Unauthorized as exc:
            if not self._learn_clock(exc.date):
                raise
            log.info("the laptop's clock was off; corrected from JARVIS's")
            return await self._connector(self._url, creds.upgrade_headers(self._now()))

    def _after_close(self, code: int, failures: int) -> float:
        if code == WS_NOT_BUILT:
            return NOT_BUILT_RETRY_S
        if code == WS_UNAUTHORIZED:
            return NOT_LINKED_RETRY_S
        return self._backoff(failures)

    def _backoff(self, failures: int) -> float:
        base = BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]
        return base * (1.0 + _JITTER * (2.0 * self._rng() - 1.0))

    async def _wait(self, stop: asyncio.Event, seconds: float) -> None:
        if stop.is_set():
            return
        waiter = asyncio.ensure_future(stop.wait())
        sleeper = asyncio.ensure_future(self._sleep(seconds))
        try:
            await asyncio.wait({waiter, sleeper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            waiter.cancel()
            sleeper.cancel()

    def _now(self) -> float:
        return self._clock() + self.offset_s

    def _learn_clock(self, date: str | None) -> bool:
        """True when the cloud's Date header moved our clock (then a retry is worth it)."""
        if not date:
            return False
        try:
            server = parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            return False
        off = server - self._clock()
        if abs(off - self.offset_s) <= _SKEW_FIX_S:
            return False
        self.offset_s = off
        return True

    # ---- one connection ------------------------------------------------------------------------

    async def _serve(self, conn: Connection, session: Session, stop: asyncio.Event) -> int:
        self._queue = asyncio.Queue(maxsize=OUTBOX_MAX)
        writer = asyncio.ensure_future(self._write(conn))
        checker = asyncio.ensure_future(self._check(session))
        stopper = asyncio.ensure_future(stop.wait())
        reader = asyncio.ensure_future(self._read(conn, session))
        log.info("connected to JARVIS")
        try:
            await session.connected()
            done, _ = await asyncio.wait(
                {reader, writer, stopper}, return_when=asyncio.FIRST_COMPLETED
            )
            code = reader.result() if reader in done and not reader.cancelled() else 1000
            if writer in done and writer.exception() is not None:
                code = 1006
            return code
        except LinkClosed as exc:
            return exc.code
        finally:
            self._queue = None
            for task in (writer, checker, stopper, reader):
                task.cancel()
            session.disconnected()
            try:
                await conn.close()
            except (LinkClosed, OSError):
                pass
            if self._dropped:
                log.warning("audio was dropped on a slow link", extra={"messages": self._dropped})
                self._dropped = 0
            log.info("disconnected from JARVIS")

    async def _read(self, conn: Connection, session: Session) -> int:
        while True:
            try:
                data = await asyncio.wait_for(conn.recv(), self._idle)
            except TimeoutError:
                log.info("no message from JARVIS for a while; reconnecting")
                return 1006
            except LinkClosed as exc:
                return exc.code
            await self._dispatch(data, session)

    async def _dispatch(self, data: str | bytes, session: Session) -> None:
        try:
            if isinstance(data, str):
                await session.handle(parse_cloud_to_desk(data))
                return
            kind, pcm = unpack_audio(data)
            if kind is not AudioKind.JARVIS:
                raise ProtocolError("unexpected audio kind")
            session.jarvis_audio(pcm)
        except ProtocolError:
            log.warning("a message from JARVIS did not fit the contract; ignored")
        except Exception:  # noqa: BLE001 - one bad turn must not drop the call's link
            log.exception("handling a message from JARVIS failed")

    async def _write(self, conn: Connection) -> None:
        queue = self._queue
        assert queue is not None
        while True:
            item = await queue.get()
            await conn.send(item)

    async def _check(self, session: Session) -> None:
        while True:
            await asyncio.sleep(self._check_every)
            try:
                await session.light_check()
            except Exception:  # noqa: BLE001 - a failed check must not drop the link
                log.exception("the periodic check failed")


__all__ = [
    "BACKOFF_S",
    "Connection",
    "Connector",
    "DeskClient",
    "LinkClosed",
    "Refused",
    "Session",
    "Unauthorized",
    "ws_url",
]
