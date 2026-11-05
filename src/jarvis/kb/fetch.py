# src/jarvis/kb/fetch.py
"""Fetching the text of a saved link (R2 D10; Layer 6 via the existing web door).

Only through `WebAllowance` and the web provider, in the order `web/tools.py` uses:
    reserve 1 credit -> provider.extract(url) -> settle / refund / latch
Tavily fetches the page, never this server (no SSRF). The page's words are other people's: the
caller stores them as a `PageExcerpt` and every reader fences them. A link whose path or query
holds an email address, a phone number or anything the sensitive filter flags is never sent
(a planted link must not carry the owner's data out). Vendor text never reaches the owner.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from jarvis.kb.models import (
    MAX_EXCERPT,
    MAX_PAGE_TITLE,
    NotesError,
    normalise_link,
    private_part,
)
from jarvis.tools.external import clean_text, model_text
from jarvis.web.allowance import AllowanceReached, AllowanceUnreadable
from jarvis.web.ports import CreditsExhausted
from jarvis.web.service import WebService

MAX_FETCHED = 12_000
MSG_WEB_OFF = "Fetching page text isn't set up on this server."
MSG_FAILED = "JARVIS couldn't read that page right now. No web credit was used."
MSG_USED_UP = "This month's free web credits are used up. They start again on the 1st."
MSG_UNREADABLE = "JARVIS can't read this month's web credit count, so nothing was fetched."


@dataclass(frozen=True)
class PageText:
    title: str
    excerpt: str
    left: int  # web credits left this month


def _clean(raw: str) -> str:
    return model_text(unicodedata.normalize("NFC", clean_text(raw))).strip()


async def fetch_page(web: WebService | None, url: str) -> PageText:
    """Read `url` through the allowance and the provider. Raises `NotesError` in plain words."""
    if web is None:
        raise NotesError(409, "web_off", MSG_WEB_OFF)
    link = normalise_link(url)
    if private_part(link) is not None:
        raise NotesError(
            422, "bad_url", "That link holds private details, so it was not fetched.", "private"
        )
    allowance = web.allowance
    try:
        r = await allowance.reserve(1, kind="read")
    except AllowanceReached:
        raise NotesError(409, "allowance", MSG_USED_UP) from None
    except AllowanceUnreadable:
        raise NotesError(409, "allowance", MSG_UNREADABLE) from None
    try:
        page = await web.provider.extract(link)
    except CreditsExhausted:
        await allowance.latch()
        raise NotesError(409, "allowance", MSG_USED_UP) from None
    except Exception:  # noqa: BLE001 - nothing was charged; the vendor's words stay out
        await allowance.refund(r)
        raise NotesError(502, "fetch_failed", MSG_FAILED) from None
    charged = page.credits if page.credits is not None else int(page.ok)
    if charged == 0:
        await allowance.refund(r)
    else:
        await allowance.settle(r, charged=charged)
    text = _clean(page.text) if page.ok else ""
    if not text:
        raise NotesError(502, "fetch_failed", MSG_FAILED)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return PageText(first[:MAX_PAGE_TITLE], text[:MAX_EXCERPT], r.left)


__all__ = ["MAX_FETCHED", "PageText", "fetch_page", "private_part"]
