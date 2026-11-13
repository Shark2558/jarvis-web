# tests/test_r7_a_shell.py -- R7 Part A on the server (docs/plans/r7-mobile.md D3, D8, D15, D21):
# the web app manifest has what Chrome needs to install the console, for the app's Trusted Web
# Activity and for the share sheet; its icons are real PNGs of the sizes it claims; both are public
# and set no cookie; the CSP gained exactly `manifest-src 'self'`; the share worker is served with
# the console's CSP from its own folder; with no worker the share route discards the body unread
# and says "Open JARVIS once, then share again."; the status route is owner-only; the share tray's
# privacy row says it lives in this phone's browser only; the switches turn each piece off.
from __future__ import annotations

import fnmatch
import json
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r7_fakes_a import ICONS, ROOT, STATIC, multipart, png_size, raw_post, text

import jarvis.api.app_shell as shell
import jarvis.api.r7_wiring as wiring
from jarvis.api import create_app
from jarvis.api.console import CONSOLE_CSP
from jarvis.config import Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.mobile.ports import LAUNCH_WORDS, MobileContext, MobilePart, never_locked
from jarvis.privacy.ports import CategoryView, PrivacySource

# The console's CSP before R7 (R11.1 on main @ 5519e2d): R7 adds exactly one directive.
CSP_BEFORE_R7 = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "frame-src https://www.youtube-nocookie.com; worker-src 'self'"
)
SHARE_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def _locked(settings: Settings, **update: Any) -> Settings:
    """A server that asks for the token, so a public route is proved public."""
    return settings.model_copy(update={"api_token": SecretStr("not-a-real-token"), **update})


def _manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(text(STATIC / "manifest.webmanifest"))
    return data


# ---- the manifest (D3) --------------------------------------------------------------------------
def test_the_manifest_parses_and_has_what_chrome_needs_to_install_it() -> None:
    m = _manifest()
    assert m["name"] == "JARVIS" and m["short_name"] == "JARVIS"
    assert m["id"] == "/" and m["scope"] == "/"
    assert m["start_url"] == "/?source=app"  # how Part C knows the installed app (D21)
    assert m["display"] == "standalone"
    assert m["theme_color"] == m["background_color"] == "#04070D"
    html = text(STATIC / "console.html")
    assert '<meta name="theme-color" content="#04070D">' in html  # the page's own colour
    assert m.get("prefer_related_applications", False) is False
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes
    assert ("512x512", "maskable") in sizes
    for icon in m["icons"]:
        assert icon["type"] == "image/png" and icon["src"].startswith("/static/icons/")


def test_every_icon_is_a_real_png_of_the_size_it_claims() -> None:
    m = _manifest()
    listed = list(m["icons"]) + [i for s in m["shortcuts"] for i in s["icons"]]
    for icon in listed:
        name = icon["src"].removeprefix("/static/icons/")
        assert name in shell.ICONS, name
        w, h = png_size((ICONS / name).read_bytes())
        assert f"{w}x{h}" == icon["sizes"], name
    assert {p.name for p in ICONS.iterdir()} == set(shell.ICONS)  # nothing unlisted is shipped


def test_the_shortcuts_use_three_of_the_four_launch_words_and_the_apps_address() -> None:
    shortcuts = _manifest()["shortcuts"]
    assert [s["url"] for s in shortcuts] == [
        "/?source=app&do=talk",
        "/?source=app&do=look",
        "/?source=app&do=sos",
    ]
    assert [s["short_name"] for s in shortcuts] == ["Talk", "Camera", "SOS"]
    for s in shortcuts:
        assert s["url"].rsplit("=", 1)[1] in LAUNCH_WORDS
        assert s["icons"] and all(i["sizes"] == "96x96" for i in s["icons"])


def test_the_share_target_posts_files_to_the_share_route() -> None:
    target = _manifest()["share_target"]
    assert target["action"] == shell.SHARE_IN_PATH == wiring.SHARE_IN_PATH == "/app/share/in"
    assert target["method"] == "POST" and target["enctype"] == "multipart/form-data"
    params = target["params"]
    assert {params["title"], params["text"], params["url"]} == {"title", "text", "url"}
    (files,) = params["files"]
    assert files["name"] == "files"
    assert SHARE_TYPES <= set(files["accept"])
    assert not [a for a in files["accept"] if a.startswith("application/") and a not in SHARE_TYPES]
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    assert all(a in SHARE_TYPES or a in extensions for a in files["accept"])


def test_the_manifest_and_icons_ship_in_the_image() -> None:
    """The image installs with `pip install .`: a file missing from package-data 404s in prod."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["jarvis.api"]
    files = ["static/manifest.webmanifest", "static/app-share-sw.js"]
    files += [f"static/icons/{n}" for n in shell.ICONS]
    for rel in files:
        assert (ROOT / "src" / "jarvis" / "api" / rel).is_file(), rel
        assert any(fnmatch.fnmatch(rel, g) for g in globs), f"{rel} not in package-data"


def test_the_csp_gained_exactly_manifest_src_self() -> None:
    assert CONSOLE_CSP == CSP_BEFORE_R7 + "; manifest-src 'self'"


async def test_the_manifest_is_public_sets_no_cookie_and_is_never_locked(
    settings: Settings,
) -> None:
    async with running(_locked(settings)) as (_, c):
        r = await c.get("/manifest.webmanifest")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/manifest+json"
        assert "set-cookie" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.json() == _manifest()
        assert (await c.get("/app/status")).status_code == 401  # owner-only, unlike the manifest
    assert never_locked("GET", "/manifest.webmanifest")


async def test_the_icons_are_served_from_an_allow_list_only(settings: Settings) -> None:
    async with running(_locked(settings)) as (_, c):
        for name in shell.ICONS:
            r = await c.get(f"/static/icons/{name}")
            assert r.status_code == 200 and r.headers["content-type"] == "image/png", name
            assert r.content == (ICONS / name).read_bytes()
            assert "set-cookie" not in r.headers
        for bad in ("nope.png", "..%2fconsole.html", "jarvis-192.PNG", ".png"):
            assert (await c.get(f"/static/icons/{bad}")).status_code == 404, bad
    assert never_locked("GET", "/static/icons/jarvis-192.png")


async def test_without_the_share_switch_the_manifest_has_no_share_target(
    settings: Settings,
) -> None:
    async with running(_locked(settings, app_share_enabled=False)) as (_, c):
        m = (await c.get("/manifest.webmanifest")).json()
        assert "share_target" not in m and m["shortcuts"] == _manifest()["shortcuts"]
        assert (await c.get("/app/share/sw.js")).status_code == 404
        body, kind = multipart({}, [("a.jpg", "image/jpeg", b"\xff\xd8\xff")])
        r = await c.post("/app/share/in", content=body, headers={"content-type": kind})
        assert r.status_code == 200 and shell.SHARE_OFF in r.text


async def test_without_the_mobile_switch_nothing_of_the_app_is_served(settings: Settings) -> None:
    async with running(_locked(settings, mobile_enabled=False)) as (app, c):
        assert (await c.get("/manifest.webmanifest")).status_code == 404
        assert (await c.get("/static/icons/jarvis-192.png")).status_code == 404
        assert (await c.get("/app/share/sw.js")).status_code == 404
        assert (await c.get("/app/share/in")).status_code == 404  # the reload page too
        assert app.state.r7_parts["shell"].ready == "off"


# ---- the share worker and the share route (D15) -----------------------------------------------
async def test_the_share_worker_is_served_from_its_own_folder_with_the_console_csp(
    settings: Settings,
) -> None:
    async with running(_locked(settings)) as (_, c):
        r = await c.get("/app/share/sw.js")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/javascript")
        assert r.headers["content-security-policy"] == CONSOLE_CSP
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["service-worker-allowed"] == "/app/share/"
        assert r.text == text(STATIC / "app-share-sw.js")
    assert never_locked("GET", "/app/share/sw.js") and never_locked("POST", "/app/share/in")


async def test_with_no_worker_the_server_discards_the_share_unread_and_says_what_to_do(
    settings: Settings,
) -> None:
    body, kind = multipart(
        {"title": "Holiday", "text": "made up"},
        [
            ("first.jpg", "image/jpeg", b"\xff\xd8\xff" + b"A" * 300_000),
            ("second.pdf", "application/pdf", b"%PDF-1.4 " + b"B" * 300_000),
        ],
    )
    app = create_app(_locked(settings), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        status, headers, reply, spy = await raw_post(
            app, "/app/share/in", body, {"content-type": kind}
        )
    assert status == 200
    assert spy.pulled == 0  # not one byte of the body was read, by the route or a middleware
    page = reply.decode()
    assert shell.MISSED == "Open JARVIS once, then share again." and shell.MISSED in page
    assert "first.jpg" not in page and "Holiday" not in page  # nothing of the share comes back
    assert headers["content-security-policy"] == CONSOLE_CSP
    assert headers["cache-control"] == "no-store" and headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "<script" not in page and 'href="/"' in page
    assert "set-cookie" not in headers


async def test_an_oversized_share_is_refused_before_it_is_read(settings: Settings) -> None:
    app = create_app(_locked(settings), provider=MockProvider(), store=InMemorySessionStore())
    big = b"x" * (wiring.BODY_CAPS["/app/share/in"] + 1)
    async with app.router.lifespan_context(app):
        status, _, _, spy = await raw_post(app, "/app/share/in", big, {"content-type": "x/y"})
    assert status == 413 and spy.pulled == 0


async def test_a_served_manifest_cannot_be_changed_through_a_caller(settings: Settings) -> None:
    first = shell.manifest(settings)
    first["icons"].append({"src": "/evil"})
    first["shortcuts"].clear()
    again = shell.manifest(settings)
    assert all(i["src"] != "/evil" for i in again["icons"]) and again["shortcuts"]


async def test_the_share_route_answers_a_get_with_the_console(settings: Settings) -> None:
    async with running(_locked(settings)) as (_, c):
        r = await c.get("/app/share/in")
        assert r.status_code == 303 and r.headers["location"] == "/"


# ---- the part: status, privacy, contract ------------------------------------------------------
async def test_the_status_route_says_ready_and_whether_sharing_is_on(settings: Settings) -> None:
    async with running(settings) as (app, c):
        r = await c.get("/app/status")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert r.json() == {"part": "shell", "ready": "ready", "share": True}
        assert isinstance(app.state.r7_parts["shell"], MobilePart)
    async with running(settings.model_copy(update={"app_share_enabled": False})) as (_, c):
        assert (await c.get("/app/status")).json()["share"] is False


def _ctx(s: Settings) -> MobileContext:
    return MobileContext(s=s, docs=None, audit=None, state=lambda _n: None)


def test_the_part_keeps_its_contract_and_gives_the_brain_nothing(settings: Settings) -> None:
    part = wiring.check_part("shell", shell.build(_ctx(settings)))
    assert part.tools == () and part.clock_jobs == () and part.daily_jobs == ()
    assert part.ready == "ready"
    assert "app_lock" not in part.services and "sos_hook" not in part.services
    assert "door" not in part.services
    off = shell.build(_ctx(settings.model_copy(update={"mobile_enabled": False})))
    assert off.ready == "off"


async def test_the_share_tray_has_a_privacy_row_that_says_it_stays_on_this_phone(
    settings: Settings,
) -> None:
    (row,) = shell.build(_ctx(settings)).privacy
    assert isinstance(row, PrivacySource)
    view = await row.describe("owner")
    assert isinstance(view, CategoryView) and view.id == row.id == "share_tray"
    assert view.count is None and view.delete == "none" and view.export is False
    assert view.retention == "24 hours" and "browser" in view.where
    assert "never" in view.what  # the server never holds them before a press
    assert await row.export("owner") is None and await row.delete("owner") == 0


@pytest.mark.parametrize("path", ["/manifest.webmanifest", "/app/share/sw.js", "/app/status"])
def test_every_route_of_the_part_is_one_router(path: str) -> None:
    paths = {getattr(r, "path", "") for r in shell.router.routes}
    assert path in paths
    assert "/static/icons/{name}" in paths and "/app/share/in" in paths


# ---- launch words on a visit another site sent (D8; the server half is I0's, held here too) ----
@pytest.mark.parametrize(
    ("query", "location"),
    [
        ("?source=app&do=talk&open=home&reauth=1", "/?source=app&reauth=1"),
        ("?do=look", "/"),
        ("?open=vault&do=sos&keep=a%26b", "/?keep=a%26b"),
    ],
)
async def test_a_cross_site_visit_loses_do_and_open_and_keeps_every_other_word(
    settings: Settings, query: str, location: str
) -> None:
    async with running(settings) as (_, c):
        r = await c.get("/" + query, headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 302 and r.headers["location"] == location
        for site in ("none", "same-origin", "same-site"):
            assert (await c.get("/" + query, headers={"Sec-Fetch-Site": site})).status_code == 200
