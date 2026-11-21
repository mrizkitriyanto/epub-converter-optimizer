import time
import xml.etree.ElementTree as ET

from eco.epub.cleanup import drop_empty_blocks, is_empty_document

XHTML = "http://www.w3.org/1999/xhtml"


def xhtml(body: str) -> ET.Element:
    return ET.fromstring(f'<body xmlns="{XHTML}">{body}</body>')


def texts(body: ET.Element) -> list[str]:
    return [text.strip() for text in body.itertext() if text.strip()]


def test_empty_paragraphs_and_break_runs_go():
    body = xhtml(
        "<p>a</p><p>&#160;</p><div style='page-break-after:always'></div><p><br/></p>"
        "<p>b<br/><br/><br/>c</p>"
    )
    assert drop_empty_blocks(body) == 5  # 3 empty blocks and 2 extra breaks
    assert texts(body) == ["a", "b", "c"]
    assert len(body.findall(f".//{{{XHTML}}}br")) == 1


def test_an_empty_anchor_is_kept():
    body = xhtml("<p id='n1'></p><p>t</p>")
    assert drop_empty_blocks(body) == 0


def test_tails_survive():
    body = xhtml("<div>x<p> </p>tail</div>")
    drop_empty_blocks(body)
    assert "".join(body.itertext()) == "xtail"


def test_a_block_with_an_image_is_kept():
    body = xhtml("<p><img src='a.jpg' alt=''/></p><div><span> </span></div>")
    assert drop_empty_blocks(body) == 0


def test_empty_document_detection():
    assert is_empty_document(xhtml("<p>&#160;</p><div></div>"))
    assert not is_empty_document(xhtml("<p><img src='a.jpg' alt=''/></p>"))
    assert not is_empty_document(xhtml("<p>word</p>"))


def test_a_break_with_an_id_is_kept():
    body = xhtml("<p><br id='x'/></p><p>t</p>")
    assert drop_empty_blocks(body) == 0


def test_media_that_is_gone_does_not_count():
    def gone(el):
        return el.get("src") == "gone.svg"

    body = xhtml("<div><img src='gone.svg' alt=''/></div>")
    assert drop_empty_blocks(body, gone) == 1
    assert is_empty_document(xhtml("<p><img src='gone.svg' alt=''/></p>"), gone)
    assert not is_empty_document(xhtml("<p><img src='kept.jpg' alt=''/></p>"), gone)


def test_many_empty_paragraphs_take_linear_time():
    body = xhtml("<p></p>" * 20000 + "<p>t</p>")
    start = time.perf_counter()
    assert drop_empty_blocks(body) == 20000
    assert time.perf_counter() - start < 1
