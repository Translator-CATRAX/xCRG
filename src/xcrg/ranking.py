from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

from translator_tom import (
    Attribute,
    CURIE,
    Message,
    QNodeID,
    QueryGraph,
)

from . import DebugLevel, biolink, trapi
from .context import RunContext
from .ngd import get_ngd_score
from .utilities import XCRGResult, as_type


@dataclass(frozen = True, slots = False)
class QualifiedStatement:
    num_publications : int
    num_studies      : int
    evidence_count   : int
    knowledge_level  : str          # KnowledgeLevelEnum
    agent_type       : str | None   # AgentTypeEnum
    confidence_score : float | None


@dataclass(frozen = True, slots = False)
class ResultStatistics:
    answer_id            : CURIE
    answer_name          : str
    specificity          : int
    information_content  : int
    num_direct_edges     : int
    num_xcrg_edges       : int
    ngd_score            : float | None
    qualified_statements : list[QualifiedStatement]


@dataclass(frozen = True, slots = False)
class ScoredResult:
    result: XCRGResult
    stats: ResultStatistics
    score: float


def get_qualified_stmt(attributes: list[Attribute]) -> QualifiedStatement:
    num_publications = 0
    num_studies = 0
    evidence_count = 0
    knowledge_level: str = "not_provided"
    agent_type: str | None = None
    confidence_score: float | None = None

    for attribute in attributes:
        match attribute.attribute_type_id:
            case "biolink:publications":
                if publications := as_type(attribute.value, list):
                    num_publications = len(publications)
            case "biolink:has_supporting_studies":
                # TODO: Does this attribute value have a canonical structure defined somewhere?
                if obj := as_type(attribute.value, dict):
                    for key in obj:
                        num_studies = len(obj[key].get("has_study_results") or [])
            case "biolink:evidence_count":
                evidence_count = as_type(attribute.value, int) or 0
            case "biolink:knowledge_level":
                knowledge_level = as_type(attribute.value, str) or "not_provided"
            case "biolink:agent_type":
                agent_type = as_type(attribute.value, str)
            case "biolink:has_confidence_score":
                confidence_score = as_type(attribute.value, float)

    return QualifiedStatement(
        num_publications = num_publications,
        num_studies = num_studies,
        evidence_count = evidence_count,
        knowledge_level = knowledge_level,
        agent_type = agent_type,
        confidence_score = confidence_score
    )


def get_result_statistics(
    ctx: RunContext,
    message: Message,
    result: XCRGResult,
    answer_qid: QNodeID,
    use_category_specificity: bool,
) -> ResultStatistics:
    """Return sort metrics for the answer node bound by a result."""
    assert (kgraph := message.knowledge_graph)

    if not (answer_id := trapi.get_bound_node_curie(result, answer_qid)):
        raise Exception(f"Failed to find CURIE for answer QNodeID: {answer_qid}")
    answer_node = kgraph.nodes[answer_id]
    answer_name = answer_node.name or "" # TODO

    specificity = (
        biolink.get_node_category_specificity(ctx, answer_node)
        if use_category_specificity
        else 0
    )

    attributes: list[Attribute] = []
    if answer_node:
        attributes = answer_node.attributes

    values: list[int] = [0]
    for attribute in attributes:
        if attribute.attribute_type_id != "biolink:information_content":
            continue
        raw_value = attribute.value
        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in raw_values:
            try:
                values.append(int(value)) # TODO
            except (TypeError, ValueError):
                continue
    information_content: int = max(values)

    num_direct_edges = len(result.xcrg_direct_binding_ids)
    num_xcrg_edges = len(result.xcrg_support_edge_ids)

    qualified_statements = list[QualifiedStatement]()

    for edge_id in result.xcrg_support_edge_ids:
        attributes = kgraph.edges[edge_id].attributes_list
        statement = get_qualified_stmt(attributes)
        qualified_statements.append(statement)

    for edge_id in result.xcrg_direct_binding_ids:
        attributes = kgraph.edges[edge_id].attributes_list
        statement = get_qualified_stmt(attributes)
        qualified_statements.append(statement)

    ngd_score = get_ngd_score(
        ctx,
        result.node_bindings[ctx.subject_qid][0].id,
        result.node_bindings[ctx.object_qid][0].id
    )

    return ResultStatistics(
        answer_id = answer_id,
        answer_name = answer_name,
        specificity = specificity,
        information_content = information_content,
        num_direct_edges = num_direct_edges,
        num_xcrg_edges = num_xcrg_edges,
        qualified_statements = qualified_statements,
        ngd_score = ngd_score
    )


def calculate_score_for_result(statistics: ResultStatistics) -> float:
    total_score: float = 0

    for stmt in statistics.qualified_statements:
        score: float = 0

        agent_factor: float
        match stmt.agent_type:
            case "manual_agent":        agent_factor = 2
            case "automated_agent":     agent_factor = 1.5
            case "computational_model": agent_factor = 1.5
            case "text_mining_agent":   agent_factor = 1
            case _:                     agent_factor = 1

        knowledge_factor: float
        match stmt.knowledge_level:
            case "knowledge_assertion":     knowledge_factor = 2
            case "logical_entailment":      knowledge_factor = 1.5
            case "prediction":              knowledge_factor = 1.5
            case "statistical_association": knowledge_factor = 1
            case "text_co_occurrence":      knowledge_factor = 1
            case "observation":             knowledge_factor = 1
            case _:                         knowledge_factor = 1

        # For now, just having a confidence score is enough to boost the score
        confidence_factor: float
        if stmt.confidence_score:
            confidence_factor = 1.5
        else:
            confidence_factor = 1

        factors = [
            agent_factor,
            knowledge_factor,
            confidence_factor
        ]

        score += math.log2(stmt.num_studies + 1)      * 1.5
        score += math.log2(stmt.num_publications + 1) * 1.25
        score += math.log2(stmt.evidence_count + 1)   * 1
        score *= (sum(factors) / len(factors))

        total_score += score

    # ngd_factor = (statistics.ngd_score or 0) + 1
    # info_factor = ((statistics.information_content or 0) / 100) + 1 # TODO
    # specificity_factor = statistics.specificity / 4 # TODO
    #
    # factors = [
    #     ngd_factor,
    #     info_factor,
    #     specificity_factor
    # ]
    #
    # return total_score # * (sum(factors) / len(factors))

    return total_score


def rank_results(ctx: RunContext, message: Message, results: list[XCRGResult]) -> list[XCRGResult]:
    """Score, sort, rank, and limit results in the response."""
    qgraph = cast(QueryGraph, message.query_graph)

    answer_qid = ctx.get_answer_qid()

    use_category_specificity = False
    if qnode := qgraph.nodes.get(answer_qid):
        use_category_specificity = any(biolink.is_chemical_category(ctx, c) for c in qnode.categories_list)

    scored_results = list[ScoredResult]()
    for result in results:
        stats = get_result_statistics(
            ctx,
            message,
            result,
            answer_qid,
            use_category_specificity
        )
        score = calculate_score_for_result(stats)
        scored_result = ScoredResult(result, stats, score)
        scored_results.append(scored_result)
        result.ngd_score = stats.ngd_score

    sorted_results = sorted(scored_results, key = lambda x: x.score, reverse = True)

    ctx.debug_dump_json(
        label = "xcrg_scored_results",
        payload = [
            {
                "rank": i,
                "score": r.score,
                "stats": r.stats,
            }
            for i, r in enumerate(sorted_results, start = 1)
        ],
        level = DebugLevel.BASIC
    )

    final_results = [x.result for x in sorted_results]
    final_results = final_results[0:ctx.num_max_results]

    return final_results
