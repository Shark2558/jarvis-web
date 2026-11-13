# evals/r7/shell.py
"""R7 eval, Part A (`shell`, BUILT): the app on the web side (docs/plans/r7-mobile.md D3, D8, D9,
D10, D15; "Tests and evals per part", row A). Every case runs the real app in process (mock
brain) or reads the real console sources:

- manifest       GET /manifest.webmanifest: public, no cookie, what Chrome needs to install the
                 console (name, start_url /?source=app, standalone, #04070D, 192/512/maskable
                 PNGs of the sizes they claim), the Talk/Camera/SOS shortcuts with launch words
                 and the share target (POST multipart to /app/share/in, JPEG/PNG/WebP/PDF)
- csp            the console's CSP gained exactly `manifest-src 'self'`
- launch_words   only the four words and the dock's panels, each key at most once, filtered by
                 the allow-list; a cross-site visit loses `do` and `open` and keeps `reauth`
- talk           do=talk focuses the mic button and says "Tap to talk"; it never presses,
                 clicks, unlocks or opens a microphone
- share_worker   the share worker takes the one POST, keeps at most 5 items of 10 MB for 24
                 hours, answers 303 to /?do=shared and sends nothing anywhere
- share_unread   with no worker the server never reads a byte of the share and says "Open JARVIS
                 once, then share again."
- share_door     the tray sends only through I0's one picture door (no fetch, no /v1 path of its
                 own) and asks the server only after sign-in
- push           every alert kind opens its panel (/?open=<panel>, a panel the reader allows),
                 the push worker keeps that target, tags by kind, offers Talk and hands the target
                 to the open window over BroadcastChannel, never navigating

NOTE: the cases that read sources (talk, share_worker, share_door, push) are tripwires: they look
for the literal tokens (`fetch(`, `.click(`, `navigate(`), so a renamed
call could slip past them. The
behavioural guards are the browser tests (tests/browser/test_r7_a_*.py), among them the posts from
another site that must store nothing (test_r7_a_share_review.py).

Negative control (the plan's four, each applied ON ITS OWN to the sources in memory): the
allow-list switched off, the share worker made to upload at once, do=talk made to call press() (a
click on the mic button), the click handler's navigate() path put back. Each must fail the case it
targets, so no control can hide behind another.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, get_args

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r7_fakes_a import dock_panels, multipart, png_size, raw_post  # noqa: E402

from jarvis.alerts import AlertKind  # noqa: E402
from jarvis.api import create_app  # noqa: E402
from jarvis.api.app_shell import MISSED  # noqa: E402
from jarvis.api.console import CONSOLE_CSP  # noqa: E402
from jarvis.config import LLMBackend, SessionBackend, Settings  # noqa: E402
from jarvis.llm.mock_provider import MockProvider  # noqa: E402
from jarvis.memory.inmemory import InMemorySessionStore  # noqa: E402
from jarvis.mobile.ports import LAUNCH_WORDS  # noqa: E402
from jarvis.webpush.service import payload_for  # noqa: E402

PART = "shell"
BUILT = True
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
SOURCES = ("console-r7-links.js", "console-r7-share.js", "app-share-sw.js", "console-sw.js")
CSP_BEFORE_R7 = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "frame-src https://www.youtube-nocookie.com; worker-src 'self'"
)
SHARE_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
SW_RULE = re.compile(r"^/(?:\?(?:open=[a-z]{2,20}|do=(?:talk|look|sos|shared)))?$")
NO_NETWORK = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "importScripts")

Src = Mapping[str, str]
Case = Callable[[Src], Awaitable[list[str]]]

# The plan's four controls: (name, file, the line as built, what the control puts there, the case
# it must fail).
CONTROLS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "allow-list switched off",
        "console-r7-links.js",
        "const pick = (value, list) => (typeof value === 'string' && list.includes(value) ? "
        "value : '');",
        "const pick = (value, list) => (typeof value === 'string' ? value : '');",
        "shell:launch_words",
    ),
    (
        "share worker uploads at once",
        "app-share-sw.js",
        "  if (foreign(req)) return finish([{ name: '', why: WHY.origin }], HOME);",
        "  if (foreign(req)) return finish([{ name: '', why: WHY.origin }], HOME);\n"
        "  await fetch('/v1/attachments', { method: 'POST', body: req });",
        "shell:share_worker",
    ),
    (
        "do=talk calls press()",
        "console-r7-links.js",
        "    mic.focus();",
        "    mic.focus(); mic.click();",
        "shell:talk",
    ),
    (
        "navigate() path put back",
        "console-sw.js",
        "try { await win.focus(); handOver(target); return; }",
        "try { await win.focus(); await win.navigate(target); return; }",
        "shell:push",
    ),
)


def _settings(**over: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="dev",
        llm_backend=LLMBackend.MOCK,
        session_backend=SessionBackend.MEMORY,
        usd_inr_live=False,
        log_level="CRITICAL",
        api_token=SecretStr("eval-token-not-a-secret"),
        **over,
    )


def _code(src: str) -> str:
    """Source without comments (headers name what the code must never do)."""
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", re.sub(r"/\*.*?\*/", "", src, flags=re.S))


def _between(src: str, start: str, end: str) -> str:
    return src[src.index(start) : src.index(end, src.index(start))] if start in src else ""


# ---- the cases ---------------------------------------------------------------------------------
async def manifest(_: Src) -> list[str]:
    bad: list[str] = []
    app = create_app(_settings(), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e") as c:
            r = await c.get("/manifest.webmanifest")
            if r.status_code != 200 or r.headers.get("content-type") != "application/manifest+json":
                return [f"the manifest answered {r.status_code}"]
            if "set-cookie" in r.headers:
                bad.append("the manifest set a cookie")
            m = r.json()
            want = {"name": "JARVIS", "start_url": "/?source=app", "display": "standalone"}
            want |= {"theme_color": "#04070D", "background_color": "#04070D", "scope": "/"}
            bad += [f"{k} is {m.get(k)!r}" for k, v in want.items() if m.get(k) != v]
            claims = [(i["src"], i["sizes"], i.get("purpose", "any")) for i in m.get("icons", [])]
            claims += [(i["src"], i["sizes"], "any") for s in m["shortcuts"] for i in s["icons"]]
            for src, sizes, _purpose in claims:
                got = await c.get(src)
                if got.status_code != 200 or "x".join(map(str, png_size(got.content))) != sizes:
                    bad.append(f"{src} is not a {sizes} PNG")
            purposes = {(s, p) for _, s, p in claims}
            if not {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= purposes:
                bad.append("the 192, 512 and maskable icons are not all there")
            words = [s["url"].rsplit("do=", 1)[-1] for s in m["shortcuts"]]
            if words != ["talk", "look", "sos"] or not all(w in LAUNCH_WORDS for w in words):
                bad.append(f"the shortcuts use {words}")
            t = m.get("share_target", {})
            files = (t.get("params", {}).get("files") or [{}])[0]
            if (t.get("action"), t.get("method"), t.get("enctype")) != (
                "/app/share/in",
                "POST",
                "multipart/form-data",
            ) or not SHARE_TYPES <= set(files.get("accept", [])):
                bad.append("the share target is not the share route's")
    return bad


async def csp(_: Src) -> list[str]:
    return [] if CONSOLE_CSP == CSP_BEFORE_R7 + "; manifest-src 'self'" else ["the CSP changed"]


async def launch_words(src: Src) -> list[str]:
    code, bad = _code(src["console-r7-links.js"]), []
    words = re.search(r"const WORDS = Object\.freeze\(\[([^\]]*)\]\)", code)
    panels = re.search(r"const PANELS = Object\.freeze\(\[([^\]]*)\]\)", code)
    if not words or re.findall(r"'([a-z]+)'", words.group(1)) != list(LAUNCH_WORDS):
        bad.append("the words are not exactly the four")
    if not panels or re.findall(r"'([a-z]+)'", panels.group(1)) != dock_panels():
        bad.append("the panels are not exactly the dock's")
    pick = re.search(r"const pick = \(value, list\) => \(([^;]*)\);", code)
    if not pick or "list.includes(value)" not in pick.group(1):
        bad.append("a value is not checked against its allow-list")
    if "all.length === 1 ? all[0] : ''" not in code:
        bad.append("a repeated key is not ignored")
    if "history.replaceState(" not in code:
        bad.append("the words stay in the address")
    app = create_app(_settings(), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://e") as c:
            r = await c.get(
                "/?do=talk&open=home&reauth=1", headers={"Sec-Fetch-Site": "cross-site"}
            )
            if r.status_code != 302 or r.headers.get("location") != "/?reauth=1":
                bad.append("a cross-site visit keeps do or open, or loses reauth")
    return bad


async def talk(src: Src) -> list[str]:
    code = _code(src["console-r7-links.js"])
    body = _between(code, "function talk()", "async function partOpen")
    if not body:
        return ["no talk screen"]
    banned = ("press(", ".click(", "dispatchEvent(", "unlock(", "getUserMedia", "listen(")
    bad = [f"do=talk calls {b}" for b in (*banned, ".start(", "SpeechRecognition") if b in code]
    if "mic.focus()" not in body or "loop.say(TALK_LINE)" not in body:
        bad.append("do=talk does not ready the mic button")
    if "const TALK_LINE = 'Tap to talk';" not in code:
        bad.append("the line is not 'Tap to talk'")
    return bad


async def share_worker(src: Src) -> list[str]:
    code = _code(src["app-share-sw.js"])
    bad = [f"the worker calls {b}" for b in (*NO_NETWORK, "postMessage") if b in code]
    for need in (
        "req.method !== 'POST'",
        "url.pathname !== '/app/share/in'",
        "const LANDING = '/?do=shared';",
        ", 303)",
        "const MAX_ITEMS = 5;",
        "const MAX_BYTES = 10 * 1024 * 1024;",
        "const KEEP_MS = 24 * 60 * 60 * 1000;",
        "function foreign(req)",
        "const MAX_BODY = 60 * 1024 * 1024;",
        "const SNIFF = {",
    ):
        if need not in code:
            bad.append(f"the worker lacks {need}")
    if code.count("addEventListener('fetch'") != 1 or "clients.claim" in code:
        bad.append("the worker does more than take one POST")
    return bad


async def share_unread(_: Src) -> list[str]:
    body, kind = multipart({"text": "made up"}, [("a.jpg", "image/jpeg", b"\xff" * 200_000)])
    app = create_app(_settings(), provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        status, _headers, reply, spy = await raw_post(
            app, "/app/share/in", body, {"content-type": kind}
        )
    bad = (
        [] if status == 200 and MISSED in reply.decode() else ["the server did not say what to do"]
    )
    return bad + ([f"the server read {spy.pulled} chunks of the share"] if spy.pulled else [])


async def share_door(src: Src) -> list[str]:
    code = _code(src["console-r7-share.js"])
    banned = (*NO_NETWORK, "/v1/attachments", "/v1/vault", "/v1/chat", "JarvisAttach", "JarvisChat")
    bad = [f"the tray uses {b}" for b in banned if b in code]
    if "M.parts.send" not in code or "d.ask(file, ASK_TEXT)" not in code:
        bad.append("the tray does not send through the one door")
    ready = _between(code, "async function ready()", "document.addEventListener('jarvis:ready'")
    if code.count("M.api(") != 1 or "worker();" not in ready:
        bad.append("the tray asks the server outside its sign-in path")
    return bad


async def push(src: Src) -> list[str]:
    code, bad = _code(src["console-sw.js"]), []
    links = _code(src["console-r7-links.js"])
    found = re.search(r"const PANELS = Object\.freeze\(\[([^\]]*)\]\)", links)
    allowed = set(re.findall(r"'([a-z]+)'", found.group(1))) if found else set()
    for kind in get_args(AlertKind):
        url = json.loads(payload_for(kind, "A made-up alert."))["url"]
        ok = url == "/" if kind == "test" else url.removeprefix("/?open=") in allowed
        if not ok or not SW_RULE.fullmatch(url):
            bad.append(f"{kind} opens {url}")
    if "navigate(" in code:
        bad.append("a tap navigates a window the worker does not control")
    if "new BroadcastChannel('jarvis-launch')" not in code or "handOver(target)" not in code:
        bad.append("a tap does not hand the target to the open window")
    if "tag: kind" not in code or "action: 'talk'" not in code:
        bad.append("the tag or the Talk action is missing")
    if "/^\\/(?:\\?(?:open=[a-z]{2,20}|do=(?:talk|look|sos|shared)))?$/" not in code:
        bad.append("the worker's address rule is not the panel rule")
    return bad


CASES: Mapping[str, Case] = {
    "manifest": manifest,
    "csp": csp,
    "launch_words": launch_words,
    "talk": talk,
    "share_worker": share_worker,
    "share_unread": share_unread,
    "share_door": share_door,
    "push": push,
}


def sources() -> dict[str, str]:
    return {name: (STATIC / name).read_text(encoding="utf-8") for name in SOURCES}


def controlled(name: str) -> dict[str, str]:
    """The sources with one control applied."""
    src = sources()
    for control_name, file, line, broken, _case in CONTROLS:
        if control_name != name:
            continue
        if line not in src[file]:
            raise RuntimeError(f"control {name!r}: its line is not in {file} any more")
        src[file] = src[file].replace(line, broken, 1)
    return src


async def _run(src: Src) -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        try:
            failures = await case(src)
        except Exception as exc:  # noqa: BLE001 - a case that breaks is a failed case
            failures = [f"{type(exc).__name__}: {exc}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run(sources())


async def control() -> dict[str, Any]:
    failed: list[str] = []
    caught = True
    for name, _file, _line, _broken, target in CONTROLS:
        these = [r["id"] for r in await _run(controlled(name)) if not r["passed"]]
        caught = caught and target in these
        failed += [f"{name} -> {case}" for case in these]
    return {
        "name": "shell: " + "; ".join(name for name, *_ in CONTROLS) + " (each alone)",
        "suite_failed": caught,
        "failed_cases": failed,
    }
