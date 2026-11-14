# src/jarvis/offline/phrases_r14.py
"""No-AI pass 2 (docs/plans/r14-hardening.md D12): anchored, conservative phrase routers, tried
with the other extra routers before pass 1 (so before its generative check). The WHOLE message
must be the phrase (an optional "hey / ok", "Jarvis," and "please", end punctuation), so a
request inside a longer sentence ("remind me to add milk to my grocery list", "draft a mail to the
plumber") is never taken here. Each ends in ONE tool call through the gateway (its policy, rows,
Telegram classes, cards and audit all apply) or a fixed line. No model, ever.

    add milk and 2 kg rice to my grocery list         grocery_add(items)
    what's on my shopping list                         grocery_list
    remove milk from my grocery list                   grocery_remove(items)
    what's expiring in my vault                        vault_expiring
    where did I put my passport                        belongings_where(item)
    I kept the keys in the drawer                      belongings_put(item, place)
    is the house armed / home status                   home_status
    arm the alarm (for the night)                      home_arm(mode)
    disarm the alarm                                   a fixed line: never a tool (Home panel only)
    where's my parcel                                  gmail_track_packages
    check my email / any new mail                      gmail_inbox_summary (plain code)
    what did I delete                                  deleted_list
    what do you remember about Lekha                   memory_search(query)
    what time is it / what's the date                  a fixed line from the clock
    when was my last backup / test my backup           vitals_backups / vitals_drill_start (card)
    book a plumber for tomorrow morning                maint_service_request (never a booking)
    what can you do (without the AI)                   a fixed list: the 11 skills, what works

`ROUTERS` are separate functions, so the wiring puts them into No-AI mode one at a time (one that
does not fit never drops the others); parcels come before "where is my ..." things.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from jarvis.groceries.items import NAME_MAX, UNIT_ALIASES
from jarvis.offline.rules import NoAICall, NoAIRoute
from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS

Router = Callable[[str, datetime], NoAIRoute | None]
MAX_TEXT = 400
MAX_ITEMS = 20
DISARM_LINE = "Disarming is only in the Home panel, Sir."
TOO_MANY = f"That's more than {MAX_ITEMS} items, Sir: say them in two goes."
TOO_LONG = f"An item's name is at most {NAME_MAX} characters, Sir."
WITHOUT_AI: tuple[str, ...] = (
    "notes, timers and reminders",
    "your to-dos, calendar and reminders list",
    "groceries: add, remove and show",
    "what's expiring in your vault",
    "where you put things",
    "home status and arming the alarm",
    "your parcels and your inbox at a glance",
    "Recently deleted",
    "what I remember about someone",
    "the time and the date",
    "your backups, and a restore drill on a card",
    "a home-service request (never a booking)",
    "the systems check and Vitals",
    "your helpers: bills, chores, upkeep, the kitchen, nudges, sleep and steps",
)
ABILITIES_LINE = (
    "With the AI off I can still do these, Sir: " + "; ".join(WITHOUT_AI) + ".\n"
    "My skills: " + ", ".join(SKILL_LABELS[s] for s in SKILL_IDS) + ".\n"
    "Anything that needs writing or thinking (a draft, a summary, an explanation) needs the AI "
    "switched on."
)

_I = re.IGNORECASE
_LEAD = r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"(?:\s+please)?[\s.!?]*$"
_MY = r"(?:my|the)\s+"
_THING = r"(?P<item>[A-Za-z][\w' -]{0,39}?)"


def _p(body: str) -> re.Pattern[str]:
    return re.compile(_LEAD + r"(?:" + body + r")" + _END, _I)


def _one(tool: str, **args: Any) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def _line(text: str) -> str:
    return " ".join(str(text)[:MAX_TEXT].split())


def _simple(pattern: re.Pattern[str], tool: str) -> Router:
    def route(text: str, now: datetime) -> NoAIRoute | None:
        return _one(tool) if pattern.match(_line(text)) else None

    route.__name__ = route.__qualname__ = f"r14_{tool}"
    return route


# ---- groceries ----------------------------------------------------------------------------------
_LIST = r"(?:grocery|groceries|shopping)(?:\s+list)?"
G_ADD = _p(rf"(?:add|put)\s+(?P<items>.+?)\s+(?:to|on|in|onto|into)\s+{_MY}{_LIST}")
G_REMOVE = _p(
    rf"(?:remove|delete|take|tick\s+off|cross\s+off)\s+(?P<items>.+?)\s+"
    rf"(?:from|off|out\s+of)\s+{_MY}{_LIST}"
)
G_SHOW = _p(
    rf"(?:what(?:'s|\s+is)\s+on|(?:show|read|check|open)(?:\s+me)?)\s+{_MY}{_LIST}|my\s+{_LIST}"
)
_SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*", _I)
_ARTICLE = re.compile(r"^(?:some|a|an|the)\s+", _I)
_QTY = re.compile(r"^(?P<qty>\d{1,4}(?:\.\d{1,2})?)\s*(?P<unit>[A-Za-z]+\b)?\s*(?P<name>.*)$")


def _names(raw: str) -> list[str]:
    return [n for n in (_ARTICLE.sub("", p.strip(" .")) for p in _SPLIT.split(raw)) if n]


def _item(name: str) -> dict[str, Any]:
    m = _QTY.match(name)
    if m is None or not m["name"] and not m["unit"]:
        return {"name": name}
    unit = (m["unit"] or "").casefold()
    if unit in UNIT_ALIASES and m["name"]:
        return {"name": m["name"], "qty": m["qty"], "unit": unit}
    rest = " ".join(x for x in (m["unit"], m["name"]) if x)
    return {"name": rest, "qty": m["qty"]} if rest else {"name": name}


def groceries(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if G_SHOW.match(one):
        return _one("grocery_list")
    add, remove = G_ADD.match(one), G_REMOVE.match(one)
    found = add or remove
    if found is None:
        return None
    names = _names(found["items"])
    if not names:
        return None
    if len(names) > MAX_ITEMS:
        return NoAIRoute(reply=TOO_MANY)
    if any(len(n) > NAME_MAX for n in names):
        return NoAIRoute(reply=TOO_LONG)
    if add is not None:
        return _one("grocery_add", items=[_item(n) for n in names])
    return _one("grocery_remove", items=[_item(n)["name"] for n in names])


# ---- the vault, parcels, the inbox, Recently deleted, backups ----------------------------------
VAULT = _p(
    r"what(?:'s|\s+is|\s+are)?\s+(?:expiring|about\s+to\s+expire|due\s+to\s+expire)"
    rf"(?:\s+soon)?(?:\s+in\s+{_MY}vault)?"
    r"|(?:which|what)\s+(?:documents?|papers?)\s+(?:expire|are\s+expiring)(?:\s+soon)?"
    rf"|(?:is\s+)?any(?:thing)?\s+(?:documents?\s+)?expiring(?:\s+soon)?(?:\s+in\s+{_MY}vault)?"
    r"|(?:show\s+(?:me\s+)?)?(?:my\s+)?vault\s+expir(?:y|ies|ing)(?:\s+dates?)?"
)
PARCELS = _p(
    r"where(?:'s|\s+is|\s+are)\s+(?:my|the)\s+(?:parcels?|packages?|orders?|deliver(?:y|ies)|courier)"
    r"|(?:track|check)\s+(?:my\s+)?(?:parcels?|packages?|orders?|deliveries)"
    r"|any\s+(?:parcels?|packages?|deliveries)(?:\s+(?:today|coming))?"
    r"|my\s+(?:parcels?|packages?|deliveries)"
)
INBOX = _p(
    r"(?:check|read|show(?:\s+me)?|open)\s+(?:my\s+)?(?:e-?mails?|mails?|inbox|gmail)"
    r"|any\s+(?:new\s+|unread\s+)?(?:e-?mails?|mails?)"
    r"|(?:do\s+i\s+have|have\s+i\s+got)\s+(?:any\s+)?(?:new\s+|unread\s+)?(?:e-?mails?|mail)"
    r"|what(?:'s|\s+is)\s+in\s+my\s+inbox|my\s+inbox"
)
DELETED = _p(
    r"what\s+(?:did|have)\s+(?:i|you)\s+(?:deleted?|removed?)"
    r"(?:\s+(?:recently|lately|today|this\s+week))?"
    r"|(?:show\s+(?:me\s+)?|open\s+)?(?:my\s+|the\s+)?recently\s+deleted(?:\s+(?:items|things))?"
    r"|(?:show|list)\s+(?:me\s+)?(?:my\s+)?deleted\s+(?:items|things)"
)
BACKUPS = _p(
    r"when\s+was\s+(?:my|the)\s+last\s+backup|(?:what(?:'s|\s+is)\s+)?(?:my\s+|the\s+)?backups?"
    r"\s+status|(?:are|is)\s+(?:my|the)\s+backups?\s+(?:ok(?:ay)?|working|on|fine)"
    r"|(?:show|check)\s+(?:me\s+)?(?:my\s+|the\s+)?backups?|(?:my\s+)?backups|last\s+backup"
)
DRILL = _p(
    r"test\s+(?:my|the)\s+backups?|(?:run|start|do)\s+(?:a\s+)?(?:restore|backup)\s+(?:drill|test)"
    r"|restore\s+drill"
)


# ---- things: where they are, where they went --------------------------------------------------
_NOT_THINGS = frozenset(
    "parcel parcels package packages order orders delivery deliveries courier meeting meetings "
    "appointment appointments event events".split()
)
WHERE = _p(
    r"where(?:'s|\s+is|\s+are|\s+did\s+i\s+(?:put|keep|leave|store)|\s+do\s+i\s+keep"
    r"|\s+have\s+i\s+(?:put|kept))\s+" + _MY + _THING
)
PUT = _p(
    r"i(?:'ve|\s+have)?\s+(?:kept|put|placed|left|stored|moved|hid|hidden)\s+" + _MY + _THING
    + r"\s+(?P<prep>in|inside|on\s+top\s+of|on|under|behind|at|with|near|beside|next\s+to)\s+"
    r"(?P<place>\S.{0,79}?)"
)  # fmt: skip


def things(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if (m := WHERE.match(one)) is not None:
        item = " ".join(m["item"].split())
        if _NOT_THINGS.intersection(item.casefold().split()):
            return None  # a parcel or a meeting is someone else's question
        return _one("belongings_where", item=item)
    if (m := PUT.match(one)) is None:
        return None
    prep = " ".join(m["prep"].casefold().split())
    place = m["place"].strip(" .")
    return _one(
        "belongings_put",
        item=" ".join(m["item"].split()),
        place=place if prep == "in" else f"{prep} {place}",
    )


# ---- home: status, arm; never disarm ---------------------------------------------------------
_HOUSE = r"(?:house|home|alarm)"
HOME_STATUS = _p(
    rf"(?:is|are)\s+{_MY}{_HOUSE}\s+(?:armed|on|safe|ok(?:ay)?)|is\s+the\s+alarm\s+set"
    rf"|(?:what(?:'s|\s+is)\s+)?(?:my\s+|the\s+)?(?:home|house)\s+status"
    rf"|how(?:'s|\s+is)\s+{_MY}(?:house|home)"
)
DISARM = _p(
    rf"disarm(?:\s+{_MY}{_HOUSE})?"
    r"|(?:turn|switch)\s+off\s+the\s+(?:burglar\s+|house\s+|home\s+)?alarm"
)
ARM = _p(
    rf"(?:arm\s+{_MY}{_HOUSE}|(?:turn|switch)\s+on\s+the\s+(?:burglar\s+|house\s+|home\s+)?alarm)"
    r"(?P<night>\s+for\s+(?:the\s+night|tonight))?"
)


def home(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if DISARM.match(one):
        return NoAIRoute(reply=DISARM_LINE)  # D12: disarm never routes, not even to home_disarm
    if HOME_STATUS.match(one):
        return _one("home_status")
    if (m := ARM.match(one)) is not None:
        return _one("home_arm", mode="night" if m["night"] else "away")
    return None


# ---- memory, the clock, what JARVIS can do ------------------------------------------------------
MEMORY = _p(
    r"what\s+do\s+you\s+(?:remember|recall)\s+about\s+(?P<q>\S.{0,79}?)"
    r"|(?:search|check)\s+(?:your|my)\s+memory\s+(?:for|about)\s+(?P<q2>\S.{0,79}?)"
)
TIME = _p(
    r"what(?:'s|\s+is)\s+the\s+time(?:\s+now)?|what\s+time\s+is\s+it(?:\s+now)?"
    r"|tell\s+me\s+the\s+time|(?:the\s+|current\s+)?time(?:\s+now)?"
)
DATE = _p(
    r"what(?:'s|\s+is)\s+(?:the\s+date|today'?s\s+date)(?:\s+today)?"
    r"|what\s+(?:day|date)\s+is\s+(?:it|today)(?:\s+today)?|(?:today'?s\s+)?date(?:\s+today)?"
)
ABILITIES = _p(
    r"what\s+(?:can|could)\s+you\s+do(?:\s+(?:without|with\s+no)\s+(?:the\s+)?ai|\s+offline"
    r"|\s+now|\s+for\s+me)?|what\s+works\s+(?:without|with\s+no)\s+(?:the\s+)?ai"
    r"|what\s+are\s+your\s+(?:skills|abilities)|help"
)


def memory(text: str, now: datetime) -> NoAIRoute | None:
    m = MEMORY.match(_line(text))
    if m is None:
        return None
    query = (m["q"] or m["q2"] or "").strip(" .?!")
    return _one("memory_search", query=query) if query else None


def clock(text: str, now: datetime) -> NoAIRoute | None:
    one = _line(text)
    if TIME.match(one):
        zone = now.strftime("%Z")
        return NoAIRoute(reply=f"It's {now:%H:%M}{f' ({zone})' if zone else ''}, Sir.")
    if DATE.match(one):
        return NoAIRoute(reply=f"Today is {now:%A}, {now.day} {now:%B %Y}, Sir.")
    return None


def abilities(text: str, now: datetime) -> NoAIRoute | None:
    return NoAIRoute(reply=ABILITIES_LINE) if ABILITIES.match(_line(text)) else None


# ---- row 102: a home-service request (never a booking) ----------------------------------------
_JOBS: tuple[tuple[str, str], ...] = (
    (r"plumber", "plumber"),
    (r"electrician", "electrician"),
    (r"carpenter", "carpenter"),
    (r"ac\s+(?:repair|service|technician|mechanic)(?:\s+person)?|ac\s+repairman", "ac"),
    (r"(?:house\s+)?cleaner|cleaning(?:\s+service)?|deep\s+cleaning", "cleaning"),
    (r"appliance\s+repair(?:\s+person|man)?|repairman", "appliance"),
    (r"pest\s+control(?:\s+service)?|exterminator", "pest"),
    (r"handyman", "other"),
)
_WHEN = (
    r"(?:(?:for|on|at|by|this|next)\s+)?(?:today|tonight|tomorrow|this|next|mon|tue|wed|thu|fri"
    r"|sat|sun|\d{1,2}(?::\d{2})?\s*(?:am|pm))[\w\s:]{0,30}?"
)
SERVICE = _p(
    r"(?:book|get|call|find|arrange|hire|i\s+need)(?:\s+me)?\s+(?:a|an)\s+"
    r"(?P<job>" + "|".join(p for p, _ in _JOBS) + r")"
    r"(?:\s+(?:to|for)\s+(?P<problem>(?!(?:today|tonight|tomorrow|this|next|on|at)\b)\S.{0,199}?))?"
    r"(?:\s+(?P<when>" + _WHEN + r"))?"
)
_LEADING = re.compile(r"^(?:for|on|at|by)\s+", _I)


def _job(words: str) -> str:
    one = " ".join(words.casefold().split())
    return next(job for pattern, job in _JOBS if re.fullmatch(pattern, one))


def service(text: str, now: datetime) -> NoAIRoute | None:
    m = SERVICE.match(_line(text))
    if m is None:
        return None
    args: dict[str, Any] = {"job": _job(m["job"])}
    if m["problem"]:
        args["problem"] = m["problem"].strip(" .")
    if m["when"]:
        args["when"] = _LEADING.sub("", m["when"].strip(" ."))
    return NoAIRoute((NoAICall("maint_service_request", args),))


ROUTERS: tuple[Router, ...] = (
    _simple(PARCELS, "gmail_track_packages"),
    groceries,
    _simple(VAULT, "vault_expiring"),
    things,
    home,
    _simple(INBOX, "gmail_inbox_summary"),
    _simple(DELETED, "deleted_list"),
    memory,
    clock,
    _simple(DRILL, "vitals_drill_start"),
    _simple(BACKUPS, "vitals_backups"),
    service,
    abilities,
)

__all__ = [
    "ABILITIES_LINE",
    "DISARM_LINE",
    "ROUTERS",
    "WITHOUT_AI",
    "abilities",
    "clock",
    "groceries",
    "home",
    "memory",
    "service",
    "things",
]
