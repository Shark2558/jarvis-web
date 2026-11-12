# tests/test_r11_seams.py -- R11 I0 seams (docs/plans/r11-free-helpers.md "Seams the I0 adds"):
# the version, the thirteen helper alert kinds and their place in the one policy, storm control
# for nudges and disaster warnings, the five keyring purposes, the six permission rows, the
# settings, the fixed names the parts share, the No-AI phrasebook, the brief's Helpers section,
# the build book's layer and the guide's card. The gate: tests/test_r11_gate.py. The app wiring,
# routes and console: tests/test_r11_wiring.py.
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from r11_fakes import NOON_IST, TWO_AM_IST

import jarvis
from jarvis.alerts import R11_ALERT_KINDS, AlertKind
from jarvis.api.home_wiring import RESERVED_HOME_JOBS
from jarvis.api.personal import RESERVED_JOB_NAMES
from jarvis.api.r4_wiring import R4_JOB_NAMES
from jarvis.api.r6_wiring import R6_JOB_NAMES
from jarvis.brief.models import BriefData, HelpersSection
from jarvis.brief.render import render_text
from jarvis.buildbook.gen.layers import LAYER_OF
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers import kinds
from jarvis.helpers.brief import MAX_SECTION_LINES, HelpersBrief
from jarvis.keyring import PURPOSES, Keyring
from jarvis.notify.held import summary
from jarvis.notify.models import NO_SWITCH, NotifySettings
from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS, decide
from jarvis.notify.ports import DEFAULT_URGENCY, Decision, Signal
from jarvis.notify.storm import MAX_NUDGES_PER_HOUR, NUDGE_KINDS, Storm
from jarvis.notify.telegram_out import R1_TOGGLE
from jarvis.offline.mode import MAX_PHRASES, BrainMode
from jarvis.offline.rules import NoAICall, NoAIRoute, route_no_ai
from jarvis.permissions.groups import GROUPS, get_group, groups_for

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"
REMINDERS = (
    "bill_due",
    "birthday",
    "chore_due",
    "maintenance_due",
    "weather_warning",
    "breach_notice",
)
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
KEY = bytes(range(1, 33))


def test_the_version_is_eleven() -> None:
    assert jarvis.__version__.startswith("11.")  # the exact number: tests/test_about.py


# ---- alert kinds (D5) ---------------------------------------------------------------------------
def test_thirteen_helper_kinds_make_thirty_six_and_each_belongs_to_one_part() -> None:
    every = get_args(AlertKind)
    assert len(R11_ALERT_KINDS) == 13 and set(R11_ALERT_KINDS) <= set(every)
    assert len(every) == len(set(every)) == 38 and set(DEFAULT_URGENCY) == set(every)  # R11.1: +2
    assert kinds.part_kinds() == frozenset(R11_ALERT_KINDS)
    owners = [p for k in R11_ALERT_KINDS for p in kinds.PARTS if k in kinds.KINDS_OF[p]]
    assert len(owners) == 13  # exactly one part each
    assert set(kinds.NUDGE_KINDS) == EPHEMERAL_KINDS == NUDGE_KINDS


def _at(kind: str, now: datetime, s: NotifySettings | None = None) -> Decision:
    return decide(Signal(source="nudge", kind=kind), s or NotifySettings(), now)  # type: ignore[arg-type]


def test_a_disaster_warning_rings_through_the_night() -> None:
    assert DEFAULT_URGENCY["disaster_alert"] == "urgent"
    assert _at("disaster_alert", TWO_AM_IST).action == "ring"
    assert _at("disaster_alert", NOON_IST).action == "ring"


@pytest.mark.parametrize("kind", REMINDERS)
def test_a_reminder_rings_by_day_and_is_held_at_night(kind: str) -> None:
    assert DEFAULT_URGENCY[kind] == "important" and kind in DAYTIME_RING_KINDS
    assert kind not in EPHEMERAL_KINDS
    assert _at(kind, NOON_IST).action == "ring"  # even with "only urgent things ring" (default)
    assert _at(kind, TWO_AM_IST).action == "hold"


@pytest.mark.parametrize("kind", kinds.NUDGE_KINDS)
def test_a_nudge_rings_by_day_and_is_dropped_never_held_at_night(kind: str) -> None:
    assert DEFAULT_URGENCY[kind] == "important" and kind in DAYTIME_RING_KINDS
    assert _at(kind, NOON_IST).action == "ring"
    night = _at(kind, TWO_AM_IST)
    assert (night.action, night.reason) == ("drop", "stale_at_night")
    vip_night = NotifySettings(ring_for="important")
    assert _at(kind, TWO_AM_IST, vip_night).action == "drop"


def test_a_weather_note_is_quiet() -> None:
    assert DEFAULT_URGENCY["weather_note"] == "info"
    assert _at("weather_note", NOON_IST).action == "silent"
    assert _at("weather_note", TWO_AM_IST).action == "drop"


@pytest.mark.parametrize("kind", R11_ALERT_KINDS)
def test_every_helper_kind_has_the_owners_switch(kind: str) -> None:
    assert kind not in NO_SWITCH and kind not in R1_TOGGLE
    for switch, action in (("off", "drop"), ("feed", "drop")):
        assert _at(kind, NOON_IST, NotifySettings(kinds={kind: switch})).action == action


def test_held_helper_reminders_are_named_in_the_morning_summary() -> None:
    items = [{"kind": k, "at": "2026-11-10T01:00:00+05:30"} for k in REMINDERS]
    text = summary(items)
    for words in ("bill reminder", "birthday", "chore", "home upkeep", "weather warning", "breach"):
        assert words in text, text


def test_the_alerts_card_lists_the_helper_kinds_in_order() -> None:
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    block = js[js.index("const KINDS = [") : js.index("];", js.index("const KINDS = ["))]
    listed = re.findall(r"\['([a-z_]+)', '", block)
    # R11.1 added its two kinds after them (tests/test_r11_1_seams.py)
    assert listed[-15:-2] == list(R11_ALERT_KINDS) and len(listed) == len(set(listed))


# ---- storm control (D5) -------------------------------------------------------------------------
def _nudge(kind: str) -> Signal:
    return Signal(source="nudge", kind=kind)  # type: ignore[arg-type]


def test_nudges_have_a_ceiling_an_hour_and_a_gap_per_kind() -> None:
    storm, ring = Storm(), Decision(action="ring", reason="important", urgency="important")
    t = NOON_IST
    assert storm.admit("u", _nudge("nudge_hydrate"), ring, t).admit
    again = storm.admit("u", _nudge("nudge_hydrate"), ring, t + timedelta(minutes=19))
    assert (again.admit, again.reason) == (False, "nudge_gap")
    assert storm.admit("u", _nudge("nudge_hydrate"), ring, t + timedelta(minutes=20)).admit
    # five kinds, three rounds 21 minutes apart inside one hour: 15 tries, at most 8 go
    many, got = Storm(), []
    for i in range(15):
        at = t + timedelta(minutes=21 * (i // 5) + i % 5)
        got.append(many.admit("w", _nudge(kinds.NUDGE_KINDS[i % 5]), ring, at))
    assert sum(v.admit for v in got) == MAX_NUDGES_PER_HOUR
    assert {v.reason for v in got if not v.admit} == {"nudge_cap"}


def test_a_disaster_warning_is_never_capped_only_de_duplicated() -> None:
    storm, ring = Storm(), Decision(action="ring", reason="urgent", urgency="urgent")
    for i in range(50):  # fifty different warnings in a few minutes: all go
        sig = Signal(source="nudge", kind="disaster_alert", subject=f"cap-{i}")
        assert storm.admit("u", sig, ring, NOON_IST + timedelta(seconds=i)).admit
    same = Signal(source="nudge", kind="disaster_alert", subject="cap-1")
    assert storm.admit("u", same, ring, NOON_IST + timedelta(minutes=5)).reason == "duplicate"
    assert storm.admit("u", same, ring, NOON_IST + timedelta(minutes=31)).admit


# ---- keyring, rows, settings --------------------------------------------------------------------
def test_five_keyring_purposes_each_with_its_own_key() -> None:
    new = ("bills", "spend", "wellbeing", "alerts_place", "kitchen")
    assert set(new) <= set(PURPOSES) and len(PURPOSES) == len(set(PURPOSES)) == 18
    ring = Keyring(KEY)
    for purpose in new:
        blob = ring.cipher(purpose).encrypt(b"x", aad=f"{purpose}/u/v1")
        assert ring.cipher(purpose).decrypt(blob, aad=f"{purpose}/u/v1") == b"x"
        others = [p for p in new if p != purpose]
        with pytest.raises(Exception):  # noqa: B017 - a key for one purpose opens no other
            ring.cipher(others[0]).decrypt(blob, aad=f"{purpose}/u/v1")


ROWS = {
    "bills": ("Bills", "See and keep your bills and due dates", R2),
    "bill_pay": ("Bills", "Get a bill payment ready for your UPI PIN", R3),
    "household": ("Home helpers", "Chores, home upkeep and your free-time list", R2),
    "nudges": ("Nudges", "Nudges and your top priority", R2),
    "outdoor": (
        "Weather and alerts",
        "Weather, disaster alerts and breach notices for your area",
        R2,
    ),
    "kitchen": ("Kitchen", "Pantry, recipes, nutrition and grocery spend", R2),
}


def test_six_rows_after_connectors_and_before_maps() -> None:
    ids = [g.id for g in GROUPS]
    at = ids.index("connectors")
    assert ids[at + 1 : at + 7] == list(ROWS) and ids[-2:] == ["maps", "youtube"]


@pytest.mark.parametrize("gid", list(ROWS))
def test_the_helper_rows(gid: str) -> None:
    g = get_group(gid)
    assert g is not None and (g.section, g.label, g.risk) == ROWS[gid]
    assert g.irreversible is (gid == "bill_pay") and g.hint and "₹" not in g.hint


def test_preparing_a_payment_is_only_in_the_irreversible_row() -> None:
    assert {g.id for g in groups_for("bill_pay_prepare", R3)} == {"bill_pay"}
    assert {g.id for g in groups_for("bill_payee_set", R3)} == {"bill_pay"}
    assert {g.id for g in groups_for("bill_add", R2)} == {"bills"}
    assert {g.id for g in groups_for("contacts_birthdays", R1)} == {"contacts"}
    assert {g.id for g in groups_for("calendar_kitchen_blocks", R2)} == {"calendar_change"}


def test_every_tool_family_lands_in_exactly_one_helper_row() -> None:
    for part, families in kinds.TOOL_FAMILIES.items():
        for fam in families:
            name = fam + "x" if fam.endswith("_") else fam
            rows = {g.id for g in groups_for(name, R2)}
            assert len(rows) == 1, (part, fam, rows)


BOUNDS = (
    ("helpers_enabled", True, None),
    ("weather_enabled", True, None),
    ("disaster_alerts_enabled", True, None),
    ("nudges_max_per_day", 16, (1, 40)),
    ("nudges_max_per_hour", 4, (1, 8)),
    ("helpers_clock_budget_s", 20.0, (5.0, 40.0)),
    ("weather_poll_minutes", 60, (15, 180)),
    ("disaster_poll_minutes", 10, (5, 60)),
)


@pytest.mark.parametrize(("name", "default", "bounds"), BOUNDS)
def test_the_helper_settings(
    name: str, default: object, bounds: tuple[float, float] | None
) -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert getattr(s, name) == default and (Settings.model_fields[name].description or "").strip()
    if bounds is None:
        return
    lo, hi = bounds
    for bad in (lo - 1, hi + 1):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{name: bad})  # type: ignore[call-arg]


def test_the_storm_ceiling_is_the_settings_maximum() -> None:
    assert Settings.model_fields["nudges_max_per_hour"].metadata[-1].le == MAX_NUDGES_PER_HOUR


# ---- the fixed names the parts share (D2) -------------------------------------------------------
def test_job_names_are_unique_and_never_an_older_jobs() -> None:
    names = [n for jobs in (*kinds.CLOCK_JOBS.values(), *kinds.DAILY_JOBS.values()) for n in jobs]
    names += [kinds.CLOCK_JOB, kinds.DAILY_JOB, kinds.SWEEP_JOB]
    taken = RESERVED_JOB_NAMES | RESERVED_HOME_JOBS | R4_JOB_NAMES | R6_JOB_NAMES
    assert len(names) == len(set(names)) and not set(names) & taken


def test_privacy_ids_collections_and_tabs_are_unique_and_complete() -> None:
    ids = [kinds.GATE_PRIVACY_ID, *(i for v in kinds.PRIVACY_IDS.values() for i in v)]
    assert len(ids) == len(set(ids)) == 8 and all(i.startswith("helpers_") for i in ids)
    cols = [c for v in kinds.COLLECTIONS.values() for c in v]
    assert len(cols) == len(set(cols)) == 15
    assert list(kinds.TABS) == list(kinds.PARTS) == ["today", "house", "nudges", "kitchen"]
    assert kinds.tool_allowed("today", "bill_pay_prepare")
    assert not kinds.tool_allowed("today", "chore_done") and not kinds.tool_allowed(
        "kitchen", "bill_x"
    )
    assert kinds.tool_allowed("kitchen", "calendar_kitchen_blocks")
    assert not kinds.tool_allowed("kitchen", "calendar_create_event")


def test_the_guide_card_names_every_collection_and_both_outside_services() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    card = guide[guide.index("#### C60 · Helpers (R11)") : guide.index("### Layer 6")]
    data = re.search(r"\| Data it keeps \| (.*) \|", card)
    assert data is not None
    spans = {s.split("/")[0] for s in re.findall(r"`([^`]+)`", data.group(1))}
    assert {c for v in kinds.COLLECTIONS.values() for c in v} <= spans
    services = re.search(r"\| Outside services \| (.*) \|", card)
    assert services is not None and {"Open-Meteo", "NDMA SACHET"} <= {
        x.strip() for x in services.group(1).split(",")
    }
    assert LAYER_OF["helpers"] == "L5"


# ---- No-AI phrasebook (D18) ---------------------------------------------------------------------
def _stop_standup(text: str, now: datetime) -> NoAIRoute | None:
    if re.fullmatch(r"(?i)\s*don'?t remind me to stand up\s*[.!]?", text):
        return NoAIRoute((NoAICall("nudge_stop", {"kind": "nudge_standup"}),))
    return None


def _broken(text: str, now: datetime) -> NoAIRoute | None:
    raise RuntimeError("a broken phrasebook")


def test_the_helpers_phrases_run_first_and_a_broken_one_is_skipped() -> None:
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    text = "don't remind me to stand up"
    plain = route_no_ai(text, now)
    assert plain.calls == () and "remind you" in plain.reply  # without them: "remind you when?"
    got = route_no_ai(text, now, (_broken, _stop_standup))
    assert got.calls == (NoAICall("nudge_stop", {"kind": "nudge_standup"}),)
    assert route_no_ai("show my vitals", now, (_stop_standup,)).calls[0].tool == "vitals_show"


def test_brain_mode_carries_the_phrasebook() -> None:
    mode = BrainMode(Settings(_env_file=None))  # type: ignore[call-arg]
    assert mode.phrases == ()
    mode.add_phrases([_stop_standup])
    assert mode.phrases == (_stop_standup,)
    with pytest.raises(ValueError):
        mode.add_phrases([_stop_standup] * MAX_PHRASES)


# ---- the brief's Helpers section ----------------------------------------------------------------
class _Lines:
    def __init__(self, name: str, lines: object, fail: bool = False) -> None:
        self.name, self._lines, self._fail = name, lines, fail

    async def lines(self, uid: str, tz: object, day: date) -> object:
        if self._fail:
            raise RuntimeError("down")
        return self._lines


async def test_the_helpers_section_takes_each_parts_lines_bounded_and_clean() -> None:
    parts = [
        _Lines("today", ["Electricity ₹1,240 due tomorrow", "Priya's birthday today", "x", "4th"]),
        _Lines("house", ["Weather:\n31 °C \x07 rain after 15:00 · Open-Meteo"]),
        _Lines("nudges", "not a list"),
        _Lines("kitchen", ["k"] * 9, fail=True),
    ]
    got = await HelpersBrief(lambda: parts).section("u", UTC, date(2026, 11, 10))
    assert got is not None and got.lines == (
        "Electricity ₹1,240 due tomorrow",
        "Priya's birthday today",
        "x",
        "Weather: 31 °C rain after 15:00 · Open-Meteo",
    )
    many = [_Lines(str(i), ["a", "b", "c"]) for i in range(5)]
    full = await HelpersBrief(lambda: many).section("u", UTC, date(2026, 11, 10))
    assert full is not None and len(full.lines) == MAX_SECTION_LINES
    assert await HelpersBrief(lambda: []).section("u", UTC, date(2026, 11, 10)) is None


def test_the_brief_text_shows_the_helpers_section() -> None:
    data = BriefData(
        date="2026-11-10", tz="Asia/Kolkata", helpers=HelpersSection(lines=("Bill due",))
    )
    assert "HELPERS\n  Bill due" in render_text(data)
    assert "HELPERS" not in render_text(BriefData(date="2026-11-10", tz="Asia/Kolkata"))
