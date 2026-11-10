# scripts/ui_snapshots.py — repeatable screenshots of every console panel, for UI audits.
# ruff: noqa: E501 -- only DOM_CHECKS_JS (a JavaScript string evaluated in the page) has long lines
"""Start the real app (mock brain, in-memory store, bearer-token auth — exactly like
tests/browser/conftest.py `server_url`), sign in like tests/browser/test_console.py `Console.open`,
and capture, for DESKTOP 1440x900 and PHONE 390x844 on the night and day surfaces:

  * the whole viewport and the top bar (`header.topbar`);
  * every panel (`#p-<id>`), plus extra shots when its body scrolls;
  * extra states: Vitals with the "Track something JARVIS can't see" form open, the systems-check
    pop-up (`#sysCheck`, from the Systems card's Run) with every result in, and, night only,
    Vitals answering 503 and Vitals whose own records can't be read (`manual_unavailable`).

R4 panels get realistic data from `page.route` fulfilments (tests/browser/ui_checks.py: built
with the server's own models, so the shapes match the routes). Each panel also gets DOM
checks run in the page (overlapping interactive elements, off-theme fonts, browser-default
controls, run-together text, overflow, contrast, small targets); the findings go to checks.json and
a summary into index.md beside the PNGs.

Usage (from the repo root; Chromium is pre-installed — never `playwright install`):
    /tmp/venv-c/bin/python scripts/ui_snapshots.py --out /home/claude/ui-audit/before
Exit status: 0 when every capture worked and no uncaught page error happened, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, sync_playwright

log = logging.getLogger("ui_snapshots")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "browser"))
from ui_checks import (  # noqa: E402
    DOM_CHECKS_JS,
    FINISH_ANIMATIONS_JS,
    PANELS,
    READY,
    install_mocks,
)  # noqa: E402  (shared with test_ui_audit)

TOKEN = "ui-snapshots-token-not-a-secret"
START_TIMEOUT_S = 30
SETTLE_MS = 700  # panelIn (.22s) + rise (.4s) animations, then a margin
WAIT_MS = 5000  # per readiness selector; a miss is logged, never fatal
MAX_SCROLL_SHOTS = 4

VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 900},
    "phone": {"width": 390, "height": 844},
}
SURFACES = ("night", "day")


# ================================================================================================
# server + browser plumbing
# ================================================================================================
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


@contextmanager
def serve() -> Iterator[str]:
    """The real app as a subprocess, with the same env as tests/browser/conftest.py."""
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
        "JARVIS_USD_INR_LIVE": "0",
        "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    cmd = [sys.executable, "-m", "jarvis.cli", "serve", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
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


@dataclass
class Run:
    out: Path
    shots: list[tuple[str, str]] = field(default_factory=list)  # (group, file name)
    checks: dict[str, Any] = field(default_factory=dict)
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class Console:
    """One signed-in console page (same steps as tests/browser/test_console.py `Console`)."""

    def __init__(self, browser: Browser, url: str, vp: str, surface: str, run: Run) -> None:
        self.url, self.vp, self.surface, self.run = url, vp, surface, run
        self.tag = f"{vp}-{surface}"
        self.ctx = browser.new_context(viewport=VIEWPORTS[vp], device_scale_factor=1)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: run.page_errors.append(f"[{self.tag}] {e}"))
        self.page.on("console", self._on_console)

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            where = msg.location.get("url", "") if msg.location else ""
            self.run.console_errors.append(f"[{self.tag}] {msg.text} @ {where}")

    def open(self) -> None:
        self.page.goto(self.url + "/")
        self.page.locator("#tokIn, #welcome").first.wait_for()
        gate = self.page.locator("#tokIn")
        if gate.count():
            gate.fill(TOKEN)
            self.page.locator("#tokBtn").click()
        self.page.locator("#welcome").wait_for()
        if self.surface == "day":  # the Appearance menu, as test_switching_night_to_day does
            self.page.locator("#themeBtn").click()
            self.page.locator('label[for="jx-s-day"]').click()
            self.page.keyboard.press("Escape")
        got = self.page.locator("html").get_attribute("data-surface")
        if got != self.surface:
            raise RuntimeError(f"surface is {got!r}, wanted {self.surface!r}")
        self.wait_for("#brainModeBadge")
        self.page.wait_for_timeout(1200)  # deferred scripts + the 3D module settle

    def wait_for(self, selector: str) -> bool:
        try:
            self.page.locator(selector).first.wait_for(state="attached", timeout=WAIT_MS)
            return True
        except Exception:  # noqa: BLE001 - a missing state is reported, never fatal
            self.run.warnings.append(f"[{self.tag}] not seen within {WAIT_MS} ms: {selector}")
            return False

    def open_panel(self, panel: str, ready: bool = True) -> None:
        tab = self.page.locator(f'.dk[data-open="{panel}"]')
        if self.page.locator(f"#p-{panel}").is_visible():
            pass  # already open (the Conversation, by default): a tab click would toggle it shut
        elif tab.is_visible():
            tab.click()
        else:  # phones: the tabs that don't fit the bar sit behind More (slice 8)
            self.page.locator("#dockMore").click()
            self.page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
        self.page.locator(f"#p-{panel}").wait_for(state="visible")
        if ready and panel in READY:
            self.wait_for(READY[panel])
        self.page.wait_for_timeout(SETTLE_MS)

    def close_panel(self, panel: str) -> None:
        if self.vp == "desktop" and panel != "chat":
            btn = self.page.locator(f"#p-{panel} [data-close]")
            if btn.is_visible():
                btn.click()

    def close(self) -> None:
        self.ctx.close()


# ================================================================================================
# capture
# ================================================================================================
def shoot(c: Console, selector: str | None, name: str, group: str) -> None:
    path = c.run.out / f"{name}.png"
    try:
        if selector is None:
            c.page.screenshot(path=str(path), animations="disabled", caret="hide")
        else:
            c.page.locator(selector).first.screenshot(
                path=str(path), animations="disabled", caret="hide"
            )
        c.run.shots.append((group, path.name))
    except Exception as exc:  # noqa: BLE001 - one failed shot must not stop the run
        c.run.failures.append(f"{name}: {exc}")


def check(c: Console, selector: str, name: str) -> None:
    try:
        c.page.evaluate(FINISH_ANIMATIONS_JS)  # measured at the end state, as the gate does
        c.run.checks[name] = c.page.evaluate(DOM_CHECKS_JS, selector)
    except Exception as exc:  # noqa: BLE001
        c.run.failures.append(f"checks {name}: {exc}")


def shoot_panel(c: Console, panel: str, name: str) -> None:
    """The panel as seen, then one shot per further screenful while its body scrolls."""
    sel = f"#p-{panel}"
    body = c.page.locator(f"{sel} .pbody").first
    if body.count():  # a click (Run, say) may have scrolled it: the first shot is the top
        body.evaluate("b => { b.scrollTop = 0; }")
        c.page.wait_for_timeout(100)
    shoot(c, sel, name, c.tag)
    check(c, sel, name)
    if not body.count():
        return
    dims = body.evaluate("b => [b.scrollHeight, b.clientHeight]")
    step = 0
    while dims[0] > dims[1] + 8 and step < MAX_SCROLL_SHOTS:
        step += 1
        at_end = body.evaluate(
            "(b, s) => { b.scrollTop = s * b.clientHeight * 0.9; "
            "return b.scrollTop + b.clientHeight >= b.scrollHeight - 2; }",
            step,
        )
        c.page.wait_for_timeout(150)
        shoot(c, sel, f"{name}-s{step}", c.tag)
        if at_end:
            break
    body.evaluate("b => { b.scrollTop = 0; }")


def vitals_form(c: Console) -> None:
    """Vitals with its add form open ("Track something JARVIS can't see", R5.1 D2)."""
    c.open_panel("vitals")
    btn = c.page.locator("#vtAddBtn")
    if not btn.count():
        c.run.failures.append(f"[{c.tag}] Vitals has no 'Track something JARVIS can't see'")
        return
    btn.click()
    form = c.page.locator("#vtAddBody form").first
    form.wait_for()
    form.evaluate("f => f.scrollIntoView({block: 'start'})")
    c.page.wait_for_timeout(250)
    name = f"{c.tag}-vitals-form"
    shoot(c, "#p-vitals", name, c.tag)
    check(c, "#p-vitals", name)
    shoot(c, "#vtAddBody form", f"{name}-only", c.tag)
    btn.click()  # closed again
    c.close_panel("vitals")


def brain_menu(c: Console) -> None:
    """The open brain menu, then its AI-on confirm (a stateful fake: the server's mode is untouched)."""
    state = {"mode": "ai"}

    def fake(route: Any) -> None:
        if route.request.method == "POST":
            state["mode"] = json.loads(route.request.post_data or "{}")["mode"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"mode": state["mode"], "meaning": ""}),
        )

    c.page.route("**/v1/settings/brain-mode", fake)
    try:
        pill = c.page.locator("#brainModeBadge")
        pill.click()
        c.page.locator("#brainMenu").wait_for(state="visible", timeout=WAIT_MS)
        c.page.mouse.move(0, 0)
        c.page.wait_for_timeout(450)
        shoot(c, None, f"{c.tag}-brain-menu", c.tag)
        check(c, "#brainMenu", f"{c.tag}-brain-menu")
        c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
        c.page.locator("#brainModeBadge", has_text="No-AI").wait_for(timeout=WAIT_MS)
        pill.click()
        c.page.locator("#brainMenu .bmopt[data-mode=ai]").click()
        c.page.locator("#brainMenu .bmask").wait_for(state="visible", timeout=WAIT_MS)
        c.page.mouse.move(0, 0)
        c.page.wait_for_timeout(450)
        shoot(c, None, f"{c.tag}-brain-confirm", c.tag)
        check(c, "#brainMenu", f"{c.tag}-brain-confirm")
        c.page.get_by_role("button", name="Switch on").click()
        c.page.locator("#brainModeBadge", has_text="AI on").wait_for(timeout=WAIT_MS)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        c.run.failures.append(f"[{c.tag}] brain menu: {exc}")
        c.page.keyboard.press("Escape")
    finally:
        c.page.unroute("**/v1/settings/brain-mode", fake)


def systems_popup(c: Console) -> None:
    """The systems-check pop-up (R5.1 D6) from the Systems card's Run, every result in."""
    run_btn = c.page.locator("#systemsCard .btn", has_text="Run")
    if not run_btn.count():
        c.run.failures.append(f"[{c.tag}] the Systems card has no Run button")
        return
    run_btn.first.click()
    dialog = c.page.locator("#sysCheck")
    try:
        dialog.wait_for(state="visible", timeout=WAIT_MS)
        c.page.locator("#sysCheck .scrow").first.wait_for(timeout=WAIT_MS)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        c.run.failures.append(f"[{c.tag}] the systems-check pop-up did not open: {exc}")
        return
    dialog.click(position={"x": 8, "y": 8})  # a pointer inside keeps it open (no countdown)
    c.page.wait_for_timeout(900)  # the ticks and the briefing have landed
    name = f"{c.tag}-syscheck"
    shoot(c, None, name, c.tag)
    shoot(c, "#sysCheck", f"{name}-only", c.tag)
    # the concerns list scrolls inside the pop-up: a second shot at its end shows every item
    c.page.evaluate(
        "() => { const l = document.querySelector('#sysCheck .scconcerns li:last-child');"
        " if (l) l.scrollIntoView({block: 'end'}); }"
    )
    c.page.wait_for_timeout(200)
    shoot(c, "#sysCheck", f"{name}-more", c.tag)
    c.page.evaluate(
        "() => { const d = document.getElementById('sysCheck'); if (d) d.style.maxHeight = 'none'; }"
    )
    check(c, "#sysCheck", name)
    c.page.evaluate(
        "() => { const d = document.getElementById('sysCheck'); if (d) d.style.maxHeight = ''; }"
    )
    try:
        c.page.locator("#sysCheckClose").first.click(timeout=WAIT_MS)
    except Exception:  # noqa: BLE001 - Esc closes it too
        c.page.keyboard.press("Escape")
    c.page.wait_for_timeout(300)


# History lists the live server's own conversations: give it some (one with a long title), so its
# rows are captured and checked full, as tests/browser/test_ui_audit.py does.
SEED_TITLES = (
    "Please draft a polite follow-up message to the vendor about the delayed October invoice",
    "Where is my daughter's school?",
    "what do I drink?",
    "hello",
)


def seed_conversations(browser: Browser, url: str, run: Run) -> None:
    c = Console(browser, url, "desktop", "night", run)
    try:
        c.open()
        for title in SEED_TITLES:
            c.page.locator("#newBtn").click()
            before = c.page.locator(".row.jarvis .bubble:not(.typing)").count()
            c.page.locator("#input").fill(title)
            c.page.locator("#send").click()
            c.page.locator(".row.jarvis .bubble:not(.typing)").nth(before).wait_for()
    finally:
        c.close()


def capture_combo(browser: Browser, url: str, vp: str, surface: str, run: Run) -> None:
    c = Console(browser, url, vp, surface, run)
    try:
        install_mocks(c.page)
        c.open()
        shoot(c, None, f"{c.tag}-page", c.tag)
        shoot(c, "header.topbar", f"{c.tag}-topbar", c.tag)
        check(c, "header.topbar", f"{c.tag}-topbar")
        brain_menu(c)
        for panel in PANELS:
            log.info("%s %s", c.tag, panel)
            try:
                c.open_panel(panel)
            except Exception as exc:  # noqa: BLE001
                run.failures.append(f"[{c.tag}] open {panel}: {exc}")
                continue
            if panel == "integrations":  # Run opens the pop-up (the mocked stream), shot, closed
                systems_popup(c)
            shoot_panel(c, panel, f"{c.tag}-{panel}")
            c.close_panel(panel)
        vitals_form(c)
    finally:
        c.close()


def capture_vitals_503(browser: Browser, url: str, vp: str, run: Run) -> None:
    c = Console(browser, url, vp, "night", run)
    c.tag = f"{vp}-night-503"
    try:
        install_mocks(c.page, vitals_503=True)
        c.open()
        c.open_panel("vitals", ready=False)
        c.wait_for("#vitals-board .bnote.bad:not(:empty)")
        shoot_panel(c, "vitals", f"{c.tag}-vitals")
    finally:
        c.close()


def capture_vitals_manual_unavailable(browser: Browser, url: str, vp: str, run: Run) -> None:
    """D2: the owner's own records can't be read; JARVIS's own items still show."""
    c = Console(browser, url, vp, "night", run)
    c.tag = f"{vp}-night-manual-unavailable"
    try:
        install_mocks(c.page, manual_unavailable=True)
        c.open()
        c.open_panel("vitals")
        shoot_panel(c, "vitals", f"{c.tag}-vitals")
    finally:
        c.close()


def write_index(run: Run) -> None:
    lines = [
        "# UI snapshots",
        "",
        f"Made {time.strftime('%Y-%m-%d %H:%M:%S')} by "
        "scripts/ui_snapshots.py. DOM-check findings per shot: checks.json.",
        "",
    ]
    groups: dict[str, list[str]] = {}
    for group, name in run.shots:
        groups.setdefault(group, []).append(name)
    for group in sorted(groups):
        lines += [f"## {group}", ""] + [f"- [{n}]({n})" for n in groups[group]] + [""]
    lines += [
        "## DOM checks (counts per shot)",
        "",
        "| shot | overlaps | offTheme | systemFont | defaults | runTogether | overflow | "
        "contrast | smallTargets | unlabelled |",
        "|" + "---|" * 10,
    ]
    keys = [
        "overlaps",
        "offTheme",
        "systemFont",
        "defaults",
        "runTogether",
        "overflow",
        "contrast",
        "smallTargets",
        "unlabelled",
    ]
    for name, res in sorted(run.checks.items()):
        if isinstance(res, dict) and not res.get("missing"):
            lines.append(
                f"| {name} | " + " | ".join(str(len(res.get(k) or [])) for k in keys) + " |"
            )
    for title, items in (
        ("Page errors", run.page_errors),
        ("Failures", run.failures),
        ("Warnings", run.warnings),
        ("Console errors", run.console_errors),
    ):
        lines += ["", f"## {title} ({len(items)})", ""] + [f"- {x}" for x in items[:200]]
    (run.out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run.out / "checks.json").write_text(json.dumps(run.checks, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="directory for the PNGs and index.md")
    ap.add_argument("--viewports", default="desktop,phone")
    ap.add_argument("--surfaces", default=",".join(SURFACES))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    run = Run(out=args.out)
    run.out.mkdir(parents=True, exist_ok=True)
    vps = [v for v in args.viewports.split(",") if v in VIEWPORTS]
    surfaces = [s for s in args.surfaces.split(",") if s in SURFACES]
    with serve() as url, sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            seed_conversations(browser, url, run)
            for vp in vps:
                for surface in surfaces:
                    capture_combo(browser, url, vp, surface, run)
                if "night" in surfaces:
                    capture_vitals_503(browser, url, vp, run)
                    capture_vitals_manual_unavailable(browser, url, vp, run)
        finally:
            browser.close()
    write_index(run)
    log.info(
        "%d shots, %d page errors, %d failures -> %s",
        len(run.shots),
        len(run.page_errors),
        len(run.failures),
        run.out / "index.md",
    )
    return 1 if run.page_errors or run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
