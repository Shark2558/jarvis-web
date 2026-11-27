# src/jarvis/calls/privacy.py
"""Calls in the Privacy panel (R18 combined review; R2 D14's `PrivacySource`; cross-cutting
security). Before the review the calls kept data with no Privacy row: a call could be deleted
only in Calls or by the 30-day job, and never exported. Four rows, in the panel's "Phone calls"
section, registered by `api.r18_wiring.r18_privacy_sources`:

- `calls`: every call record with its sealed parts (audio, transcript, summary), the call cards
  and the numbers called before. Export: each call's time, length, languages, ₹, summary and
  transcript; the number only masked (it is the other person's), the audio not at all (Calls plays
  and downloads it). Delete (passkey: it can't be brought back): all of them. Today's counters and
  the months' ₹ stay: they keep the daily limits and the calls cap and hold no number.
- `call_settings`: his settings (first name, caps, languages, answering, records, paid options).
  Delete puts the defaults back.
- `call_desk`: the laptop's call desk link (id, version, when; its seed is sealed and never
  shown) and an unused link code. Delete is Unlink.
- `call_lang_check`: the language check's results, his voice scores among them. Delete: no Indian
  language is offered until the check runs again.

Nothing here logs or exports a number in full, a seed, a key or audio.
"""

from __future__ import annotations

from typing import Any, Protocol

from jarvis.calls.cards import masked
from jarvis.calls.models import CallRecord
from jarvis.calls.records import RecordKeeper, RecordRefused
from jarvis.calls.store import DocCallStore
from jarvis.logging import get_logger
from jarvis.privacy.export import fingerprint
from jarvis.privacy.ports import CategoryView, PrivacySource

log = get_logger(__name__)

SECTION = "Phone calls"
OURS = "Firestore, encrypted by JARVIS"
GOOGLE = "Firestore, Google-encrypted"
EXPORT_MAX = 300  # 30 days at the most of 10 calls a day
NO_AUDIO = "Recordings are not in the export: play or download each one in Calls."


def _base(source: PrivacySource, **kw: Any) -> dict[str, Any]:
    return {"id": source.id, "section": source.section, "label": source.label, **kw}


# ---- calls -------------------------------------------------------------------------------------
class CallsPrivacy:
    id = "calls"
    section = SECTION
    label = "Your calls"

    def __init__(self, store: DocCallStore, keeper: RecordKeeper) -> None:
        self._store, self._keeper = store, keeper

    async def describe(self, uid: str) -> CategoryView:
        rows = await self._store.call_rows(uid)
        return CategoryView(
            **_base(
                self,
                what=(
                    "Each call JARVIS placed or answered for you: when, how long, the languages "
                    "and the ₹, with its transcript, its English summary and its audio recording; "
                    "the call cards you wrote and the numbers called before. Numbers are sealed."
                ),
                unit="calls",
                retention="30 days unless you Keep a call (Calls → Settings: 1 to 30 days)",
                where=OURS,
            ),
            count=len(rows),
            encrypted_by_jarvis=True,
            export=True,
            delete="passkey" if rows else "none",
            recoverable=False,
            note=(
                "Today's call counters and this month's ₹ stay: they keep the daily limits and "
                "the calls cap, and hold no number."
            ),
            rev=fingerprint("calls", sorted(rows)),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        records = await self._store.list_records(uid, limit=EXPORT_MAX)
        return {"calls": [await self._one(uid, r) for r in records], "audio": NO_AUDIO}

    async def _one(self, uid: str, r: CallRecord) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": r.id,
            "direction": r.direction.value,
            "number": masked(r.number_e164),
            "contact_name": r.contact_name,
            "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "seconds": r.seconds,
            "languages": list(r.languages_used),
            "cost_inr": r.cost_inr,
            "recorded": r.recorded,
            "objected": r.objected,
            "kept": r.keep,
        }
        try:
            summary = await self._keeper.summary(uid, r.id)
            transcript = await self._keeper.transcript(uid, r.id)
        except RecordRefused as exc:  # a part that doesn't open: said, never a guess
            log.warning("call part not exported", extra={"code": exc.code})
            return out | {"note": exc.words}
        out["summary"] = summary.model_dump(mode="json") if summary else None
        out["transcript"] = (
            [ln.model_dump(mode="json") for ln in transcript.lines] if transcript else []
        )
        return out

    async def delete(self, uid: str) -> int:
        await self._keeper.blobs.wipe(uid)  # the sealed parts first: their keys go
        gone = await self._store.wipe_calls(uid)
        log.info("calls deleted from the Privacy panel", extra={"calls": gone})
        return gone


# ---- settings ------------------------------------------------------------------------------------
class CallSettingsPrivacy:
    id = "call_settings"
    section = SECTION
    label = "Calls settings"

    def __init__(self, store: DocCallStore) -> None:
        self._store = store

    async def describe(self, uid: str) -> CategoryView:
        saved = await self._store.settings_saved(uid)
        current = (await self._store.settings(uid)).model_dump(mode="json")
        return CategoryView(
            **_base(
                self,
                what=(
                    "Your first name for the opening line, the calls caps, your default "
                    "languages, answering the calls you miss, how long calls are kept, and "
                    "Sarvam or the balanced brain."
                ),
                unit="setting",
                retention="Until you change or delete it",
                where=GOOGLE,
            ),
            count=1 if saved else 0,
            export=True,
            delete="simple" if saved else "none",
            recoverable=False,
            note=(
                "Deleting puts the defaults back: ₹200 a month, ₹20 and 6 minutes a call, "
                "answering off, Sarvam and the balanced brain off, and no first name (calls wait "
                "until you add it)."
            ),
            rev=fingerprint("call_settings", saved, current),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return {"settings": (await self._store.settings(uid)).model_dump(mode="json")}

    async def delete(self, uid: str) -> int:
        return 1 if await self._store.reset_settings(uid) else 0


# ---- the call desk -------------------------------------------------------------------------------
class _Desks(Protocol):
    async def linked_view(self, uid: str) -> dict[str, Any] | None: ...

    async def code_waiting(self, uid: str) -> bool: ...


class _Door(Protocol):
    async def unlink(self, uid: str) -> dict[str, Any]: ...


class CallDeskPrivacy:
    id = "call_desk"
    section = SECTION
    label = "Call desk link"

    def __init__(self, desks: _Desks, door: _Door) -> None:
        self._desks, self._door = desks, door

    async def describe(self, uid: str) -> CategoryView:
        link = await self._desks.linked_view(uid)
        code = await self._desks.code_waiting(uid)
        held = link is not None or code
        return CategoryView(
            **_base(
                self,
                what=(
                    "The link to the call desk on your laptop: its id, its version and when it "
                    "was linked (its key is sealed and never shown), and a link code you asked "
                    "for until it is used or expires."
                ),
                unit="link",
                retention="Until you unlink it (a code: 10 minutes)",
                where=OURS,
            ),
            count=1 if link is not None else 0,
            encrypted_by_jarvis=True,
            export=link is not None,
            delete="simple" if held else "none",
            recoverable=False,
            note="Deleting unlinks the desk: link it again with a new code from Calls → Settings.",
            rev=fingerprint("call_desk", link, code),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        link = await self._desks.linked_view(uid)
        return None if link is None else {"desk": link}

    async def delete(self, uid: str) -> int:
        out = await self._door.unlink(uid)
        return 1 if out.get("unlinked") else 0


# ---- the language check --------------------------------------------------------------------------
class LanguageCheckPrivacy:
    id = "call_lang_check"
    section = SECTION
    label = "Language check results"

    def __init__(self, store: DocCallStore) -> None:
        self._store = store

    async def describe(self, uid: str) -> CategoryView:
        results = await self._store.language_results()
        basis = sorted((r.lang, r.option.value, r.checked_at.isoformat()) for r in results)
        return CategoryView(
            **_base(
                self,
                what=(
                    "How each language and speech option did in the language check: what it "
                    "heard right, its timings, its ₹ a minute, why one failed, and the 1–5 voice "
                    "scores you entered. No audio is kept."
                ),
                unit="results",
                retention="Until the next check of that language, or until you delete them",
                where=GOOGLE,
            ),
            count=len(results),
            export=bool(results),
            delete="confirm" if results else "none",
            recoverable=False,
            note=(
                "Deleting means no Indian language is offered on a call until the check runs "
                "again; English goes back to “not yet checked”."
            ),
            rev=fingerprint("call_lang_check", basis),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        results = await self._store.language_results()
        return {"results": [r.model_dump(mode="json") for r in results]} if results else None

    async def delete(self, uid: str) -> int:
        return await self._store.delete_language_results()


def calls_privacy_sources(
    store: DocCallStore, keeper: RecordKeeper, desks: _Desks, door: _Door
) -> tuple[PrivacySource, ...]:
    """The four rows, in the panel's order."""
    return (
        CallsPrivacy(store, keeper),
        CallSettingsPrivacy(store),
        CallDeskPrivacy(desks, door),
        LanguageCheckPrivacy(store),
    )


__all__ = [
    "SECTION",
    "CallDeskPrivacy",
    "CallSettingsPrivacy",
    "CallsPrivacy",
    "LanguageCheckPrivacy",
    "calls_privacy_sources",
]
