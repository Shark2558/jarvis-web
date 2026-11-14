# evals/r14/selfwatch.py
"""R14 eval, Part B's suite (`selfwatch`, BUILT): self-health on fakes (docs/plans/r14-hardening.md
"Per item", B). The real watch (`jarvis.selfwatch.jobs.Watch`) with the real `ticks.run_jobs`
and observer, the real alert policy and storm (tests/r14_fakes_b.py `RingCounter`), memory
documents (or a store that is down), a settable clock:

- 3 failures in a row -> one `job_failing`, still one after 3 more hours of failing; recovery ->
  one `selfwatch_ok`; skips never count;
- a whole-Firestore outage (every job failing, every document call failing) -> at most 1 ring;
- the 5-minute clock unseen for 20 minutes (said by the tick) and no tick by 05:00 (said by the
  5-minute clock), each once per outage, and "back" once;
- the brief missed at its time + 60 minutes, not a minute before;
- 31 errors in an hour -> one alert, 30 -> none; nothing the alert's own sending logs counts;
- a spend spike (its rupees in the text), none before 7 days of history;
- a new revision told once, naming the version;
- nothing rings at 02:00 (held for the morning);
- every text is a fixed template: no logger name, no exception or vendor words, <= 300
  characters, rupees only in the spike.

Negative controls (each must fail its case): streak counting off (every failure a new streak)
-> "once per streak" fails; aggregation off (one alert per job, no hourly limit) -> the outage
rings more than once; the outcome ignored (a skip counts as a failure) -> `job_failing` on a skip.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r14_fakes_b import TWO_AM, UID, BrokenDocs, BWorld, FlakyJob, build_world  # noqa: E402

from jarvis.selfwatch import jobs, ledger  # noqa: E402
from jarvis.selfwatch.ledger import Streak  # noqa: E402
from jarvis.selfwatch.ports import SENDING  # noqa: E402
from jarvis.ticks import JobOutcome  # noqa: E402

PART = "selfwatch"
BUILT = True
IST = ZoneInfo("Asia/Kolkata")
Case = Callable[[], Awaitable[list[str]]]


def ist(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)


def _expect(failures: list[str], what: str, got: object, want: object) -> None:
    if got != want:
        failures.append(f"{what}: {got!r} (wanted {want!r})")


async def _runs(w: BWorld, n: int, *extra: Any) -> None:
    for _ in range(n):
        await w.watchdog(*extra)
        w.clock.advance(minutes=5)


# ---- the cases -----------------------------------------------------------------------------------
async def once_per_streak() -> list[str]:
    f: list[str] = []
    w = build_world()
    job = FlakyJob("vault_reminders")
    await _runs(w, 1, job)
    await _runs(w, 1, job)
    _expect(f, "after 2 failures", w.ring.kinds(), [])
    await _runs(w, 2, job)
    _expect(f, "after 3 failures", w.ring.kinds(), ["job_failing"])
    await _runs(w, 36, job)
    _expect(f, "after 3 more hours", w.ring.kinds(), ["job_failing"])
    return f


async def recovery_once() -> list[str]:
    f: list[str] = []
    w = build_world()
    job = FlakyJob("web")
    await _runs(w, 4, job)
    job.failing = False
    await _runs(w, 6, job)
    _expect(f, "kinds", w.ring.kinds(), ["job_failing", "selfwatch_ok"])
    _expect(f, "the recovery rings", [s.rang for s in w.ring.sent[1:]], [False])
    return f


async def skips_never_count() -> list[str]:
    f: list[str] = []
    w = build_world()
    for _ in range(10):
        w.watch.observe(JobOutcome("watchdog", "health_check", "skipped", 0.0))
        await w.watch.clock_job.run((UID,))
        w.clock.advance(minutes=5)
    _expect(f, "alerts after 10 skips", w.ring.kinds(), [])
    return f


async def outage_rings_once() -> list[str]:
    f: list[str] = []
    w = build_world(docs=BrokenDocs())
    names = ("health_check", "helpers_clock", "mobile_clock", "home_offline", "book_sweep")
    failing = [FlakyJob(n) for n in names]
    await _runs(w, 12, *failing)  # an hour
    rings = len(w.ring.rings())
    if rings > 1:
        f.append(f"{rings} rings in an hour of outage")
    if not w.ring.kinds() or w.ring.kinds()[0] != "job_failing":
        f.append(f"the outage was not said: {w.ring.kinds()}")
    return f


async def clock_gaps() -> list[str]:
    f: list[str] = []
    w = build_world(now=ist(16, 7, 0))
    await w.watchdog()
    w.clock.now = ist(16, 7, 30)
    await w.tick()
    w.clock.now = ist(16, 8, 0)
    await w.tick()
    _expect(f, "5-minute clock stopped, said once", w.ring.kinds(), ["clock_stopped"])
    w.clock.now = ist(16, 8, 2)
    await w.watchdog()
    _expect(f, "and back once", w.ring.kinds(), ["clock_stopped", "selfwatch_ok"])
    m = build_world(now=ist(15, 9, 0))
    await m.tick()
    for at in (ist(16, 4, 55), ist(16, 5, 0), ist(16, 5, 5)):
        m.clock.now = at
        await m.watchdog()
    _expect(f, "no tick by 05:00, said once", m.ring.kinds(), ["clock_stopped"])
    return f


async def brief_missed() -> list[str]:
    f: list[str] = []
    w = build_world(now=ist(16, 7, 59))
    w.brief.due_at = ist(16, 7, 0).astimezone(IST)
    await w.watchdog()
    _expect(f, "at 07:59", w.ring.kinds(), [])
    w.clock.now = ist(16, 8, 0)
    await w.watchdog()
    w.clock.now = ist(16, 8, 30)
    await w.watchdog()
    _expect(f, "at 08:00 and after", w.ring.kinds(), ["brief_missed"])
    return f


async def _errors(n: int) -> BWorld:
    w = build_world(now=ist(16, 12, 0))
    for _ in range(n):
        rec = logging.LogRecord("jarvis.vault.service", logging.ERROR, __file__, 1, "x", (), None)
        rec.created = ist(16, 12, 0).timestamp()
        w.watch.errors.handle(rec)
    await w.watchdog()
    return w


async def errors_piling() -> list[str]:
    f: list[str] = []
    _expect(f, "30 in an hour", (await _errors(30)).ring.kinds(), [])
    w = await _errors(31)
    _expect(f, "31 in an hour", w.ring.kinds(), ["errors_piling"])
    token = SENDING.set(True)
    try:  # what the notifier logs while an alert is sent never counts
        for _ in range(40):
            w.watch.errors.handle(
                logging.LogRecord("jarvis.notify.service", 40, "", 1, "x", (), None)
            )
    finally:
        SENDING.reset(token)
    _expect(f, "sending feeds the count", w.watch.errors.pending(), {})
    return f


async def spend_spike() -> list[str]:
    f: list[str] = []
    for days, want in ((10, ["spend_spike"]), (6, [])):
        w = build_world()
        total = 0.0
        for day in range(12 - days, 12):
            w.clock.now = ist(day, 4, 0)
            total += 400.0 if day == 11 else 20.0
            w.billing.inr[UID] = total
            await w.tick()
        _expect(f, f"{days - 2} days of history", w.ring.kinds(), want)
        if want and "₹400" not in w.ring.sent[0].text:
            f.append("the spike's rupees are not said")
    return f


async def new_revision() -> list[str]:
    f: list[str] = []
    w = build_world()
    await w.watchdog()  # the first run only remembers what is live
    w.watch.deploys = type(w.watch.deploys)(revision="jarvis-00042", version="14.1.0")
    await _runs(w, 3)
    _expect(f, "kinds", w.ring.kinds(), ["deploy_changed"])
    if w.ring.sent and "14.1.0" not in w.ring.sent[0].text:
        f.append("the version is not said")
    return f


async def nothing_rings_at_two() -> list[str]:
    f: list[str] = []
    w = build_world(now=TWO_AM)
    await w.watchdog()
    w.watch.deploys = type(w.watch.deploys)(revision="jarvis-00042", version="14.1.0")
    await _runs(w, 5, FlakyJob("web"))
    _expect(f, "said", sorted(set(w.ring.kinds())), ["deploy_changed", "job_failing"])
    _expect(f, "rang", len(w.ring.rings()), 0)
    return f


async def fixed_texts() -> list[str]:
    f: list[str] = []
    worlds = [build_world()]
    await _runs(worlds[0], 6, FlakyJob("vault_reminders"), FlakyJob("memory"))
    worlds.append(await _errors(31))
    for w in worlds:
        for s in w.ring.sent:
            bad = [n for n in ("jarvis.", "secret", "Error", "RuntimeError", "₹") if n in s.text]
            if bad or len(s.text) > 300:
                f.append(f"{s.kind}: {bad or len(s.text)}")
            if not s.sending:
                f.append(f"{s.kind} was sent without SENDING set")
    return f


CASES: dict[str, Case] = {
    "three_failures_one_alert": once_per_streak,
    "recovery_one_info": recovery_once,
    "skip_never_counts": skips_never_count,
    "outage_rings_once": outage_rings_once,
    "clock_gaps_once_per_outage": clock_gaps,
    "brief_missed_at_time_plus_60": brief_missed,
    "errors_31_an_hour": errors_piling,
    "spend_spike": spend_spike,
    "new_revision_once": new_revision,
    "nothing_rings_at_two": nothing_rings_at_two,
    "fixed_texts": fixed_texts,
}


async def _run(names: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for name in names:
        failures = await CASES[name]()
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run(tuple(CASES))


# ---- the negative controls -----------------------------------------------------------------------
@contextmanager
def _patched(module: Any, **attrs: Any) -> Iterator[None]:
    old = {k: getattr(module, k) for k in attrs}
    for k, v in attrs.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


def _no_counting(entry: Streak | None, outcome: str, at: datetime) -> Streak | None:
    """Streak counting off: every failure is a fresh streak, already "in a row"."""
    if outcome in ledger.FAILING:
        return Streak(99, at)
    return None if outcome == "ok" else entry


async def _controlled() -> dict[str, list[dict[str, Any]]]:
    got: dict[str, list[dict[str, Any]]] = {}
    with _patched(ledger, step=_no_counting):
        got["streak counting off"] = await _run(("three_failures_one_alert",))
    one_each = lambda names: [(n, (n,)) for n in names]  # noqa: E731
    with _patched(jobs, job_alerts=one_each, JOB_ALERT_EVERY=timedelta(0)):
        got["aggregation off"] = await _run(("outage_rings_once",))
    with _patched(ledger, FAILING=frozenset({"failed", "timed_out", "skipped"})):
        got["the outcome ignored"] = await _run(("skip_never_counts",))
    return got


async def control() -> dict[str, Any]:
    got = await _controlled()
    failed = {name: [r["id"] for r in rs if not r["passed"]] for name, rs in got.items()}
    return {
        "name": " + ".join(got),
        "suite_failed": all(failed.values()),
        "failed_cases": [case for ids in failed.values() for case in ids],
    }
