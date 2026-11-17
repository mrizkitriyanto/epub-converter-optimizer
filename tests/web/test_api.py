"""The jobs API: uploads, events, cancel, rebuild and downloads.

A TestClient hands the app its whole body as one message, and it returns only when the response
has ended. So the tests that need a body in pieces, or a stream that never ends, call the app
the way a server does (`wire`), and two of them run a real uvicorn (`serving`).
"""

import asyncio
import errno
import io
import json
import logging
import re
import shutil
import signal
import threading
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx
import pytest
import uvicorn
from fakes import endless_work, epub_title, failing_work, fake_work, wait_for
from fastapi.testclient import TestClient

from eco.options import Options
from eco.web import app as web_app
from eco.web import jobs
from eco.web.app import _Upload, create_app
from eco.web.jobs import JobStore, Runner

LOCAL = "http://127.0.0.1:8000"  # a browser on this computer, server on the default port
MB = 1024 * 1024
BOUNDARY = "ecoboundary7d3f"
TOO_LARGE = {"error": "File too large (limit 1 MB)"}
BOOK = "# Bab Ü\n\nIsi bab satu.\n\n## Bagian\n\nTeks lagi.\n".encode()


# Helpers


def client(tmp_path, **kwargs):
    """The app on tmp_path without its lifespan: no runner thread, so a job stays queued."""
    return TestClient(create_app(tmp_path, token=None, **kwargs), base_url=LOCAL)


@contextmanager
def running(tmp_path, **kwargs):
    """The same with the lifespan: the runner converts the jobs, one at a time."""
    with client(tmp_path, **kwargs) as c:
        yield c


def post(c, *files, options=None, **kwargs):
    """POST /api/jobs. Each file is (name, bytes); options is a dict, or text sent as it is."""
    data = None
    if options is not None:
        data = {"options": options if isinstance(options, str) else json.dumps(options)}
    return c.post("/api/jobs", files=[("files[]", f) for f in files], data=data, **kwargs)


def multipart(*parts):
    """A multipart/form-data body made by hand, in the order given. A part is (field, filename or
    None, bytes). Returns the body and its Content-Type."""
    body = b""
    for field, filename, data in parts:
        disposition = f'form-data; name="{field}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        body += f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n\r\n".encode()
        body += data + b"\r\n"
    return body + f"--{BOUNDARY}--\r\n".encode(), f"multipart/form-data; boundary={BOUNDARY}"


def on_disk(tmp_path):
    """Everything under the data folder."""
    return sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))


def stored(tmp_path, job_id) -> list[str]:
    """The files of a job's input folder, as `<n>/<name>`."""
    inputs = tmp_path / "jobs" / job_id / "input"
    return sorted(p.relative_to(inputs).as_posix() for p in inputs.rglob("*") if p.is_file())


def tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def sse(text):
    """The events of an event stream. Each message is one `data: <json>` line and a blank line."""
    messages = text.split("\n\n")
    assert messages.pop() == ""  # the stream ends with the blank line of its last message
    events = []
    for message in messages:
        assert message.startswith("data: ") and "\n" not in message, message
        events.append(json.loads(message.removeprefix("data: ")))
    return events


def strings(value):
    """Every string in a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def assert_no_path(documents, root: Path):
    """No JSON document (a parsed value) holds the data folder, or any absolute path at all."""
    forms = [str(root), str(root).replace("\\", "\\\\"), root.as_posix()]
    for document in documents:
        text = json.dumps(document, ensure_ascii=False)
        assert not any(form in text for form in forms), text
        for found in strings(document):
            assert not PurePosixPath(found).is_absolute(), found
            assert not PureWindowsPath(found).is_absolute(), found


def done_job(store: JobStore, name="a.md", output=b"an EPUB"):
    """A finished job made without a worker: one input, one output `<stem>.x4.epub`, an `end`
    event."""
    info = store.create([(name, io.BytesIO(b"# A"))], Options())
    out = store.job_dir(info.id) / "output" / f"{Path(name).stem}.x4.epub"
    out.write_bytes(output)
    info.files[0].outputs = {"epub": str(out)}
    info.status = "done"
    store.save(info)
    store.append_event(info.id, {"type": "end", "status": "done"})
    return info


async def subscribed(runner, job_id):
    """Wait, on the loop, until a stream of the job has made its queue."""
    for _ in range(500):
        if runner._subs.get(job_id):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no stream subscribed within 5 s")


def backdate(store: JobStore, job_id: str, seconds: float):
    """Make a job older, so that "newest first" does not hang on the step of the clock."""
    info = store.get(job_id)
    info.created -= seconds
    store.save(info)


def scope(method, path, headers):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},  # what uvicorn says
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode("latin-1")) for k, v in headers],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


@dataclass
class Wired:
    messages: list
    pulled: int = 0  # how many pieces of the body the app took

    @property
    def status(self):
        return self.messages[0]["status"]

    @property
    def body(self):
        return b"".join(m.get("body", b"") for m in self.messages[1:])

    def json(self):
        return json.loads(self.body)


async def wire(
    app, method, path, *, headers=(), chunks=(b"",), complete=True, probe=None, gone=None
):
    """Call the app as a server does. The body comes piece by piece in `chunks`; `probe` runs
    before each piece. After the last piece the client has gone, or with `complete=False` it
    goes in the middle of the body. With `gone` (an Event) it stays until the event is set."""
    wired = Wired([])
    pending = list(chunks)

    async def receive():
        if pending:
            wired.pulled += 1
            if probe:
                probe()
            return {
                "type": "http.request",
                "body": pending.pop(0),
                "more_body": bool(pending) or not complete,
            }
        if gone is not None:
            await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        wired.messages.append(message)

    await app(scope(method, path, [("host", "127.0.0.1:8000"), *headers]), receive, send)
    return wired


@dataclass
class Live:
    url: str
    server: uvicorn.Server
    thread: threading.Thread


@contextmanager
def serving(app, server=None):
    """The app on a real uvicorn (or the `server` given), in a thread, at a free port of this
    computer."""
    if server is None:  # (a Config sets up logging again: the caller of a Server made it first)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        wait_for(lambda: server.started, 20)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield Live(f"http://127.0.0.1:{port}", server, thread)
    finally:
        server.should_exit = True
        thread.join(30)


class Records(logging.Handler):
    """Every log record it is given."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@dataclass
class Finished:
    app: object
    client: TestClient
    data: Path
    posted: httpx.Response
    live: str  # the event stream opened right after the POST
    replay: str  # the event stream opened after the job had ended

    @property
    def id(self):
        return self.posted.json()["id"]


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    """One job of two Markdown files, run to its end by the fake worker through the API."""
    data = tmp_path_factory.mktemp("finished")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(jobs, "_work", fake_work)
        app = create_app(data, token=None)  # the runner takes its worker here, so this is enough:
    with TestClient(app, base_url=LOCAL) as c:  # the other tests of the module get the real one
        posted = post(c, ("Bab Ü.md", b"# A\n"), ("notes.md", b"# B\n"))
        events = f"/api/jobs/{posted.json()['id']}/events"
        live = c.get(events).text  # returns when the stream ends
        yield Finished(app, c, data, posted, live, c.get(events).text)


# Uploads: file types


def test_docx_is_refused_with_its_name(tmp_path):
    c = client(tmp_path)
    r = post(c, ("report.docx", b"PK"))
    assert (r.status_code, r.json()) == (400, {"error": "Unsupported file type: report.docx"})
    assert on_disk(tmp_path) == ["jobs"]


@pytest.mark.parametrize("name", ["a.PDF", "A.Md", "book.EPUB", "x.y.md"])
def test_type_is_checked_by_suffix_and_case_does_not_matter(tmp_path, name):
    r = post(client(tmp_path), (name, b"x"))
    assert r.status_code == 201
    assert [f["name"] for f in r.json()["files"]] == [name]


@pytest.mark.parametrize("name", ["Report.DOCX", "../../evil.exe", "no-suffix", "archive.md.zip"])
def test_the_refusal_names_the_file_as_uploaded(tmp_path, name):
    r = post(client(tmp_path), (name, b"x"))
    assert (r.status_code, r.json()) == (400, {"error": f"Unsupported file type: {name}"})


def test_one_bad_file_refuses_the_whole_upload_and_leaves_nothing(tmp_path):
    c = client(tmp_path)
    r = post(c, ("a.md", b"# A"), ("b.docx", b"PK"), ("c.md", b"# C"))
    assert (r.status_code, r.json()) == (400, {"error": "Unsupported file type: b.docx"})
    assert on_disk(tmp_path) == ["jobs"]
    assert c.get("/api/jobs").json() == []


def test_a_path_in_an_upload_name_stays_inside_the_job(tmp_path):
    c = client(tmp_path)
    r = post(c, ("../../x.pdf", b"%PDF-1.4"), ("..\\..\\y.md", b"# Y"))
    assert r.status_code == 201
    assert [f["name"] for f in r.json()["files"]] == ["x.pdf", "y.md"]
    job = tmp_path / "jobs" / r.json()["id"]
    assert stored(tmp_path, r.json()["id"]) == ["0/x.pdf", "1/y.md"]
    outside = [
        p
        for p in tmp_path.rglob("*")
        if p not in (tmp_path / "jobs", job) and not p.is_relative_to(job)
    ]
    assert outside == [] and not (tmp_path.parent / "x.pdf").exists()


def test_two_uploads_with_one_name_are_stored_apart_each_under_its_own_name(tmp_path):
    job = post(client(tmp_path), ("a.md", b"# One"), ("a.md", b"# Two")).json()
    assert [(f["index"], f["name"]) for f in job["files"]] == [(0, "a.md"), (1, "a.md")]
    assert stored(tmp_path, job["id"]) == ["0/a.md", "1/a.md"]
    inputs = tmp_path / "jobs" / job["id"] / "input"
    assert [(inputs / n / "a.md").read_bytes() for n in "01"] == [b"# One", b"# Two"]


def test_a_name_that_is_not_utf8_is_read_as_latin1(tmp_path):
    body, content_type = multipart(("files[]", "bäb.md", b"# A"))
    body = body.replace("bäb.md".encode(), "bäb.md".encode("latin-1"))  # as an old client sends it
    r = client(tmp_path).post("/api/jobs", content=body, headers={"content-type": content_type})
    assert [f["name"] for f in r.json()["files"]] == ["bäb.md"]


def test_a_body_that_is_not_multipart_is_refused(tmp_path):
    c = client(tmp_path)
    for kwargs in (
        {"json": {"a": 1}},
        {"content": b"x"},
        {"content": b"--b--", "headers": {"content-type": "multipart/form-data"}},
    ):
        r = c.post("/api/jobs", **kwargs)
        assert (r.status_code, r.json()) == (
            400,
            {"error": "Send the files as multipart/form-data"},
        )
    assert on_disk(tmp_path) == ["jobs"]


def test_no_files_is_an_error(tmp_path):
    body, content_type = multipart(("options", None, b"{}"))
    r = client(tmp_path).post("/api/jobs", content=body, headers={"content-type": content_type})
    assert (r.status_code, r.json()) == (400, {"error": "No files were uploaded"})


def test_a_body_cut_short_is_refused_and_leaves_nothing(tmp_path):
    body, content_type = multipart(("files[]", "a.md", b"# A\n" * 100))
    cut = body[:-20]  # the closing boundary never comes
    r = client(tmp_path).post("/api/jobs", content=cut, headers={"content-type": content_type})
    assert (r.status_code, r.json()) == (400, {"error": "The upload could not be read"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_client_that_leaves_in_the_middle_leaves_nothing(tmp_path):
    app = create_app(tmp_path, token=None)
    body, content_type = multipart(("files[]", "a.md", b"x" * 200_000))
    chunks = [body[i : i + 65536] for i in range(0, 150_000, 65536)]  # 3 pieces, then it is gone
    headers = [("content-type", content_type)]
    wired = asyncio.run(
        wire(app, "POST", "/api/jobs", headers=headers, chunks=chunks, complete=False)
    )
    assert wired.pulled == len(chunks)
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_that_arrives_in_small_pieces_is_stored_whole(tmp_path):
    app = create_app(tmp_path, token=None)
    # lines that look like the boundary, and every byte value
    content = b"# T\r\n\r\n--" + BOUNDARY.encode() + b"-not-the-end\r\n--" + bytes(range(256)) * 20
    body, content_type = multipart(
        ("options", None, b'{"title": "T"}'), ("files[]", "Bäb.md", content)
    )
    chunks = [body[i : i + 5] for i in range(0, len(body), 5)]  # the headers are cut in two too
    headers = [("content-type", content_type)]
    wired = asyncio.run(wire(app, "POST", "/api/jobs", headers=headers, chunks=chunks))
    assert wired.status == 201
    job = wired.json()
    assert (tmp_path / "jobs" / job["id"] / "input" / "0" / "Bäb.md").read_bytes() == content
    assert (job["files"][0]["name"], job["options"]["title"]) == ("Bäb.md", "T")


def test_the_origin_check_stops_an_upload_before_anything_is_written(tmp_path):
    r = post(client(tmp_path), ("a.md", b"# A"), headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert on_disk(tmp_path) == ["jobs"]


# Uploads: the size limit


def test_an_upload_over_the_limit_is_413(tmp_path):
    c = client(tmp_path, max_upload_mb=1)
    r = post(c, ("big.md", b"x" * (MB + 1)))
    assert (r.status_code, r.json()) == (413, TOO_LARGE)
    assert on_disk(tmp_path) == ["jobs"]


def test_an_upload_of_exactly_the_limit_passes(tmp_path):
    r = post(client(tmp_path, max_upload_mb=1), ("big.md", b"x" * MB))
    assert r.status_code == 201
    assert r.json()["files"][0]["size"] == MB


def test_the_limit_is_for_all_the_files_of_a_request(tmp_path):
    c = client(tmp_path, max_upload_mb=1)
    most = b"x" * (MB * 6 // 10)
    assert post(c, ("a.md", most)).status_code == 201
    r = post(c, ("a.md", most), ("b.md", most))
    assert (r.status_code, r.json()) == (413, TOO_LARGE)
    assert len(c.get("/api/jobs").json()) == 1
    assert len(list((tmp_path / "jobs").iterdir())) == 1  # nothing of the second request


def test_the_limit_comes_from_the_app(tmp_path):
    r = post(client(tmp_path, max_upload_mb=3), ("big.md", b"x" * (3 * MB + 1)))
    assert (r.status_code, r.json()) == (413, {"error": "File too large (limit 3 MB)"})


def test_the_default_limit_is_500_mb(tmp_path):
    app = create_app(tmp_path, token=None)
    body, content_type = multipart(("files[]", "a.md", b"# A"))
    headers = [("content-type", content_type), ("content-length", str(600 * MB))]
    wired = asyncio.run(wire(app, "POST", "/api/jobs", headers=headers, chunks=[body]))
    assert (wired.status, wired.json()) == (413, {"error": "File too large (limit 500 MB)"})
    declared = [("content-type", content_type), ("content-length", str(len(body)))]
    ok = asyncio.run(wire(app, "POST", "/api/jobs", headers=declared, chunks=[body]))
    assert ok.status == 201  # a 500 MB limit is no hindrance to a small book


def test_a_huge_declared_size_is_refused_without_reading_the_body(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    body, content_type = multipart(("files[]", "a.md", b"# A"))  # small, and valid
    headers = [("content-type", content_type), ("content-length", str(50 * 1024 * MB))]
    wired = asyncio.run(wire(app, "POST", "/api/jobs", headers=headers, chunks=[body]))
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled == 0
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_with_no_size_is_cut_off_soon_after_the_limit(tmp_path, monkeypatch):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    seen = []
    rmtree = shutil.rmtree

    def spy(path, *args, **kwargs):  # what the job folder held when it was thrown away
        seen.append(tree_size(Path(path)))
        rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", spy)
    piece = 64 * 1024
    body, content_type = multipart(("files[]", "big.md", b"x" * (100 * piece)))  # 6.4 MB
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    headers = [("content-type", content_type)]  # chunked: no Content-Length
    wired = asyncio.run(wire(app, "POST", "/api/jobs", headers=headers, chunks=chunks))
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled <= 20 < len(chunks)  # about 1 MB was read, not the 6.4 MB
    assert seen and max(seen) <= MB  # never a byte over the limit on the disk
    assert on_disk(tmp_path) == ["jobs"]


def test_a_file_after_the_limit_is_not_read(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    piece = 64 * 1024
    body, content_type = multipart(
        ("files[]", "a.md", b"x" * (MB // 2)),
        ("files[]", "b.md", b"x" * (MB // 2 + 1)),  # together they are one byte over
        ("files[]", "c.md", b"x" * (50 * piece)),
    )
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    wired = asyncio.run(
        wire(app, "POST", "/api/jobs", headers=[("content-type", content_type)], chunks=chunks)
    )
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled <= 20 < len(chunks)
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_of_other_parts_is_cut_off_too(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    piece = 64 * 1024
    # no file is large, but the request is: the framing and the options never come to 1 MiB
    body, content_type = multipart(
        ("files[]", "a.md", b"# A"), ("note", None, b"x" * (100 * piece))
    )
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    wired = asyncio.run(
        wire(app, "POST", "/api/jobs", headers=[("content-type", content_type)], chunks=chunks)
    )
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled <= 34 < len(chunks)
    assert on_disk(tmp_path) == ["jobs"]


def test_an_error_while_writing_leaves_nothing_and_answers_json(tmp_path, monkeypatch):
    def full(self, data, start, end):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(_Upload, "_part_data", full)
    c = TestClient(create_app(tmp_path, token=None), base_url=LOCAL, raise_server_exceptions=False)
    r = post(c, ("a.md", b"# A"))
    assert (r.status_code, r.json()) == (500, {"error": "Something went wrong on the server"})
    assert on_disk(tmp_path) == ["jobs"]


def test_the_framework_never_buffers_an_upload(tmp_path, monkeypatch):
    # Starlette's form parser spools every file to a temporary file before the route runs
    def refuse(*args, **kwargs):
        raise AssertionError("the form parser was used")

    monkeypatch.setattr("starlette.requests.Request.form", refuse)
    monkeypatch.setattr("starlette.formparsers.MultiPartParser.parse", refuse)
    assert post(client(tmp_path), ("a.md", b"# A")).status_code == 201


# Uploads: the number of files


def tiny(count):
    """`count` Markdown files of one byte each."""
    return [(f"{n}.md", b"#") for n in range(count)]


def test_200_files_in_a_request_are_the_most(tmp_path):
    r = post(client(tmp_path), *tiny(200))
    assert r.status_code == 201
    assert [f["name"] for f in r.json()["files"]] == [f"{n}.md" for n in range(200)]


def test_201_files_in_a_request_are_too_many(tmp_path):
    r = post(client(tmp_path), *tiny(201))
    assert (r.status_code, r.json()) == (400, {"error": "Too many files (limit 200)"})
    assert on_disk(tmp_path) == ["jobs"]


def test_the_201st_file_is_refused_when_its_headers_end_and_not_a_byte_of_it_is_written(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path, token=None)
    held = []
    rmtree = shutil.rmtree

    def spy(path, *args, **kwargs):  # the files the job folder held when it was thrown away
        held.append(sum(1 for p in Path(path).rglob("*") if p.is_file()))
        rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", spy)
    piece = 64 * 1024
    parts = [("files[]", name, data) for name, data in tiny(200)]
    parts.append(("files[]", "last.md", b"x" * (100 * piece)))  # 6.4 MB
    body, content_type = multipart(*parts)
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    headers = [("content-type", content_type)]
    wired = asyncio.run(wire(app, "POST", "/api/jobs", headers=headers, chunks=chunks))
    assert (wired.status, wired.json()) == (400, {"error": "Too many files (limit 200)"})
    assert (
        wired.pulled == 1
    )  # the headers of the 201st were in the first piece: its data, never read
    assert held == [200]  # the 201st was never opened
    assert on_disk(tmp_path) == ["jobs"]


# Uploads: options


def test_options_are_kept_in_the_job(tmp_path):
    c = client(tmp_path)
    options = {
        "device": "x3",
        "firmware": "crosspoint",
        "formats": ["epub"],
        "size": "small",
        "mode": "reflow",
        "landscape": False,
        "ocr": "off",
        "title": "A Title",
        "author": "An Author",
        "lang": "id",
        "font_size": 40,
    }
    job = post(c, ("a.md", b"# A"), options=options).json()
    assert job["options"] == options
    assert c.get(f"/api/jobs/{job['id']}").json()["options"] == options  # and after a reload


def test_options_that_the_api_showed_are_taken_back_by_rebuild(tmp_path):
    c = client(tmp_path)
    job = post(c, ("a.md", b"# A"), options={"device": "x3", "title": "T"}).json()
    r = c.post(f"/api/jobs/{job['id']}/rebuild", json={**job["options"], "size": "best"})
    assert r.status_code == 201
    assert r.json()["options"] == {**job["options"], "size": "best"}


def test_missing_options_mean_the_defaults(tmp_path):
    job = post(client(tmp_path), ("a.md", b"# A")).json()
    assert job["options"] == {**asdict(Options()), "formats": ["epub"]}


def test_options_may_come_after_the_files(tmp_path):
    good, content_type = multipart(
        ("files[]", "a.md", b"# A"), ("options", None, b'{"device": "x3"}')
    )
    c = client(tmp_path / "ok")
    r = c.post("/api/jobs", content=good, headers={"content-type": content_type})
    assert (r.status_code, r.json()["options"]["device"]) == (201, "x3")
    bad, content_type = multipart(
        ("files[]", "a.md", b"# A"), ("options", None, b'{"device": "x5"}')
    )
    c = client(tmp_path / "bad")
    r = c.post("/api/jobs", content=bad, headers={"content-type": content_type})
    assert (r.status_code, r.json()) == (422, {"error": "unknown device: 'x5'"})
    assert on_disk(tmp_path / "bad") == ["jobs"]  # the file that came first is thrown away


def test_an_empty_title_author_and_language_are_not_set(tmp_path):
    job = post(client(tmp_path), ("a.md", b"# A"), options={"title": "", "author": "", "lang": ""})
    assert [job.json()["options"][k] for k in ("title", "author", "lang")] == [None] * 3


def test_other_form_fields_are_ignored(tmp_path):
    body, content_type = multipart(("note", None, b"hello"), ("files[]", "a.md", b"# A"))
    r = client(tmp_path).post("/api/jobs", content=body, headers={"content-type": content_type})
    assert r.status_code == 201 and len(r.json()["files"]) == 1


def test_the_field_may_be_called_files_too(tmp_path):
    body, content_type = multipart(("files", "a.md", b"# A"))
    r = client(tmp_path).post("/api/jobs", content=body, headers={"content-type": content_type})
    assert r.status_code == 201 and len(r.json()["files"]) == 1


FONT_SIZE = "font_size must be a whole number from 8 to 96"
BAD_OPTIONS = [
    ({"device": "x5"}, "unknown device: 'x5'"),
    ({"firmware": "kindle"}, "unknown firmware: 'kindle'"),
    ({"formats": ["xtc"]}, "unknown format: 'xtc'"),
    ({"size": "huge"}, "unknown size: 'huge'"),
    ({"mode": "wide"}, "unknown mode: 'wide'"),
    ({"ocr": "maybe"}, "unknown ocr: 'maybe'"),
    ({"font_size": 4}, FONT_SIZE),
    ({"font_size": 97}, FONT_SIZE),
    ({"font_size": "40"}, FONT_SIZE),
    ({"font_size": 40.5}, FONT_SIZE),
    ({"font_size": True}, FONT_SIZE),  # goes into Typst source: only a plain number may
    ({"font_size": '12pt); #read("x"'}, FONT_SIZE),
    ({"formats": "epub"}, "Invalid value for formats"),
    ({"formats": []}, "Invalid value for formats"),
    ({"formats": [1]}, "Invalid value for formats"),
    ({"device": ["x4"]}, "Invalid value for device"),
    ({"device": None}, "Invalid value for device"),
    ({"landscape": "yes"}, "Invalid value for landscape"),
    ({"title": 5}, "Invalid value for title"),
    ({"lang": ["id"]}, "Invalid value for lang"),
    ({"colour": "red"}, "Unknown option: colour"),
    ("not json", "The options are not valid JSON"),
    ('{"device": ', "The options are not valid JSON"),
    ("[" * 60_000, "The options are not valid JSON"),  # too deep for the JSON reader
    ("[1, 2]", "The options must be a JSON object"),
    ('"x4"', "The options must be a JSON object"),
    ("x" * 70_000, "The options are too long"),
]


@pytest.mark.parametrize("options, message", BAD_OPTIONS, ids=lambda v: repr(v)[:30])
def test_invalid_options_are_422_with_the_reason_and_leave_nothing(tmp_path, options, message):
    c = client(tmp_path)
    r = post(c, ("a.md", b"# A"), options=options)
    assert (r.status_code, r.json()) == (422, {"error": message})
    assert on_disk(tmp_path) == ["jobs"]


def test_invalid_options_before_the_files_stop_the_upload_early(tmp_path):
    app = create_app(tmp_path, token=None)
    piece = 64 * 1024
    body, content_type = multipart(
        ("options", None, b'{"device": "x5"}'), ("files[]", "a.md", b"x" * (100 * piece))
    )
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    wired = asyncio.run(
        wire(app, "POST", "/api/jobs", headers=[("content-type", content_type)], chunks=chunks)
    )
    assert (wired.status, wired.json()) == (422, {"error": "unknown device: 'x5'"})
    assert wired.pulled == 1  # the options were in the first piece: the file was never read


# Job info


def test_post_returns_the_new_job(tmp_path):
    c = client(tmp_path)
    r = post(c, ("a.md", b"# A\n"), ("b.PDF", b"%PDF-1.4"))
    assert r.status_code == 201
    job = r.json()
    assert set(job) == {"id", "status", "created", "position", "options", "files"}
    assert re.fullmatch(r"[0-9a-f]{16}", job["id"])
    assert (job["status"], job["position"]) == ("queued", 0)
    nothing = {"error": None, "outputs": {}, "sizes": {}}
    assert job["files"] == [
        {"index": 0, "name": "a.md", "kind": "md", "size": 4, **nothing},
        {"index": 1, "name": "b.PDF", "kind": "pdf", "size": 8, **nothing},
    ]


def test_a_file_that_is_gone_from_the_disk_shows_no_size(tmp_path):
    app = create_app(tmp_path, token=None)
    c = TestClient(app, base_url=LOCAL)
    job = post(c, ("a.md", b"# A")).json()
    Path(app.state.store.get(job["id"]).files[0].path).unlink()
    assert c.get(f"/api/jobs/{job['id']}").json()["files"][0]["size"] is None


def test_the_second_job_waits_in_the_queue(tmp_path):
    c = client(tmp_path)
    first = post(c, ("a.md", b"# A")).json()
    second = post(c, ("b.md", b"# B")).json()
    assert (first["position"], second["status"], second["position"]) == (0, "queued", 1)


def test_get_one_job_and_the_list_newest_first(tmp_path):
    app = create_app(tmp_path, token=None)
    c = TestClient(app, base_url=LOCAL)
    a = post(c, ("a.md", b"# A")).json()
    backdate(app.state.store, a["id"], 100)
    b = post(c, ("b.md", b"# B")).json()
    assert c.get(f"/api/jobs/{a['id']}").json() == {**a, "created": a["created"] - 100}
    assert c.get(f"/api/jobs/{b['id']}").json() == b
    assert [job["id"] for job in c.get("/api/jobs").json()] == [b["id"], a["id"]]


def test_the_list_holds_the_20_most_recent_jobs(tmp_path):
    app = create_app(tmp_path, token=None)
    store = app.state.store
    ids = []
    for n in range(25):
        info = store.create([("a.md", io.BytesIO(b"# A"))], Options())
        info.created = 1000 + n
        store.save(info)
        ids.append(info.id)
    listing = TestClient(app, base_url=LOCAL).get("/api/jobs").json()
    assert [job["id"] for job in listing] == ids[::-1][:20]


ROUTES = [
    ("GET", "{id}"),
    ("GET", "{id}/events"),
    ("POST", "{id}/cancel"),
    ("POST", "{id}/rebuild"),
    ("GET", "{id}/files/0/download/epub"),
]


@pytest.mark.parametrize("method, route", ROUTES)
@pytest.mark.parametrize(
    "job_id", ["0123456789abcdef", "nope", "0123456789ABCDEF", "a" * 17, "%2e%2e"]
)
def test_an_unknown_job_is_404_on_every_route(tmp_path, method, route, job_id):
    r = client(tmp_path).request(method, "/api/jobs/" + route.format(id=job_id))
    assert (r.status_code, r.json()) == (404, {"error": "No such job"})


# Events


def test_events_give_stage_page_and_finding_and_end_last(finished):
    events = sse(finished.live)
    assert events[0] == {"type": "file", "index": 0, "status": "started"}
    assert {"stage", "page", "finding"} <= {e["type"] for e in events}
    assert {"type": "stage", "stage": "layout", "status": "started"} in events
    assert [e for e in events if e["type"] == "page"][:3] == [
        {"type": "page", "done": done, "total": 3} for done in (1, 2, 3)
    ]
    found = {
        "type": "finding",
        "page": 2,
        "kind": "blank_page",
        "level": "info",
        "message": "Blank page skipped.",
    }
    assert found in events
    assert events[-1] == {"type": "end", "status": "done"}
    assert [e["type"] for e in events].count("end") == 1  # the one end is the last event


def test_a_second_connection_after_the_end_replays_the_same_events(finished):
    assert sse(finished.replay) == sse(finished.live)
    assert finished.replay == finished.live  # byte for byte


def test_the_stream_is_an_event_stream_and_is_not_cached(finished):
    r = finished.client.get(f"/api/jobs/{finished.id}/events")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/event-stream"
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_job_that_has_ended_leaves_no_subscriber(finished):
    assert finished.app.state.runner._subs == {}


def test_a_file_result_shows_the_name_and_size_of_its_output_not_its_path(finished):
    done = [e for e in sse(finished.live) if e["type"] == "file" and e["status"] == "done"]
    assert [e["outputs"] for e in done] == [
        {"epub": "Bab Ü.x4.epub"},
        {"epub": "notes.x4.epub"},
    ]
    assert all("book_dir" not in e for e in done)


def test_reloading_mid_conversion_restores_the_state(tmp_path, fake_worker):
    app = create_app(tmp_path, token=None)
    with TestClient(app, base_url=LOCAL) as c:
        store = app.state.store
        job_id = post(c, ("a.md", b"# A"), ("b.md", b"# B"), ("c.md", b"# C")).json()["id"]
        wait_for(lambda: len(store.events(job_id)) >= 4, 20)  # a file, a stage, two pages
        before = [e["type"] for e in store.events(job_id)]
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "running"
        # the page is loaded again: the job, then the events from the first one
        reloaded = sse(c.get(f"/api/jobs/{job_id}/events").text)
        assert [e["type"] for e in reloaded][: len(before)] == before
        assert len(reloaded) > len(before)  # and on to the end, live
        assert reloaded[-1] == {"type": "end", "status": "done"}
        assert sse(c.get(f"/api/jobs/{job_id}/events").text) == reloaded
        done = c.get(f"/api/jobs/{job_id}").json()
        assert [f["outputs"] for f in done["files"]] == [
            {"epub": "a.x4.epub"},
            {"epub": "b.x4.epub"},
            {"epub": "c.x4.epub"},
        ]


def test_the_stream_stops_listening_when_the_client_disconnects(tmp_path, monkeypatch):
    app = create_app(tmp_path, token=None)
    runner, store = app.state.runner, app.state.store
    job = store.create([("a.md", io.BytesIO(b"# A"))], Options())  # never submitted: no end
    unsubscribed = []
    unsubscribe = runner.unsubscribe
    monkeypatch.setattr(runner, "unsubscribe", lambda *a: (unsubscribed.append(a), unsubscribe(*a)))

    async def main():
        gone = asyncio.Event()
        call = asyncio.create_task(wire(app, "GET", f"/api/jobs/{job.id}/events", gone=gone))
        await subscribed(runner, job.id)
        assert len(runner._subs[job.id]) == 1  # the stream is open, on a queue of its own
        assert not call.done()
        gone.set()  # the browser closes the tab
        return await asyncio.wait_for(call, 5)

    wired = asyncio.run(main())
    assert wired.status == 200
    assert runner._subs == {}
    assert [(a[0], a[1].empty()) for a in unsubscribed] == [(job.id, True)]


def test_the_stream_stops_listening_when_the_server_cancels_it(tmp_path):
    app = create_app(tmp_path, token=None)
    runner, store = app.state.runner, app.state.store
    job = store.create([("a.md", io.BytesIO(b"# A"))], Options())

    async def main():
        call = asyncio.create_task(
            wire(app, "GET", f"/api/jobs/{job.id}/events", gone=asyncio.Event())
        )
        await subscribed(runner, job.id)
        call.cancel()  # as uvicorn does to a task that outlives its graceful shutdown
        with pytest.raises(asyncio.CancelledError):
            await call

    asyncio.run(main())
    assert runner._subs == {}


def test_a_stream_of_a_finished_job_ends_by_itself_and_registers_nothing(tmp_path):
    app = create_app(tmp_path, token=None)
    job = done_job(app.state.store)
    wired = asyncio.run(wire(app, "GET", f"/api/jobs/{job.id}/events"))
    assert sse(wired.body.decode()) == [{"type": "end", "status": "done"}]
    assert app.state.runner._subs == {}


def test_the_stream_gives_the_events_of_a_job_as_they_come(tmp_path):
    app = create_app(tmp_path, token=None)
    runner, store = app.state.runner, app.state.store
    job = store.create([("a.md", io.BytesIO(b"# A"))], Options())
    store.append_event(job.id, {"type": "file", "index": 0, "status": "started"})

    async def main():
        call = asyncio.create_task(
            wire(app, "GET", f"/api/jobs/{job.id}/events", gone=asyncio.Event())
        )
        await subscribed(runner, job.id)
        with runner._lock:  # what the runner does for an event
            runner._publish(job, {"type": "page", "done": 1, "total": 2}, save=False)
            runner._publish(job, {"type": "end", "status": "done"}, save=False)
        return await asyncio.wait_for(call, 5)

    wired = asyncio.run(main())
    assert sse(wired.body.decode()) == [
        {"type": "file", "index": 0, "status": "started"},
        {"type": "page", "done": 1, "total": 2},
        {"type": "end", "status": "done"},
    ]
    assert runner._subs == {}


def test_a_quiet_stream_sends_a_keepalive_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "KEEPALIVE", 0.1)
    app = create_app(tmp_path, token=None)
    job = app.state.store.create([("a.md", io.BytesIO(b"# A"))], Options())  # never ends

    async def main():
        gone = asyncio.Event()
        call = asyncio.create_task(wire(app, "GET", f"/api/jobs/{job.id}/events", gone=gone))
        await asyncio.sleep(0.6)
        gone.set()
        return await asyncio.wait_for(call, 5)

    wired = asyncio.run(main())
    sent = [m["body"] for m in wired.messages[1:] if m.get("body")]
    assert 2 <= len(sent) <= 12 and set(sent) == {b": keepalive\n\n"}


def test_events_hold_the_keepalive_back(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "KEEPALIVE", 0.3)
    app = create_app(tmp_path, token=None)
    runner, store = app.state.runner, app.state.store
    job = store.create([("a.md", io.BytesIO(b"# A"))], Options())

    async def main():
        call = asyncio.create_task(
            wire(app, "GET", f"/api/jobs/{job.id}/events", gone=asyncio.Event())
        )
        await subscribed(runner, job.id)
        for done in range(1, 7):  # an event every 0.1 s, for twice the keepalive time
            with runner._lock:
                runner._publish(job, {"type": "page", "done": done, "total": 6}, save=False)
            await asyncio.sleep(0.1)
        with runner._lock:
            runner._publish(job, {"type": "end", "status": "done"}, save=False)
        return await asyncio.wait_for(call, 5)

    wired = asyncio.run(main())
    events = sse(wired.body.decode())  # one comment would break this: it takes only `data:` lines
    assert [e["type"] for e in events] == ["page"] * 6 + ["end"]


def test_the_stop_flag_is_the_apps_own_and_starts_clear(tmp_path):
    one, two = create_app(tmp_path / "one", token=None), create_app(tmp_path / "two", token=None)
    assert isinstance(one.state.stopping, threading.Event) and not one.state.stopping.is_set()
    one.state.stopping.set()
    assert not two.state.stopping.is_set()


def test_a_stream_ends_with_no_end_event_when_the_server_is_stopping(tmp_path):
    app = create_app(tmp_path, token=None)
    runner = app.state.runner
    job = app.state.store.create([("a.md", io.BytesIO(b"# A"))], Options())  # never ends

    async def main():
        call = asyncio.create_task(
            wire(app, "GET", f"/api/jobs/{job.id}/events", gone=asyncio.Event())
        )
        await subscribed(runner, job.id)
        app.state.stopping.set()
        return await asyncio.wait_for(call, 2)

    wired = asyncio.run(main())
    assert (wired.status, wired.body) == (
        200,
        b"",
    )  # nothing, and not the `end` of a job that has not ended
    assert runner._subs == {}


def test_a_server_that_is_told_to_stop_sets_the_flag_before_uvicorn_acts(tmp_path, monkeypatch):
    app = create_app(tmp_path, token=None)
    seen = []
    handle_exit = uvicorn.Server.handle_exit

    def spy(self, sig, frame):
        seen.append(app.state.stopping.is_set())  # as uvicorn begins
        handle_exit(self, sig, frame)

    monkeypatch.setattr(uvicorn.Server, "handle_exit", spy)
    server = web_app.Server(uvicorn.Config(app, host="127.0.0.1", port=0))
    server.handle_exit(signal.SIGTERM, None)
    assert seen == [True] and server.should_exit and app.state.stopping.is_set()


def test_one_ctrl_c_stops_the_server_even_with_a_stream_open(tmp_path, monkeypatch):
    app = create_app(tmp_path, token=None)
    stops = []
    stop = Runner.stop
    monkeypatch.setattr(Runner, "stop", lambda self: (stops.append(self), stop(self))[1])
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", timeout_graceful_shutdown=5
    )
    server = web_app.Server(config)
    logged = Records()  # added after the Config, which sets the logging up
    loggers = [logging.getLogger(), logging.getLogger("uvicorn")]  # this one passes nothing up
    for logger in loggers:
        logger.addHandler(logged)
    try:
        with serving(app, server) as live:
            # made after the start, so the runner never queues it: its stream has no end
            job = app.state.store.create([("a.md", io.BytesIO(b"# A"))], Options())
            read, failed = [], []

            def open_stream():
                try:
                    with httpx.stream(
                        "GET", f"{live.url}/api/jobs/{job.id}/events", timeout=30
                    ) as r:
                        read.extend(r.iter_lines())
                except Exception as e:  # noqa: BLE001  the test reports it
                    failed.append(e)

            reader = threading.Thread(target=open_stream, daemon=True)
            reader.start()
            wait_for(lambda: app.state.runner._subs.get(job.id), 10)  # the stream is open
            server.handle_exit(signal.SIGINT, None)  # Ctrl+C
            live.thread.join(2)
            assert not live.thread.is_alive(), "the server still runs 2 s after Ctrl+C"
            reader.join(5)
        assert (read, failed) == ([], [])  # the stream ended, by the server, with nothing
        assert app.state.runner._subs == {}
        assert len(stops) == 1  # runner.stop() ran: the lifespan ended
        assert [r.getMessage() for r in logged.records if r.levelno >= logging.ERROR] == []
    finally:
        for logger in loggers:
            logger.removeHandler(logged)


# Cancel


def test_cancel_a_queued_job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_work", endless_work)
    app = create_app(tmp_path, token=None)
    with TestClient(app, base_url=LOCAL) as c:
        a = post(c, ("a.md", b"# A")).json()
        wait_for(lambda: app.state.store.events(a["id"]), 20)  # a runs and never ends
        b = post(c, ("b.md", b"# B")).json()
        assert (b["status"], b["position"]) == ("queued", 1)
        r = c.post(f"/api/jobs/{b['id']}/cancel")
        assert (r.status_code, r.json()["id"], r.json()["status"]) == (202, b["id"], "cancelled")
        assert sse(c.get(f"/api/jobs/{b['id']}/events").text) == [
            {"type": "end", "status": "cancelled"}
        ]
        assert c.get(f"/api/jobs/{a['id']}").json()["status"] == "running"  # a is not touched
        again = c.post(f"/api/jobs/{b['id']}/cancel")  # it is over
        assert (again.status_code, again.json()) == (
            409,
            {"error": "This job has already finished"},
        )


def test_cancel_a_running_job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_work", endless_work)
    app = create_app(tmp_path, token=None)
    with TestClient(app, base_url=LOCAL) as c:
        a = post(c, ("a.md", b"# A")).json()
        wait_for(lambda: app.state.store.events(a["id"]), 20)
        r = c.post(f"/api/jobs/{a['id']}/cancel")
        assert (r.status_code, r.json()["id"]) == (202, a["id"])
        wait_for(lambda: c.get(f"/api/jobs/{a['id']}").json()["status"] == "cancelled", 15)
        events = sse(c.get(f"/api/jobs/{a['id']}/events").text)
        assert events[-1] == {"type": "end", "status": "cancelled"}


def test_cancel_a_job_that_has_finished_is_409(tmp_path):
    app = create_app(tmp_path, token=None)
    job = done_job(app.state.store)
    r = TestClient(app, base_url=LOCAL).post(f"/api/jobs/{job.id}/cancel")
    assert (r.status_code, r.json()) == (409, {"error": "This job has already finished"})


# Rebuild


def test_rebuild_makes_a_new_job_from_the_same_files(tmp_path):
    app = create_app(tmp_path, token=None)
    c = TestClient(app, base_url=LOCAL)
    old = post(
        c, ("Bab Ü.md", "# Ü\n".encode()), ("b.pdf", b"%PDF-1.4 x"), options={"device": "x4"}
    ).json()
    backdate(app.state.store, old["id"], 100)
    r = c.post(f"/api/jobs/{old['id']}/rebuild", json={"device": "x3", "size": "small"})
    assert r.status_code == 201
    new = r.json()
    assert new["id"] != old["id"] and (new["status"], new["position"]) == ("queued", 1)
    assert [(f["name"], f["kind"], f["size"]) for f in new["files"]] == [
        (f["name"], f["kind"], f["size"]) for f in old["files"]
    ]
    assert (new["options"]["device"], new["options"]["size"]) == ("x3", "small")
    assert c.get(f"/api/jobs/{old['id']}").json() == {**old, "created": old["created"] - 100}
    store = app.state.store
    assert [Path(f.path).read_bytes() for f in store.get(new["id"]).files] == [
        Path(f.path).read_bytes() for f in store.get(old["id"]).files
    ]
    assert [job["id"] for job in c.get("/api/jobs").json()] == [new["id"], old["id"]]


def test_rebuild_of_two_uploads_with_one_name_keeps_both_in_the_new_layout(tmp_path):
    c = client(tmp_path)
    old = post(c, ("a.md", b"# One"), ("a.md", b"# Two")).json()
    new = c.post(f"/api/jobs/{old['id']}/rebuild", json={"size": "small"}).json()
    assert [(f["index"], f["name"]) for f in new["files"]] == [(0, "a.md"), (1, "a.md")]
    assert stored(tmp_path, new["id"]) == ["0/a.md", "1/a.md"]
    inputs = tmp_path / "jobs" / new["id"] / "input"
    assert [(inputs / n / "a.md").read_bytes() for n in "01"] == [b"# One", b"# Two"]


def test_rebuild_without_options_uses_the_defaults(tmp_path):
    c = client(tmp_path)
    old = post(c, ("a.md", b"# A"), options={"device": "x3"}).json()
    r = c.post(f"/api/jobs/{old['id']}/rebuild")
    assert (r.status_code, r.json()["options"]["device"]) == (201, "x4")


@pytest.mark.parametrize(
    "body, message",
    [
        (b'{"device": "x5"}', "unknown device: 'x5'"),
        (b'{"font_size": 200}', FONT_SIZE),
        (b'{"formats": ["pdf"]}', "unknown format: 'pdf'"),
        (b"not json", "The options are not valid JSON"),
        (b"[1]", "The options must be a JSON object"),
        (b"x" * 70_000, "The options are too long"),
    ],
)
def test_rebuild_with_invalid_options_is_422_and_makes_no_job(tmp_path, body, message):
    c = client(tmp_path)
    old = post(c, ("a.md", b"# A")).json()
    r = c.post(f"/api/jobs/{old['id']}/rebuild", content=body)
    assert (r.status_code, r.json()) == (422, {"error": message})
    assert [job["id"] for job in c.get("/api/jobs").json()] == [old["id"]]
    assert len(list((tmp_path / "jobs").iterdir())) == 1


def test_rebuild_of_a_finished_job_runs_again(tmp_path, fake_worker):
    with running(tmp_path) as c:
        old = post(c, ("a.md", b"# A")).json()
        wait_for(lambda: c.get(f"/api/jobs/{old['id']}").json()["status"] == "done", 20)
        new = c.post(f"/api/jobs/{old['id']}/rebuild", json={"size": "best"}).json()
        wait_for(lambda: c.get(f"/api/jobs/{new['id']}").json()["status"] == "done", 20)
        done = c.get(f"/api/jobs/{new['id']}").json()
        assert done["options"]["size"] == "best"
        assert done["files"][0]["outputs"] == {"epub": "a.x4.epub"}


# Downloads


def test_a_file_with_a_non_ascii_name_downloads(finished):
    r = finished.client.get(f"/api/jobs/{finished.id}/files/0/download/epub")
    assert r.status_code == 200
    assert r.content == b"not a real EPUB"
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"Bab _.x4.epub\"; filename*=UTF-8''Bab%20%C3%9C.x4.epub"
    )
    assert r.headers["content-type"] == "application/epub+zip"
    assert r.headers["content-length"] == str(len(r.content))


def test_every_file_of_a_job_downloads(finished):
    r = finished.client.get(f"/api/jobs/{finished.id}/files/1/download/epub")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        "attachment; filename=\"notes.x4.epub\"; filename*=UTF-8''notes.x4.epub"
    )


def test_the_ascii_name_of_a_download_has_no_quote_backslash_control_or_non_ascii_character():
    # `safe_name` lets none of the first three through, so an upload cannot show this by itself
    name = 'a"b\\c\x01d\x7fé€ f.epub'
    assert web_app._disposition(name) == (
        'attachment; filename="a_b_c_d___ f.epub"; '
        "filename*=UTF-8''a%22b%5Cc%01d%7F%C3%A9%E2%82%AC%20f.epub"
    )


def test_an_ascii_name_is_the_same_in_both_forms():
    assert web_app._disposition("book.x4.epub") == (
        "attachment; filename=\"book.x4.epub\"; filename*=UTF-8''book.x4.epub"
    )


@pytest.mark.parametrize(
    "path, message",
    [
        ("files/2/download/epub", "No such file in this job"),
        ("files/-1/download/epub", "No such file in this job"),
        ("files/x/download/epub", "No such file in this job"),
        ("files/00/download/epub", "No such file in this job"),
        ("files/%2B1/download/epub", "No such file in this job"),
        ("files/99999999999999999999/download/epub", "No such file in this job"),
        ("files/0/download/pdf", "No such output file"),
        ("files/0/download/EPUB", "No such output file"),
        ("files/0/download/job.json", "No such output file"),
    ],
)
def test_a_download_that_does_not_exist_is_404(finished, path, message):
    r = finished.client.get(f"/api/jobs/{finished.id}/{path}")
    assert (r.status_code, r.json()) == (404, {"error": message})


def test_a_file_that_did_not_convert_has_nothing_to_download(tmp_path):
    app = create_app(tmp_path, token=None)
    job = app.state.store.create([("a.md", io.BytesIO(b"# A"))], Options())
    r = TestClient(app, base_url=LOCAL).get(f"/api/jobs/{job.id}/files/0/download/epub")
    assert (r.status_code, r.json()) == (404, {"error": "No such output file"})


def test_an_output_that_is_gone_from_the_disk_is_404(tmp_path):
    app = create_app(tmp_path, token=None)
    job = done_job(app.state.store)
    Path(app.state.store.get(job.id).files[0].outputs["epub"]).unlink()
    r = TestClient(app, base_url=LOCAL).get(f"/api/jobs/{job.id}/files/0/download/epub")
    assert (r.status_code, r.json()) == (404, {"error": "No such output file"})


def test_a_download_never_leaves_the_output_folder(tmp_path):
    app = create_app(tmp_path, token=None)
    store = app.state.store
    job = done_job(store)
    secret = tmp_path / "secret.txt"
    secret.write_text("the secret")
    info = store.get(job.id)
    info.files[0].outputs = {"epub": str(secret)}  # as a job.json written by hand would say
    store.save(info)
    r = TestClient(app, base_url=LOCAL).get(f"/api/jobs/{job.id}/files/0/download/epub")
    assert (r.status_code, "the secret" in r.text) == (404, False)


# What the API shows


def test_no_json_of_the_api_shows_a_path_of_the_server(finished):
    c = finished.client
    documents = [
        finished.posted.json(),
        c.get(f"/api/jobs/{finished.id}").json(),
        c.get("/api/jobs").json(),
        c.get(f"/api/jobs/{finished.id}/files/9/download/epub").json(),
        c.get("/api/jobs/nope").json(),
        sse(finished.live),
        sse(finished.replay),
    ]
    assert_no_path(documents, finished.data)


def test_the_finished_job_as_the_api_shows_it(finished):
    job = finished.client.get(f"/api/jobs/{finished.id}").json()
    assert (job["status"], job["position"]) == ("done", 0)
    assert job["files"] == [
        {
            "index": 0,
            "name": "Bab Ü.md",
            "kind": "md",
            "size": 4,
            "error": None,
            "outputs": {"epub": "Bab Ü.x4.epub"},
            "sizes": {"epub": 15},
        },
        {
            "index": 1,
            "name": "notes.md",
            "kind": "md",
            "size": 4,
            "error": None,
            "outputs": {"epub": "notes.x4.epub"},
            "sizes": {"epub": 15},
        },
    ]


def test_a_path_in_an_error_message_is_not_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_work", failing_work)
    app = create_app(tmp_path, token=None)
    with TestClient(app, base_url=LOCAL) as c:
        job = post(c, ("a.md", b"# A")).json()
        wait_for(lambda: c.get(f"/api/jobs/{job['id']}").json()["status"] == "failed", 20)
        stored = app.state.store.get(job["id"]).files[0].error
        assert str(tmp_path) in stored.replace("\\\\", "\\")  # the worker did name the path
        shown = c.get(f"/api/jobs/{job['id']}").json()
        events = sse(c.get(f"/api/jobs/{job['id']}/events").text)
        failed = next(e for e in events if e["status"] == "failed")
        for error in (shown["files"][0]["error"], failed["error"]):
            assert error.startswith("[Errno 13] Permission denied: '<data>")
        assert_no_path([shown, c.get("/api/jobs").json(), events], tmp_path)


# Errors


@pytest.mark.parametrize(
    "method, path, status",
    [
        ("GET", "/api/nope", 404),
        ("GET", "/api/jobs/0123456789abcdef/nope", 404),
        ("GET", "/static/missing.css", 404),
        ("GET", "/nope", 404),
        ("DELETE", "/api/jobs", 405),
        ("PUT", "/api/jobs/0123456789abcdef", 405),
        ("GET", "/api/jobs/0123456789abcdef/cancel", 405),
        ("POST", "/api/jobs/0123456789abcdef/events", 405),
        ("POST", "/", 405),
    ],
)
def test_fastapis_own_errors_are_json_with_an_error_key(tmp_path, method, path, status):
    r = client(tmp_path).request(method, path)
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/json")
    assert list(r.json()) == ["error"] and r.json()["error"]
    assert ("allow" in r.headers) == (status == 405)


def test_a_request_that_fastapi_cannot_read_is_422_with_an_error_key(tmp_path):
    app = create_app(tmp_path, token=None)

    @app.get("/api/typed/{n}")
    def typed(n: int):
        return {"n": n}

    c = TestClient(app, base_url=LOCAL)
    assert c.get("/api/typed/3").json() == {"n": 3}
    r = c.get("/api/typed/abc")
    assert r.status_code == 422
    assert list(r.json()) == ["error"] and "n" in r.json()["error"]


def test_an_unexpected_error_is_json_too(tmp_path):
    app = create_app(tmp_path, token=None)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("boom")

    r = TestClient(app, base_url=LOCAL, raise_server_exceptions=False).get("/api/boom")
    assert (r.status_code, r.json()) == (500, {"error": "Something went wrong on the server"})
    assert r.headers["x-frame-options"] == "DENY"  # still through the guard


# Network mode


def test_the_api_needs_the_token_and_works_with_it(tmp_path):
    app = create_app(tmp_path, token="s3cret")
    c = TestClient(app, base_url=LOCAL)
    job = done_job(app.state.store)
    base = f"/api/jobs/{job.id}"
    calls = [
        ("GET", "/api/jobs"),
        ("POST", "/api/jobs"),
        ("GET", base),
        ("GET", f"{base}/events"),
        ("POST", f"{base}/cancel"),
        ("POST", f"{base}/rebuild"),
        ("GET", f"{base}/files/0/download/epub"),
    ]
    for method, path in calls:
        r = c.request(method, path)
        assert (r.status_code, r.json()) == (401, {"error": "Missing or invalid token"}), path
    auth = {"Authorization": "Bearer s3cret"}
    assert sse(c.get(f"{base}/events", headers=auth).text) == [{"type": "end", "status": "done"}]
    assert c.get(f"{base}/files/0/download/epub", headers=auth).content == b"an EPUB"
    r = post(c, ("../../x.pdf", b"%PDF-1.4"), headers=auth)
    assert r.status_code == 201
    assert stored(tmp_path, r.json()["id"]) == ["0/x.pdf"]
    assert not (tmp_path.parent / "x.pdf").exists() and not (tmp_path / "x.pdf").exists()


# The real worker and the real server


def test_a_markdown_book_converts_through_the_real_worker_and_downloads(tmp_path):
    with running(tmp_path) as c:
        job = post(c, ("Bab Ü.md", BOOK)).json()
        wait_for(
            lambda: c.get(f"/api/jobs/{job['id']}").json()["status"] in ("done", "failed"), 120
        )
        events = sse(c.get(f"/api/jobs/{job['id']}/events").text)
        assert events[-1] == {"type": "end", "status": "done"}
        assert {"file", "stage"} <= {e["type"] for e in events}
        [done] = [e for e in events if e["type"] == "file" and e["status"] == "done"]
        assert done["outputs"] == {"epub": "Bab Ü.x4.epub"}
        assert done["sizes"]["epub"] > 0 and "book_dir" not in done
        shown = c.get(f"/api/jobs/{job['id']}").json()
        assert shown["files"][0]["outputs"] == done["outputs"]  # the job and its event agree
        assert shown["files"][0]["sizes"] == done["sizes"]
        assert_no_path([shown, events], tmp_path)
        got = c.get(f"/api/jobs/{job['id']}/files/0/download/epub")
        assert got.headers["content-disposition"] == (
            "attachment; filename=\"Bab _.x4.epub\"; filename*=UTF-8''Bab%20%C3%9C.x4.epub"
        )
        assert len(got.content) == done["sizes"]["epub"]
        with zipfile.ZipFile(io.BytesIO(got.content)) as z:
            assert z.namelist()[0] == "mimetype"
            assert z.read("mimetype") == b"application/epub+zip"
        assert epub_title(io.BytesIO(got.content)) == "Bab Ü"  # the upload's name, as it came


def test_a_real_server_streams_events_as_they_happen_and_drops_a_closed_stream(
    tmp_path, fake_worker
):
    app = create_app(tmp_path, token=None)
    with serving(app) as live, httpx.Client(base_url=live.url, timeout=60) as c:
        job = c.post("/api/jobs", files=[("files[]", ("a.md", b"# A"))]).json()
        with c.stream("GET", f"/api/jobs/{job['id']}/events") as r:
            assert r.headers["content-type"] == "text/event-stream"
            lines = r.iter_lines()
            first = next(line for line in lines if line)
            assert json.loads(first.removeprefix("data: ")) == {
                "type": "file",
                "index": 0,
                "status": "started",
            }
            # that came while the job runs: the stream is not held back until its end
            assert app.state.store.get(job["id"]).status == "running"
            assert len(app.state.runner._subs[job["id"]]) == 1
        # the connection is closed now
        wait_for(lambda: app.state.runner._subs == {}, 10)
        wait_for(lambda: c.get(f"/api/jobs/{job['id']}").json()["status"] == "done", 20)


def test_a_real_server_refuses_a_large_upload_and_goes_on(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    with serving(app) as live, httpx.Client(base_url=live.url, timeout=60) as c:
        r = c.post("/api/jobs", files=[("files[]", ("big.md", b"x" * (8 * MB)))])
        assert (r.status_code, r.json()) == (413, TOO_LARGE)
        assert c.get("/api/jobs").json() == []  # the same connection still works
        ok = c.post("/api/jobs", files=[("files[]", ("small.md", b"# A"))])
        assert ok.status_code == 201
    assert sorted(p.name for p in (tmp_path / "jobs").iterdir() if p.is_dir()) == [ok.json()["id"]]
