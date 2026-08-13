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
    return find_chemicals_affecting_gene(config, "increased", "NCBIGene:154") # ADRB2


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("CHEBI:64064", "top_answer"), # salmeterol
        XCRG_Answer("CHEBI:5147", "top_answer"), # formoterol
        XCRG_Answer("CHEBI:9449", "top_answer"), # terbutaline
        XCRG_Answer("CHEBI:2549", "top_answer"), # Albuterol

        XCRG_Answer("CHEBI:8499", "never_show", fails_on_arax = True), # Propranolol
    ]
)
def test_increased_activity_or_abundance_of_adrb2(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
