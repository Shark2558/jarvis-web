# src/jarvis/watch/words.py
"""Every sentence the watch and sleep tools say (docs/plans/r7-mobile.md D18): fixed templates
filled with numbers and JARVIS's own words only. Nothing diagnoses or advises; the numbers are
named as the watch's or the phone's own estimates (or the time he typed)."""

from __future__ import annotations

from datetime import datetime

from jarvis.watch.models import Stages
from jarvis.watch.sleep import FROM, Night, Week, hm
from jarvis.watch.store import WatchState

ESTIMATE: dict[str, str] = {
    "watch": "These are your watch's own estimates, Sir, never a diagnosis.",
    "phone": "These are your phone's own estimates, Sir, never a diagnosis.",
    "app": "These are that app's own estimates, Sir, never a diagnosis.",
    "typed": "That is the time you typed, Sir.",
}
WEEK_NOTE = "These are estimates, Sir, never a diagnosis."
NO_NIGHT = (
    "I have no sleep for last night yet, Sir. The JARVIS app on your phone sends it from Health "
    'Connect, or tell me, for example, "I slept 11:30 to 6".'
)
NO_WEEK = "I have no nights recorded in the last 7 days, Sir."
NEVER_SYNCED = (
    "Your phone hasn't synced yet, Sir: link the JARVIS app in Integrations → Phone app and "
    "open it once."
)
NOTHING_TODAY = "Nothing from your watch or phone for today yet, Sir."
SWITCHED_OFF = "Watch data is switched off on this server, Sir."


def stages_words(st: Stages) -> str:
    return (
        f"Stages: {hm(st.awake)} awake, {hm(st.light)} light, {hm(st.deep)} deep, {hm(st.rem)} REM."
    )


def last_night_words(night: Night | None) -> str:
    if night is None:
        return NO_NIGHT
    head = (
        f"Last night you slept {hm(night.minutes)}, {night.start} to {night.end}, "
        f"{FROM[night.source]}."
    )
    parts = [head]
    if night.stages is not None:
        parts.append(stages_words(night.stages))
    parts.append(ESTIMATE[night.source])
    return " ".join(parts)


def week_words(w: Week | None) -> str:
    if w is None:
        return NO_WEEK
    count = "1 night" if w.nights == 1 else f"{w.nights} nights"
    beds = (
        f"you went to bed at {w.bed_from}"
        if w.bed_from == w.bed_to
        else f"bedtimes ranged from {w.bed_from} to {w.bed_to}"
    )
    return (
        f"Over the last 7 nights you slept {hm(w.avg_minutes)} on average ({count} recorded); "
        f"{beds}. {WEEK_NOTE}"
    )


def synced_words(state: WatchState, local: datetime | None) -> str:
    if state.last_sync is None or local is None:
        return NEVER_SYNCED
    return f"Last synced at {local.strftime('%H:%M')} on {local.day} {local.strftime('%b')}."


def noted_words(night: Night) -> str:
    return (
        f"Noted, Sir: last night you slept {hm(night.minutes)}, {night.start} to {night.end} "
        f"({FROM['typed']})."
    )


__all__ = [
    "ESTIMATE",
    "NEVER_SYNCED",
    "NOTHING_TODAY",
    "NO_NIGHT",
    "NO_WEEK",
    "SWITCHED_OFF",
    "last_night_words",
    "noted_words",
    "stages_words",
    "synced_words",
    "week_words",
]
