# src/jarvis/wardrobe/catalog/matching.py
"""The "seen before?" rule (docs/plans/r13-wardrobe.md D7; INV-05, INV-06; plan review L10), as
a pure reference: the PHONE runs it (D's scan module; the query fingerprint never leaves it), this
module states it once for A's tests and eval.

His saved fingerprints of ONE model (uint8 x 1,280) are centred by their mean (MobileNet's pooled
features are non-negative, so raw cosines of unrelated pieces are already high), compared by
cosine, each piece scored by the best of its views, at most 3 candidates offered. Starting bands on
the centred score (calibrated in the pilot): >= 0.80 "likely", 0.60-0.80 "maybe", below "new?";
two candidates of one type within 0.03 are "identical copies: read its label or tap which one".
Nothing is decided here: he taps.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

LIKELY, MAYBE, TWINS = 0.80, 0.60, 0.03
MAX_CANDIDATES = 3


@dataclass(frozen=True)
class Candidate:
    piece: str
    score: float
    band: str  # likely | maybe | new


def vector(v: str) -> list[float]:
    return [float(b) for b in base64.b64decode(v)]


def _centred(rows: Sequence[list[float]]) -> tuple[list[list[float]], list[float]]:
    dims = len(rows[0])
    mean = [sum(r[i] for r in rows) / len(rows) for i in range(dims)]
    return [[x - m for x, m in zip(r, mean, strict=True)] for r in rows], mean


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def band(score: float) -> str:
    return "likely" if score >= LIKELY else "maybe" if score >= MAYBE else "new"


def candidates(saved: Sequence[Mapping[str, str]], query: str) -> tuple[Candidate, ...]:
    """`saved`: his fingerprints ({p: piece, v: base64}); `query`: the scan's (base64)."""
    if not saved:
        return ()
    rows = [vector(e["v"]) for e in saved]
    centred, mean = _centred(rows)
    q = [x - m for x, m in zip(vector(query), mean, strict=True)]
    best: dict[str, float] = {}
    for e, row in zip(saved, centred, strict=True):
        best[e["p"]] = max(best.get(e["p"], -1.0), _cos(q, row))
    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_CANDIDATES]
    return tuple(Candidate(p, round(s, 4), band(s)) for p, s in ranked)


def twins(found: Sequence[Candidate]) -> bool:
    """Two near-identical candidates: ask for the label or a tap, never pick (INV-07, LND-04)."""
    return len(found) >= 2 and found[0].score - found[1].score <= TWINS


__all__ = ["LIKELY", "MAYBE", "TWINS", "Candidate", "band", "candidates", "twins", "vector"]
