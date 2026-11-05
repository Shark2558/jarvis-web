# src/jarvis/brief/render.py
"""BriefData → plain text (Layer 8). Every fact is rendered by code from data; the optional AI
lines come last under their label, so the facts above them are identical with or without AI
(the injection eval asserts exactly that). The section JSON is `BriefData` itself.

This text is also the body of the message put in the owner's inbox *from "JARVIS"*, and mail
clients make URLs in plain text clickable. Other people's words (titles, places, names,
subjects) are therefore shown in “ ” under a line saying who wrote them, and every link in them
is disarmed (`defang`): schemes and `//host` are removed, and every other domain-looking token
— any `label.letters`, in any script, no list of top-level domains — has its dots shown as
`[.]`, so a hostile subject cannot borrow JARVIS's name for a phishing link. The sender's
address is printed only when it is a strict ASCII addr-spec. `BriefData` keeps the one-line
original (the console shows it as text, never as a link)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from jarvis.brief.models import (
    AI_LABEL,
    AIBlock,
    BriefData,
    BriefEvent,
    InboxItem,
    SectionState,
    TodoItem,
)
from jarvis.tools.addresses import plain_address
from jarvis.tools.card import quoted, strip_invisible
from jarvis.tools.spoken import withhold_if_sensitive

NOT_CONNECTED = "Google is not connected: connect it in the console (Integrations) to see your {}."
UNAVAILABLE = "Your {} could not be read just now."
PARTIAL = (
    "JARVIS read only part of your to-do list (at most 10 lists and 300 tasks each), so there "
    "may be more."
)
NOT_GRANTED = (
    "JARVIS has no permission for your to-do list yet: press Grant next to 'To-do list' in the "
    "console (Integrations) to see it here."
)
OTHERS_NOTE = "Titles and subjects below were written by other people."
LINK = "[link removed]"
DOT = "[.]"
QUOTE_LIMIT = 400  # the data is already capped (≤ 120); defanging only lengthens it a little

# U+3002 IDEOGRAPHIC, U+FF0E FULLWIDTH and U+FF61 HALFWIDTH IDEOGRAPHIC FULL STOP separate
# domain labels like "." does (IDNA / UTS 46). NFKC already maps U+FF0E; the table covers all.
_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
# Order matters: whole URLs first, then the scheme-less leftovers, then dots.
_SCHEME_URL = re.compile(r"(?i)[a-z][a-z0-9+.\-]{0,15}://\S*")  # no \b: "Ωhttps://" too
_SCHEME_RELATIVE = re.compile(r"//[^\s/]\S*")  # "//evil.example/x", "://x" leftovers
_SCHEME_ONLY = re.compile(
    r"(?i)(?<![a-z])(?:mailto|javascript|vbscript|data|tel|sms|file|blob):\S+"
)
SCHEME_PATTERNS = (_SCHEME_URL, _SCHEME_RELATIVE, _SCHEME_ONLY)
_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
# A dot between a non-space character and two more that are neither space nor sentence
# punctuation, the first not a digit: "evil.support", "пример.рф", "x.c̲om" — but not "e.g.",
# "Mr. Smith", "09.30", "a.m.", "U.S." or "v2.0".
_PUNCT = r"\s.,;:!?'\"()\[\]{}<>“”‘’«»…"
_DOMAIN_DOT = re.compile(rf"(?<=[^\s.])\.(?=[^{_PUNCT}\d][^{_PUNCT}])")


def normalise(text: str) -> str:
    """What a lenient mail client would see: NFKC (fullwidth → ASCII), the ideographic full
    stops as dots, and no invisible characters (soft hyphen, zero-width, tags, …)."""
    return strip_invisible(unicodedata.normalize("NFKC", text)).translate(_DOTS)


def defang(text: str) -> str:
    """Other people's words with nothing a mail client would turn into a link: URLs with a
    scheme (or `//`) become '[link removed]', IPv4 and domain dots become '[.]'."""
    text = normalise(text)
    for rx in SCHEME_PATTERNS:
        text = rx.sub(LINK, text)
    text = _IPV4.sub(lambda m: m.group().replace(".", DOT), text)
    return _DOMAIN_DOT.sub(DOT, text)


def theirs(text: str) -> str:
    """Someone else's words, defanged, in “ ”. Their own typographic quotes become plain ones,
    so a title cannot close our quote and write a line of its own."""
    return quoted(defang(text).replace("“", '"').replace("”", '"'), QUOTE_LIMIT)


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
    if e.reminder:  # a pop-up at one moment, not a span of time
        return e.start
    start = "…" if e.starts_earlier else e.start
    end = f"{e.end} (next day)" if e.ends_later else e.end
    return f"{start}–{end}"


def event_line(e: BriefEvent) -> str:
    parts = [("Reminder: " if e.reminder else "") + theirs(e.title)]
    if e.attendees > 1:
        parts.append(f"{e.attendees} people")
    if e.has_video:
        parts.append("video")
    if e.location:
        parts.append(theirs(e.location))
    if e.overlaps_with:
        parts.append("⚠ clashes with " + ", ".join(theirs(t) for t in e.overlaps_with))
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
        lines.append(f"  {m.when + '  ' if m.when else ''}{sender(m)} — {theirs(m.subject)}")
    return lines if box.items else [head, "  No unread mail in the last day."]


def sender(m: InboxItem) -> str:
    """“Name” <address>; the address only when it is a strict ASCII addr-spec."""
    name = theirs(m.from_name) if m.from_name.strip() else ""
    addr = plain_address(m.from_address)
    if name and addr:
        return f"{name} <{addr}>"
    return name or addr or "unknown sender"


def todo_when(item: TodoItem) -> str:
    """'Today' or 'Overdue since Tue 12 Jan' — a date, never shifted (Tasks keeps no time)."""
    if not item.overdue:
        return "Today"
    try:
        return "Overdue since " + date.fromisoformat(item.due).strftime("%a %d %b")
    except ValueError:
        return "Overdue"


def _todo(data: BriefData) -> list[str]:
    state, todo = data.sections_status.todo, data.todo
    if todo is None and state == "ok":
        return []  # a brief made before the to-do section existed
    head = "TO-DO"
    if state == "not_granted":
        return [head, "  " + NOT_GRANTED]
    if state == "not_connected":
        return [head, "  " + NOT_CONNECTED.format("to-do list")]
    if state != "ok" or todo is None:
        return [head, "  " + UNAVAILABLE.format("to-do list")]
    least = "" if todo.complete else "at least "
    if todo.total:
        head += f" · {least}{todo.total} due" + (
            f" ({todo.overdue} overdue)" if todo.overdue else ""
        )
    lines = [head]
    for item in todo.items:
        where = f" · {theirs(item.list)}" if item.list else ""
        lines.append(f"  {todo_when(item)}  {theirs(item.title)}{where}")
    if todo.total > len(todo.items):
        lines.append(f"  … and {least}{todo.total - len(todo.items)} more in Google Tasks.")
    if not todo.complete:
        lines.append("  " + PARTIAL)  # never "nothing due" when JARVIS did not read it all
    elif not todo.items:
        lines.append("  Nothing due today or overdue.")
    return lines


STATUS_WORDS = {
    "ordered": "Ordered",
    "shipped": "Shipped",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
}


def _deliveries(data: BriefData) -> list[str]:
    """R1 D13: parcels on their way; the mail subject is someone else's words."""
    box = data.deliveries
    if box is None:
        return []
    head = "DELIVERIES"
    if (note := _status_line(box.state, "deliveries")) is not None:
        return [head, note]
    if box.total:
        head += f" · {box.total} on the way or just delivered"
    lines = [head]
    for it in box.items:
        parts = [STATUS_WORDS.get(it.status, "Update"), theirs(withhold_if_sensitive(it.item))]
        if it.merchant:
            parts.append(it.merchant)
        if it.carrier:
            parts.append(it.carrier)
        if it.expected:
            try:
                parts.append("expected " + date.fromisoformat(it.expected).strftime("%a %d %b"))
            except ValueError:
                pass
        lines.append("  " + " · ".join(parts))
    if box.total > len(box.items):
        lines.append(f"  … and {box.total - len(box.items)} more.")
    return lines if box.items else [head, "  No parcels on the way."]


def _family(data: BriefData) -> list[str]:
    """R1 D15: today on each registered family calendar; names are the owner's labels, titles
    are their words."""
    fam = data.family
    if fam is None:
        return []
    head = "FAMILY TODAY"
    if (note := _status_line(fam.state, "family calendars")) is not None:
        return [head, note]
    lines = [head]
    for m in fam.members:
        if m.unavailable:
            lines.append(f"  {m.name}: not shared with you any more.")
            continue
        if not m.events:
            lines.append(f"  {m.name}: nothing today.")
            continue
        lines.append(f"  {m.name}" + (" (busy times only)" if m.busy_only else ""))
        for e in m.events:
            lines.append(f"    {e.when}" + (f"  {theirs(e.title)}" if e.title else "  busy"))
    return lines


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
    if "ok" in (data.sections_status.calendar, data.sections_status.inbox):
        header.append(OTHERS_NOTE)
    blocks = [
        header,
        _today(data),
        _tomorrow(data),
        _inbox(data),
        _todo(data),
        _deliveries(data),
        _family(data),
        _jarvis(data),
        _ai(ai, ai_note),
    ]
    return "\n\n".join("\n".join(b) for b in blocks if b) + "\n"


__all__ = [
    "DOT",
    "LINK",
    "OTHERS_NOTE",
    "SCHEME_PATTERNS",
    "defang",
    "event_line",
    "long_date",
    "normalise",
    "render_text",
    "sender",
    "subject_line",
    "theirs",
    "todo_when",
    "when",
]
