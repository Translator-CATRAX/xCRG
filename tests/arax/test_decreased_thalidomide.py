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
    return find_genes_affected_by_chemical(config, "decreased", "CHEBI:74947") # Thalidomide


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("NCBIGene:5004", "acceptable", fails_on_arax = True), # ORM1
        XCRG_Answer("NCBIGene:57167", "acceptable"), # SALL4
        XCRG_Answer("NCBIGene:5005", "acceptable", fails_on_arax = True), # ORM2
    ]
)
def test_decreased_activity_or_abundance_of_smarce1(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
