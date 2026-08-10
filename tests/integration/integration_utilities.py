from math import ceil
from typing import Literal, cast

from translator_tom import (
    CURIE,
    Message,
    QEdge,
    QNode,
    Qualifier,
    QualifierConstraint,
    Query,
    QueryGraph,
    Response,
)

from xcrg import trapi


def get_query_for_chemicals_affecting_gene(
    direction: Literal["increased", "decreased"],
    gene_id: CURIE
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
                nodes = {
                    "on": QNode(
                        categories = ["biolink:Gene"],
                        ids = [gene_id],
                    ),
                    "sn": QNode(
                        categories = ["biolink:ChemicalEntity"],
                    )
                }
            )
        )
    )


def get_query_for_genes_affected_by_chemical(
    direction: Literal["increased", "decreased"],
    chemical_id: CURIE
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
                nodes = {
                    "on": QNode(
                        categories = ["biolink:Gene"],
                    ),
                    "sn": QNode(
                        categories = ["biolink:ChemicalEntity"],
                        ids = [chemical_id],
                    )
                }
            )
        )
    )


def get_answer_curies(response: Response) -> list[CURIE]:
    qgraph = cast(QueryGraph, response.message.query_graph)
    _, edge = trapi.get_single_query_edge(response.message.query_graph)

    answer_qid = trapi.get_answer_qid(qgraph, edge.subject, edge.object)

    return [
        binding.id
        for result in response.message.results_list
        for binding in result.node_bindings[answer_qid]
    ]


def assert_is_answer(curie: CURIE, response: Response):
    assert curie in get_answer_curies(response), f"CURIE should be an answer: {curie}"


def assert_is_top_answer(curie: CURIE, response: Response):
    x = max(30, ceil(len(response.message.results_list) / 10))
    assert curie in get_answer_curies(response)[0:x], f"CURIE should be in top {x} answers: {curie}"


def assert_is_acceptable_answer(curie: CURIE, response: Response):
    x = ceil(len(response.message.results_list) / 2)
    assert curie in get_answer_curies(response)[0:x], f"CURIE should be in top 50% of answers: {curie}"


def assert_bad_but_forgivable_answer(curie: CURIE, response: Response):
    x = ceil(len(response.message.results_list) / 2)
    assert curie not in get_answer_curies(response)[0:x], f"CURIE should not be in top 50% of answers: {curie}"


def assert_is_never_show_answer(curie: CURIE, response: Response):
    assert curie not in get_answer_curies(response), f"CURIE should never appear in answers: {curie}"
