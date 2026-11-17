import pytest
from fakes import fake_work

from eco.web import jobs


@pytest.fixture
def fake_worker(monkeypatch):
    """Every Runner made in the test runs `fakes.fake_work` in its spawned worker process."""
    monkeypatch.setattr(jobs, "_work", fake_work)
    return fake_work
