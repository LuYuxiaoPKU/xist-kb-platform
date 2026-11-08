"""Regulator name normalization: fold what is the same, keep what is not.

The table has 1,339 distinct raw names for genes that are fewer than that. Two
mechanical folds are safe; anything requiring knowledge of gene synonymy is not,
because a wrong merge silently combines two different factors.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_regulators.py"


@pytest.fixture(scope="module")
def reg_module():
    spec = importlib.util.spec_from_file_location("build_regulators", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_regulators"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("Tsix", "Tsix"),
        ("TSIX", "TSIX"),  # case is folded for grouping, not for display
        ("OCT4 (Pou5f1)", "OCT4"),
        ("Oct4 (POU5F1)", "Oct4"),
        ("RELA (p65)", "RELA"),
        ("NCRNA00183 (JPX/ENOX)", "NCRNA00183"),
        ("Rnf12", "Rnf12"),
    ],
)
def test_alias_is_stripped(reg_module, raw, canonical):
    assert reg_module.normalize_regulator(raw)[0] == canonical


@pytest.mark.parametrize(
    "raw",
    [
        # Experimental conditions, not gene aliases: stripping them would merge
        # rows that differ in what they measured.
        "Oxygen tension (5% vs 20%)",
        "Tetracycline/doxycycline-inducible promoter (artificial)",
        "X-Ra (X-Reactivation)",
        "Doxycycline-induced Xist (TX allele, nls-rtTA from ROSA26)",
    ],
)
def test_conditions_are_not_stripped(reg_module, raw):
    assert reg_module.normalize_regulator(raw)[0] == raw
    assert reg_module.normalize_regulator(raw)[1] == ""


def test_alias_is_reported_for_review(reg_module):
    canonical, alias = reg_module.normalize_regulator("Oct4 (Pou5f1)")
    assert canonical == "Oct4"
    assert alias == "Pou5f1"


def test_parenthesised_name_alone_is_kept(reg_module):
    # "(RLIM)" has nothing outside the parentheses; the parenthesised text is
    # the name, not an alias of the empty string.
    assert reg_module.normalize_regulator("(RLIM)")[0] == "(RLIM)"


def test_empty_and_none_return_empty(reg_module):
    assert reg_module.normalize_regulator("") == ("", "")
    assert reg_module.normalize_regulator(None) == ("", "")
    assert reg_module.normalize_regulator("   ") == ("", "")


def test_case_only_variants_fold_to_one_group(reg_module):
    names = ["Tsix", "TSIX", "tsix"]
    folded = {reg_module.normalize_regulator(n)[0].lower() for n in names}
    assert folded == {"tsix"}


def test_synonyms_are_deliberately_not_merged(reg_module):
    # Oct4 and POU5F1 are the same gene, but deciding that needs external
    # knowledge; the alias column preserves the link for a future synonym table.
    assert reg_module.normalize_regulator("Oct4")[0] != reg_module.normalize_regulator("POU5F1")[0]
