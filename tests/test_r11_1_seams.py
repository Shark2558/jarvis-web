# tests/test_r11_1_seams.py -- R11.1 I0 seams (docs/plans/r11-1-observations.md "Seams the I0
# adds"): the version, the settings, the two alert kinds and the two permission rows with their
# pinned counts, a picture as a content block that only a seeing, non-training brain is sent, the
# reply-finishing module the Brain now calls, the four parts' plug-in contract and wiring, their
# stub routes, the console loader that brings the four part modules, the line budgets the builders
# rely on, and the eval runner.
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import get_args

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

import jarvis
import jarvis.api.r11_1_wiring as wiring
from jarvis.alerts import R11_1_ALERT_KINDS, AlertKind
from jarvis.api import create_app
from jarvis.api.console import APP_ASSETS
from jarvis.config import Settings
from jarvis.core import finish
from jarvis.core.brain_types import _owner_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.core.models import ChatRequest
from jarvis.documents.pictures import turn_pictures
from jarvis.fixes.ports import PARTS, ROUTE_PREFIX, TOOL_FAMILIES, FixContext, FixPart, tool_allowed
from jarvis.llm.anthropic_provider import AnthropicProvider
from jarvis.llm.base import (
    PICTURE_TYPES,
    PICTURE_WITHHELD,
    ChatMessage,
    Completion,
    ImageBlock,
    Role,
    TextBlock,
    Usage,
    without_pictures,
)
from jarvis.llm.brains import BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.notify.held import summary
from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
from jarvis.notify.ports import DEFAULT_URGENCY
from jarvis.permissions.groups import GROUPS, get_group, groups_for
from jarvis.tools.base import Tool

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"
R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PART_JS = [f"console-r111-{p}.js" for p in ("plan", "files", "photos", "look")]
PART_CSS = [n.replace(".js", ".css") for n in PART_JS]


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_the_version_is_eleven_point_one() -> None:
    assert jarvis.__version__ == "11.1.1"  # R11.1 hotfix 1 (was 11.1.0)


# ---- settings -----------------------------------------------------------------------------------
def test_the_new_settings_have_safe_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.max_output_tokens == 1024  # a plain chat reply stays short and cheap
    assert s.work_output_tokens == 8192  # O1: a turn that works with tools or files
    assert s.empty_reply_retries == 1
    assert s.calendar_batch_max == 100  # O2
    assert s.series_enabled is True
    assert s.voice_understand is True and s.voice_hint_words == 40  # O3
    assert s.attach_max_files == 10 and s.attach_folder_max_files == 50  # O4
    assert s.attach_zip_max_files == 50 and s.attach_total_mb == 40
    assert s.attach_picture_max_kb == 900  # one Firestore document, as bytes
    assert s.photos_max_picked == 2000  # O6: Google's Picker maximum
    assert s.photos_import_batch == 10
    assert s.picture_research_enabled is True  # O9's alternative
    assert s.mail_summary_max_reads == 30  # O12


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("work_output_tokens", 512),
        ("work_output_tokens", 32_001),  # R11.1 I1: the tool loop does not stream (A 3.13)
        ("empty_reply_retries", 3),
        ("calendar_batch_max", 101),
        ("voice_hint_words", 201),
        ("attach_max_files", 11),  # R11.1 I1: at most what ChatRequest carries (B 3.3)
        ("attach_picture_max_kb", 1000),
        ("photos_max_picked", 2001),
        ("photos_max_picked", 0),
        ("mail_summary_max_reads", 101),
    ],
)
def test_a_setting_outside_its_range_is_refused(field: str, bad: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


# ---- alert kinds --------------------------------------------------------------------------------
def test_two_kinds_make_thirty_eight() -> None:
    every = get_args(AlertKind)
    assert R11_1_ALERT_KINDS == ("series_checkin", "faces_to_name")
    assert len(every) == len(set(every)) == 38 and set(DEFAULT_URGENCY) == set(every)
    assert DEFAULT_URGENCY["series_checkin"] == "important"
    assert DEFAULT_URGENCY["faces_to_name"] == "info"
    # "did the session happen?" is asked every time: it rings by day and is HELD at night,
    # never dropped the way a nudge is
    assert "series_checkin" in DAYTIME_RING_KINDS and "series_checkin" not in EPHEMERAL_KINDS
    assert "faces_to_name" not in DAYTIME_RING_KINDS


def test_the_held_summary_and_the_alerts_card_know_both_kinds() -> None:
    words = summary([{"kind": "series_checkin"}, {"kind": "faces_to_name"}])
    assert "study" in words.lower() and "face" in words.lower()
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    for kind in R11_1_ALERT_KINDS:
        assert f"['{kind}'," in js


# ---- permission rows ----------------------------------------------------------------------------
def test_two_rows_make_forty_six_and_sit_before_maps() -> None:
    ids = [g.id for g in GROUPS]
    assert len(ids) == len(set(ids)) == 46
    assert ids[ids.index("kitchen") + 1 : ids.index("maps")] == ["plans", "pictures"]
    plans, pictures = get_group("plans"), get_group("pictures")
    assert plans is not None and pictures is not None
    assert (plans.section, plans.risk) == ("Calendar plans", R2)
    assert (pictures.section, pictures.risk) == ("Pictures", R1)


def test_the_new_tools_fall_into_the_right_rows() -> None:
    assert {g.id for g in groups_for("series_list", R1)} == {"plans"}
    assert {g.id for g in groups_for("series_reschedule", R2)} == {"plans"}
    assert {g.id for g in groups_for("picture_research", R1)} == {"pictures"}
    # the batch is a calendar write and the mail summary a mail read: their existing rows
    assert {g.id for g in groups_for("calendar_create_events", R2)} == {"calendar_change"}
    assert {g.id for g in groups_for("gmail_inbox_summary", R1)} == {"email_read"}


# ---- pictures in jarvis.llm ---------------------------------------------------------------------
def test_a_picture_block_takes_jpeg_or_png_only() -> None:
    block = ImageBlock(media_type="image/jpeg", data=JPEG)
    assert block.type == "image" and PICTURE_TYPES == ("image/jpeg", "image/png")
    with pytest.raises(ValidationError):
        ImageBlock(media_type="image/svg+xml", data=b"<svg/>")
    with pytest.raises(ValidationError):
        ImageBlock(media_type="image/png", data=b"")
    msg = ChatMessage(role=Role.USER, content=[TextBlock(text="what is this?"), block])
    assert msg.text() == "what is this?"  # a picture is never text


def test_claude_is_sent_the_picture_as_base64() -> None:
    assert AnthropicProvider.vision is True
    msg = ChatMessage(
        role=Role.USER,
        content=[TextBlock(text="look"), ImageBlock(media_type="image/png", data=b"\x89PNG1234")],
    )
    sent = AnthropicProvider._to_params([msg])[0]["content"]
    assert sent[0] == {"type": "text", "text": "look"}
    assert sent[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBORzEyMzQ="},
    }


def test_a_brain_that_cannot_see_or_may_train_never_gets_the_picture() -> None:
    seeing = BrainSpec("a", "A", MockProvider(), {ModelTier.FAST: "m"})
    assert seeing.sees_pictures is False  # the mock has no eyes
    MockProvider.vision = True
    try:
        assert seeing.sees_pictures is True
        training = BrainSpec(
            "t", "T", MockProvider(), {ModelTier.FAST: "m"}, trains_on_content=True
        )
        assert training.sees_pictures is False  # private pictures never reach a training brain
    finally:
        MockProvider.vision = False
    msg = ChatMessage(
        role=Role.USER,
        content=[TextBlock(text="look"), ImageBlock(media_type="image/jpeg", data=JPEG)],
    )
    plain = ChatMessage(role=Role.USER, content="hello")
    out = without_pictures([msg, plain])
    assert out[1] is plain
    assert out[0].content == [TextBlock(text="look"), TextBlock(text=PICTURE_WITHHELD)]
    assert msg.content[1].type == "image"  # the caller's message is not changed


# ---- a spoken message keeps what was heard ------------------------------------------------------
def test_a_spoken_turn_keeps_the_heard_words_and_a_typed_one_never_does() -> None:
    spoken = ChatRequest(message="add the CSV file", channel="voice", heard="add D csb file")
    assert _owner_turn("add the CSV file", spoken, None).heard == "add D csb file"
    typed = ChatRequest(message="add the CSV file", heard="add D csb file")
    assert _owner_turn("add the CSV file", typed, None).heard is None
    with pytest.raises(ValidationError):
        ChatRequest(message="x", channel="voice", heard="h" * 2001)


async def test_no_picture_is_attached_until_part_b_builds_it() -> None:
    assert await turn_pictures(None, "owner", "sess_1") == []


# ---- the reply-finishing module -----------------------------------------------------------------
def _completion(text: str, stop: str | None = "end_turn") -> Completion:
    return Completion(
        text=text, model="m", provider="mock", usage=Usage(), stop_reason=stop, latency_ms=1
    )


def test_the_brain_takes_its_reply_from_the_finish_module() -> None:
    assert finish.reply_text(_completion("  Done, Sir. ")) == "Done, Sir."
    assert finish.reply_text(_completion("")) == finish.EMPTY  # R11.1 A: a plain sentence, by code
    assert finish.OLD_FILLER not in finish.EMPTY
    assert not hasattr(finish, "FILLER")  # R11.1 I1: I0's alias is gone (INTEGRATION-A 3.1)
    assert finish.cut_short(_completion("half", "max_tokens")) is True
    assert finish.cut_short(_completion("whole")) is False
    assert finish.output_cap(Settings(_env_file=None), working=False) == 1024
    assert finish.output_cap(Settings(_env_file=None), working=True) == 8192
    brain = (SRC / "core" / "brain.py").read_text(encoding="utf-8")
    assert "nothing to add" not in brain and "finish.reply_text(" in brain
    assert "finish.log_turn(" in brain and "with_pictures(" in brain


def test_the_line_budgets_leave_the_builders_room() -> None:
    assert _lines(SRC / "core" / "brain.py") <= 770  # 779 at R11 (guard < 800): Part A made it 704
    assert _lines(SRC / "tools" / "gateway.py") <= 760  # no part may grow it
    # guard 750; R11.1 I1 made it 731 (the brief's governed inbox read, the one turn guard)
    assert _lines(SRC / "api" / "app.py") <= 735
    assert _lines(STATIC / "console.html") <= 795  # guard < 800: 798 at R11, 795 at R11.1


# ---- the four parts -----------------------------------------------------------------------------
def test_the_four_parts_and_what_each_owns() -> None:
    assert PARTS == ("plan", "files", "photos", "look")
    assert tool_allowed("plan", "calendar_create_events") and tool_allowed("plan", "series_list")
    assert tool_allowed("plan", "gmail_inbox_summary")
    assert tool_allowed("files", "voice_understand") is False  # B adds no tool: a route only
    assert tool_allowed("photos", "faces_groups") and tool_allowed("look", "picture_research")
    assert not tool_allowed("look", "series_list") and not tool_allowed("plan", "picture_research")
    assert set(TOOL_FAMILIES) == set(ROUTE_PREFIX) == set(PARTS)
    for name in PARTS:
        part = importlib.import_module(wiring.PART_MODULES[name]).build
        assert callable(part)


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_the_app_starts_with_four_stub_parts_and_their_status_routes(
    settings: Settings,
) -> None:
    async with running(settings) as (app, client):
        parts = app.state.r111_parts
        assert list(parts) == list(PARTS)
        assert all(isinstance(p, FixPart) and p.name == n for n, p in parts.items())
        for name in PARTS:
            r = await client.get(ROUTE_PREFIX[name])
            assert r.status_code == 200, name
            assert r.json()["part"] == name and "ready" in r.json()
            assert r.headers["cache-control"] == "no-store"


def _tool(name: str) -> Tool:
    async def run(_: dict[str, object]) -> str:
        return "ok"

    return Tool(name, "a test tool", {"type": "object", "properties": {}}, R1, run)


def _ctx(app: FastAPI, s: Settings) -> FixContext:
    return FixContext(s=s, docs=None, audit=None, state=lambda n: getattr(app.state, n, None))


def test_a_part_that_breaks_its_contract_is_left_out_and_the_rest_stay(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = FastAPI()

    def build(name: str, ctx: FixContext) -> FixPart:
        if name == "plan":
            return FixPart("plan", tools=(_tool("picture_research"),))  # another part's tool
        if name == "files":
            raise RuntimeError("boom")
        if name == "photos":
            return FixPart("look")  # another part's name
        return FixPart("look", tools=(_tool("picture_research"),), ready="ready")

    monkeypatch.setattr(wiring, "_build", build)
    parts = wiring.build_parts(_ctx(app, settings))
    assert [parts[n].ready for n in ("plan", "files", "photos")] == [wiring.SETUP_FAILED] * 3
    assert parts["look"].ready == "ready"
    assert [t.name for t in wiring.fix_tools(parts)] == ["picture_research"]
    assert wiring.fix_tools(None) == ()


def test_the_wiring_files_have_their_slots() -> None:
    app_py = (SRC / "api" / "app.py").read_text(encoding="utf-8")
    for needle in ("wire_r11_1(app, s, docs, audit)", "install_r11_1_routes(app)", "r111="):
        assert needle in app_py, needle
    setup = (SRC / "tools" / "setup.py").read_text(encoding="utf-8")
    assert "r111: Sequence[Tool] = ()" in setup


# ---- the console --------------------------------------------------------------------------------
def test_one_loader_brings_the_four_part_modules_and_their_styles() -> None:
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    assert html.count('<script type="module" src="/static/console-r111.js"></script>') == 1
    loader = (STATIC / "console-r111.js").read_text(encoding="utf-8")
    for js, css in zip(PART_JS, PART_CSS, strict=True):
        assert f"./{js}" in loader and f"/static/{css}" in loader
        assert js not in html and css not in html  # the page itself gains one line only
        assert APP_ASSETS[js] == APP_ASSETS["console.js"] and APP_ASSETS[css] == "text/css"
        assert (STATIC / js).is_file() and (STATIC / css).is_file()
        assert "innerHTML" not in (STATIC / js).read_text(encoding="utf-8")
    assert "console-r111.js" in APP_ASSETS
    assert "innerHTML" not in loader and "window.JarvisFixes" in loader


def test_the_four_confirm_dialogs_kept_every_id_when_their_lines_were_joined() -> None:
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    for name in ("limit", "brief", "memory", "drive"):
        block = re.search(rf'<dialog class="bdialog" id="{name}Dialog".*?</dialog>', html, re.S)
        assert block is not None
        for part in ("Title", "Text", "No", "Yes"):
            assert f'id="{name}Dialog{part}"' in block.group(0)
        assert f'<h2 id="{name}DialogTitle"></h2><div id="{name}DialogText"></div>' in block.group(
            0
        )


# ---- the guide and the evals --------------------------------------------------------------------
def test_the_guide_has_the_r11_1_card() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    card = guide[guide.index("#### C61 · ") : guide.index("### Layer 6")]
    for needle in (
        "`src/jarvis/fixes/`",
        "`src/jarvis/series/`",
        "`src/jarvis/understand/`",
        "`src/jarvis/facegroups/`",
        "`src/jarvis/picture/`",
        "`console-r111.js`",
        "`series/{uid}`",
        "Built in R11.1",  # R11.1 I1: as built, no longer PLANNED
        "`photo_imports/{uid}`",
        "`face_groups/{uid}`",
    ):
        assert needle in card, needle
    assert "PLANNED" not in card


def test_every_part_is_built_and_the_runner_passes_with_every_control_failing() -> None:
    """R11.1 I1 (retires I0's stub-stage test): all four parts are built, every case passes, and
    each part's own negative control made that part fail (a part that cannot fail proves
    nothing)."""
    run = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "r11_1" / "run.py"), "--mock"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-4000:]
    assert "not built yet" not in run.stdout
    report = json.loads((ROOT / "evals" / "r11_1" / "report.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in report["results"]}
    assert not any(i.endswith(":not_built_yet") or i.endswith(":missing") for i in ids), ids
    assert report["passed"] == report["cases"]
    control = report["negative_control"]
    assert control["suite_failed"] is True and control["parts_not_built"] == []
    parts = ("plan", "files", "photos", "look")
    assert set(control["failed_cases"]) == set(parts)
    for part in parts:
        assert {i.split(":", 1)[0] for i in ids} >= {part}, part
        assert control["failed_cases"][part], f"{part}: its control failed none of its cases"


def test_the_r11_1_suite_is_gated_in_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if '"r11_1 (gated)"' in x)
    assert 'HERE / "r11_1" / "run.py"' in line and line.rstrip().endswith("True),")


def test_the_build_book_knows_the_layer_of_every_r11_1_package() -> None:
    """A package missing from the layer map fails the book's `--check` (and so the deploy)."""
    from jarvis.buildbook.gen.layers import LAYER_OF

    assert LAYER_OF["understand"] == "L2"
    assert LAYER_OF["facegroups"] == "L2"
    assert LAYER_OF["series"] == "L5"
    assert LAYER_OF["picture"] == "L5"
    assert LAYER_OF["fixes"] == "X"
