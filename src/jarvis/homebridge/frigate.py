# src/jarvis/homebridge/frigate.py
"""The bridge's client for Frigate's internal API (R3 D7, D12, D15). Compose network only.

- `events(...)`: Frigate's event list WITHOUT thumbnails (`include_thumbnails=0`); the bridge drops
  everything but the fields it forwards.
- `stats()`: is Frigate up and which cameras produce frames (a heartbeat part).
- `snapshot(event_id)`: one small JPEG for an opted-in burglar alert (`h=480`, `bbox=0`).
- `has_doorstep_model()`: is a `doorstep` classification model configured (D16).

Redirects are off, every call has a deadline and a size cap, and an event id is checked before it
goes into a URL. The parameter names follow Frigate's older docs and are re-checked against the
pinned version's `/api/docs` at the owner's first run (not verified here). Any failure is `None` /
empty: Frigate being down never raises into the bridge.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_URL = "http://frigate:5000"
TIMEOUT_S = 5.0
MAX_JSON = 2 * 1024 * 1024
MAX_JPEG = 512 * 1024
EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,50}$")


class FrigateClient:
    def __init__(
        self, base_url: str = DEFAULT_URL, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=False, trust_env=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(
        self, path: str, params: dict[str, str] | None, cap: int
    ) -> httpx.Response | None:
        try:
            resp = await self._client.get(self._base + path, params=params)
        except httpx.HTTPError:
            log.warning("frigate unreachable")
            return None
        if resp.status_code != 200 or len(resp.content) > cap:
            log.warning("frigate answered oddly", extra={"status": resp.status_code})
            return None
        return resp

    async def _json(self, path: str, params: dict[str, str] | None = None) -> Any:
        resp = await self._get(path, params, MAX_JSON)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    async def events(
        self,
        *,
        labels: str,
        cameras: str | None,
        zones: str | None,
        after: int,
        before: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        params = {
            "labels": labels,
            "after": str(after),
            "before": str(before),
            "limit": str(limit),
            "include_thumbnails": "0",
        }
        if cameras:
            params["cameras"] = cameras
        if zones:
            params["zones"] = zones
        data = await self._json("/api/events", params)
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []

    async def stats(self) -> tuple[bool, dict[str, bool]]:
        """(Frigate answers, {camera: producing frames})."""
        data = await self._json("/api/stats")
        if not isinstance(data, dict):
            return False, {}
        cams = data.get("cameras")
        online: dict[str, bool] = {}
        if isinstance(cams, dict):
            for name, info in cams.items():
                fps = info.get("camera_fps") if isinstance(info, dict) else None
                if isinstance(name, str) and re.fullmatch(r"^[a-z0-9_]{1,24}$", name):
                    online[name] = (
                        isinstance(fps, int | float) and not isinstance(fps, bool) and fps > 0
                    )
        return True, online

    async def has_doorstep_model(self) -> bool | None:
        data = await self._json("/api/config")
        if not isinstance(data, dict):
            return None
        custom = (data.get("classification") or {}).get("custom")
        return isinstance(custom, dict) and "doorstep" in custom

    async def snapshot(self, event_id: str) -> bytes | None:
        if not EVENT_ID.fullmatch(event_id):
            return None
        resp = await self._get(
            f"/api/events/{event_id}/snapshot.jpg",
            {"h": "480", "quality": "70", "bbox": "0"},
            MAX_JPEG,
        )
        return None if resp is None else resp.content


__all__ = ["DEFAULT_URL", "FrigateClient"]
