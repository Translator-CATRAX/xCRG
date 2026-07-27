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
    QEdge,
    QEdgeID,
    Query,
    QueryGraph,
    Response,
    Result,
)


@dataclass
class MessageStatistics:
    result_count : int
    node_count   : int
    edge_count   : int

    @staticmethod
    def zero():
        return MessageStatistics(0, 0, 0)


def get_single_query_edge(query: Query) -> tuple[QEdgeID, QEdge]:
    """Return the single query edge for xCRG queries."""
    qedges = cast(QueryGraph, query.message.query_graph).edges
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
    nodes: dict[CURIE, Node],
    final_nodes: dict[CURIE, Node],
) -> None:
    """Copy a Retriever-provided KG node verbatim into the final KG."""
    if node_id and node_id in nodes and node_id not in final_nodes:
        final_nodes[node_id] = deepcopy(nodes[node_id])


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
