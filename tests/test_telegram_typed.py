# tests/test_telegram_typed.py -- R1 I1 (I0 leftover): Telegram text from the paired owner is TYPED
# (counts for a WhatsApp number and a web_read link), voice never does, and a forwarded / via-bot
# Telegram message (fenced as outside content) is someone else's text and never does.
from __future__ import annotations

from typing import Literal

import pytest

from jarvis.core.models import Role, Session, Turn
from jarvis.tools.external import wrap_external
from jarvis.tools.taint import context_trust
from jarvis.web.ledger import conversation_of
from jarvis.whatsapp.provenance import conversation_words, country_typed, number_source

NUMBER = "+919876543210"
RAW = "+91 98765 43210"
URL = "https://example.com/menu"
Channel = Literal["text", "voice", "telegram"]


def _session(content: str, channel: Channel) -> Session:
    return Session(user_id="u", turns=[Turn(role=Role.USER, content=content, channel=channel)])


def _who(session: Session) -> str:
    with conversation_words(session):
        return number_source(NUMBER)


@pytest.mark.parametrize(("channel", "expected"), [("text", "you"), ("telegram", "you")])
def test_typed_channels_count_for_a_number(channel: Channel, expected: str) -> None:
    assert _who(_session(f"message {RAW}", channel)) == expected


def test_voice_never_counts_for_a_number() -> None:
    assert _who(_session(f"message {RAW}", "voice")) == "elsewhere"


def test_a_forwarded_telegram_number_is_not_typed() -> None:
    fenced = wrap_external(f"call me on {RAW}", source="forwarded")
    assert _who(_session(fenced, "telegram")) == "elsewhere"


def test_the_country_code_rule_follows_the_same_channels() -> None:
    with conversation_words(_session(f"to {RAW}", "telegram")):
        assert country_typed(NUMBER) is True
    with conversation_words(_session(f"to {RAW}", "voice")):
        assert country_typed(NUMBER) is False
    fenced = wrap_external(f"to {RAW}", source="forwarded")
    with conversation_words(_session(fenced, "telegram")):
        assert country_typed(NUMBER) is False


def test_the_current_forwarded_message_is_not_typed_either() -> None:
    fenced = wrap_external(f"call me on {RAW}", source="forwarded")
    with context_trust(untrusted=False, spoken=False, owner_text=fenced):
        assert _who(Session(user_id="u")) == "elsewhere"
    with context_trust(untrusted=False, spoken=False, owner_text=f"call {RAW}"):
        assert _who(Session(user_id="u")) == "you"


def test_links_typed_on_telegram_count_voice_and_forwarded_do_not() -> None:
    assert conversation_of(_session(f"read {URL}", "telegram")).allows(URL)
    assert conversation_of(_session(f"read {URL}", "text")).allows(URL)
    assert not conversation_of(_session(f"read {URL}", "voice")).allows(URL)
    fenced = wrap_external(f"read {URL}", source="forwarded")
    assert not conversation_of(_session(fenced, "telegram")).allows(URL)
