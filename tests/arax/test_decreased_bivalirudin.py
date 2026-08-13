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
    return find_genes_affected_by_chemical(config, "decreased", "CHEBI:59173") # Bivalirudin


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("UMLS:C0040018", "top_answer", fails_on_arax = True), # Thrombin
        XCRG_Answer("NCBIGene:4353", "top_answer"), # MPO
        XCRG_Answer("NCBIGene:2147", "top_answer"), # F2
        # BUG: https://github.com/NCATSTranslator/Tests/issues/83
        XCRG_Answer("CHEMBL.TARGET:CHEMBL204", "top_answer", fails_on_arax = True), # UNIPROTKB#P00734
    ]
)
def test_decreased_activity_or_abundance_of_bivalirudin(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
