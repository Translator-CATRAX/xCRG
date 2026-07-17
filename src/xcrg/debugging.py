from dataclasses import dataclass
from pathlib import Path

from translator_tom.models.shared import QEdgeID


@dataclass
class DebugContext:
    """Assorted data for debugging xCRG runner."""
    query_id: str
    created_at: str
    run_name: str
    run_dir: Path | None
    query_edge_id: QEdgeID
    source_qnode: str # TODO: CURIE?
    target_qnode: str # TODO: CURIE?
    source_label: str
    target_label: str
    direction: str | None
    artifacts: list[dict]
