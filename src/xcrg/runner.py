"""Reusable xCRG direct and inferred lookup logic."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import Counter
from copy import deepcopy
from typing import cast

from translator_tom import (
    CURIE,
    Analysis,
    Attribute,
    AuxGraphID,
    AuxiliaryGraph,
    AuxiliaryGraphsDict,
    BaseQueryGraph,
    Edge,
    EdgeBinding,
    EdgeID,
    FastJsonValue,
    KnowledgeGraph,
    KnowledgeType,
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
    RetrievalSource,
)

from . import DebugLevel, biolink, ngd, retriever, trapi
from .config import XCRGConfig
from .constants import TF_QNODE_ID, TP53_CURIE, DIRECT_QEDGE_ID
from .context import RunContext
from .reporting import LogReporter, Reporter
from .utilities import (
    asc_optional,
    chunk_values,
    desc_optional,
    make_stable_id,
    partition,
    XCRGResult
)


def get_sign_templates(final_direction: str) -> list[tuple[str, str]]:
    """Return sign-compatible two-hop templates for the desired final direction."""
    if final_direction == "increased":
        return [("increased", "increased"), ("decreased", "decreased")]
    if final_direction == "decreased":
        return [("increased", "decreased"), ("decreased", "increased")]
    raise ValueError(f"Unsupported final direction: {final_direction}")


def build_two_hop_query(
    ctx: RunContext,
    tf_list: list[CURIE],
    first_direction: str,
    second_direction: str,
) -> Query:
    """Build a TF-mediated two-hop TRAPI query from the original inferred query."""
    return Query(
        message = Message(
            query_graph = QueryGraph(
                nodes = {
                    ctx.subject_qid: deepcopy(ctx.subject_qnode),
                    TF_QNODE_ID: QNode(ids = tf_list, categories = ["biolink:Gene"]),
                    ctx.object_qid: deepcopy(ctx.object_qnode),
                },
                edges = {
                    "e0": QEdge(
                        subject = ctx.subject_qid,
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
                        object = ctx.object_qid,
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
        bypass_cache = ctx.query.bypass_cache,
        submitter = ctx.query.submitter or ctx.config.resource_id
        # TODO: Query.timeout will become available in TRAPI 2.0
        # two_hop_query.timeout = two_hop_query.timeout or config.timeout
        # TODO: q.tiers = q.tiers or config.normalized_tiers()
    )


def build_one_hop_query(ctx: RunContext) -> Query:
    """Build the direct one-hop query that accompanies inferred xCRG mode."""
    direct_edge = deepcopy(ctx.query_edge)
    direct_edge.knowledge_type = None

    return Query(
        message = Message(
            query_graph = QueryGraph(
                nodes = {
                    ctx.subject_qid: deepcopy(ctx.subject_qnode),
                    ctx.object_qid: deepcopy(ctx.object_qnode),
                },
                edges = {
                    DIRECT_QEDGE_ID: direct_edge
                }
            ),
            knowledge_graph = KnowledgeGraph.new(),
            results = [],
            auxiliary_graphs = AuxiliaryGraphsDict(),
        ),
        bypass_cache = ctx.query.bypass_cache,
        submitter = ctx.query.submitter
    )


def build_combined_query_graph(ctx: RunContext) -> QueryGraph:
    """Build a response query graph that can bind direct and TF-mediated results."""
    query = build_one_hop_query(ctx)
    qgraph = cast(QueryGraph, query.message.query_graph)
    qgraph.nodes[TF_QNODE_ID] = QNode(
        ids = ctx.tf_list,
        categories = ["biolink:Gene"]
    )
    qgraph.edges["e0"] = QEdge(
        subject = ctx.subject_qid,
        predicates = ["biolink:affects"],
        object = TF_QNODE_ID
    )
    qgraph.edges["e1"] = QEdge(
        subject = TF_QNODE_ID,
        predicates = ["biolink:affects"],
        object = ctx.object_qid
    )
    return qgraph


def result_has_edge_predicate(
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
    object_qid: QNodeID
) -> Response:
    """Filter subclass and wrong-direction results from a direct Retriever response."""
    message = response.message

    edges: dict[EdgeID, Edge] = {}
    if message.knowledge_graph:
        edges = message.knowledge_graph.edges

    filtered_results: list[Result] = []
    for result in message.results_list:
        if result_has_edge_predicate(result, edges, "biolink:subclass_of"):
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

    return Response(
        schema_version = response.schema_version,
        biolink_version = response.biolink_version,
        message = filtered_message,
    )


def merge_filtered_responses(
    ctx: RunContext,
    responses: list[Response],
    query_graph: QueryGraph
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
            # TODO: Is there a better way to do this?
            result_dict = result.to_dict()
            key = json.dumps(
                {
                    "node_bindings": result_dict.get('node_bindings', {}),
                    "analyses": result_dict.get('analyses', [])
                },
                sort_keys=True,
            )

            if key not in seen_results:
                seen_results.add(key)
                results.append(result)

    return Response(
        schema_version = responses[0].schema_version if responses else ctx.trapi_schema_version,
        biolink_version = responses[0].biolink_version if responses else ctx.biolink_version,
        message = Message(
            query_graph = query_graph,
            knowledge_graph = KnowledgeGraph(nodes = nodes, edges = edges),
            results = results,
            auxiliary_graphs = aux_graph
        )
    )


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


# TODO: should answer_id really be an empty string?
def get_result_answer_metrics(
    ctx: RunContext,
    result: Result,
    nodes: dict[CURIE, Node],
    answer_qid: QNodeID,
    use_category_specificity: bool,
) -> tuple[int, float | None, CURIE]:
    """Return sort metrics for the answer node bound by a result."""
    answer_id = get_bound_node_curie(result, answer_qid) or ""
    answer_node = nodes.get(answer_id)

    specificity = (
        biolink.get_node_category_specificity(ctx, answer_node)
        if use_category_specificity
        else 0
    )

    attributes: list[Attribute]
    if answer_node:
        attributes = answer_node.attributes
    else:
        attributes = []

    values = []
    for attribute in attributes:
        if attribute.attribute_type_id != "biolink:information_content":
            continue
        raw_value = attribute.value
        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in raw_values:
            try:
                values.append(float(cast(int | float | str, value))) # TODO
            except (TypeError, ValueError):
                continue
    information_content = max(values) if values else None

    return specificity, information_content, answer_id


def stamp_rank_scores(
    results: list[Result],
    scoring_method: str,
    resource_id: str | None = None
) -> None:
    """Assign rank-derived TRAPI Analysis.score values after sorting."""
    total = len(results)
    if total == 0:
        return
    for index, result in enumerate(results):
        score = float(total - index) / total
        for analysis in result.analyses:
            if resource_id and resource_id != analysis.resource_id:
                continue
            analysis.score = score
            analysis.scoring_method = scoring_method


def sort_xcrg_combined_results(ctx: RunContext, response: Response) -> None:
    """Sort direct results first, then TF-mediated results by the xCRG policy."""
    message = response.message
    query_graph = message.query_graph or BaseQueryGraph(nodes = {})

    kg_nodes = dict[CURIE, Node]()
    if kg_graph := message.knowledge_graph:
        if nodes := kg_graph.nodes:
            kg_nodes = nodes

    answer_qnode_id = get_answer_qnode_id(query_graph, ctx.subject_qid, ctx.object_qid)

    use_category_specificity = False
    if qnode := query_graph.nodes.get(answer_qnode_id):
        use_category_specificity = any(biolink.is_chemical_category(ctx, c) for c in qnode.categories_list)

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
            ctx,
            result,
            kg_nodes,
            answer_qnode_id,
            use_category_specificity
        )

        ngd_score = ngd.get_ngd_score(
            ctx,
            get_bound_node_curie(result, ctx.subject_qid),
            get_bound_node_curie(result, ctx.object_qid)
        )

        return (
            desc_optional(specificity),
            desc_optional(information_content),
            asc_optional(ngd_score),
            answer_id,
            indices.get(result, 0)
        )

    def inferred_key(result: Result) -> tuple:
        tf_id = get_bound_node_curie(result, TF_QNODE_ID) or ""
        specificity, information_content, answer_id = get_result_answer_metrics(
            ctx,
            result,
            kg_nodes,
            answer_qnode_id,
            use_category_specificity
        )

        ngd_score = ngd.get_ngd_score(
            ctx,
            get_bound_node_curie(result, answer_qnode_id),
            get_bound_node_curie(result, TF_QNODE_ID)
        )

        return (
            tf_degrees.get(tf_id, 0),
            tf_id,
            desc_optional(specificity),
            desc_optional(information_content),
            asc_optional(ngd_score),
            answer_id,
            indices.get(result, 0)
        )

    sorted_results = sorted(direct_results, key = direct_key) + \
                     sorted(inferred_results, key = inferred_key)

    stamp_rank_scores(sorted_results, ctx.config.scoring_method)
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


def make_xcrg_inferred_edge(
    ctx: RunContext,
    subject_id: CURIE,
    object_id: CURIE,
    original_qedge: QEdge,
    support_graph_ids: list[str],
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
                attribute_source = ctx.config.resource_id
            ),
            Attribute(
                attribute_type_id = "biolink:agent_type",
                value = "computational_model",
                attribute_source = ctx.config.resource_id
            ),
            Attribute(
                attribute_type_id = "biolink:support_graphs",
                value = cast(FastJsonValue, support_graph_ids), # TODO
                attribute_source = ctx.config.resource_id
            ),
        ],
        sources = [
            RetrievalSource(
                resource_id = ctx.config.resource_id,
                resource_role = "primary_knowledge_source"
            )
        ]
    )

    if not edge.qualifiers:
        edge.qualifiers = None

    return edge_id, edge


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
    trapi.copy_node(subject_id, retriever_nodes, final_nodes)
    trapi.copy_node(object_id, retriever_nodes, final_nodes)
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
    ctx: RunContext,
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

        trapi.copy_node(source_id, retriever_nodes, kg_nodes)
        trapi.copy_node(target_id, retriever_nodes, kg_nodes)

        inferred_edge_id, inferred_edge = make_xcrg_inferred_edge(
            ctx,
            source_id,
            target_id,
            original_qedge,
            [support_graph_id]
        )

        kg_edges[inferred_edge_id] = inferred_edge
        xcrg_bindings.append(EdgeBinding(id = inferred_edge_id, attributes = []))

    if xcrg_bindings:
        analysis = Analysis(
            resource_id = ctx.config.resource_id,
            edge_bindings = {
                original_qedge_id: xcrg_bindings,
            }
        )
        ngd.add_ngd_analysis_support_graph(
            ctx,
            analysis,
            kg_edges,
            kg_nodes,
            auxiliary_graphs,
            retriever_nodes,
            source_id,
            target_id
        )
        final_result.analyses = [analysis]
    else:
        final_result.analyses = []


def build_trapi_clean_response(ctx: RunContext, old_response: Response) -> Response:
    """Convert debug-shaped direct+2-hop results into one-hop TRAPI results."""
    old_kgraph = old_response.message.knowledge_graph or KnowledgeGraph.new()
    old_aux_graphs = old_response.message.auxiliary_graphs_dict

    new_qgraph = deepcopy(ctx.query_graph)
    new_kgraph = KnowledgeGraph.new()
    new_aux_graphs = AuxiliaryGraphsDict()

    new_results_by_pair = {}
    new_results = list[XCRGResult]()

    for result_index, result in enumerate(old_response.message.results_list):
        source_id = get_bound_node_curie(result, ctx.subject_qid)
        target_id = get_bound_node_curie(result, ctx.object_qid)
        if not source_id or not target_id:
            continue

        pair_key = (source_id, target_id)
        if pair_key not in new_results_by_pair and len(new_results) >= ctx.config.max_results:
            continue

        final_result = get_or_create_final_result(
            new_results_by_pair,
            new_results,
            ctx.subject_qid,
            ctx.object_qid,
            source_id,
            target_id,
        )

        if final_result.xcrg_first_score is None:
            for analysis in result.analyses:
                if score := analysis.score:
                    final_result.xcrg_first_score = score
            final_result.xcrg_first_index = result_index

        if is_two_hop_result(result):
            path_edge_ids: list[str] = [
                binding.id
                for qedge_id in ("e0", "e1")
                for binding in trapi.get_edge_bindings(result, qedge_id)
            ]
            if path_edge_ids:
                add_support_path_edges(
                    final_result,
                    path_edge_ids,
                )
        else:
            add_direct_evidence(
                final_result,
                trapi.get_edge_bindings(result, DIRECT_QEDGE_ID),
            )

    for final_result in new_results:
        finalize_clean_result_analyses(
            ctx,
            final_result,
            new_qgraph,
            old_kgraph.nodes,
            old_kgraph.edges,
            old_aux_graphs,
            new_kgraph.nodes,
            new_kgraph.edges,
            new_aux_graphs,
            ctx.query_edge_id,
            ctx.query_edge
        )

    new_results.sort(
        key = lambda it: (
            desc_optional(it.xcrg_first_score),
            it.xcrg_first_index or 0
        )
    )

    new_response = Response(
        schema_version = old_response.schema_version,
        biolink_version = old_response.biolink_version,
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

    stamp_rank_scores(
        new_response.message.results_list,
        ctx.config.scoring_method,
        ctx.config.resource_id
    )

    return new_response


def filter_inferred_response(
    response: Response,
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> Response:
    """Filter subclass and wrong-direction results from a two-hop Retriever response."""
    message = response.message

    edges = dict[EdgeID, Edge]()
    if message.knowledge_graph:
        edges = message.knowledge_graph.edges

    filtered_results = []
    for result in message.results_list:
        tf_id = get_bound_node_curie(result, TF_QNODE_ID)
        if tf_id == TP53_CURIE:
            continue
        if result_has_edge_predicate(result, edges, "biolink:subclass_of"):
            continue
        if not result_preserves_direction(result, edges, subject_qid, object_qid):
            continue
        filtered_results.append(result)

    filtered_message = deepcopy(message)
    filtered_message.results = filtered_results
    if not filtered_message.knowledge_graph:
        filtered_message.knowledge_graph = KnowledgeGraph.new()
    if not filtered_message.auxiliary_graphs:
        filtered_message.auxiliary_graphs = AuxiliaryGraphsDict()

    return Response(
        schema_version = response.schema_version,
        biolink_version = response.biolink_version,
        message = filtered_message
    )


async def run_direct_lookup(ctx: RunContext) -> Response:
    """Run a direct (one-hop) xCRG lookup."""
    return await retriever.run_sync_lookup(ctx, ctx.query)


async def run_inferred_lookup(ctx: RunContext) -> Response:
    """Run phase-one TF-mediated inferred xCRG lookup."""
    ctx.debug_dump_json("original_inferred_query", ctx.query)

    one_hop_query = build_one_hop_query(ctx)
    ctx.debug_dump_json("direct_lookup_query", one_hop_query)

    one_hop_response = await retriever.run_sync_lookup(ctx, one_hop_query)
    ctx.debug_dump_json("direct_raw_response", one_hop_response)

    filtered_direct_response = filter_direct_response(one_hop_response, ctx.subject_qid, ctx.object_qid)
    ctx.debug_dump_json("direct_filtered_response", filtered_direct_response)

    final_direction = trapi.get_qualifier_value(ctx.query_edge, "biolink:object_direction_qualifier")
    sign_templates = get_sign_templates(final_direction or "")
    tf_batches = chunk_values(ctx.tf_list, ctx.config.tf_batch_size)
    ctx.reporter.info(
        "Running inferred xCRG lookup with %s TFs across %s batches of up to %s IDs.",
        len(ctx.tf_list),
        len(tf_batches),
        ctx.config.tf_batch_size,
    )

    filtered_responses = []
    debug_summary = {
        "query_id": ctx.query_id,
        "final_direction": final_direction,
        "tf_count": len(ctx.tf_list),
        "batch_size": ctx.config.tf_batch_size,
        "batch_count": len(tf_batches),
        "direct_response": trapi.get_message_statistics(filtered_direct_response),
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
            two_hop_query = build_two_hop_query(ctx, tf_batch, first_dir, second_dir)
            ctx.debug_dump_json(f"template_{template_idx}_batch_{batch_idx}_query", two_hop_query)

            response = await retriever.run_sync_lookup(ctx, two_hop_query)
            ctx.debug_dump_json(f"template_{template_idx}_batch_{batch_idx}_raw_response", response)

            filtered_response = filter_inferred_response(response, ctx.subject_qid, ctx.object_qid)
            ctx.debug_dump_json(f"template_{template_idx}_batch_{batch_idx}_filtered_response", filtered_response)

            filtered_responses.append(filtered_response)
            template_summary["batches"].append(
                {
                    "batch_index": batch_idx,
                    "tf_ids": tf_batch,
                    "tf_count": len(tf_batch),
                    "raw_response": trapi.get_message_statistics(response),
                    "filtered_response": trapi.get_message_statistics(filtered_response),
                }
            )
        debug_summary["templates"].append(template_summary)

    merged_query_graph = build_combined_query_graph(ctx)

    qgraph = build_two_hop_query(
        ctx,
        ctx.tf_list,
        sign_templates[0][0],
        sign_templates[0][1],
    ).message.query_graph

    merged_inferred = merge_filtered_responses(
        ctx,
        filtered_responses,
        cast(QueryGraph, qgraph)
    )

    merged = merge_filtered_responses(
        ctx,
        [filtered_direct_response, merged_inferred],
        merged_query_graph
    )

    sort_xcrg_combined_results(ctx, merged)
    ctx.debug_dump_json("merged_debug_response", merged)

    final_response = build_trapi_clean_response(ctx, merged)
    debug_summary["merged_response"] = trapi.get_message_statistics(final_response)
    debug_summary["debug_run_dir"] = str(ctx.debug_ctx and ctx.debug_ctx.run_dir) # TODO

    ctx.debug_dump_json("inferred_debug_summary", debug_summary)
    ctx.debug_dump_json("final_response", final_response, level = DebugLevel.BASIC)

    return final_response


def validate_query(query: Query) -> KnowledgeType:
    """Raise an Error if the given query fails to adhere to a valid xCRG query shape."""
    qgraph = query.message.query_graph
    if not isinstance(qgraph, QueryGraph):
        raise ValueError("xCRG query requires a non-pathfinder query graph.")

    _, qedge = trapi.get_single_query_edge(query)

    if "biolink:affects" not in qedge.predicates_list:
        raise ValueError("xCRG query requires a biolink:affects predicate.")

    qnodes = qgraph.nodes

    subject_qnode = qnodes.get(qedge.subject)
    if not subject_qnode:
        raise ValueError("xCRG query edge requires a 'subject' node reference.")
    object_qnode = qnodes.get(qedge.object)
    if not object_qnode:
        raise ValueError("xCRG query edge requires an 'object' node reference.")

    knowledge_type = qedge.knowledge_type or "lookup"

    match knowledge_type: # default per TRAPI spec; subject to change
        # Validate a phase-one inferred xCRG query while preserving user direction.
        case "inferred":
            pinned_count = sum(1 for node in [subject_qnode, object_qnode] if node.ids)
            if pinned_count != 1:
                raise ValueError("xCRG inferred query requires exactly one pinned endpoint node.")

            if "biolink:ChemicalEntity" not in subject_qnode.categories_list:
                raise ValueError("xCRG inferred query requires one 'ChemicalEntity' endpoint.")
            if "biolink:Gene" not in object_qnode.categories_list:
                raise ValueError("xCRG inferred query requires one 'Gene' endpoint.")

            direction = trapi.get_qualifier_value(qedge, "biolink:object_direction_qualifier")
            if direction not in {"increased", "decreased"}:
                raise ValueError("xCRG inferred query direction must be 'increased' or 'decreased'.")

            valid_aspects = biolink.get_valid_aspect_qualifiers()
            aspect = trapi.get_qualifier_value(qedge, "biolink:object_aspect_qualifier")
            if aspect not in valid_aspects:
                raise ValueError(
                    f"Inferred xCRG query requires an 'object_aspect_qualifier' that is a "
                    f"descendant of {biolink.ASPECT_QUALIFIER_ROOT!r} "
                    f"(e.g. {', '.join(sorted(valid_aspects))}); but got {aspect!r}."
                )
        # Validate the direct one-hop xCRG query shape.
        case "lookup":
            pinned_ids = [qid for qid, qnode in qnodes.items() if qnode.ids]
            if len(pinned_ids) != 1:
                raise ValueError("xCRG direct lookup supports exactly one pinned query node.")
            pinned_node = qnodes[pinned_ids[0]]
            if "biolink:Gene" not in pinned_node.categories_list:
                raise ValueError("xCRG direct lookup requires the pinned node to be a 'Gene'.")

            unbound_ids = [qid for qid, qnode in qnodes.items() if not qnode.ids]
            if len(unbound_ids) != 1:
                raise ValueError("xCRG direct lookup supports exactly one unbound query node.")
            unbound_node = qnodes[unbound_ids[0]]
            if "biolink:ChemicalEntity" not in unbound_node.categories_list:
                raise ValueError("xCRG direct lookup requires the unbound node to be a 'ChemicalEntity'.")
        case _:
            raise ValueError("Invalid knowledge type; valid values are 'inferred' or 'lookup'.")

    return knowledge_type


def is_xcrg_mvp2_query(query: dict | Query) -> bool: # TODO: is_valid_query
    try:
        if isinstance(query, dict):
            query = Query.from_dict(query)
        validate_query(query)
        return True
    except Exception:
        return False


async def async_run_xcrg(
    message: dict,
    config: XCRGConfig,
    logger: logging.Logger | None = None,
    query_id: str | None = None,
) -> dict:
    """Run xCRG and return a complete TRAPI response."""

    reporter: Reporter
    if logger is None:
        reporter = LogReporter()
    else:
        reporter = LogReporter(logger)

    query = Query.from_dict(message)
    # TODO: Query.timeout will become available in TRAPI 2.0
    # query.timeout = query.timeout or config.timeout
    query.submitter = query.submitter or config.resource_id

    ctx = RunContext.new(
        query_id = query_id or uuid.uuid4().hex[:8],
        query = query,
        config = config,
        reporter = reporter
    )

    response: Response
    if validate_query(query) == "inferred":
        response = await run_inferred_lookup(ctx)
    else:
        response = await run_direct_lookup(ctx)

    return response.to_dict()


def run_xcrg(
    message: dict,
    config: XCRGConfig,
    logger: logging.Logger | None = None,
    query_id: str | None = None,
) -> dict:
    """Synchronous wrapper for callers that are not already running an event loop."""
    return asyncio.run(
        async_run_xcrg(
            message=message,
            config=config,
            logger=logger,
            query_id=query_id,
        )
    )
