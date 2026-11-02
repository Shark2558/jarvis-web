# evals/contacts_whatsapp/fake_people.py
"""An in-memory Google People API (people.searchContacts) behind httpx.MockTransport.

Shared by the unit tests (tests/people_fakes.py imports it by path) and the eval harness. It
behaves like the real API where that matters (verified 2026-11-03 against
developers.google.com/people/api/rest/v1/people/searchContacts and …/v1/contacts):
`GET /v1/people:searchContacts` with `query` (prefix phrases: "foo name" matches "fo", "nam",
"foo n" but not "oo n") over names, nicknames, email addresses, phone numbers and organisations;
`readMask` is required (400 without); `pageSize` defaults to 10 and is capped at 30; the answer is
`{"results": [{"person": {...}}]}` and only the masked fields come back. Search uses a lazy cache:
a client sends an empty-query warm-up first. `cold_searches` makes that many searches after a
warm-up come back empty (the cache not caught up yet).

Every request is recorded; the eval asserts on what this fake RECEIVED (People API is read only:
anything but a GET is a failure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

SEARCH_PATH = "/v1/people:searchContacts"
MAX_PAGE = 30
DEFAULT_PAGE = 10
SEARCHED = ("names", "nicknames", "emailAddresses", "phoneNumbers", "organizations")


def person(
    rid: str,
    name: str,
    *,
    phones: list[str | tuple[str, str]] = (),  # type: ignore[assignment]
    emails: list[str] = (),  # type: ignore[assignment]
) -> dict[str, Any]:
    """A contact. A phone is "value" (no canonical form) or (value, canonicalForm)."""
    out: dict[str, Any] = {
        "resourceName": f"people/{rid}",
        "etag": "e",
        "names": [{"displayName": name, "metadata": {"primary": True}}] if name else [],
    }
    if emails:
        out["emailAddresses"] = [{"value": e, "type": "home"} for e in emails]
    if phones:
        nums = []
        for p in phones:
            value, canon = (p, None) if isinstance(p, str) else p
            entry: dict[str, Any] = {"value": value, "type": "mobile"}
            if canon:
                entry["canonicalForm"] = canon
            nums.append(entry)
        out["phoneNumbers"] = nums
    return out


def _texts(p: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in SEARCHED:
        for item in p.get(key) or []:
            for k in ("displayName", "value", "name", "canonicalForm"):
                v = item.get(k)
                if isinstance(v, str):
                    out.append(v.casefold())
    return out


def _prefix_phrase(value: str, query: str) -> bool:
    starts = [0] + [i + 1 for i, c in enumerate(value) if c in " @.-+"]
    return any(value.startswith(query, s) for s in starts)


@dataclass
class FakePeople:
    contacts: list[dict[str, Any]] = field(default_factory=list)
    cold_searches: int = 0
    fail_status: int | None = None  # every call answers this (403 → API switched off)
    requests: list[httpx.Request] = field(default_factory=list)
    _cold_left: int = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "GET" or request.url.path != SEARCH_PATH:
            return httpx.Response(404, json={"error": {"code": 404}})
        if self.fail_status == 403:
            reason = {"reason": "accessNotConfigured"}
            return httpx.Response(403, json={"error": {"code": 403, "errors": [reason]}})
        if self.fail_status is not None:
            return httpx.Response(self.fail_status, json={"error": {"code": self.fail_status}})
        q = request.url.params
        if not q.get("readMask"):
            return httpx.Response(400, json={"error": {"code": 400}})
        query = (q.get("query") or "").casefold().strip()
        if not query:  # the warm-up
            self._cold_left = self.cold_searches
            return httpx.Response(200, json={})
        if self._cold_left > 0:
            self._cold_left -= 1
            return httpx.Response(200, json={})
        size = int(q.get("pageSize") or 0) or DEFAULT_PAGE
        size = min(size, MAX_PAGE)
        mask = set(q["readMask"].split(","))
        hits = [p for p in self.contacts if any(_prefix_phrase(t, query) for t in _texts(p))]
        people = [
            {k: v for k, v in p.items() if k in mask or k in ("resourceName", "etag")}
            for p in hits[:size]
        ]
        return httpx.Response(
            200, json={"results": [{"person": p} for p in people]} if people else {}
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def searches(self) -> list[str]:
        """The queries asked, in order ("" is a warm-up)."""
        return [r.url.params.get("query", "") for r in self.requests]

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]
