# tests/test_brief_deliver.py — slice 7: RFC 5322 brief + Gmail messages.insert, at most once
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from email import message_from_bytes
from email.policy import default as default_policy

import pytest
from brief_fakes import OWNER_EMAIL, OWNER_UID, BriefGoogle, connector

from jarvis.brief.deliver import (
    INSERT_URL,
    InboxDelivery,
    build_brief_message,
    insert_message,
)
from jarvis.brief.models import BriefData
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)
DAY = "2027-01-15"
BODY = "JARVIS morning brief — Friday\n\n  10:00–11:00  Review · ⚠ clashes ₹3\n"


def _parse(raw: str) -> object:
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return data, message_from_bytes(data, policy=default_policy)


def test_message_is_plain_utf8_from_jarvis_to_the_owner_only() -> None:
    raw = build_brief_message(
        owner="Akash@Example.com", subject="JARVIS morning brief — Fri 15 Jan", body=BODY, now=NOW
    )
    data, msg = _parse(raw)
    assert msg["From"].addresses[0].display_name == "JARVIS"  # type: ignore[attr-defined]
    assert msg["From"].addresses[0].addr_spec == "akash@example.com"  # type: ignore[attr-defined]
    assert str(msg["To"]) == "akash@example.com"  # type: ignore[index]
    assert msg["Cc"] is None and msg["Bcc"] is None  # type: ignore[index]
    assert str(msg["Subject"]) == "JARVIS morning brief — Fri 15 Jan"  # type: ignore[index]
    assert msg["Date"].datetime == NOW and msg["Message-ID"]  # type: ignore[index]
    assert msg.get_content_type() == "text/plain"  # type: ignore[attr-defined]
    assert msg.get_content_charset() == "utf-8"  # type: ignore[attr-defined]
    assert msg.get_content().replace("\r\n", "\n") == BODY  # type: ignore[attr-defined]
    assert b"\r\n" in data and data.isascii()  # CRLF, 7-bit transport-safe
    assert b"\n" not in data.replace(b"\r\n", b"")  # no bare LF anywhere


@pytest.mark.parametrize("owner", ["", "not-an-address", "a@b.c\r\nBcc: x@evil.com", "x <a@b.co>"])
def test_bad_owner_address_is_refused(owner: str) -> None:
    with pytest.raises(ValueError):
        build_brief_message(owner=owner, subject="s", body="b", now=NOW)


def test_subject_header_injection_is_refused() -> None:
    with pytest.raises(ValueError):
        build_brief_message(owner=OWNER_EMAIL, subject="hi\r\nBcc: x@evil.com", body="b", now=NOW)


async def test_insert_call_shape_and_no_retry() -> None:
    fake = BriefGoogle()
    conn = await connector(fake)
    mid = await insert_message(conn, OWNER_UID, "UkFX")
    req = fake.inserts[0]
    assert str(req.url).startswith(INSERT_URL)
    assert INSERT_URL == "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    assert req.method == "POST" and req.url.params["internalDateSource"] == "dateHeader"
    assert json.loads(req.content) == {"raw": "UkFX", "labelIds": ["INBOX", "UNREAD"]}
    assert mid == "ins1"
    fake.fail["insert"] = 503
    with pytest.raises(GoogleAPIError):
        await insert_message(conn, OWNER_UID, "UkFX")
    posts = [r for r in fake.requests if r.method == "POST"]
    assert len(posts) == 2  # one success + ONE failed attempt: never retried


# ---- orchestration --------------------------------------------------------------------------


async def _ready_store() -> BriefStore:
    store = BriefStore(MemoryDocs())
    c = await store.claim(
        OWNER_UID,
        DAY,
        tz="Asia/Kolkata",
        trigger="scheduled",
        force=False,
        now=NOW,
        max_generations=6,
    )
    await store.finish(
        c.record.model_copy(
            update={"status": "ready", "data": BriefData(date=DAY, tz="Asia/Kolkata"), "text": BODY}
        )
    )
    return store


async def test_delivery_marks_sends_once_and_audits() -> None:
    fake = BriefGoogle()
    store, audit = await _ready_store(), AuditLog()
    d = InboxDelivery(await connector(fake), store, audit)
    rec = await store.get_brief(OWNER_UID, DAY)
    assert rec is not None
    assert await d.deliver(OWNER_UID, rec, now=NOW) is True
    assert await d.deliver(OWNER_UID, rec, now=NOW) is False
    assert len(fake.inserts) == 1
    after = await store.get_brief(OWNER_UID, DAY)
    assert after is not None and after.inbox.status == "delivered"
    assert after.inbox.message_id == "ins1"
    raw = json.loads(fake.inserts[0].content)["raw"]
    _, msg = _parse(raw)
    assert msg.get_content().replace("\r\n", "\n") == BODY  # type: ignore[attr-defined]
    tail = (await audit.tail(10)).entries
    assert [(e.agent, e.tool, e.outcome, e.risk) for e in tail] == [
        ("morning_brief", "morning_brief.inbox", "executing", ActionRisk.REVERSIBLE),
        ("morning_brief", "morning_brief.inbox", "executed", ActionRisk.REVERSIBLE),
    ]
    assert OWNER_EMAIL not in str([e.model_dump() for e in tail])  # no content in the audit


async def test_failure_is_recorded_and_never_retried() -> None:
    fake = BriefGoogle(fail={"insert": 500})
    store = await _ready_store()
    d = InboxDelivery(await connector(fake), store, AuditLog())
    rec = await store.get_brief(OWNER_UID, DAY)
    assert rec is not None
    assert await d.deliver(OWNER_UID, rec, now=NOW) is False
    fake.fail.clear()
    assert await d.deliver(OWNER_UID, rec, now=NOW) is False
    assert len([r for r in fake.requests if r.method == "POST"]) == 1
    after = await store.get_brief(OWNER_UID, DAY)
    assert after is not None and after.inbox.status == "failed"


async def test_missing_insert_scope_fails_without_calling_google() -> None:
    fake = BriefGoogle()
    store = await _ready_store()
    d = InboxDelivery(await connector(fake, insert=False), store, AuditLog())
    rec = await store.get_brief(OWNER_UID, DAY)
    assert rec is not None
    assert await d.deliver(OWNER_UID, rec, now=NOW) is False
    assert fake.inserts == [] and not [r for r in fake.requests if r.method == "POST"]
    after = await store.get_brief(OWNER_UID, DAY)
    assert after is not None and after.inbox.status == "failed"


class _DeadAudit(AuditLog):
    async def append(self, **kw: object) -> object:  # type: ignore[override]
        raise RuntimeError("audit down")


async def test_no_audit_record_means_no_insert() -> None:
    fake = BriefGoogle()
    store = await _ready_store()
    d = InboxDelivery(await connector(fake), store, _DeadAudit())
    rec = await store.get_brief(OWNER_UID, DAY)
    assert rec is not None
    assert await d.deliver(OWNER_UID, rec, now=NOW) is False
    assert fake.inserts == []
    after = await store.get_brief(OWNER_UID, DAY)
    assert after is not None and after.inbox.status == "failed"
