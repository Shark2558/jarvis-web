# tests/browser/test_permissions.py — Approvals → Permissions and "Approve with passkey" in a real
# Chromium (slice 10 D). The passkey ceremony is real end to end: Chromium's virtual authenticator
# (CDP WebAuthn.addVirtualAuthenticator, user verification on) answers navigator.credentials, and
# the real server (permissions_server.py: everything real but the model) verifies with py_webauthn.
# Covers: the collapsed section and its summary, Allow / Ask first / Never (irreversible rows offer
# two), setting up a passkey, an irreversible card approved with it (exactly one send), a cancelled
# check left as a plain message on the card (nothing sent), "not supported in this browser", and a
# server without a public address. 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import CSP_SPY, DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOKEN = "browser-permissions-token-not-a-secret"
AUTHENTICATOR = {
    "protocol": "ctap2",
    "transport": "internal",
    "hasResidentKey": True,
    "hasUserVerification": True,
    "isUserVerified": True,
    "automaticPresenceSimulation": True,
}


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def perm_url() -> Iterator[str]:
    """The real app (scripted model) at http://localhost:<port> — its own relying party."""
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    port = _port()
    url = f"http://localhost:{port}"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token",
        "JARVIS_API_TOKEN": TOKEN,
        "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0",
        "JARVIS_PUBLIC_BASE_URL": url,
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "permissions_server.py"), str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 30
    while True:
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            raise RuntimeError(f"permissions server exited early:\n{err}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            if time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError("permissions server did not become healthy") from None
            time.sleep(0.2)
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _get(url: str, path: str) -> Any:
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _with_authenticator(c: Console) -> Any:
    cdp = c.ctx.new_cdp_session(c.page)
    cdp.send("WebAuthn.enable", {"enableUI": False})
    auth = cdp.send("WebAuthn.addVirtualAuthenticator", {"options": AUTHENTICATOR})
    return cdp, auth["authenticatorId"]


def _open_permissions(c: Console) -> None:
    c.open_panel("approvals")
    btn = c.page.locator("#permSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#permGroups .pgrp").first.wait_for()


def test_permissions_rows_set_up_a_passkey_and_approve_with_it(browser: Any, perm_url: str) -> None:
    c = Console(browser, perm_url, TOKEN, DESKTOP)
    try:
        cdp, auth_id = _with_authenticator(c)
        c.open()
        _open_permissions(c)
        page = c.page
        rows = page.locator("#permGroups .pgrp")
        assert rows.count() >= 9
        send = rows.filter(has_text="Send email")
        assert send.locator(".seg-opt").all_text_contents() == ["Ask first", "Never"]
        web = rows.filter(has_text="Search and read the web")
        assert web.locator(".seg-opt").all_text_contents() == ["Allow", "Ask first", "Never"]
        web.get_by_text("Never", exact=True).click()
        page.locator("#permNote", has_text="Search and read the web: Never.").wait_for()
        assert web.locator("input[value=deny]").is_checked()

        # set up a passkey (the virtual authenticator answers navigator.credentials.create)
        page.locator("#pskLabel").fill("Test laptop")
        page.locator("#pskAdd").click()
        page.locator(".pskrow", has_text="Test laptop").wait_for()
        assert page.locator("#pskReq").get_attribute("aria-pressed") == "true"
        page.locator("#permSetBtn").click()  # collapse: the one-line summary says it all
        summary = str(page.locator("#permSum").text_content())
        assert "1 switched off" in summary and "Passkey on (1)" in summary

        # an irreversible card is approved with the passkey: exactly one send
        c.send("send: lunch at one")
        card = page.locator("#approvals .approval").first
        card.wait_for()
        approve = card.locator(".approve")
        assert approve.text_content() == "Approve with passkey"
        approve.click()
        page.locator(".row.jarvis .bubble", has_text="Noted, Sir.").nth(1).wait_for()
        page.locator("#approvals .empty", has_text="Nothing waiting.").wait_for()
        audit = _get(perm_url, "/v1/audit?limit=5")["entries"]
        assert [e["outcome"] for e in audit if e["tool"] == "send_message"][-1] == "executed"

        # the check is cancelled (no passkey on this device any more): plain words, nothing sent
        cdp.send("WebAuthn.clearCredentials", {"authenticatorId": auth_id})
        c.send("send: second message")
        card = page.locator("#approvals .approval").first
        card.wait_for()
        card.locator(".approve").click()
        err = card.locator(".perr")
        err.wait_for(state="visible")
        assert "Nothing was changed" in str(err.text_content())
        assert card.locator(".approve").is_enabled()
        sent = [
            e
            for e in _get(perm_url, "/v1/audit?limit=20")["entries"]
            if e["tool"] == "send_message"
        ]
        assert [e["outcome"] for e in sent].count("executed") == 1
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_without_passkey_support_the_section_says_so(browser: Any, perm_url: str) -> None:
    c = Console(browser, perm_url, TOKEN, PHONE)
    try:
        c.page.add_init_script("delete window.PublicKeyCredential;")
        c.open()
        _open_permissions(c)
        c.page.locator("#pskBox .lerr", has_text="not supported in this browser").wait_for()
        assert c.page.locator("#pskAdd").count() == 0
        # the phone layout keeps 44 px targets and no sideways scroll
        h = c.page.locator("#permGroups .seg-opt").first.bounding_box()
        assert h is not None and h["height"] >= 43
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_a_server_without_a_public_address_explains_passkeys_are_off(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(CSP_SPY)
        c.open()
        _open_permissions(c)
        c.page.locator("#pskBox", has_text="JARVIS_PUBLIC_BASE_URL").wait_for()
        assert str(c.page.locator("#permSum").text_content()).endswith("Passkey not available")
        assert c.page.locator("#pskAdd").count() == 0
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
