# src/jarvis/drive/client.py
"""Drive v3 over httpx as JARVIS's own account (slice 12 D1; Layer 6). No Google SDK.

Endpoints (developers.google.com/workspace/drive/api/reference/rest/v3, checked 2026-11-03):

    GET /drive/v3/files              q, fields, pageSize (≤ 1000), pageToken → files, nextPageToken,
                                     incompleteSearch. JARVIS sends exactly three queries:
                                       sharedWithMe and mimeType = '<folder>' and trashed = false
                                       '<id>' in parents and trashed = false   (direct children)
                                       fullText contains '<escaped>' and trashed = false
    GET /drive/v3/files/{id}         metadata (fields below); alt=media → the bytes (not for
                                     Google Docs/Sheets/Slides, which need export)
    GET /drive/v3/files/{id}/export  mimeType=text/plain | text/csv; Google caps exports at 10 MB

In a query, a ' and a \\ inside a string are escaped with a backslash (search-files guide).
`sharingUser` is "the user who shared the file with the requesting user". Every call: the bearer
token from `TokenSource`, an overall deadline, no redirects, a size cap on the body, and strict
type checks (a malformed entry in a list is dropped; malformed metadata is "unreadable"). A 401
gets one fresh token; 429/5xx get one retry (every call here only reads). Errors are our own
plain English — Google's text never leaves this module. Ids are checked before any request.
"""

from __future__ import annotations

import asyncio
import json
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
MAX_PAGE = 100
NAME_LIMIT = 300
MIME_LIMIT = 200
FILE_FIELDS = (
    "id,name,mimeType,parents,trashed,size,modifiedTime,"
    "sharingUser(emailAddress),shortcutDetails(targetId,targetMimeType)"
)
LIST_FIELDS = f"nextPageToken,incompleteSearch,files({FILE_FIELDS})"
RETRY = frozenset({429, 500, 502, 503, 504})
OFF_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})

UNREADABLE = "Google Drive sent an answer JARVIS couldn't read."
TOO_BIG = "That file is over 10 MB, so JARVIS can't read it."
GONE = "That Drive item isn't available to JARVIS (not shared with it, or deleted)."
_FRIENDLY = {
    400: "Google Drive refused the request as invalid.",
    401: "Google Drive didn't accept JARVIS's access. Try again in a minute.",
    403: "Google Drive refused: JARVIS isn't allowed to read that.",
    429: "Google Drive is busy right now; try again in a minute.",
}
OFF = "The Google Drive API isn't switched on for your JARVIS project yet (re-run the deploy)."


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


def _size(v: object) -> int | None:
    """Drive sends sizes as decimal strings (int64)."""
    if isinstance(v, str) and v.isdigit() and len(v) <= 19:
        return int(v)
    return None


def parse_file(raw: object) -> DriveFile | None:
    """One files resource, type-checked; None when any field we rely on is malformed."""
    if not isinstance(raw, dict):
        return None
    fid, name, mime = raw.get("id"), _str(raw.get("name"), NAME_LIMIT), raw.get("mimeType")
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
    email = sharer.get("emailAddress") if isinstance(sharer, dict) else None
    sc = raw.get("shortcutDetails")
    target = sc.get("targetId") if isinstance(sc, dict) else None
    target_mime = sc.get("targetMimeType") if isinstance(sc, dict) else None
    modified = raw.get("modifiedTime")
    return DriveFile(
        id=fid,
        name=name,
        mime=str(mime),
        parents=tuple(parents),
        trashed=trashed,
        size=_size(raw.get("size")),
        modified=modified if isinstance(modified, str) and len(modified) <= 40 else None,
        sharer=email.strip().lower() if isinstance(email, str) and len(email) <= 320 else None,
        target_id=target if isinstance(target, str) and DRIVE_ID.fullmatch(target) else None,
        target_mime=_str(target_mime, MIME_LIMIT),
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


class DriveClient:
    def __init__(
        self,
        tokens: TokenSource,
        *,
        http: httpx.AsyncClient | None = None,
        deadline_s: float = DEADLINE_S,
        max_file_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        self.tokens = tokens
        self._own = http is None
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._deadline = deadline_s
        self._max_file = max_file_bytes

    async def aclose(self) -> None:
        if self._own:
            await self.http.aclose()

    # ---- the one door ------------------------------------------------------------------------

    async def _call(self, url: str, params: dict[str, Any], cap: int, too_big: str) -> bytes:
        try:
            async with asyncio.timeout(self._deadline):
                status, body = await self._send(url, params, cap, too_big)
                if status == 401:
                    self.tokens.invalidate()
                    status, body = await self._send(url, params, cap, too_big)
                elif status in RETRY:
                    status, body = await self._send(url, params, cap, too_big)
        except TimeoutError:
            raise DriveUnavailable("Google Drive took too long to answer; try again.") from None
        if status == 200:
            return body
        log.warning("drive error", extra={"status": status, "path": httpx.URL(url).path})
        if status in (404, 410):
            raise DriveNotFound(GONE)
        if status == 403 and not OFF_REASONS.isdisjoint(_reasons(body)):
            raise DriveUnavailable(OFF)
        if status == 401:
            raise DriveUnavailable(_friendly(401))
        raise DriveError(_friendly(status))

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

    async def _json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        raw = await self._call(url, params, MAX_JSON_BYTES, UNREADABLE)
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
        data = await self._json(API, params)
        files = data.get("files")
        if not isinstance(files, list):
            raise DriveError(UNREADABLE)
        parsed = [f for f in (parse_file(x) for x in files) if f is not None]
        nxt = data.get("nextPageToken")
        token = nxt if isinstance(nxt, str) and 0 < len(nxt) <= 2048 else None
        return Page(tuple(parsed), token, data.get("incompleteSearch") is True)

    # ---- reads -------------------------------------------------------------------------------

    async def shared_folders(self, *, limit_pages: int = 5) -> list[DriveFile]:
        """Folders shared directly with JARVIS's account (with who shared each)."""
        q = f"sharedWithMe and mimeType = '{FOLDER_MIME}' and trashed = false"
        out: list[DriveFile] = []
        token: str | None = None
        for _ in range(limit_pages):
            page = await self._list(q, token, MAX_PAGE)
            out.extend(f for f in page.files if f.is_folder)
            token = page.next_token
            if token is None:
                break
        return out

    async def children(
        self, folder_id: str, *, page_token: str | None = None, page_size: int = 50
    ) -> Page:
        fid = check_id(folder_id)
        return await self._list(f"'{fid}' in parents and trashed = false", page_token, page_size)

    async def search(self, text: str, *, page_size: int = 50) -> Page:
        q = f"fullText contains '{escape_query(text)}' and trashed = false"
        return await self._list(q, None, page_size)

    async def get(self, file_id: str) -> DriveFile:
        fid = check_id(file_id)
        f = parse_file(await self._json(f"{API}/{fid}", {"fields": FILE_FIELDS}))
        if f is None or f.id != fid:
            raise DriveError(UNREADABLE)
        return f

    async def export(self, file_id: str, mime: str) -> bytes:
        fid = check_id(file_id)
        return await self._call(f"{API}/{fid}/export", {"mimeType": mime}, self._max_file, TOO_BIG)

    async def download(self, file_id: str) -> bytes:
        fid = check_id(file_id)
        return await self._call(f"{API}/{fid}", {"alt": "media"}, self._max_file, TOO_BIG)


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


__all__ = ["API", "FILE_FIELDS", "DriveClient", "check_id", "escape_query", "parse_file"]
