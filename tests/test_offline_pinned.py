# tests/test_offline_pinned.py -- security review fix 2: DNS rebinding between the address check and
# the connection. The transport resolves the name itself, refuses unless every address is public,
# and connects to THAT address (SNI and Host stay the hostname), so a resolver that flips after the
# check cannot reach a private IP.
from __future__ import annotations

import httpx
import pytest

from jarvis.offline.config import PinnedTransport

NAME = "laptop.tail1234.ts.net"


class Seen:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def h(req: httpx.Request) -> httpx.Response:
            self.requests.append(req)
            return httpx.Response(200, json={"ok": True})

        return httpx.MockTransport(h)


def resolver(*answers: list[str]):  # type: ignore[no-untyped-def]
    """Answers in turn; the last one repeats."""
    calls = {"n": 0}

    async def r(host: str) -> list[str]:
        i = min(calls["n"], len(answers) - 1)
        calls["n"] += 1
        return list(answers[i])

    r.calls = calls  # type: ignore[attr-defined]
    return r


async def _get(t: PinnedTransport, url: str = f"https://{NAME}/v1/models") -> httpx.Response:
    async with httpx.AsyncClient(transport=t) as c:
        return await c.get(url, headers={"authorization": "Bearer k"})


async def test_connects_to_the_validated_address_keeping_host_and_sni() -> None:
    seen = Seen()
    r = await _get(PinnedTransport(resolver(["8.8.8.8"]), seen.transport()))
    assert r.status_code == 200
    req = seen.requests[0]
    assert req.url.host == "8.8.8.8" and req.url.path == "/v1/models"
    assert req.headers["host"] == NAME
    assert req.extensions["sni_hostname"] == NAME
    assert req.headers["authorization"] == "Bearer k"


async def test_a_non_default_port_stays_in_the_host_header() -> None:
    seen = Seen()
    await _get(
        PinnedTransport(resolver(["8.8.8.8"]), seen.transport()), f"https://{NAME}:8443/v1/models"
    )
    req = seen.requests[0]
    assert req.url.port == 8443 and req.headers["host"] == f"{NAME}:8443"


async def test_the_post_body_is_forwarded() -> None:
    seen = Seen()
    async with httpx.AsyncClient(
        transport=PinnedTransport(resolver(["8.8.8.8"]), seen.transport())
    ) as c:
        await c.post(f"https://{NAME}/v1/chat/completions", json={"a": 1})
    assert seen.requests[0].content == b'{"a":1}' or b'"a"' in seen.requests[0].content


@pytest.mark.parametrize(
    "ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1"]
)
async def test_a_private_answer_never_reaches_the_connection(ip: str) -> None:
    seen = Seen()
    with pytest.raises(httpx.ConnectError):
        await _get(PinnedTransport(resolver([ip]), seen.transport()))
    assert seen.requests == []


async def test_a_resolver_that_flips_after_the_check_cannot_reach_a_private_ip() -> None:
    from jarvis.offline.config import ensure_public

    seen = Seen()
    flip = resolver(["8.8.8.8"], ["169.254.169.254"])
    await ensure_public(NAME, resolver=flip)  # the earlier check passes (first answer)
    with pytest.raises(httpx.ConnectError):  # the connection resolves again: now private
        await _get(PinnedTransport(flip, seen.transport()))
    assert seen.requests == []


async def test_a_mixed_answer_is_refused_and_no_answer_is_refused() -> None:
    seen = Seen()
    for answer in (["8.8.8.8", "10.0.0.1"], []):
        with pytest.raises(httpx.ConnectError):
            await _get(PinnedTransport(resolver(answer), seen.transport()))
    assert seen.requests == []


async def test_a_resolver_error_is_a_connect_error() -> None:
    async def boom(host: str) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(httpx.ConnectError):
        await _get(PinnedTransport(boom, Seen().transport()))


async def test_an_ip_literal_url_is_refused_outright() -> None:
    seen = Seen()
    with pytest.raises(httpx.ConnectError):
        await _get(
            PinnedTransport(resolver(["8.8.8.8"]), seen.transport()), "https://8.8.8.8/v1/models"
        )
    assert seen.requests == []


# ---- M4: prefer IPv4, fail over across the validated addresses ---------------------------------


class Flaky:
    """Refuses to connect to the hosts in `dead`; records every attempt."""

    def __init__(self, dead: set[str]) -> None:
        self.dead = dead
        self.attempts: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def h(req: httpx.Request) -> httpx.Response:
            self.attempts.append(req)
            if req.url.host in self.dead:
                raise httpx.ConnectError("no route")
            return httpx.Response(200, json={"ok": True})

        return httpx.MockTransport(h)


async def test_ipv4_is_tried_before_ipv6_whatever_the_resolver_order() -> None:
    flaky = Flaky(set())
    await _get(PinnedTransport(resolver(["2607:f8b0::1", "3.3.3.3"]), flaky.transport()))
    assert [r.url.host for r in flaky.attempts] == ["3.3.3.3"]


async def test_a_dead_first_address_fails_over_keeping_sni_and_host() -> None:
    flaky = Flaky({"3.3.3.3"})
    r = await _get(PinnedTransport(resolver(["2607:f8b0::1", "3.3.3.3"]), flaky.transport()))
    assert r.status_code == 200
    assert [a.url.host for a in flaky.attempts] == ["3.3.3.3", "2607:f8b0::1"]
    for req in flaky.attempts:
        assert req.extensions["sni_hostname"] == NAME and req.headers["host"] == NAME


async def test_every_address_dead_is_a_connect_error() -> None:
    flaky = Flaky({"3.3.3.3", "4.4.4.4"})
    with pytest.raises(httpx.ConnectError):
        await _get(PinnedTransport(resolver(["4.4.4.4", "3.3.3.3"]), flaky.transport()))
    assert len(flaky.attempts) == 2


async def test_failover_never_leaves_the_validated_set() -> None:
    flaky = Flaky({"8.8.8.8"})
    with pytest.raises(httpx.ConnectError):
        await _get(PinnedTransport(resolver(["8.8.8.8", "10.0.0.1"]), flaky.transport()))
    assert flaky.attempts == []
