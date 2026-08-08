#! /usr/bin/env python3
"""Generate an analysis comparing response data from two debug runs."""

import csv
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from translator_tom import (
    CURIE,
    Query,
    QueryGraph,
    Response,
    Result,
)

# TODO: importing xcrg really breaks type-checking + linting
#  How can we improve this?
from xcrg import trapi


OUTPUT_DIR = Path("output")
DEBUG_DIR = OUTPUT_DIR / "debug"


@dataclass(frozen = True, slots = False)
class RankedResult:
    rank: int
    curie: CURIE
    name: str
    result: Result


def log(*values: object) -> None:
    print(*values)


def find_and_deserialize_response(debug_dir: Path) -> Response:
    if not debug_dir or not debug_dir.exists():
        log(f"debug_dir is invalid: {debug_dir}")
        sys.exit(1)
    # Be flexible in case the filename ever changes
    matches = sorted(debug_dir.glob("**/*response.json"))
    json_file = matches[-1] # We want the last response
    try:
        with open(json_file, "rb") as f:
            return Response.from_json(f.read())
    except Exception:
        log(f"Failed to read Response from JSON file: {json_file}")
        sys.exit(1)


def get_ranked_results(response: Response) -> dict[CURIE, RankedResult]:
    assert(kgraph := response.message.knowledge_graph)
    _, qedge = trapi.get_single_query_edge(Query(message = response.message))
    answer_qid = trapi.get_answer_qid(
        cast(QueryGraph, response.message.query_graph),
        qedge.subject,
        qedge.object
    )
    results = dict[CURIE, RankedResult]()
    for rank, result in enumerate(response.message.results_list, start = 1):
        qnode = result.node_bindings[answer_qid][0]
        curie = qnode.id
        name = kgraph.nodes[curie].name or "???"
        results[curie] = RankedResult(rank, curie, name, result)
    return results


# def get_data_for_result(response: Response, result: Result) -> ResultData:
#     message = response.message
#     qgraph = cast(QueryGraph, message.query_graph)
#     assert (kgraph := message.knowledge_graph)
#
#     analysis: Analysis
#     for analysis in result.analyses:
#         assert isinstance(analysis, Analysis)
#         if analysis.scoring_method == "xcrg-result-filtering-v2": # TODO: hardcoded scoring_method
#             analysis = analysis
#             break
#         else:
#             print("No xCRG analysis found in the response")
#             sys.exit(1)
#
#     _, qedge = xcrg.trapi.get_single_query_edge(Query(message = message))
#     answer_qnode_id = xcrg.ranking.get_answer_qnode_id(qgraph, qedge.subject, qedge.object)
#
#     curie = result.node_bindings[answer_qnode_id][0].id
#     name = kgraph.nodes[curie].name
#
#     ngd_score = float("inf") # No NGD data if database was not used
#     for sgraph_id in analysis.support_graphs_list:
#         sgraph = message.auxiliary_graphs_dict[sgraph_id]
#         for attribute in sgraph.attributes:
#             if attribute.original_attribute_name == "normalized_google_distance":
#                 if isinstance(attribute.value, float):
#                     ngd_score = float(attribute.value)
#
#     ctx = xcrg.context.RunContext(
#         query_id = "",
#         query = Query(message = message),
#         config = xcrg.config.XCRGConfig(
#             retriever_url = ""
#         ),
#         reporter = xcrg.reporting.StubReporter()
#     )
#
#     answer_qnode_id = xcrg.ranking.get_answer_qnode_id(qgraph, ctx.subject_qid, ctx.object_qid)
#
#     use_category_specificity = False
#     if qnode := qgraph.nodes.get(answer_qnode_id):
#         use_category_specificity = any(xcrg.biolink.is_chemical_category(ctx.reporter, c) for c in qnode.categories_list)
#
#     metrics = xcrg.ranking.get_result_statistics(
#         ctx,
#         message,
#         result,
#         answer_qnode_id,
#         use_category_specificity
#     )
#
#     num_publications   = sum(x.num_publications for x in metrics.qualified_statements)
#     num_studies        = sum(x.num_studies      for x in metrics.qualified_statements)
#     sum_evidence_count = sum(x.evidence_count   for x in metrics.qualified_statements)
#
#     xcrg_score = xcrg.ranking.calculate_score_for_result(metrics, None) # ngd_score)
#
#     return ResultData(
#         curie = curie,
#         name = name,
#         specificity = metrics.specificity,
#         information_content = metrics.information_content,
#         ngd_score = ngd_score,
#         num_edges = metrics.num_edges,
#         num_xcrg_edges = metrics.num_xcrg_edges,
#         num_publications = num_publications,
#         num_studies = num_studies,
#         sum_evidence_count = sum_evidence_count,
#         xcrg_score = xcrg_score,
#         rank = 0 # This needs to be updated later
#     )


def main():
    script_file = Path(sys.argv[0])

    if len(sys.argv) < 2:
        log("Generate an analysis comparing response data from two debug runs.")
        log("")
        log(f"usage: {script_file.name} <old_debug_dir> [new_debug_dir]")
        log("")
        log("positional arguments:")
        log("  old_debug_dir (required): pinned data to compare with.")
        log("  new_debug_dir (optional): new data; defaults to last run.")
        sys.exit(1)

    old_debug_dir = Path(sys.argv[1])

    new_debug_dir: Path
    if len(sys.argv) > 2:
        new_debug_dir = Path(sys.argv[2])
    else:
        debug_dirs = sorted(DEBUG_DIR.iterdir())
        if not debug_dirs:
            log(f"No debug data could be found in default directory: {DEBUG_DIR}")
        new_debug_dir = debug_dirs[-1]

    if old_debug_dir == new_debug_dir:
        log("old_debug_dir and new_debug_dir cannot be the same")
        sys.exit(1)

    # # We need to rank by the new xcrg score
    # new_response = find_and_deserialize_response(new_debug_dir)
    # new_results_list= list[ResultData]()
    # for new_result in new_response.message.results_list:
    #     new_results_list.append(get_data_for_result(new_response, new_result))
    # new_results_list.sort(key = lambda x: x.xcrg_score, reverse = True)
    # # We need to update the rank after sorting
    # for rank, new_result in enumerate(new_results_list, start = 1):
    #     new_result.rank = rank
    # new_results = {x.curie: x for x in new_results_list}
    #
    # # Maintain the original ranking
    # old_response = find_and_deserialize_response(old_debug_dir)
    # old_results = dict[CURIE, ResultData]()
    # for rank, new_result in enumerate(old_response.message.results_list, start = 1):
    #     data = get_data_for_result(old_response, new_result)
    #     data.rank = rank
    #     old_results[data.curie] = data

    new_response = find_and_deserialize_response(new_debug_dir)
    new_results = get_ranked_results(new_response)

    old_response = find_and_deserialize_response(old_debug_dir)
    old_results = get_ranked_results(old_response)

    output_dir = script_file.parent.parent / "output"
    output_dir.mkdir(exist_ok = True)

    csv_file = output_dir / "compare_response.tsv"

    fields: list[str] = [
        "new_rank",
        "old_rank",
        "rank_change",
        "id",
        "name",
    ]

    with open(csv_file, "w") as f:
        writer = csv.DictWriter(f, fields, delimiter = '\t')
        writer.writeheader()

        for curie, new_result in new_results.items():
            old_rank = "---"
            dt_rank = "---"

            if old_result := old_results.get(curie):
                old_rank = str(old_result.rank)
                match old_result.rank - new_result.rank:
                    case x if x > 0:
                        dt_rank = f"+{x}"
                    case x if x < 0:
                        dt_rank = f"{x}"

            writer.writerow({
                "new_rank": new_result.rank,
                "old_rank": old_rank,
                "rank_change": dt_rank,
                "id": new_result.curie,
                "name": new_result.name,
            })


if __name__ == "__main__":
    main()
