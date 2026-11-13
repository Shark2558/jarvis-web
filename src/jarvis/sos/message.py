# src/jarvis/sos/message.py
"""Every word an SOS sends, written by code and never by a model (docs/plans/r7-mobile.md D19, D20).

- To his contacts (`message_for`): "SOS from {label}: I need help. My location at 14:05:
  {maps link} (within about 20 m). Sent by my JARVIS assistant." The time is when the phone fixed
  the place (so it says how old the fix is) and the accuracy is rounded; without a place: "My
  location is not available." A test says it is a test; "I'm safe" carries no place.
- To a contact who joined or left (`joined_words`, `left_words`).
- To him (`notice_for`): how many were reached, never a name (an alert names nobody).
The label is his own, cleaned (`models.clean_label`). Nothing anyone writes back is ever used.
"""

from __future__ import annotations

from jarvis.sos.models import Kind, Location

ASSISTANT = "Sent by my JARVIS assistant."
NO_PLACE = "My location is not available."
EMERGENCY = "112"


def degrees(e6: int) -> str:
    """Micro-degrees as decimal degrees with 6 places, in integers only (no float noise)."""
    sign = "-" if e6 < 0 else ""
    whole, frac = divmod(abs(e6), 1_000_000)
    return f"{sign}{whole}.{frac:06d}"


def maps_link(loc: Location) -> str:
    return f"https://maps.google.com/?q={degrees(loc.lat_e6)},{degrees(loc.lon_e6)}"


def accuracy_words(metres: int) -> str:
    if metres >= 1000:
        return f"within about {max(1, round(metres / 1000))} km"
    return f"within about {max(5, round(metres / 5) * 5)} m"


def _place(loc: Location | None, fixed_at: str) -> str:
    if loc is None:
        return NO_PLACE
    return f"My location at {fixed_at}: {maps_link(loc)} ({accuracy_words(loc.accuracy_m)})."


def message_for(kind: Kind, label: str, loc: Location | None, fixed_at: str) -> str:
    if kind == "safe":
        return f"{label} is safe now. Thank you. {ASSISTANT}"
    if kind == "test":
        head = f"TEST from {label}: this is only a test of my JARVIS SOS, please ignore it."
    else:
        head = f"SOS from {label}: I need help."
    return f"{head} {_place(loc, fixed_at)} {ASSISTANT}"


def joined_words(label: str) -> str:
    return (
        f"You are now an emergency contact for {label}. This bot writes to you only when {label} "
        "presses SOS or sends a test. Send /stop to leave."
    )


def left_words(label: str) -> str:
    return f"You are no longer an emergency contact for {label}. They have been told."


LEFT_NOTICE = (
    "One of your emergency contacts left your SOS list on Telegram, Sir. Open Integrations "
    "→ Emergency SOS to see who."
)
WHAT = {"real": "SOS", "test": "Test SOS", "safe": '"I\'m safe"'}


def notice_for(kind: Kind, outcome: str, reached: int, joined: int, at: str, why: str) -> str:
    """The owner's alert: counts and JARVIS's words only (`why` is our own refusal words)."""
    what = WHAT[kind]
    if outcome == "refused":
        return f"{what} at {at} was not sent on Telegram: {why} Use the SMS screen or call 112."
    if outcome == "unavailable":
        return f"{what} at {at} could not be sent: {why} Use the SMS screen or call 112."
    if outcome == "none_joined":
        return (
            f"{what} at {at}: no emergency contact has joined on Telegram, so nothing was sent "
            "there. Use the SMS screen or call 112."
        )
    if reached == 0:
        return f"{what} at {at} reached no one on Telegram. Use the SMS screen or call 112 now."
    if reached < joined:
        return (
            f"{what} at {at} reached {reached} of {joined} emergency contacts on Telegram; "
            f"{joined - reached} not reached. Use the SMS screen or call 112."
        )
    return f"{what} sent at {at} to {reached} of {joined} emergency contacts on Telegram."


__all__ = [
    "ASSISTANT",
    "EMERGENCY",
    "LEFT_NOTICE",
    "NO_PLACE",
    "accuracy_words",
    "degrees",
    "joined_words",
    "left_words",
    "maps_link",
    "message_for",
    "notice_for",
]
