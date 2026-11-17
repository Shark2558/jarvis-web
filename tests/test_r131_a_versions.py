# tests/test_r131_a_versions.py -- R13.1 Part A, D4 (AVT-02's store half, AVT-03's versions): six
# whole-cm measurements in preview v2's ranges, a value outside refused in words, one he didn't
# type estimated from his height and shown "estimated"; a draft while he types, "Use these
# measurements" makes it current (the old current becomes the first earlier, five kept), "Keep
# the current" drops it; every BodyView carries `model.morph_weights` (the engine's one rule).
# Saved selections never change with a version. Fixed clock (`r131_fakes.NOW`).
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from r131_fakes import NOW

from jarvis.wardrobe.tryon import model as m
from jarvis.wardrobe.tryon import versions as v
from jarvis.wardrobe.tryon.store import KeptLook, Saved, SlotRec, TryonDoc


def _later(n: int) -> datetime:
    return NOW + timedelta(minutes=n)


def test_avt02_store_keeps_what_he_typed_and_estimates_the_rest_from_his_height() -> None:
    doc = v.draft(TryonDoc(), {"height": 178, "chest": 100}, NOW)
    d = doc.draft
    assert d is not None and doc.current is None  # a draft until he uses it
    assert d.typed == ("height", "chest") and d.height == 178 and d.chest == 100
    est = m.estimated(178)
    assert (d.shoulders, d.waist, d.hips, d.inseam) == (
        est["shoulders"], est["waist"], est["hips"], est["inseam"]
    )  # fmt: skip


def test_avt02_store_with_no_height_typed_estimates_from_the_samples() -> None:
    d = v.draft(TryonDoc(), {"waist": 90}, NOW).draft
    assert d is not None and d.typed == ("waist",) and d.height == m.SAMPLE["height"]
    assert d.waist == 90 and d.chest == m.SAMPLE["chest"]


def test_avt02_store_keeps_earlier_typed_values_and_reestimates_the_untyped_ones() -> None:
    doc = v.use(v.draft(TryonDoc(), {"height": 172, "waist": 90}, NOW))
    again = v.draft(doc, {"height": 186}, _later(1)).draft
    assert again is not None and again.typed == ("height", "waist")
    assert again.waist == 90  # still his
    assert again.chest == m.estimated(186)["chest"]  # follows the new height


@pytest.mark.parametrize(("measure", "bad"), [("height", 149), ("height", 196), ("waist", 61),
                                              ("inseam", 93), ("chest", 0)])  # fmt: skip
def test_avt02_store_refuses_a_value_outside_its_range_in_words(measure: str, bad: int) -> None:
    with pytest.raises(v.OutOfRange) as got:
        v.draft(TryonDoc(), {measure: bad}, NOW)
    assert str(got.value) == m.range_words(measure)  # type: ignore[arg-type]
    assert got.value.measure == measure


def test_avt02_store_refuses_nothing_typed_and_a_measure_it_doesnt_know() -> None:
    with pytest.raises(v.NothingTyped):
        v.draft(TryonDoc(), {}, NOW)
    with pytest.raises(v.NothingTyped):
        v.draft(TryonDoc(), {"height": None}, NOW)
    with pytest.raises(ValueError):
        v.draft(TryonDoc(), {"neck": 40}, NOW)


def test_avt02_store_use_makes_the_draft_current_and_keeps_five_earlier() -> None:
    doc = TryonDoc()
    for n in range(8):
        doc = v.use(v.draft(doc, {"height": 160 + n}, _later(n)))
    assert doc.current is not None and doc.current.height == 167 and doc.draft is None
    assert [b.height for b in doc.earlier] == [166, 165, 164, 163, 162]  # newest first, five


def test_avt02_store_keep_the_current_drops_the_draft_only() -> None:
    doc = v.use(v.draft(TryonDoc(), {"height": 172}, NOW))
    drafted = v.draft(doc, {"height": 178}, _later(1))
    kept = v.drop(drafted)
    assert kept.draft is None and kept.current == doc.current and kept.earlier == ()


def test_avt02_store_use_or_drop_with_no_draft_is_refused() -> None:
    with pytest.raises(v.NoDraft) as used:
        v.use(TryonDoc())
    assert str(used.value) == v.NO_DRAFT_USE
    with pytest.raises(v.NoDraft) as dropped:
        v.drop(TryonDoc())
    assert str(dropped.value) == v.NO_DRAFT_DROP


def test_avt03_a_new_version_never_touches_saved_selections_or_figure_choices() -> None:
    saved = Saved(id="tc_0000abcd", at=NOW, looks=(
        KeptLook(slots=(SlotRec(slot="top", piece="wi_000000000001"),)),
    ))  # fmt: skip
    doc = TryonDoc(saved=(saved,), assets={"wi_000000000001": {"template": "shirt"}})  # type: ignore[dict-item]
    after = v.use(v.draft(v.use(v.draft(doc, {"height": 172}, NOW)), {"height": 178}, NOW))
    assert after.saved == doc.saved and after.assets == doc.assets


def test_every_body_view_carries_the_engines_morph_weights_and_typed_fields() -> None:
    doc = v.draft(TryonDoc(), {"height": 178, "waist": 70}, NOW)
    assert doc.draft is not None
    view = v.body_view(doc.draft)
    assert view.weights == m.morph_weights(doc.draft.values())
    assert view.weights["waist"] == 0.0 and view.weights["waist_down"] > 0  # below the sample
    assert view.typed == ("height", "waist") and view.height == 178 and view.at == NOW
    shown = v.versions_view(v.use(doc))
    assert shown.current == view and shown.draft is None and shown.earlier == ()


def test_the_figure_words_say_estimated_or_no_figure_yet() -> None:
    assert v.figure_words(TryonDoc()) == m.NO_FIGURE
    assert v.figure_words(v.use(v.draft(TryonDoc(), {"height": 180}, NOW))) == m.ESTIMATED
