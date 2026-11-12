# tests/test_r11_1_i1_photos.py -- R11.1 I1: Part C's photo import joined to the app
# (INTEGRATION-C 3.3, 3.4): the Photos service carries the owner's import limits from the first
# call, and the home kit's version note names the step that updates it.
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jarvis.api.r4_wiring import wire_photos
from jarvis.config import Settings
from jarvis.photos.models import ImportLimits
from jarvis.storage.docs import MemoryDocs

ROOT = Path(__file__).resolve().parents[1]


def test_the_photos_service_has_his_import_limits_from_the_first_call(settings: Settings) -> None:
    s = settings.model_copy(
        update={"photos_enabled": True, "photos_max_picked": 500, "photos_import_batch": 20}
    )
    app = SimpleNamespace(
        state=SimpleNamespace(google=object(), faces=object(), home_client=object())
    )
    svc = wire_photos(app, s, MemoryDocs())  # type: ignore[arg-type]
    assert svc is not None and svc.limits == ImportLimits(500, 20)


def test_the_old_kit_note_names_the_update_step() -> None:
    js = (ROOT / "src/jarvis/api/static/console-home.js").read_text(encoding="utf-8")
    assert "setup-windows.ps1 -Update" in js


# ---- INTEGRATION-C 3.4: a delete the home laptop finishes later says so in plain words --------
async def test_a_delete_that_waits_for_the_laptop_says_pending_in_plain_words() -> None:
    from test_privacy_service import UID, world

    from jarvis.facegroups.privacy import PENDING_NOTE, FaceGroupsPrivacy

    assert FaceGroupsPrivacy(lambda: None).pending_note() == PENDING_NOTE
    assert PENDING_NOTE == "Pending: it finishes when your home laptop is back on."
    w = await world()
    w.simple.noop_delete = True  # the rows are still there after the delete
    w.simple.pending_note = lambda: PENDING_NOTE  # type: ignore[attr-defined]
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.remaining == 1 and out.pending == PENDING_NOTE


async def test_a_source_without_a_note_or_with_nothing_left_has_no_pending_words() -> None:
    from test_privacy_service import UID, world

    w = await world()
    w.simple.noop_delete = True
    left = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert left.remaining == 1 and left.pending == ""  # the dashboard's generic words stay
    w = await world()
    w.simple.pending_note = lambda: "Pending: later."  # type: ignore[attr-defined]
    done = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert done.remaining == 0 and done.pending == ""  # nothing left: nothing is pending


async def test_a_note_that_breaks_or_is_not_a_short_line_is_left_out() -> None:
    from test_privacy_service import UID, world

    w = await world()
    w.simple.noop_delete = True

    def broken() -> str:
        raise RuntimeError("laptop said: secret")

    w.simple.pending_note = broken  # type: ignore[attr-defined]
    out = await w.svc.delete(
        UID, "places", rev=await w.rev("places"), confirm=None, proof=None, fresh_left_s=None
    )
    assert out.pending == "" and out.remaining == 1


def test_the_dashboard_shows_the_pending_words_before_the_generic_ones() -> None:
    js = (ROOT / "src/jarvis/api/static/console-privacy.js").read_text(encoding="utf-8")
    assert "typeof out.pending === 'string' && out.pending" in js
    assert js.index("out.pending") < js.index("still there. Try again in a moment.")
