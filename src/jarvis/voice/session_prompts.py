# src/jarvis/voice/session_prompts.py
"""The voice session's prompts (R5.2 row 81; docs/plans/r5-2-voice.md 3.3): about 120 short lines
in 4 blocks of about 5 minutes, read aloud once each.

    block 1  commands JARVIS knows      (the console's own local commands: `voice.commands`)
    block 2  your words, places, names  (his "words to recognise" first, then generic ones)
    block 3  numbers and times          (never a source of corrections: money, codes, times)
    block 4  everyday requests          (and up to 5 of his words a second time)
    every block: "Hey Jarvis" said 30 ways in all (near, far, quiet, tired, over music, ...)

Every block has 30 prompts: 22 or 23 lines to listen to and 7 or 8 "Hey Jarvis". 20 lines a
block are held out: every listening engine hears them and they are scored (80 in all: at Google's
15-second billing step, the comparison's ~20 minutes); the rest, and 24 of the 30 "Hey Jarvis",
are for training (the wake word, the speaker check). Six "Hey Jarvis" are held out for the wake
word's own eval. Each command or request carries its key phrase: it was understood right when the
key phrase is in what an engine heard (command accuracy).

The sentences are generic: no person, place or detail of the owner's is in this file. His own
words arrive at run time from his `VoiceSettings.phrases` (and any he types when he starts);
prompt ids never contain them. Pure (no I/O).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.localspeech.protocol import PromptKind
from jarvis.voice.profile import BLOCKS, Prompt

BLOCK_TITLES: Final[dict[int, str]] = {
    1: "Commands",
    2: "Your words, places and names",
    3: "Numbers and times",
    4: "Everyday requests",
}
LINES: Final[dict[int, int]] = {1: 23, 2: 22, 3: 23, 4: 22}  # lines to listen to, per block
WAKES: Final[dict[int, int]] = {1: 7, 2: 8, 3: 7, 4: 8}  # "Hey Jarvis", per block
HELD_OUT_PER_BLOCK: Final = 20
OWN_WORDS_BLOCK_2: Final = 10  # his words read in block 2 ...
OWN_WORDS_BLOCK_4: Final = 5  # ... and the first 5 again in block 4 (so a mishearing can repeat)
TYPED_WORDS_MAX: Final = 20  # new names and places he may type when he starts
WAKE_TEXT: Final = "Hey Jarvis"
WAKE_HELD_OUT_EVERY: Final = 5  # every 5th "Hey Jarvis" is held out (6 of 30)

# (text, key phrase): the console's local commands (`jarvis.voice.commands.COMMAND_HINTS`, R7's
# camera phrases); the key is the command itself.
COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("Jarvis, stop talking.", "stop talking"),
    ("Mic off.", "mic off"),
    ("Stop listening to me.", "stop listening to me"),
    ("Switch to the keyboard.", "switch to the keyboard"),
    ("Switch to my earphones.", "switch to my earphones"),
    ("Switch to my speaker.", "switch to my speaker"),
    ("Which devices are connected?", "which devices are connected"),
    ("Hold on.", "hold on"),
    ("Never mind.", "never mind"),
    ("That'll be all.", "that'll be all"),
    ("Let me type.", "let me type"),
    ("Cameras off.", "cameras off"),
    ("List my devices.", "list my devices"),
    ("End the conversation.", "end the conversation"),
    ("Turn off the camera.", "turn off the camera"),
    ("Be quiet, Jarvis.", "be quiet"),
    ("Wait a moment.", "wait a moment"),
    ("Stop speaking.", "stop speaking"),
    ("Mute the mic.", "mute the mic"),
    ("What's connected?", "what's connected"),
    ("Forget it.", "forget it"),
    ("Typing mode.", "typing mode"),
    ("Stop there.", "stop there"),
)
# Generic places and names (no one's in particular); the key is the name.
PLACES: Final[tuple[tuple[str, str], ...]] = (
    ("What's the weather in Mumbai?", "Mumbai"),
    ("Remind me to call Priya.", "Priya"),
    ("Book a cab to Chennai Central.", "Chennai Central"),
    ("Send a message to Arjun.", "Arjun"),
    ("How far is Hyderabad from here?", "Hyderabad"),
    ("Is Lakshmi free this evening?", "Lakshmi"),
    ("Show me trains to Kolkata.", "Kolkata"),
    ("Add Rahul to the guest list.", "Rahul"),
    ("What's the time in Dubai?", "Dubai"),
    ("What time does Sunita land?", "Sunita"),
    ("Search for Mysuru Palace.", "Mysuru Palace"),
    ("Message Vikram about dinner.", "Vikram"),
    ("Plan a trip to Jaipur.", "Jaipur"),
    ("Call Anita on speaker.", "Anita"),
    ("Weather in Delhi tomorrow.", "Delhi"),
    ("Remind Kiran about the meeting.", "Kiran"),
    ("Open my notes about Pune.", "Pune"),
    ("Show photos from Shimla.", "Shimla"),
    ("Play the news from London.", "London"),
    ("Ask Meera when she is free.", "Meera"),
    ("Find a pharmacy near Bandra.", "Bandra"),
    ("Directions to Lucknow station.", "Lucknow"),
)
# Numbers and times: written so that a fair engine can match them (no leading zeros, no
# ordinals, no "o'clock"); never a source of corrections.
NUMBERS: Final[tuple[str, ...]] = (
    "Set a timer for 25 minutes.",
    "Wake me at 6:45 tomorrow.",
    "Remind me at 7:30 in the evening.",
    "What's 18 percent of 2,400?",
    "Add 3 kilos of rice to the list.",
    "My meeting is at 10:15.",
    "The bill was 450 rupees.",
    "Call me back in 15 minutes.",
    "The code is 4 7 2 9.",
    "Set an alarm for 5:20.",
    "It's 32 degrees outside.",
    "The train leaves at 9:40 from platform 4.",
    "Order 2 litres of milk.",
    "Split 1,200 between 4 people.",
    "Book a table for 7 on Saturday.",
    "The flight is at 11:40 tonight.",
    "Count down from 10.",
    "Add 250 grams of sugar.",
    "Remind me on March 21.",
    "The battery is at 80 percent.",
    "Room 304 on the second floor.",
    "Dial extension 2 1 4.",
    "It costs 1,999 rupees.",
)
REQUESTS: Final[tuple[tuple[str, str], ...]] = (
    ("What's on my calendar today?", "calendar today"),
    ("Read my latest email.", "latest email"),
    ("Add milk and bread to the shopping list.", "shopping list"),
    ("Remind me to water the plants.", "water the plants"),
    ("What's the weather like this weekend?", "weather"),
    ("Play some relaxing music.", "relaxing music"),
    ("Turn on the living room lights.", "living room lights"),
    ("Turn off the fan in the bedroom.", "fan in the bedroom"),
    ("How much did I spend this month?", "spend this month"),
    ("Summarise my unread messages.", "unread messages"),
    ("Start a note called groceries.", "note called groceries"),
    ("What's my next meeting?", "next meeting"),
    ("Show me today's brief.", "today's brief"),
    ("Is it going to rain tomorrow?", "rain tomorrow"),
    ("Pause the music.", "pause the music"),
    ("Read that again, please.", "read that again"),
    ("Draft a reply saying I'll be late.", "draft a reply"),
    ("Find the document about the electricity bill.", "electricity bill"),
    ("Open the vault.", "open the vault"),
    ("What did I ask you yesterday?", "ask you yesterday"),
    ("Thank you, Jarvis.", "thank you"),
    ("Good night, Jarvis.", "good night"),
)
OWN_TEMPLATE_2: Final = "Look up {word}."
OWN_TEMPLATE_4: Final = "Make a note about {word}."
# "Hey Jarvis", 30 ways (the wake word's clips: row 83; plan 3.3)
WAKE_WAYS: Final[tuple[str, ...]] = (
    "close to the microphone",
    "from across the room",
    "quietly",
    "as if you are tired",
    "with music playing",
    "quickly",
    "slowly",
    "a little louder",
    "while walking",
    "turned away",
    "in a low voice",
    "in a higher voice",
    "with a smile",
    "as a question",
    "firmly",
    "softly",
    "from the doorway",
    "with a fan running",
    "after a pause",
    "half asleep",
    "with the TV on",
    "from arm's length",
    "leaning back",
    "in your normal voice",
    "with a busy room",
    "calmly",
    "urgently",
    "while typing",
    "with your hand near your mouth",
    "as the first thing today",
)


@dataclass(frozen=True)
class PromptPlan:
    """The session's prompts and each one's key phrase (command accuracy, new words)."""

    prompts: tuple[Prompt, ...]
    keys: dict[str, str]
    own: frozenset[str]  # ids of the prompts that read one of his own words

    def by_id(self, prompt_id: str) -> Prompt | None:
        return next((p for p in self.prompts if p.id == prompt_id), None)


def _own_words(words: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for w in words:
        if w.strip():
            seen.setdefault(w.casefold(), w.strip())
    return list(seen.values())[:OWN_WORDS_BLOCK_2]


def _lines(block: int, own: list[str]) -> list[tuple[PromptKind, str, str, bool]]:
    """(kind, text, key, his word?) for one block's lines to listen to."""
    if block == 1:
        return [(PromptKind.COMMAND, t, k, False) for t, k in COMMANDS]
    if block == 3:
        return [(PromptKind.NUMBERS, t, "", False) for t in NUMBERS]
    if block == 2:
        mine = [(PromptKind.WORDS, OWN_TEMPLATE_2.format(word=w), w, True) for w in own]
        generic = [(PromptKind.PLACES, t, k, False) for t, k in PLACES]
        return (mine + generic)[: LINES[2]]
    again = [(PromptKind.WORDS, OWN_TEMPLATE_4.format(word=w), w, True) for w in own]
    asks = [(PromptKind.COMMAND, t, k, False) for t, k in REQUESTS]
    return (again[:OWN_WORDS_BLOCK_4] + asks)[: LINES[4]]


def _held_out(index: int, count: int) -> bool:
    """20 of a block's lines held out, the others spread through it (not all at the end)."""
    train = count - HELD_OUT_PER_BLOCK
    spaced = {round((i + 1) * count / (train + 1)) - 1 for i in range(train)}
    return index not in spaced


def build_prompts(own_words: Sequence[str] = ()) -> PromptPlan:
    """The 120 prompts, his words (`own_words`: his phrases, then any he typed) in blocks 2 and 4.
    A "Hey Jarvis" comes after every third or fourth line, so no block ends on a run of them."""
    own = _own_words(own_words)
    prompts: list[Prompt] = []
    keys: dict[str, str] = {}
    mine: set[str] = set()
    wake_index = 0
    for block in range(1, BLOCKS + 1):
        lines = _lines(block, own)
        wakes = WAKES[block]
        every = max(1, len(lines) // wakes)
        line_no = wake_no = 0
        for i, (kind, text, key, is_own) in enumerate(lines):
            line_no += 1
            pid = f"b{block}_{kind.value[:4]}_{line_no:02d}"
            prompts.append(
                Prompt(id=pid, block=block, kind=kind, text=text, held_out=_held_out(i, len(lines)))
            )
            if key:
                keys[pid] = key
            if is_own:
                mine.add(pid)
            if (i + 1) % every == 0 and wake_no < wakes:
                wake_no += 1
                prompts.append(_wake(block, wake_no, wake_index))
                wake_index += 1
        while wake_no < wakes:  # a block with few lines still has all its "Hey Jarvis"
            wake_no += 1
            prompts.append(_wake(block, wake_no, wake_index))
            wake_index += 1
    return PromptPlan(prompts=tuple(prompts), keys=keys, own=frozenset(mine))


def _wake(block: int, number: int, index: int) -> Prompt:
    return Prompt(
        id=f"b{block}_wake_{number:02d}",
        block=block,
        kind=PromptKind.WAKE,
        text=WAKE_TEXT,
        held_out=index % WAKE_HELD_OUT_EVERY == WAKE_HELD_OUT_EVERY - 1,
        how=WAKE_WAYS[index % len(WAKE_WAYS)],
    )


def scored(prompt: Prompt) -> bool:
    """Held out and listened to (a "Hey Jarvis" is the wake word's, not the engines' test)."""
    return prompt.held_out and prompt.kind is not PromptKind.WAKE


__all__ = [
    "BLOCK_TITLES",
    "COMMANDS",
    "HELD_OUT_PER_BLOCK",
    "LINES",
    "NUMBERS",
    "PLACES",
    "REQUESTS",
    "TYPED_WORDS_MAX",
    "WAKES",
    "WAKE_TEXT",
    "WAKE_WAYS",
    "PromptPlan",
    "build_prompts",
    "scored",
]
