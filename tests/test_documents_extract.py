# tests/test_documents_extract.py — slice 10 E (D-E1): server-side text extraction. Type by name
# AND magic bytes; pypdf / python-docx / UTF-8 (BOM, UTF-16, cp1252 → latin-1) text; limits on
# pages, characters, time and zip size; plain messages for encrypted, scanned and broken files.
from __future__ import annotations

import codecs
import itertools

import pytest
from doc_fakes import (
    CONTENT_TYPES,
    OLE_MAGIC,
    docx_bomb,
    encrypt_pdf,
    make_docx,
    make_pdf,
    make_zip,
)

from jarvis.documents.extract import Limits, extract, kind_for, normalise, sniff
from jarvis.documents.models import DocumentRejected


def rejected(fn, *a, **kw) -> DocumentRejected:  # type: ignore[no-untyped-def]
    with pytest.raises(DocumentRejected) as ei:
        fn(*a, **kw)
    return ei.value


# ---- type: extension, then magic bytes --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Q4 report.PDF", "pdf"),
        ("notes.docx", "docx"),
        ("a.txt", "txt"),
        ("README.md", "md"),
        ("x.markdown", "md"),
        ("data.CSV", "csv"),
    ],
)
def test_kind_comes_from_a_known_extension(name: str, kind: str) -> None:
    assert kind_for(name) == kind


@pytest.mark.parametrize("name", ["report", "old.doc", "sheet.xlsx", "run.exe", "pic.png", ".pdf"])
def test_other_extensions_are_unsupported_with_a_plain_message(name: str) -> None:
    e = rejected(kind_for, name)
    assert e.code == "unsupported" and e.status == 415
    assert "PDF" in str(e) and "Word" in str(e)


def test_a_pdf_named_docx_is_refused_by_its_magic_bytes() -> None:
    e = rejected(sniff, make_pdf(["hi"]), "docx")
    assert e.code == "unsupported" and "don't match" in str(e)


@pytest.mark.parametrize("kind", ["pdf", "txt", "md", "csv"])
def test_a_zip_is_never_read_as_pdf_or_text(kind: str) -> None:
    e = rejected(sniff, make_zip({"a.txt": b"x"}), kind)
    assert e.code == "unsupported"


def test_a_png_named_txt_is_refused() -> None:
    assert rejected(sniff, b"\x89PNG\r\n\x1a\n" + b"\0" * 40, "txt").code == "unsupported"


def test_an_ole_file_named_docx_is_called_password_protected_or_old() -> None:
    e = rejected(sniff, OLE_MAGIC + b"\0" * 100, "docx")
    assert e.code == "encrypted" and "password" in str(e) and ".doc" in str(e)


def test_an_empty_file_is_refused() -> None:
    assert rejected(sniff, b"", "txt").code == "empty"


# ---- PDF --------------------------------------------------------------------------------------


def test_pdf_text_pages_and_page_offsets() -> None:
    out = extract(make_pdf(["Page one says hello", "Second page (with brackets)", "Third"]), "pdf")
    assert out.kind == "pdf" and out.pages == 3 and out.pages_total == 3 and not out.truncated
    assert "Page one says hello" in out.text and "Second page (with brackets)" in out.text
    assert len(out.page_starts) == 3 and out.page_starts[0] == 0
    assert out.text[out.page_starts[1] :].startswith("Second page")


def test_pdf_page_limit_keeps_the_first_pages_and_says_so() -> None:
    out = extract(make_pdf(["one", "two", "three"]), "pdf", Limits(max_pages=2))
    assert out.pages == 2 and out.pages_total == 3 and out.truncated
    assert "three" not in out.text


def test_pdf_with_a_user_password_is_refused_plainly() -> None:
    e = rejected(extract, encrypt_pdf(make_pdf(["secret plans"])), "pdf")
    assert e.code == "encrypted" and "password" in str(e)


def test_pdf_with_only_an_owner_password_opens_like_any_viewer_would() -> None:
    out = extract(encrypt_pdf(make_pdf(["open to read"]), user_password=""), "pdf")
    assert "open to read" in out.text


def test_scanned_pdf_with_no_text_layer_says_no_text_found() -> None:
    e = rejected(extract, make_pdf(["", ""]), "pdf")
    assert e.code == "no_text" and "scan" in str(e)


def test_broken_pdf_is_unreadable_not_a_crash() -> None:
    e = rejected(extract, b"%PDF-1.7\n" + b"garbage " * 200, "pdf")
    assert e.code == "unreadable"


def test_pdf_characters_are_capped() -> None:
    out = extract(make_pdf(["word " * 400, "more " * 400]), "pdf", Limits(max_chars=1_000))
    assert len(out.text) == 1_000 and out.truncated


def test_pdf_time_budget_keeps_what_was_read() -> None:
    ticks = itertools.count(0.0, 5.0)  # every clock read is 5 s later
    out = extract(
        make_pdf(["first", "second", "third"]), "pdf", Limits(budget_s=6), clock=lambda: next(ticks)
    )
    assert out.truncated and "first" in out.text and "third" not in out.text


def test_pdf_time_budget_with_nothing_read_is_too_slow() -> None:
    ticks = itertools.count(0.0, 100.0)
    e = rejected(extract, make_pdf(["first"]), "pdf", Limits(budget_s=1), clock=lambda: next(ticks))
    assert e.code == "too_slow"


# ---- DOCX ---------------------------------------------------------------------------------------


def test_docx_paragraphs_and_tables_in_document_order() -> None:
    data = make_docx(["Intro line", "Second para"], table=[["Name", "Role"], ["Asha", "Lead"]])
    out = extract(data, "docx")
    assert out.kind == "docx" and out.pages is None and not out.truncated
    t = out.text
    assert t.index("Intro line") < t.index("Name | Role") < t.index("Asha | Lead")
    assert t.index("Asha | Lead") < t.index("After the table.")


def test_docx_that_unpacks_past_the_total_limit_is_refused_before_parsing() -> None:
    e = rejected(extract, docx_bomb(2_000_000), "docx", Limits(zip_max_total=1_000_000))
    assert e.code == "too_complex" and "unpacks" in str(e)


def test_docx_bomb_at_the_real_limits() -> None:
    e = rejected(extract, docx_bomb(51 * 1024 * 1024), "docx")
    assert e.code == "too_complex"


def test_docx_with_an_extreme_compression_ratio_is_refused() -> None:
    e = rejected(extract, docx_bomb(3_000_000), "docx", Limits(zip_max_ratio=50))
    assert e.code == "too_complex"


def test_docx_with_too_many_zip_entries_is_refused() -> None:
    entries = {f"word/media/{i}.xml": b"x" for i in range(30)}
    entries |= {"[Content_Types].xml": CONTENT_TYPES, "word/document.xml": b"<x/>"}
    e = rejected(extract, make_zip(entries), "docx", Limits(zip_max_entries=20))
    assert e.code == "too_complex"


def test_a_zip_without_a_word_document_is_not_a_docx() -> None:
    e = rejected(
        extract, make_zip({"[Content_Types].xml": CONTENT_TYPES, "a.xml": b"<a/>"}), "docx"
    )
    assert e.code == "unsupported"


def test_a_damaged_docx_is_unreadable() -> None:
    data = make_zip({"[Content_Types].xml": CONTENT_TYPES, "word/document.xml": b"<not xml"})
    assert rejected(extract, data, "docx").code == "unreadable"


def test_an_empty_docx_has_no_text() -> None:
    assert rejected(extract, make_docx([]), "docx").code == "no_text"


# ---- text, Markdown, CSV --------------------------------------------------------------------


def test_utf8_bom_is_dropped() -> None:
    out = extract(codecs.BOM_UTF8 + "naïve café".encode(), "txt")
    assert out.text == "naïve café"


def test_utf16_with_bom_is_read() -> None:
    out = extract("കേരളം — Kerala".encode("utf-16"), "md")
    assert out.text == "കേരളം — Kerala"


def test_windows_1252_falls_back_cleanly() -> None:
    out = extract("“Quoted” café".encode("cp1252"), "txt")
    assert out.text == "“Quoted” café"


def test_bytes_cp1252_cannot_hold_fall_back_to_latin1() -> None:
    out = extract(b"caf\xe9 \x81", "txt")  # 0x81 is undefined in cp1252
    assert out.text.startswith("café")


def test_csv_is_kept_as_text() -> None:
    out = extract(b"name,amount\nAsha,1200\nRavi,900\n", "csv")
    assert out.kind == "csv" and "Asha,1200" in out.text and out.pages is None


def test_binary_named_txt_is_refused() -> None:
    e = rejected(extract, b"abc\x00\x01\x02\x03def" * 50, "txt")
    assert e.code == "unsupported" and "text file" in str(e)


def test_text_is_capped_at_the_character_limit() -> None:
    out = extract(b"a" * 5_000, "txt", Limits(max_chars=1_200))
    assert len(out.text) == 1_200 and out.truncated


def test_whitespace_only_text_has_no_text() -> None:
    assert rejected(extract, b"   \n\n \t ", "txt").code == "no_text"


# ---- normalisation --------------------------------------------------------------------------


def test_normalise_cleans_controls_line_endings_blank_runs_and_lone_surrogates() -> None:
    raw = "a\r\nb\rc\x07d   \n\n\n\n\ne\ud800f‌"
    assert normalise(raw) == "a\nb\ncd\n\nef‌"  # ZWNJ (Malayalam) is kept
