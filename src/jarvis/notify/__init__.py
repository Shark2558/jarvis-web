# src/jarvis/notify/__init__.py
"""One alert policy for home alerts, nudges and (R12) calls (R3 D10; Layer 8, Layer 3 rules).

`ports` holds the shared shapes and protocols (R3 I0); the policy, quiet hours, storm control,
held alerts and the policy-aware `AlertSink` are R3 D's.
"""

from jarvis.notify.ports import (
    DEFAULT_URGENCY,
    Action,
    Decision,
    Delivery,
    DirectNotifier,
    Notifier,
    NotifyPolicy,
    Signal,
    SignalSource,
    Urgency,
)

__all__ = [
    "DEFAULT_URGENCY",
    "Action",
    "Decision",
    "Delivery",
    "DirectNotifier",
    "Notifier",
    "NotifyPolicy",
    "Signal",
    "SignalSource",
    "Urgency",
]
