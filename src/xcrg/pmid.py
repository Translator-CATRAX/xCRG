import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import cast

from translator_tom import CURIE

from .memory import U32_View
from .reporting import Reporter

_PMID_CACHE_MAX_ROWS = 512
_PMID_CONNECTIONS = {}
_PMID_WARNING_EMITTED = False
_PMID_CACHE = OrderedDict()


def get_pmid_connection(db_file: Path | None, reporter: Reporter) -> sqlite3.Connection | None:
    """Return a cached read-only CURIE-to-PMID SQLite connection."""
    global _PMID_WARNING_EMITTED

    if db_file is None:
        if not _PMID_WARNING_EMITTED:
            reporter.warning("xCRG curie_to_pmids DB path is not configured; NGD PMID support is disabled.")
            _PMID_WARNING_EMITTED = True
        return None

    cache_key = db_file.as_posix()
    if cache_key in _PMID_CONNECTIONS:
        return _PMID_CONNECTIONS[cache_key]

    if not db_file.exists():
        if not _PMID_WARNING_EMITTED:
            reporter.warning("xCRG curie_to_pmids DB not found at %s; NGD PMID support is disabled.", db_file)
            _PMID_WARNING_EMITTED = True
        return None

    try:
        connection = sqlite3.connect(
            f"file:{db_file.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        _PMID_CONNECTIONS[cache_key] = connection
        return connection
    except sqlite3.Error as exc:
        if not _PMID_WARNING_EMITTED:
            reporter.warning(
                "Failed to open xCRG curie_to_pmids DB at %s; NGD PMID support is disabled: %s",
                db_file,
                exc,
            )
            _PMID_WARNING_EMITTED = True
        return None


def get_curie_pmids(db_file: Path | None, reporter: Reporter, curie: CURIE | None) -> set[str] | None:
    """Return normalized PMID identifiers for one CURIE from curie_to_pmids."""
    if not curie:
        return None

    cache_key = (db_file, curie)
    if cache_key in _PMID_CACHE:
        _PMID_CACHE.move_to_end(cache_key)
        return _PMID_CACHE[cache_key]

    connection = get_pmid_connection(db_file, reporter)
    if connection is None:
        return None

    pmids = set[str]()
    try:
        row = connection.execute("SELECT pmids FROM curie_to_pmids WHERE curie = ?", (curie,)).fetchone()
        data = cast(bytes, row[0])
        u32s = U32_View(data, byte_order = "little")
        for u32 in u32s:
            pmids.add(str(u32))
    except Exception as e:
        reporter.warning("An error occurred while selecting PMIDs: %s", e)

    _PMID_CACHE[cache_key] = pmids
    _PMID_CACHE.move_to_end(cache_key)
    while len(_PMID_CACHE) > _PMID_CACHE_MAX_ROWS:
        _PMID_CACHE.popitem(last=False)
    return pmids
