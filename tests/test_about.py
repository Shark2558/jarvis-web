# tests/test_about.py -- R6.1 D4: one version source, and the build date the image was stamped
# with (never the request time). `jarvis.about` feeds the Vitals "About JARVIS" line.
from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

import pytest

import jarvis
from jarvis import about
from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider

ROOT = Path(__file__).resolve().parents[1]


def test_the_version_lives_in_one_place() -> None:
    """The one literal of this release's number in the tests; every other test derives it.
    pyproject.toml has no number of its own: setuptools reads `jarvis.__version__` (review L2)."""
    assert jarvis.__version__ == "11.1.1"  # R11.1 hotfix 1 (was 11.1.0 at R11.1)
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in meta["project"] and "version" in meta["project"]["dynamic"]
    assert meta["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "jarvis.__version__"}


def test_the_api_app_carries_the_one_version(settings: Settings, provider: MockProvider) -> None:
    """R6.1 I1: the FastAPI app's own version (OpenAPI `info.version`) is `jarvis.__version__`,
    not a number of its own (it said 0.0.1 until R6.1)."""
    app = create_app(settings, provider=provider)
    assert app.version == jarvis.__version__
    assert app.openapi()["info"]["version"] == jarvis.__version__


def test_setuptools_reads_the_version_from_the_package() -> None:
    pyprojecttoml = pytest.importorskip("setuptools.config.pyprojecttoml")
    cfg = pyprojecttoml.read_configuration(ROOT / "pyproject.toml", expand=True)
    assert cfg["project"]["version"] == jarvis.__version__


def test_version_is_shown_with_a_v() -> None:
    assert about.version() == f"v{jarvis.__version__}"
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


BAD_STAMPS = [
    "",
    "yesterday",
    "2026-13-01",
    "11 Nov 2026",
    "2026-11-11T25:00:00Z",
    "x" * 500,
    "9" * 64,
    "\x00",
    "2026-11-11T05:30:00[Asia/Kolkata]",
    # R6.1 review M1: a time that leaves year 1..9999 once moved to the owner's zone
    "9999-12-31T23:59:59Z",
    "0001-01-01T00:00:00+14:00",
    "9999-12-31T23:59:59-14:00",
    # a day no image was built on (a clock reset to its epoch), shown by the console as unknown
    "0001-01-01",
    "0001-01-01T00:00:00Z",
    "1999-12-31T12:00:00Z",
]


@pytest.mark.parametrize("raw", BAD_STAMPS)
def test_a_bad_stamp_is_unknown_never_an_error(raw: str) -> None:
    assert about.build_date(environ={about.BUILD_DATE_ENV: raw}, stamp=None) == about.UNKNOWN


@pytest.mark.parametrize("raw", BAD_STAMPS)
def test_a_bad_stamp_file_is_unknown_never_an_error(tmp_path: Path, raw: str) -> None:
    stamp = tmp_path / "BUILD_DATE"
    stamp.write_text(raw, encoding="utf-8")
    assert about.build_date(environ={}, stamp=stamp) == about.UNKNOWN


@pytest.mark.parametrize("zone", ["America", "a" * 300, "", "../etc", "\x00"])
def test_a_bad_zone_falls_back_never_an_error(zone: str) -> None:
    env = {about.BUILD_DATE_ENV: "2026-11-10T20:00:00Z"}
    assert about.build_date(environ=env, stamp=None, zone=zone) == "11 Nov 2026"


def test_without_any_zone_data_the_day_is_utcs(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_zones(name: str) -> None:
        raise about.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(about, "ZoneInfo", no_zones)
    env = {about.BUILD_DATE_ENV: "2026-11-10T20:00:00Z"}
    assert about.build_date(environ=env, stamp=None) == "10 Nov 2026"


def test_fields_never_raise_and_say_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Whatever goes wrong reading the date, the Vitals answer still carries both fields."""

    def boom(**_: object) -> str:
        raise RuntimeError("a bug in the date code")

    monkeypatch.setattr(about, "build_date", boom)
    about.fields.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="jarvis.about"):
            got = about.fields("Asia/Kolkata")
            again = about.fields("Asia/Kolkata")
    finally:
        about.fields.cache_clear()
    assert got == again == {"version": about.version(), "build_date": about.UNKNOWN}
    said = [r for r in caplog.records if r.name == "jarvis.about"]
    assert len(said) == 1 and "a bug in the date code" not in said[0].getMessage()


def test_a_bad_stamp_is_logged_once_per_process(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(about.BUILD_DATE_ENV, "9999-12-31T23:59:59Z")
    monkeypatch.setattr(about, "PACKAGED_STAMP", None)
    about.fields.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="jarvis.about"):
            for _ in range(3):
                assert about.fields("Asia/Kolkata")["build_date"] == about.UNKNOWN
    finally:
        about.fields.cache_clear()
    said = [r for r in caplog.records if r.name == "jarvis.about"]
    assert len(said) == 1 and "9999" not in said[0].getMessage()


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
        got = about.fields("Asia/Kolkata")
        assert got == {"version": f"v{jarvis.__version__}", "build_date": "11 Nov 2026"}
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
