import tempfile
from importlib.metadata import version

from fastapi.testclient import TestClient

from eco import __version__
from eco.cli import main
from eco.models import models_dir, models_ready
from eco.web.app import create_app


def test_health_without_token(tmp_path):
    response = TestClient(create_app(tmp_path, token="secret")).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": __version__, "models_ready": False}
    assert response.headers["x-content-type-options"] == "nosniff"


def test_models_env_and_version_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("ECO_MODELS", str(tmp_path / "models"))
    directory = models_dir(tmp_path / "data")
    assert directory == tmp_path / "models"
    directory.mkdir()
    (directory / ".complete").write_text("0.0.1")
    assert not models_ready(directory)
    (directory / ".complete").write_text(version("docling"))
    assert models_ready(directory)


def test_unwritable_data_dir_for_convert_and_web(tmp_path, monkeypatch, capsys):
    directory = tmp_path / "data"
    directory.mkdir()
    real_tempfile = tempfile.TemporaryFile

    def deny(*args, **kwargs):
        if kwargs.get("dir") == directory:
            raise PermissionError("denied")
        return real_tempfile(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", deny)
    for command in ("convert", "web"):
        args = [command, "missing.md"] if command == "convert" else [command, "--no-browser"]
        assert main([*args, "--data", str(directory)]) == 1
        assert f"error: Data directory not writable: {directory}" in capsys.readouterr().err
