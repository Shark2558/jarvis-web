# src/jarvis/vitals/words.py
"""What each automatic Vitals item means for the owner (R5.1 D2, D5): FIXED plain English written
here, never a vendor's or an exception's text, never a key value. `impact` says what stops ("If
this stops: ..."); `fix` says what to do. The panel shows them under an amber or red item and the
systems-check briefing reads them (`ProviderView.impact` / `.fix`). The owner's own (manual)
records have none: JARVIS can't know what they are for.

R11.1 D18: the home laptop's own parts. Its heartbeat says which part failed (`frigate`, `mqtt`);
`HOME_FAULTS`, a map keyed by that part, holds the row's words and the fix steps (the kit's own
script and containers, `deploy/home/`). `home_fault(parts)` reads only those keys as plain
booleans, so a camera's or a device's name never reaches a row."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from jarvis.vitals.auto import SPEND_ID

ALLOWANCE_PREFIX = "allowance_"
QUOTA_PREFIX = "quota_"
NO_CREDIT = "is out of credit"  # the Claude key's reason when the account can't be billed

WORDS: Mapping[str, tuple[str, str]] = {
    "brain_claude": (
        "If this stops: paid AI replies stop; JARVIS answers with the free brain where it can.",
        "Add credit or make a new key in the Anthropic console, then run the JARVIS setup "
        "again and paste the new key when it asks.",
    ),
    "brain_gemini": (
        "If this stops: the free AI brain stops answering; paid replies carry on if Claude "
        "is set up.",
        "Wait for the free limit to reset, or make a new key in Google AI Studio and run the "
        "JARVIS setup again.",
    ),
    "google_link": (
        "If this stops: Gmail, Calendar, Drive and Photos stop working in JARVIS.",
        "Reconnect Google in the Integrations panel.",
    ),
    "telegram_bot": (
        "If this stops: alerts and Telegram chat won't reach you.",
        "Run a systems check; if Telegram still fails, check the bot with BotFather and run the "
        "JARVIS setup again with its token.",
    ),
    "web_credits": (
        "If this stops: JARVIS can't search the web until the credits reset.",
        "Wait for the monthly reset, or raise the plan in the Tavily dashboard.",
    ),
    "github_token": (
        "If this stops: JARVIS can't read your GitHub.",
        "Paste a new token in Connectors (make one on GitHub: Settings, Developer settings).",
    ),
    "home_link": (
        "If this stops: the home camera, devices and alarm can't reach JARVIS.",
        "Check the home laptop is on, awake and online, then restart the JARVIS bridge on it.",
    ),
    "build_book": (  # R6 review L2: shown only when the book could not start
        "If this stops: the build book is off on this server; the rest of JARVIS keeps working.",
        "Deploy again; if it stays, the server's logs name the error class shown here.",
    ),
    SPEND_ID: (
        "If this stops: paid replies pause; JARVIS uses the free brain.",
        "Raise the monthly limit with Set limit above, or wait for the new month.",
    ),
}

# (item id, its fixed reason) -> (impact, fix) when the cause is known in code (R5.1 I1)
BY_REASON: Mapping[tuple[str, str], tuple[str, str]] = {
    ("brain_claude", NO_CREDIT): (
        "Now: paid AI replies are paused until the account is topped up; JARVIS answers with the "
        "free brain where it can.",
        "Top up at console.anthropic.com → Plans & billing",
    ),
}

ALLOWANCE_WORDS = (
    "If this runs out: voice keeps working but each use costs rupees, counted in this "
    "month's AI spend.",
    "Nothing to do: it resets on its own. Use voice less until then to avoid the cost.",
)
QUOTA_FIX = "Nothing to do: it resets on its own."


# ---- the home laptop's parts (R11.1 D18) ---------------------------------------------------------
HOME_LINK_ID = "home_link"
HOME_ON = "is on, but "
START_KIT = "On the home laptop, run start-home.ps1."
RESTART = "open Ubuntu and run: docker restart"
# `docker restart` takes them in this order: the messenger first, then what connects to it
RESTART_ORDER = ("jarvis-home-mosquitto-1", "jarvis-home-frigate-1", "jarvis-home-bridge-1")
SEVERAL_STAY = "If that fails"
SEVERAL_IMPACT = (
    "Now: burglar alerts can't arrive until you start both again with start-home.ps1 on the "
    "home laptop."
)


@dataclass(frozen=True)
class HomeFault:
    """One part of the home kit the laptop's heartbeat can report as failing."""

    name: str  # the part in plain words, with the product's name
    state: str  # how it is failing
    so: str  # the consequence said on the row itself ("" when `state` already makes it plain)
    impact: str  # what stops now, and until when
    stays: str  # how the second fix step begins
    containers: tuple[str, ...]  # what that second step restarts (the kit's container names)

    @property
    def reason(self) -> str:
        return f"{HOME_ON}{self.name} {self.state}{self.so}"

    @property
    def fix(self) -> str:
        return f"{START_KIT} {self.stays}, {RESTART} {' '.join(self.containers)}"


@dataclass(frozen=True)
class HomeWords:
    """A home row's three lines for the parts that are failing right now."""

    reason: str
    impact: str
    fix: str


HOME_FAULTS: Mapping[str, HomeFault] = {
    "frigate": HomeFault(
        name="the camera watcher (Frigate)",
        state="is not answering",
        so="",
        impact="Now: nothing is watching the camera, so burglar alerts can't arrive until you "
        "start it again with start-home.ps1 on the home laptop.",
        stays="If it still doesn't answer",
        containers=("jarvis-home-frigate-1",),
    ),
    "mqtt": HomeFault(
        name="the camera's messenger (MQTT)",
        state="is not connected",
        so=", so burglar alerts can't arrive",
        impact="Now: what the camera sees can't reach JARVIS until you start it again with "
        "start-home.ps1 on the home laptop.",
        stays="If it stays disconnected",
        containers=("jarvis-home-mosquitto-1", "jarvis-home-bridge-1"),
    ),
}


def _home_words(failing: tuple[HomeFault, ...]) -> HomeWords:
    if len(failing) == 1:
        one = failing[0]
        return HomeWords(one.reason, one.impact, one.fix)
    said = " and ".join(f"{f.name} {f.state}" for f in failing)
    wanted = {c for f in failing for c in f.containers}
    containers = [c for c in RESTART_ORDER if c in wanted]
    fix = f"{START_KIT} {SEVERAL_STAY}, {RESTART} {' '.join(containers)}"
    return HomeWords(f"{HOME_ON}{said}", SEVERAL_IMPACT, fix)


def home_fault(parts: object) -> HomeWords | None:
    """The row's words for the parts the laptop reported as failing, or None when none of the
    known parts did. Only a plain `False` under a key of `HOME_FAULTS` counts: every other key
    and value (camera ids, counts, anything a newer bridge adds) is never read."""
    if not isinstance(parts, Mapping):
        return None
    failing = tuple(f for key, f in HOME_FAULTS.items() if parts.get(key) is False)
    return _home_words(failing) if failing else None


def _home_by_reason(reason: str) -> HomeWords | None:
    """The words whose row text is exactly `reason` (every set of parts that can fail together)."""
    faults = tuple(HOME_FAULTS.values())
    for n in range(1, len(faults) + 1):
        for failing in combinations(faults, n):
            found = _home_words(failing)
            if found.reason == reason:
                return found
    return None


def words_for(pid: str, label: str, reason: str = "") -> tuple[str, str]:
    """(impact, fix) for an automatic item; ("", "") when JARVIS has nothing fixed to say.
    A quota's impact names its own label, which comes from code (the SKU table). `reason` is the
    item's own fixed reason: a known cause (`BY_REASON`, a failing part of the home laptop) has
    its own words."""
    if (pid, reason) in BY_REASON:
        return BY_REASON[(pid, reason)]
    if pid == HOME_LINK_ID and (home := _home_by_reason(reason)) is not None:
        return home.impact, home.fix
    if pid in WORDS:
        return WORDS[pid]
    if pid.startswith(ALLOWANCE_PREFIX):
        return ALLOWANCE_WORDS
    if pid.startswith(QUOTA_PREFIX):
        return f"If this runs out: {label} pause until it resets.", QUOTA_FIX
    return "", ""


__all__ = [
    "BY_REASON",
    "HOME_FAULTS",
    "NO_CREDIT",
    "WORDS",
    "HomeFault",
    "HomeWords",
    "home_fault",
    "words_for",
]
