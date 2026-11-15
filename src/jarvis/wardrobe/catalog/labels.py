# src/jarvis/wardrobe/catalog/labels.py
"""QR labels for identical copies (docs/plans/r13-wardrobe.md D7, INV-07; plan review L5, M5).

A label is a number and 8 characters of lower-case base32; its QR's payload is exactly
`jw1:<code>`. His code for number N is a keyed hash of (his id, N) (`code_for`), so printing a
sheet writes nothing (`GET labels.svg` only draws) and nobody can guess his codes; a label enters
his sealed index when he sticks it on a piece (`assign`). A read code counts only when it is that
AND one of HIS assigned labels (`resolve`); any other code on a clothing tag is "not a JARVIS
label": never sent, opened or shown. The sheet (`svg`) is 24 labels a page, numbers and QR codes
only (no text of his), drawn
with segno (BSD-3-Clause, already vendored for R11's UPI QR) as plain SVG paths: no script, no
link, no outside reference; the route serves it with `default-src 'none'`, `nosniff` and as an
attachment. A piece has at most one label; giving its code to another piece frees the first.
"""

from __future__ import annotations

from collections.abc import Sequence
from xml.sax.saxutils import escape

import segno

from jarvis.storage.docs import DocTx
from jarvis.wardrobe.catalog.store import NOT_IN, CatalogStore
from jarvis.wardrobe.model import WardrobeLabel, WardrobeView, label_code_of
from jarvis.wardrobe.ports import Commit, Refused

PER_SHEET = 24
MAX_LABELS = 600
COLUMNS, ROWS = 4, 6
CELL_W, CELL_H, QR_SIDE = 50, 46, 34  # millimetres on an A4 page (210 x 297)
NOT_HIS = "That isn't one of your JARVIS labels."
_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def resolve(view: WardrobeView, payload: object) -> str | None:
    """The piece a read QR names, or None ("not a JARVIS label", or not one of his)."""
    code = label_code_of(payload) if isinstance(payload, str) else None
    found = view.labels.get(code) if code is not None else None
    return found.piece if found is not None else None


def _qr_path(payload: str, x0: float, y0: float) -> str:
    code = segno.make(payload, error="m", micro=False)
    size = len(code.matrix)
    unit = QR_SIDE / size
    runs: list[str] = []
    for y, row in enumerate(code.matrix):
        for x, dark in enumerate(row):
            if dark:
                runs.append(
                    f"M{x0 + x * unit:.2f} {y0 + y * unit:.2f}h{unit:.2f}v{unit:.2f}h-{unit:.2f}z"
                )
    return "".join(runs)


def svg(labels: Sequence[WardrobeLabel]) -> str:
    """One A4 page of up to 24 labels: each QR and its number, nothing else."""
    cells: list[str] = []
    for i, lb in enumerate(labels[:PER_SHEET]):
        cx, cy = 5 + (i % COLUMNS) * CELL_W, 9 + (i // COLUMNS) * CELL_H
        path = _qr_path(f"jw1:{lb.code}", cx + 8, cy)
        cells.append(f'<path d="{path}" fill="#000"/>')
        number = escape(f"No. {int(lb.number)}")
        cells.append(
            f'<text x="{cx + 25}" y="{cy + QR_SIDE + 6}" font-size="5" text-anchor="middle"'
            f' font-family="monospace">{number}</text>'
        )
    head = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm"'
        ' viewBox="0 0 210 297"><rect width="210" height="297" fill="#fff"/>'
    )
    return head + "".join(cells) + "</svg>"


class Labels:
    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    resolve = staticmethod(resolve)

    def code_for(self, uid: str, number: int) -> str:
        digest = bytes.fromhex(self.store.sealer.mac(f"label/{uid}/{number}"))
        return "".join(_B32[b % 32] for b in digest[:8])

    def number_of(self, uid: str, code: str) -> int | None:
        return next((n for n in range(1, MAX_LABELS + 1) if self.code_for(uid, n) == code), None)

    async def sheet(self, uid: str, page: int = 1) -> tuple[WardrobeLabel, ...]:
        """Page `page` of his labels (24 a page), each with the piece it is on, if any."""
        if not 1 <= page <= MAX_LABELS // PER_SHEET:
            raise Refused(f"There are {MAX_LABELS // PER_SHEET} sheets of labels.")
        view = await self.store.view(uid)
        out = []
        for n in range((page - 1) * PER_SHEET + 1, page * PER_SHEET + 1):
            code = self.code_for(uid, n)
            piece = view.labels[code].piece if code in view.labels else None
            out.append(WardrobeLabel.model_validate({"code": code, "number": n, "piece": piece}))
        return tuple(out)

    async def assign(self, uid: str, code: str, pid: str | None) -> WardrobeLabel:
        out: list[WardrobeLabel] = []

        number = self.number_of(uid, code)
        if number is None:
            raise Refused(NOT_HIS)

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            lb = view.labels.get(code) or WardrobeLabel.model_validate(
                {"code": code, "number": number}
            )
            recs = []
            if pid is not None:
                p = view.piece(pid)
                if p is None or p.merged_into is not None:
                    raise Refused(NOT_IN)
                recs.append(p.model_copy(update={"label_code": code}))
            if lb.piece is not None and lb.piece != pid and lb.piece in view.pieces:
                recs.append(view.pieces[lb.piece].model_copy(update={"label_code": None}))
            out[:] = [lb.model_copy(update={"piece": pid})]
            return Commit(records=tuple(recs))

        def relabel(fresh: WardrobeView) -> WardrobeView:
            labels = {k: (v.model_copy(update={"piece": None}) if pid and v.piece == pid else v)
                      for k, v in fresh.labels.items()}  # fmt: skip
            return fresh.model_copy(update={"labels": {**labels, code: out[0]}})

        await self.store.transact(uid, fn, index=relabel)
        return out[0]


__all__ = ["MAX_LABELS", "NOT_HIS", "PER_SHEET", "Labels", "resolve", "svg"]
