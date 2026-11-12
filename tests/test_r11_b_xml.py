# tests/test_r11_b_xml.py -- R11 Part B, security review M1 (docs/plans/r11-free-helpers.md D13):
# outside XML (SACHET's CAP and RSS) in two layers. (a) the bytes: strict UTF-8 only, no NUL, no
# BOM but UTF-8's, no declared other encoding, no `<!DOCTYPE` / `<!ENTITY` in the text; (b) the
# parser: stdlib expat with every DTD handler (DOCTYPE, entity declaration, external and unparsed
# entity, notation) raising, so a DTD is refused by the parser itself, not only by the text check.
# The reviewer's BOM-less UTF-16 sample (accepted before, its entity expanded) is refused.
from __future__ import annotations

import codecs

import pytest
from r11_fakes_b import fixture

from jarvis.helpers.house import cap, sachet, xmlsafe
from jarvis.helpers.sources import MAX_CAP_BYTES

DTD = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "PWNED">]><a>&x;</a>'
NS = "urn:oasis:names:tc:emergency:cap:1.2"
CAP_DTD = (
    f'<?xml version="1.0"?><!DOCTYPE alert [<!ENTITY ev "Landslide">]><alert xmlns="{NS}">'
    "<identifier>x1</identifier><status>Actual</status><msgType>Alert</msgType>"
    "<scope>Public</scope><info><category>Geo</category><event>&ev;</event></info></alert>"
)


def _refused(raw: bytes) -> None:
    with pytest.raises(xmlsafe.UnsafeXml):
        xmlsafe.parse_xml(raw, limit=MAX_CAP_BYTES)


def test_the_reviewers_bomless_utf16_samples_are_refused() -> None:
    for codec in ("utf-16-le", "utf-16-be"):
        _refused(DTD.encode(codec))
        _refused(DTD.split("?>", 1)[1].encode(codec))  # no declaration either
        with pytest.raises(ValueError):
            cap.parse_cap(CAP_DTD.encode(codec))  # was parsed to "Landslide" before


def test_utf16_and_utf32_with_a_bom_and_any_nul_are_refused() -> None:
    plain = '<?xml version="1.0"?><a>ok</a>'
    for codec in ("utf-16", "utf-32", "utf-32-le", "utf-32-be"):
        _refused(plain.encode(codec))
    for bom in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE, codecs.BOM_UTF32_BE):
        _refused(bom + b"<a>ok</a>")
    _refused(b"<a>o\x00k</a>")


def test_only_strict_utf8_and_a_utf8_declaration() -> None:
    _refused(b"<a>\xff</a>")  # not UTF-8
    _refused(b"<a>\xed\xa0\x80</a>")  # a UTF-8-encoded surrogate: not strict UTF-8
    for decl in ("ISO-8859-1", "utf-16", "us-ascii", "UTF 8", "utf-7"):
        _refused(f'<?xml version="1.0" encoding="{decl}"?><a/>'.encode())
    _refused(b"<?xml version='1.0' encoding=utf-16?><a/>")  # unquoted: not readable, refused
    for ok in (b'<?xml version="1.0" encoding="UTF-8"?><a/>', b"\xef\xbb\xbf<a/>", b"<a/>"):
        assert xmlsafe.parse_xml(ok, limit=100).tag == "a"


def test_entity_expansion_is_refused_in_utf8_and_by_the_parser_itself() -> None:
    _refused(DTD.encode())
    _refused(b'<a><!eNtItY x "y"></a>')
    # layer (b) alone, the text check skipped: the parser refuses the DTD itself
    for text in (DTD, '<!DOCTYPE a SYSTEM "file:///etc/hostname"><a/>', "<!DOCTYPE a><a/>"):
        with pytest.raises(xmlsafe.UnsafeXml):
            xmlsafe.expat_tree(text)


def test_every_dtd_handler_of_the_parser_raises() -> None:
    parser = xmlsafe.make_parser(xmlsafe.Builder())
    handlers = (
        parser.StartDoctypeDeclHandler,
        parser.EntityDeclHandler,
        parser.UnparsedEntityDeclHandler,
        parser.ExternalEntityRefHandler,
        parser.NotationDeclHandler,
    )
    for handler in handlers:
        with pytest.raises(xmlsafe.UnsafeXml):
            handler("a", "b", "c", "d", "e", "f", "g")  # type: ignore[call-arg]


def test_a_normal_utf8_cap_and_the_rss_still_parse_with_their_namespaces() -> None:
    root = xmlsafe.parse_xml(fixture("b_cap_geo_landslide.xml"), limit=MAX_CAP_BYTES)
    assert root.tag == f"{{{NS}}}alert"
    a = cap.parse_cap(fixture("b_cap_geo_landslide.xml"))
    assert a.info is not None and a.info.event == "Landslide"
    assert a.info.headline.startswith("Landslide warning")
    items = sachet.parse_rss(fixture("b_sachet_rss.xml"))
    assert len(items) == 5 and items[0].guid == "1794300000000101"
    assert xmlsafe.parse_xml(b"<a x='1'>&amp;&#x41;<b/>t</a>", limit=100).text == "&A"


def test_size_and_element_count_are_bounded() -> None:
    _refused(b"")
    with pytest.raises(xmlsafe.UnsafeXml):
        xmlsafe.parse_xml(b"<a>" + b"x" * 200 + b"</a>", limit=100)
    with pytest.raises(xmlsafe.UnsafeXml):
        xmlsafe.parse_xml(b"<a>" * 6000 + b"</a>" * 6000, limit=MAX_CAP_BYTES)
    with pytest.raises(xmlsafe.UnsafeXml):
        xmlsafe.parse_xml(b"<a><b></a>", limit=100)  # broken
    assert cap.UnsafeXml is xmlsafe.UnsafeXml and cap.parse_xml is xmlsafe.parse_xml
