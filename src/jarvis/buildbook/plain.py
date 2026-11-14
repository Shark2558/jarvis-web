# src/jarvis/buildbook/plain.py
"""Plain words for the build book (R6 D2's Integrations row, D15's show). Fixed text written by
people, never by a model: what each layer is for, what a package does when its code has no
docstring, which outside services JARVIS talks to (and which settings name them), what each alert
kind means and what each vault key protects. The generator (`buildbook/gen`) joins these to facts
it reads from the code; nothing here names the owner or holds a value of a setting.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

LAYER_WORDS: Mapping[str, str] = MappingProxyType(
    {
        "L1": "where you reach me: the console, Telegram and the terminal",
        "L2": "how I take things in: speech, documents and what the home camera sees",
        "L3": "what I keep in mind: the conversation, long-term memory and scheduled work",
        "L4": "where I think: the brain, the model router and the No-AI fallback",
        "L5": "what I can do: briefs, research, notes, groceries, family and more",
        "L6": "what I connect to: tools, Google, the home bridge and the camera",
        "L7": "where things are kept: the document store and the sealed vault",
        "L8": "how I answer back: alerts, browser notifications and the activity log",
        "X": "what runs through everything: keys, permissions, costs, health and privacy",
    }
)

# Packages whose __init__ has no docstring (the code's own first line wins when there is one)
PACKAGE_WORDS: Mapping[str, str] = MappingProxyType(
    {
        "api": "The web server: the console, the routes and the sign-in.",
        "family": "The family calendar, read from the calendars the owner chose.",
        "groceries": "The grocery list.",
        "llm": "The model router and one adapter per AI brain; nothing else imports a vendor SDK.",
        "memory": "The conversation store (sessions).",
        "packages": "Package tracking, deterministic, no model.",
        "tools": "The tool registry and the policy gateway every tool call passes through.",
    }
)


@dataclass(frozen=True)
class ServiceWords:
    """An outside service: the Settings names that configure it (by prefix or exact name) and
    the health probe that checks it, if any."""

    id: str
    label: str
    what: str
    prefixes: tuple[str, ...]
    probe: str = ""


SERVICES: tuple[ServiceWords, ...] = (
    ServiceWords(
        "anthropic",
        "Anthropic Claude",
        "The default AI brain, chosen by tier (fast, balanced, strong), never by a fixed model.",
        ("anthropic_", "model_"),
        "brain",
    ),
    ServiceWords(
        "gemini",
        "Google Gemini",
        "A free brain the owner can switch to; Google may learn from what it is told.",
        ("gemini_",),
    ),
    ServiceWords(
        "openai_compat",
        "OpenAI-compatible brain",
        "Any brain that speaks the OpenAI chat format, including one on the owner's laptop.",
        ("openai_compat_",),
    ),
    ServiceWords(
        "google",
        "Google sign-in, Gmail and Calendar",
        "The owner's sign-in, and the mail and calendar the owner connects.",
        ("google_client_", "google_tools_", "owner_emails", "auth_mode"),
        "google",
    ),
    ServiceWords(
        "google_maps",
        "Google Maps and YouTube",
        "Place search, routes and YouTube look-ups, inside Google's free allowances.",
        ("google_api_key", "maps_"),
    ),
    ServiceWords(
        "drive",
        "Google Drive",
        "Read-only access to the folders the owner shares with JARVIS.",
        ("drive",),
    ),
    ServiceWords(
        "firestore",
        "Firestore",
        "The document store: conversations, approvals, the audit chain and the sealed vault.",
        ("firestore_",),
        "docs",
    ),
    ServiceWords(
        "redis",
        "Redis",
        "An optional fast session store for local runs.",
        ("redis_",),
        "redis",
    ),
    ServiceWords(
        "telegram",
        "Telegram",
        "The front door on the phone, and alerts from fixed templates.",
        ("telegram_",),
        "telegram",
    ),
    ServiceWords(
        "tavily",
        "Tavily web search",
        "Web search with citations, stopped at the free monthly credits.",
        ("tavily_", "web_search_"),
        "web",
    ),
    ServiceWords(
        "google_speech",
        "Google Cloud speech",
        "JARVIS's voice and speech recognition, inside the free monthly allowance.",
        ("voice_",),
    ),
    ServiceWords(
        "home_bridge",
        "The home bridge",
        "The laptop at home: Home Assistant and the camera, reached only through a signed link.",
        ("home_",),
        "home",
    ),
    ServiceWords(
        "web_push",
        "Browser notifications",
        "Standard Web Push to the owner's browsers.",
        ("webpush_",),
    ),
    ServiceWords(
        "frankfurter",
        "Frankfurter exchange rates",
        "The daily dollar-to-rupee rate, with no key.",
        ("usd_inr_",),
    ),
    ServiceWords(
        "scheduler",
        "Cloud Scheduler",
        "The morning tick and the five-minute watchdog that wake JARVIS on time.",
        ("brief_scheduler_",),
    ),
)

ALERT_WORDS: Mapping[str, str] = MappingProxyType(
    {
        "approval_waiting": "Something is waiting for my approval",
        "offline_on": "Offline mode switched on",
        "offline_off": "Offline mode switched off",
        "brief_ready": "My morning brief is ready",
        "vault_expiry": "A document in my vault is due to expire",
        "test": "A test alert the owner asked for",
        "home_intruder": "Someone at the camera while the alarm is armed",
        "home_hazard": "Smoke, gas or water alarm at home",
        "home_package": "A package was left",
        "home_greeting": "Someone JARVIS recognised arrived",
        "home_offline": "My home laptop stopped answering",
        "home_online": "My home laptop is back",
        "home_arm_failed": "The alarm could not be armed",
        "home_summary": "A summary of many alerts at once",
        "home_offline_idle": "Laptop stopped answering (alarm off)",
        "vitals_warn": "A key, quota or bill is getting close to its limit",
        "vitals_critical": "A key, quota or bill has reached its limit or expired",
        "health_fault": "One of my systems is down",
        "health_recovered": "A system that was down works again",
        "health_degraded": "A system is slow or partly working",
        "book_sealed": "A release's build book was sealed in my vault",
        "book_seal_failed": "A release's build book could not be sealed",
        "book_session_closed": "A build book session closed",
        # R11: the helpers (docs/plans/r11-free-helpers.md D5)
        "disaster_alert": "A disaster warning for my area",
        "bill_due": "A bill is due",
        "birthday": "A birthday in my contacts today",
        "chore_due": "A chore on the rota is due",
        "maintenance_due": "Home upkeep is due",
        "weather_warning": "A weather warning for my area",
        "breach_notice": "A data-breach notice arrived in my mail",
        "nudge_standup": "A nudge to stand up",
        "nudge_hydrate": "A nudge to drink water",
        "nudge_activity": "A planned activity didn't happen",
        "nudge_free_time": "An idea for free time",
        "nudge_focus": "My top priority now",
        "weather_note": "A minor weather note",
        "series_checkin": "A planned session: did it happen?",
        "faces_to_name": "New faces to name from my photo folder",
        # R7 (docs/plans/r7-mobile.md D25)
        "sos_sent": "An SOS was sent",
        "phone_linked": "A phone was linked to JARVIS",
        "sos_contact_left": "An emergency contact left",
        "phone_unlinked": "A phone was unlinked",
        "watch_stale": "The watch has not synced for a day",
    }
)

PURPOSE_WORDS: Mapping[str, str] = MappingProxyType(
    {
        "vault": "documents in the vault",
        "vault_index": "the vault's index",
        "notes": "notes, memos and links",
        "belongings": "where things are kept",
        "tickets": "single-use download tickets",
        "home": "the home link",
        "home_feed": "the home alert feed",
        "faces": "the faces registry",
        "webpush": "browser subscriptions",
        "notify": "the VIP list for alerts",
        "connectors": "the owner's own account tokens",
        "book_index": "the sealed build books",
        "book_session": "build book sessions",
        # R11
        "bills": "bills and their UPI IDs",
        "spend": "grocery spend from receipts",
        "wellbeing": "the water and activity log",
        "alerts_place": "the place for weather and disaster alerts",
        "kitchen": "the pantry, diet and saved recipes",
        # R7
        "watch": "the watch's daily steps, heart rate and sleep",
        "sos": "the emergency contacts",
        "vision": "the camera results you kept",
    }
)


def alert_words(kind: str) -> str:
    return ALERT_WORDS.get(kind) or kind.replace("_", " ").capitalize()


def purpose_words(purpose: str) -> str:
    return PURPOSE_WORDS.get(purpose) or purpose.replace("_", " ")


__all__ = [
    "ALERT_WORDS",
    "LAYER_WORDS",
    "PACKAGE_WORDS",
    "PURPOSE_WORDS",
    "SERVICES",
    "ServiceWords",
    "alert_words",
    "purpose_words",
]
