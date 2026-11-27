# src/jarvis/voice/session_store.py
"""The voice session in progress (R5.2 row 81; Layer 7 via the `Docs` port):

    {prefix}voice_session/{uid}   user_id, the `SessionDoc` fields, updated_at

What the cloud keeps while a session runs and until its recordings are deleted: the prompts (his
own words among them, as in `voice_settings`), which ones are recorded, and the words the browser
and Google heard for the held-out prompts (at most `HEARD_CHARS` each). Never audio: the clips
are on the laptop kit only (encrypted there). The comparison's ₹ answer is kept here too: his
YES, the ₹ he was shown, and the Google seconds used. "Delete my recordings" deletes this
document with the clips; the results live on in `voice_profile`.

A stored document that does not validate reads as no session (the owner starts again; nothing
is lost that a new session can't give back). Transactional `update`, like the profile store.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.localspeech.protocol import JOB_ID, SESSION_ID
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id
from jarvis.voice.profile import Prompt, SessionState

log = get_logger(__name__)

COLLECTION: Final = "voice_session"
PROMPTS_MAX: Final = 160
HEARD_CHARS: Final = 400
WORDS_KEPT: Final = 50
REASON_CHARS: Final = 200
_STAMPS = frozenset({"user_id", "updated_at"})


class CompareMode(StrEnum):
    FREE = "free"  # inside this month's free Google minutes: every call free-only
    YES = "yes"  # beyond them, after his typed YES: priced, up to the ₹ he was shown
    OFF = "off"  # he chose to compare without Google (or the setting is 0 minutes)
    UNAVAILABLE = "unavailable"  # Google's listening is not set up or not answering here
    NEEDS_YES = "needs_yes"  # the free minutes ran out mid-session: the ₹ question again
    LIMIT = "limit"  # his monthly limit was reached: no more Google for this session


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Compare(_Frozen):
    mode: CompareMode
    cap_clips: int = Field(ge=0, le=PROMPTS_MAX)  # clips Google may hear (minutes / 15 s)
    minutes: float = Field(ge=0, le=60)  # what the comparison needs, at most
    inr_per_minute: float = Field(default=0.0, ge=0)
    inr_max: float = Field(default=0.0, ge=0)  # the most it may cost (shown before his YES)
    seconds: float = Field(default=0.0, ge=0)  # Google seconds used (15 s steps)
    clips: int = Field(default=0, ge=0)  # clips Google heard
    yes_at: AwareDatetime | None = None


Heard = dict[str, str]


class SessionDoc(_Frozen):
    session_id: str = Field(pattern=SESSION_ID)
    state: SessionState = SessionState.RECORDING
    started_at: AwareDatetime
    prompts: tuple[Prompt, ...] = Field(min_length=1, max_length=PROMPTS_MAX)
    keys: dict[str, str] = Field(default_factory=dict, max_length=PROMPTS_MAX)
    own: tuple[str, ...] = Field(default=(), max_length=PROMPTS_MAX)  # ids reading his words
    typed: tuple[str, ...] = Field(default=(), max_length=WORDS_KEPT)  # new words he gave
    done: tuple[str, ...] = Field(default=(), max_length=PROMPTS_MAX)
    browser: Heard = Field(default_factory=dict, max_length=PROMPTS_MAX)
    google: Heard = Field(default_factory=dict, max_length=PROMPTS_MAX)
    google_ms: dict[str, int] = Field(default_factory=dict, max_length=PROMPTS_MAX)
    compare: Compare
    job_id: str | None = Field(default=None, pattern=JOB_ID)
    words_added: tuple[str, ...] = Field(default=(), max_length=WORDS_KEPT)
    reason: str = Field(default="", max_length=REASON_CHARS)  # plain words when FAILED
    scored_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = {p.id for p in self.prompts}
        if len(ids) != len(self.prompts):
            raise ValueError("a prompt id is used once")
        named = [*self.keys, *self.own, *self.done, *self.browser, *self.google, *self.google_ms]
        if not set(named) <= ids:
            raise ValueError("every id is one of the session's prompts")
        if len(set(self.done)) != len(self.done):
            raise ValueError("a prompt is recorded once")
        texts = [*self.keys.values(), *self.browser.values(), *self.google.values()]
        if any(len(t) > HEARD_CHARS for t in texts):
            raise ValueError("a transcript is kept short")
        return self

    def prompt(self, prompt_id: str) -> Prompt | None:
        return next((p for p in self.prompts if p.id == prompt_id), None)

    def next_prompt(self) -> str | None:
        done = set(self.done)
        return next((p.id for p in self.prompts if p.id not in done), None)


class SessionStore(Protocol):
    async def get(self, uid: str) -> SessionDoc | None: ...

    async def save(self, uid: str, doc: SessionDoc) -> SessionDoc: ...

    async def update(
        self, uid: str, change: Callable[[SessionDoc], SessionDoc]
    ) -> SessionDoc | None: ...  # None: there is no session (nothing written)

    async def delete(self, uid: str) -> bool: ...


def decode(doc: Any) -> SessionDoc | None:
    if not isinstance(doc, dict):
        return None
    body = {k: v for k, v in doc.items() if k not in _STAMPS}
    try:
        return SessionDoc.model_validate(body)
    except ValidationError as exc:
        log.warning("voice session unreadable: none used", extra={"errors": exc.error_count()})
        return None


def encode(uid: str, doc: SessionDoc) -> dict[str, Any]:
    at = datetime.now(UTC).isoformat()
    return {"user_id": uid, **doc.model_dump(mode="json"), "updated_at": at}


def _checked(uid: str) -> str:
    if not safe_id(uid):
        raise ValueError("invalid user id")
    return uid


class DocSessionStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}{COLLECTION}"

    def _path(self, uid: str) -> str:
        return f"{self._col}/{_checked(uid)}"

    async def get(self, uid: str) -> SessionDoc | None:
        return decode(await self._d.get(self._path(uid)))

    async def save(self, uid: str, doc: SessionDoc) -> SessionDoc:
        path = self._path(uid)

        async def fn(tx: DocTx) -> SessionDoc:
            tx.set(path, encode(uid, doc))
            return doc

        return await self._d.transaction(fn)

    async def update(
        self, uid: str, change: Callable[[SessionDoc], SessionDoc]
    ) -> SessionDoc | None:
        path = self._path(uid)

        async def fn(tx: DocTx) -> SessionDoc | None:
            cur = decode(await tx.get(path))
            if cur is None:
                return None
            new = change(cur)
            tx.set(path, encode(uid, new))
            return new

        return await self._d.transaction(fn)

    async def delete(self, uid: str) -> bool:
        path = self._path(uid)

        async def fn(tx: DocTx) -> bool:
            found = await tx.get(path) is not None
            if found:
                tx.delete(path)
            return found

        return await self._d.transaction(fn)


class MemorySessionStore:
    """Tests: the same contract, in this process."""

    def __init__(self) -> None:
        self._kept: dict[str, SessionDoc] = {}

    async def get(self, uid: str) -> SessionDoc | None:
        return self._kept.get(_checked(uid))

    async def save(self, uid: str, doc: SessionDoc) -> SessionDoc:
        self._kept[_checked(uid)] = doc
        return doc

    async def update(
        self, uid: str, change: Callable[[SessionDoc], SessionDoc]
    ) -> SessionDoc | None:
        cur = await self.get(uid)
        return None if cur is None else await self.save(uid, change(cur))

    async def delete(self, uid: str) -> bool:
        return self._kept.pop(_checked(uid), None) is not None


__all__ = [
    "COLLECTION",
    "HEARD_CHARS",
    "Compare",
    "CompareMode",
    "DocSessionStore",
    "MemorySessionStore",
    "SessionDoc",
    "SessionStore",
    "decode",
    "encode",
]
