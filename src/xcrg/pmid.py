import json
import sqlite3
from collections import OrderedDict

from translator_tom import CURIE

from .context import RunContext


_PMID_CACHE_MAX_ROWS = 512
_PMID_CONNECTIONS = {}
_PMID_WARNING_EMITTED = False
_PMID_CACHE = OrderedDict()


def normalize_pmid(pmid: object | None) -> str | None:
    """Normalize DB PMID values to the numeric string used for intersections."""
    if pmid is None:
        return None
    value = str(pmid).strip()
    if not value:
        return None
    if value.upper().startswith("PMID:"):
        value = value.split(":", 1)[1]
    return value


def get_pmid_connection(ctx: RunContext) -> sqlite3.Connection | None:
    """Return a cached read-only CURIE-to-PMID SQLite connection."""
    global _PMID_WARNING_EMITTED

    db_path = ctx.curie_to_pmids_db_file
    if db_path is None:
        if not _PMID_WARNING_EMITTED:
            ctx.reporter.warning(
                "xCRG curie_to_pmids DB path is not configured; NGD PMID support is disabled."
            )
            _PMID_WARNING_EMITTED = True
        return None

    cache_key = db_path.as_posix()
    if cache_key in _PMID_CONNECTIONS:
        return _PMID_CONNECTIONS[cache_key]

    if not db_path.exists():
        if not _PMID_WARNING_EMITTED:
            ctx.reporter.warning(
                "xCRG curie_to_pmids DB not found at %s; NGD PMID support is disabled.",
                db_path,
            )
            _PMID_WARNING_EMITTED = True
        return None

    try:
        connection = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        _PMID_CONNECTIONS[cache_key] = connection
        return connection
    except sqlite3.Error as exc:
        if not _PMID_WARNING_EMITTED:
            ctx.reporter.warning(
                "Failed to open xCRG curie_to_pmids DB at %s; NGD PMID support is disabled: %s",
                db_path,
                exc,
            )
            _PMID_WARNING_EMITTED = True
        return None


def get_curie_pmids(ctx: RunContext, curie: CURIE | None) -> set[str] | None:
    """Return normalized PMID identifiers for one CURIE from curie_to_pmids."""
    if not curie:
        return None

    cache_key = (ctx.config.curie_to_pmids_db_path, curie)
    if cache_key in _PMID_CACHE:
        _PMID_CACHE.move_to_end(cache_key)
        return _PMID_CACHE[cache_key]

    connection = get_pmid_connection(ctx)
    if connection is None:
        return None

    try:
        row = connection.execute(
            "SELECT pmids FROM curie_to_pmids WHERE curie = ?",
            (curie,),
        ).fetchone()
    except sqlite3.Error:
        pmids = set()
    else:
        if row is None:
            pmids = set()
        else:
            try:
                pmids = set()
                for pmid in json.loads(row[0]):
                    normalized_pmid = normalize_pmid(pmid)
                    if normalized_pmid:
                        pmids.add(normalized_pmid)
            except (TypeError, ValueError, json.JSONDecodeError):
                pmids = set()

    _PMID_CACHE[cache_key] = pmids
    _PMID_CACHE.move_to_end(cache_key)
    while len(_PMID_CACHE) > _PMID_CACHE_MAX_ROWS:
        _PMID_CACHE.popitem(last=False)
    return pmids
