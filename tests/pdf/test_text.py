import pytest

from eco.book import Block
from eco.pdf.text import (
    clean_heading_artifacts,
    dehyphenate,
    detect_language,
    join_split_paragraphs,
    normalize,
)


def test_normalize_ligatures_nfc_and_space_runs():
    assert normalize("ﬁnal ﬂow ﬀ oﬃce baﬄe") == "final flow ff office baffle"
    assert normalize("é") == "é"
    assert normalize("a   b    c") == "a b c"


def test_normalize_leaves_the_rest_alone():
    assert normalize(" a\tb\n\nc ") == " a\tb\n\nc "


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("Seni iMendengar r Aktif", "Seni Mendengar Aktif"),
        ('Pesan n Singkat: "Bagaimana a kabarmu?"', 'Pesan Singkat: "Bagaimana kabarmu?"'),
        ("1. Sapaan n yang Membuat Nyaman", "1. Sapaan yang Membuat Nyaman"),
        ("2. Ucapan an yang Makin Sering Dipakai", "2. Ucapan yang Makin Sering Dipakai"),
    ],
)
def test_heading_artifacts(raw, clean):
    assert clean_heading_artifacts(raw) == clean


@pytest.mark.parametrize(
    "text,lang",
    [("Pergi ke Kelas", "id"), ("Jadi di Sini", "id"), ("History in India", "en")],
)
def test_heading_artifacts_keep_real_short_words(text, lang):
    assert clean_heading_artifacts(text, lang) == text


def test_heading_artifacts_without_lang_protect_nothing():
    assert clean_heading_artifacts("Pergi ke Kelas") == "Pergi Kelas"


def test_heading_artifacts_leave_numbering_alone():
    assert clean_heading_artifacts("1. Pendahuluan") == "1. Pendahuluan"


def dehyphenated(text, context=""):
    """The text of one paragraph after dehyphenate, with `context` as the rest of the book."""
    out, _ = dehyphenate([Block("paragraph", text), Block("paragraph", context)])
    return out[0].text


@pytest.mark.parametrize(
    "text, context, expected",
    [
        # a reduplication split inside its second half joins (the joined part is a word)
        ("mereka masing-ma-\nsing pulang", "masing-masing", "mereka masing-masing pulang"),
        # an em dash that the PDF parser reads as "-", before a split word
        ("the result-unprece-\ndented gain", "", "the result-unprecedented gain"),
        # a reduplication split at its own hyphen keeps it
        ("para guru-\nguru datang", "guru itu", "para guru-guru datang"),
        ("mereka masing-\nmasing pulang", "masing-masing", "mereka masing-masing pulang"),
        # the spec's example
        ("hujan lebat, seper–\ntinya saya", "sepertinya iya", "hujan lebat, sepertinya saya"),
        # "ated" is no word of its own, so the split joins although "hyphenated" is nowhere else
        ("a hyphen-\nated word", "one hyphen", "a hyphenated word"),
        # both parts are words and the joined word is nowhere else: the hyphen stays
        ("the end-of-\nseason sale", "the end of the season", "the end-of-season sale"),
        ("a some-\nthing", "some thing", "a some-thing"),
        ("a some-\nthing", "some thing, something", "a something"),
        # a digit on either side, or a word that holds "/" or ".", keeps its hyphen
        ("see example.org/a-\nb today", "ab", "see example.org/a-b today"),
        ("at /srv/data-\nset now", "dataset", "at /srv/data-set now"),
        ("a 512-\nbyte page", "512byte", "a 512-byte page"),
        ("Figure 4-\n2 shows", "", "Figure 4-2 shows"),
        ("model x-\n9 runs", "x9", "model x-9 runs"),
        # a capital after the break joins only when the joined word is elsewhere
        ("run Olly-\nDbg now", "OllyDbg", "run OllyDbg now"),
        ("run Hex-\nRays now", "", "run Hex-Rays now"),
        # the fragments at the split are no words of their own
        ("the infor-\nmation", "", "the information"),
        # OCR can read a hyphen at a line end as an em dash; a real em dash keeps its place
        ("seperti se—\nkarang", "sekarang", "seperti sekarang"),
        ("to spend—\nthis is", "spend this", "to spend—this is"),
        # an em dash joins only on a joined word the book has: a word seen once is no fragment
        ("the result—\nunprecedented gain", "", "the result—unprecedented gain"),
        # a line break that the reading order merge left with a space after it
        ("para guru-\n guru datang", "guru itu", "para guru-guru datang"),
        # a word split over three lines
        ("a mul-\nti-\nline", "", "a multiline"),
    ],
)
def test_a_line_end_hyphen_follows_the_spec_rule(text, context, expected):
    assert dehyphenated(text, context) == expected


def test_a_hyphen_inside_a_line_is_left_alone():
    text = "-rw-rw-rw- 1 root, first- and second-order, guru- guru"
    assert dehyphenated(text, "guruguru") == text


def test_the_prose_of_every_block_is_dehyphenated_with_the_vocabulary_of_the_whole_book():
    table = (
        "<table><tr><td>a hyphen- ated cell</td><td>password- protected</td>"
        "<td>see 512- byte</td></tr></table>"
    )
    blocks = [
        Block("heading", "A hyphen-\nated head"),
        Block("list_item", "a hyphen-\nated item"),
        Block("footnote", "a hyphen-\nated note"),
        Block("image", image="images/a.png", caption="a hyphen-\nated caption"),
        Block("table", html=table),
        Block("code", "x = hyphen-\nated"),
        Block("paragraph", "some-\nthing about a password, protected"),
        Block("heading", "Something"),
    ]
    out, joins = dehyphenate(blocks)
    assert [b.text for b in out[:3]] == [
        "A hyphenated head",
        "a hyphenated item",
        "a hyphenated note",
    ]
    assert out[3].caption == "a hyphenated caption"
    assert out[4].html == (
        "<table><tr><td>a hyphenated cell</td><td>password-protected</td>"
        "<td>see 512-byte</td></tr></table>"  # a digit keeps the hyphen
    )
    assert out[5] == blocks[5]
    assert out[6].text == "something about a password, protected"
    assert joins == 6


def test_the_text_of_a_formula_or_an_image_is_no_prose_and_stays_as_it_is():
    blocks = [
        Block("formula", "y = b-\nc"),
        Block("image", "x = a-\nb", image="images/c.png", caption="a hyphen-\nated caption"),
    ]
    out, joins = dehyphenate(blocks)
    assert [b.text for b in out] == ["y = b-\nc", "x = a-\nb"]
    assert out[1].caption == "a hyphenated caption"
    assert joins == 1


def test_dehyphenate_does_not_mutate_its_input():
    para = Block("paragraph", "seper-\ntinya", page=3)
    out, joins = dehyphenate([para])
    assert (out[0].text, out[0].page, joins) == ("sepertinya", 3, 1)
    assert para.text == "seper-\ntinya"


def test_language():
    assert detect_language("Ini adalah buku yang sangat bagus dan menarik untuk dibaca") == "id"
    assert detect_language("This is the book that we read for the class") == "en"


def test_language_empty_and_tie_give_en():
    assert detect_language("") == "en"
    assert detect_language("yang the") == "en"


@pytest.mark.parametrize(
    "text, lang", [("Why I Invest", "en"), ("Here I am", "en"), ("Menjadi Si Sibuk", "id")]
)
def test_real_short_words_in_headings_are_not_removed(text, lang):
    assert clean_heading_artifacts(text, lang) == text


def test_join_split_paragraphs_merges_lowercase_continuation():
    blocks = [
        Block("paragraph", "Kalimat ini belum selesai", page=1),
        Block("paragraph", "dan lanjut di sini.", page=2),
        Block("paragraph", "Baru."),
    ]
    out = join_split_paragraphs(blocks)
    assert [b.text for b in out] == ["Kalimat ini belum selesai dan lanjut di sini.", "Baru."]
    assert out[0].page == 1
    assert len(blocks) == 3 and blocks[0].text == "Kalimat ini belum selesai"


def test_join_split_paragraphs_merges_three_pages():
    blocks = [Block("paragraph", "satu"), Block("paragraph", "dua"), Block("paragraph", "tiga.")]
    assert [b.text for b in join_split_paragraphs(blocks)] == ["satu dua tiga."]


@pytest.mark.parametrize("end", [".", "!", "?", ":", ";", '"', "”", ")"])
def test_join_split_paragraphs_stops_at_sentence_end(end):
    blocks = [Block("paragraph", "Selesai" + end), Block("paragraph", "lanjut")]
    assert len(join_split_paragraphs(blocks)) == 2


def test_join_split_paragraphs_needs_lowercase_start_and_two_paragraphs():
    assert len(join_split_paragraphs([Block("paragraph", "a"), Block("paragraph", "Besar")])) == 2
    assert len(join_split_paragraphs([Block("paragraph", "a"), Block("heading", "kecil")])) == 2
    assert len(join_split_paragraphs([Block("list_item", "a"), Block("paragraph", "kecil")])) == 2


def test_join_split_paragraphs_keeps_the_line_break_after_a_hyphen_for_dehyphenate():
    blocks = [Block("paragraph", "para guru-", page=1), Block("paragraph", "guru datang.", page=2)]
    assert [b.text for b in join_split_paragraphs(blocks)] == ["para guru-\nguru datang."]


def test_join_split_paragraphs_keeps_the_line_break_after_an_em_dash_too():
    blocks = [Block("paragraph", "seperti se\u2014", page=1), Block("paragraph", "karang.", page=2)]
    assert [b.text for b in join_split_paragraphs(blocks)] == ["seperti se\u2014\nkarang."]
