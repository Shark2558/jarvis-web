# tests/test_r52_v5_never_approves.py -- R5.2 V5 (plan D6, slice 9 D11): the speaker check never
# approves anything: not a tool call, a card, a passkey, an unlock or a Telegram approval. "Spoken
# by the owner" is a display label at most: the server has no input that could carry "the owner's
# voice" into a decision, and nothing reads such a label. Read as code (who mentions the label or a
# voice print) and as behaviour (the real app, a waiting irreversible card: the label in a header
# or a body changes nothing; the passkey is still asked for).
# The console side: tests/test_r52_v5_console.py and tests/browser/test_r52_v5_voiceprint.py.
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from test_permissions_api import (  # noqa: F401  (fixtures and helpers of the passkey tests)
    CSRF,
    _card,
    _ready,
    gclient,
    google_settings,
)

from jarvis.core.guardrails import PendingAction
from jarvis.core.models import ChatRequest
from jarvis.llm.mock_provider import MockProvider
from jarvis.tools.builtin import InMemoryWorld
from jarvis.tools.context import ToolContext
from jarvis.tools.gateway import Gateway
from jarvis.voice import profile as vp

SRC = Path(__file__).resolve().parents[1] / "src/jarvis"
LABEL = re.compile(r"x-jarvis-spoken-by|SPOKEN_BY_HEADER|SPOKEN_BY_OWNER", re.IGNORECASE)
PRINT_WORDS = re.compile(r"voice[ _-]?print|speaker[ _-]?check|spoken[ _-]by", re.IGNORECASE)
WHERE_THE_LABEL_IS_DEFINED = {"voice/profile.py"}
# Where an approval, a passkey, an unlock, a permission or a Telegram approval is decided. None of
# them may even mention the label or a voice print, whatever a later release adds for display.
DECIDERS = (
    "tools/gateway.py",
    "tools/policy.py",
    "tools/context.py",
    "tools/taint.py",
    "core/guardrails.py",
    "core/approve_all.py",
    "core/brain.py",
    "api/routes.py",
    "api/permissions.py",
    "api/auth.py",
    "api/book_gate.py",
    "api/book_lock.py",
    "api/calls_routes.py",
    "permissions",
    "telegram",
    "vault",
    "vault_inbox",
    "mobile",
    "calls",
    "calldesk",
)
OWNER_SAYS = {vp.SPOKEN_BY_HEADER: vp.SPOKEN_BY_OWNER}


def _py(rel: str) -> list[Path]:
    path = SRC / rel
    return sorted(path.rglob("*.py")) if path.is_dir() else [path] if path.is_file() else []


def test_only_the_voice_profile_names_the_spoken_by_label() -> None:
    named = {
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if LABEL.search(p.read_text(encoding="utf-8"))
    }
    assert named == WHERE_THE_LABEL_IS_DEFINED


def test_nothing_imports_the_label_from_the_voice_profile() -> None:
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "jarvis.voice.profile":
                names = {a.name for a in node.names}
                assert not names & {"SPOKEN_BY_HEADER", "SPOKEN_BY_OWNER", "*"}, path
            if isinstance(node, ast.Attribute) and node.attr in {
                "SPOKEN_BY_HEADER",
                "SPOKEN_BY_OWNER",
            }:
                raise AssertionError(f"{path} reads {node.attr}")


def test_no_module_that_decides_an_approval_mentions_the_label_or_a_voice_print() -> None:
    checked = [p for rel in DECIDERS for p in _py(rel)]
    assert len(checked) > 30, "the decider list no longer matches the tree"
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert not LABEL.search(text), path
        assert not PRINT_WORDS.search(text), path


def test_no_decision_has_an_input_for_the_owners_voice() -> None:
    words = re.compile(r"speaker|spoken_by|voice_?print|owner_voice|verified_voice|embedding")
    fields = [f.name for f in dataclasses.fields(ToolContext)]
    assert not [f for f in fields if words.search(f)], fields  # `spoken` lowers trust: R2 I1
    assert not [p for p in inspect.signature(Gateway.execute).parameters if words.search(p)]
    assert not [f for f in PendingAction.model_fields if words.search(f)]
    assert not [f for f in ChatRequest.model_fields if words.search(f)]
    # and the cloud keeps no voice print: the voice profile has nowhere to put one
    assert not [f for f in vp.VoiceProfile.model_fields if re.search(r"print|embedding|vector", f)]


# ---- behaviour: the real app, a waiting irreversible card ------------------------------------
async def test_a_spoken_turn_labelled_the_owners_still_leaves_an_irreversible_card_waiting(
    client: AsyncClient, provider: MockProvider, world: InMemoryWorld
) -> None:
    from jarvis.llm.base import ToolCall

    send = ToolCall(id="t1", name="send_message", arguments={"to": "priya@x.com", "body": "3pm"})
    body = {"message": "send it", "channel": "voice", "spoken_by": "owner", "speaker": "owner"}
    outcomes: list[Any] = []
    for headers in (OWNER_SAYS, {}):
        provider.script_tool_calls([send], "Waiting for you.")
        r = await client.post("/v1/chat", json=body, headers=headers)
        assert r.status_code == 200, r.text
        outcomes.append([(p["tool"], p["risk"]) for p in r.json()["pending_approvals"]])
    assert outcomes[0] == outcomes[1] == [("send_message", "irreversible")]
    assert world.sent == []  # nothing was sent: the label approved nothing


async def test_the_label_is_no_passkey_and_no_approval(
    gclient: AsyncClient,  # noqa: F811
    provider: MockProvider,
    world: InMemoryWorld,
) -> None:
    await _ready(gclient)
    pid, sid = await _card(gclient, provider)
    labelled = {"spoken_by": "owner", "speaker_check": "owner"}
    for extra, refused in (({}, 403), (labelled, 403), ({"passkey": vp.SPOKEN_BY_OWNER}, 422)):
        r = await gclient.post(
            f"/v1/approvals/{pid}/approve",
            json={"session_id": sid, **extra},
            headers={**CSRF, **OWNER_SAYS},
        )
        # the passkey check stands; a label where the passkey goes is just a body that is not one
        assert r.status_code == refused, r.text
        assert refused == 422 or r.json()["error"] == "passkey_required"
    r = await gclient.post(
        "/v1/approvals/approve-all",
        json={"session_id": sid, "ids": [pid]},
        headers={**CSRF, **OWNER_SAYS},
    )
    assert (
        world.sent == []
    )  # approve-all never runs an irreversible card; the label changes nothing
    cards = (await gclient.get("/v1/approvals", headers=OWNER_SAYS)).json()
    assert [c["id"] for c in cards] == [pid] and cards[0]["passkey_required"] is True
