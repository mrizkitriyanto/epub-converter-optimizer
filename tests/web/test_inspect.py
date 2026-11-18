"""The inspect route: the pages of one uploaded PDF, and how many of them are scanned.

Select files shows these numbers in each PDF's row before the conversion. The PDF is uploaded the
way a job's files are (streamed to disk, the same limit), read once under the PDFium lock, and
deleted before the answer, so after every request the data folder holds what it held before.
"""

import asyncio
import json
import threading
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from fakes import wire
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from eco.pdf.pages import inspect_pdf
from eco.web import app as web_app
from eco.web import preview
from eco.web.app import _PdfUpload, _Upload, create_app

LOCAL = "http://127.0.0.1:8000"  # a browser on this computer, server on the default port
MB = 1024 * 1024
BOUNDARY = "ecoboundary7d3f"
TOO_LARGE = {"error": "File too large (limit 1 MB)"}
NOT_A_PDF = {"error": "Only PDF files can be inspected"}
RATES = {"digital": 0.7, "scanned": 2.1, "pages": 0.2}
GOOD = "A-z_0123456789ab"  # a token that eco web takes


# Helpers


def client(tmp_path, **kwargs):
    """The app on tmp_path without its lifespan: no runner thread."""
    return TestClient(create_app(tmp_path, token=None, **kwargs), base_url=LOCAL)


def inspect(c, name, data, **kwargs):
    return c.post("/api/inspect", files={"file": (name, data)}, **kwargs)


def multipart(*parts):
    """A multipart/form-data body made by hand. A part is (field, filename or None, bytes).
    Returns the body and its Content-Type."""
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


def assert_no_path(document, root: Path):
    """The JSON document holds neither the data folder nor any absolute path."""
    forms = [str(root), str(root).replace("\\", "\\\\"), root.as_posix()]
    text = json.dumps(document, ensure_ascii=False)
    assert not any(form in text for form in forms), text
    strings = []

    def collect(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                collect(key)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(document)
    for found in strings:
        assert not PurePosixPath(found).is_absolute(), found
        assert not PureWindowsPath(found).is_absolute(), found


@pytest.fixture
def digital(fixtures_dir):
    """Three pages: text, nothing, text."""
    return fixtures_dir["blank"].read_bytes()


@pytest.fixture
def scanned(fixtures_dir):
    """One page that is a picture of a page of text: no text layer."""
    return fixtures_dir["scanned"][0].read_bytes()


@pytest.fixture
def mixed(fixtures_dir):
    """Five pages: the three of `digital`, then two that are one picture each."""
    writer = PdfWriter()
    for page in PdfReader(fixtures_dir["blank"]).pages:
        writer.add_page(page)
    picture = PdfReader(fixtures_dir["photo"][0]).pages[0]
    writer.add_page(picture)
    writer.add_page(picture)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# What it answers


def test_a_digital_pdf_answers_its_pages_and_none_scanned(tmp_path, digital):
    r = inspect(client(tmp_path), "book.pdf", digital)
    assert r.status_code == 200
    assert (r.json()["pages"], r.json()["scanned_pages"]) == (3, 0)


def test_a_pdf_of_pictures_counts_them_as_scanned(tmp_path, scanned, mixed):
    c = client(tmp_path)
    assert [inspect(c, "scan.pdf", scanned).json()[k] for k in ("pages", "scanned_pages")] == [1, 1]
    assert [inspect(c, "mix.pdf", mixed).json()[k] for k in ("pages", "scanned_pages")] == [5, 2]


def test_the_scanned_pages_are_the_ones_the_read_stage_of_the_pipeline_counts(tmp_path, mixed):
    path = tmp_path / "mixed.pdf"
    path.write_bytes(mixed)
    expected = [info.is_scanned for info in inspect_pdf(path)]
    answer = inspect(client(tmp_path / "data"), "mixed.pdf", mixed).json()
    assert (answer["pages"], answer["scanned_pages"]) == (len(expected), sum(expected))


def test_the_answer_is_the_counts_and_the_provisional_rates_and_nothing_else(tmp_path, digital):
    answer = inspect(client(tmp_path), "book.pdf", digital).json()
    assert answer == {"pages": 3, "scanned_pages": 0, "seconds_per_page": RATES}
    assert [type(v) for v in answer["seconds_per_page"].values()] == [float] * 3


@pytest.mark.parametrize("name", ["book.PDF", "My Book.Pdf", "a.b.pdf"])
def test_the_type_is_checked_by_suffix_and_case_does_not_matter(tmp_path, digital, name):
    assert inspect(client(tmp_path), name, digital).status_code == 200


def test_the_answer_is_json_with_no_path_in_it(tmp_path, digital, mixed):
    c = client(tmp_path)
    for name, data in (
        ("a.pdf", digital),
        ("../../x.pdf", mixed),
        ("C:\\Users\\me\\y.pdf", digital),
    ):
        r = inspect(c, name, data)
        assert r.status_code == 200
        assert_no_path(r.json(), tmp_path)


# What it refuses


@pytest.mark.parametrize(
    "name", ["notes.md", "report.DOCX", "book.epub", "no-suffix", "archive.pdf.zip", "pdf"]
)
def test_anything_that_is_not_a_pdf_is_400(tmp_path, digital, name):
    r = inspect(client(tmp_path), name, digital)  # even when its bytes are a PDF
    assert (r.status_code, r.json()) == (400, NOT_A_PDF)
    assert on_disk(tmp_path) == ["jobs"]


def test_two_files_are_400_and_leave_nothing(tmp_path, digital):
    files = [("file", ("a.pdf", digital)), ("file", ("b.pdf", digital))]
    r = client(tmp_path).post("/api/inspect", files=files)
    assert (r.status_code, r.json()) == (400, {"error": "Too many files (limit 1)"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_second_file_after_a_refused_one_changes_nothing(tmp_path, digital):
    files = [("file", ("a.md", b"# A")), ("file", ("b.pdf", digital))]
    r = client(tmp_path).post("/api/inspect", files=files)
    assert (r.status_code, r.json()) == (400, NOT_A_PDF)
    assert on_disk(tmp_path) == ["jobs"]


def test_the_file_goes_in_the_field_file(tmp_path, digital):
    r = client(tmp_path).post("/api/inspect", files={"files[]": ("a.pdf", digital)})
    assert (r.status_code, r.json()) == (400, {"error": "No files were uploaded"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_that_is_not_multipart_is_refused(tmp_path):
    c = client(tmp_path)
    for kwargs in (
        {"json": {"a": 1}},
        {"content": b"x"},
        {"content": b"--b--", "headers": {"content-type": "multipart/form-data"}},
    ):
        r = c.post("/api/inspect", **kwargs)
        assert (r.status_code, r.json()) == (
            400,
            {"error": "Send the files as multipart/form-data"},
        )
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_cut_short_is_refused_and_leaves_nothing(tmp_path, digital):
    body, content_type = multipart(("file", "a.pdf", digital))
    r = client(tmp_path).post(
        "/api/inspect", content=body[:-20], headers={"content-type": content_type}
    )  # the closing boundary never comes
    assert (r.status_code, r.json()) == (400, {"error": "The upload could not be read"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_client_that_leaves_in_the_middle_leaves_nothing(tmp_path, digital):
    app = create_app(tmp_path, token=None)
    body, content_type = multipart(("file", "a.pdf", b"x" * 200_000))
    chunks = [body[i : i + 65536] for i in range(0, 150_000, 65536)]  # 3 pieces, then it is gone
    headers = [("content-type", content_type)]
    wired = asyncio.run(
        wire(app, "POST", "/api/inspect", headers=headers, chunks=chunks, complete=False)
    )
    assert wired.pulled == len(chunks)
    assert on_disk(tmp_path) == ["jobs"]


def test_the_method_is_post(tmp_path):
    r = client(tmp_path).get("/api/inspect")
    assert (r.status_code, r.json()) == (405, {"error": "Method Not Allowed"})


# The limit: the same as for a job's files, and its text


def test_a_file_over_the_limit_is_413_and_leaves_nothing(tmp_path, digital):
    padded = digital + b"\n" * (MB + 1 - len(digital))
    r = inspect(client(tmp_path, max_upload_mb=1), "big.pdf", padded)
    assert (r.status_code, r.json()) == (413, TOO_LARGE)
    assert on_disk(tmp_path) == ["jobs"]


def test_a_file_of_exactly_the_limit_passes(tmp_path, digital):
    padded = digital + b"\n" * (MB - len(digital))  # a PDF may have bytes after its end
    r = inspect(client(tmp_path, max_upload_mb=1), "big.pdf", padded)
    assert (r.status_code, r.json()["pages"]) == (200, 3)


def test_the_limit_comes_from_the_app(tmp_path, digital):
    padded = digital + b"\n" * (3 * MB + 1 - len(digital))
    r = inspect(client(tmp_path, max_upload_mb=3), "big.pdf", padded)
    assert (r.status_code, r.json()) == (413, {"error": "File too large (limit 3 MB)"})


def test_a_huge_declared_size_is_refused_without_reading_the_body(tmp_path, digital):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    body, content_type = multipart(("file", "a.pdf", digital))  # small, and valid
    headers = [("content-type", content_type), ("content-length", str(50 * 1024 * MB))]
    wired = asyncio.run(wire(app, "POST", "/api/inspect", headers=headers, chunks=[body]))
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled == 0
    assert on_disk(tmp_path) == ["jobs"]


def test_a_body_with_no_size_is_cut_off_soon_after_the_limit(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=1)
    piece = 64 * 1024
    body, content_type = multipart(("file", "big.pdf", b"x" * (100 * piece)))  # 6.4 MB
    chunks = [body[i : i + piece] for i in range(0, len(body), piece)]
    headers = [("content-type", content_type)]  # chunked: no Content-Length
    wired = asyncio.run(wire(app, "POST", "/api/inspect", headers=headers, chunks=chunks))
    assert (wired.status, wired.json()) == (413, TOO_LARGE)
    assert wired.pulled <= 20 < len(chunks)  # about 1 MB was read, not the 6.4 MB
    assert on_disk(tmp_path) == ["jobs"]


def test_the_body_is_never_read_whole_into_memory(tmp_path, digital, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the whole body was read")

    for target in (
        "starlette.requests.Request.body",
        "starlette.requests.Request.form",
        "starlette.formparsers.MultiPartParser.parse",
    ):
        monkeypatch.setattr(target, refuse)
    assert inspect(client(tmp_path), "a.pdf", digital).status_code == 200


# A PDF that cannot be read: M1's own words


def test_a_file_that_is_no_pdf_gets_the_message_of_the_pipeline(tmp_path):
    r = inspect(client(tmp_path), "junk.pdf", b"not a pdf")
    assert (r.status_code, r.json()) == (400, {"error": "Not a readable PDF: junk.pdf"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_damaged_pdf_gets_the_message_of_the_pipeline(tmp_path, digital):
    r = inspect(client(tmp_path), "half.pdf", digital[: len(digital) // 3])
    assert (r.status_code, r.json()) == (400, {"error": "Not a readable PDF: half.pdf"})
    assert on_disk(tmp_path) == ["jobs"]


def test_a_password_protected_pdf_gets_the_message_of_the_pipeline(tmp_path, encrypted_pdf):
    data = tmp_path / "data"  # the fixture's file is in tmp_path
    r = inspect(client(data), "locked.pdf", encrypted_pdf.read_bytes())
    assert (r.status_code, r.json()) == (400, {"error": "PDF is password-protected: locked.pdf"})
    assert on_disk(data) == ["jobs"]


def test_the_message_names_the_file_as_a_conversion_would_store_it(tmp_path):
    r = inspect(client(tmp_path), "../../a:b?.pdf", b"not a pdf")
    assert (r.status_code, r.json()) == (400, {"error": "Not a readable PDF: a_b_.pdf"})
    assert_no_path(r.json(), tmp_path)


# The folder of the request


def test_nothing_is_left_after_an_answer_and_requests_do_not_meet(tmp_path, digital, mixed):
    c = client(tmp_path)
    for data in (digital, mixed, digital):  # the same name too: each is in a folder of its own
        assert inspect(c, "book.pdf", data).status_code == 200
        assert on_disk(tmp_path) == ["jobs"]


def test_the_pdf_is_there_while_it_is_read_and_gone_when_the_client_has_its_answer(
    tmp_path, digital, monkeypatch
):
    real = preview.describe_pdf
    seen = []

    def spy(path):
        seen.append(path.is_file())
        return real(path)

    monkeypatch.setattr(web_app, "describe_pdf", spy)
    c = client(tmp_path)
    r = inspect(c, "book.pdf", digital)
    assert (r.status_code, seen) == (200, [True])  # it was there while it was read
    assert on_disk(tmp_path) == ["jobs"]  # and is gone when the client has its answer


def test_the_folder_is_no_job_while_the_pdf_is_read(tmp_path, digital, monkeypatch):
    app = create_app(tmp_path, token=None)
    seen = {}
    real = preview.inspect_pdf

    def spy(path):
        folder = path.parents[2]  # <data>/jobs/<id>/input/0/<name>
        seen["parent"] = folder.parent
        seen["job_json"] = (folder / "job.json").exists()
        seen["jobs"] = app.state.store.list()
        return real(path)

    monkeypatch.setattr(preview, "inspect_pdf", spy)
    assert inspect(TestClient(app, base_url=LOCAL), "book.pdf", digital).status_code == 200
    assert seen == {"parent": tmp_path / "jobs", "job_json": False, "jobs": []}


def test_a_folder_left_by_a_request_that_was_killed_goes_when_the_server_starts(tmp_path, digital):
    with pytest.MonkeyPatch.context() as killed:
        killed.setattr(_Upload, "discard", lambda self: None)  # the server dies before it cleans up
        assert inspect(client(tmp_path), "book.pdf", digital).status_code == 200
    (left,) = [p for p in (tmp_path / "jobs").iterdir()]
    assert (left / "input" / "0" / "book.pdf").is_file()
    with client(tmp_path):  # the next start purges the folders that no job.json owns
        pass
    assert [p.name for p in (tmp_path / "jobs").iterdir()] == ["server.lock"]


def test_an_unexpected_failure_while_reading_is_a_500_and_leaves_nothing(
    tmp_path, digital, monkeypatch
):
    def broken(path):
        raise RuntimeError(f"PDFium broke on {path}")

    monkeypatch.setattr(preview, "inspect_pdf", broken)
    app = create_app(tmp_path, token=None)
    r = inspect(TestClient(app, base_url=LOCAL, raise_server_exceptions=False), "a.pdf", digital)
    assert (r.status_code, r.json()) == (500, {"error": "Something went wrong on the server"})
    assert on_disk(tmp_path) == ["jobs"]


def test_the_pdf_is_read_under_the_pdfium_lock(tmp_path, digital, monkeypatch):
    held = []
    real = preview.inspect_pdf

    def spy(path):
        held.append(preview._PDFIUM.locked())
        return real(path)

    monkeypatch.setattr(preview, "inspect_pdf", spy)
    assert inspect(client(tmp_path), "a.pdf", digital).status_code == 200
    assert held == [True]


def test_the_pdf_is_read_on_a_worker_thread_and_not_on_the_event_loop(
    tmp_path, digital, monkeypatch
):
    # a long book takes seconds in PDFium, and the other requests must not wait on the loop for it
    threads = {}
    real_path, real_describe = _PdfUpload.pdf_path, web_app.describe_pdf

    def path_on_the_loop(self):
        threads["loop"] = threading.get_ident()
        return real_path(self)

    def describe_where_it_runs(path):
        threads["describe"] = threading.get_ident()
        return real_describe(path)

    monkeypatch.setattr(_PdfUpload, "pdf_path", path_on_the_loop)
    monkeypatch.setattr(web_app, "describe_pdf", describe_where_it_runs)
    assert inspect(client(tmp_path), "a.pdf", digital).status_code == 200
    assert threads["describe"] != threads["loop"]


def test_it_waits_for_a_render_that_holds_the_pdfium_lock(tmp_path, digital):
    c = client(tmp_path)
    answered = threading.Event()

    def ask():
        inspect(c, "a.pdf", digital)
        answered.set()

    with preview._PDFIUM:  # a preview is drawing
        worker = threading.Thread(target=ask, daemon=True)
        worker.start()
        assert not answered.wait(0.5)
    assert answered.wait(10)
    worker.join(10)


# The guard


def test_in_network_mode_it_is_401_without_the_token_and_reads_nothing(tmp_path, digital):
    app = create_app(tmp_path, token=GOOD)
    c = TestClient(app, base_url=LOCAL)
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        r = inspect(c, "a.pdf", digital, headers=headers)
        assert (r.status_code, r.json()) == (401, {"error": "Missing or invalid token"})
    assert on_disk(tmp_path) == ["jobs"]
    ok = inspect(c, "a.pdf", digital, headers={"Authorization": f"Bearer {GOOD}"})
    assert (ok.status_code, ok.json()["pages"]) == (200, 3)


def test_a_request_from_another_site_is_refused_before_anything_is_written(tmp_path, digital):
    r = inspect(client(tmp_path), "a.pdf", digital, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert on_disk(tmp_path) == ["jobs"]
