# tests/browser/book_mocks.py -- R6 D: the build book contract (docs/plans/r6-build-book.md
# "Contract") answered by Playwright page.route stubs, since builders B and C build the real routes
# in parallel. Shapes follow the plan's Contract table and jarvis.buildbook.model (Scene, Beat, Fact,
# TalkReply, SessionView); the show script's `lines` / `closing` shape is the one D asks I1 for
# (src/jarvis/api/static/INTEGRATION-D.md). Test data only: no fact here is shipped to a page.
# ruff: noqa: E501 -- JavaScript stubs and narration strings
from __future__ import annotations

import io
import json
import struct
import wave
from typing import Any

RELEASE = {
    "id": "3f2a1c9",
    "label": "R6",
    "sha": "3f2a1c9" + "0" * 33,
    "committed_at": "2026-11-10T09:00:00+05:30",
}
SEALED = [
    {"id": "3f2a1c9", "label": "R6", "sealed_at": "2026-11-10T09:12:00+05:30", "mb": 4.6},
    {"id": "aebff3a", "label": "R5.1", "sealed_at": "2026-11-08T18:40:00+05:30", "mb": 4.4},
    {"id": "9b97eab", "label": "R5", "sealed_at": "2026-11-02T11:05:00+05:30", "mb": 4.1},
]
LOCK_ID = "bl_0123456789ab"
TOKEN = "bk-token-not-a-secret-0123456789abcdef"


def status(**over: Any) -> dict[str, Any]:
    """GET /v1/book (Contract row 1)."""
    body: dict[str, Any] = {
        "available": True,
        "release": RELEASE,
        "sealed": SEALED,
        "kept": 3,
        "used_mb": 13.1,
        "limit_mb": 60,
        "session": None,
        "lock": {"on": False},
        "last_closed": {  # D14 "what stays": the status doc, as C's BookService answers it (I1)
            "last_closed_at": "2026-11-09T14:25:00+05:30",
            "notified": True,
        },
        "talk": {"on": True},
        "open": {"passkey_ready": True, "fresh_left_s": 240},
    }
    body.update(over)
    return body


SECTIONS = {
    "architecture": {
        "packages": [
            {
                "name": "api",
                "layer": "L1",
                "files": 64,
                "lines": 14210,
                "summary": "HTTP routes and the console.",
            },
            {
                "name": "voice",
                "layer": "L2",
                "files": 22,
                "lines": 4120,
                "summary": "Speech in and out.",
            },
            {
                "name": "core",
                "layer": "L4",
                "files": 18,
                "lines": 5230,
                "summary": "The reasoning loop.",
            },
            {
                "name": "tools",
                "layer": "L6",
                "files": 31,
                "lines": 7400,
                "summary": "Every tool behind one gateway.",
            },
            {
                "name": "vault",
                "layer": "L7",
                "files": 9,
                "lines": 2100,
                "summary": "Sealed documents.",
            },
            {
                "name": "buildbook",
                "layer": "X",
                "files": 14,
                "lines": 3300,
                "summary": "This book.",
            },
        ],
        "fit": [
            {
                "release": "R6",
                "feature": "Build book",
                "layer": "Cross-cutting",
                "phase": "7",
                "verdict": "Build now",
            }
        ],
    },
    "stack": {
        "items": [
            {"role": "language", "name": "Python", "version": ">=3.11", "source": "pyproject.toml"},
            {
                "role": "base image",
                "name": "python",
                "version": "3.12-slim",
                "source": "Dockerfile",
            },
            {"role": "3d", "name": "three.js", "version": "0.187.0", "source": "api/console.py"},
        ]
    },
    "libraries": [
        {
            "name": "fastapi",
            "version": "0.115.0",
            "kind": "python",
            "licence": "MIT",
            "flag": None,
            "role": "web",
        },
        {
            "name": "pydantic",
            "version": "2.9.2",
            "kind": "python",
            "licence": "MIT",
            "flag": None,
            "role": "data",
        },
        {
            "name": "hey_jarvis.onnx",
            "version": "",
            "kind": "model",
            "licence": "CC BY-NC-SA 4.0",
            "flag": "non_commercial",
            "role": "voice",
        },
    ],
    "integrations": {
        "services": [
            {
                "id": "telegram",
                "label": "Telegram",
                "what": "Sends alerts from fixed templates.",
                "settings": ["telegram_bot_token"],
                "checked": True,
            }
        ],
        "key_purposes": ["vault", "book_index", "book_session"],
        "alert_kinds": [
            {"kind": "book_sealed", "level": "important", "what": "A book was sealed."}
        ],
    },
    "workflows": [
        {
            "id": "chat_turn",
            "title": "One conversation turn",
            "steps": [
                {"label": "The console sends the message", "symbol": "jarvis.api.chat:chat"},
                {"label": "The brain answers", "symbol": "jarvis.core.brain:Brain.turn"},
            ],
        },
    ],
    "limitations": [
        {
            "text": "Voice ID is not built yet.",
            "kind": "deferred",
            "source": "docs/plans/r6-build-book.md",
            "release": "R6",
        },
    ],
    "costs": {
        "usd_inr": 95.24,
        "rate_date": "2026-11-10",
        "items": [
            {
                "id": "balanced_in",
                "label": "Balanced brain, input",
                "kind": "model",
                "unit": "1M input tokens",
                "inr": 190.48,
                "free": "",
            },
            {
                "id": "cloud_run",
                "label": "Cloud Run",
                "kind": "cloud",
                "unit": "month",
                "inr": 0.0,
                "free": "2 million requests a month",
            },
        ],
    },
    "decisions": [
        {
            "plan": "docs/plans/r6-build-book.md",
            "release": "R6",
            "title": "Release R6: the build book",
            "decisions": ["D1 · Deterministic, private, free.", "D2 · Sources."],
        },
    ],
}


def _beats(n: int, *texts: str, focus: tuple[str, ...] = ()) -> list[dict[str, str]]:
    return [
        {"id": f"s{n:02d}b{i + 1:02d}", "text": t, "focus": focus[i] if i < len(focus) else ""}
        for i, t in enumerate(texts)
    ]


def _facts(*rows: tuple[Any, ...]) -> list[dict[str, Any]]:
    keys = ("label", "value", "n", "group", "flag")
    out = []
    for r in rows:
        f = {"label": "", "value": "", "n": None, "group": "", "flag": ""}
        f.update(dict(zip(keys, r, strict=False)))
        out.append(f)
    return out


LAYERS = [
    ("User Interaction", "L1", 6),
    ("Input Processing", "L2", 4),
    ("Context & Orchestration", "L3", 5),
    ("Core Reasoning Engine", "L4", 3),
    ("Skills & Capabilities", "L5", 7),
    ("Integration & Tools", "L6", 8),
    ("Data & Persistence", "L7", 6),
    ("Response & Output", "L8", 4),
    ("Cross-cutting", "X", 9),
]
SCENES = [
    {
        "n": 1,
        "id": "book",
        "title": "The build book",
        "beats": _beats(1, "Release R6 at a glance.", "Sealed in your vault."),
        "facts": _facts(
            ("Release", "R6"),
            ("Commit", "3f2a1c9"),
            ("Packages", "38", 38),
            ("Lines", "61,240", 61240),
        ),
    },
    {
        "n": 2,
        "id": "layers",
        "title": "Eight layers",
        "beats": _beats(2, "Eight layers.", "The core loop.", focus=("L1", "L4")),
        "facts": _facts(*[(a, b, c) for a, b, c in LAYERS]),
    },
    {
        "n": 3,
        "id": "turn",
        "title": "One conversation turn",
        "beats": _beats(
            3, "A message arrives.", "The gateway checks it.", focus=("Console", "Gateway")
        ),
        "facts": _facts(
            ("Console", "jarvis.api.chat"),
            ("Guard", "jarvis.core.guard"),
            ("Context", "jarvis.memory"),
            ("Brain", "jarvis.llm"),
            ("Gateway", "jarvis.tools.gateway"),
            ("Tool", "jarvis.tools"),
            ("Audit", "jarvis.tools.audit"),
            ("Reply", "jarvis.api.chat"),
        ),
    },
    {
        "n": 4,
        "id": "memory",
        "title": "Memory and privacy",
        "beats": _beats(4, "The vault is sealed.", focus=("vault",)),
        "facts": _facts(
            ("Vault chunks", "512 KiB", 6, "vault"),
            ("vault", "", None, "purpose"),
            ("memory", "", None, "purpose"),
            ("book_index", "", None, "purpose"),
            ("book_session", "", None, "purpose"),
        ),
    },
    {
        "n": 5,
        "id": "confirm",
        "title": "Confirm before commit",
        "beats": _beats(5, "An approval waits.", focus=("Passkey",)),
        "facts": _facts(("Approval card",), ("Passkey",), ("Gateway",), ("Audit",)),
    },
    {
        "n": 6,
        "id": "voice",
        "title": "Voice",
        "beats": _beats(6, "Your voice comes in."),
        "facts": _facts(
            ("Microphone",),
            ("VAD",),
            ("Speech to text",),
            ("Brain",),
            ("Text to speech",),
            ("Speaker",),
        ),
    },
    {
        "n": 7,
        "id": "home",
        "title": "Home",
        "beats": _beats(7, "Faces stay home."),
        "facts": _facts(
            ("Laptop", "", None, "edge"),
            ("Camera", "", None, "home"),
            ("Faces", "stay home", None, "home"),
            ("Alerts", "", None, "cloud"),
        ),
    },
    {
        "n": 8,
        "id": "own",
        "title": "On its own",
        "beats": _beats(8, "The morning tick."),
        "facts": _facts(("Morning tick",), ("Brief",), ("Vitals",), ("Telegram",)),
    },
    {
        "n": 9,
        "id": "stack",
        "title": "Stack and licences",
        "beats": _beats(9, "What I run on."),
        "facts": _facts(
            ("fastapi", "MIT", None, "web"),
            ("pydantic", "MIT", None, "data"),
            ("three.js", "MIT", None, "3d"),
            ("hey_jarvis", "CC BY-NC-SA 4.0", None, "voice", "non_commercial"),
        ),
    },
    {
        "n": 10,
        "id": "costs",
        "title": "Costs",
        "beats": _beats(10, "What I cost."),
        "facts": _facts(
            ("Balanced brain", "₹190.48 per 1M tokens", 190.48, "model"),
            ("Cloud voice", "₹2,857 per 1M characters", 2857.2, "voice"),
            ("Cloud Run", "free allowance", 0, "cloud", "free"),
        ),
    },
    {
        "n": 11,
        "id": "later",
        "title": "Not built yet",
        "beats": _beats(11, "Not built yet."),
        "facts": _facts(
            ("Voice ID", "", None, "deferred"), ("Sharing the sealed code", "", None, "not_in_plan")
        ),
    },
]
HEARD = "How do you keep my data private?"  # what show/hear answers for a spoken question
LINES = {
    "ask": "Do you have any questions about how I'm built?",
    "anything_else": "Anything else you'd like to know?",
    "hand_back": "Please hand the device back to my owner.",
}
CLOSING = {
    "guest": [
        {
            "id": "credit",
            "text": "Everything you've seen was designed and built by my owner and creator. The credit is all his.",
        },
        {
            "id": "sealed_guest",
            "text": "The code is sealed in my vault, for the people my owner allows.",
        },
        {"id": "thanks_guest", "text": "Thank you for listening."},
    ],
    "owner": [
        {
            "id": "credit",
            "text": "Everything you've seen was designed and built by my owner and creator. The credit is all his.",
        },
        {
            "id": "sealed_owner",
            "text": "The code is sealed in your vault, for the people you allow, Sir.",
        },
        {"id": "thanks_owner", "text": "Thank you, Sir."},
    ],
}


def script(audience: str = "guest", scenes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """GET /v1/book/show/script: {release, audience, scenes, lines, closing, costs, talk, until}."""
    return {
        "release": {k: RELEASE[k] for k in ("id", "label", "committed_at")},
        "audience": audience,
        "scenes": SCENES if scenes is None else scenes,
        "lines": {k: {"id": k, "text": v} for k, v in LINES.items()},
        "closing": CLOSING[audience],
        "costs": {"month_inr": 412.5, "limit_inr": 1500} if audience == "owner" else {},
        "talk": {"on": True},
        "until": "2099-01-01T00:00:00+00:00",
    }


def wav(seconds: float = 0.15, rate: int = 16000) -> bytes:
    """A short, valid, silent PCM16 mono WAV (what show/speak answers in the stubs)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


# JarvisPasskey.prove is replaced (the vault tests do the same): the ceremony itself is tested in
# test_permissions.py. Every call is recorded with its purpose and target.
PASSKEY_STUB = """
window.__proofs = [];
window.JarvisPasskey = Object.assign({}, window.JarvisPasskey, {
  prove: async (purpose, target) => { window.__proofs.push([purpose, target]); return { purpose, target, stub: true }; },
  message: (e) => (e && e.message) || 'x',
});
"""
# A browser voice that "speaks" instantly (headless Chromium has no voices) and records each line.
SPEECH_STUB = """
window.__spoken = [];
(() => {
  const synth = { speaking: false, pending: false, paused: false,
    speak(u) { window.__spoken.push(u.text); setTimeout(() => { u.onstart && u.onstart(); setTimeout(() => u.onend && u.onend(), 60); }, 10); },
    cancel() {}, pause() {}, resume() {}, getVoices() { return []; } };
  try { Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true }); } catch (_) {}
})();
"""


def google_mode(page: Any) -> None:
    """/console/config says Google sign-in: a guest lock exists only there, so only there the show asks
    for it. Routed after the console booted with the test token (token mode), or on the show page alone."""
    config = {"auth_mode": "google", "honorific": "Sir", "brain": "mock", "privacy_warning": ""}
    page.route("**/console/config", lambda r: j(r, 200, config))


def j(route: Any, status_code: int, body: Any) -> None:
    route.fulfill(
        status=status_code,
        content_type="application/json",
        body=json.dumps(body),
        headers={"Cache-Control": "no-store"},
    )


class FakeBook:
    """Every book route of the Contract, stubbed on one page; records (method, path, headers, body)."""

    def __init__(self, page: Any, **status_over: Any) -> None:
        self.page = page
        self.calls: list[dict[str, Any]] = []
        self.status = status(**status_over)
        self.open_answers: list[tuple[int, Any]] = []  # consumed in order; then a fresh token
        self.script_answer: tuple[int, Any] = (200, script("guest"))
        self.script_fails: list[
            Any
        ] = []  # consumed first: a status code, or "abort" (the network drops)
        self.hear_answers: list[
            Any
        ] = []  # consumed in order ("abort" or (code, body)); then {text}
        self.speak_status = 200
        self.ask_answers: list[dict[str, Any]] = []
        self.lock: dict[str, Any] | None = {"on": False}  # None: a server without the lock route
        self.resume_answers: list[
            Any
        ] = []  # consumed in order ("abort" or (code, body)); then resumed
        self.settings = {
            "creator_name": "",
            "show_voice": "cloud",
            "talk_on": True,
            "allow_training_brain": False,
        }
        page.route("**/v1/book", self._status)
        page.route("**/v1/book/**", self._route)

    def _record(self, route: Any) -> dict[str, Any]:
        req = route.request
        path = "/" + req.url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        body: Any = None
        raw = req.post_data_buffer  # bytes: a spoken question is a WAV, not text
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except ValueError:  # UnicodeDecodeError is a ValueError too
                body = raw
        call = {"method": req.method, "path": path, "headers": dict(req.headers), "body": body}
        self.calls.append(call)
        return call

    def to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def _status(self, route: Any) -> None:
        self._record(route)
        j(route, 200, self.status)

    def _route(self, route: Any) -> None:  # noqa: C901 - one table of routes
        c = self._record(route)
        m, p = c["method"], c["path"]
        if p == "/v1/book/open" and m == "POST":
            code, body = self.open_answers.pop(0) if self.open_answers else (200, self.opened(c))
            return j(route, code, body)
        if p == "/v1/book/sections" or p.endswith("/sections"):
            return j(route, 200, {"release": RELEASE, "sections": SECTIONS})
        if p.endswith("/ticket") and m == "POST":
            return j(route, 200, {"ticket": "tk_" + "a" * 20, "expires_in_s": 60})
        if p.startswith("/v1/book/download/"):
            return route.fulfill(
                status=200,
                body=b"PK\x05\x06" + b"\x00" * 18,
                headers={
                    "Content-Type": "application/zip",
                    "X-Content-Type-Options": "nosniff",
                    "Content-Disposition": 'attachment; filename="JARVIS-source-9b97eab.zip"',
                },
            )
        if p == "/v1/book/settings":
            if m == "PUT" and isinstance(c["body"], dict):
                self.settings.update(c["body"])
            return j(route, 200, self.settings)
        if p == "/v1/book/show/script":
            if self.script_fails:
                return self._fail(route, self.script_fails.pop(0))
            return j(route, *self.script_answer)
        if p == "/v1/book/show/hear" and m == "POST":
            got = self.hear_answers.pop(0) if self.hear_answers else (200, {"text": HEARD})
            return self._fail(route, got) if got == "abort" else j(route, *got)
        if p == "/v1/book/show/speak":
            if self.speak_status != 200:
                return j(
                    route, self.speak_status, {"error": "voice_off", "detail": "No cloud voice."}
                )
            return route.fulfill(status=200, body=wav(), headers={"Content-Type": "audio/wav"})
        if p == "/v1/book/show/ask":
            return j(route, 200, self.ask_answers.pop(0) if self.ask_answers else self.reply())
        if p == "/v1/book/show/beat":
            return j(route, 200, {"until": "2099-01-01T00:00:00+00:00"})
        if p == "/v1/book/show/lock":
            if self.lock is None:
                return j(route, 404, {"error": "not_found", "detail": "Not Found"})
            return j(route, 200, self.lock)
        if p == "/v1/book/close":
            return j(route, 200, {"closed": True, "wiped": True, "notified": True})
        if p == "/v1/book/resume":
            got = self.resume_answers.pop(0) if self.resume_answers else (200, {"resumed": True})
            return self._fail(route, got) if got == "abort" else j(route, *got)
        return j(route, 404, {"error": "not_found", "detail": p})

    @staticmethod
    def _fail(route: Any, how: Any) -> None:
        """ "abort": the connection drops (fetch rejects with a TypeError); a number: that status."""
        if how == "abort":
            return route.abort("failed")
        return j(route, int(how), {"error": "unavailable", "detail": "Try again in a moment."})

    @staticmethod
    def opened(call: dict[str, Any]) -> dict[str, Any]:
        audience = (call.get("body") or {}).get("audience", "owner")
        return {
            "token": TOKEN,
            "session_id": "bk_0123456789abcdef",
            "audience": audience,
            "until": "2099-01-01T00:00:00+00:00",
        }

    @staticmethod
    def reply(
        text: str = "I read e-mail through the Gmail connector, behind the gateway.",
        refused: bool = False,
        left: int = 19,
    ) -> dict[str, Any]:
        return {
            "reply_id": "r_0123456789ab",
            "reply": text,
            "refused": refused,
            "follow_up": LINES["anything_else"],
            "left": left,
        }
