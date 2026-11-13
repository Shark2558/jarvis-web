# tests/r7_fakes_a.py -- R7 Part A (docs/plans/r7-mobile.md D3, D8, D15): what Part A's tests share.
# Never imported from conftest.
#
#   png_size(raw) -> (w, h)              the IHDR of a PNG (and a check that it IS one)
#   multipart(fields, files) -> (body, content type)   a share sheet's form post, made in the test
#   SpyReceive(body)                     an ASGI `receive` that counts how many body messages the
#                                        app pulled: "the server discards the body unread"
#   raw_post(app, path, body, headers)   one POST straight through the ASGI app with that spy
#   links_words() / links_panels()       the two allow-lists, read from console-r7-links.js
#   dock_panels()                        every panel the dock opens (console.html)
#
# Pictures and files are bytes made here (no real photo, no real person); names are made up.
from __future__ import annotations

import re
import struct
import uuid
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
ICONS = STATIC / "icons"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[MutableMapping[str, Any], Receive, Send], Awaitable[None]]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def png_size(raw: bytes) -> tuple[int, int]:
    if not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", raw[16:24])
    return int(width), int(height)


def multipart(
    fields: Mapping[str, str], files: Sequence[tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    """The body a share sheet posts: text fields, then `files` entries (name, type, bytes)."""
    boundary = "----jarvis-test-" + uuid.uuid4().hex
    out: list[bytes] = []
    for key, value in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        out.append(value.encode() + b"\r\n")
    for name, kind, raw in files:
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
            f'filename="{name}"\r\nContent-Type: {kind}\r\n\r\n'
        )
        out.append(head.encode() + raw + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


class SpyReceive:
    """Hands the body over in chunks and counts every chunk the app (or a middleware) took."""

    def __init__(self, body: bytes, chunk: int = 64 * 1024) -> None:
        self._chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)] or [b""]
        self.pulled = 0
        self.calls = 0

    async def __call__(self) -> Message:
        self.calls += 1
        if self.pulled < len(self._chunks):
            data = self._chunks[self.pulled]
            self.pulled += 1
            return {
                "type": "http.request",
                "body": data,
                "more_body": self.pulled < len(self._chunks),
            }
        return {"type": "http.disconnect"}


async def raw_post(
    app: ASGIApp, path: str, body: bytes, headers: Mapping[str, str]
) -> tuple[int, dict[str, str], bytes, SpyReceive]:
    spy = SpyReceive(body)
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in {**headers, "content-length": str(len(body)), "host": "test"}.items()
        ],
    }
    await app(scope, spy, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    out_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in start["headers"]}
    reply = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return int(start["status"]), out_headers, reply, spy


def _array(js: str, name: str) -> list[str]:
    found = re.search(rf"const {name} = Object\.freeze\(\[([^\]]*)\]\)", js)
    if found is None:
        raise ValueError(f"console-r7-links.js has no frozen {name} list")
    return re.findall(r"'([a-z]+)'", found.group(1))


def links_words() -> list[str]:
    return _array(text(STATIC / "console-r7-links.js"), "WORDS")


def links_panels() -> list[str]:
    return _array(text(STATIC / "console-r7-links.js"), "PANELS")


def dock_panels() -> list[str]:
    html = text(STATIC / "console.html")
    dock = html[html.index('id="dock"') : html.index("</nav>")]
    return re.findall(r'data-open="(\w+)"', dock)


__all__ = [
    "ICONS",
    "PNG_SIGNATURE",
    "ROOT",
    "STATIC",
    "SpyReceive",
    "dock_panels",
    "links_panels",
    "links_words",
    "multipart",
    "png_size",
    "raw_post",
    "text",
]
