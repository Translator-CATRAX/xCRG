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

# TODO: importing xcrg thiw way breaks type-checking + linting; how can we improve?
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
