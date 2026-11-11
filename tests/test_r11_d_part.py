# tests/test_r11_d_part.py -- R11 Part D (plan D2, D17): the kitchen's `build(ctx)` honours the
# contract (names it owns), its privacy rows list / export / delete, and its brief line.
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from r11_fakes import UID
from r11_fakes_d import MailBox, Rules, connector, kctx

from jarvis.api.r11_wiring import check_part
from jarvis.helpers.kinds import COLLECTIONS, PRIVACY_IDS
from jarvis.helpers.kitchen import part as kitchen_part
from jarvis.helpers.kitchen.models import Prefs
from jarvis.privacy.sources import CallbackSource

TZ = ZoneInfo("Asia/Kolkata")
RECEIPTS = ("d_receipt_zepto_oct.eml", "d_receipt_blinkit_nov.eml")


async def _built(google: bool = True, **kw: object) -> tuple[object, ...]:
    box = MailBox(RECEIPTS)
    conn = await connector(box.client()) if google else None
    c, _, docs, clock = kctx(google=conn, rules=Rules(), **kw)  # type: ignore[arg-type]
    return kitchen_part.build(c), c, docs, clock, box


async def test_the_part_keeps_to_the_names_it_owns() -> None:
    built, *_ = await _built()
    assert check_part("kitchen", built) is built  # type: ignore[arg-type]
    assert [j.name for j in built.daily_jobs] == ["grocery_spend"]  # type: ignore[attr-defined]
    assert built.clock_jobs == ()  # type: ignore[attr-defined]
    assert [p.id for p in built.privacy] == list(PRIVACY_IDS["kitchen"])  # type: ignore[attr-defined]
    assert built.ready.startswith("ready")  # type: ignore[attr-defined]


async def test_without_google_or_a_keyring_the_part_still_builds_and_says_why() -> None:
    built, *_ = await _built(google=False)
    names = {t.name for t in built.tools}  # type: ignore[attr-defined]
    assert "calendar_kitchen_blocks" not in names and "pantry_add" in names
    assert built.daily_jobs == ()  # type: ignore[attr-defined]
    off, *_ = await _built(sealed=False)
    assert "token key" in off.ready and off.daily_jobs == ()  # type: ignore[attr-defined]


async def test_it_writes_only_its_own_collections() -> None:
    built, c, docs, _, _ = await _built()
    svc = built.services["kitchen"]  # type: ignore[attr-defined]
    await svc.add(UID, "rice, dal")
    await svc.spend.set_on(UID, True)
    await built.daily_jobs[0].run([])  # type: ignore[attr-defined]
    names = {p.split("/")[0].removeprefix(c.prefix) for p in docs._data}  # noqa: SLF001
    assert names <= set(COLLECTIONS["kitchen"]), names


async def test_privacy_rows_list_export_and_delete() -> None:
    built, c, docs, _, _ = await _built()
    svc = built.services["kitchen"]  # type: ignore[attr-defined]
    await svc.add(UID, "rice, dal")
    await svc.store.change(UID, lambda k: k.model_copy(update={"prefs": Prefs(note="no garlic")}))
    await svc.spend.set_on(UID, True)
    await built.daily_jobs[0].run([])  # type: ignore[attr-defined]
    rows: dict[str, CallbackSource] = {p.id: p for p in built.privacy}  # type: ignore[attr-defined]
    kitchen, spend = rows["helpers_kitchen"], rows["helpers_spend"]
    kv, sv = await kitchen.describe(UID), await spend.describe(UID)
    assert (kv.section, kv.delete, kv.encrypted_by_jarvis, kv.count) == (
        "Helpers",
        "confirm",
        True,
        3,
    )
    assert (sv.delete, sv.count, sv.encrypted_by_jarvis) == ("passkey", 2, True)
    exported = await kitchen.export(UID)
    assert exported is not None and exported["pantry"] == ["rice", "dal"]
    money = await spend.export(UID)
    assert money is not None and money["months"][0]["total"] == "₹456"
    assert money["months"][0]["orders"][0] == {
        "merchant": "Blinkit",
        "day": "2026-11-05",
        "amount": "₹456",
    }
    assert "key" not in json.dumps(money)  # the keyed hashes never leave
    assert await kitchen.delete(UID) == 1 and await spend.delete(UID) == 3
    assert (await kitchen.describe(UID)).count == 0 and (await spend.describe(UID)).count == 0


async def test_the_brief_says_last_months_grocery_total_on_the_first_only() -> None:
    built, c, _, clock, _ = await _built()
    svc = built.services["kitchen"]  # type: ignore[attr-defined]
    await svc.spend.set_on(UID, True)
    await built.daily_jobs[0].run([])  # type: ignore[attr-defined]
    (brief,) = built.brief  # type: ignore[attr-defined]
    clock.at = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    assert await brief.lines(UID, TZ, date(2026, 11, 1)) == [
        "Groceries in October 2026: about ₹789 from 1 order (your e-mailed receipts)."
    ]
    assert await brief.lines(UID, TZ, date(2026, 11, 2)) == []
