# evals/r13_1/looks.py
"""R13.1 eval, Part A (`looks`: try-on data; docs/plans/r13-1-try-on.md "Tests and evals").

Every case runs Part A's real part and routes on R13's real styling part, store and gateway
(`tests/r131_fakes_a.py`, a FIXED clock: 17 Nov 2026 09:00 IST); nothing calls Google.

- AVT-03: a new measurement version leaves every saved selection's piece ids as they were, the
  old version in use until "Use these measurements", an untyped one estimated;
- AVT-04: a kurta's front and back under its own id; with a front only, the back is asked for and
  it stays selectable;
- AVT-05: his figure choice is saved against the piece id (`tryon/{uid}.assets`) and drawn from
  its own crop;
- AVT-09: the laundry jacket offered as "Draft: in the laundry"; the fresh check refuses it with
  no `outfit_plan` call; the race (to the laundry between the check and the call) is refused by
  `outfit_plan` itself, the plan unchanged; one press makes at most one card;
- AVT-11: a saved comparison keeps both lists and is re-checked on opening ("Draft");
- AVT-14: no private piece's id, colour, photo or label in any look, option or words served (a
  reply card's covered slot, row 388, included);
- OPS-05: C's half first, `tryon/{uid}` last, the spend kept, the catalog's `rev` unchanged;
- D20: `outfit_plan`'s `lock` and `reserve` refuse a piece in the laundry.

Controls (each must turn its case red): the private filter off (AVT-14); a slot's options keep
private pieces (AVT-14, review A-1 F4); the fresh check off (AVT-09's laundry jacket gets past
the early refusal); `lock` without D20's check (`styling.actions.unready` answers None: the race
writes the jacket, D20's case fails). Each row's own control (M8): AVT-03 a new version rewrites
a saved comparison's piece ids; AVT-04 the look drops the kurta's back view; AVT-05 the choice
kept in page memory, not `tryon/{uid}`; AVT-09 `lock` without D20's check; AVT-11 a saved
comparison answers its slots as Ready, never re-checked (review A-1 F11); OPS-05 the erase also
deletes the wardrobe's photos.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r131_fakes_a import UID, PlanCalls, T, a_world, build_tryon, seeme_docs  # noqa: E402

from jarvis.privacy.ports import PrivacyRegistry  # noqa: E402
from jarvis.privacy.service import CONFIRM_WORD, PrivacyService  # noqa: E402
from jarvis.storage.docs import DocTx  # noqa: E402
from jarvis.wardrobe.ports import Commit  # noqa: E402
from jarvis.wardrobe.styling import actions  # noqa: E402
from jarvis.wardrobe.tryon import assets, confirm, erase, kept, looks, saved, versions  # noqa: E402
from jarvis.wardrobe.tryon import model as m  # noqa: E402
from jarvis.wardrobe.tryon.http import AssetChoice, SavedIn, TryonLook  # noqa: E402
from jarvis.wardrobe.tryon.store import TryonDoc  # noqa: E402

PART = "looks"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
IN_LAUNDRY = "The navy jacket is in the laundry: it can't be confirmed for this event."
LOCK_REFUSED = "The navy jacket is in the laundry: it can't be locked into this plan."
MAROON_RGB = json.dumps(list(m.rgb_of("maroon")))  # a look serves colour as numbers, never words
FIGURE = f"jarvis_tryon/{UID}"


def _slot(look: TryonLook, slot: str) -> Any:
    return next((s for s in look.slots if s.slot == slot), None)


# ---- the cases ----------------------------------------------------------------------------------
async def avt03_versions_keep_saved_selections() -> list[str]:
    a, out = await a_world(), []
    pid = await a.plan()
    s = a.service
    await s.put_body(UID, {"height": 172})
    first = await s.use_body(UID)
    look = await s.looks.for_plan(UID, pid)
    pairs = [{"slot": x.slot, "piece": x.piece} for x in look.slots if x.piece]
    made = await s.save(UID, SavedIn.model_validate({"looks": [{"plan": pid, "slots": pairs}]}))
    before = json.dumps([x.look.model_dump(mode="json") for x in made.looks])
    drafted = await s.put_body(UID, {"height": 178})
    if drafted.current != first.current:
        out.append("the old version was replaced before he used the new one")
    if drafted.draft is None or drafted.draft.typed != ("height",):
        out.append("an untyped measurement isn't shown estimated")
    await s.use_body(UID)
    again = await s.saved_one(UID, made.id)
    if json.dumps([x.look.model_dump(mode="json") for x in again.looks]) != before:
        out.append("a saved comparison's piece ids changed with the version")
    now = await s.looks.for_plan(UID, pid)
    if [(x.slot, x.piece) for x in now.slots] != [(x.slot, x.piece) for x in look.slots]:
        out.append("the plan's look changed with the version")
    return out


async def avt04_kurta_front_and_back() -> list[str]:
    a, out = await a_world(), []
    kurta = _slot(await a.service.looks.for_pieces(UID, f"top:{T.kurta}"), "top")
    if kurta is None or kurta.piece != T.kurta or kurta.views != ("front", "back"):
        out.append(f"the kurta's views: {getattr(kurta, 'views', None)}")
    cards = [(r.view, r.photo) for r in getattr(kurta, "refs", ())]
    if cards != [("front", "wh_00000000a001"), ("back", "wh_00000000a002")]:
        out.append(f"the kurta's reference cards: {cards}")  # AVT-04's front and back cards
    await a.w.edit(T.kurta, photos=("wh_00000000a001",))
    front = _slot(await a.service.looks.for_pieces(UID, f"top:{T.kurta}"), "top")
    if front is None or front.missing != ("back",) or not front.eligible:
        out.append("a front-only kurta doesn't ask for the back, or isn't selectable")
    return out


async def avt05_association_saved_against_the_id() -> list[str]:
    a, out = await a_world(), []
    choice = AssetChoice(piece=T.striped, template="shirt", texture_view="front")
    await a.service.choose(UID, T.striped, choice)
    stored = (await a.service.store.read(UID)).assets.get(T.striped)
    if stored is None or stored.texture_view != "front":
        out.append("the choice is not in tryon/{uid}.assets")
    fresh = build_tryon(a.ctx).services["tryon_looks"]  # another page, another day
    shirt = _slot(await fresh.looks.for_pieces(UID, f"top:{T.striped}"), "top")
    if shirt is None or shirt.texture_view != "front" or shirt.photo != "wh_00000000b001":
        out.append("the figure doesn't draw his choice from its own crop")
    if shirt is not None and "template" not in shirt.approximate:
        out.append("the shape isn't marked approximate")
    return out


async def avt09_fresh_check_refuses_without_a_call() -> list[str]:
    a, out = await a_world(), []
    pid = await a.plan()
    await a.move(T.rain_jacket)
    outer = _slot(await a.service.looks.for_plan(UID, pid), "outer")
    offered = next((o for o in getattr(outer, "options", ()) if o.piece == T.rain_jacket), None)
    if offered is None or offered.eligible or offered.readiness != "Draft: in the laundry":
        out.append("the laundry jacket isn't offered as a draft")
    calls = PlanCalls(a)
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=await a.whole(pid, outer=T.rain_jacket))
    if got.status_code != 409 or got.json().get("detail") != IN_LAUNDRY:
        out.append(f"not refused in words before the call: {got.status_code} {got.json()}")
    if calls.n:
        out.append("an outfit_plan call was made for a draft")
    return out


async def avt09_race_refused_by_outfit_plan() -> list[str]:
    a, out = await a_world(), []
    pid = await a.plan()

    async def to_the_laundry() -> None:
        await a.move(T.rain_jacket)

    whole = await a.whole(pid, outer=T.rain_jacket)  # every slot the figure shows
    PlanCalls(a, before=to_the_laundry)
    before = (await a.styling.plans.read(UID)).plan(pid)
    async with a.client() as c:
        got = await c.post("/v1/tryon/confirm", json=whole)
    if got.status_code != 409 or got.json() != {"error": "refused", "detail": LOCK_REFUSED}:
        out.append(f"not refused in R13's words: {got.status_code}")  # never 200 "executed"
    if (await a.styling.plans.read(UID)).plan(pid) != before:
        out.append("the plan changed")
    if len(await a.w.gw.gate.pending()) > 1:
        out.append("more than one card for one press")
    return out


async def avt11_saved_rechecked() -> list[str]:
    a, out = await a_world(), []
    formal = {"slots": [{"slot": "top", "piece": T.white}, {"slot": "bottom", "piece": T.trousers}]}
    festive = {"slots": [{"slot": "top", "piece": T.kurta}, {"slot": "bottom", "piece": T.pyjama}]}
    made = await a.service.save(UID, SavedIn.model_validate({"looks": [formal, festive]}))
    await a.move(T.kurta)
    again = await a.service.saved_one(UID, made.id)
    lists = [[(s.slot, s.piece) for s in x.look.slots] for x in again.looks]
    if lists != [[(s["slot"], s["piece"]) for s in x["slots"]] for x in (formal, festive)]:
        out.append("an item list was lost")
    if not again.draft or again.looks[0].draft or not again.looks[1].draft:
        out.append("the changed look isn't marked Draft, or the other is")
    if len(again.looks) != 2 or again.looks[1].readiness[0] != "Draft: in the laundry":
        out.append("the festive look lost its readiness words")
    return out


async def avt14_private_slots_covered() -> list[str]:
    a, out = await a_world(), []
    await a.w.edit(T.vest, label="Lucky vest", colour="maroon")
    pid = await a.plan()
    await a.move(T.under)
    served = [
        await a.service.looks.for_plan(UID, pid),
        await a.service.looks.for_day(UID, "today"),
        await a.service.looks.for_pieces(UID, f"top:{T.shirt},base:{T.vest},underwear:{T.under}"),
        await a.service.looks.for_pieces(UID, f"top:,bottom:{T.trousers}"),  # a card's covered top
    ]
    out += _private_served(served, (T.vest, T.under))
    await a.w.edit(T.white, private=True, label="Lucky shirt", colour="maroon")  # private since
    later = [  # the plan's top now covered; another top shown, whose options must skip it
        await a.service.looks.for_plan(UID, pid),
        await a.service.looks.for_pieces(UID, f"top:{T.shirt}"),
    ]
    return out + _private_served(later, (T.vest, T.under, T.white))


def _private_served(served: list[TryonLook], ids: tuple[str, ...]) -> list[str]:
    """Each private piece's id, label or colour (as words, or as the `rgb` a look serves) found
    in a look, and each covered slot drawn."""
    out: list[str] = []
    for look in served:
        text = json.dumps(look.model_dump(mode="json"))
        out += [f"{n} served" for n in (*ids, "maroon", MAROON_RGB, "Lucky") if n in text]
        for s in look.slots:
            if (s.slot in m.PRIVATE_SLOTS or s.private) and (
                s.template or s.rgb or s.photo or s.options or s.piece
            ):
                out.append(f"the {s.slot} slot is drawn")
    return out


async def ops05_erase_order_and_catalog_rev() -> list[str]:
    a, out = await a_world(seeme=True), []
    await a.service.put_body(UID, {"height": 176})
    await a.service.use_body(UID)
    paths = await seeme_docs(a.docs)
    before, crops = await a.view(), dict(a.vault.crops)
    assert a.seeme is not None
    order: list[bool] = []
    real = a.seeme.erase

    async def watched(uid: str) -> int:
        order.append(await a.docs.get(FIGURE) is not None)
        return await real(uid)

    a.seeme.erase = watched  # type: ignore[method-assign]
    reg = PrivacyRegistry()
    for row in a.part.privacy:
        reg.register(row)
    svc = PrivacyService(reg)
    row = next(x for x in (await svc.view(UID)).categories if x.id == kept.ALL_ID)
    await svc.delete(UID, kept.ALL_ID, rev=row.rev, confirm=CONFIRM_WORD, proof=None,
                     fresh_left_s=60)  # fmt: skip
    if order != [True]:
        out.append("C's half didn't go before the figure")
    if [p for p in paths if await a.docs.get(p) is not None] != [paths[-1]]:
        out.append("C's documents weren't all gone, or the spend went too")
    if await a.docs.get(FIGURE) is not None:
        out.append("the figure is still there")
    after = await a.view()
    if after.rev != before.rev or after.pieces != before.pieces or a.vault.crops != crops:
        out.append("the wardrobe catalog changed")
    return out


async def d20_lock_and_reserve_refuse_a_laundry_piece() -> list[str]:
    a, out = await a_world(), []
    pid = await a.plan()
    await a.move(T.blazer)
    before = (await a.styling.plans.read(UID)).plan(pid)
    for action in ("lock", "reserve"):
        got = await a.w.call("outfit_plan", action=action, plan=pid, piece=T.blazer)
        if not (got.result or {}).get("refused"):
            out.append(f"{action} took a blazer in the laundry")
    if (await a.styling.plans.read(UID)).plan(pid) != before:
        out.append("the plan changed")
    return out


CASES: dict[str, Case] = {
    "avt03_versions_keep_saved_selections": avt03_versions_keep_saved_selections,
    "avt04_kurta_front_and_back": avt04_kurta_front_and_back,
    "avt05_association_saved_against_the_id": avt05_association_saved_against_the_id,
    "avt09_fresh_check_refuses_without_a_call": avt09_fresh_check_refuses_without_a_call,
    "avt09_race_refused_by_outfit_plan": avt09_race_refused_by_outfit_plan,
    "avt11_saved_rechecked": avt11_saved_rechecked,
    "avt14_private_slots_covered": avt14_private_slots_covered,
    "ops05_erase_order_and_catalog_rev": ops05_erase_order_and_catalog_rev,
    "d20_lock_and_reserve_refuse_a_laundry_piece": d20_lock_and_reserve_refuse_a_laundry_piece,
}


async def _run(name: str) -> dict[str, Any]:
    try:
        failures = await CASES[name]()
    except Exception as exc:  # noqa: BLE001 - a case that breaks fails, with its class name
        failures = [f"raised {type(exc).__name__}"]
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


async def cases() -> list[dict[str, Any]]:
    return [await _run(name) for name in CASES]


# ---- the controls -------------------------------------------------------------------------------
@contextmanager
def _swapped(module: Any, name: str, value: Any) -> Iterator[None]:
    real = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, real)


def _rewrites_saved(real: Callable[[TryonDoc], TryonDoc]) -> Callable[[TryonDoc], TryonDoc]:
    def use(doc: TryonDoc, *seen: Any) -> TryonDoc:  # AVT-03's control: it rewrites saved ids
        new = real(doc, *seen)
        saved = tuple(
            s.model_copy(update={"looks": tuple(
                lk.model_copy(update={"slots": tuple(
                    x.model_copy(update={"piece": T.striped}) for x in lk.slots
                )}) for lk in s.looks
            )}) for s in new.saved
        )  # fmt: skip
        return new.model_copy(update={"saved": saved})

    return use


def _no_back(real: Any) -> Any:
    async def views(*args: Any) -> dict[str, Any]:  # AVT-04's control: the back view dropped
        return {k: v for k, v in (await real(*args)).items() if v != "back"}

    return views


def _page_memory(real: Any) -> Any:
    def choose(doc: TryonDoc, *args: Any) -> Any:  # AVT-05's control: never in tryon/{uid}
        _, made = real(doc, *args)
        return doc, made

    return choose


def _takes_photos(real: Any) -> Any:
    async def erase_all(ctx: Any, store: Any, uid: str) -> int:  # OPS-05's: the photos go too
        async def fn(view: Any, tx: DocTx) -> Commit:
            recs = tuple(p.model_copy(update={"photos": ()}) for p in view.pieces.values())
            return Commit(records=recs)

        await ctx.store().transact(uid, fn)
        return int(await real(ctx, store, uid))

    return erase_all


def _keeps_private(real: Any) -> Any:
    def units(f: Any, slot: str) -> Any:  # AVT-14's second control (F4): options keep private
        bare = {k: p.model_copy(update={"private": False}) for k, p in f.view.pieces.items()}
        return real(replace(f, view=f.view.model_copy(update={"pieces": bare})), slot)

    return units


def _never_rechecked(real: Any) -> Any:
    def look_view(r: Any, look: Any) -> Any:  # AVT-11's control (F11): Ready, never re-checked
        got = real(r, look)
        ready = tuple(m.READY for _ in got.readiness) if got is not None else ()
        return got and got.model_copy(update={"readiness": ready, "draft": False})

    return look_view


def _controls() -> list[tuple[str, Any, str, Any]]:
    """(the case it must turn red, module, name, the stand-in)."""
    no_d20 = (actions, "unready", lambda *a, **k: None)
    return [
        ("avt14_private_slots_covered", looks, "covered", lambda *a: False),
        ("avt14_private_slots_covered", looks.o, "_units", _keeps_private(looks.o._units)),
        ("avt09_fresh_check_refuses_without_a_call", confirm, "first_draft", lambda *a: None),
        ("avt09_race_refused_by_outfit_plan", *no_d20),
        ("d20_lock_and_reserve_refuse_a_laundry_piece", *no_d20),
        ("avt03_versions_keep_saved_selections", versions, "use", _rewrites_saved(versions.use)),
        ("avt04_kurta_front_and_back", looks, "photo_views", _no_back(looks.photo_views)),
        ("avt05_association_saved_against_the_id", assets, "choose", _page_memory(assets.choose)),
        ("ops05_erase_order_and_catalog_rev", erase, "erase_all", _takes_photos(erase.erase_all)),
        ("avt11_saved_rechecked", saved, "look_view", _never_rechecked(saved.look_view)),
    ]


async def control() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case, module, name, value in _controls():
        with _swapped(module, name, value):
            got = await _run(case)
        results.append({**got, "id": f"{got['id']}~{module.__name__.rsplit('.', 1)[-1]}.{name}"})
    failed = [r["id"] for r in results if not r["passed"]]
    return {
        "name": "the private filter off; the fresh check off; lock without D20's check; "
        "options keep private pieces; each row's own control (AVT-03, 04, 05, 09, 11, OPS-05)",
        "suite_failed": len(failed) == len(results),  # every control turned its case red
        "failed_cases": failed,
    }
