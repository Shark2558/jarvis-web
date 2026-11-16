# tests/test_r13_a_photos.py -- R13 Part A (docs/plans/r13-wardrobe.md D9, D7; OPS-01's server
# half, INV-06): a photo is a clean JPEG of the right size, sealed, never of a private piece (from
# the record), one per view; fingerprints of one model only, never a private piece's; the
# "seen before?" reference rule keeps one patterned shirt's id across its views.
from __future__ import annotations

import base64
import json
import random
from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_a import Catalog, catalog, fp, jpeg

from jarvis.wardrobe.catalog.edits import Edit, NewPiece
from jarvis.wardrobe.catalog.matching import candidates, twins
from jarvis.wardrobe.catalog.photos import NOT_JPEG, PRIVATE, frame_size
from jarvis.wardrobe.ports import Refused


@pytest.fixture
def cat() -> Catalog:
    return catalog()


def desk(cat: Catalog) -> Any:
    return cat.store.desk  # type: ignore[attr-defined]


async def _add(cat: Catalog, *specs: NewPiece) -> list[str]:
    return list((await desk(cat).service.add(UID, specs)).ids)


def _stored(cat: Catalog) -> str:
    return json.dumps(cat.docs._data)  # noqa: SLF001 - every stored byte


# ---- the photo (D9) ---
async def test_a_saved_photo_is_cleaned_sealed_and_comes_back_without_its_exif(
    cat: Catalog,
) -> None:
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    photo, size = await desk(cat).vault.save(UID, shirt, "front", jpeg(512, 384))
    assert (await cat.store.view(UID)).pieces[shirt].photos == (photo,)
    back = await desk(cat).vault.get(UID, photo)
    assert back is not None and back.startswith(b"\xff\xd8") and len(back) == size
    assert b"GPS-LAT-LONG" not in back  # the APP1 segment is dropped
    assert frame_size(back) == (512, 384)
    raw = _stored(cat)
    assert "GPS" not in raw and base64.b64encode(back).decode()[:40] not in raw
    doc = await cat.docs.get(f"jarvis_wardrobe_photo/{UID}_{photo}")
    assert doc is not None and set(doc) == {
        "v", "kid", "owner", "piece", "view", "bytes", "blob", "updated_at"
    }  # fmt: skip


@pytest.mark.parametrize(
    ("data", "words"),
    [
        (jpeg(600, 400), "at most 512 pixels"),  # a 600-px photo is refused (OPS-01)
        (jpeg(400, 600), "at most 512 pixels"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 100, NOT_JPEG),
        (b"\xff\xd8\xff" + b"\x00" * 50, NOT_JPEG),
        (jpeg(extra=b"x" * 210 * 1024), "at most 200 KB"),
    ],
)
async def test_a_photo_that_isnt_a_clean_jpeg_of_the_right_size_is_refused(
    cat: Catalog, data: bytes, words: str
) -> None:
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    with pytest.raises(Refused) as got:
        await desk(cat).vault.save(UID, shirt, "front", data)
    assert words in str(got.value)
    assert (await cat.store.view(UID)).pieces[shirt].photos == ()


async def test_a_private_piece_never_gets_a_photo_or_a_fingerprint_from_its_record(
    cat: Catalog,
) -> None:
    [vest] = await _add(cat, NewPiece(type="vest"))  # private by default: from the record
    with pytest.raises(Refused) as got:
        await desk(cat).vault.save(UID, vest, "front", jpeg())
    assert str(got.value) == PRIVATE
    with pytest.raises(Refused):
        await desk(cat).vault.prints.save(UID, vest, "front", "mnv2-int8-1", fp(1))
    assert "wardrobe_photo" not in _stored(cat) and "wardrobe_fp" not in _stored(cat)


async def test_one_photo_a_view_and_a_retake_replaces_it(cat: Catalog) -> None:
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    first, _ = await desk(cat).vault.save(UID, shirt, "front", jpeg())
    back, _ = await desk(cat).vault.save(UID, shirt, "back", jpeg())
    again, _ = await desk(cat).vault.save(UID, shirt, "front", jpeg(256, 256))
    assert (await cat.store.view(UID)).pieces[shirt].photos == (back, again)
    assert await desk(cat).vault.get(UID, first) is None  # the old front is gone
    assert await desk(cat).vault.count(UID) == 2


async def test_deleting_one_photo_and_then_all_leaves_the_catalog_usable(cat: Catalog) -> None:
    shirt, tee = await _add(cat, NewPiece(type="shirt"), NewPiece(type="t_shirt"))
    one, _ = await desk(cat).vault.save(UID, shirt, "front", jpeg())
    await desk(cat).vault.save(UID, tee, "front", jpeg())
    await desk(cat).vault.prints.save(UID, tee, "front", "mnv2-int8-1", fp(2))
    assert await desk(cat).vault.delete(UID, one) is True
    assert await desk(cat).vault.delete(UID, one) is False
    assert await desk(cat).vault.delete_all(UID) == 1
    view = await cat.store.view(UID)
    assert all(p.photos == () and p.fp_model is None for p in view.pieces.values())
    assert "wardrobe_photo" not in _stored(cat) and "wardrobe_fp" not in _stored(cat)
    assert (await desk(cat).search.find(UID, "shirt")).best is not None  # e2e 7: still usable


# ---- fingerprints (D7) ---
async def test_fingerprints_are_sealed_listed_by_model_and_replaced_per_view(cat: Catalog) -> None:
    shirt, tee = await _add(cat, NewPiece(type="shirt"), NewPiece(type="t_shirt"))
    prints = desk(cat).vault.prints
    await prints.save(UID, shirt, "front", "mnv2-int8-1", fp(1))
    await prints.save(UID, shirt, "front", "mnv2-int8-1", fp(3))  # a new look: replaced
    await prints.save(UID, tee, "front", "mnv2-fp32-1", fp(4))
    got = await prints.items(UID, "mnv2-int8-1")
    assert [(e["p"], e["w"], e["v"]) for e in got] == [(shirt, "front", fp(3))]
    assert [e["p"] for e in await prints.items(UID, "mnv2-fp32-1")] == [tee]
    assert fp(3)[:40] not in _stored(cat)
    assert (await cat.store.view(UID)).pieces[shirt].fp_model == "mnv2-int8-1"


@pytest.mark.parametrize("bad", ["A" * 1708, "not base64!" * 155, fp(1)[:-4] + "===="])
async def test_a_fingerprint_that_is_not_1280_bytes_is_refused(cat: Catalog, bad: str) -> None:
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    with pytest.raises(Refused):
        await desk(cat).vault.prints.save(UID, shirt, "front", "mnv2-int8-1", bad[:1708])


async def test_fingerprints_past_one_shard_are_kept_and_dropped_per_piece(cat: Catalog) -> None:
    ids = await _add(cat, *(NewPiece(type="shirt") for _ in range(20)))
    for _ in range(11):
        ids += await _add(cat, *(NewPiece(type="shirt") for _ in range(20)))
    prints = desk(cat).vault.prints
    for n, pid in enumerate(ids[:205]):
        await prints.save(UID, pid, "front", "mnv2-int8-1", fp(n))
    assert await cat.docs.get(f"jarvis_wardrobe_fp/{UID}_1") is not None
    await desk(cat).service.edit(UID, ids[0], Edit(private=True))
    left = await prints.items(UID, "mnv2-int8-1")
    assert len(left) == 204 and ids[0] not in {e["p"] for e in left}


# ---- INV-06 · one patterned shirt keeps its id across front, back and folded fingerprints ---
def _noisy(base: list[int], rng: random.Random, spread: int) -> str:
    return base64.b64encode(
        bytes(max(0, min(255, b + rng.randint(-spread, spread))) for b in base)
    ).decode()


def test_inv06_one_patterned_shirt_keeps_its_id_across_its_views() -> None:
    rng = random.Random(6)
    shirt = [rng.randint(0, 255) for _ in range(1280)]
    saved = [
        {"p": "wi_" + "a" * 12, "v": _noisy(shirt, rng, 12)},  # front
        {"p": "wi_" + "a" * 12, "v": _noisy(shirt, rng, 12)},  # back
    ]
    for n in range(8):  # his other pieces
        other = [rng.randint(0, 255) for _ in range(1280)]
        saved.append({"p": f"wi_{n:012x}", "v": _noisy(other, rng, 4)})
    folded = _noisy(shirt, rng, 30)  # folded: further from both
    found = candidates(saved, folded)
    assert found[0].piece == "wi_" + "a" * 12 and found[0].band == "likely"
    assert len(found) <= 3 and not twins(found)


def test_two_identical_vests_are_twins_and_nothing_is_decided() -> None:
    rng = random.Random(7)
    vest = [rng.randint(0, 255) for _ in range(1280)]
    saved = [{"p": "wi_" + "b" * 12, "v": _noisy(vest, rng, 3)},
             {"p": "wi_" + "c" * 12, "v": _noisy(vest, rng, 3)}]  # fmt: skip
    saved += [{"p": f"wi_{n:012x}", "v": _noisy([rng.randint(0, 255) for _ in range(1280)], rng, 1)}
              for n in range(4)]  # fmt: skip
    found = candidates(saved, _noisy(vest, rng, 3))
    assert {c.piece for c in found[:2]} == {"wi_" + "b" * 12, "wi_" + "c" * 12} and twins(found)


def test_no_saved_fingerprint_means_no_candidate() -> None:
    assert candidates([], fp(1)) == ()


async def test_l9_merging_into_a_private_piece_drops_the_others_photos_and_fingerprints(
    cat: Catalog,
) -> None:
    vest, other = await _add(cat, NewPiece(type="vest"), NewPiece(type="vest", private=False))
    await desk(cat).vault.save(UID, other, "front", jpeg())
    await desk(cat).vault.prints.save(UID, other, "front", "mnv2-int8-1", fp(4))
    await desk(cat).merge.merge(UID, vest, other)  # one piece now, and it is private (D9)
    view = await cat.store.view(UID)
    assert view.pieces[other].photos == () and view.pieces[other].fp_model is None
    assert await desk(cat).vault.count(UID) == 0
    assert await desk(cat).vault.prints._read(cat.docs.get, UID) == []  # noqa: SLF001
    assert "wardrobe_photo/" not in _stored(cat)
