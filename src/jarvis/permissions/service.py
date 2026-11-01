# src/jarvis/permissions/service.py
"""Owner permissions and passkeys: what the API calls (slice 10 D).

The rules
- Choices: per group Allow / Ask first / Never; an irreversible group never Allow (422).
- "Require passkey for irreversible actions" is IN FORCE when switched on and at least one passkey
  is registered. It switches itself on with the first passkey.
- In force, approving a card whose call can't be undone (`PendingAction.irreversible`) needs a
  fresh passkey check (`check_approval`): a challenge bound to that approval id, its arguments
  hash, its conversation and tool; single use, 2 minutes, user verification, sign count, RP ID
  and origin all checked. A check made for anything else is refused.
- Lowering protection needs proof — a passkey check made for exactly that, OR a Google sign-in
  in the last 5 minutes (the recovery path when the passkey is lost): removing a passkey,
  switching the requirement off, and adding a passkey once one exists (else a stolen session
  could add its own passkey and approve with it).
- Without a relying party (no JARVIS_PUBLIC_BASE_URL, or an IP address) passkeys are unavailable
  and approvals work as before: the owner's approval token alone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from jarvis.core.guardrails import ActionRisk, PendingAction
from jarvis.logging import get_logger
from jarvis.permissions.ceremony import (
    CeremonyFailed,
    RelyingParty,
    authentication_options,
    registration_options,
    verify_assertion,
    verify_registration,
)
from jarvis.permissions.errors import (
    PasskeyNotFound,
    PasskeyRejected,
    PasskeyRequired,
    PasskeysUnavailable,
    ProofRequired,
)
from jarvis.permissions.groups import GROUPS, PermissionRejected, validate_choices
from jarvis.permissions.models import (
    ChallengeRequest,
    ChallengeView,
    GroupView,
    PasskeyProof,
    PasskeyView,
    PermissionsPatch,
    PermissionsView,
    RegisterRequest,
)
from jarvis.permissions.passkeys import (
    CHALLENGE_TTL,
    LABEL_MAX,
    MAX_PASSKEYS,
    Challenge,
    ChallengeStore,
    NeedsProof,
    PasskeyLimit,
    PasskeyStore,
    StoredPasskey,
)
from jarvis.permissions.store import OwnerPermissions, PermissionsStore
from jarvis.tools.audit import AuditTrail
from jarvis.tools.policy import PolicyRule

log = get_logger(__name__)

ApprovalLookup = Callable[[str], Awaitable[PendingAction | None]]
Clock = Callable[[], datetime]
NO_RP = (
    "Passkeys need this server's public web address (JARVIS_PUBLIC_BASE_URL with a domain "
    "name), so they are off here."
)
NEEDS_PASSKEY = (
    "This action can't be undone, so it needs your passkey. Approve it in the JARVIS console in "
    "your browser (the command line can't use passkeys)."
)
NEEDS_PROOF = (
    "Confirm it's you first: use one of your passkeys, or sign in with Google again (that counts "
    "for 5 minutes)."
)
_LABEL_DROP = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _binding(uid: str, purpose: str, *parts: str) -> str:
    return hashlib.sha256(
        "\x00".join(["jarvis-passkey", uid, purpose, *parts]).encode()
    ).hexdigest()


def approval_binding(uid: str, action: PendingAction) -> str:
    """What an approval check is bound to: the card's id, exact arguments, conversation, tool."""
    args = json.dumps(action.arguments, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(args.encode()).hexdigest()
    return _binding(uid, "approve", action.id, digest, action.scope or "", action.tool)


def clean_label(raw: str, fallback: str) -> str:
    text = " ".join(_LABEL_DROP.sub("", raw or "").split())[:LABEL_MAX].strip()
    return text or fallback


class PermissionsService:
    def __init__(
        self,
        *,
        store: PermissionsStore,
        passkeys: PasskeyStore,
        challenges: ChallengeStore,
        rp: RelyingParty | None,
        can_reauth: bool,
        clock: Clock = _utcnow,
        audit: AuditTrail | None = None,
    ) -> None:
        self.store, self.passkeys, self.challenges = store, passkeys, challenges
        self.rp, self.can_reauth, self._clock = rp, can_reauth, clock
        self.audit = audit  # every change to the owner's protection lands in the audit chain

    async def _record(self, uid: str, tool: str, outcome: str, detail: str) -> None:
        """Append to the audit chain AFTER the change: an outage is logged loudly, never turned
        into an error for a change that already happened. Credential ids stay out of the text."""
        if self.audit is None:
            return
        try:
            await self.audit.append(
                agent="owner",
                tool=tool,
                risk=ActionRisk.REVERSIBLE,
                outcome=outcome,
                args={"user": uid, "what": detail},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "AUDIT WRITE FAILED after a permission change",
                extra={"tool": tool, "outcome": outcome, "error": type(exc).__name__},
            )

    # ---- the gateway's rule source --------------------------------------------------------------
    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return await self.store.rules_for(user_id)

    # ---- view and changes -----------------------------------------------------------------------
    async def view(self, uid: str, *, fresh_left_s: int | None = None) -> PermissionsView:
        perms = await self.store.get(uid)
        keys = await self.passkeys.owned(uid) if self.rp is not None else []
        return self._view(perms, keys, fresh_left_s)

    def _view(
        self, perms: OwnerPermissions, keys: list[StoredPasskey], fresh_left_s: int | None
    ) -> PermissionsView:
        groups = [
            GroupView(
                id=g.id,
                section=g.section,
                label=g.label,
                hint=g.hint,
                irreversible=g.irreversible,
                choices=[c.value for c in g.choices],
                effect=perms.choices.get(g.id, g.default).value,
                default=g.default.value,
            )
            for g in GROUPS
        ]
        return PermissionsView(
            groups=groups,
            require_passkey=perms.require_passkey and bool(keys),
            passkeys=[
                PasskeyView(
                    id=k.id,
                    label=k.label,
                    created_at=k.created_at,
                    last_used_at=k.last_used_at,
                    backed_up=k.backed_up,
                )
                for k in keys
            ],
            passkeys_available=self.rp is not None,
            passkeys_note="" if self.rp is not None else NO_RP,
            can_reauth=self.can_reauth,
            fresh_sign_in_s=fresh_left_s if self.can_reauth else None,
            max_passkeys=MAX_PASSKEYS,
            rev=perms.rev,
        )

    async def update(
        self, uid: str, patch: PermissionsPatch, *, fresh_left_s: int | None = None
    ) -> PermissionsView:
        choices = validate_choices(patch.groups or {})  # 422 before anything is touched
        keys = await self.passkeys.owned(uid) if self.rp is not None else []
        if patch.require_passkey is True and not keys:
            raise PermissionRejected("Set up a passkey first, then switch this on.")
        how = ""
        if patch.require_passkey is False and await self.passkey_required(uid):
            how = await self._prove(
                uid, patch.proof, "disable", _binding(uid, "disable"), fresh_left_s
            )

        def change(cur: OwnerPermissions) -> OwnerPermissions:
            merged = {**cur.choices, **choices}
            require = (
                cur.require_passkey if patch.require_passkey is None else patch.require_passkey
            )
            return cur.model_copy(update={"choices": merged, "require_passkey": require})

        perms = await self.store.update(uid, change)
        log.info(
            "permissions changed",
            extra={"groups": sorted(choices), "require_passkey": patch.require_passkey},
        )
        what = [f"{gid}={effect.value}" for gid, effect in sorted(choices.items())]
        if patch.require_passkey is not None:
            what.append(f"require_passkey={'on' if patch.require_passkey else 'off'}")
        if how:
            what.append(f"proof: {how}")
        if what:
            await self._record(uid, "permissions", "changed", "; ".join(what))
        return self._view(perms, keys, fresh_left_s)

    async def passkey_required(self, uid: str) -> bool:
        if self.rp is None:
            return False
        perms = await self.store.get(uid)
        return perms.require_passkey and bool(await self.passkeys.owned(uid))

    # ---- ceremonies -----------------------------------------------------------------------------
    def _rp(self) -> RelyingParty:
        if self.rp is None:
            raise PasskeysUnavailable(NO_RP)
        return self.rp

    async def _new_challenge(
        self, uid: str, purpose: str, binding: str, *, note: str = ""
    ) -> tuple[str, bytes]:
        cid = secrets.token_urlsafe(24)
        # random bytes + the binding digest: the authenticator signs what the check is for
        challenge = secrets.token_bytes(32) + bytes.fromhex(binding)
        await self.challenges.create(
            cid=cid,
            uid=uid,
            purpose=purpose,
            binding=binding,
            challenge=_b64u(challenge),
            note=note,
        )
        return cid, challenge

    async def challenge(
        self, uid: str, req: ChallengeRequest, *, approvals: ApprovalLookup
    ) -> ChallengeView:
        """Options for navigator.credentials.get() bound to one purpose."""
        rp = self._rp()
        keys = await self.passkeys.owned(uid)
        if not keys:
            raise PermissionRejected("No passkey is set up yet.")
        if req.purpose == "approve":
            action = await approvals(req.approval_id or "") if req.approval_id else None
            if action is None or not (action.scope or "").startswith(f"{uid}:"):
                raise LookupError("That approval is no longer waiting.")
            binding = approval_binding(uid, action)
        elif req.purpose == "remove":
            if not any(k.id == req.credential_id for k in keys):
                raise PasskeyNotFound("No such passkey.")
            binding = _binding(uid, "remove", req.credential_id or "")
        else:  # add another passkey, or switch the requirement off
            binding = _binding(uid, req.purpose)
        cid, challenge = await self._new_challenge(uid, req.purpose, binding)
        allow = [(k.id, tuple(k.transports)) for k in keys]
        return ChallengeView(
            challenge_id=cid,
            public_key=authentication_options(rp, challenge=challenge, allow=allow),
            expires_in_s=int(CHALLENGE_TTL.total_seconds()),
        )

    async def register_options(
        self,
        uid: str,
        *,
        user_name: str,
        proof: PasskeyProof | None = None,
        fresh_left_s: int | None = None,
    ) -> ChallengeView:
        rp = self._rp()
        keys = await self.passkeys.owned(uid)
        if len(keys) >= MAX_PASSKEYS:
            raise PermissionRejected(f"You have {MAX_PASSKEYS} passkeys. Remove one first.")
        how = ""
        if keys:  # adding to an existing set lowers nothing only if it is really the owner
            how = await self._prove(uid, proof, "add", _binding(uid, "add"), fresh_left_s)
        cid, challenge = await self._new_challenge(
            uid, "register", _binding(uid, "register"), note=how
        )
        handle = hashlib.sha256(f"jarvis-passkey-user:{uid}".encode()).digest()
        opts = registration_options(
            rp,
            challenge=challenge,
            user_handle=handle,
            user_name=user_name,
            exclude=[(k.id, tuple(k.transports)) for k in keys],
        )
        return ChallengeView(
            challenge_id=cid, public_key=opts, expires_in_s=int(CHALLENGE_TTL.total_seconds())
        )

    async def register(
        self, uid: str, req: RegisterRequest, *, fresh_left_s: int | None = None
    ) -> PermissionsView:
        rp = self._rp()
        ch = await self._take(uid, req.challenge_id, "register", _binding(uid, "register"))
        try:
            new = verify_registration(
                rp, req.credential.model_dump(exclude_none=True), challenge=_unb64u(ch.challenge)
            )
        except CeremonyFailed as exc:
            log.warning("passkey registration refused", extra={"reason": exc.reason[:160]})
            raise PasskeyRejected(
                "failed", "The new passkey couldn't be checked. Try again on this site."
            ) from exc
        now = self._clock()
        label = clean_label(req.label, "Passkey " + now.strftime("%d %b %Y"))
        try:
            keys = await self.passkeys.add(
                uid,
                StoredPasskey(
                    id=new.id,
                    public_key=new.public_key,
                    sign_count=new.sign_count,
                    label=label,
                    created_at=now.isoformat(),
                    transports=list(new.transports),
                    backed_up=new.backed_up,
                ),
                # options handed out without proof (no passkey then) can only add the FIRST one:
                # else a stolen session could slip its own passkey in after the owner's
                only_if_none=not ch.note,
            )
        except NeedsProof as exc:
            raise ProofRequired(NEEDS_PROOF) from exc
        except PasskeyLimit as exc:
            raise PermissionRejected(
                "That passkey is already set up, or you have too many."
            ) from exc
        perms = await self.store.get(uid)
        if len(keys) == 1:  # the first passkey switches the requirement on
            perms = await self.store.update(
                uid, lambda cur: cur.model_copy(update={"require_passkey": True})
            )
        log.info("passkey registered", extra={"count": len(keys)})
        first = "first passkey; requirement on"
        await self._record(
            uid, "passkey", "added", first if len(keys) == 1 else f"proof: {ch.note or 'none'}"
        )
        return self._view(perms, keys, fresh_left_s)

    async def remove(
        self,
        uid: str,
        cred_id: str,
        *,
        proof: PasskeyProof | None,
        fresh_left_s: int | None = None,
    ) -> PermissionsView:
        self._rp()
        keys = await self.passkeys.owned(uid)
        if not any(k.id == cred_id for k in keys):
            raise PasskeyNotFound("No such passkey.")
        how = await self._prove(
            uid, proof, "remove", _binding(uid, "remove", cred_id), fresh_left_s
        )
        left = await self.passkeys.remove(uid, cred_id)
        if left is None:
            raise PasskeyNotFound("No such passkey.")
        perms = await self.store.get(uid)
        log.info("passkey removed", extra={"left": len(left)})
        await self._record(uid, "passkey", "removed", f"proof: {how}")
        return self._view(perms, left, fresh_left_s)

    # ---- the approval guard ---------------------------------------------------------------------
    async def check_approval(
        self, uid: str, action: PendingAction, proof: PasskeyProof | None
    ) -> None:
        """Pass, or raise: an irreversible card needs a passkey check made for exactly it."""
        if not action.irreversible or not await self.passkey_required(uid):
            return
        if proof is None:
            raise PasskeyRequired(NEEDS_PASSKEY)
        await self._verify(uid, proof, "approve", approval_binding(uid, action))

    # ---- proof ----------------------------------------------------------------------------------
    async def _prove(
        self,
        uid: str,
        proof: PasskeyProof | None,
        purpose: str,
        binding: str,
        fresh_left_s: int | None,
    ) -> str:
        """A passkey check for exactly this, or a Google sign-in in the last 5 minutes. Returns
        which one it was (for the audit)."""
        if proof is not None:
            await self._verify(uid, proof, purpose, binding)
            return "passkey"
        if self.can_reauth and fresh_left_s is not None and fresh_left_s > 0:
            log.info("recent Google sign-in accepted as proof")
            return "recent Google sign-in"
        raise ProofRequired(NEEDS_PROOF)

    async def _take(self, uid: str, challenge_id: str, purpose: str, binding: str) -> Challenge:
        ch = await self.challenges.take(challenge_id)  # gone now, whatever happens next
        if ch is None or ch.user_id != uid:
            raise PasskeyRejected(
                "replayed", "That passkey check was already used. Please try again."
            )
        if ch.expires_at <= self._clock():
            raise PasskeyRejected(
                "expired", "The passkey check took longer than 2 minutes. Please try again."
            )
        if (
            ch.purpose != purpose
            or ch.binding != binding
            or not _unb64u(ch.challenge).endswith(bytes.fromhex(binding))
        ):
            raise PasskeyRejected(
                "wrong_action", "That passkey check was made for something else. Please try again."
            )
        return ch

    async def _verify(self, uid: str, proof: PasskeyProof, purpose: str, binding: str) -> None:
        rp = self._rp()
        challenge = (await self._take(uid, proof.challenge_id, purpose, binding)).challenge
        keys = await self.passkeys.owned(uid)
        key = next((k for k in keys if k.id == proof.credential.rawId), None)
        if key is None or proof.credential.id != proof.credential.rawId:
            raise PasskeyRejected("unknown_passkey", "That passkey isn't set up with JARVIS.")
        try:
            count = verify_assertion(
                rp,
                proof.as_json(),
                challenge=_unb64u(challenge),
                public_key=key.public_key,
                sign_count=key.sign_count,
            )
        except CeremonyFailed as exc:
            log.warning("passkey check refused", extra={"reason": exc.reason[:160]})
            raise PasskeyRejected(
                "failed", "The passkey check didn't go through. Please try again on this site."
            ) from exc
        if not await self.passkeys.record_use(
            uid, key.id, old_count=key.sign_count, new_count=count
        ):
            raise PasskeyRejected(
                "replayed", "That passkey check was already used. Please try again."
            )


__all__ = [
    "NEEDS_PASSKEY",
    "NEEDS_PROOF",
    "NO_RP",
    "PermissionsService",
    "approval_binding",
    "clean_label",
]
