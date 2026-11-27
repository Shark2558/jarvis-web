# tests/test_r52_v4_console_wake.py -- R5.2 V4 (row 83): the console's side of his own "Hey Jarvis"
# without a browser: console-wakeword-own.js is served, linked and talks only to the wake-word
# routes through the console's transport; its numbers are the kit's; console-wakeword.js keeps its
# one fetch, its one import and its privacy rules, and only consults the helper.
# (tests/browser/test_r52_v4_wake_own.py runs both in Chromium.)
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient

from jarvis.api.console import APP_ASSETS
from jarvis.localspeech.wakeword import formats

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
OWN = "console-wakeword-own.js"


def _js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", _js(name), flags=re.S)


async def test_the_helper_is_an_allow_listed_no_store_script_linked_from_the_page(
    client: AsyncClient,
) -> None:
    assert APP_ASSETS[OWN] == "application/javascript"
    r = await client.get(f"/static/{OWN}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    html = (await client.get("/")).text
    assert f'<script src="/static/{OWN}" defer></script>' in html


def test_the_helper_uses_only_the_console_transport_and_the_wake_word_routes() -> None:
    code = _code(OWN)
    for banned in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "EventSource",
        "postMessage",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "innerHTML",
        "eval(",
        "new Function",
        "http://",
        "https://",
        "getUserMedia",
        "document.",
    ):
        assert banned not in code, banned
    assert "window.JarvisConsole.api" in code and "window.JarvisChat.raw" in code
    assert re.findall(r"'(/v1/[^']*)'", code) == ["/v1/voice/profile/wakeword"]
    for suffix in ("'/verifier'", "'/model'", "'/train'"):
        assert f"BASE + {suffix}" in code
    assert (
        "window.JarvisWakeOwn = Object.freeze({ status, verifier, model, train, rescorer });"
        in code
    )


def test_the_helpers_numbers_are_the_kits_and_the_pinned_embedding_model() -> None:
    js = _js(OWN)

    def const(name: str) -> str:
        found = re.search(rf"\b{name} = ([^;,]+)[;,]", js)
        assert found, name
        return found.group(1).strip()

    assert int(const("FRAMES")) == formats.FRAMES and int(const("DIM")) == formats.DIM
    assert int(const("VERIFIER_MAX")) == formats.VERIFIER_MAX_BYTES
    assert int(const("MODEL_MAX")) == formats.OWNED_MAX_BYTES
    assert const("EMBEDDING_SHA256") == f"'{formats.console_pins()[formats.EMBEDDING_MODEL]}'"
    assert const("OWNER_LICENCE") == "'LicenseRef-Owner'"
    assert "'jarvis-wake-verifier'" in js  # formats.VERIFIER_FORMAT
    assert "subtle.digest('SHA-256'" in js  # a file is used only with the announced hash


def test_the_detector_keeps_its_one_fetch_one_import_and_only_asks_the_helper() -> None:
    js = _js("console-wakeword.js")
    assert re.findall(r"\bfetch\(\s*([^,)]+)", js) == ["MODEL_BASE + name"]
    assert set(re.findall(r"import\(\s*([^)]+?)\s*\)", js)) == {"ORT_BASE + 'ort.wasm.min.mjs'"}
    assert js.count("window.JarvisWakeOwn") == 2  # the header comment and fromOwn()
    assert "const own = window.JarvisWakeOwn;" in js
    assert "verifier.rescore(base, features)" in js  # after today's score, on the same window
    assert "return loadOnce(true);" in js  # his model refused by the runtime: today's model
    for banned in ("/v1/", "localStorage", "indexedDB", "postMessage", "XMLHttpRequest"):
        assert banned not in js, banned


def test_both_scripts_stay_small() -> None:
    for name in (OWN, "console-wakeword.js"):
        assert len(_js(name).splitlines()) <= 800, name
