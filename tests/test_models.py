import hashlib
import os
import socket
import subprocess
import sys
from pathlib import PureWindowsPath

import httpx
import pytest
import requests
from huggingface_hub.errors import (
    HfHubHTTPError,
    LocalEntryNotFoundError,
    OfflineModeIsEnabled,
    RevisionNotFoundError,
)

from eco import models
from eco.cli import main
from eco.models import _model_name, download_models, models_ready, offline_env, unsafe_files


def test_model_names_in_messages_use_forward_slashes():
    # A Windows path must give the same name as on Linux and macOS (ruling R-61).
    path = PureWindowsPath("C:/data/models/RapidOcr/onnx/det.onnx")
    assert _model_name(path, PureWindowsPath("C:/data/models")) == "RapidOcr/onnx/det.onnx"


def test_retry_then_success(tmp_path, monkeypatch):
    calls = []

    def flaky(**kw):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("reset")
        (kw["output_dir"] / "m.safetensors").write_bytes(b"x")

    monkeypatch.setattr("eco.models._docling_download", flaky)
    download_models(tmp_path, sleep=lambda s: None)
    assert len(calls) == 3 and models_ready(tmp_path)


def test_pickle_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "eco.models._docling_download",
        lambda **kw: (kw["output_dir"] / "w.pt").write_bytes(b"x"),
    )
    with pytest.raises(RuntimeError, match="w.pt"):
        download_models(tmp_path, sleep=lambda s: None)
    assert not models_ready(tmp_path)


def test_setup_prompt_no(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["setup", "--data", str(tmp_path)]) == 1
    assert "Total download: ~417 MB" in capsys.readouterr().out


def _http_error(cls, status):
    response = httpx.Response(status, request=httpx.Request("GET", "https://huggingface.co/x"))
    return cls(f"HTTP {status}", response=response)


def _caused_by(error, cause):
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "error,retried",
    [
        (ConnectionError("reset"), True),
        (TimeoutError("stalled"), True),
        (httpx.ReadError("connection reset by peer"), True),
        (httpx.ConnectError("TLS handshake reset"), True),
        (requests.ConnectionError("reset"), True),
        (requests.exceptions.ChunkedEncodingError("cut off"), True),
        (_http_error(HfHubHTTPError, 503), True),
        # huggingface_hub turns a failed metadata request into this, raised from the network error
        (_caused_by(LocalEntryNotFoundError("cannot locate"), httpx.ConnectError("reset")), True),
        (_http_error(RevisionNotFoundError, 404), False),
        (OfflineModeIsEnabled("HF_HUB_OFFLINE is set"), False),
        (LocalEntryNotFoundError("not cached"), False),
        (ValueError("bad argument"), False),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, BaseException) else None,
)
def test_retries_only_network_errors(tmp_path, monkeypatch, error, retried):
    calls, waits = [], []

    def fail(**kw):
        calls.append(1)
        raise error

    monkeypatch.setattr("eco.models._docling_download", fail)
    with pytest.raises(RuntimeError if retried else type(error)):
        download_models(tmp_path, attempts=3, sleep=waits.append)
    assert len(calls) == (3 if retried else 1)
    assert len(waits) == (2 if retried else 0)
    assert not models_ready(tmp_path)


def test_unsafe_files_allowlist(tmp_path):
    safe = ["a.safetensors", "b.onnx", "c.npz", "d.json", "e.txt", "f.yaml", "g.yml", "h.md"]
    bad = ["x.pt", "x.pth", "x.bin", "x.pkl", "x.pickle", "x.ckpt", "x.joblib", "x.png", "LICENSE"]
    exempt = [".complete", "repo/.cache/huggingface/download/a.lock", "repo/.cache/huggingface/x"]
    # The exemptions hold only at their own place.
    misplaced = ["sub/.complete", "repo/sub/.cache/huggingface/a.lock"]
    for rel in [*(f"repo/sub/{n}" for n in safe + bad), *exempt, *misplaced]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    expected = [f"repo/sub/{n}" for n in bad] + misplaced
    assert unsafe_files(tmp_path) == sorted(tmp_path / rel for rel in expected)


def test_models_ready_needs_matching_marker(tmp_path):
    assert not models_ready(tmp_path / "missing")
    (tmp_path / ".complete").write_text("0.0.1")
    assert not models_ready(tmp_path)


def test_ipv4_wraps_fetch_and_restores(tmp_path, monkeypatch):
    families = []

    def record(host, port, family=0, *args, **kwargs):
        families.append(family)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", record)

    def fetch(**kw):
        socket.getaddrinfo("huggingface.co", 443, 0, socket.SOCK_STREAM)
        socket.getaddrinfo("huggingface.co", 443, family=socket.AF_INET6)
        raise ValueError("boom")

    monkeypatch.setattr("eco.models._docling_download", fetch)
    with pytest.raises(ValueError):
        download_models(tmp_path, ipv4=True, sleep=lambda s: None)
    assert families == [socket.AF_INET, socket.AF_INET]
    assert socket.getaddrinfo is record


def test_offline_env_sets_and_restores(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    with offline_env():
        assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert "TRANSFORMERS_OFFLINE" not in os.environ


def test_fetch_uses_pinned_models(tmp_path, monkeypatch):
    hf, ocr = [], []
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda **kw: hf.append(kw))
    monkeypatch.setattr(
        "docling.models.stages.ocr.rapid_ocr_model.RapidOcrModel.download_models",
        lambda **kw: ocr.append(kw),
    )
    monkeypatch.setattr("eco.models._rapidocr_expected", lambda ocr_dir: {})
    models._docling_download(output_dir=tmp_path)
    assert hf == [
        {
            "repo_id": "docling-project/docling-layout-heron",
            "revision": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
            "local_dir": tmp_path / "docling-project--docling-layout-heron",
            "allow_patterns": ["*.json", "*.safetensors"],
        },
        {
            "repo_id": "docling-project/docling-models",
            "revision": "fc0f2d45e2218ea24bce5045f58a389aed16dc23",
            "local_dir": tmp_path / "docling-project--docling-models",
            "allow_patterns": ["model_artifacts/tableformer/accurate/*"],
        },
    ]
    assert ocr == [{"backend": "onnxruntime", "local_dir": tmp_path / "RapidOcr", "progress": True}]


def test_rapidocr_hashes_come_from_the_registry(tmp_path):
    """The files conversion loads, with rapidocr 3.10.0's SHA-256 (they change with that pin)."""
    assert models._rapidocr_expected(tmp_path) == {
        tmp_path / "PP-OCRv6_det_small.onnx": (
            "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"
        ),
        tmp_path / "ch_ppocr_mobile_v2.0_cls_mobile.onnx": (
            "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"
        ),
        tmp_path / "PP-OCRv6_rec_small.onnx": (
            "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"
        ),
    }


GOOD = b"onnx model"


@pytest.fixture
def ocr_payloads(monkeypatch):
    """Fake the OCR download of one file whose registry SHA-256 is that of GOOD.

    Each download writes the next payload. Like Docling's helper, it skips a file that exists.
    """
    payloads = []

    def download(*, backend, local_dir, progress):
        local_dir.mkdir(parents=True, exist_ok=True)
        if not (local_dir / "det.onnx").exists():
            (local_dir / "det.onnx").write_bytes(payloads.pop(0))

    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda **kw: None)
    monkeypatch.setattr(
        "docling.models.stages.ocr.rapid_ocr_model.RapidOcrModel.download_models", download
    )
    monkeypatch.setattr(
        "eco.models._rapidocr_expected",
        lambda ocr_dir: {ocr_dir / "det.onnx": hashlib.sha256(GOOD).hexdigest()},
    )
    return payloads


def test_bad_ocr_file_is_fetched_again(tmp_path, ocr_payloads):
    ocr_payloads += [b"<html>502 Bad Gateway</html>", GOOD]
    waits = []
    download_models(tmp_path, sleep=waits.append)
    assert (tmp_path / "RapidOcr/det.onnx").read_bytes() == GOOD
    assert len(waits) == 1 and models_ready(tmp_path)


def test_existing_bad_ocr_file_is_replaced(tmp_path, ocr_payloads):
    (tmp_path / "RapidOcr").mkdir()
    (tmp_path / "RapidOcr/det.onnx").write_bytes(b"cut off")
    ocr_payloads += [GOOD]
    download_models(tmp_path, sleep=lambda s: None)
    assert (tmp_path / "RapidOcr/det.onnx").read_bytes() == GOOD
    assert models_ready(tmp_path)


def test_bad_ocr_file_fails_setup_after_last_attempt(monkeypatch, capsys, tmp_path, ocr_payloads):
    ocr_payloads += [b"bad"] * 8
    waits = []
    monkeypatch.setitem(download_models.__kwdefaults__, "sleep", waits.append)
    assert main(["setup", "--yes", "--data", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "RapidOcr/det.onnx" in err and "SHA-256" in err
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err
    assert len(waits) == 7 and not ocr_payloads
    assert not (tmp_path / "models/RapidOcr/det.onnx").exists()
    assert not models_ready(tmp_path / "models")


def test_ocr_file_without_registry_hash_is_refused(monkeypatch, tmp_path, ocr_payloads):
    ocr_payloads += [GOOD]
    monkeypatch.setattr("eco.models._rapidocr_expected", lambda d: {d / "det.onnx": None})
    with pytest.raises(RuntimeError, match="det.onnx"):
        download_models(tmp_path, sleep=lambda s: pytest.fail("retried"))
    assert not models_ready(tmp_path)


def test_import_sets_hub_defaults_and_stays_lazy():
    """huggingface_hub reads its settings once, at import, so eco must set them first."""
    code = (
        "import sys, eco.cli\n"
        "assert 'huggingface_hub' not in sys.modules and 'docling' not in sys.modules\n"
        "from huggingface_hub import constants as c\n"
        "print(c.HF_HUB_DISABLE_XET, c.HF_HUB_DOWNLOAD_TIMEOUT)\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("HF_HUB_")}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout
    assert out.split() == ["True", "20"]


def test_setup_end_of_input_is_no(monkeypatch, tmp_path):
    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    monkeypatch.setattr("eco.models._docling_download", lambda **kw: pytest.fail("downloaded"))
    assert main(["setup", "--data", str(tmp_path)]) == 1


def test_setup_yes_downloads(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted"))
    monkeypatch.setattr(
        "eco.models._docling_download",
        lambda **kw: (kw["output_dir"] / "m.onnx").write_bytes(b"x"),
    )
    assert main(["setup", "--yes", "--data", str(tmp_path)]) == 0
    assert f"Models ready in {tmp_path / 'models'}" in capsys.readouterr().out
    assert models_ready(tmp_path / "models")


def test_setup_when_ready_does_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "eco.models._docling_download",
        lambda **kw: (kw["output_dir"] / "m.onnx").write_bytes(b"x"),
    )
    download_models(tmp_path / "models")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted"))
    monkeypatch.setattr("eco.models._docling_download", lambda **kw: pytest.fail("downloaded"))
    assert main(["setup", "--data", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == f"Models ready in {tmp_path / 'models'}"


def test_setup_failure_is_one_line(monkeypatch, capsys, tmp_path):
    """Exhausted retries also raise RuntimeError (see above): this covers both expected failures."""
    monkeypatch.setattr(
        "eco.models._docling_download",
        lambda **kw: (kw["output_dir"] / "w.pkl").write_bytes(b"x"),
    )
    assert main(["setup", "--yes", "--data", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "w.pkl" in err and len(err.strip().splitlines()) == 1 and "Traceback" not in err


# A missing Microsoft Visual C++ Redistributable (task M3-N3, decision Q-20)


def _winerror(code, text):
    """An OSError with the `winerror` that ctypes.WinError sets. Only Windows reads the fourth
    argument of OSError, so the attribute is set by hand."""
    error = OSError(text)
    error.winerror = code
    return error


def _rtree_error():
    return OSError("could not find or load spatialindex_c-64.dll")


# The forms of an error that says a DLL of the PDF engine could not be loaded.
DLL_ERRORS = {
    "rtree": _rtree_error(),
    "pytorch by its code": _winerror(126, "The specified module could not be found."),
    "pytorch by its text": OSError(
        "[WinError 126] The specified module could not be found. Error loading "
        r'"C:\eco\.venv\Lib\site-packages\torch\lib\c10.dll" or one of its dependencies.'
    ),
    "onnxruntime": ImportError(
        "DLL load failed while importing onnxruntime_pybind11_state: "
        "The specified module could not be found."
    ),
}

OTHER_ERRORS = {
    "rtree's words without a dll": OSError("could not find or load libspatialindex_c.so"),
    "pytorch's words without a dll": OSError('Error loading "libtorch_cpu.so"'),
    "another winerror": _winerror(5, "Access is denied."),
    "an import that finds no module": ModuleNotFoundError("No module named 'onnxruntime'"),
    "another import error": ImportError("cannot import name 'index' from 'rtree'"),
    "rtree's words in another type": RuntimeError("could not find or load spatialindex_c-64.dll"),
    "the import words in another type": ValueError("DLL load failed while importing cv2"),
    "a network error": ConnectionError("connection reset"),
}


@pytest.mark.parametrize("error", DLL_ERRORS.values(), ids=list(DLL_ERRORS))
def test_the_dll_errors_of_the_pdf_engine_are_found_on_windows(platform_is, error):
    platform_is("win32")
    assert models.vc_runtime_missing(error)


@pytest.mark.parametrize("system", ["linux", "darwin"])
@pytest.mark.parametrize("error", DLL_ERRORS.values(), ids=list(DLL_ERRORS))
def test_the_same_errors_say_nothing_about_the_runtime_on_other_systems(platform_is, system, error):
    platform_is(system)
    assert not models.vc_runtime_missing(error)


@pytest.mark.parametrize("error", OTHER_ERRORS.values(), ids=list(OTHER_ERRORS))
def test_other_errors_are_not_a_missing_runtime(platform_is, error):
    platform_is("win32")
    assert not models.vc_runtime_missing(error)


@pytest.mark.parametrize("link", ["__cause__", "__context__"])
def test_a_dll_error_behind_another_error_is_found(platform_is, link):
    platform_is("win32")
    outer = ImportError("cannot import name 'index' from 'rtree'")
    setattr(outer, link, _rtree_error())
    assert models.vc_runtime_missing(outer)


def test_a_chain_of_other_errors_is_not_a_missing_runtime(platform_is):
    platform_is("win32")
    assert not models.vc_runtime_missing(_caused_by(RuntimeError("outer"), ValueError("inner")))


def test_the_message_is_the_one_text_every_layer_shows(vc_message):
    assert str(models.VcRuntimeMissing()) == vc_message


def test_a_missing_vc_runtime_is_named_and_never_retried(
    tmp_path, monkeypatch, platform_is, vc_message
):
    platform_is("win32")
    calls, original = [], _rtree_error()

    def fail(**kw):
        calls.append(1)
        raise original

    monkeypatch.setattr("eco.models._docling_download", fail)
    with pytest.raises(models.VcRuntimeMissing) as raised:
        download_models(tmp_path, sleep=lambda s: pytest.fail("retried"))
    assert str(raised.value) == vc_message
    assert "ipv4" not in str(raised.value).lower()
    assert raised.value.__cause__ is original
    assert calls == [1] and not models_ready(tmp_path)


def test_setup_says_when_the_vc_runtime_is_missing(
    monkeypatch, capsys, tmp_path, platform_is, vc_message
):
    platform_is("win32")

    def fail(**kw):
        raise _rtree_error()

    monkeypatch.setattr("eco.models._docling_download", fail)
    assert main(["setup", "--yes", "--data", str(tmp_path)]) == 1
    assert capsys.readouterr().err == f"error: {vc_message}\n"
