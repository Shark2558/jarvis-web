# tests/test_whatsapp_clean.py - slice 12 review fixes for the WhatsApp draft text
# (jarvis.whatsapp.draft.clean_text / text_arg), mirrored by console-whatsapp.js:
#   FE-8  stacked combining marks ("Zalgo" text) render as near-invisible smears: more than 4
#         marks in a row (Unicode category M*) after one base character is refused in plain
#         words; real Malayalam, Hindi / Devanagari, Odia, Tibetan and emoji still pass.
from __future__ import annotations

import pytest

from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.whatsapp.draft import MAX_MARKS, STACKED, draft_card, text_arg
from jarvis.whatsapp.tools import whatsapp_tools

ZALGO = "Hi" + "\u0310" * 120 + " pay here"
LEGIT = [
    "\u0d28\u0d3e\u0d33\u0d46 \u0d15\u0d3e\u0d23\u0d3e\u0d02",  # Malayalam: see you tomorrow
    "\u0d38\u0d4d\u200c\u0d24",  # Malayalam with ZWNJ between letters
    "\u0d0e\u0d28\u0d4d\u200d\u0d31\u0d46",  # Malayalam old-style chillu (ZWJ) inside a word
    "\u0939\u093f\u0928\u094d\u0926\u0940",  # Hindi
    "\u0915\u094d\u200d\u0937",  # Devanagari conjunct with ZWJ
    "\u0b13\u0b21\u0b3c\u0b3f\u0b06",  # Odia (nukta + vowel sign: two marks)
    "\u0f56\u0f66\u0f92\u0fb2\u0f74\u0f56\u0f66",  # Tibetan stack (three marks)
    "\u2764\ufe0f",  # heart with the emoji variation selector
    "1\ufe0f\u20e3",  # keycap 1
    "\U0001f468\u200d\U0001f469\u200d\U0001f467",  # family (emoji ZWJ sequence)
    "a\u0301\u0302\u0303\u0304",  # exactly four marks after one base: allowed
]


@pytest.mark.parametrize("text", LEGIT)
def test_real_scripts_and_emoji_pass(text: str) -> None:
    assert text_arg(text) == text


@pytest.mark.parametrize(
    "text",
    [
        ZALGO,
        "a\u0301\u0302\u0303\u0304\u0305",  # five marks after one base
        "pay \u0d15" + "\u0d4d" * 5,  # a real script's mark, stacked
        "a" + "\u0301\u0301\u200d" * 10,  # joiners between the marks don't break the run
        "\u0301" * 5 + "x",  # marks with no base at all
    ],
)
def test_more_than_four_stacked_marks_are_refused_in_plain_words(text: str) -> None:
    with pytest.raises(ValueError) as exc:
        text_arg(text)
    assert str(exc.value) == STACKED
    assert "stacked accent marks" in STACKED and "retype" in STACKED
    assert MAX_MARKS == 4  # console-whatsapp.js mirrors this exact threshold


def test_a_card_is_never_made_from_stacked_text() -> None:
    card = draft_card(name=None, number="+919876543210", text=ZALGO, source="you", assumed=False)
    assert card is None


async def test_the_tool_refuses_a_stacked_text_before_anything_runs() -> None:
    reg = ToolRegistry()
    for t in whatsapp_tools(None):
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    call = ToolCall(id="w", name="whatsapp_draft", arguments={"to": "98765 43210", "text": ZALGO})
    with context_trust(untrusted=False, owner_text="98765 43210"):
        out = await gw.execute(call, scope="u_owner:sess_1")
    assert out.outcome is GatewayOutcome.ERROR and out.error == STACKED
