import io
import json
import multiprocessing
import os
import queue
import signal
import tempfile
import time
import zipfile
from importlib.metadata import version
from pathlib import Path

import pytest
from fakes import (
    crashing_work,
    epub_text,
    epub_title,
    hold_server_lock,
    interrupted_work,
    serve_one_job,
    stubborn_work,
    untimed,
    wait_for,
)

from eco.models import MARKER, models_dir
from eco.options import Options
from eco.style import PageStyle
from eco.web import jobs
from eco.web.jobs import STOPPED, JobStore, Runner, safe_name, server_lock


def md(name="a.md", text=b"# A\n\nText.\n"):
    return (name, io.BytesIO(text))


@pytest.fixture
def started(tmp_path):
    """Start a Runner on the jobs of tmp_path; every runner stops after the test."""
    runners = []

    def start(worker=None):
        store = JobStore(tmp_path)
        run = Runner(store, tmp_path, worker=worker)
        run.start()
        runners.append(run)
        return store, run

    yield start
    for run in runners:
        run.stop()


def workers():
    return {p.pid for p in multiprocessing.active_children()}


def test_queue_and_cancel(tmp_path, fake_worker):
    store = JobStore(tmp_path)
    run = Runner(store, tmp_path)
    run.start()
    try:
        a = store.create([("a.md", io.BytesIO(b"# A"))], Options())
        b = store.create([("b.md", io.BytesIO(b"# B"))], Options())
        run.submit(a.id)
        run.submit(b.id)
        assert store.get(b.id).status == "queued" and store.get(b.id).position == 1
        assert run.cancel(a.id)
        wait_for(lambda: store.get(a.id).status == "cancelled", 10)
        wait_for(lambda: store.get(b.id).status == "done", 10)
        assert untimed(store.events(b.id))[-1] == {"type": "end", "status": "done"}
    finally:
        run.stop()


def test_upload_name_cannot_escape(tmp_path):
    info = JobStore(tmp_path).create([("../../x.md", io.BytesIO(b"# X"))], Options())
    assert (
        Path(info.files[0].path).resolve().is_relative_to((tmp_path / "jobs" / info.id).resolve())
    )


def test_purge(tmp_path):
    store = JobStore(tmp_path)
    info = store.create([("a.md", io.BytesIO(b"#"))], Options())
    assert store.purge(now=info.created + 6 * 86400) == 0
    assert store.purge(now=info.created + 8 * 86400) == 1
    assert store.list() == []


def test_a_reserved_folder_is_no_job_until_it_is_adopted(tmp_path):
    store = JobStore(tmp_path)
    job = store.reserve()
    assert job.parent == store.root
    assert sorted(p.name for p in job.iterdir()) == ["input", "output"]
    for n, (name, data) in enumerate([("a.md", b"# A"), ("b.PDF", b"%PDF")]):
        (job / "input" / str(n)).mkdir()
        (job / "input" / str(n) / name).write_bytes(data)
    assert store.list() == []
    with pytest.raises(KeyError):
        store.get(job.name)
    info = store.adopt(job, ["a.md", "b.PDF"], Options(device="x3"))
    assert (info.id, info.status, info.position) == (job.name, "queued", 0)
    assert [(f.name, Path(f.path), f.kind) for f in info.files] == [
        ("a.md", job / "input" / "0" / "a.md", "md"),
        ("b.PDF", job / "input" / "1" / "b.PDF", "pdf"),
    ]
    assert store.get(info.id).options["device"] == "x3"
    assert [i.id for i in store.list()] == [info.id]
    assert (job / "input" / "0" / "a.md").read_bytes() == b"# A"  # adopted as they are, not copied


def test_a_reserved_folder_that_is_never_adopted_is_purged_by_its_age(tmp_path):
    store = JobStore(tmp_path)
    job = store.reserve()
    assert store.purge() == 0
    assert store.purge(now=time.time() + 8 * 86400) == 1
    assert not job.exists()


def test_purge_with_orphans_removes_a_folder_without_a_job_json_at_any_age(tmp_path):
    store = JobStore(tmp_path)
    cut = store.reserve()  # no job.json, made just now
    young = store.create([md()], Options())
    assert store.purge() == 0  # by age alone, nothing is old
    assert store.purge(orphans=True) == 1
    assert not cut.exists()
    assert [info.id for info in store.list()] == [young.id]


@pytest.mark.parametrize(
    "text",
    [
        b"{not json",
        b"[]",
        b"\x00" * 300,  # what a power loss can leave
        b'{"id": "x", "a field of a later eco": 1}',  # a newer or an older eco wrote it
    ],
)
def test_purge_at_start_leaves_a_job_json_it_cannot_read_to_the_age_rule(tmp_path, text):
    store = JobStore(tmp_path)
    job = store.reserve()
    (job / "job.json").write_bytes(text)
    (job / "output" / "book.x4.epub").write_bytes(b"an EPUB")
    assert store.purge(orphans=True) == 0
    assert (job / "output" / "book.x4.epub").is_file()  # never deleted at once
    assert store.purge(now=time.time() + 8 * 86400, orphans=True) == 1  # but after 7 days
    assert not job.exists()


def expired(store, status):
    """A job made 8 days ago, with `status`."""
    info = store.create([md()], Options())
    info.created -= 8 * 86400
    info.status = status
    store.save(info)
    return info


def test_purge_that_keeps_the_queued_jobs_takes_the_others_that_expired(tmp_path):
    store = JobStore(tmp_path)
    queued, running = expired(store, "queued"), expired(store, "running")
    expired(store, "done")
    young = store.create([md()], Options())
    assert store.purge(keep_queued=True) == 1  # the done one
    assert sorted(info.id for info in store.list()) == sorted([queued.id, running.id, young.id])
    assert store.purge() == 1  # without the keyword the queued one goes too, as it did
    assert sorted(info.id for info in store.list()) == sorted([running.id, young.id])


def test_adopt_that_fails_removes_the_folder(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    job = store.reserve()
    (job / "input" / "0").mkdir()
    (job / "input" / "0" / "a.md").write_bytes(b"# A")

    def full(info):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", full)
    with pytest.raises(OSError, match="disk full"):
        store.adopt(job, ["a.md"], Options())
    assert not job.exists()


def test_purge_keeps_a_job_that_runs(tmp_path):
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    info.status = "running"
    store.save(info)
    assert store.purge(now=info.created + 8 * 86400) == 0


@pytest.mark.parametrize(
    "name, safe",
    [
        ("../../x.md", "x.md"),
        ("..\\..\\x.md", "x.md"),
        ("C:\\Users\\me\\Bab Ü.md", "Bab Ü.md"),
        ("a:b.pdf", "a_b.pdf"),
        ('<>"|?*.epub', "______.epub"),
        ("name. ", "name"),
        ("ta\tb\x00\x7f.md", "tab.md"),
        ("\x01\x1f . .", "file"),
        ("..", "file"),
        ("", "file"),
        ("nul.pdf", "_nul.pdf"),
        ("CON", "_CON"),
        ("console.md", "console.md"),
    ],
)
def test_upload_names_are_safe_on_every_os(name, safe):
    assert safe_name(name) == safe


@pytest.mark.parametrize(
    "name",
    [
        "COM0.pdf",
        "lpt0.md",
        "COM¹.pdf",  # COM¹: Windows takes the superscript digits as 1, 2 and 3
        "com²",
        "LPT³.epub",
        "CONIN$.pdf",
        "conout$.md",  # written to the console on Windows 10
        "con .pdf",  # Windows drops the spaces before the dot
        "Aux  .epub",
    ],
)
def test_every_windows_device_name_gets_a_mark_in_front(name):
    assert safe_name(name) == f"_{name}"


@pytest.mark.parametrize("name", ["COM10.pdf", "lpt.md", "conin.pdf", "console .md", "com⁴"])
def test_a_name_that_only_looks_like_a_device_is_kept(name):
    assert safe_name(name) == name


@pytest.mark.parametrize("stem", ["a" * 300, "文" * 120, "\U0001f4d5" * 60, "é" * 150 + "x" * 100])
def test_a_long_upload_name_is_cut_by_bytes_and_keeps_its_type(tmp_path, stem):
    # Linux and macOS take at most 255 bytes in a file name, and a CJK character or an emoji is
    # three or four of them: 86 characters may already be too many
    name = safe_name(stem + ".pdf")
    assert len(name.encode()) <= 200 and name.endswith(".pdf")
    assert stem.startswith(name.removesuffix(".pdf"))  # cut at a character, never inside one
    (tmp_path / name).write_bytes(b"%PDF")  # a name the disk takes


def test_a_device_name_that_a_cut_makes_gets_its_mark_within_the_limit():
    name = safe_name("con" + " " * 300 + "a.pdf")  # the cut leaves "con" and the type
    assert name == "_con.pdf"
    long = safe_name("_" * 400 + ".pdf")
    assert len(long.encode()) <= 200


def stored(job_dir: Path) -> list[str]:
    """The files of the job's input folder, as `<n>/<name>`."""
    inputs = job_dir / "input"
    return sorted(p.relative_to(inputs).as_posix() for p in inputs.rglob("*") if p.is_file())


def test_uploads_are_stored_in_a_folder_of_their_own_with_a_safe_name(tmp_path):
    uploads = [("A.PDF", io.BytesIO(b"%PDF")), md("a:b.md"), ("c.epub", io.BytesIO(b"PK"))]
    info = JobStore(tmp_path).create(uploads, Options())
    inputs = tmp_path / "jobs" / info.id / "input"
    assert [(f.name, Path(f.path), f.kind) for f in info.files] == [
        ("A.PDF", inputs / "0" / "A.PDF", "pdf"),
        ("a_b.md", inputs / "1" / "a_b.md", "md"),
        ("c.epub", inputs / "2" / "c.epub", "epub"),
    ]
    assert sorted(p.name for p in inputs.iterdir()) == ["0", "1", "2"]
    assert stored(tmp_path / "jobs" / info.id) == ["0/A.PDF", "1/a_b.md", "2/c.epub"]
    assert Path(info.files[1].path).read_bytes() == b"# A\n\nText.\n"


def test_two_uploads_with_one_name_are_stored_apart(tmp_path):
    info = JobStore(tmp_path).create([md("a.md", b"# One"), md("a.md", b"# Two")], Options())
    assert stored(tmp_path / "jobs" / info.id) == ["0/a.md", "1/a.md"]
    assert [Path(f.path).read_bytes() for f in info.files] == [b"# One", b"# Two"]
    assert [f.name for f in info.files] == ["a.md", "a.md"]


def test_create_refuses_other_file_types(tmp_path):
    store = JobStore(tmp_path)
    with pytest.raises(ValueError, match="^Unsupported file type: report.docx$"):
        store.create([md(), ("report.docx", io.BytesIO(b"x"))], Options())
    assert list((tmp_path / "jobs").iterdir()) == []


def test_job_survives_a_new_store(tmp_path):
    info = JobStore(tmp_path).create([md()], Options(device="x3", formats=("epub",)))
    again = JobStore(tmp_path).get(info.id)
    assert (again.id, again.status, again.position, again.files) == (
        info.id,
        "queued",
        0,
        info.files,
    )
    assert again.options == {**info.options, "formats": ["epub"]}


def test_a_job_of_m2_loads_with_its_font_size_in_the_style(tmp_path):
    """M2 wrote `font_size` into the options. The upgraded server reads it as `style.font_size`."""
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    path = tmp_path / "jobs" / info.id / "job.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["options"]["style"]
    data["options"]["font_size"] = 96  # M2 took 8 to 96
    path.write_text(json.dumps(data), encoding="utf-8")
    again = store.get(info.id)
    assert again.options["style"] == PageStyle(font_size=64).to_json()
    assert "font_size" not in again.options
    assert [j.id for j in store.list()] == [info.id]


@pytest.mark.parametrize("job_id", ["0123456789abcdef", "..", "../jobs", "0123456789ABCDEF"])
def test_unknown_job_is_a_key_error(tmp_path, job_id):
    store = JobStore(tmp_path)
    with pytest.raises(KeyError):
        store.get(job_id)
    with pytest.raises(KeyError):
        store.events(job_id)


def test_list_is_newest_first(tmp_path):
    store = JobStore(tmp_path)
    ids = [store.create([md()], Options()).id for _ in range(3)]
    assert [info.id for info in store.list(limit=2)] == [ids[2], ids[1]]


def test_events_are_kept_in_order(tmp_path):
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    events = [{"type": "page", "done": n, "total": 2} for n in (1, 2)] + [
        {"type": "end", "status": "done"}
    ]
    for event in events:
        store.append_event(info.id, event)
    assert untimed(store.events(info.id)) == events


def test_end_event_is_kept_before_the_status_that_ends_the_job(tmp_path):
    """So a reader that sees the job ended finds its `end` event, as test_queue_and_cancel does."""
    calls = []

    class Recording(JobStore):
        def save(self, info):
            calls.append(info.status)
            super().save(info)

        def append_event(self, job_id, event):
            calls.append(event["type"])
            super().append_event(job_id, event)

    store = Recording(tmp_path)
    run = Runner(store, tmp_path)  # never started: the job stays queued
    info = store.create([md()], Options())
    run.submit(info.id)
    calls.clear()
    assert run.cancel(info.id)
    assert calls == ["end", "cancelled"]


def test_job_json_is_on_the_disk_before_it_takes_the_place_of_the_old_one(tmp_path, monkeypatch):
    # a power loss after the rename must not leave an empty job.json
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    calls = []
    real_replace = os.replace
    monkeypatch.setattr(jobs.os, "fsync", lambda fd: calls.append("fsync"))
    monkeypatch.setattr(
        jobs.os, "replace", lambda src, dst: (calls.append("replace"), real_replace(src, dst))
    )
    info.status = "done"
    store.save(info)
    assert calls == ["fsync", "replace"]


def test_save_tries_again_while_another_program_holds_job_json(tmp_path, monkeypatch):
    # Windows: an antivirus or the search indexer holds the file for a moment ([WinError 5])
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    monkeypatch.setattr(jobs, "_RETRY_WAITS", (0, 0))
    real_replace, tries = os.replace, []

    def held_twice(src, dst):
        tries.append(dst)
        if len(tries) <= 2:
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(jobs.os, "replace", held_twice)
    info.status = "done"
    store.save(info)
    assert len(tries) == 3 and store.get(info.id).status == "done"


def test_save_gives_up_after_the_last_try(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    monkeypatch.setattr(jobs, "_RETRY_WAITS", (0, 0))
    tries = []

    def held(src, dst):
        tries.append(dst)
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(jobs.os, "replace", held)
    info.status = "done"
    with pytest.raises(PermissionError):
        store.save(info)
    assert len(tries) == 3
    monkeypatch.undo()
    assert store.get(info.id).status == "queued"  # the old job.json, whole


def test_save_tries_again_only_on_windows():
    assert bool(jobs._RETRY_WAITS) == (os.name == "nt")
    assert sum(jobs._RETRY_WAITS) < 2  # a moment, not a hang


def test_a_save_that_fails_after_the_end_writes_no_second_end(tmp_path, fake_worker):
    class FailsOnce(JobStore):
        failed = False

        def save(self, info):
            if info.status == "done" and not self.failed:  # the save that ends the job
                self.failed = True
                raise OSError("the disk is busy")
            super().save(info)

    store = FailsOnce(tmp_path)
    run = Runner(store, tmp_path)
    run.start()
    try:
        info = store.create([md()], Options())
        run.submit(info.id)
        wait_for(lambda: store.failed and store.get(info.id).status == "done", 20)
    finally:
        run.stop()
    ends = [event for event in store.events(info.id) if event["type"] == "end"]
    assert untimed(ends) == [{"type": "end", "status": "done"}]


def test_a_job_whose_end_was_kept_but_not_its_status_ends_as_its_end_says(tmp_path, started):
    # the server stopped between the `end` event and job.json: the next start writes no second end
    old = JobStore(tmp_path)
    info = old.create([md()], Options())
    info.status = "running"
    old.save(info)
    old.append_event(info.id, {"type": "file", "index": 0, "status": "started"})
    old.append_event(info.id, {"type": "end", "status": "cancelled"})
    store, _ = started()
    assert store.get(info.id).status == "cancelled"
    assert store.events(info.id)[1:] == [{"type": "end", "status": "cancelled"}]


def test_rebuild_makes_a_new_job_from_the_same_inputs(tmp_path):
    store = JobStore(tmp_path)
    old = store.create([md("Bab Ü.md")], Options())
    new = store.rebuild(old.id, Options(device="x3"))
    path = Path(new.files[0].path)
    assert new.id != old.id and (new.status, new.options["device"]) == ("queued", "x3")
    assert (new.files[0].name, new.files[0].kind, new.files[0].outputs) == ("Bab Ü.md", "md", {})
    assert path == tmp_path / "jobs" / new.id / "input" / "0" / "Bab Ü.md"
    assert path.read_bytes() == Path(old.files[0].path).read_bytes()


def test_rebuild_links_each_input_into_the_layout_of_the_new_job(tmp_path):
    store = JobStore(tmp_path)
    uploads = [md("a.md", b"# One"), md("a.md", b"# Two"), md("b.md", b"# Three")]
    old = store.create(uploads, Options())
    new = store.rebuild(old.id, Options(size="small"))
    assert stored(tmp_path / "jobs" / new.id) == ["0/a.md", "1/a.md", "2/b.md"]
    for before, after in zip(old.files, new.files, strict=True):
        assert Path(after.path).parents[1] == tmp_path / "jobs" / new.id / "input"
        assert Path(after.path).read_bytes() == Path(before.path).read_bytes()
        assert (after.name, after.kind) == (before.name, before.kind)
        assert os.path.samefile(before.path, after.path)  # a link: the file is not written again
    assert stored(tmp_path / "jobs" / old.id) == ["0/a.md", "1/a.md", "2/b.md"]  # as it was


def test_markdown_converts_in_a_worker_process(started):
    store, run = started()  # the real _work
    info = store.create([md("Bab Ü.md", b"# Bab 1\n\nIsi.\n")], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    done = store.get(info.id)
    job = Path(done.files[0].path).parents[2]
    epub = Path(done.files[0].outputs["epub"])
    assert (done.status, done.files[0].error, done.files[0].book_dir) == ("done", None, None)
    assert epub == job / "output" / "Bab Ü.x4-pro.epub" and zipfile.is_zipfile(epub)
    assert Path(done.files[0].path).read_bytes() == b"# Bab 1\n\nIsi.\n"
    steps = [
        (e["type"], e.get("stage"), e["status"])
        for e in store.events(info.id)
        if e["type"] in ("file", "stage", "end")
    ]
    assert steps == [
        ("file", None, "started"),
        ("stage", "epub", "started"),
        ("stage", "epub", "finished"),
        ("stage", "optimize", "started"),
        ("stage", "optimize", "finished"),
        ("file", None, "done"),
        ("end", None, "done"),
    ]
    assert not (job / "tmp").exists()


def test_stray_file_in_the_input_folder_is_not_an_input(started):
    store, run = started()  # the real _work
    info = store.create([md()], Options())
    (Path(info.files[0].path).parents[1] / "desktop.ini").write_text("[.ShellClassInfo]")
    (Path(info.files[0].path).parent / "Thumbs.db").write_text("x")  # and one by the upload
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    assert store.get(info.id).status == "done"


def finished_job(store, info):
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    return store.get(info.id)


def test_a_book_is_titled_with_the_name_of_its_upload(started):
    store, run = started()  # the real _work
    info = store.create([md("book.md", b"# Chapter\n\nText.\n")], Options())
    run.submit(info.id)
    done = finished_job(store, info)
    assert (done.status, done.files[0].error) == ("done", None)
    assert epub_title(done.files[0].outputs["epub"]) == "book"  # not `0-book`


def test_a_pages_mode_pdf_is_titled_with_the_name_of_its_upload(started, fixtures_dir):
    store, run = started()  # the real _work; pages mode needs no models
    three_pages = fixtures_dir["blank"].read_bytes()  # no title in its metadata
    info = store.create([("report.pdf", io.BytesIO(three_pages))], Options(mode="pages"))
    run.submit(info.id)
    done = finished_job(store, info)
    assert (done.status, done.files[0].error) == ("done", None)
    assert epub_title(done.files[0].outputs["epub"]) == "report"


def test_two_uploads_with_one_name_both_convert_and_keep_their_own_text(started):
    store, run = started()  # the real _work
    uploads = [md("a.md", b"# First\n\nOne.\n"), md("a.md", b"# Second\n\nTwo.\n")]
    info = store.create(uploads, Options())
    run.submit(info.id)
    done = finished_job(store, info)
    outputs = [Path(f.outputs["epub"]) for f in done.files]
    assert done.status == "done" and [p.name for p in outputs] == [
        "a.x4-pro.epub",
        "a.x4-pro-1.epub",
    ]
    first, second = epub_text(outputs[0]), epub_text(outputs[1])
    assert "First" in first and "Second" not in first
    assert "Second" in second and "First" not in second
    assert [epub_title(p) for p in outputs] == ["a", "a"]


def test_bad_file_fails_alone_and_the_job_goes_on(started):
    store, run = started()  # the real _work
    info = store.create([("bad.epub", io.BytesIO(b"not a zip")), md("good.md")], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    done = store.get(info.id)
    assert done.status == "done" and done.files[0].error and done.files[0].outputs == {}
    assert done.files[1].error is None and Path(done.files[1].outputs["epub"]).is_file()
    files = [e for e in store.events(info.id) if e["type"] == "file"]
    assert [(e["index"], e["status"]) for e in files] == [
        (0, "started"),
        (0, "failed"),
        (1, "started"),
        (1, "done"),
    ]
    assert files[1]["error"] == done.files[0].error


def test_job_where_no_file_converts_fails(started):
    store, run = started()  # the real _work
    info = store.create([("bad.epub", io.BytesIO(b"not a zip"))], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    assert store.get(info.id).status == "failed"
    assert untimed(store.events(info.id))[-1] == {"type": "end", "status": "failed"}


def test_a_pdf_that_needs_the_missing_vc_runtime_fails_with_its_message(
    tmp_path, monkeypatch, fixtures_dir, platform_is, vc_message
):
    # The real `_work`, called here and not in a worker process, which would not see the patches.
    platform_is("win32")
    monkeypatch.setattr(tempfile, "tempdir", None)  # `_work` moves it into the job; put back after
    models_dir(tmp_path).mkdir(parents=True)
    (models_dir(tmp_path) / MARKER).write_text(version("docling"))

    def convert(self, source, **kwargs):
        raise ImportError(
            "DLL load failed while importing onnxruntime_pybind11_state: "
            "The specified module could not be found."
        )

    monkeypatch.setattr("docling.document_converter.DocumentConverter.convert", convert)
    store = JobStore(tmp_path)
    pdf = fixtures_dir["blank"].read_bytes()
    info = store.create([("book.pdf", io.BytesIO(pdf))], Options())
    events = queue.Queue()
    jobs._work(str(store.job_dir(info.id)), info.options, str(tmp_path), events)
    sent = list(events.queue)
    failed = [e for e in sent if e["type"] == "file" and e["status"] == "failed"]
    assert [e["error"] for e in failed] == [vc_message]
    assert sent[-1] == {"type": "end", "status": "failed"}


def test_cancel_ends_the_worker_process_within_10_s(started):
    store, run = started(worker=stubborn_work)
    info = store.create([md()], Options())
    run.submit(info.id)
    wait_for(lambda: store.events(info.id), 10)
    pid = store.events(info.id)[0]["pid"]
    # the process the runner kills is the worker itself, not a launcher in front of it
    assert pid in workers()
    begin = time.monotonic()
    assert run.cancel(info.id)
    wait_for(lambda: store.get(info.id).status == "cancelled", 10)
    assert time.monotonic() - begin < 10
    assert pid not in workers()
    assert untimed(store.events(info.id))[-1] == {"type": "end", "status": "cancelled"}
    assert not run.cancel(info.id)


def test_queue_positions_follow_the_queue(started, fake_worker):
    store, run = started()
    a, b, c = (store.create([md(f"{n}.md")], Options()) for n in "abc")
    for job in (a, b, c):
        run.submit(job.id)
    assert [store.get(job.id).position for job in (b, c)] == [1, 2]
    assert run.cancel(b.id)  # a queued job ends at once
    assert (store.get(b.id).status, store.get(c.id).position) == ("cancelled", 1)
    assert untimed(store.events(b.id)) == [{"type": "end", "status": "cancelled"}]
    wait_for(lambda: store.get(c.id).status == "running", 10)
    assert (store.get(a.id).status, store.get(c.id).position) == ("done", 0)
    wait_for(lambda: store.get(c.id).status == "done", 10)


def test_submit_twice_queues_once_and_a_finished_job_is_refused(started, fake_worker):
    store, run = started()
    a, b = (store.create([md()], Options()) for _ in range(2))
    run.submit(a.id)
    run.submit(b.id)
    run.submit(b.id)
    wait_for(lambda: store.get(b.id).status == "done", 10)
    assert [e["type"] for e in store.events(b.id)].count("end") == 1
    with pytest.raises(ValueError):
        run.submit(a.id)


def test_subscriber_gets_every_event_once(started, fake_worker):
    store, run = started()
    info = store.create([md("a.md"), md("b.md")], Options())
    run.submit(info.id)
    wait_for(lambda: any(e["type"] == "page" for e in store.events(info.id)), 10)
    q = run.subscribe(info.id)  # mid-run: the replay so far, then the live events
    got = [q.get(timeout=10)]
    while got[-1]["type"] != "end":
        got.append(q.get(timeout=10))
    run.unsubscribe(info.id, q)
    assert got == store.events(info.id)
    assert [e["status"] for e in got if e["type"] == "file"] == ["started", "done"] * 2
    late = run.subscribe(info.id)  # after the end: the whole replay, and nothing more comes
    assert [late.get_nowait() for _ in got] == got and late.empty()


def test_worker_that_dies_fails_its_job_and_the_queue_goes_on(started):
    store, run = started(worker=crashing_work)
    a, b = (store.create([md()], Options()) for _ in range(2))
    run.submit(a.id)
    run.submit(b.id)
    wait_for(lambda: store.get(b.id).status == "failed", 20)
    info = store.get(a.id)
    message = "The conversion stopped unexpectedly (exit code 3)."
    assert (info.status, info.files[0].error) == ("failed", message)
    assert untimed(store.events(a.id))[-1] == {"type": "end", "status": "failed"}
    assert not workers()


def test_stop_kills_the_worker_and_keeps_the_queue(started, fake_worker):
    store, run = started()
    a, b = (store.create([md()], Options()) for _ in range(2))
    run.submit(a.id)
    run.submit(b.id)
    wait_for(lambda: any(e["type"] == "page" for e in store.events(a.id)), 10)
    run.stop()
    assert (store.get(a.id).status, store.get(a.id).files[0].error) == ("failed", STOPPED)
    assert untimed(store.events(a.id))[-1] == {"type": "end", "status": "failed"}
    assert (store.get(b.id).status, store.get(b.id).position) == ("queued", 1)
    assert not workers()


def test_new_server_settles_the_jobs_an_old_one_left(tmp_path, started, fake_worker):
    old = JobStore(tmp_path)
    was_running = old.create([md("a.md"), md("b.md")], Options())
    was_queued = old.create([md("c.md")], Options())
    was_running.status = "running"
    was_running.files[0].outputs = {"epub": "a.x4.epub"}
    old.save(was_running)
    old.append_event(was_running.id, {"type": "file", "index": 0, "status": "started"})
    store, _ = started()
    left = store.get(was_running.id)
    # a job that had started is not started again: it ends, by the same rule as any other
    assert (left.status, [f.error for f in left.files]) == ("done", [None, STOPPED])
    assert untimed(store.events(was_running.id))[-1] == {"type": "end", "status": "done"}
    # a job that never started keeps its place and runs
    wait_for(lambda: store.get(was_queued.id).status == "done", 10)


def test_ctrl_c_in_the_console_does_not_stop_the_worker(started):
    # the console sends it to the worker too (Windows: one console; POSIX: one process group); the
    # server stops the worker itself, so a job must not end "stopped unexpectedly (exit code 1)"
    store, run = started(worker=interrupted_work)
    info = store.create([md()], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status not in ("queued", "running"), 20)
    left = store.get(info.id)
    assert (left.status, left.files[0].error) == ("done", None)


def test_a_worker_ends_when_its_server_is_killed(tmp_path):
    # taskkill /F, SIGKILL or the OOM killer: the server cannot stop its worker, which would run
    # on, and later hang at its exit on a full pipe of events nobody reads
    ctx = multiprocessing.get_context("spawn")
    server = ctx.Process(target=serve_one_job, args=(str(tmp_path),))  # its runner has children
    server.start()
    pid = None
    try:
        store = JobStore(tmp_path)

        def worker_pid():
            for info in store.list():
                for event in store.events(info.id):
                    if "pid" in event:
                        return event["pid"]
            return None

        wait_for(lambda: worker_pid() is not None, 60)
        pid = worker_pid()
        assert not free(tmp_path / "worker")  # the worker runs and holds its lock
        server.kill()
        server.join(10)
        wait_for(lambda: free(tmp_path / "worker"), 15)  # the worker went with its server
    finally:
        if server.is_alive():
            server.kill()
        if pid is not None and not free(tmp_path / "worker"):
            os.kill(pid, signal.SIGTERM)  # do not leave it running when the test fails


def test_server_lock_is_held_once_per_data_folder(tmp_path):
    with server_lock(tmp_path):
        with pytest.raises(RuntimeError) as busy, server_lock(tmp_path):
            pass
        assert str(busy.value) == f"Another eco web is already using {tmp_path}"
        with server_lock(tmp_path / "other"):  # another data folder is free
            pass
    with server_lock(tmp_path):  # free again once released
        pass


def free(data_dir) -> bool:
    try:
        with server_lock(data_dir):
            return True
    except RuntimeError:
        return False


def test_server_lock_of_a_killed_process_is_free(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    held = ctx.Event()
    proc = ctx.Process(target=hold_server_lock, args=(str(tmp_path), held), daemon=True)
    proc.start()
    try:
        assert held.wait(30)
        assert not free(tmp_path)  # another process holds it
    finally:
        proc.kill()  # as a crash: the lock is never released by the process itself
        proc.join(10)
    wait_for(lambda: free(tmp_path), 10)


def test_a_job_json_without_epubcheck_still_loads(tmp_path):
    store = JobStore(tmp_path)
    info = store.create([md()], Options())
    path = tmp_path / "jobs" / info.id / "job.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for f in data["files"]:
        f.pop("epubcheck", None)  # a job.json from before the field existed
    path.write_text(json.dumps(data), encoding="utf-8")
    assert store.get(info.id).files[0].epubcheck is None


def test_a_done_file_keeps_its_epubcheck_outcome(started, fake_worker):
    store, run = started()
    info = store.create([md()], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status == "done", 10)
    assert store.get(info.id).files[0].epubcheck == "passed"


def test_page_and_book_events_reach_the_browser_dict():
    from eco.events import BookEvent, PageEvent

    assert jobs._event(PageEvent(3, 10, 4)) == {"type": "page", "done": 3, "total": 10, "page": 4}
    assert jobs._event(BookEvent(5, (2,), (5,))) == {
        "type": "book",
        "pages": 5,
        "scanned": [2],
        "blank": [5],
    }


def test_every_stored_event_has_a_server_time(started, fake_worker):
    store, run = started()
    info = store.create([("a.md", io.BytesIO(b"# A"))], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status == "done", 10)
    events = store.events(info.id)
    assert events and all(isinstance(e["t"], float) for e in events)
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)
