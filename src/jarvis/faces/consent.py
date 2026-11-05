# src/jarvis/faces/consent.py
"""Consent for recognising a face (R3 D13). The statement is fixed text with a version (`fc1`);
an adult's is the person's own agreement, a child's a parent's or guardian's. Nobody is enrolled
without it. A consent older than 365 days shows a yearly question (it does not stop anything)."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.faces.models import CONSENT_VERSION, Person

YEARLY = timedelta(days=365)
_ADULT = (
    "{name} agreed that the camera at my home may recognise their face and greet them by name; "
    "their face pictures stay on my laptop; they can ask me to delete them at any time"
)
_CHILD = (
    "{name} is under 18 and I am their parent or legal guardian (or have their parent's agreement)"
)
STATEMENTS = {"fc1": (_ADULT, _CHILD)}


class ConsentRejected(ValueError):
    """Consent is missing or the wrong kind (`code` is stable; the HTTP status is 422)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def statement(version: str, child: bool, name: str = "<name>") -> str:
    found = STATEMENTS.get(version)
    if found is None:
        raise ConsentRejected("consent_missing", "That consent statement is out of date.")
    return found[1 if child else 0].format(name=name)


def check(*, child: bool, given_by: str, version: str, confirm: object) -> None:
    """Raises `ConsentRejected` unless the right statement was ticked by the right person."""
    if confirm is not True or version not in STATEMENTS:
        raise ConsentRejected(
            "consent_missing", "Tick the consent statement first: JARVIS names nobody without it."
        )
    if child and given_by != "parent_guardian":
        raise ConsentRejected(
            "child_needs_guardian", "A child needs a parent's or legal guardian's consent."
        )
    if not child and given_by != "self":
        raise ConsentRejected(
            "consent_missing",
            "An adult has to agree for themselves; a guardian can't agree for them.",
        )


def renewal_due(person: Person, now: datetime) -> bool:
    return now - datetime.fromisoformat(person.consent_at) > YEARLY


__all__ = [
    "CONSENT_VERSION",
    "STATEMENTS",
    "YEARLY",
    "ConsentRejected",
    "check",
    "renewal_due",
    "statement",
]
