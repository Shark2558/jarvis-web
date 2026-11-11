# tests/r11_fakes_a.py -- R11 Part A's own fakes (BRIEF-COMMON.md: unique per part). Built on I0's
# shared `r11_fakes` (Clock, FakeNotifier, ctx), never a copy of them. No real personal data:
# example.com addresses, obviously fake UPI IDs (`test@okfake`), made-up contacts.
#
# - `keyring()`: a fixed test keyring (32 distinct bytes, never a real key).
# - `today_ctx(...)`: I0's `ctx("today")` with a keyring, Google, permissions or pending sources.
# - `FakePeople`: the People API's `people/me/connections` for a linked owner, over httpx's mock
#   transport; it records every request (so a test can prove a denied row asked nothing).
# - `DenyRules` / `BrokenRules`: the owner's permission rows saying Never, or unreadable.
# - `gateway_rig(part)`: a real Gateway with the part's tools, an approval gate and an audit log.
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr
from r11_fakes import UID, Clock, FakeNotifier, ctx

from jarvis.core.guardrails import ConfirmationGate
from jarvis.helpers.ports import HelperContext, HelperPart, PendingSource
from jarvis.integrations.google import CONTACTS_SCOPE, GoogleConnector
from jarvis.integrations.vault import GoogleTokens, MemoryTokenStore
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

IST = ZoneInfo("Asia/Kolkata")
TEST_ROOT = bytes(range(1, 33))  # 32 distinct bytes: a test key, never a real one
FAKE_UPI = "test@okfake"
OTHER_UPI = "mallory@okfake"
CORE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def keyring() -> Keyring:
    return Keyring(TEST_ROOT)


def person(rid: str, name: str, month: int, day: int, year: int | None = 1990) -> dict[str, Any]:
    date: dict[str, int] = {"month": month, "day": day}
    if year is not None:
        date["year"] = year
    return {
        "resourceName": f"people/{rid}",
        "names": [{"displayName": name, "metadata": {"primary": True}}],
        "birthdays": [{"date": date, "text": f"{month}/{day}/{year or ''}"}],
    }


@dataclass
class FakePeople:
    """`GET people/me/connections`: `people` split into pages of `page`; `status` to fail."""

    people: list[dict[str, Any]] = field(default_factory=list)
    page: int = 1000
    status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        token = request.url.params.get("pageToken")
        start = int(token) if token else 0
        chunk = self.people[start : start + self.page]
        body: dict[str, Any] = {"connections": chunk, "totalPeople": len(self.people)}
        if start + self.page < len(self.people):
            body["nextPageToken"] = str(start + self.page)
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def connector(
    fake: FakePeople, *, contacts: bool = True, linked: bool = True
) -> GoogleConnector:
    store = MemoryTokenStore()
    if linked:
        await store.put(
            UID,
            GoogleTokens(
                email="owner@example.com",
                access_token=SecretStr("acc"),
                refresh_token=SecretStr("ref"),
                expires_at=4_000_000_000.0,
                scopes=[*CORE_SCOPES, *([CONTACTS_SCOPE] if contacts else [])],
            ),
        )
    return GoogleConnector(store, client_id="cid", client_secret=SecretStr("s"), http=fake.client())


class DenyRules:
    """The owner's rows: Never for tools matching `pattern`."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern=self.pattern, effect=Effect.DENY, source="owner:test")]


class BrokenRules:
    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        raise RuntimeError("the permissions store is down")


def today_ctx(
    *,
    keys: bool = True,
    google: GoogleConnector | None = None,
    rules: object | None = None,
    pending: tuple[PendingSource, ...] = (),
    clock: Clock | None = None,
    notifier: FakeNotifier | None = None,
    **over: Any,
) -> tuple[HelperContext, FakeNotifier, MemoryDocs, Clock]:
    kw: dict[str, Any] = {}
    if clock is not None:
        kw["clock"] = clock
    if notifier is not None:
        kw["notifier"] = notifier
    c, n, docs, clk = ctx("today", pending=pending, **kw, **over)
    c = dataclasses.replace(
        c,
        keyring=keyring() if keys else None,
        google=google,
        permissions=(lambda: rules),  # type: ignore[arg-type,return-value]
    )
    return c, n, docs, clk


@dataclass
class Rig:
    gateway: Gateway
    audit: AuditLog
    scope: str = f"{UID}:s1"


def gateway_rig(part: HelperPart, *, rules: object | None = None) -> Rig:
    reg = ToolRegistry()
    for tool in part.tools:
        reg.register(tool)
    audit = AuditLog()
    gw = Gateway(
        registry=reg,
        policy=Policy(),
        gate=ConfirmationGate(),
        audit=audit,
        rules=rules,  # type: ignore[arg-type]
    )
    return Rig(gw, audit)


def every_text(docs: MemoryDocs) -> str:
    """Everything stored, as one string (a needle search over every document)."""
    return repr(docs._data)  # noqa: SLF001 - the fake's own store, for needle checks


def at(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    """A wall time in the owner's zone (Asia/Kolkata), as an aware UTC time."""
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(UTC)


__all__ = [
    "FAKE_UPI",
    "OTHER_UPI",
    "BrokenRules",
    "DenyRules",
    "IST",
    "FakePeople",
    "Rig",
    "at",
    "connector",
    "every_text",
    "gateway_rig",
    "keyring",
    "person",
    "today_ctx",
]
