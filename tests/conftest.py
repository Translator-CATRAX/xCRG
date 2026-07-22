from pathlib import Path

import pytest


# Configure optional test parameters; these currently only affect integration tests
def pytest_addoption(parser):
    parser.addoption(
        "--ngd_db_file",
        help = "The path to the NGD database file"
    )
    parser.addoption(
        "--curie_to_pmids_db_file",
        help = "The path to the Curie-to-PMIDs database file"
    )


@pytest.fixture()
def project_dir() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture
def ngd_db_file(request) -> Path | None:
    if file := request.config.getoption("--ngd_db_file"):
        return Path(file)
    else:
        return None


@pytest.fixture
def curie_to_pmids_db_file(request) -> Path | None:
    if file := request.config.getoption("--curie_to_pmids_db_file"):
        return Path(file)
    else:
        return None


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: run integration tests; requires additional configuration")
    config.addinivalue_line("markers", "unit: run local unit tests")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
