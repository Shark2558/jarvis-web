# src/jarvis/privacy/service.py
"""The privacy dashboard's service (R2 D14; cross-cutting security).

    view        every registered category, one row each (a failing source keeps its row)
    export      one category as JSON (never a secret)
    export_all  "Download everything": every exportable category except vault files
    delete      one category: the delete class decides what must be proven first

Delete classes (`CategoryView.delete`):
    none      explained, never deletable here
    simple    a setting or a link he can make again (the console's confirm dialog)
    confirm   a confirm dialog that lists what goes
    passkey   content that can't be brought back: with passkeys in force, a passkey check for
              purpose `privacy_delete` bound to (category id, rev); otherwise the typed word
              DELETE plus a Google sign-in less than 5 minutes old

A `rev` that no longer matches (the data changed since he looked) is a 409 and burns no proof.
Every export and delete is audited as agent `owner`: the category and a count, never content.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from jarvis.core.guardrails import ActionRisk, InputRejected
from jarvis.logging import get_logger
from jarvis.permissions.errors import ProofRequired
from jarvis.permissions.models import PasskeyProof
from jarvis.permissions.service import PermissionsService
from jarvis.privacy.export import scrub
from jarvis.privacy.ports import SOURCE_BUDGET_S, CategoryView, PrivacyRegistry, PrivacySource
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

CONFIRM_WORD = "DELETE"
AUDIT_AGENT = "owner"
VAULT_FILES_NOTE = "Vault files are not in this download. Use Vault, then Export, for the files."
NEEDS_TYPED = f"Type {CONFIRM_WORD} to confirm."
NEEDS_REAUTH = "Sign in with Google again first (it counts for 5 minutes)."
CHANGED = "This changed - check again."
UNAVAILABLE = "Couldn't check that category right now."
DELETE_FAILED = "Couldn't delete that just now. Check the list and try again."


class NotDeletable(PermissionError):
    """403 not_deletable: the category has no delete here (the card says why)."""


class NotExportable(PermissionError):
    """403 no_export: the category has no export."""


class Changed(Exception):
    """409 changed: the data changed since the owner looked."""


class SourceUnavailable(Exception):
    """503 unavailable: the category could not be read right now; nothing was done."""


class DeleteFailed(Exception):
    """502 delete_failed: the category's own delete failed (the cause is logged, never shown)."""


class PrivacyView(BaseModel):
    categories: list[CategoryView]
    passkey_in_force: bool
    generated_at: str


class Deleted(BaseModel):
    deleted: int
    category: str
    # what is still there after the delete (None: it could not be read back). A delete that
    # left rows is reported with this number, never as a clean success.
    remaining: int | None = None
    # R11.1 I1: a source that finishes a delete later (the home laptop's face groups) says so in
    # its own fixed words; "" otherwise, and always when nothing is left
    pending: str = ""


PENDING_MAX = 200


def _pending(source: object) -> str:
    """A source's own fixed words for a delete it finishes later, or "" (none, a fault, or not
    one short line: never a source's error text)."""
    note = getattr(source, "pending_note", None)
    if not callable(note):
        return ""
    try:
        words = note()
    except Exception as exc:  # noqa: BLE001 - the dashboard's generic words stay
        log.warning("privacy pending note unreadable", extra={"error": type(exc).__name__})
        return ""
    ok = isinstance(words, str) and 0 < len(words) <= PENDING_MAX and "\n" not in words
    return words if ok else ""


class PrivacyService:
    def __init__(
        self,
        registry: PrivacyRegistry,
        *,
        permissions: PermissionsService | None = None,
        audit: AuditTrail | None = None,
        clock: Callable[[], datetime] | None = None,
        budget_s: float = SOURCE_BUDGET_S,
    ) -> None:
        self.registry = registry
        self.permissions = permissions
        self.audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._budget_s = budget_s

    # ---- view -----------------------------------------------------------------------------------

    async def passkey_in_force(self, uid: str) -> bool:
        if self.permissions is None:
            return False
        try:
            return await self.permissions.passkey_required(uid)
        except Exception as exc:  # noqa: BLE001 - unreadable passkey data: fail closed
            log.warning("passkey state unreadable", extra={"error": type(exc).__name__})
            return True

    async def view(self, uid: str) -> PrivacyView:
        cats = await self.registry.describe_all(uid)
        return PrivacyView(
            categories=cats,
            passkey_in_force=await self.passkey_in_force(uid),
            generated_at=self._clock().isoformat(),
        )

    # ---- helpers --------------------------------------------------------------------------------

    def _source(self, category_id: str) -> PrivacySource:
        source = self.registry.get(category_id)
        if source is None:
            raise LookupError("There is no such category.")
        return source

    async def _describe(self, uid: str, source: PrivacySource) -> CategoryView:
        """The category as it is now, or SourceUnavailable (never a guess)."""
        try:
            async with asyncio.timeout(self._budget_s):
                view = await source.describe(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "privacy source failed", extra={"source": source.id, "error": type(exc).__name__}
            )
            raise SourceUnavailable(UNAVAILABLE) from None
        if not isinstance(view, CategoryView) or view.id != source.id or not view.available:
            raise SourceUnavailable(UNAVAILABLE)
        return view

    async def _audit(self, tool: str, outcome: str, category: str, count: int, how: str) -> None:
        """It already happened (or failed): an audit outage is logged, never raised. The detail
        is the category and a count - never content."""
        if self.audit is None:
            return
        detail = f"{category}: {count}" + (f" ({how})" if how else "")
        try:
            await self.audit.append(
                agent=AUDIT_AGENT,
                tool=tool,
                risk=ActionRisk.IRREVERSIBLE if tool == "privacy_delete" else ActionRisk.READ_ONLY,
                outcome=outcome,
                args={"category": category, "count": count},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AUDIT WRITE FAILED for privacy", extra={"error": type(exc).__name__})

    async def _prove(
        self,
        uid: str,
        purpose: str,
        target: str,
        *,
        typed: bool,
        confirm: str | None,
        proof: PasskeyProof | None,
        fresh_left_s: int | None,
    ) -> str:
        """Passes (returning how, for the audit) or raises. With passkeys in force: a passkey check
        made for exactly (purpose, target). Otherwise a Google sign-in < 5 min old, plus the typed
        word when `typed`. Fails closed."""
        if self.permissions is not None:
            note = await self.permissions.check_purpose(uid, purpose, target, proof)
            if note is not None:
                return note
        if typed and confirm != CONFIRM_WORD:
            raise InputRejected(NEEDS_TYPED)
        if fresh_left_s is None or fresh_left_s <= 0:
            raise ProofRequired(NEEDS_REAUTH, reason="reauth")
        return "re-sign-in"

    # ---- export ---------------------------------------------------------------------------------

    async def export(
        self,
        uid: str,
        category_id: str,
        *,
        proof: PasskeyProof | None = None,
        fresh_left_s: int | None = None,
    ) -> dict[str, Any]:
        """One category. Content (passkey-class) categories need a proof of their own - purpose
        `privacy_export`, target `export:<id>` - or the fresh sign-in fallback, so a stolen
        session cannot read them one by one around the "Download everything" gate."""
        source = self._source(category_id)
        view = await self._describe(uid, source)
        if not view.export:
            raise NotExportable("This category can't be downloaded.")
        how = ""
        if view.delete == "passkey":
            how = await self._prove(
                uid,
                "privacy_export",
                f"export:{category_id}",
                typed=False,
                confirm=None,
                proof=proof,
                fresh_left_s=fresh_left_s,
            )
        data = await source.export(uid)
        if data is None:
            raise NotExportable("This category can't be downloaded.")
        await self._audit("privacy_export", "executed", category_id, view.count or 0, how)
        return {
            "category": category_id,
            "generated_at": self._clock().isoformat(),
            "data": scrub(data),
        }

    async def export_all(
        self, uid: str, *, proof: PasskeyProof | None, fresh_left_s: int | None
    ) -> dict[str, Any]:
        how = await self._prove(
            uid,
            "privacy_export",
            "all",
            typed=False,
            confirm=None,
            proof=proof,
            fresh_left_s=fresh_left_s,
        )
        out: dict[str, Any] = {}
        unavailable: list[str] = []
        total = 0
        for view in await self.registry.describe_all(uid):
            if not view.available:  # its placeholder row has no export flag: still say so
                unavailable.append(view.id)
                continue
            if not view.export:
                continue
            try:
                async with asyncio.timeout(self._budget_s):
                    data = await self._source(view.id).export(uid)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "privacy export failed", extra={"source": view.id, "error": type(exc).__name__}
                )
                unavailable.append(view.id)
                continue
            if data is not None:
                out[view.id] = scrub(data)
                total += view.count or 0
        await self._audit("privacy_export", "executed", "all", total, how)
        return {
            "generated_at": self._clock().isoformat(),
            "categories": out,
            "unavailable": unavailable,
            "vault_files": VAULT_FILES_NOTE,
        }

    # ---- delete ---------------------------------------------------------------------------------

    async def delete(
        self,
        uid: str,
        category_id: str,
        *,
        rev: str,
        confirm: str | None,
        proof: PasskeyProof | None,
        fresh_left_s: int | None,
    ) -> Deleted:
        source = self._source(category_id)
        view = await self._describe(uid, source)
        if view.delete == "none":
            raise NotDeletable("This category can't be deleted here.")
        if not rev or rev != view.rev:
            raise Changed(CHANGED)
        how = ""
        if view.delete == "passkey":
            how = await self._prove(
                uid,
                "privacy_delete",
                f"{category_id}:{view.rev}",
                typed=True,
                confirm=confirm,
                proof=proof,
                fresh_left_s=fresh_left_s,
            )
            # the proof was checked for the rev he saw; the data may have moved while that ran
            if (await self._describe(uid, source)).rev != view.rev:
                raise Changed(CHANGED)
        # R3 S4: a source can ask for more first (the home link while the alarm is armed needs
        # the Disarm button's proof); it raises its own refusal, and nothing is deleted
        authorize = getattr(source, "authorize_delete", None)
        if authorize is not None:
            await authorize(uid, proof=proof, fresh_left_s=fresh_left_s)
        before = _to_delete(view)
        failure: str | None = None
        count = 0
        try:
            count = await source.delete(uid)
        except Exception as exc:
            failure = type(exc).__name__
            log.error("privacy delete failed", extra={"source": category_id, "error": failure})
        left = await self._left(uid, source)
        if failure is not None:  # what the delete did before it failed is what the rows say
            count = max(0, before - left) if left is not None and before is not None else 0
            if count == 0:
                await self._audit("privacy_delete", "error", category_id, 0, failure)
                raise DeleteFailed(DELETE_FAILED)
        suffix = f"{how}, {left} left" if left else how
        await self._audit("privacy_delete", "executed", category_id, count, suffix)
        pending = _pending(source) if left else ""
        return Deleted(deleted=count, category=category_id, remaining=left, pending=pending)

    async def _left(self, uid: str, source: PrivacySource) -> int | None:
        """What a delete of this category would still remove; None when it can't be read back."""
        try:
            return _to_delete(await self._describe(uid, source), after=True)
        except SourceUnavailable:
            return None


def _to_delete(view: CategoryView, *, after: bool = False) -> int | None:
    if after and view.delete == "none":  # nothing deletable is left
        return 0
    return view.count if view.delete_count is None else view.delete_count


__all__ = [
    "CONFIRM_WORD",
    "Changed",
    "DeleteFailed",
    "Deleted",
    "NotDeletable",
    "NotExportable",
    "PrivacyService",
    "PrivacyView",
    "SourceUnavailable",
]
