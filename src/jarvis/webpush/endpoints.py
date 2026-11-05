# src/jarvis/webpush/endpoints.py
"""The push endpoint rule (R3 D11). The endpoint is a URL the browser hands us, so it is an SSRF
input: https only, port 443, no user info, no IP literal, a host on the allow-list of push
services, every resolved address public. Redirects are off in the sender."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from jarvis.offline.config import Resolver, UrlRejected, public_ips, system_resolver

MAX_ENDPOINT_CHARS = 700
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
)
ALLOWED_SUFFIXES: tuple[str, ...] = (".notify.windows.com",)
ENFORCE = True  # negative control only: the allow-list off
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
BAD = "That isn't a browser push address JARVIS can use."


class BadEndpoint(ValueError):
    """The endpoint is refused (plain words only)."""


def host_allowed(host: str) -> bool:
    return host in ALLOWED_HOSTS or any(
        host.endswith(s) and len(host) > len(s) for s in ALLOWED_SUFFIXES
    )


def shape(url: str) -> str:
    """The endpoint's host, after the checks that need no network."""
    if not isinstance(url, str) or not url.isascii() or len(url) > MAX_ENDPOINT_CHARS:
        raise BadEndpoint(BAD)
    if any(c in url for c in " \t\r\n\\"):
        raise BadEndpoint(BAD)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise BadEndpoint(BAD) from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.fragment:
        raise BadEndpoint(BAD)
    if port not in (None, 443) or not parts.path or parts.path == "/":
        raise BadEndpoint(BAD)
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise BadEndpoint(BAD)
    if not _HOST.fullmatch(host):
        raise BadEndpoint(BAD)
    if ENFORCE and not host_allowed(host):
        raise BadEndpoint(BAD)
    return host


async def check(url: str, *, resolver: Resolver = system_resolver) -> str:
    """The endpoint's host, or `BadEndpoint`. Also refuses a host that resolves anywhere
    non-public."""
    host = shape(url)
    try:
        await public_ips(host, resolver=resolver)
    except UrlRejected:
        raise BadEndpoint(BAD) from None
    return host


__all__ = ["ALLOWED_HOSTS", "BadEndpoint", "check", "host_allowed", "shape"]
