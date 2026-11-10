# src/jarvis/buildbook/gen/chunks.py
"""R6 D2, D11: the talk-through's digest — the book again as plain sentences, an overview
(<= 2,000 characters) and chunks of <= 1,500 characters per section (`model.DigestChunk`), which
the talk lane (C) scores by keyword. Built from the same `show.Parts` as the show; fixed
sentence shapes, no model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from jarvis.buildbook.gen.code import clip
from jarvis.buildbook.gen.show import Parts
from jarvis.buildbook.model import DIGEST_CHUNK_CHARS, LAYERS, Digest, DigestChunk

OVERVIEW_MAX = 2_000
_LAYER_NAME = dict(LAYERS)
Groups = list[list[str]]  # lines packed together; a new group starts a new chunk


def _n(count: int, word: str) -> str:
    return f"{count:,} {word}" + ("" if count == 1 else "s")


def pack(section: str, lines: Iterable[str]) -> list[tuple[str, str]]:
    """Lines joined into chunks of at most DIGEST_CHUNK_CHARS (a longer line is cut)."""
    out, cur = [], ""
    for line in (clip(ln, DIGEST_CHUNK_CHARS) for ln in lines if ln.strip()):
        if cur and len(cur) + 1 + len(line) > DIGEST_CHUNK_CHARS:
            out.append((section, cur))
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return [*out, (section, cur)] if cur else out


def _architecture(p: Parts) -> Groups:
    return [[
        f"{x.name}: layer {x.layer} ({_LAYER_NAME[x.layer]}), {_n(x.files, 'file')}, "
        f"{x.lines:,} lines. {x.summary}"
        for x in p.architecture.packages
    ]]  # fmt: skip


def _fit(p: Parts) -> Groups:
    rows = p.architecture.fit
    return [[f"{r.release} {r.feature}: {r.layer}; phase {r.phase}; {r.verdict}." for r in rows]]


def _stack(p: Parts) -> Groups:
    return [[f"{i.role}: {i.name} {i.version} ({i.source})." for i in p.stack.items]]


def _libraries(p: Parts) -> Groups:
    return [[
        f"{x.name} {x.version}: {x.licence} ({x.kind}, {x.role})"
        + (f", flagged {x.flag}." if x.flag else ".")
        for x in p.libraries
    ]]  # fmt: skip


def _integrations(p: Parts) -> Groups:
    it = p.integrations
    services = [
        f"{s.label}: {s.what} Settings: {', '.join(s.settings) or 'none'}." for s in it.services
    ]
    alerts = [f"Alert {a.kind} ({a.level}): {a.what}." for a in it.alert_kinds]
    return [services, [f"Keys, one per purpose: {', '.join(it.key_purposes)}."], alerts]


def _workflows(p: Parts) -> Groups:
    return [
        [f"{w.title}:", *(f"{n}. {s.label} ({s.symbol})." for n, s in enumerate(w.steps, 1))]
        for w in p.workflows
    ]


def _limitations(p: Parts) -> Groups:
    return [[f"{x.release or 'earlier'} {x.kind}: {x.text}" for x in p.limitations]]


def _costs(p: Parts) -> Groups:
    c = p.costs
    items = [
        f"{i.label}: ₹{i.inr:,.2f} per {i.unit}" + (f"; free: {i.free}." if i.free else ".")
        for i in c.items
    ]
    return [[f"Rates at ₹{c.usd_inr:,.2f} to the dollar on {c.rate_date}.", *items]]


def _decisions(p: Parts) -> Groups:
    return [[f"{d.title} ({d.release or 'slice'}):", *d.decisions] for d in p.decisions]


SECTIONS: tuple[tuple[str, Callable[[Parts], Groups]], ...] = (
    ("architecture", _architecture),
    ("fit", _fit),
    ("stack", _stack),
    ("libraries", _libraries),
    ("integrations", _integrations),
    ("workflows", _workflows),
    ("limitations", _limitations),
    ("costs", _costs),
    ("decisions", _decisions),
)


def overview(p: Parts) -> str:
    layers = "; ".join(
        f"{lid} {name}: " + ", ".join(x.name for x in p.architecture.packages if x.layer == lid)
        for lid, name in LAYERS
    )
    services = ", ".join(s.label for s in p.integrations.services) or "none"
    flows = ", ".join(w.title for w in p.workflows)
    text = (
        f"JARVIS build book, release {p.release.label} (commit {p.release.id}, "
        f"{p.release.committed_at[:10]}). {len(p.architecture.packages)} parts in eight layers and "
        f"a cross-cutting band. {layers}. {len(p.libraries)} libraries. Services: {services}. "
        f"Workflows: {flows}. {len(p.limitations)} limitations listed."
    )
    return clip(text, OVERVIEW_MAX)


def build_digest(p: Parts) -> Digest:
    found = [c for name, make in SECTIONS for group in make(p) for c in pack(name, group)]
    chunks = tuple(
        DigestChunk(id=f"c{n:03d}", section=section, text=text)
        for n, (section, text) in enumerate(found, start=1)
    )
    return Digest(overview=overview(p), chunks=chunks)


__all__ = ["OVERVIEW_MAX", "SECTIONS", "build_digest", "overview", "pack"]
