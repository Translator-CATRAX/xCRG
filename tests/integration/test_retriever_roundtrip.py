"""Test roundtrip to Retriever with a basic query."""
import pytest
from translator_tom import Response

from tests.utilities import XCRG_Answer, assert_answer
from xcrg.config import XCRGConfig
from xcrg.dev import Query_Args, find_chemicals_affecting_gene
from xcrg.models import Direction


@pytest.fixture(scope = "session")
def response(config: XCRGConfig) -> Response:
    return find_chemicals_affecting_gene(config, Query_Args(Direction.DECREASED, "NCBIGene:5742")) # PTGS1


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
