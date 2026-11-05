# src/jarvis/health/store.py
"""`{prefix}health_last/{uid}` = the last overall status and the last result per integration
(R4 D6), on the Docs port. One document per owner, overwritten by each check."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jarvis.health.models import HealthReport, ProbeResult
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, Set

log = get_logger(__name__)


class HealthStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}health_last"

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    async def last(self, uid: str) -> HealthReport | None:
        doc = await self._d.get(self._path(uid))
        if doc is None:
            return None
        try:
            results = tuple(ProbeResult.model_validate(v) for v in doc["results"].values())
            return HealthReport(overall=doc["overall"], results=results, at=doc["at"])
        except (KeyError, TypeError, AttributeError, ValidationError):
            log.warning("a stored health result was unreadable and is ignored")
            return None

    async def save(self, uid: str, report: HealthReport) -> None:
        data: dict[str, Any] = {
            "overall": report.overall,
            "at": report.at,
            "results": {r.key: r.model_dump(mode="json") for r in report.results},
        }
        await self._d.write([Set(self._path(uid), data)])


__all__ = ["HealthStore"]
