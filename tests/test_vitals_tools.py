# tests/test_vitals_tools.py -- R4 D2/D12: vitals_show / vitals_set_key / vitals_delete_key through
# the gateway; names match the `vitals_*` permission rows; no key values; audited.
from __future__ import annotations

from typing import Any

from vitals_fakes import Rig, key

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.permissions.groups import GROUPS
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.vitals.tools import VitalsDeps, tools

SCOPE = "u_owner:sess_1"


def build(rig: Rig, settings: Settings | None = None) -> Gateway:
    reg = ToolRegistry()
    for t in tools(VitalsDeps(rig.svc, settings or rig.settings)):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=AuditLog())


async def call(gw: Gateway, name: str, **args: Any):  # type: ignore[no-untyped-def]
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


def test_three_tools_with_the_documented_risks() -> None:
    by = {t.name: t for t in tools(VitalsDeps(Rig().svc, Settings()))}
    assert by["vitals_show"].risk is ActionRisk.READ_ONLY
    assert by["vitals_set_key"].risk is ActionRisk.REVERSIBLE
    assert by["vitals_delete_key"].risk is ActionRisk.REVERSIBLE
    assert all(t.activity_words for t in by.values())


def test_names_match_the_vitals_permission_rows() -> None:
    rows = {g.id: g for g in GROUPS if g.id in ("vitals", "vitals_change")}
    assert set(rows) == {"vitals", "vitals_change"}
    for t in tools(VitalsDeps(Rig().svc, Settings())):
        assert t.name.startswith("vitals_")


def test_disabled_setting_registers_nothing() -> None:
    off = Settings(vitals_enabled=False)
    assert tools(VitalsDeps(Rig().svc, off)) == []


async def test_show_returns_the_board_with_spend_in_rupees() -> None:
    rig = Rig()
    await rig.svc.set_key("u_owner", key("brain", limit=100, used=90))

    res = await call(build(rig), "vitals_show")

    assert res.outcome is GatewayOutcome.EXECUTED
    out = res.result
    assert out["overall"] == "amber" and out["spend"]["text"] == "₹100 of ₹500 this month"
    assert any(i["id"] == "brain" and i["status"] == "amber" for i in out["items"])
    assert "$" not in str(out)


async def test_show_can_filter_to_items_needing_attention() -> None:
    rig = Rig()
    await rig.svc.set_key("u_owner", key("brain", limit=100, used=90))

    res = await call(build(rig), "vitals_show", attention_only=True)

    assert [i["id"] for i in res.result["items"]] == ["brain"]


async def test_show_storage_trouble_is_an_answer_not_a_failure() -> None:
    rig = Rig()

    async def boom(*_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
        from jarvis.vitals.store import VitalsUnavailable

        raise VitalsUnavailable("plain words")

    rig.store.list_manual = boom  # type: ignore[method-assign]

    res = await call(build(rig), "vitals_show")

    assert res.result == {"status": "unavailable", "message": "plain words"}


async def test_set_key_adds_then_edits_a_manual_record() -> None:
    rig = Rig()
    gw = build(rig)

    r1 = await call(
        gw,
        "vitals_set_key",
        id="brave",
        label="Brave search key",
        kind="key",
        limit=2000,
        used=100,
        unit="queries",
        expires_at="2027-01-15",
        note="renews yearly",
    )
    r2 = await call(
        gw, "vitals_set_key", id="brave", label="Brave search key", kind="key", limit=3000
    )

    assert r1.outcome is GatewayOutcome.EXECUTED and r1.result["saved"] == "brave"
    (rec,) = await rig.store.list_manual("u_owner")
    assert rec.limit == 3000 and r2.result["saved"] == "brave"


async def test_set_key_rejects_bad_input_with_plain_words() -> None:
    rig = Rig()
    gw = build(rig)

    bad_kind = await call(gw, "vitals_set_key", id="k", label="K", kind="wallet")
    bad_date = await call(gw, "vitals_set_key", id="k", label="K", kind="key", expires_at="soon")
    reserved = await call(gw, "vitals_set_key", id="ai_spend", label="K", kind="key")

    for r in (bad_kind, bad_date):
        assert r.outcome is GatewayOutcome.ERROR and r.error
    assert reserved.result["status"] == "rejected" and reserved.result["message"]
    assert await rig.store.list_manual("u_owner") == []


async def test_set_key_refuses_something_that_looks_like_the_key_itself() -> None:
    rig = Rig()
    secret = "sk-" + "A1b2C3d4" * 5

    res = await call(build(rig), "vitals_set_key", id="k", label="K", kind="key", note=secret)

    assert res.outcome is GatewayOutcome.ERROR and "never" in (res.error or "").lower()
    assert secret not in repr(res)
    assert await rig.store.list_manual("u_owner") == []


async def test_delete_key_removes_a_tracked_record() -> None:
    rig = Rig()
    gw = build(rig)
    await call(gw, "vitals_set_key", id="k", label="K", kind="key")

    res = await call(gw, "vitals_delete_key", id="k")

    assert res.result["removed"] is True and await rig.store.list_manual("u_owner") == []


async def test_delete_key_unknown_or_builtin_id_says_nothing_removed() -> None:
    gw = build(Rig())

    assert (await call(gw, "vitals_delete_key", id="ghost")).result["removed"] is False
    assert (await call(gw, "vitals_delete_key", id="ai_spend")).result["removed"] is False


async def test_every_call_is_audited() -> None:
    rig = Rig()
    gw = build(rig)

    await call(gw, "vitals_show")
    await call(gw, "vitals_set_key", id="k", label="K", kind="key")

    tail = await gw.audit.tail(10)  # type: ignore[attr-defined]
    assert [e.tool for e in tail.entries][-2:] == ["vitals_show", "vitals_set_key"]
    assert tail.verified
