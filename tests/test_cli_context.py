"""End-to-end test of the `context` CLI command against a synthetic Gold dir."""

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from xist_kb.cli import app
from xist_kb.ingest.migrate_v2 import (
    CLAIMS_SCHEMA,
    INTERACTORS_SCHEMA,
    PAPERS_SCHEMA,
    PROVENANCE_SCHEMA,
    REGULATIONS_SCHEMA,
    SPECIES_XIST_SCHEMA,
    XCI_STATUS_SCHEMA,
)

PAPER_TEXT = """\
Abstract
XIST is a long non-coding RNA that coats the inactive X.

Results
We found that XIST recruits the silencing complex to the inactive X
chromosome in cis, and that this requires the A-repeat.

Discussion
Our data suggest a model in which coating precedes silencing.
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "gold"
    out.mkdir()
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "p1.txt").write_text(PAPER_TEXT, encoding="utf-8")
    # the server's filesystem is case sensitive; paper_id does not match the
    # file's case, and the command must still find it
    (text_dir / "P2.txt").write_text("Abstract\nNo results heading here.\n", encoding="utf-8")

    now = datetime.now(UTC)
    papers = [
        {
            "paper_id": pid,
            "doi": None,
            "pmid": None,
            "pmcid": None,
            "openalex_id": None,
            "title": f"Paper {pid}",
            "abstract": None,
            "year": 2020,
            "journal": "J",
            "first_author": "A",
            "authors": [],
            "species": [],
            "taxonomic_group": None,
            "status": "annotated",
            "has_text": True,
            "has_pdf": False,
            "has_annotation": True,
            "source": "test",
            "retrieved_at": now,
        }
        for pid in ("p1", "p2")
    ]
    claims = [
        {
            "claim_id": claim_id,
            "paper_id": paper_id,
            "claim": "text",
            "topic": "xci",
            "evidence": None,
            "evidence_type": "direct_experimental",
            "directness": "direct",
            "section": section,
            "figure_or_table": None,
            "species": [],
            "cell_type": None,
            "confidence": "high",
            "caveat": None,
            "quote": quote,
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov1",
        }
        for claim_id, paper_id, section, quote in (
            (
                "c_quote",
                "p1",
                "results",
                "XIST recruits the silencing complex to the inactive X chromosome",
            ),
            ("c_section", "p1", "results", None),
            ("c_none", "p1", "not_reported", "a quote that is not in the text at all"),
            ("c_noheading", "p2", "results", None),
        )
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
        }
    ]

    pq.write_table(pa.Table.from_pylist(papers, PAPERS_SCHEMA), out / "papers.parquet")
    pq.write_table(pa.Table.from_pylist(claims, CLAIMS_SCHEMA), out / "claims.parquet")
    pq.write_table(
        pa.Table.from_pylist(provenance, PROVENANCE_SCHEMA), out / "provenance.parquet"
    )
    # connect() opens a view per Gold table; the context command only reads
    # claims, but it cannot start without the rest of the layer present
    for name, schema in (
        ("interactors", INTERACTORS_SCHEMA),
        ("regulations", REGULATIONS_SCHEMA),
        ("xci_status", XCI_STATUS_SCHEMA),
        ("species_xist", SPECIES_XIST_SCHEMA),
    ):
        pq.write_table(schema.empty_table(), out / f"{name}.parquet")

    monkeypatch.setenv("XIST_KB_DATA", str(tmp_path))
    monkeypatch.setenv("XIST_KB_TEXT_DIR", str(text_dir))
    # paths.py and engine.py read the environment at import time
    import importlib

    from xist_kb import paths
    from xist_kb.query import engine

    importlib.reload(paths)
    importlib.reload(engine)
    return out


def run(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_quote_tier_prints_located_span(env):
    out = run("context", "c_quote")
    assert "quote located" in out
    assert "offsets" in out
    # the span itself is highlighted, with surrounding context on both sides
    assert "recruits the silencing complex" in out
    assert "offsets 89:" in out  # the quote starts at the top of the Results body


def test_section_tier_prints_body_and_fraction(env):
    out = run("context", "c_section")
    assert "section only" in out
    assert "results" in out
    assert "% of the paper" in out
    assert "recruits the silencing complex" in out


def test_section_flag_prints_whole_body(env):
    out = run("context", "c_section", "--section")
    assert "Our data suggest a model" not in out  # that line is in Discussion
    assert "recruits the silencing complex" in out


def test_missing_heading_is_reported(env):
    out = run("context", "c_noheading")
    assert "no context" in out
    assert "no such heading" in out


def test_quote_not_in_text_without_heading_is_reported(env):
    out = run("context", "c_none")
    assert "no context" in out
    assert "not found" in out


def test_prefix_match_resolves_unique_id(env):
    out = run("context", "c_quo")
    assert "quote located" in out


def test_ambiguous_prefix_exits_nonzero(env):
    result = CliRunner().invoke(app, ["context", "c_"])
    assert result.exit_code == 1
    assert "match" in result.output


def test_unknown_claim_exits_nonzero(env):
    result = CliRunner().invoke(app, ["context", "nope"])
    assert result.exit_code == 1
    assert "no claim matching" in result.output
