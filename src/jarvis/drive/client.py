# src/jarvis/drive/client.py
"""Drive v3 over httpx as JARVIS's own account (slice 12 D1; Layer 6). No Google SDK.

Endpoints (developers.google.com/workspace/drive/api/reference/rest/v3, checked 2026-11-03):

    GET /drive/v3/files              q, fields, pageSize, pageToken → files, nextPageToken,
                                     incompleteSearch. JARVIS sends these queries only:
                                       sharedWithMe [and '<email>' in owners]
                                         and mimeType = '<folder>' and trashed = false
                                       '<id>' in parents and trashed = false   (direct children)
                                       fullText contains '<escaped>' [and '<email>' in owners]
                                         and trashed = false
    GET /drive/v3/files/{id}         metadata (fields below); alt=media → the bytes (not for
                                     Google Docs/Sheets/Slides, which need export)
    GET /drive/v3/files/{id}/export  mimeType=text/plain | text/csv; Google caps exports at 10 MB

In a query, a ' and a \\ inside a string are escaped with a backslash (search-files guide).
`sharingUser` is "the user who shared the file with the requesting user"; `owners` is who owns it
(a stranger can't make the owner own anything, so `'<owner>' in owners` can't be flooded).

Every call: the bearer token from `TokenSource`, an overall deadline, no redirects, a size cap on
the body, and strict type checks (a malformed entry in a list is dropped; malformed metadata is
"unreadable"; a name past `NAME_LIMIT` is cut, never a reason to drop the item). Pages are small
(≤ 25) so that a page of very long hostile names stays under the size cap. A 401 gets one fresh
token. 429, 5xx and a 403 rate limit get at most `MAX_RETRIES` retries, waiting with jittered
exponential backoff (≤ `BACKOFF_TOTAL_S` asleep in all; every call here only reads). Errors are
our own plain English — Google's text never leaves this module; logs say the kind of call and the
status, never a file id. Ids are checked before any request.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from jarvis.drive.ports import (
    DRIVE_ID,
    FOLDER_MIME,
    MAX_FILE_BYTES,
    DriveError,
    DriveFile,
    DriveNotFound,
    DriveUnavailable,
    Page,
    TokenSource,
)
from jarvis.logging import get_logger

log = get_logger(__name__)

API = "https://www.googleapis.com/drive/v3/files"
DEADLINE_S = 25.0
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
MAX_JSON_BYTES = 2_000_000
MAX_PAGE = 25  # entries a list page may ask for (see the module docstring)
NAME_LIMIT = 300
MIME_LIMIT = 200
EMAIL_LIMIT = 320
MAX_OWNERS = 10
FILE_FIELDS = (
    "id,name,mimeType,parents,trashed,size,modifiedTime,md5Checksum,"
    "sharingUser(emailAddress),owners(emailAddress),shortcutDetails(targetId,targetMimeType)"
)
LIST_FIELDS = f"nextPageToken,incompleteSearch,files({FILE_FIELDS})"
MD5 = re.compile(r"[0-9a-fA-F]{32}")
RETRY = frozenset({429, 500, 502, 503, 504})
RATE_REASONS = frozenset({"userRateLimitExceeded", "rateLimitExceeded"})
OFF_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
EXPORT_TOO_BIG = "exportSizeLimitExceeded"
MAX_RETRIES = 2
BACKOFF_BASE_S = 1.0  # retry n waits BASE * 2**n, times 0.5-1.0 (jitter)
BACKOFF_TOTAL_S = 4.0

UNREADABLE = "Google Drive sent an answer JARVIS couldn't read."
TOO_BIG = "That file is over 10 MB, so JARVIS can't read it."
GONE = "That Drive item isn't available to JARVIS (not shared with it, or deleted)."
BUSY = "Google Drive is busy right now; try again in a minute."
_FRIENDLY = {
    400: "Google Drive refused the request as invalid.",
    401: "Google Drive didn't accept JARVIS's access. Try again in a minute.",
    403: "Google Drive refused: JARVIS isn't allowed to read that.",
    429: BUSY,
}
OFF = "The Google Drive API isn't switched on for your JARVIS project yet (re-run the deploy)."

Sleep = Callable[[float], Awaitable[None]]


def escape_query(text: str) -> str:
    """A value for a single-quoted Drive query string: \\ → \\\\, ' → \\'."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def check_id(value: object) -> str:
    if not isinstance(value, str) or not DRIVE_ID.fullmatch(value):
        raise ValueError("not a Drive id")
    return value


def _friendly(status: int) -> str:
    if status in _FRIENDLY:
        return _FRIENDLY[status]
    if status >= 500:
        return "Google Drive is temporarily unavailable; try again shortly."
    return f"Google Drive returned an unexpected status ({status})."


def _str(v: object, limit: int) -> str | None:
    return v if isinstance(v, str) and 0 < len(v) <= limit else None


def _name(v: object) -> str | None:
    """A display name: other people's words, cut (never dropped) when very long."""
    if not isinstance(v, str) or not v:
        return None
    return v if len(v) <= NAME_LIMIT else v[: NAME_LIMIT - 1] + "…"


def _email(v: object) -> str | None:
    return v.strip().lower() if isinstance(v, str) and 0 < len(v) <= EMAIL_LIMIT else None


def _owners(v: object) -> tuple[str, ...]:
    if not isinstance(v, list):
        return ()
    found = (_email(o.get("emailAddress")) for o in v[:MAX_OWNERS] if isinstance(o, dict))
    return tuple(e for e in found if e)


def _size(v: object) -> int | None:
    """Drive sends sizes as decimal strings (int64)."""
    if isinstance(v, str) and v.isdigit() and len(v) <= 19:
        return int(v)
    return None


def parse_file(raw: object) -> DriveFile | None:
    """One files resource, type-checked; None when any field we rely on is malformed."""
    if not isinstance(raw, dict):
        return None
    fid, name, mime = raw.get("id"), _name(raw.get("name")), raw.get("mimeType")
    if not isinstance(fid, str) or not DRIVE_ID.fullmatch(fid) or name is None:
        return None
    if _str(mime, MIME_LIMIT) is None:
        return None
    parents = raw.get("parents", [])
    if not isinstance(parents, list) or not all(
        isinstance(p, str) and DRIVE_ID.fullmatch(p) for p in parents
    ):
        return None
    trashed = raw.get("trashed", False)
    if not isinstance(trashed, bool):
        return None
    sharer = raw.get("sharingUser")
    sc = raw.get("shortcutDetails")
    target = sc.get("targetId") if isinstance(sc, dict) else None
    target_mime = sc.get("targetMimeType") if isinstance(sc, dict) else None
    modified = raw.get("modifiedTime")
    md5 = raw.get("md5Checksum")
    return DriveFile(
        id=fid,
        name=name,
        mime=str(mime),
        parents=tuple(parents),
        trashed=trashed,
        size=_size(raw.get("size")),
        modified=modified if isinstance(modified, str) and len(modified) <= 40 else None,
        sharer=_email(sharer.get("emailAddress")) if isinstance(sharer, dict) else None,
        owners=_owners(raw.get("owners")),
        target_id=target if isinstance(target, str) and DRIVE_ID.fullmatch(target) else None,
        target_mime=_str(target_mime, MIME_LIMIT),
        md5=md5 if isinstance(md5, str) and MD5.fullmatch(md5) else None,
    )


def _reasons(body: bytes) -> set[str]:
    try:
        data = json.loads(body)
    except ValueError:
        return set()
    err = data.get("error") if isinstance(data, dict) else None
    items = err.get("errors") if isinstance(err, dict) else None
    out: set[str] = set()
    for it in items if isinstance(items, list) else []:
        r = it.get("reason") if isinstance(it, dict) else None
        if isinstance(r, str):
            out.add(r)
    details = err.get("details") if isinstance(err, dict) else None
    for d in details if isinstance(details, list) else []:
        r = d.get("reason") if isinstance(d, dict) else None
        if isinstance(r, str):
            out.add(r)
    return out


def _retryable(status: int, body: bytes) -> bool:
    return status in RETRY or (status == 403 and not RATE_REASONS.isdisjoint(_reasons(body)))


class DriveClient:
    def __init__(
        self,
        tokens: TokenSource,
        *,
        http: httpx.AsyncClient | None = None,
        deadline_s: float = DEADLINE_S,
        max_file_bytes: int = MAX_FILE_BYTES,
        sleep: Sleep = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.tokens = tokens
        self._own = http is None
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._deadline = deadline_s
        self._max_file = max_file_bytes
        self._sleep = sleep
        self._rand = rand

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    # ---- the one door ------------------------------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        jitter = 0.5 + 0.5 * min(1.0, max(0.0, self._rand()))
        return float(BACKOFF_BASE_S * (2.0**attempt) * jitter)

    async def _call(
        self, op: str, url: str, params: dict[str, Any], cap: int, too_big: str
    ) -> bytes:
        try:
            async with asyncio.timeout(self._deadline):
                status, body = await self._send(url, params, cap, too_big)
                if status == 401:
                    self.tokens.invalidate()
                    status, body = await self._send(url, params, cap, too_big)
                slept = 0.0
                for attempt in range(MAX_RETRIES):
                    if not _retryable(status, body):
                        break
                    wait = min(self._backoff(attempt), BACKOFF_TOTAL_S - slept)
                    if wait > 0:
                        await self._sleep(wait)
                        slept += wait
                    status, body = await self._send(url, params, cap, too_big)
        except TimeoutError:
            raise DriveUnavailable("Google Drive took too long to answer; try again.") from None
        if status == 200:
            return body
        log.warning("drive error", extra={"op": op, "status": status})  # never the id / path
        raise self._error(status, body)

    @staticmethod
    def _error(status: int, body: bytes) -> DriveError:
        reasons = _reasons(body)
        if status in (404, 410):
            return DriveNotFound(GONE)
        if status == 403 and not OFF_REASONS.isdisjoint(reasons):
            return DriveUnavailable(OFF)
        if status == 403 and EXPORT_TOO_BIG in reasons:
            return DriveError(TOO_BIG)
        if status == 403 and not RATE_REASONS.isdisjoint(reasons):
            return DriveError(BUSY)
        if status == 401:
            return DriveUnavailable(_friendly(401))
        return DriveError(_friendly(status))

    async def _send(
        self, url: str, params: dict[str, Any], cap: int, too_big: str
    ) -> tuple[int, bytes]:
        token = await self.tokens.token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
        try:
            async with self.http.stream(
                "GET", url, params=params, headers=headers, timeout=HTTP_TIMEOUT
            ) as r:
                if r.status_code != 200:
                    return r.status_code, await _read(r, 64 * 1024, UNREADABLE, strict=False)
                return 200, await _read(r, cap, too_big)
        except httpx.HTTPError as exc:
            log.warning("drive unreachable", extra={"reason": type(exc).__name__})
            raise DriveUnavailable("Couldn't reach Google Drive; try again shortly.") from None

    async def _json(self, op: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        raw = await self._call(op, url, params, MAX_JSON_BYTES, UNREADABLE)
        try:
            data = json.loads(raw)
        except ValueError:
            raise DriveError(UNREADABLE) from None
        if not isinstance(data, dict):
            raise DriveError(UNREADABLE)
        return data

    async def _list(self, q: str, page_token: str | None, page_size: int) -> Page:
        params: dict[str, Any] = {
            "q": q,
            "fields": LIST_FIELDS,
            "pageSize": max(1, min(page_size, MAX_PAGE)),
            "spaces": "drive",
        }
        if page_token:
            params["pageToken"] = page_token
        data = await self._json("list", API, params)
        files = data.get("files")
        if not isinstance(files, list):
            raise DriveError(UNREADABLE)
        parsed = [f for f in (parse_file(x) for x in files) if f is not None]
        nxt = data.get("nextPageToken")
        token = nxt if isinstance(nxt, str) and 0 < len(nxt) <= 2048 else None
        return Page(tuple(parsed), token, data.get("incompleteSearch") is True)

    # ---- reads -------------------------------------------------------------------------------

    async def shared_folders(
        self, *, owner: str | None = None, page_token: str | None = None
    ) -> Page:
        """One page of folders shared directly with JARVIS's account (with who shared each);
        with `owner`, only the folders that address owns."""
        owned = f"'{escape_query(owner)}' in owners and " if owner is not None else ""
        q = f"sharedWithMe and {owned}mimeType = '{FOLDER_MIME}' and trashed = false"
        page = await self._list(q, page_token, MAX_PAGE)
        return Page(tuple(f for f in page.files if f.is_folder), page.next_token, page.incomplete)

    async def children(
        self, folder_id: str, *, page_token: str | None = None, page_size: int = MAX_PAGE
    ) -> Page:
        fid = check_id(folder_id)
        return await self._list(f"'{fid}' in parents and trashed = false", page_token, page_size)

    async def search(
        self, text: str, *, owner: str | None = None, page_token: str | None = None
    ) -> Page:
        """One page of full-text hits; with `owner`, only files that address owns."""
        owned = f" and '{escape_query(owner)}' in owners" if owner is not None else ""
        q = f"fullText contains '{escape_query(text)}'{owned} and trashed = false"
        return await self._list(q, page_token, MAX_PAGE)

    async def get(self, file_id: str) -> DriveFile:
        fid = check_id(file_id)
        f = parse_file(await self._json("get", f"{API}/{fid}", {"fields": FILE_FIELDS}))
        if f is None or f.id != fid:
            raise DriveError(UNREADABLE)
        return f

    async def export(self, file_id: str, mime: str) -> bytes:
        fid = check_id(file_id)
        url, params = f"{API}/{fid}/export", {"mimeType": mime}
        return await self._call("export", url, params, self._max_file, TOO_BIG)

    async def download(self, file_id: str) -> bytes:
        fid = check_id(file_id)
        url, params = f"{API}/{fid}", {"alt": "media"}
        return await self._call("download", url, params, self._max_file, TOO_BIG)


async def _read(r: httpx.Response, cap: int, too_big: str, *, strict: bool = True) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in r.aiter_bytes():
        size += len(chunk)
        if size > cap:
            if strict:
                raise DriveError(too_big)
            break
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = [
    "API",
    "BACKOFF_TOTAL_S",
    "FILE_FIELDS",
    "MAX_PAGE",
    "MAX_RETRIES",
    "NAME_LIMIT",
    "DriveClient",
    "check_id",
    "escape_query",
    "parse_file",
]
