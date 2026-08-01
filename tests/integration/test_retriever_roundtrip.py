from pathlib import Path

from translator_tom import (
    Message,
    QEdge,
    QNode,
    Qualifier,
    QualifierConstraint,
    Query,
    QueryGraph,
    Response
)

import xcrg


# Test roundtrip xCRG query to Retriever and back.
# This test can be performed locally *without* the db files.
#
# But for a real simulation of results, provide the db files using pytest cli args.
# You can find the full list of cli args documented in tests/conftest.py.
def test_retriever_roundtrip(
    project_dir: Path,
    retriever_url: str,
    debug_level: xcrg.DebugLevel,
    ngd_db_file: Path | None,
    curie_to_pmids_db_file : Path | None
):
    query = Query(
        message = Message(
            query_graph = QueryGraph(
                nodes = {
                    "on": QNode(
                        categories = ["biolink:Gene"],
                        ids = ["NCBIGene:5742"],
                    ),
                    "sn": QNode(
                        categories = ["biolink:ChemicalEntity"],
                    )
                },
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
                                        qualifier_value = "decreased"
                                    )
                                ]
                            )
                        ]
                    )
                }
            )
        )
    )

    # TODO: At some point, we may want to have test utilities
    debug_dir: Path | None = None
    if debug_level != xcrg.DebugLevel.NONE:
        assert (debug_dir := project_dir / "output" / "debug")
        debug_dir.mkdir(parents = True, exist_ok = True)

    config = xcrg.XCRGConfig(
        retriever_url = retriever_url,
        ngd_db_path = ngd_db_file,
        curie_to_pmids_db_path = curie_to_pmids_db_file,
        debug_dir = debug_dir,
        debug_level = debug_level
    )

    response = xcrg.run_xcrg(query.to_dict(), config)
    response = Response.from_dict(response)

    # These obvious treatment options should appear in results
    expected_curies: set[str] = {
        "CHEBI:46195", # Acetaminophen
        "CHEBI:5855"   # Ibuprofen
    }

    actual_curies = {
        node_binding.id
        for result in response.message.results_list
        for node_binding in result.node_bindings["sn"] # chemical entities
        if node_binding.id in expected_curies
    }

    assert actual_curies == expected_curies
