# tests/test_kb_models.py -- R2 C: the note model, its cleaning and the trust-by-origin rule (D10).
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.kb.models import (
    MAX_TAGS,
    MAX_TEXT,
    NOTE_ID,
    Note,
    NotesError,
    PageExcerpt,
    clean_fields,
    host_of,
    normalise_link,
    vouches,
)

AT = datetime(2026, 11, 3, tzinfo=UTC)


def _note(**over: object) -> Note:
    base: dict[str, object] = {
        "id": "n_0123456789ab",
        "kind": "note",
        "title": "t",
        "text": "x",
        "origin": "typed",
        "created_at": AT,
        "updated_at": AT,
    }
    base.update(over)
    return Note(**base)  # type: ignore[arg-type]


def test_id_shape() -> None:
    assert NOTE_ID.fullmatch("n_0123456789ab")
    assert not NOTE_ID.fullmatch("n_0123456789AB")
    assert not NOTE_ID.fullmatch("v_0123456789ab")


@pytest.mark.parametrize("origin", ["typed", "memo", "imported"])
def test_owner_origins_vouch(origin: str) -> None:
    assert vouches(_note(origin=origin))


@pytest.mark.parametrize("origin", ["voice", "outside"])
def test_voice_and_outside_never_vouch(origin: str) -> None:
    assert not vouches(_note(origin=origin))


def test_a_note_with_page_text_never_vouches_whatever_its_origin() -> None:
    page = PageExcerpt(title="p", excerpt="other people's words", fetched_at=AT)
    assert not vouches(_note(kind="link", url="https://example.com/", page=page))


def test_clean_fields_trims_collapses_and_derives_a_title() -> None:
    f = clean_fields(kind="note", text="  The plumber is Ravi,\n comes on Tuesdays.  ", title=None)
    assert f.title.startswith("The plumber is Ravi")
    assert f.text == "The plumber is Ravi,\ncomes on Tuesdays."


def test_clean_fields_limits_and_tags() -> None:
    with pytest.raises(NotesError) as e:
        clean_fields(kind="note", text="a" * (MAX_TEXT + 1))
    assert e.value.status == 422 and e.value.code == "input_rejected"
    f = clean_fields(kind="note", text="ok", tags=[f"Tag{i}" for i in range(20)] + ["tag0"])
    assert len(f.tags) == MAX_TAGS and f.tags[0] == "tag0"


def test_clean_fields_refuses_empty_note_but_allows_a_link_without_text() -> None:
    with pytest.raises(NotesError):
        clean_fields(kind="note", text="   ")
    f = clean_fields(kind="link", text="", url="https://example.com/a")
    assert f.title == "example.com/a"


@pytest.mark.parametrize(
    "bad",
    [
        "http://example.com/",
        "javascript:alert(1)",
        "data:text/html,hi",
        "https://user:pw@example.com/",
        "https://127.0.0.1/",
        "ftp://example.com/",
        "not a url",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_bad_links_are_refused(bad: str) -> None:
    with pytest.raises(NotesError) as e:
        normalise_link(bad)
    assert e.value.code == "bad_url" and e.value.status == 422


def test_link_is_normalised_and_host_shown_as_punycode() -> None:
    assert normalise_link(" https://Example.com:443/a#frag ") == "https://example.com/a"
    assert host_of("https://www.bücher.example/x") == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "text",
    [
        "my card is 4111 1111 1111 1111",
        "the wifi password: hunter2hunter2",
        "PAN ABCDE1234F for the file",
    ],
)
def test_sensitive_text_is_refused_with_the_vault_words(text: str) -> None:
    with pytest.raises(NotesError) as e:
        clean_fields(kind="note", text=text)
    assert e.value.code == "sensitive" and e.value.status == 422
    assert "Vault" in e.value.detail
    assert "4111" not in e.value.detail and "hunter2" not in e.value.detail


def test_sensitive_is_checked_in_every_field() -> None:
    for kw in (
        {"title": "card 4111 1111 1111 1111"},
        {"owner_note": "password: hunter2hunter2"},
        {"tags": ["pan abcde1234f"]},
    ):
        with pytest.raises(NotesError) as e:
            clean_fields(kind="note", text="fine", **kw)  # type: ignore[arg-type]
        assert e.value.code == "sensitive"
