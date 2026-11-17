# tests/test_r131_a_needles.py -- R13.1 Part A (BRIEF-A section 2, "Every route"; plan D4, "Private
# by default"): his measurements never reach a log record, a tool call's arguments or result, or
# the audit. Six measurements he types, each a number nothing else in the pilot carries, go
# through every Part A route and the paths that log (R13's records unreadable, the key changed);
# then no record, tool call or audit entry names any of them. I1's `needles` suite searches every
# other sink with the wired app.
#
# The one place his numbers belong (INTEGRATION-A 8.4, review A-1): his own Privacy export of
# `tryon_figure` ("Your measurements and your 3D figure"), both the single export's `data` and
# `export_all`'s `categories.tryon_figure`. Nowhere else: no other category, not `unavailable`,
# not the export's audit line, no log. `outside_the_figure` is that rule; its positive control
# plants a number in another category's export and must find it.
from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
from r131_fakes_a import SHOES, UID, AWorld, T, a_world

from jarvis.keyring import Keyring
from jarvis.privacy.ports import PrivacyRegistry
from jarvis.privacy.service import PrivacyService
from jarvis.privacy.sources import CallbackSource, Look
from jarvis.tools.audit import AuditLog
from jarvis.wardrobe.catalog.store import WardrobeUnavailable
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.part import TryonService

TYPED = {"height": 187, "shoulders": 51, "chest": 117, "waist": 93, "hips": 109, "inseam": 83}
NEEDLES = [re.compile(rf"(?<![0-9.]){v}(?![0-9])") for v in TYPED.values()]
RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


AT = re.compile(r"(?:[A-Za-z0-9_/.-]+\.py:[0-9]+:[A-Za-z0-9_<>]+|\?)")  # `store.where`


def _said(record: logging.LogRecord) -> str:
    """A record as the formatters write it: its message and every `extra=` field. Its `at` (review
    A-1 F3) must be a code location and nothing else; its line number is not searched, since it
    may equal one of his numbers by chance."""
    extras = {k: v for k, v in record.__dict__.items() if k not in RESERVED}
    at = extras.pop("at", None)
    assert at is None or AT.fullmatch(str(at)), at
    return f"{record.getMessage()} {json.dumps(extras, default=str)}"


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HEX = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])[0-9a-f]{8,}(?![0-9A-Za-z])")
# a moment the code itself stamps (the export's `generated_at` reads the real clock): its minute
# can be 51, his shoulders (seen at I1's fix, 22:51 UTC): never a number of his
WHEN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z)?")


def _found(texts: list[str]) -> list[str]:
    """The texts that carry one of his numbers. Random ids, hashes and moments (a plan's `op_` id,
    the audit's argument hash, a session's UUID, a time stamp) are masked first: "2b93d7" is not
    his waist, and 22:51 is not his shoulders."""
    masked = [(t, HEX.sub("<hex>", UUID.sub("<id>", WHEN.sub("<when>", t)))) for t in texts]
    return [t for t, m in masked if any(n.search(m) for n in NEEDLES)]


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
            await c.post("/v1/tryon/confirm", json=await a.whole(pid)),
        ):
            assert r.status_code == 200, (r.request.url, r.text)


async def _a_bug_that_carries_his_height(a: AWorld) -> None:
    from jarvis.wardrobe.tryon import versions

    real = versions.versions_view

    def broken(doc: Any) -> Any:
        raise TypeError(f"height {TYPED['height']} chest {TYPED['chest']}")  # a bug's message

    versions.versions_view = broken  # type: ignore[assignment]
    try:
        async with a.client() as c:
            assert (await c.get("/v1/tryon")).status_code == 500
    finally:
        versions.versions_view = real  # type: ignore[assignment]


async def test_his_measurements_never_reach_a_log_a_tool_call_or_the_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = await a_world()
    pid = await a.plan()
    calls = _tool_calls(a)
    with caplog.at_level(logging.DEBUG):
        await _every_route(a, pid)

        async def broken(uid: str) -> Any:
            raise WardrobeUnavailable("R13's store is down")  # what R13's store raises

        a.styling.view = broken  # type: ignore[method-assign]
        async with a.client() as c:
            assert (await c.get("/v1/tryon")).status_code == 200  # logs R13's trouble
        await _a_bug_that_carries_his_height(a)  # logged at ERROR: never its message
        other = TryonService(a.ctx)
        other.store._ring = Keyring(bytes(range(1, 33)))  # noqa: SLF001 - the key changed
        with pytest.raises(Exception, match="tryon"):
            await other.store.read(UID)  # logs that it can't be opened
    assert calls, "the confirm made its one outfit_plan call"
    assert caplog.records, "the paths that log did log"
    assert [r.levelname for r in caplog.records if r.getMessage() == "try-on route failed"] == [
        "ERROR"
    ]
    assert _found([_said(r) for r in caplog.records]) == []
    assert _found(calls) == []
    entries = (await a.w.audit.tail(200)).entries
    assert _found([json.dumps([e.tool, e.detail, e.args_hash]) for e in entries]) == []
    assert all(re.fullmatch(r"[0-9a-f]{16}", e.args_hash) for e in entries)  # a hash, no text
    stored = await a.docs.get(f"jarvis_tryon/{UID}")
    plain = {k: v for k, v in stored.items() if k != "blob"}  # the blob is sealed (AES-GCM)
    assert set(plain) == {"owner", "rev", "updated_at"} and _found([json.dumps(plain)]) == []
    assert not any(m in stored["blob"] for m in TYPED)  # no measurement's name in clear


def outside_the_figure(export: dict[str, Any]) -> list[str]:
    """The parts of an `export_all` that carry one of his numbers, `tryon_figure`'s own payload
    aside (the one place they belong: his own copy of his own data)."""
    rest = {k: v for k, v in export.items() if k != "categories"}
    others = {k: v for k, v in export["categories"].items() if k != kept.FIGURE_ID}
    return _found([json.dumps(rest, default=str), json.dumps(others, default=str)])


def _planted() -> CallbackSource:
    """Another category whose export carries his height: the rule's positive control."""

    async def look(uid: str) -> Look:
        return Look(1, [1])

    async def export(uid: str) -> dict[str, Any]:
        return {"note": f"height {TYPED['height']}"}

    return CallbackSource(kept.SPECS[kept.PHOTO_ID], look, export)


async def _exports(a: AWorld, *extra: Any) -> tuple[dict[str, Any], dict[str, Any], AuditLog]:
    reg = PrivacyRegistry()
    for row in (*a.part.privacy, *extra):
        reg.register(row)
    audit = AuditLog()
    svc = PrivacyService(reg, audit=audit)
    one = await svc.export(UID, kept.FIGURE_ID, proof=None, fresh_left_s=60)
    every = await svc.export_all(UID, proof=None, fresh_left_s=60)
    return one, every, audit


async def test_his_measurements_are_in_his_own_figure_export_and_nowhere_else(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = await a_world()
    await a.service.put_body(UID, TYPED)
    await a.service.use_body(UID)
    others = kept.stand_ins("seeme", a.docs, a.ctx.s.firestore_prefix)  # C's rows, as at I1
    with caplog.at_level(logging.DEBUG):
        one, every, audit = await _exports(a, *others)
    figure = json.dumps(every["categories"][kept.FIGURE_ID])
    for n in NEEDLES:  # all six: his export is his own copy of his own data
        assert n.search(json.dumps(one["data"])) and n.search(figure), n.pattern
    assert _found([json.dumps({k: v for k, v in one.items() if k != "data"})]) == []
    assert outside_the_figure(every) == []  # no other category, not `unavailable`
    entries = (await audit.tail(10)).entries
    assert [e.tool for e in entries] == ["privacy_export", "privacy_export"]
    assert _found([json.dumps([e.tool, e.detail, e.args_hash]) for e in entries]) == []
    assert _found([_said(r) for r in caplog.records]) == []

    _, planted, _ = await _exports(a, _planted())  # the rule's positive control
    assert outside_the_figure(planted) != []
