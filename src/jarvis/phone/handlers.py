# src/jarvis/phone/handlers.py
"""Part C's two door handlers (R7 D6, D16; `MobilePart.services["door"]`): `hello` and `inbox`.

A handler sees only a request that passed every check of the door (`PhoneRequest`: the exact
signed bytes, the phone and its owner). Its body must ALSO be the one JSON form
(`contract.canonical_json`): the bytes were signed as written, and a second way of writing the same
payload (spaces, a repeated key) is refused, never guessed at.

- `hello` {v, app_version, version_code, model, android, can{...}}: records what the app said it
  may do and answers with its settings and, for the SMS screen, `sos: {enabled, label, contacts:
  [{label, phone}]}` from what Part D offers (`services["sos_contacts"]` of the body part). When
  Part D cannot say who they are (no token key, the store unreadable, the part left out) `sos` is
  left OUT of the answer, so the phone keeps the numbers it holds (I1; phone-contract section 2).
- `inbox`: the first line {v, name, mime, sha256, bytes}, one `\\n`, then the file. The file must be
  what its first line says (size and SHA-256, compared in constant time; PDF, JPEG or PNG, at most
  10 MB). It goes to `VaultIntake.intake(source="digilocker")`: an item in "Check details", exactly
  like the Drive path. The file's name is checked for shape and then dropped: never stored, logged
  or answered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.mobile import contract
from jarvis.mobile.ports import PhoneReply, PhoneRequest
from jarvis.phone.store import PhoneStore
from jarvis.vault.ports import MAX_FILE_BYTES, VAULT_MIMES

log = get_logger(__name__)

FIRST_LINE_MAX = 1024
RETRY_CODES = frozenset({"unavailable", "vault_full", "busy"})  # about now, not about the file
CONTACTS_MAX = 5
SOS_SEAM = "sos_contacts"  # Part D's service on the body part (INTEGRATION-C.md, Needs I1)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
TOUCH_EVERY_S = 60.0
VAULT_OFF = "The vault isn't available on this server, so the file was not added."
REJECTED = {"error": "input_rejected"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Can(_Strict):
    notifications: bool
    health_read: bool
    health_background: bool
    location: bool
    folder: bool
    tile: bool


class Hello(_Strict):
    v: Literal[1]
    app_version: str = Field(pattern=r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
    version_code: int = Field(ge=0, le=10**9)
    model: str = Field(pattern=r"^[A-Za-z0-9 ._-]{1,40}$")
    android: int = Field(ge=0, le=99)
    can: Can


class InboxHead(_Strict):
    v: Literal[1]
    name: str = Field(min_length=1, max_length=200)
    mime: str = Field(max_length=40)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_FILE_BYTES)


def _label(value: Any) -> str:
    return " ".join(_CONTROL.sub("", value).split())[:40] if isinstance(value, str) else ""


def _number(value: Any) -> str:
    """A phone number as the SMS screen dials it: `+` and digits only, at most 16."""
    if not isinstance(value, str):
        return ""
    digits = "".join(c for c in value if c.isascii() and c.isdigit())
    plus = "+" if value.strip().startswith("+") else ""
    return (plus + digits)[:16] if digits else ""


def canonical(raw: bytes, model: type[_Strict]) -> _Strict | None:
    """The payload, only when `raw` is exactly its one JSON form."""
    try:
        data = json.loads(raw.decode("utf-8"))
        parsed = model.model_validate(data)
        same = contract.canonical_json(data) == raw
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError, ValidationError):
        return None
    return parsed if same else None


class DoorHandlers:
    def __init__(
        self,
        s: Settings,
        store: PhoneStore,
        *,
        state: Callable[[str], Any],
        clock: Callable[[], float],
    ) -> None:
        self._s, self._store, self._state, self._clock = s, store, state, clock
        self._touched: dict[str, float] = {}

    def services(self) -> dict[str, Callable[[PhoneRequest], Awaitable[PhoneReply]]]:
        return {"hello": self.hello, "inbox": self.inbox}

    # ---- hello --------------------------------------------------------------------------------
    async def hello(self, req: PhoneRequest) -> PhoneReply:
        body = canonical(req.body, Hello)
        if not isinstance(body, Hello):
            return PhoneReply(422, REJECTED)
        changes = {
            "app_version": body.app_version,
            "version_code": body.version_code,
            "android": body.android,
            "model": body.model,
            "can": body.can.model_dump(),
            "last_seen": req.at,
        }
        await self._store.update_phone(req.uid, req.device_id, changes)
        self._touched[req.device_id] = req.at
        answer: dict[str, Any] = {
            "v": 1,
            "device_id": req.device_id,
            "settings": self._settings(),
        }
        sos = await self._sos(req.uid)
        if sos is not None:  # unknown: left out, so the phone keeps the numbers it has
            answer["sos"] = {"enabled": self._s.sos_enabled, **sos}
        return PhoneReply(200, answer)

    def _settings(self) -> dict[str, Any]:
        s = self._s
        return {
            "app_lock_minutes": s.app_lock_minutes,
            "watch_enabled": s.watch_enabled,
            "sos_countdown_s": s.sos_countdown_s,
            "health_every_h": 6,
            "inbox_every_min": 60,
            "inbox_per_run": 3,
            "inbox_max_bytes": MAX_FILE_BYTES,
        }

    async def _sos(self, uid: str) -> dict[str, Any] | None:
        """{label, contacts} for the SMS screen (phone-contract section 4): what Part D offers as
        `services["sos_contacts"]`, an `async (uid) -> {label, contacts: [{label, phone}]}` (a bare
        list of contacts is read too). Labels are plain text of at most 40 characters; a number
        keeps only `+` and digits; a contact with no number is left out (Telegram only). None when
        Part D cannot say (no seam, or it raised: SosOff, SosUnavailable): not "no contacts"."""
        parts: Mapping[str, Any] = self._state("r7_parts") or {}
        body = parts.get("body")
        read = body.services.get(SOS_SEAM) if body is not None else None
        if not callable(read):
            log.warning("sos contacts seam missing", extra={"seam": SOS_SEAM})
            return None
        try:
            got = await read(uid)
        except Exception as exc:  # noqa: BLE001 - the hello still answers; the phone keeps its list
            log.warning("sos contacts unreadable", extra={"error": type(exc).__name__})
            return None
        whole = got if isinstance(got, Mapping) else {"contacts": got}
        out = []
        for c in list(whole.get("contacts") or [])[:CONTACTS_MAX]:
            if not isinstance(c, Mapping):
                continue
            label, number = _label(c.get("label")), _number(c.get("phone"))
            if label and number:
                out.append({"label": label, "phone": number})
        return {"label": _label(whole.get("label")), "contacts": out}

    # ---- inbox (D16) --------------------------------------------------------------------------
    async def inbox(self, req: PhoneRequest) -> PhoneReply:
        head_raw, sep, data = req.body.partition(b"\n")
        if not sep or len(head_raw) > FIRST_LINE_MAX:
            return PhoneReply(422, REJECTED)
        head = canonical(head_raw, InboxHead)
        if not isinstance(head, InboxHead) or head.mime not in VAULT_MIMES:
            return PhoneReply(422, REJECTED)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != head.bytes or not hmac.compare_digest(digest, head.sha256):
            return PhoneReply(422, REJECTED)
        vault = self._state("vault")
        if vault is None:
            return PhoneReply(503, {"error": "vault_off", "detail": VAULT_OFF})
        result = await vault.intake(req.uid, data, source="digilocker")
        log.info("phone inbox", extra={"status": result.status, "code": result.code})
        if result.status in ("added", "duplicate"):
            return PhoneReply(200, {"status": result.status})
        if result.code in RETRY_CODES:
            return PhoneReply(503, {"status": "skipped", "code": result.code})
        return PhoneReply(422, {"status": "skipped", "code": result.code or "skipped"})

    async def seen(self, req: PhoneRequest) -> None:
        """Last seen, for every admitted request, at most once a minute (hello writes it too)."""
        if req.route == "hello" or req.at - self._touched.get(req.device_id, 0.0) < TOUCH_EVERY_S:
            return
        try:
            await self._store.update_phone(req.uid, req.device_id, {"last_seen": req.at})
        except Exception as exc:  # noqa: BLE001 - a cosmetic "last seen" never refuses a request
            log.warning("phone last-seen write failed", extra={"error": type(exc).__name__})
            return  # not marked as written: the next request tries again
        self._touched[req.device_id] = req.at
        if len(self._touched) > 64:
            self._touched.pop(next(iter(self._touched)))


__all__ = ["FIRST_LINE_MAX", "Can", "DoorHandlers", "Hello", "InboxHead", "canonical"]
