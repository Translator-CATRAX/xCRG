from __future__ import annotations

from copy import deepcopy
from enum import Enum

from translator_tom import (
    CURIE,
    AuxiliaryGraphsDict,
    KnowledgeGraph,
    Message,
    QEdge,
    QNode,
    Qualifier,
    QualifierConstraint,
    Query,
    QueryGraph,
)

from .constants import TF_QNODE_ID, DIRECT_QEDGE_ID
from .context import RunContext


class Direction(Enum):
    INCREASED = "increased"
    DECREASED = "decreased"


Direction_Template = tuple[Direction, Direction]


# Sign-compatible two-hop templates for desired final direction
DIRECTION_TEMPLATES: dict[Direction, tuple[Direction_Template, Direction_Template]] = {
    Direction.INCREASED: (
        (Direction.INCREASED, Direction.INCREASED),
        (Direction.DECREASED, Direction.DECREASED)
    ),
    Direction.DECREASED: (
        (Direction.INCREASED, Direction.DECREASED),
        (Direction.DECREASED, Direction.INCREASED)
    )
}


def build_two_hop_query(
    ctx: RunContext,
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
                        qualifier_constraints = [
                            QualifierConstraint(
                                qualifier_set = [
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_aspect_qualifier",
                                        qualifier_value = "activity_or_abundance",
                                    ),
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_direction_qualifier",
                                        qualifier_value = first_direction.value,
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
                                        qualifier_value = second_direction.value,
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
