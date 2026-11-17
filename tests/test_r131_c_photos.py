# tests/test_r131_c_photos.py -- R13.1 Part C: his photo (D12) and the photo of a garment he is
# thinking of buying (D22): JPEG only, the side from its SOF marker, the size, cleaned (EXIF and GPS
# dropped, never decoded), sealed with its own AAD, a plain owner; a garment is never his (no `wi_`
# id, no R13 write). Fixed clocks only. Written first and run red.
from __future__ import annotations

import struct
from datetime import timedelta

import pytest
from r131_fakes import NOW, RING, UID, FixedClock, jpeg

from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.seeme.garments import GarmentStore
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import PersonPhoto, Sealer, clean_jpeg
from jarvis.wardrobe.tryon import model as m

PREFIX = "jarvis_"
GPS = b"Exif\x00\x00GPS-r131-latitude-9.93"


def with_exif(data: bytes) -> bytes:
    """`data` with an APP1 (EXIF, a made-up GPS needle) after SOI."""
    app1 = b"\xff\xe1" + struct.pack(">H", len(GPS) + 2) + GPS
    return data[:2] + app1 + data[2:]


def _photo(docs: MemoryDocs | None = None, clock: FixedClock | None = None) -> PersonPhoto:
    return PersonPhoto(docs or MemoryDocs(), PREFIX, Sealer(RING), now=clock or FixedClock(NOW))


def _garments(docs: MemoryDocs | None = None, clock: FixedClock | None = None) -> GarmentStore:
    return GarmentStore(docs or MemoryDocs(), PREFIX, Sealer(RING), now=clock or FixedClock(NOW))


# ---- the checks every picture of his passes ------------------------------------------------------
def test_a_clean_jpeg_drops_exif_and_keeps_its_frame() -> None:
    raw = with_exif(jpeg(600, 1200, 16))
    clean = clean_jpeg(raw, max_kb=700)
    assert GPS not in clean and clean.startswith(b"\xff\xd8") and clean.endswith(b"\xff\xd9")


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, 422, "not_jpeg"),  # JPEG only
        (b"\xff\xd8\xff\xe0garbage", 422, "not_jpeg"),
        (jpeg(1569, 800), 422, "too_large"),  # the side from its SOF marker
        (jpeg(600, 1600), 422, "too_large"),
        (jpeg(600, 1200, 700 * 1024), 413, "too_large"),  # over 700 KB
    ],
)
def test_what_isnt_a_small_clean_jpeg_is_refused_in_words(
    data: bytes, status: int, code: str
) -> None:
    with pytest.raises(SeeMeRefused) as err:
        clean_jpeg(data, max_kb=700)
    assert (err.value.status, err.value.code) == (status, code) and err.value.words


def test_the_limit_is_his_setting() -> None:
    clean_jpeg(jpeg(600, 1200, 150 * 1024), max_kb=200)
    with pytest.raises(SeeMeRefused):
        clean_jpeg(jpeg(600, 1200, 150 * 1024), max_kb=100)


# ---- his photo (D12) -----------------------------------------------------------------------------
async def test_his_photo_is_sealed_with_its_own_aad_and_a_plain_owner() -> None:
    docs = MemoryDocs()
    store = _photo(docs)
    raw = jpeg(600, 1200, 64)
    clean = clean_jpeg(raw, max_kb=700)  # what is kept: the cleaned JPEG
    view = await store.save(UID, raw)
    assert view.kept and view.at == NOW and view.bytes == len(clean)
    doc = await docs.get(f"{PREFIX}tryon_person/{UID}")
    assert doc is not None and doc["owner"] == UID and "updated_at" in doc
    assert clean not in str(doc).encode() and set(doc) >= {"blob", "kid", "bytes", "at"}
    assert await store.get(UID) == clean
    moved = {**doc}
    await docs.write([Set(f"{PREFIX}tryon_person/other-owner", {**moved, "owner": "other-owner"})])
    assert await store.get("other-owner") is None  # the AAD names the owner: it won't open


async def test_a_new_photo_replaces_the_old_in_one_write() -> None:
    docs = MemoryDocs()
    store = _photo(docs)
    await store.save(UID, jpeg(600, 1200, 8))
    before = len(docs.log)
    new = jpeg(500, 1000, 8)
    await store.save(UID, new)
    assert len(docs.log) == before + 1 and await store.get(UID) == clean_jpeg(new, max_kb=700)


async def test_deleting_his_photo_takes_his_yes_with_it_in_one_write() -> None:
    docs = MemoryDocs()
    store = _photo(docs)
    await store.save(UID, jpeg(600, 1200))
    await docs.write([Set(f"{PREFIX}tryon_consent/{UID}", {"owner": UID, "blob": "x"})])
    sizes = len(docs.batch_sizes) + len(docs.tx_sizes)
    assert await store.delete(UID) is True
    assert len(docs.batch_sizes) + len(docs.tx_sizes) == sizes + 1  # one write
    assert await docs.get(f"{PREFIX}tryon_person/{UID}") is None
    assert await docs.get(f"{PREFIX}tryon_consent/{UID}") is None
    assert await store.delete(UID) is False and (await store.view(UID)).kept is False


async def test_a_photo_that_wont_open_reads_as_none_and_is_never_overwritten_silently() -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"{PREFIX}tryon_person/{UID}", {"owner": UID, "blob": "broken"})])
    assert await _photo(docs).get(UID) is None


# ---- a garment he is thinking of buying (D22) -------------------------------------------------
async def test_a_garment_photo_is_kept_under_a_tg_id_with_fixed_words() -> None:
    docs = MemoryDocs()
    store = _garments(docs)
    raw = with_exif(jpeg(600, 800, 32))
    g = await store.save(UID, "shirt", "navy", raw, keep_days=30)
    assert g.id.startswith("tg_") and len(g.id) == 15 and not g.id.startswith("wi_")
    assert g.words == "a new navy shirt, not in your wardrobe" and g.slot == "top"
    assert g.at == NOW and g.until == NOW + timedelta(days=30) and not g.kept
    stored = await store.get(UID, g.id)
    assert stored is not None and GPS not in stored  # cleaned like his photo
    doc = await docs.get(f"{PREFIX}tryon_garment/{UID}_{g.id}")
    assert doc is not None and doc["owner"] == UID and doc["type"] == "shirt"
    assert stored not in str(doc).encode()
    assert all(not op.path.startswith(f"{PREFIX}wardrobe") for op in docs.log)  # never his


async def test_the_list_holds_words_and_sizes_never_the_bytes() -> None:
    clock = FixedClock(NOW)
    store = _garments(clock=clock)
    await store.save(UID, "jeans", "light_blue", jpeg(600, 800), keep_days=30)
    clock.set(NOW + timedelta(minutes=1))
    await store.save(UID, "blazer", "charcoal", jpeg(600, 800), keep_days=30)
    listed = await store.listed(UID, keep_days=30, kept=set())
    assert [g.words for g in listed.garments] == [
        "new light blue jeans, not in your wardrobe",
        "a new charcoal blazer, not in your wardrobe",
    ]
    assert "blob" not in listed.model_dump_json()


async def test_the_21st_garment_photo_is_too_many() -> None:
    clock = FixedClock(NOW)
    store = _garments(clock=clock)
    for n in range(m.GARMENT_MAX):
        clock.set(NOW + timedelta(seconds=n))
        await store.save(UID, "shirt", "navy", jpeg(300, 300), keep_days=30)
    with pytest.raises(SeeMeRefused) as err:
        await store.save(UID, "shirt", "navy", jpeg(300, 300), keep_days=30)
    assert (err.value.status, err.value.code) == (409, "too_many")
    assert err.value.words == "You have 20 garment photos: delete one first."


@pytest.mark.parametrize(
    ("kind", "colour"),
    [("sneaker", "white"), ("shirt", "tartan"), ("watch", "grey"), ("", ""), ("shirt", "")],
)
async def test_only_a_garment_type_and_a_fixed_colour(kind: str, colour: str) -> None:
    with pytest.raises(SeeMeRefused) as err:
        await _garments().save(UID, kind, colour, jpeg(300, 300), keep_days=30)
    assert (err.value.status, err.value.code) == (422, "not_a_garment")


async def test_a_garment_shown_by_a_kept_picture_stays_and_its_delete_takes_only_it() -> None:
    docs = MemoryDocs()
    store = _garments(docs)
    a = await store.save(UID, "shirt", "navy", jpeg(300, 300), keep_days=30)
    b = await store.save(UID, "kurta", "maroon", jpeg(300, 300), keep_days=30)
    listed = await store.listed(UID, keep_days=30, kept={a.id})
    shown = {g.id: g for g in listed.garments}
    assert shown[a.id].until is None and shown[a.id].kept and shown[b.id].until is not None
    assert await store.delete(UID, a.id) is True and await store.delete(UID, a.id) is False
    assert await store.get(UID, a.id) is None and await store.get(UID, b.id) is not None
    assert await store.get(UID, "wi_000000000001") is None  # never a wardrobe id
    assert await store.get("other-owner", b.id) is None
