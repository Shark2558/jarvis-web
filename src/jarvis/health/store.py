# src/jarvis/health/store.py
"""`{prefix}health_last/{uid}` = the last overall status and the last result per integration
(R4 D6), on the Docs port. One document per owner, overwritten by each check."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jarvis.health.models import HealthReport, HealthState, ProbeResult, Status
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, Set

log = get_logger(__name__)


class HealthStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}health_last"

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    async def state(self, uid: str) -> HealthState | None:
        doc = await self._d.get(self._path(uid))
        if doc is None:
            return None
        try:
            results = tuple(ProbeResult.model_validate(v) for v in doc["results"].values())
            report = HealthReport(overall=doc["overall"], results=results, at=doc["at"])
            alerted = {str(k): _status(v) for k, v in doc.get("alerted", {}).items()}
            streaks = {str(k): _streak(v) for k, v in doc.get("streaks", {}).items()}
        except (KeyError, TypeError, AttributeError, ValueError, IndexError, ValidationError):
            log.warning("a stored health result was unreadable and is ignored")
            return None
        return HealthState(report=report, alerted=alerted, streaks=streaks)

    async def last(self, uid: str) -> HealthReport | None:
        st = await self.state(uid)
        return None if st is None else st.report

    async def save(self, uid: str, state: HealthState) -> None:
        report = state.report
        data: dict[str, Any] = {
            "overall": report.overall,
            "at": report.at,
            "results": {r.key: r.model_dump(mode="json") for r in report.results},
            "alerted": dict(state.alerted),
            "streaks": {
                k: [st, n, first, last] for k, (st, n, first, last) in state.streaks.items()
            },
        }
        await self._d.write([Set(self._path(uid), data)])


def _time(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("bad time")
    return float(value)


def _streak(v: Any) -> tuple[Status, int, float | None, float | None]:
    """[status, count] (before R5.1) or [status, count, first_at, last_counted_at]."""
    first = _time(v[2]) if len(v) > 2 else None
    last = _time(v[3]) if len(v) > 3 else None
    return (_status(v[0]), int(v[1]), first, last)


def _status(value: object) -> Status:
    if value not in ("ok", "degraded", "down"):
        raise ValueError("unknown status")
    return value


__all__ = ["HealthStore"]
