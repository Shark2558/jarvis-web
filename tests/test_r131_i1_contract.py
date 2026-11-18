# tests/test_r131_i1_contract.py -- R13.1 I1: the contract decisions I1 took on I0's files after
# review A-1 (INTEGRATION-A 11.4, items 3-5). Written red first.
#
#   F8   BodyIn takes whole numbers only, at the contract itself (A also answers "not_whole")
#   F9   "All your try-on data" counts documents and says the month's spend stays
#   F10  a stored measurement version written by a later release still opens (a rollback keeps
#        his figure); what he sends stays strict
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.http_figure import BodyIn
from jarvis.wardrobe.tryon.model import Body
from jarvis.wardrobe.tryon.store import TryonDoc

AT = datetime(2026, 11, 17, 3, 30, tzinfo=UTC)
SIX = {"height": 172, "shoulders": 44, "chest": 96, "waist": 82, "hips": 98, "inseam": 80}


@pytest.mark.parametrize("bad", ["172", 172.0, 172.5, True])
def test_body_in_takes_whole_numbers_only(bad: object) -> None:
    with pytest.raises(ValidationError):
        BodyIn.model_validate({"height": bad})
    assert BodyIn.model_validate({"height": 172}).height == 172


def test_body_in_still_refuses_a_field_it_does_not_know() -> None:
    with pytest.raises(ValidationError):
        BodyIn.model_validate({"height": 172, "foot": 27})


def test_a_stored_version_from_a_later_release_still_opens() -> None:
    later = {**SIX, "typed": ["height"], "at": AT.isoformat(), "foot": 27}
    body = Body.model_validate(later)
    assert body.values() == SIX and "foot" not in body.model_dump()
    doc = TryonDoc.model_validate({"current": later, "earlier": [later]})
    assert doc.current == body and doc.earlier == (body,)


def test_all_your_try_on_data_counts_documents_and_says_the_spend_stays() -> None:
    spec = kept.SPECS[kept.ALL_ID]
    assert spec.unit == "documents"
    assert spec.what.endswith(
        "The month's Try-on spend (numbers only) stays 13 months for your monthly limit."
    )
