from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

from translator_tom import (
    Analysis,
    Attribute,
    AuxiliaryGraph,
    AuxGraphID,
    CURIE,
    Message,
    QNodeID,
    QueryGraph,
    Response,
    Result
)

from . import DebugLevel, biolink, trapi
from .context import RunContext
from .utilities import as_type


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
    num_edges            : int
    num_xcrg_edges       : int
    qualified_statements : list[QualifiedStatement]
  # ngd_score            : float | None


@dataclass(frozen = True, slots = False)
class ScoredResult:
    result: Result
    stats: ResultStatistics
    score: float


def get_xcrg_graph(attributes: list[Attribute]) -> AuxGraphID:
    for attribute in attributes:
        if attribute.attribute_type_id == "biolink:support_graphs":
            graph_ids = as_type(attribute.value, list) or []
            # TODO: Is there ever going to be more than one graph?
            for graph_id in graph_ids:
                if graph_id.startswith("xcrg"):  # TODO: hardcoded
                    return graph_id
    raise Exception("The xCRG support graph could not be found.") # TODO


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
    result: Result,
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

    qualified_statements = list[QualifiedStatement]()

    # Find the edge bindings for the main graph
    bindings = [
        binding
        for analysis in result.analyses
        if isinstance(analysis, Analysis)
        for bindings in analysis.edge_bindings.values()
        for binding in bindings
    ]

    # Collect the qualified statements on the main graph
    num_edges = len(bindings)
    for binding in bindings:
        attributes = kgraph.edges[binding.id].attributes_list
        statement = get_qualified_stmt(attributes)
        qualified_statements.append(statement)

    # Find the xCRG support graph (if one exists)
    xgraph: AuxiliaryGraph | None = None
    for analysis in result.analyses:
        if not isinstance(analysis, Analysis): continue
        if xgraph: break
        for graph_id in analysis.support_graphs_list:
            if graph_id.startswith("xcrg"):
                xgraph = message.auxiliary_graphs_dict[graph_id]
                break

    # Collect the qualified statements from the xcrg support graph
    num_xcrg_edges = 0
    if xgraph:
        num_xcrg_edges = len(xgraph.edges)
        for edge_id in xgraph.edges:
            attributes = kgraph.edges[edge_id].attributes_list
            statement = get_qualified_stmt(attributes)
            qualified_statements.append(statement)

    # Figure out the NGD for the result
    # curie_a: CURIE | None
    # curie_b: CURIE | None
    # if trapi.is_two_hop_result(result):
    #     curie_a = trapi.get_bound_node_curie(result, answer_qid)
    #     curie_b = trapi.get_bound_node_curie(result, TF_QNODE_ID)
    # else:
    #     curie_a = trapi.get_bound_node_curie(result, ctx.subject_qid)
    #     curie_b = trapi.get_bound_node_curie(result, ctx.object_qid)
    # ngd_score = ngd.get_ngd_score(ctx, curie_a, curie_b)

    return ResultStatistics(
        answer_id = answer_id,
        answer_name = answer_name,
        specificity = specificity,
        information_content = information_content,
        num_edges = num_edges,
        num_xcrg_edges = num_xcrg_edges,
        qualified_statements = qualified_statements,
        # ngd_score = ngd_score
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

    factors = [
        # ngd_factor,
        # info_factor,
        # specificity_factor
    ]

    return total_score # * (sum(factors) / len(factors))


def sort_xcrg_combined_results(ctx: RunContext, response: Response) -> None:
    """Sort direct results first, then TF-mediated results by the xCRG policy."""
    message = response.message
    qgraph = cast(QueryGraph, message.query_graph)

    answer_qid = ctx.get_answer_qid()

    use_category_specificity = False
    if qnode := qgraph.nodes.get(answer_qid):
        use_category_specificity = any(biolink.is_chemical_category(ctx, c) for c in qnode.categories_list)

    best_results = dict[CURIE, ScoredResult]()
    for result in message.results_list:
        stats = get_result_statistics(
            ctx,
            message,
            result,
            answer_qid,
            use_category_specificity
        )
        score = calculate_score_for_result(stats)
        if (prev := best_results.get(stats.answer_id)) and prev.score > score:
            continue
        best_results[stats.answer_id] = ScoredResult(result, stats, score)

    sorted_results = sorted(best_results.values(), key = lambda x: x.score, reverse = True)
    ctx.debug_dump_json(
        label = "xcrg_scored_results",
        payload = [
            {
                "score": x.score,
                "stats": x.stats,
            }
            for x in sorted_results
        ],
        level = DebugLevel.BASIC
    )

    final_results = [x.result for x in sorted_results]

    trapi.stamp_rank_scores(final_results, ctx.config.scoring_method)
    message.results = final_results
