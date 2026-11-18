import asyncio
import hmac
import io
import json
import logging
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fakes import endless_work, wait_for
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from eco import cli
from eco.cli import main
from eco.options import DEVICES, FIRMWARES, MODES, OCR_MODES, SIZES, Options
from eco.web import app as web_app
from eco.web import jobs, preview
from eco.web.app import CSP, _Guard, create_app
from eco.web.jobs import JobStore, Runner
from eco.web.strings import STRINGS

LOCAL = "http://127.0.0.1:8000"  # a browser on this computer, server on the default port
SECURE = {
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}
DENIED = {"error": "Missing or invalid token"}
GOOD = "A-z_0123456789ab"  # 16 characters: the shortest token eco web takes
TOKEN_RULE = "error: The token must be at least 16 characters, each one of A-Z, a-z, 0-9, - or _."


def local(tmp_path, **kwargs):
    return TestClient(create_app(tmp_path, token=None, **kwargs), base_url=LOCAL)


def with_echo(app):
    """The app plus one route for every state-changing method, to see a request get through."""
    app.add_api_route("/echo", lambda: {"ok": True}, methods=["POST", "PUT", "PATCH", "DELETE"])
    return app


def secured(response):
    return {k: response.headers.get(k) for k in SECURE} == SECURE


# The three tests of the brief


def test_token_required_everywhere(tmp_path):
    c = TestClient(create_app(tmp_path, token="s3cret"))
    for url in ("/", "/static/app.css", "/api/jobs", "/api/setup"):
        assert c.get(url).status_code == 401
    assert c.get("/?token=s3cret", follow_redirects=False).status_code in (302, 307)
    assert c.get("/").status_code == 200  # cookie now set


def test_security_headers(tmp_path):
    r = TestClient(create_app(tmp_path, token=None)).get("/")
    assert r.headers["content-security-policy"].startswith("default-src 'self'")


def test_web_generates_token_for_lan(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("uvicorn.Server.run", lambda *a, **k: None)
    main(["web", "--host", "0.0.0.0", "--no-browser", "--data", str(tmp_path)])
    assert "?token=" in capsys.readouterr().out


# Token


PATHS = ["/", "/static/app.css", "/static/missing.css", "/api/jobs", "/api/setup", "/nope"]
CREDENTIALS = [
    {},
    {"headers": {"Authorization": "Bearer wrong"}},
    {"headers": {"Authorization": "Basic s3cret"}},
    {"headers": {"Authorization": "s3cret"}},
    {"headers": {"Authorization": "Bearer s3cret-and-more"}},
    {"headers": {"Authorization": "Bearer \xe9".encode("latin-1")}},
    {"cookies": {"eco_token": "wrong"}},
    {"cookies": {"eco_token": ""}},
    {"params": {"token": "s3cret"}},  # the address-bar token logs in at / only
]


@pytest.mark.parametrize(
    "path, credentials",
    [(p, c) for p in PATHS for c in CREDENTIALS if not (p == "/" and "params" in c)],
    ids=lambda v: repr(v)[:40],
)
def test_wrong_or_missing_token_is_refused_on_every_path(tmp_path, path, credentials):
    credentials = dict(credentials)  # shared by every path
    c = TestClient(create_app(tmp_path, token="s3cret"), cookies=credentials.pop("cookies", None))
    for method in ("GET", "POST"):
        r = c.request(method, path, follow_redirects=False, **credentials)
        assert (r.status_code, r.json()) == (401, DENIED)


@pytest.mark.parametrize("token", ["wrong", "", "s3cre", "\xe9", "s3cret "])
def test_wrong_address_bar_token_is_refused(tmp_path, token):
    c = TestClient(create_app(tmp_path, token="s3cret"))
    c.cookies.set("eco_token", "s3cret")  # even with a good cookie: the wrong token is an error
    r = c.get(f"/?token={quote(token)}", follow_redirects=False)
    assert (r.status_code, r.json()) == (401, DENIED)
    assert "set-cookie" not in r.headers


def test_bearer_token_opens_every_path(tmp_path):
    c = TestClient(create_app(tmp_path, token="s3cret"), headers={"Authorization": "bearer s3cret"})
    assert c.get("/").status_code == 200
    assert c.get("/static/app.css").status_code == 200
    assert c.get("/api/jobs").status_code == 200  # past the guard: a route of the jobs API
    assert c.get("/nope").status_code == 404  # past the guard: no such route


def test_address_bar_token_becomes_a_strict_http_only_cookie(tmp_path):
    c = TestClient(create_app(tmp_path, token="s3cret"))
    r = c.get("/?token=s3cret", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"
    parts = [p.strip() for p in r.headers["set-cookie"].split(";")]
    assert parts[0] == "eco_token=s3cret"
    assert {p.lower() for p in parts[1:]} == {"httponly", "samesite=strict", "path=/"}
    assert c.get("/static/app.css").status_code == 200
    assert c.get("/nope").status_code == 404


def test_token_with_odd_characters_works_in_cookie_and_header(tmp_path):
    token = 'a b;c"d,e\\f'
    c = TestClient(create_app(tmp_path, token=token))
    assert c.get(f"/?token={quote(token, safe='')}", follow_redirects=False).status_code == 302
    assert c.get("/").status_code == 200
    c.cookies.clear()
    assert c.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_tokens_are_compared_in_constant_time(tmp_path, monkeypatch):
    compared = []

    def compare_digest(a, b):
        compared.append((a, b))
        return a == b

    monkeypatch.setattr(hmac, "compare_digest", compare_digest)
    c = TestClient(create_app(tmp_path, token="s3cret"))
    c.get("/", headers={"Authorization": "Bearer x"})
    c.get("/?token=y", follow_redirects=False)
    c.cookies.set("eco_token", "z")
    c.get("/")
    assert {(b"x", b"s3cret"), (b"y", b"s3cret"), (b"z", b"s3cret")} <= set(compared)


def test_empty_token_means_local_mode(tmp_path):
    c = TestClient(create_app(tmp_path, token=""), base_url=LOCAL)
    assert c.get("/").status_code == 200


# Security headers


def test_csp_is_exactly_the_one_of_the_constraints():
    assert CSP == SECURE["content-security-policy"]


def test_security_headers_on_every_kind_of_response(tmp_path):
    token = TestClient(create_app(tmp_path, token="s3cret"))
    responses = {
        "401": token.get("/static/app.css"),
        "302": token.get("/?token=s3cret", follow_redirects=False),
    }
    app = with_echo(create_app(tmp_path, token=None))

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    c = TestClient(app, base_url=LOCAL, raise_server_exceptions=False)
    responses |= {
        "200 page": c.get("/"),
        "200 static": c.get("/static/app.css"),
        "404 static": c.get("/static/missing.css"),
        "404": c.get("/nope"),
        "403 host": c.get("/", headers={"Host": "evil.example:8000"}),
        "403 origin": c.post("/echo", headers={"Origin": "http://evil.example"}),
        "500": c.get("/boom"),
    }
    assert {name: r.status_code for name, r in responses.items()} == {
        name: int(name[:3]) for name in responses
    }
    assert [name for name, r in responses.items() if not secured(r)] == []


def test_static_css_is_served_as_css(tmp_path):
    r = local(tmp_path).get("/static/app.css")
    assert r.headers["content-type"].startswith("text/css")


# Host and Origin in local mode (M2-R11)


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "LocalHost:8000"]
)
def test_local_mode_answers_at_a_loopback_name(tmp_path, host):
    assert local(tmp_path).get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example:8000",  # DNS rebinding: the attacker's name resolves to 127.0.0.1
        "evil.example",
        "127.0.0.1",  # no port, but the server is not on 80
        "localhost:8001",
        "127.0.0.1:80",
        "localhost.evil.example:8000",
        "127.0.0.1.nip.io:8000",
        "localhost.:8000",
        "::1:8000",
        "",
    ],
)
def test_local_mode_refuses_any_other_host(tmp_path, host):
    r = local(tmp_path).get("/", headers={"Host": host})
    assert (r.status_code, r.json()) == (403, {"error": STRINGS["error_host"]})


@pytest.mark.parametrize("path", ["/static/app.css", "/api/jobs", "/nope"])
def test_local_mode_refuses_a_foreign_host_before_routing(tmp_path, path):
    assert local(tmp_path).get(path, headers={"Host": "evil.example:8000"}).status_code == 403


def test_local_mode_on_port_80_takes_a_host_without_port(tmp_path):
    c = TestClient(create_app(tmp_path, token=None), base_url="http://localhost")
    assert c.get("/", headers={"Host": "localhost"}).status_code == 200
    assert c.get("/", headers={"Host": "localhost:80"}).status_code == 200
    assert c.get("/", headers={"Host": "localhost:8000"}).status_code == 403


def test_token_mode_answers_at_any_host(tmp_path):
    c = TestClient(create_app(tmp_path, token="s3cret"), base_url="http://192.168.1.20:8000")
    r = c.get("/", headers={"Authorization": "Bearer s3cret", "Host": "eco-box.lan:8000"})
    assert r.status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "http://127.0.0.1:8001",
        "https://127.0.0.1:8000",
        "http://localhost:8000",  # another loopback name is another origin
        "null",
    ],
)
def test_state_change_from_another_origin_is_refused(tmp_path, method, origin):
    c = TestClient(with_echo(create_app(tmp_path, token=None)), base_url=LOCAL)
    r = c.request(method, "/echo", headers={"Origin": origin})
    assert (r.status_code, r.json()) == (403, {"error": STRINGS["error_origin"]})


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://127.0.0.1:8000"},
        {"Origin": "HTTP://127.0.0.1:8000"},
        {"Host": "localhost:8000", "Origin": "http://localhost:8000"},
        {"Host": "[::1]:8000", "Origin": "http://[::1]:8000"},
    ],
)
def test_state_change_from_the_app_or_without_origin_gets_through(tmp_path, method, headers):
    c = TestClient(with_echo(create_app(tmp_path, token=None)), base_url=LOCAL)
    r = c.request(method, "/echo", headers=headers)
    assert (r.status_code, r.json()) == (200, {"ok": True})


def test_reading_from_another_origin_is_not_an_origin_error(tmp_path):
    assert local(tmp_path).get("/", headers={"Origin": "http://evil.example"}).status_code == 200


def test_token_mode_still_refuses_a_state_change_from_another_origin(tmp_path):
    app = with_echo(create_app(tmp_path, token="s3cret"))
    c = TestClient(app, base_url=LOCAL, headers={"Authorization": "Bearer s3cret"})
    r = c.post("/echo", headers={"Origin": "http://evil.example"})
    assert (r.status_code, r.json()) == (403, {"error": STRINGS["error_origin"]})
    assert c.post("/echo", headers={"Origin": LOCAL}).status_code == 200
    assert c.post("/echo").status_code == 200


# Websockets and other scopes (M2-R14)


@pytest.mark.parametrize(
    "token, headers",
    [
        (None, {}),  # local mode, this computer's address
        ("s3cret", {"Authorization": "Bearer s3cret"}),  # network mode, the right token
        ("s3cret", {"Host": "evil.example:8000"}),  # network mode, no token, another site
    ],
)
def test_websocket_is_refused_before_any_route(tmp_path, token, headers):
    app = create_app(tmp_path, token=token)
    reached = []

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        reached.append(True)
        await websocket.accept()
        await websocket.send_text("the user's books")

    c = TestClient(app, base_url=LOCAL)
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        c.websocket_connect("ws://127.0.0.1:8000/ws", headers=headers),
    ):
        pass
    assert (closed.value.code, reached) == (1008, [])


def test_guard_lets_only_lifespan_and_http_through():
    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(scope["type"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    for token in (None, "s3cret"):
        guard = _Guard(app, token)
        for kind in ("lifespan", "websocket", "webtransport", "something-new"):
            asyncio.run(guard({"type": kind}, receive, send))
    assert reached == ["lifespan", "lifespan"]
    assert sent == [{"type": "websocket.close", "code": 1008}] * 2


# The page


def test_page_embeds_the_strings_as_json_that_no_string_can_break(tmp_path, monkeypatch):
    monkeypatch.setitem(STRINGS, "zz_test", "</script><script>alert(1)</script><!-- & '  ")
    html = local(tmp_path).get("/").text
    found = re.search(
        r'<script id="strings" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    assert json.loads(found.group(1)) == STRINGS
    assert "<script>alert(1)" not in html and "<!--" not in html


def test_page_is_the_shell_in_english(tmp_path):
    r = local(tmp_path).get("/")
    assert r.headers["content-type"].startswith("text/html")
    assert '<html lang="en">' in r.text and STRINGS["local_only"] in r.text
    assert '<link rel="stylesheet" href="/static/app.css">' in r.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_no_api_docs_pages(tmp_path, path):
    # Swagger UI and ReDoc load their files from a CDN
    assert local(tmp_path).get(path).status_code == 404


# The workspace (Task 9). No browser runs the script in these tests, so besides the places the
# page must have, they check what a typo in the script or the page would break without a sound.

SOURCES = Path(web_app.HERE)
PAGE_PLACES = [
    "stepper",
    "drop-zone",
    "device",
    "size",
    "start",
    "progress",
    "findings",
    "source-pane",
    "device-pane",
    "view-as",
]


def source(name):
    """The text of one of the three files of the page: index.html, app.css or app.js."""
    folder = "templates" if name.endswith(".html") else "static"
    return (SOURCES / folder / name).read_text(encoding="utf-8")


def test_page_has_the_places_of_the_workspace(tmp_path):
    html = local(tmp_path).get("/").text
    assert [p for p in PAGE_PLACES if f'id="{p}"' not in html] == []
    # the strings block holds every text, so the two lines must be in the markup itself
    markup = re.sub(r'<script id="strings".*?</script>', "", html, flags=re.DOTALL)
    assert "Everything is processed on this computer." in markup
    assert "Approximate preview" in markup


def test_page_loads_its_script_and_style_from_the_static_folder(tmp_path):
    html = local(tmp_path).get("/").text
    assert re.search(r'<script src="/static/app\.js"[^>]*\bdefer\b', html)
    assert '<link rel="stylesheet" href="/static/app.css">' in html
    assert '<link rel="icon" href="data:,">' in html  # no request for /favicon.ico, no 404 logged


def test_app_js_is_served_as_javascript(tmp_path):
    r = local(tmp_path).get("/static/app.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")


def test_the_script_is_javascript_whatever_the_system_maps_js_to(tmp_path, monkeypatch):
    # /etc/mime.types and the Windows registry may say application/javascript
    monkeypatch.setitem(mimetypes.types_map, ".js", "application/javascript")
    r = local(tmp_path).get("/static/app.js")
    assert r.headers["content-type"].startswith("text/javascript")


def test_no_external_address_in_the_page_its_style_or_its_script(tmp_path):
    rendered = local(tmp_path).get("/").text
    found = {
        name: text
        for name, text in {
            "index.html": source("index.html"),
            "rendered page": rendered,
            "app.css": source("app.css"),
            "app.js": source("app.js"),
        }.items()
        if "http://" in text or "https://" in text
    }
    assert list(found) == []


def test_css_and_script_make_no_blob_address(tmp_path):
    # img-src is 'self' data:, so a picture is shown by its own address or as a data URL
    assert [n for n in ("app.css", "app.js") if "blob:" in source(n)] == []


def test_page_has_no_inline_style_script_or_event_handler(tmp_path):
    for html in (source("index.html"), local(tmp_path).get("/").text):
        tags = re.findall(r"<[a-zA-Z][^>]*>", html)
        assert [t for t in tags if re.search(r"\sstyle\s*=", t)] == []
        assert [t for t in tags if re.search(r"\son[a-z]+\s*=", t)] == []
        scripts = [t for t in tags if t.startswith("<script")]
        assert scripts and all('src="' in t or 'type="application/json"' in t for t in scripts)


def test_script_sets_no_style_attribute_and_builds_no_markup_from_text():
    js = source("app.js")
    assert not re.search(r"setAttribute\(\s*['\"]style['\"]", js)  # CSP: style-src 'self'
    # the names of files and the messages of the server are not trusted: text goes in as text
    risky = r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function"
    assert re.findall(risky, js) == []


def test_css_keeps_a_visible_focus_ring():
    css = source("app.css")
    assert ":focus-visible" in css
    assert not re.search(r"outline\s*:\s*(none|0)\b", css)


def test_every_text_the_page_and_the_script_use_is_in_strings():
    js = source("app.js")
    html = re.sub(r"\{#.*?#\}", "", source("index.html"), flags=re.DOTALL)  # not the comments
    used = set(re.findall(r"\bt\('([a-z0-9_]+)'", js))
    used |= {f"{k}_{n}" for k in re.findall(r"\btn\('([a-z0-9_]+)'", js) for n in ("one", "other")}
    used |= set(re.findall(r"strings\.([a-z0-9_]+)", html))
    assert len(used) > 50  # the patterns still find the texts
    assert sorted(used - set(STRINGS)) == []


def test_every_element_the_script_looks_up_is_in_the_page(tmp_path):
    html = local(tmp_path).get("/").text
    looked_up = set(re.findall(r"\$\('([a-z0-9-]+)'\)", source("app.js")))
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(looked_up) > 30 and sorted(looked_up - set(ids)) == []
    assert sorted({i for i in ids if ids.count(i) > 1}) == []  # an id is in the page once


def options_of(html, select_id):
    found = re.search(rf'<select id="{select_id}">(.*?)</select>', html, re.DOTALL)
    return sorted(re.findall(r'<option value="([^"]*)"', found.group(1)))


def test_the_choices_of_the_page_are_the_ones_the_server_takes(tmp_path):
    html = local(tmp_path).get("/").text
    expected = {
        "device": DEVICES,
        "size": SIZES,
        "live-size": SIZES,
        "firmware": FIRMWARES,
        "ocr": OCR_MODES,
        "mode": MODES,
        "view-as": preview.VIEWS,
    }
    assert {name: options_of(html, name) for name in expected} == {
        name: sorted(values) for name, values in expected.items()
    }


def test_the_page_takes_the_files_and_the_job_ids_that_the_server_makes(tmp_path):
    html, js = local(tmp_path).get("/").text, source("app.js")
    accepted = re.search(r'<input id="file-input"[^>]*\saccept="([^"]*)"', html).group(1)
    assert sorted(accepted.split(",")) == sorted(jobs.KINDS)
    kinds = re.search(r"SUPPORTED_FILE = /(.*)/i;", js).group(1)
    assert all(re.search(kinds, f"book{suffix}", re.IGNORECASE) for suffix in jobs.KINDS)
    assert not re.search(kinds, "report.docx", re.IGNORECASE)
    job = JobStore(tmp_path).create([("a.md", io.BytesIO(b"# A"))], Options())
    ids = re.search(r"/\^#job=\((.*?)\)\$/", js).group(1)  # how the script reads the address
    assert re.fullmatch(ids, job.id)


def test_the_font_size_limits_of_the_page_are_the_servers(tmp_path):
    html, js = local(tmp_path).get("/").text, source("app.js")
    low, high = web_app.FONT_SIZES.start, web_app.FONT_SIZES.stop - 1
    fields = re.findall(
        r'<input id="(?:font-size|live-font)" type="[a-z]+" min="(\d+)" max="(\d+)"', html
    )
    assert fields == [(str(low), str(high))] * 2
    assert re.search(rf"Math\.min\({high}, Math\.max\({low}, ", js)  # the clamp in the script


def test_every_api_address_in_the_script_is_a_route(tmp_path):
    app = create_app(tmp_path, token=None)
    found = re.findall(r"""['"`](/api/[^'"`]*)['"`]""", source("app.js"))
    assert len(found) > 10
    unknown = []
    for address in found:
        path = re.sub(r"\$\{[^}]*\}", "x", address).split("?")[0]  # a value, and no query
        if not any(r.path_regex.match(path) for r in app.routes if hasattr(r, "path_regex")):
            unknown.append(address)
    assert unknown == []


# Task 9, fix round 1. Still no browser, so these read the page and the functions of the script
# that carry each fix. They would fail on the page of commit 999f85c.


def function_body(js, name):
    """The source of one function of app.js. They all sit one level inside its closure: each
    starts at two spaces and ends at a closing brace that has two spaces."""
    found = re.search(rf"\n  (?:async )?function {name}\(.*?\n  \}}\n", js, re.DOTALL)
    assert found, f"app.js has no function {name}"
    return found.group(0)


def stage_markup(html, name):
    """The markup from the section of one stage up to the start of the next stage."""
    chunks = re.split(r'(?=<section id="stage-)', html)
    return next(c for c in chunks if c.startswith(f'<section id="stage-{name}"'))


def test_a_new_review_starts_with_the_panel_closed_and_the_buttons_as_new():
    # the panel, Apply and Try again are the same elements for every job
    js = source("app.js")
    assert "resetReviewDom();" in function_body(js, "showReview")
    reset = function_body(js, "resetReviewDom")
    assert "hidePanel();" in reset
    assert "setText($('apply'), t('apply'))" in reset  # not "Applying…" from the job before
    assert "$('try-again').disabled = false" in reset
    assert "$('panel-error').hidden = true" in reset and "setText($('panel-error'), '')" in reset
    hide = function_body(js, "hidePanel")
    for part in ("$('settings-panel').hidden = true", "classList.remove('with-panel')"):
        assert part in hide
    assert "setAttribute('aria-expanded', 'false')" in hide
    assert "hidePanel();" in function_body(js, "closePanel")


def test_the_lists_of_review_are_not_kept_from_another_job():
    js = source("app.js")
    # two jobs can have the same pattern of converted files, so the job is part of the key
    pick = function_body(js, "renderFilePick")
    assert "const key = `${job.id}:" in pick
    findings = function_body(js, "renderFindings")
    assert "const key = `${state.job.id}:" in findings


def test_the_replay_of_a_stream_ends_on_a_gap_between_two_events_not_on_a_slow_start():
    js = source("app.js")
    gap = r"stream\.lastAt !== null\s*&&\s*now - stream\.lastAt >= REPLAY_GAP_MS"
    assert re.search(gap, function_body(js, "listen"))
    assert "openedAt" not in js  # the time the stream was opened decides nothing


def test_a_late_reason_for_a_failed_picture_is_not_written_under_another_page():
    body = function_body(source("app.js"), "explainImage")
    assert re.search(r"if \(image\.getAttribute\('src'\) === address\) setText\(status, ", body)
    assert body.count("setText(") == 1  # every answer, a reason or a network error, goes through it


def test_each_step_link_puts_the_focus_where_it_leads():
    js = source("app.js")
    assert "onclick: (event) => onStepLink(event, index)" in function_body(js, "stepItem")
    body = function_body(js, "onStepLink")
    assert "$('file-input').focus()" in body and "$('device').focus()" in body


def test_the_xtc_hint_of_the_preview_toggle_is_text_on_the_page_and_not_a_tooltip(tmp_path):
    html = local(tmp_path).get("/").text
    radio = re.search(r'<input type="radio" name="preview-format" value="xtc"[^>]*>', html).group(0)
    described = re.search(r'aria-describedby="([^"]+)"', radio)
    assert described, "the disabled toggle names its hint"
    hint = re.search(rf'<p id="{described.group(1)}" class="([^"]*)">([^<]*)</p>', html)
    assert hint and hint.group(2) == STRINGS["coming_later"]
    assert "visually-hidden" not in hint.group(1)
    assert f'title="{STRINGS["coming_later"]}"' not in html  # a tooltip needs a pointer


# Ruling M2-R39: continue without the models


def test_the_texts_of_ruling_m2_r39():
    assert STRINGS["setup_skip"] == "Continue without models"
    assert STRINGS["models_download"] == "Download models"
    note = STRINGS["models_missing_note"]
    assert note == "Without the AI models, PDFs convert only with Layout set to Page images."
    # the note must use the names that the page gives the setting and its value
    assert STRINGS["mode_label"] in note and STRINGS["mode_pages"] in note


def test_the_setup_gate_has_one_primary_button_and_a_secondary_one_to_go_on(tmp_path):
    gate = stage_markup(local(tmp_path).get("/").text, "setup")
    buttons = re.findall(
        r'<button id="([^"]+)" type="button" class="([^"]+)"[^>]*>([^<]*)</button>', gate
    )
    assert [i for i, classes, _ in buttons if "primary" in classes.split()] == ["setup-download"]
    skip = [(classes, text) for i, classes, text in buttons if i == "setup-skip"]
    assert skip == [("secondary", STRINGS["setup_skip"])]


def test_select_files_has_the_note_about_the_models_and_a_secondary_button_to_the_gate(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    note = re.search(r'<div id="models-note" class="[^"]*" hidden>(.*?)</div>', select, re.DOTALL)
    assert note, "the note is in the markup, hidden until the script shows it"
    assert f'<p class="muted">{STRINGS["models_missing_note"]}</p>' in note.group(1)
    button = '<button id="models-download" type="button" class="secondary">'
    assert f"{button}{STRINGS['models_download']}</button>" in note.group(1)
    assert "primary" not in note.group(1)  # Start conversion stays the one primary button


def test_the_script_goes_on_without_the_models_for_this_page_load_only():
    js = source("app.js")
    assert re.search(r"state\.setup\.ready \|\| state\.skipModels", function_body(js, "showStart"))
    go_on = function_body(js, "continueWithoutModels")
    assert "state.skipModels = true;" in go_on and "showSelect();" in go_on
    assert js.count("skipModels = true") == 1  # set by that button and by nothing else
    assert re.search(r"skipModels: false", js)  # a new page load starts at the gate
    for store in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert store not in js  # the choice is not remembered across visits
    bind = function_body(js, "bind")
    assert "$('setup-skip').addEventListener('click', continueWithoutModels);" in bind
    assert "$('models-download').addEventListener('click', showSetup);" in bind


def test_select_files_shows_the_note_while_the_models_are_missing():
    js = source("app.js")
    assert "renderModelsNote();" in function_body(js, "showSelect")
    assert "$('models-note').hidden = state.setup.ready" in function_body(js, "renderModelsNote")


def test_a_download_goes_on_when_the_user_leaves_the_gate_and_select_files_follows_it():
    js = source("app.js")
    # the gate keeps what the download made of it (a running download, a failure): showing the gate
    # again must not reset its buttons, or the primary button would start a second download
    show = function_body(js, "showSetup")
    assert "setSetupButtons" not in show and "setup-error" not in show
    assert "setSetupButtons(false);" in function_body(js, "init")  # set once, when the page starts
    assert "setup" not in function_body(js, "stopWork")  # a change of stage leaves the stream alone
    ended = function_body(js, "setupEnded")
    assert re.search(r"else if \(state\.stage === 'select'\) renderModelsNote\(\);", ended)


# Lifespan


def test_startup_purges_before_the_runner_starts_and_shutdown_stops_it(
    tmp_path, monkeypatch, fake_worker
):
    calls = []
    for cls, name in ((JobStore, "purge"), (Runner, "start"), (Runner, "stop")):
        original = getattr(cls, name)

        def record(self, *a, _name=name, _original=original, **k):
            calls.append(_name)
            return _original(self, *a, **k)

        monkeypatch.setattr(cls, name, record)
    store = JobStore(tmp_path)
    old = store.create([("old.md", io.BytesIO(b"# Old"))], Options())
    old.created -= 8 * 86400  # past RETENTION_DAYS, still queued
    store.save(old)
    app = create_app(tmp_path, token=None)
    with TestClient(app, base_url=LOCAL):
        assert calls == ["purge", "start"]
        assert store.list() == []  # gone, never queued
    assert calls == ["purge", "start", "stop"]


def record_calls(monkeypatch):
    """The names of the JobStore.purge, Runner.start and Runner.stop calls from now on."""
    calls = []
    for cls, name in ((JobStore, "purge"), (Runner, "start"), (Runner, "stop")):
        original = getattr(cls, name)

        def record(self, *a, _name=name, _original=original, **k):
            calls.append(_name)
            return _original(self, *a, **k)

        monkeypatch.setattr(cls, name, record)
    return calls


def test_second_server_on_the_same_data_stops_before_it_touches_a_job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "_work", endless_work)
    first = create_app(tmp_path, token=None)
    with TestClient(first, base_url=LOCAL):
        store = first.state.store
        job = store.create([("a.md", io.BytesIO(b"# A"))], Options())
        first.state.runner.submit(job.id)
        wait_for(lambda: store.events(job.id), 10)  # its worker runs
        calls = record_calls(monkeypatch)
        try:
            with TestClient(create_app(tmp_path, token=None), base_url=LOCAL):
                refused = None
        except RuntimeError as e:
            refused = str(e)
        # the first server's job goes on as if nothing happened
        assert store.get(job.id).status == "running"
        assert store.events(job.id) == [{"type": "file", "index": 0, "status": "started"}]
        assert calls == []
        assert refused == f"Another eco web is already using {tmp_path}"


def test_servers_on_other_data_folders_and_one_after_another_run(tmp_path):
    a, b = create_app(tmp_path / "a", token=None), create_app(tmp_path / "b", token=None)
    with TestClient(a, base_url=LOCAL) as ca, TestClient(b, base_url=LOCAL) as cb:
        assert (ca.get("/").status_code, cb.get("/").status_code) == (200, 200)
    with TestClient(create_app(tmp_path / "a", token=None), base_url=LOCAL) as again:
        assert again.get("/").status_code == 200


def test_app_keeps_its_store_runner_and_upload_limit(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=7)
    assert app.state.store.root == tmp_path / "jobs"
    assert isinstance(app.state.runner, Runner)
    assert app.state.max_upload_mb == 7
    assert create_app(tmp_path, token=None).state.max_upload_mb == 500


# Expiry of the jobs


def old_job(store, status):
    """A job made 8 days ago, with `status`, and no worker for it."""
    info = store.create([("a.md", io.BytesIO(b"# A"))], Options())
    info.created -= 8 * 86400
    info.status = status
    store.save(info)
    return info


def test_start_removes_a_folder_without_a_job_json_whatever_its_age(tmp_path):
    store = JobStore(tmp_path)
    cut = store.reserve()  # an upload that a hard kill cut: no job.json, made minutes ago
    (cut / "input" / "0").mkdir()
    (cut / "input" / "0" / "a.md").write_bytes(b"# A")
    broken = store.reserve()
    (broken / "job.json").write_text("{not json", encoding="utf-8")
    young = store.create([("b.md", io.BytesIO(b"# B"))], Options())
    young.status = "done"  # not queued again by the start
    store.save(young)
    with TestClient(create_app(tmp_path, token=None), base_url=LOCAL):
        assert not cut.exists() and not broken.exists()
        assert store.job_dir(young.id).exists()


def test_the_purge_at_start_takes_the_orphans_and_the_hourly_one_does_not_wait_for_an_hour(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(web_app, "PURGE_EVERY", 0.05)
    calls = []  # (the keywords of the call, the thread it ran in)
    purge = JobStore.purge

    def spy(self, *args, **kwargs):
        calls.append((kwargs, threading.get_ident()))
        return purge(self, *args, **kwargs)

    monkeypatch.setattr(JobStore, "purge", spy)
    app = create_app(tmp_path, token=None)
    store = app.state.store
    with TestClient(app, base_url=LOCAL):
        writing = store.reserve()  # an upload that is coming in, made minutes ago
        os.utime(writing, (time.time() - 300,) * 2)
        expired, waiting, running = (old_job(store, s) for s in ("done", "queued", "running"))
        wait_for(lambda: not store.root.joinpath(expired.id).exists(), 10)  # the hourly purge
        wait_for(lambda: len(calls) >= 4, 10)  # which has been round more than once by now
        assert [store.root.joinpath(j.id).exists() for j in (waiting, running)] == [True, True]
        assert writing.exists()  # a folder without job.json goes by its age here, not at once
    assert [kwargs for kwargs, _ in calls[:2]] == [{"orphans": True}, {"keep_queued": True}]
    assert all(kwargs == {"keep_queued": True} for kwargs, _ in calls[1:])
    assert all(thread != calls[0][1] for _, thread in calls[1:])  # not on the loop's thread
    made = len(calls)
    time.sleep(0.3)  # six times the interval
    assert len(calls) == made  # the server has stopped, and so has the purge


def test_a_purge_that_fails_does_not_end_the_hourly_purge(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(web_app, "PURGE_EVERY", 0.05)
    calls = []
    purge = JobStore.purge

    def flaky(self, *args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:  # the first hourly one; the first of all is the start's
            raise OSError("the disk is busy")
        return purge(self, *args, **kwargs)

    monkeypatch.setattr(JobStore, "purge", flaky)
    with TestClient(create_app(tmp_path, token=None), base_url=LOCAL):
        wait_for(lambda: len(calls) >= 4, 10)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "The hourly purge failed"
    ]


# eco web


@pytest.fixture
def served(monkeypatch):
    """`eco web` without a server or a browser: the server that was to run (`seen["server"]`), its
    app with the settings of its uvicorn config (`seen["run"]`), and what webbrowser.open got."""
    seen = {"opened": [], "run": None, "server": None}
    opened = threading.Event()
    monkeypatch.delenv("ECO_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_BROWSER_DELAY", 0.05)

    def run(server, sockets=None):  # uvicorn.Server.run
        config = server.config
        settings = ("host", "port", "log_level", "timeout_graceful_shutdown")
        seen["run"] = (config.app, {name: getattr(config, name) for name in settings})
        seen["server"] = server
        opened.wait(seen.get("wait", 0))

    def open_(url):
        seen["opened"].append(url)
        opened.set()

    monkeypatch.setattr("uvicorn.Server.run", run)
    monkeypatch.setattr("webbrowser.open", open_)
    return seen


def open_line(out):
    return [line for line in out.splitlines() if line.startswith("Open: ")]


def test_web_on_this_computer_needs_no_token(served, capsys, tmp_path):
    assert main(["web", "--no-browser", "--data", str(tmp_path)]) == 0
    assert open_line(capsys.readouterr().out) == ["Open: http://127.0.0.1:8000/"]
    app, kwargs = served["run"]
    assert kwargs == {
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "warning",
        "timeout_graceful_shutdown": 5,  # for what the stop flag does not end: it takes 5 s at most
    }
    assert TestClient(app, base_url=LOCAL).get("/").status_code == 200


def test_web_runs_the_server_that_tells_the_app_to_stop(served, tmp_path):
    main(["web", "--no-browser", "--data", str(tmp_path)])
    server, (app, _) = served["server"], served["run"]
    assert isinstance(server, web_app.Server)
    server.handle_exit(signal.SIGINT, None)  # what Ctrl+C does: the app's streams are told to end
    assert app.state.stopping.is_set()


def test_web_ends_quietly_on_the_ctrl_c_that_uvicorn_passes_on(monkeypatch, capsys, tmp_path):
    def stopped(server, sockets=None):  # uvicorn raises the Ctrl+C that stopped it once it has
        raise KeyboardInterrupt

    monkeypatch.setattr("uvicorn.Server.run", stopped)
    try:
        code = main(["web", "--no-browser", "--data", str(tmp_path)])
    except KeyboardInterrupt:  # one that got out would end the whole test session
        pytest.fail("eco web did not take the Ctrl+C that uvicorn passes on")
    assert code == 0
    out, err = capsys.readouterr()
    assert err == "" and open_line(out) == ["Open: http://127.0.0.1:8000/"]


def test_web_made_up_token_opens_the_app(served, capsys, tmp_path):
    main(["web", "--host", "0.0.0.0", "--port", "9000", "--no-browser", "--data", str(tmp_path)])
    [line] = open_line(capsys.readouterr().out)
    found = re.fullmatch(r"Open: http://0\.0\.0\.0:9000/\?token=([A-Za-z0-9_-]{32})", line)
    assert found
    app, kwargs = served["run"]
    assert (kwargs["host"], kwargs["port"]) == ("0.0.0.0", 9000)
    c = TestClient(app)
    assert c.get("/").status_code == 401
    assert c.get("/", headers={"Authorization": f"Bearer {found.group(1)}"}).status_code == 200


def test_web_made_up_token_is_new_each_time(served, capsys, tmp_path):
    for _ in range(2):
        main(["web", "--host", "192.168.1.20", "--no-browser", "--data", str(tmp_path)])
    first, second = open_line(capsys.readouterr().out)
    assert first != second


def test_web_token_from_env_and_option(served, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("ECO_TOKEN", "token-from-the-env")
    main(["web", "--no-browser", "--data", str(tmp_path)])
    main(["web", "--token", "token_from_the_option", "--no-browser", "--data", str(tmp_path)])
    assert open_line(capsys.readouterr().out) == [
        "Open: http://127.0.0.1:8000/?token=token-from-the-env",
        "Open: http://127.0.0.1:8000/?token=token_from_the_option",
    ]
    app, _ = served["run"]
    c = TestClient(app, base_url=LOCAL)
    assert c.get("/", headers={"Authorization": "Bearer token-from-the-env"}).status_code == 401
    assert c.get("/", headers={"Authorization": "Bearer token_from_the_option"}).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        "short",
        GOOD[:15],
        "café-café-café-café",
        "aaaaaaaaaa bbbbbbbbbb",
        "abcdefghijklmnop.",
        "abcdefghijklmnop+",
        "abcdefghijklmnop\n",
    ],
)
@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_web_refuses_a_weak_token(served, capsys, tmp_path, token, host):
    argv = ["web", "--host", host, "--token", token, "--no-browser", "--data", str(tmp_path / "d")]
    assert main(argv) == 2
    assert capsys.readouterr() == ("", TOKEN_RULE + "\n")
    assert served["run"] is None
    assert not (tmp_path / "d").exists()  # refused before anything is made


@pytest.mark.parametrize("token", ["short", "café-café-café-café"])
def test_web_refuses_a_weak_eco_token(served, capsys, monkeypatch, tmp_path, token):
    monkeypatch.setenv("ECO_TOKEN", token)
    assert main(["web", "--no-browser", "--data", str(tmp_path)]) == 2
    assert capsys.readouterr() == ("", TOKEN_RULE + "\n")
    assert served["run"] is None


@pytest.mark.parametrize("token", [GOOD, "Z" * 64, "-_-_-_-_-_-_-_-_"])
def test_web_takes_a_strong_token(served, capsys, tmp_path, token):
    assert main(["web", f"--token={token}", "--no-browser", "--data", str(tmp_path)]) == 0
    assert open_line(capsys.readouterr().out) == [f"Open: http://127.0.0.1:8000/?token={token}"]
    app, _ = served["run"]
    c = TestClient(app, base_url=LOCAL)
    assert c.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 200


@pytest.mark.parametrize(
    "host, line, bind",
    [
        ("::1", "Open: http://[::1]:8000/", "::1"),
        ("localhost", "Open: http://localhost:8000/", "localhost"),
    ],
)
def test_web_loopback_hosts_print_their_address(served, capsys, tmp_path, host, line, bind):
    main(["web", "--host", host, "--no-browser", "--data", str(tmp_path)])
    assert open_line(capsys.readouterr().out) == [line]
    assert served["run"][1]["host"] == bind


def test_web_ipv6_any_address_is_bracketed_and_needs_a_token(served, capsys, tmp_path):
    main(["web", "--host", "::", "--no-browser", "--data", str(tmp_path)])
    [line] = open_line(capsys.readouterr().out)
    assert line.startswith("Open: http://[::]:8000/?token=")
    assert served["run"][1]["host"] == "::"


def test_second_eco_web_on_the_same_data_stops_with_one_line(capsys, monkeypatch, tmp_path):
    ran = []

    def run(server, sockets=None):  # as uvicorn: the app's lifespan runs
        ran.append(server.config.app)
        with TestClient(server.config.app):
            pass

    monkeypatch.setattr("uvicorn.Server.run", run)
    with TestClient(create_app(tmp_path, token=None), base_url=LOCAL):
        calls = record_calls(monkeypatch)
        code = main(["web", "--port", "8001", "--no-browser", "--data", str(tmp_path)])
        assert (code, ran, calls) == (1, [], [])
    out, err = capsys.readouterr()
    assert (out, err) == ("", f"error: Another eco web is already using {tmp_path}\n")


def test_eco_web_on_another_data_folder_runs(served, capsys, tmp_path):
    with TestClient(create_app(tmp_path / "a", token=None), base_url=LOCAL):
        assert main(["web", "--no-browser", "--data", str(tmp_path / "b")]) == 0
    assert served["run"] is not None


def test_web_passes_the_data_folder_and_upload_limit(served, tmp_path):
    main(["web", "--no-browser", "--max-upload-mb", "3", "--data", str(tmp_path / "d")])
    app, _ = served["run"]
    assert app.state.store.root == tmp_path / "d" / "jobs"
    assert app.state.max_upload_mb == 3


@pytest.mark.parametrize(
    "argv, url",
    [
        ([], "http://127.0.0.1:8000/"),
        (["--host", "::1", "--port", "8001"], "http://[::1]:8001/"),
        (["--host", "0.0.0.0", "--token", GOOD], f"http://127.0.0.1:8000/?token={GOOD}"),
        (["--host", "::", "--token", GOOD], f"http://[::1]:8000/?token={GOOD}"),
        (["--host", "192.168.1.20", "--token", GOOD], f"http://192.168.1.20:8000/?token={GOOD}"),
    ],
)
def test_web_opens_the_browser_once_the_server_runs(served, tmp_path, argv, url):
    served["wait"] = 5
    main(["web", *argv, "--data", str(tmp_path)])
    assert served["opened"] == [url]


def test_web_no_browser_opens_none(served, tmp_path):
    served["wait"] = 0.5  # ten times the browser delay
    main(["web", "--no-browser", "--data", str(tmp_path)])
    assert served["opened"] == []


def test_web_browser_is_not_opened_when_the_server_ends_first(served, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_BROWSER_DELAY", 0.3)
    main(["web", "--data", str(tmp_path)])  # run returns at once, as when the port is taken
    threading.Event().wait(0.6)
    assert served["opened"] == []


@pytest.mark.parametrize("argv", [["--version"], ["setup", "--help"], ["web", "--help"]])
def test_other_commands_do_not_import_the_web_stack(argv):
    code = (
        "import sys\n"
        "from eco.cli import main\n"
        f"main({argv!r})\n"
        "print(sorted(m for m in ('fastapi', 'starlette', 'uvicorn') if m in sys.modules))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[-1] == "[]"
