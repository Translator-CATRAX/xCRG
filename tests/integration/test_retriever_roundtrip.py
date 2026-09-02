"""Test roundtrip to Retriever with a basic query."""
import pytest
from translator_tom import Response

import xcrg
from tests.utilities import (
    XCRG_Answer,
    assert_answer,
    find_chemicals_affecting_gene,
)


@pytest.fixture(scope = "session")
def response(config: xcrg.XCRGConfig) -> Response:
    return find_chemicals_affecting_gene(config, "decreased", "NCBIGene:5742") # PTGS1


# This test can be performed locally *without* the db files.
#
# For a real simulation of results, provide the db files using pytest cli args.
# You can find the full list of cli args documented in tests/conftest.py.
@pytest.mark.parametrize(
    "answer",
    [
        XCRG_Answer("CHEBI:46195", "Acetaminophen", "exists"),
        XCRG_Answer("CHEBI:5855", "Ibuprofen", "exists"),
    ]
)
def test_decreased_activity_or_abundance_of_ace(response: Response, answer: XCRG_Answer):
    assert_answer(response, answer)
