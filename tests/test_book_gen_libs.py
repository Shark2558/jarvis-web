# tests/test_book_gen_libs.py
"""R6 D2: the Libraries & licences and Stack sections (`gen.libs`). Python libraries come from
requirements.lock with the licence of the installed dist (License-Expression -> License ->
classifiers -> "not stated"); vendored code, models and fonts from their licence files. Copyleft
(GPL / AGPL / LGPL with no permissive choice) and non-commercial licences are flagged, and each
flag is also a Limitation."""

from __future__ import annotations

from pathlib import Path

import pytest
from book_gen_fakes import COMMIT_DATE, ROOT, fixture_repo

from jarvis.buildbook.gen import libs
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.sections import Library

OSI = "License :: OSI Approved :: "


@pytest.mark.parametrize(
    ("expression", "field", "classifiers", "want"),
    [
        ("MIT", "", [], "MIT"),
        ("Apache-2.0 OR BSD-3-Clause", "BSD", [], "Apache-2.0 OR BSD-3-Clause"),
        (None, "BSD-3-Clause", [f"{OSI}MIT License"], "BSD-3-Clause"),
        (None, "Line one\nLine two of a full text", [f"{OSI}MIT License"], "MIT License"),
        (None, "x" * 200, [], "not stated"),
        (None, "", [f"{OSI}MIT License", f"{OSI}Apache Software License"],
         "MIT License OR Apache Software License"),
        (None, None, ["Programming Language :: Python"], "not stated"),
        (None, "UNKNOWN", [], "not stated"),
    ],
)  # fmt: skip
def test_the_licence_of_a_dist_follows_the_d2_order(
    expression: str | None, field: str | None, classifiers: list[str], want: str
) -> None:
    assert libs.licence_from_meta(expression, field, classifiers) == want


@pytest.mark.parametrize(
    ("licence", "flag"),
    [
        ("MIT", None),
        ("Apache-2.0", None),
        ("GPL-3.0-or-later", "copyleft"),
        ("GNU General Public License v3 (GPLv3)", "copyleft"),
        ("LGPL-2.1", "copyleft"),
        ("AGPL-3.0", "copyleft"),
        ("LGPL-3.0 OR MIT", None),  # a permissive choice exists
        ("GPL-2.0 AND MIT", "copyleft"),
        ("CC-BY-NC-SA-4.0", "non_commercial"),
        ("not stated", None),
        ("MPL-2.0", None),
    ],
)
def test_flags(licence: str, flag: str | None) -> None:
    assert libs.flag_of(licence) == flag


def test_licence_files_are_recognised_by_their_text() -> None:
    static = ROOT / "src" / "jarvis" / "api" / "static"
    read = lambda p: (static / p).read_text(encoding="utf-8")  # noqa: E731
    assert libs.licence_from_text(read("vendor/LICENSE-three.txt")) == "MIT"
    assert libs.licence_from_text(read("vendor/ort/LICENSE-onnxruntime.txt")) == "MIT"
    assert libs.licence_from_text(read("wakeword/LICENSE.txt")) == "CC-BY-NC-SA-4.0"
    assert libs.licence_from_text(read("wakeword/LICENSE-openwakeword-code.txt")) == "Apache-2.0"
    assert libs.licence_from_text(read("fonts/OFL-orbitron.txt")) == "OFL-1.1"
    assert libs.licence_from_text("GNU GENERAL PUBLIC LICENSE Version 3") == "GPL-3.0"
    assert libs.licence_from_text("some words") == "not stated"


def test_the_lock_is_read_name_and_version(tmp_path: Path) -> None:
    r = Repo.from_git(fixture_repo(tmp_path))
    assert libs.locked(r) == (("fastapi", "0.115.0"), ("httpx", "0.27.2"), ("pydantic", "2.9.2"))


def test_python_libraries_take_the_licence_lookup_and_flag(tmp_path: Path) -> None:
    r = Repo.from_git(fixture_repo(tmp_path))
    table = {"fastapi": "MIT", "httpx": "GPL-3.0", "pydantic": "not stated"}
    got = {lib.name: lib for lib in libs.libraries(r, table.__getitem__)}
    assert got["fastapi"] == Library(
        name="fastapi", version="0.115.0", kind="python", licence="MIT", role="web"
    )
    assert got["httpx"].flag == "copyleft"
    assert got["pydantic"].licence == "not stated" and got["pydantic"].flag is None


def test_the_real_libraries_and_the_wake_model_flag() -> None:
    r = Repo.from_git(ROOT)
    got = libs.libraries(r, lambda _name: "MIT")
    by = {(lib.kind, lib.name): lib for lib in got}
    assert len([lib for lib in got if lib.kind == "python"]) == len(libs.locked(r))
    three = by[("vendored", "three.js")]
    assert (three.version, three.licence) == ("0.187.0", "MIT")
    model = by[("model", "openWakeWord models")]
    assert model.flag == "non_commercial" and model.version == "0.5.1"
    assert by[("font", "Orbitron")].licence == "OFL-1.1"
    assert [lib.name for lib in got] == [lib.name for lib in sorted(got, key=libs.sort_key)]


def test_installed_licence_reads_dist_metadata() -> None:
    assert libs.installed_licence("pydantic") == "MIT"
    assert libs.installed_licence("no-such-dist-r6") == "not stated"


def test_flagged_licences_become_limitations() -> None:
    lib = Library(
        name="openWakeWord models",
        version="0.5.1",
        kind="model",
        licence="CC-BY-NC-SA-4.0",
        flag="non_commercial",
        role="voice",
    )
    ok = Library(name="fastapi", version="1", kind="python", licence="MIT")
    (lim,) = libs.licence_limits((lib, ok), "R6")
    assert lim.kind == "licence" and lim.release == "R6"
    assert "openWakeWord models" in lim.text and "non-commercial" in lim.text


def test_the_stack_of_the_real_repo() -> None:
    items = libs.stack(Repo.from_git(ROOT)).items
    roles = {(i.role, i.name) for i in items}
    assert ("language", "Python") in roles and ("base image", "python") in roles
    assert {("ci job", "test"), ("ci job", "deploy")} <= roles
    assert ("vendored", "three.js") in roles and ("dependency", "fastapi") in roles
    base = next(i for i in items if i.role == "base image")
    assert base.version == "3.12-slim" and base.source == "Dockerfile"


def test_the_stack_of_the_fixture(tmp_path: Path) -> None:
    items = libs.stack(Repo.from_git(fixture_repo(tmp_path))).items
    assert [(i.role, i.name, i.version) for i in items] == [
        ("language", "Python", ">=3.11"),
        ("base image", "python", "3.12-slim"),
        ("dependency", "fastapi", "0.115.0"),
        ("dependency", "httpx", "0.27.2"),
        ("dependency", "pydantic", "2.9.2"),
        ("ci job", "test", ""),
        ("ci job", "deploy", ""),
    ]


def test_an_empty_checkout_has_an_empty_stack(tmp_path: Path) -> None:
    r = Repo.from_dir(tmp_path, sha="e" * 40, committed_at=COMMIT_DATE)
    assert libs.stack(r).items == () and libs.libraries(r, lambda _n: "MIT") == ()
