# tests/test_offline_url.py -- R1 C (D10): the SSRF-safe rule for the laptop's tunnel URL.
# Only https://<machine>.<tailnet>.ts.net[:443|:8443|:10000][/v1]; no IP literal, userinfo, query or
# fragment; every resolved address must be public. Settings' _is_private_host lets .ts.net use plain
# http, so this is a separate, stricter rule.
from __future__ import annotations

import pytest

from jarvis.offline import config as cfg
from jarvis.offline.config import UrlRejected, check_url

PUB = ["8.8.8.8"]


def resolver(ips: list[str]):  # type: ignore[no-untyped-def]
    async def _r(host: str) -> list[str]:
        return list(ips)

    return _r


@pytest.mark.parametrize(
    ("url", "base"),
    [
        ("https://laptop.tail1234.ts.net", "https://laptop.tail1234.ts.net/v1"),
        ("https://laptop.tail1234.ts.net/", "https://laptop.tail1234.ts.net/v1"),
        ("https://laptop.tail1234.ts.net/v1", "https://laptop.tail1234.ts.net/v1"),
        ("https://laptop.tail1234.ts.net/v1/", "https://laptop.tail1234.ts.net/v1"),
        ("https://laptop.tail1234.ts.net:443/v1", "https://laptop.tail1234.ts.net/v1"),
        ("https://laptop.tail1234.ts.net:8443", "https://laptop.tail1234.ts.net:8443/v1"),
        ("https://laptop.tail1234.ts.net:10000/v1", "https://laptop.tail1234.ts.net:10000/v1"),
        ("  https://Laptop.Tail1234.TS.net/v1  ", "https://laptop.tail1234.ts.net/v1"),
        ("https://my-pc.tail-abc.ts.net", "https://my-pc.tail-abc.ts.net/v1"),
    ],
)
async def test_good_urls_are_normalised(url: str, base: str) -> None:
    got = await check_url(url, resolver=resolver(PUB))
    assert got.base == base
    assert got.host == base.split("//")[1].split("/")[0].split(":")[0]


BAD = [
    ("", "empty"),
    ("laptop.tail1234.ts.net", "no scheme"),
    ("http://laptop.tail1234.ts.net/v1", "plain http"),
    ("ftp://laptop.tail1234.ts.net", "ftp"),
    ("https://100.64.1.2/v1", "IPv4 literal"),
    ("https://8.8.8.8", "public IPv4 literal"),
    ("https://[::1]/v1", "IPv6 literal"),
    ("https://[::ffff:127.0.0.1]/v1", "mapped IPv6 literal"),
    ("https://localhost/v1", "localhost"),
    ("https://evil.example.com/v1", "not ts.net"),
    ("https://laptop.tail1234.ts.net.evil.com/v1", "ts.net as a prefix"),
    ("https://evilts.net/v1", "lookalike"),
    ("https://laptop.ts.net/v1", "no tailnet label"),
    ("https://ts.net/v1", "bare ts.net"),
    ("https://a.b.c.tail1234.ts.net/v1", "too many labels"),
    ("https://laptop.tail1234.ts.net./v1", "trailing dot"),
    ("https://user:pw@laptop.tail1234.ts.net/v1", "userinfo"),
    ("https://laptop.tail1234.ts.net@evil.com/v1", "userinfo trick"),
    ("https://evil.com\\@laptop.tail1234.ts.net/v1", "backslash trick"),
    ("https://laptop.tail1234.ts.net/v1?x=1", "query"),
    ("https://laptop.tail1234.ts.net/v1#frag", "fragment"),
    ("https://laptop.tail1234.ts.net:80/v1", "port 80"),
    ("https://laptop.tail1234.ts.net:11434/v1", "ollama port"),
    ("https://laptop.tail1234.ts.net:99999/v1", "port out of range"),
    ("https://laptop.tail1234.ts.net:abc/v1", "port not a number"),
    ("https://laptop.tail1234.ts.net/v2", "other path"),
    ("https://laptop.tail1234.ts.net/v1/chat", "deeper path"),
    ("https://laptop.tail1234.ts.net/v1/../admin", "dot segments"),
    ("https://laptop.tail1234.ts.net//v1", "double slash"),
    ("https://laptop.tail1234.ts.net/%2e%2e/", "encoded dots"),
    ("https://laptop.tail1234.ts.net/v1\n", "newline inside"),
    ("https://laptop .tail1234.ts.net/v1", "space in host"),
    ("https://l\u0430ptop.tail1234.ts.net/v1", "cyrillic a"),
    ("https://laptop.tail1234.ts.net/v1\x00", "NUL"),
    ("https://" + "a" * 70 + ".tail1234.ts.net", "label too long"),
    ("https://laptop.tail1234.ts.net/" + "v" * 400, "very long"),
    ("https://-laptop.tail1234.ts.net", "label starts with hyphen"),
]


@pytest.mark.parametrize(("url", "why"), BAD, ids=[w for _, w in BAD])
async def test_bad_urls_are_refused_in_plain_words(url: str, why: str) -> None:
    with pytest.raises(UrlRejected) as ei:
        await check_url(url, resolver=resolver(PUB))
    msg = str(ei.value)
    assert msg and msg[0].isupper() and "Traceback" not in msg
    assert ei.value.reason == msg


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.10",
        "127.0.0.1",
        "169.254.169.254",
        "169.254.1.1",
        "100.64.0.9",  # tailnet / CGNAT: a Funnel name never resolves here
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:10.0.0.1",
    ],
)
async def test_a_private_resolution_is_refused(ip: str) -> None:
    with pytest.raises(UrlRejected, match="public"):
        await check_url("https://laptop.tail1234.ts.net/v1", resolver=resolver([ip]))


async def test_one_private_address_among_public_ones_is_refused() -> None:
    with pytest.raises(UrlRejected):
        await check_url(
            "https://laptop.tail1234.ts.net/v1", resolver=resolver(["8.8.8.8", "10.0.0.1"])
        )


async def test_public_ipv6_is_fine() -> None:
    got = await check_url(
        "https://laptop.tail1234.ts.net/v1", resolver=resolver(["2606:4700:4700::1111"])
    )
    assert got.base.endswith("/v1")


async def test_an_unresolvable_or_empty_name_is_refused() -> None:
    async def boom(host: str) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(UrlRejected, match="find"):
        await check_url("https://laptop.tail1234.ts.net/v1", resolver=boom)
    with pytest.raises(UrlRejected, match="find"):
        await check_url("https://laptop.tail1234.ts.net/v1", resolver=resolver([]))


async def test_a_garbage_address_from_the_resolver_is_refused() -> None:
    with pytest.raises(UrlRejected):
        await check_url("https://laptop.tail1234.ts.net/v1", resolver=resolver(["not-an-ip"]))


async def test_ensure_public_can_be_rechecked_before_a_call() -> None:
    await cfg.ensure_public("laptop.tail1234.ts.net", resolver=resolver(PUB))
    with pytest.raises(UrlRejected):
        await cfg.ensure_public("laptop.tail1234.ts.net", resolver=resolver(["127.0.0.1"]))


async def test_the_rule_can_be_switched_off_only_for_the_negative_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "ENFORCE_URL_RULE", False)
    got = await check_url("http://169.254.169.254/latest", resolver=resolver(["127.0.0.1"]))
    assert "169.254.169.254" in got.base  # the control: nothing is checked


async def test_the_default_resolver_asks_the_system_and_is_checked_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    answers = {"private": "10.1.2.3", "public": "8.8.4.4"}
    box = {"ip": answers["private"]}

    def fake(host: str, *a: object, **k: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (box["ip"], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(UrlRejected, match="public"):
        await check_url("https://laptop.tail1234.ts.net/v1")
    box["ip"] = answers["public"]
    got = await check_url("https://laptop.tail1234.ts.net/v1")
    assert got.base == "https://laptop.tail1234.ts.net/v1"
