# tests/test_billing_fx.py — slice 7b: the USD→INR rate (Frankfurter, once a day, never raises).
# The sandbox cannot reach api.frankfurter.dev: every test uses a fake httpx transport.
from __future__ import annotations

import asyncio
import math
from datetime import timedelta
from typing import Any

import httpx
import pytest
from billing_fakes import NOW, BrokenDocs, Clock

from jarvis.billing.fx import (
    DEFAULT_AS_OF,
    DEFAULT_RATE,
    FRANKFURTER_URL,
    FxRates,
    parse_as_of,
    parse_rate,
)
from jarvis.config import Settings
from jarvis.storage.docs import MemoryDocs

FX_DOC = "jarvis_fx/usd_inr"


class FakeFx:
    """Frankfurter stand-in: answers `body` (JSON), `raw` bytes, a status, or raises."""

    def __init__(
        self,
        body: Any = None,
        *,
        status: int = 200,
        raw: bytes | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.body = body if body is not None else {"date": "2026-11-14", "rate": 95.61}
        self.status, self.raw, self.exc = status, raw, exc
        self.requests: list[httpx.Request] = []
        self.gate: asyncio.Event | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.gate is not None:
            await self.gate.wait()
        if self.exc is not None:
            raise self.exc
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw)
        return httpx.Response(self.status, json=self.body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def _fx(
    fake: FakeFx | None, *, docs: MemoryDocs | None = None, clock: Clock | None = None
) -> FxRates:
    return FxRates(
        docs=docs,
        default_rate=DEFAULT_RATE,
        http=fake.client() if fake else None,
        clock=clock or Clock(),
    )


# ---- parsing -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "want"),
    [
        ({"rate": 95.31}, 95.31),
        ({"date": "2026-11-14", "base": "USD", "quote": "INR", "rate": 95}, 95.0),
        ({"rates": {"INR": 94.8}}, 94.8),
        ({"rates": [{"date": "2026-11-14", "rate": 96.2}]}, 96.2),
        ({"rate": 50}, 50.0),
        ({"rate": 200}, 200.0),
    ],
)
def test_parse_accepts_a_finite_rate_in_range_at_the_known_places(body: Any, want: float) -> None:
    assert parse_rate(body) == want


@pytest.mark.parametrize(
    "body",
    [
        {},  # missing
        {"rate": "95.31"},  # a string
        {"rate": 0},
        {"rate": -95.3},
        {"rate": float("nan")},
        {"rate": float("inf")},
        {"rate": 1e9},
        {"rate": 49.99},
        {"rate": 200.01},
        {"rate": True},  # bool is not a number here
        {"rate": None},
        {"rate": [95.3]},
        {"rates": {"INR": {"rate": 95.3}}},  # nested one level too deep
        {"rates": {"inr": 95.3}},  # case matters
        {"rates": []},
        {"rates": [95.3]},
        {"rates": [{"value": 95.3}]},
        {"data": {"rate": 95.3}},  # not one of the known places
        [{"rate": 95.3}],  # a top-level list is not a documented shape
        None,
        "95.3",
        95.3,
    ],
)
def test_parse_rejects_anything_else(body: Any) -> None:
    assert parse_rate(body) is None


def test_parse_as_of_reads_a_real_date_or_falls_back() -> None:
    assert parse_as_of({"date": "2026-11-14"}, "2026-11-15") == "2026-11-14"
    assert parse_as_of({"rates": [{"date": "2026-11-13"}]}, "2026-11-15") == "2026-11-13"
    for bad in ({"date": "14/11/2026"}, {"date": "2026-02-30"}, {"date": 20261114}, {}, None):
        assert parse_as_of(bad, "2026-11-15") == "2026-11-15"


# ---- fetching -----------------------------------------------------------------------------------


async def test_a_good_answer_becomes_the_rate_and_is_cached_in_firestore() -> None:
    fake, docs = FakeFx(), MemoryDocs()
    fx = _fx(fake, docs=docs)
    r = await fx.refresh()
    assert (r.inr_per_usd, r.as_of, r.source) == (95.61, "2026-11-14", "frankfurter")
    req = fake.requests[0]
    assert req.method == "GET" and str(req.url) == FRANKFURTER_URL  # fixed URL, nothing added
    assert FRANKFURTER_URL == "https://api.frankfurter.dev/v2/rate/usd/inr"
    stored = await docs.get(FX_DOC)
    assert stored is not None
    assert (stored["rate"], stored["as_of"], stored["source"]) == (
        95.61,
        "2026-11-14",
        "frankfurter",
    )
    assert fx.peek() == r


async def test_fetches_at_most_once_a_day() -> None:
    fake, clock = FakeFx(), Clock()
    fx = _fx(fake, clock=clock)
    await fx.refresh()
    await fx.refresh()
    await fx.rate()
    clock.at = NOW + timedelta(hours=23, minutes=59)
    await fx.refresh()
    assert len(fake.requests) == 1
    clock.at = NOW + timedelta(days=1, seconds=1)
    fake.body = {"date": "2026-11-15", "rate": 96.0}
    assert (await fx.refresh()).inr_per_usd == 96.0
    assert len(fake.requests) == 2


async def test_a_failed_fetch_also_waits_a_day() -> None:
    fake = FakeFx(status=503)
    fx = _fx(fake)
    await fx.refresh()
    await fx.refresh()
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "fake",
    [
        FakeFx(exc=httpx.ConnectError("no route")),
        FakeFx(exc=httpx.ReadTimeout("slow")),
        FakeFx(exc=RuntimeError("anything at all")),
        FakeFx(status=500),
        FakeFx(status=404, body={"rate": 95.3}),  # the right number on an error status
        FakeFx(raw=b"<html>not json</html>"),
        FakeFx(raw=b'{"rate": NaN}'),
        FakeFx(body={"rate": 1e9}),
        FakeFx(body={"rate": "95"}),
    ],
)
async def test_any_failure_falls_back_to_the_default_and_never_raises(fake: FakeFx) -> None:
    fx = _fx(fake)
    r = await fx.refresh()
    assert (r.inr_per_usd, r.source) == (DEFAULT_RATE, "default")
    assert r.as_of == DEFAULT_AS_OF == "2026-11-01"
    assert DEFAULT_RATE == 95.24


async def test_a_failure_keeps_the_last_cached_value() -> None:
    docs = MemoryDocs()
    old = (NOW - timedelta(days=3)).isoformat()
    await docs.transaction(
        _put(
            {
                "rate": 94.1,
                "as_of": "2026-11-11",
                "source": "frankfurter",
                "fetched_at": old,
                "checked_at": old,
            }
        )
    )
    fake = FakeFx(exc=httpx.ConnectError("down"))
    fx = _fx(fake, docs=docs)
    r = await fx.refresh()
    assert (r.inr_per_usd, r.as_of, r.source) == (94.1, "2026-11-11", "cached")
    assert len(fake.requests) == 1  # it was stale, so it tried
    # …and the attempt is remembered, so another instance does not try again today
    assert (await docs.get(FX_DOC) or {}).get("checked_at") == NOW.isoformat()


async def test_a_fresh_firestore_value_is_used_without_fetching() -> None:
    docs = MemoryDocs()
    recent = (NOW - timedelta(hours=2)).isoformat()
    await docs.transaction(
        _put(
            {
                "rate": 95.0,
                "as_of": "2026-11-15",
                "source": "frankfurter",
                "fetched_at": recent,
                "checked_at": recent,
            }
        )
    )
    fake = FakeFx()
    fx = _fx(fake, docs=docs)
    r = await fx.refresh()
    assert (r.inr_per_usd, r.source) == (95.0, "cached") and fake.requests == []


async def test_a_bad_firestore_value_is_ignored() -> None:
    docs = MemoryDocs()
    recent = NOW.isoformat()
    await docs.transaction(_put({"rate": 9999, "as_of": "x", "checked_at": recent}))
    fx = _fx(None, docs=docs)
    assert (await fx.refresh()).source == "default"


async def test_memory_beats_firestore_after_the_first_load() -> None:
    docs, fake = MemoryDocs(), FakeFx()
    fx = _fx(fake, docs=docs)
    await fx.refresh()
    reads = docs.reads
    for _ in range(5):
        assert (await fx.rate()).inr_per_usd == 95.61
    assert docs.reads == reads  # no more database reads for the rate


async def test_firestore_down_still_gives_a_rate() -> None:
    docs = BrokenDocs(fail_reads=True, fail_tx=True)
    fake = FakeFx()
    fx = FxRates(docs=docs, default_rate=DEFAULT_RATE, http=fake.client(), clock=Clock())
    r = await fx.refresh()
    assert (r.inr_per_usd, r.source) == (95.61, "frankfurter")  # the write failed; memory has it


async def test_without_http_it_never_fetches() -> None:
    fx = _fx(None)
    assert (await fx.refresh()).source == "default"
    assert (await fx.rate()).inr_per_usd == DEFAULT_RATE


async def test_rate_never_waits_for_the_network() -> None:
    fake = FakeFx()
    fake.gate = asyncio.Event()  # the server does not answer until released
    fx = _fx(fake)
    r = await asyncio.wait_for(fx.rate(), timeout=0.5)
    assert r.source == "default"  # answered at once with what it knows
    await asyncio.sleep(0)
    assert len(fake.requests) == 1  # …and started the day's fetch in the background
    assert (await asyncio.wait_for(fx.rate(), timeout=0.5)).source == "default"
    assert len(fake.requests) == 1  # one fetch in flight, not one per reply
    fake.gate.set()
    assert (await fx.refresh()).source == "frankfurter"
    assert fx.peek().inr_per_usd == 95.61


async def test_an_owner_set_default_has_no_made_up_date() -> None:
    fx = FxRates(docs=None, default_rate=90.0, http=None, clock=Clock())
    r = await fx.refresh()
    assert (r.inr_per_usd, r.as_of, r.source) == (90.0, None, "default")


def test_settings_carry_the_default_rate() -> None:
    s = Settings(_env_file=None)
    assert s.usd_inr_rate == 95.24 and s.usd_inr_live is True
    with pytest.raises(ValueError):
        Settings(_env_file=None, usd_inr_rate=0)
    assert math.isfinite(s.usd_inr_rate)


def _put(data: dict[str, Any]) -> Any:
    async def fn(tx: Any) -> None:
        tx.set(FX_DOC, data)

    return fn
