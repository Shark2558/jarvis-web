# tests/test_r14_d_notes.py -- R14 D13 (4): `GET /v1/notes/export` leaves an audit line (agent
# `privacy`, the count only, never a note's words) BEFORE the file goes out; when the audit chain
# can't be written the export is refused (503, nothing sent). Before R14 the export left no trace.
from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from kb_fakes import Rig, build_rig
from pydantic import SecretStr
from starlette.middleware.sessions import SessionMiddleware

from jarvis.api.notes import EXPORT_AUDIT_TOOL, install_notes
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.audit import AuditLog

BEARER = {"Authorization": "Bearer cli-token"}
SECRET_WORDS = "the spare key is under the third flowerpot"


class RecordingAudit(AuditLog):
    def __init__(self) -> None:
        super().__init__()
        self.asked: list[dict[str, Any]] = []

    async def append(self, **kw: Any) -> Any:
        self.asked.append(kw)
        return await super().append(**kw)


class BrokenAudit(AuditLog):
    async def append(self, **kw: Any) -> Any:
        raise RuntimeError("audit store down")


def _app(s: Settings, rig: Rig, audit: AuditLog | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="x" * 32)
    app.state.settings = s
    app.state.notes = rig.svc
    app.state.gateway = SimpleNamespace(audit=audit) if audit is not None else None
    install_notes(app)
    return app


@pytest.fixture
def rig() -> Rig:
    return build_rig()


async def _client(s: Settings, rig: Rig, audit: AuditLog | None) -> AsyncIterator[AsyncClient]:
    app = _app(s.model_copy(update={"api_token": SecretStr("cli-token")}), rig, audit)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.headers.update(BEARER)
        yield c


async def _two_notes(c: AsyncClient) -> None:
    for text in (SECRET_WORDS, "second note"):
        assert (await c.post("/v1/notes", json={"kind": "note", "text": text})).status_code == 201


async def test_the_export_is_audited_with_the_count_only(settings: Settings, rig: Rig) -> None:
    audit = RecordingAudit()
    async for c in _client(settings, rig, audit):
        await _two_notes(c)
        r = await c.get("/v1/notes/export")
        assert r.status_code == 200 and len(r.json()["notes"]) == 2
    entries = (await audit.tail(10)).entries
    [entry] = [e for e in entries if e.tool == EXPORT_AUDIT_TOOL]
    assert (entry.agent, entry.outcome, entry.risk) == ("privacy", "executed", ActionRisk.READ_ONLY)
    assert entry.detail == "notes: 2" and "flowerpot" not in entry.model_dump_json()
    [asked] = [a for a in audit.asked if a["tool"] == EXPORT_AUDIT_TOOL]
    assert asked["args"] == {"count": 2}


async def test_an_export_the_audit_cannot_record_is_refused(settings: Settings, rig: Rig) -> None:
    async for c in _client(settings, rig, BrokenAudit()):
        await _two_notes(c)
        r = await c.get("/v1/notes/export")
        assert r.status_code == 503 and r.json()["error"] == "export_unaudited"
        assert "flowerpot" not in r.text and "content-disposition" not in r.headers


async def test_without_an_audit_chain_the_export_still_answers(
    settings: Settings, rig: Rig
) -> None:
    async for c in _client(settings, rig, None):  # tools switched off: there is no chain
        await _two_notes(c)
        assert (await c.get("/v1/notes/export")).status_code == 200
