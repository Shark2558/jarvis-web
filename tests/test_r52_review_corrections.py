# tests/test_r52_review_corrections.py -- R5.2 combined review: corrections never touch numbers,
# money or codes (brief "Recognition", enforced by `jarvis.voice.profile.Correction`). The guard
# listed the cardinal numbers and "first second third" only, so a learned correction could still
# write or rewrite an ordinal ("fifth"), a plural ("hundreds"), "dozen", "twice" or "passcode".
from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.voice.profile import Correction, apply_corrections

MISSED = (
    "fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fifteenth "
    "twentieth thirtieth hundredth thousandth millionth zeros zeroes tens dozens hundreds "
    "thousands millions billions twenties nineties dozen nought naught once twice thrice "
    "password passcode passkey pincode cvc"
).split()


@pytest.mark.parametrize("word", MISSED)
def test_review_a_correction_never_writes_a_number_money_or_code_word(word: str) -> None:
    with pytest.raises(ValidationError):
        Correction(heard="fit", meant=word)
    with pytest.raises(ValidationError):
        Correction(heard=word, meant="JARVIS")
    with pytest.raises(ValidationError):
        Correction(heard=f"the {word}", meant="JARVIS")


def test_review_an_ordinary_correction_still_works() -> None:
    fix = Correction(heard="java's", meant="JARVIS")
    assert apply_corrections("remind me on the fifth, java's", (fix,)) == (
        "remind me on the fifth, JARVIS"
    )
