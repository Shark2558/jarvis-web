# src/jarvis/brief/render.py
"""BriefData → plain text (Layer 8). Every fact is rendered by code from data; the optional AI
lines come last under their label, so the facts above them are identical with or without AI
(the injection eval asserts exactly that). The section JSON is `BriefData` itself.

This text is also the body of the message put in the owner's inbox *from "JARVIS"*, and mail
clients make URLs in plain text clickable. Other people's words (titles, places, names,
subjects) therefore have links replaced here, so a hostile subject cannot borrow JARVIS's name
for a phishing link. `BriefData` keeps the one-line original (the console shows it as text)."""

from __future__ import annotations

import re
from datetime import date

from jarvis.brief.models import AI_LABEL, AIBlock, BriefData, BriefEvent, SectionState

NOT_CONNECTED = "Google is not connected: connect it in the console (Integrations) to see your {}."
UNAVAILABLE = "Your {} could not be read just now."
LINK = "[link removed]"

# Order matters: schemes before bare domains.
_SCHEME_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]{0,15}://\S*")
_SCHEME_ONLY = re.compile(r"(?i)\b(?:mailto|javascript|vbscript|data|tel|sms|file|blob):\S+")
_WWW = re.compile(r"(?i)\bwww\.\S*")
_TLDS = (
    "com|net|org|io|co|ai|app|dev|me|info|biz|xyz|top|site|online|link|click|live|ly|gl|to|"
    "in|uk|us|ru|cn|tk|ml|ga|cf|gq|zip|mov|gov|edu|xn--[a-z0-9-]+"
)
_BARE_DOMAIN = re.compile(rf"(?i)\b(?:[a-z0-9-]+\.)+(?:{_TLDS})\b(?:[/?#:]\S*)?")
SCHEME_PATTERNS = (_SCHEME_URL, _SCHEME_ONLY, _WWW)
LINK_PATTERNS = (*SCHEME_PATTERNS, _BARE_DOMAIN)


def strip_links(text: str) -> str:
    """Replace anything a mail client would turn into a link with '[link removed]'."""
    for rx in LINK_PATTERNS:
        text = rx.sub(LINK, text)
    return text


def long_date(day: str) -> str:
    return date.fromisoformat(day).strftime("%A %d %B %Y")


def subject_line(data: BriefData) -> str:
    return f"JARVIS morning brief — {date.fromisoformat(data.date).strftime('%a %d %b')}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _status_line(state: SectionState, what: str) -> str | None:
    if state == "not_connected":
        return "  " + NOT_CONNECTED.format(what)
    if state == "unavailable":
        return "  " + UNAVAILABLE.format(what)
    return None


def when(e: BriefEvent) -> str:
    if e.all_day:
        return "All day"
    start = "…" if e.starts_earlier else e.start
    end = f"{e.end} (next day)" if e.ends_later else e.end
    return f"{start}–{end}"


def event_line(e: BriefEvent) -> str:
    parts = [strip_links(e.title)]
    if e.attendees > 1:
        parts.append(f"{e.attendees} people")
    if e.has_video:
        parts.append("video")
    if e.location:
        parts.append(strip_links(e.location))
    if e.overlaps_with:
        parts.append("⚠ clashes with " + ", ".join(strip_links(t) for t in e.overlaps_with))
    return f"{when(e)}  " + " · ".join(parts)


def _today(data: BriefData) -> list[str]:
    cal = data.calendar
    head = "TODAY"
    if data.sections_status.calendar == "ok" and cal.today:
        head += f" · {_plural(len(cal.today), 'event')}"
        if cal.clashes:
            head += f" · {cal.clashes} clash" + ("" if cal.clashes == 1 else "es")
    lines = [head]
    if (note := _status_line(data.sections_status.calendar, "calendar")) is not None:
        return [*lines, note]
    lines += [f"  {event_line(e)}" for e in cal.today] or ["  Nothing on the calendar today."]
    if cal.free_blocks:
        lines.append("  Free: " + ", ".join(f"{b.start}–{b.end}" for b in cal.free_blocks))
    else:
        lines.append("  No free half-hour between 09:00 and 18:00.")
    return lines


def _tomorrow(data: BriefData) -> list[str]:
    if data.sections_status.calendar != "ok":
        return []
    first = data.calendar.tomorrow_first
    return ["TOMORROW", f"  First: {event_line(first)}" if first else "  Nothing yet tomorrow."]


def _inbox(data: BriefData) -> list[str]:
    box = data.inbox
    head = "INBOX"
    if data.sections_status.inbox == "ok" and box.total:
        head += f" · {box.total} unread in the last day (showing {len(box.items)})"
    if (note := _status_line(data.sections_status.inbox, "inbox")) is not None:
        return [head, note]
    lines = [head]
    for m in box.items:
        name = strip_links(m.from_name)
        who = (
            f"{name} <{m.from_address}>"
            if name and m.from_address
            else (m.from_address or name or "unknown sender")
        )
        lines.append(f"  {m.when + '  ' if m.when else ''}{who} — {strip_links(m.subject)}")
    return lines if box.items else [head, "  No unread mail in the last day."]


def _jarvis(data: BriefData) -> list[str]:
    if data.sections_status.jarvis != "ok":
        return ["JARVIS", "  Approvals could not be checked just now."]
    n = data.jarvis.approvals_waiting
    if not n:
        return ["JARVIS", "  No approvals waiting."]
    return ["JARVIS", f"  {_plural(n, 'approval')} waiting for you in the console."]


def _ai(ai: AIBlock | None, note: str | None) -> list[str]:
    if ai is not None and ai.lines:
        return [AI_LABEL, *(f"  • {x}" for x in ai.lines)]
    if note:
        return ["AI summary", f"  {note}"]
    return []


def render_text(data: BriefData, ai: AIBlock | None = None, ai_note: str | None = None) -> str:
    header = [f"JARVIS morning brief — {long_date(data.date)} ({data.tz})"]
    blocks = [header, _today(data), _tomorrow(data), _inbox(data), _jarvis(data), _ai(ai, ai_note)]
    return "\n\n".join("\n".join(b) for b in blocks if b) + "\n"


__all__ = [
    "LINK",
    "LINK_PATTERNS",
    "SCHEME_PATTERNS",
    "event_line",
    "long_date",
    "render_text",
    "strip_links",
    "subject_line",
    "when",
]
