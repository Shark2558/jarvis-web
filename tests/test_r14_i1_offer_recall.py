# tests/test_r14_i1_offer_recall.py -- R14 I1 follow-up (integrated code review M2): his headline
# new questions about JARVIS itself (D8's "Where the AI money goes", the database's size, the
# clocks, whether JARVIS is healthy) are offered the Vitals tools on the first round, on the
# fullest registry the fakes build, with a fresh offer (no sticky set, no history). Before, they
# got only the 4 core tools and needed a `skills_open` round, and two of them only the kitchen's
# `spend_month`.
from __future__ import annotations

import pytest
from test_telegram_tool_guard import linked_gateway

from jarvis.llm.base import ChatMessage, Role, ToolSpec
from jarvis.skills.offer import SkillOffer
from jarvis.skills.ports import OfferContext
from jarvis.skills.registry import SkillRegister, load_catalogue

VITALS_QUESTIONS = (
    "How much did AI cost this month?",
    "Where does the AI money go?",
    "How big is the database?",
    "What's the db size?",
    "Is JARVIS healthy?",
    "How is the health of JARVIS?",
    "Are the clocks running?",
    "How much have I spent on Claude?",
    "kitna kharcha hua AI pe?",
    "AI ka kharcha kitna hai?",
    "database kitna bada hai?",
)
NOT_ABOUT_JARVIS = (  # ordinary words that must not pull the Vitals group in
    "Remind me at 5 o'clock to call Ravi",
    "Book a health check-up for my mother",
    "How much did I spend on groceries?",
    "Suggest a healthy breakfast",
)


async def _specs() -> list[ToolSpec]:
    return (await linked_gateway()).registry.specs()


def _offered(specs: list[ToolSpec], text: str) -> list[str]:
    offer = SkillOffer(SkillRegister(load_catalogue()), sticky_s=0)
    ctx = OfferContext("t", text, (ChatMessage(role=Role.USER, content=text),), "trace")
    return [s.name for s in offer(ctx, specs)]


@pytest.mark.parametrize("text", VITALS_QUESTIONS)
async def test_his_questions_about_jarvis_are_offered_the_vitals_tools(text: str) -> None:
    got = _offered(await _specs(), text)
    assert "vitals_show" in got, (text, got)


@pytest.mark.parametrize("text", NOT_ABOUT_JARVIS)
async def test_ordinary_words_do_not_pull_in_the_vitals_group(text: str) -> None:
    assert "vitals_show" not in _offered(await _specs(), text)
