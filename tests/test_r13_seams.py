# tests/test_r13_seams.py -- R13 I0 seams (docs/plans/r13-wardrobe.md "The I0 seam list", 1-16):
# the version and the book's release name, four alert kinds and every table that names one, two
# key purposes, three permission rows and the save cap, the bin's `wardrobe_item` kind, the
# Telegram personal switch, "never Approve all", the settings, the parts' contract, the states
# table, the redaction views, the HTTP contract, the wiring, the vision contract and the pixel
# panels, the console's joins (stubs), the skill register, the guide's planned cards, the eval
# runner's staged gate, the model files' manifest, the size guards and "no real clock".
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

import jarvis
from jarvis import keyring
from jarvis.alerts import R13_ALERT_KINDS, AlertKind
from jarvis.buildbook.gen import plans
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.plain import ALERT_WORDS
from jarvis.config import Settings
from jarvis.core.guardrails import NO_BULK_TOOLS, ActionRisk, PendingAction
from jarvis.notify.held import summary
from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
from jarvis.notify.ports import DEFAULT_URGENCY
from jarvis.permissions.groups import GROUPS, get_group, groups_for
from jarvis.permissions.models import PermissionsPatch
from jarvis.telegram import rules as tg
from jarvis.undo.models import IN_PLACE_KINDS, KIND_WORDS, KINDS, PASSKEY_PURGE_KINDS
from jarvis.webpush.service import TARGETS

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
KINDS13 = ("outfit_ready", "outfit_changed", "laundry_overdue", "wardrobe_review")
# The 18 tools (plan "Tools"), each with its risk and its permission row
TOOLS13: dict[str, tuple[ActionRisk, str]] = {
    "wardrobe_find": (R1, "wardrobe"),
    "wardrobe_count": (R1, "wardrobe"),
    "wardrobe_add": (R2, "wardrobe"),
    "wardrobe_edit": (R2, "wardrobe"),
    "wardrobe_places": (R2, "wardrobe"),
    "wardrobe_merge": (R2, "wardrobe"),
    "wardrobe_retire": (R2, "wardrobe"),
    "wardrobe_remove": (R2, "wardrobe"),
    "laundry_status": (R1, "laundry"),
    "laundry_move": (R2, "laundry"),
    "laundry_review": (R2, "laundry"),
    "laundry_correct": (R2, "laundry"),
    "laundry_send_out": (R2, "laundry"),
    "outfit_suggest": (R1, "outfits"),
    "outfit_plans": (R1, "outfits"),
    "outfit_plan": (R2, "outfits"),
    "outfit_prefs": (R2, "outfits"),
    "wear_log": (R2, "outfits"),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> int:
    return len(_text(path).splitlines())


# ---- 1 · the version and the book's release name ------------------------------------------------
def test_the_version_is_thirteen() -> None:
    assert jarvis.__version__ == "13.1.0"  # R13.1 I0 (13.0.0 at R13; nothing compares it, D21)


def test_the_real_repository_is_r13_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)  # R13.1 I0: the release is now R13.1 (tests/test_r131_seams.py)
    assert plans.release_label(repo) == "R13.1"
    assert plans.plan_paths(repo)[0] == "docs/plans/r13-1-try-on.md"
    assert "docs/plans/r13-wardrobe.md" in plans.plan_paths(repo)


# ---- 2 · four alert kinds and every table that names one (D19) -----------------------------------
def test_four_kinds_make_fifty_six() -> None:
    every = get_args(AlertKind)
    assert R13_ALERT_KINDS == KINDS13
    assert len(every) == len(set(every)) == 56 and set(DEFAULT_URGENCY) == set(every)
    assert [DEFAULT_URGENCY[k] for k in KINDS13] == ["important"] * 3 + ["info"]
    # the three important ones ring by day and are held at night, never dropped like a nudge
    assert set(KINDS13[:3]) <= DAYTIME_RING_KINDS and "wardrobe_review" not in DAYTIME_RING_KINDS
    assert not set(KINDS13) & EPHEMERAL_KINDS


def test_the_held_words_the_alerts_card_the_book_and_push_know_every_new_kind() -> None:
    js = _text(STATIC / "console-alerts.js")
    for kind in KINDS13:
        assert f"['{kind}'," in js, kind
        assert "(1 alert)" not in summary([{"kind": kind}]), kind  # its own held words
        assert kind in ALERT_WORDS, kind
        assert TARGETS[kind] == "helpers", kind  # a tap opens Helpers (its last sub-tab, D1)
    assert "outfit" in summary([{"kind": "outfit_changed"}]).lower()
    assert "laundry" in summary([{"kind": "laundry_overdue"}]).lower()


# ---- 3 · two key purposes ------------------------------------------------------------------------
def test_two_key_purposes_make_twenty_four() -> None:
    assert keyring.PURPOSES[-4:-2] == ("wardrobe", "wardrobe_photos")  # R13.1 + 2 after them
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 26
    ring = keyring.Keyring(bytes(range(7, 39)))
    blob = ring.cipher("wardrobe").encrypt(b"x", aad="wardrobe/u/v1")
    with pytest.raises(Exception):  # noqa: B017 - each purpose is its own key
        ring.cipher("wardrobe_photos").decrypt(blob, aad="wardrobe/u/v1")
    assert ring.cipher("wardrobe").decrypt(blob, aad="wardrobe/u/v1") == b"x"


# ---- 4 · three permission rows and the save cap (D18) --------------------------------------------
def test_three_rows_make_fifty_two_and_sit_after_pictures() -> None:
    ids = [g.id for g in GROUPS]
    assert len(ids) == len(set(ids)) == 52
    at = ids.index("pictures")
    assert ids[at + 1 : at + 4] == ["wardrobe", "laundry", "outfits"]
    assert ids[-2:] == ["maps", "youtube"]  # Maps and YouTube stay last
    for gid in ("wardrobe", "laundry", "outfits"):
        g = get_group(gid)
        assert g is not None and g.risk is R2 and not g.irreversible and len(g.choices) == 3
        assert g.section == "Wardrobe" and g.hint and "₹" not in g.hint
    outfits = get_group("outfits")
    assert outfits is not None and "calendar" in outfits.hint.lower()
    laundry = get_group("laundry")
    assert laundry is not None and "never" in laundry.hint.lower()


@pytest.mark.parametrize("tool", sorted(TOOLS13))
def test_each_tool_falls_into_its_row(tool: str) -> None:
    risk, row = TOOLS13[tool]
    assert {g.id for g in groups_for(tool, risk)} == {row}


def test_the_save_cap_is_fifty_four() -> None:
    PermissionsPatch(groups={f"g{i}": "ask" for i in range(54)})  # 52 rows, two to spare
    with pytest.raises(ValidationError):
        PermissionsPatch(groups={f"g{i}": "ask" for i in range(55)})


# ---- 5 · the bin's wardrobe_item (D16) -----------------------------------------------------------
def test_wardrobe_item_is_an_in_place_kind_purged_with_the_passkey() -> None:
    assert "wardrobe_item" in KINDS and KIND_WORDS["wardrobe_item"] == "wardrobe piece"
    assert "wardrobe_item" in IN_PLACE_KINDS and "wardrobe_item" in PASSKEY_PURGE_KINDS
    js = _text(STATIC / "console-deleted.js")
    assert "wardrobe_item: 'Wardrobe piece'" in js and "wardrobe_item: 'wardrobe piece'" in js


# ---- 6 · Telegram: the personal switch (D18) -----------------------------------------------------
def test_the_four_families_join_the_personal_switch() -> None:
    from fnmatch import fnmatchcase

    assert tg.PERSONAL_PATTERNS[:3] == ("vault_*", "kb_*", "belongings_*")
    assert set(tg.PERSONAL_PATTERNS[3:]) == {"wardrobe_*", "laundry_*", "outfit_*", "wear_*"}
    assert "wardrobe" in tg.PERSONAL_REFUSAL and "console" in tg.PERSONAL_REFUSAL
    for tool in TOOLS13:
        assert any(fnmatchcase(tool, p) for p in tg.PERSONAL_PATTERNS), tool
        assert not any(fnmatchcase(tool, p) for p in tg.PRIVATE_PATTERNS), tool


# ---- 7 · merge and archive are never "Approve all" (D16) -----------------------------------------
@pytest.mark.parametrize("tool", ["wardrobe_merge", "wardrobe_retire"])
def test_merge_and_archive_are_never_approved_in_bulk(tool: str) -> None:
    assert tool in NO_BULK_TOOLS
    card = PendingAction(tool=tool, arguments={}, risk=R3, summary="x", tool_risk=R2)
    assert card.bulk_ok is False
    other = PendingAction(tool="wardrobe_edit", arguments={}, risk=R3, summary="x", tool_risk=R2)
    assert other.bulk_ok is True


# ---- 8 · settings --------------------------------------------------------------------------------
def test_the_r13_settings_have_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.wardrobe_enabled is True
    assert (s.wardrobe_max_pieces, s.wardrobe_index_max_kb, s.wardrobe_stale_days) == (400, 900, 14)
    assert (s.wardrobe_plan_evening, s.wardrobe_wear_close) == ("20:00", "04:00")
    assert (s.wardrobe_change_window_h, s.wardrobe_calendar_refresh_min) == (36, 60)
    assert (s.wardrobe_photo_side, s.wardrobe_photo_max_kb, s.wardrobe_photos_per_piece) == (
        512,
        200,
        3,
    )
    assert (s.wardrobe_ai_tag_month_inr, s.wardrobe_review_keep_days) == (30, 30)
    assert s.wardrobe_backup_max_mb == 25


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("wardrobe_max_pieces", 49),
        ("wardrobe_max_pieces", 501),
        ("wardrobe_index_max_kb", 951),
        ("wardrobe_stale_days", 2),
        ("wardrobe_stale_days", 91),
        ("wardrobe_plan_evening", "8pm"),
        ("wardrobe_plan_evening", "24:00"),
        ("wardrobe_change_window_h", 5),
        ("wardrobe_change_window_h", 73),
        ("wardrobe_calendar_refresh_min", 14),
        ("wardrobe_calendar_refresh_min", 361),
        ("wardrobe_photo_side", 255),
        ("wardrobe_photo_side", 513),
        ("wardrobe_photo_max_kb", 49),
        ("wardrobe_photo_max_kb", 401),
        ("wardrobe_photos_per_piece", 0),
        ("wardrobe_photos_per_piece", 4),
        ("wardrobe_ai_tag_month_inr", -1),
        ("wardrobe_ai_tag_month_inr", 201),
        ("wardrobe_backup_max_mb", 4),
        ("wardrobe_backup_max_mb", 31),
        ("wardrobe_wear_close", "4:00"),
    ],
)
def test_an_r13_setting_outside_its_range_is_refused(field: str, bad: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


def test_config_stays_under_its_guard() -> None:
    assert _lines(SRC / "config.py") < 800


# ---- 9 · the parts' contract (wardrobe/ports.py) -------------------------------------------------
def test_the_four_parts_and_what_each_owns() -> None:
    from jarvis.alerts import R13_ALERT_KINDS as KINDS
    from jarvis.wardrobe import ports

    assert ports.PARTS[:4] == ("catalog", "laundry", "styling", "phone")  # R13.1 + tryon, seeme
    assert set(ports.TOOL_OWNER) == set(TOOLS13) and len(ports.TOOL_OWNER) == 18
    for tool, part in ports.TOOL_OWNER.items():
        assert ports.tool_allowed(part, tool), tool
        assert not any(ports.tool_allowed(p, tool) for p in ports.PARTS if p != part), tool
    assert not ports.tool_allowed("catalog", "wardrobe_shout")  # a family word alone is not enough
    assert set(ports.ROUTE_PREFIX) == set(ports.COLLECTIONS) == set(ports.PARTS)
    assert ports.R13_JOB_NAMES[:3] == ("wardrobe_sweep", "laundry_daily", "outfit_clock")
    assert ports.R13_JOB_NAMES[3:] == ("seeme_daily",)  # R13.1 C (tests/test_r131_seams.py)
    assert ports.CLOCK_JOB_NAMES == {"outfit_clock"} and set(ports.JOB_OWNER) == {
        *ports.R13_JOB_NAMES
    }
    assert set(ports.KIND_OWNER) == set(KINDS)
    assert {ports.KIND_OWNER[k] for k in ("outfit_ready", "outfit_changed")} == {"styling"}
    assert ports.CARD_ALWAYS == {"wardrobe_merge", "wardrobe_retire"} <= NO_BULK_TOOLS
    assert ports.QUERY_TOOLS == ports.SPOKEN_OK == {"laundry_move", "wear_log"}
    assert ports.R13_STATUS_ROUTE == "/v1/r13" and ports.MAX_RESULT_PIECES == 20


def test_every_planned_collection_is_named_and_flat() -> None:
    from jarvis.wardrobe.ports import COLLECTIONS

    every = {c for cs in COLLECTIONS.values() for c in cs}
    assert every == {
        *("wardrobe", "wardrobe_log", "wardrobe_photo", "wardrobe_fp", "wardrobe_restore"),
        *("wardrobe_laundry", "wardrobe_review", "wardrobe_plans", "wardrobe_cal"),
        *("wardrobe_outlook", "wardrobe_told"),
        # R13.1 (tests/test_r131_seams.py; the guide's cards C72-C73)
        *("tryon", "tryon_person", "tryon_consent", "tryon_picture", "tryon_spend"),
    }
    guide = _text(ROOT / "docs" / "architecture" / "JARVIS-Architecture.md")
    for name in every:
        assert f"`{name}/" in guide, name  # the guide's cards C69-C71 name every one


def test_the_context_carries_the_one_clock_and_his_zone() -> None:
    from dataclasses import fields

    from jarvis.wardrobe.ports import WardrobeContext

    names = {f.name for f in fields(WardrobeContext)}
    assert {"now", "zone", "state", "notifier", "reads", "outside", "store"} <= names


# ---- 9 · the states table (D3) -------------------------------------------------------------------
def test_the_ten_states_and_only_ready_is_eligible() -> None:
    from jarvis.wardrobe import states as st

    assert len(st.STATES) == 10 and st.STATE_WORDS["review"] == "Missing or in review"
    assert [s for s in st.STATES if st.eligible(s)] == ["ready"]
    assert st.owned("in_laundry") and not st.owned("archived")  # laundry stays owned (INV-14)


@pytest.mark.parametrize(
    ("kind", "current", "to", "want"),
    [
        ("registered", None, None, "ready"),
        ("wear_started", "ready", None, "in_use"),
        ("wear_done", "in_use", None, "in_laundry"),
        ("wear_done", "in_use", "ready", "ready"),  # the rewear rule: a belt
        ("deposited", "in_use", None, "in_laundry"),
        ("load_started", "in_laundry", None, "washing"),
        ("dried", "washing", None, "drying"),
        ("needs_prep", "drying", None, "needs_prep"),
        ("returned", "needs_prep", None, "ready"),
        ("sent_out", "in_laundry", None, "with_provider"),
        ("received", "with_provider", "needs_prep", "needs_prep"),
        ("damaged", "ready", None, "needs_repair"),
        ("repaired", "needs_repair", None, "ready"),
        ("archived", "ready", None, "archived"),
        ("restored", "archived", None, "review"),
    ],
)
def test_each_rows_transition(kind: str, current: str | None, to: str | None, want: str) -> None:
    from jarvis.wardrobe import states as st

    assert st.allowed(kind, current), (kind, current)  # type: ignore[arg-type]
    assert st.target_of(kind, current, to=to) == want  # type: ignore[arg-type]


def test_the_table_refuses_what_the_workbook_does() -> None:
    from jarvis.wardrobe import states as st

    assert not st.allowed("load_started", "ready") and not st.allowed("dried", "in_laundry")
    assert not st.allowed("returned", "with_provider") and not st.allowed("restored", "ready")
    assert st.target_of("wear_done", "in_use", to="washing") is None  # not one of its choices
    assert st.target_of("released", "review", back_to="drying") == "drying"
    assert st.target_of("found", "review", back_to=None) == "ready"


def test_pairs_and_sets_are_wearable_only_when_complete() -> None:
    from jarvis.wardrobe.states import wearable_pair, wearable_set

    assert wearable_pair(["ready", "ready"]) and not wearable_pair(["ready", "in_laundry"])
    whole, alone = wearable_set([("ready", True), ("in_laundry", False)])
    assert (whole, alone) == (False, (0,))  # the kurta can go alone; its set can't (INV-12)


# ---- 9 · the records (D2) and the redaction views (D10) ------------------------------------------
def test_records_round_trip_through_short_keys() -> None:
    from jarvis.wardrobe.model import Piece

    p = Piece.model_validate(
        {"id": "wi_" + "1" * 12, "category": "tops", "type": "shirt", "label": "ഷർട്ട്",
         "colour": "navy", "size": {"v": "40", "ok": True}, "features": {"sleeve": "long"}}
    )  # fmt: skip
    stored = p.to_json()
    assert {"i", "c", "t", "l", "co", "sz", "f"} <= set(stored) and "id" not in stored
    assert Piece.model_validate(stored) == p
    with pytest.raises(ValidationError):
        Piece.model_validate({**stored, "f": {"sleeve": "puffed"}})  # fixed lists only
    with pytest.raises(ValidationError):
        Piece.model_validate({**stored, "i": "wi_short"})


def test_a_maximal_piece_stays_small_with_short_keys() -> None:
    from jarvis.wardrobe.model import CARE_WORDS, Piece

    p = Piece.model_validate(
        {"id": "wi_" + "f" * 12, "category": "tops", "type": "shirt", "label": "ഷ" * 60,
         "colour": "light_blue", "second": "navy", "pattern": "checked",
         "locked": ("colour", "pattern"), "features": {"sleeve": "long", "collar": "spread"},
         "size": {"v": "40 SLIM", "ok": True}, "brand": {"v": "A" * 30, "ok": False},
         "fabric": [{"v": "cotton", "ok": True}], "care": [{"v": c} for c in CARE_WORDS[:8]],
         "formality": 4, "occasions": ("work", "formal"), "weather": ("warm",),
         "place": "wl_" + "1" * 8, "label_code": "abcdefgh", "photos": ["wh_" + "2" * 12] * 3,
         "wears": 120, "events": 400}
    )  # fmt: skip
    import json

    raw = json.dumps(p.to_json(), ensure_ascii=False).encode()
    assert len(raw) < 1_300  # 600 of them stay under the 900 KB guard before sealing (M9)


def test_the_qr_reader_takes_only_jarvis_own_labels() -> None:
    from jarvis.wardrobe.model import label_code_of

    assert label_code_of("jw1:abcd2345") == "abcd2345"
    for foreign in ("https://example.com", "jw1:ABCD2345", "jw1:abcd23456", "jw2:abcd2345", ""):
        assert label_code_of(foreign) is None, foreign


def test_a_private_piece_is_count_only_outside_his_panel() -> None:
    from jarvis.wardrobe import redact
    from jarvis.wardrobe.model import Piece

    vest = Piece.model_validate(
        {"id": "wi_" + "3" * 12, "category": "base", "type": "vest", "label": "My old vest",
         "colour": "black", "private": True}
    )  # fmt: skip
    shirt = Piece.model_validate(
        {"id": "wi_" + "4" * 12, "category": "tops", "type": "shirt", "label": "Office blue",
         "colour": "navy", "size": {"v": "40"}, "care": [{"v": "hand_wash", "ok": True}]}
    )  # fmt: skip
    for sink in redact.SINKS:
        shown = str(redact.view(vest, sink))
        assert ("My old vest" in shown) is (sink == "panel"), sink
    assert redact.alert_words(vest) == redact.card_words(vest).split(" (")[0] == "a private basic"
    assert redact.card_words(vest, 17) == "a private basic (No. 17)"
    assert redact.alert_words(shirt) == "a navy shirt" and "Office" not in redact.card_words(shirt)
    model = redact.model_view(shirt)
    assert "size" not in model and model["care"] == ["hand_wash"]  # unverified never reaches it
    assert redact.bin_title(shirt) == redact.bin_title(vest) == "A wardrobe piece"
    custom = shirt.model_copy(update={"type": "lungi_fancy"})
    assert redact.alert_words(custom) == "a navy piece"  # his own type words stay his


# ---- 9 · the HTTP contract (wardrobe/http.py, H5) ------------------------------------------------
def test_every_planned_route_has_its_models_under_its_parts_prefix() -> None:
    from jarvis.wardrobe import http
    from jarvis.wardrobe.ports import ROUTE_PREFIX

    planned = {
        ("GET", "/v1/wardrobe"), ("GET", "/v1/wardrobe/pieces/{id}"),
        ("POST", "/v1/wardrobe/scan"), ("POST", "/v1/wardrobe/photos"),
        ("DELETE", "/v1/wardrobe/photos/{id}"), ("GET", "/v1/wardrobe/photos/{id}"),
        ("GET", "/v1/wardrobe/fingerprints"), ("POST", "/v1/wardrobe/fingerprints"),
        ("POST", "/v1/wardrobe/tag"), ("GET", "/v1/wardrobe/tag/estimate"),
        ("GET", "/v1/wardrobe/labels.svg"), ("POST", "/v1/wardrobe/labels"),
        ("GET", "/v1/wardrobe/backup"), ("PUT", "/v1/wardrobe/settings"),
        ("POST", "/v1/wardrobe/restore/check"),
        ("POST", "/v1/wardrobe/restore"), ("GET", "/v1/wardrobe/pilot"),
        ("POST", "/v1/wardrobe/tools/{tool}"), ("GET", "/v1/laundry"),
        ("GET", "/v1/laundry/review"), ("GET", "/v1/outfits"), ("GET", "/v1/outfits/calendars"),
        ("PUT", "/v1/outfits/settings"), ("GET", "/v1/r13"),
    }  # fmt: skip
    assert {(m, p) for m, p, *_ in http.ROUTES} == planned
    for _, path, part, req, reply, errors in http.ROUTES:
        if part in ROUTE_PREFIX:
            assert any(path.startswith(x) for x in ROUTE_PREFIX[part]), path  # type: ignore[index]
        for model in (req, reply):
            if isinstance(model, type):
                assert model.model_config.get("extra") == "forbid", (path, model)
        assert 401 in errors and 429 in errors, path


def test_the_scan_request_bounds_what_a_phone_sends() -> None:
    from jarvis.wardrobe.http import EventIn, FingerprintIn, ScanRequest

    one = {"client_id": "scan-0001", "piece": "wi_" + "5" * 12, "kind": "deposited"}
    assert ScanRequest.model_validate({"events": [one]}).events[0].source == "tap"
    for bad in ({"events": []}, {"events": [one] * 51}, {"events": [{**one, "note": "x" * 121}]}):
        with pytest.raises(ValidationError):
            ScanRequest.model_validate(bad)
    with pytest.raises(ValidationError):
        EventIn.model_validate({**one, "picture": "...."})  # nothing else rides along
    with pytest.raises(ValidationError):
        FingerprintIn.model_validate(
            {"piece": one["piece"], "view": "front", "model": "x", "v": ""}
        )


# ---- 11 · the vision contract and the pixel panels (D8, D9, H6, M7) ------------------------------
def test_the_wardrobe_tasks_are_checked_but_never_kept() -> None:
    from jarvis.vision.results import TASKS, WARDROBE_TASKS, parse_result

    assert TASKS == ("text", "code", "objects", "pose", "quality")  # the kept-results enum
    assert WARDROBE_TASKS == ("embed", "colour", "person", "face")
    base = {"v": 1, "at": 1763000000, "ms": 70, "device": "phone", "ok": True}
    base["quality"] = {"light": 0.5, "sharp": 0.7}
    embed = {
        **base,
        "task": "embed",
        "data": {"v": "A" * 1708, "dims": 1280, "model": "mnv2-int8-1"},
    }
    assert parse_result(embed) is None  # never a kept vision result
    assert parse_result(embed, wardrobe=True) is not None
    assert (
        parse_result({**embed, "data": {**embed["data"], "v": "A" * 1709}}, wardrobe=True) is None
    )
    colour = {
        **base,
        "task": "colour",
        "data": {"name": "multicolour", "second": "navy", "share": 0.4},
    }
    assert parse_result(colour, wardrobe=True) is not None
    face = {**base, "task": "face", "data": {"found": True, "count": 21, "boxes": []}}
    assert parse_result(face, wardrobe=True) is None  # at most 20


def test_vision_assets_know_the_wardrobe_release() -> None:
    from jarvis.vision import assets

    assert assets.WARDROBE_RELEASE == "r13-1"
    five = assets.installed({})
    assert set(five) == {"text", "code", "objects", "pose", "quality"}  # R7's answer unchanged
    both = assets.installed({}, {assets.EMBED_INT8: "application/octet-stream"})
    assert both["embed"] and both["colour"] and not both["face"] and not both["person"]
    assert assets.installed({}, {assets.EMBED_FP32: "x"})["embed"]  # the fallback, if vendored


# the panels that may see pixels: R13's two and R13.1's photo check (tests/test_r131_seams.py
# holds it to the scan module's rules, D12)
PANELS = ("console-camera-panel.js", "console-wardrobe-scan.js", "console-tryon-photo.js")
ENGINE = ("console-vision.js", "console-camera.js")  # the port and the camera's own door
# the drawing modules that use canvas APIs on their OWN canvases (never a camera frame); R13.1's
# figure engine and its textures (B) too, held to their own rules in tests/test_r131_seams.py
DRAWING = ("console-fx.js", "console-3d.js", "console-r111-files.js")
DRAWING += ("console-tryon-3d.js", "console-tryon-cloth.js")
PIXEL_APIS = ("drawImage", "getImageData", "toBlob", "createImageBitmap", "captureStream")
_CALLS = re.compile(
    r"(?:JarvisVision|Vis\(\)|parts\s*\.\s*vision)\s*\.\s*(?:run|stream)\s*\("
    r"|(?:JarvisCamera|Cam\(\)|parts\s*\.\s*camera)\s*\.\s*(?:frame|photo)\s*\("
)


def _code(path: Path) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", _text(path), flags=re.S)  # comments say the rules


@pytest.mark.parametrize("path", sorted(STATIC.glob("console*.js")), ids=lambda p: p.name)
def test_only_the_two_named_panels_take_pixels(path: Path) -> None:
    if path.name in (*PANELS, *ENGINE):
        return
    code = _code(path)
    assert not _CALLS.search(code), path.name
    assert "JarvisCamera" not in code, path.name
    if path.name not in DRAWING:
        for api in PIXEL_APIS:
            assert api not in code, (path.name, api)


def test_the_scan_module_keeps_the_camera_panels_rules() -> None:
    code = _code(STATIC / "console-wardrobe-scan.js")
    for bad in (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "WebSocket",
        "localStorage",
        "JarvisChat",
        ".raw(",
        "FormData",
    ):
        assert bad not in code, bad
    for bad in ("sessionStorage", "indexedDB", "innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert bad not in code, bad
    for call in re.findall(r"(?:JarvisConsole\.api|M\.api)\(\s*([^,)]+)", code):
        assert call.strip().startswith(("'/v1/wardrobe", "'/v1/laundry", "P")), call
    sends = set(re.findall(r"door\.(\w+)\(", code))
    assert sends <= {"wardrobe", "tag"}, sends
    assert _text(STATIC / "console-wardrobe-scan.js").isascii()
    assert "JarvisCameraModes" in code and "register('wardrobe'" in code


def test_the_door_is_the_only_caller_of_the_wardrobes_picture_routes() -> None:
    for path in STATIC.glob("console*.js"):
        code = _code(path)
        if path.name == "console-r7-send.js":
            assert "'/v1/wardrobe/photos?piece='" in code and "'/v1/wardrobe/tag?piece='" in code
            assert "wardrobe, tag, thumb, drop," in code
            continue
        assert not re.search(r"""['"`]/v1/wardrobe/(?:photos|tag)\b""", code), path.name


def test_the_camera_panel_mounts_one_wardrobe_mode_and_stops_it() -> None:
    js = _text(STATIC / "console-camera-panel.js")
    assert "['wardrobe', 'Wardrobe']" in js and "window.JarvisCameraModes = Object.freeze(" in js
    assert "if (id !== 'wardrobe' || MODES[id]" in js
    assert "stopLive(); stopModes(); clear();" in js  # the panel hidden: the mode stops too
    assert "if (S.tab === 'wardrobe') stopLive(); else stopModes();" in js


# ---- 12 · the console's joins (D1) ---------------------------------------------------------------
def test_console_html_is_byte_identical_to_r14s() -> None:
    import hashlib

    got = hashlib.sha256((STATIC / "console.html").read_bytes()).hexdigest()
    assert got == "9f4c0c68f45e46fe150e65e182f4d2ba1132eb556b3ddee0ba3491e4c85450a2"  # 9a8392b
    assert _lines(STATIC / "console.html") == 782


def test_helpers_gains_a_console_only_wardrobe_tab() -> None:
    from jarvis.helpers import kinds

    js = _text(STATIC / "console-helpers.js")
    assert "['wardrobe', 'Wardrobe']" in js and "import('./console-helpers-wardrobe.js')" in js
    assert list(kinds.TABS) == [*kinds.PARTS, "watch"]  # helpers/kinds.py TABS stays five
    tab = _text(STATIC / "console-helpers-wardrobe.js")
    assert "H.register('wardrobe'" in tab and "import('./console-wardrobe-pieces.js')" in tab


def test_the_new_console_files_are_served_and_loaded_by_code() -> None:
    from jarvis.api.console import APP_ASSETS

    names = ("console-helpers-wardrobe.js", "console-wardrobe-pieces.js")
    names += ("console-wardrobe-scan.js", "console-wardrobe.css")
    loader = _text(STATIC / "console-r7.js")
    for name in names:
        assert name in APP_ASSETS and (STATIC / name).is_file(), name
        assert name not in _text(STATIC / "console.html"), name
    assert "import('./console-wardrobe-scan.js')" in loader
    assert "'/static/console-wardrobe.css'" in loader


def test_the_wardrobe_css_only_places_things() -> None:
    css = re.sub(r"/\*.*?\*/", "", _text(STATIC / "console-wardrobe.css"), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)  # no colour literal
    for prop in re.findall(
        r"(?:color|background|font(?:-family)?|box-shadow|border-radius)\s*:\s*([^;]+)", css
    ):
        assert prop.strip().startswith("var(--"), prop
    assert _lines(STATIC / "console-wardrobe.css") <= 200


# ---- size guards and "no real clock" -------------------------------------------------------------
def test_the_size_guards_hold() -> None:
    assert _lines(SRC / "api" / "app.py") <= 735
    assert _lines(SRC / "tools" / "gateway.py") == 760
    assert _lines(SRC / "core" / "brain.py") <= 741
    for path in STATIC.glob("console*.js"):
        assert _lines(path) <= 800, path.name
    assert _lines(STATIC / "console-camera-panel.js") <= 483
    assert _lines(STATIC / "console-r7-send.js") <= 165  # R13.1 I0: person, picture, myPhoto
    assert _lines(STATIC / "console-helpers.js") <= 238
    new_css = [p for p in STATIC.glob("console-wardrobe*.css")]
    assert sum(_lines(p) for p in new_css) <= 300
    for path in (SRC / "wardrobe").rglob("*.py"):
        assert _lines(path) <= 400, path.name
    assert _lines(SRC / "api" / "r13_wiring.py") <= 400


_CLOCK = re.compile(r"datetime\.now\(|date\.today\(|time\.time\(|utcnow|datetime\.today\(")


@pytest.mark.parametrize(
    "path",
    [*sorted((SRC / "wardrobe").rglob("*.py")), *sorted(SRC.glob("offline/phrases_r13.py"))],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_nothing_under_wardrobe_reads_the_real_clock(path: Path) -> None:
    assert not _CLOCK.search(_text(path)), path  # ctx.now() only (D15)


def test_the_wiring_files_have_their_slots() -> None:
    app_py = _text(SRC / "api" / "app.py")
    for needle in (
        "import jarvis.api.r13_wiring as r13",
        "await r13.wire_r13(app, s, docs, audit)",
        "r13=r13.r13_tools(app.state.r13_parts)",
        "**r13.BODY_CAPS,",
        "r13.install_r13_routes(app)",
    ):
        assert app_py.count(needle) == 1, needle
    assert app_py.index("await r14.wire_r14(") < app_py.index("await r13.wire_r13(")
    assert app_py.index("await r13.wire_r13(") < app_py.index("_wire_gateway(app, s, inj")
    personal = _text(SRC / "api" / "personal.py")
    assert personal.index("*r13_privacy_sources(app)") < personal.index(
        "*home_privacy_sources(app)"
    )
    from jarvis.home.watchdog import ADVISORY_JOBS
    from jarvis.offline.phrases_r14 import WITHOUT_AI

    assert "outfit_clock" in ADVISORY_JOBS
    assert "your wardrobe: where a piece is, laundry, today's outfit" in WITHOUT_AI


# ---- 11 · the model files: the script's pins, the manifest, the licences (D8, M8, M15) -----------
VISION = STATIC / "vendor" / "vision"
R13_1 = VISION / "r13-1"


def _assets_script() -> object:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "wardrobe_assets", ROOT / "scripts" / "wardrobe_assets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_wardrobe_release_matches_the_scripts_pins() -> None:
    script = _assets_script()
    assert script.problems() == []  # type: ignore[attr-defined]
    import json

    manifest = json.loads((R13_1 / "MANIFEST.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    assert set(files) == {"mobilenetv2-int8-embed.onnx", "version-RFB-320.onnx"} | {
        "ssd_mobilenet_v1_12-int8.onnx"
    }  # the fp32 fallback is not vendored unless needed
    embed = files["mobilenetv2-int8-embed.onnx"]
    assert embed["sha256"].startswith("c32ba47c") and embed["quant"]["zero_point"] == 0
    assert embed["selfcheck"]["sha256"].startswith("e5b53d7e") and embed["model"] == "mnv2-int8-1"
    assert "section 4" in embed["changes"]
    ssd = files["ssd_mobilenet_v1_12-int8.onnx"]
    assert ssd["licence"] == (
        "MIT (ONNX Model Zoo); weights from the TensorFlow Object Detection API (Apache-2.0)"
    )
    assert manifest["fallback"]["mobilenetv2-fp32-embed.onnx"]["sha256"].startswith("d0049881")
    total = sum(int(e["bytes"]) for e in files.values())
    assert total < 14 * 1024 * 1024  # about 13.2 MB (plan "Risks": repository size)


def test_the_route_serves_the_wardrobe_files_and_the_tasks_are_installed() -> None:
    from jarvis.api import console
    from jarvis.vision import assets

    console.vision_files.cache_clear()
    served13 = console.vision_files(assets.WARDROBE_RELEASE)
    got = assets.installed(console.vision_files(assets.RELEASE), served13)
    assert all(got[t] for t in ("embed", "colour", "person", "face"))


def test_every_wardrobe_licence_is_apache_or_mit_and_the_book_knows_it() -> None:
    from jarvis.buildbook.gen.libs import VENDORED, licence_from_text

    for name, want in (
        ("LICENSE-onnx-models.txt", "Apache-2.0"),
        ("LICENSE-ultraface.txt", "MIT"),
        ("LICENSE-tensorflow-models.txt", "Apache-2.0"),
    ):
        assert licence_from_text(_text(VISION / name)) == want, name
        assert f"vendor/vision/{name}" in VENDORED, name
    notice = _text(VISION / "NOTICE-wardrobe-models.txt")
    assert "MODIFIED" in notice and "non-commercial" in notice


def test_the_book_still_reads_r7s_vision_versions_beside_the_wardrobe_release() -> None:
    from jarvis.buildbook.gen.libs import _manifest_versions

    found = _manifest_versions(Repo.from_git(ROOT))
    assert found.get("manifest:tesseract.js") == "7.0.0"
    assert found.get("manifest:zxing-wasm") == "3.1.6"


# ---- 13 · the skill register (D18) ---------------------------------------------------------------
def test_the_register_files_the_18_wardrobe_tools_in_three_groups() -> None:
    from jarvis.skills.registry import SkillRegister, load_catalogue
    from jarvis.wardrobe.ports import NO_AI_TOOLS, TOOL_OWNER

    reg = SkillRegister(load_catalogue())
    cat = reg.catalogue
    assert not cat.planned  # I1 emptied `planned`: every tool it named is built
    assert NO_AI_TOOLS <= cat.no_ai and not set(TOOL_OWNER) & set(cat.telegram_open)
    for tool in TOOL_OWNER:
        assert len(reg.filed(tool)) == 1, tool
    skill = {t: reg.skill_of(t) for t in TOOL_OWNER}
    assert {skill[t] for t in TOOL_OWNER if t.startswith(("wardrobe_", "laundry_"))} == {"task"}
    assert {skill[t] for t in TOOL_OWNER if t.startswith(("outfit_", "wear_"))} == {"decision"}
    groups = {g.id: g for g in cat.groups}
    assert {"wardrobe", "laundry", "outfits"} <= set(groups)
    for word in ("shirt", "kurta", "sock", "belt"):
        assert word in groups["wardrobe"].words, word
    for word in ("laundry", "dhobi", "dry clean", "iron"):
        assert word in groups["laundry"].words, word
    for word in ("outfit", "wear", "dress code", "pehen"):
        assert word in groups["outfits"].words, word


async def test_no_pattern_or_name_of_the_wardrobe_is_stale_once_planned_is_empty() -> None:
    from test_r14_skill_coverage import linked_gateway

    from jarvis.skills.registry import SkillRegister, load_catalogue

    gw = await linked_gateway()
    problems = SkillRegister(load_catalogue()).problems(gw.registry)
    assert not any(w in p for p in problems for w in ("wardrobe_", "laundry_", "outfit_", "wear_"))


# ---- 15 · the eval runner, staged (M11) ----------------------------------------------------------
def _runner() -> object:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("r13_run", ROOT / "evals" / "r13" / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_r13_runner_passes_staged_and_its_contract_control_fails_it() -> None:
    import json
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "r13" / "run.py"), "--mock"],
        capture_output=True, text=True, env=env, timeout=300, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((ROOT / "evals" / "r13" / "report.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in report["results"]}
    assert {f"contract:{p}_builds" for p in ("catalog", "laundry", "styling", "phone")} <= ids
    assert "contract:refuses_another_parts_tool" in ids
    control = report["negative_control"]
    assert control["suite_failed"] is True and control["failed_cases"]["contract"]
    assert control["stubs_pass"] is False and control["parts_not_built"] == []  # after I1


def test_the_gate_is_flipped_at_i1_and_a_stub_fails_and_every_part_is_built() -> None:
    import asyncio
    from types import SimpleNamespace

    runner = _runner()
    assert runner.STUBS_PASS is False  # type: ignore[attr-defined]  # I1 flipped it: pinned
    assert all(runner.load(p).BUILT for p in runner.PARTS)  # type: ignore[attr-defined]

    async def not_built() -> list[dict[str, object]]:
        return [{"id": "x:not_built_yet", "passed": True, "failures": []}]

    stub = SimpleNamespace(BUILT=False, cases=not_built)
    runner.load = lambda part: stub  # type: ignore[attr-defined]
    results, controls = asyncio.run(runner.run_parts(("catalog",)))  # type: ignore[attr-defined]
    assert [(r["id"], r["passed"]) for r in results] == [("x:not_built_yet", False)]
    assert controls == {}


def test_the_r13_suite_is_gated_in_run_all_mock() -> None:
    text = _text(ROOT / "evals" / "run_all_mock.py")
    line = next(x for x in text.splitlines() if '"r13 (gated)"' in x)
    assert 'HERE / "r13" / "run.py"' in line and line.rstrip().endswith("True),")


# ---- 15 · the fake server Part D builds against (H5) ---------------------------------------------
async def test_the_fake_server_answers_every_route_with_its_model(settings: object) -> None:
    from httpx import ASGITransport, AsyncClient
    from r13_fake_server import fake_app, fake_state
    from r13_fakes import PILOT

    from jarvis.memory.inmemory import InMemorySessionStore
    from jarvis.wardrobe import http

    store, clock = await fake_state()
    app = fake_app(store, clock, settings=settings, store=InMemorySessionStore())
    shirt = PILOT[0].id
    paths = {"{id}": shirt, "{tool}": "wardrobe_find"}
    bodies: dict[str, object] = {
        "/v1/wardrobe/scan": {
            "events": [{"client_id": "scan-00000001", "piece": shirt, "kind": "deposited"}]
        },
        "/v1/wardrobe/fingerprints": {"piece": shirt, "view": "front", "model": "mnv2-int8-1",
                                      "v": "A" * 1708},
        "/v1/wardrobe/labels": {"code": "abcd2345", "piece": shirt},
        "/v1/wardrobe/tools/{tool}": {"arguments": {}},
        "/v1/outfits/settings": {"calendar": None},
        "/v1/wardrobe/settings": {"ai_tagging": True},
    }  # fmt: skip
    query = {
        "/v1/wardrobe/photos": f"?piece={shirt}&view=front",
        "/v1/wardrobe/tag": f"?piece={shirt}",
    }
    query["/v1/wardrobe/tag/estimate"] = f"?piece={shirt}"
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 64
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for method, path, _, req, reply, _ in http.ROUTES:
                url = path
                for k, v in paths.items():
                    url = url.replace(k, v)
                url += query.get(path, "")
                kw: dict[str, object] = {}
                if req == "image/jpeg":
                    kw = {"content": jpeg, "headers": {"content-type": "image/jpeg"}}
                elif req == "application/octet-stream":
                    kw = {"content": b"JWB1-fake"}
                elif path in bodies:
                    kw = {"json": bodies[path]}
                if method == "DELETE" or path == "/v1/wardrobe/photos/{id}":
                    url = url.replace(shirt, "wh_" + "0" * 11 + "1")
                got = await c.request(method, url, **kw)  # type: ignore[arg-type]
                if path == "/v1/wardrobe/photos/{id}" and method == "GET":
                    assert got.status_code in (200, 404), path
                    continue
                assert got.status_code == 200, (method, path, got.text)
                if isinstance(reply, type):
                    reply.model_validate(got.json())  # exactly the contract's shape
                else:
                    assert got.headers["content-type"].startswith(str(reply)), path
