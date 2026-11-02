# evals/drive/fake_drive.py
"""An in-memory Google Drive (v3) and Cloud Run metadata server for the slice 12 Drive evals and
tests, over httpx MockTransport. Tests load this file by path (tests/drive_fakes.py): evals never
import from tests/.

What it models (what JARVIS relies on, docs checked 2026-11-03):
  - what the service account can SEE: an item shared with it, or anything below such an item
    (Drive's inherited access); everything else is a 404, as Drive answers for an unseen file;
  - `sharingUser.emailAddress`: who shared the item (the nearest shared ancestor's sharer);
  - `trashed`: explicitly, or because a folder above it is in the trash;
  - files.list for the three queries JARVIS sends (shared folders, children, fullText), paged;
  - files.get metadata and `alt=media`, files.export (text/plain, text/csv).
Every request is recorded, so tests assert on what Drive actually received.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx

FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"
SHORTCUT = "application/vnd.google-apps.shortcut"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"
FILES_PATH = "/drive/v3/files"
TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
DRIVE_TOKEN = "ya29.fake-drive-token"
SERVICE_EMAIL = "jarvis-run@proj-123.iam.gserviceaccount.com"
_SHARED_Q = re.compile(r"sharedWithMe and mimeType = '([^']+)' and trashed = false")
_PARENTS_Q = re.compile(r"'([A-Za-z0-9_-]+)' in parents and trashed = false")
_FULLTEXT_Q = re.compile(r"fullText contains '((?:[^'\\]|\\.)*)' and trashed = false")


@dataclass
class Item:
    id: str
    name: str
    mime: str
    parents: list[str] = field(default_factory=list)
    content: bytes = b""
    shared_by: str | None = None  # shared directly with the service account by this account
    trashed: bool = False
    target: str | None = None  # a shortcut's target id
    size: int | None = None  # None: len(content) for a blob, absent for Google files


class FakeDrive:
    """Scriptable Drive: `folder`/`file`/`shortcut` build the tree; `fail` maps an item id (or
    "list") to an HTTP status served instead; `token` is the bearer it accepts."""

    def __init__(self) -> None:
        self.items: dict[str, Item] = {}
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, int] = {}
        self.token = DRIVE_TOKEN
        self.page_size_cap = 1000

    # ---- building the tree -----------------------------------------------------------------

    def folder(self, fid: str, name: str, parent: str | None = None, **kw: Any) -> Item:
        return self._add(Item(fid, name, FOLDER, [parent] if parent else [], **kw))

    def file(
        self,
        fid: str,
        name: str,
        parent: str | None,
        content: bytes | str = b"",
        mime: str = DOC,
        **kw: Any,
    ) -> Item:
        data = content.encode() if isinstance(content, str) else content
        return self._add(Item(fid, name, mime, [parent] if parent else [], data, **kw))

    def shortcut(self, fid: str, name: str, parent: str | None, target: str, **kw: Any) -> Item:
        return self._add(Item(fid, name, SHORTCUT, [parent] if parent else [], target=target, **kw))

    def _add(self, item: Item) -> Item:
        self.items[item.id] = item
        return item

    def move(self, fid: str, new_parent: str) -> None:
        self.items[fid].parents = [new_parent]

    # ---- what the service account sees ----------------------------------------------------

    def _chain(self, item: Item) -> list[Item]:
        out, seen, todo = [], set(), [item]
        while todo:
            it = todo.pop()
            if it.id in seen:
                continue
            seen.add(it.id)
            out.append(it)
            todo.extend(self.items[p] for p in it.parents if p in self.items)
        return out

    def sharer(self, item: Item) -> str | None:
        return next((it.shared_by for it in self._chain(item) if it.shared_by), None)

    def visible(self, item: Item) -> bool:
        return self.sharer(item) is not None

    def is_trashed(self, item: Item) -> bool:
        return any(it.trashed for it in self._chain(item))

    def meta(self, item: Item) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": item.id,
            "name": item.name,
            "mimeType": item.mime,
            "parents": list(item.parents),
            "trashed": self.is_trashed(item),
            "modifiedTime": "2026-11-01T10:00:00.000Z",
        }
        if (who := self.sharer(item)) is not None:
            out["sharingUser"] = {"emailAddress": who, "displayName": "Someone"}
        if not item.mime.startswith("application/vnd.google-apps."):
            out["size"] = str(item.size if item.size is not None else len(item.content))
        if item.target is not None:
            target = self.items.get(item.target)
            out["shortcutDetails"] = {
                "targetId": item.target,
                "targetMimeType": target.mime if target else DOC,
            }
        return out

    # ---- transport -----------------------------------------------------------------------------

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return _err(401, "authError")
        path = request.url.path
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if path == FILES_PATH:
            if "list" in self.fail:
                return _err(self.fail["list"], "backendError")
            return self._list(params)
        m = re.fullmatch(rf"{FILES_PATH}/([^/]+)(/export)?", path)
        if m is None:
            return _err(404, "notFound")
        fid, export = m.group(1), bool(m.group(2))
        if fid in self.fail:
            return _err(self.fail[fid], "forbidden" if self.fail[fid] == 403 else "backendError")
        item = self.items.get(fid)
        if item is None or not self.visible(item):
            return _err(404, "notFound")
        if export:
            return self._export(item, params.get("mimeType", ""))
        if params.get("alt") == "media":
            if item.mime.startswith("application/vnd.google-apps."):
                return _err(403, "fileNotDownloadable")
            return httpx.Response(200, content=item.content)
        return httpx.Response(200, json=self.meta(item))

    def _export(self, item: Item, mime: str) -> httpx.Response:
        wanted = {DOC: TXT, SLIDES: TXT, SHEET: "text/csv"}.get(item.mime)
        if wanted is None or mime != wanted:
            return _err(400, "badRequest")
        return httpx.Response(200, content=item.content)

    def _list(self, params: dict[str, str]) -> httpx.Response:
        q = params.get("q", "")
        visible = [i for i in self.items.values() if self.visible(i) and not self.is_trashed(i)]
        if m := _SHARED_Q.fullmatch(q):
            found = [i for i in visible if i.shared_by and i.mime == m.group(1)]
        elif m := _PARENTS_Q.fullmatch(q):
            found = [i for i in visible if m.group(1) in i.parents]
            found.sort(key=lambda i: (i.mime != FOLDER, i.name.lower()))
        elif m := _FULLTEXT_Q.fullmatch(q):
            needle = re.sub(r"\\(.)", r"\1", m.group(1)).lower()
            found = [
                i
                for i in visible
                if needle in i.name.lower() or needle in i.content.decode("utf-8", "ignore").lower()
            ]
        else:
            return _err(400, "invalidQuery")
        size = min(int(params.get("pageSize", "100")), self.page_size_cap)
        start = int(params.get("pageToken", "o0")[1:] or 0)
        page = found[start : start + size]
        body: dict[str, Any] = {"files": [self.meta(i) for i in page], "incompleteSearch": False}
        if start + size < len(found):
            body["nextPageToken"] = f"o{start + size}"
        return httpx.Response(200, json=body)

    def sent(self, *, path_suffix: str = "") -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(path_suffix)]


def _err(status: int, reason: str) -> httpx.Response:
    body = {
        "error": {
            "code": status,
            "message": f"VENDOR TEXT {reason} — must never reach the owner",
            "errors": [{"reason": reason, "message": "vendor detail"}],
        }
    }
    return httpx.Response(status, content=json.dumps(body).encode())


class FakeMetadata:
    """The Cloud Run metadata server's token endpoint: records requests, answers in order."""

    def __init__(self, token: str = DRIVE_TOKEN, expires_in: int = 3599) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: list[httpx.Response] = []
        self.token = token
        self.expires_in = expires_in

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.answers:
            return self.answers.pop(0)
        if request.headers.get("metadata-flavor") != "Google":
            return httpx.Response(403, text="Missing Metadata-Flavor header")
        body = {"access_token": self.token, "expires_in": self.expires_in, "token_type": "Bearer"}
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class StaticTokens:
    """A `TokenSource` that never touches the network (unit tests and evals)."""

    def __init__(self, token: str = DRIVE_TOKEN) -> None:
        self.value = token
        self.invalidated = 0

    async def token(self) -> str:
        return self.value

    def invalidate(self) -> None:
        self.invalidated += 1

    async def email(self) -> str:
        return SERVICE_EMAIL

    async def aclose(self) -> None:
        return None


__all__ = [
    "DOC",
    "DOCX",
    "DRIVE_TOKEN",
    "FOLDER",
    "PDF",
    "SERVICE_EMAIL",
    "SHEET",
    "SHORTCUT",
    "SLIDES",
    "TOKEN_URL",
    "TXT",
    "FakeDrive",
    "FakeMetadata",
    "Item",
    "StaticTokens",
]
