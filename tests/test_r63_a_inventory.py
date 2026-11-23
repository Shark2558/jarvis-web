# tests/test_r63_a_inventory.py -- R6.3 part A, D2b and G5 (docs/plans/r6-3-book-content.md): the
# technology inventory. Android's build plugins and libraries, the home kit's images, the bridge's
# own pins, the dev tools; one SPDX spelling a licence; the run-time / build-and-maintenance split;
# the rows in book.json's Stack (R6's rows first, unchanged) and the libraries' licences spelled
# once. A fixture with all five sources (tests/r63_fakes_a.INVENTORY_FILES) and this checkout.
from __future__ import annotations

from pathlib import Path

import pytest
from r63_fakes_a import INVENTORY_FILES, repo_of

from jarvis.buildbook.gen import inventory, libs
from jarvis.buildbook.gen.repo import Repo

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("given", "spdx"),
    [
        ("Apache 2.0", "Apache-2.0"),
        ("Apache License, Version 2.0", "Apache-2.0"),
        ("Apache-2.0", "Apache-2.0"),
        ("MIT License", "MIT"),
        ("3-Clause BSD License", "BSD-3-Clause"),
        ("BSD License", "BSD"),  # which BSD is not stated: kept as "BSD"
        ("MIT License OR Apache 2.0", "MIT OR Apache-2.0"),
        ("EPL-2.0 OR BSD-3-Clause", "EPL-2.0 OR BSD-3-Clause"),
        ("GPL-3.0-only", "GPL-3.0-only"),
        ("Licence-pydantic", "Licence-pydantic"),  # an unknown spelling stays as given
        ("not stated", "not stated"),
    ],
)
def test_one_spdx_spelling_a_licence(given: str, spdx: str) -> None:
    assert inventory.spdx(given) == spdx


def test_the_inventory_s_rows_from_its_five_sources(tmp_path: Path) -> None:
    rows = inventory.items(repo_of(tmp_path, INVENTORY_FILES))
    got = [(r.group, r.name, r.version, r.licence, r.use, r.source) for r in rows]
    toml, compose = "android/gradle/libs.versions.toml", "deploy/home/docker-compose.yml"
    bridge, dev = "deploy/home/bridge-requirements.txt", "pyproject.toml"
    markdy = "tools/markdy/package-lock.json"
    run, build = "run-time", "build and maintenance"
    assert got == [
        ("android library", "androidx.core:core", "1.17.0", "Apache-2.0", run, toml),
        (
            "android library",
            "androidx.health.connect:connect-client",
            "1.1.0",
            "Apache-2.0",
            run,
            toml,
        ),
        ("android build", "com.android.application", "9.5.1", "not stated", build, toml),
        ("android build", "org.jetbrains.kotlin.jvm", "2.4.10", "not stated", build, toml),
        ("home kit image", "eclipse-mosquitto", "2.0.20", "not stated", run, compose),
        ("home kit image", "frigate", "0.17.2", "not stated", run, compose),
        ("home bridge", "aiomqtt", "2.5.1", "BSD-3-Clause", run, bridge),
        ("home bridge", "opencv-python-headless", "4.12.0.88", "not stated", run, bridge),
        ("home bridge", "paho-mqtt", "2.1.0", "EPL-2.0 OR BSD-3-Clause", run, bridge),
        ("dev tool", "pytest", ">=8", "not stated", build, dev),
        ("dev tool", "ruff", ">=0.5", "not stated", build, dev),
        ("dev tool", "@markdy/cli", "1.5.7", "MIT", build, markdy),
    ]  # the cloud lock's fastapi is the Libraries section's; JARVIS's own bridge image is no row


def test_a_checkout_without_the_sources_has_no_inventory(tmp_path: Path) -> None:
    assert inventory.items(repo_of(tmp_path, {"README.md": "x\n"})) == ()


def test_the_rows_join_the_stack_after_r6_s(tmp_path: Path) -> None:
    repo = repo_of(tmp_path, INVENTORY_FILES)
    items = libs.stack(repo).items
    roles = [i.role for i in items]
    assert roles[:2] == ["language", "dependency"]  # R6's rows first, as before
    tail = [(i.role, i.name, i.version, i.source) for i in items[2:]]
    assert tail == [(r.group, r.name, r.version, r.source) for r in inventory.items(repo)]
    assert {inventory.USE[i.role] for i in items} == {"run-time", "build and maintenance"}


def test_the_libraries_licences_are_spelled_once(tmp_path: Path) -> None:
    repo = repo_of(tmp_path, INVENTORY_FILES)
    (lib,) = libs.libraries(repo, lambda _n: "Apache Software License, Version 2.0")
    assert lib.licence == "Apache-2.0" and lib.flag is None


def test_the_inventory_of_this_checkout() -> None:
    repo = Repo.from_git(ROOT)
    rows = inventory.items(repo)
    groups = {r.group for r in rows}
    assert groups == {
        "android library",
        "android build",
        "home kit image",
        "home bridge",
        "dev tool",
    }
    by = {(r.group, r.name): r for r in rows}
    assert by[("android build", "com.android.application")].version == "9.5.1"
    assert all(r.licence == "Apache-2.0" for r in rows if r.group == "android library")
    assert {n for g, n in by if g == "home kit image"} == {
        "eclipse-mosquitto",
        "frigate",
        "home-assistant",
    }
    locked = {n for n, _ in libs.locked(repo)}
    assert not any(r.name in locked for r in rows if r.group == "home bridge")
    assert ("dev tool", "@markdy/cli") in by and ("dev tool", "pytest") in by
    assert all(inventory.spdx(r.licence) == r.licence for r in rows)
