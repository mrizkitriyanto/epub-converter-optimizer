"""The setup API: what is missing, the one download, and its event stream.

`download_models` is always replaced: no test opens a connection or fetches a model. The
`no_real_download` fixture makes a test that forgets to replace it fail instead of downloading,
and it waits at the end of every test for the download thread to finish (a test that holds a run
open opens its gate first), so no run, and no logging handler of one, outlives its test.
"""

import asyncio
import json
import logging
import threading
from importlib.metadata import version
from pathlib import Path

import pytest
from fakes import sse, wait_for, wire
from fastapi.testclient import TestClient

from eco.models import MODELS, ModelInfo, download_models, models_dir
from eco.web import app as web_app
from eco.web import models_setup
from eco.web.app import create_app

LOCAL = "http://127.0.0.1:8000"
START = "Downloading the AI models (417 MB). Finished files are kept if it stops."
RETRY = "Attempt 1 of 8 failed (ConnectError: connection reset). Retrying in 2 s."
BAD_BODY = 'Send nothing, or a JSON object such as {"ipv4": true}'


@pytest.fixture(autouse=True)
def no_real_download(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test started the real download")

    monkeypatch.setattr(models_setup, "download_models", refuse)
    yield
    # Torn down after the fixtures of the test, so after every gate was opened.
    runs = [t for t in threading.enumerate() if t.name == "eco-model-download"]
    for run in runs:
        run.join(10)
    assert not any(run.is_alive() for run in runs), "a download thread outlived its test"


def fake_download(calls, *, gate=None, fail=None, retries=1):
    """A `download_models` that logs `retries` failed attempts on the `eco.models` logger, as the
    real one does, waits for `gate` if given, then fails with `fail` or finishes the models."""

    def download(d, *, ipv4=False, attempts=8, sleep=None):
        calls.append({"dir": d, "ipv4": ipv4})
        for n in range(1, retries + 1):
            logging.getLogger("eco.models").warning(
                "Attempt %d of 8 failed (ConnectError: connection reset). Retrying in %d s.",
                n,
                2**n,
            )
        if gate is not None:
            assert gate.wait(10), "the test never opened the gate"
        if fail is not None:
            raise fail
        d.mkdir(parents=True, exist_ok=True)
        (d / ".complete").write_text(version("docling"))

    return download


@pytest.fixture
def calls(monkeypatch):
    """Replace `download_models` by a quick one that succeeds. The list holds each call."""
    made = []
    monkeypatch.setattr(models_setup, "download_models", fake_download(made))
    return made


@pytest.fixture
def held(monkeypatch):
    """A download that waits for the gate. The gate is opened at the end of the test."""
    gate = threading.Event()
    monkeypatch.setattr(models_setup, "download_models", fake_download([], gate=gate))
    yield gate
    gate.set()


def client(tmp_path):
    return TestClient(create_app(tmp_path, token=None), base_url=LOCAL)


def idle(c):
    """Wait until no run is going."""
    setup = c.app.state.setup
    wait_for(lambda: not setup._running, 10)


def run_to_end(c, body=None):
    """POST a download, wait for its stream to end, and return the events."""
    assert c.post("/api/setup/download", json=body).status_code == 202
    return sse(c.get("/api/setup/events").text)


async def subscribed(setup):
    """Wait, on the loop, until a stream has made its queue."""
    for _ in range(500):
        if setup._subs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no stream subscribed within 5 s")


# GET /api/setup


def test_setup_lists_the_models_with_their_sizes(tmp_path):
    shown = client(tmp_path).get("/api/setup")
    assert shown.status_code == 200
    assert shown.json() == {
        "ready": False,
        "models": [{"name": m.name, "size_mb": m.size_mb} for m in MODELS],
        "total_mb": sum(m.size_mb for m in MODELS),
    }
    assert shown.json()["total_mb"] == 417


def test_the_total_is_the_sum_of_the_registry_not_a_number_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(models_setup, "MODELS", (ModelInfo("One", 5), ModelInfo("Two", 7)))
    shown = client(tmp_path).get("/api/setup").json()
    assert shown["models"] == [{"name": "One", "size_mb": 5}, {"name": "Two", "size_mb": 7}]
    assert shown["total_mb"] == 12


def test_ready_is_true_when_the_models_are_in_the_data_folder(tmp_path):
    models = models_dir(tmp_path)
    models.mkdir(parents=True)
    (models / ".complete").write_text(version("docling"))
    assert client(tmp_path).get("/api/setup").json()["ready"] is True


def test_ready_is_false_for_a_marker_of_another_docling(tmp_path):
    models = models_dir(tmp_path)
    models.mkdir(parents=True)
    (models / ".complete").write_text("0.0.1")
    assert client(tmp_path).get("/api/setup").json()["ready"] is False


# POST /api/setup/download


def test_a_download_that_retries_once_makes_the_models_ready(tmp_path, calls):
    c = client(tmp_path)
    assert c.get("/api/setup").json()["ready"] is False
    assert c.post("/api/setup/download").status_code == 202
    events = sse(c.get("/api/setup/events").text)
    assert events[-1] == {"type": "end", "status": "done", "message": "The AI models are ready."}
    assert c.get("/api/setup").json()["ready"] is True
    assert calls == [{"dir": models_dir(tmp_path), "ipv4": False}]


def test_a_second_post_during_the_run_is_409_and_starts_nothing(tmp_path, monkeypatch):
    calls, gate = [], threading.Event()
    monkeypatch.setattr(models_setup, "download_models", fake_download(calls, gate=gate))
    c = client(tmp_path)
    try:
        assert c.post("/api/setup/download").status_code == 202
        second = c.post("/api/setup/download")
        assert (second.status_code, second.json()) == (
            409,
            {"error": "The AI models are already downloading"},
        )
    finally:
        gate.set()
    sse(c.get("/api/setup/events").text)
    assert len(calls) == 1


def test_after_the_end_a_new_run_starts_and_its_log_replaces_the_old_one(tmp_path, calls):
    c = client(tmp_path)
    first = run_to_end(c)
    idle(c)
    second = run_to_end(c, {"ipv4": True})
    assert len(calls) == 2
    assert [e["type"] for e in second] == ["progress", "progress", "end"]
    assert first[0] != second[0] and "over IPv4" in second[0]["message"]
    assert sse(c.get("/api/setup/events").text) == second


def test_two_posts_at_once_start_one_run(tmp_path, monkeypatch):
    calls, gate = [], threading.Event()
    monkeypatch.setattr(models_setup, "download_models", fake_download(calls, gate=gate))
    c = client(tmp_path)
    start, statuses = threading.Barrier(8), []

    def post():
        start.wait()
        statuses.append(c.post("/api/setup/download").status_code)

    threads = [threading.Thread(target=post) for _ in range(8)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    finally:
        gate.set()
    idle(c)
    assert sorted(statuses) == [202] + [409] * 7
    assert len(calls) == 1


def test_the_download_runs_on_a_daemon_thread(tmp_path, held):
    c = client(tmp_path)
    c.post("/api/setup/download")
    (thread,) = [t for t in threading.enumerate() if t.name == "eco-model-download"]
    assert thread.daemon  # Ctrl+C must not wait for a 417 MB download
    held.set()
    idle(c)


@pytest.mark.parametrize(
    ("body", "ipv4"),
    [(None, False), ({}, False), ({"ipv4": False}, False), ({"ipv4": True}, True)],
)
def test_the_ipv4_flag_reaches_the_download(tmp_path, calls, body, ipv4):
    run_to_end(client(tmp_path), body)
    assert [call["ipv4"] for call in calls] == [ipv4]


def test_a_blank_body_with_a_json_header_is_the_defaults(tmp_path, calls):
    c = client(tmp_path)
    c.post("/api/setup/download", content=b"  ", headers={"content-type": "application/json"})
    sse(c.get("/api/setup/events").text)
    assert [call["ipv4"] for call in calls] == [False]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"not json", BAD_BODY),
        (b"[true]", BAD_BODY),
        (b"null", BAD_BODY),
        (b"\xff\xfe", BAD_BODY),
        (b'{"ipv4": 1}', "ipv4 must be true or false"),
        (b'{"ipv4": "true"}', "ipv4 must be true or false"),
        (b'{"ipv4": null}', "ipv4 must be true or false"),
        (b'{"ipv6": true}', "Unknown setting: ipv6"),
        (b'{"ipv4": true, "attempts": 1}', "Unknown setting: attempts"),
    ],
)
def test_a_bad_body_is_422_and_starts_nothing(tmp_path, calls, raw, message):
    c = client(tmp_path)
    refused = c.post("/api/setup/download", content=raw)
    assert (refused.status_code, refused.json()) == (422, {"error": message})
    assert not c.app.state.setup.started and calls == []
    assert c.get("/api/setup/events").status_code == 404


def test_a_body_that_is_too_long_is_422(tmp_path, calls):
    refused = client(tmp_path).post("/api/setup/download", content=b" " * (1 << 17))
    assert refused.status_code == 422 and calls == []


def test_the_body_is_checked_before_the_running_check(tmp_path, held):
    c = client(tmp_path)
    c.post("/api/setup/download")
    assert c.post("/api/setup/download", json={"ipv4": 1}).status_code == 422
    held.set()
    idle(c)


# GET /api/setup/events


def test_no_run_since_the_server_started_is_404(tmp_path):
    shown = client(tmp_path).get("/api/setup/events")
    assert (shown.status_code, shown.json()) == (404, {"error": "No download has started"})


def test_the_stream_says_it_starts_then_each_retry_then_ends(tmp_path, calls):
    assert run_to_end(client(tmp_path)) == [
        {"type": "progress", "message": START},
        {"type": "progress", "message": RETRY},
        {"type": "end", "status": "done", "message": "The AI models are ready."},
    ]


def test_the_start_line_says_when_the_run_uses_ipv4(tmp_path, calls):
    assert "over IPv4" in run_to_end(client(tmp_path), {"ipv4": True})[0]["message"]


def test_the_stream_is_an_event_stream_that_a_proxy_does_not_buffer(tmp_path, calls):
    c = client(tmp_path)
    c.post("/api/setup/download")
    shown = c.get("/api/setup/events")
    assert shown.headers["content-type"] == "text/event-stream"
    assert shown.headers["cache-control"] == "no-cache"
    assert shown.headers["x-accel-buffering"] == "no"


def test_a_stream_opened_after_the_run_gets_all_of_it(tmp_path, calls):
    c = client(tmp_path)
    live = run_to_end(c)
    idle(c)
    assert sse(c.get("/api/setup/events").text) == live


def test_a_late_subscriber_gets_the_run_so_far_then_the_live_events_once_each(tmp_path, held):
    app = create_app(tmp_path, token=None)
    setup = app.state.setup
    TestClient(app, base_url=LOCAL).post("/api/setup/download")
    wait_for(lambda: len(setup._events) == 2, 10)  # the start line and the retry

    async def main():
        call = asyncio.create_task(wire(app, "GET", "/api/setup/events", gone=asyncio.Event()))
        await subscribed(setup)
        with setup._lock:  # what the thread does for a line, while the reader is live
            setup._publish({"type": "progress", "message": "a live line"})
        held.set()
        return await asyncio.wait_for(call, 10)

    events = sse(asyncio.run(main()).body.decode())
    assert [e.get("message") for e in events[:3]] == [START, RETRY, "a live line"]
    assert events[-1]["type"] == "end" and len(events) == 4
    assert setup._subs == []  # unsubscribed after the end


def test_the_stream_stops_listening_when_the_client_goes(tmp_path, held):
    app = create_app(tmp_path, token=None)
    setup = app.state.setup
    TestClient(app, base_url=LOCAL).post("/api/setup/download")

    async def main():
        gone = asyncio.Event()
        call = asyncio.create_task(wire(app, "GET", "/api/setup/events", gone=gone))
        await subscribed(setup)
        assert len(setup._subs) == 1
        gone.set()  # the client goes
        await asyncio.wait_for(call, 5)

    asyncio.run(main())
    assert setup._subs == []


def test_the_stream_ends_at_once_when_the_server_is_stopping(tmp_path, held):
    app = create_app(tmp_path, token=None)
    TestClient(app, base_url=LOCAL).post("/api/setup/download")

    async def main():
        call = asyncio.create_task(wire(app, "GET", "/api/setup/events", gone=asyncio.Event()))
        await subscribed(app.state.setup)
        app.state.stopping.set()
        return await asyncio.wait_for(call, 2)

    wired = asyncio.run(main())
    assert wired.status == 200
    events = sse(wired.body.decode())  # the replay of the run so far, and no `end`
    assert events and all(e["type"] == "progress" for e in events)
    assert app.state.setup._subs == []


def test_a_quiet_stream_sends_a_keepalive_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "KEEPALIVE", 0.1)
    gate = threading.Event()
    monkeypatch.setattr(models_setup, "download_models", fake_download([], gate=gate, retries=0))
    app = create_app(tmp_path, token=None)
    TestClient(app, base_url=LOCAL).post("/api/setup/download")

    async def main():
        gone = asyncio.Event()
        call = asyncio.create_task(wire(app, "GET", "/api/setup/events", gone=gone))
        await asyncio.sleep(0.6)
        gone.set()
        return await asyncio.wait_for(call, 5)

    try:
        wired = asyncio.run(main())
    finally:
        gate.set()
    sent = [m["body"] for m in wired.messages[1:] if m.get("body")]
    assert sent[0].startswith(b"data: ")  # the start line
    assert 2 <= len(sent) <= 12 and set(sent[1:]) == {b": keepalive\n\n"}


# Failure and what the page may see


def test_a_failure_ends_with_failed_and_the_message_of_the_error(tmp_path, monkeypatch):
    error = RuntimeError("Download failed after 8 attempts (ConnectError: reset).")
    monkeypatch.setattr(models_setup, "download_models", fake_download([], fail=error))
    c = client(tmp_path)
    events = run_to_end(c)
    assert events[-1] == {
        "type": "end",
        "status": "failed",
        "message": "Download failed after 8 attempts (ConnectError: reset).",
    }
    assert c.get("/api/setup").json()["ready"] is False
    idle(c)
    assert c.post("/api/setup/download").status_code == 202  # a failed run can be tried again
    sse(c.get("/api/setup/events").text)


def test_an_error_without_text_still_ends_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(models_setup, "download_models", fake_download([], fail=OSError()))
    events = run_to_end(client(tmp_path))
    assert events[-1] == {"type": "end", "status": "failed", "message": "The download failed."}


def test_a_missing_vc_runtime_ends_the_run_with_its_message_and_tells_the_page_it_is_not_ipv4(
    tmp_path, monkeypatch, platform_is, vc_message
):
    def fail(**kwargs):
        raise OSError("could not find or load spatialindex_c-64.dll")

    monkeypatch.setattr("eco.models._docling_download", fail)  # the real download_models runs
    monkeypatch.setattr(models_setup, "download_models", download_models)
    platform_is("win32")
    c = client(tmp_path)
    events = run_to_end(c)
    assert [e["type"] for e in events] == ["progress", "end"]  # no retry was tried
    assert events[-1] == {
        "type": "end",
        "status": "failed",
        "message": vc_message,
        "vc_runtime_missing": True,
    }
    assert c.get("/api/setup").json()["ready"] is False
    idle(c)
    assert c.post("/api/setup/download").status_code == 202  # the plain retry stays
    sse(c.get("/api/setup/events").text)


@pytest.mark.parametrize("form", ["plain", "slashes", "oserror"])
def test_no_absolute_path_of_the_server_is_in_any_event(tmp_path, monkeypatch, form):
    root = models_dir(tmp_path)
    error = {
        "plain": RuntimeError(f"cannot write {root}"),
        "slashes": RuntimeError(f"cannot write {root.as_posix()}/layout"),
        "oserror": PermissionError(13, "Permission denied", str(root / "layout")),  # doubled
    }[form]

    def download(d, **kwargs):
        logging.getLogger("eco.models").warning("Attempt 1 of 8 failed (%s). Retrying.", error)
        raise error

    monkeypatch.setattr(models_setup, "download_models", download)
    events = run_to_end(client(tmp_path))
    text = json.dumps(events, ensure_ascii=False)
    for path in (str(tmp_path), tmp_path.as_posix(), str(tmp_path).replace("\\", "\\\\")):
        assert path not in text
    assert "<data>" in events[-1]["message"] and "<data>" in events[1]["message"]
    assert events[-1]["status"] == "failed"


def test_no_log_handler_is_left_on_eco_models(tmp_path, monkeypatch, calls):
    log = logging.getLogger("eco.models")
    before = list(log.handlers)
    c = client(tmp_path)
    run_to_end(c)
    idle(c)
    assert log.handlers == before
    monkeypatch.setattr(models_setup, "download_models", fake_download([], fail=RuntimeError("x")))
    run_to_end(c)
    idle(c)
    assert log.handlers == before


def test_a_handler_is_attached_for_the_run_only(tmp_path, held):
    log = logging.getLogger("eco.models")
    before = list(log.handlers)
    c = client(tmp_path)
    c.post("/api/setup/download")
    wait_for(lambda: len(log.handlers) == len(before) + 1, 10)
    held.set()
    idle(c)
    assert log.handlers == before


def test_a_line_logged_on_eco_models_after_the_run_is_not_an_event(tmp_path, calls):
    c = client(tmp_path)
    events = run_to_end(c)
    idle(c)
    logging.getLogger("eco.models").warning("something else")
    assert sse(c.get("/api/setup/events").text) == events


# The guard and the data folder


def test_the_setup_routes_need_the_token_in_network_mode(tmp_path, calls):
    token = "A-z_0123456789ab"
    c = TestClient(create_app(tmp_path, token=token), base_url=LOCAL)
    for method, path in [
        ("get", "/api/setup"),
        ("post", "/api/setup/download"),
        ("get", "/api/setup/events"),
    ]:
        refused = getattr(c, method)(path)
        assert (refused.status_code, refused.json()) == (401, {"error": "Missing or invalid token"})
    assert calls == []
    bearer = {"authorization": f"Bearer {token}"}
    assert c.get("/api/setup", headers=bearer).status_code == 200
    assert c.post("/api/setup/download", headers=bearer).status_code == 202
    sse(c.get("/api/setup/events", headers=bearer).text)


def test_a_post_from_another_site_is_refused(tmp_path, calls):
    refused = client(tmp_path).post("/api/setup/download", headers={"origin": "http://evil.test"})
    assert refused.status_code == 403 and calls == []


def test_the_wrong_method_is_405_in_the_error_shape(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/setup/download").status_code == 405
    refused = c.post("/api/setup")
    assert refused.status_code == 405 and "error" in refused.json()


def test_the_models_go_into_the_data_folders_models_folder(tmp_path, calls):
    run_to_end(client(tmp_path / "data"))
    assert calls[0]["dir"] == Path(tmp_path / "data" / "models")
