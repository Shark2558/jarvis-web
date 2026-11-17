# src/jarvis/wardrobe/seeme/texts.py
"""R13.1 Part C's fixed words (docs/plans/r13-1-try-on.md D11-D15, D18, D22): every owner-facing
sentence of "See it on me", in one place. ₹ only (never a dollar figure); no label of his, no text
from a garment's photo or Google's answer is ever put into one of these."""

from __future__ import annotations


class SeeMeRefused(Exception):  # noqa: N818 - a refusal in plain words, not a bug
    """Every refusal of See it on me: an HTTP status, a code (`http.SEEME_ERRORS`, the console
    branches on it) and fixed words. `str()` is the code only (never the words in a log). `inr`
    is what this refusal added to his spend (the audit's number): 0 unless kept at the hold."""

    def __init__(self, status: int, code: str, words: str, *, inr: float = 0.0) -> None:
        super().__init__(code)
        self.status, self.code, self.words, self.inr = status, code, words, inr


# ---- off, and why (503) ---------------------------------------------------------------------
OFF_NO_STORE = "See it on me needs JARVIS's storage, which isn't set up on this server."
OFF_NO_KEY = "See it on me needs JARVIS's token key, which isn't set up on this server."
OFF_PICTURES = "Pictures are not set up on this server."
OFF_BY_HIM = "See it on me is switched off in Try-on settings."
OFF_TRYON = "Try-on is switched off on this server."
RETIRED = (
    "Google has retired this image model, so See it on me is off until a newer one is set. JARVIS "
    "will offer the next one, with your YES again."
)
NOTICE = "Google may retire this image model on {day}."
NO_AI = "See it on me is off while JARVIS runs without AI (No-AI mode)."
NO_WARDROBE = "Your wardrobe isn't ready yet: try again in a minute."
INVALID = "That request isn't one See it on me takes: refresh the page and try again."
UNAVAILABLE_NOW = "See it on me can't be reached just now. Try again in a minute."
CONSOLE_ONLY = "See it on me works only in the JARVIS console, signed in: not from a script."

# ---- his photo, a garment's photo (D12, D22) ------------------------------------------------
NOT_JPEG = "Send the photo as a JPEG."
TOO_LARGE = "This photo is too detailed to send: try a plainer background."
TOO_WIDE = "A photo is at most 1,568 pixels a side."
PHOTO_GONE = "Your photo and your YES are deleted."
NO_PHOTO = "Add your photo for See it on me first."
NOT_A_GARMENT = "Choose a top, a bottom or an outer layer, and one of the fixed colours."
TOO_MANY = "You have {n} garment photos: delete one first."
NO_GARMENT = "Add the photo of the garment you are thinking of buying first."
GARMENT_GONE = "That garment's photo isn't there any more."
GARMENT_DELETED = "The garment's photo is deleted."

# ---- consent (D11) --------------------------------------------------------------------------
CONSENT_NEEDED = "Read what is sent, and type YES, first."
NOT_YES = "Type YES in capitals to agree; nothing changed."
OLD_WORDS = "The words have changed: read them again and type YES."

# ---- his pieces (D13.1) ---------------------------------------------------------------------
PRIVATE = "A private piece is never sent."
NO_FRONT = "It has no front photo yet: add one in Camera, Wardrobe."
NOT_SENDABLE = "Only a top, a bottom or an outer layer of yours goes in the picture."
SAME_SLOT = "Only one of yours a slot, and never in the new garment's slot."
NO_WORDS = "JARVIS can't describe this piece in its fixed words, so nothing was sent."
NOT_HIS = "That piece isn't in your wardrobe."
PAIR_WITH = "With your {words}."
PAIR_NONE = (
    "Nothing of yours that is ready goes with it just now, so the picture would show the new "
    "garment alone."
)
PAIR_OFF = (
    "Your wardrobe's suggestions can't be read just now: pick pieces yourself, or show the new "
    "garment alone."
)

# ---- money (D13, D15) -----------------------------------------------------------------------
CONFIRM = "Make 1 picture of you in {garment}{mine}? {about}. {spent} of {cap} used this month."
CONFIRM_COST = "Confirm the price first."
RAISE_CONFIRM = "Raising the limit to {cap} needs your OK first."
PRICE_CHANGED = "The price changed: look at it again before you make the picture."
BUSY = "A picture is being made: wait for it to finish."
CAP_REACHED = (
    "This month's try-on limit of {cap} is used: {spent} spent. It resets on {day}, or raise it "
    "in Try-on settings."
)
CAP_OFF = "Your monthly try-on limit is ₹0, so See it on me is off. Raise it in Try-on settings."
CAP_UNREADABLE = (
    "JARVIS couldn't read this month's try-on spending just now, so nothing was sent. Try again "
    "in a minute."
)

# ---- the call (D13.5) -----------------------------------------------------------------------
BLOCKED = (
    "Google didn't make this picture (its safety check). It may still be charged ({about}). Try "
    "another photo of you: standing, plain background, fitted clothes."
)
MAYBE_BILLED = (
    "Google didn't answer in time, so there is no picture. It may still be charged ({about})."
)
GOOGLE_BUSY = "Google is busy: try again in a minute. Nothing was charged."
UNAVAILABLE = "Google's image model isn't available just now. Nothing was charged."
NOT_KEPT = "This picture is too large to keep: it is shown once and not kept."  # D's words for
# a `PictureView` with `kept=False` and `until=None` (shown once; INTEGRATION-C, Fix C-1)
WITHDRAWN = (
    "Your photo or the garment's photo was deleted while the picture was being made, so it isn't "
    "kept. It may still be charged ({about})."
)
NOT_SAVED = (
    "Google made the picture, but JARVIS couldn't save it, so it can't be shown. It may still be "
    "charged ({about})."
)
PICTURE_GONE = "That picture isn't there any more."
PICTURE_DELETED = "The picture is deleted."
TOO_MANY_KEPT = "You keep {n} pictures already: delete one, or stop keeping one, first."

# ---- the consent's fixed lines (D11), the template's words ------------------------------------
SENT_LINE = (
    "What is sent: your photo, the photo you give of a garment you are thinking of buying, and the "
    "photos of up to two of your own pieces worn with it. Never a private piece, your "
    "measurements or anything else."
)
TO_WHOM_LINE = "To whom: {provider}, {model}, {where}."
KEEPS_LINE = (
    "What Google keeps: it says it won't use your pictures to train its models without your "
    "permission, and it may log requests to check for abuse."
)
CACHE_OFF_LINE = "Google's own short-term cache of requests is switched off for JARVIS."
CACHE_ON_LINE = "Google may keep each request in its own cache for up to 24 hours."
PRICE_LINE = (
    "Every picture shows its price in rupees, with GST, before anything is sent, under your "
    "monthly try-on limit."
)
MARK_LINE = "Google adds Content Credentials (C2PA) to every picture it makes."
END_LINE = "Google supports this model until at least {day}; a newer model asks for your YES again."
WITHDRAW_LINE = "To withdraw, delete your photo for See it on me: your YES goes with it."
