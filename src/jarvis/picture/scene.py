# src/jarvis/picture/scene.py
"""What may be said of a picture: the look's description, screened sentence by sentence (R11.1
D17, D21-D; security review H2 and M1; Layer 4, guardrails). Plain code, no model.

Two screens, both by whole sentences (a sentence is kept as the look wrote it, or dropped):

- `vet_scene`, for EVERY picture (the look's `has_person` is not trusted): a sentence is dropped
  when it is in another script, hints at who someone is ("looks like", "famous", "the minister"),
  introduces someone ("this is ...", in any letter case), starts with a lower-case word that is
  not a plain opener (a name written small), carries a word that was withheld elsewhere (a
  subject, a claimed caption), or carries a capitalised word (ALL CAPS too) that is not its plain
  opener and is neither printed in the picture nor part of a vetted thing's name. So "The Gateway
  of India stands beside the sea." stays when the Gateway is a vetted subject, and "A crane
  beside Rajesh Examplekar." goes.
- `screen_scene`, in addition for a picture with a person: every capitalised run must belong to
  a named thing ("a Samsung phone"), and the opener must be a plain one.

The price, on purpose: a description that names a place the picture neither prints nor lists as
a vetted thing loses that sentence.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.picture.words import (
    HINT,
    INTRODUCES,
    OPENERS,
    SENTENCE,
    WORD,
    capitalised,
    is_thing_word,
    plain,
    run_end,
    words_of,
)

PERSON_FALLBACK = "There is a person in the picture."


def _sentences(scene: str) -> list[str]:
    return [s for s in SENTENCE.split(scene.strip()) if s]


def stop_words(names: Sequence[str]) -> frozenset[str]:
    """The words of names withheld elsewhere (any letter case), never a plain opener."""
    return frozenset(w for name in names for w in words_of(name) if len(w) > 1) - OPENERS


def _opener_ok(first: str) -> bool:
    """A sentence opens with a plain opener, or with a capital (which is then vetted)."""
    return capitalised(first) or plain(first) in OPENERS


def _vetted(sentence: str, allowed: frozenset[str], banned: frozenset[str]) -> bool:
    if not sentence.isascii() or HINT.search(sentence) or INTRODUCES.search(sentence):
        return False
    words = WORD.findall(sentence)
    if not words or not _opener_ok(words[0]) or banned & set(words_of(sentence)):
        return False
    for i, word in enumerate(words):
        if not capitalised(word) or (i == 0 and plain(word) in OPENERS):
            continue
        if plain(word) not in allowed:
            return False
    return True


def vet_scene(scene: str, allowed: frozenset[str], banned: Sequence[str] = ()) -> str:
    """The sentences of `scene` that name nothing the picture does not show in its own words.
    `allowed`: the folded words printed in the picture and of the vetted things' names. `banned`:
    names withheld elsewhere. Nothing left: ""."""
    stop = stop_words(banned)
    return " ".join(s for s in _sentences(scene) if _vetted(s, allowed, stop))


# ---- in addition, for a picture with a person ---------------------------------------------------
def _capital_runs_ok(words: list[str]) -> bool:
    """Every capitalised word after the first belongs to a named thing: its run of capitalised
    words holds a thing word, or the word right after the run is one ("a Samsung phone")."""
    i = 1
    while i < len(words):
        if not capitalised(words[i]):
            i += 1
            continue
        j = run_end(words, i)
        run = [plain(w) for w in words[i : j + 1]]  # the run and the word after it
        if not any(is_thing_word(w) for w in run):
            return False
        i = j
    return True


def _sentence_ok(sentence: str, banned: frozenset[str]) -> bool:
    if not sentence.isascii() or HINT.search(sentence):
        return False  # another script has no capitals to check; a hint is a hint
    words = WORD.findall(sentence)
    if not words:
        return False
    if capitalised(words[0]) and words[0].lower() not in OPENERS:
        return False
    if banned & set(words_of(sentence)):
        return False
    return _capital_runs_ok(words)


def screen_scene(scene: str, banned: Sequence[str] = ()) -> str:
    """What may be said of a picture with a person: the sentences that only describe what is
    visible. `banned`: names withheld elsewhere (a subject, a claimed caption), in any letter
    case. Nothing left: `PERSON_FALLBACK`."""
    stop = stop_words(banned)
    kept = [s for s in _sentences(scene) if _sentence_ok(s, stop)]
    return " ".join(kept) or PERSON_FALLBACK


__all__ = ["PERSON_FALLBACK", "screen_scene", "stop_words", "vet_scene"]
