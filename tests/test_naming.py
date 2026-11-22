import pytest
from fixtures.make import book_epub

from eco.naming import MAX_NAME, BookFacts, facts_from_epub, library_name
from eco.pdf.text import sure_language

ID_TEXT = "yang dan di ini itu dengan untuk tidak dari dalam " * 5
EN_TEXT = "the and of to is in that for with it " * 5


def facts(title, authors=(), language="", text=ID_TEXT):
    return BookFacts(title, list(authors), language, text)


def test_sure_language_says_nothing_without_enough_stopwords():
    assert sure_language(ID_TEXT) == "id"
    assert sure_language(EN_TEXT) == "en"
    assert sure_language("猫 " * 100) is None
    assert sure_language("the and of") is None


def test_language_comes_from_the_text_not_the_metadata():
    assert library_name(facts("Never Split the Difference", ["Chris Voss"], "en")) == (
        "ID - Never Split the Difference - Chris Voss"
    )
    assert library_name(facts("Deep Work", ["Cal Newport"], "id", EN_TEXT)) == (
        "EN - Deep Work - Cal Newport"
    )


def test_unknown_text_uses_the_metadata_language_then_nothing():
    assert library_name(facts("Kokoro", ["Natsume Soseki"], "ja-JP", "猫")) == (
        "JA - Kokoro - Natsume Soseki"
    )
    assert library_name(facts("Kokoro", ["Natsume Soseki"], "", "猫")) == "Kokoro - Natsume Soseki"


def test_last_first_is_turned_round():
    assert library_name(facts("The 7 Habits", ["Covey, Stephen"], text=EN_TEXT)) == (
        "EN - The 7 Habits - Stephen Covey"
    )


def test_several_authors_give_the_first_and_a_marker_in_the_book_language():
    many = "Chad Maurice, Jeremy Thompson and William Copeland"
    assert library_name(facts("Threat Hunting", [many], text=EN_TEXT)) == (
        "EN - Threat Hunting - Chad Maurice et al."
    )
    assert library_name(facts("Buku", ["Ani", "Budi"])) == "ID - Buku - Ani dkk."


def test_a_title_ending_in_a_name_gives_the_author_when_there_is_none():
    assert library_name(facts("Bicara itu ada seninya - Oh Su Hyang")) == (
        "ID - Bicara itu ada seninya - Oh Su Hyang"
    )
    assert library_name(facts("Catatan - jilid dua")) == "ID - Catatan - jilid dua"


def test_no_author_leaves_the_part_out():
    assert library_name(facts("Atomic Habits")) == "ID - Atomic Habits"


def test_windows_forbidden_characters():
    assert library_name(facts('Atomic Habits: Perubahan "Kecil"? a/b', ["James Clear"])) == (
        "ID - Atomic Habits - Perubahan Kecil ab - James Clear"
    )


@pytest.mark.parametrize("title", [":?*", "   ", "...", ""])
def test_no_title_left_gives_no_name(title):
    assert library_name(facts(title, ["X"])) is None


def test_reserved_name_and_trailing_dots():
    assert library_name(facts("CON", text="猫")) == "CON_"
    assert library_name(facts("nul", text="猫")) == "nul_"
    assert library_name(facts("Title...", text="猫")) == "Title"


def test_long_names_are_cut_at_a_word():
    name = library_name(facts("word " * 60, ["Ani"]))
    assert len(name) <= MAX_NAME and name.startswith("ID - word") and name.endswith(" - Ani")
    assert "  " not in name and not name.endswith(" - - Ani")


def test_facts_from_epub(tmp_path):
    epub = book_epub(
        tmp_path / "b.epub",
        "Never Split the Difference",
        ["Chris Voss", "Tahl Raz"],
        "en",
        ["<p>Aku telah <b>meng</b>habiskan</p>", "<p>dua dekade</p>"],
    )
    got = facts_from_epub(epub)
    assert (got.title, got.authors, got.language) == (
        "Never Split the Difference",
        ["Chris Voss", "Tahl Raz"],
        "en",
    )
    assert "Aku telah menghabiskan" in got.text and "dua dekade" in got.text
