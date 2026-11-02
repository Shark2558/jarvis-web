# tests/test_google_grants.py — slice 12 D7: optional Google permissions ("Grant") generalised.
# Exactly one allow-listed name per Grant; a renewal keeps every optional scope the link already
# holds; a plain (re)connect asks for what it always did plus only what is held (review L8).
from __future__ import annotations

import pytest

from jarvis.integrations.google import (
    CONNECT_SCOPES,
    CONTACTS_SCOPE,
    GRANTS,
    INSERT_SCOPE,
    OPTIONAL_SCOPES,
    REQUIRED_SCOPES,
    TASKS_SCOPE,
    TOOL_SCOPES,
    YOUTUBE_SCOPE,
    can_use_contacts,
    can_use_tasks,
    can_use_youtube,
    connect_scopes,
    grant_name,
    held_grants,
)


def test_the_new_scopes_are_the_read_only_ones() -> None:
    assert CONTACTS_SCOPE == "https://www.googleapis.com/auth/contacts.readonly"
    assert YOUTUBE_SCOPE == "https://www.googleapis.com/auth/youtube.readonly"
    assert GRANTS == {"tasks": TASKS_SCOPE, "contacts": CONTACTS_SCOPE, "youtube": YOUTUBE_SCOPE}


def test_every_grant_is_optional_and_never_required() -> None:
    for scope in GRANTS.values():
        assert scope in OPTIONAL_SCOPES and scope in TOOL_SCOPES
        assert scope not in REQUIRED_SCOPES and scope not in CONNECT_SCOPES
    assert set(TOOL_SCOPES) == {"openid", "email", *REQUIRED_SCOPES, *OPTIONAL_SCOPES}


def test_a_plain_connect_asks_exactly_what_it_always_did() -> None:
    assert connect_scopes() == " ".join(CONNECT_SCOPES)
    assert INSERT_SCOPE in connect_scopes().split()
    for scope in GRANTS.values():
        assert scope not in connect_scopes().split()


def test_connect_scopes_adds_each_named_grant_once_in_a_fixed_order() -> None:
    both = connect_scopes({"youtube", "contacts"}).split()
    assert both == [*CONNECT_SCOPES, CONTACTS_SCOPE, YOUTUBE_SCOPE]
    assert connect_scopes(["tasks", "tasks"]).split() == [*CONNECT_SCOPES, TASKS_SCOPE]
    with pytest.raises(ValueError):
        connect_scopes({"drive"})


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("tasks", "tasks"),
        ("contacts", "contacts"),
        ("youtube", "youtube"),
        ("CONTACTS", None),
        (" contacts", None),
        ("contacts,youtube", None),
        ("contacts.readonly", None),
        (CONTACTS_SCOPE, None),
        ("https://mail.google.com/", None),
        ("", None),
        (None, None),
        ("__proto__", None),
        ("drive", None),
    ],
)
def test_grant_name_is_an_exact_allow_list(raw: str | None, want: str | None) -> None:
    assert grant_name(raw) == want


def test_held_grants_reads_the_link_scopes() -> None:
    assert held_grants([]) == frozenset()
    assert held_grants([*REQUIRED_SCOPES, CONTACTS_SCOPE]) == frozenset({"contacts"})
    assert held_grants(TOOL_SCOPES) == frozenset(GRANTS)


def test_can_use_helpers() -> None:
    assert can_use_contacts([CONTACTS_SCOPE])
    # the full contacts scope also allows people.searchContacts (People API reference)
    assert can_use_contacts(["https://www.googleapis.com/auth/contacts"])
    assert not can_use_contacts(REQUIRED_SCOPES)
    assert not can_use_contacts(["https://www.googleapis.com/auth/contacts.other.readonly"])
    assert can_use_youtube([YOUTUBE_SCOPE]) and not can_use_youtube(REQUIRED_SCOPES)
    assert can_use_tasks([TASKS_SCOPE]) and not can_use_tasks([CONTACTS_SCOPE])
