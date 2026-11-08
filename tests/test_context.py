from __future__ import annotations

import pytest

from xist_kb.extract.context import (
    MAX_SECTION_CHARS,
    TextStore,
    build_context,
    find_quote_spans,
    normalize_text,
)
from xist_kb.models_context import ContextKind

PAPER = """\
Abstract
XIST is a long non-coding RNA.
Introduction
X chromosome inactivation silences one copy in females.
Results
We found that XIST recruits the silencing complex to the inactive X.
This requires repeat A.
References
1. Someone 2020.
"""


def test_normalized_offsets_map_back_to_original():
    text = "Hello\n\n  World"
    norm = normalize_text(text)
    assert norm.text == "hello world"
    # "world" starts at original index 9
    start, end = norm.span(6, 11)
    assert text[start:end] == "World"


def test_lowercase_expanding_character_keeps_offsets_aligned():
    # 'İ'.lower() is two characters; a naive chars/offsets append drifts and
    # every later quote slice comes out shifted. Found on 19 real claims.
    text = "İstanbul database analysis of gene expression"
    norm = normalize_text(text)
    assert len(norm.text) == len(norm.orig_offsets)
    spans = find_quote_spans(text, "database analysis of gene expression")
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "database analysis of gene expression"


def test_quote_span_survives_reflowed_whitespace():
    # the annotation's quote has single spaces; the text has a newline
    quote = "silences one copy in females"
    spans = find_quote_spans(PAPER, quote)
    assert len(spans) == 1
    assert spans[0].text == "silences one copy in females"
    assert PAPER[spans[0].start : spans[0].end] == spans[0].text


def test_quote_span_survives_case_difference():
    spans = find_quote_spans(PAPER, "xist is a long non-coding rna")
    assert len(spans) == 1
    assert PAPER[spans[0].start : spans[0].end] == "XIST is a long non-coding RNA"


def test_duplicate_quote_returns_every_occurrence():
    text = "the complex binds dna here.\nthe complex binds dna there.\n"
    spans = find_quote_spans(text, "the complex binds dna")
    assert len(spans) == 2
    assert spans[0].start < spans[1].start


def test_short_quote_is_refused():
    assert find_quote_spans(PAPER, "XIST") == []


def test_quote_not_in_text_returns_empty():
    assert find_quote_spans(PAPER, "a sentence that never appears anywhere at all") == []


def test_context_prefers_quote_over_section():
    context = build_context(
        "c1", "p1", "XIST recruits the silencing complex", "results", PAPER
    )
    assert context.kind is ContextKind.QUOTE
    assert len(context.spans) == 1
    assert context.section is None


def test_context_falls_back_to_section():
    context = build_context("c1", "p1", None, "results", PAPER)
    assert context.kind is ContextKind.SECTION
    assert context.section is not None
    assert "recruits the silencing complex" in context.section.text
    assert context.section.name == "results"


def test_section_fallback_when_quote_missing():
    context = build_context("c1", "p1", "totally absent sentence here", "results", PAPER)
    assert context.kind is ContextKind.SECTION


def test_section_fraction_reported():
    context = build_context("c1", "p1", None, "results", PAPER)
    assert context.section is not None
    assert 0 < context.section.fraction_of_paper < 1


def test_missing_heading_is_reported_not_faked():
    context = build_context("c1", "p1", None, "conclusion", PAPER)
    assert context.kind is ContextKind.NONE
    assert "conclusion" in context.reason


def test_no_text_is_reported():
    context = build_context("c1", "p1", "some quote that is long enough", "results", None)
    assert context.kind is ContextKind.NONE
    assert "full text" in context.reason


def test_no_quote_no_section_is_reported():
    context = build_context("c1", "p1", None, "not_reported", PAPER)
    assert context.kind is ContextKind.NONE


def test_huge_section_is_truncated():
    body = "Sentence. " * 10_000  # 100k chars of Results
    text = "Results\n" + body + "\n"
    context = build_context("c1", "p1", None, "results", text)
    assert context.section is not None
    assert context.section.truncated is True
    assert context.section.char_count > MAX_SECTION_CHARS
    assert len(context.section.text) == MAX_SECTION_CHARS


def test_section_repeats_are_concatenated():
    text = "Results\nfirst block here.\nResults\nsecond block here.\n"
    context = build_context("c1", "p1", None, "results", text)
    assert context.section is not None
    assert "first block" in context.section.text
    assert "second block" in context.section.text


def test_text_store_is_case_insensitive(tmp_path):
    (tmp_path / "Smith2020_abc.txt").write_text("body", encoding="utf-8")
    store = TextStore(tmp_path)
    assert store.get("smith2020_ABC") == "body"
    assert store.get("missing") is None


def test_text_store_missing_dir_returns_none(tmp_path):
    store = TextStore(tmp_path / "nope")
    assert store.get("anything") is None


@pytest.mark.parametrize(
    "section", ["results", "RESULTS", "Results"]
)
def test_section_lookup_is_case_insensitive(section):
    context = build_context("c1", "p1", None, section, PAPER)
    assert context.kind is ContextKind.SECTION
