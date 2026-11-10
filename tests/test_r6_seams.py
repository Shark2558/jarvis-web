# tests/test_r6_seams.py
"""R6 I0 seams: the shared hooks the four R6 workstreams build on (docs/plans/r6-build-book.md,
"Seams the I0 adds" items 1-10).

The two keyring purposes (`book_index`, `book_session`), the two passkey purposes (`book_open`,
`book_resume` bound to exactly one guest lock id), the three book alert kinds (important: ring in
waking hours even when only urgent things ring, held in quiet hours), the four Book settings.
The console half (assets in order, `/book/show` with the console's CSP) and the D11 import
boundary of `jarvis.buildbook` are further down.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from jarvis.alerts import AlertKind
from jarvis.config import Settings
from jarvis.integrations.vault import VaultError
from jarvis.keyring import PURPOSES, Keyring
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Signal
from jarvis.permissions.groups import PermissionRejected
from jarvis.permissions.models import (
    BOOK_LOCK_TARGET,
    TARGETED_PURPOSES,
    ChallengeRequest,
    Purpose,
)
from jarvis.permissions.service import purpose_binding

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
KEY = bytes(range(1, 33))
UID = "u_owner"
LOCK = "bl_0123456789ab"
BOOK_KINDS = ("book_sealed", "book_seal_failed", "book_session_closed")
NOON_IST = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)  # 12:00 in Asia/Kolkata
TWO_AM_IST = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)  # 02:00 in Asia/Kolkata


# ---- 1 keyring purposes ------------------------------------------------------------------------
def test_the_book_index_and_session_purposes_have_their_own_keys() -> None:
    assert {"book_index", "book_session"} <= set(PURPOSES)
    ring = Keyring(KEY)
    aad = f"book/index/{UID}/v1"
    blob = ring.cipher("book_index").encrypt(b"releases", aad=aad)
    assert ring.cipher("book_index").decrypt(blob, aad=aad) == b"releases"
    for other in ("book_session", "vault_index", "vault"):
        with pytest.raises(VaultError):
            ring.cipher(other).decrypt(blob, aad=aad)
    # D9: the session token is stored as a MAC in the book_session domain, never in clear
    tag = ring.mac("book_session", "token")
    assert tag != ring.mac("tickets", "token") and ring.mac_matches("book_session", "token", tag)


# ---- 2 passkey purposes --------------------------------------------------------------------------
def test_book_open_and_book_resume_are_targeted_passkey_purposes() -> None:
    for purpose in ("book_open", "book_resume"):
        assert purpose in get_args(Purpose) and purpose in TARGETED_PURPOSES
    req = ChallengeRequest(purpose="book_resume", target=LOCK)
    assert req.target == LOCK


def test_book_open_is_bound_to_the_owner_and_the_purpose_and_takes_no_target() -> None:
    bound = purpose_binding(UID, "book_open", None)
    assert bound == purpose_binding(UID, "book_open", "")
    assert bound != purpose_binding("u_other", "book_open", None)
    assert bound != purpose_binding(UID, "vault_unlock", None)  # a vault proof never opens it
    with pytest.raises(PermissionRejected):
        purpose_binding(UID, "book_open", LOCK)


def test_book_resume_is_bound_to_exactly_one_guest_lock() -> None:
    assert BOOK_LOCK_TARGET == r"^bl_[0-9a-f]{12}$" and re.fullmatch(BOOK_LOCK_TARGET, LOCK)
    other = "bl_ba9876543210"
    assert purpose_binding(UID, "book_resume", LOCK) != purpose_binding(UID, "book_resume", other)
    bad_targets = (
        None,
        "",
        "bl_0123456789a",
        "bl_0123456789abc",
        "BL_0123456789AB",
        "bl_0123456789aG",
        "h_01234567:1",
    )
    for bad in bad_targets:
        with pytest.raises(PermissionRejected):
            purpose_binding(UID, "book_resume", bad)


def test_the_console_passkey_helper_allows_both_book_purposes() -> None:
    js = (STATIC / "console-permissions.js").read_text(encoding="utf-8")
    allow = re.search(r"if \(!\[([^\]]+)\]\.includes\(purpose\)\)", js)
    assert allow, "JarvisPasskey.prove's allow-list"
    listed = set(re.findall(r"'([a-z_]+)'", allow.group(1)))
    assert {"book_open", "book_resume"} <= listed
    assert listed <= set(TARGETED_PURPOSES)


# ---- 3 alert kinds -------------------------------------------------------------------------------
def test_three_book_kinds_join_the_alert_kinds_as_important_daytime_rings() -> None:
    kinds = get_args(AlertKind)
    assert set(BOOK_KINDS) <= set(kinds) and len(kinds) == len(set(kinds)) == 23
    for kind in BOOK_KINDS:
        assert DEFAULT_URGENCY[kind] == "important"
        assert kind in DAYTIME_RING_KINDS


@pytest.mark.parametrize("kind", BOOK_KINDS)
@pytest.mark.parametrize("ring_for", ["urgent", "important"])
def test_a_book_notice_rings_in_waking_hours(kind: str, ring_for: str) -> None:
    # the default is ring_for="urgent": an important kind outside DAYTIME_RING_KINDS stays silent
    signal = Signal(source="system", kind=kind)  # type: ignore[arg-type]
    assert decide(signal, NotifySettings(ring_for=ring_for), NOON_IST).action == "ring"  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", BOOK_KINDS)
def test_a_book_notice_is_held_in_quiet_hours(kind: str) -> None:
    signal = Signal(source="system", kind=kind)  # type: ignore[arg-type]
    assert decide(signal, NotifySettings(), TWO_AM_IST).action == "hold"


def test_the_alerts_card_lists_the_book_kinds_only_with_every_other_important_kind() -> None:
    """I0 rule: a book kind joins the Alerts card's switch list only if every other important
    kind is on it. R4's vitals_critical / health_fault are not, so the book kinds are not either
    (their switch still works through PUT /v1/notify/settings)."""
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    block = js[js.index("const KINDS = [") : js.index("];", js.index("const KINDS = ["))]
    listed = set(re.findall(r"\['([a-z_]+)', '", block))
    important = {k for k, v in DEFAULT_URGENCY.items() if v == "important" and k != "test"}
    if important - set(BOOK_KINDS) <= listed:
        assert set(BOOK_KINDS) <= listed
    else:
        assert not set(BOOK_KINDS) & listed


# ---- 4 settings ----------------------------------------------------------------------------------
def test_book_settings_defaults_and_bounds() -> None:
    s = Settings(_env_file=None)
    assert (s.book_session_minutes, s.book_idle_minutes) == (45, 10)
    assert (s.book_max_total_mb, s.book_talk_questions) == (60, 20)
    for field, good, bad in (
        ("book_session_minutes", (15, 120), (14, 121)),
        ("book_idle_minutes", (5, 30), (4, 31)),
        ("book_max_total_mb", (20, 200), (19, 201)),
        ("book_talk_questions", (1, 50), (0, 51)),
    ):
        for v in good:
            assert getattr(Settings(_env_file=None, **{field: v}), field) == v
        for v in bad:
            with pytest.raises(ValidationError):
                Settings(_env_file=None, **{field: v})
