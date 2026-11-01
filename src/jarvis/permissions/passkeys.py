# src/jarvis/permissions/passkeys.py
"""Registered passkeys and single-use WebAuthn challenges (slice 10 D; Layer 7, `Docs` port).

    {prefix}passkeys/{uid}               user_id, creds [{id, public_key, sign_count, label,
                                         created_at, last_used_at, transports, backed_up}],
                                         updated_at   (≤ 10 passkeys: one small document)
    {prefix}webauthn_challenges/{id}     user_id, purpose, binding, challenge, created_at,
                                         expires_at   (2 minutes; deleted when used)

Only public keys are stored — a passkey's private key never leaves the owner's device. A
challenge is taken (read + deleted in one transaction) before anything is checked, so it works
once even when the check fails. The sign count is advanced with a compare-and-set inside a
transaction: two uses of the same assertion can't both pass. Expired challenges a browser never
answered are swept when the same owner asks for a new one (and at most 10 are live per owner).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query, Set
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)

MAX_PASSKEYS = 10
CHALLENGE_TTL = timedelta(minutes=2)
MAX_LIVE_CHALLENGES = 10
LABEL_MAX = 40

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StoredPasskey(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(max_length=1400)  # base64url credential id (≤ 1023 bytes)
    public_key: str = Field(max_length=2048)  # base64url COSE public key
    sign_count: int = Field(ge=0)
    label: str = Field(max_length=LABEL_MAX)
    created_at: str
    last_used_at: str | None = None
    transports: list[str] = Field(default_factory=list)
    backed_up: bool = False


class Challenge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    user_id: str
    purpose: str
    binding: str  # hex sha256 of what the ceremony is for
    challenge: str  # base64url bytes the authenticator signs
    expires_at: datetime
    note: str = ""  # how a registration was authorised (for the audit): passkey / recent sign-in


class PasskeyLimit(Exception):
    """The owner already has the most passkeys allowed."""


class NeedsProof(Exception):
    """A registration authorised without proof (no passkey existed then) met an existing one."""


def _decode_creds(doc: Any) -> list[StoredPasskey]:
    if not isinstance(doc, dict) or not isinstance(doc.get("creds"), list):
        return []
    out: list[StoredPasskey] = []
    for raw in doc["creds"]:
        try:
            out.append(StoredPasskey.model_validate(raw))
        except (ValueError, TypeError):
            log.error("unreadable stored passkey skipped")
    return out


class PasskeyStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}passkeys"

    def _path(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._col}/{uid}"

    def _doc(self, uid: str, creds: list[StoredPasskey]) -> dict[str, Any]:
        return {
            "user_id": uid,
            "creds": [c.model_dump() for c in creds],
            "updated_at": _utcnow().isoformat(),
        }

    async def owned(self, uid: str) -> list[StoredPasskey]:
        return _decode_creds(await self._d.get(self._path(uid)))

    async def add(
        self, uid: str, cred: StoredPasskey, *, only_if_none: bool = False
    ) -> list[StoredPasskey]:
        """Store a new passkey. `only_if_none`: the registration was authorised while the owner
        had none, so it may only become the FIRST one (checked inside the transaction)."""
        path = self._path(uid)

        async def fn(tx: DocTx) -> list[StoredPasskey]:
            creds = _decode_creds(await tx.get(path))
            if only_if_none and creds:
                raise NeedsProof("a passkey exists now")
            if any(c.id == cred.id for c in creds):
                raise PasskeyLimit("already registered")
            if len(creds) >= MAX_PASSKEYS:
                raise PasskeyLimit("too many")
            new = [*creds, cred]
            tx.set(path, self._doc(uid, new))
            return new

        return await self._d.transaction(fn)

    async def remove(self, uid: str, cred_id: str) -> list[StoredPasskey] | None:
        """The passkeys left, or None when there was no such passkey."""
        path = self._path(uid)

        async def fn(tx: DocTx) -> list[StoredPasskey] | None:
            creds = _decode_creds(await tx.get(path))
            left = [c for c in creds if c.id != cred_id]
            if len(left) == len(creds):
                return None
            tx.set(path, self._doc(uid, left))
            return left

        return await self._d.transaction(fn)

    async def record_use(self, uid: str, cred_id: str, *, old_count: int, new_count: int) -> bool:
        """Advance the sign count iff it is still `old_count` (compare-and-set)."""
        path = self._path(uid)
        at = _utcnow().isoformat()

        async def fn(tx: DocTx) -> bool:
            creds = _decode_creds(await tx.get(path))
            hit = next((c for c in creds if c.id == cred_id), None)
            if hit is None or hit.sign_count != old_count:
                return False
            new = [
                c.model_copy(update={"sign_count": new_count, "last_used_at": at})
                if c.id == cred_id
                else c
                for c in creds
            ]
            tx.set(path, self._doc(uid, new))
            return True

        return await self._d.transaction(fn)


class ChallengeStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_", clock: Clock = _utcnow) -> None:
        self._d = docs
        self._col = f"{prefix}webauthn_challenges"
        self._clock = clock

    def _path(self, cid: str) -> str:
        return f"{self._col}/{cid}"

    async def create(
        self, *, cid: str, uid: str, purpose: str, binding: str, challenge: str, note: str = ""
    ) -> Challenge:
        if not safe_id(cid) or not safe_id(uid):
            raise ValueError("invalid id")
        now = self._clock()
        ch = Challenge(
            id=cid,
            user_id=uid,
            purpose=purpose,
            binding=binding,
            challenge=challenge,
            expires_at=now + CHALLENGE_TTL,
            note=note,
        )
        await self._sweep(uid, now)
        await self._d.write(
            [
                Set(
                    self._path(cid),
                    {**ch.model_dump(), "created_at": now},
                )
            ]
        )
        return ch

    async def _sweep(self, uid: str, now: datetime) -> None:
        """Drop this owner's expired challenges and keep the live ones under the cap."""
        try:
            rows = await self._d.query(Query(self._col, where=("user_id", uid)))
        except Exception as exc:  # noqa: BLE001 — tidying must never block a ceremony
            log.warning("challenge sweep skipped", extra={"error": type(exc).__name__})
            return
        live: list[tuple[datetime, str]] = []
        gone: list[str] = []
        for cid, data in rows:
            exp = data.get("expires_at")
            if not isinstance(exp, datetime) or exp <= now:
                gone.append(cid)
            else:
                live.append((exp, cid))
        live.sort()
        excess = len(live) - (MAX_LIVE_CHALLENGES - 1)
        gone += [cid for _, cid in live[: max(0, excess)]]
        if gone:
            await self._d.write([Delete(self._path(cid)) for cid in gone])

    async def take(self, cid: str) -> Challenge | None:
        """Read and delete in one transaction: a challenge works at most once."""
        if not safe_id(cid):
            return None
        path = self._path(cid)

        async def fn(tx: DocTx) -> Challenge | None:
            data = await tx.get(path)
            if data is None:
                return None
            tx.delete(path)
            try:
                return Challenge.model_validate(data)
            except (ValueError, TypeError):
                log.error("unreadable webauthn challenge dropped")
                return None

        return await self._d.transaction(fn)


__all__ = [
    "CHALLENGE_TTL",
    "Challenge",
    "ChallengeStore",
    "LABEL_MAX",
    "MAX_PASSKEYS",
    "NeedsProof",
    "PasskeyLimit",
    "PasskeyStore",
    "StoredPasskey",
]
