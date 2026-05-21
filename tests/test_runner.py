"""Smoke tests for the reusable xCRG package."""

import json
import sqlite3

from xcrg import XCRGConfig, is_xcrg_mvp2_query
from xcrg.runner import (
    build_trapi_clean_response,
    load_tf_list,
    merge_filtered_responses,
)


def make_config() -> XCRGConfig:
    return XCRGConfig(
        retriever_url="https://example.org/query",
        ngd_db_path=None,
    )


def make_curie_to_pmids_db(tmp_path, rows: dict[str, list[int]]) -> str:
    db_path = tmp_path / "curie_to_pmids.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE curie_to_pmids (curie TEXT PRIMARY KEY, pmids TEXT)")
    connection.executemany(
        "INSERT INTO curie_to_pmids VALUES (?, ?)",
        [(curie, json.dumps(pmids)) for curie, pmids in rows.items()],
    )
    connection.commit()
    connection.close()
    return str(db_path)


def make_inferred_query() -> dict:
    return {
        "message": {
            "query_graph": {
                "nodes": {
                    "chem": {
                        "ids": ["CHEBI:1"],
                        "categories": ["biolink:ChemicalEntity"],
                    },
                    "gene": {"categories": ["biolink:Gene"]},
                },
                "edges": {
                    "e0": {
                        "subject": "chem",
                        "object": "gene",
                        "predicates": ["biolink:affects"],
                        "knowledge_type": "inferred",
                    }
                },
            }
        }
    }


def primary_source() -> list[dict]:
    return [
        {
            "resource_id": "infores:test",
            "resource_role": "primary_knowledge_source",
        }
    ]


def test_is_xcrg_mvp2_query_detects_supported_shape():
    query = {
        "message": {
            "query_graph": {
                "nodes": {
                    "chem": {"categories": ["biolink:ChemicalEntity"]},
                    "gene": {
                        "ids": ["NCBIGene:6323"],
                        "categories": ["biolink:Gene"],
                    },
                },
                "edges": {
                    "e0": {
                        "subject": "chem",
                        "object": "gene",
                        "predicates": ["biolink:affects"],
                        "knowledge_type": "inferred",
                        "qualifier_constraints": [
                            {
                                "qualifier_set": [
                                    {
                                        "qualifier_type_id": "biolink:object_aspect_qualifier",
                                        "qualifier_value": "activity_or_abundance",
                                    },
                                    {
                                        "qualifier_type_id": "biolink:object_direction_qualifier",
                                        "qualifier_value": "decreased",
                                    },
                                ]
                            }
                        ],
                    }
                },
            }
        }
    }

    assert is_xcrg_mvp2_query(query)


def test_load_tf_list_uses_bundled_default_resource():
    tf_list = load_tf_list(make_config())

    assert "NCBIGene:7157" in tf_list
    assert len(tf_list) > 100


def test_merge_filtered_responses_keeps_rich_retriever_metadata():
    config = make_config()
    sparse_response = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "NCBIGene:1991": {
                        "attributes": [],
                        "categories": [],
                    }
                },
                "edges": {
                    "edge1": {
                        "subject": "CHEBI:17688",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1991",
                        "attributes": [],
                    }
                },
            },
            "results": [],
        }
    }
    rich_response = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "NCBIGene:1991": {
                        "name": "ELANE",
                        "attributes": [
                            {
                                "attribute_type_id": "biolink:Attribute",
                                "original_attribute_name": "symbol",
                                "value": "ELANE",
                            }
                        ],
                        "categories": ["biolink:Gene", "biolink:Protein"],
                    }
                },
                "edges": {
                    "edge1": {
                        "subject": "CHEBI:17688",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1991",
                        "attributes": [
                            {
                                "attribute_type_id": "biolink:knowledge_level",
                                "value": "knowledge_assertion",
                            }
                        ],
                        "sources": primary_source(),
                        "qualifiers": [
                            {
                                "qualifier_type_id": "biolink:object_direction_qualifier",
                                "qualifier_value": "increased",
                            }
                        ],
                    }
                },
            },
            "results": [],
        }
    }

    merged = merge_filtered_responses(
        [rich_response, sparse_response],
        {"nodes": {}, "edges": {}},
        config,
    )

    merged_node = merged["message"]["knowledge_graph"]["nodes"]["NCBIGene:1991"]
    merged_edge = merged["message"]["knowledge_graph"]["edges"]["edge1"]
    assert merged_node == rich_response["message"]["knowledge_graph"]["nodes"][
        "NCBIGene:1991"
    ]
    assert merged_edge == rich_response["message"]["knowledge_graph"]["edges"][
        "edge1"
    ]


def test_clean_response_adds_binding_attributes_and_biolink_creation_date():
    config = make_config()
    original_message = make_inferred_query()
    combined_message = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "CHEBI:1": {"categories": ["biolink:ChemicalEntity"]},
                    "NCBIGene:1": {"categories": ["biolink:Gene"]},
                    "NCBIGene:tf": {"categories": ["biolink:Gene"]},
                },
                "edges": {
                    "direct1": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                    "path0": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:tf",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                    "path1": {
                        "subject": "NCBIGene:tf",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                },
            },
            "results": [
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {"edge_bindings": {"direct": [{"id": "direct1"}]}}
                    ],
                },
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "tf": [{"id": "NCBIGene:tf"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {
                            "edge_bindings": {
                                "e0": [{"id": "path0"}],
                                "e1": [{"id": "path1"}],
                            }
                        }
                    ],
                },
            ],
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    missing_node_attrs = [
        binding
        for result in response["message"]["results"]
        for bindings in result["node_bindings"].values()
        for binding in bindings
        if "attributes" not in binding
    ]
    missing_edge_attrs = [
        binding
        for result in response["message"]["results"]
        for analysis in result["analyses"]
        for bindings in analysis["edge_bindings"].values()
        for binding in bindings
        if "attributes" not in binding
    ]
    datetime_attrs = [
        attr
        for edge in response["message"]["knowledge_graph"]["edges"].values()
        for attr in edge.get("attributes", [])
        if attr.get("attribute_type_id") == "metatype:Datetime"
    ]
    creation_attrs = [
        attr
        for edge in response["message"]["knowledge_graph"]["edges"].values()
        for attr in edge.get("attributes", [])
        if attr.get("attribute_type_id") == "biolink:creation_date"
    ]
    auxiliary_graphs = response["message"].get("auxiliary_graphs") or {}
    auxiliary_graphs_without_attributes = [
        aux_id
        for aux_id, aux_graph in auxiliary_graphs.items()
        if aux_graph.get("attributes") != []
    ]

    assert missing_node_attrs == []
    assert missing_edge_attrs == []
    assert datetime_attrs == []
    assert creation_attrs
    assert auxiliary_graphs_without_attributes == []


def test_clean_response_adds_ngd_publications_from_curie_to_pmids(tmp_path):
    config = XCRGConfig(
        retriever_url="https://example.org/query",
        ngd_db_path=None,
        curie_to_pmids_db_path=make_curie_to_pmids_db(
            tmp_path,
            {
                "CHEBI:1": [1001, 1002, 1003],
                "NCBIGene:1": [1002, 1003, 1004],
            },
        ),
    )
    original_message = make_inferred_query()
    combined_message = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "CHEBI:1": {"categories": ["biolink:ChemicalEntity"]},
                    "NCBIGene:1": {"categories": ["biolink:Gene"]},
                },
                "edges": {
                    "direct1": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                },
            },
            "results": [
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {"edge_bindings": {"direct": [{"id": "direct1"}]}}
                    ],
                },
            ],
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    ngd_edges = [
        edge
        for edge_id, edge in response["message"]["knowledge_graph"]["edges"].items()
        if edge_id.startswith("xcrg_ngd_edge_")
    ]
    publication_attrs = [
        attr
        for edge in ngd_edges
        for attr in edge.get("attributes", [])
        if attr.get("attribute_type_id") == "biolink:publications"
    ]

    assert len(ngd_edges) == 1
    assert publication_attrs == [
        {
            "attribute_source": "infores:arax",
            "attribute_type_id": "biolink:publications",
            "original_attribute_name": "publications",
            "value_type_id": "EDAM-DATA:1187",
            "value": ["PMID:1002", "PMID:1003"],
        }
    ]


def test_clean_response_preserves_retriever_nodes_verbatim_and_prunes_unused():
    config = make_config()
    original_message = make_inferred_query()
    chem_node = {
        "name": "Chem One",
        "categories": ["biolink:SmallMolecule"],
        "attributes": [
            {
                "attribute_type_id": "biolink:information_content",
                "value": 12.3,
            }
        ],
        "extra_field_from_retriever": {"keep": True},
    }
    gene_node = {
        "name": "Gene One",
        "categories": ["biolink:Gene"],
        "attributes": [
            {
                "attribute_type_id": "biolink:symbol",
                "value": "GENE1",
            }
        ],
    }
    tf_node = {
        "name": "TF One",
        "categories": ["biolink:Gene"],
        "attributes": [
            {
                "attribute_type_id": "biolink:symbol",
                "value": "TF1",
            }
        ],
    }
    combined_message = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "CHEBI:1": chem_node,
                    "NCBIGene:1": gene_node,
                    "NCBIGene:tf": tf_node,
                    "NCBIGene:unused": {
                        "name": None,
                        "categories": [],
                        "attributes": [],
                    },
                },
                "edges": {
                    "path0": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:tf",
                        "attributes": [{"attribute_type_id": "biolink:foo"}],
                        "sources": primary_source(),
                    },
                    "path1": {
                        "subject": "NCBIGene:tf",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [{"attribute_type_id": "biolink:bar"}],
                        "sources": primary_source(),
                    },
                },
            },
            "results": [
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "tf": [{"id": "NCBIGene:tf"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {
                            "edge_bindings": {
                                "e0": [{"id": "path0"}],
                                "e1": [{"id": "path1"}],
                            }
                        }
                    ],
                }
            ],
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    final_nodes = response["message"]["knowledge_graph"]["nodes"]
    assert final_nodes["CHEBI:1"] == chem_node
    assert final_nodes["NCBIGene:1"] == gene_node
    assert final_nodes["NCBIGene:tf"] == tf_node
    assert "NCBIGene:unused" not in final_nodes


def test_clean_response_uses_only_pinned_query_metadata_for_missing_endpoint():
    config = make_config()
    original_message = make_inferred_query()
    original_message["message"]["query_graph"]["nodes"]["gene"]["ids"] = ["NCBIGene:1"]
    combined_message = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "CHEBI:1": {
                        "name": "Chem One",
                        "categories": ["biolink:SmallMolecule"],
                        "attributes": [],
                    }
                },
                "edges": {
                    "direct1": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": primary_source(),
                    }
                },
            },
            "results": [
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {"edge_bindings": {"direct": [{"id": "direct1"}]}}
                    ],
                }
            ],
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    final_nodes = response["message"]["knowledge_graph"]["nodes"]
    final_edges = response["message"]["knowledge_graph"]["edges"]
    assert final_nodes["NCBIGene:1"] == {
        "categories": ["biolink:Gene"],
        "attributes": [],
    }
    assert "direct1" in final_edges


def test_clean_response_does_not_drop_retriever_node_with_empty_metadata():
    config = make_config()
    original_message = make_inferred_query()
    empty_tf_node = {
        "name": None,
        "categories": [],
        "attributes": [],
    }
    combined_message = {
        "message": {
            "knowledge_graph": {
                "nodes": {
                    "CHEBI:1": {
                        "name": "Chem One",
                        "categories": ["biolink:SmallMolecule"],
                        "attributes": [],
                    },
                    "NCBIGene:tf": empty_tf_node,
                    "NCBIGene:1": {
                        "name": "Gene One",
                        "categories": ["biolink:Gene"],
                        "attributes": [],
                    },
                },
                "edges": {
                    "path0": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:tf",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                    "path1": {
                        "subject": "NCBIGene:tf",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": primary_source(),
                    },
                },
            },
            "results": [
                {
                    "node_bindings": {
                        "chem": [{"id": "CHEBI:1"}],
                        "tf": [{"id": "NCBIGene:tf"}],
                        "gene": [{"id": "NCBIGene:1"}],
                    },
                    "analyses": [
                        {
                            "edge_bindings": {
                                "e0": [{"id": "path0"}],
                                "e1": [{"id": "path1"}],
                            }
                        }
                    ],
                }
            ],
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    final_nodes = response["message"]["knowledge_graph"]["nodes"]
    inferred_bindings = [
        binding
        for result in response["message"]["results"]
        for analysis in result["analyses"]
        for bindings in analysis["edge_bindings"].values()
        for binding in bindings
        if binding["id"].startswith("xcrg_inferred_edge_")
    ]

    assert final_nodes["NCBIGene:tf"] == empty_tf_node
    assert inferred_bindings


def test_clean_response_limits_to_configured_top_result_count():
    config = XCRGConfig(
        retriever_url="https://example.org/query",
        ngd_db_path=None,
        max_results=2,
    )
    original_message = make_inferred_query()
    nodes = {"CHEBI:1": {"categories": ["biolink:ChemicalEntity"]}}
    edges = {}
    results = []
    for index in range(3):
        gene_id = f"NCBIGene:{index}"
        edge_id = f"direct{index}"
        nodes[gene_id] = {"categories": ["biolink:Gene"]}
        edges[edge_id] = {
            "subject": "CHEBI:1",
            "predicate": "biolink:affects",
            "object": gene_id,
            "attributes": [],
            "sources": primary_source(),
        }
        results.append(
            {
                "node_bindings": {
                    "chem": [{"id": "CHEBI:1"}],
                    "gene": [{"id": gene_id}],
                },
                "analyses": [
                    {
                        "edge_bindings": {"direct": [{"id": edge_id}]},
                        "score": 1.0 - (index * 0.1),
                    }
                ],
            }
        )
    combined_message = {
        "message": {
            "knowledge_graph": {"nodes": nodes, "edges": edges},
            "results": results,
        }
    }

    response = build_trapi_clean_response(
        original_message,
        combined_message,
        "chem",
        "gene",
        config,
    )

    final_results = response["message"]["results"]
    final_nodes = response["message"]["knowledge_graph"]["nodes"]
    answer_ids = [
        result["node_bindings"]["gene"][0]["id"]
        for result in final_results
    ]

    assert len(final_results) == 2
    assert answer_ids == ["NCBIGene:0", "NCBIGene:1"]
    assert "NCBIGene:2" not in final_nodes
