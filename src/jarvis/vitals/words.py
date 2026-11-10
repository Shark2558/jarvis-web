# src/jarvis/vitals/words.py
"""What each automatic Vitals item means for the owner (R5.1 D2, D5): FIXED plain English written
here, never a vendor's or an exception's text, never a key value. `impact` says what stops ("If
this stops: ..."); `fix` says what to do. The panel shows them under an amber or red item and the
systems-check briefing reads them (`ProviderView.impact` / `.fix`). The owner's own (manual)
records have none: JARVIS can't know what they are for."""

from __future__ import annotations

from collections.abc import Mapping

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


def words_for(pid: str, label: str, reason: str = "") -> tuple[str, str]:
    """(impact, fix) for an automatic item; ("", "") when JARVIS has nothing fixed to say.
    A quota's impact names its own label, which comes from code (the SKU table). `reason` is the
    item's own fixed reason: a known cause (`BY_REASON`) has its own words."""
    if (pid, reason) in BY_REASON:
        return BY_REASON[(pid, reason)]
    if pid in WORDS:
        return WORDS[pid]
    if pid.startswith(ALLOWANCE_PREFIX):
        return ALLOWANCE_WORDS
    if pid.startswith(QUOTA_PREFIX):
        return f"If this runs out: {label} pause until it resets.", QUOTA_FIX
    return "", ""


__all__ = ["BY_REASON", "NO_CREDIT", "WORDS", "words_for"]
