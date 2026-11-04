# src/jarvis/offline/config.py
"""The rule for the laptop's tunnel address (R1 D10), written to be SSRF-safe.

The owner types this URL into the console and the server then calls it with a bearer key, so it must
not be able to point JARVIS at an internal service (metadata server, a private network) or leak the
key to someone else. The rule is much stricter than `config._is_private_host` (which lets `.ts.net`
use plain http):

- only `https://<machine>.<tailnet>.ts.net`, port 443 (default), 8443 or 10000 (Tailscale Funnel's),
  path nothing, `/` or `/v1`; a trailing slash is fine
- no IP literal, userinfo, query, fragment, dot segment, trailing dot or non-ASCII character
- EVERY address the name resolves to must be public (never private, loopback, link-local or
  `169.254.169.254`, nor an IPv4-mapped form of one); checked when the URL is saved and again before
  each call (`ensure_public`), so a name that later points inward is refused
- redirects are never followed and the reply is capped at 1 MB (`jarvis.llm.local_provider`)

`ENFORCE_URL_RULE` exists so the offline eval can prove its negative control (the suite must fail
with the rule off); it is never switched off in production code.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

ENFORCE_URL_RULE = True
MAX_URL_CHARS = 200
ALLOWED_PORTS = frozenset({443, 8443, 10000})
RESOLVE_TIMEOUT_S = 5.0

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_URL = re.compile(
    rf"https://(?P<host>{_LABEL}\.{_LABEL}\.ts\.net)(?::(?P<port>[0-9]{{1,5}}))?(?P<path>/(?:v1/?)?)?"
)

Resolver = Callable[[str], Awaitable[list[str]]]

SHAPE_HELP = (
    "Use your Tailscale Funnel address, like https://my-laptop.tail1234.ts.net "
    "(no IP address, no extra path)."
)


class UrlRejected(ValueError):
    """The address breaks the rule. The message is plain words for the owner."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CheckedUrl:
    base: str  # https://host[:port]/v1 : what the client appends /chat/completions to
    host: str


async def system_resolver(host: str) -> list[str]:
    """Every address the system resolver gives for `host` (IPv4 and IPv6)."""
    loop = asyncio.get_running_loop()
    async with asyncio.timeout(RESOLVE_TIMEOUT_S):
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]).split("%", 1)[0] for i in infos})


def _is_public(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


async def public_ips(host: str, *, resolver: Resolver = system_resolver) -> list[str]:
    """Every address `host` resolves to, only if there is at least one and ALL are public."""
    try:
        ips = await resolver(host)
    except (OSError, TimeoutError):
        ips = []
    if not ips:
        raise UrlRejected("Couldn't find that address on the internet. Is Tailscale Funnel on?")
    if not all(_is_public(i) for i in ips):
        raise UrlRejected(
            "That name points at a private address. Only public Funnel addresses are allowed."
        )
    return ips


async def ensure_public(host: str, *, resolver: Resolver = system_resolver) -> None:
    """Refuse unless the name resolves, and every address it resolves to is public."""
    await public_ips(host, resolver=resolver)


def _ipv4_first(ips: list[str]) -> list[str]:
    """IPv4 before IPv6 (Cloud Run has no IPv6 egress), each family in the resolver's order."""
    v4 = [i for i in ips if ":" not in i]
    return v4 + [i for i in ips if ":" in i]


class PinnedTransport(httpx.AsyncBaseTransport):
    """Connects to the address it just validated (closes the DNS-rebinding gap between a check and
    the connection). Per request: resolve the name, refuse unless every answer is public, then send
    the request to an answer (IPv4 first, then each other validated one in turn if a connection
    fails) with the Host header and the TLS server name (SNI, certificate check) still the
    hostname. An IP-literal URL is refused outright."""

    def __init__(
        self, resolver: Resolver = system_resolver, inner: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._resolver = resolver
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            raise httpx.ConnectError("refused: an IP address is not an allowed target")
        try:
            ips = await public_ips(host, resolver=self._resolver)
        except UrlRejected as exc:
            raise httpx.ConnectError(exc.reason) from None
        port = request.url.port
        host_header = f"{host}:{port}" if port is not None else host
        headers = [(k, v) for k, v in request.headers.raw if k.lower() != b"host"]
        headers.append((b"host", host_header.encode()))
        last: httpx.ConnectError | httpx.ConnectTimeout | None = None
        for ip in _ipv4_first(ips):
            pinned = httpx.Request(
                request.method,
                request.url.copy_with(host=ip),
                headers=headers,
                stream=request.stream,
                extensions={**request.extensions, "sni_hostname": host},
            )
            try:
                return await self._inner.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc  # this address did not connect: try the next validated one
        raise last if last is not None else httpx.ConnectError("no address to connect to")

    async def aclose(self) -> None:
        await self._inner.aclose()


async def check_url(url: str, *, resolver: Resolver = system_resolver) -> CheckedUrl:
    """The normalised base URL, or `UrlRejected` with the reason in plain words."""
    text = url.strip(" \t") if isinstance(url, str) else ""
    if not ENFORCE_URL_RULE:  # negative control only
        return CheckedUrl(base=text, host=text)
    if not text:
        raise UrlRejected("Enter the address of your laptop.")
    if len(text) > MAX_URL_CHARS:
        raise UrlRejected(SHAPE_HELP)
    if text.lower().startswith("http://"):
        raise UrlRejected("The address must start with https:// (the tunnel is encrypted).")
    m = _URL.fullmatch(text.lower()) if text.isascii() else None
    if m is None:
        raise UrlRejected(SHAPE_HELP)
    port = m.group("port")
    if port is not None and int(port) not in ALLOWED_PORTS:
        raise UrlRejected("Tailscale Funnel only uses port 443, 8443 or 10000.")
    host = m.group("host")
    await ensure_public(host, resolver=resolver)
    suffix = "" if port in (None, "443") else f":{port}"
    return CheckedUrl(base=f"https://{host}{suffix}/v1", host=host)


__all__ = [
    "ALLOWED_PORTS",
    "CheckedUrl",
    "PinnedTransport",
    "Resolver",
    "UrlRejected",
    "check_url",
    "ensure_public",
    "public_ips",
    "system_resolver",
]
