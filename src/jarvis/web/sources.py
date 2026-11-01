# src/jarvis/web/sources.py
"""Web addresses and citations (slice 10 B). Pure: no I/O.

`normalize_url` is the one definition of "the same page" used by the web_read allow-list
(normalised exact match), the ledger and the console's Sources row: https only, no user info, a
real DNS name (no IP literal, no single label), host lower-cased and IDNA-encoded (punycode), the
default port and the fragment dropped, path and query kept exactly (percent-encoded).
"""

from __future__ import annotations

import re

import httpx
from pydantic import BaseModel

MAX_URL_CHARS = 2048
TITLE_LIMIT = 200
# A DNS name of at least two labels whose last label starts with a letter (so no IPv4 literal);
# IDNA hosts arrive here already as xn-- labels.
_HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
)
_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]")
_URL_IN_TEXT = re.compile(r"https://\S+", re.IGNORECASE)
_TRAILING = ".,;:!?'\"*>]}"


class Source(BaseModel):
    """One numbered web source a reply cited (`n` is the [n] in the text). Built only by the
    ledger from normalised, capped values; no length constraints here on purpose, so a stored
    turn can never make its whole conversation unreadable. The console re-checks every field."""

    n: int
    title: str
    url: str
    domain: str


def normalize_url(raw: object) -> str | None:
    """The canonical https form of `raw`, or None when it is not an acceptable web address."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or len(text) > MAX_URL_CHARS or _UNSAFE.search(text):
        return None
    try:
        u = httpx.URL(text)
        host = u.raw_host.decode("ascii").rstrip(".")
        path = u.raw_path.decode("ascii")
    except (httpx.InvalidURL, ValueError, UnicodeError):
        return None
    if u.scheme != "https" or u.userinfo or not _HOST.fullmatch(host):
        return None
    port = f":{u.port}" if u.port is not None else ""
    out = f"https://{host}{port}{path or '/'}"
    return out if len(out) <= MAX_URL_CHARS else None


def domain_of(url: str) -> str:
    """The host to show (punycode stays punycode, so a look-alike name can't pass as another)."""
    try:
        host = httpx.URL(url).raw_host.decode("ascii")
    except (httpx.InvalidURL, ValueError, UnicodeError):
        return ""
    return host[4:] if host.startswith("www.") else host


def _trim(candidate: str) -> str:
    """Drop sentence punctuation after a link, and a closing parenthesis it did not open."""
    while candidate:
        if candidate[-1] in _TRAILING:
            candidate = candidate[:-1]
        elif candidate[-1] == ")" and candidate.count("(") < candidate.count(")"):
            candidate = candidate[:-1]
        else:
            break
    return candidate


def urls_in_text(text: str) -> list[str]:
    """Every https link written in `text`, normalised, in order, without duplicates."""
    out: list[str] = []
    for m in _URL_IN_TEXT.finditer(text or ""):
        url = normalize_url(_trim(m.group(0)))
        if url is not None and url not in out:
            out.append(url)
    return out


__all__ = [
    "MAX_URL_CHARS",
    "TITLE_LIMIT",
    "Source",
    "domain_of",
    "normalize_url",
    "urls_in_text",
]
