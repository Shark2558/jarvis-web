# tests/test_evals_r11.py -- the R11 eval (evals/r11_helpers) in the unit suite, mock mode: I0's
# `gate` part passes and its control (the caps switched off) makes it fail; every part file
# exists with the shared interface, and an unbuilt part reports only "not built yet". Each builder
# adds its own assertions for its part here (or in its own tests/test_evals_r11_<part>.py).
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "evals" / "r11_helpers"
RUN = HERE / "run.py"
PARTS = ("gate", "today", "house", "nudges", "kitchen", "needles")


def test_every_part_file_has_the_interface() -> None:
    for part in PARTS:
        spec = importlib.util.spec_from_file_location(f"r11_eval_{part}", HERE / f"{part}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / "tests"))
        spec.loader.exec_module(module)
        assert module.PART == part and isinstance(module.BUILT, bool), part
        assert callable(module.cases) and callable(module.control), part


def test_the_gate_part_passes_and_its_control_fails_it() -> None:
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock"], capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    report = json.loads((HERE / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert report["passed"] == report["cases"] and "gate:fourteen-days-on-time" in ids
    control = report["negative_control"]
    assert (
        control["suite_failed"] is True and "gate:caps-per-kind" in control["failed_cases"]["gate"]
    )
    unbuilt = set(control["parts_not_built"])
    for part in unbuilt:
        assert f"{part}:not_built_yet" in ids


def test_every_part_is_built_and_each_control_fails_its_own_part() -> None:
    """I1: all six parts are built (no "not built yet"); the needles part passes after a whole
    day of every part, and its controls fail every needle's own case (masking off: the card
    number; fence off: the CAP instruction in a tool result; each needle planted in each surface,
    tool results included)."""
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock"], capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    report = json.loads((HERE / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert not any(i.endswith(":not_built_yet") for i in ids)
    assert {"needles:card-number-nowhere", "needles:the-day-happened"} <= ids
    control = report["negative_control"]
    assert control["parts_not_built"] == []
    assert set(control["failed_cases"]) == set(PARTS)
    needles = {
        "card-number-nowhere",
        "birth-year-nowhere",
        "emailed-upi-nowhere",
        "cap-instruction-nowhere",
        "pantry-note-nowhere",
        "no-water-count-in-logs",
    }
    assert {f"needles:{n}" for n in needles} <= set(control["failed_cases"]["needles"])
    assert "needles:the-day-happened" not in control["failed_cases"]["needles"]


def test_the_suite_is_gated_in_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if '"r11_helpers (gated)"' in x)
    assert 'HERE / "r11_helpers" / "run.py"' in line and line.rstrip().endswith("True),")


# ---- I1 code review H1: needles over wall-clock stamps and random ids (the flake) -------------
# A stamp's microseconds (`.198810`), a random hex id (`a1988b`) and a log record's own floats
# hold "1988" and "svg" by chance; a substring needle then reported a leak that was not there,
# about once in 30-60 runs. These feed the needles exactly such text, deterministically.
STAMPS = "{'at': '2026-11-12T10:28:30.198810+00:00', 'id': 'a1988b', 'k': 'QsvgZ0b'}"


def _eval_part(part: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"r11_eval_{part}_unit", HERE / f"{part}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "tests"))
    spec.loader.exec_module(module)
    return module


def test_a_clock_stamp_or_a_random_id_is_never_a_birth_year() -> None:
    needles = _eval_part("needles")
    found = needles.findings({s: STAMPS for s in needles.SURFACES}, [STAMPS])
    assert found["birth-year-nowhere"] == [], found
    assert all(v == [] for v in found.values()), found
    for real in ("Asha Example, born 1988", "1988-11-12", "(1988)", "1988"):
        assert needles.findings({"documents": real}, [])["birth-year-nowhere"], real


async def test_a_stamp_in_the_unplanted_day_leaves_every_plant_failing_only_its_own_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needles = _eval_part("needles")
    texts = {s: f"the day's {s} {STAMPS}" for s in needles.SURFACES}
    monkeypatch.setattr(needles, "run_day", _fake_day)
    monkeypatch.setattr(needles, "surfaces", _texts_of(texts))
    planted, base = await needles._planted()
    own = needles.own_case_only(planted, base)
    assert base == set() and own and all(own.values()), sorted(k for k, v in own.items() if not v)


async def test_one_real_finding_in_the_unplanted_day_disables_only_that_needle_s_plants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control's own-case check is relative to the unplanted day: one stray finding there
    cannot turn every other plant into "did not fail its own case"."""
    needles = _eval_part("needles")
    texts = {s: f"the day's {s}" for s in needles.SURFACES}
    texts["brief"] += " auntie's masala tin"
    monkeypatch.setattr(needles, "run_day", _fake_day)
    monkeypatch.setattr(needles, "surfaces", _texts_of(texts))
    planted, base = await needles._planted()
    own = needles.own_case_only(planted, base)
    assert base == {"needles:pantry-note-nowhere"}
    assert {k for k, v in own.items() if not v} == {k for k in own if k.startswith("pantry-note")}


def test_a_random_id_or_ciphertext_is_not_a_stored_link_or_qr() -> None:
    today = _eval_part("today")
    assert not today.link_or_qr_in(STAMPS)
    for real in (
        "upi://pay?pa=x",
        "<svg xmlns='http://www.w3.org/2000/svg'>",
        "data:image/svg+xml",
    ):
        assert today.link_or_qr_in(real), real


def test_a_log_record_s_own_clock_and_ids_are_not_a_logged_birth_year() -> None:
    today = _eval_part("today")
    handler = today._Logs()
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "birthday sent", (), None)
    record.created, record.msecs, record.thread = 1731988000.198810, 198.81, 41988
    record.contact = "c1"
    record.session = "a1988b"
    handler.emit(record)
    text = " ".join(handler.text)
    assert "1731988000" not in text and "41988" not in text, text
    assert "birthday sent" in text and "c1" in text
    assert not today.birth_year_in(text)
    assert today.birth_year_in("Asha Example (1988)")


class _Day:
    class logs:  # noqa: N801 - the World's `logs.lines`, read by `_planted`
        lines: list[str] = []


async def _fake_day() -> _Day:
    return _Day()


def _texts_of(texts: dict[str, str]) -> Any:
    async def surfaces(_w: Any) -> dict[str, str]:
        return dict(texts)

    return surfaces
