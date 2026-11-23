# evals/r6_3/writer.py
"""R6.3 eval, part B's `writer` suite (evals/r6_3/run.py; docs/plans/r6-3-book-content.md "Tests
and evals"), on in-memory fakes and the scripted brains through `jarvis.llm` (no model is ever
called). Each case is the named test of the same name in tests/test_r63_b_*.py, run here as it is
(a case passes when its test passes), plus `no_laptop_on_complete` (a cloud that is down for the
router too, so a writer built on the router's `complete()` would reach the ready laptop).

Its negative controls (the plan's `writer` row and each row's own), each applied alone; every one
must turn its own cases red, else the suite cannot fail and proves nothing:

    the hold as read-then-write (two parallel reserves pass the cap)        caps:parallel
    the YES check off                                    trial, pick (first without the 2nd YES)
    "update by itself" granted without its YES                                     authority
    a paid-tier Gemini offered at Rs 0                                             not_offered
    `write_text` built on the router's `complete()`                       no_laptop_on_complete
    the free carry only on Update                                                 three_seals
    no replace in the pages vault                                                    continue
    R6's Privacy hold not read by the pages vault                               delete_in_flight
    a pages entry written into R6's index                                     rollback_reader
    the run's YES carried to a new release                                        across_deploy
    the reference check off (the fake path is sealed)                            fake_path_refused
    one exemption of check (2) removed                                                precision
    `.claude/**` and `tests/**` read into a pack                                  never_reads
    row 379: the tier check off (a FAST page is sealed)                                row379
    trial: the cap check off                                                       trial
    deploy: `book_write` starting an update without his Update                      deploy
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "src", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
import test_r63_b_caps as t_caps  # noqa: E402
import test_r63_b_cases as t_cases  # noqa: E402
import test_r63_b_rows as t_rows  # noqa: E402
import test_r63_b_units as t_units  # noqa: E402
import test_r63_b_vault as t_vault  # noqa: E402
from r63_fake_brains import (  # noqa: E402
    CLAUDE_TIERS,
    FAKE_PATH_DRAFT,
    RecordingLaptop,
    ScriptedWriter,
    Step,
    claude_like,
    down,
    gemini_like,
    registry,
)
from r63_fakes import UID  # noqa: E402
from r63_fakes_b import seal_r6, service, steps  # noqa: E402

import jarvis.llm.write as write  # noqa: E402
from jarvis.buildbook.seal_index import BookCrypto  # noqa: E402
from jarvis.buildbook.writer import caps, checks, consent, job, packs, part, run, sweep, texts  # noqa: E402
from jarvis.buildbook.writer import vault as pages_vault  # noqa: E402
from jarvis.buildbook.writer.http import TrialIn  # noqa: E402
from jarvis.llm.base import LLMUnreachable  # noqa: E402
from jarvis.llm.brains import BrainSpec  # noqa: E402
from jarvis.llm.router import ModelTier  # noqa: E402
from jarvis.storage.docs import Set  # noqa: E402

PART = "writer"
BUILT = True
Case = Callable[[], Awaitable[None]]


async def _call(fn: Callable[..., Any], *args: Any) -> None:
    """Run a test function as a case (a fresh MonkeyPatch when it takes one)."""
    wants = "monkeypatch" in inspect.signature(fn).parameters
    with pytest.MonkeyPatch.context() as mp:
        got = fn(*args, monkeypatch=mp) if wants else fn(*args)
        if inspect.isawaitable(got):
            await got


def _of(fn: Callable[..., Any], *args: Any) -> Case:
    return lambda: _call(fn, *args)


class DownWriter(ScriptedWriter):
    """A cloud that is down for streams AND for the router's `complete()`."""

    async def complete(self, **kw: Any) -> Any:
        raise LLMUnreachable("the AI provider could not be reached")


async def _no_laptop_on_complete() -> None:
    laptop = RecordingLaptop()
    cloud = DownWriter("anthropic").push(*[down() for _ in range(20)])
    spec = BrainSpec(id="anthropic", label="Claude", provider=cloud, tiers=dict(CLAUDE_TIERS))
    built = service(brains=registry(spec, gemini_like(), laptop=laptop))
    est = await built.service.estimate(UID, "trial")
    await built.service.start_trial(UID, TrialIn(typed="YES", estimate_id=est.id))
    await built.service.step(UID)
    assert laptop.calls == 0, "the writer reached the laptop"


async def _fake_path_refused() -> None:
    claude = claude_like(*[Step(text=FAKE_PATH_DRAFT) for _ in range(20)])
    built = service(brains=registry(claude, gemini_like()))
    await seal_r6(built)
    await t_rows.pick(built)
    await t_rows.run_first(built)
    await steps(built)
    page = await built.service.page(UID, "pg_card_c01", None)
    assert page.meta is None, "a page citing a path that isn't there was sealed"


def _test(module: Any, start: str) -> Callable[..., Any]:
    """The one test function of `module` whose name starts with `start`."""
    found = [getattr(module, n) for n in dir(module) if n.startswith(start)]
    if len(found) != 1:
        raise LookupError(start)
    return found[0]


def _t(module: Any, start: str, *args: Any) -> Case:
    return _of(_test(module, start), *args)


BAD = (
    ("FAKE_PATH_DRAFT", "refs"),
    ("TYPED_NUMBER_DRAFT", "numbers"),
    ("EMAIL_DRAFT", "personal"),
    ("INVENTED_DRAFT", "invented"),
    ("PLANNED_OUTSIDE_DRAFT", "planned"),
    ("UNVERIFIED_DRAFT", "unverified"),
)
CASES: dict[str, Case] = {
    "row379": _t(t_rows, "test_row379"),
    "trial": _t(t_rows, "test_the_trial_spends_nothing"),
    "pick": _t(t_rows, "test_the_first_write_needs_the_pick"),
    "deploy": _t(t_rows, "test_nothing_spends_by_itself"),
    "authority": _t(t_rows, "test_spending_authority"),
    "row380_grows": _t(t_rows, "test_row380"),
    "no_laptop": _t(t_rows, "test_no_laptop_call"),
    "no_laptop_on_complete": _no_laptop_on_complete,
    "not_offered": _t(t_rows, "test_a_paid_tier_gemini"),
    "clocks_wait_for_a_measure": _t(t_rows, "test_the_clocks_start_no_call"),
    "meter_unreadable": _t(t_rows, "test_an_unreadable_meter"),
    "released_429": _t(t_cases, "test_a_429_is_released"),
    "cut_margin": _t(t_cases, "test_a_cut_call"),
    "length_stop": _t(t_cases, "test_a_length_stop"),
    "one_lease": _t(t_cases, "test_ten_steps_at_once"),
    "same_pack": _t(t_cases, "test_the_free_brain_gets_the_same_pack"),
    "no_ai": _t(t_cases, "test_no_ai_pauses"),
    "storage": _t(t_cases, "test_the_80_percent_storage_line"),
    "continue": _t(t_cases, "test_a_first_write_stopped_at_its_cap"),
    "three_seals": _t(t_cases, "test_three_seals"),
    "use_first": _t(t_cases, "test_an_update_over_the_release_cap"),
    "across_deploy": _t(t_cases, "test_a_run_across_a_deploy"),
    "auto_within_cap": _t(t_cases, "test_update_by_itself"),
    "slow_brain": _t(t_cases, "test_a_slow_brain"),
    "privacy_delete": _t(t_cases, "test_privacy_delete"),
    "never_reads": _t(t_cases, "test_a_pack_never_reads"),
    "fake_path_refused": _fake_path_refused,
    "caps:eight_then_refused": _t(t_caps, "test_eight_holds_fit"),
    "caps:parallel": _t(t_caps, "test_two_parallel_reserves"),
    "caps:gate": _t(t_caps, "test_the_80_percent_gate"),
    "caps:settle_old": _t(t_caps, "test_settle_old"),
    "caps:month_before": _t(t_caps, "test_the_month_before"),
    "vault:attach_replace": _t(t_vault, "test_attach_then_replace"),
    "rollback_reader": _t(t_vault, "test_the_pages_index_never_touches"),
    "delete_in_flight": _t(t_vault, "test_an_attach_in_flight"),
    "vault:storage_limit": _t(t_vault, "test_an_attach_past_the_storage_limit"),
    "checks:good": _t(t_units, "test_the_good_draft_passes"),
    **{
        f"checks:{code}": _t(t_units, "test_each_bad_draft", getattr(t_units, name), code)
        for name, code in BAD
    },
    **{
        f"precision:{pid}": _t(t_units, "test_the_precision_case_a_good_page", pid)
        for pid in sorted(t_units.PRECISION)
    },
    "hold_rs_11_84": _t(t_units, "test_the_hold_of_a_full_pack"),
    "grants": _t(t_units, "test_lowering_grants_nothing"),
}


async def _run(names: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        try:
            await CASES[name]()
            failures: list[str] = []
        except (Exception, pytest.fail.Exception) as exc:  # noqa: BLE001 - its result
            failures = [f"{type(exc).__name__}: {str(exc)[:200]}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run(list(CASES))


# ---- the negative controls ----------------------------------------------------------------------
Apply = Callable[[pytest.MonkeyPatch], None]


async def _racy_reserve(self: Any, uid: str, **kw: Any) -> Any:
    """The hold as read-then-write: read, check, then write outside any transaction."""
    months = self.keys_now()
    docs = [caps.decode(uid, await self.docs.get(self.path(uid, m))) for m in months]
    held = caps.Hold(
        inr=kw["hold_inr"], at=self.clock().isoformat(), run=kw["run"], page=kw["page"]
    )
    self._check(docs, held, kw["key"], kw["cap_inr"], kw["month_cap"], kw["gate"])
    await asyncio.sleep(0)
    this = docs[0]
    new = this.model_copy(update={"held_inr": this.held_inr + held.inr,
                                  "holds": {**this.holds, kw["call_id"]: held}})  # fmt: skip
    await self.docs.write([Set(self.path(uid, months[0]), caps.encode(new, self.clock()))])
    return caps.Held(uid, kw["call_id"], held.inr, months[0], kw["run"], kw["key"])


def _no_auto_words(mp: pytest.MonkeyPatch) -> None:
    real = consent.grants

    def grants(**kw: Any) -> tuple[str, ...]:
        return tuple(w for w in real(**kw) if "with no question asked" not in w)

    mp.setattr(consent, "grants", grants)


async def _on_complete(router: Any, **kw: Any) -> Any:
    """`write_text` built on the router's `complete()` (it may fall back to the laptop)."""
    got = await router.complete(tier=kw["tier"], system=kw["system"],
                                system_dynamic=kw["system_dynamic"], messages=kw["messages"],
                                max_tokens=kw["max_tokens"])  # fmt: skip
    model = router.resolve(kw["tier"])
    return write.Written(got.text, model, "anthropic", kw["tier"], got.usage, 0.0, 0.0, True, None)


def _attach_only(mp: pytest.MonkeyPatch) -> None:
    real = pages_vault.PagesVault.put

    async def put(self: Any, uid: str, rid: str, data: bytes, **kw: Any) -> Any:
        found = (await self.index(uid)).find(rid)
        return found if found is not None else await real(self, uid, rid, data, **kw)

    mp.setattr(pages_vault.PagesVault, "put", put)


def _into_r6_index(mp: pytest.MonkeyPatch) -> None:
    real = pages_vault.PagesVault.put

    async def put(self: Any, uid: str, rid: str, data: bytes, **kw: Any) -> Any:
        entry = await real(self, uid, rid, data, **kw)
        path = f"{self._prefix}book/{uid}"
        doc = await self._d.get(path)
        if doc is not None:
            crypto = BookCrypto(self._ring)
            index = json.loads(crypto.open_index(uid, doc["blob"]))
            index["pages"] = [{"release": rid}]
            blob = crypto.seal_index(uid, json.dumps(index).encode())
            await self._d.write([Set(path, {**doc, "blob": blob})])
        return entry

    mp.setattr(pages_vault.PagesVault, "put", put)


def _tier_off(mp: pytest.MonkeyPatch) -> None:
    real = run.judge

    def judge(w: Any, spec: Any, ctx: Any) -> Any:
        return real(dataclasses.replace(w, tier=ModelTier.BALANCED), spec, ctx)

    mp.setattr(run, "judge", judge)


async def _no_second_yes(self: Any, uid: str, typed: str) -> Any:
    doc = await self.store.doc(uid)
    if doc.run is not None and doc.run.state in run.ACTIVE:
        raise texts.WriterRefused("running")
    return doc


async def _eager_update(self: Any, uid: str) -> None:
    doc = await self.store.doc(uid)
    if doc.update_ready is not None and not (doc.run and doc.run.state in run.ACTIVE):
        est = await self.estimate(uid, "update")
        await self._start(uid, "update", est, est.pages, yes=False)


async def _free_carry_off(self: Any, uid: str, rid: str, kept: Any) -> int:
    return 0


def _set(target: Any, name: str, value: Any) -> Apply:
    return lambda mp: mp.setattr(target, name, value)


def _paid_gemini_offered(spec: Any, tier: ModelTier = ModelTier.BALANCED) -> bool:
    return bool(write.pricing.is_priced(write.model_of(spec, tier)))


NO_3D = tuple(n for n in checks.STANDARD_NAMES if n != "3D")
CONTROLS: tuple[tuple[str, Apply, tuple[str, ...]], ...] = (
    ("the hold as read-then-write", _set(caps.WriterCaps, "reserve", _racy_reserve),
     ("caps:parallel",)),
    ("the YES check off", _set(consent, "is_yes", lambda typed: True), ("trial", "pick")),
    ("update by itself accepted without its YES", _no_auto_words, ("authority",)),
    ("a paid-tier Gemini offered at Rs 0", _set(write, "offered", _paid_gemini_offered),
     ("not_offered",)),
    ("write_text built on complete()", _set(write, "write_text", _on_complete),
     ("no_laptop_on_complete",)),
    ("the carry run only on Update", _set(sweep.FreeWork, "carry", _free_carry_off),
     ("three_seals",)),
    ("no replace in the pages vault", _attach_only, ("continue",)),
    ("the Privacy hold check off", _set(pages_vault, "held_of", lambda doc: None),
     ("delete_in_flight",)),
    ("a pages entry written into R6's index", _into_r6_index, ("rollback_reader",)),
    ("the run's YES carried to a new release",
     _set(job.Steps, "same_release", lambda self, r: True), ("across_deploy",)),
    ("the reference check off", _set(checks, "_ref_ok", lambda span, ctx: True),
     ("fake_path_refused",)),
    ("one exemption of check (2) removed", _set(checks, "STANDARD_NAMES", NO_3D),
     ("precision:pg_card_c16",)),
    (".claude/** and tests/** in a pack", _set(packs, "readable", lambda path: True),
     ("never_reads",)),
    ("row 379: the tier check off", _tier_off, ("row379",)),
    ("trial: the cap check off", _set(caps, "run_of", lambda docs, key, kind: 0.0), ("trial",)),
    ("pick: first accepted without the second YES",
     _set(part.WriterService, "_ready_to_run", _no_second_yes), ("pick",)),
    ("deploy: book_write starting an update without his Update",
     _set(part.WriterService, "_auto_update", _eager_update), ("deploy",)),
)  # fmt: skip


@contextmanager
def _applied(apply: Apply) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        apply(mp)
        yield


async def control() -> dict[str, Any]:
    """Each control alone; it must turn every one of its cases red."""
    caught: list[str] = []
    missed: list[str] = []
    for name, apply, names in CONTROLS:
        with _applied(apply):
            got = await _run(list(names))
        red = [c["id"] for c in got if not c["passed"]]
        caught += red
        if len(red) != len(names):
            missed.append(name)
    return {
        "name": "; ".join(n for n, _, _ in CONTROLS),
        "suite_failed": not missed,
        "failed_cases": caught,
        "missed": missed,
    }
