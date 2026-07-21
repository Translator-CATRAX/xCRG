import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: run integration tests; requires additional configuration")
    config.addinivalue_line("markers", "unit: run local unit tests")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
