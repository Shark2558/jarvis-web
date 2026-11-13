# tests/test_r7_c_static.py -- R7 Part C, read from the source (r7-mobile.md D0, D6, D21):
# the console modules are ASCII, build with textContent only, use the console's own transport and
# wait for the sign-in; the stylesheet only places things with existing tokens (<= 150 lines); the
# door never reads a session; nothing but the app mark's one write turns the app lock on; the
# fifth 423 reader (the show page's) leaves device_locked alone. Also the part's build and its
# privacy row (count, export without keys, delete = unlink every phone).
from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest
from r7_fakes_c import CSRF, add_passkey, browser, linked_phone, owner_uid, phone_app, phone_service

from jarvis.api import phone as phone_api
from jarvis.config import Settings
from jarvis.mobile.ports import MobileContext
from jarvis.phone import applock, door, handlers
from jarvis.phone.part import OFF, READY, build
from jarvis.privacy.ports import CategoryView

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
JS = ("console-r7-phone.js", "console-r7-lock.js")
CSS = STATIC / "console-r7-phone.css"
PHONE_PKG = ROOT / "src" / "jarvis" / "phone"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", JS)
def test_the_console_modules_are_ascii_and_build_with_text_only(name: str) -> None:
    src = _text(STATIC / name)
    assert src.isascii(), name
    for banned in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert banned not in src, (name, banned)
    assert "fetch(" not in src, (
        name
    )  # a part uses the console's own transport (cookie, CSRF header)
    assert "jarvis:ready" in src and "JarvisConsole.ready" in src  # nothing before sign-in
    assert len(src.splitlines()) <= 800


def test_the_stylesheet_only_places_things_with_existing_tokens() -> None:
    css = _text(CSS)
    assert css.isascii() and len(css.splitlines()) <= 150
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body)  # no colour literal
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", body)
    for banned in ("font-family", "box-shadow", "border-radius", "@import", "url("):
        assert banned not in body, banned
    for font in re.findall(r"font:([^;}]+)", body):
        assert "var(--tech)" in font  # the same type as the Telegram and Home link codes


def test_the_fifth_423_reader_leaves_the_app_lock_to_its_cover() -> None:
    talk = _text(STATIC / "console-book-talk.js")
    assert "e.status === 423 && e.code !== 'device_locked'" in talk
    console = _text(STATIC / "console.js")
    assert "if ((await code423(r)) === 'device_locked') deviceLocked(); showLocked();" in console
    assert console.count("lockedBy(") >= 5  # api, raw, the recheck, the boot, and its definition


def test_the_door_never_reads_or_writes_a_session() -> None:
    for fn in (phone_api.phone_door, phone_api.phone_link, phone_api.asset_links):
        assert "session" not in inspect.getsource(fn), fn.__name__
    for mod in (door, handlers):
        assert "session" not in _text(Path(mod.__file__ or "")), mod.__name__


def test_only_the_app_mark_turns_the_lock_on_and_nothing_turns_it_off() -> None:
    writes = []
    for path in [*PHONE_PKG.glob("*.py"), ROOT / "src" / "jarvis" / "api" / "phone.py"]:
        for line in _text(path).splitlines():
            if "APP_KEY" in line and ("] =" in line or "pop(" in line or "del " in line):
                writes.append(line.strip())
    assert writes == ["session[APP_KEY] = now"]


def test_nothing_of_a_key_reaches_a_log_line() -> None:
    for path in PHONE_PKG.glob("*.py"):
        for call in re.findall(r"log\.\w+\((.*?)\)\n", _text(path), flags=re.S):
            for word in ("public_key", "fingerprint", "signature", "nonce", "code_hash", "name"):
                assert f'"{word}"' not in call, (path.name, word)


def test_the_activity_rule_has_no_background_write_in_it() -> None:
    assert {"/v1/book/show/beat", "/v1/brief/seen"} <= applock.BACKGROUND_WRITES


# ---- the part's build ------------------------------------------------------------------------
def _ctx(settings: Settings, **extra: Any) -> MobileContext:
    from jarvis.storage.docs import MemoryDocs

    return MobileContext(
        s=settings.model_copy(update=extra), docs=MemoryDocs(), audit=None, state=lambda _: None
    )


def test_the_part_offers_its_door_routes_the_lock_and_one_privacy_row(settings: Settings) -> None:
    part = build(_ctx(settings))
    assert part.name == "phone" and part.ready == READY and part.tools == ()
    assert set(part.services["door"]) == {"hello", "inbox"}
    assert callable(part.services["app_lock"]) and len(part.privacy) == 1
    off = build(_ctx(settings, mobile_enabled=False))
    assert off.ready == OFF and "door" not in off.services and "app_lock" not in off.services


# ---- the privacy row -------------------------------------------------------------------------
@pytest.fixture
async def app(settings: Settings) -> Any:
    async with phone_app(settings) as a:
        yield a


async def test_the_privacy_row_counts_exports_without_keys_and_deletes_by_unlinking(
    app: Any,
) -> None:
    (row,) = app.state.r7_parts["phone"].privacy
    view = await row.describe(owner_uid())
    assert isinstance(view, CategoryView) and view.count == 0 and view.delete == "none"
    async with browser(app) as c:
        device, _ = await linked_phone(app, c)
        await linked_phone(app, c)
    view = await row.describe(owner_uid())
    assert view.count == 2 and view.delete == "simple" and view.export and view.recoverable
    exported = await row.export(owner_uid())
    assert exported is not None and len(exported["phones"]) == 2
    flat = str(exported)
    assert "public_key" not in flat and "fingerprint" not in flat and device in flat
    assert exported["app_lock"] == {"on": True, "passkeys_from_the_app": 0}
    assert await row.delete(owner_uid()) == 2
    assert (await row.describe(owner_uid())).count == 0
    async with browser(app) as c:
        assert (await c.get("/v1/phone")).json()["phones"] == []


async def test_the_privacy_dashboard_lists_the_row(app: Any) -> None:
    async with browser(app) as c:
        await add_passkey(c)
        r = await c.get("/v1/privacy", headers=CSRF)
        assert r.status_code == 200, r.text
        ids = [cat["id"] for cat in r.json()["categories"]]
    assert "phones" in ids
    assert phone_service(app).s.phone_link_max == 3
