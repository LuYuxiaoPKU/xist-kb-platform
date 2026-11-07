"""Tests for the vocabulary cleaners.

These cover the exact defects found in V2 data, so a regression here means a
migration would silently reintroduce them.
"""

import pytest

from xist_kb.vocab import (
    CONFIDENCE_VALUES,
    EVIDENCE_TYPE_VALUES,
    normalize_doi,
    normalize_enum,
    normalize_species_list,
    normalize_topic,
    normalize_year,
)


class TestTopics:
    def test_standard_topic_passes_through(self):
        assert normalize_topic("chromatin") == "chromatin"

    def test_none_becomes_other(self):
        assert normalize_topic(None) == "other"

    def test_empty_string_becomes_other(self):
        assert normalize_topic("") == "other"

    def test_stringified_list(self):
        assert normalize_topic("['xci']") == "xci"

    def test_real_list_takes_first_standard(self):
        assert normalize_topic(["methods", "xci"]) == "methods"

    def test_multi_topic_string_prefers_standard(self):
        assert normalize_topic("other, polycomb") == "polycomb"

    def test_fragment_maps_to_canonical(self):
        assert normalize_topic("gene_regulation") == "gene_silencing"
        assert normalize_topic("pluripotency") == "early_embryo"

    def test_other_with_hint_uses_hint(self):
        assert normalize_topic("other - pluripotency") == "early_embryo"

    def test_unknown_falls_back_to_other(self):
        assert normalize_topic("quantum biology") == "other"

    def test_substring_match(self):
        assert normalize_topic("xist_rna_function_analysis") == "xist_rna_function"


class TestSpecies:
    def test_common_name_maps_to_binomial(self):
        assert normalize_species_list("human") == ["Homo sapiens"]

    def test_semicolon_joined_string_splits(self):
        assert normalize_species_list("human; mouse") == ["Homo sapiens", "Mus musculus"]

    def test_dedupes_preserving_order(self):
        assert normalize_species_list("human; Human") == ["Homo sapiens"]

    def test_sentinels_drop_out(self):
        assert normalize_species_list("not reported") == []
        assert normalize_species_list("") == []
        assert normalize_species_list(None) == []

    def test_parenthetical_description_removed(self):
        assert normalize_species_list("Sus scrofa (pig)") == ["Sus scrofa"]

    def test_count_phrase_rejected(self):
        assert normalize_species_list("10 gibbon species") == []

    def test_already_latin_passes_through(self):
        assert normalize_species_list("Mus musculus") == ["Mus musculus"]

    def test_lowercase_binomial_capitalised(self):
        assert normalize_species_list("mus musculus") == ["Mus musculus"]

    def test_mixed_list_and_sentinels(self):
        assert normalize_species_list(["human", "not reported", "mouse"]) == [
            "Homo sapiens",
            "Mus musculus",
        ]


class TestEnums:
    def test_plain_value(self):
        assert normalize_enum("high", CONFIDENCE_VALUES) == "high"

    def test_stringified_list_is_unwrapped(self):
        # This is the exact V2 defect: 559 claims had confidence "['high']".
        assert normalize_enum("['high']", CONFIDENCE_VALUES) == "high"

    def test_list_input(self):
        assert normalize_enum(["medium"], CONFIDENCE_VALUES) == "medium"

    def test_space_to_underscore(self):
        assert normalize_enum("not reported", EVIDENCE_TYPE_VALUES) == "not_reported"

    def test_unknown_uses_default(self):
        assert normalize_enum("banana", CONFIDENCE_VALUES) == "not_reported"

    def test_none_uses_default(self):
        assert normalize_enum(None, CONFIDENCE_VALUES) == "not_reported"

    def test_alias_repaired(self):
        assert normalize_enum("experimental", EVIDENCE_TYPE_VALUES) == "direct_experimental"

    def test_empty_list_uses_default(self):
        assert normalize_enum([], CONFIDENCE_VALUES) == "not_reported"


class TestIdentifiers:
    def test_doi_url_prefix_stripped(self):
        assert normalize_doi("https://doi.org/10.1038/NATURE12345") == "10.1038/nature12345"

    def test_doi_scheme_prefix_stripped(self):
        assert normalize_doi("doi: 10.1101/2020.01.01.123456") == "10.1101/2020.01.01.123456"

    def test_doi_sentinel_returns_none(self):
        assert normalize_doi("not reported") is None
        assert normalize_doi("") is None
        assert normalize_doi(None) is None

    def test_year_int_passes(self):
        assert normalize_year(2019) == 2019

    def test_year_extracted_from_noise(self):
        assert normalize_year("published 2019 online") == 2019

    def test_year_sentinel_returns_none(self):
        assert normalize_year("not reported") is None

    def test_year_out_of_range_ignored(self):
        assert normalize_year(1234) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("xci, methods", "xci"),
        ("['chromatin']", "chromatin"),
        ("other", "other"),
    ],
)
def test_topic_parametrized(value, expected):
    assert normalize_topic(value) == expected
