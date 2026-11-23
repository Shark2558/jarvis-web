# tests/browser/conftest.py — Playwright smoke tests for the web console (slice 6 pipeline item).
# They need a real Chromium, so they are opt-in: JARVIS_BROWSER_TESTS=1 (CI `browser` job,
# `make browser-test`). Without it every test here is skipped, never failed.
from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "browser-test-token-not-a-secret"
START_TIMEOUT_S = 30


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "browser: drives the console in headless Chromium (JARVIS_BROWSER_TESTS=1)"
    )


def _shard_plan() -> ModuleType:
    """Load shard_plan.py beside this file (CI runs plain pytest: tests/ is not a package)."""
    path = Path(__file__).with_name("shard_plan.py")
    spec = importlib.util.spec_from_file_location("jarvis_browser_shard_plan", path)
    if spec is None or spec.loader is None:
        raise pytest.UsageError("tests/browser/shard_plan.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_of(item: pytest.Item) -> str:
    return item.nodeid.split("::", 1)[0]


def _keep_shard(config: pytest.Config, items: list[pytest.Item], spec: str) -> None:
    """Keep only this machine's share of the browser tests (JARVIS_BROWSER_SHARD=i/n)."""
    plan_mod = _shard_plan()
    try:
        index, total = plan_mod.parse(spec)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    counts: dict[str, int] = {}
    for item in items:
        if "browser" in item.keywords:
            counts[_file_of(item)] = counts.get(_file_of(item), 0) + 1
    plan = plan_mod.assign(counts, total)
    kept = [i for i in items if "browser" not in i.keywords or plan[_file_of(i)] == index]
    kept_ids = {id(i) for i in kept}
    dropped = [i for i in items if id(i) not in kept_ids]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("JARVIS_BROWSER_TESTS") == "1":
        spec = os.environ.get("JARVIS_BROWSER_SHARD", "").strip()
        if spec:
            _keep_shard(config, items, spec)
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
        "JARVIS_USD_INR_LIVE": "0",  # the default rate (₹95.24): no call to frankfurter.dev
        # One server serves the whole suite from one IP; the app's 120/min per-IP limit (unit-tested
        # in tests/) would turn a fast CI runner's requests into 429s. Per-owner voice limits stay.
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
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
