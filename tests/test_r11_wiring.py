# tests/test_r11_wiring.py -- R11 I0 seams on the app and the console (docs/plans/
# r11-free-helpers.md "Seams the I0 adds" 7-10; I1): `wire_r11` builds the gate and the four
# built parts, a part's contract is checked and a failing part leaves the rest running, its tools go
# through the gateway and the owner's rows, the two composites ride the tick (and the 5-minute
# watchdog, which with Home off runs only the helpers' clock), the privacy row, the brief's source,
# the /v1/helpers routes, the app.py slots and size guard, and the Helpers panel's frame.
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import jarvis.api.r11_wiring as r11
from jarvis.api import create_app, tick_wiring
from jarvis.api.console import APP_ASSETS
from jarvis.api.r7_wiring import mobile_clock_jobs, mobile_daily_jobs
from jarvis.api.r11_1_wiring import fix_clock_jobs
from jarvis.api.scheduler_auth import WATCHDOG_PATH, require_scheduler
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.clock import Composite
from jarvis.helpers.kinds import CLOCK_JOBS, PARTS
from jarvis.helpers.ports import HelperContext, HelperPart
from jarvis.llm.base import ToolCall
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools.base import Tool
from jarvis.tools.gateway import GatewayOutcome

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "jarvis" / "api"
STATIC = API / "static"
CSRF = {"X-Requested-With": "JARVIS"}
PART_MODULES = [f"console-helpers-{p}.js" for p in PARTS]


@dataclass
class App:
    app: FastAPI
    client: AsyncClient

    @property
    def state(self) -> Any:
        return self.app.state


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[App]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    app.dependency_overrides[require_scheduler] = lambda: None  # the Scheduler's token, faked
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield App(app, c)


# ---- wire_r11 -----------------------------------------------------------------------------------
async def test_the_helpers_start_with_four_empty_parts_and_both_composites(
    settings: Settings,
) -> None:
    async with running(settings) as a:
        st = a.state
        assert list(st.r11_parts) == list(PARTS)
        # I1: all four parts are built (no stub, no failed setup) and each is contract-clean
        readies = {p.ready for p in st.r11_parts.values()}
        assert not readies & {"not built yet", r11.SETUP_FAILED}, readies
        for name, part in st.r11_parts.items():
            assert r11.check_part(name, part) is part
            assert part.tools and part.privacy and part.phrases, name
        assert st.helpers_sender is not None and st.helpers_off is None
        assert isinstance(st.helpers_clock, Composite)
        jobs = st.helpers_clock.job_names
        fixes = {j.name for j in fix_clock_jobs(a)}  # R11.1: the parts' jobs ride the same clock
        mobile = {j.name for j in mobile_clock_jobs(a)}  # R7: Part D's watch_stale ...
        assert mobile == {"watch_stale"} and not mobile & set(jobs)  # ... on R7's own tick job
        own = set(jobs) - fixes
        assert sorted(own) == sorted(j for p in PARTS for j in CLOCK_JOBS[p]), jobs
        assert fixes == {"series_checkin", "photos_import", "face_groups_poll"}  # R11.1 A, C
        assert fixes <= set(jobs)
        r7_daily = tuple(j.name for j in mobile_daily_jobs(a))  # R7: the parts' sweeps ...
        assert "body_sweep" in r7_daily
        assert st.helpers_daily.job_names == ("breach_watch", "helpers_sweep")  # ... not here
        names = [j.name for j in st.tick_jobs]
        # R11's two composites, then R7's own two (never inside the helpers': code M5)
        assert names[-4:] == ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]
        assert st.brief._helpers is not None  # noqa: SLF001 - the brief's Helpers source
        assert "helpers_nudge" in st.privacy.registry.ids()


async def test_switched_off_the_helpers_leave_nothing_behind(settings: Settings) -> None:
    async with running(settings.model_copy(update={"helpers_enabled": False})) as a:
        st = a.state
        assert st.r11_parts == {} and st.helpers_sender is None and st.helpers_clock is None
        assert st.helpers_off == "switched_off" and st.brief._helpers is None  # noqa: SLF001
        assert not {"helpers_clock", "helpers_daily"} & {j.name for j in st.tick_jobs}
        got = (await a.client.get("/v1/helpers")).json()
        assert got == {"enabled": False, "off": "switched_off"}
        r = await a.client.post("/v1/helpers/gate/all/stop", headers=CSRF)
        assert r.status_code == 404 and r.json()["error"] == "helpers_off"


def _tool(name: str, risk: ActionRisk) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {"spoken": f"{name} ran"}

    return Tool(name, f"R11 test tool {name}", {"type": "object", "properties": {}}, risk, run)


class _Job:
    budget_s = 5.0

    def __init__(self, name: str) -> None:
        self.name = name
        self.seen: list[Sequence[str]] = []

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.seen.append(tuple(owners))
        return {"done": 1}


def test_a_part_may_use_only_its_own_names() -> None:
    ok = HelperPart(name="today", tools=(_tool("bill_list", ActionRisk.READ_ONLY),))
    assert r11.check_part("today", ok) is ok
    bad: list[tuple[Any, object]] = [
        ("today", HelperPart(name="house")),  # another part's name
        ("today", HelperPart(name="today", tools=(_tool("chore_done", ActionRisk.REVERSIBLE),))),
        ("today", HelperPart(name="today", clock_jobs=(_Job("nudges"),))),
        ("kitchen", HelperPart(name="kitchen", daily_jobs=(_Job("breach_watch"),))),
        ("today", "not a part"),
    ]
    for name, part in bad:
        with pytest.raises(ValueError):
            r11.check_part(name, part)


async def test_a_failing_part_is_left_empty_and_the_others_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _Job("bills_due")

    def today(ctx: HelperContext) -> HelperPart:
        return HelperPart(
            name="today",
            tools=(
                _tool("bill_list", ActionRisk.READ_ONLY),
                _tool("bill_pay_prepare", ActionRisk.IRREVERSIBLE),
            ),
            clock_jobs=(job,),
            ready="ok",
        )

    def house(ctx: HelperContext) -> HelperPart:
        raise RuntimeError("Part B is broken")

    stubs = {p: (lambda ctx, p=p: HelperPart(name=p)) for p in PARTS}  # the parts not under test
    builders = {**stubs, "today": today, "house": house}
    monkeypatch.setattr(r11, "BUILDERS", builders)
    async with running(settings) as a:
        st = a.state
        assert st.r11_parts["today"].ready == "ok" and st.r11_parts["house"].ready == "setup failed"
        assert st.r11_parts["nudges"].ready == "not built yet"
        r111 = tuple(j.name for j in fix_clock_jobs(a))  # R11.1 A and C: on the same clock
        assert r111 == ("series_checkin", "photos_import", "face_groups_poll")
        assert st.helpers_clock.job_names == ("bills_due", *r111)  # R7's watch_stale is not here
        gw = st.gateway
        assert {"bill_list", "bill_pay_prepare"} <= {s.name for s in gw.registry.specs()}
        res = await gw.execute(ToolCall(id="t1", name="bill_list", arguments={}), scope="u:s")
        assert res.outcome is GatewayOutcome.EXECUTED
        pay = await gw.execute(
            ToolCall(id="t2", name="bill_pay_prepare", arguments={}), scope="u:s"
        )
        assert pay.outcome is GatewayOutcome.AWAITING_CONFIRMATION  # R3: always a card
        out = await a.client.post(WATCHDOG_PATH)  # Home off: the one 5-minute clock (R14 D7)
        assert out.status_code == 200 and out.json()["jobs"]["helpers_clock"] == "ok"
        assert set(out.json()["jobs"]) == {"health_check", "helpers_clock", "mobile_clock"}
        assert job.seen == [r11.owners_of(settings)]  # the configured owners, never a list passed
        status = await st.helpers_status.read()
        assert status is not None and status["jobs"]["bills_due"] == "ok"
        assert set(status["jobs"]) == {"bills_due", *r111}  # every job ran and said how


async def test_with_home_on_the_clock_is_added_to_the_watchdog_once(settings: Settings) -> None:
    class Dog:
        def __init__(self) -> None:
            self.added: list[str] = []

        def extend(self, job: Any) -> None:
            self.added.append(job.name)

        def prepend(self, job: Any) -> None:
            self.added.insert(0, job.name)

    async with running(settings) as a:
        st = a.state
        dog = st.home_watchdog = Dog()
        st.r11_jobs = st.clock_jobs = None
        first, again = r11.r11_tick_jobs(a.app), r11.r11_tick_jobs(a.app)
        assert first is again
        tick_wiring.install_clocks(a.app)  # R14 D7: the one 5-minute clock puts it on the dog
        assert dog.added.count("helpers_clock") == 1


async def test_a_failing_helper_job_is_degraded_never_a_503(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(_Job):
        async def run(self, owners: Sequence[str]) -> dict[str, int]:
            raise RuntimeError("down")

    def nudges(ctx: HelperContext) -> HelperPart:
        return HelperPart(name="nudges", clock_jobs=(Broken("nudges"),))

    monkeypatch.setattr(r11, "BUILDERS", {**r11.BUILDERS, "nudges": nudges})
    async with running(settings) as a:
        out = await a.client.post(WATCHDOG_PATH)
        assert out.status_code == 200 and out.json()["jobs"]["helpers_clock"] == "degraded"


# ---- /v1/helpers --------------------------------------------------------------------------------
async def test_the_helpers_view_and_the_nudge_controls(settings: Settings) -> None:
    async with running(settings) as a:
        c = a.client
        view = (await c.get("/v1/helpers")).json()
        assert view["enabled"] is True
        assert [(p["name"], p["tab"]) for p in view["parts"]] == [
            ("today", "Today"),
            ("house", "Home"),
            ("nudges", "Nudges"),
            ("kitchen", "Kitchen"),
        ]
        assert view["clock"]["stale"] is True and view["clock"]["last_run"] is None
        assert view["nudges"]["caps"]["nudge_hydrate"] == 8 and view["nudges"]["max_per_day"] == 16
        assert set(view["fortnight"]) >= {"reminders_on_time", "reminders_late"}
        r = await c.put("/v1/helpers/gate", json={"caps": {"nudge_hydrate": 3}}, headers=CSRF)
        assert r.status_code == 200 and r.json()["nudges"]["caps"]["nudge_hydrate"] == 3
        assert r.headers["cache-control"] == "no-store"
        r = await c.post(
            "/v1/helpers/gate/nudge_hydrate/snooze", json={"minutes": 60}, headers=CSRF
        )
        assert "nudge_hydrate" in r.json()["nudges"]["snoozed"]
        r = await c.post("/v1/helpers/gate/all/stop", headers=CSRF)
        assert "*" in r.json()["nudges"]["stopped"]
        r = await c.post("/v1/helpers/gate/all/resume", headers=CSRF)
        assert r.json()["nudges"]["stopped"] == {} and r.json()["nudges"]["snoozed"] == {}
        for path, body in (
            ("/v1/helpers/gate/bill_due/stop", None),
            ("/v1/helpers/gate/nudge_hydrate/snooze", {"minutes": 5}),
        ):
            r = await c.post(path, json=body, headers=CSRF)
            assert r.status_code == 422 and r.json()["error"] == "invalid"
        r = await c.put("/v1/helpers/gate", json={"caps": {"nudge_hydrate": 99}}, headers=CSRF)
        assert r.status_code == 422
        await a.client.post(WATCHDOG_PATH)
        assert (await c.get("/v1/helpers")).json()["clock"]["stale"] is False


def test_the_four_part_routers_live_under_their_own_prefix() -> None:
    from jarvis.api import helpers_house, helpers_kitchen, helpers_nudges, helpers_today

    for part, module in zip(
        PARTS, (helpers_today, helpers_house, helpers_nudges, helpers_kitchen), strict=True
    ):
        assert module.PREFIX == f"/v1/helpers/{part}"
        paths = [r.path for r in module.router.routes]  # type: ignore[attr-defined]
        assert paths and all(p.startswith(module.PREFIX) for p in paths), part


async def test_every_parts_routes_are_mounted_and_answer_off_safely(settings: Settings) -> None:
    """I1: each part's router is mounted; with no token key each GET answers, never a 500."""
    async with running(settings) as a:
        for part in PARTS:
            r = await a.client.get(f"/v1/helpers/{part}")
            assert r.status_code < 500 and r.json().get("detail") != "Not Found", (part, r.text)
            assert r.headers["cache-control"] == "no-store", part


# ---- app.py and the other wiring files ----------------------------------------------------------
def _lines() -> list[str]:
    return (API / "app.py").read_text(encoding="utf-8").splitlines()


def _at(lines: list[str], needle: str) -> int:
    hits = [i for i, line in enumerate(lines) if needle in line]
    assert len(hits) == 1, (needle, hits)
    return hits[0]


def test_app_py_has_the_six_r11_slots_and_stays_under_its_guard() -> None:
    lines = _lines()
    assert len(lines) <= 750
    # R11.1 and R7 are wired between them: their parts' jobs ride the helpers' clock
    assert _at(lines, "await wire_r11(app, s, docs, audit)") == _at(lines, "await wire_r6(") + 3
    assert _at(lines, "install_r11_routes(app)") == _at(lines, "install_r6_routes(app)") + 1
    # R14 I0 moved the tick list into api/tick_wiring.py (app.py had no line to spare)
    ticks = (API / "tick_wiring.py").read_text(encoding="utf-8").splitlines()
    assert _at(ticks, "*r11_tick_jobs(app),") == _at(ticks, "*r6_tick_jobs(app),") + 1
    assert _at(ticks, "*r7.mobile_tick_jobs(app),") == _at(ticks, "*r11_tick_jobs(app),") + 1
    assert "finish_wiring(app)" in "\n".join(lines)
    assert _at(lines, "r11=app.state.r11_parts,") == _at(lines, "r4=app.state.r4_parts,") + 1
    assert _at(lines, "helpers=helpers_brief(app),") == _at(lines, "vitals=vitals_brief(app),") + 1
    assert "def _log_up" not in "\n".join(lines) and "log_up(app, s)" in "\n".join(lines)
    personal = (API / "personal.py").read_text(encoding="utf-8")
    assert personal.index("*r11_privacy_sources(app)") < personal.index(
        "*home_privacy_sources(app)"
    )


# ---- the console --------------------------------------------------------------------------------
def test_the_console_has_the_helpers_tab_last_its_panel_and_its_frame() -> None:
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    assert len(html.splitlines()) < 800
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    # R7 I0: Camera is the last tab now, Helpers the one before it; the sheet is console-dock.js's
    assert re.findall(r'data-open="(\w+)"', dock)[-2:] == ["helpers", "camera"]
    dock_js = (STATIC / "console-dock.js").read_text(encoding="utf-8")
    assert "    helpers: '" in dock_js and "    camera: '" in dock_js
    assert 'id="p-helpers" data-panel="helpers" aria-labelledby="t-helpers" hidden' in html
    assert 'data-grip aria-label="Move Helpers panel' in html and "Close Helpers panel" in html
    assert html.index('src="/static/console-book.js"') < html.index(
        'src="/static/console-helpers.js"'
    )
    deck = (STATIC / "console-deck.js").read_text(encoding="utf-8")
    assert "'book', 'helpers', 'camera']" in deck and "helpers: { x: col2" in deck  # R7: + Camera
    shell = (STATIC / "console-helpers.js").read_text(encoding="utf-8")
    for name in PART_MODULES:
        assert name in APP_ASSETS and f"import('./{name}')" in shell
        js = (STATIC / name).read_text(encoding="utf-8")
        tab = name.removeprefix("console-helpers-").removesuffix(".js")
        assert f"H.register('{tab}'" in js and "innerHTML" not in js
    assert {"console-helpers.js", "console-helpers.css"} <= set(APP_ASSETS)
    assert "innerHTML" not in shell and "insertAdjacentHTML" not in shell
    assert "role', 'tablist'" in shell and "ArrowRight" in shell
    css = (STATIC / "console-helpers.css").read_text(encoding="utf-8")
    assert "#" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # no new colours: tokens only


def test_the_helpers_context_is_frozen_and_parts_can_replace_fields() -> None:
    from r11_fakes import ctx

    c, _, _, _ = ctx("today")
    assert replace(c, keyring=None).sender.part == "today"
    with pytest.raises(AttributeError):
        c.owners = ()  # type: ignore[misc]


async def test_a_parts_phrase_answers_in_no_ai_mode_through_its_tool(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D18: a part's phrasebook joins the one BrainMode; with the AI off, "don't remind me to stand
    up" reaches the part's own tool through the gateway, and sets no calendar reminder."""
    from jarvis.offline.rules import NoAICall, NoAIRoute

    def phrase(text: str, now: Any) -> NoAIRoute | None:
        if re.fullmatch(r"(?i)\s*don'?t remind me to stand up\s*", text):
            return NoAIRoute((NoAICall("nudge_stop", {}),))
        return None

    def nudges(ctx: HelperContext) -> HelperPart:
        tool = _tool("nudge_stop", ActionRisk.READ_ONLY)
        return HelperPart(name="nudges", tools=(tool,), phrases=(phrase,))

    monkeypatch.setattr(r11, "BUILDERS", {**r11.BUILDERS, "nudges": nudges})
    async with running(settings) as a:
        phrases = a.state.brain_mode.phrases
        assert phrase in phrases and len(phrases) > 1  # with the four parts' own phrasebooks
        r = await a.client.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=CSRF)
        assert r.status_code == 200
        r = await a.client.post("/v1/chat", json={"message": "don't remind me to stand up"})
        assert r.status_code == 200 and r.json()["reply"] == "nudge_stop ran", r.text
