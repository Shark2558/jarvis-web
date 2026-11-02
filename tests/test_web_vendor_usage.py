# tests/test_web_vendor_usage.py — slice 11 D7 (b): Tavily's own count (GET /usage, verified at
# docs.tavily.com/documentation/api-reference/endpoint/usage on 2026-11-02; not among the
# credit-charging endpoints) cross-checks the local monthly ledger at most once a day, from the
# scheduler tick. The correction only RAISES the month's count (never lowers it: a low or glitchy
# vendor reading can't reopen web search), caps at the 900 stop, and is skipped while the owner's
# month (IST) is not yet the vendor's (UTC) month. Fake transport only: no network.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from test_scheduler_auth import KEY as JWK
from test_scheduler_auth import SA, FakeJWKS, token, verifier
from web_fakes import USAGE_URL, FakeTavily

from jarvis.api import create_app
from jarvis.api.scheduler_auth import TICK_PATH
from jarvis.config import SessionBackend, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import Doc, MemoryDocs, Set
from jarvis.web.allowance import MONTHLY_CREDITS, AllowanceReached, WebAllowance
from jarvis.web.ports import UsageReporter, VendorUsage, WebError
from jarvis.web.service import WebService, build_web_service
from jarvis.web.tavily import TavilyProvider
from jarvis.web.vendor_usage import CHECK_EVERY, VendorCheck

KEY = "tvly-test-secret-key"
NOON = datetime(2026, 11, 15, 6, 30, tzinfo=UTC)  # 12:00 IST


class Clock:
    def __init__(self, now: datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _provider(fake: FakeTavily) -> TavilyProvider:
    return TavilyProvider(SecretStr(KEY), http=fake.client())


def _rig(fake: FakeTavily, clock: Clock) -> tuple[VendorCheck, WebAllowance, MemoryDocs]:
    docs = MemoryDocs()
    allowance = WebAllowance(docs, now=clock)
    return VendorCheck(docs, _provider(fake), allowance, now=clock), allowance, docs


# ---- the adapter: GET /usage ----------------------------------------------------------------


async def test_usage_is_a_get_with_bearer_auth_and_reads_the_documented_shape() -> None:
    fake = FakeTavily()
    p = _provider(fake)
    assert isinstance(p, UsageReporter)
    u = await p.usage()
    [req] = fake.requests
    assert req.method == "GET" and str(req.url) == USAGE_URL
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.content == b""  # nothing in a body, the key only in the header
    assert u == VendorUsage(used=500, limit=1000, exhausted=False)  # the larger of key / plan


@pytest.mark.parametrize(
    ("key", "account", "expected"),
    [
        ({"usage": 1000, "limit": 1000}, {"plan_usage": 10}, VendorUsage(1000, 1000, True)),
        ({"usage": 3, "limit": None}, {"plan_usage": 1000, "plan_limit": 1000},
         VendorUsage(1000, 1000, True)),
        ({"usage": 7, "limit": None}, {}, VendorUsage(7, None, False)),
        ({"usage": "7", "limit": True}, {"plan_usage": 9, "plan_limit": -1},
         VendorUsage(9, None, False)),
        ({"usage": 2.0}, {"plan_usage": 4}, VendorUsage(4, None, False)),
        # slice 11 review LOW-5: a limit of 0 is "none set", never "used up"
        ({"usage": 0, "limit": 0}, {"plan_usage": 0, "plan_limit": 0}, VendorUsage(0, None, False)),
        ({"usage": 5, "limit": 0}, {"plan_usage": 7, "plan_limit": 1000},
         VendorUsage(7, 1000, False)),
        # integral floats are counts; a fraction, NaN or infinity is not
        ({"usage": 12.0, "limit": 1000.0}, {}, VendorUsage(12, 1000, False)),
        ({"usage": 1000.0, "limit": 1000}, {}, VendorUsage(1000, 1000, True)),
        ({"usage": 3.5, "limit": 7.25}, {"plan_usage": 9, "plan_limit": -0.0},
         VendorUsage(9, None, False)),
    ],
)  # fmt: skip
async def test_usage_fields_are_type_checked(
    key: dict[str, object], account: dict[str, object], expected: VendorUsage
) -> None:
    fake = FakeTavily()
    fake.usage = {"key": key, "account": account}
    assert await _provider(fake).usage() == expected


async def test_nan_and_infinity_are_never_counts() -> None:
    """Python's JSON reader accepts NaN / Infinity: a count or limit that is one is dropped."""
    raw = (
        b'{"key": {"usage": NaN, "limit": Infinity},'
        b' "account": {"plan_usage": 2, "plan_limit": -Infinity}}'
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw))
    )
    assert await TavilyProvider(SecretStr(KEY), http=http).usage() == VendorUsage(2, None, False)
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b'{"key": {"usage": Infinity}}')
        )
    )
    with pytest.raises(WebError, match="unreadable"):
        await TavilyProvider(SecretStr(KEY), http=http).usage()


@pytest.mark.parametrize(
    "body", [{}, {"key": "x"}, {"key": {"usage": -1}, "account": {"plan_usage": "a"}}, [1, 2]]
)
async def test_unreadable_usage_is_an_error(body: object) -> None:
    fake = FakeTavily()
    fake.usage = body
    with pytest.raises(WebError, match="unreadable"):
        await _provider(fake).usage()


async def test_usage_errors_are_plain_words_without_vendor_text_or_the_key() -> None:
    fake = FakeTavily()
    fake.status = 401
    with pytest.raises(WebError) as exc:
        await _provider(fake).usage()
    assert "vendor text" not in str(exc.value) and KEY not in str(exc.value)


# ---- the ledger correction ------------------------------------------------------------------


async def test_the_correction_raises_the_count_and_keeps_the_side_counts() -> None:
    clock = Clock()
    a = WebAllowance(MemoryDocs(), now=clock)
    await a.reserve(1, kind="search")
    use = await a.correct(VendorUsage(used=120, limit=1000, exhausted=False))
    assert use is not None and use.credits == 120 and use.searches == 1


async def test_the_correction_never_lowers_the_count() -> None:
    a = WebAllowance(MemoryDocs(), now=Clock())
    for _ in range(5):
        await a.reserve(1, kind="search")
    use = await a.correct(VendorUsage(used=2, limit=1000, exhausted=False))
    assert use is not None and use.credits == 5


async def test_the_correction_caps_at_the_stop_and_an_exhausted_vendor_closes_the_month() -> None:
    a = WebAllowance(MemoryDocs(), now=Clock())
    use = await a.correct(VendorUsage(used=990, limit=1000, exhausted=False))
    assert use is not None and use.credits == MONTHLY_CREDITS
    b = WebAllowance(MemoryDocs(), now=Clock())
    use = await b.correct(VendorUsage(used=3, limit=3, exhausted=True))
    assert use is not None and use.credits == MONTHLY_CREDITS
    with pytest.raises(AllowanceReached):
        await b.reserve(1, kind="search")


async def test_an_unreadable_counter_stays_closed() -> None:
    clock = Clock()
    docs = MemoryDocs()
    a = WebAllowance(docs, now=clock)
    await docs.write([Set(f"jarvis_web_usage/{a.month()}", {"credits": "lots"})])
    assert await a.correct(VendorUsage(used=10, limit=None, exhausted=False)) is None
    assert (await docs.get(f"jarvis_web_usage/{a.month()}")) == {"credits": "lots"}


# ---- the daily check ------------------------------------------------------------------------


async def test_the_check_corrects_the_ledger_once_a_day() -> None:
    fake, clock = FakeTavily(), Clock()
    check, allowance, _ = _rig(fake, clock)
    got = await check.run()
    assert got == VendorUsage(500, 1000, False)
    assert (await allowance.usage()).credits == 500
    clock.now += timedelta(hours=23)
    assert await check.run() is None  # not due yet: no call
    clock.now += timedelta(hours=1)
    fake.usage["account"]["plan_usage"] = 640
    assert await check.run() == VendorUsage(640, 1000, False)
    assert (await allowance.usage()).credits == 640
    assert [r.url.path for r in fake.requests] == ["/usage", "/usage"]
    assert CHECK_EVERY == timedelta(hours=24)


async def test_the_once_a_day_claim_is_shared_by_every_instance() -> None:
    fake, clock = FakeTavily(), Clock()
    check, allowance, docs = _rig(fake, clock)
    other = VendorCheck(docs, _provider(fake), allowance, now=clock)  # another Cloud Run instance
    assert await check.run() is not None
    assert await other.run() is None
    assert len(fake.requests) == 1


async def test_no_check_while_the_owners_month_is_not_the_vendors_month() -> None:
    fake = FakeTavily()
    clock = Clock(datetime(2026, 11, 30, 20, 0, tzinfo=UTC))  # 1 Dec 01:30 IST, still Nov in UTC
    check, allowance, _ = _rig(fake, clock)
    assert await check.run() is None
    assert fake.requests == []  # last month's vendor count never lands in the new month
    clock.now = datetime(2026, 12, 1, 0, 30, tzinfo=UTC)  # 06:00 IST: both December
    assert await check.run() is not None  # not claimed by the skipped tick
    assert (await allowance.usage()).month == "2026-12"


async def test_a_failing_vendor_never_raises_and_never_changes_the_ledger() -> None:
    fake, clock = FakeTavily(), Clock()
    check, allowance, _ = _rig(fake, clock)
    fake.status = 503
    assert await check.run() is None
    assert (await allowance.usage()).credits == 0
    fake.status = None
    assert await check.run() is None  # the day's check was used: no retry storm
    clock.now += CHECK_EVERY
    assert await check.run() is not None


async def test_the_check_costs_no_credit() -> None:
    fake, clock = FakeTavily(), Clock()
    fake.usage = {"key": {"usage": 0, "limit": 1000}, "account": {"plan_usage": 0}}
    check, allowance, _ = _rig(fake, clock)
    await check.run()
    assert (await allowance.usage()).credits == 0  # nothing reserved for the check itself
    assert all(r.url.path == "/usage" for r in fake.requests)


async def test_the_vendor_snapshot_is_kept_for_the_record() -> None:
    fake, clock = FakeTavily(), Clock()
    check, _, docs = _rig(fake, clock)
    await check.run()
    snap = await docs.get("jarvis_web_vendor_usage/tavily")
    assert snap is not None and snap["used"] == 500 and snap["limit"] == 1000
    assert snap["checked_at"] == clock.now and snap["month"] == "2026-11"
    assert KEY not in json.dumps(snap, default=str)


async def test_a_broken_store_never_raises() -> None:
    class Broken(MemoryDocs):
        async def transaction(self, fn):  # type: ignore[no-untyped-def,override]
            raise ConnectionError("firestore unreachable")

        async def get(self, path: str) -> Doc | None:
            raise ConnectionError("firestore unreachable")

    fake, clock = FakeTavily(), Clock()
    allowance = WebAllowance(Broken(), now=clock)
    check = VendorCheck(Broken(), _provider(fake), allowance, now=clock)
    assert await check.run() is None
    assert fake.requests == []


# ---- wiring ---------------------------------------------------------------------------------


async def test_the_service_runs_the_check_and_never_raises() -> None:
    fake, clock = FakeTavily(), Clock()
    check, allowance, _ = _rig(fake, clock)
    svc = WebService(_provider(fake), allowance, vendor_check=check)
    await svc.check_vendor_usage()
    assert (await allowance.usage()).credits == 500
    await WebService(_provider(fake), allowance).check_vendor_usage()  # no check: a no-op


def test_build_wires_the_check_for_tavily(settings: Settings) -> None:
    s = settings.model_copy(update={"web_search_enabled": True, "tavily_api_key": SecretStr(KEY)})
    svc = build_web_service(s, MemoryDocs())
    assert svc is not None and svc.vendor_check is not None


async def test_the_scheduler_tick_runs_the_check(settings: Settings) -> None:
    s = settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "session_backend": SessionBackend.FIRESTORE,
        }
    )
    app = create_app(
        s, provider=MockProvider(), store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(JWK)),
    )  # fmt: skip
    async with app.router.lifespan_context(app):
        ran: list[bool] = []

        class Web:
            async def check_vendor_usage(self) -> None:
                ran.append(True)

            async def aclose(self) -> None:
                return None

        app.state.web = Web()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
        assert r.status_code == 200 and ran == [True]
