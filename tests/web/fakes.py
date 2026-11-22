"""Stand-in workers for the job tests, a wait helper, and readers of an EPUB.

A worker runs in a spawned process, which imports its target by module and name. So each fake is
a module-level function of this importable module: a monkeypatch made in the test process alone
would never reach the child."""

import json
import os
import signal
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


def wait_for(condition, timeout: float) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError(f"not true within {timeout} s")
        time.sleep(0.05)


def epub_title(source) -> str:
    """The `dc:title` of an EPUB: a path, or a file object."""
    with zipfile.ZipFile(source) as z:
        container = ElementTree.fromstring(z.read("META-INF/container.xml"))
        opf = ElementTree.fromstring(z.read(container.find(".//{*}rootfile").get("full-path")))
    return opf.find(".//{http://purl.org/dc/elements/1.1/}title").text


def epub_text(source) -> str:
    """The XHTML of all the chapters of an EPUB, one after another."""
    with zipfile.ZipFile(source) as z:
        return "".join(z.read(n).decode() for n in z.namelist() if n.endswith(".xhtml"))


def _inputs(job: Path) -> list[Path]:
    """The uploads of a job in order: the one file in each `input/<n>/` folder."""
    folders = sorted((job / "input").iterdir(), key=lambda folder: int(folder.name))
    return [next(folder.iterdir()) for folder in folders]


def fake_work(job_dir, options, data_dir, q) -> None:
    """`_work` without Docling: per file a stage, 3 pages at 0.2 s each, a finding and an output."""
    job = Path(job_dir)
    for i, path in enumerate(_inputs(job)):
        q.put({"type": "file", "index": i, "status": "started"})
        q.put({"type": "stage", "stage": "layout", "status": "started"})
        for done in range(1, 4):
            time.sleep(0.2)
            q.put({"type": "page", "done": done, "total": 3})
        q.put(
            {
                "type": "finding",
                "page": 2,
                "kind": "blank_page",
                "level": "info",
                "message": "Blank page skipped.",
            }
        )
        q.put({"type": "stage", "stage": "layout", "status": "finished"})
        out = job / "output" / f"{path.stem}.x4.epub"
        out.write_bytes(b"not a real EPUB")
        outputs = {"epub": str(out)}
        if "xtch" in options.get("formats", ()):
            xtch = job / "output" / f"{path.stem}.x4.xtch"
            xtch.write_bytes(b"not a real XTCH")
            outputs["xtch"] = str(xtch)
        q.put(
            {
                "type": "file",
                "index": i,
                "status": "done",
                "outputs": outputs,
                "epubcheck": "passed",
                "library_name": f"ID - {path.stem} - Ani",
            }
        )
    q.put({"type": "end", "status": "done"})


def endless_work(job_dir, options, data_dir, q) -> None:
    """Starts its first file and never ends by itself; SIGTERM ends it."""
    q.put({"type": "file", "index": 0, "status": "started"})
    while True:
        time.sleep(0.1)


def stubborn_work(job_dir, options, data_dir, q) -> None:
    """Ignores SIGTERM (Windows has no way to ignore TerminateProcess) and never ends by itself."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    q.put({"type": "file", "index": 0, "status": "started", "pid": os.getpid()})
    while True:
        time.sleep(0.1)


def failing_work(job_dir, options, data_dir, q) -> None:
    """Fails its only file with an error that holds the file's full path, as an OSError does."""
    path = _inputs(Path(job_dir))[0]
    q.put({"type": "file", "index": 0, "status": "started"})
    error = f"[Errno 13] Permission denied: {str(path)!r}"
    q.put({"type": "file", "index": 0, "status": "failed", "error": error})
    q.put({"type": "end", "status": "failed"})


def crashing_work(job_dir, options, data_dir, q) -> None:
    """Dies in its first file without an `end` event, as a native crash would."""
    q.put({"type": "file", "index": 0, "status": "started"})
    q.close()
    q.join_thread()  # the event reaches the runner before the process dies
    os._exit(3)


def interrupted_work(job_dir, options, data_dir, q) -> None:
    """Gets the Ctrl+C that a console sends to every process in it (SIGINT), then goes on and
    ends `done`."""
    signal.raise_signal(signal.SIGINT)
    q.put({"type": "file", "index": 0, "status": "started"})
    q.put({"type": "end", "status": "done"})


def locking_work(job_dir, options, data_dir, q) -> None:
    """Holds the server lock of `<data_dir>/worker` and never ends by itself, so a test can see
    from another process whether this one still lives. Its first event tells its pid."""
    from eco.web.jobs import server_lock

    with server_lock(Path(data_dir) / "worker"):
        q.put({"type": "file", "index": 0, "status": "started", "pid": os.getpid()})
        while True:
            time.sleep(0.1)


def serve_one_job(data_dir) -> None:
    """A server's runner and nothing else: it runs one job with `locking_work`, then waits until
    it is killed."""
    import io

    from eco.options import Options
    from eco.web.jobs import JobStore, Runner

    store = JobStore(Path(data_dir))
    runner = Runner(store, Path(data_dir), worker=locking_work)
    runner.start()
    runner.submit(store.create([("a.md", io.BytesIO(b"# A"))], Options()).id)
    while True:
        time.sleep(0.1)


def hold_server_lock(data_dir, held) -> None:
    """Holds the server lock of `data_dir` until the process is killed."""
    from eco.web.jobs import server_lock

    with server_lock(data_dir):
        held.set()
        while True:
            time.sleep(0.1)


# Reading what an app answers


def sse(text):
    """The events of an event stream. Each message is one `data: <json>` line and a blank line."""
    messages = text.split("\n\n")
    assert messages.pop() == ""  # the stream ends with the blank line of its last message
    events = []
    for message in messages:
        assert message.startswith("data: ") and "\n" not in message, message
        events.append(json.loads(message.removeprefix("data: ")))
    return untimed(events)


def untimed(events):
    """Events without `t`, the server time that the runner stamps on each: for comparisons."""
    if isinstance(events, dict):
        return {k: v for k, v in events.items() if k != "t"}
    return [untimed(e) for e in events]


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
