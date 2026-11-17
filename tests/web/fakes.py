"""Stand-in workers for the job tests, and a wait helper.

A worker runs in a spawned process, which imports its target by module and name. So each fake is
a module-level function of this importable module: a monkeypatch made in the test process alone
would never reach the child."""

import os
import signal
import time
from pathlib import Path


def wait_for(condition, timeout: float) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError(f"not true within {timeout} s")
        time.sleep(0.05)


def _inputs(job: Path) -> list[Path]:
    return sorted((job / "input").iterdir(), key=lambda p: int(p.name.partition("-")[0]))


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
        out = job / "output" / f"{Path(path.name.partition('-')[2]).stem}.x4.epub"
        out.write_bytes(b"not a real EPUB")
        q.put({"type": "file", "index": i, "status": "done", "outputs": {"epub": str(out)}})
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


def hold_server_lock(data_dir, held) -> None:
    """Holds the server lock of `data_dir` until the process is killed."""
    from eco.web.jobs import server_lock

    with server_lock(data_dir):
        held.set()
        while True:
            time.sleep(0.1)
