import pytest
from fixtures.make import build_all


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("pdf_fixtures"))
