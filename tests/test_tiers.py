from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from xist_kb.build.tiers import build, fuzzy_locate

PAPER_TEXT = """\
Abstract
XIST is a long non-coding RNA.
Results
We found that XIST recruits the silencing complex to the inactive X chromosome.
The same sentence appears again: XIST recruits the silencing complex to the inactive X chromosome.
A near-identical sentence: XIST recruits the silence complex to the inactive X chromosome.
A short quote: Fig 2.
"""


@pytest.fixture
def corpus(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "p1.txt").write_text(PAPER_TEXT, encoding="utf-8")

    claims = [
        # P1: unique in the text
        ("c_p1", "p1", "unique claim", "XIST is a long non-coding RNA.", "abstract", "prov_llm"),
        # P2: appears twice
        (
            "c_p2",
            "p1",
            "repeated claim",
            "XIST recruits the silencing complex to the inactive X chromosome",
            "results",
            "prov_llm",
        ),
        # P3: near-identical wording, not exact
        (
            "c_p3",
            "p1",
            "fuzzy claim",
            "XIST recruits the silencing complex to the inactive X chromosome in cis",
            "results",
            "prov_llm",
        ),
        # S: no quote, section known and present
        ("c_s", "p1", "section claim", None, "results", "prov_llm"),
        # S but the heading is absent
        ("c_s_missing", "p1", "section claim 2", None, "discussion", "prov_llm"),
        # C: no quote and no section
        ("c_c", "p1", "no info claim", None, "not_reported", "prov_llm"),
        # K: rule extraction, never a claim
        ("c_k", "p1", "tag", None, "xci", "prov_rule"),
        # C: paper has no text at all
        (
            "c_notext",
            "p_missing",
            "orphan",
            "some quote here that is long enough",
            "results",
            "prov_llm",
        ),
    ]
    rows = [
        {
            "claim_id": cid,
            "paper_id": pid,
            "claim": claim,
            "quote": quote,
            "section": section,
            "provenance_id": prov,
        }
        for cid, pid, claim, quote, section, prov in claims
    ]
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            pa.schema(
                [
                    ("claim_id", pa.string()),
                    ("paper_id", pa.string()),
                    ("claim", pa.string()),
                    ("quote", pa.string()),
                    ("section", pa.string()),
                    ("provenance_id", pa.string()),
                ]
            ),
        ),
        gold / "claims.parquet",
    )
    provs = [
        {"provenance_id": "prov_llm", "method": "llm"},
        {"provenance_id": "prov_rule", "method": "rule"},
    ]
    pq.write_table(
        pa.Table.from_pylist(
            provs, pa.schema([("provenance_id", pa.string()), ("method", pa.string())])
        ),
        gold / "provenance.parquet",
    )
    return gold, text_dir


def run_build(corpus):
    gold, text_dir = corpus
    out = gold / "claim_provenance.parquet"
    report = build(gold / "claims.parquet", gold / "provenance.parquet", text_dir, out)
    return report, {r["claim_id"]: r for r in pq.read_table(out).to_pylist()}


def test_tiers_assigned_correctly(corpus):
    _, by_id = run_build(corpus)
    assert by_id["c_p1"]["tier"] == "P1"
    assert by_id["c_p2"]["tier"] == "P2"
    assert by_id["c_p3"]["tier"] == "P3"
    assert by_id["c_s"]["tier"] == "S"
    assert by_id["c_s_missing"]["tier"] == "S"
    assert by_id["c_c"]["tier"] == "C_no_section"
    assert by_id["c_k"]["tier"] == "K"
    assert by_id["c_notext"]["tier"] == "C_no_text"


def test_p1_span_slices_to_the_quote(corpus):
    _, by_id = run_build(corpus)
    row = by_id["c_p1"]
    assert PAPER_TEXT[row["span_start"] : row["span_end"]] == "XIST is a long non-coding RNA."


def test_p2_records_occurrence_count(corpus):
    _, by_id = run_build(corpus)
    assert by_id["c_p2"]["span_count"] == 2


def test_s_renderable_only_when_heading_exists(corpus):
    _, by_id = run_build(corpus)
    assert by_id["c_s"]["section_renderable"] is True
    assert by_id["c_s_missing"]["section_renderable"] is False


def test_rule_claims_never_located(corpus):
    _, by_id = run_build(corpus)
    assert by_id["c_k"]["span_start"] is None
    assert by_id["c_k"]["section_renderable"] is None


def test_report_counts_sum_to_total(corpus):
    report, _ = run_build(corpus)
    assert report["claims"] == 8
    assert sum(report["tiers"].values()) == 8


def test_p3_span_is_the_alignment_not_the_window(corpus):
    """A window-sized P3 span would highlight 800 chars where 70 match."""
    _, by_id = run_build(corpus)
    row = by_id["c_p3"]
    length = row["span_end"] - row["span_start"]
    assert length < 200


def test_fuzzy_locate_returns_original_offsets():
    text = "Preamble.\n\nThe  XIST recruits\nthe silencing complex to the inactive X."
    quote = "XIST recruits the silencing complex to the inactive X"
    score, start, end = fuzzy_locate(text, quote)
    assert score >= 90
    assert text[start:end].strip() != ""
    assert "silencing" in text[start:end]


def test_fuzzy_locate_refuses_dissimilar_text():
    text = "Entirely unrelated material about cell culture media."
    score, _, _ = fuzzy_locate(text, "XIST recruits the silencing complex to the inactive X")
    assert score == 0


def test_fuzzy_locate_without_anchor_words():
    assert fuzzy_locate("some text", "12 34 56") == (0, 0, 0)
