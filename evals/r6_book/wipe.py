# evals/r6_book/wipe.py
"""R6 eval part `wipe` (builder C): after a book session closes, its conversation is gone and the
owner is told (D14). Through the real app with the worst-case brain (it echoes the question).

Cases: a guest asks a needle question (answered) and a needle owner-data ask (refused), then the
closing ends the session. Afterwards the needle is in no document (the book's and the app's:
memory, Activity, billing, permissions), no History session, no log record, no audit entry and
no notice (Telegram text); the session document reads back absent; exactly ONE content-free
`book_session_closed` notice; the audit holds exactly `book_open` + `book_close`; an abandoned
session is swept by the `book_sweep` job ("ended by itself").
Negative control: the delete skipped (the store says it deleted, but did not).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from book_app_fakes import book, book_app, open_book, register_passkey, sign_in
from book_show_fakes import Clock

from jarvis.buildbook.service import BookSweepJob
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.config import LLMBackend, Settings

PART = "wipe"
BUILT = True
NEEDLE = "NEEDLE4417"
Case = dict[str, Any]


class _Keep(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.text: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.text.append(f"{record.getMessage()} {record.__dict__}")


def _case(cid: str, ok: bool, why: str) -> Case:
    return {"id": f"{PART}:{cid}", "passed": ok, "failures": [] if ok else [why]}


@asynccontextmanager
async def _app() -> AsyncIterator[Any]:
    s = Settings(_env_file=None, env="dev", llm_backend=LLMBackend.MOCK, usd_inr_live=False)
    gen = book_app(s)
    app = await gen.__anext__()
    app.state.book_clock = Clock()
    keep, root = _Keep(), logging.getLogger()
    root.addHandler(keep)
    level, root.level = root.level, logging.DEBUG
    app.state.eval_logs = keep
    try:
        yield app
    finally:
        root.removeHandler(keep)
        root.level = level
        await gen.aclose()


async def _show(app: Any) -> tuple[str, dict[str, Any]]:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        opened = await open_book(c, auth, "guest")
        h = book(opened["token"])
        await c.get("/v1/book/show/script", headers=h)
        replies = []
        for q in (f"How does the {NEEDLE} voice pipeline work?", f"What is {NEEDLE}'s e-mail?"):
            r = await c.post("/v1/book/show/ask", json={"text": q}, headers=h)
            replies.append(r.json()["reply"])
        app.state.eval_replies = replies
        app.state.book_clock.advance(minutes=4)
        closed = (await c.post("/v1/book/close", json={"reason": "closing"}, headers=h)).json()
    return opened["session_id"], closed


async def _places(app: Any) -> dict[str, str]:
    """Every place a question could have landed, as text."""
    audit = await app.state.gateway.audit.tail(500)
    store = app.state.store
    return {
        "book documents": app.state.book_docs.dump(),
        "app documents (memory, Activity, billing)": json.dumps(
            app.state.activity_store._d._data, default=str, ensure_ascii=False
        ),
        "History sessions": json.dumps(
            {k: v.model_dump(mode="json") for k, v in store._data.items()}, ensure_ascii=False
        ),
        "logs": "\n".join(app.state.eval_logs.text),
        "audit": " ".join(e.model_dump_json() for e in audit.entries),
        "notices": " ".join(m for _, _, m in app.state.book_notifier.sent),
    }


async def _after_close(app: Any) -> list[Case]:
    sid, closed = await _show(app)
    went = NEEDLE in app.state.book_provider.seen() and NEEDLE in app.state.eval_replies[0]
    out = [_case("needle-went-through-the-lane", went, "the scan below would prove nothing")]
    out += [
        _case(
            "close-answer", closed == {"closed": True, "wiped": True, "notified": True}, str(closed)
        )
    ]
    gone = await app.state.book_docs.get(f"jarvis_book_sessions/{sid}")
    out.append(
        _case("session-document-absent", gone is None, "the session document is still there")
    )
    for place, text in (await _places(app)).items():
        out.append(_case(f"no-needle:{place}", NEEDLE not in text, f"the question is in {place}"))
    sent = app.state.book_notifier.sent
    kinds = [s.kind for _, s, _ in sent]
    one = kinds == ["book_session_closed"] and "Its conversation was deleted" in sent[0][2]
    out.append(_case("one-content-free-notice", one, str(kinds)))
    tail = await app.state.gateway.audit.tail(500)
    tools = [e.tool for e in tail.entries if e.tool.startswith("book_")]
    out.append(_case("audit-open-and-close-only", tools == ["book_open", "book_close"], str(tools)))
    return out


async def _abandoned(app: Any) -> list[Case]:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        await open_book(c, auth, "owner")
    app.state.book_clock.advance(minutes=12)
    counts = await BookSweepJob(app.state.book_service, clock=app.state.book_clock).run([])
    sent = app.state.book_notifier.sent
    ok = counts == {"closed": 1, "failed": 0} and len(sent) == 1 and "ended by itself" in sent[0][2]
    return [_case("abandoned-session-swept", ok, f"{counts} {[m for _, _, m in sent]}")]


async def _suite() -> list[Case]:
    async with _app() as app:
        out = await _after_close(app)
    async with _app() as app:
        out += await _abandoned(app)
    return out


async def cases() -> list[Case]:
    return await _suite()


async def control() -> dict[str, Any]:
    async def says_deleted(self: DocBookSessions, path: str) -> bool:
        return True  # skipped: nothing was deleted

    with patch.object(DocBookSessions, "_delete", says_deleted):
        results = await _suite()
    failed = [r["id"] for r in results if not r["passed"]]
    return {
        "name": "wipe: the delete skipped",
        "suite_failed": bool(failed),
        "failed_cases": failed,
    }
