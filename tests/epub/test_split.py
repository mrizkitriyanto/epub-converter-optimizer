import xml.etree.ElementTree as ET

from eco.epub.split import pack, split_document

H = "http://www.w3.org/1999/xhtml"


def tree(body: str) -> ET.Element:
    return ET.fromstring(
        f'<html xmlns="{H}"><head><title>t</title></head><body>{body}</body></html>'
    )


def paragraphs(first: int, count: int, size: int = 2000) -> str:
    return "".join(f'<p id="p{n}">{n} {"x" * size}</p>' for n in range(first, first + count))


def ids(parts: list[ET.Element], tag: str = "p") -> list[str]:
    return [el.get("id") for part in parts for el in part.iter(f"{{{H}}}{tag}")]


def size(part: ET.Element) -> int:
    return len(ET.tostring(part, encoding="utf-8"))


def first_block(part: ET.Element) -> ET.Element:
    node = part.find(f"{{{H}}}body")
    while node[0].tag.endswith(("}div", "}section")):
        node = node[0]
    return node[0]


def test_a_big_wrapper_beside_a_small_one_is_opened():
    # the shape of an InDesign export: the whole chapter in one container, an empty one after it
    body = (
        f'<div class="outer"><div id="big" class="c">{paragraphs(0, 69)}</div>'
        '<div id="tail" class="c"/></div>'
    )
    parts = split_document(tree(body), 30_000)
    assert len(parts) >= 5 and all(size(part) <= 31_000 for part in parts)
    assert ids(parts) == [f"p{n}" for n in range(69)]  # nothing lost, nothing doubled, in order
    shells = [div for part in parts for div in part.iter(f"{{{H}}}div") if div.get("class") == "c"]
    assert [div.get("id") for div in shells].count("big") == 1  # the id stays unique
    assert ids(parts, "div").count("tail") == 1


def test_a_wrapper_with_loose_text_between_its_children_is_not_opened():
    body = f'<div class="outer"><div id="big">{paragraphs(0, 30)}loose text</div><p>end</p></div>'
    parts = split_document(tree(body), 30_000)
    assert len(parts) == 2 and size(parts[0]) > 30_000
    assert "loose text" in ET.tostring(parts[0], encoding="unicode")


def test_a_part_starts_at_a_heading_rather_than_in_the_middle_of_a_section():
    body = paragraphs(0, 10) + '<h2 id="mid">Mid</h2>' + paragraphs(10, 10)
    parts = split_document(tree(body), 30_000)
    assert first_block(parts[1]).get("id") == "mid"
    assert ids(parts) == [f"p{n}" for n in range(20)]


def test_a_heading_in_a_section_counts_as_the_start_of_a_part():
    body = paragraphs(0, 10) + f'<section><h2 id="mid">Mid</h2>{paragraphs(10, 5)}</section>'
    parts = split_document(tree(body), 30_000)
    assert first_block(parts[1]).get("id") == "mid"


def test_pack_moves_the_cut_back_to_the_last_heading_when_half_the_room_stays():
    assert pack([10] * 8, 50, {3}) == [[0, 1, 2], [3, 4, 5, 6, 7]]
    assert pack([10] * 8, 50, {1}) == [[0, 1, 2, 3, 4], [5, 6, 7]]  # 10 < 25 would stay
    assert pack([10] * 8, 50, set()) == [[0, 1, 2, 3, 4], [5, 6, 7]]
    assert pack([10, 60, 10], 50, set()) == [[0], [1], [2]]  # too big for any part: alone


def test_pack_never_moves_a_heading_into_a_part_it_would_overflow():
    assert pack([20, 20, 5, 25, 45], 70, {2}) == [[0, 1, 2, 3], [4]]
