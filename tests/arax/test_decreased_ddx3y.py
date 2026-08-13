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
    return find_chemicals_affecting_gene(config, "decreased", "NCBIGene:8653") # DDX3Y


@pytest.mark.parametrize(
    "answer",
    [
        XCRG_Answer("UMLS:C0311474", "never_show"),                        # dna double stranded
        XCRG_Answer("UMLS:C1328819", "never_show"),                        # Small molecule
        XCRG_Answer("CHEBI:28748",   "acceptable", fails_on_arax = True),  # Doxorubicin
        XCRG_Answer("UMLS:C4079590", "acceptable", fails_on_arax = True),  # RK-33

    ]
)
def test_decreased_activity_or_abundance_of_ddx3y(response: Response, answer: XCRG_Answer):
    assert_answer(response, answer)
