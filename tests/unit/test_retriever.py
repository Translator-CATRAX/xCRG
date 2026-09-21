from datetime import timedelta
from pathlib import Path

from xcrg.reporting import StubReporter
from xcrg.retriever import Retriever_Cache

def test_basic_cache_behavior(tmp_path):
    cache = Retriever_Cache(StubReporter(), tmp_path, ttl = timedelta(weeks = 1))
    file = Path(tmp_path / "foo.json")
    content = "{'foo': 'bar'}"

    cache.write_file(file.name, content)
    assert file.exists()
    with open(file, "r", encoding = "utf-8") as f:
        assert f.read() == content

    assert cache.read_file("foo.json") == content
