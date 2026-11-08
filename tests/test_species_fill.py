"""Species filling refuses values that are not species.

The source data holds clades ("Mammalia", "Theria"), common names the vocabulary
map missed ("chimpanzee", "macaque"), viruses ("HIV-1"), the pseudo-binomial
"Multiple species", and corrupted field residue ("not reported not_reported XIST
expression"). Any of those copied into a fill table would be indistinguishable
from a real annotation downstream.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_species_fill.py"


@pytest.fixture(scope="module")
def fill_module():
    # The builder lives outside the package because it runs against the real
    # corpus; loading it by path keeps the test independent of sys.path games.
    spec = importlib.util.spec_from_file_location("build_species_fill", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_species_fill"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "value",
    ["Homo sapiens", "Mus musculus", "Drosophila melanogaster", "Escherichia coli"],
)
def test_real_binomials_pass(fill_module, value):
    assert fill_module._known_species_only([value]) == [value]


@pytest.mark.parametrize(
    "value",
    [
        "Mammalia",
        "Theria",
        "Multiple species",
        "Mammalian cells",
        "vertebrates",
        "chimpanzee",
        "macaque",
        "HIV-1",
        "KSHV",
        "not reported",
        "",
        "not reported not_reported XIST expression",
    ],
)
def test_non_species_values_are_refused(fill_module, value):
    assert fill_module._known_species_only([value]) == []


def test_empty_markers_are_not_usable(fill_module):
    for marker in ("", "  ", "not reported", "unknown", "N/A", "none"):
        assert not fill_module._usable(marker)
    assert fill_module._usable("Homo sapiens")


def test_filter_preserves_order_and_drops_only_bad(fill_module):
    values = ["Mus musculus", "Mammalia", "Homo sapiens", "HIV-1"]
    assert fill_module._known_species_only(values) == ["Mus musculus", "Homo sapiens"]
