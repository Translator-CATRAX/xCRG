from dataclasses import dataclass
from math import ceil
from typing import Literal, cast

from translator_tom import (
    CURIE,
    Message,
    QEdge,
    QNode,
    QNodeID,
    Qualifier,
    QualifierConstraint,
    Query,
    QueryGraph,
    Response,
)

from xcrg import XCRGConfig, run_xcrg, trapi


AnswerExpectation = Literal[
    "exists",
    "top_answer",
    "acceptable",
    "bad_but_forgivable",
    "never_show",
]


@dataclass
class XCRG_Answer:
    curie: CURIE
    expectation: AnswerExpectation
    fails_on_arax: bool = False

    def get_pytest_id(self) -> str:
        status = " (fails on ARAX)" if self.fails_on_arax else ""
        return f"{self.curie} should be {self.expectation}{status}"


def make_xcrg_query(
    nodes: dict[QNodeID, QNode],
    direction: Literal["increased", "decreased"]
) -> Query:
    return Query(
        message = Message(
            query_graph = QueryGraph(
                edges = {
                    "t_edge": QEdge(
                        knowledge_type = "inferred",
                        subject = "sn",
                        predicates = ["biolink:affects"],
                        object = "on",
                        qualifier_constraints = [
                            QualifierConstraint(
                                qualifier_set = [
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_aspect_qualifier",
                                        qualifier_value = "activity_or_abundance"
                                    ),
                                    Qualifier(
                                        qualifier_type_id = "biolink:object_direction_qualifier",
                                        qualifier_value = direction
                                    )
                                ]
                            )
                        ]
                    )
                },
                nodes = nodes
            )
        )
    )


def find_chemicals_affecting_gene(
    config: XCRGConfig,
    direction: Literal["increased", "decreased"],
    gene_id: CURIE,
    query_id: str | None = None
) -> Response:
    nodes = {
        "sn": QNode(categories=["biolink:ChemicalEntity"], ids=None),
        "on": QNode(categories=["biolink:Gene"], ids=[gene_id])
    }
    query = make_xcrg_query(nodes, direction)
    response = run_xcrg(query.to_dict(), config, query_id = query_id)
    return Response.from_dict(response)


def find_genes_affected_by_chemical(
    config: XCRGConfig,
    direction: Literal["increased", "decreased"],
    chemical_id: CURIE,
    query_id: str | None = None
) -> Response:
    nodes = {
        "sn": QNode(categories=["biolink:ChemicalEntity"], ids=[chemical_id]),
        "on": QNode(categories=["biolink:Gene"], ids=None)
    }
    query = make_xcrg_query(nodes, direction)
    response = run_xcrg(query.to_dict(), config, query_id = query_id)
    return Response.from_dict(response)


def assert_answer(response: Response, answer: XCRG_Answer):
    qgraph = cast(QueryGraph, response.message.query_graph)
    _, edge = trapi.get_single_query_edge(qgraph)
    answer_qid = trapi.get_answer_qid(qgraph, edge.subject, edge.object)

    answers = [
        binding.id
        for result in response.message.results_list
        for binding in result.node_bindings[answer_qid]
    ]

    match answer.expectation:
        case "exists":
            assert answer.curie in answers, f"Answer should exist in results: {answer.curie}"
        case "top_answer":
            n = max(30, ceil(len(answers) / 10))
            assert answer.curie in answers[0:n], f"Answer should be in top {n} results: {answer.curie}"
        case "acceptable":
            n = ceil(len(answers) / 2)
            assert answer.curie in answers[0:n], f"Answer should be in top 50% of results: {answer.curie}"
        case "bad_but_forgivable":
            n = ceil(len(answers) / 2)
            assert answer.curie not in answers[0:n], f"Answer should not be in top 50% of results: {answer.curie}"
        case "never_show":
            assert answer.curie not in answers, f"Answer should never appear in results: {answer.curie}"
        case _:
            raise ValueError(f"Invalid AnswerExpectation: {answer.expectation}")
