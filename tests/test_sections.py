from __future__ import annotations

import pytest

from xist_kb.extract.sections import (
    CLAIM_SECTIONS,
    find_sections,
    get_section_text,
    section_spans,
)

ABSTRACT = """\
Title of the paper
Abstract
XIST coats the inactive X chromosome.
Introduction
X chromosome inactivation is a process.
Results
We found that XIST recruits silencing factors.
Discussion
Our findings suggest a model.
Methods
Cells were grown at 37 C.
References
1. Someone et al. 2020.
"""


def test_find_sections_returns_document_order():
    names = [s.name for s in find_sections(ABSTRACT)]
    assert names == ["abstract", "introduction", "results", "discussion", "methods", "references"]


def test_body_offsets_are_contiguous():
    text = ABSTRACT
    sections = find_sections(text)
    for current, following in zip(sections, sections[1:], strict=False):
        assert current.body_end == following.heading_start
    assert sections[-1].body_end == len(text)


def test_body_start_is_after_heading_line():
    text = ABSTRACT
    section = find_sections(text)[2]  # results
    assert text[section.heading_start : section.body_start].strip() == "Results"
    assert text[section.body_start : section.body_end].strip().startswith("We found")


def test_numbered_headings_match():
    text = "1. Introduction\nSome text.\n2. Results\nMore text.\n"
    assert [s.name for s in find_sections(text)] == ["introduction", "results"]


def test_keyword_inside_a_sentence_is_not_a_heading():
    text = (
        "Introduction\n"
        "The results in the complete inactivation of one allele.\n"
        "Results\n"
        "Real body.\n"
    )
    assert [s.name for s in find_sections(text)] == ["introduction", "results"]


def test_repeated_heading_is_kept_as_separate_sections():
    text = "Results\nfirst block\nResults\nsecond block\n"
    sections = find_sections(text)
    assert [s.name for s in sections] == ["results", "results"]
    assert sections[0].body_end == sections[1].heading_start


def test_get_section_text_concatenates_repeats():
    text = "Results\nfirst block\nResults\nsecond block\n"
    body = get_section_text(text, "results")
    assert "first block" in body
    assert "second block" in body


def test_get_section_text_returns_none_when_heading_absent():
    assert get_section_text(ABSTRACT, "conclusion") is None


def test_get_section_text_accepts_annotation_spelling():
    # annotations write "Results", "Materials and Methods", "not_reported"
    assert "silencing factors" in get_section_text(ABSTRACT, "Results")
    text = "Materials and Methods\nCells were grown.\n"
    assert "grown" in get_section_text(text, "methods")


def test_back_matter_heading_in_front_half_is_ignored():
    # a PDF running header can print "References" early; taking it as a
    # boundary made the preceding Abstract swallow the whole front matter.
    text = (
        "Abstract\n"
        + "A" * 100
        + "\nReferences\n"
        + "B" * 100
        + "\nResults\nreal results\nReferences\n1. cited\n"
    )
    sections = find_sections(text)
    names = [s.name for s in sections]
    assert names == ["abstract", "results", "references"]
    abstract = sections[0]
    assert abstract.char_count > 200  # not cut short by the stray heading


def test_back_matter_at_end_is_a_boundary():
    sections = find_sections(ABSTRACT)
    results = next(s for s in sections if s.name == "results")
    assert "References" not in ABSTRACT[results.body_start : results.body_end]


def test_section_spans_reports_fraction():
    text = ABSTRACT
    spans = section_spans(find_sections(text), len(text))
    assert all(0 < s["fraction"] <= 1 for s in spans)
    assert sum(s["char_count"] for s in spans) <= len(text)


def test_claim_sections_excludes_back_matter():
    assert "references" not in CLAIM_SECTIONS
    assert "results" in CLAIM_SECTIONS


def test_empty_text_has_no_sections():
    assert find_sections("") == []


@pytest.mark.parametrize("name", ["summary", "background", "results and discussion"])
def test_alias_headings_map_to_canonical(name):
    text = f"{name.title()}\nbody\n"
    sections = find_sections(text)
    assert len(sections) == 1
    assert sections[0].name in CLAIM_SECTIONS
