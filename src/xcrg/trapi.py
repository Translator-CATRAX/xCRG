from copy import deepcopy

from translator_tom import (
    CURIE,
    Biolink,
    EdgeBinding,
    Node,
    QEdge,
    QEdgeID,
    QNodeID,
    QueryGraph,
    Result,
)

from xcrg.utilities import XCRGResult


def get_single_query_edge(qgraph: QueryGraph | None) -> tuple[QEdgeID, QEdge]:
    """Return the single query edge for xCRG queries."""
    if qgraph is None:
        raise ValueError("Query graph is required.")
    qedges = qgraph.edges
    if not qedges:
        raise ValueError("xCRG queries are currently required to have only one query edge.")
    qedge_id = next(iter(qedges))
    return qedge_id, qedges[qedge_id]


def get_qualifier_value(edge: QEdge, qualifier_type_id: Biolink.Qualifier) -> str | None:
    """Return a qualifier value from the first qualifier set, if present."""
    constraints = edge.constraints
    if not constraints: return None
    for qualifier in constraints.qualifiers_list:
        for type_id, value in qualifier.items():
            if type_id == qualifier_type_id:
                return value
    return None


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
    for analysis in result.analyses_list:
        binding = analysis.edge_bindings_dict.get(qedge_id)
        if not binding: continue
        for edge_id in binding.ids:
            if edge_id in seen:
                continue
            seen.add(edge_id)
            copied_binding = deepcopy(binding)
            bindings.append(copied_binding)
    return bindings


def get_bound_node_curie(result: Result | XCRGResult, qid: QNodeID) -> CURIE | None:
    """Return the first node binding id for the given qnode."""
    binding = result.node_bindings.get(qid)
    if not binding: return None
    return binding.ids[0]


def result_edge_binding_keys(result: Result) -> set[str]:
    """Return qedge ids bound by any analysis in the result."""
    keys = set()
    for analysis in result.analyses_list:
        keys.update(analysis.edge_bindings_dict.keys())
    return keys


def is_two_hop_result(result: Result) -> bool:
    """Return True for TF-mediated inferred results."""
    keys = result_edge_binding_keys(result)
    return "e0" in keys and "e1" in keys # TODO: hardcoded


def is_two_hop_query(qgraph: QueryGraph) -> bool:
    edges = qgraph.edges_dict
    return "e0" in edges and "e1" in edges # TODO: hardcoded


def get_answer_qid(
    query_graph: QueryGraph,
    subject_qid: QNodeID,
    object_qid: QNodeID,
) -> QNodeID:
    """Return the unpinned endpoint qnode whose bindings are the answer list."""
    for qid in (subject_qid, object_qid):
        if (qnode := query_graph.nodes.get(qid)) and not qnode.ids:
            return qid
    return object_qid
