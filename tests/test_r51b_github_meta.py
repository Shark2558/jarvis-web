# tests/test_r51b_github_meta.py -- R5.1 D2: the GitHub connector records what GitHub's own
# response headers say about the token (its expiry and the hourly API limit) in the connector's
# stored record, in clear fields that hold no secret; the token stays sealed and is never logged.
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from faces_fakes import ROOT, UID
from google_fakes import FakeGoogle
from pydantic import SecretStr

from jarvis.integrations.github import GithubClient, GithubError, GithubStore
from jarvis.integrations.github_meta import META_WRITE_EVERY_S, TokenMeta, parse_expiry
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs, Set

TOKEN = "ghp_SuperSecretTokenValue1234567890abcd"
API = "https://api.github.com"
EXPIRES = "2026-12-31 23:59:59 UTC"
EXPIRES_TS = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()


class Tick:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def headers(*, expires: str | None = EXPIRES, used: int = 12, reset: int = 1_800_003_600) -> dict:
    h = {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-used": str(used),
        "x-ratelimit-reset": str(reset),
    }
    if expires is not None:
        h["github-authentication-token-expiration"] = expires
    return h


def build() -> tuple[GithubClient, FakeGoogle, MemoryDocs, Tick]:
    fake, docs, tick = FakeGoogle(), MemoryDocs(), Tick()
    client = GithubClient(GithubStore(docs, Keyring(ROOT)), http=fake.client(), clock=tick)
    return client, fake, docs, tick


def stored(docs: MemoryDocs) -> dict:
    return docs._data[f"jarvis_connectors_github/{UID}"]  # noqa: SLF001 - test inspection


async def connect(client: GithubClient, fake: FakeGoogle, **kw: object) -> None:
    fake.on(
        "GET",
        f"{API}/user",
        httpx.Response(200, json={"login": "akash-dev"}, headers=headers(**kw)),
    )  # type: ignore[arg-type]
    await client.connect(UID, SecretStr(TOKEN))
    fake.routes.clear()


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (EXPIRES, EXPIRES_TS),
        ("2026-12-31 23:59:59 +0000", EXPIRES_TS),
        ("2026-12-31 15:59:59 -0800", EXPIRES_TS),
        ("2026-12-31T23:59:59Z", EXPIRES_TS),
        ("", None),
        ("soon", None),
        (None, None),
    ],
)
def test_expiry_header_is_parsed_or_ignored(value: str | None, want: float | None) -> None:
    assert parse_expiry(value) == want


async def test_connect_records_the_expiry_and_hourly_limit_in_clear_fields() -> None:
    client, fake, docs, _ = build()

    await connect(client, fake)

    meta = stored(docs)["meta"]
    assert meta["expires_at"] == EXPIRES_TS
    assert (meta["rate_limit"], meta["rate_used"], meta["rate_reset"]) == (5000, 12, 1_800_003_600)
    text = json.dumps(stored(docs))
    assert TOKEN not in text and "akash-dev" not in text
    got = await client.token_meta(UID)
    assert got is not None and got.expires_at == EXPIRES_TS


async def test_a_token_without_the_header_does_not_expire() -> None:
    client, fake, docs, _ = build()

    await connect(client, fake, expires=None)

    assert stored(docs)["meta"]["expires_at"] is None
    assert (await client.token_meta(UID)).expires_at is None  # type: ignore[union-attr]


async def test_calls_update_the_limit_in_memory_and_store_it_at_most_every_few_minutes() -> None:
    client, fake, docs, tick = build()
    await connect(client, fake)
    fake.on("GET", f"{API}/user/repos", httpx.Response(200, json=[], headers=headers(used=40)))

    tick.now += 30
    await client.repos(UID)
    assert (await client.token_meta(UID)).rate_used == 40  # type: ignore[union-attr]
    assert stored(docs)["meta"]["rate_used"] == 12  # not written again yet

    tick.now += META_WRITE_EVERY_S
    await client.repos(UID)
    assert stored(docs)["meta"]["rate_used"] == 40


async def test_a_changed_expiry_is_stored_at_once() -> None:
    client, fake, docs, tick = build()
    await connect(client, fake)
    later = "2027-03-01 00:00:00 UTC"
    fake.on(
        "GET", f"{API}/user/repos", httpx.Response(200, json=[], headers=headers(expires=later))
    )

    tick.now += 5
    await client.repos(UID)

    assert stored(docs)["meta"]["expires_at"] == datetime(2027, 3, 1, tzinfo=UTC).timestamp()


async def test_a_rate_limited_answer_updates_the_count_but_keeps_the_expiry() -> None:
    client, fake, _, tick = build()
    await connect(client, fake)
    limited = {**headers(expires=None, used=5000), "x-ratelimit-remaining": "0"}
    fake.on("GET", f"{API}/user/repos", httpx.Response(403, json={}, headers=limited))

    tick.now += 5
    with pytest.raises(GithubError):
        await client.repos(UID)

    meta = await client.token_meta(UID)
    assert meta is not None and meta.rate_used == 5000 and meta.expires_at == EXPIRES_TS


async def test_another_instance_reads_the_stored_meta() -> None:
    client, fake, docs, _ = build()
    await connect(client, fake)

    other = GithubClient(GithubStore(docs, Keyring(ROOT)), http=fake.client())

    meta = await other.token_meta(UID)
    assert meta is not None and meta.rate_limit == 5000


async def test_disconnect_forgets_the_meta_and_a_missing_record_is_never_recreated() -> None:
    client, fake, docs, tick = build()
    await connect(client, fake)
    await client.disconnect(UID)

    assert await client.token_meta(UID) is None
    assert await client._store.note_meta(UID, TokenMeta(tick.now)) is False  # noqa: SLF001
    assert f"jarvis_connectors_github/{UID}" not in docs._data  # noqa: SLF001


async def test_bad_stored_meta_reads_as_none() -> None:
    client, _, docs, _ = build()
    await docs.write(
        [Set(f"jarvis_connectors_github/{UID}", {"blob": "x", "meta": {"seen_at": "x"}})]
    )

    assert await client.token_meta(UID) is None


async def test_a_failing_meta_write_never_breaks_the_call_and_never_logs_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, fake, _, tick = build()
    await connect(client, fake)

    async def boom(*_a: object) -> bool:
        raise OSError(f"store down {TOKEN}")

    client._store.note_meta = boom  # type: ignore[method-assign]  # noqa: SLF001
    fake.on("GET", f"{API}/user/repos", httpx.Response(200, json=[], headers=headers(used=99)))
    tick.now += META_WRITE_EVERY_S + 1

    with caplog.at_level(logging.DEBUG):
        assert await client.repos(UID) == ()
    assert TOKEN not in caplog.text
