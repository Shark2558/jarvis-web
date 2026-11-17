# tests/test_r131_a_errors.py -- R13.1 Part A, review A-1 F3: an unexpected error (a bug, in A or in
# R13's engine) is logged at ERROR with where it happened (the module, line and function: no value
# of his) and answered as an internal error, 500 `internal`; storage trouble stays a warning and
# 503 `unavailable`, and the figure still answers when only R13's records can't be read. Never
# the error's message, never a trace: those can carry his numbers.
from __future__ import annotations

import logging
from typing import Any

import pytest
from r131_fakes_a import NOW, T, a_world

from jarvis.storage.docs import IndexNotReady
from jarvis.wardrobe.catalog.store import WardrobeUnavailable
from jarvis.wardrobe.tryon import looks, store
from jarvis.wardrobe.tryon.http import Refusal, TryonView
from jarvis.wardrobe.tryon.model import NO_FIGURE

SECRET = "height 187"  # what a bug's message might carry: never logged


def _route_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name in ("jarvis.api.tryon", "jarvis.wardrobe.tryon.part")
    ]


async def test_a_bug_in_a_route_is_an_internal_error_logged_where_it_happened(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kw: Any) -> Any:
        raise TypeError(SECRET)

    monkeypatch.setattr(looks, "slot_of", broken)  # a bug while building the reply
    a = await a_world()
    with caplog.at_level(logging.DEBUG):
        async with a.client() as c:
            got = await c.get(f"/v1/tryon/look?pieces=top:{T.shirt}")
    assert got.status_code == 500 and got.headers["cache-control"] == "no-store"
    assert Refusal.model_validate(got.json()).error == "internal"  # not "unavailable"
    [rec] = _route_records(caplog)
    assert rec.levelno == logging.ERROR and rec.exc_info is None
    assert rec.__dict__["error"] == "TypeError" and rec.__dict__["route"] == "look"
    path, line, name = rec.__dict__["at"].split(":")  # A's code, its line, its function
    assert path == "wardrobe/tryon/looks.py" and line.isdigit() and name in ("build", "<genexpr>")
    assert SECRET not in rec.getMessage() and SECRET not in str(rec.__dict__)


@pytest.mark.parametrize("trouble", [
    WardrobeUnavailable("JARVIS couldn't open your wardrobe just now."),  # R13's store
    IndexNotReady("composite index missing"),  # the docs layer
    TimeoutError(),
])  # fmt: skip
async def test_storage_trouble_stays_a_503_and_a_warning(
    trouble: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    a = await a_world()

    async def down(uid: str) -> Any:
        raise trouble

    a.styling.view = down  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG):
        async with a.client() as c:
            got = await c.get("/v1/tryon/look?day=today")
    assert got.status_code == 503 and got.json()["error"] == "unavailable"
    [rec] = _route_records(caplog)
    assert rec.levelno == logging.WARNING and rec.__dict__["error"] == type(trouble).__name__


async def test_a_bug_reading_r13s_records_is_internal_not_an_empty_figure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = await a_world()

    async def bug(uid: str) -> Any:
        raise KeyError(SECRET)

    a.styling.view = bug  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG):
        async with a.client() as c:
            got = await c.get("/v1/tryon")
    assert got.status_code == 500 and got.json()["error"] == "internal"  # never "No figure yet"
    assert [r.levelno for r in _route_records(caplog)] == [logging.ERROR]


async def test_r13s_store_down_still_shows_the_figure_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = await a_world()

    async def down(uid: str) -> Any:
        raise WardrobeUnavailable("JARVIS couldn't open your wardrobe just now.")

    a.styling.view = down  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG):
        async with a.client() as c:
            got = await c.get("/v1/tryon")
    assert got.status_code == 200 and TryonView.model_validate(got.json()).words == NO_FIGURE
    [rec] = _route_records(caplog)
    assert rec.levelno == logging.WARNING and rec.__dict__["at"].endswith(":read")


def test_a_firestore_error_is_storage_trouble_without_importing_its_sdk() -> None:
    kind = type("ServiceUnavailable", (Exception,), {"__module__": "google.api_core.exceptions"})
    assert store.storage_trouble(kind("down"))
    assert store.storage_trouble(store.Off()) and store.storage_trouble(OSError())
    assert not store.storage_trouble(TypeError()) and not store.storage_trouble(KeyError())


def _raised(fn: Any, *args: Any) -> Exception:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - the error under test
        return exc
    raise AssertionError("no error")


def test_where_names_the_innermost_frame_of_jarvis_and_never_a_local_path() -> None:
    paths = store.TryonStore(None, None, prefix="", now=lambda: NOW)
    path, line, name = store.where(_raised(paths.path, "a/b")).split(":")  # not an owner id
    assert (path, name) == ("wardrobe/tryon/store.py", "_owner") and line.isdigit()

    def outside() -> None:
        raise ValueError(SECRET)

    elsewhere = store.where(_raised(outside))  # no frame of jarvis: the file's name only
    assert elsewhere.startswith("test_r131_a_errors.py:") and elsewhere.endswith(":outside")
