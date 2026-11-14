# src/jarvis/selfwatch/deploys.py
"""A new version live (docs/plans/r14-hardening.md D5): Cloud Run's `K_REVISION`
(`Settings.cloud_run_revision`) or `jarvis.__version__` differs from what
`{prefix}selfwatch/deploy` holds. Checked once per process (the first 5-minute run after a
start); told once per revision (the caller's claim, cause = revision and version), naming the
version only.

- The very first run only remembers what is live: with nothing stored there is nothing to
  compare (R14's own first deploy says nothing).
- A new revision is remembered (`remember`) only once its alert is settled: one that reached
  nobody is found new again at the next run and told then.
- A revision seen before (the same one after a restart, or the old one still answering while a
  deploy moves traffic) is never told again and never overwrites the newer one: the document
  keeps the last `MAX_SEEN` revisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.storage.docs import Docs, DocTx

MAX_SEEN = 10


class DeployWatch:
    def __init__(self, *, revision: str | None, version: str, prefix: str = "jarvis_") -> None:
        self._revision = revision
        self._version = version
        self._path = f"{prefix}selfwatch/deploy"
        self.checked = False

    @property
    def key(self) -> str:
        return f"{self._revision or '-'}|{self._version}"

    async def check(self, docs: Docs, now: datetime) -> tuple[str, str] | None:
        """(cause, version) when this process is a new revision to tell (not remembered yet:
        `remember` after the alert); None otherwise. Raises when the store is down (tried
        again at the next run)."""
        if self.checked:
            return None

        async def fn(tx: DocTx) -> bool:
            doc: dict[str, Any] | None = await tx.get(self._path)
            if doc is None:
                self._keep(tx, None, now)  # the first run: nothing to compare
                return False
            return self.key not in _seen(doc)

        new = await docs.transaction(fn)
        self.checked = not new
        return (self.key, self._version) if new else None

    async def remember(self, docs: Docs, now: datetime) -> None:
        """This revision is live and was told: never told again. Raises when the store is down."""

        async def fn(tx: DocTx) -> None:
            self._keep(tx, await tx.get(self._path), now)

        await docs.transaction(fn)
        self.checked = True

    def _keep(self, tx: DocTx, doc: dict[str, Any] | None, now: datetime) -> None:
        seen = _seen(doc or {})
        if self.key in seen:
            return
        body = {"revision": self._revision, "version": self._version, "at": now.isoformat()}
        tx.set(self._path, {**body, "seen": [*seen, self.key][-MAX_SEEN:]})

    @staticmethod
    async def current(docs: Docs, *, prefix: str = "jarvis_") -> dict[str, Any]:
        """The live revision and version as last stored (for the status route)."""
        doc = await docs.get(f"{prefix}selfwatch/deploy") or {}
        return {"revision": doc.get("revision"), "version": doc.get("version"), "at": doc.get("at")}


def _seen(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("seen")
    return [s for s in raw if isinstance(s, str)] if isinstance(raw, list) else []


__all__ = ["MAX_SEEN", "DeployWatch"]
