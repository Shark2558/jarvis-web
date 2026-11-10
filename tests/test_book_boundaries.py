# tests/test_book_boundaries.py -- R6 D11/D12 boundaries of builder C's code, checked statically and
# at run time: the talk lane gets brains, billing and the no-AI switch through its constructor
# only and never imports the brain, tools, memory, documents, the Google link, the persona or the
# app; nothing logs a question, reply, token or book text (an AST scan of every log call and a
# needle in a whole guest show's log output); every module <= 400 lines and function <= 50.
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import pytest
from book_app_fakes import book, book_app, open_book, register_passkey, sign_in
from book_show_fakes import Clock

from jarvis.config import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
C_MODULES = [
    SRC / "buildbook" / f"{n}.py"
    for n in (
        "sessions",
        "lock",
        "guard",
        "guard_words",
        "prompt",
        "digest",
        "talk",
        "service",
        "show_script",
        "closing",
        "telling",
        "unlock",
    )
] + [
    SRC / "api" / f"{n}.py"
    for n in ("book_show", "book_lock", "book_show_access", "book_show_wiring")
]
LANE_FORBIDDEN = (
    "jarvis.core.brain",
    "jarvis.core.persona",
    "jarvis.core.prompts",
    "jarvis.tools",
    "jarvis.memory",
    "jarvis.documents",
    "jarvis.integrations.google",
    "jarvis.api",
    "jarvis.offline",
    "anthropic",
    "google.genai",
    "openai",
)
CONTENT_NAMES = {
    "text",
    "question",
    "reply",
    "answer",
    "token",
    "turns",
    "blob",
    "message",
    "asked",
    "said",
    "body",
    "heard",
}
NEEDLE = "NEEDLE5521"


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize(
    "name",
    [
        "talk",
        "guard",
        "guard_words",
        "prompt",
        "digest",
        "sessions",
        "closing",
        "telling",
        "lock",
        "show_script",
    ],
)
def test_the_lane_imports_nothing_that_reaches_the_owner(name: str) -> None:
    mods = _imports(SRC / "buildbook" / f"{name}.py")
    assert not [m for m in mods if any(m == b or m.startswith(b + ".") for b in LANE_FORBIDDEN)]


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def test_the_lane_gets_brains_billing_and_mode_by_constructor_and_never_tools() -> None:
    src = (SRC / "buildbook" / "talk.py").read_text(encoding="utf-8")
    assert "app.state" not in src and "Gateway" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "tools":
            assert _is_none(node.value)
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == "tools":
                    assert _is_none(v)
    assert '"tools": None' in src
    init = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    assert [a.arg for a in init.args.args][:6] == [
        "self",
        "brains",
        "billing",
        "mode",
        "book",
        "sessions",
    ]


def _log_calls(path: Path) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "log"
    ]


@pytest.mark.parametrize("path", C_MODULES, ids=lambda p: p.name)
def test_no_log_call_carries_content(path: Path) -> None:
    for call in _log_calls(path):
        assert call.args and isinstance(call.args[0], ast.Constant), ast.unparse(call)
        used = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}
        assert not used & CONTENT_NAMES, ast.unparse(call)


@pytest.mark.parametrize("path", C_MODULES, ids=lambda p: p.name)
def test_sizes(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 400
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            assert (node.end_lineno or 0) - node.lineno + 1 <= 50, node.name


class Keep(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def test_a_whole_guest_show_logs_no_question_reply_or_token(settings: Settings) -> None:
    keep = Keep()  # the app's configure_logging replaces the root handlers: add ours after
    async for app in book_app(settings):
        root = logging.getLogger()
        root.addHandler(keep)
        level, root.level = root.level, logging.DEBUG
        app.state.book_clock = Clock()
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            opened = await open_book(c, auth, "guest")
            h = book(opened["token"])
            await c.get("/v1/book/show/script", headers=h)
            for q in (f"How does {NEEDLE} voice work?", f"What is {NEEDLE} owner's e-mail?"):
                await c.post("/v1/book/show/ask", json={"text": q}, headers=h)
            await c.post("/v1/book/close", json={}, headers=h)
        root.removeHandler(keep)
        root.level = level
        text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in keep.records)
        assert NEEDLE not in text and opened["token"] not in text
        assert keep.records  # the run did log (sign-in, passkey, ...)


def test_the_audit_holds_no_content(settings: Any) -> None:
    src = (SRC / "buildbook" / "service.py").read_text(encoding="utf-8")
    for call in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)]:
        if isinstance(call.func, ast.Attribute) and call.func.attr in ("record", "append"):
            used = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}
            assert not used & (CONTENT_NAMES - {"message"}), ast.unparse(call)
