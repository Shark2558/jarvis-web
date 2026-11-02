# tests/web_fakes.py — a scriptable fake Tavily (httpx transport) for the web-search tests.
# A plain module (not conftest) so test files can import it under pytest's default import mode.
from __future__ import annotations

import json
from typing import Any

import httpx

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


def hit(n: int, *, host: str = "example.com", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": f"Result {n}",
        "url": f"https://{host}/page{n}",
        "content": f"Snippet number {n}.",
        "score": 0.9 - n / 100,
        "published_date": "2026-10-30",
    }
    base.update(over)
    return base


class FakeTavily:
    """Records every request; answers /search with `results` and /extract from `pages`.
    `status` (with optional `body`) makes every call fail with that HTTP status instead."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.results: list[dict[str, Any]] = [hit(i) for i in range(1, 6)]
        self.pages: dict[str, str] = {}
        self.status: int | None = None
        self.body: bytes | None = None
        self.raw_search: bytes | None = None  # served verbatim instead of the JSON results

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return httpx.Response(self.status, content=self.body or b'{"detail":"vendor text"}')
        url = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        payload = json.loads(request.content or b"{}")
        if url == SEARCH_URL:
            if self.raw_search is not None:
                return httpx.Response(200, content=self.raw_search)
            limit = int(payload.get("max_results", 5))
            return httpx.Response(
                200,
                json={
                    "query": payload.get("query"),
                    "answer": None,
                    "images": [],
                    "results": self.results[:limit],
                    "response_time": "0.42",
                    "usage": {"credits": 1},
                    "request_id": "req-1",
                },
            )
        if url == EXTRACT_URL:
            wanted = payload.get("urls") or []
            target = wanted[0] if isinstance(wanted, list) and wanted else str(wanted)
            if target in self.pages:
                return httpx.Response(
                    200,
                    json={
                        "results": [{"url": target, "raw_content": self.pages[target]}],
                        "failed_results": [],
                        "response_time": 0.3,
                        "usage": {"credits": 1},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "results": [],
                    "failed_results": [{"url": target, "error": "vendor says: blocked"}],
                    "response_time": 0.3,
                },
            )
        return httpx.Response(404, json={"detail": "unknown"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def bodies(self, path: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.requests:
            if r.url.path == path:
                out.append(json.loads(r.content))
        return out

    def queries(self) -> list[str]:
        return [str(b.get("query")) for b in self.bodies("/search")]

    def extracted(self) -> list[str]:
        return [str((b.get("urls") or [""])[0]) for b in self.bodies("/extract")]
