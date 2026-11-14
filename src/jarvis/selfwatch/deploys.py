# src/jarvis/selfwatch/deploys.py
"""A new version live (docs/plans/r14-hardening.md D5): Cloud Run's `K_REVISION`
(`Settings.cloud_run_revision`) or `jarvis.__version__` differs from what
`{prefix}selfwatch/deploy` holds. Checked once per process (the first 5-minute run after a
start); told once per revision (the caller's claim, cause = revision and version), naming the
version only.

- The very first run only remembers what is live: with nothing stored there is nothing to
  compare (R14's own first deploy says nothing).
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
        """(cause, version) when this process is a new revision to tell; None otherwise. Raises
        when the store is down (tried again at the next run)."""
        if self.checked:
            return None
        key = self.key

        async def fn(tx: DocTx) -> bool:
            doc: dict[str, Any] | None = await tx.get(self._path)
            seen = [s for s in (doc or {}).get("seen") or [] if isinstance(s, str)]
            if key in seen:
                return False
            body = {"revision": self._revision, "version": self._version, "at": now.isoformat()}
            tx.set(self._path, {**body, "seen": [*seen, key][-MAX_SEEN:]})
            return doc is not None

        new = await docs.transaction(fn)
        self.checked = True
        return (key, self._version) if new else None

    @staticmethod
    async def current(docs: Docs, *, prefix: str = "jarvis_") -> dict[str, Any]:
        """The live revision and version as last stored (for the status route)."""
        doc = await docs.get(f"{prefix}selfwatch/deploy") or {}
        return {"revision": doc.get("revision"), "version": doc.get("version"), "at": doc.get("at")}


__all__ = ["MAX_SEEN", "DeployWatch"]
