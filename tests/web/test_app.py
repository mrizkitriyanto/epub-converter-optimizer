import hmac
import io
import json
import re
import subprocess
import sys
import threading
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from eco import cli
from eco.cli import main
from eco.options import Options
from eco.web.app import CSP, create_app
from eco.web.jobs import JobStore, Runner
from eco.web.strings import STRINGS

LOCAL = "http://127.0.0.1:8000"  # a browser on this computer, server on the default port
SECURE = {
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}
DENIED = {"error": "Missing or invalid token"}


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
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
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
    for path in ("/api/jobs", "/nope"):
        assert c.get(path).status_code == 404  # past the guard: no such route (yet)


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


def test_app_keeps_its_store_runner_and_upload_limit(tmp_path):
    app = create_app(tmp_path, token=None, max_upload_mb=7)
    assert app.state.store.root == tmp_path / "jobs"
    assert isinstance(app.state.runner, Runner)
    assert app.state.max_upload_mb == 7
    assert create_app(tmp_path, token=None).state.max_upload_mb == 500


# eco web


@pytest.fixture
def served(monkeypatch):
    """`eco web` without a server or a browser: what uvicorn.run and webbrowser.open got."""
    seen = {"opened": [], "run": None}
    opened = threading.Event()
    monkeypatch.delenv("ECO_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_BROWSER_DELAY", 0.05)

    def run(app, **kwargs):
        seen["run"] = (app, kwargs)
        opened.wait(seen.get("wait", 0))

    def open_(url):
        seen["opened"].append(url)
        opened.set()

    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setattr("webbrowser.open", open_)
    return seen


def open_line(out):
    return [line for line in out.splitlines() if line.startswith("Open: ")]


def test_web_on_this_computer_needs_no_token(served, capsys, tmp_path):
    assert main(["web", "--no-browser", "--data", str(tmp_path)]) == 0
    assert open_line(capsys.readouterr().out) == ["Open: http://127.0.0.1:8000/"]
    app, kwargs = served["run"]
    assert kwargs == {"host": "127.0.0.1", "port": 8000, "log_level": "warning"}
    assert TestClient(app, base_url=LOCAL).get("/").status_code == 200


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
    monkeypatch.setenv("ECO_TOKEN", "from-env")
    main(["web", "--no-browser", "--data", str(tmp_path)])
    main(["web", "--token", "from option", "--no-browser", "--data", str(tmp_path)])
    assert open_line(capsys.readouterr().out) == [
        "Open: http://127.0.0.1:8000/?token=from-env",
        "Open: http://127.0.0.1:8000/?token=from%20option",
    ]
    app, _ = served["run"]
    c = TestClient(app, base_url=LOCAL)
    assert c.get("/", headers={"Authorization": "Bearer from-env"}).status_code == 401
    assert c.get("/", headers={"Authorization": "Bearer from option"}).status_code == 200


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
        (["--host", "0.0.0.0", "--token", "t"], "http://127.0.0.1:8000/?token=t"),
        (["--host", "::", "--token", "t"], "http://[::1]:8000/?token=t"),
        (["--host", "192.168.1.20", "--token", "t"], "http://192.168.1.20:8000/?token=t"),
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
