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
