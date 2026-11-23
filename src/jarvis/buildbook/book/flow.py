# src/jarvis/buildbook/book/flow.py
"""R6.3.1 D3 (docs/plans/r6-3-1-book-at-build.md): a page's flowchart, `flows/<page_id>.json`.

Pure data, exactly the plan's spec (extra fields refused everywhere): a `title` (at most 60
characters), a direction (`dir`: "down" or "right"), 2-14 `nodes` and 1-24 `edges`. A node has a
slug `id` (unique), a `label` (at most 28 characters), a `kind` (step, store, service, guard,
person), a `rank` 0-9 and a `col` 0-5 (no two nodes in the same place: the layout is explicit,
so it needs no layout library) and an optional `ref`, a path the page may cite. An edge goes
`from` one node `to` another (both existing ids), with an optional `label` (at most 20) and a
`style`, "main" (the default) or "side". Required for chapters and modules (`REQUIRED_FOR`).

Edge's `from` is a Python keyword: the field is `from_`, read and written only by its alias
("from"), so dump with `by_alias=True`. Error messages here name positions and rules, never a
label or an id.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from jarvis.buildbook.sections import Frozen

SLUG = r"^[a-z][a-z0-9_]{0,30}$"
NodeKind = Literal["step", "store", "service", "guard", "person"]
NODE_KINDS: tuple[NodeKind, ...] = ("step", "store", "service", "guard", "person")
REQUIRED_FOR = ("chapter", "module")  # D3: a flowchart for each; optional elsewhere
TITLE_MAX, LABEL_MAX, EDGE_LABEL_MAX, REF_MAX = 60, 28, 20, 300
NODES_MIN, NODES_MAX, EDGES_MIN, EDGES_MAX = 2, 14, 1, 24
RANK_MAX, COL_MAX = 9, 5


class FlowNode(Frozen):
    id: str = Field(pattern=SLUG)
    label: str = Field(min_length=1, max_length=LABEL_MAX)
    kind: NodeKind
    rank: int = Field(ge=0, le=RANK_MAX)
    col: int = Field(ge=0, le=COL_MAX)
    ref: str | None = Field(default=None, min_length=1, max_length=REF_MAX)


class FlowEdge(Frozen):
    from_: str = Field(alias="from", pattern=SLUG)
    to: str = Field(pattern=SLUG)
    label: str | None = Field(default=None, min_length=1, max_length=EDGE_LABEL_MAX)
    style: Literal["main", "side"] = "main"


class FlowSpec(Frozen):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    dir: Literal["down", "right"]
    nodes: tuple[FlowNode, ...] = Field(min_length=NODES_MIN, max_length=NODES_MAX)
    edges: tuple[FlowEdge, ...] = Field(min_length=EDGES_MIN, max_length=EDGES_MAX)

    @model_validator(mode="after")
    def _drawable(self) -> FlowSpec:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("two nodes have the same id")
        places = [(n.rank, n.col) for n in self.nodes]
        if len(places) != len(set(places)):
            raise ValueError("two nodes share a rank and a col")
        known = set(ids)
        for i, edge in enumerate(self.edges, start=1):
            if edge.from_ not in known or edge.to not in known:
                raise ValueError(f"edge {i} goes from or to a node id that isn't there")
        return self

    def words(self) -> tuple[tuple[str, str], ...]:
        """Every text a reader sees, with where it is: ("title", ...), ("node <id>", ...),
        ("edge <n>", ...)."""
        out = [("title", self.title)]
        out += [(f"node {n.id}", n.label) for n in self.nodes]
        out += [(f"edge {i}", e.label) for i, e in enumerate(self.edges, 1) if e.label]
        return tuple(out)


__all__ = [
    "NODE_KINDS",
    "REQUIRED_FOR",
    "SLUG",
    "FlowEdge",
    "FlowNode",
    "FlowSpec",
    "NodeKind",
]
