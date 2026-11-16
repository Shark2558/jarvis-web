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

from jarvis.storage.docs import Set
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


async def test_the_settings_answer_the_contracts_lead_and_never_store_one() -> None:
    from httpx import ASGITransport, AsyncClient
    from r13_fakes_c import app_of

    w = await world(at=ist(2026, 11, 16, 20, 0))
    async with AsyncClient(transport=ASGITransport(app=app_of(w)), base_url="http://t") as c:
        got = await c.put("/v1/outfits/settings", json={"lead_h": 6, "auto_swap": True})
    assert got.status_code == 200 and got.json()["lead_h"] == 12  # the contract's default
    stored = (await w.styling.plans.read(UID)).choice
    assert stored.auto_swap is True and "lead_h" not in stored.model_dump()
