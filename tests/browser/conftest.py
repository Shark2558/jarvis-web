# tests/browser/conftest.py — Playwright smoke tests for the web console (slice 6 pipeline item).
# They need a real Chromium, so they are opt-in: JARVIS_BROWSER_TESTS=1 (CI `browser` job,
# `make browser-test`). Without it every test here is skipped, never failed.
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "browser-test-token-not-a-secret"
START_TIMEOUT_S = 30


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "browser: drives the console in headless Chromium (JARVIS_BROWSER_TESTS=1)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("JARVIS_BROWSER_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set JARVIS_BROWSER_TESTS=1 to run the Playwright smoke tests")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthy(url: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"jarvis serve exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError("jarvis serve did not become healthy in time")


@pytest.fixture(scope="session")
def token() -> str:
    return TOKEN


@pytest.fixture(scope="session")
def server_url() -> Iterator[str]:
    """The real app as a subprocess: mock brain, in-memory store, bearer-token auth."""
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token",
        "JARVIS_API_TOKEN": TOKEN,
        "JARVIS_LOG_LEVEL": "WARNING",
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "jarvis.cli", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(url, proc)
    except RuntimeError:
        proc.kill()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(f"server failed to start:\n{err}") from None
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
