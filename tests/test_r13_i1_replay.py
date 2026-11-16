# tests/test_r13_i1_replay.py -- R13 I1 (Workshop decision 6; INTEGRATION-B 6.10): D's tool calls,
# replayed through each part's REAL schema and the real gateway. Part B found exactly this class
# of bug (the panel named `piece` and `none`, the tool takes `pieces` and `outcome`); the gateway
# refuses an argument a schema doesn't name, so such a press would fail on his phone.
#
# Three sources, so nothing D sends can skip the replay:
#   1. the RECORDED corpus (`tests/fixtures/r13/d_calls.json`, from D's browser and Node scenarios,
#      folded by `tests/r13_record.py`): every call with its real values;
#   2. D's No-AI sentences (`tests/test_r13_d_phrases.py` ROWS): the phone's calls;
#   3. D's JS SOURCE: each `tool('name', {...})` literal's keys, so a button the scenarios never
#      press is still checked (a name the tools don't have, a key their schema doesn't name).
# Control: the same replay with one unknown argument added must fail.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_r13_a_routes import _owner, running
from test_r13_d_phrases import ROWS

from jarvis.config import Settings
from jarvis.llm.base import ToolCall
from jarvis.tools.taint import context_trust
from jarvis.wardrobe.ports import TOOL_OWNER

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "jarvis" / "api" / "static"
CORPUS = json.loads((ROOT / "tests" / "fixtures" / "r13" / "d_calls.json").read_text("utf-8"))
JS = ("console-helpers-wardrobe.js", "console-wardrobe-pieces.js", "console-wardrobe-scan.js")
PLACEHOLDER = re.compile(r"<[^>]*>")
BAD = ("unknown arguments", "missing arguments", "unknown tool")


def phone_calls() -> list[dict[str, Any]]:
    """D20's sentences' calls (the value a step takes from the one before is a real-looking id)."""
    out = []
    for sentence, calls in ROWS:
        for tool, args in calls:
            if tool in TOOL_OWNER:
                fixed = {
                    k: "wi_" + "a" * 12 if PLACEHOLDER.fullmatch(str(v)) else v
                    for k, v in args.items()
                }
                out.append({"source": "phone", "tool": tool, "arguments": fixed, "said": sentence})
    return out


def _literals(source: str) -> list[tuple[str, list[str]]]:
    """(tool name, top-level keys) of every `tool('name', { ... })` object literal in D's JS."""
    found = []
    for m in re.finditer(r"""\btool\(\s*['"]([a-z_]+)['"]\s*,\s*\{""", source):
        depth, i, keys, token = 1, m.end(), [], ""
        while i < len(source) and depth:
            ch = source[i]
            depth += ch in "{[(" and 1 or ch in "}])" and -1 or 0
            if depth == 1:
                token += ch
            if depth == 1 and ch == ",":
                keys.append(token[:-1])
                token = ""
            i += 1
        keys.append(token.rstrip("}").strip() if token.strip() else "")
        names = [re.match(r"\s*([A-Za-z_]\w*)\s*(?::|$)", k) for k in keys if k.strip()]
        found.append((m.group(1), [n.group(1) for n in names if n]))
    return found


def js_calls() -> list[tuple[str, str, list[str]]]:
    return [
        (name, tool, keys)
        for name in JS
        for tool, keys in _literals((STATIC / name).read_text("utf-8"))
    ]


def test_the_static_reader_finds_the_buttons_it_should() -> None:
    names = {t for _, t, _ in js_calls()}
    assert {"laundry_review", "wear_log", "laundry_move", "laundry_send_out"} <= names
    assert {"wardrobe_retire", "wardrobe_remove", "wardrobe_add"} <= names
    keys = {tuple(k) for _, t, k in js_calls() if t == "laundry_review"}
    assert ("action", "entry", "outcome", "pieces") in keys


REAL_IDS = {
    "entry": ("rv_", 10),
    "plan": ("op_", 8),
}  # the fake server's "rv_1" / "pl_1" are not ids


def realistic(args: dict[str, Any]) -> dict[str, Any]:
    """The same call with the ids a real server would have sent (D's code only echoes them)."""
    out = dict(args)
    for key, (prefix, n) in REAL_IDS.items():
        if key in out and not re.fullmatch(rf"{prefix}[0-9a-f]{{{n}}}", str(out[key])):
            out[key] = prefix + "0123456789abcdef"[:n]
    return out


async def replay(
    app: Any, calls: list[dict[str, Any]], *, extra: dict[str, Any] | None = None
) -> list[str]:
    """Every call through the real gateway; what comes back that says "your arguments are wrong"."""
    gw = app.state.gateway
    failures: list[str] = []
    for n, row in enumerate(calls):
        args = {**realistic(row["arguments"]), **(extra or {})}
        tool = gw.registry.get(row["tool"])
        if tool is None:
            failures.append(f"{row['source']}: no tool {row['tool']}")
            continue
        try:
            tool.validate(args)
        except ValueError as exc:
            failures.append(f"{row['source']}: {row['tool']} {exc}")
            continue
        with context_trust(untrusted=False, spoken=False, owner_text=None):
            res = await gw.execute(
                ToolCall(id=f"replay-{n}", name=row["tool"], arguments=args), scope="u:replay"
            )
        if res.error and any(res.error.startswith(b) for b in BAD):
            failures.append(f"{row['source']}: {row['tool']} {res.error}")
        if res.pending is not None:
            await gw.gate.cancel(res.pending.id)
    return failures


def test_the_corpus_covers_every_kind_of_press_d_makes() -> None:
    seen = {(r["source"], r["tool"]) for r in CORPUS}
    assert {("panel", "wardrobe_add"), ("panel", "laundry_review"), ("panel", "wear_log")} <= seen
    assert ("scan", "laundry_move") in seen and ("scan", "wardrobe_edit") in seen
    assert len(phone_calls()) >= 25


async def test_every_recorded_and_spoken_call_passes_its_parts_real_schema(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (app, _):
        assert await replay(app, [*CORPUS, *phone_calls()]) == []


async def test_every_button_in_d_s_source_names_a_real_tool_and_only_its_arguments(
    settings: Settings,
) -> None:
    async with running(_owner(settings)) as (app, _):
        reg = app.state.gateway.registry
        bad = []
        for file, name, keys in js_calls():
            tool = reg.get(name)
            if tool is None:
                bad.append(f"{file}: no tool {name}")
                continue
            props = tool.input_schema.get("properties", {})
            bad += [f"{file}: {name} has no argument {k}" for k in keys if k not in props]
        assert bad == []


async def test_control_one_unknown_argument_fails_the_replay(settings: Settings) -> None:
    async with running(_owner(settings)) as (app, _):
        failures = await replay(app, [*CORPUS, *phone_calls()], extra={"bogus": 1})
        assert failures and all("unknown arguments: bogus" in f for f in failures)
        assert len(failures) == len(CORPUS) + len(phone_calls())


@pytest.mark.parametrize("tool", sorted(TOOL_OWNER))
async def test_each_of_the_18_tools_is_registered_by_its_own_part(
    settings: Settings, tool: str
) -> None:
    async with running(_owner(settings)) as (app, _):
        assert app.state.gateway.registry.get(tool) is not None, tool
