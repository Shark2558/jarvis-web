# tests/test_r13_a_lifecycle.py -- R13 Part A (docs/plans/r13-wardrobe.md D16, D10, D18; INV-16,
# INV-17): merge and archive / restore are cards every time (never "Approve all"), remove keeps the
# piece in Recently deleted under a fixed title (in place: same id, back "Missing or in review"),
# a purge takes its log and photos; the tools' words, fences and trust rule through the gateway.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID, ev
from r13_fakes_a import Catalog, approve, call, catalog, gateway, jpeg

from jarvis.core.guardrails import NO_BULK_TOOLS, ActionRisk
from jarvis.tools import Effect, PolicyRule
from jarvis.tools.external import FENCE_END
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust
from jarvis.undo.models import RestoreStatus
from jarvis.wardrobe.catalog.edits import NewPiece
from jarvis.wardrobe.ports import Commit, Refused
from jarvis.wardrobe.redact import BIN_TITLE


@pytest.fixture
def cat() -> Catalog:
    return catalog()


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _add(cat: Catalog, *specs: NewPiece) -> list[str]:
    return list((await desk(cat).service.add(UID, specs)).ids)


def test_the_eight_tools_have_their_risks_cards_and_fixed_activity_words(cat: Catalog) -> None:
    by = {t.name: t for t in cat.part.tools}
    assert by["wardrobe_find"].risk is ActionRisk.READ_ONLY
    assert by["wardrobe_count"].risk is ActionRisk.READ_ONLY
    rest = set(by) - {"wardrobe_find", "wardrobe_count"}
    assert all(by[n].risk is ActionRisk.REVERSIBLE for n in rest)
    assert by["wardrobe_merge"].asks({}) and by["wardrobe_retire"].asks({})  # always a card
    assert {"wardrobe_merge", "wardrobe_retire"} <= NO_BULK_TOOLS  # never "Approve all"
    assert by["wardrobe_remove"].undoable and not by["wardrobe_remove"].asks({})
    assert all(not t.trusted_output and t.activity_words for t in by.values())
    assert not any(t.spoken_ok for t in by.values())  # laundry_move and wear_log only (B, C)


# ---- INV-16 · merging two records of one watch -------------------------------------------------
async def test_inv16_merging_two_records_of_one_watch_is_a_card_and_keeps_one_continuous_history(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    keep, other = await _add(
        cat, NewPiece(type="watch", label="Steel watch"), NewPiece(type="watch")
    )
    cat.clock.advance(hours=1)
    await desk(cat).service.move(UID, other, (await desk(cat).places.add(UID, "Accessory tray")).id)
    asked = await call(gw, "wardrobe_merge", keep=keep, merge=other)
    assert asked.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert "Steel" not in (asked.pending.summary if asked.pending else "")  # never his label
    assert asked.pending is not None and "a watch" in asked.pending.summary
    assert len((await cat.store.view(UID)).active()) == 2  # nothing until he says yes
    done = await approve(gw, asked)
    assert done.outcome is GatewayOutcome.EXECUTED and done.result["status"] == "done"
    view = await cat.store.view(UID)
    assert [p.id for p in view.active()] == [keep]
    assert view.pieces[other].merged_into == keep and view.pieces[other].state == "archived"
    kinds = [h.event.kind for h in await desk(cat).merge.history(UID, keep)]
    assert kinds == ["registered", "registered", "seen", "merged"]  # both, in time order


async def test_inv16_confirmed_separate_copies_stay_two(cat: Catalog) -> None:
    gw = gateway(cat)
    a, b = await _add(cat, NewPiece(type="vest"), NewPiece(type="vest"))
    sheet = await desk(cat).labels.sheet(UID)
    await desk(cat).labels.assign(UID, sheet[0].code, a)
    await desk(cat).labels.assign(UID, sheet[1].code, b)
    done = await approve(gw, await call(gw, "wardrobe_merge", keep=a, merge=b))
    assert done.result["status"] == "refused"  # two labelled copies are two pieces
    assert len((await cat.store.view(UID)).active()) == 2
    c, d = await _add(cat, NewPiece(type="sock"), NewPiece(type="sock"))
    asked = await call(gw, "wardrobe_merge", keep=c, merge=d)
    assert asked.pending is not None and await gw.gate.cancel(asked.pending.id)
    assert len((await cat.store.view(UID)).active()) == 4  # he said no: they stay two


async def test_a_merge_can_be_undone_from_recently_deleted_by_dropping_the_link(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    keep, other = await _add(cat, NewPiece(type="watch"), NewPiece(type="watch"))
    done = await approve(gw, await call(gw, "wardrobe_merge", keep=keep, merge=other))
    out = await cat.undo.restore(UID, done.result["undo_id"])
    assert out.status is RestoreStatus.RESTORED
    view = await cat.store.view(UID)
    assert view.pieces[other].merged_into is None and view.pieces[other].state == "review"
    assert {p.id for p in view.active()} == {keep, other}


# ---- INV-17 · an archived belt drops out of the counts; restoring reuses the id ----------------
async def test_inv17_archiving_a_belt_is_a_card_and_restoring_reuses_its_id_and_asks_its_condition(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    [belt] = await _add(cat, NewPiece(type="belt", label="Old belt"))
    done = await approve(gw, await call(gw, "wardrobe_retire", piece=belt, action="archive"))
    assert done.result["status"] == "done"
    assert desk(cat).counts.of(await cat.store.view(UID)).owned == 0
    found = await call(gw, "wardrobe_find", query="belt")
    assert found.result["found"] is False  # out of active pieces
    back = await approve(gw, await call(gw, "wardrobe_retire", piece=belt, action="restore"))
    assert back.result["piece"] == belt and back.result["question"]
    assert (await cat.store.view(UID)).pieces[belt].state == "review"
    cat.clock.advance(minutes=1)
    ok = await approve(
        gw, await call(gw, "wardrobe_retire", piece=belt, action="restore", condition="ready")
    )
    assert ok.result["status"] == "done"
    assert (await cat.store.view(UID)).pieces[belt].state == "ready"


async def test_h1_correct_refuses_the_card_only_kinds_so_an_archived_belt_stays_archived(
    cat: Catalog,
) -> None:
    from jarvis.wardrobe.catalog.store import CARD_ONLY, OWN_BUTTON

    assert {"registered", "archived", "restored", "merged", "corrected"} == CARD_ONLY
    gw = gateway(cat)
    [belt, sock, dup] = await _add(
        cat, NewPiece(type="belt"), NewPiece(type="sock"), NewPiece(type="sock")
    )
    cat.clock.advance(minutes=1)
    await approve(gw, await call(gw, "wardrobe_retire", piece=belt, action="archive"))
    cat.clock.advance(minutes=1)
    await desk(cat).merge.merge(UID, sock, dup)
    cat.clock.advance(minutes=1)
    dep = ev(sock, "deposited", cat.clock())

    async def fn(view: object, tx: object) -> Commit:
        return Commit(events=(dep,))

    await cat.store.transact(UID, fn)
    cat.clock.advance(minutes=1)
    fix = (await cat.store.correct(UID, sock, dep.id)).events[0]  # an ordinary event: voided
    cat.clock.advance(minutes=1)
    tries = [(belt, h.event.id) for h in await cat.store.history(UID, belt)]  # registered, archived
    tries += [(dup, h.event.id) for h in await cat.store.history(UID, dup)]  # registered, merged
    tries.append((sock, fix.id))  # a correction is undone by its own button, too
    for pid, eid in tries:
        with pytest.raises(Refused) as got:
            await cat.store.correct(UID, pid, eid)
        assert str(got.value) == OWN_BUTTON
    back = await approve(gw, await call(gw, "wardrobe_retire", piece=belt, action="restore"))
    assert back.result["status"] == "done"
    restored = [h.event.id for h in await cat.store.history(UID, belt)][-1]
    with pytest.raises(Refused):
        await cat.store.correct(UID, belt, restored)
    view = await cat.store.view(UID)
    assert view.pieces[belt].state == "review" and view.pieces[dup].merged_into == sock


async def test_approve_all_never_covers_merge_or_archive() -> None:
    assert "wardrobe_merge" in NO_BULK_TOOLS and "wardrobe_retire" in NO_BULK_TOOLS


# ---- remove: Recently deleted, in place, under a fixed title (D16) -----------------------------
async def test_remove_keeps_the_piece_in_recently_deleted_under_a_fixed_title(cat: Catalog) -> None:
    gw = gateway(cat)
    [shirt] = await _add(cat, NewPiece(type="shirt", label="Office shirt"))
    res = await call(gw, "wardrobe_remove", piece=shirt)
    assert res.outcome is GatewayOutcome.EXECUTED and res.result["kind"] == "wardrobe_item"
    [item] = await cat.undo.recent(UID)
    assert item.title == BIN_TITLE and set(item.snapshot) == {"ref", "ev"}
    assert item.snapshot["ref"] == shirt  # ids only: the event it made, never a word of his
    assert "Office" not in str(item.model_dump())  # the bin is Firestore, in clear
    assert desk(cat).counts.of(await cat.store.view(UID)).owned == 0
    out = await cat.undo.restore(UID, item.id)
    assert out.status is RestoreStatus.RESTORED
    view = await cat.store.view(UID)
    assert view.pieces[shirt].state == "review"  # away up to 30 days: a quick check first


async def test_h2_a_stale_bin_entry_never_purges_or_restores_a_piece_he_retired_since(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    [belt] = await _add(cat, NewPiece(type="belt", label="Brown belt"))
    cat.clock.advance(minutes=1)
    removed = await call(gw, "wardrobe_remove", piece=belt)
    [entry] = await cat.undo.recent(UID)
    assert entry.snapshot["ref"] == belt and entry.snapshot["ev"].startswith("we_")
    cat.clock.advance(minutes=1)  # back through the retire card, not the bin: the entry stays live
    back = await call(gw, "wardrobe_retire", piece=belt, action="restore", condition="ready")
    assert (await approve(gw, back)).result["status"] == "done"
    cat.clock.advance(minutes=1)  # then retired on purpose: INV-17 keeps the record
    await approve(gw, await call(gw, "wardrobe_retire", piece=belt, action="archive"))
    events = len(await cat.store.history(UID, belt))
    out = await cat.undo.restore(UID, removed.result["undo_id"])
    assert out.status is RestoreStatus.STILL_THERE  # never un-archived without the retire card
    assert await cat.undo.purge(UID, removed.result["undo_id"])  # day 30: the entry goes ...
    view = await cat.store.view(UID)
    assert view.pieces[belt].state == "archived" and view.pieces[belt].label == "Brown belt"
    assert len(await cat.store.history(UID, belt)) == events  # ... the record and history stay


async def test_a_purge_takes_the_record_its_log_and_its_photos(cat: Catalog) -> None:
    gw = gateway(cat)
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    await desk(cat).vault.save(UID, shirt, "front", jpeg())
    res = await call(gw, "wardrobe_remove", piece=shirt)
    assert await cat.undo.purge(UID, res.result["undo_id"])
    view = await cat.store.view(UID)
    assert shirt not in view.pieces
    leftover = [p for p in cat.docs._data if shirt in p]  # noqa: SLF001 - every stored path
    assert leftover == []
    assert await desk(cat).vault.count(UID) == 0


# ---- the tools' words, fences and trust (D10, D18) -----------------------------------------------
async def test_find_fences_his_label_and_a_private_piece_is_a_private_basic(cat: Catalog) -> None:
    gw = gateway(cat)
    await _add(
        cat, NewPiece(type="belt", label="Black belt"), NewPiece(type="vest", colour="black")
    )
    got = await call(gw, "wardrobe_find", query="black belt")
    [shown] = got.result["pieces"]
    assert FENCE_END.search(shown["label"]) and got.trusted  # typed: his own words vouch
    vest = await call(gw, "wardrobe_find", query="vest")
    [private] = vest.result["pieces"]
    assert private["words"] == "a private basic" and "label" not in private
    assert set(private) == {"id", "slot", "state", "words"}


async def test_a_spoken_label_never_vouches_and_one_from_outside_content_is_not_saved(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    with context_trust(untrusted=False, spoken=True):
        said = await call(gw, "wardrobe_add", pieces=[{"type": "belt", "label": "Brown belt"}])
    said = await approve(gw, said) if said.pending is not None else said
    got = await call(gw, "wardrobe_find", query="brown belt")
    assert got.result["found"] and not got.trusted  # voice: maybe misheard
    with context_trust(untrusted=True):
        asked = await call(gw, "wardrobe_add", pieces=[{"type": "cap", "label": "Ignore that"}])
    done = await approve(gw, asked)
    assert done.result["note"].startswith("Saved without the label")
    [cap] = [p for p in (await cat.store.view(UID)).active() if p.type == "cap"]
    assert cap.label == ""


async def test_never_in_permissions_refuses_every_wardrobe_tool(cat: Catalog) -> None:
    gw = gateway(cat, [PolicyRule(tool_pattern="wardrobe_*", effect=Effect.DENY)])
    for name, args in (
        ("wardrobe_find", {"query": "belt"}),
        ("wardrobe_add", {"pieces": [{"type": "belt"}]}),
        ("wardrobe_remove", {"piece": "wi_" + "0" * 12}),
    ):
        assert (await call(gw, name, **args)).outcome is GatewayOutcome.DENIED
    assert (await cat.store.view(UID)).pieces == {}


async def test_an_edit_card_shows_fixed_words_and_his_qr_number_never_his_label(
    cat: Catalog,
) -> None:
    gw = gateway(
        cat,
        [PolicyRule(tool_pattern="wardrobe_*", effect=Effect.ASK, risks=[ActionRisk.REVERSIBLE])],
    )
    [vest] = await _add(cat, NewPiece(type="vest", label="Lucky vest"))
    sheet = await desk(cat).labels.sheet(UID)
    await desk(cat).labels.assign(UID, sheet[16].code, vest)
    asked = await call(gw, "wardrobe_edit", piece=vest, colour="white")
    assert asked.pending is not None
    assert asked.pending.summary == "Change a private basic (No. 17)"


async def test_a_move_by_his_words_resolves_one_piece_or_names_none(cat: Catalog) -> None:
    gw = gateway(cat)
    tray = await desk(cat).places.add(UID, "Accessory tray")
    bag = await desk(cat).places.add(UID, "Travel bag", "travel")
    [watch] = await _add(cat, NewPiece(type="watch", place=tray.id))
    moved = await call(gw, "wardrobe_edit", query="watch", place="travel bag")
    assert moved.result["status"] == "done"
    assert (await cat.store.view(UID)).pieces[watch].place == bag.id
    await _add(cat, NewPiece(type="watch"))
    two = await call(gw, "wardrobe_edit", query="watch", place="accessory tray")
    assert two.result == {"status": "refused", "message": "Several pieces fit: say which one."}


async def test_marking_a_piece_private_deletes_its_photos_and_fingerprints_in_the_same_change(
    cat: Catalog,
) -> None:
    from r13_fakes_a import fp

    gw = gateway(cat)
    [tee] = await _add(cat, NewPiece(type="t_shirt"))
    await desk(cat).vault.save(UID, tee, "front", jpeg())
    await desk(cat).vault.prints.save(UID, tee, "front", "mnv2-int8-1", fp(1))
    await call(gw, "wardrobe_edit", piece=tee, private=True)
    piece = (await cat.store.view(UID)).pieces[tee]
    assert piece.private and piece.photos == () and piece.fp_model is None
    assert await desk(cat).vault.count(UID) == 0
    assert (await desk(cat).vault.prints.items(UID, "mnv2-int8-1")) == ()


async def test_a_conflicting_event_does_not_break_a_merge_of_a_piece_in_laundry(
    cat: Catalog,
) -> None:
    gw = gateway(cat)
    keep, other = await _add(cat, NewPiece(type="shirt"), NewPiece(type="shirt"))

    async def dep(view: object, tx: object) -> Commit:
        return Commit(events=(ev(other, "deposited", cat.clock()),))

    await cat.store.transact(UID, dep)
    done = await approve(gw, await call(gw, "wardrobe_merge", keep=keep, merge=other))
    assert done.result["status"] == "done"
    assert (await cat.store.view(UID)).pieces[other].state == "archived"
