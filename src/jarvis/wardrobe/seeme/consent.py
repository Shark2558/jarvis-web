# src/jarvis/wardrobe/seeme/consent.py
"""R13.1 Part C: his typed YES, specific and bound to provider, model and location
(docs/plans/r13-1-try-on.md D11; plan review M3).

    {prefix}tryon_consent/{uid}   {v, kid, owner, blob, updated_at}
        blob = AES-GCM({at, version, hash, provider, model, location}), purpose `tryon`, AAD
        `model.aad_consent(uid)`

- The card's fixed lines (`words(desc, cache=)`): what is sent (his photo, the photo he gives of a
  garment he may buy, up to two of his pieces; never a private piece or his measurements), to whom
  (provider, model, where it is processed), what Google keeps (no training without permission;
  may log for abuse checks; its cache off, or "up to 24 hours" when `tryon_cache`), every
  picture's ₹ first under his cap, Content Credentials, the model's end date, how to withdraw.
- `give(uid, typed, version, desc)`: exactly `YES` once trimmed (letters only: "yes", "Yes",
  "YES!" are refused and nothing changes) for the CURRENT template version.
- The hash is SHA-256 over the FIXED template: its version, provider, model, location and location
  words. NEVER the day's ₹ or the cap (those are on every estimate): a moved rate keeps consent
  current; a different provider, model, location or template version asks again.
- Only from a signed-in browser (the route's console-only rule). Withdraw = delete his photo
  (`vault.PersonPhoto.delete` takes this document with it).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from jarvis.llm.tryon import TryOnDescription
from jarvis.storage.docs import Docs, Set
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import VERSION as DOC_VERSION
from jarvis.wardrobe.seeme.vault import Sealer
from jarvis.wardrobe.tryon.http import ConsentView
from jarvis.wardrobe.tryon.model import CONSENT, PURPOSE, YES, aad_consent

VERSION = "c2"  # the template's version: a change of its words asks for his YES again
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")  # fmt: skip


def day_words(iso: str) -> str:
    """ "28 May 2027" (fixed English words)."""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return ""
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def template_text(desc: TryOnDescription) -> str:
    """What the hash covers: the template's version and who processes it, where. Nothing else."""
    fixed = {"version": VERSION, "provider": desc.provider, "model": desc.model,
             "location": desc.location, "location_words": desc.location_words}  # fmt: skip
    return json.dumps(fixed, sort_keys=True, separators=(",", ":"))


def digest(desc: TryOnDescription) -> str:
    return hashlib.sha256(template_text(desc).encode()).hexdigest()


def words(desc: TryOnDescription, *, cache: bool) -> tuple[str, ...]:
    lines = [
        texts.SENT_LINE,
        texts.TO_WHOM_LINE.format(
            provider=desc.provider, model=desc.model_words, where=desc.location_words
        ),  # fmt: skip
        texts.KEEPS_LINE,
        texts.CACHE_ON_LINE if cache else texts.CACHE_OFF_LINE,
        texts.PRICE_LINE,
        texts.MARK_LINE,
    ]
    if desc.retires_on:
        lines.append(texts.END_LINE.format(day=day_words(desc.retires_on)))
    return (*lines, texts.WITHDRAW_LINE)


def is_yes(typed: str) -> bool:
    return isinstance(typed, str) and typed.strip() == YES


class Consent:
    def __init__(
        self, docs: Docs, prefix: str, sealer: Sealer, *, now: Callable[[], datetime]
    ) -> None:
        self.docs, self.prefix, self.sealer, self.now = docs, prefix, sealer, now

    def path(self, uid: str) -> str:
        return f"{self.prefix}{CONSENT}/{uid}"

    async def _record(self, uid: str) -> dict[str, Any] | None:
        doc = await self.docs.get(self.path(uid))
        if doc is None or doc.get("owner") != uid:
            return None
        plain = self.sealer.open(PURPOSE, aad_consent(uid), doc.get("blob"))
        if plain is None:
            return None
        try:
            rec = json.loads(plain)
        except ValueError:
            return None
        return rec if isinstance(rec, dict) else None

    async def given_at(self, uid: str) -> datetime | None:
        """When he typed YES (for the Privacy export), or None."""
        rec = await self._record(uid)
        try:
            return None if rec is None else datetime.fromisoformat(str(rec.get("at")))
        except ValueError:
            return None

    async def current(self, uid: str, desc: TryOnDescription) -> bool:
        rec = await self._record(uid)
        return rec is not None and rec.get("hash") == digest(desc)

    async def view(self, uid: str, desc: TryOnDescription, *, cache: bool) -> ConsentView:
        rec = await self._record(uid)
        at = None
        if rec is not None:
            try:
                at = datetime.fromisoformat(str(rec.get("at")))
            except ValueError:
                at = None
        current = rec is not None and rec.get("hash") == digest(desc)
        return ConsentView(
            given=rec is not None, at=at, current=current, version=VERSION,
            words=words(desc, cache=cache),
        )  # fmt: skip

    async def give(
        self, uid: str, typed: str, version: str, desc: TryOnDescription, *, cache: bool
    ) -> ConsentView:
        if not is_yes(typed):
            raise SeeMeRefused(422, "not_yes", texts.NOT_YES)
        if version != VERSION:
            raise SeeMeRefused(422, "consent_needed", texts.OLD_WORDS)
        at = self.now()
        rec = {"at": at.isoformat(), "version": VERSION, "hash": digest(desc),
               "provider": desc.provider, "model": desc.model,
               "location": desc.location}  # fmt: skip
        blob = self.sealer.seal(PURPOSE, aad_consent(uid), json.dumps(rec).encode())
        body = {"v": DOC_VERSION, "kid": self.sealer.kid, "owner": uid, "blob": blob,
                "updated_at": at.isoformat()}  # fmt: skip
        await self.docs.write([Set(self.path(uid), body)])
        return ConsentView(given=True, at=at, current=True, version=VERSION,
                           words=words(desc, cache=cache))  # fmt: skip


__all__ = ["VERSION", "Consent", "day_words", "digest", "is_yes", "template_text", "words"]
