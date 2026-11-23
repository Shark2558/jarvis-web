# src/jarvis/buildbook/writer/fill.py
"""R6.3 D10 (2): the filler. A page's numbers outside its made-up example are `{{fact:<key>}}`
placeholders (`model.FACT_PLACEHOLDER`); the filler writes each one's value from the release's
fact pack, so every number comes from the code and never from the brain. The same template is
filled again at each release by the free carry (D11), so a changed constant reads right without a
brain call. An unknown key is left as it is and named by `unknown_keys` (check (2) refuses it).
"""

from __future__ import annotations

import re

from jarvis.buildbook.facts_model import FactPack, Scalar
from jarvis.buildbook.writer.model import FACT_PLACEHOLDER

GROUP_FROM = 10_000  # 12,345 is grouped; 2026 or 1500 are not (a year, a small count)


def show(value: Scalar) -> str:
    """A fact's value as a page shows it."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, int):
        return f"{value:,}" if abs(value) >= GROUP_FROM else str(value)
    if isinstance(value, float):
        whole = value.is_integer()
        return show(int(value)) if whole else f"{value:.4f}".rstrip("0").rstrip(".")
    return value


def keys_in(text: str) -> tuple[str, ...]:
    return tuple(m.group(1) for m in FACT_PLACEHOLDER.finditer(text))


def unknown_keys(text: str, facts: FactPack) -> tuple[str, ...]:
    return tuple(dict.fromkeys(k for k in keys_in(text) if k not in facts.values))


def fill(text: str, facts: FactPack) -> str:
    def swap(m: re.Match[str]) -> str:
        got = facts.values.get(m.group(1))
        return m.group(0) if got is None else show(got.value)

    return FACT_PLACEHOLDER.sub(swap, text)


__all__ = ["GROUP_FROM", "fill", "keys_in", "show", "unknown_keys"]
