# src/jarvis/notify/ports.py
"""The notify ports (R3 D10; Layer 8 notifications). Deterministic, no model call anywhere.

- `Signal`: what happened, as the policy sees it: where it came from, the alert kind, an optional
  person reference (a face id now; a phone number or address in R12), whether the Faces registry
  marks that person VIP or a child, the camera (for storm control and held items) and optional
  words to scan for emergency terms (an R12 call transcript; never sent, never stored).
- `DEFAULT_URGENCY`: the level of every alert kind before any rule raises it. Recognition only
  ever raises a level (a VIP rings), never lowers one.
- `Decision`: ring | silent | hold | drop, the reason (a short word) and the level it used. "Feed
  only" is `drop` with reason `feed_only`: nothing is sent, the home feed still lists it.
- `Delivery`: what was done (the decision, Telegram sent or not, how many browsers got it, whether
  a photo went); `feed_decision` is the word the home feed stores.
- `NotifyPolicy.decide(signal, settings, now)`: pure; `settings` is D's notify settings model.
- `Notifier.notify(uid, signal, message, *, named_message=None, photo=None)`: `message` is a
  fixed-template text (<= 300 characters) that names nobody; `named_message` is the same text with
  a name from the consent registry, used only when the owner switched names in alerts on and the
  person is not a child; `photo` (D12) only reaches Telegram for a burglar alert he opted in to.
- `DirectNotifier`: straight to an `AlertSink` (B and C tests until D lands): rings (silent for
  info kinds), never names anyone, never forwards a photo.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from jarvis.alerts import AlertKind, AlertSink
from jarvis.home.ports import LABEL_ID

Urgency = Literal["urgent", "important", "info"]
SignalSource = Literal["home", "nudge", "call", "message", "system"]  # R4: vitals + self-health
Action = Literal["ring", "silent", "hold", "drop"]
FeedDecision = Literal["ring", "silent", "held", "dropped"]
MAX_PUSH_DEVICES = 5  # D11

DEFAULT_URGENCY: Mapping[str, Urgency] = MappingProxyType(
    {
        # urgent: rings through quiet hours. home_summary is the storm summary ("12 more
        # detections at the Gate") that follows urgent rings. A laptop that stopped answering
        # while armed, and an alarm that could not arm or lost its camera link, mean burglar
        # alerts can't arrive: never held through the night (integrated review H5).
        "home_intruder": "urgent",
        "home_hazard": "urgent",
        "home_summary": "urgent",
        "home_offline": "urgent",
        "home_arm_failed": "urgent",
        # important: held in quiet hours; rings unless "Only urgent things ring"
        "home_package": "important",
        "approval_waiting": "important",
        "vault_expiry": "important",
        "test": "important",  # D10 rule 1 rings a test whatever its level
        # info: silent or feed only
        "home_greeting": "info",
        "home_online": "info",
        "offline_on": "info",
        "offline_off": "info",
        "brief_ready": "info",
        # R4: a red vitals line and a self-health fault ring through quiet hours (never held, like
        # hazards); an amber warning and a recovery are info (silent / feed only).
        "vitals_critical": "urgent",
        "health_fault": "urgent",
        "vitals_warn": "info",
        "health_recovered": "info",
    }
)
_FEED: dict[str, FeedDecision] = {
    "ring": "ring",
    "silent": "silent",
    "hold": "held",
    "drop": "dropped",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Signal(_Frozen):
    source: SignalSource
    kind: AlertKind
    person_ref: str | None = Field(default=None, min_length=1, max_length=200)
    vip: StrictBool = False  # set only from faces.ports.Resolved.vip
    child: StrictBool = False  # set only from faces.ports.Resolved.child: never named
    camera: str | None = Field(default=None, pattern=LABEL_ID)
    text: str | None = Field(default=None, max_length=4000)


class Decision(_Frozen):
    action: Action
    reason: str = Field(min_length=1, max_length=40, pattern=r"^[a-z_]+$")
    urgency: Urgency


class Delivery(_Frozen):
    action: Action
    reason: str = Field(min_length=1, max_length=40)
    telegram: StrictBool = False
    push: int = Field(default=0, ge=0, le=MAX_PUSH_DEVICES)
    photo_sent: StrictBool = False

    @property
    def feed_decision(self) -> FeedDecision:
        return _FEED[self.action]


@runtime_checkable
class NotifyPolicy(Protocol):
    def decide(self, signal: Signal, settings: Any, now: datetime) -> Decision: ...


@runtime_checkable
class Notifier(Protocol):
    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery: ...


class DirectNotifier:
    """Every signal straight to one sink: no quiet hours, no storm control, no names, no photo."""

    def __init__(self, sink: AlertSink) -> None:
        self._sink = sink

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        silent = DEFAULT_URGENCY.get(signal.kind, "important") == "info"
        res = await self._sink.send(uid, message, kind=signal.kind, silent=silent)
        return Delivery(action="silent" if silent else "ring", reason="direct", telegram=res.sent)


__all__ = [
    "DEFAULT_URGENCY",
    "MAX_PUSH_DEVICES",
    "Action",
    "Decision",
    "Delivery",
    "DirectNotifier",
    "FeedDecision",
    "Notifier",
    "NotifyPolicy",
    "Signal",
    "SignalSource",
    "Urgency",
]
