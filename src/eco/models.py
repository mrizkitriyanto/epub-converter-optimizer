"""AI model setup: the only code in eco that may use the network (spec §6.4, §6.5, §8.14)."""

import hashlib
import logging
import os
import socket
import time
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

# huggingface_hub reads these once, when huggingface_hub.constants is first loaded, so they
# are set here, before any import of it. hf-xet cannot be forced to IPv4 and stalls on the
# owner's network.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "20")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_mb: int


# Measured sizes (MB = 1,000,000 bytes) of what _docling_download fetches. Update them together
# with the revision pins in _HF_MODELS and the Docling pin in pyproject.toml (which pins RapidOCR).
MODELS = (
    ModelInfo("Layout (docling-layout-heron)", 172),
    ModelInfo("Tables (TableFormer)", 213),
    ModelInfo("OCR (RapidOCR)", 32),
)

# (repo, commit, files) for the layout model and the accurate TableFormer that conversion uses.
_HF_MODELS = (
    (
        "docling-project/docling-layout-heron",
        "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
        ["*.json", "*.safetensors"],
    ),
    (
        "docling-project/docling-models",
        "fc0f2d45e2218ea24bce5045f58a389aed16dc23",  # tag v2.3.0
        ["model_artifacts/tableformer/accurate/*"],
    ),
)

# Data and text formats only; pickle-based formats (.pt, .pth, .bin, .pkl, .ckpt, ...) are refused.
ALLOWED_SUFFIXES = (".safetensors", ".onnx", ".npz", ".json", ".txt", ".yaml", ".yml", ".md")
MARKER = ".complete"


class ModelsMissing(Exception):
    def __init__(self):
        super().__init__("AI models are not installed. Run: eco setup")


class ChecksumMismatch(Exception):
    """A downloaded file is not the one the registry lists. It is deleted, so a retry fetches it."""


def models_dir(data_dir: Path) -> Path:
    return data_dir / "models"


def models_ready(d: Path) -> bool:
    marker = d / MARKER
    return marker.is_file() and marker.read_text() == version("docling")


def unsafe_files(d: Path) -> list[Path]:
    """Every file under `d` that is not in an allowed format, except huggingface_hub's own
    bookkeeping in `<repo folder>/.cache/huggingface/` and eco's marker."""
    bad = []
    for path in d.rglob("*"):
        rel = path.relative_to(d).parts
        if not path.is_file() or rel == (MARKER,) or rel[1:3] == (".cache", "huggingface"):
            continue
        if path.suffix not in ALLOWED_SUFFIXES:
            bad.append(path)
    return sorted(bad)


@contextmanager
def force_ipv4():
    """Resolve host names to IPv4 addresses only, for every socket in the process."""
    original = socket.getaddrinfo

    def ipv4_only(host, port, family=0, *args, **kwargs):
        return original(host, port, socket.AF_INET, *args, **kwargs)

    socket.getaddrinfo = ipv4_only
    try:
        yield
    finally:
        socket.getaddrinfo = original


@contextmanager
def offline_env():
    """Set HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE, and restore them afterwards.

    huggingface_hub (and transformers through it) reads them once, when
    `huggingface_hub.constants` is first loaded. So they take effect only if that happens inside
    the block, and then they stay in effect for the rest of the process. Import Docling inside
    the block.
    """
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(dict.fromkeys(keys, "1"))
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _docling_download(*, output_dir: Path) -> None:
    """Fetch the three models conversion uses into the folders Docling's `artifacts_path` reads.

    huggingface_hub keeps finished files and skips them on the next call. A partial file is
    resumed within one call, but restarts from zero on the next one.
    """
    from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
    from huggingface_hub import snapshot_download

    for repo, commit, patterns in _HF_MODELS:
        snapshot_download(
            repo_id=repo,
            revision=commit,
            local_dir=output_dir / repo.replace("/", "--"),
            allow_patterns=patterns,
        )
    # Docling's default language and the backend conversion uses. The download URLs are pinned
    # by the rapidocr version in uv.lock. Files already on disk are skipped.
    ocr_dir = output_dir / RapidOcrModel._model_repo_folder
    RapidOcrModel.download_models(backend="onnxruntime", local_dir=ocr_dir, progress=True)
    # Docling's helper saves an HTTP error page as the model and later skips any file that
    # exists, so every file is checked here and the bad ones are deleted for the retry to fetch.
    bad = []
    for path, expected in _rapidocr_expected(ocr_dir).items():
        name = _model_name(path, output_dir)
        if expected is None:
            raise RuntimeError(f"rapidocr's registry has no SHA-256 for {name}; refusing it")
        if not path.is_file() or _sha256(path) != expected:
            path.unlink(missing_ok=True)
            bad.append(name)
    if bad:
        raise ChecksumMismatch(f"SHA-256 does not match rapidocr's registry: {', '.join(bad)}")


def _model_name(path: Path, models_dir: Path) -> str:
    """How messages name a model file: its path under the models folder, with forward slashes
    on every OS."""
    return path.relative_to(models_dir).as_posix()


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _rapidocr_expected(ocr_dir: Path) -> dict[Path, str | None]:
    """Each RapidOCR file conversion loads from `ocr_dir`, with its SHA-256 from rapidocr's
    registry (None if the registry has none). Docling's own helpers pick the files."""
    from docling.models.stages.ocr import rapid_ocr_model as r
    from rapidocr.inference_engine.base import InferSession

    def entries(node):
        if isinstance(node, Mapping):
            if "model_dir" in node:
                yield node["model_dir"], node.get("SHA256")
            for value in node.values():
                yield from entries(value)

    sha = dict(entries(InferSession.model_info))
    spec = r._resolve_rapidocr(r._RAPIDOCR_DEFAULT_LANGUAGE, "onnxruntime")
    artifacts = r._rapidocr_artifacts(
        ocr_dir,
        r._backend_to_engine_type("onnxruntime"),
        spec.ppocr_version,
        spec.rapidocr_code,
    )
    return {path: sha.get(url) for a in artifacts.values() for path, url in a.files.items()}


def _retryable(e: BaseException | None) -> bool:
    """True if `e`, or an error it was raised from, is a network failure or a bad download
    worth another try."""
    import httpx
    import requests
    from huggingface_hub.errors import HfHubHTTPError, OfflineModeIsEnabled

    transient = (
        ChecksumMismatch,
        ConnectionError,
        TimeoutError,
        httpx.NetworkError,
        httpx.TimeoutException,
        httpx.RemoteProtocolError,
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    while e is not None:
        if isinstance(e, OfflineModeIsEnabled):  # a ConnectionError, but no retry will help
            return False
        if isinstance(e, HfHubHTTPError):
            return e.response.status_code == 429 or e.response.status_code >= 500
        if isinstance(e, transient):
            return True
        e = e.__cause__ or e.__context__
    return False


def download_models(d: Path, *, ipv4: bool = False, attempts: int = 8, sleep=time.sleep) -> None:
    """Download the models into `d`, retrying network failures and OCR files whose SHA-256 is
    wrong, then check every file's format.

    Raises RuntimeError when the download still fails after `attempts` tries, when an OCR file
    has no SHA-256 in rapidocr's registry, or when a file is not in an allowed format. Other
    errors are raised as they are.
    """
    d.mkdir(parents=True, exist_ok=True)
    with force_ipv4() if ipv4 else nullcontext():
        for attempt in range(1, attempts + 1):
            try:
                _docling_download(output_dir=d)
                break
            except Exception as e:
                if not _retryable(e):
                    raise
                reason = f"{type(e).__name__}: {' '.join(str(e).split())}"
                if attempt == attempts:
                    hint = "" if ipv4 else " or eco setup --ipv4"
                    raise RuntimeError(
                        f"Download failed after {attempts} attempts ({reason}). Finished files "
                        f"are kept; run eco setup again{hint}."
                    ) from e
                wait = min(2**attempt, 60)
                log.warning(
                    "Attempt %d of %d failed (%s). Retrying in %d s.",
                    attempt,
                    attempts,
                    reason,
                    wait,
                )
                sleep(wait)
    bad = unsafe_files(d)
    if bad:
        names = ", ".join(_model_name(p, d) for p in bad)
        raise RuntimeError(f"Refused model files that are not in a data format: {names}")
    (d / MARKER).write_text(version("docling"))
