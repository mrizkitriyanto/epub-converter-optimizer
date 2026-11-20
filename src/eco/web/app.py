"""The web app: one page, its static files, and the jobs API.

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

The jobs API. Every error it answers, and FastAPI's own 404, 405 and 422 too, is JSON
`{"error": "<plain English>"}`. No path of the server leaves through it: a job shows names,
indexes, statuses, sizes, options, positions and errors (with the data folder cut out).

    POST /api/jobs                                multipart: `files[]`, and `options` as JSON; 201
    GET  /api/jobs                                the 20 newest jobs
    GET  /api/jobs/{id}                           one job
    GET  /api/jobs/{id}/events                    server-sent events: replay, then live, to `end`
    POST /api/jobs/{id}/cancel                    202, or 409 when the job has finished
    POST /api/jobs/{id}/rebuild                   JSON options; 201, a new job from the same files
    GET  /api/jobs/{id}/files/{n}/download/{fmt}  an output, as an attachment
    GET  /api/fonts?job={id}                      bundled and uploaded font families
    POST /api/jobs/{id}/fonts                     one `.ttf` or `.otf` font upload
    DELETE /api/jobs/{id}                         204, the job and all its files are gone; 409
                                                  while it is queued or running

The rows of Select files show each PDF's pages, how many are scanned and an estimate. The page asks
for them one PDF at a time (`eco.web.preview.describe_pdf` does the work). The PDF goes in the field
`file`, is stored the way a job's upload is, in a reserved job folder that is deleted before the
answer whatever it is, and has the same size limit:

    POST /api/inspect                             multipart: `file`; {"pages", "scanned_pages",
                                                  "seconds_per_page": {"digital", "scanned", "pages"}}

The model setup (`eco.web.models_setup` does the work; its page is the first one when the models
are missing). `ipv4` in the body of the POST is optional:

    GET  /api/setup                               ready, the models with their sizes, total_mb
    POST /api/setup/download                      202, or 409 while it runs; `{"ipv4": true}`
    GET  /api/setup/events                        server-sent events of the last run; 404 before one

The previews of the review stage (`eco.web.preview` does the work, the routes only check what they
are given, and its errors are answered like all the others). `format` is `epub`, `xtch`, or `xtc`;
`view` is
`crosspoint`, `crossink` or `stock` (both have defaults); pages count from 1, chapters from 0:

    GET  /api/jobs/{id}/files/{n}/pages?format=&view=            page counts, page map, chapters
    GET  /api/jobs/{id}/files/{n}/source/{page}.png              a PDF page, 600 px wide
    GET  /api/jobs/{id}/files/{n}/preview/{format}/{page}.png    a device page; `?view=`
    GET  /api/jobs/{id}/files/{n}/xtc/{page}.png                 a decoded XTC/XTCH output page
    GET  /api/jobs/{id}/files/{n}/live.png                       one page of a chapter, rendered now:
         ?format=&view=&page=|chapter=&font_size=&size=          `page` (a PDF's source page) or
                                                                 `chapter`; the PNG has the headers
                                                                 X-Excerpt-Index and X-Excerpt-Pages
    GET  /api/jobs/{id}/files/{n}/text                           the book's Markdown, plain text

The upload limit (`--max-upload-mb`, in MiB) is for all the files of a request together. It is
kept while the body arrives, see `_Upload`: a body that goes over it is refused at once, and
nothing of it stays on the disk. A request may hold `MAX_FILES` files.

While the server runs, the lifespan purges the jobs older than RETENTION_DAYS once in `PURGE_EVERY`
(not the queued and the running ones), and `Server` ends the event streams when it is asked to stop.
"""

from __future__ import annotations

import hmac
import http
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import threading
import time
from collections.abc import AsyncIterator, Callable, Collection
from contextlib import aclosing, asynccontextmanager, suppress
from dataclasses import fields
from functools import partial
from pathlib import Path
from types import FrameType
from typing import BinaryIO
from urllib.parse import quote

import anyio
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from python_multipart import MultipartParser
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import parse_options_header
from starlette.datastructures import MutableHeaders, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from eco.font_library import MAX_FONT_BYTES, add_font, remove_font
from eco.font_library import list_fonts as shared_fonts
from eco.options import Options
from eco.saved_styles import (
    delete_style,
    get_default,
    list_styles,
    load_style,
    save_style,
    set_default,
)
from eco.style import BUNDLED_FONTS, TYPST_FAMILY, PageStyle, available_weights
from eco.web.jobs import KINDS, JobInfo, JobStore, Runner, input_path, safe_name, server_lock
from eco.web.models_setup import ModelSetup
from eco.web.preview import PreviewError, Previews, describe_pdf
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

MB = 1024 * 1024
# What a request body may hold besides its files: multipart framing and the options.
_OVERHEAD = MB
MAX_FILES = 200  # in one request
_MAX_OPTIONS = 1 << 16
_FILE_FIELDS = ("files[]", "files")
_OPTION_NAMES = {f.name for f in fields(Options)}
_INDEX = re.compile(r"0|[1-9][0-9]{0,5}")  # a file's number in a URL: no sign, no leading zero
_MEDIA = {"epub": "application/epub+zip"}
_POLL = 0.05  # seconds between two looks of an event stream at its queue
_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # a proxy in front must not hold the events back
}
KEEPALIVE = 15.0  # seconds of silence after which an event stream sends a comment
PURGE_EVERY = 3600.0  # seconds between two purges of the old jobs while the server runs

log = logging.getLogger(__name__)

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
        static = scope.get("path", "").startswith("/static/")

        async def send_secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SECURITY_HEADERS)
                if static:  # after an upgrade the page must not run the old modules
                    headers["Cache-Control"] = "no-cache"
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
        elif not (
            method == "GET" and request.scope["path"] == "/api/health"
        ) and not self._authorized(request):
            return _error(401, STRINGS["error_token"])
        # The page answers with `Referrer-Policy: no-referrer`, under which a browser sends
        # `Origin: null` with a form POST and with a fetch() whose mode is not "cors", and this
        # check refuses both. So every state-changing request of the page must stay a fetch() in
        # its default mode.
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


class Server(uvicorn.Server):
    """uvicorn's server, which tells the app when it is asked to stop (Ctrl+C, SIGTERM).

    uvicorn waits for the responses in flight before it stops, and an event stream is one that does
    not end by itself. So `handle_exit` first sets `app.state.stopping`, which ends every event
    stream at its next look, and then does what uvicorn does. Its `config.app` is the app that
    `create_app` made.
    """

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        self.config.app.state.stopping.set()
        super().handle_exit(sig, frame)


def _text(raw: bytes) -> str:
    """A header value as text: UTF-8, as browsers send it, else Latin-1."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _too_large(mb: int) -> str:
    return STRINGS["error_too_large"].format(mb=mb)


def _disposition(name: str) -> str:
    """The `Content-Disposition` of a download. The name comes twice: in ASCII for a client that
    reads only `filename` (a non-ASCII character, a quote, a backslash or a control character
    becomes `_`), and as UTF-8 for one that reads `filename*`, which takes the place of the other
    (RFC 6266, section 4.3)."""
    ascii_name = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def _page_number(page: str) -> int:
    """A page number in a URL: a plain decimal, as strict as a file's number. 404 for the rest."""
    if not _INDEX.fullmatch(page):
        raise HTTPException(404, STRINGS["error_page"])
    return int(page)


def _png(data: bytes, **headers: str) -> Response:
    return Response(data, media_type="image/png", headers=headers)


def _valid(name: str, value) -> bool:
    if name == "formats":
        return isinstance(value, list) and bool(value) and all(isinstance(v, str) for v in value)
    if name == "landscape":
        return isinstance(value, bool)
    if name in ("title", "author", "lang"):
        return value is None or isinstance(value, str)
    return isinstance(value, str)  # device, firmware, size, mode and ocr


def _options(
    raw: bytes, font_extra_dirs: tuple[Path, ...] = (), default_style: PageStyle | None = None
) -> Options:
    """The Options of a posted JSON object. Nothing posted gives the defaults. Anything else that
    is wrong is HTTP 422 with a plain message; for a device or the like that does not exist, the
    message of `Options` itself."""
    if not raw.strip():
        return Options(style=default_style) if default_style else Options()
    try:
        given = json.loads(raw)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or too deep for the reader
        raise HTTPException(422, STRINGS["error_options_json"]) from None
    if not isinstance(given, dict):
        raise HTTPException(422, STRINGS["error_options_object"])
    for name, value in given.items():
        if name not in _OPTION_NAMES:
            raise HTTPException(422, STRINGS["error_option_unknown"].format(name=name))
        if name == "style":  # it goes into Typst source (the previews): `PageStyle` checks it all
            try:
                if default_style is not None and isinstance(value, dict):
                    value = {**default_style.to_json(), **value}
                given[name] = PageStyle.from_json(value, font_extra_dirs)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
        elif not _valid(name, value):
            raise HTTPException(422, STRINGS["error_option_value"].format(name=name))
    if "formats" in given:
        given["formats"] = tuple(given["formats"])
    for name in ("title", "author", "lang"):
        if name in given:
            given[name] = given[name] or None  # a blank form field is not a value
    try:
        if default_style is not None:
            given.setdefault("style", default_style)
        return Options(**given)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _font_details(path: Path) -> tuple[str, list[int]]:
    import typst

    fonts = typst.Fonts(
        include_system_fonts=False,
        include_embedded_fonts=False,
        font_paths=[str(path.parent)],
    ).fonts()
    matching = [font for font in fonts if Path(font.path).resolve() == path.resolve()]
    families = {font.family for font in matching}
    if len(families) != 1:
        raise ValueError("Not a usable font file")
    family = families.pop()
    if any(ord(char) < 32 or char in '"\\' for char in family):
        raise ValueError("Not a usable font file")
    weights = sorted({font.weight for font in matching if font.style == "normal"})
    if not weights:
        raise ValueError("Not a usable font file")
    return family, weights


def _fonts(folder: Path | None) -> list[dict]:
    families = {name: available_weights(name) for name in (*BUNDLED_FONTS, TYPST_FAMILY)}
    if folder and folder.is_dir():
        import typst

        for font in typst.Fonts(
            include_system_fonts=False,
            include_embedded_fonts=False,
            font_paths=[str(folder)],
        ).fonts():
            if font.style == "normal" and Path(font.path).resolve().is_relative_to(
                folder.resolve()
            ):
                families.setdefault(font.family, [])
                families[font.family].append(font.weight)
    return [
        {"family": family, "weights": sorted(set(weights))}
        for family, weights in sorted(families.items())
    ]


class _Upload:
    """The body of `POST /api/jobs`, taken as it arrives.

    Each file is written straight into a reserved job folder and counted as it is written, so a
    body that goes over the limit is refused at once and `discard` leaves nothing of it. Starlette's
    own form parser is not used: it writes every file to a temporary file before the route runs,
    and the limit could only be checked after that. The options field may come before or after the
    files; `feed` takes the pieces of the body, `finish` makes the job. Anything it refuses is an
    HTTPException, and the caller then calls `discard`.
    """

    # What a body may hold. `_PdfUpload` takes less.
    fields = _FILE_FIELDS  # the form fields that hold a file
    kinds: Collection[str] = KINDS  # the suffixes of the files it takes
    max_files = MAX_FILES
    unsupported = "error_unsupported"  # the key of the text for a file of another type

    def __init__(
        self,
        store: JobStore,
        boundary: bytes,
        limit_mb: int,
        font_extra_dirs: tuple[Path, ...] = (),
    ):
        self.store = store
        self.font_extra_dirs = font_extra_dirs
        self.limit = limit_mb * MB
        self.job: Path | None = None  # the folder the files are written into, made at the first
        self.names: list[str] = []  # the stored name of each file; its place is its number
        default = get_default(store.root.parent)
        self.options = (
            Options(style=load_style(store.root.parent, default)) if default else Options()
        )
        self.adopted = False
        self._too_large = _too_large(limit_mb)
        self._seen = 0  # bytes of the body so far
        self._size = 0  # bytes of the files so far
        self._ended = False  # the closing boundary has come
        self._file: BinaryIO | None = None  # the file being written
        self._field: bytearray | None = None  # the options field being read
        self._headers: dict[bytes, bytes] = {}
        self._key, self._value = bytearray(), bytearray()
        callbacks = {
            "on_part_begin": self._part_begin,
            "on_header_field": lambda data, start, end: self._key.extend(data[start:end]),
            "on_header_value": lambda data, start, end: self._value.extend(data[start:end]),
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_finished,
            "on_part_data": self._part_data,
            "on_part_end": self._part_end,
            "on_end": self._end,
        }
        try:
            self._parser = MultipartParser(boundary, callbacks)
        except FormParserError:  # a boundary that is too long
            raise HTTPException(400, STRINGS["error_unreadable"]) from None

    def feed(self, chunk: bytes) -> None:
        self._seen += len(chunk)
        if self._seen > self.limit + _OVERHEAD:
            raise HTTPException(413, self._too_large)
        try:
            self._parser.write(chunk)
        except FormParserError:
            raise HTTPException(400, STRINGS["error_unreadable"]) from None

    def finish(self) -> JobInfo:
        """The queued job of what came. HTTP 400 for a body that was cut short or held no file."""
        self._complete()
        info = self.store.adopt(self.job, self.names, self.options)
        self.adopted = True
        return info

    def _complete(self) -> None:
        if not self._ended:
            raise HTTPException(400, STRINGS["error_unreadable"])
        if not self.names:
            raise HTTPException(400, STRINGS["error_no_files"])

    def discard(self) -> None:
        """Close the file being written and delete the job folder, unless a job was made of it."""
        if self._file:
            with suppress(OSError):  # the disk may be what failed
                self._file.close()
        if self.job and not self.adopted:
            shutil.rmtree(self.job, ignore_errors=True)

    def _part_begin(self) -> None:
        self._headers = {}

    def _header_end(self) -> None:
        self._headers[bytes(self._key).lower()] = bytes(self._value)
        self._key.clear()
        self._value.clear()

    def _headers_finished(self) -> None:
        _, params = parse_options_header(self._headers.get(b"content-disposition"))
        field = _text(params.get(b"name", b""))
        if b"filename" in params:
            if field in self.fields:
                self._open(_text(params[b"filename"]))
        elif field == "options":
            self._field = bytearray()
        # any other part is read and dropped

    def _open(self, uploaded: str) -> None:
        # now, as the headers end: no byte of this one is read
        if len(self.names) >= self.max_files:
            raise HTTPException(400, STRINGS["error_too_many"].format(limit=self.max_files))
        name = safe_name(uploaded)
        if Path(name).suffix.lower() not in self.kinds:
            raise HTTPException(400, STRINGS[self.unsupported].format(name=uploaded))
        self.job = self.job or self.store.reserve()
        path = input_path(self.job / "input", len(self.names), name)
        path.parent.mkdir()
        self._file = path.open("wb")
        self.names.append(name)

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if self._file is not None:
            if self._size + (end - start) > self.limit:  # checked before the write: never over
                raise HTTPException(413, self._too_large)
            self._file.write(memoryview(data)[start:end])
            self._size += end - start
        elif self._field is not None:
            self._field.extend(data[start:end])
            if len(self._field) > _MAX_OPTIONS:
                raise HTTPException(422, STRINGS["error_options_long"])

    def _part_end(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
        if self._field is not None:
            field, self._field = bytes(self._field), None
            self.options = _options(field, self.font_extra_dirs, self.options.style)

    def _end(self) -> None:
        self._ended = True


class _PdfUpload(_Upload):
    """The body of `POST /api/inspect`: one PDF in the field `file`. It is written the same way, into
    a reserved job folder, which is no job (it has no job.json, so a server that is killed leaves
    what the next start purges). The route calls `discard` when it has read the PDF."""

    fields = ("file",)
    kinds = (".pdf",)
    max_files = 1  # a second one is "Too many files (limit 1)"
    unsupported = "error_inspect_type"

    def pdf_path(self) -> Path:
        """Where the PDF that came is stored. HTTP 400 for a body cut short or with no file."""
        self._complete()
        return input_path(self.job / "input", 0, self.names[0])


def _boundary(request: Request, limit_mb: int) -> bytes:
    """The boundary of a multipart upload. HTTP 400 for a body that is no multipart form, and 413 for
    one whose declared size is over the limit: that is refused before the body is read. A body
    without a size (or a lying one) is refused by `_Upload` as soon as it goes over."""
    content_type, params = parse_options_header(request.headers.get("content-type"))
    boundary = params.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary:
        raise HTTPException(400, STRINGS["error_not_form"])
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit_mb * MB + _OVERHEAD:
        raise HTTPException(413, _too_large(limit_mb))
    return boundary


async def _receive(upload: _Upload, request: Request) -> None:
    """Give the body of the request to the upload as it arrives, piece by piece, on the thread pool
    (it writes to the disk). ClientDisconnect, if the client goes, is the caller's."""
    async with aclosing(request.stream()) as body:
        async for chunk in body:
            if chunk:
                await run_in_threadpool(upload.feed, chunk)


def _scrubber(root: Path) -> Callable[[str], str]:
    """A function that puts `<data>` for the data folder in a text, in the three forms a path takes
    in an error message: as printed, with doubled backslashes (as an OSError shows a Windows path)
    and with slashes."""
    roots = {str(path) for path in (root, root.resolve()) if path.is_absolute()}
    forms = {form for r in roots for form in (r, r.replace("\\", "\\\\"), Path(r).as_posix())}
    longest_first = sorted(forms, key=len, reverse=True)

    def scrub(text: str) -> str:
        for form in longest_first:
            text = text.replace(form, "<data>")
        return text

    return scrub


def _size(path: str) -> int | None:
    try:
        return os.stat(path).st_size
    except OSError:
        return None


def _public(info: JobInfo, scrub: Callable[[str], str]) -> dict:
    """A job as the API shows it: names, indexes, sizes and the like, and no path of the server.
    A file's `outputs` (format to name) and `sizes` (format to bytes) are what its `file` event
    shows, so the page reads both the same way; `size` is the upload's."""
    return {
        "id": info.id,
        "status": info.status,
        "created": info.created,
        "position": info.position,
        "options": info.options,
        "files": [
            {
                "index": n,
                "name": f.name,
                "kind": f.kind,
                "size": _size(f.path),
                "error": scrub(f.error) if f.error else None,
                "outputs": {fmt: Path(path).name for fmt, path in f.outputs.items()},
                "sizes": {fmt: _size(path) for fmt, path in f.outputs.items()},
                "epubcheck": f.epubcheck,
            }
            for n, f in enumerate(info.files)
        ],
    }


def _public_event(event: dict, scrub: Callable[[str], str]) -> dict:
    """An event as the browser gets it: a file's result without the paths of the server."""
    if event["type"] != "file":
        return event
    shown = {k: v for k, v in event.items() if k not in ("outputs", "book_dir", "error")}
    if "outputs" in event:
        shown["outputs"] = {fmt: Path(path).name for fmt, path in event["outputs"].items()}
    if "error" in event:
        shown["error"] = scrub(event["error"])
    return shown


async def _events(
    subscribe: Callable[[], queue.Queue[dict]],
    unsubscribe: Callable[[queue.Queue[dict]], None],
    show: Callable[[dict], dict],
    stopping: threading.Event,
) -> AsyncIterator[str]:
    """The messages of an event stream: the events of a job (or of the model download) so far,
    then each new one, up to `end`, each as `show` makes it. `subscribe` gives the queue of
    those events and `unsubscribe` takes it back. The stream also ends, with no `end` (the job
    has not ended), as soon as `stopping` is set: the server is stopping, and it waits for its
    streams. After KEEPALIVE seconds with no event it sends a comment, `: keepalive`, which a
    browser ignores and a proxy takes for traffic.

    The subscription starts here, in the generator, and ends in its `finally`: when the stream
    ends, when the client goes (the response is cancelled), and when the server cancels the
    response. A stream that is never opened subscribes to nothing."""
    q = subscribe()
    silent_since = time.monotonic()
    try:
        while not stopping.is_set():
            try:
                event = q.get_nowait()
            except queue.Empty:
                if time.monotonic() - silent_since >= KEEPALIVE:
                    silent_since = time.monotonic()
                    yield ": keepalive\n\n"
                await anyio.sleep(_POLL)  # the queue is the runner thread's: it cannot be awaited
                continue
            silent_since = time.monotonic()
            yield f"data: {json.dumps(show(event), ensure_ascii=False)}\n\n"
            if event["type"] == "end":
                return
    finally:
        unsubscribe(q)


async def _small_body(request: Request) -> bytes:
    """The body of a request that only holds a few options: HTTP 422 for more than _MAX_OPTIONS.
    ClientDisconnect, if the client goes, is the caller's."""
    raw = bytearray()
    async with aclosing(request.stream()) as body:
        async for chunk in body:
            raw.extend(chunk)
            if len(raw) > _MAX_OPTIONS:
                raise HTTPException(422, STRINGS["error_options_long"])
    return bytes(raw)


def _setup_start(raw: bytes) -> bool:
    """The `ipv4` flag of the body of `POST /api/setup/download`: nothing, or a JSON object whose
    only key may be `ipv4`, a boolean. HTTP 422 for anything else."""
    if not raw.strip():
        return False
    try:
        given = json.loads(raw)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or too deep for the reader
        raise HTTPException(422, STRINGS["error_setup_body"]) from None
    if not isinstance(given, dict):
        raise HTTPException(422, STRINGS["error_setup_body"])
    for name in given:
        if name != "ipv4":
            raise HTTPException(422, STRINGS["error_setup_key"].format(name=name))
    if not isinstance(given.get("ipv4", False), bool):
        raise HTTPException(422, STRINGS["error_setup_ipv4"])
    return given.get("ipv4", False)


def create_app(data_dir: Path, *, token: str | None, max_upload_mb: int = 500) -> FastAPI:
    """The app on the jobs of `data_dir`. With a token it is in network mode, else in local mode
    (an empty token is none). While it runs, it holds the data folder's `server_lock` and runs
    the job runner."""
    # StaticFiles takes the type from the system, and /etc/mime.types or the Windows registry may
    # say application/javascript for .js
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("font/woff2", ".woff2")  # Windows may not know it
    store = JobStore(data_dir)
    runner = Runner(store, data_dir)

    async def expire() -> None:
        """While the server runs, purge the old jobs once in PURGE_EVERY. The queued ones are the
        runner's and the running ones the worker's, so they are left; so is a folder that is
        only minutes old, an upload that is coming in. The work is on a thread, off the event
        loop. A purge that fails is logged, and the next one tries again."""
        while True:
            await anyio.sleep(PURGE_EVERY)
            try:
                await anyio.to_thread.run_sync(partial(store.purge, keep_queued=True))
            except Exception:
                log.exception("The hourly purge failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with server_lock(data_dir):  # first: a second server on these jobs stops here
            # Before start(), which would queue again the expired jobs left queued. No request is
            # in flight yet, so a folder without a job.json is an upload that a hard kill cut.
            store.purge(orphans=True)
            runner.start()
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(expire)
                try:
                    yield
                finally:
                    tasks.cancel_scope.cancel()
                    runner.stop()

    # no /docs, /redoc or /openapi.json: their pages load scripts from a CDN
    app = _App(token or None, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.runner = runner
    previews = app.state.previews = Previews(store)
    app.state.data_dir = Path(data_dir)
    app.state.max_upload_mb = max_upload_mb
    app.state.stopping = threading.Event()  # set by `Server` when it is asked to stop
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/api/health")
    def health():
        from eco import __version__, models

        return {
            "ok": True,
            "version": __version__,
            "models_ready": models.models_ready(models.models_dir(Path(data_dir))),
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        # tojson escapes <, > and &, so no string can end the script element
        context = {
            "strings": STRINGS,
            "max_upload_mb": str(app.state.max_upload_mb),
            "builtin_style": PageStyle().to_json(),  # what "eco default" on Select sends
        }
        return _templates.TemplateResponse(request, "index.html", context)

    # One answer for every error, so the page reads one key: FastAPI's own 404, 405 and 422, the
    # HTTPExceptions of the routes below, and an error nobody expected.

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if not isinstance(detail, str):
            detail = http.HTTPStatus(exc.status_code).phrase
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"][1:])
        message = f"{where}: {first['msg']}" if where else first["msg"]
        return JSONResponse({"error": message}, status_code=422)

    @app.exception_handler(PreviewError)
    async def preview_error(request: Request, exc: PreviewError):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return JSONResponse({"error": STRINGS["error_server"]}, status_code=500)

    scrub = _scrubber(Path(data_dir))
    setup = app.state.setup = ModelSetup(Path(data_dir), scrub)

    def job_of(job_id: str) -> JobInfo:
        try:
            return store.get(job_id)
        except KeyError:
            raise HTTPException(404, STRINGS["error_job"]) from None

    def file_of(job_id: str, n: str) -> tuple[JobInfo, int]:
        """The job and the index of its file `n`. `n` is a plain decimal that the job has."""
        info = job_of(job_id)
        if not _INDEX.fullmatch(n) or int(n) >= len(info.files):
            raise HTTPException(404, STRINGS["error_file"])
        return info, int(n)

    def queue_job(make: Callable[[], JobInfo]) -> JobInfo:
        """Queue the new job `make` makes, and show it as it is once queued: its position."""
        info = make()
        runner.submit(info.id)
        return store.get(info.id)

    @app.post("/api/jobs", status_code=201)
    async def create_job(request: Request):
        limit = app.state.max_upload_mb
        library = Path(data_dir) / "fonts"
        upload = _Upload(
            store, _boundary(request, limit), limit, (library,) if library.is_dir() else ()
        )
        try:
            await _receive(upload, request)
            info = await run_in_threadpool(queue_job, upload.finish)
        except ClientDisconnect:  # nobody is there to answer
            upload.discard()
            return Response(status_code=400)
        except BaseException:
            upload.discard()
            raise
        return _public(info, scrub)

    @app.post("/api/inspect")
    async def inspect_upload(request: Request):
        limit = app.state.max_upload_mb
        upload = _PdfUpload(store, _boundary(request, limit), limit)
        try:
            await _receive(upload, request)
            return await run_in_threadpool(describe_pdf, upload.pdf_path())  # under the PDFium lock
        except ClientDisconnect:  # nobody is there to answer
            return Response(status_code=400)
        finally:  # on every way out, and before the answer goes
            upload.discard()

    @app.get("/api/jobs")
    def list_jobs():
        return [_public(info, scrub) for info in store.list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return _public(job_of(job_id), scrub)

    @app.get("/api/styles")
    def styles_list():
        return list_styles(Path(data_dir))

    @app.get("/api/styles/{name}")
    def style_get(name: str):
        try:
            findings = []
            style = load_style(Path(data_dir), name, findings=findings)
            return JSONResponse(
                style.to_json(),
                headers={"X-Style-Findings": quote("; ".join(f.message for f in findings))},
            )
        except ValueError as error:
            raise HTTPException(404, str(error)) from None

    @app.put("/api/styles/{name}")
    async def style_put(name: str, request: Request, overwrite: bool = False):
        try:
            raw = await request.json()
            return save_style(Path(data_dir), name, raw, overwrite=overwrite).to_json()
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(
                409 if str(error).startswith("Style already exists:") else 422, str(error)
            ) from None

    @app.delete("/api/styles/{name}", status_code=204)
    def style_delete(name: str):
        try:
            delete_style(Path(data_dir), name)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        return Response(status_code=204)

    @app.put("/api/styles/{name}/default")
    def style_default(name: str):
        try:
            set_default(Path(data_dir), name)
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        return {"default_style": name}

    @app.get("/api/fonts")
    def list_fonts(job: str | None = None):
        folder = None
        if job is not None:
            job_of(job)
            folder = store.job_dir(job) / "fonts"
        families = {item["family"]: item for item in _fonts(folder)}
        for item in shared_fonts(Path(data_dir)):
            families[item["family"]] = item
        return [families[name] for name in sorted(families)]

    @app.post("/api/fonts")
    async def upload_library_fonts(request: Request):
        form = await request.form()
        uploads = form.getlist("files")
        if not uploads:
            raise HTTPException(400, "Not a usable font file")
        results = []
        for upload in uploads:
            if not isinstance(upload, UploadFile) or not upload.filename:
                raise HTTPException(400, "Not a usable font file")
            content = await upload.read(MAX_FONT_BYTES + 1)
            await upload.close()
            try:
                results.append(add_font(Path(data_dir), upload.filename, content))
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
        return results

    @app.delete("/api/fonts/{family}", status_code=204)
    def delete_library_font(family: str):
        if not remove_font(Path(data_dir), family):
            raise HTTPException(404, "Font not found")
        return Response(status_code=204)

    @app.post("/api/jobs/{job_id}/fonts")
    async def upload_font(job_id: str, request: Request):
        job_of(job_id)
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise HTTPException(400, "Not a usable font file")
        name = safe_name(upload.filename)
        if Path(name).suffix.lower() not in (".ttf", ".otf"):
            raise HTTPException(400, "Not a usable font file")
        folder = store.job_dir(job_id) / "fonts"
        folder.mkdir(exist_ok=True)
        target = folder / name
        number = 0
        while target.exists():
            number += 1
            target = folder / f"{Path(name).stem}-{number}{Path(name).suffix}"
        size = 0
        try:
            with target.open("wb") as output:
                while chunk := await upload.read(MB):
                    size += len(chunk)
                    if size > app.state.max_upload_mb * MB:
                        raise HTTPException(413, _too_large(app.state.max_upload_mb))
                    output.write(chunk)
            try:
                family, weights = _font_details(target)
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return {"family": family, "weights": weights}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str):
        await run_in_threadpool(job_of, job_id)  # 404 now, not in the middle of a stream
        return StreamingResponse(
            _events(
                lambda: runner.subscribe(job_id),
                lambda q: runner.unsubscribe(job_id, q),
                lambda event: _public_event(event, scrub),
                app.state.stopping,
            ),
            headers=_SSE_HEADERS,
        )

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str):
        job_of(job_id)
        if not runner.cancel(job_id):
            raise HTTPException(409, STRINGS["error_finished"])
        return _public(store.get(job_id), scrub)

    @app.post("/api/jobs/{job_id}/rebuild", status_code=201)
    async def rebuild_job(job_id: str, request: Request):
        await run_in_threadpool(job_of, job_id)
        try:
            raw = await _small_body(request)
        except ClientDisconnect:
            return Response(status_code=400)
        font_folder = store.job_dir(job_id) / "fonts"
        library = Path(data_dir) / "fonts"
        options = _options(raw, tuple(p for p in (library, font_folder) if p.is_dir()))
        info = await run_in_threadpool(queue_job, lambda: store.rebuild(job_id, options))
        return _public(info, scrub)

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str):
        try:
            store.delete(job_id)
        except KeyError:
            raise HTTPException(404, STRINGS["error_job"]) from None
        except ValueError:
            raise HTTPException(409, STRINGS["error_not_ended"]) from None
        return Response(status_code=204)

    @app.get("/api/jobs/{job_id}/files/{n}/download/{fmt}")
    def download(job_id: str, n: str, fmt: str):
        info, index = file_of(job_id, n)
        made = info.files[index].outputs.get(fmt)  # `fmt` is only ever looked up, never a path
        path = Path(made) if made else None
        output_folder = (store.job_dir(job_id) / "output").resolve()
        if not path or not path.is_file() or not path.resolve().is_relative_to(output_folder):
            raise HTTPException(404, STRINGS["error_output"])
        return FileResponse(
            path,
            media_type=_MEDIA.get(fmt, "application/octet-stream"),
            headers={"Content-Disposition": _disposition(path.name)},
        )

    @app.get("/api/setup")
    def setup_state():
        return {
            "ready": setup.ready(),
            "models": setup.models(),
            "total_mb": setup.total_mb(),
        }

    @app.post("/api/setup/download", status_code=202)
    async def setup_download(request: Request):
        try:
            ipv4 = _setup_start(await _small_body(request))
        except ClientDisconnect:
            return Response(status_code=400)
        if not setup.start(ipv4=ipv4):
            raise HTTPException(409, STRINGS["error_setup_running"])
        return {"status": "started"}

    @app.get("/api/setup/events")
    def setup_events():
        if not setup.started:
            raise HTTPException(404, STRINGS["error_setup_none"])
        return StreamingResponse(
            _events(setup.subscribe, setup.unsubscribe, lambda event: event, app.state.stopping),
            headers=_SSE_HEADERS,
        )

    # These do file work and long renders, so they are plain `def`: they run on the thread pool.

    @app.get("/api/jobs/{job_id}/files/{n}/pages")
    def preview_pages(
        job_id: str,
        n: str,
        fmt: str = Query("epub", alias="format"),
        view: str = "crosspoint",
    ):
        info, index = file_of(job_id, n)
        return previews.pages(info, index, fmt, view)

    @app.get("/api/jobs/{job_id}/files/{n}/source/{page}.png")
    def source_page(job_id: str, n: str, page: str):
        info, index = file_of(job_id, n)
        return _png(previews.source_page(info, index, _page_number(page)))

    @app.get("/api/jobs/{job_id}/files/{n}/preview/{fmt}/{page}.png")
    def device_page(job_id: str, n: str, fmt: str, page: str, view: str = "crosspoint"):
        info, index = file_of(job_id, n)
        return _png(previews.device_page(info, index, fmt, view, _page_number(page)))

    @app.get("/api/jobs/{job_id}/files/{n}/xtc/{page}.png")
    def xtc_page(job_id: str, n: str, page: str):
        info, index = file_of(job_id, n)
        return _png(previews.xtc_page(info, index, _page_number(page)))

    @app.get("/api/jobs/{job_id}/files/{n}/live.png")
    def live_page(
        job_id: str,
        n: str,
        fmt: str = Query("epub", alias="format"),
        view: str = "crosspoint",
        page: int | None = None,
        chapter: int | None = None,
        font_size: int | None = None,
        size: str | None = None,
        style: str | None = None,
    ):
        info, index = file_of(job_id, n)
        if (page is None) == (chapter is None):
            raise HTTPException(422, STRINGS["error_live_target"])
        font_folder = store.job_dir(job_id) / "fonts"
        library = Path(data_dir) / "fonts"
        extra_dirs = tuple(p for p in (library, font_folder) if p.is_dir())
        parsed_style = None
        if style is not None:
            try:
                parsed_style = PageStyle.from_json(json.loads(style), extra_dirs)
            except (ValueError, RecursionError) as error:
                raise HTTPException(422, str(error)) from None
        if font_size is not None:  # it goes into Typst source
            try:
                PageStyle(font_size=font_size)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
        shown = previews.live(
            info,
            index,
            fmt,
            view,
            font_size=font_size,
            size=size,
            page=page,
            chapter=chapter,
            style=parsed_style,
        )
        return _png(
            shown.png,
            **{
                "X-Excerpt-Index": str(shown.index),
                "X-Excerpt-Pages": str(shown.pages),
                "X-Font-Fallback": quote(shown.font_fallback or ""),
            },
        )

    @app.get("/api/jobs/{job_id}/files/{n}/text")
    def book_text(job_id: str, n: str):
        info, index = file_of(job_id, n)
        return FileResponse(previews.text(info, index), media_type="text/plain; charset=utf-8")

    return app
