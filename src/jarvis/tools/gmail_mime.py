# src/jarvis/tools/gmail_mime.py
"""MIME helpers for the Gmail tools: read a Gmail `payload` tree, HTML → text, build the raw
RFC 2822 message Gmail's drafts.create / messages.send expect. Pure functions, no I/O."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from html import unescape
from html.parser import HTMLParser
from typing import Any

_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_HEADER_UNSAFE = re.compile(r"[\r\n\x00]")
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr"}
)
_SKIP_TAGS = frozenset({"script", "style", "head", "title", "noscript"})


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


# ---- reading --------------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip:
            self.parts.append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if not self._skip:
            self.parts.append(unescape(f"&#{name};"))


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def headers_of(payload: dict[str, Any]) -> dict[str, str]:
    """Header name (lower-case) → value, first occurrence wins."""
    out: dict[str, str] = {}
    for h in payload.get("headers") or []:
        name = str(h.get("name", "")).lower()
        if name and name not in out:
            out[name] = str(h.get("value", ""))
    return out


@dataclass
class Attachment:
    name: str
    size: int
    mime_type: str


@dataclass
class ParsedBody:
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)


def _decode_part(part: dict[str, Any]) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    return b64url_decode(str(data)).decode("utf-8", errors="replace")


def parse_body(payload: dict[str, Any]) -> ParsedBody:
    """Walk the MIME tree: text/plain preferred, else text/html converted; attachments listed
    by name and size (never downloaded)."""
    plain: list[str] = []
    html: list[str] = []
    attachments: list[Attachment] = []

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "").lower()
        filename = str(part.get("filename") or "")
        if filename:
            attachments.append(
                Attachment(filename, int((part.get("body") or {}).get("size") or 0), mime)
            )
        elif mime == "text/plain":
            plain.append(_decode_part(part))
        elif mime == "text/html":
            html.append(_decode_part(part))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(t for t in plain if t.strip())
    if not text.strip() and html:
        text = html_to_text("\n".join(html))
    return ParsedBody(text=text, attachments=attachments)


# ---- writing --------------------------------------------------------------------------------


def parse_recipients(raw: Any) -> list[str]:
    """'a@x.y, b@x.y' or a list → validated lower-case addresses (at least one)."""
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    addrs = [str(a).strip().lower() for a in items if str(a).strip()]
    bad = [a for a in addrs if not _ADDRESS.match(a)]
    if not addrs:
        raise ValueError("at least one recipient is required")
    if bad:
        raise ValueError(f"invalid recipient address: {', '.join(bad)}")
    return addrs


def check_header_value(value: Any, *, name: str, limit: int = 998) -> str:
    text = str(value or "")
    if _HEADER_UNSAFE.search(text):
        raise ValueError(f"{name} must be a single line")
    if len(text) > limit:
        raise ValueError(f"{name} is too long")
    return text


def reply_subject(subject: str, original_subject: str) -> str:
    """Keep the owner's subject; ensure a reply carries a single 'Re:' prefix."""
    base = subject.strip() or original_subject.strip()
    return base if re.match(r"(?i)^re:", base) else f"Re: {base}"


def build_raw_message(
    *,
    to: list[str],
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """RFC 2822 text as Gmail's base64url `raw`. From is set by Gmail (the authenticated user)."""
    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    msg.set_content(body)
    return b64url_encode(msg.as_bytes())


__all__ = [
    "Attachment",
    "ParsedBody",
    "b64url_decode",
    "b64url_encode",
    "build_raw_message",
    "check_header_value",
    "headers_of",
    "html_to_text",
    "parse_body",
    "parse_recipients",
    "reply_subject",
]
