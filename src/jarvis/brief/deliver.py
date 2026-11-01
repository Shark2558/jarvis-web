# src/jarvis/brief/deliver.py
"""Put the brief in the owner's own Gmail inbox (Layer 8 → 6) with `users.messages.insert`.

insert has no recipient: it adds one message to the authenticated mailbox and nothing leaves
the account, so it needs no R3 approval (R2, reversible: the owner can delete it). At most once
per day: the `sending` mark is taken in a transaction BEFORE the call, and the call is never
retried (a 5xx may come after Gmail stored it). An audit entry is written before the call
(fail closed: no record, no insert) and after it (best effort).
"""

from __future__ import annotations

from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid

from jarvis.brief.models import BriefRecord, InboxState
from jarvis.brief.render import subject_line
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleConnector, can_insert
from jarvis.logging import get_logger
from jarvis.tools.addresses import parse_address
from jarvis.tools.audit import AuditTrail
from jarvis.tools.card import one_line
from jarvis.tools.gmail_mime import b64url_encode, check_header_value

log = get_logger(__name__)

INSERT_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
LABELS = ("INBOX", "UNREAD")
AGENT = "morning_brief"
TOOL = "morning_brief.inbox"
SUBJECT_LIMIT = 200


def build_brief_message(*, owner: str, subject: str, body: str, now: datetime) -> str:
    """RFC 5322, text/plain UTF-8 (quoted-printable, CRLF), From "JARVIS" <owner>, To owner.
    Returned as Gmail's base64url `raw`. A Date header is set: insert uses it as the date."""
    addr = parse_address(owner)
    local, _, domain = addr.partition("@")
    msg = EmailMessage(policy=SMTP)
    msg["From"] = Address(display_name="JARVIS", username=local, domain=domain)
    msg["To"] = Address(username=local, domain=domain)
    msg["Subject"] = check_header_value(subject, name="subject", limit=SUBJECT_LIMIT)
    msg["Date"] = format_datetime(now)
    msg["Message-ID"] = make_msgid(idstring="jarvis-brief", domain=domain)
    msg.set_content(body, charset="utf-8", cte="quoted-printable")
    return b64url_encode(msg.as_bytes())


async def insert_message(conn: GoogleConnector, uid: str, raw: str) -> str:
    """One POST, never retried (retry_safe=False). Returns Gmail's message id."""
    out = await conn.request(
        uid,
        "POST",
        INSERT_URL,
        params={"internalDateSource": "dateHeader"},
        json={"raw": raw, "labelIds": list(LABELS)},
        retry_safe=False,
    )
    return one_line(out.get("id") if isinstance(out, dict) else "", 128)


class InboxDelivery:
    def __init__(self, google: GoogleConnector, store: BriefStore, audit: AuditTrail) -> None:
        self._google = google
        self._store = store
        self._audit = audit

    async def _address(self, uid: str) -> str | None:
        """The linked mailbox, if it is usable and allows insert."""
        st = await self._google.status(uid)
        if not st["connected"] or st["needs_reconnect"] or not can_insert(st["scopes"]):
            return None
        return str(st["email"] or "") or None

    async def deliver(self, uid: str, rec: BriefRecord, *, now: datetime) -> bool:
        """True iff this call inserted the brief. Never raises for Google or audit failures."""
        if rec.status != "ready" or rec.data is None or rec.inbox.status != "off":
            return False
        owner = await self._address(uid)
        if owner is None:
            await self._store.end_inbox(
                uid, rec.date, InboxState(status="failed", at=now), expect="off"
            )
            log.warning("brief inbox delivery skipped: link lacks insert permission")
            return False
        if await self._store.begin_inbox(uid, rec.date, now) is None:
            return False  # someone else holds (or held) today's mark
        args = {"date": rec.date}
        try:
            await self._audit.append(
                agent=AGENT, tool=TOOL, risk=ActionRisk.REVERSIBLE, outcome="executing", args=args
            )
        except Exception as exc:  # noqa: BLE001 — fail closed: no audit record, no insert
            log.error(
                "audit unavailable; brief NOT put in inbox", extra={"error": type(exc).__name__}
            )
            await self._settle(uid, rec.date, InboxState(status="failed", at=now))
            return False
        try:
            raw = build_brief_message(
                owner=owner, subject=subject_line(rec.data), body=rec.text, now=now
            )
            mid = await insert_message(self._google, uid, raw)
        except Exception as exc:  # noqa: BLE001 — recorded, never retried
            log.warning("brief inbox delivery failed", extra={"reason": type(exc).__name__})
            await self._settle(uid, rec.date, InboxState(status="failed", at=now))
            await self._audit_after(args, "error", type(exc).__name__)
            return False
        await self._settle(uid, rec.date, InboxState(status="delivered", at=now, message_id=mid))
        await self._audit_after(args, "executed", "")
        log.info("brief put in inbox", extra={"date": rec.date})
        return True

    async def _settle(self, uid: str, day: str, state: InboxState) -> None:
        try:
            await self._store.end_inbox(uid, day, state)
        except Exception as exc:  # noqa: BLE001 — the mark stays "sending" → shown as unknown
            log.error("brief inbox state not saved", extra={"error": type(exc).__name__})

    async def _audit_after(self, args: dict[str, str], outcome: str, detail: str) -> None:
        try:
            await self._audit.append(
                agent=AGENT,
                tool=TOOL,
                risk=ActionRisk.REVERSIBLE,
                outcome=outcome,
                args=args,
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 — it already happened; log loudly
            log.error("AUDIT WRITE FAILED after brief insert", extra={"error": type(exc).__name__})


__all__ = ["INSERT_URL", "InboxDelivery", "build_brief_message", "insert_message"]
