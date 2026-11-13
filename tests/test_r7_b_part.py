# tests/test_r7_b_part.py -- R7 Part B's plug-in (docs/plans/r7-mobile.md D12, D25; I0 seams 8,
# 20): `build(ctx)` gives the kept-results store, the brain's one read `vision_results` (R1, the
# "Camera results" row; the text a camera read reaches the brain fenced as other people's words),
# the 90-day sweep on the morning tick, and two privacy rows. Off in settings, or with no token key,
# it says so and keeps nothing (looking on the device still works: frames never come here).
from __future__ import annotations

import base64
from typing import Any

from pydantic import SecretStr
from r7_fakes_b import (
    LABEL_TEXT,
    QR_TEXT,
    ROOT_KEY,
    UID,
    Clock,
    code_result,
    objects_result,
    text_result,
)

from jarvis.api.r7_wiring import check_part
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.mobile.ports import MobileContext, MobilePart, tool_allowed
from jarvis.permissions.groups import get_group
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.vision import part as vision_part
from jarvis.vision.store import VisionStore

SCOPE = f"{UID}:sess_b"
KEY = SecretStr(base64.b64encode(ROOT_KEY).decode())  # made-up bytes, never a real key


def _ctx(settings: Settings, *, key: bool = True, docs: MemoryDocs | None = None,
         **over: Any) -> MobileContext:  # fmt: skip
    s = settings.model_copy(update={"token_key": KEY if key else None, **over})
    state = {"vision_now": Clock()}
    return MobileContext(s=s, docs=docs if docs is not None else MemoryDocs(), audit=None,
                         state=state.get)  # fmt: skip


def _gateway(part: MobilePart) -> Gateway:
    reg = ToolRegistry()
    for t in part.tools:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


def _store(part: MobilePart) -> VisionStore:
    store = part.services["vision"].store
    assert isinstance(store, VisionStore)
    return store


def test_the_part_keeps_its_contract_and_says_it_is_ready(settings: Settings) -> None:
    part = check_part("vision", vision_part.build(_ctx(settings)))
    assert part.ready == "ready"
    assert [t.name for t in part.tools] == ["vision_results"]
    assert all(tool_allowed("vision", t.name) for t in part.tools)
    tool = part.tools[0]
    assert tool.risk is ActionRisk.READ_ONLY and tool.activity_words and not tool.trusted_output
    assert [j.name for j in part.daily_jobs] == ["vision_sweep"] and not part.clock_jobs
    assert [p.id for p in part.privacy] == ["vision_results", "vision_device"]
    group = get_group("vision")
    assert group is not None and group.section == "Camera results"


def test_off_in_settings_it_offers_nothing(settings: Settings) -> None:
    part = check_part("vision", vision_part.build(_ctx(settings, vision_enabled=False)))
    assert part.ready.startswith("off") and part.tools == () and part.daily_jobs == ()
    assert part.services.get("vision") is None and part.privacy == ()


def test_without_a_token_key_it_says_nothing_can_be_kept(settings: Settings) -> None:
    part = check_part("vision", vision_part.build(_ctx(settings, key=False)))
    assert "token key" in part.ready and part.tools == () and part.daily_jobs == ()
    assert _store(part).sealed is False
    assert [p.id for p in part.privacy] == ["vision_results", "vision_device"]


async def test_the_tool_lists_kept_results_and_fences_what_was_read(settings: Settings) -> None:
    part = vision_part.build(_ctx(settings))
    store = _store(part)
    await store.keep(UID, text_result())
    await store.keep(UID, code_result())
    await store.keep(UID, objects_result())
    out = await _gateway(part).execute(
        ToolCall(id="t", name="vision_results", arguments={"days": 7}), scope=SCOPE
    )
    assert out.outcome is GatewayOutcome.EXECUTED, out.error
    got = out.result
    assert (
        got["count"] == 3 and got["message"] == "You kept 3 camera results in the last 7 days, Sir."
    )
    by_task = {r["task"]: r for r in got["results"]}
    assert FENCE_PREFIX in by_task["text"]["text"] and LABEL_TEXT in by_task["text"]["text"]
    assert FENCE_PREFIX in by_task["code"]["codes"][0]["value"]
    assert QR_TEXT in by_task["code"]["codes"][0]["value"]
    assert by_task["objects"]["objects"] == [{"label": "cup", "score": 0.82}]
    only = await _gateway(part).execute(
        ToolCall(id="t2", name="vision_results", arguments={"task": "code"}), scope=SCOPE
    )
    assert [r["task"] for r in only.result["results"]] == ["code"]


async def test_the_tool_says_plainly_when_nothing_was_kept(settings: Settings) -> None:
    part = vision_part.build(_ctx(settings))
    out = await _gateway(part).execute(
        ToolCall(id="t", name="vision_results", arguments={}), scope=SCOPE
    )
    assert out.result == {
        "count": 0,
        "results": [],
        "message": "You haven't kept any camera results in the last 7 days, Sir.",
    }


async def test_the_tool_refuses_days_outside_the_keep(settings: Settings) -> None:
    gw = _gateway(vision_part.build(_ctx(settings)))
    for bad in ({"days": 0}, {"days": 91}, {"days": "lots"}, {"task": "faces"}):
        out = await gw.execute(ToolCall(id="t", name="vision_results", arguments=bad), scope=SCOPE)
        assert out.outcome is GatewayOutcome.ERROR, bad


async def test_the_sweep_runs_for_every_owner(settings: Settings) -> None:
    docs = MemoryDocs()
    ctx = _ctx(settings, docs=docs)
    part = vision_part.build(ctx)
    store = _store(part)
    await store.keep(UID, text_result())
    clock = ctx.state("vision_now")
    clock.at = clock.at.replace(year=2027, month=3)  # well past 90 days
    counts = await part.daily_jobs[0].run([UID, "owner-c"])
    assert counts == {"days_removed": 1, "owners": 2}


async def test_the_privacy_rows_count_export_and_delete_with_a_passkey(settings: Settings) -> None:
    part = vision_part.build(_ctx(settings))
    store = _store(part)
    await store.keep(UID, text_result())
    results, device = part.privacy
    view = await results.describe(UID)
    assert view.count == 1 and view.delete == "passkey" and view.encrypted_by_jarvis
    assert view.retention == "90 days" and "Never" in view.note
    exported = await results.export(UID)
    assert exported is not None and exported["results"][0]["data"]["text"] == LABEL_TEXT
    assert await results.delete(UID) == 1 and (await results.describe(UID)).count == 0
    dev = await device.describe(UID)
    assert dev.count is None and dev.delete == "none" and "this browser" in dev.where.lower()


def test_the_keyring_has_the_vision_purpose() -> None:
    assert Keyring(bytes(range(32))).cipher("vision") is not None
