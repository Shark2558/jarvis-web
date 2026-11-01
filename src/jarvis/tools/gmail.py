# src/jarvis/tools/gmail.py
"""Gmail tools (Layer 5/6, Communication) over the REST connector.

search/read are R1 and return only the fields asked for — search never returns bodies, read
truncates the body and lists attachments without fetching them. create_draft is R2. send is R3:
the approval card reads "Send an email to {to}: {subject}" and there is no "don't ask again".
Mail content reaches the model fenced as EXTERNAL CONTENT (see tools/external.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleConnector
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import sender_address, wrap_external
from jarvis.tools.gmail_mime import (
    build_raw_message,
    check_header_value,
    headers_of,
    parse_body,
    parse_recipients,
    reply_subject,
)

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
MESSAGES_URL = f"{BASE}/messages"
DRAFTS_URL = f"{BASE}/drafts"
SEND_URL = f"{BASE}/messages/send"
BODY_LIMIT = 8_000
SUBJECT_LIMIT = 300
SNIPPET_LIMIT = 300
MAX_RESULTS = 25
DEFAULT_RESULTS = 10
QUERY_LIMIT = 500
BODY_ARG_LIMIT = 20_000
META_HEADERS = ("From", "To", "Cc", "Date", "Subject", "Message-ID", "References")

_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

_TO = {"type": "string", "description": "Recipient address(es), comma-separated"}
_REPLY = {
    "type": "string",
    "description": "Gmail message id to reply to (threads the mail; subject gets Re:)",
}


def _validate_message_id(raw: Any) -> str:
    mid = str(raw or "")
    if not _MESSAGE_ID.match(mid):
        raise ValueError("message_id is not a valid Gmail message id")
    return mid


@dataclass
class GmailAPI:
    conn: GoogleConnector

    # ---- read side ------------------------------------------------------------------------

    async def _metadata(self, uid: str, mid: str) -> dict[str, Any]:
        data = await self.conn.request(
            uid,
            "GET",
            f"{MESSAGES_URL}/{mid}",
            params={"format": "metadata", "metadataHeaders": list(META_HEADERS)},
        )
        return dict(data) if isinstance(data, dict) else {}

    async def search(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        query = str(a.get("query") or "").strip()[:QUERY_LIMIT]
        if not query:
            raise ValueError("query is required (Gmail search syntax, e.g. from:x newer_than:7d)")
        limit = max(1, min(int(a.get("max") or DEFAULT_RESULTS), MAX_RESULTS))
        listing = await self.conn.request(
            uid, "GET", MESSAGES_URL, params={"q": query, "maxResults": limit}
        )
        ids = [str(m["id"]) for m in listing.get("messages") or [] if m.get("id")][:limit]
        messages = [self._summary(await self._metadata(uid, mid)) for mid in ids]
        return {"query": query, "messages": messages}

    def _summary(self, m: dict[str, Any]) -> dict[str, Any]:
        h = headers_of(m.get("payload") or {})
        sender = sender_address(h.get("from", "")) or "unknown sender"
        return {
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            "from": h.get("from", ""),
            "to": h.get("to", ""),
            "date": h.get("date", ""),
            "subject": wrap_external(
                h.get("subject", "(no subject)"), source=sender, limit=SUBJECT_LIMIT
            ),
            "snippet": wrap_external(
                str(m.get("snippet") or ""), source=sender, limit=SNIPPET_LIMIT
            ),
        }

    async def read(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        mid = _validate_message_id(a.get("message_id"))
        m = await self.conn.request(uid, "GET", f"{MESSAGES_URL}/{mid}", params={"format": "full"})
        payload = m.get("payload") or {}
        h = headers_of(payload)
        sender = sender_address(h.get("from", "")) or "unknown sender"
        parsed = parse_body(payload)
        return {
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            "from": h.get("from", ""),
            "to": h.get("to", ""),
            "cc": h.get("cc", ""),
            "date": h.get("date", ""),
            "subject": wrap_external(
                h.get("subject", "(no subject)"), source=sender, limit=SUBJECT_LIMIT
            ),
            "body": wrap_external(parsed.text or "(empty body)", source=sender, limit=BODY_LIMIT),
            "attachments": [
                {"name": x.name, "size": x.size, "mime_type": x.mime_type}
                for x in parsed.attachments
            ],
        }

    # ---- write side -----------------------------------------------------------------------

    async def _compose(self, uid: str, a: dict[str, Any]) -> tuple[str, str | None, list[str], str]:
        """→ (raw message, thread id, recipients, subject). Threading headers come from the
        original message when replying."""
        to = parse_recipients(a.get("to"))
        subject = check_header_value(a.get("subject"), name="subject", limit=SUBJECT_LIMIT)
        body = str(a.get("body") or "")[:BODY_ARG_LIMIT]
        in_reply_to = references = thread_id = None
        if a.get("reply_to_message_id"):
            original = await self._metadata(uid, _validate_message_id(a["reply_to_message_id"]))
            h = headers_of(original.get("payload") or {})
            in_reply_to = h.get("message-id") or None
            references = h.get("references") or None
            thread_id = original.get("threadId")
            subject = reply_subject(subject, h.get("subject", ""))
        raw = build_raw_message(
            to=to, subject=subject, body=body, in_reply_to=in_reply_to, references=references
        )
        return raw, thread_id, to, subject

    async def create_draft(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        raw, thread_id, to, subject = await self._compose(uid, a)
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        d = await self.conn.request(uid, "POST", DRAFTS_URL, json={"message": message})
        return {
            "draft_id": d.get("id"),
            "message_id": (d.get("message") or {}).get("id"),
            "to": ", ".join(to),
            "subject": subject,
        }

    async def send(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        raw, thread_id, to, _ = await self._compose(uid, a)
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        m = await self.conn.request(uid, "POST", SEND_URL, json=message)
        return {
            "sent": True,
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            "to": ", ".join(to),
        }


# ---- argument checks (pure; run before policy/approval) -------------------------------------


def _check_search(a: dict[str, Any]) -> None:
    if not str(a.get("query") or "").strip():
        raise ValueError("query is required")


def _check_message_id(a: dict[str, Any]) -> None:
    _validate_message_id(a.get("message_id"))


def _check_compose(a: dict[str, Any]) -> None:
    parse_recipients(a.get("to"))
    check_header_value(a.get("subject"), name="subject", limit=SUBJECT_LIMIT)
    if a.get("reply_to_message_id"):
        _validate_message_id(a["reply_to_message_id"])


_COMPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "to": _TO,
        "subject": {"type": "string"},
        "body": {"type": "string", "description": "Plain-text body"},
        "reply_to_message_id": _REPLY,
    },
    "required": ["to", "subject", "body"],
}


def gmail_tools(conn: GoogleConnector) -> list[Tool]:
    api = GmailAPI(conn)
    return [
        Tool(
            "gmail_search",
            "Search the owner's Gmail (Gmail query syntax). Returns id, from, to, date, subject "
            "and snippet for up to 25 messages — never full bodies; use gmail_read for one.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
                },
                "required": ["query"],
            },
            ActionRisk.READ_ONLY,
            api.search,
            agent="google",
            check=_check_search,
        ),
        Tool(
            "gmail_read",
            "Read one message by id: headers, text body (truncated to 8000 chars) and the list "
            "of attachments (names and sizes only).",
            {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
            ActionRisk.READ_ONLY,
            api.read,
            agent="google",
            check=_check_message_id,
        ),
        Tool(
            "gmail_create_draft",
            "Save a draft in the owner's Gmail (nothing is sent). Give reply_to_message_id to "
            "thread it as a reply.",
            _COMPOSE_SCHEMA,
            ActionRisk.REVERSIBLE,
            api.create_draft,
            agent="google",
            summary_template="Draft an email to {to}: {subject}",
            check=_check_compose,
        ),
        Tool(
            "gmail_send",
            "Send an email from the owner's Gmail. Irreversible: the owner must confirm every "
            "send. Give reply_to_message_id to reply in-thread.",
            _COMPOSE_SCHEMA,
            ActionRisk.IRREVERSIBLE,
            api.send,
            agent="google",
            summary_template="Send an email to {to}: {subject}",
            check=_check_compose,
        ),
    ]


__all__ = ["BODY_LIMIT", "GmailAPI", "gmail_tools"]
