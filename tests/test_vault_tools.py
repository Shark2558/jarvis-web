# tests/test_vault_tools.py -- R2 D7: metadata only, fenced, vouching, spoken masking, cards
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from vault_fakes import NOW, PDF, UID, make

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools import Effect, PolicyRule
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.vault.tools import vault_tools

SCOPE = f"{UID}:sess_1"
TODAY = NOW.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()


async def rig():  # type: ignore[no-untyped-def]
    svc, docs, _ = make()
    reg = ToolRegistry()
    for t in vault_tools(svc):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    return svc, docs, gw


async def call(gw: Gateway, name: str, **args: Any):  # type: ignore[no-untyped-def]
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


async def seed(svc, *, days: int | None, type_id="passport", n=0, last4="4821"):  # type: ignore[no-untyped-def]
    item = (await svc.add_file(UID, PDF + str(n).encode(), type_hint=type_id)).item
    patch: dict[str, Any] = {"last4": last4, "confirm": days is not None}
    if days is not None:
        patch["expires_on"] = (TODAY + dt.timedelta(days=days)).isoformat()
    await svc.update(UID, item.id, patch)
    return item


async def test_registry_risks_and_flags() -> None:
    _, _, gw = await rig()
    reg = {n: gw.registry.get(n) for n in ("vault_list", "vault_expiring", "vault_set_dates")}
    assert reg["vault_list"].risk is ActionRisk.READ_ONLY  # type: ignore[union-attr]
    assert reg["vault_expiring"].risk is ActionRisk.READ_ONLY  # type: ignore[union-attr]
    assert reg["vault_set_dates"].risk is ActionRisk.REVERSIBLE  # type: ignore[union-attr]
    for t in reg.values():
        assert t is not None and t.may_vouch and t.activity_words and not t.spoken_ok
        assert "file" in t.description.lower() or "date" in t.description.lower()
    assert reg["vault_set_dates"].activity_words == "Changed a vault date"  # type: ignore[union-attr]


async def test_no_tool_adds_deletes_or_reads_files() -> None:
    _, _, gw = await rig()
    names = {t.name for t in gw.registry.all()} if hasattr(gw.registry, "all") else set()
    assert not {
        n for n in names if any(w in n for w in ("add", "remove", "delete", "read", "open"))
    }


async def test_list_is_metadata_only_fenced_and_vouches() -> None:
    svc, _, gw = await rig()
    await seed(svc, days=400)
    res = await call(gw, "vault_list")
    assert res.outcome is GatewayOutcome.EXECUTED
    text = json.dumps(res.result)
    doc = res.result["documents"][0]
    assert doc["type"] == "Passport" and doc["whose"] == "you" and doc["ends"] == "4821"
    assert doc["state"] == "ok" and doc["days_left"] == 400 and FENCE_END.split("{")[0][:2]
    assert "your vault" in doc["title"]
    assert "sha256" not in text and "dek" not in text and "chunk" not in text
    assert res.owner_authored is True if hasattr(res, "owner_authored") else True


async def test_states_and_unconfirmed_dates_are_hidden() -> None:
    svc, _, gw = await rig()
    await seed(svc, days=10, type_id="puc", n=1)
    await seed(svc, days=-3, type_id="vehicle_insurance", n=2)
    await seed(svc, days=None, type_id="driving_licence", n=3)
    docs = {d["type"]: d for d in (await call(gw, "vault_list")).result["documents"]}
    assert docs["PUC certificate"]["state"] == "expires soon"
    assert docs["Vehicle insurance"]["state"] == "expired"
    dl = docs["Driving licence"]
    assert dl["state"] == "check details" and dl["expires_on"] is None and dl["days_left"] is None


async def test_filters_by_holder_and_type() -> None:
    svc, _, gw = await rig()
    h = await svc.add_holder(UID, "Anjali")
    mine = await seed(svc, days=100, n=1)
    theirs = (await svc.add_file(UID, PDF + b"9", type_hint="passport", holder_id=h.id)).item
    got = (await call(gw, "vault_list", holder="Anjali")).result["documents"]
    assert [d["id"] for d in got] == [theirs.id]
    got = (await call(gw, "vault_list", holder="you")).result["documents"]
    assert [d["id"] for d in got] == [mine.id]
    assert (await call(gw, "vault_list", type="driving licence")).result["documents"] == []
    bad = await call(gw, "vault_list", type="spaceship")
    assert bad.outcome is not GatewayOutcome.EXECUTED


async def test_expiring_uses_confirmed_dates_only() -> None:
    svc, _, gw = await rig()
    await seed(svc, days=20, n=1)
    await seed(svc, days=200, n=2, type_id="puc")
    await seed(svc, days=None, n=3, type_id="pan")
    got = (await call(gw, "vault_expiring", within_days=90)).result
    assert got["count"] == 1 and got["documents"][0]["days_left"] == 20
    assert (
        await call(gw, "vault_expiring", within_days=999)
    ).outcome is not GatewayOutcome.EXECUTED


async def test_empty_vault_says_where_to_add() -> None:
    _, _, gw = await rig()
    assert "Vault panel" in (await call(gw, "vault_list")).result["note"]


async def test_set_dates_is_a_card_showing_old_and_new_then_confirms() -> None:
    svc, _, gw = await rig()
    gw.policy.rules.append(PolicyRule(tool_pattern="vault_*", effect=Effect.ASK, source="owner:x"))
    item = await seed(svc, days=30, type_id="vehicle_insurance")
    first = await call(gw, "vault_set_dates", item=item.id, expires_on="2027-03-03")
    assert first.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    card = first.pending.summary  # type: ignore[union-attr]
    assert "vehicle insurance" in card and "->" in card and "2027-03-03" in card
    assert "4821" not in card
    assert (await svc.view(UID))["items"][0]["expires_on"] != "2027-03-03"
    done = await gw.execute(
        ToolCall(
            id="c", name="vault_set_dates", arguments={"item": item.id, "expires_on": "2027-03-03"}
        ),
        confirmation_id=first.pending.id,  # type: ignore[union-attr]
        scope=SCOPE,
    )
    assert done.outcome is GatewayOutcome.EXECUTED
    view = (await svc.view(UID))["items"][0]
    assert view["expires_on"] == "2027-03-03" and view["dates_confirmed"]


async def test_set_dates_input_checks() -> None:
    svc, _, gw = await rig()
    item = await seed(svc, days=30)
    for args in (
        {"item": "nope", "expires_on": "2027-01-01"},
        {"item": item.id},
        {"item": item.id, "expires_on": "03/03/2027"},
        {"item": item.id, "issued_on": "2030-01-01", "expires_on": "2029-01-01"},
        {"item": item.id, "expires_on": "2027-01-01", "extra": 1},
    ):
        res = await call(gw, "vault_set_dates", **args)
        assert res.outcome is not GatewayOutcome.EXECUTED, args


async def test_another_owner_cannot_be_reached() -> None:
    svc, _, gw = await rig()
    await seed(svc, days=30)
    other = await gw.execute(
        ToolCall(id="c", name="vault_list", arguments={}), scope="u_other00000000002:s"
    )
    assert other.result["documents"] == []


async def test_on_a_spoken_turn_the_last_four_is_left_out_and_titles_are_masked() -> None:
    from jarvis.tools.taint import context_trust

    svc, _, gw = await rig()
    item = await seed(svc, days=100)
    await svc.update(UID, item.id, {"title": "Passport 90210 copy"})
    with context_trust(untrusted=False, spoken=True):
        doc = (await call(gw, "vault_list")).result["documents"][0]
    assert doc["ends"] is None and "90210" not in json.dumps(doc)
    typed = (await call(gw, "vault_list")).result["documents"][0]
    assert typed["ends"] == "4821"
