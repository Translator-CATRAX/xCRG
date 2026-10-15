from __future__ import annotations

from copy import deepcopy

from translator_tom import (
    CURIE,
    Message,
    QEdge,
    QEdgeConstraints,
    QNode,
    Query,
    QueryGraph,
    QueryParameters,
)

from xcrg import biolink, trapi
from .constants import DIRECT_QEDGE_ID, TF_QNODE_ID
from .context import Run_Context
from .models import Direction


def validate_query(query: Query):
    """Raise an Error if the given query fails to adhere to a valid xCRG query shape."""
    qgraph = query.message.query_graph
    if not qgraph: raise ValueError("xCRG query requires a query graph.")

    _, qedge = trapi.get_single_query_edge(qgraph)

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


def is_valid_query(query: Query) -> bool:
    """Return boolean result based on whether validate_query succeeds or not."""
    try:
        validate_query(query)
        return True
    except Exception as _:
        return False


def build_two_hop_query(
    ctx: Run_Context,
    tf_list: list[CURIE],
    first_direction: Direction,
    second_direction: Direction
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
                        constraints = QEdgeConstraints(
                            qualifiers = [{
                                "biolink:object_aspect_qualifier": "activity_or_abundance",
                                "biolink:object_direction_qualifier": first_direction.value
                            }]
                        )
                    ),
                    "e1": QEdge(
                        subject = TF_QNODE_ID,
                        object = ctx.object_qid,
                        predicates = ["biolink:affects"],
                        constraints = QEdgeConstraints(
                            qualifiers = [{
                                "biolink:object_aspect_qualifier": "activity_or_abundance",
                                "biolink:object_direction_qualifier": second_direction.value
                            }]
                        )
                    )
                }
            )
        ),
        parameters = QueryParameters(
            bypass_cache = ctx.query.get_parameters().bypass_cache
            # TODO: timeout = config.timeout
            # TODO: tiers = ctx.query.get_parameters().tiers or config.normalized_tiers()
        ),
        submitter = ctx.query.submitter or ctx.config.resource_id
    )


def build_one_hop_query(ctx: Run_Context) -> Query:
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
            )
        ),
        parameters = QueryParameters(
            bypass_cache = ctx.query.get_parameters().bypass_cache
            # TODO: timeout = config.timeout
            # TODO: tiers = ctx.query.get_parameters().tiers or config.normalized_tiers()
        ),
        submitter = ctx.query.submitter
    )
