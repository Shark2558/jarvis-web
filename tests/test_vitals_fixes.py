# tests/test_vitals_fixes.py -- R4 A review fixes: every entry path is guarded, alerts survive one
# bad read, the hourly throttle, billing edge cases, plain 422s.
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from vitals_fakes import T0, UID, FakeBilling, Rig, key, usage_view

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.api import router
from jarvis.vitals.job import POLL_EVERY_S, VitalsJob
from jarvis.vitals.models import aware, zone_of
from jarvis.vitals.store import VitalsStore, VitalsUnavailable
from jarvis.vitals.tools import VitalsDeps, tools

SECRET = "sk-" + "A1b2C3d4" * 5
ID_SECRET = "sk-" + "a1b2c3d4" * 4
BAD = {"id": ID_SECRET, "label": SECRET, "note": SECRET, "unit": "sk-a1b2c3d4e5f6g7h8"}


def gateway(rig: Rig) -> Gateway:
    reg = ToolRegistry()
    for t in tools(VitalsDeps(rig.svc, rig.settings)):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=AuditLog())


async def call(gw: Gateway, name: str, **args: Any):  # type: ignore[no-untyped-def]
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope="u_owner:s1")


# --- D-A2: the guard runs in Tool.check, before any card or audit text ---------------------


@pytest.mark.parametrize("field", ["id", "label", "note", "unit"])
def test_check_refuses_a_pasted_key_before_summary_or_run(field: str) -> None:
    rig = Rig()
    tool = {t.name: t for t in tools(VitalsDeps(rig.svc, rig.settings))}["vitals_set_key"]
    args = {"id": "k", "label": "K", "kind": "key", field: BAD[field]}

    with pytest.raises(ValueError) as ei:
        tool.validate(args)

    assert SECRET not in str(ei.value) and "never" in str(ei.value).lower()


async def test_gateway_refuses_before_run_and_nothing_is_stored_or_echoed() -> None:
    rig = Rig()
    res = await call(gateway(rig), "vitals_set_key", id="k", label="K", kind="key", note=SECRET)

    assert res.outcome is GatewayOutcome.ERROR and "never" in (res.error or "").lower()
    assert SECRET not in repr(res)
    assert await rig.store.list_manual(UID) == []


def test_set_key_summary_is_a_masked_label_and_delete_shows_only_the_id() -> None:
    rig = Rig()
    by = {t.name: t for t in tools(VitalsDeps(rig.svc, rig.settings))}

    card = by["vitals_set_key"].summary(
        {"id": "k", "label": "A very long label indeed", "kind": "key"}
    )
    gone = by["vitals_delete_key"].summary({"id": "brave", "note": SECRET})

    assert "A very long " in card and "indeed" not in card and "…" in card
    assert "brave" in gone and SECRET not in gone


def test_delete_check_rejects_a_bad_id() -> None:
    tool = {t.name: t for t in tools(VitalsDeps(Rig().svc, Rig().settings))}["vitals_delete_key"]

    with pytest.raises(ValueError):
        tool.validate({"id": SECRET})


async def test_set_key_date_only_expiry_is_end_of_day_in_the_owner_zone() -> None:
    rig = Rig()
    await call(
        gateway(rig), "vitals_set_key", id="k", label="K", kind="key", expires_at="2027-01-15"
    )

    (rec,) = await rig.store.list_manual(UID)

    assert rec.expires_at is not None
    assert rec.expires_at.isoformat() == "2027-01-15T23:59:59"  # the zone is applied at use
    assert aware(rec.expires_at, zone_of("Asia/Kolkata")).isoformat().endswith("+05:30")


# --- REST route: same guard, plain 422, no echo ------------------------------------------


@pytest.fixture
async def rig_client() -> AsyncIterator[tuple[Rig, AsyncClient]]:
    rig = Rig()
    app = FastAPI()
    app.include_router(router)
    app.state.vitals = rig.svc
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: UID
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield rig, c


async def test_put_refuses_a_key_value_in_any_field_without_echoing_it(rig_client) -> None:  # type: ignore[no-untyped-def]
    rig, c = rig_client
    for field in ("note", "label", "unit"):
        body = {"id": "k", "label": "K", "kind": "key", field: SECRET}
        r = await c.put("/v1/vitals/keys", json=body)
        assert r.status_code == 422 and SECRET not in r.text
    r = await c.put("/v1/vitals/keys", json={"id": ID_SECRET, "label": "K", "kind": "key"})
    assert r.status_code == 422 and SECRET not in r.text
    assert await rig.store.list_manual(UID) == []


async def test_put_validation_error_never_echoes_input_or_unknown_field_names(rig_client) -> None:  # type: ignore[no-untyped-def]
    _, c = rig_client

    r1 = await c.put("/v1/vitals/keys", json={"id": "k", "label": "K", "kind": SECRET})
    r2 = await c.put("/v1/vitals/keys", json={"id": "k", "label": "K", "kind": "key", SECRET: 1})
    r3 = await c.put("/v1/vitals/keys", content=json_bytes(SECRET))

    for r in (r1, r2, r3):
        assert r.status_code == 422 and SECRET not in r.text
    assert "kind" in r1.json()["detail"]


def json_bytes(s: str) -> bytes:
    return ('"' + s + '"').encode()


async def test_put_date_only_expiry_then_board_does_not_crash(rig_client) -> None:  # type: ignore[no-untyped-def]
    _, c = rig_client

    ok = await c.put(
        "/v1/vitals/keys",
        json={"id": "k", "label": "K", "kind": "key", "expires_at": "2026-12-01"},
    )
    board = await c.get("/v1/vitals")

    assert ok.status_code == 200 and board.status_code == 200
    assert any(i["id"] == "k" for i in board.json()["items"])


async def test_delete_with_a_bad_id_is_a_422_not_a_503(rig_client) -> None:  # type: ignore[no-untyped-def]
    _, c = rig_client

    assert (await c.delete("/v1/vitals/keys/Bad.Id")).status_code == 422


# --- store ---------------------------------------------------------------------------------


async def test_store_name_is_collision_free_and_rejects_bad_ids() -> None:
    assert VitalsStore._name("a__b", "c") != VitalsStore._name("a", "b__c")
    for bad in ("../x", "A", "", "x" * 41):
        with pytest.raises(ValueError):
            VitalsStore._name(UID, bad)


async def test_storage_failure_keeps_the_cause_chained_but_plain_words() -> None:
    rig = Rig()

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("secret detail")

    rig.docs.query = boom  # type: ignore[method-assign]

    with pytest.raises(VitalsUnavailable) as ei:
        await rig.store.list_manual(UID)

    assert "secret detail" not in str(ei.value)
    assert isinstance(ei.value.__cause__, RuntimeError)


async def test_cap_counts_raw_rows_including_unreadable_ones() -> None:
    from jarvis.storage.docs import Set
    from jarvis.vitals.models import MAX_MANUAL
    from jarvis.vitals.store import VitalsFull

    rig = Rig()
    ops = [
        Set(f"jarvis_vitals_providers/junk{i}", {"user_id": UID, "kind": 5, "label": f"j{i}"})
        for i in range(MAX_MANUAL)
    ]
    await rig.docs.write(ops)

    with pytest.raises(VitalsFull):
        await rig.store.put(UID, key("new"))


# --- auto: billing edge cases ---------------------------------------------------------------


async def test_unreadable_stored_limit_is_unknown_not_ok() -> None:
    view = usage_view(10, None).model_copy(update={"limit_unreadable": True})
    rig = Rig(billing=FakeBilling(view))

    board = await rig.svc.board(UID)

    assert next(v for v in board.items if v.provider.id == "ai_spend").status == "unknown"


async def test_zero_limit_with_spend_is_red() -> None:
    rig = Rig(billing=FakeBilling(usage_view(5, 0)))

    board = await rig.svc.board(UID)

    assert next(v for v in board.items if v.provider.id == "ai_spend").status == "red"


# --- alerts: at-least-once, per-provider isolation, prefix ----------------------------------


async def test_alert_text_has_the_fixed_prefix() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=10, used=10))
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.sent[0][2].startswith("Vitals — ")


async def test_set_status_failing_after_a_send_resends_next_time() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=10, used=10))
    real = rig.store.set_status
    calls = {"n": 0}

    async def flaky(*a: Any, **k: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise VitalsUnavailable("down")
        await real(*a, **k)

    rig.store.set_status = flaky  # type: ignore[method-assign]

    first = await rig.svc.check_and_alert(UID, rig.notifier)
    second = await rig.svc.check_and_alert(UID, rig.notifier)

    assert first == 1 and second == 1  # at-least-once: the alert is repeated, never lost
    assert await rig.svc.check_and_alert(UID, rig.notifier) == 0


async def test_one_bad_status_read_does_not_abort_the_owner() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("aaa", limit=10, used=10))
    await rig.svc.set_key(UID, key("bbb", limit=10, used=10))
    real = rig.store.last_status

    async def flaky(uid: str, pid: str):  # type: ignore[no-untyped-def]
        if pid == "aaa":
            raise VitalsUnavailable("down")
        return await real(uid, pid)

    rig.store.last_status = flaky  # type: ignore[method-assign]

    assert await rig.svc.check_and_alert(UID, rig.notifier) == 1


# --- job throttle ---------------------------------------------------------------------------


async def test_job_skips_an_owner_polled_less_than_an_hour_ago() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("a", limit=10, used=10))
    job = VitalsJob(rig.svc, rig.notifier, clock=rig.clock)
    polled: list[str] = []
    real = rig.svc.check_and_alert

    async def spy(uid: str, notifier: Any) -> int:
        polled.append(uid)
        return await real(uid, notifier)

    rig.svc.check_and_alert = spy  # type: ignore[method-assign]

    await job.run([UID])
    rig.clock.advance(seconds=POLL_EVERY_S - 60)
    await job.run([UID])
    rig.clock.advance(seconds=120)
    await job.run([UID])

    assert polled == [UID, UID]


def test_poll_interval_is_an_hour() -> None:
    assert POLL_EVERY_S == 3600
    assert T0 + timedelta(seconds=POLL_EVERY_S) > T0
