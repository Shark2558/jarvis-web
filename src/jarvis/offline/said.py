# src/jarvis/offline/said.py
"""What No-AI mode says for the real tools' results (R14 I1, INTEGRATION-D "Needs I1" 7).

The tools answer the model with data: lists, counts and flags, other people's words fenced as
EXTERNAL CONTENT, and notes written to the model ("Tell the owner…", "Do not say…"). With the AI
off nobody turns that into words, so `offline/no_ai.py` showed most of D12's answers as compact
JSON, fence markers and all. Each sayer here writes one fixed-template reply from its tool's own
result fields; a fence is shown as its inner words on one line (`plain`), never its markers. A
result a sayer doesn't recognise (a refusal, a permission note, a shape it doesn't know) is None,
and the generic renderer runs as before. The tools' results, and so what the model sees, are
unchanged; a sayer that raises is logged by class name and the generic renderer runs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from jarvis.tools.card import one_line

log = logging.getLogger(__name__)

Sayer = Callable[[Mapping[str, Any]], str | None]

ITEM_LIMIT = 80  # characters of one name, title or line shown
LISTED = 10  # items named in one reply; the rest are counted
_FENCED = re.compile(r"<<EXTERNAL CONTENT from [^\n]*?>>\n(.*?)\n<<END [0-9a-f]{6}>>", re.S)
_LEFT_OVER = re.compile(r"<<(?:EXTERNAL CONTENT|END)[^>]*>>")
PARCEL_WORDS = {
    "ordered": "ordered",
    "shipped": "shipped",
    "out_for_delivery": "out for delivery",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "returned": "returned",
    "refunded": "refunded",
}
HIDDEN_ON_TELEGRAM = (
    "Deleted vault documents, notes and things aren't listed on Telegram (your choice in "
    "Integrations, Telegram); they are in Recently deleted in the console."
)
ARMING = (
    "Arming, Sir: waiting for your laptop. If it is off or asleep it arms when it is back, and "
    "JARVIS tells you if it hasn't answered in 5 minutes."
)
NO_ZONES = (
    "The alarm is switched on, Sir, but nothing is protected yet: no camera has an alarm zone. "
    "Pick the gate zone in the Home panel."
)


def plain(value: Any, limit: int = ITEM_LIMIT) -> str:
    """A fenced value's inner words on one line (a value with no fence as it is), never a
    marker."""
    text = "" if value is None else str(value)
    inner = " ".join(m.group(1) for m in _FENCED.finditer(text)) or text
    return one_line(_LEFT_OVER.sub("", inner), limit)


def _end(text: str) -> str:
    """`text` as a sentence: a full stop unless it already ends with one, a "?" or a "!"."""
    return text if text.endswith((".", "?", "!")) else text + "."


def _named(names: Sequence[str]) -> str:
    shown = [n for n in names[:LISTED] if n]
    more = len(names) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def _list(result: Mapping[str, Any], key: str) -> list[Mapping[str, Any]] | None:
    value = result.get(key)
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, Mapping)]


def _note(result: Mapping[str, Any]) -> str:
    note = result.get("note")
    return f" {note}" if isinstance(note, str) and note.strip() else ""


# ---- groceries ----------------------------------------------------------------------------------


def _quantity(item: Mapping[str, Any]) -> str:
    name, qty, unit = plain(item.get("name")), item.get("qty"), item.get("unit")
    if isinstance(qty, int | float) and not isinstance(qty, bool):
        amount = f"{qty:g} {unit}" if unit else f"{qty:g}"
        return f"{name} ({amount})"
    return name


def grocery_list(result: Mapping[str, Any]) -> str | None:
    items = _list(result, "items")
    if items is None:
        return None
    if not items:
        note = result.get("note")
        return note if isinstance(note, str) and note else "Your Groceries list is empty, Sir."
    return f"Your Groceries list ({len(items)}), Sir: {_named([_quantity(i) for i in items])}."


_GROCERY_DONE = {
    "added": "added {t}",
    "merged": "{t} now",
    "replaced": "{t} (was {was})",
    "already_on_list": "{t} is already on it",
    "ticked_off": "ticked off {t}",
    "not_found": "{t} isn't on it",
}


def grocery_change(result: Mapping[str, Any]) -> str | None:
    rows = _list(result, "results")
    if result.get("status") != "done" or not rows:
        return None
    done = []
    for row in rows:
        words = _GROCERY_DONE.get(str(row.get("action")))
        if words is None:
            return None
        title = plain(row.get("title") or row.get("name"))
        done.append(words.format(t=title, was=plain(row.get("was"))))
    return f"Your Groceries list, Sir: {'; '.join(done)}.{_note(result)}"


# ---- the vault, things, Recently deleted, memory ------------------------------------------------


def _days(left: Any) -> str:
    if not isinstance(left, int) or isinstance(left, bool):
        return "no date"
    if left < 0:
        return f"expired {-left} day{'s' if left != -1 else ''} ago"
    return "expires today" if left == 0 else f"{left} day{'s' if left != 1 else ''} left"


def _document(row: Mapping[str, Any]) -> str:
    whose = "your" if row.get("whose") == "you" else f"{plain(row.get('whose'))}'s"
    title, kind = plain(row.get("title")), plain(row.get("type"))
    name = title if title.lower() == kind.lower() or not kind else f"{title} ({kind})"
    return f"{whose} {name}, on {row.get('expires_on') or 'no date'}, {_days(row.get('days_left'))}"


def vault_expiring(result: Mapping[str, Any]) -> str | None:
    rows, within = _list(result, "documents"), result.get("within_days")
    if rows is None or not isinstance(within, int):
        return None
    if not rows:
        return f"Nothing in your vault expires in the next {within} days, Sir."
    verb = "document expires" if len(rows) == 1 else "documents expire"
    head = f"{len(rows)} {verb} within {within} days"
    return f"{head}, Sir: {'; '.join(_document(r) for r in rows[:LISTED])}."


def _thing(row: Mapping[str, Any]) -> str:
    whose = row.get("whose")
    owner = f"{plain(whose)}'s" if whose else "Your"
    out = f"{owner} {plain(row.get('name'))}: {plain(row.get('place'))}"
    out += f" (noted on {row.get('noted_on')})" if row.get("noted_on") else ""
    return out + (f"; {row['noted_how']}" if isinstance(row.get("noted_how"), str) else "")


def belongings_where(result: Mapping[str, Any]) -> str | None:
    if result.get("found") is False:
        note = result.get("note")
        return note if isinstance(note, str) and note else None
    best = result.get("best")
    if result.get("found") is not True or not isinstance(best, Mapping):
        return None
    others = _list(result, "others") or []
    also = "".join(f" Also noted: {_thing(o)}." for o in others)
    return f"{_thing(best)}.{also}"


def belongings_put(result: Mapping[str, Any]) -> str | None:
    if result.get("status") != "done":
        return None
    said = f"Noted, Sir. Your {plain(result.get('item'))}: {plain(result.get('place'))}"
    if result.get("moved") and result.get("previous_place"):
        said += f" (before: {plain(result['previous_place'])})"
    return said + "."


def _deleted(row: Mapping[str, Any]) -> str:
    when = str(row.get("deleted_at") or "")[:10]
    out = f"{row.get('kind') or 'item'} “{plain(row.get('title'))}”, {when}"
    return out + (" (restored)" if row.get("restored") is True else "")


def deleted_list(result: Mapping[str, Any]) -> str | None:
    rows, days = _list(result, "items"), result.get("kept_days")
    if rows is None or not isinstance(days, int):
        return None
    hidden = f" {HIDDEN_ON_TELEGRAM}" if result.get("note") else ""
    if not rows:
        return f"Nothing was deleted in the last {days} days, Sir.{hidden}"
    listed = "; ".join(_deleted(r) for r in rows[:LISTED])
    return f"Recently deleted, kept {days} days, Sir: {listed}.{hidden}"


def memory_search(result: Mapping[str, Any]) -> str | None:
    notes = _list(result, "notes")
    if notes is None:
        return None
    if not notes:
        return "I have nothing saved about that, Sir."
    texts = [plain(n.get("text"), 200).rstrip(".") for n in notes[:LISTED]]
    return f"From your memory, Sir: {'; '.join(t for t in texts if t)}."


# ---- mail ---------------------------------------------------------------------------------------


def _parcel(p: Mapping[str, Any]) -> str:
    status = PARCEL_WORDS.get(str(p.get("status")), "on its way")
    out = f"{plain(p.get('merchant')) or 'an order'}, {status}"
    out += f" by {plain(p.get('carrier'))}" if p.get("carrier") else ""
    return out + (f", expected {p['expected']}" if p.get("expected") else "")


def parcels(result: Mapping[str, Any]) -> str | None:
    rows = _list(result, "packages")
    if rows is None:
        return None
    if not rows:
        return _note(result).strip() or "No parcels found in your mail, Sir."
    more = " There are more in your mail." if result.get("more") is True else ""
    count = f"{len(rows)} parcel{'s' if len(rows) != 1 else ''}"
    return f"{count}, Sir: {'; '.join(_parcel(r) for r in rows[:LISTED])}.{more}"


def _letters(group: Mapping[str, Any]) -> str:
    items = _list(group, "items") or []
    said = [f"{plain(x.get('from'))}: {plain(x.get('subject'))}" for x in items[:LISTED]]
    return f" {_end(plain(group.get('label')) + ': ' + '; '.join(said))}" if said else ""


def inbox_summary(result: Mapping[str, Any]) -> str | None:
    groups = result.get("groups")
    if not isinstance(groups, Mapping):
        return None
    shown = [g for g in groups.values() if isinstance(g, Mapping)]
    counts = [f"{plain(g.get('label'))} {g['unread']}" for g in shown if g.get("unread")]
    unread = result.get("unread")
    head = f"{unread} unread in your inbox, Sir" if isinstance(unread, int) else "Your inbox, Sir"
    out = head + (f": {', '.join(counts)}." if counts else ".")
    out += "".join(_letters(g) for g in shown)
    held = result.get("withheld_note")
    out += f" {held}." if isinstance(held, str) and held else ""
    return out + _note(result)


# ---- home ---------------------------------------------------------------------------------------


def home_arm(result: Mapping[str, Any]) -> str | None:
    return {"pending": ARMING, "no_zones": NO_ZONES}.get(str(result.get("status")))


def home_status(result: Mapping[str, Any]) -> str | None:
    if result.get("linked") is not True:
        return None
    alarm = result.get("alarm")
    tail = f" The alarm: {alarm}." if isinstance(alarm, str) else ""
    if result.get("laptop") != "online":
        message = result.get("message")
        return f"{message}{tail}" if isinstance(message, str) else None
    cams = _list(result, "cameras") or []
    online = sum(1 for c in cams if c.get("online") is True)
    seen = f" (seen {result['last_seen']})" if result.get("last_seen") else ""
    plural = "s" if len(cams) != 1 else ""
    cameras = f" {online} of {len(cams)} camera{plural} online." if cams else ""
    return f"Your home laptop is online, Sir{seen}.{cameras}{tail}"


SAYERS: dict[str, Sayer] = {
    "grocery_list": grocery_list,
    "grocery_add": grocery_change,
    "grocery_remove": grocery_change,
    "vault_expiring": vault_expiring,
    "belongings_where": belongings_where,
    "belongings_put": belongings_put,
    "deleted_list": deleted_list,
    "memory_search": memory_search,
    "gmail_track_packages": parcels,
    "gmail_inbox_summary": inbox_summary,
    "home_arm": home_arm,
    "home_status": home_status,
}


def say(tool: str, result: Any) -> str | None:
    """`tool`'s reply for `result` in words, or None (no sayer, or a shape it doesn't know)."""
    sayer = SAYERS.get(tool)
    if sayer is None or not isinstance(result, Mapping):
        return None
    try:
        said = sayer(result)
    except Exception as exc:  # noqa: BLE001 - never break a No-AI reply: the generic line runs
        log.warning("no-ai sayer failed", extra={"tool": tool, "error": type(exc).__name__})
        return None
    return said if said and said.strip() else None


__all__ = ["SAYERS", "Sayer", "plain", "say"]
