import json
import math
import sqlite3
from collections import OrderedDict
from datetime import datetime, timezone
from typing import cast

from translator_tom import (
    CURIE,
    Analysis,
    Attribute,
    AuxiliaryGraph,
    AuxiliaryGraphsDict,
    Edge,
    EdgeID,
    FastJsonValue,
    Node,
    RetrievalSource,
)

from . import trapi
from .context import RunContext
from .pmid import get_curie_pmids
from .utilities import make_stable_id


NGD_CACHE_MAX_ROWS = 256
MAX_NGD_PUBLICATIONS = 30
NGD_VALUE_URL = "https://arax.ncats.io/api/rtx/v1/ui/#/PubmedMeshNgd"
NGD_DESCRIPTION = (
    "Normalized google distance is a metric based on edge subject/object node "
    "co-occurrence in abstracts of PubMed articles."
)

_NGD_CONNECTIONS = {}
_NGD_WARNING_EMITTED = False
_NGD_NEIGHBOR_CACHE = OrderedDict()

COMPUTED_EDGE_CONTAINER_DESCRIPTION = (
    "This edge is a container for a computed value between two nodes that is not "
    "directly attachable to other edges."
)


def get_ngd_connection(ctx: RunContext) -> sqlite3.Connection | None:
    """Return a cached read-only NGD SQLite connection when the local DB exists."""
    global _NGD_WARNING_EMITTED

    db_path = ctx.ngd_db_file
    if db_path is None:
        if not _NGD_WARNING_EMITTED:
            ctx.reporter.warning("xCRG NGD DB path is not configured; NGD tie-breaker is disabled.")
            _NGD_WARNING_EMITTED = True
        return None

    cache_key = db_path.as_posix()
    if cache_key in _NGD_CONNECTIONS:
        return _NGD_CONNECTIONS[cache_key]

    if not db_path.exists():
        if not _NGD_WARNING_EMITTED:
            ctx.reporter.warning(
                "xCRG NGD DB not found at %s; NGD tie-breaker is disabled.",
                db_path,
            )
            _NGD_WARNING_EMITTED = True
        return None

    try:
        connection = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        _NGD_CONNECTIONS[cache_key] = connection
        return connection
    except sqlite3.Error as exc:
        if not _NGD_WARNING_EMITTED:
            ctx.reporter.warning(
                "Failed to open xCRG NGD DB at %s; NGD tie-breaker is disabled: %s",
                db_path,
                exc,
            )
            _NGD_WARNING_EMITTED = True
        return None


def get_ngd_neighbors(
    ctx: RunContext,
    curie: CURIE | None,
) -> dict[CURIE, float] | None:
    """Return cached NGD neighbors for one CURIE from the adjacency-list DB."""
    if not curie:
        return None

    if curie in _NGD_NEIGHBOR_CACHE:
        _NGD_NEIGHBOR_CACHE.move_to_end(curie)
        return _NGD_NEIGHBOR_CACHE[curie]

    connection = get_ngd_connection(ctx)
    if connection is None:
        return None

    try:
        row = connection.execute(
            "SELECT ngd FROM curie_ngd WHERE curie = ?",
            (curie,),
        ).fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        neighbors = {}
    else:
        try:
            neighbors = {}
            for neighbor, score in json.loads(row[0]):
                try:
                    ngd_score = float(score)
                except (TypeError, ValueError):
                    continue
                # Only keep meaningful NGD values. Missing/invalid values should
                # behave like "no tie-breaker" instead of helping a result.
                if not math.isfinite(ngd_score) or ngd_score <= 0.0:
                    continue
                neighbors[str(neighbor)] = ngd_score
        except (TypeError, ValueError, json.JSONDecodeError):
            neighbors = {}

    _NGD_NEIGHBOR_CACHE[curie] = neighbors
    _NGD_NEIGHBOR_CACHE.move_to_end(curie)
    while len(_NGD_NEIGHBOR_CACHE) > NGD_CACHE_MAX_ROWS:
        _NGD_NEIGHBOR_CACHE.popitem(last=False)
    return neighbors


def get_ngd_score(
    ctx: RunContext,
    curie_a: CURIE | None,
    curie_b: CURIE | None,
) -> float | None:
    """Return lower-is-better NGD for a CURIE pair, if present in the local DB."""
    if not curie_a or not curie_b:
        return None
    if curie_a == curie_b:
        return None

    neighbors = get_ngd_neighbors(ctx, curie_a)
    if neighbors:
        score = neighbors.get(curie_b)
        if score is not None:
            return score

    # The DB is expected to be symmetric, but this fallback is cheap insurance
    # for partial rows or future DB variants.
    reverse_neighbors = get_ngd_neighbors(ctx, curie_b)
    if reverse_neighbors:
        assert curie_a # Because PyCharm cannot infer that it cannot be null here
        score = reverse_neighbors.get(curie_a)
        if score is not None:
            return score
    return None


def pmid_sort_key(pmid: str) -> tuple[int, str]:
    """Sort numeric PMID strings deterministically while tolerating odd values."""
    try:
        return 0, f"{int(pmid):020d}"
    except Exception:
        return 1, str(pmid)


def get_ngd_publications(
    ctx: RunContext,
    curie_a: CURIE | None,
    curie_b: CURIE | None,
) -> list[str] | None:
    """Return PMID intersection from the same CURIE-to-PMID source as NGD."""
    pmids_a = get_curie_pmids(ctx, curie_a)
    pmids_b = get_curie_pmids(ctx, curie_b)
    if pmids_a is None or pmids_b is None:
        return None
    shared_pmids = pmids_a & pmids_b
    ordered_pmids = sorted(shared_pmids, key = pmid_sort_key)
    return [f"PMID:{pmid}" for pmid in ordered_pmids[:MAX_NGD_PUBLICATIONS]]


def make_xcrg_ngd_edge(
    ctx: RunContext,
    subject_id: CURIE,
    object_id: CURIE,
    ngd_score: float | str,
    publications: list[str] | None,
) -> tuple[EdgeID, Edge]:
    """Create an ARAX-style virtual NGD edge for analysis support graphs."""
    edge_id = make_stable_id(
        "xcrg_ngd_edge",
        {
            "source": subject_id,
            "target": object_id,
            "ngd": ngd_score,
        },
    )
    edge = Edge(
        subject = subject_id,
        predicate = "biolink:occurs_together_in_literature_with",
        object = object_id,
        attributes = [
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "EDAM-DATA:2526",
                description = NGD_DESCRIPTION,
                original_attribute_name = "normalized_google_distance",
                value_url = NGD_VALUE_URL,
                value = ngd_score,
            ),
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "EDAM-OPERATION:0226",
                original_attribute_name = "virtual_relation_label",
                value = "N1",
            ),
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "biolink:creation_date",
                original_attribute_name = "defined_datetime",
                value = datetime.now(timezone.utc).isoformat(),
            ),
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "EDAM-DATA:1772",
                description = COMPUTED_EDGE_CONTAINER_DESCRIPTION,
                value_type_id = "metatype:Boolean",
                value = True,
            ),
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "biolink:knowledge_level",
                value = "statistical_association",
            ),
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "biolink:agent_type",
                value = "automated_agent",
            ),
        ],
        sources = [
            RetrievalSource(
                resource_id = ctx.config.resource_id,
                resource_role = "primary_knowledge_source",
            )
        ]
    )

    if publications:
        assert edge.attributes # guaranteed; for type checkers
        edge.attributes.append(
            Attribute(
                attribute_source = ctx.config.resource_id,
                attribute_type_id = "biolink:publications",
                original_attribute_name = "publications",
                value_type_id = "EDAM-DATA:1187",
                value = cast(FastJsonValue, publications), # TODO
            )
        )

    return edge_id, edge


def add_ngd_analysis_support_graph(
    ctx: RunContext,
    analysis: Analysis,
    kg_edges: dict[EdgeID, Edge],
    kg_nodes: dict[CURIE, Node],
    auxiliary_graphs: AuxiliaryGraphsDict,
    retriever_nodes: dict[CURIE, Node],
    source_id: CURIE,
    target_id: CURIE,
) -> None:
    """Attach a virtual NGD edge as analysis-level support.

    ARAX/xDTD keeps the analysis support graph even when no NGD is available,
    displaying the NGD value as "inf". Keep that as a string to avoid emitting
    non-standard JSON numeric Infinity.
    """
    ngd_score = get_ngd_score(ctx, source_id, target_id)
    ngd_value: float | str = ngd_score if ngd_score is not None else "inf"
    publications = get_ngd_publications(ctx, source_id, target_id)

    ngd_edge_id, ngd_edge = make_xcrg_ngd_edge(
        ctx,
        source_id,
        target_id,
        ngd_value,
        publications
    )

    trapi.copy_node(source_id, retriever_nodes, kg_nodes)
    trapi.copy_node(target_id, retriever_nodes, kg_nodes)
    kg_edges[ngd_edge_id] = ngd_edge

    support_graph_id = make_stable_id(
        "xcrg_ngd_support",
        {
            "source": source_id,
            "target": target_id,
            "edge": ngd_edge_id,
        },
    )
    auxiliary_graphs[support_graph_id] = AuxiliaryGraph(
        edges = [ngd_edge_id],
        attributes = []
    )

    if not analysis.support_graphs:
        analysis.support_graphs = []
    # explicit set above means we get the actual list ref
    support_graphs = analysis.support_graphs_list

    if support_graph_id not in support_graphs:
        support_graphs.append(support_graph_id)
