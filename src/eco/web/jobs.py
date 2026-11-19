"""Jobs of the web GUI: a store on disk, and a runner that converts one job at a time.

A job is the folder `<data>/jobs/<id>/`:

    job.json      the JobInfo, written whole (a new file, then a rename); it goes first when the
                  job is deleted, so a folder without one is no job
    events.jsonl  every event of the run, one JSON object per line, for a browser that reloads
    input/        the uploads, each in a folder of its own: `<n>/<name>`, see `input_path`
    output/       the finished files, named by `output_path` after the upload's name
    tmp/          the worker's temporary files, deleted when the worker ends

Each job runs in a fresh worker process (spawn context): Cancel can kill it, and Hugging Face's
offline settings, which a process reads once, are read anew. Once a job is made, its files are
written only under the runner's lock: by the runner thread for the job it runs, and by `submit`
and `cancel` for queued jobs. events.jsonl is written before job.json, and both before the
subscribers hear of the event.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import queue
import re
import secrets
import shutil
import signal
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from eco.events import FindingEvent, PageEvent, StageEvent
from eco.options import Options, options_from_dict, upgrade_options

if os.name == "nt":
    import msvcrt
else:
    import fcntl

RETENTION_DAYS = 7
KINDS = {".pdf": "pdf", ".md": "md", ".epub": "epub"}
STOPPED = "The server stopped before this file was converted."
_ID = re.compile(r"[0-9a-f]{16}")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')
# Windows opens a device for these names, whatever comes after a dot, and for COM and LPT also
# with 0 and the superscripts 1, 2 and 3; spaces before the dot are dropped.
_DEVICE_NAME = re.compile(
    r"(?:con|prn|aux|nul|conin\$|conout\$|com[0-9¹²³]|lpt[0-9¹²³])"
    r" *(?:\.|$)",
    re.IGNORECASE,
)
# Bytes of UTF-8 in a stored name. Linux and macOS take 255 in a file name, and a CJK character or
# an emoji is three or four of them.
_MAX_NAME_BYTES = 200
_LOOK = 0.1  # seconds between looks at the cancel and stop flags while a worker runs
# On Windows another program (an antivirus, the search indexer, a thread that still reads a file)
# may hold a file for a moment, and a rename or a removal then fails: these are the waits, in
# seconds, before each new try.
_RETRY_WAITS = (0.05, 0.1, 0.2, 0.4, 0.8) if os.name == "nt" else ()

log = logging.getLogger(__name__)


@dataclass
class JobFile:
    name: str  # the upload's name, made safe
    path: str  # the stored upload, input/<n>/<name>
    kind: str  # pdf, md or epub
    outputs: dict[str, str]  # format -> file in output/
    book_dir: str | None  # a PDF's book folder in the extraction cache, for previews
    error: str | None  # why this file was not converted


@dataclass
class JobInfo:
    id: str
    status: str  # queued, running, done, failed or cancelled
    created: float
    options: dict  # the fields of Options
    files: list[JobFile]
    position: int  # for a queued job, the jobs ahead of it; 0 otherwise


def safe_name(name: str) -> str:
    """An upload's name that is safe to store on every OS.

    The last part of any path (`/` or `\\`), without control characters, `<>:"|?*` turned into
    `_` (a `:` would open an NTFS alternate data stream), no trailing dots or spaces (Windows drops
    them), at most 200 bytes of UTF-8 with the type kept (cut at a character), a `_` in front of a
    Windows device name (it is the only guard of the stored name, and outputs are named after it),
    and `file` when nothing is left.
    """
    name = re.split(r"[/\\]", name)[-1]
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cs"))
    name = _BAD_CHARS.sub("_", name).rstrip(". ")
    if len(name.encode()) >= _MAX_NAME_BYTES:  # cut to one byte less: room for the `_`
        suffix = Path(name).suffix[:10]
        room = _MAX_NAME_BYTES - 1 - len(suffix.encode())
        name = name.encode()[:room].decode(errors="ignore").rstrip(". ") + suffix
    if _DEVICE_NAME.match(name):
        name = f"_{name}"
    return name or "file"


def input_path(inputs: Path, n: int, name: str) -> Path:
    """Where upload `n` is stored: `<inputs>/<n>/<name>`, `name` being its `safe_name`.

    The file keeps the name it was uploaded under, because M1 takes names from the path it reads:
    the title of a PDF that has none and of a Markdown file that has none, and the source name that
    `epub_to_book` writes. A prefix such as `<n>-` would become the title of the book. The folder
    is the upload's own, so two uploads with one name do not meet. A Windows device name would open
    the device even here (`nul.pdf` is NUL there): `safe_name` keeps it out of the name.
    """
    return inputs / str(n) / name


def _file(name: str, path: Path) -> JobFile:
    return JobFile(name, str(path), KINDS[Path(name).suffix.lower()], {}, None, None)


def _status(info: JobInfo) -> str:
    """How a job ends when it was not cancelled: done if any file converted."""
    return "done" if any(f.outputs for f in info.files) else "failed"


def _remove(folder: Path) -> None:
    """Delete `folder`, trying again after each of _RETRY_WAITS. What still does not go stays."""
    for wait in (*_RETRY_WAITS, None):
        shutil.rmtree(folder, ignore_errors=True)
        if wait is None or not folder.exists():
            return
        time.sleep(wait)


@contextmanager
def server_lock(data_dir: Path) -> Iterator[None]:
    """Hold `<data>/jobs/server.lock` while a server uses the jobs of `data_dir`, so a second
    server stops before it touches a job: RuntimeError `Another eco web is already using <data>`.

    The lock is the OS's (msvcrt on Windows, flock elsewhere) on a file that is never written, so
    it ends with the process and a crash leaves no stale lock. A second hold fails even in the
    same process, and a worker process does not inherit it (Python's files are not inheritable).
    """
    path = Path(data_dir) / "jobs" / "server.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0)  # msvcrt locks from the file position
        try:
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError):  # held: EWOULDBLOCK, or EACCES on Windows
            raise RuntimeError(f"Another eco web is already using {data_dir}") from None
        try:
            yield
        finally:
            if os.name == "nt":  # at once; Windows releases a closed file's lock in its own time
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


class JobStore:
    """The jobs under `<data_dir>/jobs/`. One store can be shared by threads: its reads and
    writes take one lock, so no thread reads a file another thread is replacing."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def job_dir(self, job_id: str) -> Path:
        """The folder of a job. KeyError for any id that is not a job's, so never a path
        outside `jobs/`."""
        if not _ID.fullmatch(job_id) or not (self.root / job_id).is_dir():
            raise KeyError(job_id)
        return self.root / job_id

    def create(self, uploads: list[tuple[str, BinaryIO]], options: Options) -> JobInfo:
        """A queued job holding the uploads. ValueError `Unsupported file type: <name>` for a
        file that is not PDF, Markdown or EPUB; then nothing is written."""
        names = [safe_name(name) for name, _ in uploads]
        for name in names:
            if Path(name).suffix.lower() not in KINDS:
                raise ValueError(f"Unsupported file type: {name}")

        def fill(inputs: Path) -> list[JobFile]:
            files = []
            for n, (name, (_, data)) in enumerate(zip(names, uploads, strict=True)):
                path = input_path(inputs, n, name)
                path.parent.mkdir()
                with path.open("wb") as f:
                    shutil.copyfileobj(data, f)
                files.append(_file(name, path))
            return files

        return self._new(options, fill)

    def reserve(self) -> Path:
        """An empty job folder for uploads that are written as they arrive; `adopt` then makes a
        job of it. Until then the folder has no job.json: `get` and `list` do not see it, and
        `purge` deletes it by its age, as it does the folder of a `create` that never finished."""
        job = self.root / secrets.token_hex(8)
        (job / "input").mkdir(parents=True)
        (job / "output").mkdir()
        return job

    def adopt(self, job: Path, names: list[str], options: Options) -> JobInfo:
        """A queued job from the files already written to `input_path(job / "input", n, name)`,
        one for each name in `names` (made by `safe_name`, with a type in KINDS). The files stay
        where they are. If this fails the folder is deleted."""

        def fill(inputs: Path) -> list[JobFile]:
            return [_file(name, input_path(inputs, n, name)) for n, name in enumerate(names)]

        return self._new(options, fill, job)

    def rebuild(self, job_id: str, options: Options) -> JobInfo:
        """A queued job with the inputs of `job_id` (hard links where the disk allows them) and
        new options. A PDF's extraction is cached, so it is not read again."""
        old = self.get(job_id)
        old_fonts = self.job_dir(job_id) / "fonts"

        def fill(inputs: Path) -> list[JobFile]:
            if old_fonts.is_dir():
                shutil.copytree(old_fonts, inputs.parent / "fonts")
            files = []
            for n, f in enumerate(old.files):  # by number: the old job's own layout is not read
                dst = input_path(inputs, n, f.name)
                dst.parent.mkdir()
                try:
                    os.link(f.path, dst)
                except OSError:
                    shutil.copyfile(f.path, dst)
                files.append(_file(f.name, dst))
            return files

        return self._new(options, fill)

    def _new(
        self, options: Options, fill: Callable[[Path], list[JobFile]], job: Path | None = None
    ) -> JobInfo:
        job = job or self.reserve()
        try:
            stored_options = asdict(options)
            stored_options["style"] = options.style.to_json()
            info = JobInfo(job.name, "queued", time.time(), stored_options, fill(job / "input"), 0)
            self.save(info)
        except BaseException:
            shutil.rmtree(job, ignore_errors=True)
            raise
        return info

    def get(self, job_id: str) -> JobInfo:
        """The job. KeyError when there is none."""
        path = self.job_dir(job_id) / "job.json"
        with self._lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise KeyError(job_id) from None
        data["options"] = upgrade_options(data["options"])
        return JobInfo(**{**data, "files": [JobFile(**f) for f in data["files"]]})

    def list(self, limit: int = 20) -> list[JobInfo]:
        """The most recent jobs first."""
        return sorted(self._all(), key=lambda info: info.created, reverse=True)[:limit]

    def _all(self) -> list[JobInfo]:
        infos = []
        for job in self.root.iterdir():
            try:
                infos.append(self.get(job.name))
            except (KeyError, OSError, ValueError, TypeError):
                pass  # not a job folder, or one whose create never finished
        return infos

    def save(self, info: JobInfo) -> None:
        """Write job.json: a new file, flushed to the disk, then a rename, so neither a crash nor a
        power loss leaves half of one. The rename is tried again after each of _RETRY_WAITS."""
        path = self.job_dir(info.id) / "job.json"
        tmp = path.with_name("job.json.tmp")
        with self._lock:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(json.dumps(asdict(info), ensure_ascii=False, indent=1))
                f.flush()
                os.fsync(f.fileno())
            for wait in _RETRY_WAITS:
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    time.sleep(wait)
            os.replace(tmp, path)

    def delete(self, job_id: str) -> None:
        """Delete a job that has ended (done, failed or cancelled), on the user's word. Its
        job.json goes first, under the lock, so the job is gone from `get`, `list` and every route
        at once; then its folder. A folder that does not go (Windows: a file in it is held) stays
        without a job.json, and the next start purges it. KeyError when there is no such job,
        ValueError while it is queued or running: those are the runner's."""
        with self._lock:
            if self.get(job_id).status in ("queued", "running"):
                raise ValueError(f"Job {job_id} has not ended")
            (self.root / job_id / "job.json").unlink()
        _remove(self.root / job_id)

    def events(self, job_id: str) -> list[dict]:
        """The events of the job so far. A line that a crash cut short is skipped."""
        path = self.job_dir(job_id) / "events.jsonl"
        with self._lock:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        return events

    def append_event(self, job_id: str, event: dict) -> None:
        path = self.job_dir(job_id) / "events.jsonl"
        with self._lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def purge(
        self, now: float | None = None, *, orphans: bool = False, keep_queued: bool = False
    ) -> int:
        """Delete the jobs made more than RETENTION_DAYS ago, except a running one (its worker
        uses the folder) and, with `keep_queued`, a queued one (the runner has it in its queue).
        A folder without a readable job.json goes by its own age, so an upload that is coming in
        stays. With `orphans` a folder with no job.json at all goes whatever its age: for the
        start of a server, when no upload can be in flight, so what is left is an upload that a
        hard kill cut, or a deleted job that would not go. A job.json that is there but cannot be
        read (another version of eco wrote it, or a power loss emptied it) is never a reason to
        delete the job at once. Returns how many went."""
        cutoff = (time.time() if now is None else now) - RETENTION_DAYS * 86400
        deleted = 0
        for job in self.root.iterdir():
            if not _ID.fullmatch(job.name):
                continue
            try:
                info = self.get(job.name)
            except (KeyError, OSError, ValueError, TypeError):
                try:
                    orphan = orphans and not (job / "job.json").exists()
                    expired = orphan or job.stat().st_mtime < cutoff
                except FileNotFoundError:
                    continue  # it went while we looked: an upload that failed
                kept = False
            else:
                expired = info.created < cutoff
                kept = info.status == "running" or (keep_queued and info.status == "queued")
            if expired and not kept:
                shutil.rmtree(job, ignore_errors=True)
                deleted += not job.exists()
        return deleted


def _one_line(e: Exception) -> str:
    """The error as the CLI prints it: one line."""
    return " ".join(str(e).split()) or type(e).__name__


def _event(e) -> dict:
    """An M1 event as the dict the browser gets."""
    if isinstance(e, StageEvent):
        return {"type": "stage", "stage": e.stage, "status": e.status}
    if isinstance(e, PageEvent):
        return {"type": "page", "done": e.done, "total": e.total}
    f = e.finding
    return {
        "type": "finding",
        "page": f.page,
        "kind": f.kind,
        "level": f.level,
        "message": f.message,
    }


def _work(job_dir: str, options: dict, data_dir: str, q: multiprocessing.Queue) -> None:
    """The worker process: convert each input of the job in turn and put event dicts on `q`.

    A file that fails gets a `failed` event with the one-line error the CLI would print, and the
    next file goes on. The job ends `done` if any file converted, else `failed`.
    """
    from eco.pipeline import convert_file, output_path  # loads Docling: only ever in a worker

    job = Path(job_dir)
    # the runner wrote job.json before it started this process, and writes it again only after
    # this process reports a file's result
    files = json.loads((job / "job.json").read_text(encoding="utf-8"))["files"]
    (job / "tmp").mkdir(exist_ok=True)
    tempfile.tempdir = str(job / "tmp")  # what a killed worker leaves there, the runner deletes
    font_dir = job / "fonts"
    library = Path(data_dir) / "fonts"
    font_dirs = tuple(folder for folder in (library, font_dir) if folder.is_dir())
    style_findings = []
    opts = options_from_dict(options, font_dirs, style_findings)
    for finding in style_findings:
        q.put(_event(FindingEvent(finding)))
    written: list[Path] = []
    for i, file in enumerate(files):
        q.put({"type": "file", "index": i, "status": "started"})
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
                result = convert_file(
                    Path(file["path"]),
                    opts,
                    Path(scratch),
                    data_dir=Path(data_dir),
                    on_event=lambda e: q.put(_event(e)),
                    font_extra_dirs=font_dirs,
                )
                outputs = {}
                for fmt, made in result.outputs.items():
                    # named after the upload, and never like an earlier output (two uploads may
                    # have one name); a rename on one disk, so output/ never holds half a file
                    out = output_path(
                        Path(file["name"]), job / "output", opts.device, made.suffix[1:], written
                    )
                    shutil.move(made, out)
                    written.append(out)
                    outputs[fmt] = str(out)
        except Exception as e:  # noqa: BLE001  one bad file must not stop the job, as in the CLI
            q.put({"type": "file", "index": i, "status": "failed", "error": _one_line(e)})
            continue
        book_dir = str(result.book_dir) if result.book_dir else None
        q.put(
            {
                "type": "file",
                "index": i,
                "status": "done",
                "outputs": outputs,
                "book_dir": book_dir,
                "sizes": result.sizes,
                "seconds": round(result.seconds, 2),
            }
        )
    q.put({"type": "end", "status": "done" if written else "failed"})


def _worker_main(worker: Callable, *args) -> None:
    """What a worker process runs: `worker(*args)`, after two settings that every worker needs.

    Ctrl+C in the console reaches this process too (Windows: one console; POSIX: one process
    group). The server stops its worker itself (M2-R16), so SIGINT is ignored here; otherwise the
    job would end "stopped unexpectedly (exit code 1)", with a traceback on stderr.

    A server that is killed (taskkill /F, SIGKILL, the OOM killer) cannot stop its worker, which
    would run on and then hang at its exit on a pipe of events that nobody reads. So a thread
    waits for the server's process to end, and then ends this one at once."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    server = multiprocessing.parent_process()
    if server is not None:
        threading.Thread(target=_end_with, args=(server,), name="eco-watchdog", daemon=True).start()
    worker(*args)


def _end_with(server: multiprocessing.process.BaseProcess) -> None:
    server.join()
    os._exit(1)


def _kill(proc: multiprocessing.process.BaseProcess) -> None:
    """terminate(), up to 5 s for the worker to go, then kill(). kill() is TerminateProcess on
    Windows and SIGKILL on POSIX, which no process can ignore."""
    proc.terminate()
    proc.join(5)
    if proc.is_alive():
        proc.kill()
        proc.join(5)


class Runner:
    """Runs submitted jobs one at a time, first in first out, each in its own worker process.

    `worker` is the worker's entry point, `_work` by default; the process runs it through
    `_worker_main`. The spawned process imports it by module and name, so a stand-in must be a
    module-level function of an importable module.
    """

    def __init__(self, store: JobStore, data_dir: Path, worker: Callable | None = None):
        self.store = store
        self.data_dir = Path(data_dir)
        self.worker = worker or _work  # looked up now, so a test can swap the module's _work
        self._ctx = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: list[str] = []
        self._current: str | None = None
        self._cancel = threading.Event()
        self._stopping = False
        self._subs: dict[str, list[queue.Queue[dict]]] = {}
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Settle what a stopped server left, then start the runner thread.

        A job left `running` is not run again: its worker is gone, so it ends like a job whose
        server stops (files not converted get the error STOPPED; done if any file converted).
        Jobs left `queued` never started, so they keep their place, oldest first.
        """
        left = [info for info in self.store._all() if info.status in ("queued", "running")]
        for info in sorted(left, key=lambda info: info.created):
            if info.status == "running":
                shutil.rmtree(self.store.job_dir(info.id) / "tmp", ignore_errors=True)
                with self._lock:
                    self._finish(info, _status(info), STOPPED)
            else:
                self.submit(info.id)
        self._thread = threading.Thread(target=self._loop, name="eco-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the runner. A running job's worker is killed and the job ends as in `start`;
        queued jobs stay queued for the next start."""
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
        if self._thread:
            self._thread.join(15)

    def submit(self, job_id: str) -> None:
        """Queue a job made by `create` or `rebuild`; its position is written at once. Submitting
        a job that is already queued or running does nothing. ValueError for a job that ran."""
        with self._lock:
            if job_id == self._current or job_id in self._queue:
                return
            if self.store.get(job_id).status != "queued":
                raise ValueError(f"Job {job_id} has already run")
            self._queue.append(job_id)
            self._reposition()
            self._wake.notify()

    def cancel(self, job_id: str) -> bool:
        """End a queued job at once, or have the runner thread kill the running one's worker
        (the job is `cancelled` within 10 s). False when the job is neither queued nor running."""
        with self._lock:
            if job_id == self._current:
                self._cancel.set()
                return True
            if job_id not in self._queue:
                return False
            self._queue.remove(job_id)
            self._finish(self.store.get(job_id), "cancelled")
            self._reposition()
            return True

    def subscribe(self, job_id: str) -> queue.Queue[dict]:
        """A queue that holds the job's events so far (events.jsonl) and then gets each new one,
        up to `{"type": "end", ...}`. Both are taken under the runner's lock, so no event is
        missed or repeated. Call `unsubscribe` when done. KeyError for an unknown job."""
        q: queue.Queue[dict] = queue.Queue()
        with self._lock:
            events = self.store.events(job_id)
            for event in events:
                q.put(event)
            if not events or events[-1]["type"] != "end":
                self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue[dict]) -> None:
        with self._lock:
            subs = self._subs.get(job_id, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subs.pop(job_id, None)

    def _loop(self) -> None:
        while (job_id := self._next()) is not None:
            try:
                self._run(job_id)
            except Exception as e:  # one broken job must not stop the queue
                log.exception("Job %s failed in the runner", job_id)
                self._fail(job_id, f"The conversion could not run: {_one_line(e)}")
            finally:
                with self._lock:
                    self._current = None

    def _next(self) -> str | None:
        """Wait for a queued job and make it the current one. None when the runner stops."""
        with self._lock:
            while not self._queue and not self._stopping:
                self._wake.wait()
            if self._stopping:
                return None
            self._current = self._queue.pop(0)
            self._cancel.clear()
            self._reposition()
            return self._current

    def _run(self, job_id: str) -> None:
        job = self.store.job_dir(job_id)
        with self._lock:
            info = self.store.get(job_id)
            info.status, info.position = "running", 0
            self.store.save(info)
        events = self._ctx.Queue()
        args = (self.worker, str(job), info.options, str(self.data_dir), events)
        proc = self._ctx.Process(target=_worker_main, args=args, name=f"eco-{job_id}", daemon=True)
        try:
            proc.start()
            status, error = self._watch(info, proc, events)
        finally:
            if proc.is_alive():
                _kill(proc)
            shutil.rmtree(job / "tmp", ignore_errors=True)
        with self._lock:
            self._finish(info, status, error)
            self._current = None

    def _watch(self, info: JobInfo, proc, events) -> tuple[str, str | None]:
        """Pass the worker's events on until it ends. Returns the job's status and the error for
        its files that did not convert. Cancel and stop are seen within _LOOK seconds."""
        while True:
            if self._cancel.is_set():
                _kill(proc)
                return "cancelled", None
            if self._stopping:
                _kill(proc)
                return _status(info), STOPPED
            try:
                event = events.get(timeout=_LOOK)
            except queue.Empty:
                if proc.is_alive():
                    continue
                try:  # the worker is gone: take what it put just before
                    event = events.get(timeout=1)
                except queue.Empty:
                    code = proc.exitcode
                    return _status(info), f"The conversion stopped unexpectedly (exit code {code})."
            if event["type"] == "end":
                proc.join(5)  # it ends on its own; _run kills it if not
                return event["status"], None
            self._record(info, event)

    def _record(self, info: JobInfo, event: dict) -> None:
        """Keep a worker's event: a file's result goes into job.json, every event into
        events.jsonl and to the subscribers."""
        result = event["type"] == "file" and event["status"] in ("done", "failed")
        if result:
            f = info.files[event["index"]]
            if event["status"] == "done":
                f.outputs, f.book_dir = event["outputs"], event.get("book_dir")
            else:
                f.error = event["error"]
        with self._lock:
            self._publish(info, event, save=result)

    def _finish(self, info: JobInfo, status: str, error: str | None = None) -> None:
        """Under the lock: end the job. `error` goes to each file that neither converted nor
        failed. The `end` event is the job's last, and it is written once: when job.json could
        not be saved after it (a full disk, a server killed in between), a second end only saves
        job.json, with the status that the `end` gave."""
        if error:
            for f in info.files:
                if not f.outputs and not f.error:
                    f.error = error
        last = self.store.events(info.id)[-1:]
        if last and last[0]["type"] == "end":
            info.status, info.position = last[0]["status"], 0
            self.store.save(info)
            return
        info.status, info.position = status, 0
        self._publish(info, {"type": "end", "status": status}, save=True)

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            try:
                info = self.store.get(job_id)
                if info.status in ("queued", "running"):
                    self._finish(info, _status(info), error)
            except Exception:
                log.exception("Job %s could not be marked as failed", job_id)

    def _publish(self, info: JobInfo, event: dict, save: bool) -> None:
        """Under the lock: events.jsonl, then job.json, then the subscribers. A reader that sees
        the new job.json finds the event already in events.jsonl."""
        self.store.append_event(info.id, event)
        if save:
            self.store.save(info)
        for q in self._subs.get(info.id, []):
            q.put(event)
        if event["type"] == "end":
            self._subs.pop(info.id, None)

    def _reposition(self) -> None:
        """Under the lock: write each queued job's position, the number of jobs ahead of it."""
        ahead = 1 if self._current else 0
        for n, job_id in enumerate(self._queue, ahead):
            try:
                info = self.store.get(job_id)
            except KeyError:
                continue  # its folder is gone; _run fails it when its turn comes
            if info.position != n:
                info.position = n
                self.store.save(info)
