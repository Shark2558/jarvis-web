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


async def test_read_only_and_reversible_pass_without_confirmation() -> None:
    gate = ConfirmationGate()
    for risk in (ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE):
        await gate.check(PendingAction(tool="cal.list", arguments={}, risk=risk, summary="list"))
    assert (await gate.pending()) == []


async def test_irreversible_requires_then_accepts_confirmation() -> None:
    gate = ConfirmationGate()
    action = _send_email()
    with pytest.raises(ConfirmationRequired) as ei:
        await gate.check(action)
    assert ei.value.action.id == action.id
    assert [p.id for p in (await gate.pending())] == [action.id]

    await gate.check(action, confirmation_id=action.id)  # confirmed → no raise
    assert (await gate.pending()) == []
    # a confirmation token is single-use
    with pytest.raises(ConfirmationRequired):
        await gate.check(action, confirmation_id=action.id)


async def test_argument_drift_invalidates_confirmation() -> None:
    gate = ConfirmationGate()
    proposed = _send_email(body="draft 1")
    with pytest.raises(ConfirmationRequired):
        await gate.check(proposed)
    executed = PendingAction(
        tool=proposed.tool,
        arguments={**proposed.arguments, "body": "draft 2"},
        risk=ActionRisk.IRREVERSIBLE,
        summary=proposed.summary,
    )
    with pytest.raises(ConfirmationRequired):
        await gate.check(executed, confirmation_id=proposed.id)


async def test_expired_confirmation_rejected() -> None:
    gate = ConfirmationGate()
    action = _send_email()
    with pytest.raises(ConfirmationRequired):
        await gate.check(action)
    action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await gate.store.put(action)
    with pytest.raises(ConfirmationRequired):
        await gate.check(action, confirmation_id=action.id)


async def test_bogus_confirmation_keeps_action_pending_and_valid_tokens_intact() -> None:
    # HIGH-1 regression: a wrong token must not orphan the action nor consume another token
    gate = ConfirmationGate()
    a = _send_email(body="a")
    b = PendingAction(
        tool="pay_bill", arguments={"amount": 1}, risk=ActionRisk.IRREVERSIBLE, summary="pay"
    )
    for x in (a, b):
        with pytest.raises(ConfirmationRequired):
            await gate.check(x)
    with pytest.raises(ConfirmationRequired) as ei:
        await gate.check(a, confirmation_id="bogus")
    assert ei.value.action.id in {p.id for p in (await gate.pending())}  # still approvable
    with pytest.raises(ConfirmationRequired):
        await gate.check(a, confirmation_id=b.id)  # token for another tool
    assert {p.id for p in (await gate.pending())} == {a.id, b.id}  # b's token not consumed
    await gate.check(b, confirmation_id=b.id)  # and still works
