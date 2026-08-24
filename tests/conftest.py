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
    parser.addoption(
        "--use_http_cache",
        help = "Cache all HTTP responses from Retriever.",
        action = "store_true",
        default = False
    )


@pytest.fixture(scope = "session")
def config(request) -> XCRGConfig:
    project_dir = Path(__file__).parent.parent # TODO: Fragile...

    ngd_db_file: Path | None = None
    if file := request.config.getoption("--ngd_db_file"):
        ngd_db_file = Path(file)

    curie_to_pmids_db_file: Path | None = None
    if file := request.config.getoption("--curie_to_pmids_db_file"):
        curie_to_pmids_db_file = Path(file)

    debug_level = DebugLevel(request.config.getoption("--debug_level"))

    debug_dir = project_dir / "output" / "debug"
    debug_dir.mkdir(parents = True, exist_ok = True)

    use_http_cache = request.config.getoption("--use_http_cache")

    return XCRGConfig(
        retriever_url = request.config.getoption("--retriever_url"),
        ngd_db_path = ngd_db_file,
        curie_to_pmids_db_path = curie_to_pmids_db_file,
        debug_dir = debug_dir,
        debug_level = debug_level,
        debug_use_http_cache = use_http_cache
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "arax: run ARAX compliance tests (slow, requires network)")
    config.addinivalue_line("markers", "integration: run integration tests (slow, requires network)")
    config.addinivalue_line("markers", "unit: run local unit tests")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/arax/" in str(item.fspath):
            item.add_marker(pytest.mark.arax)
        if "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)


def pytest_make_parametrize_id(config, val, argname):
    # Our own special method for defining custom pytest ids
    # This is primarily so we can make nicer test names/titles
    if hasattr(val, "get_pytest_id"):
        return val.get_pytest_id()
    else:
        return argname
