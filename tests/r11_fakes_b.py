# tests/r11_fakes_b.py -- R11 Part B's own fakes (docs/plans/r11-integration/BRIEF-COMMON.md: one
# fakes file per part, unique names). Built on I0's shared `r11_fakes` (imported, never copied).
#
# - `FakeFetcher`: the outside GET port; answers fixtures by URL (Open-Meteo, the SACHET feed, one
#   CAP per identifier; a missing one answers 404), records every call, can fail (no answer at
#   all) or answer 304 (with or without an ETag).
# - `FakeGmail`: the GoogleConnector's `request` for the Gmail list and metadata reads.
# - `Rules`: an owner's permission rows (the `OwnerRules` port), or one that can't be read.
# - `house_ctx(...)`: I0's `ctx("house")` with a keyring (sealed place ON) unless `keyring=False`.
# - `PLACE`: the made-up owner's place in the fixtures (Ernakulam, Kerala; not anyone's address).
from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from r11_fakes import Clock, FakeNotifier, ctx, reads_over

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.house.fetch import Fetched, FetchError, TooLarge
from jarvis.helpers.ports import HelperContext
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.policy import Effect, PolicyRule

FIX = Path(__file__).parent / "fixtures" / "r11"
PLACE = {"district": "Ernakulam", "state": "Kerala", "lat": 9.98, "lon": 76.28}
CAP_FILES = {
    "1794300000000101": "b_cap_met_severe.xml",
    "1794300000000102": "b_cap_geo_landslide.xml",
    "1794300000000103": "b_cap_other_district.xml",
    "1794300000000104": "b_cap_injection.xml",
    "1794300000000105": "b_cap_met_moderate.xml",
}


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


@dataclass
class FakeFetcher:
    """`answers`: URL (no query) -> bytes, or a callable(params) -> bytes. `caps`: CAP identifier
    -> bytes (the SACHET CAP URL). `fail`: every call raises FetchError."""

    answers: dict[str, Any] = field(default_factory=dict)
    caps: dict[str, bytes] = field(default_factory=dict)
    fail: bool = False
    not_modified: bool = False
    bare_304: bool = False  # a 304 that carries no ETag header
    etag: str | None = '"v1"'
    calls: list[tuple[str, dict[str, str], dict[str, str]]] = field(default_factory=list)

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cap: int,
        timeout_s: float,
    ) -> Fetched:
        p, h = dict(params or {}), dict(headers or {})
        self.calls.append((url, p, h))
        if self.fail:
            raise FetchError("the outside service is down")
        if "identifier" in p:
            body = self.caps.get(p["identifier"])
            if body is None:
                raise FetchError("not found", status=404)
        else:
            got = self.answers.get(url)
            if got is None:
                raise FetchError("not found")
            body = got(p) if callable(got) else got
        if self.not_modified and h.get("If-None-Match") == self.etag:
            return Fetched(304, b"", None if self.bare_304 else self.etag)
        if len(body) > cap:
            raise TooLarge("too large")
        return Fetched(200, body, self.etag)

    def urls(self) -> list[str]:
        return [u for u, _, _ in self.calls]


def sachet_fetcher(**over: Any) -> FakeFetcher:
    from jarvis.helpers.sources import SACHET_RSS_URL

    f = FakeFetcher(**over)
    f.answers.setdefault(SACHET_RSS_URL.format(feed="kerala"), fixture("b_sachet_rss.xml"))
    for gid, name in CAP_FILES.items():
        f.caps.setdefault(gid, fixture(name))
    return f


@dataclass
class FakeGmail:
    """GoogleConnector.request for Gmail: a listing and the messages by id."""

    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    down: bool = False

    async def request(
        self, user_id: str, method: str, url: str, *, params: dict[str, Any] | None = None, **_: Any
    ) -> Any:
        self.calls.append((method, url, dict(params or {})))
        if self.down:
            from jarvis.integrations.google import GoogleAPIError

            raise GoogleAPIError("Gmail is down")
        if url.endswith("/messages"):
            return {"messages": [{"id": m} for m in self.messages]}
        mid = url.rsplit("/", 1)[1]
        return self.messages[mid]


def gmail_with(*names: str) -> FakeGmail:
    import json

    msgs = [json.loads(fixture(n)) for n in names]
    return FakeGmail({m["id"]: m for m in msgs})


@dataclass
class Rules:
    """The owner's rows as policy rules (`never`: tool patterns he set to Never)."""

    never: tuple[str, ...] = ()
    broken: bool = False

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.broken:
            raise RuntimeError("permissions unreadable")
        return [PolicyRule(tool_pattern=p, effect=Effect.DENY) for p in self.never]


def keyring() -> Keyring:
    return Keyring(os.urandom(32))


def house_ctx(
    *,
    keyring_on: bool = True,
    rules: Rules | None = None,
    google: Any = None,
    clock: Clock | None = None,
    policy: bool = False,
    docs: MemoryDocs | None = None,
    **over: Any,
) -> tuple[HelperContext, FakeNotifier, MemoryDocs, Clock]:
    clock = clock or Clock()
    notifier = FakeNotifier(clock=clock, policy=policy)
    c, n, d, k = ctx("house", clock=clock, notifier=notifier, docs=docs, **over)
    c = dataclasses.replace(
        c,
        keyring=keyring() if keyring_on else None,
        google=google,
        permissions=(lambda: rules) if rules is not None else c.permissions,
        reads=reads_over(lambda: rules, c.audit, now=k) if rules is not None else c.reads,
    )
    return c, n, d, k


READ = ActionRisk.READ_ONLY

__all__ = [
    "CAP_FILES",
    "FIX",
    "PLACE",
    "READ",
    "FakeFetcher",
    "FakeGmail",
    "Rules",
    "fixture",
    "gmail_with",
    "house_ctx",
    "keyring",
    "sachet_fetcher",
]
