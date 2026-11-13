# tests/r7_fakes_d.py -- R7 Part D's fakes (docs/plans/r7-mobile.md D17-D20). Never imported from
# conftest. Made-up people, obviously fake numbers (+10000000001...), and coordinates in the open
# South Atlantic (no real place anyone lives at).
#
#   settings(**over)        Settings with a throwaway token key (watch and SOS are sealed)
#   Clock(at)               a settable clock (aware UTC)
#   PinBot                  telegram_fakes.FakeBot that can refuse one chat's message or pin
#   Notes                   a Notifier that records (uid, kind, message)
#   BrokenDocs              a store that fails every call (fail-closed paths)
#   body_world(...)         the Part D services on MemoryDocs, a PinBot and Notes
#   needles(lat_e6, lon_e6) the strings a coordinate could leave behind
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr
from telegram_fakes import FakeBot

from jarvis.config import LLMBackend, SessionBackend, Settings
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import Doc, Docs, DocTx, MemoryDocs, Op, Query
from jarvis.tools.audit import AuditLog

KEY = bytes(range(101, 133))  # 32 distinct bytes, made for these tests only
UID = "owner"
LAT_E6, LON_E6 = -12_345_678, -23_456_789  # the open South Atlantic: nobody lives there
# Made-up contacts with obviously fake numbers; Telegram ids from a made-up range
ASHA = ("Asha Example", "+10000000001", 7_000_000_001)
RAVI = ("Ravi Example", "+10000000002", 7_000_000_002)
MEERA = ("Meera Example", "+10000000003", 7_000_000_003)


def settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "env": "dev",
        "llm_backend": LLMBackend.MOCK,
        "session_backend": SessionBackend.MEMORY,
        "usd_inr_live": False,
        "token_key": SecretStr(base64.urlsafe_b64encode(KEY).decode()),
        "user_timezone": "Asia/Kolkata",
    }
    base.update(over)
    return Settings(**base)


@dataclass
class Clock:
    at: datetime = field(default_factory=lambda: datetime(2026, 11, 12, 8, 35, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.at

    def move(self, **delta: float) -> None:
        from datetime import timedelta

        self.at = self.at + timedelta(**delta)


class PinBot(FakeBot):
    """Telegram, faked: `refuse_text` / `refuse_pin` are chat ids whose message / pin fails."""

    def __init__(self, username: str = "jarvis_test_bot") -> None:
        super().__init__(username)
        self.refuse_text: set[int] = set()
        self.refuse_pin: set[int] = set()

    def _reply(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        chat = payload.get("chat_id")
        if method == "sendMessage" and chat in self.refuse_text:
            return {"ok": False, "error_code": 403, "description": "Forbidden: VENDOR TEXT"}
        if method == "sendLocation" and chat in self.refuse_pin:
            return {"ok": False, "error_code": 400, "description": "Bad Request: VENDOR TEXT"}
        return super()._reply(method, payload)

    def to(self, chat: int, method: str = "sendMessage") -> list[dict[str, Any]]:
        return [p for p in self.of(method) if p.get("chat_id") == chat]


class Notes:
    """A Notifier that records what the owner was told."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        if self.fail:
            raise RuntimeError("notifier down")
        self.sent.append((uid, signal.kind, message))
        return Delivery(action="ring", reason="test", telegram=True)

    def kinds(self) -> list[str]:
        return [k for _, k, _ in self.sent]


class BrokenDocs(Docs):
    async def get(self, path: str) -> Doc | None:
        raise RuntimeError("store down")

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        raise RuntimeError("store down")

    async def write(self, ops: Sequence[Op]) -> None:
        raise RuntimeError("store down")

    async def transaction(self, fn: Callable[[DocTx], Awaitable[Any]]) -> Any:
        raise RuntimeError("store down")


def needles(lat_e6: int = LAT_E6, lon_e6: int = LON_E6) -> list[str]:
    """Every way a coordinate pair could be written down: micro-degrees, degrees, a maps link."""
    lat, lon = abs(lat_e6), abs(lon_e6)
    return [
        str(lat),
        str(lon),
        f"{lat // 1_000_000}.{lat % 1_000_000:06d}",
        f"{lon // 1_000_000}.{lon % 1_000_000:06d}",
        f"{lat / 1e6:.4f}",
        f"{lon / 1e6:.4f}",
    ]


def everything_written(docs: MemoryDocs, audit: AuditLog, extra: Sequence[str] = ()) -> str:
    """Every document, every audit entry and anything else given, as one text to scan."""
    import json

    rows = [json.dumps(d, default=str) for d in docs._data.values()]  # noqa: SLF001 - a test twin
    rows += [e.model_dump_json() for e in audit._entries]  # noqa: SLF001
    rows += [str(p) for p in docs._data]  # noqa: SLF001 - the addresses of documents too
    return "\n".join([*rows, *extra])


__all__ = [
    "ASHA",
    "KEY",
    "LAT_E6",
    "LON_E6",
    "MEERA",
    "RAVI",
    "UID",
    "BrokenDocs",
    "Clock",
    "Notes",
    "PinBot",
    "everything_written",
    "needles",
    "settings",
]
