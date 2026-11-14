# tests/test_r6_wiring_seams.py -- R6 I0 seams on the app and the console (docs/plans/
# r6-build-book.md "Seams the I0 adds" 5 and 9): `_wire_features` / `_wire_slice12` moved out of
# api/app.py unchanged, the three R6 slots in their places, the show lock INSIDE the sign-in
# session middleware, the R6 stubs, every R6 console file allow-listed in order, `/book/show` with
# the console's own CSP, the Book dock button and panel shell, and the 423 hop in `api()`.
from __future__ import annotations

import ast
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

import jarvis.api.app as app_module
from jarvis.api import create_app
from jarvis.api.book_lock import ShowLockMiddleware
from jarvis.api.console import APP_ASSETS, CONSOLE_CSP
from jarvis.api.r6_wiring import (
    R6_JOB_NAMES,
    R6_STATE,
    install_show_lock,
    r6_tick_jobs,
    wire_r6,
)
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "jarvis" / "api"
STATIC = API / "static"
APP_PY = API / "app.py"
R6_ASSETS = [
    "console-book.js",
    "console-book-reader.js",
    "console-book.css",
    "console-book-show.js",
    "console-book-voice.js",
    "console-book-3d.js",
    "console-book-scenes.js",
    "console-book-scenes-flow.js",
    "console-book-scenes-data.js",
    "console-book-2d.js",
    "console-book-talk.js",
    "book.css",
]
SCENE_MODULES = [
    "console-book-scenes.js",
    "console-book-scenes-flow.js",
    "console-book-scenes-data.js",
]


def _defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


# ---- 5. app.py: the extraction and the three slots ----------------------------------------------
def test_the_feature_wiring_left_app_py() -> None:
    gone = {"_wire_features", "_wire_slice12", "build_undo"}
    assert not gone & _defs(APP_PY)
    assert {"wire_features", "wire_slice12", "build_undo"} <= _defs(API / "feature_wiring.py")
    src = APP_PY.read_text(encoding="utf-8")
    assert "from jarvis.api.feature_wiring import" in src
    assert len(src.splitlines()) <= 750  # 773 at R5.1, 739 after the I0 extraction (R6 + I1 room)


def _line_index(lines: list[str], needle: str) -> int:
    hits = [i for i, line in enumerate(lines) if needle in line]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


def test_the_three_r6_slots_sit_where_the_plan_puts_them() -> None:
    lines = APP_PY.read_text(encoding="utf-8").splitlines()
    assert _line_index(lines, "await wire_r6(app, s, docs, audit)") == (
        _line_index(lines, "await wire_r4(app, s, docs, audit)") + 1
    )
    routes = _line_index(lines, "install_r6_routes(app)")
    assert routes == _line_index(lines, "install_r4_routes(app)") + 1
    assert routes < _line_index(lines, "app.include_router(console_router)")
    assert _line_index(lines, "install_show_lock(app, s)") + 1 == _line_index(
        lines, "_install_google_sign_in(app, s)"
    )


def _google(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": ["owner@example.com"],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )


class _Marker(BaseHTTPMiddleware):
    async def dispatch(self, request: Any, call_next: Any) -> Any:
        return await call_next(request)


def _order(app: FastAPI) -> list[Any]:
    """Outermost first: Starlette builds the stack from `user_middleware` in list order."""
    return [m.cls for m in app.user_middleware]


def test_the_show_lock_ends_up_inside_the_session_middleware(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Settings] = []

    def lock(app: FastAPI, s: Settings) -> None:
        calls.append(s)
        app.add_middleware(_Marker)

    monkeypatch.setattr(app_module, "install_show_lock", lock)
    app = create_app(_google(settings), provider=MockProvider(), store=InMemorySessionStore())
    order = _order(app)
    assert len(calls) == 1 and order.index(SessionMiddleware) < order.index(_Marker)
    # token mode: no cookie session, so no lock middleware either (bearer callers are untouched)
    calls.clear()
    create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    assert calls == []


def test_the_show_lock_slot_installs_cs_middleware(settings: Settings) -> None:
    app = FastAPI()
    install_show_lock(
        app, _google(settings)
    )  # I1: C's ShowLockMiddleware (tests/test_r6_wiring.py)
    assert [m.cls for m in app.user_middleware] == [ShowLockMiddleware]


async def test_without_the_keyring_wire_r6_leaves_the_book_off(settings: Settings) -> None:
    app = FastAPI()
    await wire_r6(app, settings, MemoryDocs(), AuditLog())  # no JARVIS_TOKEN_KEY: D6 book OFF
    assert all(getattr(app.state, name) is None for name in R6_STATE)
    assert "book_lock" in R6_STATE and len(R6_STATE) == len(set(R6_STATE))
    assert r6_tick_jobs(app) == ()
    assert R6_JOB_NAMES == frozenset({"book_seal", "book_sweep"})


@pytest.fixture
async def app_client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        assert all(getattr(app.state, name) is None for name in R6_STATE)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


# ---- 9. console files, /book/show and the deck --------------------------------------------------
def test_every_r6_console_file_is_allow_listed_in_order() -> None:
    names = list(APP_ASSETS)
    at = names.index(R6_ASSETS[0])  # R11's Helpers files follow them (tests/test_r11_wiring.py)
    assert names[at : at + len(R6_ASSETS)] == R6_ASSETS
    assert names[at + len(R6_ASSETS)] == "console-helpers.js"
    for name in R6_ASSETS:
        assert (STATIC / name).is_file(), name
        want = "text/css" if name.endswith(".css") else "application/javascript"
        assert APP_ASSETS[name] == want
    assert (STATIC / "book.html").is_file()


async def test_book_show_serves_the_shell_with_the_console_csp(app_client: AsyncClient) -> None:
    r = await app_client.get("/book/show")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CONSOLE_CSP
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    html = r.text
    scripts = re.findall(r'<script (?:type="module" )?src="/static/([^"]+)"', html)
    assert scripts[:2] == ["console-fx.js", "console-permissions.js"]
    assert "console-book-3d.js" in scripts and not set(SCENE_MODULES) & set(scripts)
    assert "console.js" not in scripts and "console-deck.js" not in scripts  # no deck here
    for name in re.findall(r'(?:src|href)="/static/([^"?]+)', html):
        got = await app_client.get(f"/static/{name}")
        assert got.status_code == 200, name


def test_the_3d_module_loads_the_scene_modules_itself() -> None:
    js = (STATIC / "console-book-3d.js").read_text(encoding="utf-8")
    for name in SCENE_MODULES:
        assert f"import('./{name}')" in js


def test_the_deck_has_the_book_dock_button_panel_and_more_sheet_item() -> None:
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    assert len(html.splitlines()) < 800
    people = re.search(r'<button class="dk" type="button" data-open="people"[^>]*>', html)
    book = re.search(r'<button class="dk" type="button" data-open="book"[^>]*>', html)
    assert people and book
    assert book.group(0) == people.group(0).replace("people", "book")
    assert (
        '<section class="panel card" id="p-book" data-panel="book" aria-labelledby="t-book" hidden>'
        in html
    )
    assert '<h2 id="t-book">Book</h2>' in html
    # R7 I0 seam 10: the More sheet's entry is built by console-dock.js from the dock
    assert "    book: '" in (STATIC / "console-dock.js").read_text(encoding="utf-8")
    assert html.index('src="/static/console-book-reader.js"') < html.index(
        'src="/static/console-book.js"'
    )
    deck = (STATIC / "console-deck.js").read_text(encoding="utf-8")
    order = re.search(r"const ORDER = \[([^\]]*)\]", deck)
    assert order is not None and "'book'" in order.group(1)
    assert re.search(r"\n\s+book: \{ x:", deck)  # a default place, or loadLayout would throw


def test_api_hops_to_the_show_on_a_423() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    body = js[js.index("async function api(path") : js.index("async function raw(path")]
    # R7 I0 seam 14: a 423 is read by its error code (show_locked: the show; device_locked: a cover)
    assert "if (r.status === 423) await lockedBy(r);" in body
    assert body.index("r.status === 423") < body.index("if (!r.ok)")
    raw = js[js.index("async function raw(path") : js.index("function showLocked()")]
    assert "if (r.status === 423) await lockedBy(r);" in raw
    hop = js[js.index("function showLocked()") : js.index("// ---- sign-in gate")]
    assert "async function lockedBy(r)" in hop and "showLocked(); }" in hop
    # SEC-2: replace, so no Back entry returns to the console page
    assert "location.replace('/book/show')" in hop and "throw err" in hop


def test_the_r6_console_stubs_stay_small_and_textcontent_only() -> None:
    for name in R6_ASSETS:
        text = (STATIC / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= (300 if name.endswith(".css") else 400), name
        assert "innerHTML" not in text and "eval(" not in text, name
        assert text.isascii(), name
