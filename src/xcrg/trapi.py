from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from translator_tom import (
    Analysis,
    Biolink,
    CURIE,
    EdgeBinding,
    KnowledgeGraph,
    Node,
    PathfinderQueryGraph,
    QEdge,
    QEdgeID,
    QNodeID,
    Query,
    QueryGraph,
    Response,
    Result,
)

from xcrg.utilities import make_stable_id


@dataclass
class MessageStatistics:
    result_count : int
    node_count   : int
    edge_count   : int

    @staticmethod
    def zero():
        return MessageStatistics(0, 0, 0)


def get_single_query_edge(qgraph: QueryGraph | PathfinderQueryGraph | None) -> tuple[QEdgeID, QEdge]:
    """Return the single query edge for xCRG queries."""
    if qgraph is None:
        raise ValueError("Query graph is required.")
    if isinstance(qgraph, PathfinderQueryGraph):
        raise ValueError("PathfinderQueryGraph is not supported.")
    qedges = qgraph.edges
    if len(qedges) != 1:
        raise ValueError("xCRG queries are currently required to have only one query edge.")
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


def get_message_statistics(entity: Query | Response) -> MessageStatistics:
    """Return compact counts for a TRAPI response."""
    message = entity.message
    knowledge_graph = message.knowledge_graph or KnowledgeGraph.new()
    return MessageStatistics(
        result_count = len(message.results_list),
        node_count = len(knowledge_graph.nodes),
        edge_count = len(knowledge_graph.edges),
    )


def copy_node(
    node_id: CURIE | None,
    old_nodes: dict[CURIE, Node],
    new_nodes: dict[CURIE, Node],
) -> None:
    """Copy a Retriever-provided KG node verbatim into the final KG."""
    if node_id and node_id in old_nodes and node_id not in new_nodes:
        new_nodes[node_id] = deepcopy(old_nodes[node_id])


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


def get_bound_node_curie(result: Result, qid: QNodeID) -> CURIE | None:
    """Return the first node binding id for the given qnode."""
    bindings = result.node_bindings.get(qid) or []
    if not bindings:
        return None
    return bindings[0].id


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
    return "e0" in keys and "e1" in keys # TODO: hardcoded


def is_two_hop_query(qgraph: QueryGraph) -> bool:
    return "e0" in qgraph.edges and "e1" in qgraph.edges # TODO: hardcoded


def get_answer_qid(
    query_graph: QueryGraph,
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> QNodeID:
    """Return the unpinned endpoint qnode whose bindings are the answer list."""
    for qid in (subject_qid, object_qid):
        if qnode := query_graph.nodes.get(qid):
            if not qnode.ids:
                return qid
    return object_qid


def make_stable_id_for_query(prefix: str, query: Query) -> str:
    qgraph = cast(QueryGraph, query.message.query_graph)

    if is_two_hop_query(qgraph):
        edge0 = qgraph.edges["e0"]
        edge1 = qgraph.edges["e1"]

        sn = qgraph.nodes[edge0.subject]
        tf = qgraph.nodes[edge1.subject]
        on = qgraph.nodes[edge1.object]

        return make_stable_id(prefix, {
            "sn_ids": sn.ids,
            "tf_ids": tf.ids,
            "on_ids": on.ids
        })
    else:
        _, edge = get_single_query_edge(qgraph)

        sn = qgraph.nodes[edge.subject]
        on = qgraph.nodes[edge.object]

        return make_stable_id(prefix, {
            "sn_ids": sn.ids,
            "on_ids": on.ids
        })
