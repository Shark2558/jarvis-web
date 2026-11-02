# tests/test_permissions_service.py — owner choices, passkey ceremonies, the approval guard and the
# delayed reset on the Docs twin with a software authenticator (no browser, no network) and a
# movable clock. Slice 10 D + its security review: a Google sign-in never lowers protection by
# itself (first passkey and the 24-hour reset only); unreadable passkey data fails closed.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from passkey_fakes import SoftAuthenticator

from jarvis.core.guardrails import ActionRisk, PendingAction
from jarvis.permissions.ceremony import RelyingParty
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
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
from jarvis.permissions.service import PermissionsService, clean_label, passkey_ref
from jarvis.permissions.store import PermissionsStore
from jarvis.storage.docs import MemoryDocs, Query, Set
from jarvis.tools.audit import AuditLog
from jarvis.tools.policy import Effect

UID = "u_owner"
RP = RelyingParty(id="jarvis.example.com", origin="https://jarvis.example.com")
FRESH = 240  # seconds left of a Google re-sign-in in this browser


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
        self.audit = AuditLog()
        self.notices: list[tuple[str, str, str]] = []
        self.svc = PermissionsService(
            store=PermissionsStore(self.docs),
            passkeys=PasskeyStore(self.docs),
            challenges=ChallengeStore(self.docs, clock=self.clock),
            rp=rp,
            can_reauth=can_reauth,
            clock=self.clock,
            audit=self.audit,
            notify=self.notify,
        )
        self.auth = SoftAuthenticator(origin=RP.origin)
        self.approvals: dict[str, PendingAction] = {}

    async def notify(self, uid: str, subject: str, body: str) -> bool:
        self.notices.append((uid, subject, body))
        return True

    async def lookup(self, aid: str) -> PendingAction | None:
        return self.approvals.get(aid)

    async def register(
        self, label: str = "Laptop", *, proof: PasskeyProof | None = None, fresh: int | None = FRESH
    ) -> str:
        opts = await self.svc.register_options(
            UID, user_name="owner@example.com", proof=proof, fresh_left_s=fresh
        )
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

    async def audit_rows(self) -> list[tuple[str, str, str]]:
        return [(e.tool, e.outcome, e.detail) for e in (await self.audit.tail(50)).entries]


@pytest.fixture
def rig() -> Rig:
    return Rig()


# ---- choices --------------------------------------------------------------------------------


async def test_defaults_are_todays_behaviour_and_nothing_is_required(rig: Rig) -> None:
    v = await rig.svc.view(UID)
    assert v.passkeys_available and v.passkeys == [] and v.require_passkey is False
    assert v.reset is None and v.passkeys_error == ""
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
    await rig.docs.write(
        [Set(f"jarvis_permissions/{UID}", {"groups": {"email_send": "allow", "web": "nope"}})]
    )
    v = await rig.svc.view(UID)
    assert {g.id: g.effect for g in v.groups}["email_send"] == "ask"
    assert await rig.svc.rules_for(UID) == []


# ---- registration ---------------------------------------------------------------------------


async def test_the_first_passkey_needs_a_fresh_google_sign_in_in_a_browser(rig: Rig) -> None:
    for fresh in (None, 0):  # a bearer caller (no sign-in) / a sign-in older than 5 minutes
        with pytest.raises(ProofRequired) as e:
            await rig.svc.register_options(UID, user_name="o", fresh_left_s=fresh)
        assert e.value.reason == "reauth"
    with pytest.raises(PermissionRejected):
        await rig.svc.update(UID, PermissionsPatch(require_passkey=True))
    await rig.register("  My\u202e laptop\n ")
    v = await rig.svc.view(UID)
    assert v.require_passkey is True and [p.label for p in v.passkeys] == ["My laptop"]
    assert v.passkeys[0].via_recovery is False
    stored = (await rig.svc.passkeys.owned(UID))[0]
    assert stored.public_key and "private" not in stored.model_dump_json()


async def test_a_second_passkey_needs_a_passkey_never_a_sign_in(rig: Rig) -> None:
    await rig.register()
    for fresh in (None, 0, FRESH):
        with pytest.raises(ProofRequired) as e:
            await rig.svc.register_options(UID, user_name="o", proof=None, fresh_left_s=fresh)
        assert e.value.reason == "passkey"
    await rig.register("Phone", proof=await rig.proof("add"), fresh=None)
    assert len((await rig.svc.view(UID)).passkeys) == 2


async def test_unproven_options_cannot_add_a_passkey_once_one_exists(rig: Rig) -> None:
    # a stolen session asks for options while the owner has none yet ...
    early = await rig.svc.register_options(UID, user_name="o", fresh_left_s=FRESH)
    attacker = SoftAuthenticator(origin=RP.origin)
    cred = attacker.create(early.public_key)
    await rig.register("Owner's laptop")  # ... the owner sets up the first passkey meanwhile
    req = RegisterRequest.model_validate({"challenge_id": early.challenge_id, "credential": cred})
    with pytest.raises(ProofRequired):
        await rig.svc.register(UID, req)
    assert [p.label for p in (await rig.svc.view(UID)).passkeys] == ["Owner's laptop"]


async def test_registration_challenge_is_single_use_and_expires(rig: Rig) -> None:
    opts = await rig.svc.register_options(UID, user_name="o", fresh_left_s=FRESH)
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
    opts = await rig.svc.register_options(UID, user_name="o", fresh_left_s=FRESH)
    cred = rig.auth.create(opts.public_key, origin="https://evil.example")
    with pytest.raises(PasskeyRejected) as e:
        await rig.svc.register(
            UID,
            RegisterRequest.model_validate({"challenge_id": opts.challenge_id, "credential": cred}),
        )
    assert e.value.reason == "failed"


# ---- the approval guard -----------------------------------------------------------------------


async def test_no_passkey_no_requirement(rig: Rig) -> None:
    assert await rig.svc.check_approval(UID, rig.card(), None) is None


async def test_irreversible_card_needs_a_passkey_check_made_for_it(rig: Rig) -> None:
    cid = await rig.register()
    card = rig.card()
    with pytest.raises(PasskeyRequired, match="command line"):
        await rig.svc.check_approval(UID, card, None)
    note = await rig.svc.check_approval(UID, card, await rig.proof("approve", approval_id=card.id))
    assert note == f"passkey {passkey_ref(cid)}"


async def test_reversible_and_legacy_cards(rig: Rig) -> None:
    await rig.register()
    await rig.svc.check_approval(UID, rig.card("task_add", ActionRisk.REVERSIBLE), None)
    legacy = rig.card().model_copy(update={"tool_risk": None})  # stored before slice 10
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


async def test_a_cloned_counter_is_refused_and_audited(rig: Rig) -> None:
    cid = await rig.register()
    card = rig.card()
    await rig.svc.check_approval(UID, card, await rig.proof("approve", approval_id=card.id))
    card2 = rig.card(body="again")
    with pytest.raises(PasskeyRejected):
        await rig.svc.check_approval(
            UID, card2, await rig.proof("approve", approval_id=card2.id, get_kw={"sign_count": 1})
        )
    refused = [r for r in await rig.audit_rows() if r[1] == "check_refused"]
    assert refused == [
        (
            "passkey",
            "check_refused",
            f"approve: counter went backwards on passkey {passkey_ref(cid)} (possible clone)",
        )
    ]


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
    assert ("passkey", "check_refused", "approve: unknown_passkey") in await rig.audit_rows()


async def test_challenge_for_an_approval_of_another_owner_or_gone_is_refused(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    rig.approvals[card.id] = card.model_copy(update={"scope": "u_other:s1"})
    for aid in (card.id, "nope"):
        with pytest.raises(LookupError):
            await rig.svc.challenge(
                UID, ChallengeRequest(purpose="approve", approval_id=aid), approvals=rig.lookup
            )


async def test_the_requirement_is_read_fresh_not_from_the_cache(rig: Rig) -> None:
    await rig.register()
    assert await rig.svc.passkey_required(UID) is True
    await rig.docs.write([Set(f"jarvis_permissions/{UID}", {"require_passkey": False})])
    assert await rig.svc.passkey_required(UID) is False  # another instance switched it off
    await rig.docs.write([Set(f"jarvis_permissions/{UID}", {"require_passkey": True})])
    assert await rig.svc.passkey_required(UID) is True


# ---- removal and switching off: a passkey, never a sign-in ------------------------------------


async def test_removing_needs_a_passkey_check_for_exactly_that_one(rig: Rig) -> None:
    a = await rig.register("A")
    b = await rig.register("B", proof=await rig.proof("add"), fresh=None)
    for fresh in (None, FRESH):
        with pytest.raises(ProofRequired):
            await rig.svc.remove(UID, a, proof=None, fresh_left_s=fresh)
    with pytest.raises(PasskeyRejected):
        await rig.svc.remove(UID, a, proof=await rig.proof("remove", credential_id=b))
    v = await rig.svc.remove(UID, a, proof=await rig.proof("remove", credential_id=a))
    assert [p.label for p in v.passkeys] == ["B"] and v.require_passkey is True
    v = await rig.svc.remove(UID, b, proof=await rig.proof("remove", credential_id=b))
    assert v.passkeys == [] and v.require_passkey is False
    with pytest.raises(PasskeyNotFound):
        await rig.svc.remove(UID, b, proof=None)


async def test_switching_off_needs_a_passkey_switching_on_does_not(rig: Rig) -> None:
    await rig.register()
    for fresh in (None, FRESH):
        with pytest.raises(ProofRequired):
            await rig.svc.update(UID, PermissionsPatch(require_passkey=False), fresh_left_s=fresh)
    v = await rig.svc.update(
        UID, PermissionsPatch(require_passkey=False, proof=await rig.proof("disable"))
    )
    assert v.require_passkey is False
    assert await rig.svc.check_approval(UID, rig.card(), None) is None
    v = await rig.svc.update(UID, PermissionsPatch(require_passkey=True))
    assert v.require_passkey is True


# ---- the delayed reset: the only thing a Google sign-in can do -------------------------------


async def test_a_reset_needs_a_fresh_sign_in_and_takes_24_hours(rig: Rig) -> None:
    cid = await rig.register()
    for fresh in (None, 0):
        with pytest.raises(ProofRequired) as e:
            await rig.svc.start_reset(UID, fresh_left_s=fresh)
        assert e.value.reason == "reauth"
    v = await rig.svc.start_reset(UID, fresh_left_s=FRESH)
    assert v.reset is not None and v.reset.effective_at.startswith("2026-11-02T09:00")
    assert len(rig.notices) == 1 and "24 hours" in rig.notices[0][1]
    assert "cancel the reset with one of your passkeys" in rig.notices[0][2]
    again = await rig.svc.start_reset(UID, fresh_left_s=FRESH)  # idempotent: no second notice
    assert again.reset == v.reset and len(rig.notices) == 1
    rig.clock.advance(hours=23, minutes=59)
    assert await rig.svc.passkey_required(UID) is True  # still protected meanwhile
    card = rig.card()
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_approval(UID, card, None)
    rig.clock.advance(minutes=2)
    assert await rig.svc.passkey_required(UID) is False  # carried out lazily, once
    v = await rig.svc.view(UID)
    assert v.passkeys == [] and v.reset is None and v.require_passkey is False
    rows = await rig.audit_rows()
    assert [r[1] for r in rows if r[0] == "passkey"][-3:] == [
        "reset_requested",
        "reset_notice",
        "reset_completed",
    ]
    assert cid not in str(rows)
    # the next passkey is the first again (fresh sign-in) and is marked in the list
    await rig.register("New phone")
    v = await rig.svc.view(UID)
    assert [(p.label, p.via_recovery) for p in v.passkeys] == [("New phone", True)]
    await rig.register("Key", proof=await rig.proof("add"), fresh=None)
    assert [p.via_recovery for p in (await rig.svc.view(UID)).passkeys] == [True, False]


async def test_a_reset_is_cancelled_with_a_passkey_only(rig: Rig) -> None:
    await rig.register()
    await rig.svc.start_reset(UID, fresh_left_s=FRESH)
    with pytest.raises(ProofRequired):
        await rig.svc.cancel_reset(UID, proof=None, fresh_left_s=FRESH)
    v = await rig.svc.cancel_reset(UID, proof=await rig.proof("cancel_reset"))
    assert v.reset is None
    rig.clock.advance(hours=25)
    assert len((await rig.svc.view(UID)).passkeys) == 1  # nothing happens after a cancel
    assert ("passkey", "reset_cancelled", "proof: passkey") in await rig.audit_rows()


async def test_no_passkeys_no_reset(rig: Rig) -> None:
    with pytest.raises(PermissionRejected):
        await rig.svc.start_reset(UID, fresh_left_s=FRESH)


async def test_without_an_inbox_the_reset_still_happens_and_says_so(rig: Rig) -> None:
    rig.svc.notify = None
    await rig.register()
    await rig.svc.start_reset(UID, fresh_left_s=FRESH)
    assert (
        "passkey",
        "reset_notice",
        "no inbox copy (Gmail insert unavailable)",
    ) in await rig.audit_rows()


# ---- unreadable passkey data fails closed ----------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        {"creds": "garbage"},
        {"creds": [{"id": "x"}]},
        {"nothing": True},
    ],
)
async def test_unreadable_passkey_data_fails_closed(rig: Rig, doc: dict[str, Any]) -> None:
    await rig.register()
    await rig.docs.write([Set(f"jarvis_passkeys/{UID}", doc)])
    assert await rig.svc.passkey_required(UID) is True
    v = await rig.svc.view(UID)
    assert v.require_passkey is True and "can't be read" in v.passkeys_error
    card = rig.card()
    with pytest.raises(PasskeyRequired):
        await rig.svc.check_approval(UID, card, None)
    with pytest.raises(PasskeyDataUnreadable):
        await rig.svc.challenge(
            UID, ChallengeRequest(purpose="approve", approval_id=card.id), approvals=rig.lookup
        )
    # the owner can still change group choices, and can reset (the only way out)
    await rig.svc.update(UID, PermissionsPatch(groups={"web": "deny"}))
    await rig.svc.start_reset(UID, fresh_left_s=FRESH)
    rig.clock.advance(hours=24, seconds=1)
    v = await rig.svc.view(UID)
    assert v.passkeys == [] and v.passkeys_error == "" and v.require_passkey is False


# ---- no relying party / no Google sign-in ----------------------------------------------------


async def test_without_a_public_address_or_google_sign_in_passkeys_are_unavailable() -> None:
    for r, words in ((Rig(rp=None), "JARVIS_PUBLIC_BASE_URL"), (Rig(can_reauth=False), "Google")):
        v = await r.svc.view(UID)
        assert v.passkeys_available is False and words in v.passkeys_note
        with pytest.raises(PasskeysUnavailable):
            await r.svc.register_options(UID, user_name="o", fresh_left_s=FRESH)
        assert await r.svc.check_approval(UID, r.card(), None) is None  # the token alone


async def test_challenges_are_capped_per_purpose_so_approvals_survive_a_flood(rig: Rig) -> None:
    await rig.register()
    card = rig.card()
    approve = await rig.proof("approve", approval_id=card.id)
    for _ in range(15):
        await rig.svc.challenge(UID, ChallengeRequest(purpose="add"), approvals=rig.lookup)
    live = await rig.docs.query(Query("jarvis_webauthn_challenges"))
    assert len(live) <= 11  # ≤ 10 of "add" + the approval's own
    await rig.svc.check_approval(UID, card, approve)  # not pushed out
    rig.clock.advance(minutes=3)
    await rig.svc.challenge(UID, ChallengeRequest(purpose="add"), approvals=rig.lookup)
    assert len(await rig.docs.query(Query("jarvis_webauthn_challenges"))) == 1


async def test_changes_to_protection_are_in_the_audit_chain(rig: Rig) -> None:
    await rig.svc.update(UID, PermissionsPatch(groups={"web": "deny"}))
    a = await rig.register("A")
    b = await rig.register("B", proof=await rig.proof("add"), fresh=None)
    await rig.svc.remove(UID, b, proof=await rig.proof("remove", credential_id=b))
    await rig.svc.update(
        UID, PermissionsPatch(require_passkey=False, proof=await rig.proof("disable"))
    )
    tail = await rig.audit.tail(20)
    assert tail.verified
    got = [(e.agent, e.tool, e.outcome, e.detail) for e in tail.entries]
    assert got == [
        ("owner", "permissions", "changed", "web=deny"),
        ("owner", "passkey", "added", "first passkey (recent Google sign-in); requirement on"),
        ("owner", "passkey", "added", "proof: passkey"),
        ("owner", "passkey", "removed", f"{passkey_ref(b)}; proof: passkey"),
        ("owner", "permissions", "changed", "require_passkey=off; proof: passkey"),
    ]
    assert a not in str(got) and b not in str(got)  # credential ids stay out of the audit


def test_labels_are_cleaned_and_capped() -> None:
    assert clean_label("\u202eabc\u200b  def\n", "x") == "abc def"
    assert clean_label("   ", "Passkey 1") == "Passkey 1"
    assert len(clean_label("a" * 100, "x")) == 40
