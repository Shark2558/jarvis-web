# src/jarvis/homebridge/face_index.py
"""The face groups' centres in memory, for the nearest-group search (R11.1 O7; review C-code M5).
Ships in the home kit.

Each group's average face (a unit vector of 128 numbers) and its person id. `best` compares a
new face with every centre at once: one matrix-vector product with NumPy (loaded by name, as the
engine does: it is in the bridge image only), so 5,000 unnamed groups cost a fraction of a
millisecond per face. Without NumPy the same search runs in plain Python (slower, same answers).
The index is a cache of the database: the store rebuilds it from the database whenever a write
is rolled back (review C-code M2), so the two never disagree.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any

from jarvis.homebridge.face_types import DIM, dot


def numpy_or_none() -> Any:
    try:
        return importlib.import_module("numpy")
    except ImportError:
        return None


class CentreIndex:
    def __init__(self, np: Any = None) -> None:
        self._np = np
        self._ids: list[str] = []
        self._row: dict[str, int] = {}
        self._person: dict[str, str | None] = {}
        self._vecs: list[list[float]] = []  # without NumPy
        self._mat: Any = None
        self._reset()

    def _reset(self) -> None:
        self._ids, self._row, self._person, self._vecs = [], {}, {}, []
        if self._np is not None:
            self._mat = self._np.zeros((16, DIM), dtype=self._np.float32)

    def load(self, rows: Iterable[tuple[str, Sequence[float], str | None]]) -> None:
        """Start again from the database's rows (at start, and after a rolled-back write)."""
        self._reset()
        for gid, centre, person in rows:
            self.put(gid, centre, person)

    def __contains__(self, gid: object) -> bool:
        return gid in self._row

    def __len__(self) -> int:
        return len(self._ids)

    def person(self, gid: str) -> str | None:
        return self._person.get(gid)

    def unnamed(self) -> int:
        return sum(1 for p in self._person.values() if p is None)

    def put(self, gid: str, centre: Sequence[float], person: str | None) -> None:
        """Add a group, or move its centre."""
        row = self._row.get(gid)
        if row is None:
            row = len(self._ids)
            self._ids.append(gid)
            self._row[gid] = row
            if self._np is None:
                self._vecs.append(list(centre))
            elif row >= self._mat.shape[0]:
                grown = self._np.zeros((self._mat.shape[0] * 2, DIM), dtype=self._np.float32)
                grown[:row] = self._mat[:row]
                self._mat = grown
        if self._np is None:
            self._vecs[row] = list(centre)
        else:
            self._mat[row] = centre
        self._person[gid] = person

    def name(self, gid: str, person: str | None) -> None:
        if gid in self._row:
            self._person[gid] = person

    def drop(self, gid: str) -> None:
        row = self._row.pop(gid, None)
        if row is None:
            return
        self._person.pop(gid, None)
        last = len(self._ids) - 1
        moved = self._ids[last]
        if row != last:  # the last row fills the hole
            self._ids[row] = moved
            self._row[moved] = row
            if self._np is None:
                self._vecs[row] = self._vecs[last]
            else:
                self._mat[row] = self._mat[last]
        self._ids.pop()
        if self._np is None:
            self._vecs.pop()

    def best(
        self, vector: Sequence[float], taken: set[str], threshold: float
    ) -> tuple[str | None, float]:
        """The most alike group not in `taken` with a cosine of at least `threshold`."""
        if not self._ids:
            return None, 0.0
        if self._np is None:
            return self._best_plain(vector, taken, threshold)
        np = self._np
        scores = self._mat[: len(self._ids)] @ np.asarray(vector, dtype=np.float32)
        for gid in taken:
            if gid in self._row:
                scores[self._row[gid]] = -np.inf
        i = int(np.argmax(scores))
        cosine = float(scores[i])
        if cosine < threshold:
            return None, 0.0
        return self._ids[i], min(1.0, cosine)

    def _best_plain(
        self, vector: Sequence[float], taken: set[str], threshold: float
    ) -> tuple[str | None, float]:
        best, score = None, threshold
        for gid, centre in zip(self._ids, self._vecs, strict=True):
            cosine = dot(vector, centre)
            if cosine >= score and gid not in taken:
                best, score = gid, cosine
        return best, (min(1.0, score) if best is not None else 0.0)


__all__ = ["CentreIndex", "numpy_or_none"]
