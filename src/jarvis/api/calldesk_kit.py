# src/jarvis/api/calldesk_kit.py
"""R18 C: the call desk's kit on `app.state.calls_desk_kit`, for I0's owner-only routes
`GET /v1/calls/desk/kit` and `/v1/calls/desk/kit/info` (`jarvis.api.calls_routes`), which answer
the zip with `X-Kit-Sha256` and `no-store`, like the home kit.

`install_calldesk_kit(app)` (the I1 join calls it) sets the slot only when JARVIS has an https
public address, since the kit's `desk.env` must name it; without one the slot stays empty and the
routes answer 501 as for any part not wired. The zip is built from the repository at request
time (`jarvis.calldesk.kit`), so it always carries today's protocol and signing code.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from jarvis.calldesk.kit import CallDeskKit
from jarvis.config import Settings

SLOT = "calls_desk_kit"


def desk_kit(settings: Settings, root: Path | None = None) -> CallDeskKit | None:
    url = (settings.public_base_url or "").strip()
    if not url.startswith("https://"):
        return None
    return CallDeskKit(url, root)


def install_calldesk_kit(app: FastAPI, root: Path | None = None) -> None:
    kit = desk_kit(app.state.settings, root)
    if kit is not None:
        setattr(app.state, SLOT, kit)


__all__ = ["SLOT", "desk_kit", "install_calldesk_kit"]
