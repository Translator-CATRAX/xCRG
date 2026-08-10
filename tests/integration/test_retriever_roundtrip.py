"""Test roundtrip xCRG query to Retriever and back."""
from translator_tom import Response

import xcrg
from integration_utilities import (
    assert_is_answer,
    get_query_for_chemicals_affecting_gene,
)


# This test can be performed locally *without* the db files.
#
# But for a real simulation of results, provide the db files using pytest cli args.
# You can find the full list of cli args documented in tests/conftest.py.
def test_retriever_roundtrip(config: xcrg.XCRGConfig):
    query = get_query_for_chemicals_affecting_gene("decreased", "NCBIGene:5742") # PTGS1

    response = xcrg.run_xcrg(query.to_dict(), config)
    response = Response.from_dict(response)

    assert_is_answer("CHEBI:46195", response) # Acetaminophen
    assert_is_answer("CHEBI:5855",  response) # Ibuprofen
