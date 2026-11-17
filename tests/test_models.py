import os
import socket
import subprocess
import sys

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
from eco.models import download_models, models_ready, offline_env, unsafe_files


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
