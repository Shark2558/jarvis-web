# tests/test_r131_seams.py -- R13.1 I0 seams (docs/plans/r13-1-try-on.md "The I0 seam list", 1-16):
# the version and the book's release name, two key purposes, the settings, the money helpers, the
# parts' contract (two new parts), R13.1's own types, the provider port, the wiring, the console's
# joins, the pixel and drawing rules, the engine contract, the deploy, the guide, the evals and the
# size guards. Each block was written before the code it pins and run red first.
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

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
    assert jarvis.__version__ == "5.2.0"  # R5.2 (18.0.0 at R18, 13.1.0 at R13.1); persona p13.0


def test_the_real_repository_is_r13_1_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R5.2"  # R18 at R18, R6.4 (R6.3 at R6.3 I0)
    assert plans.plan_paths(repo)[0] == "docs/plans/r5-2-voice.md"
    assert "docs/plans/r13-wardrobe.md" in plans.plan_paths(repo)


def test_the_persona_stays_p13_0() -> None:
    from jarvis.core.prompts import PERSONA_VERSION

    assert PERSONA_VERSION == "p13.0"  # no new tool (D17)


# ---- 2 · two key purposes ------------------------------------------------------------------------
def test_two_key_purposes_make_twenty_six() -> None:
    assert keyring.PURPOSES[-3:-1] == ("tryon", "tryon_photos")  # R18 appended "calls"
    assert keyring.PURPOSES[-5:-3] == ("wardrobe", "wardrobe_photos")
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 27
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
    assert (s.tryon_keep_days, s.tryon_photo_max_kb) == (30, 700)  # owner question 3: 30 days
    # I1 (INTEGRATION-C 6.2, review C-1): fail toward disclosure. Unless the deploy proved Google's
    # cache off (it passes JARVIS_TRYON_CACHE explicitly), the consent says it may be kept
    assert s.tryon_cache is True
    # I1 (INTEGRATION-C 10.4 b, review C-1 finding 6): ONE end date, the model's own
    assert "tryon_model_retires" not in Settings.model_fields


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
    # R18 +2: the import of its settings' base class (`config_calls.py`, where R18's keys live);
    # R5.2 +1: `config_voice.LocalSpeechConfig`'s import
    assert _lines(SRC / "config.py") <= 792


# ---- 8 · money: the try-on label, tax and the overall limit -------------------------------------
def test_try_on_has_its_own_usage_label() -> None:
    from jarvis.billing.service import LABELS

    assert LABELS == {"voice": "Voice", "tryon": "Try-on", "book": "Book writer"}  # + R6.3 I0


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


# ---- 3 · the contract: two new parts ------------------------------------------------------------
def test_the_two_new_parts_and_what_each_owns() -> None:
    from dataclasses import fields

    from jarvis.wardrobe import ports

    assert ports.PARTS == ("catalog", "laundry", "styling", "phone", "tryon", "seeme")
    assert ports.TOOL_FAMILIES["tryon"] == ports.TOOL_FAMILIES["seeme"] == ()  # no new tool
    assert not any(ports.TOOL_OWNER[t] in ("tryon", "seeme") for t in ports.TOOL_OWNER)
    assert ports.ROUTE_PREFIX["tryon"] == ("/v1/tryon",)
    assert ports.ROUTE_PREFIX["seeme"] == ("/v1/seeme",)
    assert set(ports.ROUTE_PREFIX) == set(ports.COLLECTIONS) == set(ports.PARTS)
    assert ports.COLLECTIONS["tryon"] == ("tryon",)
    assert ports.COLLECTIONS["seeme"] == (
        "tryon_person", "tryon_consent", "tryon_picture", "tryon_spend", "tryon_garment",
    )  # fmt: skip
    assert ports.JOB_OWNER["seeme_daily"] == "seeme" and "seeme_daily" not in ports.CLOCK_JOB_NAMES
    assert ports.R13_JOB_NAMES[-1] == "seeme_daily"
    assert ports.SERVICE_OWNER["tryon_looks"] == "tryon" and ports.SERVICE_OWNER["seeme"] == "seeme"
    assert ports.NO_DATA_PARTS == {"tryon", "seeme"}
    assert ports.PRIVACY_OWNER == {
        "tryon_figure": "tryon", "tryon_photo": "seeme", "tryon_pictures": "seeme",
        "tryon_spend": "seeme", "tryon_all": "tryon", "tryon_device": "tryon",
    }  # fmt: skip
    ctx_fields = {f.name: f for f in fields(ports.WardrobeContext)}
    assert "tryon" in ctx_fields and ctx_fields["tryon"].default() is None  # type: ignore[misc]
    assert "get" in dir(ports.PhotoVault)  # a crop opened for C's request (seam 3)


# ---- 4 · R13.1's own types (wardrobe/tryon/model.py) --------------------------------------------
def test_the_measurements_ranges_and_sample_are_preview_v2s() -> None:
    from jarvis.wardrobe.tryon import model as m

    assert m.MEASURES == ("height", "shoulders", "chest", "waist", "hips", "inseam")
    assert dict(m.RANGES) == {
        "height": (150, 195), "shoulders": (36, 54), "chest": (76, 124), "waist": (62, 120),
        "hips": (78, 126), "inseam": (66, 92),
    }  # fmt: skip
    assert dict(m.SAMPLE) == m.estimated(172)  # the sample is its own estimate
    assert m.range_words("height") == "The figure can be 150 to 195 cm tall"
    tall = m.estimated(195)
    assert tall["height"] == 195 and all(m.in_range(k, v) for k, v in tall.items())
    assert not m.in_range("waist", 61) and not m.in_range("waist", True)  # type: ignore[arg-type]


def test_a_body_version_refuses_a_value_outside_its_range_in_words() -> None:
    from datetime import UTC, datetime

    from jarvis.wardrobe.tryon import model as m

    at = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
    body = m.Body(**m.estimated(178), typed=("height",), at=at)
    assert body.values()["height"] == 178
    with pytest.raises(ValidationError, match="150 to 195 cm tall"):
        m.Body(**{**m.estimated(178), "height": 196}, at=at)
    with pytest.raises(ValidationError):
        m.Body(**m.estimated(178), typed=("height", "height"), at=at)


def test_the_template_table_is_d5s_and_every_type_is_real() -> None:
    from jarvis.wardrobe.model import TYPES
    from jarvis.wardrobe.tryon import model as m

    every_type = {t for types in TYPES.values() for t in types}
    assert set(m.TEMPLATE_OF) <= every_type
    want = {
        "shirt": "shirt", "t_shirt": "tee", "polo": "tee", "top": "tee", "kurta": "kurta",
        "trousers": "trousers", "chinos": "trousers", "jeans": "trousers", "joggers": "trousers",
        "pyjama": "trousers", "shorts": "shorts", "mundu": "wrap", "dhoti": "wrap",
        "blazer": "jacket", "jacket": "jacket", "coat": "jacket", "hoodie": "jacket",
        "sweater": "jacket", "rainwear": "jacket", "festive_layer": "jacket",
        "dress_shoe": "shoe", "boot": "shoe", "sneaker": "shoe", "sandal": "sandal",
        "slipper": "sandal", "belt": "belt", "watch": "watch", "sock": "socks",
    }  # fmt: skip
    assert dict(m.TEMPLATE_OF) == want
    for card in ("tie", "cap", "scarf", "jewellery", "bag", "eyewear", "gym", "unknown", "vest"):
        assert m.template_of(card) is None, card  # an image card only (private: covered)
    assert m.VARIANTS["jacket"] == ("open", "closed") and m.VARIANTS["shirt"][0] == "tucked"
    assert m.GARMENTS == {"shirt", "tee", "kurta", "trousers", "shorts", "wrap", "jacket"}
    assert set(m.TEMPLATE_SLOT) == set(m.TEMPLATES)
    assert m.templates_for("top") == ("shirt", "tee", "kurta")
    assert m.useful_views("kurta") == ("front", "back") and m.useful_views("trousers") == ("front",)
    assert m.useful_views("tie") == ()


def test_the_palette_has_every_fixed_colour_and_no_colour_is_mid_grey() -> None:
    from jarvis.wardrobe.model import COLOURS
    from jarvis.wardrobe.tryon import model as m

    assert set(m.PALETTE) == set(COLOURS) and len(m.PALETTE) == 19
    assert all(len(v) == 3 and all(0 <= c <= 255 for c in v) for v in m.PALETTE.values())
    assert m.rgb_of(None) == m.rgb_of("tartan") == (128, 128, 128)


def test_the_words_and_ids() -> None:
    import re

    from jarvis.wardrobe.tryon import model as m

    assert m.GENERATED == "Generated 2D style preview — not a photo; the fit is not exact"
    assert m.COVERED == "Base layer (covered)" and m.DRAFT_WORDS["in_laundry"] == (
        "Draft: in the laundry"
    )
    assert m.reserved_words("your 18:00 event") == "Draft: reserved for your 18:00 event"
    assert set(m.DRAFT_WORDS) | {"ready"} == {
        "ready", "in_use", "in_laundry", "washing", "drying", "needs_prep", "with_provider",
        "needs_repair", "review", "archived",
    }  # fmt: skip
    assert re.fullmatch(m.PICTURE_ID, m.new_picture_id())
    assert re.fullmatch(m.SAVED_ID, m.new_saved_id())
    assert re.fullmatch(m.REQUEST_ID, "tq_" + "0123456789abcdef")
    assert m.aad_person("u") == "tryon/person/u/v1"
    assert m.aad_picture("u", "tp_0123456789ab") == "tryon/picture/u/tp_0123456789ab/v1"
    assert (m.PURPOSE, m.PHOTO_PURPOSE) == keyring.PURPOSES[-3:-1]
    assert re.fullmatch(m.GARMENT_ID, m.new_garment_id()) and m.GARMENT == "tryon_garment"
    assert m.aad_garment("u", "tg_0123456789ab") == "tryon/garment/u/tg_0123456789ab/v1"


def test_a_new_garment_is_one_of_the_sendable_types_and_its_words_say_it_isnt_his() -> None:
    # D22 (the owner, 17 Nov 2026): See it on me is for a garment he is thinking of BUYING
    from jarvis.wardrobe.tryon import model as m

    assert set(m.NEW_TYPES) == {t for t, tpl in m.TEMPLATE_OF.items() if tpl in m.GARMENTS}
    assert "shirt" in m.NEW_TYPES and "kurta" in m.NEW_TYPES and "blazer" in m.NEW_TYPES
    assert not {"sneaker", "belt", "watch", "sock"} & set(m.NEW_TYPES)  # never sent
    assert m.new_garment_words("navy", "shirt") == "a new navy shirt, not in your wardrobe"
    assert m.new_garment_words("", "t_shirt") == "a new t shirt, not in your wardrobe"
    assert (
        m.new_garment_words("light_blue", "jeans") == "new light blue jeans, not in your wardrobe"
    )
    assert (m.GARMENT_MAX, m.PAIR_MAX) == (20, 2) and m.PAIR_MAX + 1 <= 3  # MAX_GARMENTS


# ---- 4 · the HTTP contract (wardrobe/tryon/http.py) ---------------------------------------------
PLANNED_ROUTES = {
    ("GET", "/v1/tryon"), ("PUT", "/v1/tryon/body"), ("POST", "/v1/tryon/body/use"),
    ("DELETE", "/v1/tryon/body/draft"), ("GET", "/v1/tryon/look"),
    ("PUT", "/v1/tryon/assets/{piece}"), ("POST", "/v1/tryon/confirm"),
    ("GET", "/v1/tryon/saved"), ("POST", "/v1/tryon/saved"), ("GET", "/v1/tryon/saved/{id}"),
    ("DELETE", "/v1/tryon/saved/{id}"), ("GET", "/v1/seeme"), ("POST", "/v1/seeme/photo"),
    ("GET", "/v1/seeme/photo"), ("DELETE", "/v1/seeme/photo"), ("POST", "/v1/seeme/consent"),
    ("GET", "/v1/seeme/estimate"), ("POST", "/v1/seeme/pictures"),
    ("GET", "/v1/seeme/pictures/{id}"), ("POST", "/v1/seeme/pictures/{id}/keep"),
    ("DELETE", "/v1/seeme/pictures/{id}"), ("PUT", "/v1/seeme/settings"),
    # D22: the photo of a garment he is thinking of buying, and his own pieces to pair with it
    ("POST", "/v1/seeme/garments"), ("GET", "/v1/seeme/garments"),
    ("GET", "/v1/seeme/garments/{id}"), ("DELETE", "/v1/seeme/garments/{id}"),
    ("GET", "/v1/seeme/pair"),
}  # fmt: skip
CONSOLE_ONLY = {
    ("POST", "/v1/seeme/photo"), ("GET", "/v1/seeme/photo"), ("DELETE", "/v1/seeme/photo"),
    ("POST", "/v1/seeme/consent"), ("POST", "/v1/seeme/pictures"),
    ("GET", "/v1/seeme/pictures/{id}"), ("POST", "/v1/seeme/pictures/{id}/keep"),
    ("DELETE", "/v1/seeme/pictures/{id}"), ("PUT", "/v1/seeme/settings"),
    ("POST", "/v1/seeme/garments"), ("GET", "/v1/seeme/garments/{id}"),
    ("DELETE", "/v1/seeme/garments/{id}"),
}  # fmt: skip


def test_every_planned_route_has_its_models_under_its_parts_prefix() -> None:
    from jarvis.wardrobe.ports import ROUTE_PREFIX
    from jarvis.wardrobe.tryon import http

    assert {(m, p) for m, p, *_ in http.ROUTES} == PLANNED_ROUTES
    assert {(m, p) for m, p, *_, console in http.ROUTES if console} == CONSOLE_ONLY
    assert "/v1/tryon/erase" not in {p for _, p, *_ in http.ROUTES}  # OPS-05 is a Privacy delete
    for _, path, part, req, reply, errors, _ in http.ROUTES:
        assert any(path.startswith(x) for x in ROUTE_PREFIX[part]), path  # type: ignore[index]
        for model in (req, reply):
            if isinstance(model, type):
                assert model.model_config.get("extra") == "forbid", (path, model)
        assert {401, 429} <= set(errors), path


def test_a_refusal_has_a_code_and_words() -> None:
    from jarvis.wardrobe.tryon.http import SEEME_ERRORS, Refusal

    r = Refusal(error="price_changed", detail="The price changed: look again.")
    assert r.model_dump() == {"error": "price_changed", "detail": "The price changed: look again."}
    assert {"cap_reached", "busy", "consent_needed", "private_piece", "blocked"} <= set(
        SEEME_ERRORS
    )
    with pytest.raises(ValidationError):
        Refusal(error="Not A Code", detail="x")


def test_a_picture_request_bounds_what_the_console_sends() -> None:
    from jarvis.wardrobe.tryon.http import ConfirmIn, ConsentIn, PictureIn

    one = {
        "garment": "tg_" + "1" * 12, "pieces": ["wi_" + "1" * 12], "inr_shown": 8.9,
        "request_id": "tq_" + "a" * 16,
    }  # fmt: skip
    assert PictureIn.model_validate(one).confirm_cost is False  # never on by default
    assert PictureIn.model_validate({**one, "pieces": []}).pieces == ()  # the new garment alone
    for bad in (
        {k: v for k, v in one.items() if k != "garment"},  # D22: always a new garment
        {**one, "garment": "wi_" + "1" * 12},  # a wardrobe piece is never "the new garment"
        {**one, "pieces": ["wi_" + "1" * 12] * 3},  # 1 new + at most 2 of his: MAX_GARMENTS 3
        {**one, "request_id": "tq_short"},
        {**one, "confirm_cost": "yes"},
        {**one, "photo": "...."},
        {**one, "plan": "op_00000001"},  # not a plan's look any more (D22)
        {**one, "url": "https://shop.example/shirt"},  # JARVIS never fetches an address
    ):
        with pytest.raises(ValidationError):
            PictureIn.model_validate(bad)
    with pytest.raises(ValidationError):
        ConsentIn.model_validate({"typed": "YES" * 10, "template_version": "c1"})
    with pytest.raises(ValidationError):
        ConfirmIn.model_validate({"plan": "op_00000001", "slots": []})


def test_a_new_garment_is_described_in_fixed_words_and_never_as_his() -> None:
    from jarvis.wardrobe.tryon import http

    g = {"id": "tg_" + "2" * 12, "type": "shirt", "colour": "navy", "at": "2026-11-17T09:00+05:30",
         "words": "a new navy shirt, not in your wardrobe"}  # fmt: skip
    GarmentIn, GarmentList, GarmentView = http.GarmentIn, http.GarmentList, http.GarmentView
    Estimate, NewGarment, Pairing, PictureView = (
        http.Estimate, http.NewGarment, http.Pairing, http.PictureView,
    )  # fmt: skip
    view = GarmentView.model_validate({**g, "bytes": 120_000, "until": "2026-12-17T09:00:00+05:30"})
    assert view.slot == "top" and not view.kept
    assert GarmentIn(type="kurta", colour="maroon").type == "kurta"
    for bad in ({"type": "sneaker", "colour": "white"}, {"type": "shirt", "colour": "teal-ish"},
                {"type": "shirt", "colour": "navy", "label": "Zara linen"}):  # fmt: skip
        with pytest.raises(ValidationError):
            GarmentIn.model_validate(bad)
    with pytest.raises(ValidationError):
        GarmentView.model_validate({**g, "type": "watch"})
    assert GarmentList(garments=(view,)).garments[0].id == g["id"]
    new = NewGarment(id=g["id"], words=g["words"])
    pic = PictureView.model_validate(
        {"id": "tp_" + "3" * 12, "made_at": g["at"], "garment": new.model_dump()}
    )
    assert pic.garment.words.endswith("not in your wardrobe") and "plan" not in pic.model_dump()
    assert Estimate(typical_inr=8.9, hold_inr=11.2, tax_pct=18, garment=new).garment == new
    pair = Pairing(
        garment=g["id"], pieces=({"piece": "wi_" + "4" * 12, "words": "charcoal trousers"},)
    )
    assert len(pair.pieces) == 1 and pair.words == ""
    with pytest.raises(ValidationError):
        Pairing(garment=g["id"], pieces=({"piece": "wi_" + "4" * 12, "words": "x"},) * 3)


def test_a_private_slot_carries_no_colour_photo_or_template_by_default() -> None:
    from jarvis.wardrobe.tryon.http import LookSlot

    covered = LookSlot(slot="base", private=True, words="Base layer (covered)")
    assert covered.rgb is None and covered.photo is None and covered.template is None
    assert covered.options == () and covered.piece is None


# ---- 9 · the console's joins (D1, D12, M7, M10) --------------------------------------------------
import re  # noqa: E402

TRYON_JS = (
    "console-tryon.js", "console-tryon-list.js", "console-tryon-me.js", "console-tryon-photo.js",
    "console-tryon-3d.js", "console-tryon-glb.js", "console-tryon-cloth.js",
    "console-tryon-card.js", "console-tryon-form.js",
)  # fmt: skip
D_JS = (
    "console-tryon.js", "console-tryon-list.js", "console-tryon-me.js", "console-tryon-card.js",
    "console-tryon-form.js",
)  # fmt: skip
B_JS = ("console-tryon-3d.js", "console-tryon-glb.js", "console-tryon-cloth.js")
LIMITS_JS = {
    "console-tryon.js": 600, "console-tryon-list.js": 300, "console-tryon-me.js": 400,
    "console-tryon-photo.js": 300, "console-tryon-3d.js": 600, "console-tryon-glb.js": 200,
    "console-tryon-cloth.js": 300, "console-tryon-card.js": 150,
    "console-tryon-form.js": 150,  # I1's split of console-tryon.js (review D-1 L12)
}  # fmt: skip


def _code(path: Path) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", _text(path), flags=re.S)  # comments say the rules


def test_console_html_is_unchanged_and_the_dock_stays_22() -> None:
    import hashlib

    got = hashlib.sha256((STATIC / "console.html").read_bytes()).hexdigest()
    # R18 E: + the Calls panel and its tab; R5.2: V4's and V5's script tags on existing lines
    assert got == "6bf7eb0ad6bc821cc6c36fd1392b131ffb7183ebb89268d9d0d88cf22e64d668"
    assert _lines(STATIC / "console.html") == 782


def test_the_new_files_are_served_and_none_is_in_the_page() -> None:
    from jarvis.api.console import APP_ASSETS

    for name in (*TRYON_JS, "console-tryon.css"):
        assert name in APP_ASSETS and (STATIC / name).is_file(), name
        assert name not in _text(STATIC / "console.html"), name
    assert "'/static/console-tryon.css'" in _text(STATIC / "console-r7.js")


def test_the_wardrobe_tab_mounts_try_it_on_once_after_the_plans() -> None:
    js = _text(STATIC / "console-helpers-wardrobe.js")
    assert "'review', 'plans', 'tryon', 'laundry', 'pieces', 'labels', 'settings'" in js
    mount = js[js.index("function mount(host)") :]
    assert "import('./console-tryon.js')" in mount and "m.mount(UI.secs.tryon, ctx())" in mount
    draw = js[js.index("function draw()") : js.index("function down(")]
    assert "tryon" not in draw  # never rebuilt by draw() (L7)
    assert "new CustomEvent('jarvis:wardrobe-fresh')" in js  # fresh readiness reaches it (D1)
    assert "btn('Show in 3D', () => tryOn(p.id))" in js  # free, on every plan
    assert "btn('See it on me'" not in js and "seeOn" not in js  # D22: for a garment to buy only
    assert "'jarvis:tryon-open'" in js and _text(STATIC / "console-helpers-wardrobe.js").isascii()


def test_a_tryon_reply_card_opens_the_look_by_itself_without_touching_the_page() -> None:
    # row 388 (D21): ChatResponse.cards -> console-media.js cards() -> window.JarvisTryOnCard
    # (console-tryon-card.js, loaded at start by console-r7.js) -> console-tryon.js inline(), lazily
    media = _code(STATIC / "console-media.js")
    hook = "const tryon = window.JarvisTryOnCard;"
    assert media.count(hook) == 1 and "tryon.cards(row, list)" in media
    assert media.index(hook) < media.index("const wrap = mk('div', 'mcards');")  # before the media
    assert "'tryon'" not in media  # console-media.js never draws the kind itself
    assert "import('./console-tryon-card.js')" in _code(STATIC / "console-r7.js")
    card = _code(STATIC / "console-tryon-card.js")
    assert "window.JarvisTryOnCard = Object.freeze({ cards, garment })" in card
    assert "import('./console-tryon.js')" in card and "'tryon'" in card
    assert "fetch(" not in card and "XMLHttpRequest" not in card  # it reads only the card
    assert "export function inline(el, card)" in _code(STATIC / "console-tryon.js")


def test_a_shared_picture_can_go_to_see_it_on_me_and_that_press_sends_nothing() -> None:
    # D22: "uploaded or shared into the app": the share tray hands the file to Try it on
    share = _code(STATIC / "console-r7-share.js")
    assert "const T = window.JarvisTryOnCard;" in share
    assert "await T.garment(await fileOf(it)); await done(it);" in share
    assert "seeme: 'See it on me (a garment to buy)'" in share
    card = _code(STATIC / "console-tryon-card.js")
    assert "async function garment(file)" in card and "m.garment(file)" in card
    assert "export function garment(file)" in _code(STATIC / "console-tryon.js")


def test_the_door_sends_his_photo_and_reads_pictures_back() -> None:
    code = _code(STATIC / "console-r7-send.js")
    assert "wardrobe, tag, thumb, drop, person, garment, picture, garmentPhoto, myPhoto," in code
    assert "postPicture(path, blob, { maxKb: Number(kb), jpeg: true })" in code
    assert "jpegTo('/v1/seeme/photo', blob, (meta || {}).maxKb)" in code
    assert "readBack(/^tp_[0-9a-f]{12}$/, '/v1/seeme/pictures/')" in code  # a picture's id only
    assert "dataUrl(path + id)" in code and "dataUrl('/v1/seeme/photo')" in code
    assert "doc.size > opts.maxKb * 1024" in code and "TOO_DETAILED" in code  # nothing sent (M7)


def test_the_door_sends_a_new_garments_photo_with_fixed_words_only() -> None:
    # D22: a garment he is thinking of buying; its type and colour are fixed-list words (checked
    # again by the server), never his label; read back by its tg_ id only
    code = _code(STATIC / "console-r7-send.js")
    assert "const WORD = /^[a-z_]{2,20}$/" in code
    assert "WORD.test(String(m.type)) && WORD.test(String(m.colour))" in code
    sent = "jpegTo('/v1/seeme/garments?type=' + m.type + '&colour=' + m.colour, blob, m.maxKb)"
    assert sent in code
    assert "readBack(/^tg_[0-9a-f]{12}$/, '/v1/seeme/garments/')" in code
    assert "fetch(" not in code and "http" not in code  # it never sends to an address


@pytest.mark.parametrize("path", sorted(STATIC.glob("console*.js")), ids=lambda p: p.name)
def test_the_door_is_the_only_caller_of_his_photo_and_the_pictures(path: Path) -> None:
    if path.name == "console-r7-send.js":
        return
    code = _code(path)
    assert not re.search(r"""['"`]/v1/seeme/(?:photo|pictures|garments)""", code), path.name


def test_shrink_takes_a_lower_limit_and_can_insist_on_a_jpeg() -> None:
    code = _code(STATIC / "console-r111-files.js")
    assert "async function shrink(file, opts)" in code
    assert "most = Math.min(limits.picture_max_kb, low) * 1024" in code  # only ever lower
    assert "&& !o.jpeg)" in code


def test_privacy_opens_one_categorys_own_delete_for_another_panel() -> None:
    js = _text(STATIC / "console-privacy.js")
    assert "window.JarvisPrivacy = Object.freeze({ refresh: () => load(true), remove });" in js
    body = js[js.index("async function remove(id)") :]
    assert "askDelete(c, document.activeElement)" in body  # the category's own dialog and passkey
    assert "c.del === 'none'" in body


# ---- 10 · the pixel and drawing rules (D9, D12, M9) ----------------------------------------------
def test_the_photo_panel_keeps_the_scan_modules_rules() -> None:
    code = _code(STATIC / "console-tryon-photo.js")
    for bad in (
        "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "sessionStorage",
        "indexedDB", "JarvisChat", ".raw(", "FormData", "innerHTML", "outerHTML",
        "insertAdjacentHTML", "getUserMedia",
    ):  # fmt: skip
        assert bad not in code, bad
    for call in re.findall(r"(?:JarvisConsole\.api|M\.api)\(\s*([^,)]+)", code):
        assert call.strip().startswith("'/v1/seeme"), call
    assert set(re.findall(r"door\.(\w+)\(", code)) <= {"person"}
    assert _text(STATIC / "console-tryon-photo.js").isascii()


@pytest.mark.parametrize("name", B_JS)
def test_the_engine_draws_only_its_own_canvases_and_loads_only_its_files(name: str) -> None:
    code = _code(STATIC / name)
    for bad in (
        "JarvisVision", "JarvisCamera", "getUserMedia", "XMLHttpRequest", "WebSocket",
        "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "innerHTML", "https://",
        "http://", "captureStream", "getImageData", "JarvisChat",
    ):  # fmt: skip
        assert bad not in code, (name, bad)
    assert not re.search(r"door\.(?:person|wardrobe|tag|drop|picture|myPhoto|vault|ask)\b", code)
    allowed = ("./console-tryon-glb.js", "./console-tryon-cloth.js")
    allowed += ("/static/vendor/three-0.187.0/three.module.min.js",)
    for spec in re.findall(r"""(?:import\(\s*|from\s+)['"]([^'"]+)['"]""", code):
        assert spec in allowed, (name, spec)
    for url in re.findall(r"""['"`](/[a-z][^'"`]*)""", code):
        assert url.startswith(("/static/vendor/mannequin/", allowed[-1])), (name, url)


@pytest.mark.parametrize("name", D_JS)
def test_ds_modules_take_no_pixels_and_send_nothing_of_his_photo(name: str) -> None:
    code = _code(STATIC / name)
    for api in ("drawImage", "getImageData", "toBlob", "createImageBitmap", "captureStream"):
        assert api not in code, (name, api)  # the caption is drawn by B's snapshot (M9)
    assert "JarvisVision" not in code and "JarvisCamera" not in code


@pytest.mark.parametrize("name", TRYON_JS)
def test_each_tryon_module_keeps_its_size_and_no_dollar_figure(name: str) -> None:
    assert _lines(STATIC / name) <= LIMITS_JS[name], name
    assert not re.search(r"\$\s?\d|\bUSD\b", _code(STATIC / name)), name  # ₹ only (D0)


def test_the_tryon_css_only_places_things() -> None:
    total = 0
    for path in STATIC.glob("console-tryon*.css"):
        css = re.sub(r"/\*.*?\*/", "", _text(path), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css), path.name
        for prop in re.findall(
            r"(?:color|background|font(?:-family)?|box-shadow|border-radius)\s*:\s*([^;]+)", css
        ):
            assert prop.strip().startswith("var(--"), (path.name, prop)
        total += _lines(path)
    assert total <= 200


# ---- 11 · the engine contract (L12) --------------------------------------------------------------
def _node(src: str) -> str:
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    got = subprocess.run(
        [node, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=60,
        check=False, cwd=ROOT,
    )  # fmt: skip
    assert got.returncode == 0, got.stderr
    return got.stdout


def test_the_engine_fits_the_contract_and_mount_without_a_host_throws() -> None:
    # I1: B's engine replaced I0's stub (INTEGRATION-B section 6, item 1): the contract still
    # holds, and a mount with no place on the page throws in words, as the stub's did
    contract = (ROOT / "tests" / "fixtures" / "r13_1" / "engine_contract.mjs").as_uri()
    engine = (STATIC / "console-tryon-3d.js").as_uri()
    out = _node(
        "globalThis.window = {};"
        f"const C = await import('{contract}'); const E = await import('{engine}');"
        "const probs = C.engineProblems(window.JarvisTryOn3D);"
        "let threw = ''; try { window.JarvisTryOn3D.mount(null, {release: 'm1'}); }"
        " catch (e) { threw = e.message; }"
        "const fig = C.sampleFigure();"
        "console.log(JSON.stringify({probs, threw, supported: E.supported(),"
        " priv: fig.look.slots.map(C.privateSlotProblems).flat(),"
        " slot: C.SLOT, stage: C.STAGE, opts: C.OPTS, views: C.VIEWS, morphs: C.MORPHS}));"
    )
    import json

    got = json.loads(out)
    assert got["probs"] == [] and got["threw"] == "The 3D view needs a place on the page."
    assert got["supported"] is False  # Node has no document, so no WebGL2
    assert got["priv"] == [] and got["views"] == {"front": 0, "side": 90, "back": 180}
    assert got["slot"] == [
        "slot", "piece", "template", "variant", "rgb", "pattern", "photo", "private",
    ]  # fmt: skip
    assert got["stage"] == [
        "show", "view", "spin", "zoom", "closer", "snapshot", "stats", "dispose",
    ]  # fmt: skip
    assert got["opts"] == ["tucked", "open", "layers", "view"] and len(got["morphs"]) == 7


def test_the_contracts_templates_are_the_servers() -> None:
    import json

    from jarvis.wardrobe.tryon import model as m

    contract = (ROOT / "tests" / "fixtures" / "r13_1" / "engine_contract.mjs").as_uri()
    got = json.loads(_node(
        f"const C = await import('{contract}');"
        "console.log(JSON.stringify({t: C.TEMPLATES, v: C.VARIANTS, l: C.LAYERS, m: C.MEASURES}));"
    ))  # fmt: skip
    assert tuple(got["t"]) == m.TEMPLATES and tuple(got["l"]) == m.LAYERS
    assert {k: tuple(v) for k, v in got["v"].items()} == dict(m.VARIANTS)
    assert tuple(got["m"]) == m.MEASURES


# ---- 15 · the eval runner, staged ----------------------------------------------------------------
def _runner() -> object:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("r13_1_run", ROOT / "evals" / "r13_1" / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_r131_runner_passes_staged_and_its_contract_control_fails_it() -> None:
    import json
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "r13_1" / "run.py"), "--mock"],
        capture_output=True, text=True, env=env, timeout=300, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((ROOT / "evals" / "r13_1" / "report.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in report["results"]}
    parts = ("catalog", "laundry", "styling", "phone", "tryon", "seeme")
    assert {f"contract:{p}_builds" for p in parts} <= ids
    assert {"contract:refuses_data_on_tryon", "contract:refuses_a_stray_route"} <= ids
    assert "contract:broken_r131_parts_leave_r13_running" in ids
    row388 = "contract:row388_what_to_wear_opens_the_tryon_card"  # D21's server half
    assert next(r for r in report["results"] if r["id"] == row388)["passed"]
    control = report["negative_control"]
    assert control["suite_failed"] is True and row388 in control["failed_cases"]["contract"]


def test_the_gate_is_flipped_at_i1_so_a_stub_never_reads_as_green() -> None:
    import asyncio
    from types import SimpleNamespace

    runner = _runner()
    assert runner.STUBS_PASS is False  # type: ignore[attr-defined]  # I1: every part is built
    for part in runner.PARTS:  # type: ignore[attr-defined]
        assert runner.load(part).BUILT is True, part  # type: ignore[attr-defined]
    assert runner.PARTS == (  # type: ignore[attr-defined]
        "figure", "looks", "seeme", "console", "e2e", "needles", "contract",
    )  # fmt: skip

    async def not_built() -> list[dict[str, object]]:
        return [{"id": "x:not_built_yet", "passed": True, "failures": []}]

    stub = SimpleNamespace(BUILT=False, cases=not_built)
    runner.load = lambda part: stub  # type: ignore[attr-defined]
    flipped, controls = asyncio.run(runner.run_parts(("figure",)))  # type: ignore[attr-defined]
    assert [(r["id"], r["passed"]) for r in flipped] == [("x:not_built_yet", False)]
    assert controls == {}
    staged, _ = asyncio.run(runner.run_parts(("figure",), stubs_pass=True))  # type: ignore[attr-defined]
    assert [(r["id"], r["passed"]) for r in staged] == [("x:not_built_yet", True)]  # before I1


def test_the_r131_suite_is_gated_in_run_all_mock_after_r13() -> None:
    text = _text(ROOT / "evals" / "run_all_mock.py")
    lines = text.splitlines()
    at = next(i for i, x in enumerate(lines) if '"r13_1 (gated)"' in x)
    assert 'HERE / "r13_1" / "run.py"' in lines[at] and lines[at].rstrip().endswith("True),")
    assert at > next(i for i, x in enumerate(lines) if '"r13 (gated)"' in x)


# ---- 15 · the fake server Parts B and D build against --------------------------------------------
NEEDS_A_GARMENT = {("POST", "/v1/seeme/pictures"), ("GET", "/v1/seeme/pair")}


async def _with_a_garment(c: Any, method: str, url: str, kw: dict[str, Any]) -> tuple[str, Any]:
    from r131_fakes import jpeg

    shot = {"headers": {"content-type": "image/jpeg"}}
    await c.post("/v1/seeme/photo", content=jpeg(600, 1200), **shot)
    gid = await c.post("/v1/seeme/garments?type=shirt&colour=navy", content=jpeg(600, 800), **shot)
    gid = gid.json()["id"]
    if method == "GET":
        return f"{url}?garment={gid}", kw
    return url, {"json": {**kw["json"], "garment": gid}}


async def test_the_fake_server_answers_every_route_with_its_model(settings: Settings) -> None:
    from httpx import ASGITransport, AsyncClient
    from r131_fake_seeme import CONSENT_VERSION
    from r131_fake_server import fake_app, fake_state
    from r131_fakes import T, jpeg

    from jarvis.memory.inmemory import InMemorySessionStore
    from jarvis.wardrobe.tryon import http

    store, clock = await fake_state()
    app = fake_app(store, clock, settings=settings, store=InMemorySessionStore())
    plan = "op_00000001"
    bodies: dict[tuple[str, str], object] = {
        ("PUT", "/v1/tryon/body"): {"height": 178},
        ("PUT", "/v1/tryon/assets/{piece}"): {"piece": T.striped, "template": "shirt"},
        ("POST", "/v1/tryon/confirm"): {"plan": plan, "slots": [{"slot": "top", "piece": T.shirt}]},
        ("POST", "/v1/tryon/saved"): {"looks": [{"slots": [{"slot": "top", "piece": T.shirt}]}]},
        ("POST", "/v1/seeme/consent"): {"typed": " YES ", "template_version": CONSENT_VERSION},
        ("POST", "/v1/seeme/pictures"): {"pieces": [T.trousers], "confirm_cost": True,
                                         "inr_shown": 8.9, "request_id": "tq_" + "0" * 16},
        ("POST", "/v1/seeme/pictures/{id}/keep"): {"keep": True},
        ("PUT", "/v1/seeme/settings"): {"cap_inr": 200},
    }  # fmt: skip
    ids: dict[str, str] = {"{piece}": T.striped}
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for method, path, _, req, reply, _, _ in http.ROUTES:
                url = path
                for k, v in ids.items():
                    url = url.replace(k, v)
                kw: dict[str, object] = {}
                if req == "image/jpeg":
                    kw = {"content": jpeg(600, 1200, 64), "headers": {"content-type": "image/jpeg"}}
                elif (method, path) in bodies:
                    kw = {"json": bodies[(method, path)]}
                if path == "/v1/tryon/body/draft":  # a draft to drop
                    await c.put("/v1/tryon/body", json={"waist": 80})
                if (method, path) in NEEDS_A_GARMENT:  # his photo again, and a new garment
                    url, kw = await _with_a_garment(c, method, url, kw)
                if (method, path) == ("POST", "/v1/seeme/garments"):
                    url = f"{url}?type=kurta&colour=maroon"
                got = await c.request(method, url, **kw)  # type: ignore[arg-type]
                assert got.status_code == 200, (method, path, got.text)
                if isinstance(reply, type):
                    found = reply.model_validate(got.json())
                    if isinstance(found, http.PictureView | http.GarmentView):
                        ids["{id}"] = found.id
                    if isinstance(found, http.SavedView) and method == "POST":
                        ids["{id}"] = found.id
                else:
                    assert got.headers["content-type"].startswith(str(reply)), path
                    assert got.headers["content-security-policy"] == "default-src 'none'"
            look = http.TryonLook.model_validate((await c.get("/v1/tryon/look")).json())
            base = next(s for s in look.slots if s.slot == "base")
            assert base.private and base.piece is None and base.rgb is None  # covered only
            q = f"pieces=top:{T.shirt},base:{T.vest}"  # row 388, on the card's own day (I1 H1)
            card = await c.get(f"/v1/tryon/look?{q}&day=today")
            got = http.TryonLook.model_validate(card.json())
            assert [(s.slot, s.piece) for s in got.slots] == [("top", T.shirt), ("base", None)]
            bare = await c.get(f"/v1/tryon/look?{q}")  # never read for today by default
            assert bare.status_code == 422 and bare.json()["error"] == "bad_day"
            stranger = await c.get("/v1/tryon/look?pieces=top:wi_000000000999&day=today")
            assert stranger.status_code == 422 and stranger.json()["error"] == "not_a_piece"
            refused = await c.post(
                "/v1/seeme/consent", json={"typed": "yes", "template_version": "c2"}
            )
            assert refused.status_code == 422 and refused.json()["error"] == "not_yes"


async def test_the_stage_page_serves_the_engine_under_the_consoles_csp(settings: Settings) -> None:
    from httpx import ASGITransport, AsyncClient
    from r131_fake_server import fake_app, fake_state

    from jarvis.api.console import CONSOLE_CSP

    store, clock = await fake_state()
    app = fake_app(store, clock, settings=settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            page = await c.get("/r131/stage")
            assert (
                page.status_code == 200 and page.headers["content-security-policy"] == CONSOLE_CSP
            )
            assert 'src="/r131/fixtures/stage.mjs"' in page.text
            mod = await c.get("/r131/fixtures/stage.mjs")
            assert mod.status_code == 200 and "JarvisTryOn3D" in mod.text
            assert (await c.get("/r131/fixtures/..%2Fr13_fakes.py")).status_code == 404
            assert (await c.get("/static/console-tryon-3d.js")).status_code == 200


# ---- 13 · the deploy (M6, G6) -------------------------------------------------------------------
def test_the_deploy_switches_on_see_it_on_me_only_when_the_api_and_a_role_worked() -> None:
    import subprocess

    sh = _text(ROOT / "deploy" / "cloudrun.sh")
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "cloudrun.sh")]).returncode == 0
    assert "gcloud services enable aiplatform.googleapis.com --quiet" in sh
    assert "--permissions=aiplatform.endpoints.predict --stage=GA" in sh  # prompt requests only
    # I1 (INTEGRATION-C 7 (a), (b)): an existing role is set back to prompt requests only, and
    # the comment says what the role really allows (prompts to ANY model, the alert the brake)
    update = 'gcloud iam roles update jarvisTryOn --project "$PROJECT" '
    assert update + "--permissions=aiplatform.endpoints.predict --quiet" in sh
    assert sh.index("gcloud iam roles describe jarvisTryOn") < sh.index(update)
    assert "can't start\n# other paid models" not in sh and "can't start other paid" not in sh
    assert "ONLY make prompt requests (to any Agent Platform model)" in sh
    assert "roles/aiplatform.user" not in sh  # fail closed: never a broader role (I1 sec. L5)
    assert "TRYON_STATE=true" in sh and "JARVIS_TRYON_PICTURES=true" not in sh  # never forced on
    infra = [ln for ln in sh.splitlines() if ln.startswith('INFRA_ENV="${INFRA_ENV},JARVIS_TRYON')]
    assert infra == [
        'INFRA_ENV="${INFRA_ENV},JARVIS_TRYON_PICTURES=${TRYON_STATE},'
        'JARVIS_TRYON_CACHE=${TRYON_CACHE}"   # R13.1 seam 13'
    ]
    assert sh.index('INFRA_ENV="${INFRA_ENV},JARVIS_TRYON') < sh.index("CONFIG_FLAGS=(")


def test_the_deploy_turns_googles_cache_off_with_the_token_never_on_a_command_line() -> None:
    sh = _text(ROOT / "deploy" / "cloudrun.sh")
    block = sh[sh.index("# Google's own 24-hour cache") : sh.index("unset tok cfg body url")]
    assert "curl -fsS --max-time 20 --config - -X PATCH" in block  # the token on stdin only
    assert '\\"disableCache\\":true' in block and "/cacheConfig" in block
    assert 'echo "$tok"' not in block and 'Bearer ${tok}\\""' in block
    assert "--display-name=jarvis-tryon" in sh and "--budget-amount=300INR" in sh  # sec. L6


def test_ci_runs_the_figure_build_scripts_tests_on_the_312_leg_only() -> None:
    # I1 (INTEGRATION-B 8, "Needs I1" 4): scipy for scripts/mannequin's tests, pinned as the
    # script's own requirements, on the 3.12 leg beside the homebridge NumPy; 3.11 is untouched
    ci = _text(ROOT / ".github" / "workflows" / "ci.yml")
    pins = _text(ROOT / "scripts" / "mannequin" / "requirements-dev.txt")
    assert "scipy==1.18.1" in pins
    step = "      - if: matrix.python == '3.12'\n        run: pip install scipy==1.18.1\n"
    assert ci.count("pip install scipy") == 1 and step in ci
    assert ci.index('pip install -e ".[dev,homebridge]"') < ci.index(step) < ci.index("ruff check")


def test_the_figure_scripts_numpy_is_the_one_ci_installs_beside_it() -> None:
    # integrated code review L7: CI's 3.12 leg runs B's build tests with the homebridge extra's
    # NumPy; the script pinned another, so a NumPy bump for the bridge could turn B's tests red
    # for a reason unrelated to the figure. One pin: a bump moves both, deliberately.
    pins = _text(ROOT / "scripts" / "mannequin" / "requirements-dev.txt").split()
    found = re.search(
        r"'numpy==([0-9.]+); python_version >= \"3\.12\"'", _text(ROOT / "pyproject.toml")
    )
    assert found is not None
    assert pins[-2:] == [f"numpy=={found.group(1)}", "scipy==1.18.1"]


# ---- 14 · the guide and the book -----------------------------------------------------------------
def test_the_guide_has_c72_and_c73_with_every_collection_and_console_module() -> None:
    from jarvis.wardrobe.ports import COLLECTIONS

    guide = _text(ROOT / "docs" / "architecture" / "JARVIS-Architecture.md")
    assert "| v13.1.5 | 18 Nov 2026, 06:15 IST | R13.1 |" in guide  # R6.3 I0: the edition moved on
    for card in ("#### C72 · Try-on figure (R13.1)", "#### C73 · See it on me (R13.1)"):
        assert card in guide, card
    for name in (*COLLECTIONS["tryon"], *COLLECTIONS["seeme"]):
        assert f"`{name}/" in guide, name
    for name in TRYON_JS:
        assert f"`{name}`" in guide, name
    assert "C72 Try-on figure, C73 See it on me (R13.1)" in guide  # built at I1
    assert "from R13.1 `tryon` and `tryon_photos`" in guide


def test_the_book_knows_the_mannequins_licences() -> None:
    from jarvis.buildbook.gen.libs import VENDORED, flag_of, licence_from_text

    assert VENDORED["vendor/mannequin/m1/LICENSE-mpfb2-CC0.txt"][3] == "3d"
    assert VENDORED["vendor/mannequin/m1/LICENSE-anny-Apache-2.0.txt"][3] == "3d"
    cc0 = "# Creative Commons CC0 1.0 Universal\n\nCREATIVE COMMONS CORPORATION IS NOT A LAW FIRM"
    assert licence_from_text(cc0) == "CC0-1.0" and flag_of("CC0-1.0") is None
    apache = 'licensed under the Apache License, \nVersion 2.0 (the "License")'
    assert licence_from_text(apache) == "Apache-2.0"


# ---- size guards, "no real clock", ₹ only ------------------------------------------------------
def test_the_size_guards_hold() -> None:
    assert _lines(SRC / "api" / "app.py") <= 739  # not edited by R13.1 (732); R18 I1 +4, R5.2 I1 +1
    assert _lines(SRC / "tools" / "gateway.py") == 760  # not edited
    assert _lines(SRC / "core" / "brain.py") <= 741  # not edited (713)
    assert _lines(SRC / "config.py") <= 792  # R18 +2, R5.2 +1: the base classes' imports
    assert _lines(STATIC / "console-helpers.js") <= 238  # not edited
    assert _lines(STATIC / "console-helpers-wardrobe.js") <= 306
    assert _lines(STATIC / "console-r7-send.js") <= 165
    assert _lines(STATIC / "console-r111-files.js") <= 335
    assert _lines(STATIC / "console-privacy.js") <= 268
    for path in STATIC.glob("console*.js"):
        assert _lines(path) <= 800, path.name
    assert sum(_lines(p) for p in STATIC.glob("console-tryon*.css")) <= 200
    for path in (SRC / "wardrobe").rglob("*.py"):
        assert _lines(path) <= 400, path.name
    assert _lines(SRC / "api" / "r13_wiring.py") <= 400
    assert _lines(SRC / "api" / "console.py") <= 475
    assert _lines(SRC / "wardrobe" / "styling" / "actions.py") <= 400
    new = [
        SRC / "llm" / "tryon.py",
        SRC / "billing" / "spend.py",
        SRC / "api" / "tryon.py",
        SRC / "api" / "seeme.py",
        SRC / "api" / "tryon_assets.py",
        SRC / "api" / "tryon_wiring.py",
    ]
    for path in new:
        assert _lines(path) <= 400, path.name
    assert _lines(SRC / "billing" / "spend.py") <= 100
    # D21, D22 (the owner's scope of 17 Nov): the card's hook, its loader, the share tray's button
    assert _lines(STATIC / "console-media.js") <= 415
    assert _lines(STATIC / "console-r7.js") <= 96  # R5.2 V3: its one registration line
    assert _lines(STATIC / "console-r7-share.js") <= 295
    assert _lines(SRC / "tools" / "reply_cards.py") <= 400
    m1 = STATIC / "vendor" / "mannequin" / "m1"
    total = sum(p.stat().st_size for p in m1.rglob("*") if p.is_file()) if m1.is_dir() else 0
    assert total <= 3.5 * 1024 * 1024  # Part B's files (D3's budget)


_CLOCK = re.compile(r"datetime\.now\(|date\.today\(|time\.time\(|utcnow|datetime\.today\(")


@pytest.mark.parametrize(
    "path",
    [*sorted((SRC / "llm").glob("tryon*.py")), *sorted((SRC / "wardrobe" / "tryon").glob("*.py")),
     *sorted((SRC / "wardrobe" / "seeme").glob("*.py")), SRC / "billing" / "spend.py"],
    ids=lambda p: str(p.relative_to(SRC)),
)  # fmt: skip
def test_no_r131_module_reads_the_real_clock_or_shows_a_dollar(path: Path) -> None:
    text = _text(path)
    assert not _CLOCK.search(text), path  # ctx.now() only
    strings = re.findall(r'"([^"\n]*)"', text)
    assert not [s for s in strings if re.search(r"\$\s?\d", s)], path  # ₹ only to the owner


def test_a_picture_is_kept_30_days_unless_he_presses_keep() -> None:
    from jarvis.wardrobe.tryon import kept, model

    assert model.PICTURE_KEEP_DAYS == Settings(_env_file=None).tryon_keep_days == 30
    words = kept.SPECS[kept.PICTURES_ID].retention
    assert words.startswith("30 days unless you press Keep") and "7 days" not in words


def test_the_figures_seven_morph_weights_come_from_the_six_measurements() -> None:
    from jarvis.wardrobe.tryon import model as m
    from jarvis.wardrobe.tryon.http import BodyView

    assert m.MORPHS == (*m.MEASURES, "waist_down")
    assert m.morph_weights(m.SAMPLE) == dict.fromkeys(m.MORPHS, 0.0)  # the sample: no morph
    top = m.morph_weights({**m.SAMPLE, "height": 195, "waist": 120})
    assert top["height"] == top["waist"] == 1.0 and top["waist_down"] == 0.0
    low = m.morph_weights({**m.SAMPLE, "waist": 62, "chest": 76})
    assert low["waist"] == 0.0 and low["waist_down"] == 1.0  # below the sample: its own morph (H3)
    assert low["chest"] == round((76 - 96) / (124 - 96), 6)  # the other sliders extrapolate (v2)
    view = BodyView(**m.SAMPLE, at=NOW_UTC, weights=m.morph_weights(m.SAMPLE))
    assert set(view.weights) == set(m.MORPHS)


NOW_UTC = __import__("datetime").datetime(2026, 11, 17, 3, 30, tzinfo=__import__("datetime").UTC)
