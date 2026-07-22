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


def test_retriever_roundtrip(
    project_dir: Path,
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

    config = xcrg.XCRGConfig(
        retriever_url = "https://retriever.ci.transltr.io/query", # TODO: Hardcoded URL
        ngd_db_path = ngd_db_file,
        curie_to_pmids_db_path = curie_to_pmids_db_file,
        tf_path = project_dir / "src/xcrg/resources/transcription_factors.json"
    )

    response = xcrg.run_xcrg(query.to_dict(), config)
    response = Response.from_dict(response)

    out_file = project_dir / "test_response.json"
    with open(out_file, "w") as f:
        f.write(response.to_json(as_str = True))

    assert True # TODO: assert something useful
