# tests/test_r7_i1_brief.py -- R7 I1 (docs/plans/r7-mobile.md D18, acceptance 8; INTEGRATION-D
# "Needs I1" 2): the brief's sleep line. `BriefService` fills the pinned `BriefData.sleep` from
# Part D's `services["brief"].sleep(uid, tz, day)` (through `r7_wiring.mobile_sleep(app)`); the
# e-mailed copy (`render_text`), the AI summary's input and Telegram never carry it; a failing or
# slow source never fails the brief; the console draws one fixed line (browser test elsewhere).
from __future__ import annotations

import asyncio
import datetime as dt
import json
from datetime import date
from typing import Any

import pytest
from brief_fakes import OWNER_UID, BriefGoogle, connector, timed

import jarvis.brief.service as brief_service
from jarvis.brief.models import SleepLine
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

NOW = dt.datetime(2026, 11, 13, 1, 30, tzinfo=dt.UTC)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
LINE = SleepLine(minutes=400, start="23:50", end="06:30", source="watch")


class Source:
    def __init__(self, line: Any = LINE, *, fail: bool = False, slow: bool = False) -> None:
        self.line, self.fail, self.slow = line, fail, slow
        self.asked: list[tuple[str, str, date]] = []

    async def sleep(self, uid: str, tz: Any, day: date) -> Any:
        self.asked.append((uid, str(tz), day))
        if self.fail:
            raise RuntimeError("watch store down")
        if self.slow:
            await asyncio.sleep(60)
        return self.line


async def service(sleep: Any) -> BriefService:
    fake = BriefGoogle(events=[timed("e1", "Standup", "2026-11-13T09:30", "2026-11-13T10:00")])
    spec = BrainSpec(
        id="b", label="B", provider=MockProvider(), tiers=TIERS, trains_on_content=False
    )
    return BriefService(
        store=BriefStore(MemoryDocs()),
        google=await connector(fake),
        brains=BrainRegistry([spec], default_id="b"),
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        sleep=sleep,
    )


async def test_the_brief_carries_last_nights_line_and_the_emailed_copy_does_not() -> None:
    src = Source()
    today = await (await service(src)).generate(OWNER_UID, trigger="manual", force=True)
    rec = today.brief
    assert rec is not None and rec.status == "ready" and rec.data is not None
    assert rec.data.sleep == LINE
    assert src.asked == [(OWNER_UID, "Asia/Kolkata", date(2026, 11, 13))]
    assert "sleep" not in rec.text.lower() and "23:50" not in rec.text  # the e-mailed copy
    assert "23:50" not in build_input(rec.data, (), include_todo=True)  # never in the AI input


@pytest.mark.parametrize("src", [Source(None), Source(fail=True), Source("6 h, from the watch")])
async def test_no_night_a_failing_source_or_a_wrong_shape_leaves_the_line_out(src: Any) -> None:
    today = await (await service(src)).generate(OWNER_UID, trigger="manual", force=True)
    rec = today.brief
    assert rec is not None and rec.status == "ready" and rec.data is not None
    assert rec.data.sleep is None


async def test_a_slow_source_never_holds_the_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brief_service, "EXTRA_TIMEOUT_S", 0.05)
    today = await (await service(Source(slow=True))).generate(
        OWNER_UID, trigger="manual", force=True
    )
    assert today.brief is not None and today.brief.status == "ready"
    assert today.brief.data is not None and today.brief.data.sleep is None


async def test_without_a_source_the_brief_is_as_before() -> None:
    today = await (await service(None)).generate(OWNER_UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.sleep is None


# ---- through the real wiring: the app builds the brief with Part D's night -------------------
async def test_the_real_app_puts_part_ds_night_into_the_brief(settings: Any) -> None:
    import base64

    from pydantic import SecretStr

    from jarvis.api import create_app, r7_wiring
    from jarvis.memory.inmemory import InMemorySessionStore

    key = SecretStr(base64.urlsafe_b64encode(bytes(range(1, 33))).decode())
    s = settings.model_copy(update={"token_key": key, "user_timezone": "Asia/Kolkata"})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        body = app.state.r7_parts["body"]
        uid = app.state.brief.owners[0]
        night = {
            "start": "2026-11-12T23:50:00+05:30",
            "end": "2026-11-13T06:30:00+05:30",
            "writer": "com.example.makerhealth",  # another health app: named as itself
            "stages": None,
        }
        days = [{"date": "2026-11-13", "steps": None, "heart": None, "sleep": [night]}]
        await body.services["watch"].intake(uid, json.dumps({"v": 1, "days": days}).encode())
        wired = app.state.brief._sleep  # the source the app built the brief with
        assert isinstance(wired, r7_wiring.MobileSleep)
        line = await wired.sleep(uid, dt.UTC, date(2026, 11, 13))
        assert line == SleepLine(minutes=400, start="23:50", end="06:30", source="app")
        assert await wired.sleep(uid, dt.UTC, date(2026, 11, 20)) is None  # no night that day
