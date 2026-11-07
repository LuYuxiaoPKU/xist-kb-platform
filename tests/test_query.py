"""Tests for the query layer, against a synthetic Gold directory."""

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from xist_kb.ingest.migrate_v2 import (
    CLAIMS_SCHEMA,
    PAPERS_SCHEMA,
    PROVENANCE_SCHEMA,
)
from xist_kb.query import search
from xist_kb.query.engine import connect, describe


@pytest.fixture
def gold(tmp_path):
    out = tmp_path / "gold"
    out.mkdir()
    now = datetime.now(UTC)
    papers = [
        {
            "paper_id": "p1",
            "doi": "10.1/a",
            "pmid": None,
            "pmcid": None,
            "openalex_id": None,
            "title": "Xist coats the inactive X",
            "abstract": None,
            "year": 2019,
            "journal": "Nature",
            "first_author": "Smith",
            "authors": [],
            "species": ["Mus musculus"],
            "taxonomic_group": "Mammalia",
            "status": "annotated",
            "has_text": True,
            "has_pdf": True,
            "has_annotation": True,
            "source": "v2_migration",
            "retrieved_at": now,
        },
        {
            "paper_id": "p2",
            "doi": None,
            "pmid": None,
            "pmcid": None,
            "openalex_id": None,
            "title": "Xist in human cells",
            "abstract": None,
            "year": 2021,
            "journal": "Cell",
            "first_author": "Doe",
            "authors": [],
            "species": ["Homo sapiens"],
            "taxonomic_group": "Mammalia",
            "status": "registered",
            "has_text": False,
            "has_pdf": False,
            "has_annotation": False,
            "source": "v2_migration",
            "retrieved_at": now,
        },
    ]
    claims = [
        {
            "claim_id": "c1",
            "paper_id": "p1",
            "claim": "Xist RNA coats the inactive X chromosome",
            "topic": "xci",
            "evidence": None,
            "evidence_type": "direct_experimental",
            "directness": "direct",
            "section": "results",
            "figure_or_table": None,
            "species": ["Mus musculus"],
            "cell_type": "ES",
            "confidence": "high",
            "caveat": None,
            "quote": "Xist RNA coats the inactive X chromosome in cis.",
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov1",
        },
        {
            "claim_id": "c2",
            "paper_id": "p1",
            "claim": "PRC2 is recruited by the A-repeat",
            "topic": "polycomb",
            "evidence": None,
            "evidence_type": "indirect_experimental",
            "directness": "indirect",
            "section": "discussion",
            "figure_or_table": None,
            "species": ["Mus musculus"],
            "cell_type": None,
            "confidence": "medium",
            "caveat": None,
            "quote": None,
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov1",
        },
        {
            "claim_id": "c3",
            "paper_id": "p2",
            "claim": "XIST escapes X inactivation in some tumours",
            "topic": "cancer_biology",
            "evidence": None,
            "evidence_type": "rule_extraction",
            "directness": "indirect",
            "section": "abstract",
            "figure_or_table": None,
            "species": ["Homo sapiens"],
            "cell_type": None,
            "confidence": "low",
            "caveat": None,
            "quote": None,
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov2",
        },
    ]
    provenance = [
        {
            "provenance_id": "prov1",
            "paper_id": "p1",
            "method": "llm",
            "model": None,
            "prompt_template": None,
            "prompt_hash": None,
            "runtime_seconds": None,
            "created_at": now,
            "source_checksum": None,
        },
        {
            "provenance_id": "prov2",
            "paper_id": "p2",
            "method": "rule",
            "model": None,
            "prompt_template": None,
            "prompt_hash": None,
            "runtime_seconds": None,
            "created_at": now,
            "source_checksum": None,
        },
    ]

    empty = {
        "interactors.parquet": pa.schema(
            [
                ("paper_id", pa.string()),
                ("protein", pa.string()),
                ("xist_domain", pa.string()),
                ("method", pa.string()),
                ("function", pa.string()),
                ("species", pa.list_(pa.string())),
                ("cell_type", pa.string()),
                ("direct_or_indirect", pa.string()),
                ("confidence", pa.string()),
                ("provenance_id", pa.string()),
            ]
        ),
        "regulations.parquet": pa.schema(
            [
                ("paper_id", pa.string()),
                ("regulator", pa.string()),
                ("target", pa.string()),
                ("direction", pa.string()),
                ("species", pa.list_(pa.string())),
                ("cell_type", pa.string()),
                ("developmental_stage", pa.string()),
                ("evidence_type", pa.string()),
                ("directness", pa.string()),
                ("confidence", pa.string()),
                ("provenance_id", pa.string()),
            ]
        ),
        "xci_status.parquet": pa.schema(
            [
                ("paper_id", pa.string()),
                ("species", pa.list_(pa.string())),
                ("cell_type", pa.string()),
                ("developmental_stage", pa.string()),
                ("xci_type", pa.string()),
                ("xist_status", pa.string()),
                ("chromatin_marks", pa.list_(pa.string())),
                ("confidence", pa.string()),
                ("provenance_id", pa.string()),
            ]
        ),
        "species_xist.parquet": pa.schema(
            [
                ("paper_id", pa.string()),
                ("species", pa.string()),
                ("taxonomic_group", pa.string()),
                ("xist_reported", pa.bool_()),
                ("confidence", pa.string()),
                ("experimental_validation", pa.string()),
                ("synteny_evidence", pa.string()),
                ("provenance_id", pa.string()),
            ]
        ),
    }

    pq.write_table(pa.Table.from_pylist(papers, PAPERS_SCHEMA), out / "papers.parquet")
    pq.write_table(pa.Table.from_pylist(claims, CLAIMS_SCHEMA), out / "claims.parquet")
    pq.write_table(
        pa.Table.from_pylist(provenance, PROVENANCE_SCHEMA), out / "provenance.parquet"
    )
    for name, schema in empty.items():
        pq.write_table(schema.empty_table(), out / name)
    return out


class TestEngine:
    def test_describe_counts(self, gold):
        conn = connect(gold)
        counts = describe(conn)
        assert counts["papers"] == 2
        assert counts["claims"] == 3

    def test_missing_gold_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="gold layer not built"):
            connect(tmp_path / "nope")


class TestClaimSearch:
    def test_no_filter_returns_all_with_total(self, gold):
        conn = connect(gold)
        rows, total = search.search_claims(conn, search.ClaimFilter())
        assert total == 3
        assert len(rows) == 3

    def test_filter_by_topic(self, gold):
        conn = connect(gold)
        rows, total = search.search_claims(conn, search.ClaimFilter(topics=["xci"]))
        assert total == 1
        assert rows[0]["claim_id"] == "c1"

    def test_filter_by_multiple_topics(self, gold):
        conn = connect(gold)
        rows, total = search.search_claims(
            conn, search.ClaimFilter(topics=["xci", "polycomb"])
        )
        assert total == 2

    def test_filter_by_species_membership(self, gold):
        conn = connect(gold)
        _rows, total = search.search_claims(
            conn, search.ClaimFilter(species=["Homo sapiens"])
        )
        assert total == 1

    def test_species_does_not_match_substring(self, gold):
        conn = connect(gold)
        # "Homo" alone must not match "Homo sapiens" in a list column.
        _rows, total = search.search_claims(conn, search.ClaimFilter(species=["Homo"]))
        assert total == 0

    def test_year_range(self, gold):
        conn = connect(gold)
        _rows, total = search.search_claims(
            conn, search.ClaimFilter(year_from=2020, year_to=2022)
        )
        assert total == 1

    def test_confidence_filter(self, gold):
        conn = connect(gold)
        _rows, total = search.search_claims(conn, search.ClaimFilter(confidence=["high"]))
        assert total == 1

    def test_text_matches_claim_or_quote(self, gold):
        conn = connect(gold)
        _rows, total = search.search_claims(conn, search.ClaimFilter(text="coats"))
        assert total == 1

    def test_text_is_case_insensitive(self, gold):
        conn = connect(gold)
        _rows, total = search.search_claims(conn, search.ClaimFilter(text="COATS"))
        assert total == 1

    def test_pagination_keeps_total(self, gold):
        conn = connect(gold)
        rows, total = search.search_claims(conn, search.ClaimFilter(limit=1, offset=0))
        assert total == 3
        assert len(rows) == 1
        rows2, _ = search.search_claims(conn, search.ClaimFilter(limit=1, offset=1))
        assert rows2[0]["claim_id"] != rows[0]["claim_id"]

    def test_joined_paper_fields_present(self, gold):
        conn = connect(gold)
        rows, _ = search.search_claims(conn, search.ClaimFilter(topics=["xci"]))
        assert rows[0]["title"] == "Xist coats the inactive X"
        assert rows[0]["journal"] == "Nature"


class TestPaperSearch:
    def test_all(self, gold):
        conn = connect(gold)
        _rows, total = search.search_papers(conn, search.PaperFilter())
        assert total == 2

    def test_status_filter(self, gold):
        conn = connect(gold)
        _rows, total = search.search_papers(conn, search.PaperFilter(status=["annotated"]))
        assert total == 1

    def test_text_filter(self, gold):
        conn = connect(gold)
        _rows, total = search.search_papers(conn, search.PaperFilter(text="human"))
        assert total == 1


class TestStats:
    def test_shapes(self, gold):
        conn = connect(gold)
        s = search.stats(conn)
        assert {t["topic"] for t in s["topics"]} == {"xci", "polycomb", "cancer_biology"}
        assert {st["status"] for st in s["statuses"]} == {"annotated", "registered"}
        assert len(s["years"]) == 2
        assert s["species"][0]["count"] == 2

    def test_topic_sorted_by_count(self, gold):
        conn = connect(gold)
        topics = search.stats(conn)["topics"]
        counts = [t["count"] for t in topics]
        assert counts == sorted(counts, reverse=True)


class TestPaperDetail:
    def test_get_paper(self, gold):
        conn = connect(gold)
        p = search.get_paper(conn, "p1")
        assert p["title"] == "Xist coats the inactive X"

    def test_missing_paper_returns_none(self, gold):
        conn = connect(gold)
        assert search.get_paper(conn, "nope") is None

    def test_claims_for_paper_carry_method(self, gold):
        conn = connect(gold)
        rows = search.get_claims_for_paper(conn, "p1")
        assert len(rows) == 2
        assert {r["annotation_method"] for r in rows} == {"llm"}

    def test_interactors_empty(self, gold):
        conn = connect(gold)
        assert search.get_interactors(conn) == []
