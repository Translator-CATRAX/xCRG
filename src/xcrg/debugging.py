import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from translator_tom import (
    QEdgeID,
    QNode,
    Query,
    QueryGraph,
    Response,
    TOMBase
)

from . import trapi
from .config import XCRGConfig
from .reporting import  Reporter
from .utilities import require


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


def safe_debug_token(value: str | None) -> str:
    """Return a filesystem-friendly token for debug run names."""
    if not value:
        return "unbound"
    token = "".join(char if char.isalnum() else "_" for char in value)
    token = "_".join(part for part in token.split("_") if part)
    return token[:80] or "unbound"


def describe_qnode_for_debug(qnode: QNode | None) -> str:
    """Return a compact qnode label for human-readable debug paths."""
    if qnode is None:
        return "unbound"
    ids = qnode.ids or []
    if ids:
        return safe_debug_token(ids[0])
    categories = qnode.categories_list
    if categories:
        return safe_debug_token(categories[0].removeprefix("biolink:"))
    return "unbound"


def make_debug_run_context(query_id: str, query: Query, config: XCRGConfig) -> DebugContext:
    """Create human-readable debug path metadata for one xCRG query."""
    created_at = datetime.now(timezone.utc)
    qnodes = require(query.message.query_graph, QueryGraph).nodes # TODO
    edge_id, edge = trapi.get_single_query_edge(query)
    direction = trapi.get_qualifier_value(edge, "biolink:object_direction_qualifier")
    source_label = describe_qnode_for_debug(qnodes.get(edge.subject))
    target_label = describe_qnode_for_debug(qnodes.get(edge.object))
    direction_label = safe_debug_token(direction)
    run_name = (
        f"{created_at.strftime('%Y%m%d_%H%M%S')}_{query_id}_"
        f"{source_label}_to_{target_label}_{direction_label}"
    )
    debug_dir = config.normalized_debug_dir()
    return DebugContext(
        query_id = query_id,
        created_at = created_at.isoformat(),
        run_name = run_name,
        run_dir = debug_dir / run_name if debug_dir else None,
        query_edge_id = edge_id,
        source_qnode = edge.subject,
        target_qnode = edge.object,
        source_label = source_label,
        target_label = target_label,
        direction = direction,
        artifacts = []
    )


def write_debug_manifest(debug_context: DebugContext, reporter: Reporter) -> None:
    """Write or refresh the human-readable debug manifest for one query."""
    if not debug_context.run_dir:
        return
    try:
        # manifest = {
        #     key: value
        #     for key, value in debug_context.items()
        #     if key not in {"run_dir"}
        # }
        manifest = vars(debug_context)
        manifest["run_dir"] = str(debug_context.run_dir)
        manifest_path = debug_context.run_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, indent=2, sort_keys=True)
    except Exception as exc:
        reporter.warning(f"Failed to write xCRG debug manifest: {exc}")


def debug_dump_json(
        label: str,
        payload: object | TOMBase,
        reporter: Reporter,
        debug_context: DebugContext | None = None,
) -> None:
    """Best-effort debug JSON dump for inferred xCRG runs."""
    if not debug_context or not debug_context.run_dir:
        return
    try:
        debug_context.run_dir.mkdir(parents=True, exist_ok=True)
        readable_path = debug_context.run_dir / f"{label}.json"
        with open(readable_path, "w", encoding="utf-8") as debug_file:
            if isinstance(payload, TOMBase):
                data = payload.to_dict()
            else:
                data = payload
            json.dump(data, debug_file, indent=2, sort_keys=True)
        match payload:
            case Query() | Response() as entity:
                summary = trapi.summarize_response_counts(entity)
            case _:
                summary = ""
        debug_context.artifacts.append(
            {
                "label": label,
                "path": str(readable_path),
                "written_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            }
        )
        write_debug_manifest(debug_context, reporter)
    except Exception as exc:
        reporter.warning(f"Failed to write debug JSON {label}: {exc}")
