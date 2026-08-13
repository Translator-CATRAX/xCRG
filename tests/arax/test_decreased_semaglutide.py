import pytest
from translator_tom import Response

import xcrg
from tests.utilities import (
    XCRG_Answer,
    assert_answer,
    find_genes_affected_by_chemical
)


@pytest.fixture(scope = "session")
def response(config: xcrg.XCRGConfig) -> Response:
    return find_genes_affected_by_chemical(config, "increased", "CHEBI:167574") # Semaglutide

@pytest.mark.parametrize(
    "test",
    [
        # NOTE: There are more tests for Semaglutide, but they do not currently return any results
        # TODO: This test appears to be erroneous or misconfigured
        XCRG_Answer("CHEBI:5931", "acceptable", fails_on_arax = True), # Insulin
        XCRG_Answer("NCBIGene:2740", "top_answer"), # GLP1R
    ]
)
def test_decreased_activity_or_abundance_of_mifepristone(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
