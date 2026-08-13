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
    return find_chemicals_affecting_gene(config, "decreased", "NCBIGene:1636") # ACE


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("CHEBI:8713", "top_answer"), # Quinapril
        XCRG_Answer("UNII:R43D2573WO", "top_answer", fails_on_arax = True), # Fosinopril
        XCRG_Answer("CHEBI:6960", "top_answer"), # Moexipril
        XCRG_Answer("CHEBI:3380", "top_answer"), # Captopril
        XCRG_Answer("CHEBI:3011", "top_answer"), # Benazapril
        XCRG_Answer("CHEBI:4784", "top_answer"), # Enalapril
        XCRG_Answer("CHEBI:8774", "top_answer"), # Ramipril
        XCRG_Answer("CHEBI:8024", "top_answer"), # Perindopril
        XCRG_Answer("CHEBI:43755", "top_answer"), # Lisinopril
        XCRG_Answer("CHEBI:9649", "top_answer"), # Trandolapril
    ]
)
def test_decreased_activity_or_abundance_of_ace(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
