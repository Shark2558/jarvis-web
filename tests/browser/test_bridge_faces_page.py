# tests/browser/test_bridge_faces_page.py -- the laptop Faces page (R3 D13) in a real browser, served by
# the bridge's own app on 127.0.0.1 with a fake Frigate library: login code, the person list by code,
# an upload for a consented id, a wrong code, and the page's own CSP (0 JS errors, 0 CSP reports).
# ruff: noqa: E501  (long comment lines and the embedded page / script fixtures)
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_homebridge_faces import JPEG, A, consent, rig

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

CODE = "correct-horse-battery"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Any]]:
    import uvicorn

    from jarvis.homebridge.local_page import create_local_app

    fl, lib, _ = rig(tmp_path)
    consent(fl, A)
    port = _free_port()
    app = create_local_app(fl, CODE, port=port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}", lib
    server.should_exit = True
    thread.join(timeout=5)


def until(page: Any, check: Any) -> None:
    for _ in range(100):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError("timed out")


def test_login_list_and_upload(served: tuple[str, Any], tmp_path: Path) -> None:
    url, lib = served
    img = tmp_path / "face.jpg"
    img.write_bytes(JPEG)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(url + "/faces")
        page.wait_for_selector("#login:not([hidden])")
        page.fill("#code", "wrong")
        page.click("#login button")
        until(page, lambda: "isn't right" in page.inner_text("#status"))
        page.fill("#code", CODE)
        page.click("#login button")
        page.wait_for_selector("#people li code")
        assert page.inner_text("#people li code") == A
        assert "0 picture(s)" in page.inner_text("#people li")
        page.set_input_files("#people input[type=file]", str(img))
        until(page, lambda: "1 picture(s)" in page.inner_text("#people li"))
        assert len(lib.pictures[A]) == 1
        assert page.evaluate("document.cookie") == ""  # the session cookie is HttpOnly
        page.reload()
        page.wait_for_selector("#people li code")  # the session survives a reload
        b.close()
    assert all("401" in e for e in errors)  # only the expected not-signed-in and wrong-code answers
