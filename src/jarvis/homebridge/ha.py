# src/jarvis/homebridge/ha.py
"""The bridge's Home Assistant client (R3 D3, D6). Ships in the home kit.

The long-lived token belongs to a dedicated NON-admin Home Assistant user, lives only in
`bridge.env`, goes only in the `Authorization` header to the configured Home Assistant address and
is never logged, returned or sent to JARVIS. Calls are `GET /api/states` and
`POST /api/services/<domain>/<service>` with the bounded data `jarvis.home.classes.service_call`
builds. Errors carry a short code, never Home Assistant's text. Redirects are off; replies are
capped at 4 MB.

Deviation from the plan (said in the report): hazard sensors are polled over REST every 10 seconds
instead of watched over the WebSocket, so the bridge needs no WebSocket library.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

TIMEOUT_S = 8.0
MAX_BYTES = 4 * 1024 * 1024
_SERVICE_PART = re.compile(r"[a-z_]{1,32}")


class HAError(Exception):
    """`code` is unreachable | unauthorised | refused | bad_reply (never HA's own text)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HAClient:
    def __init__(self, url: str, token: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._token = token
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)

    @property
    def linked(self) -> bool:
        return bool(self._token)

    def __repr__(self) -> str:
        return "HAClient(<hidden>)"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, json: object | None = None) -> Any:
        if not self._token:
            raise HAError("unauthorised")
        try:
            resp = await self._http.request(
                method,
                self._url + path,
                json=json,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError:
            raise HAError("unreachable") from None
        if resp.status_code in (401, 403):
            raise HAError("unauthorised")
        if resp.status_code >= 300 or len(resp.content) > MAX_BYTES:
            raise HAError("refused")
        try:
            return resp.json()
        except ValueError:
            raise HAError("bad_reply") from None

    async def ping(self) -> bool:
        try:
            await self._request("GET", "/api/")
        except HAError:
            return False
        return True

    async def states(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/states")
        if not isinstance(data, list):
            raise HAError("bad_reply")
        return [row for row in data if isinstance(row, dict)]

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        if not _SERVICE_PART.fullmatch(domain) or not _SERVICE_PART.fullmatch(service):
            raise HAError("refused")
        await self._request("POST", f"/api/services/{domain}/{service}", data)


__all__ = ["HAClient", "HAError"]
