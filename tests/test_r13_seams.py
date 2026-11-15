# tests/test_r13_seams.py -- R13 I0 seams (docs/plans/r13-wardrobe.md "The I0 seam list", 1-16):
# the version and the book's release name, four alert kinds and every table that names one, two
# key purposes, three permission rows and the save cap, the bin's `wardrobe_item` kind, the
# Telegram personal switch, "never Approve all", the settings, the parts' contract, the states
# table, the redaction views, the HTTP contract, the wiring, the vision contract and the pixel
# panels, the console's joins (stubs), the skill register, the guide's planned cards, the eval
# runner's staged gate, the model files' manifest, the size guards and "no real clock".
from __future__ import annotations

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
    assert jarvis.__version__ == "13.0.0"  # R13 I0 (lower than 14.0.2: nothing compares it, D21)


def test_the_real_repository_is_r13_and_its_plan_comes_first() -> None:
    repo = Repo.from_git(ROOT)
    assert plans.release_label(repo) == "R13"
    assert plans.plan_paths(repo)[0] == "docs/plans/r13-wardrobe.md"


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
    assert keyring.PURPOSES[-2:] == ("wardrobe", "wardrobe_photos")
    assert len(keyring.PURPOSES) == len(set(keyring.PURPOSES)) == 24
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
        ("wardrobe_max_pieces", 601),
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
