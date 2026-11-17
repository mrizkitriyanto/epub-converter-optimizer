"""The web app: one page, its static files, and the /api routes of later tasks.

Every request passes `_Guard` before any route sees it, and every response leaves through it:

- Local mode (no token; `eco web` listens on a loopback address). A request must be addressed
  to `127.0.0.1`, `localhost` or `[::1]` at the port the server listens on. Otherwise a web page
  whose own name resolves to 127.0.0.1 (DNS rebinding) could read the user's books through the
  user's browser: 403.
- Network mode (a token). Each request carries the token as `Authorization: Bearer <token>` or
  in the `eco_token` cookie, else 401. `GET /?token=<token>` sets the cookie and redirects to
  `/`, so the token leaves the address bar.
- Both modes refuse a POST, PUT, PATCH or DELETE whose `Origin` is another site's: 403.
- Websockets are closed (1008) before any route; only HTTP and lifespan scopes reach the app.
- Every response, refusals and errors included, carries CSP, nosniff, no-referrer and
  `X-Frame-Options: DENY` (no other site can frame the app).
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from eco.web.jobs import JobStore, Runner, server_lock
from eco.web.strings import STRINGS

HERE = Path(__file__).parent
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'"
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
COOKIE = "eco_token"
_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

_templates = Jinja2Templates(directory=HERE / "templates")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _same(given: str, token: str) -> bool:
    """Compare in constant time. As bytes: compare_digest refuses text that is not ASCII."""
    return hmac.compare_digest(given.encode(), token.encode())


def _loopback_hosts(scope: Scope) -> set[str]:
    """The Host headers of a request to this server at a loopback name: with the port the server
    listens on, or without a port when that port is HTTP's default."""
    server = scope.get("server")
    if not server:
        return set()  # port unknown: refuse all
    hosts = {f"{name}:{server[1]}" for name in _LOOPBACK_NAMES}
    return (hosts | set(_LOOPBACK_NAMES)) if server[1] == 80 else hosts


class _Guard:
    """The outermost layer of the app (see the module docstring)."""

    def __init__(self, app: ASGIApp, token: str | None):
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":  # the GUI uses none (SSE), so none is let in
            await send({"type": "websocket.close", "code": 1008})
        elif scope["type"] == "http":
            await self._http(scope, receive, send)
        # any other kind of scope never reaches the app

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(SECURITY_HEADERS)
            await send(message)

        refusal = self._refusal(Request(scope))
        await (refusal or self.app)(scope, receive, send_secured)

    def _refusal(self, request: Request) -> Response | None:
        """The response that refuses the request, or None to let it through."""
        method, host = request.method, request.headers.get("host", "").lower()
        if self.token is None:
            if host not in _loopback_hosts(request.scope):
                return _error(403, STRINGS["error_host"])
        elif method == "GET" and request.scope["path"] == "/" and "token" in request.query_params:
            return self._login(request.query_params["token"])
        elif not self._authorized(request):
            return _error(401, STRINGS["error_token"])
        origin = request.headers.get("origin")
        own = f"{request.scope['scheme']}://{host}"
        if method in _STATE_CHANGING and origin is not None and origin.lower() != own:
            return _error(403, STRINGS["error_origin"])
        return None

    def _authorized(self, request: Request) -> bool:
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and _same(given, self.token):
            return True
        return _same(request.cookies.get(COOKIE, ""), self.token)

    def _login(self, given: str) -> Response:
        """`GET /?token=<t>`: the right token goes into a cookie, and the browser to `/`."""
        if not _same(given, self.token):
            return _error(401, STRINGS["error_token"])
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(COOKIE, self.token, httponly=True, samesite="strict", path="/")
        return response


class _App(FastAPI):
    """FastAPI with `_Guard` outside all of its own middleware, so the 500 that FastAPI sends for
    an unhandled error passes the guard too."""

    def __init__(self, token: str | None, **kwargs):
        super().__init__(**kwargs)
        self.token = token

    def build_middleware_stack(self) -> ASGIApp:
        return _Guard(super().build_middleware_stack(), self.token)


def create_app(data_dir: Path, *, token: str | None, max_upload_mb: int = 500) -> FastAPI:
    """The app on the jobs of `data_dir`. With a token it is in network mode, else in local mode
    (an empty token is none). While it runs, it holds the data folder's `server_lock` and runs
    the job runner."""
    store = JobStore(data_dir)
    runner = Runner(store, data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with server_lock(data_dir):  # first: a second server on these jobs stops here
            store.purge()  # before start(), which would queue again the expired jobs left queued
            runner.start()
            try:
                yield
            finally:
                runner.stop()

    # no /docs, /redoc or /openapi.json: their pages load scripts from a CDN
    app = _App(token or None, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.runner = runner
    app.state.data_dir = Path(data_dir)
    app.state.max_upload_mb = max_upload_mb
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        # tojson escapes <, > and &, so no string can end the script element
        return _templates.TemplateResponse(request, "index.html", {"strings": STRINGS})

    return app
