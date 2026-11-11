# src/jarvis/buildbook/gen/show.py
"""R6 D2, D15: the show script (scenes 1-11), filled from the book's own sections with FIXED
templates (no model writes a word). Every number, name and label a scene draws is a `Fact` here;
D's 3D and 2D scenes read only these (no facts in JavaScript).
Scenes 12 and 13 are `buildbook/lines.py` (the questions and the closing).

The talk-through's digest (D11) is built from the same `Parts` in `gen/chunks.py`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from jarvis.buildbook import plain
from jarvis.buildbook.gen.code import clip
from jarvis.buildbook.model import (
    LAYERS,
    SHOW_SCENES,
    Beat,
    Fact,
    ReleaseRef,
    Scene,
    Show,
)
from jarvis.buildbook.sections import (
    Architecture,
    Costs,
    Integrations,
    Library,
    Limitation,
    PlanDecisions,
    Stack,
    Workflow,
)

MAX_FACTS, BEAT_MAX = 60, 400
LATER_BEATS = 4  # limitations read aloud in scene 11
PROPER = frozenset({"Cloud", "Google", "Telegram", "Firestore", "JARVIS", "Tavily"})
_FLAG_WORDS = {"non_commercial": "personal, non-commercial use only", "copyleft": "copyleft"}
_KIND_WORDS = {
    "not_in_plan": "Not in this release",
    "risk": "A risk",
    "needs_owner": "Waiting on you",
    "open_question": "An open question",
    "deferred": "Deferred",
    "licence": "A licence note",
}


@dataclass(frozen=True)
class Parts:
    """The book's sections, as the scenes and the digest read them."""

    release: ReleaseRef
    architecture: Architecture
    stack: Stack
    libraries: tuple[Library, ...]
    integrations: Integrations
    workflows: tuple[Workflow, ...]
    limitations: tuple[Limitation, ...]
    costs: Costs
    decisions: tuple[PlanDecisions, ...]

    def flow(self, fid: str) -> Workflow:
        return next(w for w in self.workflows if w.id == fid)


def fact(
    label: str, value: str = "", n: float | None = None, group: str = "", flag: str = ""
) -> Fact:
    return Fact(
        label=clip(label, 80), value=clip(value, 120), n=n, group=clip(group, 40), flag=flag
    )


def _scene(n: int, lines: Sequence[str | tuple[str, str]], facts: Iterable[Fact] = ()) -> Scene:
    beats = []
    for k, line in enumerate(lines, start=1):
        text, focus = (line, "") if isinstance(line, str) else line
        beats.append(Beat(id=f"s{n:02d}b{k:02d}", text=clip(text, BEAT_MAX), focus=clip(focus, 60)))
    _, sid, title = SHOW_SCENES[n - 1]
    return Scene(n=n, id=sid, title=title, beats=tuple(beats), facts=tuple(facts)[:MAX_FACTS])


# the accent D's flow scenes draw for a step (I1): a shield, chain links, the passkey ring
_HINTS = (
    ("guard", "guard"),
    ("gateway", "gateway"),
    ("audit", "audit"),
    ("permissions", "passkey"),
)


def _hint(symbol: str) -> str:
    module = symbol.split(":", 1)[0]
    return next((h for word, h in _HINTS if word in module), "step")


def flow_facts(flow: Workflow) -> list[Fact]:
    """A flow's steps as scene facts, in order, each with D's accent hint (else "step")."""
    return [
        fact(s.label, s.symbol.removeprefix("jarvis."), i, _hint(s.symbol))
        for i, s in enumerate(flow.steps, 1)
    ]


_steps = flow_facts


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def human_date(iso: str) -> str:
    """An ISO date as the owner reads it: 2026-11-10 -> 10 Nov 2026 (I1 screenshots, O3). Fixed
    month words, no locale, so the same commit gives the same bytes; anything else as given."""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _lower_first(text: str) -> str:
    """Lower-case a label's first letter, unless its first word is a name ("Telegram")."""
    word = text.split(" ", 1)[0]
    if word in PROPER or any(c.isupper() for c in word[1:]):
        return text
    return text[:1].lower() + text[1:]


def _joined(flow: Workflow) -> str:
    return "; ".join(_lower_first(s.label) for s in flow.steps) + "."


def _licence_family(licence: str) -> str:
    """For counting aloud only: "Apache 2.0", "Apache-2.0" and "Apache Software License" are one."""
    key = licence.lower()
    for family in ("MIT", "Apache", "BSD", "MPL", "PSF", "OFL", "GPL"):
        if family.lower() in key and " or " not in key:
            return family
    return "other"


# ---- scenes 1-4 ------------------------------------------------------------------------------
def _version(p: Parts) -> str:
    """ "version v6.1.0, " before the commit (R6.1 decision 3); nothing for an older checkout."""
    return f"version {p.release.version}, " if p.release.version else ""


def _book(p: Parts) -> Scene:
    pk = p.architecture.packages
    files, lines = sum(x.files for x in pk), sum(x.lines for x in pk)
    day = human_date(p.release.committed_at)
    return _scene(
        1,
        [
            f"This is my build book for release {p.release.label}, {_version(p)}commit "
            f"{p.release.id}, from {day}. "
            "Fixed code wrote it from my own code and plans; no AI wrote a word of it.",
            f"I am {len(pk)} parts in {files:,} files, about {lines:,} lines of code, "
            "arranged in eight layers with a band that runs through them all.",
            "Next: my layers, one conversation, memory and privacy, how I ask before I act, voice, "
            "home, what I do on my own, what I'm built from, what I cost, and what I can't do yet.",
        ],
        [
            fact("Release", p.release.label),
            fact("Commit", p.release.id),
            fact("Date", day),
            fact("Parts", n=len(pk)),
            fact("Files", n=files),
            fact("Lines", n=lines),
        ],
    )


def _layers(p: Parts) -> Scene:
    lines: list[str | tuple[str, str]] = []
    facts = []
    for lid, name in LAYERS:
        mine = [x for x in p.architecture.packages if x.layer == lid]
        count, code = len(mine), sum(x.lines for x in mine)
        head = f"Layer {lid[1:]}, {name}" if lid != "X" else "Running through all of them"
        names = ", ".join(x.name for x in mine[:6]) or "nothing yet"
        lines.append(
            (
                f"{head}: {plain.LAYER_WORDS[lid]}. {count} parts, about {code:,} lines: {names}.",
                lid,
            )
        )
        facts.append(fact(name, lid, count, "layer"))  # D: one plate a layer, n = its parts
    return _scene(2, lines, facts)


def _turn(p: Parts) -> Scene:
    flow = p.flow("chat_turn")
    steps: list[str | tuple[str, str]] = [
        (f"{s.label}.", s.symbol.removeprefix("jarvis.")) for s in flow.steps
    ]
    return _scene(
        3,
        [
            "Here is one conversation turn, from your words to my reply, "
            f"in {len(flow.steps)} steps.",
            *steps,
            "This book checked every one of those steps against the code before it was written.",
        ],
        _steps(flow),
    )


def _memory(p: Parts) -> Scene:
    keys = p.integrations.key_purposes
    words = "; ".join(plain.purpose_words(k) for k in keys[:6])
    return _scene(
        4,
        [
            "What you keep with me is encrypted by me before it is stored: "
            f"{len(keys)} separate keys, "
            f"one for each purpose, all derived from one root key. Among them: {words}.",
            f"Opening the vault: {_joined(p.flow('vault_open'))}",
            f"Learning after a conversation: {_joined(p.flow('learning'))}",
        ],
        [fact(plain.purpose_words(k), k, group="purpose") for k in keys],
    )


# ---- scenes 5-8 ------------------------------------------------------------------------------
def _confirm(p: Parts) -> Scene:
    flow = p.flow("approval")
    steps: list[str | tuple[str, str]] = [
        (f"{s.label}.", str(i)) for i, s in enumerate(flow.steps, 1)
    ]
    return _scene(
        5,
        [
            "I ask before I act. Reading is free; anything that sends, spends or deletes "
            "waits for you.",
            *steps,
        ],
        _steps(flow),
    )


def _voice(p: Parts) -> Scene:
    flow = p.flow("voice_turn")
    voice = [i for i in p.costs.items if i.kind == "voice"]
    free = next((i.free for i in voice if i.free), "")
    allowance = f" Cloud speech stays inside its free allowance: {free}." if free else ""
    return _scene(
        6,
        [
            f"You can talk to me. A spoken turn: {_joined(flow)}",
            "The wake word runs on your own device, so nothing is sent until you speak to me."
            + allowance,
        ],
        _steps(flow),  # the voice prices are scene 10's
    )


def _home(p: Parts) -> Scene:
    flow = p.flow("home_alert")
    return _scene(
        7,
        [
            "At home, a laptop runs the camera and the devices; recognising faces stays there.",
            f"A home alert: {_joined(flow)}",
        ],
        [*HOME_FACTS, *_steps(flow)],
    )


# D15 scene 7: inside the home boundary, the one laptop at its edge, the rest outside
HOME_FACTS = (
    fact("The camera", "at home", group="home"),
    fact("Recognising faces", "stays at home", group="home"),
    fact("The devices", "at home", group="home"),
    fact("The laptop", "the home bridge", group="edge"),
)


def _own(p: Parts) -> Scene:
    kinds = p.integrations.alert_kinds
    count = Counter(a.level for a in kinds)
    return _scene(
        8,
        [
            f"Some work I do on my own. Each morning: {_joined(p.flow('morning_tick'))}",
            f"And the systems check: {_joined(p.flow('systems_check'))}",
            f"I can send {len(kinds)} kinds of alert: "
            f"{count['urgent']} urgent, which ring at any hour; "
            f"{count['important']} important, which wait for the morning while you sleep; and "
            f"{count['info']} that only note things quietly.",
        ],
        [
            *_steps(p.flow("morning_tick")),
            *_steps(p.flow("systems_check")),
            *(fact(a.what, a.kind, group=a.level) for a in kinds),
        ],
    )


# ---- scenes 9-11 -----------------------------------------------------------------------------
def _stack(p: Parts) -> Scene:
    items = p.stack.items
    py = next((i.version for i in items if i.role == "language"), "")
    py = f"{py[2:]} or newer" if py.startswith(">=") else py
    base = next((f"{i.name}:{i.version}" for i in items if i.role == "base image"), "")
    jobs = sum(1 for i in items if i.role == "ci job")
    libs = p.libraries
    python = [x for x in libs if x.kind == "python"]
    top = Counter(_licence_family(x.licence) for x in libs).most_common()
    flagged = [x for x in libs if x.flag]
    notes = "; ".join(f"{x.name} ({x.licence}), {_FLAG_WORDS[x.flag]}" for x in flagged if x.flag)
    head = "One licence needs" if len(flagged) == 1 else f"{len(flagged)} licences need"
    warn = f"{head} a note: {notes}." if flagged else "No licence needs a note."
    tags = sorted(libs, key=lambda x: (not x.flag, x.kind == "python", x.name.lower()))
    return _scene(
        9,
        [
            f"I'm written in Python {py}, packed into a {base or 'Python'} container "
            "and checked on "
            f"every change by {jobs} automated jobs.",
            f"I use {len(python)} Python libraries and {len(libs) - len(python)} vendored pieces: "
            "code, models and fonts.",
            "By licence: " + ", ".join(f"{n} {name}" for name, n in top) + ".",
            warn,
        ],
        [fact(x.name, x.licence, group=x.role, flag=x.flag or "") for x in tags],
    )


def _costs(p: Parts) -> Scene:
    c = p.costs
    paid = [
        i for i in c.items if i.kind == "model" and i.inr > 0 and i.unit.endswith("input tokens")
    ]
    free_brains = [i for i in c.items if i.kind == "model" and i.inr == 0]
    span = f"₹{min(i.inr for i in paid):,.2f} to ₹{max(i.inr for i in paid):,.2f}" if paid else "₹0"
    return _scene(
        10,
        [
            f"Everything I cost is shown in rupees, at ₹{c.usd_inr:,.2f} to the dollar "
            f"on {human_date(c.rate_date)}.",
            f"The paid brains cost {span} per million input tokens; {len(free_brains)} free brains "
            "cost nothing.",
            "Web search, maps and the cloud itself stay inside their free allowances: ₹0.",
            "You set a monthly limit, and I check it before every paid call.",
        ],
        [fact(i.label, f"₹{i.inr:,.2f}", i.inr, i.kind) for i in c.items],
    )


def _later(p: Parts) -> Scene:
    lims = p.limitations
    said = [(f"{_KIND_WORDS[x.kind]}. {x.text}", x.kind) for x in lims[:LATER_BEATS]]
    return _scene(
        11,
        [
            f"Finally, what I can't do yet. My plans list {len(lims)} things, newest first.",
            *said,
            "The full list is in the book.",
        ],
        [fact(x.text, x.kind, group=x.release) for x in lims],
    )


SCENES = (_book, _layers, _turn, _memory, _confirm, _voice, _home, _own, _stack, _costs, _later)


def build_show(p: Parts) -> Show:
    return Show(scenes=tuple(make(p) for make in SCENES))


__all__ = ["SCENES", "Parts", "build_show", "fact"]
