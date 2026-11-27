# tests/test_calls_langcheck_sentences.py — R18 B: the check's 10 call sentences: English with its
# key facts; another language translated once by the brain and kept, its facts its own numbers and
# the words the brain marked (never a digit twice).
from __future__ import annotations

from collections.abc import Mapping

from jarvis.calls.langcheck.sentences import ENGLISH_SENTENCES, CheckSentences, english
from jarvis.calls.speech.translate import Translation
from jarvis.storage.docs import MemoryDocs


class Hindi:
    def __init__(self) -> None:
        self.calls = 0

    async def translate(self, english: Mapping[str, str], lang: str) -> dict[str, Translation]:
        self.calls += 1
        out = {k: Translation(f"अनुवाद {k}", ()) for k in english}
        out["pickup"] = Translation("हाँ, पिकअप कल 10:30 बजे है।", ("हाँ", "10:30"))
        return out


def test_english_has_ten_sentences_with_their_facts() -> None:
    sentences = english()
    assert len(sentences) == len(ENGLISH_SENTENCES) == 10
    by = {s.key: s for s in sentences}
    assert by["pickup"].facts == ("1030", "yes")
    assert by["appointment"].facts == ("28", "915", "November")
    assert by["booking"].facts == ("7291",)


async def test_another_language_is_translated_once_and_kept() -> None:
    docs, brain = MemoryDocs(), Hindi()
    first = await CheckSentences(docs, prefix="t_", translator=brain).sentences("hi-IN")
    again = await CheckSentences(docs, prefix="t_", translator=brain).sentences("hi-IN")
    assert brain.calls == 1 and first == again
    pickup = next(s for s in first if s.key == "pickup")
    assert pickup.facts == ("1030", "हाँ")  # "10:30" as a number, once


async def test_english_never_asks_the_brain() -> None:
    brain = Hindi()
    await CheckSentences(MemoryDocs(), prefix="t_", translator=brain).sentences("en-IN")
    assert brain.calls == 0
