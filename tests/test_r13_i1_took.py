# tests/test_r13_i1_took.py -- R13 I1 (INTEGRATION-B 6.9): ONE rule for "the owner has this alert,
# or chose not to": a channel took it, it waits in the held summary, or his own setting dropped
# it. It lives in `notify/ports.py`; Self-health's `reached`, Home's idle `took` and the laundry
# job all agree with it.
from __future__ import annotations

import pytest

from jarvis.home.watchdog import took as idle_took
from jarvis.notify import ports
from jarvis.notify.ports import Delivery
from jarvis.selfwatch import texts

CASES = [
    (Delivery(action="ring", reason="sent", telegram=True), True),
    (Delivery(action="ring", reason="sent", push=2), True),
    (Delivery(action="hold", reason="quiet_hours"), True),
    (Delivery(action="drop", reason="switched_off"), True),
    (Delivery(action="drop", reason="feed_only"), True),
    (Delivery(action="drop", reason="storm"), False),
    (Delivery(action="ring", reason="no_channel"), False),
]


@pytest.mark.parametrize(("delivery", "expected"), CASES)
def test_one_rule_for_every_caller(delivery: Delivery, expected: bool) -> None:
    assert ports.took(delivery) is expected
    assert texts.reached(delivery) is expected
    assert idle_took(delivery, idle=True) is expected


def test_a_non_delivery_is_never_taken_and_the_armed_form_is_unchanged() -> None:
    assert ports.took(None) is False and ports.took("sent") is False
    held = Delivery(action="hold", reason="quiet_hours")
    assert idle_took(held, idle=False) is False  # integrated review H5: armed, unchanged
    assert idle_took(Delivery(action="ring", reason="sent", push=1), idle=False) is True


def test_the_laundry_job_uses_the_shared_rule() -> None:
    from jarvis.wardrobe.laundry import jobs

    assert jobs.took is ports.took
    assert texts.SETTLED == ports.OWNER_SETTLED
