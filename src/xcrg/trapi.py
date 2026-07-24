from dataclasses import dataclass

from translator_tom import (
    Biolink,
    KnowledgeGraph,
    QEdge,
    QEdgeID,
    Query,
    QueryGraph,
    Response,
)

from .utilities import require


@dataclass
class SummaryCount:
    result_count : int
    node_count   : int
    edge_count   : int

    @staticmethod
    def zero():
        return SummaryCount(0, 0, 0)


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


def summarize_response_counts(entity: Query | Response) -> SummaryCount:
    """Return compact counts for a TRAPI response."""
    message = entity.message
    knowledge_graph = message.knowledge_graph or KnowledgeGraph.new()
    return SummaryCount(
        result_count = len(message.results_list),
        node_count = len(knowledge_graph.nodes),
        edge_count = len(knowledge_graph.edges),
    )
