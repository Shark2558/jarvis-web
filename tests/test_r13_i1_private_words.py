# tests/test_r13_i1_private_words.py -- the I1 security review's M3 (and the code review's brand
# and size): his words about a PRIVATE piece never sit in a card's stored arguments, because the
# approvals store is clear JSON. A typed `wardrobe_add` or `wardrobe_edit` that names a private
# piece's label (or a place by its words) is refused before any card; "type it in Helpers,
# Wardrobe". A normal piece's label is still his to give. Brand and size are free text too and
# join the spoken-turn refusal.
from __future__ import annotations

from typing import Any

import pytest
from r13_fakes import UID
from r13_fakes_a import Catalog, catalog

from jarvis.tools.context import tool_context
from jarvis.wardrobe.catalog import tools_write
from jarvis.wardrobe.catalog.edits import NewPiece


@pytest.fixture
def cat() -> Catalog:
    return catalog()


def _tool(cat: Catalog, name: str) -> Any:
    return next(t for t in cat.part.tools if t.name == name)


def test_a_private_pieces_label_is_refused_in_an_add(cat: Catalog) -> None:
    check = _tool(cat, "wardrobe_add").check
    for piece in (
        {"type": "underpants", "label": "the words about it"},  # private by default
        {"type": "shirt", "private": True, "label": "the words about it"},
    ):
        with pytest.raises(ValueError, match="keeps no label"):
            check({"pieces": [piece]})
    check({"pieces": [{"type": "underpants"}]})  # no words: fine
    check({"pieces": [{"type": "shirt", "label": "Light blue office shirt"}]})  # not private


async def test_a_private_pieces_label_is_refused_in_an_edit_before_any_card(cat: Catalog) -> None:
    [vest, shirt] = list(
        (
            await cat.store.desk.service.add(  # type: ignore[attr-defined]
                UID, [NewPiece(type="underpants"), NewPiece(type="shirt")]
            )
        ).ids
    )
    tool = _tool(cat, "wardrobe_edit")
    with tool_context(f"{UID}:s"):
        with pytest.raises(Exception, match="keeps no label"):
            await tool.preview({"piece": vest, "label": "the words about it"})
        await tool.preview({"piece": shirt, "label": "Light blue office shirt"})  # a normal piece
        await tool.preview({"piece": vest, "colour": "black"})  # no words: fine


def test_brand_and_size_are_refused_on_a_spoken_turn(cat: Catalog, monkeypatch: Any) -> None:
    monkeypatch.setattr(tools_write, "spoken_in_context", lambda: True)
    for tool, args in (
        ("wardrobe_edit", {"piece": "wi_000000000001", "brand": "Acme"}),
        ("wardrobe_edit", {"piece": "wi_000000000001", "size": "M"}),
    ):
        with pytest.raises(ValueError, match="own typed words"):
            _tool(cat, tool).check(args)
