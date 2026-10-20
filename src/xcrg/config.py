from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .debugging import Debug_Level


# TODO: validation to guarantee correct settings
@dataclass(frozen = True)
class Config:
    """The main configuration for query execution."""
    retriever_url: str
    """The URL to Retriever instance that handles TRAPI 2.0+ queries."""

    curie_ngd_db_file: str | Path | None = field(default = None)
    """The Path to ARAX NGD SQLite database used for NGD scoring/support edges."""

    curie_to_pmids_db_file: str | Path | None = field(default = None)
    """The Path to CURIE-to-PMID SQLite database used to attach NGD publication support."""

    # TODO: Clarify; is this query timeout, per-http-request timeout, etc.?
    timeout: timedelta = field(default = timedelta(seconds = 210))
    """Retriever HTTP timeout in seconds."""

    # TODO: How is this used in TRAPI 2.0+?
    tiers: Sequence[int] = field(default_factory = lambda: [0])
    """Retriever data tiers passed in TRAPI parameters.tiers"""

    tf_file: str | Path | None = field(default = None)
    """The Path to transcription tactor JSON file; defaults to the bundled list."""

    tf_batch_size : int = field(default = 50)
    """The number of transcription factors included in each batched request to Retriever."""

    resource_id: str = field(default = "infores:arax")
    """Resource ID used for xCRG-created edges and attributes."""
    
    scoring_method: str = field(default = "xcrg-result-filtering-v2") # TODO: StrEnum?
    """Result analysis scoring method label."""

    max_results: int = field(default = 500)
    """Maximum number of final ranked answers."""

    trapi_schema_version: str = field(default = "2.0.0")
    """Response schema version supplied by the caller."""

    biolink_version: str = field(default = "4.3.2")
    """Response Biolink version supplied by the caller."""

    cache_dir: Path | None = field(default = None)
    """The Path to a directory where Retriever TRAPI Responses are cached."""

    cache_ttl: timedelta | None  = field(default = None)
    """The Time-To-Live (TTL) for entries in the cache."""

    cache_clear_on_start: bool = field(default = True)
    """Determines if the cache is cleared on first invocation of the runner."""

    debug_dir: str | Path | None = field(default = None)
    """The Path to a directory where debug data will be emitted."""

    debug_run_name: str | None = field(default = None)
    """A unique name for the debug data."""

    debug_level: str | Debug_Level | None = field(default = Debug_Level.BASIC)
    """The amount of data that will be captured during a debug run."""
