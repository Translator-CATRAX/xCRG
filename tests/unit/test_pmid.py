from pathlib import Path

from tests.utilities import make_curie_to_pmids_db
from xcrg.config import XCRGConfig
from xcrg.pmid import get_curie_pmids
from xcrg.reporting import Stub_Reporter


def test_pmids(tmp_path: Path, config: XCRGConfig):
    db_file = make_curie_to_pmids_db(tmp_path, {
        "FOO:1234": [2018915346, 2271560481],
        "FOO:5678": [4023233424, 4275878409]
    })
    assert get_curie_pmids(db_file, Stub_Reporter(), "FOO:1234") == {"2018915346", "2271560481"}
    assert get_curie_pmids(db_file, Stub_Reporter(), "FOO:5678") == {"4023233424", "4275878409"}
