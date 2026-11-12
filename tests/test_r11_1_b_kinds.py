# tests/test_r11_1_b_kinds.py -- R11.1 Part B (plan D11): Excel (.xlsx / .xlsm, .xls) and
# PowerPoint (.pptx) are read as text inside their caps: values never formulas, every sheet and
# slide named, notes with their own slide; a workbook with too many sheets, a file with a DTD and
# a file that is not what its name says are refused in plain words; and the killable child process
# carries the new counts back to the server.
from __future__ import annotations

import pytest
from r11_1_fakes_b import XLS, make_pptx, make_xlsx, make_zip, many_sheets_xlsx, study_plan_xlsx

from jarvis.documents.extract import Limits, extract, kind_for, sniff
from jarvis.documents.isolation import extract_isolated
from jarvis.documents.limits import (
    ACCEPT,
    EXTENSIONS,
    KIND_LABELS,
    MAX_SHEETS,
    SUPPORTED_WORDS,
    DocumentRejected,
)


def rejected(fn, *a, **kw) -> DocumentRejected:  # type: ignore[no-untyped-def]
    with pytest.raises(DocumentRejected) as e:
        fn(*a, **kw)
    return e.value


# ---- which names are which kinds ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Plan.xlsx", "xlsx"),
        ("macro.XLSM", "xlsx"),
        ("old.xls", "xls"),
        ("deck.pptx", "pptx"),
        ("photo.png", "image"),
        ("photo.JPG", "image"),
        ("scan.jpeg", "image"),
        ("bundle.zip", "zip"),
    ],
)
def test_the_new_kinds_come_from_the_extension(name: str, kind: str) -> None:
    assert kind_for(name) == kind


@pytest.mark.parametrize("name", ["old.doc", "deck.ppt", "movie.mp4", "pic.gif", "run.exe", "a.7z"])
def test_other_kinds_are_still_refused_and_the_message_names_every_kind(name: str) -> None:
    e = rejected(kind_for, name)
    assert e.code == "unsupported" and e.status == 415
    for word in ("Excel", "PowerPoint", "pictures", "zip"):
        assert word in str(e)
    assert str(e).endswith(SUPPORTED_WORDS + ".")


def test_the_accept_list_is_every_extension_and_every_kind_has_a_plain_label() -> None:
    assert ACCEPT == tuple(EXTENSIONS)
    assert {".xlsx", ".xlsm", ".xls", ".pptx", ".png", ".jpg", ".jpeg", ".zip"} <= set(ACCEPT)
    assert set(EXTENSIONS.values()) | {"folder"} == set(KIND_LABELS)
    assert KIND_LABELS["xlsx"] == KIND_LABELS["xls"] == "Excel"
    assert KIND_LABELS["pptx"] == "PowerPoint" and KIND_LABELS["image"] == "picture"


# ---- Excel --------------------------------------------------------------------------------------


def test_an_xlsx_is_read_sheet_by_sheet_as_rows_of_text() -> None:
    out = extract(study_plan_xlsx(60), "xlsx")
    assert out.kind == "xlsx" and (out.sheets, out.rows) == (2, 63) and not out.truncated
    assert out.text.startswith("Sheet 1 of 2: Plan\nSession | Topic | Date | Minutes\n")
    assert "60 | Made-up topic 60 | 2026-12-05 | 45" in out.text
    assert "Sheet 2 of 2: Totals" in out.text


def test_a_formula_is_never_shown_only_the_value_the_file_holds() -> None:
    out = extract(make_xlsx({"Sums": [[2, 3, "=A1+B1"], ["total", "=SUM(A1:B1)"]]}), "xlsx")
    assert "=" not in out.text and "SUM" not in out.text  # no cached value: the cell reads empty
    assert out.text.splitlines()[1] == "2 | 3"


def test_numbers_dates_and_empty_cells_read_plainly() -> None:
    import datetime as dt

    rows = [
        ["When", "Paid", "Note"],
        [dt.date(2026, 11, 12), 1250.0, None],
        [dt.time(19, 30), 0.5, ""],
    ]
    text = extract(make_xlsx({"Money": rows}), "xlsx").text
    assert "2026-11-12 | 1250" in text and "19:30 | 0.5" in text
    assert "None" not in text and "1250.0" not in text


def test_a_workbook_with_too_many_sheets_is_refused_in_plain_words() -> None:
    e = rejected(extract, many_sheets_xlsx(300), "xlsx")
    assert e.code == "too_complex" and e.status == 422
    assert "300 sheets" in str(e) and f"up to {MAX_SHEETS}" in str(e)


def test_a_long_sheet_is_cut_at_its_row_cap_and_says_so() -> None:
    out = extract(
        make_xlsx({"Long": [[i, "x"] for i in range(40)]}), "xlsx", Limits(max_sheet_rows=10)
    )
    assert out.truncated and out.rows == 10
    assert "(30 more rows were not read)" in out.text and "\n9 | x\n" in out.text
    assert "\n10 | x" not in out.text


def test_a_big_workbook_is_cut_at_the_character_cap() -> None:
    out = extract(study_plan_xlsx(400), "xlsx", Limits(max_chars=2_000))
    assert out.truncated and len(out.text) <= 2_000


def test_an_xlsx_that_is_not_one_is_refused() -> None:
    assert rejected(sniff, b"just text", "xlsx").code == "unsupported"
    docx_like = make_zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"})
    assert rejected(extract, docx_like, "xlsx").code == "unsupported"
    ole = bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 64
    e = rejected(sniff, ole, "xlsx")
    assert e.code == "encrypted" and "password" in str(e)


def test_an_office_file_with_a_dtd_is_refused_before_any_parser_sees_it() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY l2 "&lol;&lol;">]>'
        b"<worksheet>&l2;</worksheet>"
    )
    good = study_plan_xlsx(2)
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            body = bomb if info.filename == "xl/worksheets/sheet1.xml" else src.read(info)
            dst.writestr(info.filename, body)
    e = rejected(extract, buf.getvalue(), "xlsx")
    assert e.code == "too_complex" and "unusual" in str(e)


def test_an_old_xls_is_read_with_its_sheets() -> None:
    out = extract(XLS.read_bytes(), "xls")
    assert out.kind == "xls" and out.sheets == 2 and out.rows == 5
    assert out.text.startswith("Sheet 1 of 2: Plan\nSession | Topic | Minutes | Fee\n")
    assert "1 | Made-up topic one | 45 | 250.5" in out.text and "SUM" not in out.text
    assert "Sheet 2 of 2: Notes\nBring the made-up workbook." in out.text


def test_an_xls_that_is_really_a_web_page_or_text_is_refused_plainly() -> None:
    e = rejected(sniff, b"<html><table><tr><td>1</td></tr></table></html>", "xls")
    assert e.code == "unsupported" and "save it as .xlsx" in str(e)
    assert rejected(extract, bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 600, "xls").code in (
        "unreadable",
        "encrypted",
    )


# ---- PowerPoint ---------------------------------------------------------------------------------

DECK = [
    (["Made-up plan", "Sixty sessions"], ["Say hello first."]),
    (["Budget", "About 500 rupees"], []),
    (["Thank you"], ["Close with the next date."]),
]


def test_a_pptx_is_read_slide_by_slide_with_each_slides_own_notes() -> None:
    out = extract(make_pptx(DECK), "pptx")
    assert out.kind == "pptx" and out.slides == 3 and not out.truncated
    assert out.text.startswith(
        "Slide 1 of 3\nMade-up plan\nSixty sessions\nNotes: Say hello first."
    )
    assert (
        "Slide 2 of 3\nBudget\nAbout 500 rupees\n\nSlide 3 of 3\nThank you\nNotes: Close with"
        in (out.text)
    )


def test_slides_are_read_in_number_order_not_name_order() -> None:
    deck = [([f"slide number {i}"], []) for i in range(1, 13)]
    text = extract(make_pptx(deck), "pptx").text
    assert (
        text.index("slide number 2\n") < text.index("slide number 10\n") < text.index("number 12")
    )


def test_slides_follow_the_decks_own_order_when_it_says_one() -> None:
    deck = [(["first made"], ["note one"]), (["second made"], []), (["third made"], [])]
    text = extract(make_pptx(deck, order=[3, 1, 2]), "pptx").text
    assert text.startswith("Slide 1 of 3\nthird made\n\nSlide 2 of 3\nfirst made\nNotes: note one")
    assert text.endswith("Slide 3 of 3\nsecond made")


def test_a_table_on_a_slide_reads_row_by_row() -> None:
    table = (
        b'<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        b'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><a:tbl>'
        b"<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Day</a:t></a:r></a:p></a:txBody></a:tc>"
        b"<a:tc><a:txBody><a:p><a:r><a:t>Topic</a:t></a:r></a:p></a:txBody></a:tc></a:tr>"
        b"<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Mon</a:t></a:r><a:br/><a:r><a:t>7 pm</a:t></a:r>"
        b"</a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Made-up</a:t></a:r></a:p>"
        b"</a:txBody></a:tc></a:tr></a:tbl></p:sld>"
    )
    text = extract(make_pptx([(["x"], [])], extra={"ppt/slides/slide1.xml": table}), "pptx").text
    assert text == "Slide 1 of 1\nDay | Topic\nMon 7 pm | Made-up"


def test_a_pptx_with_no_words_or_no_slides_says_so() -> None:
    assert rejected(extract, make_pptx([([], [])]), "pptx").code == "no_text"
    not_a_deck = make_zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"})
    assert rejected(extract, not_a_deck, "pptx").code == "unsupported"


def test_a_pptx_with_a_dtd_or_broken_xml_never_crashes() -> None:
    dtd = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><p:sld/>'
    assert rejected(
        extract, make_pptx(DECK, extra={"ppt/slides/slide9.xml": dtd}), "pptx"
    ).code == ("too_complex")
    broken = make_pptx(DECK, extra={"ppt/slides/slide2.xml": b"<p:sld><not closed"})
    out = extract(broken, "pptx")  # one bad slide never sinks the deck
    assert out.slides == 3 and "Made-up plan" in out.text and "Thank you" in out.text


def test_a_notes_link_that_points_outside_the_deck_is_ignored() -> None:
    rels = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'relationships/notesSlide" Target="../../../../etc/passwd"/></Relationships>'
    )
    deck = make_pptx([(["Only slide"], [])], extra={"ppt/slides/_rels/slide1.xml.rels": rels})
    assert extract(deck, "pptx").text == "Slide 1 of 1\nOnly slide"


# ---- the child process carries the new counts ---------------------------------------------------


async def test_the_child_process_reads_each_new_kind_and_reports_its_counts() -> None:
    sheet = await extract_isolated(study_plan_xlsx(5), "xlsx", Limits())
    assert (sheet.sheets, sheet.rows) == (2, 8) and "Made-up topic 5" in sheet.text
    old = await extract_isolated(XLS.read_bytes(), "xls", Limits())
    assert old.sheets == 2 and "Made-up topic three" in old.text
    deck = await extract_isolated(make_pptx(DECK), "pptx", Limits())
    assert deck.slides == 3 and deck.text.startswith("Slide 1 of 3")


async def test_the_child_refuses_a_300_sheet_workbook_in_plain_words() -> None:
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(many_sheets_xlsx(300), "xlsx", Limits())
    assert e.value.code == "too_complex" and "300 sheets" in str(e.value)
