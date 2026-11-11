# tests/test_r11_a_upi.py -- R11 Part A (D7): the prepared payment is an NPCI `upi://pay` intent
# (pa, pn, am with two decimals, cu=INR, tn; spaces as %20 per RFC 3986, never "+"), at most
# ₹1,00,000, and a segno QR of exactly that link as an SVG data URI. Written before upi.py / qr.py.
from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

from jarvis.helpers.today.models import PAY_CAP_PAISE, BillRefused
from jarvis.helpers.today.qr import qr_data_uri
from jarvis.helpers.today.upi import upi_link


def test_the_link_has_npcis_parameters_in_order_and_encoded() -> None:
    link = upi_link(pa="test@okfake", pn="Power & Light Co", paise=124050, tn="Electricity Nov")
    assert link == (
        "upi://pay?pa=test@okfake&pn=Power%20%26%20Light%20Co&am=1240.50&cu=INR"
        "&tn=Electricity%20Nov"
    )
    parts = urlsplit(link)
    assert parts.scheme == "upi" and parts.netloc == "pay"
    got = dict(parse_qsl(parts.query))
    assert got == {
        "pa": "test@okfake",
        "pn": "Power & Light Co",
        "am": "1240.50",
        "cu": "INR",
        "tn": "Electricity Nov",
    }
    assert "+" not in link


def test_notes_are_cut_and_cleaned_and_names_pass_the_payee_check() -> None:
    link = upi_link(pa="test@okfake", pn="N" * 40, paise=100, tn="T‮" * 60)
    got = dict(parse_qsl(urlsplit(link).query))
    assert len(got["pn"]) == 40 and len(got["tn"]) <= 50
    assert "‮" not in unquote(link)
    for bad in ("N" * 41, "Power\nCo‮", "Co (x@okfake)"):
        with pytest.raises(BillRefused):
            upi_link(pa="test@okfake", pn=bad, paise=100, tn="x")


def test_the_cap_and_a_bad_payee_are_refused() -> None:
    assert "am=100000.00" in upi_link(pa="test@okfake", pn="P", paise=PAY_CAP_PAISE, tn="x")
    with pytest.raises(BillRefused, match="1,00,000"):
        upi_link(pa="test@okfake", pn="P", paise=PAY_CAP_PAISE + 1, tn="x")
    with pytest.raises(BillRefused):
        upi_link(pa="test@okfake", pn="P", paise=0, tn="x")
    with pytest.raises(BillRefused):
        upi_link(pa="not a upi id", pn="P", paise=100, tn="x")
    with pytest.raises(BillRefused):
        upi_link(pa="test@okfake", pn="  ", paise=100, tn="x")


def test_the_qr_is_an_svg_data_uri_of_that_link() -> None:
    link = upi_link(pa="test@okfake", pn="Power Co", paise=124000, tn="Electricity")
    uri = qr_data_uri(link)
    assert uri.startswith("data:image/svg+xml;charset=utf-8,")
    svg = unquote(uri.split(",", 1)[1])
    assert svg.startswith("<svg") and "<script" not in svg and "path" in svg
    with pytest.raises(ValueError):
        qr_data_uri("https://example.com/not-upi")
