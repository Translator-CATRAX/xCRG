"""Configuration for reusable xCRG execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class XCRGConfig:
    """Runtime inputs supplied by ARAX, Shepherd, or local tests."""

    retriever_url: str
    ngd_db_path: str | Path | None = None
    tf_path: str | Path | None = None
    timeout: int = 210
    tiers: Sequence[int] = field(default_factory=lambda: [0])
    tf_batch_size: int = 50
    resource_id: str = "infores:arax"
    scoring_method: str = "xcrg-result-filtering-v2"
    max_results: int = 500
    trapi_schema_version: str = "1.6.0"
    biolink_version: str = "4.3.2"
    debug_dir: str | Path | None = None

    def normalized_tiers(self) -> list[int]:
        """Return tiers as a mutable list for TRAPI parameters."""
        return list(self.tiers)

    def normalized_ngd_db_path(self) -> Path | None:
        """Return the configured NGD DB path, if provided."""
        return Path(self.ngd_db_path) if self.ngd_db_path else None

    def normalized_tf_path(self) -> Path | None:
        """Return the configured TF file path, if provided."""
        return Path(self.tf_path) if self.tf_path else None

    def normalized_debug_dir(self) -> Path | None:
        """Return the optional debug directory path."""
        return Path(self.debug_dir) if self.debug_dir else None
