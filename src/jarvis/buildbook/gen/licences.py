# src/jarvis/buildbook/gen/licences.py
"""R6 D2: the licence of every locked Python package, from `requirements.licences.json`.

The table is committed beside `requirements.lock`, so the Libraries section is a function of the
commit alone: the PR's `--check` (an editable install that resolves whatever versions pip picks)
and the deploy (the lock installed) build the same bytes, and a dist that happens not to be
installed can't silently turn into "not stated". `table_lookup` refuses a table out of step
with the lock (a version that differs, a package missing or extra), naming the packages and the
refresh. The refresh (`python -m jarvis.buildbook.gen --licences`, with the lock installed) reads
each dist's metadata (License-Expression -> License -> classifiers, `libs.licence_from_meta`) and
refuses if any installed version differs from the lock, so the table only ever holds the
licences of the exact locked versions.
"""

from __future__ import annotations

import importlib.metadata as md
import json
from collections.abc import Callable
from typing import Any

from jarvis.buildbook.gen.libs import LOCK, NOT_STATED, LicenceLookup, installed_licence, locked
from jarvis.buildbook.gen.repo import GenError, Repo

TABLE = "requirements.licences.json"
REFRESH = (
    f"refresh it: pip install --require-hashes -r {LOCK}, then "
    "python -m jarvis.buildbook.gen --licences"
)
SHOWN = 8  # package names named in an error
MetaLookup = Callable[[str], tuple[str | None, str]]  # name -> (installed version, licence)


def installed_meta(name: str) -> tuple[str | None, str]:
    try:
        version = md.version(name)
    except md.PackageNotFoundError:
        return None, NOT_STATED
    return version, installed_licence(name)


def _rows(repo: Repo) -> dict[str, tuple[str, str]]:
    raw = repo.text(TABLE)
    if raw is None:
        raise GenError(f"{TABLE} is missing (the licence of each locked package); {REFRESH}")
    try:
        dists = json.loads(raw)["dists"]
        rows = {str(n): (str(d["version"]), str(d["licence"])) for n, d in dists.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GenError(f"{TABLE} isn't a licence table; {REFRESH}") from None
    if any(not lic.strip() or len(lic) > 80 for _, lic in rows.values()):
        raise GenError(f"{TABLE}: every licence is one short line; {REFRESH}")
    return rows


def table_lookup(repo: Repo) -> LicenceLookup:
    """The licence of a locked package as the committed table records it."""
    pins = dict(locked(repo))
    if not pins:
        return lambda _name: NOT_STATED
    rows = _rows(repo)
    off = sorted(n for n, v in pins.items() if n not in rows or rows[n][0] != v)
    off += sorted(set(rows) - set(pins))
    if off:
        names = ", ".join(off[:SHOWN]) + (" …" if len(off) > SHOWN else "")
        raise GenError(f"{TABLE} is out of step with {LOCK} for {len(off)} package(s): {names}; "
                       f"{REFRESH}")  # fmt: skip
    return lambda name: rows[name][1]


def table_bytes(repo: Repo, meta: MetaLookup | None = None) -> bytes:
    """The table for the checkout's lock, from installed metadata that matches it exactly."""
    read = meta or installed_meta
    dists: dict[str, Any] = {}
    off = []
    for name, version in locked(repo):
        have, licence = read(name)
        if have != version:
            off.append(f"{name} {have or 'missing'} (locked {version})")
        dists[name] = {"version": version, "licence": licence}
    if off:
        raise GenError(f"the installed packages aren't {LOCK}'s: {'; '.join(off[:SHOWN])}; "
                       f"pip install --require-hashes -r {LOCK} first")  # fmt: skip
    doc = {"v": 1, "lock": LOCK, "dists": dists}
    return (json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_table(repo: Repo) -> int:
    """`--licences`: rewrite the checkout's table; returns the number of packages."""
    data = table_bytes(repo, installed_meta)
    (repo.root / TABLE).write_bytes(data)
    return len(json.loads(data)["dists"])


__all__ = ["REFRESH", "TABLE", "installed_meta", "table_bytes", "table_lookup", "write_table"]
