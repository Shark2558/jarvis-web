# tests/test_about.py -- R6.1 D4: one version source, and the build date the image was stamped
# with (never the request time). `jarvis.about` feeds the Vitals "About JARVIS" line.
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import jarvis
from jarvis import about

ROOT = Path(__file__).resolve().parents[1]


def test_the_version_lives_in_one_place_and_pyproject_agrees() -> None:
    assert jarvis.__version__ == "6.1.0"
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["version"] == jarvis.__version__


def test_version_is_shown_with_a_v() -> None:
    assert about.version() == "v6.1.0"
    assert re.fullmatch(about.VERSION_SHOWN, about.version())


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("2026-11-11T05:30:00Z", "11 Nov 2026"),
        ("2026-11-11T05:30:00+00:00", "11 Nov 2026"),
        ("2026-11-10T20:00:00Z", "11 Nov 2026"),  # 01:30 in India: the owner's day
        ("2026-11-11", "11 Nov 2026"),  # a bare date is taken as written
        ("2026-01-05T10:00:00+05:30", "5 Jan 2026"),
        ("  2026-11-11T05:30:00Z\n", "11 Nov 2026"),  # a stamp file's newline
    ],
)
def test_a_build_stamp_reads_as_the_owner_writes_dates(raw: str, shown: str) -> None:
    assert about.build_date(environ={about.BUILD_DATE_ENV: raw}, stamp=None) == shown


@pytest.mark.parametrize(
    "raw", ["", "yesterday", "2026-13-01", "11 Nov 2026", "2026-11-11T25:00:00Z", "x" * 500]
)
def test_a_bad_stamp_is_unknown_never_an_error(raw: str) -> None:
    assert about.build_date(environ={about.BUILD_DATE_ENV: raw}, stamp=None) == about.UNKNOWN


def test_without_a_stamp_the_date_is_unknown_never_today() -> None:
    assert about.build_date(environ={}, stamp=None) == "unknown"
    assert about.build_date(environ={}, stamp=Path("/nonexistent/BUILD_DATE")) == "unknown"


def test_the_stamp_baked_into_the_image_is_read(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD_DATE"
    stamp.write_text("2026-11-11T06:00:00Z\n", encoding="utf-8")
    assert about.build_date(environ={}, stamp=stamp) == "11 Nov 2026"


def test_an_explicit_env_stamp_wins_over_the_baked_file(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD_DATE"
    stamp.write_text("2026-11-01T06:00:00Z", encoding="utf-8")
    env = {about.BUILD_DATE_ENV: "2026-11-11T06:00:00Z"}
    assert about.build_date(environ=env, stamp=stamp) == "11 Nov 2026"


def test_a_bad_env_stamp_falls_back_to_the_baked_file(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD_DATE"
    stamp.write_text("2026-11-11T06:00:00Z", encoding="utf-8")
    assert about.build_date(environ={about.BUILD_DATE_ENV: "soon"}, stamp=stamp) == "11 Nov 2026"


def test_an_oversized_or_binary_stamp_file_is_unknown(tmp_path: Path) -> None:
    big = tmp_path / "big"
    big.write_text("2026-11-11" + " " * 5000, encoding="utf-8")
    binary = tmp_path / "bin"
    binary.write_bytes(b"\xff\xfe\x00")
    assert about.build_date(environ={}, stamp=big) == "unknown"
    assert about.build_date(environ={}, stamp=binary) == "unknown"


def test_the_date_is_shown_in_the_owners_zone() -> None:
    env = {about.BUILD_DATE_ENV: "2026-11-10T20:00:00Z"}
    assert about.build_date(environ=env, stamp=None, zone="UTC") == "10 Nov 2026"
    assert about.build_date(environ=env, stamp=None, zone="Not/AZone") == "11 Nov 2026"


def test_fields_are_the_two_the_vitals_payload_carries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(about.BUILD_DATE_ENV, "2026-11-11T06:00:00Z")
    about.fields.cache_clear()
    try:
        assert about.fields("Asia/Kolkata") == {"version": "v6.1.0", "build_date": "11 Nov 2026"}
    finally:
        about.fields.cache_clear()


def test_the_image_stamps_its_build_time_as_package_data() -> None:
    """The Dockerfile writes src/jarvis/BUILD_DATE before `pip install .`; package data carries it
    into site-packages; git and the gcloud upload never carry a stale local one."""
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stamp = next(ln for ln in docker.splitlines() if "src/jarvis/BUILD_DATE" in ln)
    assert stamp.startswith("RUN ") and "date -u" in stamp
    assert docker.index(stamp) < docker.index("pip install --no-build-isolation --no-deps .")
    assert docker.index("COPY src ./src") < docker.index(stamp)
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert about.STAMP_FILE in meta["tool"]["setuptools"]["package-data"]["jarvis"]
    assert "src/jarvis/BUILD_DATE" in (ROOT / ".gitignore").read_text(encoding="utf-8")
