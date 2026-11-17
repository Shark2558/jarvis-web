# tests/test_r131_a_needles.py -- R13.1 Part A (BRIEF-A section 2, "Every route"; plan D4, "Private
# by default"): his measurements never reach a log record, a tool call's arguments or result, or
# the audit. Six measurements he types, each a number nothing else in the pilot carries, go
# through every Part A route and the paths that log (R13's records unreadable, the key changed);
# then no record, tool call or audit entry names any of them. I1's `needles` suite searches every
# other sink with the wired app.
from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from r131_fakes_a import SHOES, UID, AWorld, T, a_world

from jarvis.keyring import Keyring
from jarvis.wardrobe.tryon.part import TryonService

TYPED = {"height": 187, "shoulders": 51, "chest": 117, "waist": 93, "hips": 109, "inseam": 83}
NEEDLES = [re.compile(rf"(?<![0-9.]){v}(?![0-9])") for v in TYPED.values()]
RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def _said(record: logging.LogRecord) -> str:
    """A record as the formatters write it: its message and every `extra=` field."""
    extras = {k: v for k, v in record.__dict__.items() if k not in RESERVED}
    return f"{record.getMessage()} {json.dumps(extras, default=str)}"


def _found(texts: list[str]) -> list[str]:
    return [t for t in texts if any(n.search(t) for n in NEEDLES)]


def _tool_calls(a: AWorld) -> list[str]:
    seen: list[str] = []
    real = a.w.gw.execute

    async def execute(call: Any, **kw: Any) -> Any:
        res = await real(call, **kw)
        seen.append(json.dumps([call.arguments, res.result, res.error], default=str))
        return res

    a.w.gw.execute = execute  # type: ignore[method-assign]
    return seen


async def _every_route(a: AWorld, pid: str) -> None:
    slots = [{"slot": "top", "piece": T.white}, {"slot": "shoes", "piece": SHOES[0]}]
    shape = {"piece": T.striped, "template": "shirt"}
    async with a.client() as c:
        for r in (
            await c.put("/v1/tryon/body", json=TYPED),
            await c.post("/v1/tryon/body/use"),
            await c.put("/v1/tryon/body", json={**TYPED, "height": 186}),
            await c.delete("/v1/tryon/body/draft"),
            await c.get("/v1/tryon"),
            await c.get(f"/v1/tryon/look?plan={pid}"),
            await c.get("/v1/tryon/look?day=today"),
            await c.put(f"/v1/tryon/assets/{T.striped}", json=shape),
            await c.post("/v1/tryon/saved", json={"looks": [{"plan": pid, "slots": slots}]}),
            await c.get("/v1/tryon/saved"),
            await c.post("/v1/tryon/confirm", json={"plan": pid, "slots": slots}),
        ):
            assert r.status_code == 200, (r.request.url, r.text)


async def test_his_measurements_never_reach_a_log_a_tool_call_or_the_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = await a_world()
    pid = await a.plan()
    calls = _tool_calls(a)
    with caplog.at_level(logging.DEBUG):
        await _every_route(a, pid)

        async def broken(uid: str) -> Any:
            raise RuntimeError("R13's store is down")

        a.styling.view = broken  # type: ignore[method-assign]
        async with a.client() as c:
            assert (await c.get("/v1/tryon")).status_code == 200  # logs R13's trouble
        other = TryonService(a.ctx)
        other.store._ring = Keyring(bytes(range(1, 33)))  # noqa: SLF001 - the key changed
        with pytest.raises(Exception, match="tryon"):
            await other.store.read(UID)  # logs that it can't be opened
    assert calls, "the confirm made its one outfit_plan call"
    assert caplog.records, "the paths that log did log"
    assert _found([_said(r) for r in caplog.records]) == []
    assert _found(calls) == []
    entries = (await a.w.audit.tail(200)).entries
    assert _found([json.dumps([e.tool, e.detail, e.args_hash]) for e in entries]) == []
    stored = await a.docs.get(f"jarvis_tryon/{UID}")
    plain = {k: v for k, v in stored.items() if k != "blob"}  # the blob is sealed (AES-GCM)
    assert set(plain) == {"owner", "rev", "updated_at"} and _found([json.dumps(plain)]) == []
    assert not any(m in stored["blob"] for m in TYPED)  # no measurement's name in clear
