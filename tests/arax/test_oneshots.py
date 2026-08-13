"""Run various ARAX integration tests locally to verify results."""
import xcrg
from tests.utilities import (
    XCRG_Answer,
    assert_answer,
    find_chemicals_affecting_gene,
    find_genes_affected_by_chemical,
)


def test_ivacaftor_increases_activity_or_abundance_of_cftr(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "increased", "NCBIGene:1080") # CFTR
    assert_answer(response, XCRG_Answer("CHEBI:66901", "acceptable")) # Ivacaftor


def test_adra2a_increases_activity_or_abundance_of_guafacine(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "increased", "CHEBI:5558") # Guafacine
    assert_answer(response, XCRG_Answer("NCBIGene:150", "acceptable"))  # ADRA2A


def test_bcl2_decreases_activity_or_abundance_of_docetaxel(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "decreased", "CHEBI:4672") # Docetaxel
    assert_answer(response, XCRG_Answer("NCBIGene:596", "acceptable")) # BCL2


def test_guanfacine_increases_activity_or_abundance_of_dlg4(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "increased", "NCBIGene:1742") # DLG4
    assert_answer(response, XCRG_Answer("CHEBI:5558", "acceptable")) # Guafacine


def test_ng_nitroarginine_methyl_ester_increases_activity_or_abundance_of_acetylcholine(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "increased", "CHEBI:15355") # Acetylcholine
    assert_answer(response, XCRG_Answer("UMLS:C0083536", "never_show")) # NG-Nitroarginine Methyl Ester


def test_cancer_decreases_activity_or_abundance_of_myc(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "decreased", "NCBIGene:4609") # MYC
    assert_answer(response, XCRG_Answer("MONDO:0004992", "never_show")) # cancer


def test_ppara_increases_activity_or_abundance_of_clofibric_acid(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "increased", "CHEBI:34648")  # clofibric acid
    assert_answer(response, XCRG_Answer("NCBIGene:5465", "top_answer"))  # PPARA


def test_dabrafenib_decreases_activity_or_abundance_of_braf(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:673") # BRAF
    assert_answer(response, XCRG_Answer("CHEBI:75045", "acceptable"))  # Dabrafenib


# TODO: This fails on ARAX because the output_id "NCBI:2629" is incorrect?
def test_gba1_decreases_activity_or_abundance_of_eliglustat(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "decreased", "CHEBI:82752")  # Eliglustat
    assert_answer(response, XCRG_Answer("NCBIGene:2629", "acceptable", fails_on_arax = True))  # GBA1


def test_canagliflozin_decreases_activity_or_abundance_of_slc5a2(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:6524") # SLC5A2
    assert_answer(response, XCRG_Answer("CHEBI:73274", "top_answer")) # Canagliflozin


def test_naphthalene_decreases_activity_or_abundance_of_bpifa1(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:51297")  # BPIFA1
    assert_answer(response, XCRG_Answer("CHEBI:16482", "acceptable")) # Naphthalene


def test_acarbose_decreases_activity_or_abundance_of_mgam(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:8972") # MGAM
    assert_answer(response, XCRG_Answer("CHEBI:2376", "top_answer", fails_on_arax = True)) # Acarbose


def test_warfarin_decreases_activity_or_abundance_of_vkorc1(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:79001") # VKORC1
    assert_answer(response, XCRG_Answer("CHEBI:10033", "top_answer")) # Warfarin


def test_cyp3a4_decreases_activity_or_abundance_of_nirmatrelvir(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "decreased", "CHEBI:170007")  # Nirmatrelvir
    assert_answer(response, XCRG_Answer("NCBIGene:1576", "acceptable", fails_on_arax = True)) # CYP3A4


def test_ppara_increases_activity_or_abundance_of_permethrin(config: xcrg.XCRGConfig):
    response = find_genes_affected_by_chemical(config, "increased", "CHEBI:34911") # Permethrin
    assert_answer(response, XCRG_Answer("NCBIGene:5465", "top_answer", fails_on_arax = True))  # PPARA


def test_sildenafil_decreases_activity_or_abundance_of_pde5a(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:8654")  # PDE5A
    assert_answer(response, XCRG_Answer("CHEBI:9139", "top_answer")) # Sildenafil


def test_mrtx_1133_decreases_activity_or_abundance_of_kras(config: xcrg.XCRGConfig):
    response = find_chemicals_affecting_gene(config, "decreased", "NCBIGene:3845")  # KRAS
    assert_answer(response, XCRG_Answer("PUBCHEM.COMPOUND:156124857", "top_answer", fails_on_arax = True)) # MRTX-1133
