# tests/test_r13_c_sealed.py -- R13 Part C's sealed documents across releases (docs/plans/
# r13-wardrobe.md D14 "a rollback must still open its documents"; code review 1 M8; security
# review 1 L6, M2): a document written with a field this build does not know (a later release's,
# or the dropped `lead_h`) still opens, his other choices kept; a document that decrypts but fails
# its check is `Unreadable` with no decrypted value in the error or its chain.
from __future__ import annotations

import json
import traceback

import pytest
from r13_fakes import UID
from r13_fakes_c import RING, ist, world

from jarvis.keyring import Keyring
from jarvis.storage.docs import Set
from jarvis.wardrobe.styling.plans import Choice
from jarvis.wardrobe.styling.sealed import Unreadable


def _sealed(collection: str, value: object) -> dict[str, object]:
    plain = json.dumps(value).encode()
    blob = RING.cipher("wardrobe").encrypt(plain, aad=f"{collection}/{UID}/v1")
    return {"uid": UID, "rev": 1, "blob": blob, "updated_at": "2026-11-16T03:30:00+00:00"}


async def test_a_document_with_a_field_this_build_does_not_know_still_opens() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    doc = {
        "plans": [],
        "choice": {"calendar": None, "fields": ["title"], "lead_h": 6, "plan_alerts": False},
        "added_by_a_later_release": {"anything": 1},
    }
    await w.docs.write([Set(f"jarvis_wardrobe_plans/{UID}", _sealed("wardrobe_plans", doc))])
    got = await w.styling.plans.read(UID)
    assert got.choice.plan_alerts is False  # his choice kept
    assert not hasattr(got.choice, "lead_h")  # dropped before the first deploy (M8)


async def test_a_document_that_fails_its_check_is_unreadable_with_no_value_in_the_error() -> None:
    w = await world(at=ist(2026, 11, 16, 20, 0))
    needle = "my-red-lace-briefs"
    doc = {"plans": [{"id": needle, "day": "2026-11-17", "code": "casual"}]}
    await w.docs.write([Set(f"jarvis_wardrobe_plans/{UID}", _sealed("wardrobe_plans", doc))])
    with pytest.raises(Unreadable) as got:
        await w.styling.plans.read(UID)
    assert got.value.__cause__ is None and got.value.__suppress_context__
    assert needle not in "".join(traceback.format_exception(got.value))


async def test_the_settings_have_no_lead_and_a_body_that_names_one_is_refused() -> None:
    from httpx import ASGITransport, AsyncClient
    from r13_fakes_c import app_of

    w = await world(at=ist(2026, 11, 16, 20, 0))
    async with AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://t") as c:
        refused = await c.put("/v1/outfits/settings", json={"lead_h": 6, "auto_swap": True})
        got = await c.put("/v1/outfits/settings", json={"auto_swap": True})
    assert refused.status_code == 422 and "lead_h" not in got.json()
    stored = (await w.styling.plans.read(UID)).choice
    assert got.status_code == 200 and stored.auto_swap is True


# ---- security review M3: a key change or one unreadable cache never stops Part C ----------------
OTHER = Keyring(bytes(range(1, 33)))  # JARVIS's key after a change
WORDS = (
    "Your outfit plans can't be opened (JARVIS's key changed): delete them in Privacy to start "
    "again."
)


def _under(ring: Keyring, collection: str, value: object) -> dict[str, object]:
    plain = json.dumps(value).encode()
    blob = ring.cipher("wardrobe").encrypt(plain, aad=f"{collection}/{UID}/v1")
    return {"uid": UID, "rev": 1, "blob": blob, "updated_at": "2026-11-16T03:30:00+00:00"}


async def test_an_unreadable_weather_cache_is_replaced_and_the_calendar_still_syncs() -> None:
    from r13_fakes_c import FakeGoogle, gevent

    work = "work-cal@example.com"
    google = FakeGoogle(
        events={work: [gevent("ev-1", ist(2026, 11, 17, 10, 0), title="Client meeting")]}
    )
    w = await world(at=ist(2026, 11, 16, 18, 0), google=google)
    await w.styling.change(UID, lambda d: d.model_copy(update={"choice": Choice(calendar=work)}))
    for col in ("wardrobe_outlook", "wardrobe_cal"):
        await w.docs.write([Set(f"jarvis_{col}/{UID}", _under(OTHER, col, {}))])
    counts = await w.part.clock_jobs[0].run([UID])
    assert counts["plans_made"] == 1 and counts["weather"] == 0 and counts.get("failed", 0) == 0
    assert (await w.styling.outlook.sealed.read(UID)).days  # replaced by the next fetch


async def test_with_a_new_key_the_clock_counts_each_step_and_the_tools_and_routes_say_so() -> None:
    from httpx import ASGITransport, AsyncClient
    from r13_fakes_c import app_of

    w = await world(at=ist(2026, 11, 16, 18, 0))
    await w.docs.write([Set(f"jarvis_wardrobe_plans/{UID}", _under(OTHER, "wardrobe_plans", {}))])
    counts = await w.part.clock_jobs[0].run([UID])
    assert counts["plans_failed_Unreadable"] == 1 and counts["weather_fetched"] == 1
    got = await w.call("outfit_suggest", day="tomorrow")
    assert got.result == {"refused": True, "message": WORDS}
    async with AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://t") as c:
        for r in (await c.get("/v1/outfits"), await c.put("/v1/outfits/settings", json={})):
            assert (r.status_code, r.json()) == (503, {"detail": WORDS})


# ---- code review L5: the claims are pruned once a day, at any hour ------------------------------
async def test_the_claims_are_pruned_once_a_day_even_by_a_late_tick() -> None:
    w = await world(at=ist(2026, 11, 16, 9, 0))
    old = w.styling.told
    w.clock.set(ist(2026, 10, 1, 9, 0))
    await old.once(UID, "ready_old")
    w.clock.set(ist(2026, 11, 16, 9, 0))  # 09:00: no tick between 00:00 and 00:05 today
    await w.part.clock_jobs[0].run([UID])
    assert await w.docs.get(old.path(UID, "ready_old")) is None  # pruned by a 09:00 tick
