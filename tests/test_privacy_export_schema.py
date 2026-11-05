# tests/test_privacy_export_schema.py - R2 D14 (review M3): a per-source schema test. What a
# source exports, after `scrub`, may only use the keys listed here. A new field in an export
# fails this test until someone has looked at it and added it - so a secret-looking field cannot
# slip into a download by being added to a model.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from billing_fakes import Clock
from google_fakes import google_tokens

from jarvis.billing.meter import UsageMeter
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ActionRisk
from jarvis.core.models import Session, Turn
from jarvis.drive.roots import RootsStore
from jarvis.family.models import Member
from jarvis.family.store import FamilyStore
from jarvis.groceries.store import GroceryStore
from jarvis.integrations.vault import MemoryTokenStore
from jarvis.llm.base import Role
from jarvis.places.store import MapsPlaces
from jarvis.privacy.export import scrub
from jarvis.privacy.sources import (
    audit_source,
    conversations_source,
    drive_source,
    google_source,
    passkeys_source,
    places_source,
    settings_source,
    spend_source,
)
from jarvis.privacy.sources_r1 import family_source, groceries_source, telegram_source
from jarvis.storage.docs import MemoryDocs
from jarvis.storage.sessions import DocSessionStore
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditLog

UID = "u_owner"

ALLOWED: dict[str, set[str]] = {
    "google": {"connected", "account", "scopes", "needs_reconnect"},
    "places": {"home", "work"},
    "drive": {"folders", "name", "id", "added_at", "email", "link", "confirmed_at"},
    "telegram": {
        "paired", "paired_at", "allow_private_reads", "alerts", "approval_waiting", "brief_ready",
        "offline",
    },
    "groceries": {"list_id", "title"},
    "family": {"members", "name", "calendar", "access", "added_at"},
    "audit": {"newest", "entries", "seq", "at", "agent", "tool", "risk", "outcome"},
    "spend": {"months", "month", "rupees", "calls"},
    "passkeys": {"passkeys", "label", "added"},
    "conversations": {
        "newest", "conversations", "id", "title", "updated_at", "turns", "role", "content", "at",
    },
}  # fmt: skip


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        out = set(value)
        for v in value.values():
            out |= keys_of(v)
        return out
    if isinstance(value, list):
        return set().union(*(keys_of(v) for v in value)) if value else set()
    return set()


async def _exports() -> dict[str, dict[str, Any]]:
    docs = MemoryDocs()
    out: dict[str, Any] = {}
    tokens = MemoryTokenStore()
    await tokens.put(UID, google_tokens())
    out["google"] = await google_source(tokens).export(UID)
    places = MapsPlaces(docs, key=bytes(range(1, 33)))
    await places.put(UID, home="Kowdiar", work="Technopark")
    out["places"] = await places_source(places).export(UID)
    roots = RootsStore(docs)
    await roots.confirm(UID, "1AbCdEfGhIjKlMnOpQrStUv", "Receipts", email="me@example.com")
    out["drive"] = await drive_source(roots).export(UID)
    tg = TelegramStore(docs)
    code, _ = await tg.start_pairing(UID)
    await tg.finish_pairing(code, tg_user_id=1, chat_id=2)
    out["telegram"] = await telegram_source(tg).export(UID)
    groceries = GroceryStore(docs)
    await groceries.remember(UID, "list_abc")
    out["groceries"] = await groceries_source(groceries).export(UID)
    fam = FamilyStore(docs)
    await fam.add(
        UID,
        Member(
            id="m1",
            name="Priya",
            calendar_id="p@example.com",
            access="reader",
            added_at="2026-11-01",
            verified_at="2026-11-01",
        ),
    )
    out["family"] = await family_source(fam).export(UID)
    log = AuditLog()
    await log.append(
        agent="owner", tool="x", risk=ActionRisk.READ_ONLY, outcome="executed", args={"a": 1}
    )
    out["audit"] = await audit_source(log).export(UID)
    meter = UsageMeter(docs)
    clock = Clock(datetime(2026, 11, 15, 6, 0, tzinfo=UTC))
    await meter.add(UID, brain_id="b", cost_usd=0.1, cost_inr=9.5, now=clock())
    out["spend"] = await spend_source(meter, clock).export(UID)
    from test_permissions_service import Rig as PermRig

    pr = PermRig()
    await pr.register("Laptop")
    out["passkeys"] = await passkeys_source(pr.svc).export(UID)
    sessions = DocSessionStore(docs)
    s = Session(id="sess_a1", user_id=UID)
    s.append(Turn(role=Role.USER, content="hi"))
    await sessions.save(s)
    out["conversations"] = await conversations_source(sessions).export(UID)
    return out


async def test_every_export_uses_only_its_listed_keys_and_scrub_changes_nothing() -> None:
    exports = await _exports()
    assert set(exports) == set(ALLOWED)
    for sid, exp in exports.items():
        assert keys_of(scrub(exp)) <= ALLOWED[sid], (sid, keys_of(exp) - ALLOWED[sid])
        assert scrub(exp) == exp, sid  # nothing the source built was secret-looking


async def test_brief_settings_export_has_no_secret_looking_key() -> None:
    exp = await settings_source(BriefStore(MemoryDocs())).export(UID)
    assert exp is not None and scrub(exp) == exp


def test_the_schema_test_itself_catches_a_new_unlisted_key() -> None:
    assert keys_of(scrub({"home": "a", "extra": 1})) - ALLOWED["places"] == {"extra"}
    with pytest.raises(AssertionError):
        assert keys_of(scrub({"home": "a", "extra": 1})) <= ALLOWED["places"]
