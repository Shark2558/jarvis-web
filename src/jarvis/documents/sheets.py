# src/jarvis/documents/sheets.py
"""Excel workbooks as text (R11.1, docs/plans/r11-1-observations.md D11; Layer 2 input). Pure and
synchronous; in the app it runs only inside the extraction worker (`jarvis.documents.worker`).

    .xlsx / .xlsm   openpyxl (MIT), read-only, `data_only`: the VALUE each cell holds, never its
                    formula; macros are never run (nothing in a workbook is executed)
    .xls            xlrd (BSD), on demand, its warnings sent nowhere (the worker's standard
                    output is the answer itself)

Only the sheets the owner can see are read (code review M5): a hidden or "very hidden" sheet is
never sent anywhere, and the text ends with "(2 hidden sheets not read)". Each visible sheet
becomes "Sheet N of M: <name>" (M: the visible sheets) and its rows as "a | b | c"; `sheets` is
the number of sheets read. Caps: a workbook with more than `Limits.max_sheets` sheets in all
(every sheet the workbook lists, hidden ones too: one count, taken once) is refused, never
half-read; at most `Limits.max_sheet_rows` rows a sheet (the rest are counted for a moment and
said), `MAX_ROW_CELLS` cells a row, `MAX_CELL_CHARS` characters a cell, `Limits.max_chars` in
all, and the time budget between rows (what was read in time is kept, marked truncated). The
.xlsx zip is checked before any XML is parsed (`extract.office_guard`: not a bomb, no document
type definition in any part).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import io
from collections.abc import Iterable, Iterator
from typing import Any

from jarvis.documents.extract import (
    ENCRYPTED_OFFICE,
    XLS_NOT_EXCEL,
    Clock,
    Extracted,
    Limits,
    _cap,
    _no_text,
    _unreadable,
    _unsupported,
    normalise,
    office_guard,
    too_complex,
    too_slow,
)
from jarvis.documents.limits import MAX_CELL_CHARS, MAX_ROW_CELLS, DocumentRejected

TITLE_CHARS = 80
COUNT_BUDGET_S = 2.0  # how long the rows past a sheet's cap are counted before "more rows"
_XL_DATE, _XL_BOOL, _XL_ERROR, _XL_NUMBER = 3, 4, 5, 2


class _Stop(Exception):
    """The time budget or the character cap ran out: keep what was read."""


def _too_many(count: int, limit: int) -> DocumentRejected:
    return DocumentRejected(
        "too_complex",
        f"This workbook has {count:,} sheets; JARVIS reads up to {limit} sheets from one file. "
        "Save the sheets you need as a smaller workbook and attach that.",
    )


ALL_HIDDEN = (
    "Every sheet in this workbook is hidden, and JARVIS reads only the sheets you can see. "
    "Unhide the ones you need, save it, and attach it again."
)


def _hidden_line(count: int) -> str:
    return f"({count} hidden sheet{'' if count == 1 else 's'} not read)"


def _number(v: float) -> str:
    if v != v or v in (float("inf"), float("-inf")):  # NaN / infinity: say nothing false
        return ""
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return format(v, ".15g")


def _clock_time(t: dt.time) -> str:
    return t.strftime("%H:%M:%S" if t.second else "%H:%M")


def cell_text(v: Any) -> str:
    """One cell's value as plain words (never a formula: the reader hands over values)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _number(v)
    if isinstance(v, dt.datetime):
        day = v.date().isoformat()
        return day if v.time() == dt.time(0, 0) else f"{day} {_clock_time(v.time())}"
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dt.time):
        return _clock_time(v)
    return " ".join(str(v).split())[:MAX_CELL_CHARS]


def _line(values: Iterable[Any]) -> str:
    cells = [cell_text(v) for v in values]
    while cells and not cells[-1]:
        cells.pop()
    return " | ".join(cells) if any(cells) else ""


def _title(name: Any) -> str:
    return " ".join(str(name or "").split())[:TITLE_CHARS] or "(no name)"


class _Reader:
    """Collects sheets as text within the caps; `more` says something was left out."""

    def __init__(
        self, limits: Limits, deadline: float, clock: Clock, sheets: int, *, hidden: int = 0
    ) -> None:
        self.limits, self.deadline, self.clock, self.sheets = limits, deadline, clock, sheets
        self.hidden = hidden  # sheets the owner cannot see: never read, only counted
        self.parts: list[str] = []
        self.used = 0
        self.rows = 0
        self.more = False

    def sheet(self, index: int, name: Any, rows: Iterator[Iterable[Any]]) -> None:
        """One sheet. Raises `_Stop` when the time or the characters ran out. A sheet that
        breaks part-way keeps the rows read before it (one bad sheet never sinks the file)."""
        lines = [f"Sheet {index} of {self.sheets}: {_title(name)}"]
        kept, stopped = 0, False
        try:
            for values in rows:
                if self.clock() > self.deadline or self.used > self.limits.max_chars:
                    stopped = True
                    break
                line = _line(values)
                if not line:
                    continue
                if kept == self.limits.max_sheet_rows:
                    lines.append(self._rest(rows))
                    self.more = True
                    break
                lines.append(line)
                kept += 1
                self.used += len(line) + 1
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 — damaged XML in the middle of a sheet
            self.more = True
            lines.append("(the rest of this sheet could not be read)")
        if kept == 0 and len(lines) == 1 and not stopped:
            lines.append("(no values)")
        self.rows += kept
        if kept or not stopped:
            self.parts.append("\n".join(lines))
        if stopped:
            self.more = True
            raise _Stop

    def _rest(self, rows: Iterator[Iterable[Any]]) -> str:
        """How many rows lie past the cap, if they can be counted in a moment."""
        until = min(self.deadline, self.clock() + COUNT_BUDGET_S)
        left = 1  # the row that met the cap
        for values in rows:
            if self.clock() > until:
                return "(more rows were not read)"
            left += 1 if _line(values) else 0
        return f"({left:,} more rows were not read)"

    def done(self, kind: str) -> Extracted:
        if not self.rows:
            if self.more:
                raise too_slow()
            if self.hidden and not self.sheets:
                raise DocumentRejected("no_text", ALL_HIDDEN)
            raise _no_text(kind)
        note = f"\n\n{_hidden_line(self.hidden)}" if self.hidden else ""
        room = dataclasses.replace(self.limits, max_chars=self.limits.max_chars - len(note))
        text, cut = _cap(normalise("\n\n".join(self.parts)), room)
        return Extracted(
            kind=kind,
            text=text + note,
            truncated=self.more or cut,
            sheets=self.sheets,
            rows=self.rows,
        )


# ---- .xlsx / .xlsm ------------------------------------------------------------------------------


def _read_book(book: Any, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    sheets = list(book.worksheets)  # every worksheet listed, in any state: the ONE count
    if len(sheets) > limits.max_sheets:
        raise _too_many(len(sheets), limits.max_sheets)
    shown = [ws for ws in sheets if ws.sheet_state == "visible"]
    reader = _Reader(limits, deadline, clock, len(shown), hidden=len(sheets) - len(shown))
    try:
        for n, ws in enumerate(shown, 1):
            ws.reset_dimensions()  # never trust the file's own "this sheet is 16,384 wide"
            rows = (row[:MAX_ROW_CELLS] for row in ws.iter_rows(values_only=True))
            reader.sheet(n, ws.title, rows)
    except _Stop:
        pass
    return reader.done("xlsx")


def _xlsx(data: bytes, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    office_guard(data, limits, kind="xlsx", folder="xl/")
    import openpyxl  # MIT

    try:
        book = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True, keep_links=False
        )
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001 — malformed XML, missing parts, a damaged zip
        raise _unreadable() from exc
    try:
        return _read_book(book, limits, deadline, clock)
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001
        raise _unreadable() from exc
    finally:
        book.close()


# ---- .xls ---------------------------------------------------------------------------------------


def _xls_value(book: Any, value: Any, ctype: int) -> Any:
    import xlrd

    if ctype == _XL_DATE:
        try:
            return xlrd.xldate_as_datetime(value, book.datemode)
        except Exception:  # noqa: BLE001 — a date serial out of range: show the number
            return value
    if ctype == _XL_BOOL:
        return bool(value)
    if ctype == _XL_ERROR:
        return xlrd.error_text_from_code.get(value, "")
    if ctype == _XL_NUMBER:
        return float(value)
    return value


def _xls_rows(book: Any, sheet: Any) -> Iterator[list[Any]]:
    for r in range(sheet.nrows):
        values = sheet.row_values(r, 0, MAX_ROW_CELLS)
        types = sheet.row_types(r, 0, MAX_ROW_CELLS)
        yield [_xls_value(book, v, t) for v, t in zip(values, types, strict=False)]


def _xls_visible(book: Any) -> list[bool]:
    """Which sheets the owner can see, without loading any: xlrd keeps each sheet's BOUNDSHEET
    flag (0 visible, 1 hidden, 2 very hidden) and has no public reader for it (xlrd 2.0.2, the
    pinned and final release)."""
    flags = book._sheet_visibility  # noqa: SLF001
    if not isinstance(flags, list) or len(flags) != book.nsheets:
        raise ValueError("unexpected sheet list")
    return [flag == 0 for flag in flags]


def _xls(data: bytes, limits: Limits, deadline: float, clock: Clock) -> Extracted:
    import xlrd  # BSD

    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=True, logfile=io.StringIO())
    except MemoryError:
        raise too_complex() from None
    except xlrd.XLRDError as exc:
        if "encrypted" in str(exc).lower():
            words = ENCRYPTED_OFFICE.format(label="Excel", ext=".xlsx")
            raise DocumentRejected("encrypted", words) from None
        if "unsupported format" in str(exc).lower():
            raise _unsupported(XLS_NOT_EXCEL) from None
        raise _unreadable() from exc
    except Exception as exc:  # noqa: BLE001 — anything a damaged or hostile file triggers
        raise _unreadable() from exc
    try:
        if book.nsheets > limits.max_sheets:
            raise _too_many(book.nsheets, limits.max_sheets)
        shown = [i for i, seen in enumerate(_xls_visible(book)) if seen]
        reader = _Reader(limits, deadline, clock, len(shown), hidden=book.nsheets - len(shown))
        try:
            for n, i in enumerate(shown, 1):
                sheet = book.sheet_by_index(i)
                reader.sheet(n, sheet.name, _xls_rows(book, sheet))
                book.unload_sheet(i)
        except _Stop:
            pass
        return reader.done("xls")
    except DocumentRejected:
        raise
    except MemoryError:
        raise too_complex() from None
    except Exception as exc:  # noqa: BLE001
        raise _unreadable() from exc
    finally:
        book.release_resources()


def read_workbook(
    data: bytes, kind: str, limits: Limits, deadline: float, clock: Clock
) -> Extracted:
    return (_xlsx if kind == "xlsx" else _xls)(data, limits, deadline, clock)


__all__ = ["cell_text", "read_workbook"]
