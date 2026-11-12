# tests/test_r11_c_sim.py -- R11 Part C's exit check on fakes (plan "Tests and evals", nudges; D3,
# D21): 14 simulated days on the 5-minute clock with Scheduler jitter and a restart after every run
# that sent something. Every nudge goes out in the first run at or after its due time, none early,
# twice or missed; the caps hold (his own cap of 3 too); snooze and stop work by phrase and by tap
# ("don't remind me to stand up" sets no reminder); the missed walk is asked about once; the
# free-time pick fits the gap, avoids rain and skips what he did in the last 3 days. The control:
# with claims off, a restart sends twice and the same judge fails.
from __future__ import annotations

from collections.abc import Iterator

import pytest
from r11_fakes_c import judge, simulate

from jarvis.helpers.nudges import store as store_module


@pytest.fixture
def claims_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def always(self: object, uid: str, day: str, key: str) -> bool:
        return True

    async def never(self: object, uid: str, day: str, key: str) -> None:
        return None

    monkeypatch.setattr(store_module.NudgeStore, "claim", always)
    monkeypatch.setattr(store_module.NudgeStore, "release", never)
    yield


async def test_fourteen_days_every_nudge_once_on_time_and_inside_the_limits() -> None:
    sim = await simulate()
    fails = await judge(sim)
    assert fails == [], "\n".join(fails[:20])
    kinds = {kind for _, kind, _ in sim.texts}
    assert kinds == {
        "nudge_standup",
        "nudge_hydrate",
        "nudge_focus",
        "nudge_free_time",
        "nudge_activity",
    }
    asks = [t for _, kind, t in sim.texts if kind == "nudge_activity"]
    assert len(asks) == 7  # the seven days he didn't check in, once each


@pytest.mark.usefixtures("claims_off")
async def test_the_control_with_claims_off_a_restart_sends_twice_and_the_check_fails() -> None:
    fails = await judge(await simulate(days=2))
    assert any(f.startswith("sent twice") for f in fails), fails[:10]
