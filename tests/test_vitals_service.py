# tests/test_vitals_service.py -- R4 D2-D4: the board (auto + manual), spend, alerts on line-cross.
from __future__ import annotations

from datetime import timedelta

import pytest
from vitals_fakes import T0, UID, FakeBilling, Rig, key, usage_view

from jarvis.billing.meter import AllowanceUse
from jarvis.quota.ledger import QuotaLedger
from jarvis.vitals.auto import AllowanceSpec
from jarvis.vitals.service import VitalsService


def by_id(board, pid):  # type: ignore[no-untyped-def]
    return next(v for v in board.items if v.provider.id == pid)


async def test_board_has_ai_spend_record_from_billing() -> None:
    rig = Rig(billing=FakeBilling(usage_view(120, 500)))

    board = await rig.svc.board(UID)

    spend = by_id(board, "ai_spend")
    assert spend.provider.kind == "billing" and spend.provider.source == "auto"
    assert (spend.provider.used, spend.provider.limit, spend.status) == (120, 500, "ok")
    assert board.spend is not None
    assert board.spend.text == "₹120 of ₹500 this month"


async def test_spend_without_a_limit_says_no_limit_and_is_ok() -> None:
    rig = Rig(billing=FakeBilling(usage_view(42.5, None)))

    board = await rig.svc.board(UID)

    assert board.spend is not None and "no limit" in board.spend.text
    assert "₹42.50" in board.spend.text
    assert by_id(board, "ai_spend").status == "ok"


async def test_spend_at_eighty_percent_is_amber_and_at_limit_red() -> None:
    rig = Rig(billing=FakeBilling(usage_view(400, 500)))
    assert by_id(await rig.svc.board(UID), "ai_spend").status == "amber"
    rig.billing.view = usage_view(500, 500)
    assert by_id(await rig.svc.board(UID), "ai_spend").status == "red"


async def test_unreadable_billing_is_unknown_not_a_failure() -> None:
    rig = Rig(billing=FakeBilling(down=True))

    board = await rig.svc.board(UID)

    assert by_id(board, "ai_spend").status == "unknown"
    assert board.spend is None and board.overall == "unknown"


async def test_spend_resets_at_the_next_month_in_the_owner_timezone() -> None:
    rig = Rig()

    reset = by_id(await rig.svc.board(UID), "ai_spend").provider.reset_at

    assert reset is not None and (reset.year, reset.month, reset.day) == (2026, 12, 1)
    assert reset.utcoffset() == timedelta(hours=5, minutes=30)


async def test_manual_records_appear_with_computed_status() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=95, unit="calls"))

    view = by_id(await rig.svc.board(UID), "brain")

    assert view.status == "amber" and view.percent == 95.0


async def test_manual_record_cannot_shadow_an_auto_id() -> None:
    rig = Rig()

    with pytest.raises(ValueError):
        await rig.svc.set_key(UID, key("ai_spend"))


async def test_quota_skus_come_from_the_ledger_and_start_at_zero() -> None:
    rig = Rig(with_ledger=True)

    board = await rig.svc.board(UID)

    q = by_id(board, "quota_maps_search")
    assert q.provider.kind == "quota" and q.provider.used == 0
    assert q.provider.limit == 4500 and q.status == "ok"  # 90% of the global 5,000
    assert q.provider.reset_at is not None


async def test_quota_near_the_stop_turns_red() -> None:
    rig = Rig(with_ledger=True)
    assert rig.ledger is not None
    sku = rig.ledger.sku("youtube_search")
    await rig.ledger.reserve(sku, sku.cap)

    assert by_id(await rig.svc.board(UID), "quota_youtube_search").status == "red"


async def test_unreadable_quota_counter_is_unknown() -> None:
    rig = Rig(with_ledger=True)

    class Bad(QuotaLedger):
        async def use(self, sku):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    rig.svc = VitalsService(
        rig.store,
        rig.settings,
        billing=rig.billing,
        ledger=Bad(rig.docs),
        clock=rig.clock,  # type: ignore[arg-type]
    )

    board = await rig.svc.board(UID)

    assert by_id(board, "quota_maps_search").status == "unknown"


async def test_allowance_records_come_from_billing() -> None:
    class B(FakeBilling):
        async def allowance(self, keys):  # type: ignore[no-untyped-def]
            return AllowanceUse("2026-11", {"tts_std": 900.0})

        def allowance_resets_at(self):  # type: ignore[no-untyped-def]
            return T0 + timedelta(days=20)

    rig = Rig(billing=B())
    rig.svc = VitalsService(
        rig.store,
        rig.settings,
        billing=rig.billing,  # type: ignore[arg-type]
        allowances=(AllowanceSpec("tts_std", "Cloud voice", 1000.0, "characters"),),
        clock=rig.clock,
    )

    v = by_id(await rig.svc.board(UID), "allowance_tts_std")

    assert (v.provider.used, v.provider.limit, v.status) == (900.0, 1000.0, "amber")
    assert v.provider.kind == "allowance"


async def test_allowance_unreadable_is_unknown() -> None:
    rig = Rig()
    rig.svc = VitalsService(
        rig.store,
        rig.settings,
        billing=rig.billing,  # type: ignore[arg-type]
        allowances=(AllowanceSpec("tts_std", "Cloud voice", 1000.0, "characters"),),
        clock=rig.clock,
    )

    assert by_id(await rig.svc.board(UID), "allowance_tts_std").status == "unknown"


async def test_delete_key_removes_a_manual_record_only() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain"))

    assert await rig.svc.delete_key(UID, "brain") is True
    assert await rig.svc.delete_key(UID, "ai_spend") is False


async def test_overall_is_the_worst_status() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("old", expires_in_days=-3))

    assert (await rig.svc.board(UID)).overall == "red"
    assert (await rig.svc.board(UID)).attention()[0].provider.id == "old"


# ---- alerts (D4) ---------------------------------------------------------------------------


async def test_amber_crossing_alerts_once_with_the_warn_kind() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", label="Brain key", limit=100, used=85))

    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_warn"]
    _, sig, msg = rig.notifier.sent[0]
    assert sig.source == "system" and "Brain key" in msg and "$" not in msg


async def test_red_crossing_uses_the_critical_kind() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=100))

    n = await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_critical"] and n == 1


async def test_amber_to_red_alerts_again_but_not_red_to_amber() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=85))
    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.set_key(UID, key("brain", limit=100, used=100))
    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.set_key(UID, key("brain", limit=100, used=85))
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_warn", "vitals_critical"]


async def test_recovery_then_a_new_crossing_alerts_again() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=85))
    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.set_key(UID, key("brain", limit=100, used=10))
    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.set_key(UID, key("brain", limit=100, used=90))
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_warn", "vitals_warn"]


async def test_time_passing_into_the_expiry_window_alerts() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", expires_in_days=40))
    assert await rig.svc.check_and_alert(UID, rig.notifier) == 0

    rig.clock.advance(days=15)

    assert await rig.svc.check_and_alert(UID, rig.notifier) == 1
    assert rig.notifier.kinds == ["vitals_warn"]


async def test_unknown_status_never_alerts_and_keeps_the_last_status() -> None:
    rig = Rig(billing=FakeBilling(usage_view(450, 500)))
    await rig.svc.check_and_alert(UID, rig.notifier)
    rig.billing.down = True
    await rig.svc.check_and_alert(UID, rig.notifier)
    rig.billing.down = False
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_warn"]


async def test_a_failed_send_is_retried_next_time() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=100))
    rig.notifier.fail = True

    assert await rig.svc.check_and_alert(UID, rig.notifier) == 0
    rig.notifier.fail = False
    assert await rig.svc.check_and_alert(UID, rig.notifier) == 1


async def test_message_is_rupees_only_for_spend() -> None:
    rig = Rig(billing=FakeBilling(usage_view(500, 500)))

    await rig.svc.check_and_alert(UID, rig.notifier)

    msg = rig.notifier.sent[0][2]
    assert "₹500" in msg and "$" not in msg and len(msg) <= 300


async def test_deleting_a_key_resets_its_alert_memory() -> None:
    rig = Rig()
    await rig.svc.set_key(UID, key("brain", limit=100, used=100))
    await rig.svc.check_and_alert(UID, rig.notifier)
    await rig.svc.delete_key(UID, "brain")
    await rig.svc.set_key(UID, key("brain", limit=100, used=100))
    await rig.svc.check_and_alert(UID, rig.notifier)

    assert rig.notifier.kinds == ["vitals_critical", "vitals_critical"]
