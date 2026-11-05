# tests/test_spoken_mask.py -- anything JARVIS SPEAKS from mail is MASKED, not classified: no 4+
# digit run, no amount and no URL can reach the speaker, whatever the sender wrote.
from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from r1d_fakes import OWNER, GmailFake, connector

from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.recall.sensitive import spoken_sensitive
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway
from jarvis.tools.gmail import gmail_tools
from jarvis.tools.gmail_digest import digest_tools
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.spoken import mask_for_speech
from jarvis.tools.taint import context_trust

SCOPE = f"{OWNER}:sess_1"
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)

PROBES = [
    "482 910 is your code",
    "Your code: 4 8 2 9 1 0",
    "Your 0TP is 482910",
    "O T P 482910",
    "O.T.P 482910",
    "Ｏ Ｔ Ｐ 482910",  # fullwidth O T P
    "Use 482910",
    "Enter 482910 to continue",
    "Swiggy: 482910",
    "482910 - Swiggy",
    "Your secret number 482910",
    "आपका ओटीपी 482910 है",
    "ओटीपी 482910",
    "तुम्हारा कोड 482910",
    "482910 ആണ് നിങ്ങളുടെ ഒടിപി",
    "२४७०३१ is your code",  # Devanagari digits
    "൪൭൦൫൩൨ ",  # Malayalam digits
    "₹500",
    "₹ 12,345",
    "Rs.500 paid",
    "INR 1,00,000 received",
    "Rs 1,23,456.78",
    "500 rupees",
    "12 lakh",
    "रु. 500",
    "Avl Bal INR 500",
    "bal: 500.00",
    "EMI of Rs 5000 due",
    "VPA john@okaxis",
    "pay to john@okaxis",
    "Card xx1234 used",
    "Login link: https://x.com/t/abc123def",
    "Pay at www.pay.example/x?id=998877 now",
    "4829\u200b10 is it",  # zero-width inside a number
    "4-8-2-9-1-0",
    "4.8.2.9.1.0",
    "The total is 5k",
    "Rs 5 crore",
]
READABLE = [
    "Lunch tomorrow? Are you free at one",
    "Meeting at 10:30 on 5 Nov in room 4",
    "Your parcel has shipped, arriving Mon 9 Nov",
    "Happy birthday Priya!",
]


def leaks(text: str) -> list[str]:
    """What must never reach the speaker."""
    found = []
    folded = text
    for run in re.finditer(r"\d(?:[\s.,\-]{0,2}\d)*", folded):
        if len(re.sub(r"\D", "", run.group(0))) >= 4:
            found.append(f"digit run {run.group(0)!r}")
    if re.search(r"₹|\brs\b|\binr\b|रु|rupee|lakh|crore", text, re.I):
        found.append("amount")
    if re.search(r"https?://|www\.|\.com/|@[a-z]", text, re.I):
        found.append("link or address")
    return found


@pytest.mark.parametrize("probe", PROBES)
def test_masked_text_holds_no_long_number_amount_or_link(probe: str) -> None:
    assert leaks(mask_for_speech(probe)) == []


@pytest.mark.parametrize("text", READABLE)
def test_ordinary_text_is_left_readable(text: str) -> None:
    assert mask_for_speech(text) == text


def test_the_masks_say_what_they_replaced() -> None:
    assert mask_for_speech("Use 482910") == "Use a number"
    assert mask_for_speech("Rs 5000 due") == "an amount due"
    assert mask_for_speech("see https://x.com/t/abc") == "see a link"
    assert mask_for_speech("pay john@okaxis") == "pay an address"
    assert mask_for_speech("") == "" and mask_for_speech(None) == ""  # type: ignore[arg-type]


def test_many_short_numbers_that_add_up_to_a_code_are_masked_too() -> None:
    # 482 and 910 are 3 digits each; together they are a code read in two goes
    out = mask_for_speech("The first part is 482 and the second part is 910 and 37 and 12")
    assert leaks(out) == [] and "482" not in out and "910" not in out


def test_masking_is_cheap_on_hostile_input() -> None:
    for hostile in (
        "1 " * 50_000,
        "Rs " * 30_000,
        "." * 100_000,
        "a@" * 40_000,
        "http://" * 20_000,
    ):
        start = time.perf_counter()
        mask_for_speech(hostile)
        assert time.perf_counter() - start < 0.2


# ---- the extra WITHHOLD layer -------------------------------------------------------------------

WITHHOLD = [p for p in PROBES if "482910" in p or "Avl Bal" in p or "bal:" in p or "EMI" in p]
WITHHOLD += [
    "VPA john@okaxis",
    "pay to john@okaxis",
    "Card xx1234 used",
    "Login link: https://x.com/t",
]


@pytest.mark.parametrize("probe", WITHHOLD)
def test_code_and_bank_looking_text_is_withheld_whole(probe: str) -> None:
    assert spoken_sensitive(probe), probe


@pytest.mark.parametrize("text", READABLE)
def test_ordinary_mail_is_not_withheld(text: str) -> None:
    assert not spoken_sensitive(text)


def test_pan_with_thousands_of_repeats_is_cheap() -> None:
    start = time.perf_counter()
    spoken_sensitive("pan " * 5000)
    assert time.perf_counter() - start < 0.1


def test_the_input_is_capped_at_a_thousand_characters() -> None:
    assert not spoken_sensitive("hello there " * 200 + " OTP")  # beyond the cap: not looked at
    assert spoken_sensitive("OTP " + "hello there " * 200)


# ---- through the tools ---------------------------------------------------------------------------


def mail(i: int, subject: str, snippet: str, body: str | None = None) -> dict[str, Any]:
    return {
        "id": f"m{i}",
        "from": "Priya <priya@example.com>",
        "subject": subject,
        "date": "Thu, 05 Nov 2026 08:30:00 +0000",
        "body": body if body is not None else snippet,
        "snippet": snippet,
    }


async def gateway(fake: GmailFake) -> Gateway:
    conn = await connector(fake.client())
    reg = ToolRegistry()
    for t in [*digest_tools(conn, lambda: NOW), *gmail_tools(conn)]:
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def call(gw: Gateway, name: str, **args: Any) -> Any:
    return await gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)


WORD_FIELDS = {"subject", "snippet", "body", "first_line"}


def spoken_fields(result: Any) -> str:
    """The words in a digest / search / read result (ids are technical, not spoken)."""
    words: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in WORD_FIELDS and isinstance(value, str):
                    words.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(result.result)
    # fence markers carry an id and the source address: not words anyone speaks
    return re.sub(r"<<[^>]*>>", "", " ".join(words))


@pytest.mark.parametrize("probe", PROBES)
async def test_the_digest_never_lets_a_probe_through(probe: str) -> None:
    fake = GmailFake([mail(1, "Alert", probe), mail(2, "Lunch?", "Free at one?")])
    res = await call(await gateway(fake), "gmail_unread_digest")
    assert leaks(spoken_fields(res)) == [], probe
    assert "Lunch?" in res.for_model()  # the harmless mail is still read


async def test_a_withheld_message_is_counted_in_plain_words() -> None:
    fake = GmailFake([mail(1, "Alert", "O T P 482910")])
    res = await call(await gateway(fake), "gmail_unread_digest")
    assert res.result["withheld_note"] == (
        "1 message withheld — it looks like a code or bank message"
    )
    assert "O T P" not in res.for_model() and "482910" not in res.for_model()


async def test_the_sender_and_subject_are_masked_too() -> None:
    fake = GmailFake([mail(1, "Your balance Rs 5000 and code 482910", "hello")])
    res = await call(await gateway(fake), "gmail_unread_digest")
    assert leaks(spoken_fields(res)) == []


@pytest.mark.parametrize("channel", ["voice", "telegram"])
async def test_search_and_read_are_masked_on_voice_and_telegram_turns(channel: str) -> None:
    fake = GmailFake(
        [mail(1, "Receipt Rs 5000", "Ref 998877 see https://x.com/r/abc", "Paid 998877")]
    )
    gw = await gateway(fake)
    if channel == "voice":
        with context_trust(untrusted=True, spoken=True):
            search = await call(gw, "gmail_search", query="receipt")
            read = await call(gw, "gmail_read", message_id="m1")
    else:
        with telegram_turn():
            search = await call(gw, "gmail_search", query="receipt")
            read = await call(gw, "gmail_read", message_id="m1")
    for res in (search, read):
        assert leaks(spoken_fields(res)) == [], channel
        assert "Receipt" in res.for_model()


async def test_the_console_reads_unmasked() -> None:
    fake = GmailFake([mail(1, "Receipt Rs 5000", "Ref 998877", "Paid 998877")])
    gw = await gateway(fake)
    search = await call(gw, "gmail_search", query="receipt")
    read = await call(gw, "gmail_read", message_id="m1")
    assert "Rs 5000" in search.for_model() and "998877" in search.for_model()
    assert "998877" in read.for_model()


WITHHELD_LINE = "withheld - open it on screen"


@pytest.mark.parametrize("channel", ["voice", "telegram"])
@pytest.mark.parametrize(
    "body",
    [
        "Your OTP is one two three four five six",
        "Your verification code 123 - 456",
        "Your OTP 12|34|56",
        "OTP onnu randu moonnu naalu anchu aaru",
    ],
)
async def test_gmail_read_and_search_withhold_a_code_mail_on_voice_and_telegram(
    channel: str, body: str
) -> None:
    fake = GmailFake([mail(1, "Your Swiggy login", body, body)])
    gw = await gateway(fake)
    ctx = context_trust(untrusted=True, spoken=True) if channel == "voice" else telegram_turn()
    with ctx:
        search = await call(gw, "gmail_search", query="swiggy")
        read = await call(gw, "gmail_read", message_id="m1")
    for res in (search, read):
        spoken = spoken_fields(res)
        assert WITHHELD_LINE in spoken, spoken
        assert not re.search(r"one two|123|12\|34|onnu|456", res.for_model()), res.for_model()


async def test_gmail_read_leaves_an_ordinary_mail_alone_on_voice() -> None:
    fake = GmailFake([mail(1, "Lunch?", "Are we still on for lunch tomorrow?")])
    with context_trust(untrusted=True, spoken=True):
        read = await call(await gateway(fake), "gmail_read", message_id="m1")
    assert "still on for lunch" in read.for_model()
    assert WITHHELD_LINE not in spoken_fields(read)


async def test_the_console_still_reads_a_code_mail_in_full() -> None:
    fake = GmailFake([mail(1, "Login", "Your OTP is one two three four five six")])
    read = await call(await gateway(fake), "gmail_read", message_id="m1")
    assert "one two three four five six" in read.for_model()
