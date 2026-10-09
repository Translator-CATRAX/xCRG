"""Hodgepodge collection of classes, functions, etc. used for development tools, scripts, tests, etc."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from translator_tom import (
    CURIE,
    KnowledgeType,
    Message,
    QEdge,
    QEdgeConstraints,
    QNode,
    QNodeID,
    Query,
    QueryGraph,
    Response,
)

from .config import XCRGConfig
from .models import Direction
from .reporting import Reporter
from .runner import run_xcrg


@dataclass(frozen = True)
class Query_Args:
    direction      : Direction
    chem_gene_id   : CURIE
    knowledge_type : KnowledgeType = field(default = "inferred")
    query_id       : str | None    = field(default_factory = lambda: uuid.uuid4().hex)


def make_xcrg_query(
    nodes: dict[QNodeID, QNode],
    direction: Direction,
    knowledge_type: KnowledgeType
) -> Query:
    return Query(
        message = Message(
            query_graph = QueryGraph(
                edges = {
                    "t_edge": QEdge(
                        knowledge_type = knowledge_type,
                        subject = "sn",
                        predicates = ["biolink:affects"],
                        object = "on",
                        constraints = QEdgeConstraints(
                            qualifiers = [{
                                "biolink:object_aspect_qualifier": "activity_or_abundance",
                                "biolink:object_direction_qualifier": direction
                            }]
                        )
                    )
                },
                nodes = nodes
            )
        )
    )


def find_chemicals_affecting_gene(
    config: XCRGConfig,
    args: Query_Args,
    reporter: Reporter | None = None,
) -> Response:
    nodes = {
        "sn": QNode(categories=["biolink:ChemicalEntity"]),
        "on": QNode(categories=["biolink:Gene"], ids=[args.chem_gene_id])
    }
    query = make_xcrg_query(nodes, args.direction, args.knowledge_type)
    response = run_xcrg(query.to_dict(), config, logger = reporter, query_id = args.query_id)
    return Response.from_dict(response)


def find_genes_affected_by_chemical(
    config: XCRGConfig,
    args: Query_Args,
    reporter: Reporter | None = None,
) -> Response:
    nodes = {
        "sn": QNode(categories=["biolink:ChemicalEntity"], ids=[args.chem_gene_id]),
        "on": QNode(categories=["biolink:Gene"])
    }
    query = make_xcrg_query(nodes, args.direction, args.knowledge_type)
    response = run_xcrg(query.to_dict(), config, logger = reporter, query_id = args.query_id)
    return Response.from_dict(response)
