# src/jarvis/phone/applock.py
"""The app lock (R7 D21): Part C's check for I0's slot (`services["app_lock"]`, an async
`(scope) -> bool` that says "this cookie session is locked"; the slot answers 423 device_locked
outside D21's never-locked list and 503 when the check raises).

Which sessions: only the installed app's. The page marks its session once it opened at
`/?source=app` (`POST /v1/session/app`); a mark only ever switches the lock ON for the session and
nothing takes it off. Ordinary browsers are never locked.

When: the lock is ARMED for an owner only while his switch is on (default on) AND a passkey he
registered from the app still exists AND passkeys are in force. Until then nothing locks, so a
passkey that lives only on the laptop (Windows Hello) can never lock him out of his phone. "From
the app": a `POST /v1/passkeys/register` made in an app session, and the passkey that appeared
because of it (read on the session's next request, within 2 minutes).

Idle: no request HE made for `app_lock_minutes`. A write with the CSRF header counts (except the
known heartbeats), and so does the page's "I'm here" call (sent at most once a minute after a real
tap or key press). Background reads never count: the Home panel's poll, the /auth/me recheck on
every return to the screen. A locked session stays locked whatever it sends, until a
`device_unlock` passkey check bound to THIS session (`ss_<24>`, kept in the signed cookie).
The last activity is kept in the signed cookie and, per session, in a small bounded table here
(the later of the two wins, so a slow background answer carrying an older cookie can't undo it).
"""

from __future__ import annotations

import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from starlette.requests import Request

from jarvis.api.auth import CSRF_HEADER, CSRF_VALUE, SAFE_METHODS, session_email
from jarvis.api.identity import user_id_for_email
from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.permissions.service import passkey_ref
from jarvis.phone.store import PhoneStore

log = get_logger(__name__)

APP_KEY, SS_KEY, SEEN_KEY = "r7_app", "r7_ss", "r7_seen"  # in the signed session cookie
SS = re.compile(r"^ss_[A-Za-z0-9_-]{24}$")
REGISTER = ("POST", "/v1/passkeys/register")
REGISTER_WINDOW_S = 120.0
ARMED_CACHE_S = 5.0
SESSIONS_MAX = 256
# writes the console sends by itself, on a timer or on viewing: never "the owner was here"
BACKGROUND_WRITES = frozenset({"/v1/book/show/beat", "/v1/brief/seen"})
# answered by Part C itself while locked (beyond the slot's own list, which already covers them)
EXEMPT = frozenset({("POST", "/v1/session/unlock")})

Scope = Any


def _header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    return next((v for k, v in headers if k.lower() == name), None)


def counts_as_activity(method: str, path: str, headers: Iterable[tuple[bytes, bytes]]) -> bool:
    """A request the owner made: a write with the CSRF header that is not a heartbeat."""
    if method.upper() in SAFE_METHODS or path in BACKGROUND_WRITES:
        return False
    return _header(headers, CSRF_HEADER.encode()) == CSRF_VALUE.encode()


def exempt(method: str, path: str) -> bool:
    return (method.upper(), path) in EXEMPT


def new_session_id() -> str:
    return "ss_" + secrets.token_urlsafe(18)


def session_id(session: Mapping[str, Any]) -> str | None:
    ss = session.get(SS_KEY)
    return ss if isinstance(ss, str) and SS.fullmatch(ss) else None


def ensure_session_id(session: dict[str, Any]) -> str:
    ss = session_id(session)
    if ss is None:
        ss = session[SS_KEY] = new_session_id()
    return ss


class AppLock:
    def __init__(
        self,
        s: Settings,
        store: PhoneStore,
        *,
        permissions: Callable[[], Any],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._s, self._store, self._perms, self._clock = s, store, permissions, clock
        self.idle_s = s.app_lock_minutes * 60.0
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._armed: dict[str, tuple[bool, float]] = {}
        self._pending: OrderedDict[str, tuple[str, frozenset[str], float]] = OrderedDict()

    # ---- the slot's check ---------------------------------------------------------------------
    async def __call__(self, scope: Scope) -> bool:
        session = scope.get("session")
        if not isinstance(session, dict) or not session.get(APP_KEY):
            return False  # not the app's session: never locked
        ss, uid = session_id(session), self._owner(scope)
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if ss is None or uid is None or exempt(method, path):
            return False
        now = self._clock()
        await self._settle_registration(uid, ss, now)
        if await self.armed(uid) and now - self.last_seen(session) > self.idle_s:
            return True
        if counts_as_activity(method, path, scope.get("headers") or ()):
            self.touch(session, now)
        if (method, path) == REGISTER:
            await self._note_registration(uid, ss, now)
        return False

    def _owner(self, scope: Scope) -> str | None:
        view = scope if scope.get("type") == "http" else {**scope, "type": "http"}
        email = session_email(Request(view), self._s)
        return user_id_for_email(email) if email else None

    # ---- activity -----------------------------------------------------------------------------
    def last_seen(self, session: Mapping[str, Any]) -> float:
        ss = session_id(session) or ""
        cookie = session.get(SEEN_KEY)
        mark = float(cookie) if isinstance(cookie, int | float) else 0.0
        return max(mark, self._seen.get(ss, 0.0))

    def touch(self, session: dict[str, Any], now: float) -> None:
        ss = ensure_session_id(session)
        session[SEEN_KEY] = now
        self._seen[ss] = max(now, self._seen.get(ss, 0.0))
        self._seen.move_to_end(ss)
        while len(self._seen) > SESSIONS_MAX:
            self._seen.popitem(last=False)

    def mark_app(self, session: dict[str, Any]) -> str:
        """The installed app's session (only ever ON). A new mark starts the idle clock."""
        ss = ensure_session_id(session)
        if not session.get(APP_KEY):
            session[APP_KEY] = self._clock()
            self.touch(session, self._clock())
        return ss

    async def locked(self, session: dict[str, Any], uid: str) -> bool:
        if not session.get(APP_KEY) or session_id(session) is None:
            return False
        return await self.armed(uid) and self._clock() - self.last_seen(session) > self.idle_s

    # ---- armed: the switch, a passkey from the app, passkeys in force --------------------------
    def forget(self, uid: str) -> None:
        self._armed.pop(uid, None)

    async def armed(self, uid: str) -> bool:
        hit = self._armed.get(uid)
        now = time.monotonic()
        if hit is not None and now - hit[1] < ARMED_CACHE_S:
            return hit[0]
        value = await self._read_armed(uid)
        self._armed[uid] = (value, now)
        return value

    async def app_keys(self, uid: str) -> tuple[bool, Sequence[str]]:
        prefs = (await self._store.owner(uid)).lock
        return prefs.on, prefs.keys

    async def _read_armed(self, uid: str) -> bool:
        on, keys = await self.app_keys(uid)
        if not on or not keys:
            return False
        perms = self._perms()
        if perms is None or not perms.available:
            return False
        owned = {passkey_ref(k.id) for k in await perms.passkeys.owned(uid)}
        if not owned & set(keys):
            return False
        return bool(await perms.passkey_required(uid))

    async def _owned_refs(self, uid: str) -> frozenset[str] | None:
        perms = self._perms()
        if perms is None or not perms.available:
            return None
        return frozenset(passkey_ref(k.id) for k in await perms.passkeys.owned(uid))

    async def _note_registration(self, uid: str, ss: str, now: float) -> None:
        before = await self._owned_refs(uid)
        if before is None:
            return
        self._pending[ss] = (uid, before, now)
        while len(self._pending) > 64:
            self._pending.popitem(last=False)

    async def _settle_registration(self, uid: str, ss: str, now: float) -> None:
        """After a registration from the app: the passkey that appeared is the app's."""
        pending = self._pending.get(ss)
        if pending is None:
            return
        who, before, at = pending
        if who != uid or now - at > REGISTER_WINDOW_S:
            self._pending.pop(ss, None)
            return
        after = await self._owned_refs(uid)
        new = sorted((after or frozenset()) - before)
        if not new:
            return  # not yet (the registration is still running), or it failed: wait
        self._pending.pop(ss, None)
        if len(new) != 1:  # another device registered one meanwhile: whose is whose is unknown,
            log.warning("app lock: two passkeys appeared at once; neither counts as the app's")
            return  # so neither arms the lock (it must never lock him out)
        await self._store.add_lock_keys(uid, new)
        self.forget(uid)
        log.info("app lock: a passkey was registered from the app", extra={"count": len(new)})


__all__ = [
    "APP_KEY",
    "BACKGROUND_WRITES",
    "SEEN_KEY",
    "SS_KEY",
    "AppLock",
    "counts_as_activity",
    "ensure_session_id",
    "exempt",
    "new_session_id",
    "session_id",
]
