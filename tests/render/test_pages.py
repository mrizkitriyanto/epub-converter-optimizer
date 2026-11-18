import json
from io import BytesIO

import pytest
from PIL import Image

import eco.render.pages as pages_module
from eco.bookfolder import load_source
from eco.options import Options, image_profile
from eco.render.md2typst import RenderSettings
from eco.render.pages import Rendered, render_book, render_chapter


def book(tmp_path, markdown):
    md = tmp_path / "b.md"
    md.write_text(markdown, encoding="utf-8")
    return load_source(md)


def render(src, **kw):
    kw.setdefault("device", "x4")
    kw.setdefault("settings", RenderSettings())
    kw.setdefault("view", "crosspoint")
    return render_book(src, **kw)


def test_render_sizes_and_map(small_book):
    r = render_book(
        load_source(small_book), device="x3", settings=RenderSettings(), view="crosspoint"
    )
    im = Image.open(BytesIO(r.pages[0]))
    assert im.size == (528, 792) and im.mode == "L"
    assert len(r.page_map) == len(r.pages) and r.chapters[0][1] == 0


def test_long_code_line_stays_inside_page(tmp_path):
    md = tmp_path / "c.md"
    md.write_text("# C\n\n```\n" + "x" * 160 + "\n```\n")
    im = Image.open(
        BytesIO(
            render_book(
                load_source(md), device="x4", settings=RenderSettings(), view="crosspoint"
            ).pages[0]
        )
    )
    assert all(im.getpixel((479 - dx, y)) > 200 for dx in range(8) for y in range(0, 800, 4))


def test_chapter_excerpt_matches_full_render(small_book):
    src, st = load_source(small_book), RenderSettings(status_bar=False)
    full = render_book(src, device="x4", settings=st, view="crosspoint")
    part, idx = render_chapter(
        src, device="x4", settings=st, view="crosspoint", source_page=full.page_map[-1]
    )
    assert part.pages[idx] == full.pages[-1]


def test_page_map_and_chapters_follow_the_markers(small_book):
    r = render(load_source(small_book))
    assert len(r.pages) == 2
    # Source page 2 starts on the first page of chapter "Two", not at the end of "One".
    assert r.page_map == [1, 3]
    assert r.chapters == [("One", 0), ("Two", 1)]


def test_pages_without_a_marker_carry_the_previous_source_page(tmp_path):
    long = "\n\n".join(f"Paragraph number {n} with a few words." for n in range(40))
    src = book(tmp_path, f"<!-- page: 4 -->\n\n# One\n\n{long}\n\n# Two\n\nshort\n")
    r = render(src)
    assert len(r.pages) > 3
    assert set(r.page_map) == {4}


def test_pages_before_the_first_marker_are_unknown(tmp_path):
    r = render(book(tmp_path, "intro\n\n# One\n\ntext\n\n<!-- page: 3 -->\n\nmore\n"))
    assert r.page_map == [0, 3]


def test_single_page_document_is_one_grayscale_page(tmp_path):
    r = render(book(tmp_path, "# Only\n\nOne short page.\n"))
    assert len(r.pages) == 1
    assert Image.open(BytesIO(r.pages[0])).mode == "L"
    assert r.chapters == [("Only", 0)]


def test_renders_with_and_without_an_image_profile(small_book):
    src = load_source(small_book)
    plain = render(src)
    profiled = render(src, image_profile=image_profile(Options(device="x4", size="small")))
    assert len(plain.pages) == len(profiled.pages) == 2
    assert plain.page_map == profiled.page_map


def test_chapter_excerpt_holds_one_chapter(small_book):
    src = load_source(small_book)
    part, idx = render_chapter(
        src, device="x4", settings=RenderSettings(), view="crosspoint", source_page=1
    )
    assert len(part.pages) == 1 and idx == 0
    assert part.chapters == [("One", 0)]
    part, idx = render_chapter(
        src, device="x4", settings=RenderSettings(), view="crosspoint", source_page=3
    )
    assert part.chapters == [("Two", 0)] and part.page_map == [3] and idx == 0


def test_chapter_excerpt_without_a_marker_below_the_page_uses_the_first_chapter(tmp_path):
    src = book(tmp_path, "# One\n\ntext\n\n<!-- page: 5 -->\n\n# Two\n\nmore\n")
    part, _ = render_chapter(
        src, device="x4", settings=RenderSettings(), view="crosspoint", source_page=2
    )
    assert part.chapters == [("One", 0)]


def test_chapter_excerpt_matches_inside_a_book_with_pictures_and_profile(small_book):
    src, st = load_source(small_book), RenderSettings(status_bar=False)
    profile = image_profile(Options(device="x4", size="small"))
    full = render_book(src, device="x4", settings=st, view="crosspoint", image_profile=profile)
    part, idx = render_chapter(
        src,
        device="x4",
        settings=st,
        view="crosspoint",
        source_page=1,
        image_profile=profile,
    )
    assert part.pages[idx] == full.pages[0]


def test_chapter_excerpt_matches_when_footnotes_are_numbered_across_chapters(tmp_path):
    src = book(
        tmp_path,
        "# One\n\nText[^1].\n\n<!-- page: 2 -->\n\n# Two\n\nMore[^2].\n\n[^1]: First.\n\n[^2]: Second.\n",
    )
    st = RenderSettings(status_bar=False)
    full = render_book(src, device="x4", settings=st, view="crosspoint")
    part, idx = render_chapter(src, device="x4", settings=st, view="crosspoint", source_page=2)
    assert part.pages[idx] == full.pages[-1]
    first, idx = render_chapter(src, device="x4", settings=st, view="crosspoint", source_page=1)
    assert first.pages[idx] == full.pages[0]


def test_excerpt_with_the_status_bar_compiles(small_book):
    part, _ = render_chapter(
        load_source(small_book),
        device="x4",
        settings=RenderSettings(),
        view="crosspoint",
        source_page=3,
    )
    assert part.chapters == [("Two", 0)]


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = pages_module.typst.compile

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(pages_module.typst, "compile", spy)
    return calls


def test_cache_is_written_and_reused_without_compiling(tmp_path, small_book, counted):
    cache = tmp_path / "cache"
    src = load_source(small_book)
    first = render(src, cache_dir=cache)
    assert counted == [1]
    assert sorted(p.name for p in cache.glob("*.png")) == ["0001.png", "0002.png"]
    assert json.loads((cache / "map.json").read_text())["page_map"] == first.page_map
    again = render(src, cache_dir=cache)
    assert counted == [1]
    assert again == first and isinstance(again, Rendered)


def test_cache_without_map_json_is_not_reused(tmp_path, small_book, counted):
    cache = tmp_path / "cache"
    src = load_source(small_book)
    render(src, cache_dir=cache)
    (cache / "map.json").unlink()
    render(src, cache_dir=cache)
    assert counted == [1, 1]
    assert (cache / "map.json").is_file()


def test_cache_with_a_missing_page_is_not_reused(tmp_path, small_book, counted):
    cache = tmp_path / "cache"
    src = load_source(small_book)
    render(src, cache_dir=cache)
    (cache / "0002.png").unlink()
    r = render(src, cache_dir=cache)
    assert counted == [1, 1] and len(r.pages) == 2


def test_cache_with_a_damaged_map_is_not_reused(tmp_path, small_book, counted):
    cache = tmp_path / "cache"
    src = load_source(small_book)
    render(src, cache_dir=cache)
    (cache / "map.json").write_text("{not json")
    render(src, cache_dir=cache)
    assert counted == [1, 1]


def test_a_cache_whose_folder_is_gone_is_not_made_again(tmp_path, small_book):
    # the web GUI keeps a cache inside a job's folder, which may be deleted during a render
    gone = tmp_path / "job"
    with pytest.raises(FileNotFoundError):
        render(load_source(small_book), cache_dir=gone / "preview")
    assert not gone.exists()
    files = {"images/a.png": b"png", "main.typ": b"x"}  # the cache folder went after it was made
    with pytest.raises(FileNotFoundError):
        pages_module._compile(files, gone / "preview")
    assert not gone.exists()


def test_rerender_drops_pages_left_by_a_longer_book(tmp_path, small_book):
    cache = tmp_path / "cache"
    (cache).mkdir()
    (cache / "0009.png").write_bytes(b"stale")
    render(load_source(small_book), cache_dir=cache)
    assert sorted(p.name for p in cache.glob("*.png")) == ["0001.png", "0002.png"]


# Chapters by index, and the cache read without its pages


def chapter_of(src, chapter, **kw):
    kw.setdefault("settings", RenderSettings(status_bar=False))
    return render_chapter(src, device="x4", view="crosspoint", chapter=chapter, **kw)


def test_chapter_by_index_is_laid_out_as_in_the_book(small_book):
    src, st = load_source(small_book), RenderSettings(status_bar=False)
    full = render_book(src, device="x4", settings=st, view="crosspoint")
    (first, i), (second, j) = chapter_of(src, 0), chapter_of(src, 1)
    assert (i, j) == (0, 0)  # the first page of the chapter
    assert (first.chapters, second.chapters) == ([("One", 0)], [("Two", 0)])
    assert first.pages[0] == full.pages[0] and second.pages[0] == full.pages[1]


@pytest.mark.parametrize("chapter", [2, 99, -1])
def test_a_chapter_that_the_book_does_not_have_is_an_error(small_book, chapter):
    with pytest.raises(pages_module.ChapterNotFound):
        chapter_of(load_source(small_book), chapter)


def test_text_before_the_first_heading_is_not_a_chapter(tmp_path):
    src = book(tmp_path, "Intro.\n\n# One\n\ntext\n\n# Two\n\nmore\n")
    assert chapter_of(src, 0)[0].chapters == [("One", 0)]
    assert chapter_of(src, 1)[0].chapters == [("Two", 0)]
    with pytest.raises(pages_module.ChapterNotFound):
        chapter_of(src, 2)


def test_a_book_without_a_heading_is_one_chapter(tmp_path):
    src = book(tmp_path, "Just text.\n\nMore text.\n")
    part, index = chapter_of(src, 0)
    assert (part.chapters, len(part.pages), index) == ([], 1, 0)
    with pytest.raises(pages_module.ChapterNotFound):
        chapter_of(src, 1)


@pytest.mark.parametrize("kw", [{}, {"source_page": 1, "chapter": 0}])
def test_a_chapter_is_asked_for_by_page_or_by_index_not_both(small_book, kw):
    with pytest.raises(ValueError, match="source_page or chapter"):
        render_chapter(
            load_source(small_book), device="x4", settings=RenderSettings(), view="crosspoint", **kw
        )


def test_the_map_of_a_cache_is_read_without_its_pages(tmp_path, small_book, monkeypatch):
    cache = tmp_path / "cache"
    rendered = render(load_source(small_book), cache_dir=cache)
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: pytest.fail("read a page"))
    assert pages_module.read_map(cache) == (rendered.page_map, rendered.chapters)
    monkeypatch.undo()
    assert pages_module.page_file(cache, 1).read_bytes() == rendered.pages[1]


def test_a_folder_that_holds_no_finished_cache_has_no_map(tmp_path, small_book):
    cache = tmp_path / "cache"
    assert pages_module.read_map(cache) is None  # no folder
    render(load_source(small_book), cache_dir=cache)
    (cache / "0002.png").unlink()
    assert pages_module.read_map(cache) is None  # a page is missing
    render(load_source(small_book), cache_dir=cache)
    assert pages_module.read_map(cache) is not None
    (cache / "map.json").write_text("{not json")
    assert pages_module.read_map(cache) is None  # a damaged map
    (cache / "map.json").unlink()
    assert pages_module.read_map(cache) is None  # a folder that was never finished
