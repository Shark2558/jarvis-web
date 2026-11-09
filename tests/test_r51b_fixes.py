# tests/test_r51b_fixes.py -- R5.1 Part B review fixes (code + security reviews), one test per fix.
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest
from faces_fakes import ROOT
from faces_fakes import UID as GUID
from fastapi import FastAPI
from google_fakes import FakeGoogle
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r51b_fakes import (
    Brain,
    Github,
    Google,
    HealthLast,
    Home,
    HomeSt,
    Meta,
    OwnRig,
    Report,
    Result,
    Usage,
    Web,
    with_keys,
)
from vitals_fakes import UID, Rig, key

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.integrations.github import GithubClient, GithubStore
from jarvis.integrations.github_meta import META_WRITE_EVERY_S, TokenMeta, parse_expiry
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.vitals.api import router
from jarvis.vitals.guard import looks_like_a_key
from jarvis.vitals.models import Provider
from jarvis.vitals.own import OwnSources
from jarvis.vitals.store import VitalsExists

TOKEN = "ghp_SuperSecretTokenValue1234567890abcd"
API = "https://api.github.com"


def by_id(board, pid):  # type: ignore[no-untyped-def]
    return next((v for v in board.items if v.provider.id == pid), None)


# ---- 1. which items Vitals stays quiet for ----
@pytest.mark.parametrize(
    ("default", "rung", "silent"),
    [
        ("anthropic", "brain_gemini", "brain_claude"),
        ("gemini", "brain_claude", "brain_gemini"),
    ],
)
async def test_only_the_default_brain_is_quiet_the_other_still_rings(
    default: str, rung: str, silent: str
) -> None:
    own = OwnSources(claude=Brain("refused"), gemini=Brain("refused"), default_brain=default)
    rig = OwnRig(own)

    await rig.svc.check_and_alert(UID, rig.notifier)

    subjects = {s.subject for _, s, _ in rig.notifier.sent}
    assert rung in subjects and silent not in subjects


async def test_with_no_known_default_brain_both_brains_ring() -> None:
    rig = OwnRig(OwnSources(claude=Brain("refused"), gemini=Brain("refused")))

    await rig.svc.check_and_alert(UID, rig.notifier)

    assert {s.subject for _, s, _ in rig.notifier.sent} >= {"brain_claude", "brain_gemini"}


async def test_google_telegram_and_home_never_ring_from_vitals() -> None:
    epoch = OwnRig(OwnSources()).epoch
    own = OwnSources(
        google=Google(False, True),
        health=HealthLast(Report((Result("telegram", "down", epoch),))),
        home=Home(HomeSt("offline", epoch - 3600)),
    )
    rig = OwnRig(own)

    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.sent == []
    board = await rig.svc.board(UID)
    assert {by_id(board, i).status for i in ("google_link", "telegram_bot", "home_link")} == {"red"}


# ---- 2. a revoked GitHub token is red ----
def gh_client() -> tuple[GithubClient, FakeGoogle, MemoryDocs, list[float]]:
    fake, docs, now = FakeGoogle(), MemoryDocs(), [1_800_000_000.0]
    client = GithubClient(
        GithubStore(docs, Keyring(ROOT)), http=fake.client(), clock=lambda: now[0]
    )
    return client, fake, docs, now


def ok_headers(**extra: str) -> dict[str, str]:
    return {
        "x-ratelimit-limit": "5000",
        "x-ratelimit-used": "1",
        "x-ratelimit-reset": "1800003600",
        **extra,
    }


async def gh_connect(client: GithubClient, fake: FakeGoogle, **headers: str) -> None:
    fake.on(
        "GET",
        f"{API}/user",
        httpx.Response(200, json={"login": "dev"}, headers=ok_headers(**headers)),
    )
    await client.connect(GUID, SecretStr(TOKEN))
    fake.routes.clear()


async def test_a_401_from_github_is_recorded_and_clears_on_success_and_reconnect() -> None:
    client, fake, docs, now = gh_client()
    await gh_connect(client, fake)
    fake.on("GET", f"{API}/user/repos", httpx.Response(401, json={}))
    now[0] += 5
    with pytest.raises(Exception, match="refused"):
        await client.repos(GUID)

    meta = await client.token_meta(GUID)
    assert meta is not None and meta.rejected_at == now[0]
    assert (
        await GithubClient(GithubStore(docs, Keyring(ROOT)), http=fake.client()).token_meta(GUID)
    ).rejected_at == now[0]  # type: ignore[union-attr]

    fake.routes.clear()
    fake.on("GET", f"{API}/user/repos", httpx.Response(200, json=[], headers=ok_headers()))
    now[0] += 5
    await client.repos(GUID)
    assert (await client.token_meta(GUID)).rejected_at is None  # type: ignore[union-attr]

    fake.routes.clear()
    fake.on("GET", f"{API}/user/repos", httpx.Response(401, json={}))
    with pytest.raises(Exception, match="refused"):
        await client.repos(GUID)
    await gh_connect(client, fake)
    assert (await client.token_meta(GUID)).rejected_at is None  # type: ignore[union-attr]


async def test_a_refused_github_token_is_red_with_the_fix() -> None:
    epoch = OwnRig(OwnSources()).epoch
    rig = OwnRig(
        OwnSources(github=Github(Meta(epoch, None, 5000, 1, epoch + 600, rejected_at=epoch)))
    )

    v = by_id(await rig.svc.board(UID), "github_token")

    assert (v.status, v.reason) == ("red", "the token was refused")
    assert "Paste a new token in Connectors" in v.fix


# ---- 3. an unreadable expiry is not "no expiry" ----
@pytest.mark.parametrize(
    "value", ["31/12/2026 PST", "1960-01-01 00:00:00 UTC", "9999-12-31 23:59:59 UTC", "soon"]
)
async def test_a_present_but_unreadable_expiry_is_unknown_and_survives_reload(value: str) -> None:
    client, fake, docs, _ = gh_client()
    await gh_connect(client, fake, **{"github-authentication-token-expiration": value})

    meta = await client.token_meta(GUID)
    assert meta is not None and meta.expires_at is None and meta.expiry_unreadable is True
    other = GithubClient(GithubStore(docs, Keyring(ROOT)), http=fake.client())
    assert (await other.token_meta(GUID)).expiry_unreadable is True  # type: ignore[union-attr]

    epoch = OwnRig(OwnSources()).epoch
    rig = OwnRig(OwnSources(github=Github(Meta(epoch, None, expiry_unreadable=True))))
    v = by_id(await rig.svc.board(UID), "github_token")
    assert (v.status, v.reason) == ("unknown", "its expiry date couldn't be read")
    assert "doesn't expire" not in v.provider.note


async def test_an_absent_expiry_header_still_means_no_expiry() -> None:
    client, fake, _, _ = gh_client()
    await gh_connect(client, fake)
    meta = await client.token_meta(GUID)
    assert meta is not None and meta.expiry_unreadable is False and meta.expires_at is None
    epoch = OwnRig(OwnSources()).epoch
    rig = OwnRig(OwnSources(github=Github(Meta(epoch))))
    v = by_id(await rig.svc.board(UID), "github_token")
    assert v.status == "ok" and "doesn't expire" in v.provider.note


def test_parse_expiry_marks_odd_values_unreadable_not_absent() -> None:
    assert parse_expiry("1960-01-01 00:00:00 UTC") is None
    assert parse_expiry("9999-12-31 23:59:59 UTC") is None
    assert (
        parse_expiry("2026-12-31 23:59:59 UTC")
        == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
    )


# ---- 4. the derived id does not trip the guard ----
LONG_LABELS = [
    "Subscription Renewal Reminder",
    "Electricity bill payment reminder",
    "Annual vehicle insurance premium renewal",
    "Quarterly professional membership dues",
    "Home loan equated monthly instalment",
]


def slug(label: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", label.lower())[:34].strip("-")


@pytest.mark.parametrize("label", LONG_LABELS)
def test_ordinary_long_labels_are_not_taken_for_keys(label: str) -> None:
    p = Provider(id=slug(label), label=label, kind="key", source="manual")
    assert p.label == label
    assert not looks_like_a_key([label])


def test_real_key_like_strings_in_the_label_are_still_refused() -> None:
    for bad in ("sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv", "ghp_" + "a1B2c3D4e5" * 4, "a" * 40):
        with pytest.raises(ValueError):
            Provider(id="car", label=bad, kind="key", source="manual")
    with pytest.raises(ValueError):  # an id that is itself a key
        Provider(id="sk-ant-api03-abcdefghijklmnop", label="Car", kind="key", source="manual")
    with pytest.raises(ValueError):  # a long hex id
        Provider(id="0123456789abcdef0123456789abcdef", label="Car", kind="key", source="manual")


# ---- 5. create-only add ----
@pytest.fixture
async def api():  # type: ignore[no-untyped-def]
    rig = Rig()
    app = FastAPI()
    app.include_router(router)
    app.state.vitals = rig.svc
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield rig, c


async def test_create_never_overwrites_an_existing_record(api) -> None:  # type: ignore[no-untyped-def]
    rig, c = api
    body = {"id": "car-insurance", "label": "Car insurance", "kind": "key", "note": "first"}
    assert (await c.put("/v1/vitals/keys", json={**body, "create": True})).status_code == 200

    dup = await c.put("/v1/vitals/keys", json={**body, "note": "second", "create": True})

    assert dup.status_code == 409 and "taken" in dup.json()["detail"]
    assert (await rig.store.list_manual(UID))[0].note == "first"
    assert (await c.put("/v1/vitals/keys", json={**body, "note": "edited"})).status_code == 200
    assert (await rig.store.list_manual(UID))[0].note == "edited"  # Edit keeps the upsert


async def test_create_in_the_store_raises_exists(api) -> None:  # type: ignore[no-untyped-def]
    rig, _ = api
    await rig.svc.set_key(UID, key("k"), create=True)
    with pytest.raises(VitalsExists):
        await rig.svc.set_key(UID, key("k"), create=True)


# ---- 6/7. odd headers cost only their own field ----
def hdrs(**h: str) -> httpx.Headers:
    return httpx.Headers({k: v.encode("utf-8") for k, v in h.items()})


def test_out_of_range_reset_drops_only_the_limit_part() -> None:
    m = TokenMeta.observe(
        hdrs(
            **{
                "x-ratelimit-limit": "5000",
                "x-ratelimit-used": "3",
                "x-ratelimit-reset": str(10**12),
                "github-authentication-token-expiration": "2026-12-31 23:59:59 UTC",
            }
        ),
        1.0,
        status=200,
        before=None,
    )
    assert m is not None and m.rate_reset is None and m.expires_at is not None


async def test_an_out_of_range_reset_does_not_blank_the_github_item() -> None:
    epoch = OwnRig(OwnSources()).epoch
    meta = Meta(epoch, epoch + 86400 * 90, 5000, 3, 1e300)
    rig = OwnRig(OwnSources(github=Github(meta)))
    v = by_id(await rig.svc.board(UID), "github_token")
    assert v.status == "ok" and v.provider.expires_at is not None


def test_stored_absurd_times_read_as_none() -> None:
    m = TokenMeta.read({"seen_at": 1.0, "expires_at": 1e300, "rate_reset": 1e300})
    assert m is not None and m.expires_at is None and m.rate_reset is None


@pytest.mark.parametrize("odd", ["²", "٣", "1" * 40, "-5", "1.5", ""])
def test_a_non_ascii_or_odd_integer_header_drops_only_that_field(odd: str) -> None:
    m = TokenMeta.observe(
        hdrs(
            **{
                "x-ratelimit-limit": "5000",
                "x-ratelimit-used": odd,
                "github-authentication-token-expiration": "2026-12-31 23:59:59 UTC",
            }
        ),
        1.0,
        status=200,
        before=None,
    )
    assert (
        m is not None and m.rate_limit == 5000 and m.rate_used is None and m.expires_at is not None
    )


# ---- 8. meta writes: backoff and the reconnect race ----
async def test_a_failed_meta_write_backs_off() -> None:
    client, fake, _, now = gh_client()
    await gh_connect(client, fake)
    calls = 0

    async def boom(*_a: object) -> bool:
        nonlocal calls
        calls += 1
        raise OSError("store down")

    client._store.note_meta = boom  # type: ignore[method-assign]  # noqa: SLF001
    fake.on("GET", f"{API}/user/repos", httpx.Response(200, json=[], headers=ok_headers()))
    now[0] += META_WRITE_EVERY_S + 1
    for _ in range(5):
        await client.repos(GUID)
        now[0] += 1
    assert calls == 1
    now[0] += META_WRITE_EVERY_S
    await client.repos(GUID)
    assert calls == 2


async def test_a_read_in_flight_across_a_reconnect_does_not_write_stale_meta() -> None:
    client, fake, docs, now = gh_client()
    await gh_connect(
        client, fake, **{"github-authentication-token-expiration": "2026-12-31 23:59:59 UTC"}
    )
    gate, started = asyncio.Event(), asyncio.Event()
    real = client._get  # noqa: SLF001

    async def slow(token, path, params, *, seen=None):  # type: ignore[no-untyped-def]
        started.set()
        await gate.wait()
        return await real(token, path, params, seen=seen)

    client._get = slow  # type: ignore[method-assign]  # noqa: SLF001
    fake.on(
        "GET",
        f"{API}/user/repos",
        httpx.Response(
            200,
            json=[],
            headers=ok_headers(
                **{"github-authentication-token-expiration": "2027-01-01 00:00:00 UTC"}
            ),
        ),
    )
    now[0] += META_WRITE_EVERY_S + 1
    task = asyncio.create_task(client.repos(GUID))
    await started.wait()

    client._get = real  # type: ignore[method-assign]  # noqa: SLF001
    fake.on(
        "GET",
        f"{API}/user",
        httpx.Response(
            200,
            json={"login": "dev"},
            headers=ok_headers(
                **{"github-authentication-token-expiration": "2030-01-01 00:00:00 UTC"}
            ),
        ),
    )
    await client.connect(GUID, SecretStr(TOKEN))
    gate.set()
    await task

    want = datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    assert docs._data[f"jarvis_connectors_github/{GUID}"]["meta"]["expires_at"] == want  # noqa: SLF001
    assert (await client.token_meta(GUID)).expires_at == want  # type: ignore[union-attr]


# ---- 9. shadowed manual records ----
async def test_a_stored_record_under_a_reserved_id_is_shown_old_and_deletable() -> None:
    rig = OwnRig(OwnSources())
    from jarvis.storage.docs import Set

    p = Provider(id="home_link", label="Home thing", kind="key", source="manual")
    await rig.docs.write(
        [
            Set(
                f"jarvis_vitals_providers/{rig.store._name(UID, 'home_link')}",
                {**p.fields(), "user_id": UID},
            )
        ]
    )  # noqa: SLF001

    board = await rig.svc.board(UID)
    old = [v for v in board.items if v.provider.source == "manual" and v.provider.id == "home_link"]
    assert [v.provider.label for v in old] == ["Home thing (old)"]

    assert await rig.svc.delete_key(UID, "home_link") is True
    board = await rig.svc.board(UID)
    assert not [v for v in board.items if v.provider.source == "manual"]
    assert await rig.svc.delete_key(UID, "home_link") is False


async def test_deleting_a_shadowed_record_keeps_the_auto_items_alert_status() -> None:
    rig = OwnRig(OwnSources())
    await rig.store.set_status(UID, "ai_spend", "amber", rig.clock())
    await rig.svc.delete_key(UID, "ai_spend")
    assert await rig.store.last_status(UID, "ai_spend") == "amber"


async def test_shadowed_records_never_alert() -> None:
    rig = OwnRig(OwnSources())
    from jarvis.storage.docs import Set

    p = Provider(id="github_token", label="Old", kind="key", source="manual", limit=1, used=5)
    await rig.docs.write(
        [
            Set(
                f"jarvis_vitals_providers/{rig.store._name(UID, 'github_token')}",
                {**p.fields(), "user_id": UID},
            )
        ]
    )  # noqa: SLF001
    await rig.svc.check_and_alert(UID, rig.notifier)
    assert rig.notifier.sent == []


# ---- 10. GET /v1/vitals: per-owner rate limit and a 15 s cache ----
async def test_the_board_is_cached_for_fifteen_seconds_and_writes_refresh_it(api) -> None:  # type: ignore[no-untyped-def]
    rig, c = api
    first = (await c.get("/v1/vitals")).json()
    rig.billing.view = rig.billing.view.model_copy(update={"used_inr": 450.0})
    assert (await c.get("/v1/vitals")).json() == first

    rig.clock.advance(seconds=16)
    assert (await c.get("/v1/vitals")).json() != first

    await c.put("/v1/vitals/keys", json={"id": "k", "label": "K", "kind": "key"})
    ids = {i["id"] for i in (await c.get("/v1/vitals")).json()["items"]}
    assert "k" in ids


async def test_get_vitals_is_rate_limited_per_owner(api) -> None:  # type: ignore[no-untyped-def]
    _, c = api
    codes = [(await c.get("/v1/vitals")).status_code for _ in range(80)]
    assert 429 in codes and codes[0] == 200
    limited = await c.get("/v1/vitals")
    assert limited.status_code == 429 and "Retry-After" in limited.headers


# ---- 11. Telegram age, concurrency ----
async def test_an_old_telegram_result_is_unknown_run_a_check() -> None:
    rig = OwnRig(OwnSources(health=HealthLast()))
    rig.own.health.report = Report((Result("telegram", "ok", rig.epoch - 3 * 3600),))  # type: ignore[union-attr]
    v = by_id(await rig.svc.board(UID), "telegram_bot")
    assert v.status == "unknown" and "systems check" in v.provider.note

    rig.own.health.report = Report((Result("telegram", "ok", rig.epoch - 3600),))  # type: ignore[union-attr]
    assert by_id(await rig.svc.board(UID), "telegram_bot").status == "ok"


async def test_the_sources_run_concurrently() -> None:
    class SlowGoogle(Google):
        async def status(self, uid: str):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.3)
            return await super().status(uid)

    class SlowHome(Home):
        async def status(self, uid: str):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.3)
            return await super().status(uid)

    class SlowWeb(Web):
        async def usage(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.3)
            return Usage(1, 10)

    class SlowGh(Github):
        async def token_meta(self, uid: str):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.3)
            return await super().token_meta(uid)

    rig = OwnRig(
        OwnSources(
            google=SlowGoogle(),
            home=SlowHome(HomeSt("online", 0.0)),
            web=SlowWeb(),
            github=SlowGh(Meta(1.0)),
        )
    )
    t0 = time.monotonic()
    board = await rig.svc.board(UID)
    elapsed = time.monotonic() - t0

    assert by_id(board, "web_credits") and by_id(board, "google_link")
    assert elapsed < 0.7  # four 0.3 s sources: ~0.3 s together, 1.2 s if serial


def test_with_keys_helper_is_importable() -> None:  # keeps the shared helper used
    assert with_keys().anthropic_api_key is not None


def test_the_usage_line_reads_for_a_singular_label() -> None:
    from jarvis.vitals.own import LABELS

    assert LABELS["web_credits"] == "Web search allowance"
