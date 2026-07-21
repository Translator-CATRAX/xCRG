"""Reusable xCRG direct and inferred lookup logic."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import uuid
from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from importlib import resources
from typing import cast

import httpx
from pydantic import BaseModel
from translator_tom import (
    CURIE,
    Analysis,
    Attribute,
    AuxGraphID,
    AuxiliaryGraph,
    AuxiliaryGraphsDict,
    BaseQueryGraph,
    Biolink,
    Edge,
    EdgeBinding,
    EdgeID,
    FastJsonValue,
    KnowledgeGraph,
    Message,
    Node,
    NodeBinding,
    QEdge,
    QEdgeID,
    QNode,
    QNodeID,
    Qualifier,
    QualifierConstraint,
    Query,
    QueryGraph,
    Response,
    Result,
    RetrievalSource
)

from .debugging import DebugContext
from .config import XCRGConfig
from .reporting import XCRGReporter
from .utilities import partition, require, XCRGResult

TF_QNODE_ID = "tf"
TP53_CURIE = "NCBIGene:7157"
DIRECT_QEDGE_ID = "direct"
MISSING_SORT_VALUE = float("inf")
NGD_CACHE_MAX_ROWS = 256
PMID_CACHE_MAX_ROWS = 512
MAX_NGD_PUBLICATIONS = 30
NGD_VALUE_URL = "https://arax.ncats.io/api/rtx/v1/ui/#/PubmedMeshNgd"
NGD_DESCRIPTION = (
    "Normalized google distance is a metric based on edge subject/object node "
    "co-occurrence in abstracts of PubMed articles."
)
COMPUTED_EDGE_CONTAINER_DESCRIPTION = (
    "This edge is a container for a computed value between two nodes that is not "
    "directly attachable to other edges."
)

try:
    from bmt import Toolkit
except ImportError:  # pragma: no cover - local unit env may not install worker deps.
    Toolkit = None

_BMT_TOOLKIT = None
_BMT_WARNING_EMITTED = False
_NGD_CONNECTIONS = {}
_NGD_WARNING_EMITTED = False
_NGD_NEIGHBOR_CACHE = OrderedDict()
_PMID_CONNECTIONS = {}
_PMID_WARNING_EMITTED = False
_PMID_CACHE = OrderedDict()
_VALID_ASPECT_QUALIFIERS: frozenset | None = None
_ASPECT_QUALIFIER_WARNING_EMITTED = False

ASPECT_QUALIFIER_ENUM = "GeneOrGeneProductOrChemicalEntityAspectEnum"
ASPECT_QUALIFIER_ROOT = "activity_or_abundance"
FALLBACK_VALID_ASPECT_QUALIFIERS: frozenset[str] = frozenset({
    "activity_or_abundance",
    "abundance",
    "activity",
    "expression",
    "synthesis"
})

FALLBACK_CATEGORY_DEPTH: dict[str, int] = {
    "biolink:ChemicalEntity": 1,
    "biolink:ChemicalMixture": 2,
    "biolink:EnvironmentalFoodContaminant": 2,
    "biolink:FoodAdditive": 2,
    "biolink:MolecularEntity": 2,
    "biolink:ComplexMolecularMixture": 3,
    "biolink:Food": 3,
    "biolink:MolecularMixture": 3,
    "biolink:NucleicAcidEntity": 3,
    "biolink:ProcessedMaterial": 3,
    "biolink:SmallMolecule": 3,
    "biolink:Drug": 4,
}


def get_single_query_edge(query: Query) -> tuple[QEdgeID, QEdge]:
    """Return the single query edge for xCRG queries."""
    qedges = require(query.message.query_graph, QueryGraph).edges # TODO
    if len(qedges) != 1:
        raise ValueError("xCRG runner currently supports only one query edge.")
    qedge_id = next(iter(qedges))
    return qedge_id, qedges[qedge_id]


def get_qualifier_value(edge: QEdge, qualifier_type_id: Biolink.Qualifier) -> str | None:
    """Return a qualifier value from the first qualifier set, if present."""
    qualifier_constraints = edge.qualifier_constraints_list
    if not qualifier_constraints:
        return None
    qualifier_set = qualifier_constraints[0].qualifier_set
    for qualifier in qualifier_set:
        if qualifier.qualifier_type_id == qualifier_type_id:
            return qualifier.qualifier_value
    return None


def get_endpoint_type(categories: list[str] | None) -> str | None:
    """Return the supported xCRG endpoint type for a QNode."""
    if categories is None:
        return None
    if "biolink:ChemicalEntity" in categories:
        return "chemical"
    if "biolink:Gene" in categories:
        return "gene"
    return None


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
    edge_id, edge = get_single_query_edge(query)
    direction = get_qualifier_value(edge, "biolink:object_direction_qualifier")
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


def validate_direct_lookup_query(query: Query) -> None:
    """Validate the direct one-hop xCRG query shape. Raise Error if invalid."""
    qnodes = require(query.message.query_graph, QueryGraph).nodes # TODO
    _, edge = get_single_query_edge(query)

    if edge.knowledge_type == "inferred":
        raise ValueError("xCRG direct lookup does not support inferred edges.")

    if "biolink:affects" not in edge.predicates_list:
        raise ValueError("xCRG direct lookup requires biolink:affects predicate.")

    if edge.subject not in qnodes:
        raise ValueError("Query edge is missing 'subject' query node reference.")
    if edge.object not in qnodes:
        raise ValueError("Query edge is missing 'object' query node reference.")

    pinned_ids = [qid for qid, qnode in qnodes.items() if qnode.ids]
    if len(pinned_ids) != 1:
        raise ValueError("xCRG direct lookup supports exactly one pinned query node.")

    unbound_ids = [qid for qid, qnode in qnodes.items() if not qnode.ids]
    if len(unbound_ids) != 1:
        raise ValueError("xCRG direct lookup supports exactly one unbound query node.")

    pinned_node = qnodes[pinned_ids[0]]
    unbound_node = qnodes[unbound_ids[0]]

    if "biolink:Gene" not in pinned_node.categories_list:
        raise ValueError("xCRG direct lookup requires the pinned node to be a Gene.")
    if "biolink:ChemicalEntity" not in unbound_node.categories_list:
        raise ValueError("xCRG direct lookup requires the unbound node to be a ChemicalEntity.")


def validate_inferred_query(query: Query) -> tuple[QNodeID, QNodeID, QEdge]:
    """Validate a phase-one inferred xCRG query while preserving user direction."""
    qnodes = require(query.message.query_graph, QueryGraph).nodes # TODO
    _, qedge = get_single_query_edge(query)

    if qedge.knowledge_type != "inferred":
        raise ValueError("Expected an inferred query edge.")

    if "biolink:affects" not in qedge.predicates_list:
        raise ValueError("Inferred xCRG query requires 'biolink:affects' predicate.")

    subject_qid = qedge.subject
    if subject_qid not in qnodes:
        raise ValueError("xCRG query is missing 'subject' node.")
    subject_qnode = qnodes[subject_qid]

    object_qid = qedge.object
    if object_qid not in qnodes:
        raise ValueError("xCRG query is missing 'object' node.")
    object_qnode = qnodes[object_qid]

    endpoint_nodes = [subject_qnode, object_qnode]
    pinned_count = sum(1 for node in endpoint_nodes if node.ids)
    if pinned_count != 1:
        raise ValueError("Inferred xCRG query requires exactly one pinned endpoint node.")

    if get_endpoint_type(subject_qnode.categories_list) != "chemical" and \
       get_endpoint_type(object_qnode.categories_list) != "gene":
        raise ValueError(
            "Inferred xCRG query currently requires one 'ChemicalEntity' endpoint "
            "and one 'Gene' endpoint."
        )

    direction = get_qualifier_value(qedge, "biolink:object_direction_qualifier")
    aspect = get_qualifier_value(qedge, "biolink:object_aspect_qualifier")
    if direction not in {"increased", "decreased"}:
        raise ValueError("Inferred xCRG query direction must be 'increased' or 'decreased'.")
    valid_aspects = get_valid_aspect_qualifiers()
    if aspect not in valid_aspects:
        raise ValueError(
            f"Inferred xCRG query requires an 'object_aspect_qualifier' that is a "
            f"descendant of {ASPECT_QUALIFIER_ROOT!r} "
            f"(e.g. {', '.join(sorted(valid_aspects))}); but got {aspect!r}."
        )

    return subject_qid, object_qid, qedge


def load_tf_list(config: XCRGConfig) -> list[str]:
    """Load transcription factors from config or bundled package resources."""
    tf_path = config.normalized_tf_path()
    if tf_path:
        with tf_path.open(encoding = "utf-8") as tf_file:
            tf_data = json.load(tf_file)
    else:
        resource = resources.files("xcrg.resources").joinpath("transcription_factors.json")
        with resource.open(encoding = "utf-8") as tf_file:
            tf_data = json.load(tf_file)
    tf_list = tf_data.get("tf") or []
    if not tf_list:
        raise ValueError("No transcription factors were found in transcription_factors.json.")
    return tf_list


# TODO: Should we just expect that the user has installed the bmt library?
def get_bmt_toolkit(reporter: XCRGReporter):
    """Return a cached Biolink Toolkit instance when the dependency is available."""
    global _BMT_TOOLKIT, _BMT_WARNING_EMITTED
    if Toolkit is None:
        if not _BMT_WARNING_EMITTED:
            reporter.warning("BMT is unavailable; using fallback specificity scores.")
            _BMT_WARNING_EMITTED = True
        return None
    if _BMT_TOOLKIT is None:
        try:
            _BMT_TOOLKIT = Toolkit()
        except Exception as exc:
            if not _BMT_WARNING_EMITTED:
                reporter.warning(
                    f"Failed to initialize BMT; using fallback specificity scores: {exc}"
                )
                _BMT_WARNING_EMITTED = True
            return None
    return _BMT_TOOLKIT


def get_valid_aspect_qualifiers() -> frozenset[str]:
    """Return the set of valid object_aspect_qualifier values for xCRG queries.

    Uses bmt to retrieve all descendants of activity_or_abundance in the
    GeneOrGeneProductOrChemicalEntityAspectEnum, falling back to a hardcoded
    set if bmt is unavailable.
    """
    global _VALID_ASPECT_QUALIFIERS, _ASPECT_QUALIFIER_WARNING_EMITTED
    if _VALID_ASPECT_QUALIFIERS is not None:
        return _VALID_ASPECT_QUALIFIERS
    # TODO: _module_logger = logging.getLogger(__name__)
    if Toolkit is not None:
        try:
            toolkit = _BMT_TOOLKIT or Toolkit()
            descendants = toolkit.get_permissible_value_descendants(
                ASPECT_QUALIFIER_ROOT, ASPECT_QUALIFIER_ENUM
            )
            _VALID_ASPECT_QUALIFIERS = frozenset(descendants)
            return _VALID_ASPECT_QUALIFIERS
        except Exception:
            if not _ASPECT_QUALIFIER_WARNING_EMITTED:
                # TODO: _module_logger.warning(
                # TODO:     f"Could not load valid aspect qualifiers from bmt; "
                # TODO:     f"using fallback set: {exc}"
                # TODO: )
                _ASPECT_QUALIFIER_WARNING_EMITTED = True
    _VALID_ASPECT_QUALIFIERS = FALLBACK_VALID_ASPECT_QUALIFIERS
    return _VALID_ASPECT_QUALIFIERS


def get_category_specificity(category: str, reporter: XCRGReporter) -> int:
    """Return a Biolink specificity heuristic based on non-mixin ancestor count."""
    bmt_toolkit = get_bmt_toolkit(reporter)
    if bmt_toolkit:
        try:
            if not bmt_toolkit.get_element(category):
                return FALLBACK_CATEGORY_DEPTH.get(category, 0)
            ancestors = (
                bmt_toolkit.get_ancestors(
                    category,
                    reflexive=False,
                    formatted=True,
                    mixin=False,
                )
                or []
            )
            return max(len(ancestors), FALLBACK_CATEGORY_DEPTH.get(category, 0))
        except Exception as exc:
            reporter.warning(
                f"Could not calculate BMT specificity for {category}: {exc}"
            )
    return FALLBACK_CATEGORY_DEPTH.get(category, 0)


def is_chemical_category(category: str, reporter: XCRGReporter) -> bool:
    """Return True when a category is ChemicalEntity or a chemical descendant."""
    if category == "biolink:ChemicalEntity" or category in FALLBACK_CATEGORY_DEPTH:
        return True
    bmt_toolkit = get_bmt_toolkit(reporter)
    if not bmt_toolkit:
        return False
    try:
        ancestors = (
            bmt_toolkit.get_ancestors(
                category,
                reflexive=False,
                formatted=True,
                mixin=False,
            )
            or []
        )
        return "biolink:ChemicalEntity" in ancestors
    except Exception as exc:
        reporter.warning(f"Could not inspect category ancestry for {category}: {exc}")
        return False


def get_node_category_specificity(node: Node | None, reporter: XCRGReporter) -> int:
    """Return the most specific chemical category score attached to a KG node."""
    if node is None:
        return 0
    chemical_categories = [
        category
        for category in node.categories_list
        if is_chemical_category(category, reporter)
    ]
    if not chemical_categories:
        return 0

    bmt_toolkit = get_bmt_toolkit(reporter)
    if bmt_toolkit and hasattr(bmt_toolkit, "get_most_specific_category"):
        try:
            most_specific = bmt_toolkit.get_most_specific_category(
                chemical_categories,
                formatted=True,
            )
            if is_chemical_category(most_specific, reporter):
                return get_category_specificity(most_specific, reporter)
        except Exception as exc:
            reporter.warning(f"Could not select most specific category with BMT: {exc}")

    return max(
        FALLBACK_CATEGORY_DEPTH.get(category, 0)
        for category in chemical_categories
    )


def get_node_information_content(node: Node | None) -> float | None:
    """Return a node's Biolink information content attribute, when present."""
    if node is None:
        return None
    values = []
    for attribute in node.attributes:
        if attribute.attribute_type_id != "biolink:information_content":
            continue
        raw_value = attribute.value
        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in raw_values:
            try:
                values.append(float(cast(int | float | str, value))) # TODO
            except (TypeError, ValueError):
                continue
    return max(values) if values else None


def get_ngd_connection(
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> sqlite3.Connection | None:
    """Return a cached read-only NGD SQLite connection when the local DB exists."""
    global _NGD_WARNING_EMITTED

    db_path = config.normalized_ngd_db_path()
    if db_path is None:
        if not _NGD_WARNING_EMITTED:
            reporter.warning("xCRG NGD DB path is not configured; NGD tie-breaker is disabled.")
            _NGD_WARNING_EMITTED = True
        return None

    cache_key = db_path.as_posix()
    if cache_key in _NGD_CONNECTIONS:
        return _NGD_CONNECTIONS[cache_key]

    if not db_path.exists():
        if not _NGD_WARNING_EMITTED:
            reporter.warning(
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
            reporter.warning(
                "Failed to open xCRG NGD DB at %s; NGD tie-breaker is disabled: %s",
                db_path,
                exc,
            )
            _NGD_WARNING_EMITTED = True
        return None


def get_ngd_neighbors(
    curie: CURIE | None,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> dict[CURIE, float] | None:
    """Return cached NGD neighbors for one CURIE from the adjacency-list DB."""
    if not curie:
        return None

    if curie in _NGD_NEIGHBOR_CACHE:
        _NGD_NEIGHBOR_CACHE.move_to_end(curie)
        return _NGD_NEIGHBOR_CACHE[curie]

    connection = get_ngd_connection(config, reporter)
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
    curie_a: CURIE | None,
    curie_b: CURIE | None,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> float | None:
    """Return lower-is-better NGD for a CURIE pair, if present in the local DB."""
    if not curie_a or not curie_b:
        return None
    if curie_a == curie_b:
        return None

    neighbors = get_ngd_neighbors(curie_a, config, reporter)
    if neighbors:
        score = neighbors.get(curie_b)
        if score is not None:
            return score

    # The DB is expected to be symmetric, but this fallback is cheap insurance
    # for partial rows or future DB variants.
    reverse_neighbors = get_ngd_neighbors(curie_b, config, reporter)
    if reverse_neighbors:
        score = reverse_neighbors.get(curie_a)
        if score is not None:
            return score
    return None


def get_pmid_connection(
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> sqlite3.Connection | None:
    """Return a cached read-only CURIE-to-PMID SQLite connection."""
    global _PMID_WARNING_EMITTED

    db_path = config.normalized_curie_to_pmids_db_path()
    if db_path is None:
        if not _PMID_WARNING_EMITTED:
            reporter.warning(
                "xCRG curie_to_pmids DB path is not configured; NGD PMID support is disabled."
            )
            _PMID_WARNING_EMITTED = True
        return None

    cache_key = db_path.as_posix()
    if cache_key in _PMID_CONNECTIONS:
        return _PMID_CONNECTIONS[cache_key]

    if not db_path.exists():
        if not _PMID_WARNING_EMITTED:
            reporter.warning(
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
            reporter.warning(
                "Failed to open xCRG curie_to_pmids DB at %s; NGD PMID support is disabled: %s",
                db_path,
                exc,
            )
            _PMID_WARNING_EMITTED = True
        return None


def get_curie_pmids(
    curie: CURIE | None,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> set[str] | None:
    """Return normalized PMID identifiers for one CURIE from curie_to_pmids."""
    if not curie:
        return None

    cache_key = (config.curie_to_pmids_db_path, curie)
    if cache_key in _PMID_CACHE:
        _PMID_CACHE.move_to_end(cache_key)
        return _PMID_CACHE[cache_key]

    connection = get_pmid_connection(config, reporter)
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
    while len(_PMID_CACHE) > PMID_CACHE_MAX_ROWS:
        _PMID_CACHE.popitem(last=False)
    return pmids


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


def get_ngd_publications(
    curie_a: CURIE | None,
    curie_b: CURIE | None,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> list[str] | None:
    """Return PMID intersection from the same CURIE-to-PMID source as NGD."""
    pmids_a = get_curie_pmids(curie_a, config, reporter)
    pmids_b = get_curie_pmids(curie_b, config, reporter)
    if pmids_a is None or pmids_b is None:
        return None
    shared_pmids = pmids_a & pmids_b
    ordered_pmids = sorted(shared_pmids, key = pmid_sort_key)
    return [f"PMID:{pmid}" for pmid in ordered_pmids[:MAX_NGD_PUBLICATIONS]]


def pmid_sort_key(pmid: str) -> tuple[int, str]:
    """Sort numeric PMID strings deterministically while tolerating odd values."""
    try:
        return 0, f"{int(pmid):020d}"
    except Exception:
        return 1, str(pmid)


def get_sign_templates(final_direction: str) -> list[tuple[str, str]]:
    """Return sign-compatible two-hop templates for the desired final direction."""
    if final_direction == "increased":
        return [("increased", "increased"), ("decreased", "decreased")]
    if final_direction == "decreased":
        return [("increased", "decreased"), ("decreased", "increased")]
    raise ValueError(f"Unsupported final direction: {final_direction}")


def chunk_values(values: list[str], chunk_size: int) -> list[list[str]]:
    """Split values into non-empty batches."""
    if chunk_size <= 0:
        raise ValueError("xCRG TF batch size must be positive.")
    return [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]


def build_two_hop_query(
    original_query: Query,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    tf_list: list[CURIE],
    first_direction: str,
    second_direction: str,
) -> Query:
    """Build a TF-mediated two-hop TRAPI query from the original inferred query."""
    query_graph = require(original_query.message.query_graph, QueryGraph) # TODO
    subject_qnode = deepcopy(query_graph.nodes[subject_qid])
    object_qnode = deepcopy(query_graph.nodes[object_qid])
    return Query(
        message = Message(
            query_graph = QueryGraph(
                nodes = {
                    subject_qid: subject_qnode,
                    TF_QNODE_ID: QNode(ids = tf_list, categories = ["biolink:Gene"]),
                    object_qid: object_qnode,
                },
                edges = {
                    "e0": QEdge(
                        subject = subject_qid,
                        object = TF_QNODE_ID,
                        predicates = ["biolink:affects"],
                        qualifier_constraints = [
                                QualifierConstraint(
                                    qualifier_set = [
                                        Qualifier(
                                            qualifier_type_id = "biolink:object_aspect_qualifier",
                                            qualifier_value = "activity_or_abundance",
                                        ),
                                        Qualifier(
                                            qualifier_type_id = "biolink:object_direction_qualifier",
                                            qualifier_value = first_direction,
                                        ),
                                    ]
                                )
                            ],
                        ),
                    "e1": QEdge (
                        subject = TF_QNODE_ID,
                        object = object_qid,
                        predicates = ["biolink:affects"],
                        qualifier_constraints = [
                            QualifierConstraint(
                                qualifier_set = [
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_aspect_qualifier",
                                        qualifier_value = "activity_or_abundance",
                                    ),
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_direction_qualifier",
                                        qualifier_value = second_direction,
                                    ),
                                ]
                            )
                        ],
                    ),
                },
            ),
            knowledge_graph = KnowledgeGraph.new(),
            results = [],
            auxiliary_graphs = AuxiliaryGraphsDict(),
        ),
        bypass_cache = original_query.bypass_cache,
        submitter = original_query.submitter
    )


def build_direct_query_for_inferred(
    original_query: Query,
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> Query:
    """Build the direct one-hop query that accompanies inferred xCRG mode."""
    query_graph = require(original_query.message.query_graph, QueryGraph) # TODO
    _, original_edge = get_single_query_edge(original_query)
    direct_edge = deepcopy(original_edge)
    direct_edge.knowledge_type = None

    return Query(
        message = Message(
            query_graph = QueryGraph(
                nodes = {
                    subject_qid: deepcopy(query_graph.nodes[subject_qid]),
                    object_qid: deepcopy(query_graph.nodes[object_qid]),
                },
                edges = {
                    DIRECT_QEDGE_ID: direct_edge
                }
            ),
            knowledge_graph = KnowledgeGraph.new(),
            results = [],
            auxiliary_graphs = AuxiliaryGraphsDict(),
        ),
        bypass_cache = original_query.bypass_cache,
        submitter = original_query.submitter
    )


def build_combined_query_graph(
    original_query: Query,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    tf_list: list[str],
) -> QueryGraph:
    """Build a response query graph that can bind direct and TF-mediated results."""
    direct_query = build_direct_query_for_inferred(original_query, subject_qid, object_qid)
    query_graph = require(direct_query.message.query_graph, QueryGraph) # TODO
    query_graph.nodes[TF_QNODE_ID] = QNode(
        ids = tf_list,
        categories = ["biolink:Gene"]
    )
    query_graph.edges["e0"] = QEdge(
        subject = subject_qid,
        predicates = ["biolink:affects"],
        object = TF_QNODE_ID
    )
    query_graph.edges["e1"] = QEdge(
        subject = TF_QNODE_ID,
        predicates = ["biolink:affects"],
        object = object_qid
    )
    return query_graph


def result_has_bad_edge_predicate(
    result: Result,
    edges: dict[EdgeID, Edge],
    predicate: str
) -> bool:
    """Return True when any bound knowledge graph edge has the given predicate."""
    for analysis in result.analyses:
        if not isinstance(analysis, Analysis):
            continue
        for bindings in analysis.edge_bindings.values():
            for binding in bindings or []:
                edge = edges.get(binding.id)
                if not edge:
                    continue
                if edge.predicate == predicate:
                    return True
    return False


def get_bound_node_curie(result: Result, qid: QNodeID) -> CURIE | None:
    """Return the first node binding id for the given qnode."""
    bindings = result.node_bindings.get(qid) or []
    if not bindings:
        return None
    return bindings[0].id


def result_preserves_direction(
    result: Result,
    edges: dict[EdgeID, Edge],
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> bool:
    """Check that the result preserves source->tf and tf->target edge directions."""
    source_curie = get_bound_node_curie(result, subject_qid)
    tf_curie = get_bound_node_curie(result, TF_QNODE_ID)
    target_curie = get_bound_node_curie(result, object_qid)
    if not source_curie or not tf_curie or not target_curie:
        return False

    for analysis in result.analyses:
        if not isinstance(analysis, Analysis): # TODO
            continue

        e0_bindings = analysis.edge_bindings.get("e0") or []
        e1_bindings = analysis.edge_bindings.get("e1") or []
        if not e0_bindings or not e1_bindings:
            return False

        for binding in e0_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != source_curie or edge.object != tf_curie:
                return False

        for binding in e1_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != tf_curie or edge.object != target_curie:
                return False

    return True


def result_preserves_direct_direction(
    result: Result,
    edges: dict[EdgeID, Edge],
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> bool:
    """Check that a direct result preserves the original source->target direction."""
    source_id = get_bound_node_curie(result, subject_qid)
    target_id = get_bound_node_curie(result, object_qid)
    if not source_id or not target_id:
        return False

    for analysis in result.analyses:
        if not isinstance(analysis, Analysis):
            continue
        edge_bindings = analysis.edge_bindings or {}
        direct_bindings = edge_bindings.get(DIRECT_QEDGE_ID) or []
        if not direct_bindings:
            return False

        for binding in direct_bindings:
            edge = edges.get(binding.id)
            if not edge or edge.subject != source_id or edge.object != target_id:
                return False

    return True


def filter_direct_response(
    response: Response,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    config: XCRGConfig,
) -> Response:
    """Filter subclass and wrong-direction results from a direct Retriever response."""
    message = response.message

    edges = {}
    if message.knowledge_graph and message.knowledge_graph.edges:
        edges = message.knowledge_graph.edges

    filtered_results: list[Result] = []
    for result in message.results_list:
        if result_has_bad_edge_predicate(result, edges, "biolink:subclass_of"):
            continue
        if not result_preserves_direct_direction(result, edges, subject_qid, object_qid):
            continue
        filtered_results.append(result)

    filtered_message = deepcopy(message)
    filtered_message.results = filtered_results
    if not filtered_message.knowledge_graph:
        filtered_message.knowledge_graph = KnowledgeGraph.new()
    if not filtered_message.auxiliary_graphs:
        filtered_message.auxiliary_graphs = AuxiliaryGraphsDict()

    return ensure_response_versions(Response(message = filtered_message), config, response)


def merge_filtered_responses(
    responses: list[Response],
    query_graph: QueryGraph,
    config: XCRGConfig,
) -> Response:
    """Merge filtered Retriever responses into a single TRAPI response."""
    nodes = dict[CURIE, Node]()
    edges = dict[EdgeID, Edge]()
    aux_graph = AuxiliaryGraphsDict()
    seen_results = set()
    results = list[Result]()

    for response in responses:
        message = response.message

        if kg_graph := message.knowledge_graph:
            merge_retriever_nodes(nodes, kg_graph.nodes)
            merge_retriever_edges(edges, kg_graph.edges)

        aux_graph.update(message.auxiliary_graphs_dict)

        for result in message.results_list:
            key = json.dumps(
                {
                    "node_bindings": result.node_bindings,
                    "analyses": result.analyses,
                },
                sort_keys=True,
            )

            if key not in seen_results:
                seen_results.add(key)
                results.append(result)

    new_response = Response(message = Message(
        query_graph = query_graph,
        knowledge_graph = KnowledgeGraph(nodes = nodes, edges = edges),
        results = results,
        auxiliary_graphs = aux_graph
    ))

    ensure_response_versions(new_response, config, *responses)

    return new_response


def merge_retriever_nodes(merged_nodes: dict[CURIE, Node], incoming_nodes: dict[CURIE, Node]) -> None:
    """Merge Retriever KG nodes without letting sparse duplicates erase metadata."""
    for node_id, incoming_node in incoming_nodes.items():
        existing_node = merged_nodes.get(node_id)
        if existing_node is None or metadata_weight(incoming_node) > metadata_weight(existing_node):
            merged_nodes[node_id] = deepcopy(incoming_node)


def merge_retriever_edges(merged_edges: dict[EdgeID, Edge], incoming_edges: dict[EdgeID, Edge]) -> None:
    """Merge Retriever KG edges without letting sparse duplicates erase metadata."""
    for edge_id, incoming_edge in incoming_edges.items():
        existing_edge = merged_edges.get(edge_id)
        if existing_edge is None or metadata_weight(incoming_edge) > metadata_weight(existing_edge):
            merged_edges[edge_id] = deepcopy(incoming_edge)


# TODO: This function needs to be reevaluated after the typing refactor
def metadata_weight(entity: Edge | Node | None) -> int:
    """Approximate how much Retriever-provided metadata an entity carries."""
    if entity is None:
        return 0
    weight = 1 # +1 simply for existing
    match entity:
        case Edge() as e:
            weight += len(e.sources)
            weight += len(e.attributes_list)
            weight += len(e.qualifiers_list)
        case Node() as n:
            weight += len(n.attributes)
            weight += len(n.categories)
            if n.name:
                weight += 1
    return weight


def get_answer_qnode_id(
    query_graph: BaseQueryGraph,
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> QNodeID:
    """Return the unpinned endpoint qnode whose bindings are the answer list."""
    for qid in (subject_qid, object_qid):
        if qnode := query_graph.nodes.get(qid):
            if not qnode.ids:
                return qid
    return object_qid


def result_edge_binding_keys(result: Result) -> set[str]:
    """Return qedge ids bound by any analysis in the result."""
    keys = set()
    for analysis in result.analyses:
        if isinstance(analysis, Analysis):
            keys.update(analysis.edge_bindings.keys())
    return keys


def is_two_hop_result(result: Result) -> bool:
    """Return True for TF-mediated inferred results."""
    keys = result_edge_binding_keys(result)
    return "e0" in keys and "e1" in keys


def answer_qnode_uses_category_specificity(
    query_graph: BaseQueryGraph,
    answer_qid: QNodeID,
    reporter: XCRGReporter,
) -> bool:
    """Chemical answers use Biolink specificity before information content."""
    qnode = query_graph.nodes.get(answer_qid)
    if not qnode:
        return False
    return any(is_chemical_category(category, reporter) for category in qnode.categories_list)


# TODO: should answer_id really be an empty string?
def get_result_answer_metrics(
    result: Result,
    nodes: dict[CURIE, Node],
    answer_qid: QNodeID,
    use_category_specificity: bool,
    reporter: XCRGReporter,
) -> tuple[int, float | None, CURIE]:
    """Return sort metrics for the answer node bound by a result."""
    answer_id = get_bound_node_curie(result, answer_qid) or ""
    answer_node = nodes.get(answer_id)
    specificity = (
        get_node_category_specificity(answer_node, reporter)
        if use_category_specificity
        else 0
    )
    information_content = get_node_information_content(answer_node)
    return specificity, information_content, answer_id


def descending_optional(value: float | int | None) -> float:
    """Convert optional descending values into ascending sort components."""
    return -float(value) if value is not None else MISSING_SORT_VALUE


def ascending_optional(value: float | int | None) -> float:
    """Convert optional ascending values into sort components."""
    return float(value) if value is not None else MISSING_SORT_VALUE


def get_result_endpoint_ngd(
    result: Result,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> float | None:
    """Return direct source-answer NGD for the final source/target pair."""
    source_id = get_bound_node_curie(result, subject_qid)
    target_id = get_bound_node_curie(result, object_qid)
    return get_ngd_score(source_id, target_id, config, reporter)


def get_result_answer_tf_ngd(
    result: Result,
    answer_qid: QNodeID,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> float | None:
    """Return answer-to-TF NGD for ordering results within a TF bucket."""
    answer_id = get_bound_node_curie(result, answer_qid)
    tf_id = get_bound_node_curie(result, TF_QNODE_ID)
    return get_ngd_score(answer_id, tf_id, config, reporter)


# def get_original_query_edge_id(message: Message) -> str:
#     """Return the original single qedge id from an xCRG response/query."""
#     qedges = message.message.query_graph.edges
#     if len(qedges) != 1:
#         raise ValueError("xCRG final response expects the original single query edge.")
#     return next(iter(qedges))


def get_edge_bindings(result: Result, qedge_id: QEdgeID) -> list[EdgeBinding]:
    """Return copied edge bindings for a qedge across all analyses."""
    bindings = list[EdgeBinding]()
    seen = set()
    for analysis in result.analyses:
        if not isinstance(analysis, Analysis):
            continue
        for binding in analysis.edge_bindings.get(qedge_id) or []:
            edge_id = binding.id
            if edge_id in seen:
                continue
            seen.add(edge_id)
            copied_binding = deepcopy(binding)
            bindings.append(copied_binding)
    return bindings


def get_result_score(result: Result) -> float | None:
    """Return the first score attached to a result analysis."""
    for analysis in result.analyses:
        if score := analysis.score:
            return score
    return None


def stamp_rank_scores(results: list[Result], config: XCRGConfig) -> None:
    """Assign rank-derived TRAPI Analysis.score values after sorting."""
    total = len(results)
    if total == 0:
        return
    for index, result in enumerate(results):
        score = float(total - index) / total
        for analysis in result.analyses:
            analysis.score = score
            analysis.scoring_method = config.scoring_method


def stamp_xcrg_rank_scores(results: list[Result], config: XCRGConfig) -> None:
    """Assign rank-derived scores only to xCRG analyses in final output."""
    total = len(results)
    if total == 0:
        return
    for index, result in enumerate(results):
        score = float(total - index) / total
        for analysis in result.analyses:
            if analysis.resource_id != config.resource_id:
                continue
            analysis.score = score
            analysis.scoring_method = config.scoring_method


def sort_xcrg_combined_results(
    response: Response,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> None:
    """Sort direct results first, then TF-mediated results by the xCRG policy."""
    message = response.message
    query_graph = message.query_graph or BaseQueryGraph(nodes = {})

    kg_nodes = dict[CURIE, Node]()
    if kg_graph := message.knowledge_graph:
        if nodes := kg_graph.nodes:
            kg_nodes = nodes

    answer_qnode_id = get_answer_qnode_id(query_graph, subject_qid, object_qid)
    use_category_specificity = answer_qnode_uses_category_specificity(
        query_graph,
        answer_qnode_id,
        reporter,
    )

    results: list[Result] = message.results or []
    # Table so we can look up the original index later in sorting functions
    indices: dict[Result, int] = { k: v for v, k in enumerate(results) }

    (inferred_results, direct_results) = partition(results, is_two_hop_result)

    tf_degrees = Counter(
        get_bound_node_curie(result, TF_QNODE_ID)
        for result in inferred_results
        if get_bound_node_curie(result, TF_QNODE_ID)
    )

    def direct_key(result: Result) -> tuple:
        specificity, information_content, answer_id = get_result_answer_metrics(
            result,
            kg_nodes,
            answer_qnode_id,
            use_category_specificity,
            reporter,
        )
        ngd_score = get_result_endpoint_ngd(
            result,
            subject_qid,
            object_qid,
            config,
            reporter,
        )
        return (
            descending_optional(specificity),
            descending_optional(information_content),
            ascending_optional(ngd_score),
            answer_id,
            indices.get(result, 0)
        )

    def inferred_key(result: Result) -> tuple:
        tf_id = get_bound_node_curie(result, TF_QNODE_ID) or ""
        specificity, information_content, answer_id = get_result_answer_metrics(
            result,
            kg_nodes,
            answer_qnode_id,
            use_category_specificity,
            reporter,
        )
        ngd_score = get_result_answer_tf_ngd(
            result,
            answer_qnode_id,
            config,
            reporter,
        )
        return (
            tf_degrees.get(tf_id, 0),
            tf_id,
            descending_optional(specificity),
            descending_optional(information_content),
            ascending_optional(ngd_score),
            answer_id,
            indices.get(result, 0)
        )

    sorted_results = sorted(direct_results, key = direct_key) + \
                     sorted(inferred_results, key = inferred_key)

    stamp_rank_scores(sorted_results, config)
    message.results = sorted_results


def query_qualifiers_to_edge_qualifiers(qedge: QEdge) -> list[Qualifier]:
    """Convert the first QEdge qualifier set into KG edge qualifiers."""
    qualifier_constraints = qedge.qualifier_constraints_list
    if not qualifier_constraints:
        return []

    qualifiers = qualifier_constraints[0].qualifier_set

    return [
        Qualifier(
            qualifier_type_id = qualifier.qualifier_type_id,
            qualifier_value = qualifier.qualifier_value
        )
        for qualifier in qualifiers
        # if qualifier.qualifier_type_id and qualifier.qualifier_value
    ]


def make_stable_id(prefix: str, payload: object) -> str:
    """Return a deterministic compact id for generated KG/support entries."""
    key = json.dumps(payload, sort_keys=True)
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
    return f"{prefix}_{suffix}"


def ensure_response_versions(
    response: Response,
    config: XCRGConfig,
    *responses: Response,
) -> Response:
    """Add response-level TRAPI/Biolink versions when upstream omitted them."""
    schema_versions = (r.schema_version for r in responses if r.schema_version)
    response.schema_version = next(schema_versions, config.trapi_schema_version)

    biolink_versions = (r.biolink_version for r in responses if r.biolink_version)
    response.biolink_version = next(biolink_versions, config.biolink_version)

    return response


def make_xcrg_inferred_edge(
    subject_id: CURIE,
    object_id: CURIE,
    original_qedge: QEdge,
    support_graph_ids: list[str],
    config: XCRGConfig,
) -> tuple[EdgeID, Edge]:
    """Create the final source->target inferred edge supported by TF paths."""
    predicate = (original_qedge.predicates_list or ["biolink:affects"])[0]

    edge_id = make_stable_id(
        "xcrg_inferred_edge",
        {
            "source": subject_id,
            "target": object_id,
            "predicate": predicate,
            "support_graphs": support_graph_ids,
        },
    )

    edge = Edge(
        subject = subject_id,
        predicate = predicate,
        object = object_id,
        qualifiers = query_qualifiers_to_edge_qualifiers(original_qedge),
        attributes = [
            Attribute(
                attribute_type_id = "biolink:knowledge_level",
                value = "prediction",
                attribute_source = config.resource_id
            ),
            Attribute(
                attribute_type_id = "biolink:agent_type",
                value = "computational_model",
                attribute_source = config.resource_id
            ),
            Attribute(
                attribute_type_id = "biolink:support_graphs",
                value = cast(FastJsonValue, support_graph_ids), # TODO
                attribute_source = config.resource_id
            ),
        ],
        sources = [
            RetrievalSource(
                resource_id = config.resource_id,
                resource_role = "primary_knowledge_source"
            )
        ]
    )

    if not edge.qualifiers:
        edge.qualifiers = None

    return edge_id, edge


def make_xcrg_ngd_edge(
    subject_id: CURIE,
    object_id: CURIE,
    ngd_score: float | str,
    publications: list[str] | None,
    config: XCRGConfig,
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
                attribute_source = config.resource_id,
                attribute_type_id = "EDAM-DATA:2526",
                description = NGD_DESCRIPTION,
                original_attribute_name = "normalized_google_distance",
                value_url = NGD_VALUE_URL,
                value = ngd_score,
            ),
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "EDAM-OPERATION:0226",
                original_attribute_name = "virtual_relation_label",
                value = "N1",
            ),
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "biolink:creation_date",
                original_attribute_name = "defined_datetime",
                value = datetime.now(timezone.utc).isoformat(),
            ),
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "EDAM-DATA:1772",
                description = COMPUTED_EDGE_CONTAINER_DESCRIPTION,
                value_type_id = "metatype:Boolean",
                value = True,
            ),
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "biolink:knowledge_level",
                value = "statistical_association",
            ),
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "biolink:agent_type",
                value = "automated_agent",
            ),
        ],
        sources = [
            RetrievalSource(
                resource_id = config.resource_id,
                resource_role = "primary_knowledge_source",
            )
        ]
    )

    if publications:
        assert edge.attributes is not None # TODO: this is guaranteed not to be null
        edge.attributes.append(
            Attribute(
                attribute_source = config.resource_id,
                attribute_type_id = "biolink:publications",
                original_attribute_name = "publications",
                value_type_id = "EDAM-DATA:1187",
                value = cast(FastJsonValue, publications), # TODO
            )
        )

    return edge_id, edge


def copy_retriever_node(
    node_id: CURIE | None,
    retriever_nodes: dict[CURIE, Node],
    final_nodes: dict[CURIE, Node],
) -> None:
    """Copy a Retriever-provided KG node verbatim into the final KG."""
    if node_id and node_id in retriever_nodes and node_id not in final_nodes:
        final_nodes[node_id] = deepcopy(retriever_nodes[node_id])


def copy_query_bound_node(
    qnode_id: QNodeID,
    node_id: CURIE | None,
    original_qgraph: BaseQueryGraph,
    retriever_nodes: dict[CURIE, Node],
    final_nodes: dict[CURIE, Node],
) -> None:
    """Copy explicit query-node metadata for a pinned answer endpoint."""
    if not node_id or node_id in final_nodes:
        return

    retriever_node = retriever_nodes.get(node_id)
    if retriever_node and retriever_node.categories:
        return

    qnode = original_qgraph.nodes.get(qnode_id)
    if not qnode:
        return

    if node_id not in qnode.ids_list:
        return

    categories = qnode.categories_list
    if not qnode.categories:
        return

    final_nodes[node_id] = Node(
        categories = deepcopy(categories),
        attributes = [],
    )


def copy_retriever_edge_and_nodes(
    edge_id: EdgeID | None,
    retriever_edges: dict[EdgeID, Edge],
    retriever_nodes: dict[CURIE, Node],
    final_edges: dict[EdgeID, Edge],
    final_nodes: dict[CURIE, Node],
    retriever_auxiliary_graphs: AuxiliaryGraphsDict | None = None,
    final_auxiliary_graphs: AuxiliaryGraphsDict | None = None,
    copied_auxiliary_graphs: set[AuxGraphID] | None = None,
) -> bool:
    """Copy a Retriever KG edge and endpoint nodes verbatim when present."""
    if not edge_id or edge_id not in retriever_edges:
        return False

    edge = deepcopy(retriever_edges[edge_id])
    subject_id = edge.subject
    object_id = edge.object

    if not node_is_present_for_evidence(subject_id, retriever_nodes, final_nodes):
        return False
    if not node_is_present_for_evidence(object_id, retriever_nodes, final_nodes):
        return False

    final_edges[edge_id] = edge
    copy_retriever_node(subject_id, retriever_nodes, final_nodes)
    copy_retriever_node(object_id, retriever_nodes, final_nodes)
    copy_retriever_edge_support_graphs(
        edge,
        retriever_edges,
        retriever_nodes,
        cast(dict, retriever_auxiliary_graphs), # TODO
        final_edges,
        final_nodes,
        final_auxiliary_graphs,
        copied_auxiliary_graphs,
    )

    return True


def copy_retriever_edge_support_graphs(
    edge: Edge,
    retriever_edges: dict[EdgeID, Edge],
    retriever_nodes: dict[CURIE, Node],
    retriever_auxiliary_graphs: AuxiliaryGraphsDict,
    final_edges: dict[EdgeID, Edge],
    final_nodes: dict[CURIE, Node],
    final_auxiliary_graphs: AuxiliaryGraphsDict | None,
    copied_auxiliary_graphs: set[AuxGraphID] | None,
) -> None:
    """Copy Retriever auxiliary graphs referenced by edge support_graphs attrs."""
    if final_auxiliary_graphs is None:
        return

    if not retriever_auxiliary_graphs:
        remove_edge_support_graph_attrs(edge)
        return

    if copied_auxiliary_graphs is None:
        copied_auxiliary_graphs = set()

    for support_graph_id in get_edge_support_graph_ids(edge):
        copy_retriever_auxiliary_graph(
            support_graph_id,
            retriever_edges,
            retriever_nodes,
            retriever_auxiliary_graphs,
            final_edges,
            final_nodes,
            final_auxiliary_graphs,
            copied_auxiliary_graphs,
        )

    trim_edge_support_graph_attrs(edge, final_auxiliary_graphs)


def trim_edge_support_graph_attrs(edge: Edge, aux_graph: AuxiliaryGraphsDict) -> None:
    """Drop support graph references that are not present in final aux graphs."""
    trimmed_attributes = []

    for attribute in edge.attributes_list:
        if attribute.attribute_type_id != "biolink:support_graphs":
            trimmed_attributes.append(attribute)
            continue

        value = attribute.value

        if isinstance(value, list):
            copied_values = [
                support_graph_id
                for support_graph_id in value
                if support_graph_id in aux_graph
            ]
            if copied_values:
                copied_attribute = deepcopy(attribute)
                copied_attribute.value = cast(FastJsonValue, copied_values) # TODO
                trimmed_attributes.append(copied_attribute)
        elif isinstance(value, str) and value in aux_graph:
            trimmed_attributes.append(attribute)

    edge.attributes = trimmed_attributes


def remove_edge_support_graph_attrs(edge: Edge) -> None:
    """Remove support_graphs attrs when no Retriever aux graph map is available."""
    edge.attributes = [
        attribute
        for attribute in edge.attributes_list
        if attribute.attribute_type_id != "biolink:support_graphs"
    ]


def get_edge_support_graph_ids(edge: Edge) -> list[AuxGraphID]:
    """Return support graph IDs referenced by a Retriever KG edge."""
    support_graph_ids = list[AuxGraphID]()
    for attribute in edge.attributes_list:
        if attribute.attribute_type_id != "biolink:support_graphs":
            continue
        value = attribute.value
        if isinstance(value, list):
            support_graph_ids.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, str):
            support_graph_ids.append(value)
    return support_graph_ids


def copy_retriever_auxiliary_graph(
    support_graph_id: AuxGraphID,
    retriever_edges: dict[EdgeID, Edge],
    retriever_nodes: dict[CURIE, Node],
    retriever_auxiliary_graphs: AuxiliaryGraphsDict,
    final_edges: dict[EdgeID, Edge],
    final_nodes: dict[CURIE, Node],
    final_auxiliary_graphs: AuxiliaryGraphsDict,
    copied_auxiliary_graphs: set[AuxGraphID],
) -> bool:
    """Copy a Retriever auxiliary graph and its referenced KG edges."""
    if support_graph_id in final_auxiliary_graphs:
        return True
    if support_graph_id in copied_auxiliary_graphs:
        return support_graph_id in final_auxiliary_graphs

    aux_graph = retriever_auxiliary_graphs.get(support_graph_id)
    if not aux_graph:
        return False

    copied_auxiliary_graphs.add(support_graph_id)
    copied_edges = []

    for edge_id in aux_graph.edges:
        # TODO: This if block is pretty gnarly
        if edge_id in final_edges or copy_retriever_edge_and_nodes(
            edge_id,
            retriever_edges,
            retriever_nodes,
            final_edges,
            final_nodes,
            retriever_auxiliary_graphs,
            final_auxiliary_graphs,
            copied_auxiliary_graphs,
        ):
            copied_edges.append(edge_id)

    if not copied_edges:
        return False

    copied_auxiliary_graph = deepcopy(aux_graph)
    copied_auxiliary_graph.edges = copied_edges
    final_auxiliary_graphs[support_graph_id] = copied_auxiliary_graph

    return True


def node_is_present_for_evidence(
    node_id: CURIE | None,
    retriever_nodes: dict[CURIE, Node],
    final_nodes: dict[CURIE, Node],
) -> bool:
    """Return True when an evidence edge has an endpoint node to reference."""
    if not node_id:
        return False
    if node_id in final_nodes:
        return True
    return node_id in retriever_nodes


def add_ngd_analysis_support_graph(
    analysis: Analysis,
    kg_edges: dict[EdgeID, Edge],
    kg_nodes: dict[CURIE, Node],
    auxiliary_graphs: AuxiliaryGraphsDict,
    retriever_nodes: dict[CURIE, Node],
    source_id: CURIE,
    target_id: CURIE,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> None:
    """Attach a virtual NGD edge as analysis-level support.

    ARAX/xDTD keeps the analysis support graph even when no NGD is available,
    displaying the NGD value as "inf". Keep that as a string to avoid emitting
    non-standard JSON numeric Infinity.
    """
    ngd_score = get_ngd_score(source_id, target_id, config, reporter)
    ngd_value: float | str = ngd_score if ngd_score is not None else "inf"
    publications = get_ngd_publications(source_id, target_id, config, reporter)

    ngd_edge_id, ngd_edge = make_xcrg_ngd_edge(
        source_id,
        target_id,
        ngd_value,
        publications,
        config,
    )

    copy_retriever_node(source_id, retriever_nodes, kg_nodes)
    copy_retriever_node(target_id, retriever_nodes, kg_nodes)
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


# TODO: This method uses the tmp types: ResultPair, XCRGResult
def get_or_create_final_result(
    final_results_by_pair: dict[tuple[CURIE, CURIE], XCRGResult],
    final_results: list[XCRGResult],
    subject_qid: QNodeID,
    object_qid: QNodeID,
    subject_id: CURIE,
    object_id: CURIE,
) -> XCRGResult:
    """Return the final one-hop result for a source/target answer pair."""
    pair_key = (subject_id, object_id)

    if pair_key not in final_results_by_pair:
        result = XCRGResult(
            node_bindings = {
                subject_qid: [NodeBinding(id = subject_id, attributes = [])],
                object_qid: [NodeBinding(id = object_id, attributes = [])]
            },
            xcrg_first_index = len(final_results)
        )
        final_results_by_pair[pair_key] = result
        final_results.append(result)

    return final_results_by_pair[pair_key]


def add_direct_evidence(final_result: XCRGResult, bindings: list[EdgeBinding]) -> None:
    """Attach direct one-hop KG edge bindings to a final result."""
    for binding in bindings:
        edge_id = binding.id
        if edge_id in final_result.xcrg_direct_binding_ids:
            continue
        final_result.xcrg_direct_binding_ids.add(edge_id)
        final_result.xcrg_direct_bindings.append(binding)


def add_support_path_edges(final_result: XCRGResult, path_edge_ids: list[EdgeID]) -> None:
    """Collect unique TF-mediated path edges for the final predicted edge."""
    for edge_id in path_edge_ids:
        if edge_id in final_result.xcrg_support_edge_ids:
            continue
        final_result.xcrg_support_edge_ids.add(edge_id)


def finalize_clean_result_analyses(
    final_result: XCRGResult,
    original_qgraph: BaseQueryGraph,
    retriever_nodes: dict[CURIE, Node],
    retriever_edges: dict[EdgeID, Edge],
    retriever_auxiliary_graphs: AuxiliaryGraphsDict,
    kg_nodes: dict[CURIE, Node],
    kg_edges: dict[EdgeID, Edge],
    auxiliary_graphs: AuxiliaryGraphsDict,
    original_qedge_id: QEdgeID,
    original_qedge: QEdge,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> None:
    """Build final Retriever/xCRG analyses after evidence grouping."""
    source_qnode = original_qedge.subject
    source_id = final_result.node_bindings[source_qnode][0].id
    copy_query_bound_node(
        source_qnode,
        source_id,
        original_qgraph,
        retriever_nodes,
        kg_nodes,
    )

    target_qnode = original_qedge.object
    target_id = final_result.node_bindings[target_qnode][0].id
    copy_query_bound_node(
        target_qnode,
        target_id,
        original_qgraph,
        retriever_nodes,
        kg_nodes,
    )

    xcrg_bindings = list[EdgeBinding]()

    direct_bindings = final_result.xcrg_direct_bindings
    for binding in direct_bindings:
        copied_binding = deepcopy(binding)
        edge_id = copied_binding.id
        if copy_retriever_edge_and_nodes(
            edge_id,
            retriever_edges,
            retriever_nodes,
            kg_edges,
            kg_nodes,
            retriever_auxiliary_graphs,
            auxiliary_graphs,
        ):
            xcrg_bindings.append(copied_binding)

    support_edges = final_result.xcrg_support_edge_ids
    copied_support_edges = [
        edge_id
        for edge_id in support_edges
        if copy_retriever_edge_and_nodes(
            edge_id,
            retriever_edges,
            retriever_nodes,
            kg_edges,
            kg_nodes,
            retriever_auxiliary_graphs,
            auxiliary_graphs,
        )
    ]

    if copied_support_edges:
        support_graph_id = make_stable_id(
            "xcrg_support",
            {
                "source": source_id,
                "target": target_id,
                "edges": copied_support_edges,
            },
        )

        auxiliary_graphs[support_graph_id] = AuxiliaryGraph(
            edges = copied_support_edges,
            attributes = [],
        )

        copy_retriever_node(source_id, retriever_nodes, kg_nodes)
        copy_retriever_node(target_id, retriever_nodes, kg_nodes)

        inferred_edge_id, inferred_edge = make_xcrg_inferred_edge(
            source_id,
            target_id,
            original_qedge,
            [support_graph_id],
            config,
        )

        kg_edges[inferred_edge_id] = inferred_edge
        xcrg_bindings.append(EdgeBinding(id = inferred_edge_id, attributes = []))

    if xcrg_bindings:
        analysis = Analysis(
            resource_id = config.resource_id,
            edge_bindings = {
                original_qedge_id: xcrg_bindings,
            }
        )
        add_ngd_analysis_support_graph(
            analysis,
            kg_edges,
            kg_nodes,
            auxiliary_graphs,
            retriever_nodes,
            source_id,
            target_id,
            config,
            reporter,
        )
        final_result.analyses = [analysis]
    else:
        final_result.analyses = []


def build_trapi_clean_response(
    query: Query,
    old_response: Response,
    subject_qid: QNodeID,
    object_qid: QNodeID,
    config: XCRGConfig,
    reporter: XCRGReporter | None = None,
) -> Response:
    """Convert debug-shaped direct+2-hop results into one-hop TRAPI results."""
    reporter = reporter or XCRGReporter() # reporter stub
    qedge_id, qedge = get_single_query_edge(query)

    old_kgraph = old_response.message.knowledge_graph or KnowledgeGraph.new()
    old_aux_graphs = old_response.message.auxiliary_graphs_dict

    new_qgraph = deepcopy(query.message.query_graph)
    new_kgraph = KnowledgeGraph.new()
    new_aux_graphs = AuxiliaryGraphsDict()

    new_results_by_pair = {}
    new_results = list[XCRGResult]()

    for result_index, result in enumerate(old_response.message.results_list):
        source_id = get_bound_node_curie(result, subject_qid)
        target_id = get_bound_node_curie(result, object_qid)
        if not source_id or not target_id:
            continue

        pair_key = (source_id, target_id)
        if pair_key not in new_results_by_pair and len(new_results) >= config.max_results:
            continue

        final_result = get_or_create_final_result(
            new_results_by_pair,
            new_results,
            subject_qid,
            object_qid,
            source_id,
            target_id,
        )

        if final_result.xcrg_first_score is None:
            final_result.xcrg_first_score = get_result_score(result)
            final_result.xcrg_first_index = result_index

        if is_two_hop_result(result):
            path_edge_ids: list[str] = [
                binding.id
                for qedge_id in ("e0", "e1")
                for binding in get_edge_bindings(result, qedge_id)
            ]
            if path_edge_ids:
                add_support_path_edges(
                    final_result,
                    path_edge_ids,
                )
        else:
            add_direct_evidence(
                final_result,
                get_edge_bindings(result, DIRECT_QEDGE_ID),
            )

    for final_result in new_results:
        finalize_clean_result_analyses(
            final_result,
            require(new_qgraph, BaseQueryGraph), # TODO
            old_kgraph.nodes,
            old_kgraph.edges,
            old_aux_graphs,
            new_kgraph.nodes,
            new_kgraph.edges,
            new_aux_graphs,
            qedge_id,
            qedge,
            config,
            reporter,
        )

    new_results.sort(
        key = lambda it: (
            descending_optional(it.xcrg_first_score),
            it.xcrg_first_index or 0
        )
    )

    new_response = Response(
        message = Message(
            query_graph = new_qgraph,
            knowledge_graph = new_kgraph,
            results = [
                result.to_trapi_result()
                for result in new_results
                if result.analyses
            ],
            auxiliary_graphs = new_aux_graphs
        )
    )

    stamp_xcrg_rank_scores(new_response.message.results_list, config)

    return ensure_response_versions(new_response, config, old_response)


def write_debug_manifest(debug_context: DebugContext, reporter: XCRGReporter) -> None:
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
    payload: object | BaseModel,
    reporter: XCRGReporter,
    debug_context: DebugContext | None = None,
) -> None:
    """Best-effort debug JSON dump for inferred xCRG runs."""
    if not debug_context or not debug_context.run_dir:
        return
    try:
        debug_context.run_dir.mkdir(parents=True, exist_ok=True)
        readable_path = debug_context.run_dir / f"{label}.json"
        with open(readable_path, "w", encoding="utf-8") as debug_file:
            if isinstance(payload, BaseModel):
                data = payload.model_dump(mode = "json")
            else:
                data = payload
            json.dump(data, debug_file, indent=2, sort_keys=True)
        match payload:
            case Query() | Response() as entity:
                summary = summarize_response_counts(entity)
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


def filter_inferred_response(
    response: Response,
    subject_qid: QNodeID,
    target_qid: QNodeID,
    config: XCRGConfig,
) -> Response:
    """Filter subclass and wrong-direction results from a two-hop Retriever response."""
    message = response.message

    kg_edges = dict[EdgeID, Edge]()
    if message.knowledge_graph:
        kg_edges = message.knowledge_graph.edges

    filtered_results = []
    for result in message.results_list:
        tf_id = get_bound_node_curie(result, TF_QNODE_ID)
        if tf_id == TP53_CURIE:
            continue
        if result_has_bad_edge_predicate(result, kg_edges, "biolink:subclass_of"):
            continue
        if not result_preserves_direction(result, kg_edges, subject_qid, target_qid):
            continue
        filtered_results.append(result)

    filtered_message = deepcopy(message)
    filtered_message.results = filtered_results
    if not filtered_message.knowledge_graph:
        filtered_message.knowledge_graph = KnowledgeGraph.new()
    if not filtered_message.auxiliary_graphs:
        filtered_message.auxiliary_graphs = AuxiliaryGraphsDict()

    return ensure_response_versions(Response(message = filtered_message), config, response)


# TODO: typing
def summarize_response_counts(entity: Query | Response) -> dict:
    """Return compact counts for a TRAPI response."""
    message = entity.message
    knowledge_graph = message.knowledge_graph or KnowledgeGraph.new()
    return {
        "result_count": len(message.results_list),
        "node_count": len(knowledge_graph.nodes),
        "edge_count": len(knowledge_graph.edges),
    }


def format_json_for_log(value: object | BaseModel) -> str:
    """Return compact JSON for diagnostic logs."""
    if isinstance(value, BaseModel):
        data = value.model_dump(mode = "json")
    else:
        data = value
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def log_retriever_response(
    response: Response,
    http_status_code: int,
    reporter: XCRGReporter,
) -> None:
    """Emit useful Retriever status/counts without requiring debug files."""
    counts = summarize_response_counts(response)
    retriever_status = response.status
    description = response.description
    reporter.info(
        "xCRG Retriever response HTTP %s; status=%s; results=%s; nodes=%s; edges=%s; description=%s",
        http_status_code,
        retriever_status,
        counts["result_count"],
        counts["node_count"],
        counts["edge_count"],
        description,
    )
    if retriever_status and retriever_status != "Complete":
        reporter.warning(
            "xCRG Retriever returned non-complete status %s: %s",
            retriever_status,
            description,
        )
    if counts["result_count"] == 0 or retriever_status != "Complete":
        for entry in response.logs[:5]:
            if isinstance(entry, dict):
                reporter.info(
                    "xCRG Retriever log [%s] %s",
                    entry.get("level", "INFO"),
                    entry.get("message"),
                )
            else:
                reporter.info("xCRG Retriever log %s", entry)


async def run_sync_retriever_lookup(
    query: Query,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> Response:
    """Run a sync Retriever lookup and return its TRAPI response."""
    reporter.info("Sending xCRG lookup query to %s", config.retriever_url)
    reporter.debug(
        "xCRG Retriever query graph: %s",
        format_json_for_log(query.message.query_graph),
    )

    # TODO: xCRG Retriever parameters: {"tiers": [0], "timeout": 210}
    #  I do not think these parameters are being used like this (at least anymore)
    # reporter.debug(
    #     "xCRG Retriever parameters: %s",
    #     format_json_for_log(query.parameters),
    # )

    # TODO: figure out how the timeout ought to work
    timeout = httpx.Timeout(timeout = 5.0) # TODO: query.timeout or 5.0)
    async with httpx.AsyncClient(timeout = timeout) as client:
        try:
            http_response = await client.post(config.retriever_url, json = query)
            http_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            reporter.error(
                "xCRG Retriever HTTP error %s from %s: %s",
                exc.response.status_code,
                config.retriever_url,
                exc.response.text[:2000],
            )
            raise
        response = Response.from_dict(http_response.json())

    message = response.message
    if not message:
        raise ValueError("Retriever response did not contain a TRAPI message.")

    if not message.knowledge_graph:
        message.knowledge_graph = KnowledgeGraph.new()
    if not message.results:
        message.results = list[Result]()
    if not message.auxiliary_graphs:
        message.auxiliary_graphs = AuxiliaryGraphsDict()

    log_retriever_response(response, http_response.status_code, reporter)

    return response


async def run_direct_lookup(
    query: Query,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> Response:
    """Run the original one-hop direct xCRG lookup."""
    validate_direct_lookup_query(query)
    return await run_sync_retriever_lookup(query, config, reporter)


async def run_inferred_lookup(
    query_id: str,
    query: Query,
    config: XCRGConfig,
    reporter: XCRGReporter,
) -> Response:
    """Run phase-one TF-mediated inferred xCRG lookup."""
    debug_context = make_debug_run_context(query_id, query, config)
    debug_dump_json(
        "original_inferred_query",
        query,
        reporter,
        debug_context,
    )
    subject_qid, object_qid, edge = validate_inferred_query(query)

    qgraph = require(query.message.query_graph, QueryGraph)
    subject_ids: list[str] = qgraph.nodes[subject_qid].ids or []
    object_ids: list[str] = qgraph.nodes[object_qid].ids or []
    endpoint_ids = set(subject_ids) | set(object_ids)

    tf_list = [
        tf_id
        for tf_id in load_tf_list(config)
        if tf_id != TP53_CURIE and tf_id not in endpoint_ids
    ]
    if not tf_list:
        raise ValueError("No transcription factors remain after TP53/target filtering.")

    direct_message = build_direct_query_for_inferred(query, subject_qid, object_qid)
    debug_dump_json(
        "direct_lookup_query",
        direct_message,
        reporter,
        debug_context,
    )
    direct_response = await run_sync_retriever_lookup(direct_message, config, reporter)
    debug_dump_json(
        "direct_raw_response",
        direct_response,
        reporter,
        debug_context,
    )
    filtered_direct_response = filter_direct_response(
        direct_response,
        subject_qid,
        object_qid,
        config,
    )
    debug_dump_json(
        "direct_filtered_response",
        filtered_direct_response,
        reporter,
        debug_context,
    )

    final_direction = get_qualifier_value(edge, "biolink:object_direction_qualifier")
    sign_templates = get_sign_templates(cast(str, final_direction)) # TODO: cast
    tf_batches = chunk_values(tf_list, config.tf_batch_size)
    reporter.info(
        "Running inferred xCRG lookup with %s TFs across %s batches of up to %s IDs.",
        len(tf_list),
        len(tf_batches),
        config.tf_batch_size,
    )

    filtered_responses = []
    debug_summary = {
        "query_id": query_id,
        "final_direction": final_direction,
        "tf_count": len(tf_list),
        "batch_size": config.tf_batch_size,
        "batch_count": len(tf_batches),
        "direct_response": summarize_response_counts(filtered_direct_response),
        "templates": [],
    }
    for template_idx, (first_dir, second_dir) in enumerate(sign_templates, start = 1):
        template_summary = {
            "template_index": template_idx,
            "first_direction": first_dir,
            "second_direction": second_dir,
            "batches": [],
        }
        for batch_idx, tf_batch in enumerate(tf_batches, start = 1):
            two_hop_query = build_two_hop_query(
                query,
                subject_qid,
                object_qid,
                tf_batch,
                first_dir,
                second_dir,
            )
            two_hop_query.timeout = config.timeout # TODO: two_hop_query.timeout or config.timeout
            # TODO: q.tiers = q.tiers or config.normalized_tiers()

            if not two_hop_query.submitter:
                two_hop_query.submitter = config.resource_id
            debug_dump_json(
                f"template_{template_idx}_batch_{batch_idx}_query",
                two_hop_query,
                reporter,
                debug_context,
            )
            response = await run_sync_retriever_lookup(two_hop_query, config, reporter)
            debug_dump_json(
                f"template_{template_idx}_batch_{batch_idx}_raw_response",
                response,
                reporter,
                debug_context,
            )
            filtered_response = filter_inferred_response(
                response,
                subject_qid,
                object_qid,
                config,
            )
            debug_dump_json(
                f"template_{template_idx}_batch_{batch_idx}_filtered_response",
                filtered_response,
                reporter,
                debug_context,
            )
            filtered_responses.append(filtered_response)
            template_summary["batches"].append(
                {
                    "batch_index": batch_idx,
                    "tf_ids": tf_batch,
                    "tf_count": len(tf_batch),
                    "raw_response": summarize_response_counts(response),
                    "filtered_response": summarize_response_counts(filtered_response),
                }
            )
        debug_summary["templates"].append(template_summary)

    merged_query_graph = build_combined_query_graph(
        query,
        subject_qid,
        object_qid,
        tf_list,
    )

    merged_inferred = merge_filtered_responses(
        filtered_responses,
        require(build_two_hop_query(
            query,
            subject_qid,
            object_qid,
            tf_list,
            sign_templates[0][0],
            sign_templates[0][1],
        ).message.query_graph, QueryGraph), # TODO: require
        config,
    )
    merged = merge_filtered_responses(
        [filtered_direct_response, merged_inferred],
        merged_query_graph,
        config,
    )
    sort_xcrg_combined_results(merged, subject_qid, object_qid, config, reporter)
    debug_dump_json(
        "merged_debug_response",
        merged,
        reporter,
        debug_context,
    )
    final_response = build_trapi_clean_response(
        query,
        merged,
        subject_qid,
        object_qid,
        config,
        reporter,
    )
    debug_summary["merged_response"] = summarize_response_counts(final_response)
    debug_summary["debug_run_dir"] = str(debug_context.run_dir)
    debug_dump_json(
        "inferred_debug_summary",
        debug_summary,
        reporter,
        debug_context,
    )
    debug_dump_json(
        "merged_inferred_response",
        final_response,
        reporter,
        debug_context,
    )
    return final_response


def is_xcrg_mvp2_query(query: dict[str, object]) -> bool:
    """Return True when a query matches the MVP2 xCRG inferred shape."""
    try:
        validate_inferred_query(Query.from_dict(query))
    except Exception:
        return False
    return True


async def async_run_xcrg(
    original_query: dict[str, object], # TODO: original_query -> query
    config: XCRGConfig,
    logger: XCRGReporter | None = None, # TODO: logger -> reporter
    query_id: str | None = None,
) -> dict:
    """Run xCRG and return a complete TRAPI response."""
    reporter = logger or XCRGReporter() # reporter stub
    query_id = query_id or uuid.uuid4().hex[:8]

    reporter.debug("Original Query:\n" + str(original_query))

    query = Query.from_dict(deepcopy(original_query))
    query.timeout = config.timeout # TODO: query.timeout or config.timeout
    # TODO: tiers parameter?

    if not query.submitter:
        query.submitter = config.resource_id

    _, edge = get_single_query_edge(query)

    response: Response
    if edge.knowledge_type == "inferred":
        response = await run_inferred_lookup(query_id, query, config, reporter)
    else:
        response = await run_direct_lookup(query, config, reporter)

    # # TODO: Figure out if Query.schema_version is part of TRAPI
    # if schema_version := original_query.get("schema_version"):
    #     response.schema_version = str(schema_version)
    # else:
    #     response.schema_version = config.trapi_schema_version
    #
    # # TODO: Figure out if Query.biolink_version is part of TRAPI
    # if biolink_version := original_query.get("biolink_version"):
    #     response.biolink_version = str(biolink_version)
    # else:
    #     response.biolink_version = config.biolink_version

    return response.to_dict()


def run_xcrg(
    query: dict[str, object],
    config: XCRGConfig,
    logger: XCRGReporter | None = None, # TODO: logger -> reporter
    query_id: str | None = None,
) -> dict:
    """Synchronous wrapper for callers that are not already running an event loop."""
    return asyncio.run(
        async_run_xcrg(
            original_query = query,
            config = config,
            logger = logger,
            query_id = query_id,
        )
    )
