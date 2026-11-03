# tests/test_whatsapp_clean.py - slice 12 review fixes for the WhatsApp draft text
# (jarvis.whatsapp.draft.clean_text / text_arg), mirrored by console-whatsapp.js:
#   FE-8  stacked combining marks ("Zalgo" text) render as near-invisible smears: more than 4
#         marks in a row (Unicode category M*) after one base character is refused in plain
#         words; real Malayalam, Hindi / Devanagari, Odia, Tibetan and emoji still pass.
#   SEC-1 an invisible channel: ZWNJ / ZWJ between Latin letters, FE0E / FE0F after a letter and
#         odd spaces survived cleaning while the approval card's one_line hid them, so the card
#         showed only the visible words and the wa.me link carried the rest. Now: every Zs
#         space and tab is one plain space; ZWNJ / ZWJ only between two letters of a non-Latin
#         script (ZWJ also between emoji); FE0E / FE0F only after an emoji or a keycap base; and
#         the card quotes the EXACT text. The cases are shared with the console
#         (tests/fixtures/whatsapp_clean_cases.json, tests/browser/test_whatsapp.py).
#   SEC-5 the selectors and joiners were still a channel ("Call 9<FE0F>8<FE0E>76" showed as
#         "Call 9876"). Now: FE0E never; FE0F only inside a keycap or after a code point whose
#         emoji form is cp + FE0F (EMOJI_FE0F_BASES); ZWNJ / ZWJ only right after a virama
#         (RFC 5892 CONTEXTJ), ZWNJ also between Arabic letters, ZWJ also inside an emoji
#         sequence; no space at either end of a line; unassigned code points (Cn) dropped but
#         a future emoji's.
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.taint import context_trust
from jarvis.whatsapp.draft import MAX_MARKS, STACKED, draft_card, text_arg
from jarvis.whatsapp.pictographic import emoji_fe0f_base, extended_pictographic
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


# ---- SEC-1: one shared rule, one shared fixture ------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "whatsapp_clean_cases.json"
CASES: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="ascii"))
ZWNJ, ZWJ = "\u200c", "\u200d"


def test_the_fixture_is_ascii_and_covers_what_the_review_named() -> None:
    raw = FIXTURE.read_text(encoding="ascii")
    assert raw.isascii()
    whys = " ".join(c["why"] for c in CASES)
    for needle in ("Latin letters", "FE0F after a letter", "NBSP", "Malayalam", "Devanagari",
                   "family", "heart", "keycap", "stacked", "S3",
                   # the final review's console-text.js additions: the strict rule drops them too
                   "soft hyphen", "U+180E", "U+E007F", "CGJ",
                   # SEC-5 H1: variation selectors only where they make an emoji
                   "Call 9876", "no U+20E3", "U+231A", "U+1F600", "FE0E (text style)",
                   "FE0F twice", "EMOJI_FE0F_BASES", "eye in speech bubble", "skin tone ZWJ",
                   "FE0F after a skin tone",
                   # M1: joiners only after a virama (or ZWNJ between Arabic letters)
                   "chillu", "Hindi half-form", "Odia virama", "Tamil virama", "Persian",
                   "Cyrillic look-alikes", "CJK", "Mathematical Alphanumeric", "Letterlike",
                   "no virama",
                   # M2, M3 and the low findings
                   "start of a line", "U+0378", "U+FDD0", "U+FFFE", "Extended_Pictographic",
                   "split a run", "U+16FE4"):  # fmt: skip
        assert needle in whys, needle
    assert any(c["out"] is None for c in CASES) and len(CASES) >= 95


@pytest.mark.parametrize("case", CASES, ids=[c["why"][:60] for c in CASES])
def test_clean_text_over_the_shared_fixture(case: dict[str, Any]) -> None:
    if case["out"] is None:
        with pytest.raises(ValueError):
            text_arg(case["in"])
    else:
        assert text_arg(case["in"]) == case["out"]
        assert text_arg(case["out"]) == case["out"]  # cleaning is idempotent


def _arabic_letter(ch: str) -> bool:
    return (
        bool(ch)
        and unicodedata.category(ch)[0] == "L"
        and unicodedata.name(ch, "").startswith("ARABIC LETTER ")
    )


def _emoji_end(text: str, i: int) -> bool:
    """text[i] ends an emoji a ZWJ may follow: an emoji, its skin tone, or its FE0F."""
    ch = text[i] if 0 <= i < len(text) else ""
    if ch == "\ufe0f":
        return i > 0 and extended_pictographic(text[i - 1])
    return bool(ch) and (extended_pictographic(ch) or 0x1F3FB <= ord(ch) <= 0x1F3FF)


@pytest.mark.parametrize("case", [c for c in CASES if c["out"]], ids=lambda c: c["why"][:60])
def test_every_kept_invisible_sits_where_a_script_or_an_emoji_needs_it(
    case: dict[str, Any],
) -> None:
    """Security review SEC-5, checked from Unicode's own data where Python has it: no FE0E; an
    FE0F only inside a keycap ([0-9#*] FE0F U+20E3) or right after a code point whose emoji form
    is cp + FE0F; a ZWNJ / ZWJ only right after a virama (canonical combining class 9, RFC 5892
    CONTEXTJ), a ZWNJ also between two Arabic letters, a ZWJ also inside an emoji sequence. No
    unassigned code point but a future emoji, no space at either end of a line (M2) \u2014 so none
    can carry data between Latin letters, spaces or after a letter."""
    text = case["out"]
    assert "\ufe0e" not in text, case["why"]
    for i, ch in enumerate(text):
        before = text[i - 1] if i > 0 else ""
        after = text[i + 1] if i + 1 < len(text) else ""
        if ch == "\ufe0f":
            keycap = before != "" and before in "0123456789#*" and after == "\u20e3"
            assert keycap or emoji_fe0f_base(before), case["why"]
        elif ch in (ZWNJ, ZWJ):
            virama = before != "" and unicodedata.combining(before) == 9
            arabic = ch == ZWNJ and _arabic_letter(before) and _arabic_letter(after)
            emoji = ch == ZWJ and _emoji_end(text, i - 1) and extended_pictographic(after)
            assert virama or arabic or emoji, case["why"]
        assert unicodedata.category(ch) != "Cn" or extended_pictographic(ch), case["why"]
        assert not (unicodedata.category(ch) == "Zs" and ch != " "), case["why"]
    assert "\t" not in text and "  " not in text
    assert all(line == line.strip(" ") for line in text.split("\n")), case["why"]


def _card_text(text: str) -> str:
    from jarvis.whatsapp.tools import _card_text as card_text

    return card_text({"to": "98765 43210", "text": text})


def _quoted_body(card: str) -> str:
    """The text as the approval card quotes it: its lines with the "> " prefix taken off."""
    lines = card.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Text (")) + 1
    return "\n".join(ln[2:] if ln.startswith("> ") else ln[1:] for ln in lines[start:])


@pytest.mark.parametrize("case", [c for c in CASES if c["out"]], ids=lambda c: c["why"][:60])
def test_the_approval_card_quotes_exactly_the_text_that_is_sent(case: dict[str, Any]) -> None:
    sent = text_arg(case["in"])
    assert _quoted_body(_card_text(case["in"])) == sent


async def test_a_hidden_payload_after_approval_is_exactly_what_the_card_showed(
    settings: Any,
) -> None:
    """The reviewer's attack through the REAL Brain and gateway: a mail steers the model into a
    draft whose text hides 'OTP 482913' in 80 ZWNJ / ZWJ. The round is tainted, so the draft
    waits for approval; after approval the wa.me link decodes to EXACTLY the card's text."""
    from jarvis.core.brain import Brain
    from jarvis.core.guardrails import ActionRisk
    from jarvis.core.models import ChatRequest
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.llm.router import ModelRouter, ModelTier
    from jarvis.memory.inmemory import InMemorySessionStore
    from jarvis.tools.base import Tool

    hidden = next(c for c in CASES if c["why"].startswith("SEC-1: 80"))
    reg = ToolRegistry()
    for t in whatsapp_tools(None):
        reg.register(t)
    reg.register(Tool("gmail_read", "read a mail", {"type": "object", "properties": {}},
                      ActionRisk.READ_ONLY, lambda a: {"body": "confirm Thursday"},
                      agent="google"))  # fmt: skip
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    provider = MockProvider()
    provider.script_tool_calls([ToolCall(id="m", name="gmail_read", arguments={})])
    provider.script_tool_calls(
        [ToolCall(id="w", name="whatsapp_draft",
                  arguments={"to": "98765 43210", "text": hidden["in"]})],
        "An approval is waiting.",
    )  # fmt: skip
    tiers = {t: f"mock-{t.value}" for t in ModelTier}
    s = settings.model_copy(update={"tools_enabled": True})
    brain = Brain(router=ModelRouter(provider, tiers), store=InMemorySessionStore(), settings=s,
                  gateway=gw)  # fmt: skip
    first = await brain.chat(ChatRequest(message="WhatsApp 98765 43210 ok", user_id="u_owner"))
    (pending,) = first.pending_approvals
    shown = _quoted_body(pending.summary)
    assert shown == hidden["out"] and ZWNJ not in pending.summary and ZWJ not in pending.summary
    provider.script("It's ready.")
    done = await brain.approve(pending.id, session_id=first.session_id, user_id="u_owner")
    (card,) = [c for c in done.cards if c.kind == "whatsapp"]
    (sent,) = parse_qs(urlsplit(card.link).query)["text"]
    assert sent == card.text == shown
