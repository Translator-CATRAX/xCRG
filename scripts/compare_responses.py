#! /usr/bin/env python3
"""Generate an analysis comparing response data from two debug runs."""

import csv
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from translator_tom import Analysis, CURIE, QueryGraph, Response


OUTPUT_DIR = Path("output")
DEBUG_DIR = OUTPUT_DIR / "debug"


@dataclass
class ResultMetrics:
    rank           : int
    id             : CURIE
    name           : str
    trapi_score    : float
    ngd_score      : float
    num_edges      : int
    num_xcrg_edges : int


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


def get_metrics_for_response(response: Response) -> dict[CURIE, ResultMetrics]:
    msg = response.message

    qgraph = cast(QueryGraph, msg.query_graph)
    qedge_id = next(iter(qgraph.edges))

    assert (kg := msg.knowledge_graph)

    metrics = dict[CURIE, ResultMetrics]()
    for i, result in enumerate(response.message.results_list):
        rank = i + 1

        subject_id = result.node_bindings["sn"][0].id
        subject_name = kg.nodes[subject_id].name

        # object_id  = result.node_bindings["on"][0].id

        analysis: Analysis
        for it in result.analyses:
            assert isinstance(it, Analysis)
            if it.scoring_method == "xcrg-result-filtering-v2": # TODO: hardcoded scoring_method
                analysis = it
                break
        else:
            print("No xCRG analysis found in the response")
            sys.exit(1)

        num_edges = len(analysis.edge_bindings[qedge_id])

        trapi_score = analysis.score or float("inf") # TODO

        num_xcrg_edges = 0
        for eb in analysis.edge_bindings[qedge_id]:
            if eb.id.startswith("xcrg"):
                xcrg_graph_id: str = ""
                for attribute in kg.edges[eb.id].attributes_list:
                    if xcrg_graph_id:
                        break
                    if attribute.attribute_type_id == "biolink:support_graphs":
                        attr_val = attribute.value
                        assert isinstance(attr_val, list)
                        for graph_id in attr_val:
                            if graph_id.startswith("xcrg"):
                                xcrg_graph_id = graph_id
                                break
                        else:
                            print("No xCRG support graph found in edge")
                            sys.exit(1)
                xcrg_graph = msg.auxiliary_graphs_dict[xcrg_graph_id]
                num_xcrg_edges = len(xcrg_graph.edges)

        ngd_score = float("inf") # No NGD data if database was not used
        for sgraph_id in analysis.support_graphs_list:
            sgraph = msg.auxiliary_graphs_dict[sgraph_id]
            for attribute in sgraph.attributes:
                if attribute.original_attribute_name == "normalized_google_distance":
                    if isinstance(attribute.value, float):
                        ngd_score = float(attribute.value)

        metrics[subject_id] = ResultMetrics(
            rank = rank,
            id = subject_id,
            name = subject_name or "", # TODO
            trapi_score = trapi_score,
            ngd_score = ngd_score,
            num_edges = num_edges,
            num_xcrg_edges = num_xcrg_edges
        )

    return metrics


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

    response01 = find_and_deserialize_response(old_debug_dir)
    metrics01  = get_metrics_for_response(response01)

    response02 = find_and_deserialize_response(new_debug_dir)
    metrics02  = get_metrics_for_response(response02)

    output_dir = script_file.parent.parent / "output"
    output_dir.mkdir(exist_ok = True)

    csv_file = output_dir / "compare_response.tsv"

    fields: list[str] = [
        "new_rank",
        "old_rank",
        "rank_change",
        "id",
        "name",
        "num_edges",
        "num_xcrg_edges",
    ]

    with open(csv_file, "w") as f:
        writer = csv.DictWriter(f, fields, delimiter = '\t')
        writer.writeheader()

        for subject_id in metrics01:
            old_result = metrics01[subject_id]
            new_result = metrics02[subject_id]

            dt_rank: str
            match new_result.rank - old_result.rank:
                case x if x > 0:
                    dt_rank = f"+{x}"
                case x if x < 0:
                    dt_rank = f"-{x}"
                case _:
                    dt_rank = "---" # TODO

            # TODO: sanity check, but is this necessary?
            assert old_result.num_edges == new_result.num_edges, "Number of edges is the same"
            assert old_result.num_xcrg_edges == new_result.num_xcrg_edges, "Number of xCRG edges is the same"

            writer.writerow({
                "new_rank": new_result.rank,
                "old_rank": old_result.rank,
                "rank_change": dt_rank,
                "id": old_result.id,
                "name": old_result.name,
                "num_edges": old_result.num_edges,
                "num_xcrg_edges": old_result.num_xcrg_edges,
            })


if __name__ == "__main__":
    main()
