"""Configuration for reusable xCRG execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .debugging import DebugLevel


# TODO: XCRGConfig -> Config
@dataclass(frozen=True)
class XCRGConfig:
    """Runtime inputs supplied by ARAX, Shepherd, or local tests."""

    retriever_url          : str
    ngd_db_path            : str | Path | None = None
    curie_to_pmids_db_path : str | Path | None = None
    tf_path                : str | Path | None = None
    timeout                : int               = 210
    tiers                  : Sequence[int]     = field(default_factory=lambda: [0])
    tf_batch_size          : int               = 50
    resource_id            : str               = "infores:arax"
    scoring_method         : str               = "xcrg-result-filtering-v2" # TODO: StrEnum?
    max_results            : int               = 500
    trapi_schema_version   : str               = "1.6.0"
    biolink_version        : str               = "4.3.2"
    debug_dir              : str | Path | None = None
    debug_level            : DebugLevel        = DebugLevel.BASIC
