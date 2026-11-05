# src/jarvis/permissions/service.py
"""Owner permissions and passkeys: what the API and the gateway call (slice 10 D).

The rules
- Choices: per group Allow / Ask first / Never; an irreversible group never Allow (422).
- Passkeys need a relying party (JARVIS_PUBLIC_BASE_URL with a domain name) AND Google sign-in:
  the FIRST passkey is set up only in a browser signed in with Google again in the last 5 minutes
  (a bearer token — the CLI — can't). Every later change to the passkeys needs a passkey.
- "Require passkey for irreversible actions" is IN FORCE when switched on and at least one passkey
  is registered — or when the stored passkeys can't be read (fail closed). The first passkey
  switches it on.
- In force, the gateway's approval guard (`check_approval`) lets a card whose call can't be undone
  run only with a fresh passkey check bound to that card's id, exact arguments, conversation and
  tool; single use, 2 minutes, user verification, sign count, RP ID and origin all checked. It
  returns which passkey approved, for the audit.
- Lowering protection — removing a passkey, switching the requirement off, adding a second
  passkey, cancelling a reset — needs a passkey check made for exactly that. There is no
  sign-in shortcut: a Google sign-in can only START a reset of all passkeys, which takes effect
  24 hours later (`RESET_DELAY`), shows in the console, puts a notice in the owner's Gmail inbox
  when the link allows it, and can be cancelled with any passkey. A passkey set up after a reset
  is marked in the list. Everything here is in the audit chain, refused checks included.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

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
    PasskeyDataUnreadable,
    PasskeyNotFound,
    PasskeyRejected,
    PasskeyRequired,
    PasskeysUnavailable,
    ProofRequired,
)
from jarvis.permissions.groups import (
    GROUPS,
    PermissionGroup,
    PermissionRejected,
    validate_choices,
)
from jarvis.permissions.models import (
    HOME_DISARM_TARGET,
    TARGET_PATTERN,
    TARGETED_PURPOSES,
    ChallengeRequest,
    ChallengeView,
    GroupView,
    PasskeyProof,
    PasskeyView,
    PermissionsPatch,
    PermissionsView,
    RegisterRequest,
    ResetView,
)
from jarvis.permissions.notify import Notify
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
RESET_DELAY = timedelta(hours=24)
FIRST = "first"  # a registration challenge's note: authorised by a recent sign-in, no passkey yet
NO_RP = (
    "Passkeys need this server's public web address (JARVIS_PUBLIC_BASE_URL with a domain "
    "name), so they are off here."
)
NO_GOOGLE = (
    "Passkeys need Google sign-in (JARVIS_AUTH_MODE=google): setting one up asks you to sign in "
    "with Google again first, which an access token can't do."
)
NEEDS_PASSKEY = (
    "This action can't be undone, so it needs your passkey. Approve it in the JARVIS console in "
    "your browser (the command line can't use passkeys)."
)
NEEDS_PASSKEY_PROOF = "Confirm it's you with one of your passkeys first."
NEEDS_REAUTH_FIRST = (
    "Sign in with Google again first (it counts for 5 minutes), then set up your passkey here in "
    "the browser."
)
NEEDS_REAUTH_RESET = (
    "Sign in with Google again first (it counts for 5 minutes), then start the reset here in the "
    "browser."
)
UNREADABLE = (
    "Your passkey data can't be read, so actions that can't be undone are blocked. Reset your "
    "passkeys in Approvals → Permissions."
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


_TARGET = re.compile(TARGET_PATTERN)
_DISARM_TARGET = re.compile(HOME_DISARM_TARGET)
NEEDS_TARGET = "That passkey check has to name what it is for."


def purpose_binding(uid: str, purpose: str, target: str | None) -> str:
    """What an R2 purpose check is bound to: owner, purpose and target (R2 D6, D8, D14).
    Fails closed: another purpose, a delete without a target or an odd target is refused.
    R3 D8: a disarm is bound to exactly one home and arm rev ("h_<8 hex>:<rev>")."""
    text = target or ""
    if purpose not in TARGETED_PURPOSES or (text and not _TARGET.fullmatch(text)):
        raise PermissionRejected("That passkey check isn't one JARVIS knows.")
    if purpose == "privacy_delete" and not text:
        raise PermissionRejected(NEEDS_TARGET)
    if purpose == "home_disarm" and not _DISARM_TARGET.fullmatch(text):
        raise PermissionRejected(NEEDS_TARGET)
    return _binding(uid, purpose, text)


def passkey_ref(cred_id: str) -> str:
    """A short, stable reference to a passkey for logs and the audit (never the id itself)."""
    return hashlib.sha256(cred_id.encode()).hexdigest()[:8]


def approval_binding(uid: str, action: PendingAction) -> str:
    """What an approval check is bound to: the card's id, exact arguments, conversation, tool."""
    args = json.dumps(action.arguments, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(args.encode()).hexdigest()
    return _binding(uid, "approve", action.id, digest, action.scope or "", action.tool)


def clean_label(raw: str, fallback: str) -> str:
    text = " ".join(_LABEL_DROP.sub("", raw or "").split())[:LABEL_MAX].strip()
    return text or fallback


def _when(at: datetime) -> str:
    return at.strftime("%d %b %Y, %H:%M UTC")


INHERITED_NOTE = "Never: you had switched off deleting before."


def _group_view(g: PermissionGroup, perms: OwnerPermissions) -> GroupView:
    inherited = g.id in perms.inherited  # slice 11 fix HIGH-1: say why it reads as Never
    return GroupView(
        id=g.id,
        section=g.section,
        label=g.label,
        hint=f"{g.hint} {INHERITED_NOTE}" if inherited else g.hint,
        irreversible=g.irreversible,
        choices=[c.value for c in g.choices],
        effect=perms.choices.get(g.id, g.default).value,
        default=g.default.value,
        inherited=inherited,
    )


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
        notify: Notify | None = None,
    ) -> None:
        self.store, self.passkeys, self.challenges = store, passkeys, challenges
        self.rp, self.can_reauth, self._clock = rp, can_reauth, clock
        self.audit = audit  # every change to the owner's protection lands in the audit chain
        self.notify = notify  # a notice in the owner's Gmail inbox (reset requested)

    @property
    def available(self) -> bool:
        return self.rp is not None and self.can_reauth

    def _rp(self) -> RelyingParty:
        if self.rp is None:
            raise PasskeysUnavailable(NO_RP)
        if not self.can_reauth:
            raise PasskeysUnavailable(NO_GOOGLE)
        return self.rp

    async def _record(self, uid: str, tool: str, outcome: str, detail: str) -> None:
        """Append to the audit chain AFTER the event: an outage is logged loudly, never turned
        into an error for something that already happened. Credential ids stay out of it."""
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
                "AUDIT WRITE FAILED after a permission event",
                extra={"tool": tool, "outcome": outcome, "error": type(exc).__name__},
            )

    async def sweep_challenges(self) -> int:
        """The scheduler tick (slice 11 D7 c): challenges no browser answered. Never raises."""
        return await self.challenges.sweep_expired()

    # ---- the gateway's rule source and approval guard ------------------------------------------
    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return await self.store.rules_for(user_id)

    async def passkey_required(self, uid: str) -> bool:
        """In force now (read fresh): switched on with a passkey, or passkey data unreadable."""
        if not self.available:
            return False
        perms = await self._settle(uid)
        try:
            return perms.require_passkey and bool(await self.passkeys.owned(uid))
        except PasskeyDataUnreadable:
            return True  # fail closed

    async def check_approval(
        self, uid: str, action: PendingAction, proof: PasskeyProof | None
    ) -> str | None:
        """The gateway's approval guard: pass (→ which passkey, for the audit) or raise. Only a
        card whose call can't be undone needs a passkey check made for exactly it."""
        if not action.irreversible or not await self.passkey_required(uid):
            return None
        if proof is None:
            raise PasskeyRequired(NEEDS_PASSKEY)
        key = await self._verify(uid, proof, "approve", approval_binding(uid, action))
        return f"passkey {passkey_ref(key.id)}"

    async def check_purpose(
        self, uid: str, purpose: str, target: str | None, proof: PasskeyProof | None
    ) -> str | None:
        """R2 guard for the vault unlock and the privacy export / delete (and Remove now), R3 for
        the burglar-alert disarm (`home_disarm`, target "<home_id>:<rev>"): None
        when passkeys are not in force (the caller then asks for a fresh Google sign-in);
        otherwise a passkey check made for exactly (purpose, target), single use, returning
        which passkey for the audit. Fails closed: no proof, a proof for something else, a
        purpose or target that isn't valid, unreadable passkey data."""
        binding = purpose_binding(uid, purpose, target)
        if not await self.passkey_required(uid):
            return None
        if proof is None:
            raise PasskeyRequired(NEEDS_PASSKEY)
        key = await self._verify(uid, proof, purpose, binding)
        return f"passkey {passkey_ref(key.id)}"

    # ---- view and changes -----------------------------------------------------------------------
    async def view(self, uid: str, *, fresh_left_s: int | None = None) -> PermissionsView:
        perms = await self._settle(uid) if self.available else await self.store.get(uid)
        keys: list[StoredPasskey] = []
        error = ""
        if self.available:
            try:
                keys = await self.passkeys.owned(uid)
            except PasskeyDataUnreadable:
                error = UNREADABLE
        return self._view(perms, keys, fresh_left_s, error)

    def _view(
        self,
        perms: OwnerPermissions,
        keys: list[StoredPasskey],
        fresh_left_s: int | None,
        error: str = "",
    ) -> PermissionsView:
        groups = [_group_view(g, perms) for g in GROUPS]
        reset = (
            ResetView(requested_at=perms.reset_requested_at, effective_at=perms.reset_effective_at)
            if perms.reset_requested_at and perms.reset_effective_at
            else None
        )
        note = "" if self.available else (NO_RP if self.rp is None else NO_GOOGLE)
        return PermissionsView(
            groups=groups,
            require_passkey=(perms.require_passkey and bool(keys)) or bool(error),
            passkeys=[
                PasskeyView(
                    id=k.id,
                    label=k.label,
                    created_at=k.created_at,
                    last_used_at=k.last_used_at,
                    backed_up=k.backed_up,
                    via_recovery=k.via_recovery,
                )
                for k in keys
            ],
            passkeys_available=self.available,
            passkeys_note=note,
            passkeys_error=error,
            reset=reset,
            can_reauth=self.can_reauth,
            fresh_sign_in_s=fresh_left_s if self.can_reauth else None,
            max_passkeys=MAX_PASSKEYS,
            rev=perms.rev,
        )

    async def update(
        self, uid: str, patch: PermissionsPatch, *, fresh_left_s: int | None = None
    ) -> PermissionsView:
        choices = validate_choices(patch.groups or {})  # 422 before anything is touched
        keys: list[StoredPasskey] = []
        error = ""
        if self.available:
            try:
                keys = await self.passkeys.owned(uid)
            except PasskeyDataUnreadable:
                error = UNREADABLE  # group choices still change; the passkey rule fails closed
        if patch.require_passkey is True and not keys:
            raise PermissionRejected("Set up a passkey first, then switch this on.")
        proven = False
        if patch.require_passkey is False and await self.passkey_required(uid):
            await self._passkey_proof(uid, patch.proof, "disable", _binding(uid, "disable"))
            proven = True

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
        if proven:
            what.append("proof: passkey")
        if what:
            await self._record(uid, "permissions", "changed", "; ".join(what))
        return self._view(perms, keys, fresh_left_s, error)

    # ---- ceremonies -----------------------------------------------------------------------------
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
        await self._settle(uid)
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
        elif req.purpose in TARGETED_PURPOSES:  # R2: bound to the target too
            binding = purpose_binding(uid, req.purpose, req.target)
        else:  # add another passkey, switch the requirement off, cancel a reset
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
        """The first passkey: a browser signed in with Google again in the last 5 minutes (a
        bearer caller has no sign-in: `fresh_left_s` is None). Any later one: a passkey check."""
        rp = self._rp()
        await self._settle(uid)
        keys = await self.passkeys.owned(uid)
        if len(keys) >= MAX_PASSKEYS:
            raise PermissionRejected(f"You have {MAX_PASSKEYS} passkeys. Remove one first.")
        if keys:
            await self._passkey_proof(uid, proof, "add", _binding(uid, "add"))
            note = "passkey"
        elif fresh_left_s is None or fresh_left_s <= 0:
            raise ProofRequired(NEEDS_REAUTH_FIRST, reason="reauth")
        else:
            note = FIRST
        cid, challenge = await self._new_challenge(
            uid, "register", _binding(uid, "register"), note=note
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
            await self._record(uid, "passkey", "refused", "registration did not verify")
            raise PasskeyRejected(
                "failed", "The new passkey couldn't be checked. Try again on this site."
            ) from exc
        now = self._clock()
        first = ch.note == FIRST
        perms = await self._settle(uid)
        after_reset = first and perms.recovered_at is not None
        try:
            keys = await self.passkeys.add(
                uid,
                StoredPasskey(
                    id=new.id,
                    public_key=new.public_key,
                    sign_count=new.sign_count,
                    label=clean_label(req.label, "Passkey " + now.strftime("%d %b %Y")),
                    created_at=now.isoformat(),
                    transports=list(new.transports),
                    backed_up=new.backed_up,
                    via_recovery=after_reset,
                ),
                # options handed out without a passkey check (none existed then) can only add
                # the FIRST one: else a stolen session could slip its own passkey in after it
                only_if_none=first,
            )
        except NeedsProof as exc:
            raise ProofRequired(NEEDS_PASSKEY_PROOF) from exc
        except PasskeyLimit as exc:
            raise PermissionRejected(
                "That passkey is already set up, or you have too many."
            ) from exc
        if first:  # the first passkey switches the requirement on
            perms = await self.store.update(
                uid,
                lambda cur: cur.model_copy(update={"require_passkey": True, "recovered_at": None}),
            )
        log.info("passkey registered", extra={"count": len(keys)})
        how = (
            "first passkey after a reset by Google sign-in; requirement on"
            if after_reset
            else "first passkey (recent Google sign-in); requirement on"
            if first
            else "proof: passkey"
        )
        await self._record(uid, "passkey", "added", how)
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
        await self._settle(uid)
        keys = await self.passkeys.owned(uid)
        if not any(k.id == cred_id for k in keys):
            raise PasskeyNotFound("No such passkey.")
        await self._passkey_proof(uid, proof, "remove", _binding(uid, "remove", cred_id))
        left = await self.passkeys.remove(uid, cred_id)
        if left is None:
            raise PasskeyNotFound("No such passkey.")
        perms = await self.store.get(uid, fresh=True)
        log.info("passkey removed", extra={"left": len(left)})
        await self._record(uid, "passkey", "removed", f"{passkey_ref(cred_id)}; proof: passkey")
        return self._view(perms, left, fresh_left_s)

    # ---- the delayed reset (recovery when every passkey is lost) ------------------------------
    async def start_reset(self, uid: str, *, fresh_left_s: int | None) -> PermissionsView:
        """Remove all passkeys in 24 hours — the only thing a Google sign-in can do here."""
        self._rp()
        perms = await self._settle(uid)
        if fresh_left_s is None or fresh_left_s <= 0:
            raise ProofRequired(NEEDS_REAUTH_RESET, reason="reauth")
        try:
            if not await self.passkeys.owned(uid):
                raise PermissionRejected("You have no passkeys to reset.")
        except PasskeyDataUnreadable:
            pass  # unreadable data is exactly what a reset is for
        if perms.reset_effective_at is None:
            now = self._clock()
            at = now + RESET_DELAY
            perms = await self.store.update(
                uid,
                lambda cur: cur.model_copy(
                    update={
                        "reset_requested_at": now.isoformat(),
                        "reset_effective_at": at.isoformat(),
                    }
                ),
            )
            await self._record(
                uid, "passkey", "reset_requested", f"by Google sign-in; takes effect {_when(at)}"
            )
            await self._notice(uid, at)
        return await self.view(uid, fresh_left_s=fresh_left_s)

    async def _notice(self, uid: str, at: datetime) -> None:
        sent = False
        if self.notify is not None:
            sent = await self.notify(
                uid,
                "JARVIS: all your passkeys will be removed in 24 hours",
                "Someone signed in to JARVIS with your Google account and asked to remove all "
                f"your passkeys. This happens on {_when(at)}.\n\nIf it was you, there is nothing "
                "to do. If it was not you: open JARVIS, go to Approvals → Permissions and cancel "
                "the reset with one of your passkeys, then secure your Google account.",
            )
        await self._record(
            uid,
            "passkey",
            "reset_notice",
            "copy put in the Gmail inbox" if sent else "no inbox copy (Gmail insert unavailable)",
        )

    async def cancel_reset(
        self, uid: str, *, proof: PasskeyProof | None, fresh_left_s: int | None = None
    ) -> PermissionsView:
        self._rp()
        perms = await self._settle(uid)
        if perms.reset_effective_at is not None:
            await self._passkey_proof(uid, proof, "cancel_reset", _binding(uid, "cancel_reset"))
            await self.store.update(
                uid,
                lambda cur: cur.model_copy(
                    update={"reset_requested_at": None, "reset_effective_at": None}
                ),
            )
            await self._record(uid, "passkey", "reset_cancelled", "proof: passkey")
        return await self.view(uid, fresh_left_s=fresh_left_s)

    async def _settle(self, uid: str) -> OwnerPermissions:
        """The owner's permissions read fresh; a reset that is due is carried out first: every
        passkey is removed (without reading them), then the reset is marked done."""
        perms = await self.store.get(uid, fresh=True)
        due = perms.reset_effective_at
        if due is None or self._clock() < datetime.fromisoformat(due):
            return perms
        await self.passkeys.wipe(uid)  # idempotent: a retry after a crash wipes again
        done: list[bool] = []

        def finish(cur: OwnerPermissions) -> OwnerPermissions:
            if cur.reset_effective_at != due:
                return cur  # finished (or cancelled and re-requested) by someone else
            done.append(True)
            return cur.model_copy(
                update={
                    "reset_requested_at": None,
                    "reset_effective_at": None,
                    "recovered_at": self._clock().isoformat(),
                    "require_passkey": False,
                }
            )

        perms = await self.store.update(uid, finish)
        if done:
            log.warning("passkey reset carried out")
            await self._record(uid, "passkey", "reset_completed", "all passkeys removed")
        return perms

    # ---- proof ----------------------------------------------------------------------------------
    async def _passkey_proof(
        self, uid: str, proof: PasskeyProof | None, purpose: str, binding: str
    ) -> StoredPasskey:
        if proof is None:
            raise ProofRequired(NEEDS_PASSKEY_PROOF)
        return await self._verify(uid, proof, purpose, binding)

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

    async def _verify(
        self, uid: str, proof: PasskeyProof, purpose: str, binding: str
    ) -> StoredPasskey:
        """The passkey that answered, or PasskeyRejected — recorded in the audit either way."""
        try:
            return await self._verify_once(uid, proof, purpose, binding)
        except PasskeyRejected as exc:
            await self._record(uid, "passkey", "check_refused", f"{purpose}: {exc.audit_detail}")
            raise

    async def _verify_once(
        self, uid: str, proof: PasskeyProof, purpose: str, binding: str
    ) -> StoredPasskey:
        rp = self._rp()
        challenge = (await self._take(uid, proof.challenge_id, purpose, binding)).challenge
        try:
            keys = await self.passkeys.owned(uid)
        except PasskeyDataUnreadable as exc:
            raise PasskeyRejected("unreadable", UNREADABLE) from exc
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
            cloned = "sign count" in exc.reason  # a counter going backwards: a cloned key?
            raise PasskeyRejected(
                "failed",
                "The passkey check didn't go through. Please try again on this site.",
                audit_detail=(
                    f"counter went backwards on passkey {passkey_ref(key.id)} (possible clone)"
                    if cloned
                    else f"did not verify (passkey {passkey_ref(key.id)})"
                ),
            ) from exc
        if not await self.passkeys.record_use(
            uid, key.id, old_count=key.sign_count, new_count=count
        ):
            raise PasskeyRejected(
                "replayed", "That passkey check was already used. Please try again."
            )
        return key


__all__ = [
    "NEEDS_PASSKEY",
    "NEEDS_PASSKEY_PROOF",
    "NO_GOOGLE",
    "NO_RP",
    "RESET_DELAY",
    "PermissionsService",
    "approval_binding",
    "clean_label",
    "passkey_ref",
]
