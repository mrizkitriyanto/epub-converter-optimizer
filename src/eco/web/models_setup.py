"""The AI model download of the setup page: one background run at a time, and its event log.

`GET /api/setup` shows what is missing, `POST /api/setup/download` starts
`eco.models.download_models` on a daemon thread (Ctrl+C must not wait for 417 MB; finished files
are kept, so the next run resumes), and `GET /api/setup/events` streams what the run says.
`ModelSetup` holds the state; the routes are in `eco.web.app`.

The events are `{"type": "progress", "message": str}` and one last
`{"type": "end", "status": "done" | "failed", "message": str}`. The progress lines are one line
when the run starts and each line that `download_models` logs on the `eco.models` logger (one per
retry) while the run lasts.

A run that failed because the Microsoft Visual C++ Redistributable is missing has one more key in
its `end` event, `"vc_runtime_missing": true`, and its `message` is the text to show. The page
tells it from the other failures by that key: downloading over IPv4 cannot help it, so the page
offers no IPv4 retry. The `end` event of any other run has no such key.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from eco.models import MODELS, VcRuntimeMissing, download_models, models_dir, models_ready
from eco.web.strings import STRINGS


class _Progress(logging.Handler):
    """Passes each record of the logger it is attached to on as a progress line."""

    def __init__(self, say: Callable[[str], None]):
        super().__init__()
        self._say = say

    def emit(self, record: logging.LogRecord) -> None:
        self._say(record.getMessage())


class ModelSetup:
    """The models of a data folder, and the one download of them that may run.

    `scrub` cuts the data folder out of a text before it is shown. Events are kept from the start
    of the last run until the next run starts. A reader takes them with `subscribe`: it gets every
    event so far and then each new one, with no gap and no repeat, because both happen under one
    lock with `_publish`.
    """

    def __init__(self, data_dir: Path, scrub: Callable[[str], str]):
        self._dir = models_dir(Path(data_dir))
        self._scrub = scrub
        self._lock = threading.Lock()
        self._running = False
        self._events: list[dict] = []
        self._started = False  # a run has been started since the server did
        self._subs: list[queue.Queue[dict]] = []

    @staticmethod
    def models() -> list[dict]:
        return [{"name": m.name, "size_mb": m.size_mb} for m in MODELS]

    @staticmethod
    def total_mb() -> int:
        return sum(m.size_mb for m in MODELS)

    def ready(self) -> bool:
        return models_ready(self._dir)

    @property
    def started(self) -> bool:
        return self._started

    def start(self, *, ipv4: bool = False) -> bool:
        """Start a download. False, and nothing started, when one is running. The check and the
        start are one step under the lock, so two calls at once start one run."""
        with self._lock:
            if self._running:
                return False
            self._running = self._started = True
            self._events = []
            line = STRINGS["setup_start_ipv4" if ipv4 else "setup_start"]
            self._publish({"type": "progress", "message": line.format(mb=self.total_mb())})
            threading.Thread(
                target=self._run, args=(ipv4,), name="eco-model-download", daemon=True
            ).start()
        return True

    def subscribe(self) -> queue.Queue[dict]:
        """A queue that holds the events so far and then gets each new one, up to `end`. Call
        `unsubscribe` when done."""
        q: queue.Queue[dict] = queue.Queue()
        with self._lock:
            for event in self._events:
                q.put(event)
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict]) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self, event: dict) -> None:
        """Keep an event and give it to every reader. The caller holds the lock."""
        self._events.append(event)
        for q in self._subs:
            q.put(event)

    def _say(self, message: str) -> None:
        with self._lock:
            self._publish({"type": "progress", "message": self._scrub(message)})

    def _run(self, ipv4: bool) -> None:
        log = logging.getLogger("eco.models")
        handler = _Progress(self._say)
        log.addHandler(handler)
        status, message = "failed", STRINGS["setup_failed"]
        extra = {}  # what else the page needs to know about the end
        try:
            download_models(self._dir, ipv4=ipv4)
            status, message = "done", STRINGS["setup_done"]
        except Exception as e:  # noqa: BLE001  the page must hear of the end, whatever failed
            message = self._scrub(str(e)) or message
            if isinstance(e, VcRuntimeMissing):
                extra["vc_runtime_missing"] = True
        finally:
            log.removeHandler(handler)  # before `end`: nothing is said after it
            with self._lock:
                self._running = False  # in the same step, so a POST after `end` is accepted
                self._publish({"type": "end", "status": status, "message": message, **extra})
