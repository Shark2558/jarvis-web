# tests/test_guardrails.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.core.guardrails import (
    ActionRisk,
    ConfirmationGate,
    ConfirmationRequired,
    PendingAction,
)


def _send_email(**kw: object) -> PendingAction:
    return PendingAction(
        tool="email.send",
        arguments={"to": "a@b.com", "subject": "hi", **kw},
        risk=ActionRisk.IRREVERSIBLE,
        summary="Send an email to a@b.com",
    )


def test_read_only_and_reversible_pass_without_confirmation() -> None:
    gate = ConfirmationGate()
    for risk in (ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE):
        gate.check(PendingAction(tool="cal.list", arguments={}, risk=risk, summary="list"))
    assert gate.pending() == []


def test_irreversible_requires_then_accepts_confirmation() -> None:
    gate = ConfirmationGate()
    action = _send_email()
    with pytest.raises(ConfirmationRequired) as ei:
        gate.check(action)
    assert ei.value.action.id == action.id
    assert [p.id for p in gate.pending()] == [action.id]

    gate.check(action, confirmation_id=action.id)  # confirmed → no raise
    assert gate.pending() == []
    # a confirmation token is single-use
    with pytest.raises(ConfirmationRequired):
        gate.check(action, confirmation_id=action.id)


def test_argument_drift_invalidates_confirmation() -> None:
    gate = ConfirmationGate()
    proposed = _send_email(body="draft 1")
    with pytest.raises(ConfirmationRequired):
        gate.check(proposed)
    executed = PendingAction(
        tool=proposed.tool,
        arguments={**proposed.arguments, "body": "draft 2"},
        risk=ActionRisk.IRREVERSIBLE,
        summary=proposed.summary,
    )
    with pytest.raises(ConfirmationRequired):
        gate.check(executed, confirmation_id=proposed.id)


def test_expired_confirmation_rejected() -> None:
    gate = ConfirmationGate()
    action = _send_email()
    with pytest.raises(ConfirmationRequired):
        gate.check(action)
    action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    gate._pending[action.id] = action
    with pytest.raises(ConfirmationRequired):
        gate.check(action, confirmation_id=action.id)
