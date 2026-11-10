# src/jarvis/api/book_status.py
"""`GET /v1/book`'s answer (R6 "Contract", D7, D9, D10, D16; builder B), kept out of api/book.py:

    {available, reason?, release, sealed: [{id, label, sealed_at, mb}], sealed_ok, sealing, kept,
     used_mb, limit_mb, session, lock: {on}, last_closed, talk: {on, why?},
     open: {passkey_ready, fresh_left_s}}

`sealing` is true while the current release is being sealed (D7: the route waits at most 20 s,
then the panel shows "Sealing this release..." and asks again); `sealed_ok` is false when the
sealed index failed its check or can't be read (the rest still shows). The live parts are C's and
each is optional: a lock that can't be read is reported ON (fail closed, as the middleware), the
session never shows its id, the talk-through says why it is off. Nothing here is book text.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import Request

from jarvis.api.auth import fresh_sign_in_left
from jarvis.api.identity import primary_user_id
from jarvis.buildbook.model import KEEP, MIB
from jarvis.buildbook.ports import BookError, BookSource, BookVault
from jarvis.buildbook.sealer import BOUNDED_S
from jarvis.logging import get_logger

log = get_logger(__name__)

NO_BOOK = "This server has no build book."
NO_KEY = (
    "The build book is off on this server: it has no encryption key, and the book is only ever "
    "kept sealed."
)
UNBUILT = "This release's build book could not be built at deploy."
TALK_OFF = "The talk-through isn't available on this server."


def _now(st: Any) -> dt.datetime:
    clock = getattr(st, "book_clock", None)  # the tests' and evals' moved clock, as C's routes
    return clock() if callable(clock) else dt.datetime.now(dt.UTC)


async def _sealing(request: Request, uid: str) -> bool:
    """D7 at console boot: seal the current release for the primary owner, bounded."""
    sealer = getattr(request.app.state, "book_sealer", None)
    if sealer is None or uid != primary_user_id(request.app.state.settings):
        return False
    out = await sealer.ensure_bounded(uid, within_s=BOUNDED_S)
    return out.state in ("sealing", "busy")


def _release_part(source: BookSource) -> dict[str, Any]:
    release = source.current()
    if release is None:
        return {"available": False, "reason": NO_BOOK, "release": None}
    ref = release.ref().model_dump()
    if not release.ok:
        return {"available": False, "reason": UNBUILT, "release": ref}
    return {"available": True, "release": ref}


async def _sealed_part(request: Request, vault: BookVault, uid: str) -> dict[str, Any]:
    try:
        rows = await vault.releases(uid)
        ok = True
    except BookError:  # tampered or unreachable: the panel says so, the rest still shows
        rows, ok = (), False
    return {
        "sealed": [r.view() for r in rows],
        "sealed_ok": ok,
        "kept": KEEP,
        "used_mb": round(sum(r.size for r in rows) / MIB, 1),
        "limit_mb": request.app.state.settings.book_max_total_mb,
    }


async def _session_part(st: Any, uid: str) -> dict[str, Any] | None:
    sessions = getattr(st, "book_sessions", None)
    if sessions is None:
        return None
    live = await sessions.live(uid, now=_now(st))
    return None if live is None else dict(live.model_dump(exclude={"session_id"}))


async def _lock_part(st: Any, uid: str) -> dict[str, bool]:
    lock = getattr(st, "book_lock", None)
    if lock is None:
        return {"on": False}
    try:
        return {"on": await lock.get(uid) is not None}
    except Exception as exc:  # noqa: BLE001 - LockUnreadable or worse: never "unlocked"
        log.warning("book lock unreadable", extra={"error": type(exc).__name__})
        return {"on": True}


async def _talk_part(st: Any, uid: str) -> dict[str, Any]:
    talk = getattr(st, "book_talk", None)
    if talk is None:
        return {"on": False, "why": TALK_OFF}
    state = await talk.state(uid)
    return {"on": True} if state.on else {"on": False, "why": state.why}


async def _last_closed(st: Any, uid: str) -> Any:
    """C's `BookService.last_closed(uid)` (D14's `{last_closed_at, notified}`), when it has one."""
    last = getattr(getattr(st, "book_service", None), "last_closed", None)
    if last is None:
        return None
    got = await last(uid)
    return got.model_dump(mode="json") if hasattr(got, "model_dump") else got


async def _live_parts(request: Request, uid: str) -> dict[str, Any]:
    st = request.app.state
    out: dict[str, Any] = {"lock": await _lock_part(st, uid)}
    parts = (("session", _session_part, None), ("talk", _talk_part, {"on": False, "why": TALK_OFF}))
    for name, read, fallback in (*parts, ("last_closed", _last_closed, None)):
        try:
            out[name] = await read(st, uid)
        except Exception as exc:  # noqa: BLE001 - one part never hides the others
            log.warning(
                "book status part unreadable", extra={"part": name, "error": type(exc).__name__}
            )
            out[name] = fallback
    return out


async def _open_part(request: Request, uid: str) -> dict[str, Any]:
    perms = getattr(request.app.state, "permissions", None)
    try:
        ready = bool(perms is not None and await perms.passkey_required(uid))
    except Exception as exc:  # noqa: BLE001 - unreadable passkeys: not ready
        log.warning("book passkey state unreadable", extra={"error": type(exc).__name__})
        ready = False
    left = fresh_sign_in_left(request, request.app.state.settings)
    return {"passkey_ready": ready, "fresh_left_s": left}


def off_body(request: Request) -> dict[str, Any]:
    """`GET /v1/book` while the book is off here (no keyring, D6): a plain 200 the panel shows,
    with the Contract's fields at their empty values (I1: never a 503 at console boot)."""
    return {
        "available": False,
        "reason": NO_KEY,
        "release": None,
        "sealed": [],
        "sealed_ok": True,
        "sealing": False,
        "kept": KEEP,
        "used_mb": 0.0,
        "limit_mb": request.app.state.settings.book_max_total_mb,
        "session": None,
        "lock": {"on": False},
        "last_closed": None,
        "talk": {"on": False, "why": TALK_OFF},
        "open": {"passkey_ready": False, "fresh_left_s": None},
    }


async def status_body(
    request: Request, uid: str, source: BookSource, vault: BookVault
) -> dict[str, Any]:
    sealing = await _sealing(request, uid)
    return {
        **_release_part(source),
        **await _sealed_part(request, vault, uid),
        "sealing": sealing,
        **await _live_parts(request, uid),
        "open": await _open_part(request, uid),
    }


__all__ = ["NO_BOOK", "NO_KEY", "TALK_OFF", "UNBUILT", "off_body", "status_body"]
