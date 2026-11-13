# tests/test_r11_1_b_kinds.py -- R11.1 Part B (plan D11): Excel (.xlsx / .xlsm, .xls) and
# PowerPoint (.pptx) are read as text inside their caps: values never formulas, every sheet and
# slide named, notes with their own slide; a workbook with too many sheets, a file with a DTD and
# a file that is not what its name says are refused in plain words; and the killable child process
# carries the new counts back to the server.
from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest
from r11_1_fakes_b import (
    XLS,
    make_png,
    make_pptx,
    make_xlsx,
    make_zip,
    many_sheets_xlsx,
    renamed_sheet_xlsx,
    sheet_xml,
    study_plan_xlsx,
)

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


def test_hidden_and_very_hidden_sheets_are_not_read_and_are_said() -> None:
    """Code review M5: a sheet the owner never sees is never sent; the text says how many were
    left out, and `sheets` counts the sheets read (one meaning)."""
    book = make_xlsx(
        {
            "Plan": [["Session", "Topic"], [1, "Made-up topic"]],
            "Secret": [["made-up hidden value"]],
            "Deep": [["made-up very hidden value"]],
        },
        states={"Secret": "hidden", "Deep": "veryHidden"},
    )
    out = extract(book, "xlsx")
    assert "hidden value" not in out.text and "Made-up topic" in out.text
    assert out.text.startswith("Sheet 1 of 1: Plan")
    assert out.text.endswith("(2 hidden sheets not read)")
    assert (out.sheets, out.rows) == (1, 2)
    one = extract(make_xlsx({"A": [["a"]], "B": [["b"]]}, states={"B": "hidden"}), "xlsx")
    assert one.text.endswith("(1 hidden sheet not read)") and one.sheets == 1


def test_a_workbook_with_only_hidden_sheets_says_so() -> None:
    # Excel will not save one, so the workbook part is edited as a hand-made file would be
    made = make_xlsx({"A": [["a"]], "B": [["b"]]}, states={"B": "veryHidden"})
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(made)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            body = src.read(info)
            if info.filename == "xl/workbook.xml":
                body = body.replace(b'sheetId="1" state="visible"', b'sheetId="1" state="hidden"')
            dst.writestr(info, body)
    e = rejected(extract, out.getvalue(), "xlsx")
    assert e.code == "no_text" and "hidden" in str(e) and "b" not in str(e).split()


def test_the_sheet_cap_counts_every_sheet_once_hidden_ones_too() -> None:
    sheets = {f"S{i}": [[f"cell {i}"]] for i in range(1, 5)}
    hidden = {f"S{i}": "hidden" for i in range(2, 5)}
    e = rejected(extract, make_xlsx(sheets, states=hidden), "xlsx", Limits(max_sheets=3))
    assert e.code == "too_complex" and "4 sheets" in str(e)


def test_a_hidden_xls_sheet_is_not_read_either(monkeypatch: pytest.MonkeyPatch) -> None:
    import xlrd

    real = xlrd.open_workbook

    def opened(*a: Any, **k: Any) -> Any:
        book = real(*a, **k)
        book._sheet_visibility[1] = 1  # noqa: SLF001 - the second sheet hidden, as Excel marks it
        return book

    monkeypatch.setattr(xlrd, "open_workbook", opened)
    out = extract(XLS.read_bytes(), "xls")
    assert out.sheets == 1 and out.text.endswith("(1 hidden sheet not read)")
    assert "Sheet 2" not in out.text


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


XXE = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]>'
LAUGHS = b'<!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'


@pytest.mark.parametrize("part", ["xl/worksheets/sheet1.txt", "xl/worksheets/sheet1.dat", "x/s"])
@pytest.mark.parametrize("doctype", [XXE, LAUGHS], ids=["external", "laughs"])
def test_a_dtd_in_a_part_with_any_name_is_refused(part: str, doctype: bytes) -> None:
    """Security review M1 (its proof of concept): openpyxl follows the relationships to a part
    of any name, so every member is scanned by its content, not its extension."""
    book = renamed_sheet_xlsx(part, sheet_xml("&e;", doctype=doctype))
    e = rejected(extract, book, "xlsx")
    assert e.code == "too_complex" and "unusual" in str(e)


async def test_the_child_refuses_the_renamed_dtd_part_too() -> None:
    book = renamed_sheet_xlsx("xl/worksheets/sheet1.txt", sheet_xml("&e;", doctype=XXE))
    with pytest.raises(DocumentRejected) as e:
        await extract_isolated(book, "xlsx", Limits())
    assert e.value.code == "too_complex"


def test_a_part_in_another_encoding_is_refused_whatever_its_name() -> None:
    utf16 = sheet_xml("plain").decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
    for body in (utf16.encode("utf-16"), utf16.encode("utf-16-le")):
        e = rejected(extract, renamed_sheet_xlsx("xl/worksheets/sheet1.txt", body), "xlsx")
        assert e.code == "too_complex"


def test_a_plain_renamed_part_and_a_picture_member_are_still_read() -> None:
    png = make_png(16, 16)  # binary, with zero bytes: never mistaken for odd XML
    book = renamed_sheet_xlsx(
        "xl/worksheets/sheet1.txt", sheet_xml("plain words"), {"xl/media/image1.png": png}
    )
    assert "plain words" in extract(book, "xlsx").text


def test_the_xml_cap_counts_a_part_by_its_content_not_its_name() -> None:
    big = sheet_xml("w " * 3_000)
    book = renamed_sheet_xlsx("xl/worksheets/sheet1.txt", big)
    with zipfile.ZipFile(io.BytesIO(book)) as zf:
        named = sum(i.file_size for i in zf.infolist() if i.filename.endswith((".xml", ".rels")))
    cap = named + len(big) // 2  # over what the names say, under what the content is
    e = rejected(extract, book, "xlsx", Limits(zip_max_xml=cap))
    assert e.code == "too_complex"
    assert "w w" in extract(book, "xlsx", Limits(zip_max_xml=named + len(big))).text


def test_a_pptx_slide_with_any_name_is_scanned_too() -> None:
    dtd = b'<?xml version="1.0"?>' + LAUGHS + b"<p:sld/>"
    e = rejected(extract, make_pptx(DECK, extra={"ppt/media/notes.bin": dtd}), "pptx")
    assert e.code == "too_complex"


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


# ---- workbooks: the edges ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        (True, "TRUE"),
        (False, "FALSE"),
        (7, "7"),
        (2.5, "2.5"),
        (1250.0, "1250"),
        (1e20, "1e+20"),
        (float("nan"), ""),
        (float("inf"), ""),
        ("two\nlines   here", "two lines here"),
        ("x" * 900, "x" * 500),
    ],
)
def test_a_cell_reads_as_plain_words(value: object, text: str) -> None:
    from jarvis.documents.sheets import cell_text

    assert cell_text(value) == text


def test_dates_and_times_in_cells_read_the_way_they_are_said() -> None:
    import datetime as dt

    from jarvis.documents.sheets import cell_text

    assert cell_text(dt.datetime(2026, 11, 12, 19, 30)) == "2026-11-12 19:30"
    assert cell_text(dt.datetime(2026, 11, 12)) == "2026-11-12"
    assert (
        cell_text(dt.time(7, 5, 9)) == "07:05:09" and cell_text(dt.date(2026, 1, 2)) == "2026-01-02"
    )


class Ticks:
    """A clock that moves one second every time it is read."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def test_a_workbook_that_runs_out_of_time_keeps_what_it_read() -> None:
    out = extract(study_plan_xlsx(60), "xlsx", Limits(budget_s=20.0), clock=Ticks())
    assert out.truncated and out.rows is not None and 0 < out.rows < 61
    assert out.text.startswith("Sheet 1 of 2: Plan") and "Sheet 2 of 2" not in out.text
    e = rejected(extract, study_plan_xlsx(60), "xlsx", Limits(budget_s=0.5), clock=Ticks())
    assert e.code == "too_slow"


def test_a_sheet_that_breaks_part_way_keeps_its_rows_and_says_so() -> None:
    from jarvis.documents.sheets import _Reader

    def rows():  # type: ignore[no-untyped-def]
        yield ["a", 1]
        yield ["b", 2]
        raise ValueError("damaged XML")

    reader = _Reader(Limits(), deadline=10.0, clock=lambda: 0.0, sheets=1)
    reader.sheet(1, "Broken", rows())
    out = reader.done("xlsx")
    assert out.truncated and out.rows == 2
    assert (
        out.text == "Sheet 1 of 1: Broken\na | 1\nb | 2\n(the rest of this sheet could not be read)"
    )


def test_rows_past_the_cap_are_counted_only_for_a_moment() -> None:
    from jarvis.documents.sheets import _Reader

    reader = _Reader(Limits(max_sheet_rows=1), deadline=1_000.0, clock=Ticks(), sheets=1)
    reader.sheet(1, "Long", iter([["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]))
    assert reader.done("xlsx").text.endswith("(more rows were not read)")


def test_an_empty_workbook_has_no_text() -> None:
    assert rejected(extract, make_xlsx({"Empty": []}), "xlsx").code == "no_text"


def test_an_xlsx_with_a_damaged_workbook_part_is_unreadable() -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(study_plan_xlsx(2))) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            body = (
                b"<workbook><not closed" if info.filename == "xl/workbook.xml" else src.read(info)
            )
            dst.writestr(info.filename, body)
    assert rejected(extract, buf.getvalue(), "xlsx").code == "unreadable"


def test_an_xls_with_too_many_sheets_is_refused_too() -> None:
    e = rejected(extract, XLS.read_bytes(), "xls", Limits(max_sheets=1))
    assert e.code == "too_complex" and "2 sheets" in str(e)


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        ("Workbook is encrypted", "encrypted"),
        ("Unsupported format, or corrupt file: Expected BOF record", "unsupported"),
        ("something else went wrong", "unreadable"),
    ],
)
def test_what_the_old_excel_reader_says_becomes_plain_words(
    monkeypatch: pytest.MonkeyPatch, raised: str, code: str
) -> None:
    import xlrd

    def boom(**_: object) -> None:
        raise xlrd.XLRDError(raised)

    monkeypatch.setattr(xlrd, "open_workbook", boom)
    e = rejected(extract, XLS.read_bytes(), "xls")
    assert e.code == code and "XLRD" not in str(e) and "BOF" not in str(e)


def test_old_excel_dates_true_false_and_errors_read_plainly() -> None:
    import datetime as dt

    from jarvis.documents.sheets import _xls_value, cell_text

    class Book:
        datemode = 0

    assert _xls_value(Book(), 46338.8125, 3) == dt.datetime(2026, 11, 12, 19, 30)
    assert _xls_value(Book(), 1e15, 3) == 1e15  # a serial out of range: the number is shown
    assert cell_text(_xls_value(Book(), 1, 4)) == "TRUE"
    assert _xls_value(Book(), 7, 5) == "#DIV/0!"
    assert (
        cell_text(_xls_value(Book(), 45.0, 2)) == "45" and _xls_value(Book(), "words", 1) == "words"
    )


def test_a_notes_page_that_cannot_be_read_is_said() -> None:
    """Code review L2: like a bad slide, a bad notes page is marked, never silently dropped."""
    deck = make_pptx(
        [(["Made-up opening"], ["Say hello"]), (["Made-up close"], [])],
        extra={"ppt/notesSlides/notesSlide2.xml": b"<p:notes><broken"},
    )
    out = extract(deck, "pptx")
    assert "Slide 1 of 2\nMade-up opening\n(notes could not be read)" in out.text
    assert "Say hello" not in out.text and "Made-up close" in out.text
