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
    return find_chemicals_affecting_gene(config, "decreased", "NCBIGene:6605") # SMARCE1


@pytest.mark.parametrize(
    "test",
    [
        XCRG_Answer("CHEBI:75998", "top_answer", fails_on_arax = True), # trametinib
        XCRG_Answer("CHEBI:72564", "top_answer", fails_on_arax = True), # temozolomide
        XCRG_Answer("UNII:DPT0O3T46P", "top_answer", fails_on_arax = True), # pembrolizumab
        XCRG_Answer("CHEBI:39867", "top_answer", fails_on_arax = True), # valproic acid

        XCRG_Answer("CHEBI:90943", "acceptable", fails_on_arax = True), # osimertinib
        XCRG_Answer("CHEBI:114785", "acceptable", fails_on_arax = True), # erlotinib
        XCRG_Answer("CHEBI:61390", "acceptable", fails_on_arax = True), # afatinib
        XCRG_Answer("UMLS:C4085970", "acceptable", fails_on_arax = True), # amivantamab-vmjw
        XCRG_Answer("HGNC.FAMILY:3410", "acceptable", fails_on_arax = True), # histone-lysine methyltransferases
        XCRG_Answer("CHEBI:49668", "acceptable", fails_on_arax = True), # gefitinib
        XCRG_Answer("CHEBI:132268", "acceptable", fails_on_arax = True), # dacomitinib

        XCRG_Answer("PUBCHEM.COMPOUND:54671203", "bad_but_forgivable", fails_on_arax = True), # doxycycline
    ]
)
def test_decreased_activity_or_abundance_of_smarce1(response: Response, test: XCRG_Answer):
    assert_answer(response, test)
