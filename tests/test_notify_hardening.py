# tests/test_notify_hardening.py -- R3 D security review fixes: hazard alerts are never dropped by
# any cap (storm, Telegram, push), push is capped, R1 switches hold on every channel, VIP contact
# details are sealed, held alerts survive a failed send, and imports are declared.
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from notify_fakes import MIDNIGHT, NOON, build
from telegram_fakes import UID

from jarvis.notify.models import Vip
from jarvis.notify.ports import Decision, Signal
from jarvis.notify.service import PUSH_PER_HOUR, NotifyService
from jarvis.notify.store import NotifyUnavailable
from jarvis.notify.storm import MAX_URGENT_IN_WINDOW, Storm
from jarvis.notify.telegram_out import URGENT_PER_HOUR

ROOT = Path(__file__).parents[1]
RING = Decision(action="ring", reason="x", urgency="urgent")


def intruder(camera: str = "gate") -> Signal:
    return Signal(source="home", kind="home_intruder", camera=camera)


def hazard(sensor: str | None = None) -> Signal:
    return Signal(source="home", kind="home_hazard", camera=sensor)


def approval() -> Signal:
    return Signal(source="nudge", kind="approval_waiting")


# ---- H1: the hazard is not in the intruder window -----------------------------------------------


def test_hazards_do_not_count_toward_the_intruder_window_and_are_never_suppressed_by_it() -> None:
    s = Storm()
    for i in range(MAX_URGENT_IN_WINDOW):
        assert s.admit(UID, intruder(f"c{i}"), RING, NOON + timedelta(seconds=i)).admit
    assert not s.admit(UID, intruder("cx"), RING, NOON + timedelta(seconds=20)).admit
    for i in range(30):  # the window is full of burglars: every hazard still goes
        assert s.admit(UID, hazard(f"s{i}"), RING, NOON + timedelta(seconds=30 + i)).admit
    s2 = Storm()
    for i in range(40):  # hazards first leave the burglar window empty
        assert s2.admit(UID, hazard(f"s{i}"), RING, NOON).admit
    assert s2.admit(UID, intruder(), RING, NOON).admit


def test_a_hazard_is_deduplicated_per_sensor_only() -> None:
    s = Storm()
    assert s.admit(UID, hazard("kitchen"), RING, NOON).admit
    assert not s.admit(UID, hazard("kitchen"), RING, NOON + timedelta(seconds=5)).admit
    assert s.admit(UID, hazard("garage"), RING, NOON + timedelta(seconds=5)).admit
    assert s.admit(UID, hazard(), RING, NOON).admit and s.admit(UID, hazard(), RING, NOON).admit
    assert s.admit(UID, hazard("kitchen"), RING, NOON + timedelta(minutes=2)).admit


def test_an_emergency_decision_for_any_kind_skips_the_window() -> None:
    s = Storm()
    for i in range(MAX_URGENT_IN_WINDOW):
        s.admit(UID, intruder(f"c{i}"), RING, NOON)
    em = Decision(action="ring", reason="emergency", urgency="urgent")
    sig = Signal(source="call", kind="home_package", text="fire")
    assert s.admit(UID, sig, em, NOON).admit


async def test_hazard_rings_after_ten_intruder_rings() -> None:
    w = await build()
    for i in range(10):
        d = await w.service.notify(UID, intruder(f"c{i}"), "Someone at the camera.")
        assert d.action == "ring"
        w.clock.advance(seconds=5)
    d = await w.service.notify(UID, hazard("kitchen"), "Smoke alarm at home.")
    assert d.action == "ring" and d.telegram and d.push == 1


# ---- H2: Telegram and storm budgets agree; hazards have no cap ---------------------------------


async def test_intruder_rings_in_an_hour_stay_within_the_telegram_urgent_budget() -> None:
    w = await build(with_push=False)
    rings = 0
    for i in range(60):  # one a minute on a fresh camera for an hour
        d = await w.service.notify(UID, intruder(f"c{i}"), "Someone.")
        rings += d.action == "ring"
        w.clock.advance(minutes=1)
    assert rings + 6 <= URGENT_PER_HOUR  # leaves room for the hourly summaries
    assert all(d.telegram for d in [await w.service.notify(UID, hazard("k"), "Smoke.")])


async def test_thirty_intruder_rings_then_a_hazard_reaches_telegram() -> None:
    w = await build()
    for i in range(30):
        await w.service.notify(UID, intruder(f"c{i}"), "Someone.")
        w.clock.advance(seconds=100)
    d = await w.service.notify(UID, hazard("kitchen"), "Smoke alarm at home.")
    assert d.telegram and d.push == 1
    assert w.tg.bot.texts[-1] == "Smoke alarm at home."


async def test_a_hazard_goes_to_telegram_with_the_urgent_bucket_empty() -> None:
    w = await build(with_push=False)
    for _ in range(URGENT_PER_HOUR):
        assert await w.store.take_urgent(UID, NOON, per_hour=URGENT_PER_HOUR, per_day=100)
    assert not (await w.alerts.send(UID, "Burglar.", kind="home_intruder")).sent
    assert (await w.alerts.send(UID, "Smoke.", kind="home_hazard")).sent


async def test_a_hazard_goes_to_telegram_with_the_daily_bucket_empty() -> None:
    w = await build(with_push=False)
    for _ in range(100):
        await w.store.take_urgent(UID, NOON, per_hour=1000, per_day=100)
    assert not (await w.alerts.send(UID, "Burglar.", kind="home_intruder")).sent
    assert (await w.alerts.send(UID, "Smoke.", kind="home_hazard")).sent


async def test_a_hazard_goes_to_telegram_when_the_counter_is_down_and_the_local_cap_is_full() -> (
    None
):
    w = await build(with_push=False)

    async def boom(*a: object, **k: object) -> bool:
        raise RuntimeError("counter down")

    w.store.take_urgent = boom  # type: ignore[method-assign]
    for _ in range(URGENT_PER_HOUR):
        assert (await w.alerts.send(UID, "Burglar.", kind="home_intruder")).sent
    assert not (await w.alerts.send(UID, "Burglar.", kind="home_intruder")).sent
    assert (await w.alerts.send(UID, "Smoke.", kind="home_hazard")).sent


async def test_a_hazard_is_not_held_by_the_normal_counter_either() -> None:
    w = await build(with_push=False)
    for _ in range(10):
        await w.alerts.send(UID, "Wait.", kind="approval_waiting")
    assert not (await w.alerts.send(UID, "Wait.", kind="approval_waiting")).sent
    assert (await w.alerts.send(UID, "Gas.", kind="home_hazard")).sent


async def test_a_telegram_refusal_of_a_burglar_alert_feeds_the_storm_summary() -> None:
    w = await build(with_push=False)
    for _ in range(URGENT_PER_HOUR):
        await w.store.take_urgent(UID, NOON, per_hour=URGENT_PER_HOUR, per_day=100)
    d = await w.service.notify(UID, intruder(), "Someone.")
    assert d.telegram is False
    w.clock.advance(minutes=11)
    assert w.service.storm.due_summary(UID, w.clock.now) == 1


# ---- M3: the push channel is capped -------------------------------------------------------------


async def test_forty_laptop_offline_alerts_in_a_minute_make_at_most_one_push() -> None:
    w = await build()
    for _ in range(40):
        await w.service.notify(UID, Signal(source="home", kind="home_offline"), "Laptop off.")
        w.clock.advance(seconds=1)
    assert len(w.push.requests) <= 1


async def test_flapping_online_and_arm_failed_have_a_minimum_gap_too() -> None:
    w = await build()
    for kind in ("home_online", "home_arm_failed"):
        for _ in range(10):
            await w.service.notify(UID, Signal(source="home", kind=kind), "x")
            w.clock.advance(seconds=1)
    assert len(w.push.requests) <= 2


async def test_pushes_per_hour_are_capped_for_normal_kinds_and_shared_by_instances() -> None:
    w = await build()
    for _ in range(PUSH_PER_HOUR + 20):
        await w.service.notify(UID, approval(), "Wait.")
        w.clock.advance(seconds=1)
    assert len(w.push.requests) == PUSH_PER_HOUR
    twin = NotifyService(w.store, w.tg.audit, push=w.push.service, now=w.clock)  # fresh process
    await twin.notify(UID, approval(), "Wait.")
    assert len(w.push.requests) == PUSH_PER_HOUR
    w.clock.advance(hours=1)
    await twin.notify(UID, approval(), "Wait.")
    assert len(w.push.requests) == PUSH_PER_HOUR + 1


async def test_a_hazard_and_a_burglar_alert_push_even_when_the_push_cap_is_used_up() -> None:
    w = await build()
    for _ in range(PUSH_PER_HOUR):
        await w.store.take_push(UID, NOON, per_hour=PUSH_PER_HOUR)
    assert (await w.service.notify(UID, approval(), "Wait.")).push == 0
    assert (await w.service.notify(UID, hazard("kitchen"), "Smoke.")).push == 1
    assert (await w.service.notify(UID, intruder(), "Someone.")).push == 1


async def test_an_unreadable_push_counter_fails_closed_for_normal_and_open_for_hazard() -> None:
    w = await build()

    async def boom(*a: object, **k: object) -> bool:
        raise RuntimeError("down")

    w.store.take_push = boom  # type: ignore[method-assign]
    assert (await w.service.notify(UID, approval(), "W")).push == 0
    assert (await w.service.notify(UID, hazard("kitchen"), "Smoke.")).push == 1


# ---- M4: the R1 per-kind switches hold on every channel ----------------------------------------


async def test_vault_expiry_is_off_by_default_on_every_channel() -> None:
    w = await build()
    d = await w.service.notify(UID, Signal(source="nudge", kind="vault_expiry"), "Passport due.")
    assert (d.action, d.reason, d.telegram, d.push) == ("drop", "switched_off", False, 0)
    assert w.push.requests == [] and w.tg.bot.of("sendMessage") == []
    await w.tg.store.set_settings(UID, alerts={"vault_expiry": True})
    d = await w.service.notify(UID, Signal(source="nudge", kind="vault_expiry"), "Passport due.")
    assert d.telegram and d.push == 1


async def test_a_kind_switched_off_in_telegram_settings_is_dropped_before_the_hold() -> None:
    w = await build(MIDNIGHT)
    await w.tg.store.set_settings(UID, alerts={"approval_waiting": False})
    d = await w.service.notify(UID, approval(), "Wait.")
    assert d.action == "drop" and await w.store.held_list(UID) == []


async def test_the_held_summary_skips_kinds_switched_off() -> None:
    w = await build(MIDNIGHT)
    await w.store.held_add(UID, {"kind": "vault_expiry", "at": "t1"})
    await w.store.held_add(UID, {"kind": "home_package", "at": "t2"})
    w.clock.now = NOON
    assert await w.service.flush_held(UID) is True
    [msg] = w.tg.bot.texts
    assert "document" not in msg and "1 alert " in msg and "package" in msg
    assert "document" not in w.push.requests[0].content.decode("latin-1")
    assert await w.store.held_list(UID) == []


async def test_a_held_summary_of_only_switched_off_kinds_sends_nothing_and_clears() -> None:
    w = await build(MIDNIGHT)
    await w.store.held_add(UID, {"kind": "vault_expiry", "at": "t1"})
    w.clock.now = NOON
    assert await w.service.flush_held(UID) is False
    assert w.tg.bot.texts == [] and await w.store.held_list(UID) == []


async def test_unreadable_telegram_settings_use_the_mirrored_defaults() -> None:
    w = await build()

    async def boom(uid: str) -> None:
        raise RuntimeError("x")

    w.tg.store.get = boom  # type: ignore[method-assign]
    d = await w.service.notify(UID, Signal(source="nudge", kind="vault_expiry"), "Due.")
    assert d.action == "drop"


# ---- M5: VIP contact details are sealed ---------------------------------------------------------


async def test_vip_phone_and_email_are_not_in_any_stored_string() -> None:
    w = await build()
    phone, mail = "+919876500011", "someone.private@example.org"
    vips = (
        Vip(id="v_00000001", kind="phone", ref=phone),
        Vip(id="v_00000002", kind="email", ref=mail),
    )
    await w.store.update(UID, lambda s: s.model_copy(update={"vip": vips}))
    dump = json.dumps(w.docs._data, default=str)
    assert phone not in dump and mail not in dump and "9876500011" not in dump
    got = await w.store.get(UID)
    assert [v.ref for v in got.vip] == [phone, mail]


async def test_a_tampered_vip_blob_fails_closed_and_is_not_overwritten() -> None:
    w = await build()
    vip = Vip(id="v_00000001", kind="phone", ref="+919876500011")
    await w.store.update(UID, lambda s: s.model_copy(update={"vip": (vip,)}))
    doc = w.docs._data["jarvis_notify/owner"]
    doc["vip_blob"] = doc["vip_blob"][:-4] + "AAAA"
    before = json.dumps(doc, sort_keys=True)
    with pytest.raises(NotifyUnavailable):
        await w.store.get(UID)
    with pytest.raises(NotifyUnavailable):
        await w.store.update(UID, lambda s: s)
    assert json.dumps(w.docs._data["jarvis_notify/owner"], sort_keys=True) == before


async def test_a_settings_document_without_vips_stores_no_blob() -> None:
    w = await build()
    await w.store.update(UID, lambda s: s.model_copy(update={"ring_for": "important"}))
    assert "vip_blob" not in w.docs._data["jarvis_notify/owner"]
    assert "vip" not in w.docs._data["jarvis_notify/owner"]


async def test_a_legacy_plaintext_vip_list_is_read_and_sealed_on_the_next_save() -> None:
    w = await build()
    ref = "+919876500022"
    w.docs._data["jarvis_notify/owner"] = {
        "vip": [{"id": "v_00000009", "kind": "phone", "ref": ref}],
        "rev": 3,
    }
    assert [v.ref for v in (await w.store.get(UID)).vip] == [ref]
    await w.store.update(UID, lambda s: s)
    assert ref not in json.dumps(w.docs._data, default=str)
    assert [v.ref for v in (await w.store.get(UID)).vip] == [ref]


# ---- M6: held alerts are removed only after delivery --------------------------------------------


async def test_held_alerts_survive_a_failed_send_and_go_on_the_next_tick() -> None:
    w = await build(MIDNIGHT, with_push=False)
    for _ in range(2):
        await w.service.notify(UID, Signal(source="home", kind="home_package"), "Pkg.")
    w.clock.now = NOON
    w.tg.bot.raise_transport = True
    assert await w.service.flush_held(UID) is False
    assert len(await w.store.held_list(UID)) == 2
    w.tg.bot.raise_transport = False
    assert await w.service.flush_held(UID) is True
    assert "2 alerts" in w.tg.bot.texts[-1] and await w.store.held_list(UID) == []


async def test_alerts_held_during_the_send_are_not_lost() -> None:
    w = await build(MIDNIGHT, with_push=False)
    await w.service.notify(UID, Signal(source="home", kind="home_package"), "Pkg.")
    w.clock.now = NOON
    real = w.alerts.send

    async def send_and_hold(*a: Any, **k: Any) -> Any:
        await w.store.held_add(UID, {"kind": "home_offline", "at": "late"})
        return await real(*a, **k)

    w.alerts.send = send_and_hold  # type: ignore[method-assign]
    assert await w.service.flush_held(UID) is True
    assert [i["kind"] for i in await w.store.held_list(UID)] == ["home_offline"]


# ---- M7: every third-party import is declared ---------------------------------------------------

IMPORT_TO_DIST = {
    "google": "google-cloud-firestore",
    "docx": "python-docx",
    # always installed with a declared package (fastapi / httpx); not part of this review
    "starlette": "fastapi",
    "anyio": "httpx",
}


def _names(found: list[str]) -> set[str]:
    return {re.split(r"[\[<>=!~ ;]", m)[0].lower().replace("_", "-") for m in found}


def _declared() -> set[str]:
    text = (ROOT / "pyproject.toml").read_text()
    block = text.split("dependencies = [", 1)[1].split("\n]", 1)[0]
    return _names(re.findall(r'^\s*"([^"]+)"', block, re.M))


def _bridge_extra() -> set[str]:
    """I1: the home bridge's own extra (its image, never the cloud's): aiomqtt; since R11.1 I1
    also OpenCV and NumPy, each with its Python marker, so the list is read as TOML."""
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return _names(list(project["optional-dependencies"]["homebridge"]))


def test_every_third_party_top_level_import_in_src_is_in_pyproject() -> None:
    declared = _declared()
    bridge = declared | _bridge_extra()
    stdlib = set(sys.stdlib_module_names)
    missing: dict[str, str] = {}
    for path in (ROOT / "src").rglob("*.py"):
        allowed = bridge if "homebridge" in path.parts else declared
        for node in ast.walk(ast.parse(path.read_text())):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split(".")[0]]
            for m in mods:
                if m in stdlib or m in {"jarvis", "__future__"}:
                    continue
                if IMPORT_TO_DIST.get(m, m).lower().replace("_", "-") not in allowed:
                    missing[m] = str(path.relative_to(ROOT))
    assert missing == {}


def test_the_lock_says_jarvis_needs_joserfc() -> None:
    assert "joserfc" in _declared()
    lock = (ROOT / "requirements.lock").read_text()
    block = lock.split("joserfc==", 1)[1].split("lxml==", 1)[0]
    assert "jarvis (pyproject.toml)" in block and "authlib" in block
