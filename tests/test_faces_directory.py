# tests/test_faces_directory.py -- R3 D13: unknown is never named. resolve() names only for an
# enrolled, consented, not-deleting registry id at score >= 0.9; everything else is UNKNOWN.
from __future__ import annotations

import math

import pytest
from faces_fakes import OTHER, UID, add_adult, add_child, enrol, faces

from jarvis.faces.directory import Directory
from jarvis.faces.ports import UNKNOWN, FaceDirectory


async def test_an_enrolled_consented_person_is_named_with_their_marks() -> None:
    f = faces()
    p = await add_adult(f, vip=True)
    await enrol(f, p)
    got = await f.directory.resolve(UID, p.id, 0.93)
    assert (got.name, got.person, got.vip, got.child) == ("Anjali", p.id, True, False)
    assert isinstance(f.directory, FaceDirectory)


async def test_a_child_is_marked_a_child() -> None:
    f = faces()
    c = await add_child(f)
    await enrol(f, c)
    got = await f.directory.resolve(UID, c.id, 0.95)
    assert got.child is True and got.named


async def test_the_threshold_is_inclusive_and_0_89_is_unknown() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    assert (await f.directory.resolve(UID, p.id, 0.89)) is UNKNOWN
    assert (await f.directory.resolve(UID, p.id, 0.9)).named


@pytest.mark.parametrize("score", [None, True, math.nan, math.inf, -1.0, "0.99"])
async def test_a_missing_or_odd_score_is_unknown(score: object) -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    assert (await f.directory.resolve(UID, p.id, score)) is UNKNOWN  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ref", [None, "", "Anjali", "fp_xyz", "fp_3a9c12ab34cdee", "FP_3A9C12AB34CD", "fp_3a9c12ab34cd"]
)
async def test_no_sub_label_a_typed_name_or_an_unregistered_id_is_unknown(ref: object) -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    assert (await f.directory.resolve(UID, ref, 0.99)) is UNKNOWN  # type: ignore[arg-type]


async def test_consented_but_not_enrolled_is_unknown() -> None:
    f = faces()
    p = await add_adult(f)
    assert (await f.directory.resolve(UID, p.id, 0.99)) is UNKNOWN


async def test_a_deleting_person_is_unknown_at_once_and_stays_so() -> None:
    f = faces(online=False)
    p = await add_adult(f)
    await enrol(f, p)
    await f.svc.remove(UID, p.id)
    assert (await f.directory.resolve(UID, p.id, 0.99)) is UNKNOWN
    await f.svc.apply_pictures(UID, {p.id: 5})  # a stale heartbeat cannot revive the name
    assert (await f.directory.resolve(UID, p.id, 0.99)) is UNKNOWN


async def test_losing_every_picture_means_not_enrolled_any_more() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    await enrol(f, p, 0)
    assert (await f.directory.resolve(UID, p.id, 0.99)) is UNKNOWN


async def test_another_owners_person_is_unknown() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    assert (await f.directory.resolve(OTHER, p.id, 0.99)) is UNKNOWN


async def test_an_unreadable_registry_is_unknown_never_a_guess() -> None:
    f = faces()
    p = await add_adult(f)
    await enrol(f, p)
    f.docs._data["jarvis_faces/" + UID]["blob"] = "garbage"  # type: ignore[attr-defined]
    assert (await Directory(f.store).resolve(UID, p.id, 0.99)) is UNKNOWN
    assert (await f.directory.resolve("../x", p.id, 0.99)) is UNKNOWN


async def test_alert_words_never_name_a_child_or_an_unnamed_person() -> None:
    from jarvis.faces.directory import alert_words
    from jarvis.faces.ports import FAMILY_CHILD, RECOGNISED_PERSON, UNKNOWN_PERSON

    f = faces()
    a, k = await add_adult(f), await add_child(f)
    await enrol(f, a)
    await enrol(f, k)
    adult = await f.directory.resolve(UID, a.id, 0.95)
    kid = await f.directory.resolve(UID, k.id, 0.95)
    assert alert_words(adult, say_names=False) == RECOGNISED_PERSON
    assert alert_words(adult, say_names=True) == "Anjali"
    for on in (True, False):
        assert alert_words(kid, say_names=on) == FAMILY_CHILD
        assert alert_words(UNKNOWN, say_names=on) == UNKNOWN_PERSON
