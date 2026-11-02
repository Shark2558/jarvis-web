# tests/test_brief_todo_review.py — slice 10 C security-review fixes for the brief's To-do
# section: M4 (the AI consent must cover to-do titles), M5 (bounded paging, "at least"),
# L6 (a timeout of its own), L9 (no AI call with nothing to read).
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from brief_fakes import OWNER_UID, BriefGoogle, todo, tokens
from pydantic import SecretStr

from jarvis.brief import collect
from jarvis.brief.collect import Collector
from jarvis.brief.models import (
    AI_CONSENT_VERSION,
    BriefData,
    BriefSettings,
    SectionsStatus,
    SettingsPatch,
    TodoItem,
    TodoSection,
)
from jarvis.brief.render import render_text
from jarvis.brief.service import NOTE_NOTHING, BriefService, apply_patch, settings_view
from jarvis.brief.store import BriefStore
from jarvis.integrations.google import GoogleConnector
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.tasks_api import PAGES_PER_LIST

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2027, 1, 15)
NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
TODO_FENCE = "<<EXTERNAL CONTENT from the owner's to-do list"


async def _conn(fake: BriefGoogle, handler: object = None) -> GoogleConnector:
    store = MemoryTokenStore()
    await store.put(OWNER_UID, tokens(tasks=True))
    transport = httpx.MockTransport(handler or fake.handler)  # type: ignore[arg-type]
    return GoogleConnector(
        store,
        client_id="c",
        client_secret=SecretStr("s"),
        http=httpx.AsyncClient(transport=transport),
    )


def _due(n: int, day: str = "2027-01-14") -> list[dict[str, object]]:
    return [todo(f"t{i:04d}", f"Task {i}", day) for i in range(n)]


# ---- M5: bounded paging, and "at least" when the budget runs out -------------------------------


async def test_pages_are_followed_within_the_budget() -> None:
    fake = BriefGoogle(todo={"L1": _due(150)})
    data = (await Collector(await _conn(fake), None).collect(OWNER_UID, IST, DAY)).data
    assert data.todo is not None and data.todo.total == 150 and data.todo.complete is True
    pages = [r for r in fake.tasks_reads() if r.url.path.endswith("/tasks")]
    assert len(pages) == 2 and pages[1].url.params["pageToken"] == "100"


async def test_past_the_budget_the_brief_says_at_least() -> None:
    fake = BriefGoogle(todo={"L1": _due(100 * PAGES_PER_LIST + 50)})
    data = (await Collector(await _conn(fake), None).collect(OWNER_UID, IST, DAY)).data
    assert data.todo is not None and data.todo.complete is False
    assert data.todo.total == 100 * PAGES_PER_LIST
    pages = [r for r in fake.tasks_reads() if r.url.path.endswith("/tasks")]
    assert len(pages) == PAGES_PER_LIST  # never more than the budget
    text = render_text(data)
    assert f"TO-DO · at least {100 * PAGES_PER_LIST} due" in text
    assert "JARVIS read only part of your to-do list" in text


async def test_more_lists_than_jarvis_reads_is_not_called_nothing_due() -> None:
    lists = [{"id": f"L{i}", "title": f"List {i}"} for i in range(12)]
    fake = BriefGoogle(tasklists=lists, todo={})
    data = (await Collector(await _conn(fake), None).collect(OWNER_UID, IST, DAY)).data
    assert data.todo is not None and data.todo.total == 0 and data.todo.complete is False
    text = render_text(data)
    assert "Nothing due today or overdue." not in text
    assert "JARVIS read only part of your to-do list" in text


# ---- L6: the section has a timeout of its own ------------------------------------------------


async def test_a_slow_tasks_service_times_out_and_the_rest_of_the_brief_is_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collect, "TODO_TIMEOUT_S", 0.2)
    fake = BriefGoogle(todo={"L1": _due(3)})

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/tasks/"):
            await asyncio.sleep(5)
        return await fake.handler(request)

    started = asyncio.get_running_loop().time()
    data = (await Collector(await _conn(fake, slow), None).collect(OWNER_UID, IST, DAY)).data
    assert asyncio.get_running_loop().time() - started < 2
    assert data.sections_status.todo == "unavailable" and data.sections_status.calendar == "ok"


# ---- M4: the AI consent must cover to-do titles ----------------------------------------------


def test_switching_the_ai_on_now_records_the_consent_that_names_to_dos() -> None:
    on = apply_patch(
        BriefSettings(),
        SettingsPatch(ai_summary=True, confirm_spend=True),
        insert_ok=False,
        now=NOW,
    )
    assert on.ai_consent == AI_CONSENT_VERSION and settings_view(on).ai_todo_consent is True


def test_an_earlier_consent_does_not_cover_to_dos_until_it_is_given_again() -> None:
    old = BriefSettings.model_validate({"ai_summary": True})  # stored before slice 10
    assert old.ai_consent < AI_CONSENT_VERSION and settings_view(old).ai_todo_consent is False
    again = apply_patch(
        old, SettingsPatch(ai_summary=True, confirm_spend=True), insert_ok=False, now=NOW
    )
    assert settings_view(again).ai_todo_consent is True
    off = apply_patch(again, SettingsPatch(ai_summary=False), insert_ok=False, now=NOW)
    assert settings_view(off).ai_todo_consent is False  # nothing is consented while off


async def _svc(fake: BriefGoogle, settings: BriefSettings) -> tuple[BriefService, MockProvider]:
    provider = MockProvider()
    store = BriefStore(MemoryDocs())
    await store.update_settings(OWNER_UID, lambda _: settings)
    svc = BriefService(
        store=store,
        google=await _conn(fake),
        brains=BrainRegistry(
            [BrainSpec(id="b", label="B", provider=provider, tiers=TIERS)], default_id="b"
        ),
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
    )
    return svc, provider


def _sent(provider: MockProvider) -> str:
    return provider.calls[0].messages[0].text() if provider.calls else ""


async def test_titles_reach_the_ai_only_under_the_consent_that_names_them() -> None:
    fake = BriefGoogle(todo={"L1": [todo("a", "Renew passport", "2027-01-14")]})
    old, provider = await _svc(fake, BriefSettings.model_validate({"ai_summary": True}))
    provider.script("Renew the passport.")
    view = await old.generate(OWNER_UID, trigger="manual", force=False)
    assert view.brief is not None and "Renew passport" in view.brief.text  # the section shows
    assert provider.calls and TODO_FENCE not in _sent(provider)
    assert "Renew passport" not in _sent(provider)
    assert view.settings.ai_todo_consent is False
    new, provider2 = await _svc(fake, BriefSettings(ai_summary=True, ai_consent=AI_CONSENT_VERSION))
    provider2.script("Renew the passport.")
    await new.generate(OWNER_UID, trigger="manual", force=False)
    assert TODO_FENCE in _sent(provider2) and "Renew passport" in _sent(provider2)


# ---- L9: no AI call when there is nothing to read --------------------------------------------


@pytest.mark.parametrize(
    ("items", "consent", "called"),
    [
        ([], AI_CONSENT_VERSION, False),  # to-do read fine but empty
        ([todo("a", "Renew passport", "2027-01-14")], 1, False),  # titles not consented
        ([todo("a", "Renew passport", "2027-01-14")], AI_CONSENT_VERSION, True),
    ],
)
async def test_with_calendar_and_inbox_down_the_ai_runs_only_on_consented_to_dos(
    items: list[dict[str, object]], consent: int, called: bool
) -> None:
    fake = BriefGoogle(todo={"L1": items}, fail={"events": 500, "list": 500})
    svc, provider = await _svc(fake, BriefSettings(ai_summary=True, ai_consent=consent))
    provider.script("Renew the passport.")
    view = await svc.generate(OWNER_UID, trigger="manual", force=False)
    assert view.brief is not None
    assert bool(provider.calls) is called
    if not called:
        assert view.brief.ai_note == NOTE_NOTHING


def test_an_incomplete_read_is_marked_in_the_text_even_with_items() -> None:
    item = TodoItem(title="Pay bill", due="2027-01-14", overdue=True)
    data = BriefData(
        date="2027-01-15",
        tz="Asia/Kolkata",
        todo=TodoSection(total=1, overdue=1, items=(item,), complete=False),
        sections_status=SectionsStatus(),
    )
    text = render_text(data)
    assert "TO-DO · at least 1 due (1 overdue)" in text and "“Pay bill”" in text
