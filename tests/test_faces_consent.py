# tests/test_faces_consent.py -- R3 D13: consent first. The statement is the plan's, by age; an
# adult needs the person's own agreement, a child a parent's or guardian's; the version and the
# date are recorded; a consent older than 365 days shows the yearly question.
from __future__ import annotations

import pytest
from faces_fakes import UID, add_adult, add_child, faces

from jarvis.faces.consent import (
    CONSENT_VERSION,
    ConsentRejected,
    check,
    renewal_due,
    statement,
)
from jarvis.faces.service import PersonRejected


def test_the_adult_statement_is_the_plans_words() -> None:
    assert statement("fc1", False, "Anjali") == (
        "Anjali agreed that the camera at my home may recognise their face and greet them by "
        "name; their face pictures stay on my laptop; they can ask me to delete them at any time"
    )


def test_the_child_statement_names_a_parent_or_guardian() -> None:
    assert statement("fc1", True, "Mini") == (
        "Mini is under 18 and I am their parent or legal guardian "
        "(or have their parent's agreement)"
    )


def test_an_unknown_version_has_no_statement() -> None:
    with pytest.raises(ConsentRejected):
        statement("fc9", False, "Anjali")


@pytest.mark.parametrize("confirm", [False, None, "yes", 1])
def test_no_ticked_statement_is_consent_missing(confirm: object) -> None:
    with pytest.raises(ConsentRejected) as err:
        check(child=False, given_by="self", version="fc1", confirm=confirm)
    assert err.value.code == "consent_missing"


def test_a_stale_or_unknown_statement_version_is_consent_missing() -> None:
    with pytest.raises(ConsentRejected) as err:
        check(child=False, given_by="self", version="fc0", confirm=True)
    assert err.value.code == "consent_missing"


def test_a_child_without_a_guardian_is_refused_with_its_own_code() -> None:
    with pytest.raises(ConsentRejected) as err:
        check(child=True, given_by="self", version="fc1", confirm=True)
    assert err.value.code == "child_needs_guardian"


def test_an_adult_cannot_be_enrolled_on_a_guardians_say_so() -> None:
    with pytest.raises(ConsentRejected) as err:
        check(child=False, given_by="parent_guardian", version="fc1", confirm=True)
    assert err.value.code == "consent_missing"


async def test_the_version_and_date_are_recorded() -> None:
    f = faces()
    p = await add_adult(f)
    assert (p.consent_version, p.given_by, p.consent_at) == (
        CONSENT_VERSION,
        "self",
        f.clock.now.isoformat(),
    )
    c = await add_child(f)
    assert c.given_by == "parent_guardian" and c.child is True


async def test_the_service_refuses_without_consent_and_stores_nothing() -> None:
    f = faces()
    with pytest.raises(PersonRejected) as err:
        await add_adult(f, confirm=False)
    assert err.value.code == "consent_missing" and err.value.status == 422
    with pytest.raises(PersonRejected) as err2:
        await add_child(f, given_by="self")
    assert err2.value.code == "child_needs_guardian"
    assert (await f.store.load(UID)).people == ()


async def test_the_yearly_check_shows_after_365_days() -> None:
    f = faces()
    p = await add_adult(f)
    assert renewal_due(p, f.clock.now) is False
    f.clock.advance(days=365)
    assert renewal_due(p, f.clock.now) is False
    f.clock.advance(days=1)
    assert renewal_due(p, f.clock.now) is True


async def test_reconfirming_restarts_the_year() -> None:
    f = faces()
    p = await add_adult(f)
    f.clock.advance(days=400)
    assert (await f.svc.view(UID)).people[0].renewal_due is True
    await f.svc.update(UID, p.id, reconfirm=True)
    assert (await f.svc.view(UID)).people[0].renewal_due is False
