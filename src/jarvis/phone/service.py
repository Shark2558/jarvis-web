# src/jarvis/phone/service.py
"""Part C's service (R7 D4, D5, D21): linking, the linked phones, the asset links, and the parts
the routes in `api/phone.py` share (the door's gate, its two handlers, the app lock).

Linking (D5): `POST /phone/link {v, code, public_key, package, fingerprint, model, app_version}`
(no cookie, no header) is checked for shape first: exactly the app's keys, the ONE package
`io.github.shark2558.jarvis`, a valid P-256 public key (an X9.62 uncompressed point ON the
curve), a signing fingerprint of exactly 32 bytes. A malformed request is not a try against the
code. Then the code (`store.link`: one transaction). A link rings `phone_linked` on every channel
(no off switch) and is audited with the device id only, never a key or a fingerprint.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.identity import LEGACY_USER_ID, user_id_for_email
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.mobile.ports import PACKAGE, MobileContext
from jarvis.notify.ports import Signal
from jarvis.phone.applock import AppLock
from jarvis.phone.door import DoorGate, PerPhoneRate
from jarvis.phone.handlers import DoorHandlers
from jarvis.phone.store import CODE_TTL_S, LinkOutcome, Phone, PhoneStore
from jarvis.storage.docs import Docs
from jarvis.telegram.pairing import new_code, normalise

log = get_logger(__name__)

RELATION = "delegate_permission/common.handle_all_urls"
LINKS_CACHE_S = 60.0
LINK_PER_MINUTE = 10  # link attempts a minute from one client
LINK_ALL_PER_MINUTE = 30  # and from everyone
LinkError = Literal["input_rejected", "not_this_app", "bad_key", "bad_fingerprint"]


class LinkBody(BaseModel):
    """Exactly what the app sends; anything else is refused, never guessed at."""

    model_config = ConfigDict(extra="forbid", strict=True)

    v: Literal[1]
    code: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=1, max_length=200)
    package: str = Field(min_length=1, max_length=120)
    fingerprint: str = Field(min_length=1, max_length=200)
    model: str = Field(pattern=r"^[A-Za-z0-9 ._-]{1,40}$")
    app_version: str = Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")


def check_link(body: LinkBody) -> tuple[LinkError | None, str, str]:
    """(refusal, the key's hex, the fingerprint's lower-case hex)."""
    if body.package != PACKAGE:
        return "not_this_app", "", ""
    key = body.public_key.lower()
    if len(key) != 130 or not key.startswith("04") or not _hex(key):
        return "bad_key", "", ""
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(key))
    except ValueError:
        return "bad_key", "", ""
    fp = body.fingerprint.lower()
    if len(fp) != 64 or not _hex(fp):
        return "bad_fingerprint", "", ""
    return None, key, fp


def _hex(text: str) -> bool:
    return all(c in "0123456789abcdef" for c in text)


def owner_ids(emails: list[str]) -> tuple[str, ...]:
    ids = tuple(dict.fromkeys(user_id_for_email(e) for e in emails))
    return ids or (LEGACY_USER_ID,)


def iso(at: float | None) -> str | None:
    return None if at is None else datetime.fromtimestamp(at, UTC).isoformat()


class PhoneService:
    def __init__(self, ctx: MobileContext, docs: Docs) -> None:
        self.s = ctx.s
        self._ctx = ctx
        self.owners = owner_ids(list(ctx.s.owner_emails))
        self.clock: Callable[[], float] = self._now  # the tests' seam, else the real clock
        self.store = PhoneStore(docs, prefix=ctx.prefix, owners=self.owners)
        self.gate = DoorGate(self.store, skew_s=ctx.s.phone_clock_skew_s, clock=self.clock)
        self.handlers = DoorHandlers(ctx.s, self.store, state=ctx.state, clock=self.clock)
        self.lock = AppLock(
            ctx.s, self.store, permissions=lambda: ctx.state("permissions"), clock=self.clock
        )
        self.link_clients = PerPhoneRate(per_minute=LINK_PER_MINUTE, max_phones=1024)
        self.link_all = PerPhoneRate(per_minute=LINK_ALL_PER_MINUTE, max_phones=1)
        self.limits = PerPhoneRate(per_minute=5, max_phones=256)  # unlocks and the lock switch
        self.code_limits = PerPhoneRate(per_minute=10, max_phones=16)  # link codes (2 calls each)
        self._links: tuple[list[dict[str, Any]], float] | None = None

    def _now(self) -> float:
        clock = self._ctx.state("phone_clock")  # the tests' and evals' clock; else the real one
        return float(clock()) if callable(clock) else time.time()

    # ---- the card -----------------------------------------------------------------------------
    async def view(self, uid: str) -> dict[str, Any]:
        owner = await self.store.owner(uid)
        left = await self.store.code_left(uid, self.clock())
        return {
            "part": "phone",
            "ready": "ready",
            "max": self.s.phone_link_max,
            "phones": [self._phone(p) for p in owner.phones],
            "code": None if left is None else {"seconds_left": left},
        }

    @staticmethod
    def _phone(p: Phone) -> dict[str, Any]:
        return {
            "id": p.id,
            "model": p.model,
            "linked_at": iso(p.linked_at),
            "last_seen": iso(p.last_seen),
            "app_version": p.app_version,
            "android": p.android,
            "can": dict(p.can),
        }

    def code_digest(self, code: str) -> str:
        """The code as stored: an HMAC under the session-signing secret (a leaked document can't
        be brute-forced offline: the code has only 40 bits)."""
        secret = self.s.session_secret
        key = secret.get_secret_value().encode() if secret is not None else b""
        return hmac.new(key, b"r7-link-code-v1:" + code.encode(), hashlib.sha256).hexdigest()

    # ---- the code -----------------------------------------------------------------------------
    async def offer(self, uid: str) -> str:
        return await self.store.offer(uid, self.clock())

    async def issue(self, uid: str, offer_id: str) -> dict[str, Any] | str:
        code = new_code()
        digest = self.code_digest(code)
        got = await self.store.issue(uid, offer_id, digest, self.clock())
        if got != "issued":
            return got
        return {"code": code, "expires_in_s": CODE_TTL_S}

    # ---- linking ------------------------------------------------------------------------------
    async def link(self, body: LinkBody, key: str, fingerprint: str) -> LinkOutcome:
        now = self.clock()
        code = normalise(body.code)
        if code is None:
            await self.store.wrong_try(now)
            return LinkOutcome("bad_code")
        digest = self.code_digest(code)

        def make() -> Phone:
            return Phone(
                id=_device_id(),
                model=body.model,
                public_key=key,
                package=body.package,
                fingerprint=fingerprint,
                linked_at=now,
                app_version=body.app_version,
            )

        out = await self.store.link(digest, make, now, max_phones=self.s.phone_link_max)
        if out.result == "bad_code":
            await self.store.wrong_try(now)
            return out
        if out.result == "linked" and out.phone is not None:
            self._links = None
            await self.audit("phone_link", {"device": out.phone.id, "model": out.phone.model})
            await self.alert(
                out.uid,
                "phone_linked",
                f"A phone was linked to JARVIS at {self._hhmm(now)}. "
                "If this wasn't you, unlink it in Integrations.",
            )
        return out

    async def unlink(self, uid: str, device_id: str) -> bool:
        gone = await self.store.unlink(uid, device_id)
        if gone is None:
            return False
        self._links = None
        self.lock.forget(uid)  # the last phone gone disarms the lock at once
        await self.audit("phone_unlink", {"device": device_id})
        when = self._hhmm(self.clock())
        await self.alert(uid, "phone_unlinked", f"A phone was unlinked from JARVIS at {when}.")
        return True

    async def unlink_all(self, uid: str) -> int:
        count = await self.store.unlink_all(uid)
        if count:
            self._links = None
            self.lock.forget(uid)
            await self.audit("phone_unlink", {"device": "all", "count": count})
        return count

    # ---- the asset links (D4) -----------------------------------------------------------------
    async def asset_links(self) -> list[dict[str, Any]]:
        """One statement for the one package with every linked phone's signing fingerprint (read
        at most once a minute: the route is public)."""
        hit = self._links
        if hit is not None and self.clock() - hit[1] < LINKS_CACHE_S:
            return hit[0]
        prints = await self.store.fingerprints()
        out: list[dict[str, Any]] = []
        if prints:
            out.append(
                {
                    "relation": [RELATION],
                    "target": {
                        "namespace": "android_app",
                        "package_name": PACKAGE,
                        "sha256_cert_fingerprints": [_colons(fp) for fp in prints],
                    },
                }
            )
        self._links = (out, self.clock())
        return out

    # ---- the audit and the alerts -------------------------------------------------------------
    async def audit(self, tool: str, args: dict[str, Any]) -> bool:
        trail = self._ctx.audit
        if trail is None:
            return False
        try:
            await trail.append(
                agent="owner",
                tool=tool,
                risk=ActionRisk.READ_ONLY,
                outcome="executed",
                args=args,
            )
        except Exception as exc:  # noqa: BLE001 - logged; the caller decides what that means
            log.error(
                "AUDIT WRITE FAILED for a phone event",
                extra={"tool": tool, "error": type(exc).__name__},
            )
            return False
        return True

    async def alert(self, uid: str, kind: Any, message: str) -> None:
        make = self._ctx.notifier
        if make is None:
            return
        try:
            await make().notify(uid, Signal(source="system", kind=kind), message)
        except Exception as exc:  # noqa: BLE001 - an alert that fails never undoes the link
            log.error("phone alert failed", extra={"kind": kind, "error": type(exc).__name__})

    def _hhmm(self, at: float) -> str:
        try:
            zone = ZoneInfo(self.s.user_timezone)
        except (KeyError, ValueError):
            zone = ZoneInfo("UTC")
        return datetime.fromtimestamp(at, zone).strftime("%H:%M")


def _device_id() -> str:
    return f"ph_{secrets.token_hex(6)}"


def _colons(fp: str) -> str:
    return ":".join(fp[i : i + 2] for i in range(0, len(fp), 2)).upper()


__all__ = [
    "RELATION",
    "LinkBody",
    "PhoneService",
    "check_link",
    "iso",
    "owner_ids",
]
