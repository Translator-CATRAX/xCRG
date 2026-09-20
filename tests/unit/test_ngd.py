from pathlib import Path

from xcrg.ngd import get_ngd_neighbors
from xcrg.reporting import StubReporter
from tests.utilities import make_ngd_db_file


def test_ngd(tmp_path: Path):
    ngd_db_file = make_ngd_db_file(tmp_path, [
        ("FOO:123", [["BAR:123", 0.123], ["BAZ:123", 0.246]], 123),
        ("FOO:234", [["BAR:234", 0.234], ["BAZ:234", 0.468]], 234)
    ])
    assert get_ngd_neighbors(ngd_db_file, StubReporter(), "FOO:123") == {
        "BAR:123": 0.123,
        "BAZ:123": 0.246
    }
    assert get_ngd_neighbors(ngd_db_file, StubReporter(), "FOO:234") == {
        "BAR:234": 0.234,
        "BAZ:234": 0.468
    }
