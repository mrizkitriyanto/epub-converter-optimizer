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


def test_dehyphenate_uses_book_vocabulary():
    blocks = [
        Block("paragraph", "Hari ini hujan lebat, seper– tinya saya juga."),
        Block("paragraph", "sepertinya iya, user- created"),
    ]
    out, n = dehyphenate(blocks)
    assert out[0].text == "Hari ini hujan lebat, sepertinya saya juga."
    assert "user-created" in out[1].text
    assert n == 1


def test_dehyphenate_keeps_other_blocks_and_does_not_mutate():
    para = Block("paragraph", "seper- tinya", page=3)
    code = Block("code", "a- b")
    out, n = dehyphenate([para, code, Block("paragraph", "sepertinya")])
    assert (out[0].text, out[0].page, out[1], n) == ("sepertinya", 3, code, 1)
    assert para.text == "seper- tinya"


def test_dehyphenate_skips_uppercase_second_word():
    out, n = dehyphenate([Block("paragraph", "Jawa- Barat Jawabarat")])
    assert (out[0].text, n) == ("Jawa- Barat Jawabarat", 0)


def test_language():
    assert detect_language("Ini adalah buku yang sangat bagus dan menarik untuk dibaca") == "id"
    assert detect_language("This is the book that we read for the class") == "en"


def test_language_empty_and_tie_give_en():
    assert detect_language("") == "en"
    assert detect_language("yang the") == "en"


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
