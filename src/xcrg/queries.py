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

from .constants import DIRECT_QEDGE_ID, TF_QNODE_ID
from .context import Run_Context
from .models import Direction


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
