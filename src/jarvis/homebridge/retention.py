# src/jarvis/homebridge/retention.py
"""Face-attempt retention at home (R3 D13, D7). Runs on the laptop; stdlib only (home kit).

Frigate keeps cropped "attempts" of faces it saw. Strangers' crops must not pile up: an attempt
with no enrolled person's id in its name goes after 72 hours; one with an id, and the doorstep
state-classification attempts, after 7 days. A deleted person's attempts go at once
(`delete_for`). Only regular image files directly inside the configured folder are touched; links
are never followed; nothing outside the folder is ever deleted. A folder that holds per-person
subfolders (`fp_<id>/`, Frigate's enrolled library) is refused: it is not an attempts folder.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
UNKNOWN_HOURS = 72
KEPT_DAYS = 7
IMAGE = re.compile(r"\.(webp|jpe?g|png)$", re.IGNORECASE)
PERSON_IN_NAME = re.compile(r"fp_[0-9a-f]{12}")
PERSON_ID = re.compile(r"fp_[0-9a-f]{12}")
LIBRARY_DIR = PERSON_ID


@dataclass(frozen=True)
class Swept:
    unknown: int
    kept: int
    doorstep: int


class Retention:
    def __init__(
        self,
        attempts_dir: Path | None,
        doorstep_dir: Path | None = None,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._attempts = attempts_dir
        self._doorstep = doorstep_dir
        self._now = now

    @staticmethod
    def _holds_library(root: Path) -> bool:
        try:
            return any(LIBRARY_DIR.fullmatch(e.name) for e in os.scandir(root) if e.is_dir())
        except OSError:
            return False

    @property
    def misconfigured(self) -> bool:
        """A configured folder that is really the enrolled library: never swept."""
        roots = (self._attempts, self._doorstep)
        return any(r is not None and r.is_dir() and self._holds_library(r) for r in roots)

    @property
    def ready(self) -> bool:
        """The attempts folder exists, is safe to sweep and this process may delete in it
        (deleting a file needs write and search on its folder; review S5: Frigate's folders are
        root's unless the kit shares them). When False, crops may remain on disk, so a delete
        must not be reported as done."""
        a = self._attempts
        return (
            a is not None
            and a.is_dir()
            and not a.is_symlink()
            and os.access(a, os.W_OK | os.X_OK)
            and not self.misconfigured
        )

    @staticmethod
    def _files(root: Path | None) -> list[Path]:
        if root is None or not root.is_dir() or root.is_symlink() or Retention._holds_library(root):
            return []
        out: list[Path] = []
        for entry in os.scandir(root):
            path = Path(entry.path)
            if IMAGE.search(entry.name) and path.is_file() and not path.is_symlink():
                out.append(path)
        return out

    def _drop_older(self, files: list[Path], hours: float) -> int:
        cutoff = self._now() - hours * 3600
        gone = 0
        for path in files:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    gone += 1
            except OSError:
                continue
        return gone

    def sweep(self) -> Swept:
        files = self._files(self._attempts)
        unknown = [p for p in files if not PERSON_IN_NAME.search(p.name)]
        kept = [p for p in files if PERSON_IN_NAME.search(p.name)]
        return Swept(
            unknown=self._drop_older(unknown, UNKNOWN_HOURS),
            kept=self._drop_older(kept, KEPT_DAYS * 24),
            doorstep=self._drop_older(self._files(self._doorstep), KEPT_DAYS * 24),
        )

    def delete_for(self, person_id: str) -> tuple[int, int]:
        """Every attempt crop of this person, now: (deleted, could not be deleted). Review H4: a
        failure is counted and said (plain words, no path), never swallowed."""
        if not PERSON_ID.fullmatch(person_id):
            return 0, 0
        gone = failed = 0
        for path in self._files(self._attempts):
            if person_id in path.name:
                try:
                    path.unlink()
                    gone += 1
                except OSError as exc:
                    failed += 1
                    log.warning(
                        "a face picture could not be deleted (check the kit's folder sharing)",
                        extra={"error": type(exc).__name__},
                    )
        return gone, failed

    def remaining_for(self, person_id: str) -> int:
        """How many of this person's crops are still in the folder (a delete re-checks)."""
        if not PERSON_ID.fullmatch(person_id):
            return 0
        return sum(1 for p in self._files(self._attempts) if person_id in p.name)


__all__ = ["KEPT_DAYS", "UNKNOWN_HOURS", "Retention", "Swept"]
