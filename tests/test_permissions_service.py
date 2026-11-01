# tests/test_permissions_service.py — owner choices, passkey ceremonies and the approval guard on
# the Docs twin with a software authenticator (no browser, no network), with a movable clock.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from passkey_fakes import SoftAuthenticator

from jarvis.core.guardrails import ActionRisk, PendingAction
from jarvis.permissions.ceremony import RelyingParty
from jarvis.permissions.errors import (
    PasskeyNotFound,
    PasskeyRejected,
    PasskeyRequired,
    PasskeysUnavailable,
    ProofRequired,
)
from jarvis.permissions.groups import PermissionRejected
from jarvis.permissions.models import (
    ChallengeRequest,
    PasskeyProof,
    PermissionsPatch,
    RegisterRequest,
)
from jarvis.permissions.passkeys import ChallengeStore, PasskeyStore
from jarvis.permissions.service import PermissionsService, clean_label
from jarvis.permissions.store import PermissionsStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.policy import Effect

UID = "u_owner"
RP = RelyingParty(id="jarvis.example.com", origin="https://jarvis.example.com")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class Rig:
    def __init__(self, *, rp: RelyingParty | None = RP, can_reauth: bool = True) -> None:
        self.docs = MemoryDocs()
        self.clock = Clock()
        self.svc = PermissionsService(
            store=PermissionsStore(self.docs),
            passkeys=PasskeyStore(self.docs),
            challenges=ChallengeStore(self.docs, clock=self.clock),
            rp=rp,
            can_reauth=can_reauth,
            clock=self.clock,
        )
        self.auth = SoftAuthenticator(origin=RP.origin)
        self.approvals: dict[str, PendingAction] = {}

    async def lookup(self, aid: str) -> PendingAction | None:
        return self.approvals.get(aid)

    async def register(self, label: str = "Laptop", **kw: Any) -> str:
        opts = await self.svc.register_options(UID, user_name="owner@example.com", **kw)
        cred = self.auth.create(opts.public_key)
        await self.svc.register(
            UID,
            RegisterRequest.model_validate(
                {"challenge_id": opts.challenge_id, "credential": cred, "label": label}
            ),
        )
        return str(cred["id"])

    async def proof(
        self, purpose: str, *, get_kw: dict[str, Any] | None = None, **req: Any
    ) -> PasskeyProof:
        ch = await self.svc.challenge(
            UID,
            ChallengeRequest(purpose=purpose, **req),
            approvals=self.lookup,  # type: ignore[arg-type]
        )
        cred = self.auth.get(ch.public_key, **(get_kw or {}))
        return PasskeyProof.model_validate({"challenge_id": ch.challenge_id, "credential": cred})

    def card(
        self, tool: str = "gmail_send", risk: ActionRisk = ActionRisk.IRREVERSIBLE, **args: Any
    ) -> PendingAction:
        a = PendingAction(
            tool=tool,
            arguments=args or {"to": "priya@example.com", "body": "3pm"},
            risk=ActionRisk.IRREVERSIBLE,
            summary="Send mail",
            scope=f"{UID}:s1",
            tool_risk=risk,
        )
        self.approvals[a.id] = a
        return a


@pytest.fixture
def rig() -> Rig:
    return Rig()


# ---- choices --------------------------------------------------------------------------------


async def test_defaults_are_todays_behaviour_and_nothing_is_required(rig: Rig) -> None:
    v = await rig.svc.view(UID)
    assert v.passkeys_available and v.passkeys == [] and v.require_passkey is False
    assert {g.id: g.effect for g in v.groups}["email_send"] == "ask"
    assert {g.id: g.effect for g in v.groups}["web"] == "allow"
    assert all(g.effect == g.default for g in v.groups)
    assert await rig.svc.rules_for(UID) == []


async def test_changes_apply_merge_and_bump_rev(rig: Rig) -> None:
    v1 = await rig.svc.update(UID, PermissionsPatch(groups={"web": "deny"}))
    v2 = await rig.svc.update(UID, PermissionsPatch(groups={"email_send": "deny"}))
    effects = {g.id: g.effect for g in v2.groups}
    assert effects["web"] == "deny" and effects["email_send"] == "deny" and v2.rev == v1.rev + 1
    rules = await rig.svc.rules_for(UID)
    assert {r.source for r in rules} == {"owner:web", "owner:email_send"}
    assert all(r.effect is Effect.DENY for r in rules)


async def test_allow_on_an_irreversible_group_is_refused_and_nothing_written(rig: Rig) -> None:
    with pytest.raises(PermissionRejected):
        await rig.svc.update(UID, PermissionsPatch(groups={"web": "deny", "email_send": "allow"}))
    assert (await rig.svc.view(UID)).rev == 0
    assert rig.docs.sets == 0


async def test_a_hand_edited_allow_for_an_irreversible_group_reads_as_ask(rig: Rig) -> None:
    await rig.docs.write([])
    from jarvis.storage.docs import Set

    await rig.docs.write(
        [Set(f"jarvis_permissions/{UID}", {"groups": {"email_send": "allow", "web": "nope"}})]
    )
    v = await rig.svc.view(UID)
    assert {g.id: g.effect for g in v.groups}["email_send"] == "ask"
    assert await rig.svc.rules_for(UID) == []


# ---- registration ---------------------------------------------------------------------------


async def test_first_passkey_switches_the_requirement_on(rig: Rig) -> None:
    with pytest.raises(PermissionRejected):
        await rig.svc.update(UID, PermissionsPatch(require_passkey=True))
    await rig.register("  My‮ laptop\n ")
    v = await rig.svc.view(UID)
    assert v.require_passkey is True and [p.label for p in v.passkeys] == ["My laptop"]
    stored = (await rig.svc.passkeys.owned(UID))[0]
    assert stored.public_key and "private" not in stored.model_dump_json()


async def test_a_second_passkey_needs_proof(rig: Rig) -> None:
    await rig.register()
    with pytest.raises(ProofRequired):
        await rig.svc.register_options(UID, user_name="o", proof=None)
    with pytest.raises(ProofRequired):  # a sign-in older than 5 minutes is no proof
        await rig.svc.register_options(UID, user_name="o", proof=None, fresh_left_s=0)
    await rig.register("Phone", proof=await rig.proof("add"))
    await rig.register("Key", proof=None, fresh_left_s=120)  # recent Google sign-in
    assert len((await rig.svc.view(UID)).passkeys) == 3


async def test_registration_challenge_is_single_use_and_expires(rig: Rig) -> None:
    opts = await rig.svc.register_options(UID, user_name="o", proof=None)
    cred = rig.auth.create(opts.public_key)
    req = RegisterRequest.model_validate({"challenge_id": opts.challenge_id, "credential": cred})
    rig.clock.advance(minutes=2, seconds=1)
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.register(UID, req)
    assert e.value.reason == "expired"
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.register(UID, req)
    assert e.value.reason == "replayed"
    assert (await rig.svc.view(UID)).passkeys == []


async def test_registration_from_another_site_is_refused(rig: Rig) -> None:
    opts = await rig.svc.register_options(UID, user_name="o", proof=None)
    cred = rig.auth.create(opts.public_key, origin="https://evil.example")
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.register(
            UID,
            RegisterRequest.model_validate({"challenge_id": opts.challenge_id, "credential": cred}),
        )
    assert e.value.reason == "failed"


# ---- the approval guard -----------------------------------------------------------------------


async def test_no_passkey_no_requirement(rig: Rig) -> None:
    await rig.svc.check_approval(UID, rig.card(), None)


async def test_irreversible_card_needs_a_passkey_check_made_for_it(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    with pytest.raises(PasskeyRequired, match="command line"):
        await rig.svc.check_approval(UID, card, None)
    await rig.svc.check_approval(UID, card, await rig.proof("approve", approval_id=card.id))


async def test_reversible_and_legacy_cards(rig: Rig) -> None:
    await rig.register()
    await rig.svc.check_approval(UID, rig.card("task_add", ActionRisk.REVERSIBLE), None)
    legacy = rig.card()
    legacy = legacy.model_copy(update={"tool_risk": None})  # stored before slice 10: fail safe
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_approval(UID, legacy, None)


async def test_replayed_check_is_refused(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    proof = await rig.proof("approve", approval_id=card.id)
    await rig.svc.check_approval(UID, card, proof)
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.check_approval(UID, card, proof)
    assert e.value.reason == "replayed"


async def test_expired_check_is_refused(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    proof = await rig.proof("approve", approval_id=card.id)
    rig.clock.advance(seconds=121)
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.check_approval(UID, card, proof)
    assert e.value.reason == "expired"


async def test_check_for_another_approval_or_purpose_is_refused(rig: Rig) -> None:
    await rig.register()
    a, b = rig.card(body="one"), rig.card(body="two")
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.check_approval(UID, b, await rig.proof("approve", approval_id=a.id))
    assert e.value.reason == "wrong_action"
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.check_approval(UID, a, await rig.proof("add"))
    assert e.value.reason == "wrong_action"
    # the same id with changed arguments is another action too
    proof = await rig.proof("approve", approval_id=a.id)
    drifted = a.model_copy(update={"arguments": {"to": "evil@example.com", "body": "one"}})
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_approval(UID, drifted, proof)


async def test_check_from_another_origin_or_rp_or_without_uv_is_refused(rig: Rig) -> None:
    await rig.register()
    for kw in ({"origin": "https://evil.example"}, {"rp_id": "evil.example"}):
        card = rig.card()
        with pytest.raises(PasskeyRejected) as e:
            await rig.svc.check_approval(
                UID, card, await rig.proof("approve", approval_id=card.id, get_kw=kw)
            )
        assert e.value.reason == "failed"
    rig.auth.user_verified = False
    card = rig.card()
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_approval(UID, card, await rig.proof("approve", approval_id=card.id))


async def test_a_cloned_authenticator_counter_is_refused(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    await rig.svc.check_approval(UID, card, await rig.proof("approve", approval_id=card.id))
    card2 = rig.card(body="again")
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_approval(
            UID, card2, await rig.proof("approve", approval_id=card2.id, get_kw={"sign_count": 1})
        )


async def test_an_unknown_passkey_is_refused(rig: Rig) -> None:
    await rig.register()
    stranger = SoftAuthenticator(origin=RP.origin)
    other = Rig()
    other.auth = stranger
    other_id = await other.register()
    card = rig.card()
    ch = await rig.svc.challenge(
        UID, ChallengeRequest(purpose="approve", approval_id=card.id), approvals=rig.lookup
    )
    cred = stranger.get(ch.public_key, credential_id=other_id)
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.check_approval(
            UID,
            card,
            PasskeyProof.model_validate({"challenge_id": ch.challenge_id, "credential": cred}),
        )
    assert e.value.reason == "unknown_passkey"


async def test_challenge_for_an_approval_of_another_owner_or_gone_is_refused(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    rig.approvals[card.id] = card.model_copy(update={"scope": "u_other:s1"})
    with pytest.raises(LookupError):
        await rig.svc.challenge(
            UID, ChallengeRequest(purpose="approve", approval_id=card.id), approvals=rig.lookup
        )
    with pytest.raises(LookupError):
        await rig.svc.challenge(
            UID, ChallengeRequest(purpose="approve", approval_id="nope"), approvals=rig.lookup
        )


# ---- removal and switching off (the recovery path) ---------------------------------------------


async def test_removing_needs_proof_and_the_last_one_switches_the_requirement_off(rig: Rig) -> None:
    a = await rig.register("A")
    b = await rig.register("B", proof=await rig.proof("add"))
    with pytest.raises(ProofRequired):
        await rig.svc.remove(UID, a, proof=None)
    with pytest.raises(PasskeyRejected):  # a check made to remove B does not remove A
        await rig.svc.remove(UID, a, proof=await rig.proof("remove", credential_id=b))
    v = await rig.svc.remove(UID, a, proof=await rig.proof("remove", credential_id=a))
    assert [p.label for p in v.passkeys] == ["B"] and v.require_passkey is True
    v = await rig.svc.remove(UID, b, proof=None, fresh_left_s=200)  # lost it: fresh sign-in
    assert v.passkeys == [] and v.require_passkey is False
    assert await rig.svc.passkey_required(UID) is False
    with pytest.raises(PasskeyNotFound):
        await rig.svc.remove(UID, b, proof=None, fresh_left_s=200)


async def test_token_mode_has_no_sign_in_recovery(rig: Rig) -> None:
    r = Rig(can_reauth=False)
    a = await r.register()
    with pytest.raises(ProofRequired):
        await r.svc.remove(UID, a, proof=None, fresh_left_s=200)
    assert (await r.svc.view(UID, fresh_left_s=200)).fresh_sign_in_s is None


async def test_switching_off_needs_proof_switching_on_does_not(rig: Rig) -> None:
    await rig.register()
    with pytest.raises(ProofRequired):
        await rig.svc.update(UID, PermissionsPatch(require_passkey=False))
    v = await rig.svc.update(
        UID, PermissionsPatch(require_passkey=False, proof=await rig.proof("disable"))
    )
    assert v.require_passkey is False
    await rig.svc.check_approval(UID, rig.card(), None)  # off: the approval token alone
    v = await rig.svc.update(UID, PermissionsPatch(require_passkey=True))
    assert v.require_passkey is True
    v = await rig.svc.update(UID, PermissionsPatch(require_passkey=False), fresh_left_s=30)
    assert v.require_passkey is False


# ---- no relying party ----------------------------------------------------------------------------


async def test_without_a_public_address_passkeys_are_unavailable() -> None:
    r = Rig(rp=None)
    v = await r.svc.view(UID)
    assert v.passkeys_available is False and "JARVIS_PUBLIC_BASE_URL" in v.passkeys_note
    with pytest.raises(PasskeysUnavailable):
        await r.svc.register_options(UID, user_name="o", proof=None)
    await r.svc.check_approval(UID, r.card(), None)  # as before: the approval token alone


async def test_challenges_are_swept_and_capped_per_owner(rig: Rig) -> None:
    await rig.register()
    for _ in range(15):
        await rig.svc.challenge(UID, ChallengeRequest(purpose="add"), approvals=rig.lookup)
    from jarvis.storage.docs import Query

    live = await rig.docs.query(Query("jarvis_webauthn_challenges"))
    assert len(live) <= 10
    rig.clock.advance(minutes=3)
    await rig.svc.challenge(UID, ChallengeRequest(purpose="add"), approvals=rig.lookup)
    assert len(await rig.docs.query(Query("jarvis_webauthn_challenges"))) == 1


def test_labels_are_cleaned_and_capped() -> None:
    assert clean_label("‮abc​  def\n", "x") == "abc def"
    assert clean_label("   ", "Passkey 1") == "Passkey 1"
    assert len(clean_label("a" * 100, "x")) == 40
