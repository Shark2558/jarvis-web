# evals/web/fake_tavily.py
"""An in-memory Tavily for the slice 10 B evals: answers POST /search from `results` and POST
/extract from `pages` over an httpx MockTransport, and records every request, so the gates are
ASSERTED ON WHAT TAVILY RECEIVED (queries sent, pages fetched), not on what the model said."""

from __future__ import annotations

import json
from typing import Any

import httpx

SEARCH_PATH = "/search"
EXTRACT_PATH = "/extract"


def hit(n: int, *, host: str = "news.example", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": f"Report {n} on the topic",
        "url": f"https://{host}/story-{n}",
        "content": f"Fact number {n} about the topic, reported on 30 October 2026.",
        "score": round(0.95 - n / 50, 3),
        "published_date": "2026-10-30",
    }
    base.update(over)
    return base


class FakeTavily:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.results: list[dict[str, Any]] = [hit(i) for i in range(1, 6)]
        self.pages: dict[str, str] = {}

    def reset(self) -> None:
        self.requests.clear()
        self.results = [hit(i) for i in range(1, 6)]
        self.pages = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content or b"{}")
        if request.url.path == SEARCH_PATH:
            limit = int(body.get("max_results", 5))
            return httpx.Response(
                200,
                json={
                    "query": body.get("query"),
                    "answer": None,
                    "images": [],
                    "results": self.results[:limit],
                    "response_time": "0.2",
                    "usage": {"credits": 1},
                },
            )
        if request.url.path == EXTRACT_PATH:
            url = (body.get("urls") or [""])[0]
            if url in self.pages:
                return httpx.Response(
                    200,
                    json={
                        "results": [{"url": url, "raw_content": self.pages[url]}],
                        "failed_results": [],
                        "usage": {"credits": 1},
                    },
                )
            return httpx.Response(
                200, json={"results": [], "failed_results": [{"url": url, "error": "blocked"}]}
            )
        return httpx.Response(404, json={"detail": "unknown"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def _bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]

    def queries(self) -> list[str]:
        return [str(b.get("query", "")) for b in self._bodies(SEARCH_PATH)]

    def extracted(self) -> list[str]:
        return [str((b.get("urls") or [""])[0]) for b in self._bodies(EXTRACT_PATH)]
