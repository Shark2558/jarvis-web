# src/jarvis/voice/profile_store.py
"""The voice profile store (R5.2 I0; Layer 7 via the `Docs` port, the pattern of
`jarvis.voice.settings`):

    {prefix}voice_profile/{uid}   user_id, the `VoiceProfile` fields, updated_at

Read through an in-process cache (30 s, one instance runs) that a write refreshes at once, so the
voice service's engine routing (V2) reads it on every recording for free. A stored document that
does not validate (hand-edited, from an older shape) reads as the default profile, as if no
session had run: routing then uses the default order, and nothing is lost that a new session can't
give back. Never audio, a voice print or a wake-word file (they stay on the owner's devices).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id
from jarvis.voice.profile import VoiceProfile
from jarvis.voice.settings import CACHE_S

log = get_logger(__name__)

COLLECTION = "voice_profile"
_STAMPS = frozenset({"user_id", "updated_at"})  # the document's own fields, not the profile's


def decode(doc: Any) -> VoiceProfile:
    if not isinstance(doc, dict):
        return VoiceProfile()
    body = {k: v for k, v in doc.items() if k not in _STAMPS}
    try:
        return VoiceProfile.model_validate(body)
    except ValidationError as exc:
        log.warning("voice profile unreadable: default used", extra={"errors": exc.error_count()})
        return VoiceProfile()


def encode(uid: str, profile: VoiceProfile) -> dict[str, Any]:
    at = datetime.now(UTC).isoformat()
    return {"user_id": uid, **profile.model_dump(mode="json"), "updated_at": at}


def _checked(uid: str) -> str:
    if not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


class DocProfileStore:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._d = docs
        self._col = f"{prefix}{COLLECTION}"
        self._clock = clock
        self._cache: dict[str, tuple[float, VoiceProfile]] = {}

    def _path(self, uid: str) -> str:
        return f"{self._col}/{_checked(uid)}"

    def _keep(self, uid: str, profile: VoiceProfile) -> VoiceProfile:
        self._cache[uid] = (self._clock(), profile)
        return profile

    async def get(self, uid: str) -> VoiceProfile:
        """The owner's profile (the default when none is stored). Storage errors propagate."""
        path = self._path(uid)
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[0] < CACHE_S:
            return hit[1]
        return self._keep(uid, decode(await self._d.get(path)))

    async def save(self, uid: str, profile: VoiceProfile) -> VoiceProfile:
        return await self.update(uid, lambda _cur: profile)

    async def update(
        self, uid: str, change: Callable[[VoiceProfile], VoiceProfile]
    ) -> VoiceProfile:
        path = self._path(uid)

        async def fn(tx: DocTx) -> VoiceProfile:
            body = encode(uid, change(decode(await tx.get(path))))
            tx.set(path, body)
            return decode(body)

        return self._keep(uid, await self._d.transaction(fn))

    async def delete(self, uid: str) -> bool:
        path = self._path(uid)

        async def fn(tx: DocTx) -> bool:
            found = await tx.get(path) is not None
            if found:
                tx.delete(path)
            return found

        found = await self._d.transaction(fn)
        self._cache.pop(uid, None)
        return found


class MemoryProfileStore:
    """Tests: the same contract, in this process."""

    def __init__(self) -> None:
        self._kept: dict[str, VoiceProfile] = {}

    async def get(self, uid: str) -> VoiceProfile:
        return self._kept.get(_checked(uid), VoiceProfile())

    async def save(self, uid: str, profile: VoiceProfile) -> VoiceProfile:
        self._kept[_checked(uid)] = profile
        return profile

    async def update(
        self, uid: str, change: Callable[[VoiceProfile], VoiceProfile]
    ) -> VoiceProfile:
        return await self.save(uid, change(await self.get(uid)))

    async def delete(self, uid: str) -> bool:
        return self._kept.pop(_checked(uid), None) is not None


__all__ = ["COLLECTION", "DocProfileStore", "MemoryProfileStore", "decode", "encode"]
