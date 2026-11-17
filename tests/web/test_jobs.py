import io
import multiprocessing
import time
import zipfile
from pathlib import Path

import pytest
from fakes import crashing_work, stubborn_work, wait_for

from eco.options import Options
from eco.web.jobs import STOPPED, JobStore, Runner, safe_name


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
        assert store.events(b.id)[-1] == {"type": "end", "status": "done"}
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


def test_long_upload_name_is_cut_and_keeps_its_type():
    name = safe_name("a" * 300 + ".pdf")
    assert len(name) == 120 and name.endswith("a.pdf")


def test_uploads_are_stored_by_number_with_a_safe_name(tmp_path):
    uploads = [("A.PDF", io.BytesIO(b"%PDF")), md("a:b.md"), ("c.epub", io.BytesIO(b"PK"))]
    info = JobStore(tmp_path).create(uploads, Options())
    stored = [(f.name, Path(f.path).name, f.kind) for f in info.files]
    assert stored == [
        ("A.PDF", "0-A.PDF", "pdf"),
        ("a_b.md", "1-a_b.md", "md"),
        ("c.epub", "2-c.epub", "epub"),
    ]
    assert sorted(p.name for p in (tmp_path / "jobs" / info.id / "input").iterdir()) == [
        "0-A.PDF",
        "1-a_b.md",
        "2-c.epub",
    ]
    assert Path(info.files[1].path).read_bytes() == b"# A\n\nText.\n"


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
    assert store.events(info.id) == events


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


def test_rebuild_makes_a_new_job_from_the_same_inputs(tmp_path):
    store = JobStore(tmp_path)
    old = store.create([md("Bab Ü.md")], Options())
    new = store.rebuild(old.id, Options(device="x3"))
    path = Path(new.files[0].path)
    assert new.id != old.id and (new.status, new.options["device"]) == ("queued", "x3")
    assert (new.files[0].name, new.files[0].kind, new.files[0].outputs) == ("Bab Ü.md", "md", {})
    assert path.parent == tmp_path / "jobs" / new.id / "input"
    assert path.read_bytes() == Path(old.files[0].path).read_bytes()


def test_markdown_converts_in_a_worker_process(started):
    store, run = started()  # the real _work
    info = store.create([md("Bab Ü.md", b"# Bab 1\n\nIsi.\n")], Options())
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    done = store.get(info.id)
    job = Path(done.files[0].path).parents[1]
    epub = Path(done.files[0].outputs["epub"])
    assert (done.status, done.files[0].error, done.files[0].book_dir) == ("done", None, None)
    assert epub == job / "output" / "Bab Ü.x4.epub" and zipfile.is_zipfile(epub)
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
    (Path(info.files[0].path).parent / "desktop.ini").write_text("[.ShellClassInfo]")
    run.submit(info.id)
    wait_for(lambda: store.get(info.id).status in ("done", "failed"), 120)
    assert store.get(info.id).status == "done"


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
    assert store.events(info.id)[-1] == {"type": "end", "status": "failed"}


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
    assert store.events(info.id)[-1] == {"type": "end", "status": "cancelled"}
    assert not run.cancel(info.id)


def test_queue_positions_follow_the_queue(started, fake_worker):
    store, run = started()
    a, b, c = (store.create([md(f"{n}.md")], Options()) for n in "abc")
    for job in (a, b, c):
        run.submit(job.id)
    assert [store.get(job.id).position for job in (b, c)] == [1, 2]
    assert run.cancel(b.id)  # a queued job ends at once
    assert (store.get(b.id).status, store.get(c.id).position) == ("cancelled", 1)
    assert store.events(b.id) == [{"type": "end", "status": "cancelled"}]
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
    assert store.events(a.id)[-1] == {"type": "end", "status": "failed"}
    assert not workers()


def test_stop_kills_the_worker_and_keeps_the_queue(started, fake_worker):
    store, run = started()
    a, b = (store.create([md()], Options()) for _ in range(2))
    run.submit(a.id)
    run.submit(b.id)
    wait_for(lambda: any(e["type"] == "page" for e in store.events(a.id)), 10)
    run.stop()
    assert (store.get(a.id).status, store.get(a.id).files[0].error) == ("failed", STOPPED)
    assert store.events(a.id)[-1] == {"type": "end", "status": "failed"}
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
    assert store.events(was_running.id)[-1] == {"type": "end", "status": "done"}
    # a job that never started keeps its place and runs
    wait_for(lambda: store.get(was_queued.id).status == "done", 10)
