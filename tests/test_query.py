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


class TestChunkSearch:
    """Sentence-window search falls back to LIKE when there is no FTS index.

    The FTS path needs a materialised index database, which a test fixture
    cannot build in milliseconds; the LIKE path exercises the same filter and
    pagination logic.
    """

    @pytest.fixture
    def with_chunks(self, gold):
        chunks = [
            {
                "chunk_id": f"ch{i}",
                "paper_id": "p1" if i < 2 else "p2",
                "chunk_index": i,
                "start": i * 600,
                "end": i * 600 + 500,
                "text": text,
                "char_count": len(text),
            }
            for i, text in enumerate(
                [
                    "Xist RNA coats the inactive X chromosome in cis.",
                    "Polycomb complexes are recruited by the A-repeat.",
                    "Dosage compensation balances X-linked gene expression.",
                ]
            )
        ]
        pq.write_table(
            pa.Table.from_pylist(
                chunks,
                pa.schema(
                    [
                        ("chunk_id", pa.string()),
                        ("paper_id", pa.string()),
                        ("chunk_index", pa.int32()),
                        ("start", pa.int32()),
                        ("end", pa.int32()),
                        ("text", pa.string()),
                        ("char_count", pa.int32()),
                    ]
                ),
            ),
            gold / "chunks.parquet",
        )
        return gold

    def test_like_fallback_finds_chunk(self, with_chunks):
        conn = connect(with_chunks)
        rows, total = search.search_chunks(conn, search.ChunkFilter(text="A-repeat"))
        assert total == 1
        assert "Polycomb" in rows[0]["text"]

    def test_respects_limit(self, with_chunks):
        conn = connect(with_chunks)
        rows, total = search.search_chunks(conn, search.ChunkFilter(text="X", limit=1))
        assert len(rows) == 1
        assert total >= 1

    def test_filters_by_paper(self, with_chunks):
        conn = connect(with_chunks)
        rows, total = search.search_chunks(
            conn, search.ChunkFilter(text="X", paper_ids=["p2"])
        )
        assert all(r["paper_id"] == "p2" for r in rows)

    def test_no_match_returns_empty(self, with_chunks):
        conn = connect(with_chunks)
        rows, total = search.search_chunks(conn, search.ChunkFilter(text="nonexistent"))
        assert rows == []
        assert total == 0


class TestTierFilter:
    @pytest.fixture
    def with_tiers(self, gold):
        rows = [
            {"claim_id": "c1", "paper_id": "p1", "tier": "P1"},
            {"claim_id": "c2", "paper_id": "p1", "tier": "S"},
            {"claim_id": "c3", "paper_id": "p2", "tier": "K"},
        ]
        import pyarrow as pa2

        schema = pa2.schema(
            [
                ("claim_id", pa2.string()),
                ("paper_id", pa2.string()),
                ("tier", pa2.string()),
            ]
        )
        pq.write_table(pa2.Table.from_pylist(rows, schema), gold / "claim_provenance.parquet")
        return gold

    def test_filter_by_single_tier(self, with_tiers):
        conn = connect(with_tiers)
        rows, total = search.search_claims(conn, search.ClaimFilter(tiers=["P1"]))
        assert total == 1
        assert rows[0]["claim_id"] == "c1"

    def test_filter_by_multiple_tiers(self, with_tiers):
        conn = connect(with_tiers)
        _, total = search.search_claims(conn, search.ClaimFilter(tiers=["P1", "S"]))
        assert total == 2


class TestRerank:
    """The FTS index is a lexeme bag, so literal hits must be ranked first.

    Measured on the real corpus: "A-repeat" matches 37,013 chunks through the
    word "repeat" alone, and the top BM25 candidate was a sentence about a
    "repeat G region" -- while the 1,394 chunks that literally say "A-repeat"
    were not in the top 400 at all.
    """

    def test_literal_matches_rank_above_lexeme_matches(self):
        rows = [
            {"text": "The alignment of the repeat G region was conserved.", "score": 9.0},
            {"text": "Deletion of the A-repeat abolishes silencing.", "score": 2.0},
        ]
        ranked = search._rerank(rows, "A-repeat")
        assert "A-repeat" in ranked[0]["text"]

    def test_all_terms_present_ranks_second(self):
        rows = [
            {"text": "Polycomb binds here.", "score": 9.0},
            {"text": "Xist recruits Polycomb complexes.", "score": 2.0},
            {"text": "Polycomb alone.", "score": 5.0},
        ]
        ranked = search._rerank(rows, "Xist Polycomb")
        assert ranked[0]["text"] == "Xist recruits Polycomb complexes."

    def test_bm25_order_survives_within_a_tier(self):
        rows = [
            {"text": "Polycomb binds here.", "score": 2.0},
            {"text": "Polycomb binds elsewhere.", "score": 9.0},
        ]
        ranked = search._rerank(rows, "Polycomb")
        assert ranked[0]["score"] == 9.0

    def test_unknown_query_keeps_bm25_order(self):
        rows = [
            {"text": "first", "score": 2.0},
            {"text": "second", "score": 9.0},
        ]
        ranked = search._rerank(rows, "unrelated")
        assert [r["text"] for r in ranked] == ["second", "first"]


class TestVisualize:
    def test_payload_shape(self, gold):
        from xist_kb.query.aggregate import visualizing_payload

        conn = connect(gold)
        payload = visualizing_payload(conn)
        assert set(payload) >= {
            "interactors",
            "species",
            "years",
            "xci_types",
            "chromatin_marks",
            "chromatin_mark_papers",
        }

    def test_mark_dict_is_parsed(self):
        from xist_kb.query.aggregate import _mark_value

        parsed = _mark_value("{'h3k27me3': 'enriched', 'h2ak119ub': None}")
        assert parsed["h3k27me3"] == "enriched"
        assert "h2ak119ub" not in parsed

    def test_unparseable_mark_returns_empty(self):
        from xist_kb.query.aggregate import _mark_value

        assert _mark_value("not a dict") == {}
        assert _mark_value("") == {}
