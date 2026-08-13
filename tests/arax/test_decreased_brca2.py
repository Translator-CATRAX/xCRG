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
    return find_chemicals_affecting_gene(config, "decreased", "NCBIGene:675") # BRCA2


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("UNII:9X5A2QIA7C", "acceptable", fails_on_arax = True), # PARP inhibitor 2X-121

        XCRG_Answer("CHEBI:16731", "bad_but_forgivable"), # Cinnamaldehyde
        XCRG_Answer("CHEBI:16842", "bad_but_forgivable", fails_on_arax = True), # Formaldehyde
        XCRG_Answer("PUBCHEM.COMPOUND:14423521", "bad_but_forgivable"), # Ursolic aldehyde

        XCRG_Answer("CHEBI:31355", "never_show", fails_on_arax = True),  # Carboplatin
        XCRG_Answer("CHEBI:176844", "never_show"),  # niraparib
        XCRG_Answer("CHEBI:83766", "never_show"),  # olaparib
        XCRG_Answer("CHEBI:16842", "never_show"),  # formaldehyde
        XCRG_Answer("CHEBI:62880", "never_show"),  # veliparib
        XCRG_Answer("CHEBI:134689", "never_show", fails_on_arax = True),  # rucaparib
        XCRG_Answer("CHEBI:231344", "never_show"),  # talazoparib
        XCRG_Answer("CHEBI:27899", "never_show"),  # Cisplatin
        XCRG_Answer("CHEBI:167900", "never_show", fails_on_arax = True),  # PJ34
        XCRG_Answer("CHEBI:41774", "never_show"),  # Tamoxifen

    ]
)
def test_decreased_activity_or_abundance_of_brca2(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
