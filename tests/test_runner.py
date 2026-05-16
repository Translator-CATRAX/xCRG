"""Smoke tests for the reusable xCRG package."""

from xcrg import XCRGConfig, is_xcrg_mvp2_query
from xcrg.runner import build_trapi_clean_response, load_tf_list


def make_config() -> XCRGConfig:
    return XCRGConfig(
        retriever_url="https://example.org/query",
        ngd_db_path=None,
    )


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


def test_clean_response_adds_binding_attributes_and_biolink_creation_date():
    config = make_config()
    original_message = {
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
                        "sources": [
                            {
                                "resource_id": "infores:test",
                                "resource_role": "primary_knowledge_source",
                            }
                        ],
                    },
                    "path0": {
                        "subject": "CHEBI:1",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:tf",
                        "attributes": [],
                        "sources": [
                            {
                                "resource_id": "infores:test",
                                "resource_role": "primary_knowledge_source",
                            }
                        ],
                    },
                    "path1": {
                        "subject": "NCBIGene:tf",
                        "predicate": "biolink:affects",
                        "object": "NCBIGene:1",
                        "attributes": [],
                        "sources": [
                            {
                                "resource_id": "infores:test",
                                "resource_role": "primary_knowledge_source",
                            }
                        ],
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

    assert missing_node_attrs == []
    assert missing_edge_attrs == []
    assert datetime_attrs == []
    assert creation_attrs
