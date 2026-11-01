# tests/google_fakes.py — fake Google REST transport + token helpers shared by the Google tests.
# A plain module (not conftest) so test files can import it under pytest's default import mode.
from __future__ import annotations

import httpx

from jarvis.integrations.vault import GoogleTokens

GOOGLE_NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z
GOOGLE_UID = "u_owner"
GOOGLE_EMAIL = "akash@example.com"


class FakeGoogle:
    """Scriptable httpx transport: records every request, answers from `routes`. A route with
    several responses serves them in order and repeats the last one."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, list[httpx.Response]] = {}

    def on(self, method: str, url: str, *responses: httpx.Response) -> None:
        self.routes.setdefault(f"{method} {url}", []).extend(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.scheme}://{request.url.host}{request.url.path}"
        queue = self.routes.get(key)
        if not queue:
            return httpx.Response(599, json={"error": f"unscripted {key}"})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def sent(self, method: str, path_suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(path_suffix)]


def google_tokens(expires_at: float = GOOGLE_NOW + 3600, **over: object) -> GoogleTokens:
    base: dict[str, object] = {
        "email": GOOGLE_EMAIL,
        "access_token": "old-access",
        "refresh_token": "the-refresh",
        "expires_at": expires_at,
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    base.update(over)
    return GoogleTokens.model_validate(base)
