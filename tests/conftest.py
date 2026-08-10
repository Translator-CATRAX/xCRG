from pathlib import Path

import pytest

from xcrg import XCRGConfig, DebugLevel


# Configure optional test parameters; these currently only affect integration tests
def pytest_addoption(parser):
    parser.addoption(
        "--retriever_url",
        help = "The URL for the Retriever query endpoint",
        default = "https://retriever.ci.transltr.io/query"
    )
    parser.addoption(
        "--ngd_db_file",
        help = "The path to the NGD database file"
    )
    parser.addoption(
        "--curie_to_pmids_db_file",
        help = "The path to the Curie-to-PMIDs database file"
    )
    parser.addoption(
        "--debug_level",
        help = "Choose how much debug data to save for each xCRG run.",
        choices = [x.value for x in DebugLevel],
        default = DebugLevel.NONE.value
    )


@pytest.fixture()
def config(request) -> XCRGConfig:
    project_dir = Path(__file__).parent.parent # TODO: Fragile...

    ngd_db_file: Path | None = None
    if file := request.config.getoption("--ngd_db_file"):
        ngd_db_file = Path(file)

    curie_to_pmids_db_file: Path | None = None
    if file := request.config.getoption("--curie_to_pmids_db_file"):
        curie_to_pmids_db_file = Path(file)

    debug_level = DebugLevel(request.config.getoption("--debug_level"))

    debug_dir: Path | None = None
    if debug_level != DebugLevel.NONE:
        assert (debug_dir := project_dir / "output" / "debug")
        debug_dir.mkdir(parents = True, exist_ok = True)

    return XCRGConfig(
        retriever_url = request.config.getoption("--retriever_url"),
        ngd_db_path = ngd_db_file,
        curie_to_pmids_db_path = curie_to_pmids_db_file,
        debug_dir = debug_dir,
        debug_level = debug_level
    )


def pytest_configure(config):
    # pytest has been configured in this project to run unit tests by default. And so the "all" marker is
    # here to make it easy to run everything again, instead of having to type "unit or integration", etc.
    config.addinivalue_line("markers", "all: run all tests")
    config.addinivalue_line("markers", "integration: run integration tests; requires additional configuration")
    config.addinivalue_line("markers", "unit: run local unit tests")


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.all)
        if "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
