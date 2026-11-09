# src/jarvis/health/briefing.py
"""The spoken systems briefing (R5.1 D5). FIXED templates only, never model text, so it works in
No-AI mode and with the brain down.

Order: "Systems check complete, Sir. I checked N systems: A, B and C." -> "All of them are
working." or "A and B are working." then one sentence per faulty system with what that breaks
("Telegram is not answering -- alerts and Telegram chat won't reach you.") -> vitals: this
month's AI spend against the limit in rupees and percent, each free allowance at or over 80 %,
each amber/red vitals item with its consequence -> "Shall I set a reminder to fix this?" when
anything needs attention, else "All systems nominal, Sir."

Words come from code: the system's label is `models.LABELS` (the stored one only for a key no
label is known for), the consequence and the fix from the fixed maps below (or the fixed text
Vitals puts on its items: `impact` / `fix`, R5.1 Part B). A probe's `reason` is never spoken (it
is only compared with JARVIS's own fixed reasons, `BY_REASON`, e.g. the brain out of credit); a
vitals item's `reason` is Vitals' own fixed template ("expires in 3 days"). Rupees only. The
spoken text is capped at about 60 s of speech (`MAX_SPOKEN`): the lowest-severity vitals lines
are dropped first and "And N more on screen." is said instead; `lines` keeps every sentence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jarvis.billing.service import rupees
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.probes import BRAIN_NO_CREDIT
from jarvis.health.report import spoken_label
from jarvis.vitals.models import Board, ProviderView

Severity = Literal["down", "degraded", "amber", "red"]

MAX_SPOKEN = 900
ALLOWANCE_WARN_PERCENT = 80.0
TEXT_MAX = 160  # one impact / fix line
OPENING = "Systems check complete, Sir."
NO_SYSTEMS = "There are no systems to check."
ALL_WORKING = "All of them are working."
ONE_WORKING = "It is working."
VITALS_UNREADABLE = "Vitals can't be read just now."
REMIND_CLOSE = "Shall I set a reminder to fix this?"
NOMINAL_CLOSE = "All systems nominal, Sir."
DASH = "—"
SPEND_ID = "ai_spend"
VITALS_PREFIX = "vitals."

IMPACT: Mapping[str, str] = {
    "brain": "JARVIS can't think; offline mode or No-AI answers only",
    "docs": "JARVIS can't save or read your data",
    "google": "calendar, email, reminders and Drive stop working",
    "telegram": "alerts and Telegram chat won't reach you",
    "home": "the camera alarm and home devices are off",
    "redis": "sessions may be lost on restart",
    "web": "web search stops",
}
FIX: Mapping[str, str] = {
    "brain": "Check the AI key and this month's limit in Vitals.",
    "docs": "Check the server's database connection.",
    "google": "Reconnect Google in Integrations.",
    "telegram": "Check the Telegram bot and its pairing in Integrations.",
    "home": "Switch the home laptop on and check its network.",
    "redis": "Restart Redis or check its address.",
    "web": "Check the web search credits in Vitals.",
}
# (probe key, one of JARVIS's own fixed probe reasons) -> (state words, impact, fix): a fault whose
# cause is known in code says so instead of "is not answering" (R5.1 I1: the AI out of credit).
BY_REASON: Mapping[tuple[str, str], tuple[str, str, str]] = {
    ("brain", BRAIN_NO_CREDIT): (
        "is out of credit",
        "paid AI replies pause until the account is topped up",
        "Top up at console.anthropic.com → Plans & billing.",
    ),
}
UNKNOWN_IMPACT = "it may not work until it's fixed"
UNKNOWN_FIX = "Run the check again in a few minutes."
SPEND_IMPACT = "paid AI replies stop at the limit"
SPEND_FIX = "Raise the monthly limit in Vitals, or wait for next month."
VITALS_IMPACT: Mapping[str, str] = {  # by vitals kind, when Vitals gives none
    "allowance": "its free allowance runs out",
    "quota": "that feature stops until it resets",
    "key": "the service using it stops working",
    "billing": "paid services stop",
    "storage": "saving stops when it's full",
}
VITALS_FIX: Mapping[str, str] = {
    "allowance": "Keep an eye on it in Vitals; it resets each month.",
    "quota": "Wait for the reset, or use that feature less.",
    "key": "Renew it before it runs out.",
    "billing": "Top up or raise the limit.",
    "storage": "Free up some space.",
}
_RANK: Mapping[str, int] = {"down": 0, "degraded": 1, "red": 2, "amber": 3}


@dataclass(frozen=True)
class Concern:
    key: str  # a probe key ("telegram") or "vitals.<id>"
    label: str
    severity: Severity
    impact: str
    fix: str

    def to_json(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "severity": self.severity,
            "impact": self.impact,
            "fix": self.fix,
        }


@dataclass(frozen=True)
class Briefing:
    spoken: str
    lines: tuple[str, ...]  # every sentence, uncapped (the screen shows everything)
    concerns: tuple[Concern, ...]
    spend: str = ""  # the vitals sentence on its own (the pop-up's Vitals summary); "" without

    def to_json(self) -> dict[str, Any]:
        return {
            "spoken": self.spoken,
            "lines": list(self.lines),
            "concerns": [c.to_json() for c in self.concerns],
            "spend": self.spend,
        }


EMPTY = Briefing(spoken="", lines=(), concerns=())


@dataclass(frozen=True)
class _Part:
    text: str
    rank: int  # 0: always said; higher: dropped first when too long


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _plain(value: object, fallback: str) -> str:
    """A fixed line from Vitals (Part B's attributes), tidied; the fallback when absent."""
    if not isinstance(value, str):
        return fallback
    one = " ".join("".join(c if c >= " " else " " for c in value).split())[:TEXT_MAX]
    return one.rstrip(".") or fallback


# ---- systems ---------------------------------------------------------------------------------
def _system_parts(results: tuple[ProbeResult, ...]) -> tuple[list[_Part], list[Concern]]:
    if not results:
        return [_Part(f"{OPENING} {NO_SYSTEMS}", 0)], []
    names = [spoken_label(r) for r in results]
    noun = "system" if len(names) == 1 else "systems"
    parts = [_Part(f"{OPENING} I checked {len(names)} {noun}: {_join(names)}.", 0)]
    working = [spoken_label(r) for r in results if r.status == "ok"]
    if len(working) == len(results):
        parts.append(_Part(ONE_WORKING if len(working) == 1 else ALL_WORKING, 0))
    elif working:
        verb = "is" if len(working) == 1 else "are"
        parts.append(_Part(f"{_cap(_join(working))} {verb} working.", 0))
    concerns: list[Concern] = []
    for r in results:
        if r.status == "ok":
            continue
        label = spoken_label(r)
        impact = IMPACT.get(r.key, UNKNOWN_IMPACT)
        state = "is not answering" if r.status == "down" else "is degraded"
        fix = FIX.get(r.key, UNKNOWN_FIX)
        state, impact, fix = BY_REASON.get((r.key, r.reason), (state, impact, fix))
        rank = 1 if r.status == "down" else 2
        parts.append(_Part(f"{_cap(label)} {state} {DASH} {impact}.", rank))
        sev: Severity = "down" if r.status == "down" else "degraded"
        concerns.append(Concern(r.key, label, sev, impact, fix))
    return parts, concerns


# ---- vitals ----------------------------------------------------------------------------------
def _impact(v: ProviderView) -> str:
    fallback = SPEND_IMPACT if v.provider.id == SPEND_ID else VITALS_IMPACT.get(v.provider.kind)
    return _plain(getattr(v, "impact", None), fallback or UNKNOWN_IMPACT)


def _fix(v: ProviderView) -> str:
    fallback = SPEND_FIX if v.provider.id == SPEND_ID else VITALS_FIX.get(v.provider.kind)
    return _plain(getattr(v, "fix", None), fallback or UNKNOWN_FIX)


def _concern(v: ProviderView) -> Concern:
    sev: Severity = "red" if v.status == "red" else "amber"
    return Concern(VITALS_PREFIX + v.provider.id, v.provider.label, sev, _impact(v), _fix(v))


def _hot(v: ProviderView) -> bool:
    return v.status in ("amber", "red")


def _allowance_high(v: ProviderView) -> bool:
    return (
        v.provider.kind == "allowance"
        and v.percent is not None
        and v.percent >= ALLOWANCE_WARN_PERCENT
    )


def _spend_part(board: Board) -> tuple[list[_Part], list[Concern]]:
    spend = board.spend
    if spend is None:
        return [], []
    used, limit = spend.used_inr, spend.limit_inr
    if limit is None:
        text = f"AI spend is {rupees(used)} this month, no limit set"
    elif limit > 0:
        text = f"AI spend is {rupees(used)} of {rupees(limit)} this month, "
        text += f"{round(used / limit * 100)} percent"
    else:
        text = f"AI spend is {rupees(used)} of {rupees(limit)} this month"
    item = next((v for v in board.items if v.provider.id == SPEND_ID and _hot(v)), None)
    if item is None:
        return [_Part(text + ".", 0)], []
    return [_Part(f"{text} {DASH} {_impact(item)}.", 0)], [_concern(item)]


def _vitals_parts(board: Board) -> tuple[list[_Part], list[Concern]]:
    parts, concerns = _spend_part(board)
    rest = [v for v in board.items if v.provider.id != SPEND_ID]
    allowances = [v for v in rest if _allowance_high(v)]
    allowances.sort(key=lambda v: (v.status != "red", v.provider.label))
    for v in allowances:
        pct = round(v.percent or 0.0)
        rank = 3 if v.status == "red" else 4
        parts.append(_Part(f"{v.provider.label}: {pct} percent used {DASH} {_impact(v)}.", rank))
        concerns.append(_concern(v))
    seen = {v.provider.id for v in allowances} | {SPEND_ID}
    for v in board.attention():  # amber and red, red first
        if v.provider.id in seen:
            continue
        why = v.reason.strip() or "needs attention"
        rank = 3 if v.status == "red" else 4
        parts.append(_Part(f"{v.provider.label} {why} {DASH} {_impact(v)}.", rank))
        concerns.append(_concern(v))
    return parts, concerns


# ---- the cap ---------------------------------------------------------------------------------
def _spoken(parts: Sequence[_Part], close: str) -> str:
    """Drop the highest-rank (least important) parts, the last of them first, until it fits."""
    kept = list(parts)
    dropped = 0

    def text() -> str:
        more = [f"And {dropped} more on screen."] if dropped else []
        return " ".join([*(p.text for p in kept), *more, *([close] if close else [])])

    while len(text()) > MAX_SPOKEN:
        droppable = [i for i, p in enumerate(kept) if p.rank > 0]
        if not droppable:
            break
        worst = max(droppable, key=lambda i: (kept[i].rank, i))
        del kept[worst]
        dropped += 1
    out = text()
    return out if len(out) <= MAX_SPOKEN else out[: MAX_SPOKEN - 1].rstrip() + "…"


def _ordered(concerns: Iterable[Concern]) -> tuple[Concern, ...]:
    """Most severe first: systems down, degraded, then vitals red, amber; stable within each."""
    items = list(concerns)
    return tuple(sorted(items, key=lambda c: (_RANK[c.severity], items.index(c))))


def compose_briefing(
    report: HealthReport | None,
    board: Board | None,
    *,
    vitals_unreadable: bool = False,
) -> Briefing:
    """The briefing for one check. `board` None: no Vitals here (nothing said about it), or, with
    `vitals_unreadable`, the board could not be read (one fixed sentence says so)."""
    results = report.results if report is not None else ()
    parts, concerns = _system_parts(results)
    spend = ""
    if board is not None:
        more, extra = _vitals_parts(board)
        spend = more[0].text if more and board.spend is not None else ""
        parts += more
        concerns += extra
    elif vitals_unreadable:
        spend = VITALS_UNREADABLE
        parts.append(_Part(VITALS_UNREADABLE, 0))
    # nothing was checked and nothing is wrong: the one line above says it all (no "nominal")
    close = REMIND_CLOSE if concerns else NOMINAL_CLOSE if results else ""
    lines = (*(p.text for p in parts), *([close] if close else []))
    return Briefing(
        spoken=_spoken(parts, close), lines=lines, concerns=_ordered(concerns), spend=spend
    )


__all__ = [
    "BY_REASON",
    "EMPTY",
    "FIX",
    "IMPACT",
    "MAX_SPOKEN",
    "NOMINAL_CLOSE",
    "REMIND_CLOSE",
    "VITALS_UNREADABLE",
    "Briefing",
    "Concern",
    "Severity",
    "compose_briefing",
]
