# tests/test_r131_fakes.py -- R13.1 I0 seam 15: the shared fakes the parts build on hold what they
# say (the pilot of owner question 11 with photos on the kurta and the striped shirt, a second
# watch, a fixed clock, JPEGs whose SOF marker gives their size, the photo vault behind R13's
# catalog).
from __future__ import annotations

from r131_fakes import (
    CROPS,
    NOW,
    PRIVATE,
    UID,
    FakePhotoVault,
    T,
    jpeg,
    sample_body,
    seeded,
    tryon_context,
)

from jarvis.wardrobe.catalog.photos import frame_size
from jarvis.wardrobe.tryon.ports import photo_vault


async def test_the_seeded_pilot_has_its_photos_a_second_watch_and_two_private_basics() -> None:
    store, clock = await seeded()
    view = await store.view(UID)
    assert clock() == NOW
    assert view.pieces[T.kurta].photos == ("wh_00000000a001", "wh_00000000a002")
    assert view.pieces[T.striped].pattern == "striped" and len(view.pieces[T.striped].photos) == 2
    assert view.pieces[T.watch2].type == "watch" and view.pieces[T.watch2].eligible
    assert all(view.pieces[p].private and not view.pieces[p].photos for p in PRIVATE)
    assert view.pieces[T.blazer].type == "blazer" and len(T.shoes) == 2


async def test_the_crops_read_their_size_and_the_vault_opens_only_his() -> None:
    assert frame_size(jpeg(512, 384)) == (512, 384)
    vault = FakePhotoVault()
    assert await vault.get(UID, "wh_00000000a001") == CROPS["wh_00000000a001"]
    assert await vault.get("someone-else", "wh_00000000a001") is None
    ctx = tryon_context()
    assert photo_vault(ctx) is not None and ctx.tryon() is None and ctx.now() == NOW


def test_a_sample_body_is_typed_only_where_said() -> None:
    body = sample_body(178)
    assert body.height == 178 and body.typed == ("height",) and body.at == NOW
