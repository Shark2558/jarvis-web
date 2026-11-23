"""Split the browser suite across parallel CI machines (the owner's ask of 23 Nov 2026).

Every test file goes to exactly one shard, so a file's module-scoped servers start once. Files are
placed largest first on the shard with the fewest tests so far (ties to the lower shard), which is
deterministic: every machine computes the same plan from the same collected tests.
"""

from __future__ import annotations

from collections.abc import Mapping

ENV = "JARVIS_BROWSER_SHARD"


def parse(spec: str) -> tuple[int, int]:
    """Read "i/n" (1-based). Raise ValueError on anything else."""
    parts = spec.strip().split("/")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"{ENV} must look like 1/4, got {spec!r}")
    index, total = int(parts[0]), int(parts[1])
    if total < 1 or not 1 <= index <= total:
        raise ValueError(f"{ENV} must be i/n with 1 <= i <= n, got {spec!r}")
    return index, total


def assign(counts: Mapping[str, int], total: int) -> dict[str, int]:
    """Map each file to a shard number 1..total, balancing the number of tests."""
    if total < 1:
        raise ValueError("total must be at least 1")
    loads = [0] * total
    plan: dict[str, int] = {}
    for name in sorted(counts, key=lambda n: (-counts[n], n)):
        shard = min(range(total), key=lambda s: (loads[s], s))
        plan[name] = shard + 1
        loads[shard] += counts[name]
    return plan
