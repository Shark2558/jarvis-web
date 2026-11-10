# tests/test_r51_int_e2e_concerns.py -- R5.1 V2 (orchestrator's look): amber / red Vitals items
# reach `briefing.concerns` and the spoken briefing through the REAL wiring (create_app ->
# LiveVitals -> VitalsService -> the board -> HealthService), not just in the briefing's unit tests.
# A GitHub token expiring in 6 days and an allowance at 91 percent must both be there.
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from r3_app import H, r3_app

DAY_S = 86_400.0


async def _wire_a_expiring_token(w: Any) -> None:
    gh = w.state.github

    async def status(uid: str) -> dict[str, Any]:
        return {"connected": True}

    async def token_meta(uid: str) -> Any:
        return SimpleNamespace(
            expires_at=time.time() + 6 * DAY_S,
            rate_limit=None,
            rate_used=None,
            rate_reset=None,
            rejected_at=None,
            expiry_unreadable=False,
        )

    gh.status, gh.token_meta = status, token_meta


async def _track_a_hot_allowance(w: Any) -> None:
    r = await w.client.put(
        "/v1/vitals/keys",
        json={
            "id": "minutes",
            "label": "Voice minutes",
            "kind": "allowance",
            "limit": 100,
            "used": 91,
            "unit": "min",
        },  # fmt: skip
        headers=H,
    )
    assert r.status_code == 200, r.text


def _keys(briefing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in briefing["concerns"]}


async def test_amber_vitals_items_reach_the_concerns_and_the_spoken_briefing() -> None:
    async with r3_app() as w:
        await _wire_a_expiring_token(w)
        await _track_a_hot_allowance(w)

        board = (await w.client.get("/v1/vitals", headers=H)).json()
        by_id = {i["id"]: i for i in board["items"]}
        assert by_id["github_token"]["status"] == "amber"  # the board itself says Watch
        assert by_id["minutes"]["status"] == "amber"

        run = (await w.client.post("/v1/health/run", json={"force": True}, headers=H)).json()
        brief = run["briefing"]
        concerns = _keys(brief)
        assert concerns["vitals.github_token"]["severity"] == "amber"
        assert concerns["vitals.minutes"]["severity"] == "amber"
        assert "GitHub token" in brief["spoken"] and "Voice minutes" in brief["spoken"]
        assert "91 percent" in brief["spoken"]
        assert brief["spoken"].endswith("Shall I set a reminder to fix this?")


async def test_the_streamed_check_and_a_plain_get_carry_the_same_concerns() -> None:
    async with r3_app() as w:
        await _wire_a_expiring_token(w)
        await _track_a_hot_allowance(w)

        stream = await w.client.post("/v1/health/run/stream", json={"force": True}, headers=H)
        events = [json.loads(line) for line in stream.text.splitlines() if line]
        done = events[-1]
        assert done["type"] == "done"
        assert {"vitals.github_token", "vitals.minutes"} <= set(_keys(done["briefing"]))

        got = (await w.client.get("/v1/health", headers=H)).json()
        assert {"vitals.github_token", "vitals.minutes"} <= set(_keys(got["briefing"]))


async def test_a_red_vitals_item_is_a_red_concern_listed_before_the_amber_ones() -> None:
    async with r3_app() as w:
        await _wire_a_expiring_token(w)
        r = await w.client.put(
            "/v1/vitals/keys",
            json={"id": "brave", "label": "Brave key", "kind": "key", "expires_at": "2020-01-01"},
            headers=H,
        )
        assert r.status_code == 200, r.text
        brief = (await w.client.post("/v1/health/run", json={"force": True}, headers=H)).json()[
            "briefing"
        ]
        order = [c["key"] for c in brief["concerns"] if c["key"].startswith("vitals.")]
        assert _keys(brief)["vitals.brave"]["severity"] == "red"
        assert order.index("vitals.brave") < order.index("vitals.github_token")
