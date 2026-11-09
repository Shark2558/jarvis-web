# evals/r4_needles/run.py
"""R4 I1 eval -- the cross-part needle scan (plan docs/plans/r4-vitals-health-people.md "Evals ->
Needles across all four parts"; brief W16). Each flow runs in the WHOLE app as `create_app` wires
it (tests/r3_app.py: the token key, a paired Telegram owner whose Bot API calls are recorded, a
linked home whose laptop is asleep) with the R4 parts on (api/r4_wiring.py).

    python evals/r4_needles/run.py --mock

Flows (cross-part):
  f01  a red vitals line AND a self-health fault during quiet hours BOTH ring on Telegram (urgent
       kinds are never held; the health fault needs two consecutive checks, D-B2). R5.1 D4: the
       fault is the AI key refused (the router's own record), and the asleep home laptop never
       rings from the systems check (the 5-minute watchdog owns that alert: no double ring)
  f02  no-AI mode answers vitals / systems / calendar with NO model call and refuses drafting with
       the fixed line
  f03  a bare private name is refused with no links (the web is a fake: no credit, no network)
  f04  a pasted key never appears in any output: the REST write and the gateway tool both refuse it
  f05  a child added to Faces is never named by vitals, the systems check, the brief or an alert
  f06  COLD START (I2 F1): the persisted mode is "none" and nothing is loaded yet; a direct
       /people/research call, the brief summariser, the recall sweep and the health probe make
       ZERO provider calls, and the health probe says the AI is switched off
  f07  FLAP (I2 F2): fifty health / vitals urgent alerts never leave the Telegram urgent budget
       short for a burglar ring (<= 6 of them ring; the next home_intruder is still delivered)

After every flow every Firestore document, log record and audit entry are scanned for the key
needle and the child's name; every Telegram text for the key and the child's name.

Negative controls (each must make the suite FAIL): a "debug" log line of the vitals write body
(before the guard); the urgent kinds demoted to "important" (then quiet hours hold them); the
people gate removed; the router's no-AI guard unbound (f06); the flap protection removed (f07).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
from pydantic import SecretStr  # noqa: E402
from r1d_common import finish  # noqa: E402
from r3_app import UID, H, R3App, r3_app, r3_settings  # noqa: E402
from research_fakes import PRIVATE_HITS, SATYA_HITS  # noqa: E402

import jarvis.notify.policy as policy_mod  # noqa: E402
import jarvis.notify.telegram_out as telegram_out_mod  # noqa: E402
import jarvis.vitals.api as vitals_api_mod  # noqa: E402
from jarvis.brief.summarize import Prepared as BriefPrepared  # noqa: E402
from jarvis.brief.summarize import Summarizer  # noqa: E402
from jarvis.llm.base import ToolCall  # noqa: E402
from jarvis.llm.router import ModelRouter, ModelTier  # noqa: E402
from jarvis.notify.models import NotifySettings, QuietHours  # noqa: E402
from jarvis.notify.ports import Signal  # noqa: E402
from jarvis.notify.store import NotifyStore  # noqa: E402
from jarvis.notify.storm import Storm  # noqa: E402
from jarvis.offline.rules import NO_AI_LINE  # noqa: E402
from jarvis.people.research import PeopleService  # noqa: E402
from jarvis.recall.extract import Extractor  # noqa: E402
from jarvis.recall.extract import Prepared as LearnPrepared  # noqa: E402
from jarvis.tools.gateway import GatewayOutcome  # noqa: E402
from jarvis.web.ports import PageText, SearchPage  # noqa: E402

CHILD = "Mira Needlechild"
KEY = "sk-ant-api03-NEEDLE7x9Qz" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
KEY_PARTS = (KEY, KEY[:20], KEY[-24:], "NEEDLE7x9Qz")
NAME_NEEDLES = (CHILD,)
PRIVATE_NAME = "Priya Nair"


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        extra = {k: v for k, v in record.__dict__.items() if k not in _STD}
        self.lines.append(f"{record.getMessage()} {json.dumps(extra, default=str)}")


_STD = set(logging.LogRecord("x", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


@contextmanager
def captured() -> Any:
    cap = Capture()
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        yield cap
    finally:
        root.removeHandler(cap)


def scan(w: R3App, cap: Capture, needles: tuple[str, ...]) -> list[str]:
    """Where any needle was found: documents, log records, audit entries, Telegram texts."""
    found: list[str] = []
    docs = json.dumps(w.docs._data, default=str)  # noqa: SLF001
    audit = json.dumps(
        [e.model_dump(mode="json") for e in w.state.gateway.audit._entries],  # noqa: SLF001
        default=str,
    )
    logs = "\n".join(cap.lines)
    texts = "\n".join(w.sent_texts())
    for n in needles:
        places = (("document", docs), ("log", logs), ("audit", audit), ("telegram", texts))
        for where, text in places:
            if n in text:
                found.append(f"{n[:12]}... in a {where}")
    return found


class FakeWeb:
    """A search vendor that answers every query with the private-person hits; no network."""

    name = "fake"

    async def search(self, query: str, *, max_results: int, topic: str, days: Any) -> SearchPage:
        return SearchPage(hits=list(PRIVATE_HITS), credits=1)

    async def extract(self, url: str) -> PageText:
        return PageText(url=url)

    async def aclose(self) -> None:
        return None


def _settings() -> Any:
    return r3_settings(tavily_api_key=SecretStr("tvly-needles-fake"))


async def _quiet_all_day(w: R3App) -> None:
    store: NotifyStore = w.state.notify_store
    await store.update(
        UID,
        lambda s: NotifySettings.model_validate(
            s.model_copy(update={"quiet": QuietHours(on=True, start="00:00", end="23:59")})
        ),
    )


async def _add_child(w: R3App) -> str:
    r = await w.client.post(
        "/v1/faces",
        json={
            "name": CHILD,
            "relation": "family",
            "child": True,
            "vip": True,
            "given_by": "parent_guardian",
            "consent_version": "fc1",
            "confirm": True,
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["person"]["id"])


async def _chat(w: R3App, text: str) -> str:
    r = await w.client.post("/v1/chat", json={"message": text, "user_id": UID})
    assert r.status_code == 200, r.text
    return str(r.json()["reply"])


def _health_job(w: R3App) -> Any:
    job = w.state.tick_jobs[-1]
    job._every_s = 0.0  # noqa: SLF001 - the flow checks twice in a row; lift the due-gate
    return job


def _model_calls(w: R3App) -> int:
    return len(w.state.brains.default.provider.calls)


# ---- the flows ---------------------------------------------------------------------------------

Flow = Callable[[R3App], Awaitable[list[str]]]


async def f01_red_vitals_and_health_fault(w: R3App) -> list[str]:
    f: list[str] = []
    await _quiet_all_day(w)
    r = await w.client.put(
        "/v1/vitals/keys",
        json={"id": "brave", "label": "Brave key", "kind": "key", "expires_at": "2020-01-01"},
        headers=H,
    )
    if r.status_code != 200:
        f.append(f"vitals write refused: {r.status_code} {r.text}")
    await w.state.tick_jobs[-2].run([UID])  # vitals_poll
    router = w.state.brains.router_for(w.state.brains.default.id)
    router._last = "refused"  # noqa: SLF001 - the last real call was refused (no model call here)
    health = _health_job(w)  # the real job; only its 15-minute due-gate is lifted here
    await health.run([UID])  # health_check (1st down; the home has never reported either)
    await health.run([UID])  # 2nd consecutive down -> health_fault
    texts = w.sent_texts()
    faults = [t for t in texts if t.startswith("Attention")]
    if not any("Vitals" in t and "Brave key" in t for t in texts):
        f.append(f"the red vitals line did not ring through quiet hours: {texts}")
    if not any("AI brain" in t for t in faults):
        f.append(f"the health fault did not ring through quiet hours: {texts}")
    if any("home" in t.lower() or "laptop" in t.lower() for t in faults):
        f.append(f"the home rang from the systems check too (D4: the watchdog owns it): {faults}")
    names = [j.name for j in w.state.tick_jobs]
    if names[-2:] != ["vitals_poll", "health_check"]:
        f.append(f"tick jobs: {names}")
    return f


async def f02_no_ai_mode_free_skills(w: R3App) -> list[str]:
    f: list[str] = []
    r = await w.client.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=H)
    if r.status_code != 200:
        return [f"brain mode flip refused: {r.text}"]
    before = _model_calls(w)
    systems = await _chat(w, "run a systems check")
    vitals = await _chat(w, "show my vitals")
    calendar = await _chat(w, "what's on my calendar today?")
    draft = await _chat(w, "draft an email to the vendor about the delay")
    if systems == NO_AI_LINE or not ("systems" in systems.lower() or "Attention" in systems):
        f.append(f"systems check not answered: {systems!r}")
    if vitals == NO_AI_LINE or "needs the AI" in vitals:
        f.append(f"vitals not answered: {vitals!r}")
    if calendar == NO_AI_LINE:  # no Google here: a fixed "not available" line is the right answer
        f.append(f"calendar sent to the AI line: {calendar!r}")
    if draft != NO_AI_LINE:
        f.append(f"drafting was not refused with the fixed line: {draft!r}")
    if _model_calls(w) != before:
        f.append("a model was called in no-AI mode")
    return f


async def f03_a_bare_private_name_is_refused_with_no_links(w: R3App) -> list[str]:
    f: list[str] = []
    w.state.web.provider = FakeWeb()
    r = await w.client.post("/v1/people/research", json={"name": PRIVATE_NAME}, headers=H)
    if r.status_code != 422:
        f.append(f"not refused: {r.status_code} {r.text[:200]}")
    body = r.json()
    if "linkedin.com" in r.text or "instagram.com" in r.text or body.get("profiles"):
        f.append("links were returned for a private individual")
    last = await w.client.get("/v1/people/last", headers=H)
    if last.json().get("dossier"):
        f.append("a refused dossier was cached to open later")
    # the no-AI tool path refuses too, with no links
    await w.client.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=H)
    reply = await _chat(w, f"research {PRIVATE_NAME}")
    if "linkedin.com" in reply or "instagram.com" in reply:
        f.append(f"the no-AI route handed out links: {reply!r}")
    return f


async def f04_a_pasted_key_never_appears_in_any_output(w: R3App) -> list[str]:
    f: list[str] = []
    r = await w.client.put(
        "/v1/vitals/keys",
        json={"id": "brave", "label": "Brave key", "kind": "key", "note": f"token {KEY}"},
        headers=H,
    )
    if r.status_code != 422:
        f.append(f"a key value was accepted: {r.status_code}")
    if any(p in r.text for p in KEY_PARTS):
        f.append("the 422 echoed the key")
    gw = w.state.gateway
    call = ToolCall(
        id="c1", name="vitals_set_key", arguments={"id": "k2", "label": f"my {KEY}", "kind": "key"}
    )
    out = await gw.execute(call, scope=UID)
    if out.outcome is GatewayOutcome.EXECUTED:
        f.append("the gateway stored a key value")
    board = (await w.client.get("/v1/vitals", headers=H)).text
    if any(p in board for p in KEY_PARTS):
        f.append("the board shows the key")
    return f


async def f05_a_child_is_never_named(w: R3App) -> list[str]:
    f: list[str] = []
    await _add_child(w)
    health_job = _health_job(w)
    await health_job.run([UID])
    await health_job.run([UID])
    health = (await w.client.post("/v1/health/run", headers=H)).text
    board = (await w.client.get("/v1/vitals", headers=H)).text
    brief = await w.state.brief.generate(UID, trigger="manual", force=True)
    text = brief.brief.text if brief.brief is not None else ""
    for where, out in (("health", health), ("vitals", board), ("brief", text)):
        if CHILD in out:
            f.append(f"child named in {where}")
    return f


class PublicWeb(FakeWeb):
    """The same fake vendor, answering with a public figure (so research may reach the model)."""

    async def search(self, query: str, *, max_results: int, topic: str, days: Any) -> SearchPage:
        return SearchPage(hits=list(SATYA_HITS), credits=1)


async def _go_cold(w: R3App) -> None:
    """Persisted "none", nothing loaded: what a freshly started instance sees before any read."""
    await w.state.brain_mode.set(UID, "none", by="needles")
    w.state.brain_mode._cache.clear()  # noqa: SLF001


async def f06_cold_start_makes_no_model_call(w: R3App) -> list[str]:
    f: list[str] = []
    w.state.web.provider = PublicWeb()
    brains = w.state.brains
    spec = brains.default
    before = _model_calls(w)
    await _go_cold(w)
    r = await w.client.post(
        "/v1/people/research", json={"name": "Satya Nadella", "context": "Microsoft"}, headers=H
    )
    if r.status_code not in (200, 422):
        f.append(f"people research: {r.status_code} {r.text[:200]}")
    await _go_cold(w)
    block = await Summarizer(brains).run(BriefPrepared(spec, spec.tiers[ModelTier.FAST], "x"))
    if block.lines:
        f.append("the brief summariser produced lines while the AI was off")
    await _go_cold(w)
    out = await Extractor(brains).run(LearnPrepared(spec, spec.tiers[ModelTier.FAST], "x"))
    if out.extraction is not None:
        f.append("the recall sweep extracted while the AI was off")
    await _go_cold(w)
    health = (await w.client.post("/v1/health/run", headers=H)).text
    if "switched off" not in health:
        f.append(f"the health report does not say the AI is switched off: {health[:200]}")
    if _model_calls(w) != before:
        f.append(f"{_model_calls(w) - before} provider call(s) on a cold start with the AI off")
    return f


async def f07_flapping_never_starves_a_burglar(w: R3App) -> list[str]:
    f: list[str] = []
    notify = w.state.notify
    for i in range(50):
        kind = "health_fault" if i % 2 == 0 else "vitals_critical"
        await notify.notify(
            UID, Signal(source="system", kind=kind, subject=f"k{i}"), f"Attention, Sir: item {i}."
        )
    flapped = [t for t in w.sent_texts() if t.startswith("Attention, Sir: item")]
    if len(flapped) > 6:
        f.append(f"{len(flapped)} health / vitals alerts rang in one hour (cap is 6)")
    await notify.notify(
        UID, Signal(source="home", kind="home_intruder", camera="gate"), "Burglar at the gate."
    )
    if not any("Burglar at the gate" in t for t in w.sent_texts()):
        f.append("the burglar ring was not delivered after the flapping alerts")
    return f


FLOWS: list[tuple[str, Flow]] = [
    ("f01_red_vitals_and_health_fault_ring_in_quiet_hours", f01_red_vitals_and_health_fault),
    ("f02_no_ai_mode_answers_free_skills_refuses_drafting", f02_no_ai_mode_free_skills),
    ("f03_bare_private_name_refused_no_links", f03_a_bare_private_name_is_refused_with_no_links),
    ("f04_pasted_key_never_in_any_output", f04_a_pasted_key_never_appears_in_any_output),
    ("f05_child_never_named", f05_a_child_is_never_named),
    ("f06_cold_start_with_persisted_none_makes_no_model_call", f06_cold_start_makes_no_model_call),
    ("f07_flapping_alerts_never_starve_a_burglar_ring", f07_flapping_never_starves_a_burglar),
]


async def one(case: str, flow: Flow) -> dict[str, Any]:
    failures: list[str] = []
    try:
        async with r3_app(_settings()) as w:
            with captured() as cap:
                logging.getLogger("jarvis.vitals.store").info("r4 needles canary")
                failures += await flow(w)
                failures += scan(w, cap, KEY_PARTS + NAME_NEEDLES)
                if not any("r4 needles canary" in line for line in cap.lines):
                    failures.append("the log capture saw nothing: the scan would be blind")
    except Exception as exc:  # noqa: BLE001 - a crash is a failed case, with its type
        failures.append(f"crashed: {type(exc).__name__}: {exc}")
    return {"id": case, "passed": not failures, "failures": failures}


async def run_all() -> list[dict[str, Any]]:
    return [await one(case, flow) for case, flow in FLOWS]


# ---- the negative controls ---------------------------------------------------------------------


async def _control_log_the_vitals_write() -> list[str]:
    """A debug line logging every vitals write BODY (before the guard) must fail the suite."""
    original = vitals_api_mod.Provider
    leak = logging.getLogger("jarvis.vitals.api")

    class Leaky(original):  # type: ignore[misc,valid-type]
        @classmethod
        def model_validate(cls, obj: Any, *a: Any, **k: Any) -> Any:
            leak.info("vitals write body", extra={"body": obj})
            return original.model_validate(obj, *a, **k)

    vitals_api_mod.Provider = Leaky  # type: ignore[misc]
    try:
        return [r["id"] for r in await run_all() if not r["passed"]]
    finally:
        vitals_api_mod.Provider = original  # type: ignore[misc]


async def _control_demote_the_urgent_kinds() -> list[str]:
    """vitals_critical / health_fault as "important" are held in quiet hours: f01 must fail."""
    original = policy_mod.urgency_of

    def demoted(kind: str) -> Any:
        if kind in ("vitals_critical", "health_fault"):
            return "important"
        return original(kind)

    policy_mod.urgency_of = demoted  # type: ignore[assignment]
    try:
        return [r["id"] for r in await run_all() if not r["passed"]]
    finally:
        policy_mod.urgency_of = original  # type: ignore[assignment]


async def _control_remove_the_people_gate() -> list[str]:
    """With the verification gate off a bare private name gets links: f03 must fail."""
    original = PeopleService.__init__

    def ungated(self: Any, *a: Any, **k: Any) -> None:
        original(self, *a, **{**k, "gate_enabled": False})

    PeopleService.__init__ = ungated  # type: ignore[method-assign]
    try:
        return [r["id"] for r in await run_all() if not r["passed"]]
    finally:
        PeopleService.__init__ = original  # type: ignore[method-assign]


async def _control_unbind_the_router_guard() -> list[str]:
    """With the router's no-AI guard a no-op, the cold-start background callers reach the
    provider: f06 must fail."""
    original = ModelRouter.bind_blocked

    def unbound(self: Any, blocked: Any, refresh: Any = None) -> None:
        return None

    ModelRouter.bind_blocked = unbound  # type: ignore[method-assign]
    try:
        return [r["id"] for r in await run_all() if not r["passed"]]
    finally:
        ModelRouter.bind_blocked = original  # type: ignore[method-assign]


async def _control_remove_the_flap_protection() -> list[str]:
    """With no gap / cap in the storm and health / vitals rings drawing from the urgent budget,
    fifty flaps starve the burglar ring: f07 must fail."""
    original_soft = Storm._soft_ok  # noqa: SLF001
    original_kinds = telegram_out_mod.SOFT_URGENT_KINDS

    def always(self: Any, uid: str, signal: Any, now: Any) -> Any:
        from jarvis.notify.storm import Verdict

        return Verdict(True)

    Storm._soft_ok = always  # type: ignore[method-assign]  # noqa: SLF001
    telegram_out_mod.SOFT_URGENT_KINDS = frozenset()
    try:
        return [r["id"] for r in await run_all() if not r["passed"]]
    finally:
        Storm._soft_ok = original_soft  # type: ignore[method-assign]  # noqa: SLF001
        telegram_out_mod.SOFT_URGENT_KINDS = original_kinds


async def controls() -> dict[str, Any]:
    logged = await _control_log_the_vitals_write()
    demoted = await _control_demote_the_urgent_kinds()
    ungated = await _control_remove_the_people_gate()
    unbound = await _control_unbind_the_router_guard()
    unflapped = await _control_remove_the_flap_protection()
    return {
        "name": "debug_log_vitals_write + demote_urgent_kinds + remove_people_gate"
        " + unbind_router_guard + remove_flap_protection",
        "suite_failed": all(bool(x) for x in (logged, demoted, ungated, unbound, unflapped))
        and any(c.startswith("f06") for c in unbound)
        and any(c.startswith("f07") for c in unflapped),
        "failed_cases": {
            "debug_log_vitals_write": logged,
            "demote_urgent_kinds": demoted,
            "remove_people_gate": ungated,
            "unbind_router_guard": unbound,
            "remove_flap_protection": unflapped,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    results = asyncio.run(run_all())
    return finish(HERE, "r4_needles", results, asyncio.run(controls()))


if __name__ == "__main__":
    sys.exit(main())
