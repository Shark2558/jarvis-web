# tests/test_r131_i1_joins.py -- R13.1 I1: A and C joined, both REAL parts over R13's real styling
# and store, at r131_fakes.NOW (17 Nov 2026 09:00 IST). Nothing reaches Google.
#
#   - D's look query: `?pieces=` with `&plan=` (a swap inside a plan's look) reads readiness in
#     that plan's context, so the plan's own pieces are Ready, never "reserved" by it
#     (INTEGRATION-D section 5);
#   - A's reference cards and C's photo pick name the same front crop (INTEGRATION-A 11.3);
#   - OPS-05 through A's own Privacy row while a See it on me press is in flight keeps no picture,
#     no photo, no YES and no figure; the spend stays and the wardrobe is untouched (review A-1
#     F12 with review C-1 finding 3).
#
# These pin behaviour the parts already had once joined: they passed when first run.
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from r131_console_query import look_query
from r131_fake_tryon import Step
from r131_fakes import UID, T
from r131_fakes_a import a_world
from r131_fakes_c import (
    NEW_SHIRT,
    PERSON,
    FakeBilling,
    GatedProvider,
    OnMode,
    StrictTryOn,
    ask,
    seeme_world,
    shown_version,
)

from jarvis.wardrobe.seeme import pair
from jarvis.wardrobe.seeme.part import build as build_c
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.tryon.part import build as build_a

PLANNED_JACKET, OTHER_JACKET = "wi_000000000017", "wi_000000000016"


async def test_a_swap_inside_a_plans_look_reads_readiness_in_that_plans_context() -> None:
    a = await a_world()
    plan = await a.plan()
    async with a.client() as c:
        look = (await c.get(f"/v1/tryon/look?plan={plan}")).json()
        held = {s["slot"]: s.get("piece") for s in look["slots"]}
        assert held["outer"] == PLANNED_JACKET
        swapped = {**held, "outer": OTHER_JACKET}
        picks = [{"slot": k, "piece": v} for k, v in swapped.items() if v]  # the console's swap
        mine = (await c.get("/v1/tryon/look?" + look_query(picks, plan, look))).json()
        bare = (await c.get("/v1/tryon/look?" + look_query(picks, None, look))).json()
    got = {s["slot"]: (s.get("piece"), s["readiness"]) for s in mine["slots"]}
    assert mine["plan"] == plan and got["outer"] == (OTHER_JACKET, "Ready")
    assert all(r == "Ready" for _, r in got.values())  # the plan's own pieces are its own
    # ... while the same pieces with no plan are held by it: why D sends the plan along
    assert bare["plan"] is None
    held_by_it = {
        s["readiness"] for s in bare["slots"] if s.get("piece") not in (None, OTHER_JACKET)
    }
    assert held_by_it == {"Draft: reserved for your plan"}


async def _joined(provider: Any) -> tuple[Any, Any, Any, Any]:
    """C's world (R13's styling, the photos with their views), then BOTH real parts registered in
    the one `r13_parts` map the services read late: his photo, his YES and a new navy shirt."""
    sw = await seeme_world(provider=provider, billing=FakeBilling(), mode=OnMode())
    parts = sw.state["r13_parts"]
    parts["seeme"] = build_c(sw.ctx)
    parts["tryon"] = build_a(sw.ctx)
    svc = parts["seeme"].services["seeme"]
    await svc.save_photo(UID, PERSON)
    await svc.give_consent(UID, "YES", shown_version(svc))
    garment = await svc.add_garment(UID, "shirt", "navy", NEW_SHIRT)
    return sw, parts, svc, garment


async def test_as_reference_cards_and_cs_photo_pick_name_the_same_front_crop() -> None:
    sw, parts, _, _ = await _joined(StrictTryOn(max_garments=1))
    looks = parts["tryon"].services["tryon_looks"].looks
    look = await looks.for_pieces(UID, f"top:{T.kurta}")
    kurta = next(s for s in look.slots if s.slot == "top")
    refs = {r.view: r.photo for r in kurta.refs}
    piece = (await sw.w.store.view(UID)).pieces[T.kurta]
    assert set(refs) == {"front", "back"}
    assert refs["front"] == await pair.front_of(sw.ctx, UID, piece)


def _left(sw: Any, collection: str) -> list[str]:
    return [p for p in sw.docs._data if f"/{collection}/" in f"/{p}"]  # noqa: SLF001


async def test_ops05_by_as_row_during_a_press_keeps_nothing_but_the_spend() -> None:
    gated = GatedProvider(StrictTryOn(max_garments=3, script=[Step()]))
    sw, parts, svc, g = await _joined(gated)
    await parts["tryon"].services["tryon_looks"].put_body(UID, {"height": 178})
    rev = (await sw.w.store.view(UID)).rev
    body = ask(g.id, (), inr=(await svc.estimate(UID, g.id, [])).typical_inr)
    press = asyncio.create_task(svc.press(UID, body))
    await gated.entered.wait()  # Google is making it ...
    prefix = sw.ctx.s.firestore_prefix
    kept = ("tryon_person", "tryon_consent", "tryon_garment", "tryon")
    assert all(_left(sw, f"{prefix}{c}") for c in kept)  # all there before the delete
    row = {r.id: r for r in parts["tryon"].privacy}["tryon_all"]
    assert await row.delete(UID) > 0  # OPS-05: A's own row, C's half through C's service
    gated.gate.set()  # ... and now it answers
    with pytest.raises(SeeMeRefused) as err:
        await press
    assert (err.value.status, err.value.code) == (422, "no_photo")
    for gone in ("tryon_picture", "tryon_person", "tryon_consent", "tryon_garment", "tryon"):
        assert _left(sw, f"{prefix}{gone}") == [], gone
    assert _left(sw, f"{prefix}tryon_spend")  # the month's spend stays (13 months)
    assert (await sw.w.store.view(UID)).rev == rev  # the wardrobe untouched
    month = await svc.kit.cap.month(UID)
    assert month.holds == {} and month.spent_inr > 0  # closed at what Google made
