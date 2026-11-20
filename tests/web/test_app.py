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
from fakes import endless_work, untimed, wait_for
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from eco import cli
from eco.cli import main
from eco.options import DEVICES, FIRMWARES, MODES, OCR_MODES, SIZES, Options
from eco.style import RANGES
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


def test_the_page_changes_state_only_with_a_fetch_in_its_default_mode(tmp_path):
    # with no-referrer a browser sends `Origin: null` for a form POST and a fetch() in another
    # mode, and the guard refuses that
    assert not re.search(
        r"\bmode\s*:\s*['\"](?:no-cors|same-origin|cors|navigate)", source("app.js")
    )
    assert not re.search(r"<form\b", local(tmp_path).get("/").text)
    r = local(tmp_path).post("/api/jobs", headers={"Origin": "null"})
    assert r.status_code == 403


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
    """The text of one page file; app.js includes the modules it loads."""
    folder = "templates" if name.endswith(".html") else "static"
    if name == "app.js":
        return "\n".join(
            (SOURCES / folder / part).read_text(encoding="utf-8")
            for part in ("core.js", "start.js", "job.js", "review.js", "pagemap.js", "app.js")
        )
    return (SOURCES / folder / name).read_text(encoding="utf-8")


def test_page_has_the_places_of_the_workspace(tmp_path):
    html = local(tmp_path).get("/").text
    assert [p for p in PAGE_PLACES if f'id="{p}"' not in html] == []
    # the strings block holds every text, so the two lines must be in the markup itself
    markup = re.sub(r'<script id="strings".*?</script>', "", html, flags=re.DOTALL)
    assert "Runs on this computer" in markup
    assert "Approximate preview" in markup


def test_page_loads_its_script_and_style_from_the_static_folder(tmp_path):
    html = local(tmp_path).get("/").text
    assert re.search(r'<script src="/static/app\.js"[^>]*\btype="module"[^>]*\bdefer\b', html)
    assert '<link rel="stylesheet" href="/static/app.css">' in html
    assert '<link rel="icon" href="data:,">' in html  # no request for /favicon.ico, no 404 logged


@pytest.mark.parametrize(
    "name", ["app.js", "core.js", "start.js", "job.js", "review.js", "pagemap.js"]
)
def test_app_modules_are_served_as_javascript(tmp_path, name):
    r = local(tmp_path).get(f"/static/{name}")
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
    if not found:  # a group of radio buttons: its fieldset has the id
        found = re.search(rf'<fieldset id="{select_id}"[^>]*>(.*?)</fieldset>', html, re.DOTALL)
        return sorted(
            re.findall(r'<input type="radio" name="[^"]+" value="([^"]*)"', found.group(1))
        )
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
    html = local(tmp_path).get("/").text
    low, high = RANGES["font_size"]  # the one range: the server takes it from PageStyle
    fields = re.findall(r'<input id="style-font-size" type="[a-z]+" min="(\d+)" max="(\d+)"', html)
    assert fields == [(str(low), str(high))]


def test_the_page_keeps_the_font_size_in_the_style_of_the_options(tmp_path):
    js = source("app.js")
    assert "options.font_size" not in js  # M2's key
    assert "...selectedStyle" in function_body(js, "readOptions")  # the chosen saved style
    assert "style: review.live.style" in js  # a rebuild keeps every page-style field


def test_focus_mode_comes_from_the_reading_style_before_and_is_set_in_review(tmp_path):
    html, js = local(tmp_path).get("/").text, source("app.js")
    assert 'id="embed-focus"' not in html and 'id="select-style"' in html
    assert 'id="focus-mode"' in stage_markup(html, "review")
    assert "$('focus-controls').hidden = review.format === 'epub'" not in js


def test_epub_review_exposes_focus_mode_and_strength_without_opening_settings(tmp_path):
    html, js = local(tmp_path).get("/").text, source("app.js")
    dock = html.split('<div id="review-dock"', 1)[1].split("</section>", 1)[0]
    assert 'id="focus-mode"' in dock
    assert 'id="focus-strength"' in dock
    assert "review.live.style[name] = value" in js
    assert "if (review.pages && review.pages.device_pages > 0) refreshDevice();" in js
    assert "reviewFocusDirty()" not in js


def test_expert_review_keeps_common_reading_controls_in_the_main_dock(tmp_path):
    html = local(tmp_path).get("/").text
    review = stage_markup(html, "review")
    dock = review.split('<div id="review-dock"', 1)[1].split('<aside id="settings-panel"', 1)[0]
    for control in ("style-font-size", "line-height", "margin-x", "first-line-indent"):
        assert re.search(rf'<input id="{control}" type="range"', dock)
        assert f'for="{control}"' in dock
        assert f'id="{control}-value"' in dock
    assert 'id="focus-mode"' in dock
    assert 'id="focus-strength"' in dock
    assert review.index('id="source-pane"') < review.index('id="device-pane"')


def test_focus_strength_leaves_keyboard_navigation_when_focus_mode_is_off():
    body = function_body(source("app.js"), "syncReviewDock")
    assert "$('focus-strength').disabled = !focus" in body
    assert "$('focus-strength-field').hidden = !focus" in body


def test_review_dock_changes_shared_live_style_and_refreshes_the_preview():
    body = function_body(source("app.js"), "onReviewDockChange")
    assert "review.live.style[name]" in body
    assert "syncReviewDock();" in body
    assert "refreshDevice();" in body
    refresh = function_body(source("app.js"), "refreshDevice")
    assert "clearTimeout(review.liveTimer);" in refresh
    assert "if (review.liveAbort) review.liveAbort.abort();" in refresh


def test_review_approval_tracks_only_successful_files():
    js = source("app.js")
    assert "reviewed: new Set()" in function_body(js, "newReview")
    approval = function_body(js, "approveCurrentFile")
    assert "filter((index) => isConverted(state.job.files[index]))" in approval
    assert "review.reviewed.add(review.fileIndex)" in approval


def test_page_shortcuts_ignore_every_interactive_target():
    body = function_body(source("app.js"), "onKey")
    for tag in ("button", "a", "input", "select", "textarea"):
        assert tag in body


def test_export_is_a_separate_stage_with_downloads_and_back_navigation(tmp_path):
    html = local(tmp_path).get("/").text
    review = stage_markup(html, "review")
    export = stage_markup(html, "export")
    assert 'id="download"' not in review
    assert 'id="export-files"' in export
    assert 'id="export-status"' in export
    assert 'id="back-to-review"' in export
    assert 'id="delete-job"' in export
    assert 'id="delete-job"' not in review


def test_export_guard_requires_every_successful_file_to_be_reviewed():
    js = source("app.js")
    ready = function_body(js, "exportReady")
    assert "filter(isConverted)" in ready
    assert "review.reviewed.size" in ready
    shown = function_body(js, "showExport")
    assert "if (!exportReady())" in shown
    assert "showReview();" in shown


def test_export_builds_safe_download_links_for_each_output():
    body = function_body(source("app.js"), "renderExport")
    assert "Object.entries(info.outputs)" in body
    assert "URLS.fileDownload(job.id, index, format)" in body
    assert "download: true" in body


def test_returning_from_export_reuses_the_existing_review_state():
    js = source("app.js")
    show = function_body(js, "showExport")
    back = function_body(js, "backToReview")
    assert "state.review =" not in show
    assert "showReview();" in back


def test_review_sliders_group_their_label_value_and_control(tmp_path):
    review = stage_markup(local(tmp_path).get("/").text, "review")
    dock = review.split('<div id="review-dock"', 1)[1]
    for control in ("style-font-size", "line-height", "margin-x", "first-line-indent"):
        pattern = (
            rf'<div class="review-control">\s*<label for="{control}">.*?'
            rf'<output id="{control}-value".*?</output></label>\s*'
            rf'<input id="{control}" type="range"'
        )
        assert re.search(pattern, dock, re.DOTALL), control


def test_review_responsive_css_stacks_comparison_and_keeps_touch_targets_large():
    css = source("app.css")
    narrow = re.search(r"@media \(max-width: 700px\) \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert re.search(
        r"\.review-grid,.*?grid-template-columns:\s*minmax\(0, 1fr\)", narrow, re.DOTALL
    )
    coarse = re.search(
        r"@media \(pointer: coarse\), \(max-width: 700px\) \{(.*?)\n\}", css, re.DOTALL
    ).group(1)
    assert 'input[type="range"]' in coarse
    assert "min-height: 44px" in coarse


def test_step_navigation_wraps_in_document_flow():
    css = source("app.css")
    stepper = re.search(r"\.stepper ol \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "flex-wrap: wrap" in stepper
    assert "position: fixed" not in css


def test_review_and_export_statuses_are_text_not_color_only():
    assert STRINGS["reviewed"] == "reviewed"
    assert STRINGS["review_required"] == "review required"
    assert "warning" in STRINGS["export_warnings_one"].lower()
    assert "warnings" in STRINGS["export_warnings_other"].lower()


def test_the_expert_panel_is_named_advanced_typography():
    assert STRINGS["change_settings"] == "Advanced typography"


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
    """The source of one function in the app's modules."""
    found = re.search(rf"\n(?:export )?(?:async )?function {name}\(.*?\n\}}\n", js, re.DOTALL)
    assert found, f"app.js has no function {name}"
    return found.group(0)


def stage_markup(html, name):
    """The markup from the section of one stage up to the start of the next stage."""
    chunks = re.split(r'(?=<section id="stage-)', html)
    return next(c for c in chunks if c.startswith(f'<section id="stage-{name}"'))


def test_guided_workspace_has_four_product_steps_and_no_settings_step(tmp_path):
    html, js = local(tmp_path).get("/").text, source("app.js")
    assert [
        STRINGS[key] for key in ("step_select", "step_processing", "step_review", "step_export")
    ] == [
        "Select",
        "Convert",
        "Review",
        "Export",
    ]
    steps = re.search(r"export const STEPS = \[(.*?)\];", js, re.DOTALL).group(1)
    assert re.findall(r"step_[a-z]+", steps) == [
        "step_select",
        "step_processing",
        "step_review",
        "step_export",
    ]
    assert 'id="stage-export"' in html
    assert "step_settings" not in steps


def test_guided_select_keeps_every_conversion_option(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    ids = {
        "file-input",
        "device",
        "size",
        "firmware",
        "ocr",
        "mode",
        "select-style",
        "book-title",
        "book-author",
        "book-lang",
        "start",
    }
    assert [name for name in sorted(ids) if f'id="{name}"' not in select] == []


def test_guided_stages_never_show_competing_primary_actions(tmp_path):
    html = local(tmp_path).get("/").text
    for name in ("select", "processing", "review", "export"):
        stage = stage_markup(html, name)
        visible = re.findall(
            r'<(?:button|a)\b(?![^>]*\bhidden\b)[^>]*class="[^"]*\bprimary\b[^"]*"', stage
        )
        assert len(visible) <= 1, (name, visible)


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


def test_the_select_step_link_puts_the_focus_on_the_file_picker():
    js = source("app.js")
    assert "go = (event) => onStepLink(event, index)" in function_body(js, "stepItem")
    body = function_body(js, "onStepLink")
    assert "$('file-input').focus()" in body
    assert "$('device').focus()" not in body  # Settings is no longer a separate step.


def test_the_xtc_preview_toggle_is_enabled_and_has_a_visible_label(tmp_path):
    html = local(tmp_path).get("/").text
    radio = re.search(r'<input type="radio" name="preview-format" value="xtc"[^>]*>', html).group(0)
    assert "disabled" not in radio and "title=" not in radio
    assert f"<span>{STRINGS['output_xtc']}</span>" in html


# Ruling M2-R39: continue without the models


def test_the_texts_of_ruling_m2_r39():
    assert STRINGS["setup_skip"] == "Continue without models"
    assert STRINGS["models_download"] == "Download models"
    note = STRINGS["models_missing_note"]
    assert note == "Without the AI models, PDFs convert only with Layout set to Page images."
    # the note must use the names that the page gives the setting and its value
    assert STRINGS["mode_label"] in note and STRINGS["mode_pages"] in note


def test_there_is_no_setup_gate_and_the_models_notice_carries_the_download(tmp_path):
    html = local(tmp_path).get("/").text
    assert 'id="stage-setup"' not in html
    select = stage_markup(html, "select")
    note = select.split('id="models-note"', 1)[1].split('id="device"', 1)[0]
    for name in ("models-text", "models-download", "models-ipv4", "models-progress"):
        assert f'id="{name}"' in note, name
    assert 'id="models-log"' in note and 'id="models-error"' in note
    assert 'class="secondary"' in note and "primary" not in note  # Start stays the one primary
    js = source("app.js")
    assert not re.search(r"\bshowSetup\b", js) and "skipModels" not in js
    assert "showSelect();" in function_body(js, "showStart")
    bind = function_body(js, "bind")
    assert "$('models-download').addEventListener('click', () => startDownload(false));" in bind
    assert "$('models-ipv4').addEventListener('click', () => startDownload(true));" in bind
    for store in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert store not in js


def test_the_models_notice_names_the_size_of_the_download():
    assert STRINGS["models_needed"] == "PDFs need the AI models ({mb} MB, downloaded once)."
    assert "idle: () => t('models_needed', { mb: state.setup.total_mb })," in source("app.js")


def test_select_files_shows_the_note_while_the_models_are_missing():
    js = source("app.js")
    assert "renderModelsNote();" in function_body(js, "showSelect")
    assert "$('models-note').hidden = state.setup.ready" in function_body(js, "renderModelsNote")


def test_a_download_goes_on_when_the_user_leaves_the_gate_and_select_files_follows_it():
    js = source("app.js")
    assert "setSetupButtons(false);" in function_body(js, "init")  # set once, when the page starts
    assert "setup" not in function_body(js, "stopWork")  # a change of stage leaves the stream alone
    ended = function_body(js, "setupEnded")
    # Select files follows: the note goes, and the rows no longer warn about the models
    select = (
        r"if \(state\.stage === 'select'\) \{\s*renderModelsNote\(\);\s*renderDetails\(\);\s*\}"
    )
    assert re.search(select, ended)


# Task N2: the rows of Select files show pages, scan state and an estimate (M2-R41), and warn about
# the models (M2-R43). Two small fixes of the models note ride along. Still no browser: these read
# the page, the texts and the functions of the script that carry each rule.


def test_the_texts_of_the_file_rows():
    assert STRINGS["file_reading"] == "Reading…"
    assert (STRINGS["kind_markdown"], STRINGS["kind_epub"]) == ("Markdown", "EPUB")
    assert (STRINGS["pages_one"], STRINGS["pages_other"]) == ("1 page", "{n} pages")
    assert STRINGS["kind_digital"] == "Digital PDF"
    assert STRINGS["kind_scanned"] == "Scanned, uses OCR"
    assert STRINGS["kind_scanned_no_ocr"] == "Scanned, no OCR"
    assert STRINGS["kind_partly"] == "Partly scanned ({scanned} of {pages} pages)"
    assert STRINGS["estimate_about"] == "about {time}"
    assert STRINGS["estimate_short"] == "under a minute"


def test_the_texts_have_no_em_dash_and_no_emoji():
    assert {ch for text in STRINGS.values() for ch in text if ord(ch) > 126} <= {"…"}


def test_the_warnings_about_the_models_use_the_names_the_page_gives_the_setting():
    warning = STRINGS["row_needs_models"]
    assert warning == "Needs the AI models. Download them, or set Layout to Page images."
    texts = [warning, STRINGS["models_downloading_note"], STRINGS["models_failed_note"]]
    assert [
        t for t in texts if STRINGS["mode_label"] not in t or STRINGS["mode_pages"] not in t
    ] == []
    assert STRINGS["models_downloading_note"].startswith("The AI models are downloading.")
    assert STRINGS["models_failed_note"].startswith("The model download did not finish.")


def test_the_script_asks_the_inspect_route_and_reads_what_the_route_sends(tmp_path, fixtures_dir):
    app = create_app(tmp_path, token=None)
    routes = [r for r in app.routes if getattr(r, "path", None) == "/api/inspect"]
    assert len(routes) == 1 and "POST" in routes[0].methods
    js = source("app.js")
    assert "inspect: '/api/inspect'," in js
    pdf = fixtures_dir["blank"].read_bytes()
    r = TestClient(app, base_url=LOCAL).post("/api/inspect", files={"file": ("a.pdf", pdf)})
    answer = r.json()
    # `scan` is what the page keeps of an answer, beside its own `status` and `message`
    assert set(re.findall(r"\bscan\.(\w+)", js)) - {"status", "message"} == set(answer)
    assert set(re.findall(r"\brate\.(\w+)", js)) == set(answer["seconds_per_page"])


def test_the_pdfs_are_read_one_at_a_time_and_a_removed_file_is_cancelled():
    js = source("app.js")
    scan = function_body(js, "scanNext")
    assert "if (state.scanning || state.uploading) return;" in scan  # one at a time, not with a job
    assert "choice.scan && choice.scan.status === 'waiting'" in scan  # the first that waits
    assert "form.append('file', entry.file, entry.file.name);" in scan  # the field of the route
    assert "new AbortController()" in scan and "signal: entry.controller.signal" in scan
    assert "method: 'POST', body: form" in scan and "URLS.inspect" in scan
    # however a reading ends, the next one starts; one that was aborted is read again later
    assert re.search(r"state\.scanning = null;\s*renderDetails\(\);\s*scanNext\(\);\s*\}", scan)
    assert re.search(r"'AbortError' \? \{ status: 'waiting' \}", scan)
    remove = function_body(js, "removeFile")
    assert "state.files.splice(index, 1)" in remove and "removed.controller.abort()" in remove
    assert "state.scanning.controller.abort()" in function_body(js, "pauseScanning")
    assert re.search(r"\bscanning: null\b", js)


def test_choosing_files_starts_the_reading_and_the_upload_of_the_job_pauses_it():
    js = source("app.js")
    add = function_body(js, "addFiles")
    assert "state.files.push(newChoice(file))" in add and "scanNext();" in add
    start = function_body(js, "startConversion")
    assert re.search(r"state\.uploading = true;\s*pauseScanning\(\);", start)  # not two uploads
    assert re.search(r"showDropErrors\(\[error\.message\]\);\s*scanNext\(\);", start)  # and on
    assert "choice.file, choice.file.name" in start
    # Start never waits for a reading, and a PDF that could not be read does not stop it
    assert "$('start').disabled = count === 0 || state.uploading;" in function_body(
        js, "renderFiles"
    )


def test_a_row_is_its_size_then_what_is_known_of_the_file():
    row = function_body(source("app.js"), "rowText")
    assert "const parts = [formatSize(choice.file.size)];" in row
    assert "parts.push(t('kind_markdown'))" in row and "parts.push(t('kind_epub'))" in row
    assert "parts.push(t('file_reading'))" in row  # a PDF that waits or is being read
    assert "parts.push(tn('pages', choice.scan.pages), pdfKind(choice.scan, options));" in row
    assert "note = choice.scan.message;" in row  # the server's own text, in the muted line
    assert "parts.join(' · ')" in row


def test_the_estimate_follows_what_the_pipeline_does_with_the_settings():
    js = source("app.js")
    body = function_body(js, "estimateSeconds")
    steps = [
        "if (options.mode === 'pages') return scan.pages * rate.pages;",
        "if (options.ocr === 'off') return scan.pages * rate.digital;",
        "if (options.ocr === 'force') return scan.pages * rate.scanned;",
        "return (scan.pages - scan.scanned_pages) * rate.digital + scan.scanned_pages * rate.scanned;",
    ]
    places = [body.index(step) for step in steps]  # page images first, the automatic one last
    assert places == sorted(places)
    time = function_body(js, "approximateTime")
    assert "if (seconds < 45) return t('estimate_short');" in time
    assert "t('estimate_about', { time: formatMinutes(Math.round(seconds / 60)) })" in time


def test_a_pdf_is_digital_scanned_or_partly_scanned_and_ocr_is_named_only_when_it_runs():
    body = function_body(source("app.js"), "pdfKind")
    assert "if (scan.scanned_pages === 0) return t('kind_digital');" in body
    partly = "if (scan.scanned_pages * 2 <= scan.pages) {"  # most is more than half
    assert (
        partly in body
        and "t('kind_partly', { scanned: scan.scanned_pages, pages: scan.pages })" in body
    )
    # no OCR runs on page images, nor when it is off
    assert "options.mode !== 'pages' && options.ocr !== 'off'" in body
    assert "t('kind_scanned')" in body and "t('kind_scanned_no_ocr')" in body


def test_the_rows_are_worked_out_again_when_the_device_layout_or_ocr_changes():
    js = source("app.js")
    bind = function_body(js, "bind")
    for setting in ("device", "mode", "ocr"):
        assert f"$('{setting}').addEventListener('change', renderDetails);" in bind
    details = function_body(js, "renderDetails")
    assert "readOptions()" in details  # the settings as they are now
    assert "replaceChildren" not in details  # only text changes, so a row with the focus keeps it
    scan = function_body(js, "scanNext")
    assert "renderDetails();" in scan and "renderFiles" not in scan  # an answer redraws no row
    assert "renderDetails();" in function_body(js, "renderFiles")


def test_a_pdf_row_warns_in_place_of_the_estimate_while_the_models_are_missing_and_needed():
    js = source("app.js")
    needs = function_body(js, "needsModels")
    assert "return !state.setup.ready && options.mode !== 'pages';" in needs
    row = function_body(js, "rowText")
    instead = (
        r"if \(needsModels\(options\)\) note = t\('row_needs_models'\);\s*"
        r"else parts\.push\(approximateTime\(estimateSeconds\(choice\.scan, options\)\)\);"
    )
    assert re.search(instead, row)  # the estimate is added only in the other branch


def test_the_file_rows_have_a_detail_line_a_note_and_the_style_for_them():
    css, js = source("app.css"), source("app.js")
    rows = function_body(js, "renderFiles")
    assert all(name in rows for name in ("file-name", "file-detail", "file-note"))
    assert "file-detail" in css and "file-note" in css
    assert "file-size" not in css and "file-size" not in js  # the class that this replaced


def test_select_files_shows_a_download_that_runs_and_one_that_failed():
    js = source("app.js")
    assert "download: 'idle'," in js  # a new page load has started no download
    assert "state.download = 'running';" in function_body(js, "startDownload")
    failed = function_body(js, "showSetupError")  # every way a download ends badly comes here
    assert "state.download = 'failed';" in failed and "renderModelsNote();" in failed
    assert "state.download = 'idle';" in function_body(js, "setupEnded")
    note = function_body(js, "renderModelsNote")
    assert "setText($('models-text'), MODELS_NOTE[state.download]());" in note
    for name, key in (
        ("running", "models_downloading_note"),
        ("failed", "models_failed_note"),
    ):
        assert f"{name}: () => t('{key}')," in js


def test_a_missing_vc_runtime_shows_its_message_alone_without_the_ipv4_button_and_hint():
    js = source("app.js")
    ended = function_body(js, "setupEnded")
    assert (
        "if (event.vc_runtime_missing) showSetupError(event.message, null, null, false);" in ended
    )
    # every other failure keeps the IPv4 hint, and the button
    assert (
        "else showSetupError(t('setup_stopped'), event.message, t('setup_stopped_hint'));" in ended
    )
    error = function_body(js, "showSetupError")
    assert "function showSetupError(lead, detail, hint, offerIpv4 = true)" in error
    assert "setSetupButtons(true, offerIpv4);" in error
    buttons = function_body(js, "setSetupButtons")
    assert "function setSetupButtons(failed, offerIpv4 = failed)" in buttons
    assert "$('models-ipv4').hidden = !offerIpv4;" in buttons
    assert "download.textContent = failed ? t('try_again')" in buttons  # the plain retry stays


def test_the_focus_leaves_the_models_note_before_the_note_is_hidden(tmp_path):
    focus = (
        "if (state.setup.ready && $('models-note').contains(document.activeElement)) "
        "$('files-title').focus();"
    )
    note = function_body(source("app.js"), "renderModelsNote")
    assert focus in note
    assert note.index(focus) < note.index("$('models-note').hidden = state.setup.ready")
    assert re.search(r'<h2 id="files-title"[^>]*tabindex="-1"', local(tmp_path).get("/").text)


# The M2 fix wave: ruling M2-R45 (delete a conversion from Review) and the live timer on "View
# as". Still no browser: these read the page, the texts and the functions that carry each rule.


def test_the_texts_of_ruling_m2_r45():
    assert STRINGS["delete_job"] == "Delete conversion"
    assert STRINGS["deleting"] == "Deleting…"
    assert STRINGS["delete_confirm"] == (
        "Delete this conversion? The uploaded files, the EPUB files and the previews are "
        "removed, and this cannot be undone."
    )
    assert STRINGS["error_not_ended"] == (
        "This conversion has not finished. Cancel it before you delete it."
    )


def test_export_has_a_low_emphasis_delete_button_and_a_line_for_its_failure(tmp_path):
    export = stage_markup(local(tmp_path).get("/").text, "export")
    button = (
        f'<button id="delete-job" type="button" class="link-button destructive">'
        f"{STRINGS['delete_job']}"
    )
    assert f"{button}</button>" in export
    assert '<p id="delete-error" class="error-text" role="alert" hidden></p>' in export


def test_a_failed_review_still_offers_a_low_emphasis_delete_action(tmp_path):
    review = stage_markup(local(tmp_path).get("/").text, "review")
    button = (
        '<button id="review-delete-job" type="button" class="link-button destructive">'
        f"{STRINGS['delete_job']}"
    )
    assert f"{button}</button>" in review
    assert '<p id="review-delete-error" class="error-text" role="alert" hidden></p>' in review


def test_delete_asks_first_and_then_goes_to_select_files_which_reads_the_recent_ones_again():
    js = source("app.js")
    bind = function_body(js, "bind")
    assert "$('delete-job').addEventListener('click', deleteJob);" in bind
    assert "$('review-delete-job').addEventListener('click', deleteJob);" in bind
    body = function_body(js, "deleteJob")
    asked = body.index("if (!window.confirm(t('delete_confirm'))) return;")
    assert asked < body.index("request(URLS.job(id), { method: 'DELETE' })")
    # the job leaves the address, so Back does not lead to it, and the route shows the start
    gone = "history.replaceState(null, '', location.pathname + location.search);"
    assert body.index(gone) < body.index("route().catch(pageFailed);")
    assert "loadRecent();" in function_body(js, "showSelect")  # which reads the list again
    assert "if (mine !== state.sequence) return;" in body  # the user went elsewhere meanwhile


def test_a_failed_delete_shows_the_servers_text_and_a_job_already_gone_counts_as_deleted():
    js = source("app.js")
    body = function_body(js, "deleteJob")
    assert "if (error.status !== 404) {" in body
    assert "setText(errorLine, error.message);" in body
    assert "errorLine.hidden = false;" in body
    assert "setText(button, t('deleting'));" in body and "setText(button, t('delete_job'));" in body
    # a disabled button loses the keyboard focus; after a failure it gets it back
    assert body.index("button.disabled = false;") < body.index("button.focus();")
    reset = function_body(js, "resetReviewDom")  # one button for every job
    for part in ("['delete-job', 'delete-error']", "['review-delete-job', 'review-delete-error']"):
        assert part in reset
    assert "$(errorId).hidden = true" in reset


def test_a_change_of_view_stops_a_live_preview_that_waits_or_is_on_its_way():
    # the timer's request reads review.pages, which a change of view empties
    body = function_body(source("app.js"), "onViewChange")
    emptied = body.index("review.pages = null")
    assert body.index("clearTimeout(review.liveTimer);") < emptied
    assert body.index("if (review.liveAbort) review.liveAbort.abort();") < emptied


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
        assert untimed(store.events(job.id)) == [{"type": "file", "index": 0, "status": "started"}]
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
    broken = store.reserve()  # a job.json that another eco wrote, or a power loss emptied
    (broken / "job.json").write_text("{not json", encoding="utf-8")
    young = store.create([("b.md", io.BytesIO(b"# B"))], Options())
    young.status = "done"  # not queued again by the start
    store.save(young)
    with TestClient(create_app(tmp_path, token=None), base_url=LOCAL):
        assert not cut.exists()
        assert broken.exists()  # it goes by its age, like any job
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


OTHER_DEVICES = "On another device, use this computer's network address in place of {local}."


def test_web_made_up_token_opens_the_app(served, capsys, tmp_path):
    main(["web", "--host", "0.0.0.0", "--port", "9000", "--no-browser", "--data", str(tmp_path)])
    [line] = open_line(capsys.readouterr().out)
    # no device can open 0.0.0.0: this computer opens its loopback address
    found = re.fullmatch(r"Open: http://127\.0\.0\.1:9000/\?token=([A-Za-z0-9_-]{32})", line)
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
    assert line.startswith("Open: http://[::1]:8000/?token=")
    assert served["run"][1]["host"] == "::"


@pytest.mark.parametrize("host, local", [("0.0.0.0", "127.0.0.1"), ("::", "[::1]")])
def test_web_on_every_address_says_how_other_devices_reach_it(
    served, capsys, tmp_path, host, local
):
    main(["web", "--host", host, "--token", GOOD, "--no-browser", "--data", str(tmp_path)])
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"Open: http://{local}:8000/?token={GOOD}", OTHER_DEVICES.format(local=local)]


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.20"])
def test_web_on_one_address_prints_that_address_alone(served, capsys, tmp_path, host):
    # an address of this computer on the network opens from every device as it is
    main(["web", "--host", host, "--token", GOOD, "--no-browser", "--data", str(tmp_path)])
    assert capsys.readouterr().out.splitlines() == [f"Open: http://{host}:8000/?token={GOOD}"]


@pytest.mark.parametrize("limit", ["0", "-1", "1.5", "x"])
def test_web_takes_a_positive_whole_upload_limit_only(served, capsys, tmp_path, limit):
    # 0 or less once refused every upload with "File too large (limit 0 MB)"
    argv = ["web", "--max-upload-mb", limit, "--no-browser", "--data", str(tmp_path / "d")]
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "--max-upload-mb: must be a whole number of MB above 0" in err
    assert served["run"] is None and not (tmp_path / "d").exists()


def test_the_help_names_every_command(capsys):
    assert main(["--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "Convert PDF and Markdown to EPUB and optimize EPUB files" in out
    assert "in a web browser (eco web)" in out
    for command in ("setup", "convert", "extract", "web"):
        assert command in out


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


# The page map redesign: tokens, font, shell and the page map module


def test_the_page_uses_the_bundled_inter_font_and_the_new_tokens():
    css = source("app.css")
    assert 'url("fonts/InterVariable.woff2")' in css
    tokens = ("#fafaf9", "#18181b", "#52525b", "#71717a", "#1d4ed8", "#15803d", "#b45309")
    tokens += ("#f59e0b", "#b91c1c", "#3f3f46", "#6d28d9", "#d4d4d8", "#e4e4e7")
    for token in tokens:
        assert token in css.lower(), token
    assert "font: 14px/1.5 Inter," in css


def test_the_font_and_its_licence_are_served(tmp_path):
    c = local(tmp_path)
    font = c.get("/static/fonts/InterVariable.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    assert font.content[:4] == b"wOF2"
    assert "SIL Open Font License" in c.get("/static/fonts/OFL.txt").text


def test_the_header_names_the_four_steps_and_runs_locally(tmp_path):
    html = local(tmp_path).get("/").text
    header = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
    assert 'id="stepper"' in header and STRINGS["runs_locally"] in header
    assert STRINGS["runs_locally"] == "Runs on this computer"


def test_the_stepper_links_back_to_convert_and_review_only_where_valid():
    body = function_body(source("app.js"), "stepItem")
    assert "showProcessing()" in body and "isActive(state.job)" in body
    assert "backToReview()" in body and "state.stage === 'export'" in body


def test_page_map_module_keeps_large_books_to_1500_squares():
    js = source("app.js")
    assert "<= 1500" in function_body(js, "pagesPerSquare")
    assert "<= 600" in function_body(js, "squareSize")
    cells = function_body(js, "mapCells")
    assert "pagesPerSquare(" in cells and "document" not in cells  # pure
    for state in ("'finding'", "'now'", "'todo'", "'done'", "'scanned'", "'digital'"):
        assert state in js
    assert "<= 600" in function_body(js, "stripBars")


def test_page_map_renderer_reuses_its_squares():
    body = function_body(source("app.js"), "renderPageMap")
    assert "container.children.length !== cells.length" in body
    assert "setProperty('--pm-size'" in body
    assert "className" in body and "title" in body


def test_page_map_labels_are_strings():
    assert STRINGS["pagemap_page"] == "Page {n}"
    assert STRINGS["pagemap_pages"] == "Pages {first} to {last}"
    for key in ("pagemap_blank", "pagemap_scanned", "pagemap_finding"):
        assert f"t('{key}')" in source("app.js")


# Select with page maps, a reading style and the model download in the page


def test_select_has_the_book_column_and_four_reading_settings(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    for name in ("drop-zone", "file-list", "device", "select-style", "size", "advanced"):
        assert f'id="{name}"' in select, name
    for name in ("start", "start-estimate", "recent", "recent-title"):
        assert f'id="{name}"' in select, name
    assert len(re.findall(r'name="output"', select)) == 2
    assert len(re.findall(r'<input type="radio" name="size"', select)) == 3
    assert 'id="font-size"' not in select and 'id="embed-focus"' not in select
    assert select.index('id="drop-zone"') < select.index('id="device"')  # book, then settings
    assert STRINGS["workspace_title"] == "Convert a book"
    assert "PDF, Markdown or EPUB, up to 500 MB" in select  # the server's own limit


def test_more_settings_holds_the_rest_and_the_font_library(tmp_path):
    select = stage_markup(local(tmp_path).get("/").text, "select")
    more = select.split('<details id="advanced"', 1)[1].split("</details>", 1)[0]
    for name in ("firmware", "ocr", "mode", "book-title", "book-author", "book-lang"):
        assert f'id="{name}"' in more, name
    assert 'id="font-library"' in more and 'id="library-font-upload"' in more
    assert STRINGS["more_settings"] == "More settings"


def test_a_pdf_row_draws_its_page_map_from_the_inspect_lists():
    js = source("app.js")
    body = function_body(js, "renderDetails")
    assert "mapCells(" in body and "'select'" in body and "renderPageMap(" in body
    assert "role: 'img'" in function_body(js, "renderFiles")
    assert "t('pagemap_summary'" in body
    assert "choice.scan.scanned" in body and "choice.scan.blank" in body


def test_the_start_options_take_style_values_from_the_chosen_style():
    body = function_body(source("app.js"), "readOptions")
    assert "$('font-size')" not in body and "$('embed-focus')" not in body
    assert "...selectedStyle" in body
    assert 'input[name="size"]:checked' in body


def test_the_start_button_shows_the_total_estimate():
    body = function_body(source("app.js"), "renderDetails")
    assert "$('start-estimate')" in body and "estimateSeconds(" in body
    assert STRINGS["start_estimate"] == "About {time} in total on this computer"


def test_recent_rows_name_status_in_words_and_offer_a_link():
    body = function_body(source("app.js"), "recentRow")
    assert "status-${job.status}" in body
    assert "t('recent_open')" in body and "t('recent_details')" in body
