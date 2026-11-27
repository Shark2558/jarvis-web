# src/jarvis/calldesk/link.py
"""Linking the call desk (R18; I0's `DeskDoor`, like the home bridge's link code).

`install-calldesk.ps1 -Link` asks for the code the console shows ("Link the call desk"; it is
valid for minutes and used once) and runs `python -m jarvis.calldesk link CODE`, which sends

    POST /v1/calls/desk/link   {"code": "<code>", "desk_version": "<x.y.z>"}

over HTTPS (Windows' certificate store) and keeps the answer, `{"desk_id", "seed"}`, in the
owner's profile folder (`credentials.CredentialStore`). Each refusal becomes plain words for the
script; the code itself is never logged or repeated. Standard library only.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from jarvis.calldesk import DESK_VERSION
from jarvis.calldesk.credentials import NotLinked, parse_link

LINK_PATH = "/v1/calls/desk/link"
TIMEOUT_S = 20.0
MAX_ANSWER_BYTES = 4096
_CODE = re.compile(r"[0-9A-Z]{6,12}")

Opener = Callable[..., Any]


class LinkFailed(Exception):
    """`reason` is plain words for the setup script."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_REFUSALS = {
    400: "JARVIS did not accept that code. Make a new one in JARVIS and try again.",
    401: "That code is wrong, used or out of time. Make a new one in JARVIS.",
    403: "That code is wrong, used or out of time. Make a new one in JARVIS.",
    404: "This JARVIS does not have calls yet: update JARVIS, then try again.",
    422: "JARVIS did not accept that code. Make a new one in JARVIS and try again.",
    429: "Too many tries. Wait a minute, then try again.",
    501: "JARVIS's calls are still being built: try again after the next update.",
    503: "Calls are switched off in JARVIS (Settings), or JARVIS is busy: try again later.",
}


def clean_code(raw: str) -> str:
    """Upper case, without spaces or dashes; LinkFailed when it can't be a code."""
    code = re.sub(r"[\s-]", "", raw).upper()
    if not _CODE.fullmatch(code):
        raise LinkFailed("That does not look like a link code: copy it from JARVIS again.")
    return code


def request_link(
    jarvis_url: str, raw_code: str, *, opener: Opener = urllib.request.urlopen
) -> tuple[str, bytes]:
    """(desk id, seed), or LinkFailed."""
    body = json.dumps({"code": clean_code(raw_code), "desk_version": DESK_VERSION}).encode()
    req = urllib.request.Request(
        jarvis_url.rstrip("/") + LINK_PATH,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"JARVIS-CallDesk/{DESK_VERSION}",
        },
    )
    try:
        with opener(req, timeout=TIMEOUT_S) as resp:
            status = int(resp.status)
            raw = resp.read(MAX_ANSWER_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise LinkFailed(
            _REFUSALS.get(exc.code, "JARVIS could not link the call desk now.")
        ) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise LinkFailed("JARVIS could not be reached. Check this laptop's internet.") from None
    if status not in (200, 201) or len(raw) > MAX_ANSWER_BYTES:
        raise LinkFailed("JARVIS could not link the call desk now.")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return parse_link(data)
    except (ValueError, NotLinked):
        raise LinkFailed("JARVIS gave an answer the call desk could not read.") from None


__all__ = ["LINK_PATH", "LinkFailed", "clean_code", "request_link"]
