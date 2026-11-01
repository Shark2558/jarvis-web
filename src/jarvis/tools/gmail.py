# src/jarvis/tools/gmail.py
"""Gmail tools (Layer 5/6, Communication) over the REST connector.

search/read are R1 and return only the fields asked for — search never returns bodies, read
truncates the body and lists attachments without fetching them. create_draft is R2 (its result
says "draft saved, not sent"). send is R3 and there is no "don't ask again": the approval card
shows every recipient (IDN domains also in punycode), the subject, the first 200 characters of
the body and whether it replies in a thread, each field flattened by `tools.card.one_line`.
Mail content reaches the model fenced as EXTERNAL CONTENT (see tools/external.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleConnector
from jarvis.tools.addresses import display_addresses, loose_address
from jarvis.tools.base import SummaryFn, Tool
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external
from jarvis.tools.gmail_mime import (
    Attachment,
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
CARD_SUBJECT_LIMIT = 200
CARD_BODY_LIMIT = 200
DRAFT_STATUS = "draft saved, not sent"
# What the model sees of headers other people wrote: bare addresses, capped lists, an ISO date;
# display names and attachment names are fenced as EXTERNAL CONTENT.
NAME_LIMIT = 120
DATE_LIMIT = 64
HEADER_SCAN_LIMIT = 10_000
MAX_LISTED_ADDRESSES = 20
MAX_ATTACHMENTS = 25
ATTACHMENT_NAME_LIMIT = 200
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}")
META_HEADERS = ("From", "To", "Cc", "Date", "Subject", "Message-ID", "References")

_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

_TO = {"type": "string", "description": "Recipient address(es), comma-separated"}
_REPLY = {
    "type": "string",
    "description": "Gmail message id to reply to (threads the mail; subject gets Re:)",
}


def _sender(header: str) -> tuple[str, str]:
    """From header → (bare address or '', display name or ''), both one clean line. When the
    header does not parse, the whole of it is treated as a (fenced) name."""
    flat = one_line(header, HEADER_SCAN_LIMIT)
    name, addr = parseaddr(flat)
    bare = loose_address(addr)
    if not bare:
        return "", one_line(flat, NAME_LIMIT)
    return bare, one_line(name, NAME_LIMIT)


def _addresses(header: str) -> list[str]:
    """To/Cc header → bare addresses, at most MAX_LISTED_ADDRESSES (+ an '… and N more')."""
    pairs = getaddresses([one_line(header, HEADER_SCAN_LIMIT)])
    found = [b for _, a in pairs if (b := loose_address(a))]
    if len(found) <= MAX_LISTED_ADDRESSES:
        return found
    return [*found[:MAX_LISTED_ADDRESSES], f"… and {len(found) - MAX_LISTED_ADDRESSES} more"]


def _date(header: str) -> str:
    flat = one_line(header, 200)
    try:
        return parsedate_to_datetime(flat).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return one_line(flat, DATE_LIMIT)


def _mime(value: str) -> str:
    m = one_line(value, 200).lower()
    return m if _MIME.fullmatch(m) else "application/octet-stream"


def _attachments(found: list[Attachment], source: str) -> list[dict[str, Any]]:
    """Names are someone else's words (a favourite place for "SYSTEM: …"): fenced and capped."""
    return [
        {
            "name": wrap_external(
                one_line(x.name, HEADER_SCAN_LIMIT), source=source, limit=ATTACHMENT_NAME_LIMIT
            ),
            "size": x.size,
            "mime_type": _mime(x.mime_type),
        }
        for x in found[:MAX_ATTACHMENTS]
    ]


def _people(h: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """→ (fence source, the from/from_name/to/date fields of a message)."""
    addr, name = _sender(h.get("from", ""))
    source = addr or "unknown sender"
    fields: dict[str, Any] = {"from": addr}
    if name:
        fields["from_name"] = wrap_external(name, source=source, limit=NAME_LIMIT)
    fields["to"] = _addresses(h.get("to", ""))
    fields["date"] = _date(h.get("date", ""))
    return source, fields


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
        sender, people = _people(h)
        return {
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            **people,
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
        sender, people = _people(h)
        parsed = parse_body(payload)
        out: dict[str, Any] = {
            "id": m.get("id"),
            "thread_id": m.get("threadId"),
            **people,
            "cc": _addresses(h.get("cc", "")),
            "subject": wrap_external(
                h.get("subject", "(no subject)"), source=sender, limit=SUBJECT_LIMIT
            ),
            "body": wrap_external(parsed.text or "(empty body)", source=sender, limit=BODY_LIMIT),
            "attachments": _attachments(parsed.attachments, sender),
        }
        if len(parsed.attachments) > MAX_ATTACHMENTS:
            out["attachments_not_listed"] = len(parsed.attachments) - MAX_ATTACHMENTS
        return out

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
            # the original subject is someone else's text: one clean line before it is reused
            subject = reply_subject(subject, one_line(h.get("subject", ""), SUBJECT_LIMIT))
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
            "status": DRAFT_STATUS,
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


def _compose_card(verb: str) -> SummaryFn:
    """Card text for a draft/send: recipients, subject, body preview, threading."""

    def summarize(a: dict[str, Any]) -> str:
        replying = bool(a.get("reply_to_message_id"))
        subject = one_line(a.get("subject"), CARD_SUBJECT_LIMIT) or (
            "(empty: the reply keeps the original subject)" if replying else "(no subject)"
        )
        lines = [
            verb,
            f"To: {display_addresses(parse_recipients(a.get('to')))}",
            f"Subject: {subject}",
            f"Body: {one_line(a.get('body'), CARD_BODY_LIMIT) or '(empty)'}",
        ]
        if replying:
            mid = one_line(a.get("reply_to_message_id"), 128)
            lines.append(f"Sent as a reply in thread (to message {mid})")
        return "\n".join(lines)

    return summarize


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
            summarize=_compose_card("Save a draft in Gmail (nothing is sent)"),
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
            summarize=_compose_card("Send an email (cannot be unsent)"),
            check=_check_compose,
        ),
    ]


__all__ = ["BODY_LIMIT", "GmailAPI", "gmail_tools"]
