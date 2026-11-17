# tests/test_r131_a_rows.py -- R13.1 Part A's rows, his workbook's acceptance checks word for word
# (docs/plans/r13-1-try-on.md, the first table), each through Part A's routes on R13's real
# styling, store and gateway (`r131_fakes_a`), at a FIXED clock (17 Nov 2026 09:00 IST).
#
#   354 AVT-03  Correcting height updates the avatar and its previews while retaining saved outfit
#               selections.
#   355 AVT-04  A kurta has recognisable front and back references and remains linked to its
#               original inventory record.
#   356 AVT-05  A patterned shirt can use an approximate silhouette while its actual reference
#               image stays visible.
#   360 AVT-09  Swapping a ready jacket changes the avatar and checklist together. A jacket in
#               laundry cannot be confirmed for the event.
#   350 OPS-05  Deleting an avatar removes it from the viewer and disables dependent previews while
#               retaining the item catalog.
from __future__ import annotations

import json
from typing import Any

from r131_fakes_a import UID, AWorld, T, a_world, build_tryon, seeme_docs

from jarvis.privacy.ports import PrivacyRegistry
from jarvis.privacy.service import CONFIRM_WORD, PrivacyService
from jarvis.tools.audit import AuditLog
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon.http import BodyVersions, SavedView, TryonLook, TryonView

IN_LAUNDRY = "The navy jacket is in the laundry: it can't be confirmed for this event."
LOCK_REFUSED = "The navy jacket is in the laundry: it can't be locked into this plan."


def _ids(look: TryonLook) -> list[tuple[str, str | None]]:
    return [(s.slot, s.piece) for s in look.slots]


def _slot(look: TryonLook, slot: str) -> Any:
    return next(s for s in look.slots if s.slot == slot)


# ---- 354 · AVT-03 ----------------------------------------------------------------------------
async def test_avt03_correcting_height_reshapes_the_figure_and_keeps_every_saved_selection() -> (
    None
):
    a = await a_world()
    pid = await a.plan()
    async with a.client() as c:
        assert (await c.put("/v1/tryon/body", json={"height": 172})).status_code == 200
        first = BodyVersions.model_validate((await c.post("/v1/tryon/body/use")).json())
        look = TryonLook.model_validate((await c.get(f"/v1/tryon/look?plan={pid}")).json())
        pairs = [{"slot": s, "piece": p} for s, p in _ids(look) if p is not None]
        made = await c.post("/v1/tryon/saved", json={"looks": [{"plan": pid, "slots": pairs}]})
        sid = SavedView.model_validate(made.json()).id
        before_look = json.dumps(_ids(look))
        before_saved = json.dumps((await c.get(f"/v1/tryon/saved/{sid}")).json()["looks"])

        typed = await c.put("/v1/tryon/body", json={"height": 178})  # he corrects his height
        draft = BodyVersions.model_validate(typed.json())
        assert draft.current == first.current  # the old version stays in use until he says so
        assert draft.draft is not None and draft.draft.height == 178
        assert draft.draft.typed == ("height",)  # every other measurement is shown "estimated"
        assert draft.draft.chest == m.estimated(178)["chest"]
        assert draft.draft.weights == m.morph_weights(
            draft.draft.model_dump(include=set(m.MEASURES))
        )
        assert draft.draft.weights["height"] != first.current.weights["height"]  # type: ignore[union-attr]
        shown = TryonView.model_validate((await c.get("/v1/tryon")).json())
        assert shown.words == m.ESTIMATED and shown.body.current.height == 172  # type: ignore[union-attr]

        used = BodyVersions.model_validate((await c.post("/v1/tryon/body/use")).json())
        assert used.current is not None and used.current.height == 178
        assert [b.height for b in used.earlier] == [172]

        again = TryonLook.model_validate((await c.get(f"/v1/tryon/look?plan={pid}")).json())
        after_saved = json.dumps((await c.get(f"/v1/tryon/saved/{sid}")).json()["looks"])
    assert json.dumps(_ids(again)) == before_look  # byte-identical piece ids per slot
    assert after_saved == before_saved


# ---- 355 · AVT-04 ----------------------------------------------------------------------------
async def test_avt04_a_kurta_shows_its_front_and_back_references_under_its_own_id() -> None:
    a = await a_world()
    catalog = (await a.view()).pieces[T.kurta]
    async with a.client() as c:
        look = TryonLook.model_validate(
            (await c.get(f"/v1/tryon/look?pieces=top:{T.kurta}")).json()
        )
        kurta = _slot(look, "top")
        assert kurta.piece == catalog.id == T.kurta  # the same wi_ id as in the catalog
        assert kurta.views == ("front", "back") and kurta.missing == ()
        assert [(r.view, r.photo) for r in kurta.refs] == [  # its two reference cards, named
            ("front", "wh_00000000a001"), ("back", "wh_00000000a002")
        ]  # fmt: skip
        assert kurta.photo in catalog.photos  # a reference card from its own crops
        assert {o.photo for o in kurta.options if o.piece == T.kurta} <= set(catalog.photos)

        await a.w.edit(T.kurta, photos=("wh_00000000a001",))  # a kurta with only a front
        only = TryonLook.model_validate(
            (await c.get(f"/v1/tryon/look?pieces=top:{T.kurta}")).json()
        )
    front = _slot(only, "top")
    assert front.views == ("front",) and front.missing == ("back",)  # asks for the back only
    assert [(r.view, r.photo) for r in front.refs] == [("front", "wh_00000000a001")]
    assert front.eligible is True and front.readiness == m.READY  # and stays selectable
    assert any(o.piece == T.kurta and o.eligible for o in front.options)


# ---- 356 · AVT-05 ----------------------------------------------------------------------------
async def test_avt05_a_patterned_shirt_draws_on_an_approximate_shape_beside_its_real_photo() -> (
    None
):
    from r13_fakes import piece

    a = await a_world()
    tie = piece("wi_0000000002aa", "tie", colour="navy")
    await a.w.add(tie)
    catalog = (await a.view()).pieces[T.striped]
    async with a.client() as c:
        chose = await c.put(f"/v1/tryon/assets/{T.striped}",
                            json={"piece": T.striped, "template": "shirt"})  # fmt: skip
        assert chose.status_code == 200
        url = f"/v1/tryon/look?pieces=top:{T.striped},tie:{tie.id}"
        look = TryonLook.model_validate((await c.get(url)).json())
    shirt = _slot(look, "top")
    assert catalog.pattern == "striped" and shirt.pattern == "striped"  # a patterned shirt
    assert shirt.template == "shirt" and "template" in shirt.approximate  # "Approximate"
    assert shirt.texture_view == "detail" and shirt.photo == "wh_00000000b002"  # its own crop
    assert "front" in shirt.views  # its front photo card stays beside the figure
    assert next(o for o in shirt.options if o.piece == T.striped).photo == "wh_00000000b001"
    assert _slot(look, "tie").card_only is True and _slot(look, "tie").template is None
    stored = await a.service.store.read(UID)  # saved against its id, not in page memory
    assert stored.assets[T.striped].template == "shirt"
    fresh = build_tryon(a.ctx).services["tryon_looks"]
    view = await fresh.tryon_view(UID, release="m1", files=())
    assert [(x.piece, x.template) for x in view.assets] == [(T.striped, "shirt")]


# ---- 360 · AVT-09 ----------------------------------------------------------------------------
class _Watch:
    """Counts `outfit_plan` calls through the world's gateway; `before` runs just ahead of one."""

    def __init__(self, a: AWorld, before: Any = None) -> None:
        self.calls: list[str] = []
        real = a.w.gw.execute

        async def execute(call: Any, **kw: Any) -> Any:
            if call.name == "outfit_plan":
                self.calls.append(call.arguments["action"])
                if before is not None:
                    await before()
            return await real(call, **kw)

        a.w.gw.execute = execute  # type: ignore[method-assign]


async def test_avt09_a_ready_jacket_swaps_figure_and_checklist_together_and_one_in_laundry_stays_a_draft() -> (  # noqa: E501 - his row's test name
    None
):
    a = await a_world()
    pid = await a.plan()
    async with a.client() as c:
        look = TryonLook.model_validate((await c.get(f"/v1/tryon/look?plan={pid}")).json())
        outer = _slot(look, "outer")
        assert outer.piece == T.blazer
        ready = next(o for o in outer.options if o.piece == T.rain_jacket)
        assert ready.eligible and ready.readiness == m.READY
        url = f"/v1/tryon/look?plan={pid}&pieces=top:{T.white},outer:{T.rain_jacket}"
        swapped = _slot(TryonLook.model_validate((await c.get(url)).json()), "outer")
        assert swapped.piece == T.rain_jacket and swapped.template == "jacket"  # the figure's layer
        assert (
            swapped.words == "a navy jacket" and swapped.readiness == m.READY
        )  # its checklist row

        await a.move(T.rain_jacket)  # the jacket goes to the laundry
        drafted = _slot(TryonLook.model_validate((await c.get(url)).json()), "outer")
        assert drafted.readiness == "Draft: in the laundry" and not drafted.eligible
        watch = _Watch(a)
        before = (await a.styling.plans.read(UID)).plan(pid)
        whole = await a.whole(pid, outer=T.rain_jacket)  # every slot the figure shows
        refused = await c.post("/v1/tryon/confirm", json=whole)
        assert refused.status_code == 409
        assert refused.json() == {"error": "draft", "detail": IN_LAUNDRY}
        assert watch.calls == []  # the server's fresh check: no outfit_plan call is made
        assert (await a.styling.plans.read(UID)).plan(pid) == before
        assert await a.w.gw.gate.pending() == []
    await _the_race_is_refused_by_outfit_plan()
    await _a_ready_jacket_is_one_lock_of_every_slot()


async def _the_race_is_refused_by_outfit_plan() -> None:
    b = await a_world()  # the race: to the laundry between the check and the call (D20)
    pid = await b.plan()

    async def to_the_laundry() -> None:
        await b.move(T.rain_jacket)

    race = _Watch(b, before=to_the_laundry)
    before = (await b.styling.plans.read(UID)).plan(pid)
    async with b.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await b.whole(pid, outer=T.rain_jacket))
    assert race.calls == ["lock"]  # ONE call, and outfit_plan's own check refused it
    assert got.status_code == 409 and got.headers["cache-control"] == "no-store"  # never "done"
    assert got.json() == {"error": "refused", "detail": LOCK_REFUSED}  # R13's own words
    assert (await b.styling.plans.read(UID)).plan(pid) == before  # the plan unchanged
    assert len(await b.w.gw.gate.pending()) <= 1  # one press makes at most one card


async def _a_ready_jacket_is_one_lock_of_every_slot() -> None:
    ok = await a_world()  # a ready jacket is confirmed in one lock of every slot
    pid = await ok.plan()
    done = _Watch(ok)
    async with ok.client() as c:
        whole = await ok.whole(pid, outer=T.rain_jacket)
        locked = await c.post("/v1/tryon/confirm", json=whole)
    assert locked.status_code == 200 and locked.json()["status"] == "executed"
    assert done.calls == ["lock"]
    plan = (await ok.styling.plans.read(UID)).plan(pid)
    assert plan.slot("outer").pieces == (T.rain_jacket,) and plan.slot("outer").locked


# ---- 350 · OPS-05 ----------------------------------------------------------------------------
async def test_ops05_deleting_the_figure_empties_the_viewer_disables_previews_and_keeps_the_catalog() -> (  # noqa: E501 - his row's test name
    None
):
    a = await a_world(seeme=True)
    async with a.client() as c:
        await c.put("/v1/tryon/body", json={"height": 176})
        await c.post("/v1/tryon/body/use")
        await c.put(f"/v1/tryon/assets/{T.striped}", json={"piece": T.striped, "card_only": True})
        await c.post("/v1/tryon/saved", json={"looks": [{"slots": [
            {"slot": "top", "piece": T.white}]}]})  # fmt: skip
        catalog = await c.get("/v1/wardrobe")  # R13's own route, as his check says
    assert catalog.status_code == 200 and catalog.json()["pieces"]
    paths = await seeme_docs(a.docs)  # his photo, YES, a picture, a garment photo, the spend
    before, crops = await a.view(), dict(a.vault.crops)

    reg = PrivacyRegistry()
    for row in a.part.privacy:
        reg.register(row)
    svc = PrivacyService(reg, audit=AuditLog())
    row = next(x for x in (await svc.view(UID)).categories if x.id == kept.ALL_ID)
    assert row.label == "All your try-on data" and row.delete == "passkey"
    got = await svc.delete(UID, kept.ALL_ID, rev=row.rev, confirm=CONFIRM_WORD, proof=None,
                           fresh_left_s=60)  # fmt: skip
    assert got.deleted == 5 and got.remaining == 0

    async with a.client() as c:
        view = TryonView.model_validate((await c.get("/v1/tryon")).json())
        saved = (await c.get("/v1/tryon/saved")).json()
        kept_catalog = await c.get("/v1/wardrobe")
    assert kept_catalog.status_code == 200  # GET /v1/wardrobe: the same pieces and rev
    assert [kept_catalog.json()[k] for k in ("pieces", "rev")] == [
        catalog.json()[k] for k in ("pieces", "rev")
    ]
    assert view.words == m.NO_FIGURE  # the viewer says "No figure yet"
    assert view.body.current is None and view.body.draft is None and view.body.earlier == ()
    assert view.saved == () and view.assets == () and saved == {"saved": []}
    left = [p for p in paths if await a.docs.get(p) is not None]
    assert left == [paths[-1]]  # pictures, garment photos, his photo and YES gone; the spend kept
    assert a.seeme is not None and a.seeme.calls == [UID]  # See it on me asks for a photo again
    after = await a.view()
    assert after.rev == before.rev and after.pieces == before.pieces  # the catalog, as it was
    assert a.vault.crops == crops
