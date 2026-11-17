# tests/test_r131_seams.py -- R13.1 I0 seams (docs/plans/r13-1-try-on.md "The I0 seam list", 1-16):
# the version and the book's release name, two key purposes, the settings, the money helpers, the
# parts' contract (two new parts), R13.1's own types, the provider port, the wiring, the console's
# joins, the pixel and drawing rules, the engine contract, the deploy, the guide, the evals and the
# size guards. Each block was written before the code it pins and run red first.
from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

import jarvis
from jarvis import keyring
from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen.repo import Repo
from jarvis.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> int:
    return len(_text(path).splitlines())


# ---- 1 · the version and the book's release name -----------------------------------------------
def test_the_version_is_thirteen_point_one() -> None:
    assert jarvis.__version__ == "13.1.0"  # R13.1 I0 (D17); the persona stays p13.0


def test_the_real_repository_is_r13_1_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R13.1"
    assert plans.plan_paths(repo)[0] == "docs/plans/r13-1-try-on.md"
    assert "docs/plans/r13-wardrobe.md" in plans.plan_paths(repo)


def test_the_persona_stays_p13_0() -> None:
    from jarvis.core.prompts import PERSONA_VERSION

    assert PERSONA_VERSION == "p13.0"  # no new tool (D17)


# ---- 2 · two key purposes ------------------------------------------------------------------------
def test_two_key_purposes_make_twenty_six() -> None:
    assert keyring.PURPOSES[-2:] == ("tryon", "tryon_photos")
    assert keyring.PURPOSES[-4:-2] == ("wardrobe", "wardrobe_photos")
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 26
    ring = keyring.Keyring(bytes(range(9, 41)))
    blob = ring.cipher("tryon_photos").encrypt(b"x", aad="tryon/person/u/v1")
    with pytest.raises(Exception):  # noqa: B017 - each purpose is its own key
        ring.cipher("tryon").decrypt(blob, aad="tryon/person/u/v1")
    with pytest.raises(Exception):  # noqa: B017 - and R13's photos key is another
        ring.cipher("wardrobe_photos").decrypt(blob, aad="tryon/person/u/v1")
    assert ring.cipher("tryon_photos").decrypt(blob, aad="tryon/person/u/v1") == b"x"


# ---- 7 · settings --------------------------------------------------------------------------------
def test_the_r131_settings_have_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.tryon_enabled is True and s.tryon_pictures is False  # pictures: the deploy sets it
    assert (s.tryon_month_cap_inr, s.tryon_tax_pct) == (300, 18)
    assert (s.tryon_model, s.tryon_location) == ("gemini-3.1-flash-image", "us")
    assert s.tryon_model_retires == "2027-05-28"
    assert (s.tryon_keep_days, s.tryon_photo_max_kb) == (7, 700)
    assert s.tryon_cache is False  # the deploy sets it when Google refused to switch caching off


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("tryon_month_cap_inr", -1),
        ("tryon_month_cap_inr", 2001),
        ("tryon_tax_pct", -1),
        ("tryon_tax_pct", 29),
        ("tryon_model", "imagen-4"),
        ("tryon_model", "virtual-try-on-001"),  # not built (D19)
        ("tryon_location", "asia-south1"),
        ("tryon_model_retires", "28 May 2027"),
        ("tryon_model_retires", "2027-13-01"),
        ("tryon_keep_days", 0),
        ("tryon_keep_days", 31),
        ("tryon_photo_max_kb", 99),
        ("tryon_photo_max_kb", 741),  # a sealed 740 KiB still fits a 1 MiB document
    ],
)
def test_an_r131_setting_outside_its_range_is_refused(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


def test_the_settings_edges_are_accepted() -> None:
    s = Settings(_env_file=None, tryon_month_cap_inr=0, tryon_tax_pct=28, tryon_location="eu")
    assert (s.tryon_month_cap_inr, s.tryon_tax_pct, s.tryon_location) == (0, 28, "eu")
    s = Settings(_env_file=None, tryon_month_cap_inr=2000, tryon_model="gemini-nano-banana-2.1")
    assert s.tryon_month_cap_inr == 2000 and s.tryon_location == "us"
    assert Settings(_env_file=None, tryon_photo_max_kb=740).tryon_photo_max_kb == 740


def test_config_stays_under_its_guard() -> None:
    assert _lines(SRC / "config.py") <= 790


# ---- 8 · money: the try-on label, tax and the overall limit -------------------------------------
def test_try_on_has_its_own_usage_label() -> None:
    from jarvis.billing.service import LABELS

    assert LABELS == {"voice": "Voice", "tryon": "Try-on"}


@pytest.mark.parametrize(
    ("inr", "pct", "want"),
    [(7.22, 18, 8.52), (7.28, 18, 8.59), (0.0, 18, 0.0), (9.5, 0, 9.5), (100, 28, 128.0)],
)
def test_with_tax_adds_gst_to_the_paise(inr: float, pct: int, want: float) -> None:
    from jarvis.billing.spend import with_tax

    assert math.isclose(with_tax(inr, pct), want, abs_tol=1e-9)


@pytest.mark.parametrize(("inr", "pct"), [(-1.0, 18), (1.0, -1), (1.0, 29), (math.nan, 18)])
def test_with_tax_refuses_what_is_not_money(inr: float, pct: int) -> None:
    from jarvis.billing.spend import with_tax

    with pytest.raises(ValueError):
        with_tax(inr, pct)
