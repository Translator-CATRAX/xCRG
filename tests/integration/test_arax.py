"""Run various ARAX integration tests locally to verify results."""
from translator_tom import Response

import xcrg
from integration_utilities import (
    assert_is_never_show_answer,
    assert_is_top_answer,
    get_query_for_chemicals_affecting_gene,
    get_query_for_genes_affected_by_chemical
)


def test_doxycycline_decreases_activity_or_abundance_of_smarce1(config: xcrg.XCRGConfig):
    query = get_query_for_chemicals_affecting_gene("decreased", "NCBIGene:6605") # SMARCE1

    response = xcrg.run_xcrg(query.to_dict(), config)
    response = Response.from_dict(response)

    assert_is_never_show_answer("PUBCHEM.COMPOUND:54671203", response) # doxycycline


def test_ppara_increases_activity_or_abundance_of_permethrin(config: xcrg.XCRGConfig):
    query = get_query_for_genes_affected_by_chemical("increased", "CHEBI:34911") # Permethrin

    response = xcrg.run_xcrg(query.to_dict(), config)
    response = Response.from_dict(response)

    assert_is_top_answer("NCBIGene:5465", response)  # PPARA
