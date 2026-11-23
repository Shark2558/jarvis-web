# src/jarvis/buildbook/writer/texts.py
"""R6.3 D6-D8, D11-D13: the writer's own words (owner-facing, plain, rupees only: never a dollar
figure, a model id or a vendor's own error text). A brain's name is the registry's `label` and its
maker `jarvis.llm.write.maker` (L3), filled in where a sentence needs them.
"""

from __future__ import annotations

from jarvis.billing.service import rupees

# ---- refusals: `http.Refusal.detail` by code ----------------------------------------------------
REFUSED: dict[str, str] = {
    "not_primary": "Only the main owner's console runs the Book's writer.",
    "no_key": "No writer brain is set up on this server.",
    "no_ai": "No-AI is on, so nothing is written. Turn it off to go on.",
    "no_brain": "That writer brain isn't set up on this server.",
    "not_yes": "Type YES in capital letters to go ahead. Nothing was changed.",
    "estimate_changed": "The estimate changed since you saw it. Look at the new one and type YES.",
    "terms_changed": "Your choice changed since those words were shown. Nothing was saved.",
    "running": "A writing run is already going. Stop it, or let it finish first.",
    "busy": "A step is already running. Try again in a moment.",
    "pick_needed": "Pick the writer and confirm its caps first.",
    "already_written": "Every page of this release is already written.",
    "nothing_to_update": "No page waits for an update.",
    "use_first": (
        "This update is more than your release cap's worth, or there is no earlier AI page to "
        "carry from, so it is a full write with its own estimate and YES."
    ),
    "bad_cap": "A cap is outside its bounds. Nothing was saved.",
    "unknown_brain": "That brain isn't known on this server.",
    "not_offered": "That brain's price isn't known, so it isn't offered.",
    "no_page": "That page isn't in this release's full book.",
    "no_trial": "That trial page isn't there.",
    "unavailable": "The writer's records can't be read right now. Nothing was spent.",
    "rate_limited": "Too many requests; wait a moment.",
}
YES_NEEDED = "This choice lets the Book spend more. Read the words above and type YES to save it."

# ---- the grants that need his typed YES (D7, H2) -------------------------------------------------
PICK_WORDS = (
    "{label} (the balanced tier) writes your Book's pages: up to {first} for the first full "
    "write, {release} a release and {month} a month."
)
PCT_WORDS = "It stops before your Vitals month passes {pct} % of your monthly limit."
RAISE_WORDS = "This raises the {what} from {old} to {new}."
PCT_RAISE_WORDS = "This raises the line it stops at from {old} % to {new} % of your monthly limit."
PAID_WORDS = "{label} is a paid brain: a page costs about {page} and a worst case {hold}."
TRAINS_WORDS = (
    "{label} may let {maker} use what it reads to improve its products: only JARVIS's public "
    "code and the facts computed from it are sent. This is separate from the talk-through's "
    "choice of brain."
)
AUTO_WORDS = (
    "Up to {release} a release and {month} a month (your caps), by itself after each deploy, "
    "with no question asked."
)
CAP_NAMES = {
    "trial": "trial cap",
    "first": "first full write's cap",
    "release": "release cap",
    "month": "monthly cap",
}

# ---- what is sent, and to whom (D6, D7) ----------------------------------------------------------
SENT_WORDS = (
    "{label} ({maker}) reads only JARVIS's public code and the facts computed from it, with "
    "names, handles and places removed, and no test or example data."
)

# ---- runs (D5-D7, D12) ---------------------------------------------------------------------------
WHY = {
    "cap": "The cap is reached: {left} page(s) keep the generated text. Go on with a new YES.",
    "month": "This month's cap is reached: {left} page(s) wait for next month or a raise.",
    "limit": "It would pass {pct} % of your monthly limit: {left} page(s) wait.",
    "over_hold": "A page was billed above its worst case, so the run stopped to be safe.",
    "unreadable": "The writer's money records can't be read, so it stopped. Nothing was spent.",
    "new_release": "A new release came: what was written is kept, and the rest joins its update.",
    "stopped": "You stopped it: what was written is kept.",
    "no_ai": "No-AI is on: the run waits until it is off.",
    "slow": (
        "Pages take longer than the clock allows: keep Book settings open to go on, or ask for "
        "the background job."
    ),
    "unavailable": "The writer's brain isn't answering right now: it tries again later.",
    "done": "",
}

# ---- notices (D11): R6's kinds, the writer's own words, ids, counts and rupees only -------------
NOTICE_PAGES = "The AI-written pages for {label} are sealed ({count} pages, about {inr})."
NOTICE_UPDATE = "The AI pages wait for your Update (about {inr})."
NOTICE_STORAGE = (
    "The build books use {used} of {limit} MiB ({pct} %): an older release goes first when a new "
    "one needs the room."
)
NOTICE_FAILED = "The AI writer stopped: {why}"


def inr(value: float) -> str:
    """Rupees as the console shows them (two decimals under Rs 100, whole rupees above)."""
    return rupees(value)


__all__ = [
    "AUTO_WORDS",
    "CAP_NAMES",
    "NOTICE_FAILED",
    "NOTICE_PAGES",
    "NOTICE_STORAGE",
    "NOTICE_UPDATE",
    "PAID_WORDS",
    "PCT_RAISE_WORDS",
    "PCT_WORDS",
    "PICK_WORDS",
    "RAISE_WORDS",
    "REFUSED",
    "SENT_WORDS",
    "TRAINS_WORDS",
    "WHY",
    "YES_NEEDED",
    "inr",
]
