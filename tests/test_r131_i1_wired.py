# tests/test_r131_i1_wired.py -- R13.1 I1 (I0-NOTES section 5, item 2): the console-only rule on
# the WIRED app. I0's fake server does not enforce it, so here every route the contract marks
# console-only (`http.ROUTES`' last column), the garment routes included, is refused to a script
# holding the owner's token (403 `console_only`, before any body is read) and reaches the part
# from his signed-in console. Nothing reaches Google.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from r13_fakes_a import jpeg

from jarvis.wardrobe.tryon import http

WIRED = Path(__file__).resolve().parents[1] / "evals" / "r13_1" / "wired.py"


def _wired() -> ModuleType:
    found = sys.modules.get("r13_1_wired")
    if found is not None:
        return found
    spec = importlib.util.spec_from_file_location("r13_1_wired", WIRED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["r13_1_wired"] = module
    spec.loader.exec_module(module)
    return module


W = _wired()
CONSOLE = [(m, p) for m, p, _, _, _, _, console in http.ROUTES if console]
IDS = {"/v1/seeme/pictures/": "tp_" + "a" * 12, "/v1/seeme/garments/": "tg_" + "b" * 12}
# What his signed-in console gets from C's part, in a fresh world (no photo, no YES, no picture):
# each route's OWN answer, so a 500 or a refusal from anywhere else can't pass (review I1 L6)
REACHED: dict[tuple[str, str], tuple[int, str | None]] = {
    ("POST", "/v1/seeme/photo"): (200, None),
    ("GET", "/v1/seeme/photo"): (404, "no_photo"),
    ("DELETE", "/v1/seeme/photo"): (200, None),
    ("POST", "/v1/seeme/consent"): (422, "consent_needed"),  # not the version shown to him
    ("POST", "/v1/seeme/pictures"): (409, "consent_needed"),
    ("GET", "/v1/seeme/pictures/{id}"): (404, "gone"),
    ("POST", "/v1/seeme/pictures/{id}/keep"): (404, "gone"),
    ("DELETE", "/v1/seeme/pictures/{id}"): (404, "gone"),
    ("PUT", "/v1/seeme/settings"): (200, None),
    ("POST", "/v1/seeme/garments"): (200, None),
    ("GET", "/v1/seeme/garments/{id}"): (404, "no_garment"),
    ("DELETE", "/v1/seeme/garments/{id}"): (404, "no_garment"),
}


def _path(path: str) -> str:
    for start, rid in IDS.items():
        if path.startswith(start):
            return path.replace("{id}", rid)
    return path


def _kw(method: str, path: str) -> dict[str, Any]:
    if path in ("/v1/seeme/photo", "/v1/seeme/garments") and method == "POST":
        query = "?type=shirt&colour=navy" if path.endswith("garments") else ""
        return {"url": path + query, "content": jpeg(), "headers": {"Content-Type": "image/jpeg"}}
    bodies = {
        "/v1/seeme/consent": {"typed": "YES", "template_version": "c2-000000000000"},
        "/v1/seeme/pictures": {"garment": IDS["/v1/seeme/garments/"], "pieces": [],
                               "confirm_cost": True, "inr_shown": 8.9,
                               "request_id": "tq_" + "0" * 16},
        "/v1/seeme/settings": {"cap_inr": 200},
    }  # fmt: skip
    body = bodies.get(path) or ({"keep": True} if path.endswith("/keep") else None)
    return {"url": _path(path), **({"json": body} if body is not None else {})}


def test_the_contract_names_twelve_console_routes_with_the_garments_among_them() -> None:
    assert len(CONSOLE) == 12
    garments = {(m, p) for m, p in CONSOLE if p.startswith("/v1/seeme/garments")}
    assert garments == {
        ("POST", "/v1/seeme/garments"),
        ("GET", "/v1/seeme/garments/{id}"),
        ("DELETE", "/v1/seeme/garments/{id}"),
    }


@pytest.mark.parametrize(("method", "path"), CONSOLE, ids=[f"{m} {p}" for m, p in CONSOLE])
async def test_a_script_with_the_token_is_refused_and_his_console_reaches_the_part(
    method: str, path: str
) -> None:
    async with W.running() as w:
        kw = _kw(method, path)
        url = kw.pop("url")
        script = await w.send(method, url, **kw)
        assert script.status_code == 403, (script.status_code, script.text[:200])
        assert script.json()["error"] == "console_only"
        again = _kw(method, path)
        again.pop("url")
        with w.signed_in():
            console = await w.send(method, url, **again)
        got = (
            console.status_code,
            console.json().get("error") if console.status_code >= 400 else None,
        )
        assert got == REACHED[(method, path)], (method, path, console.text[:200])
        assert w.google.seen == []  # nothing reached Google either way
