# src/jarvis/buildbook/owner.py
"""What the owner keeps beside his sealed build books (R6 D16, D9; builder B; Layer 7).

    {prefix}book_settings/{uid}  creator_name, show_voice, talk_on, allow_training_brain,
                                 updated_at
    {prefix}book_tickets/{uid}   {grants: [], tickets: [{mac, item: <release id>,
                                 fid: "source", until}]}

Book settings (D16): the creator's name for the closing credit (D13 `{by}`; empty = "my owner and
creator"), the show's voice (cloud | browser), the talk-through on or off, and whether the
talk-through may use a brain that trains on what it is told (off). A patch is checked before
anything is written (`SettingsRejected`, plain words that never echo the input) and applied in a
transaction; a stored field that isn't valid reads as its default, field by field. `get` lets a
storage failure through (the panel must not show defaults as if they were saved);
`get_or_default` never raises and falls back to the safe defaults (for the talk lane: no
training brain).

Download tickets (D9): the R2 `UnlockStore` (vault/unlock.py) on its own collection. A ticket is 32
random bytes shown once and stored only as an HMAC (keyring purpose `tickets`); it lives 60 s, is
bound to the owner (its document) and one release's source snapshot, and is removed the moment it
is taken. A book ticket is issued only after the route has checked a live OWNER book session, so
this store holds no unlock grants of its own.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from jarvis.buildbook.lines import CREATOR_MAX
from jarvis.buildbook.model import FileKind
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.sections import Frozen
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.vault.unlock import MAX_TICKETS, TICKET_S, Grant, Ticket, UnlockStore
from jarvis.voice.settings import clean_phrase

log = get_logger(__name__)

ShowVoice = Literal["cloud", "browser"]
VOICES: tuple[ShowVoice, ...] = ("cloud", "browser")
NAME_RAW_MAX = 400  # longer than this is refused before any cleaning work
BAD_NAME = (
    f"The creator name needs 1 to {CREATOR_MAX} characters with at least one letter, and may use "
    "only letters, numbers, spaces and - ' . &"
)
DOWN = "Book settings can't be read right now."


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SettingsRejected(BookError):
    """A Book settings change that can't be saved (422); the words never echo the input."""


class BookSettings(Frozen):
    creator_name: str = Field(default="", max_length=CREATOR_MAX)
    show_voice: ShowVoice = "cloud"
    talk_on: bool = True
    allow_training_brain: bool = False


class BookSettingsPatch(BaseModel):
    """PUT /v1/book/settings: any subset, strict types, nothing else."""

    model_config = ConfigDict(extra="forbid")

    creator_name: StrictStr | None = Field(default=None, max_length=NAME_RAW_MAX)
    show_voice: ShowVoice | None = None
    talk_on: StrictBool | None = None
    allow_training_brain: StrictBool | None = None


def _name(raw: str) -> str:
    """The name as stored: "" clears it; anything else must pass the voice phrase rules."""
    if not raw.strip():
        return ""
    cleaned = clean_phrase(raw)
    if cleaned is None or len(cleaned) > CREATOR_MAX:
        raise SettingsRejected(BAD_NAME + ".")
    return cleaned


def apply(cur: BookSettings, patch: BookSettingsPatch) -> BookSettings:
    """The settings after `patch`, or SettingsRejected."""
    changes: dict[str, Any] = patch.model_dump(exclude_none=True)
    if "creator_name" in changes:
        changes["creator_name"] = _name(changes["creator_name"])
    return cur.model_copy(update=changes)


def decode(doc: Any) -> BookSettings:
    if not isinstance(doc, dict):
        return BookSettings()
    name, voice = doc.get("creator_name"), doc.get("show_voice")
    talk, train = doc.get("talk_on"), doc.get("allow_training_brain")
    good_name = clean_phrase(name) if isinstance(name, str) else None
    return BookSettings(
        creator_name=good_name if good_name and len(good_name) <= CREATOR_MAX else "",
        show_voice=voice if voice in VOICES else "cloud",
        talk_on=talk if isinstance(talk, bool) else True,
        allow_training_brain=train if isinstance(train, bool) else False,
    )


class BookSettingsStore:
    def __init__(
        self, docs: Docs, *, prefix: str = "jarvis_", clock: Callable[[], dt.datetime] = _utcnow
    ) -> None:
        self._d = docs
        self._col = f"{prefix}book_settings"
        self._clock = clock

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> BookSettings:
        """The owner's Book settings (defaults when none are stored). BookError when storage
        fails."""
        try:
            doc = await self._d.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001
            log.error("book settings unreadable", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        return decode(doc)

    async def get_or_default(self, uid: str) -> BookSettings:
        """Never raises: the safe defaults (cloud voice, talk on, NO training brain) on failure."""
        try:
            return await self.get(uid)
        except BookError:
            return BookSettings()

    async def update(self, uid: str, patch: BookSettingsPatch) -> BookSettings:
        apply(BookSettings(), patch)  # check before touching storage
        path = self._path(uid)
        at = self._clock().isoformat()

        async def fn(tx: DocTx) -> BookSettings:
            new = apply(decode(await tx.get(path)), patch)
            tx.set(path, {**new.model_dump(), "updated_at": at})
            return new

        try:
            return await self._d.transaction(fn)
        except BookError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("book settings not saved", extra={"error": type(exc).__name__})
            raise BookError(
                "Book settings can't be saved right now. Nothing was changed."
            ) from None


class BookTickets(UnlockStore):
    """D9's single-use code-download tickets: `UnlockStore` on `{prefix}book_tickets`. Only
    `issue` and `take` apply; it holds no unlock grants (the book session is the unlock)."""

    def __init__(
        self,
        docs: Docs,
        ring: Keyring,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        super().__init__(docs, ring, minutes=1, prefix=prefix, clock=clock)
        self._col = f"{prefix}book_tickets"

    async def grant(self, uid: str) -> Grant:
        raise PermissionError("the build book is unlocked by its own session")

    async def ticket(self, uid: str, token: str, item: str | None, fid: str) -> Ticket:
        raise PermissionError("the build book is unlocked by its own session")

    async def issue(self, uid: str, rid: str, kind: FileKind = "source") -> Ticket:
        """A 60-second single-use ticket for one sealed release's file. The caller has checked a
        live owner book session and that the release is sealed."""
        now = self._clock()
        secret = secrets.token_urlsafe(32)
        row = {
            "mac": self._mac(secret),
            "item": rid,
            "fid": kind,
            "until": (now + dt.timedelta(seconds=TICKET_S)).isoformat(),
        }

        async def fn(tx: DocTx) -> None:
            _, live = self._read(await tx.get(self._path(uid)), now)
            tx.set(self._path(uid), {"grants": [], "tickets": [*live, row][-MAX_TICKETS:]})

        await self._d.transaction(fn)
        return Ticket(secret, TICKET_S)


__all__ = [
    "BAD_NAME",
    "VOICES",
    "BookSettings",
    "BookSettingsPatch",
    "BookSettingsStore",
    "BookTickets",
    "SettingsRejected",
    "ShowVoice",
    "apply",
    "decode",
]
