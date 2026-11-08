from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow.parquet as pq
import pytest

from xist_kb.annotate.store import AnnotationStore, annotation_key


def test_key_ignores_whitespace_and_case():
    a = annotation_key("p1", "Xist  coats the X", "Quote here")
    b = annotation_key("p1", "xist coats the x", "quote   here")
    assert a == b


def test_key_changes_with_content():
    base = annotation_key("p1", "claim text", "quote")
    assert base != annotation_key("p1", "other claim", "quote")
    assert base != annotation_key("p1", "claim text", "other quote")
    assert base != annotation_key("p2", "claim text", "quote")


def test_key_is_stable_across_claim_id_regeneration():
    # the whole point: the key does not take a claim_id
    assert annotation_key("p1", "c", "q") == annotation_key("p1", "c", "q")


def test_store_roundtrip(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    store.add(
        claim_id="c1",
        paper_id="p1",
        claim="Xist coats the inactive X",
        quote="Xist coats the inactive X in cis",
        verdict="correct",
        note="matches the figure",
        annotator="luyx",
    )
    rows = store.read()
    assert len(rows) == 1
    assert rows[0].verdict == "correct"
    assert rows[0].annotator == "luyx"


def test_latest_supersedes_older_annotation(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    t0 = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
    store.add(claim_id="c1", paper_id="p1", claim="c", quote="q", verdict="wrong", created_at=t0)
    store.add(
        claim_id="c1", paper_id="p1", claim="c", quote="q", verdict="correct",
        created_at=t0 + timedelta(hours=1),
    )
    latest = store.latest()
    assert len(latest) == 1
    assert next(iter(latest.values())).verdict == "correct"


def test_annotation_survives_new_claim_id(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    store.add(claim_id="old_id", paper_id="p1", claim="c", quote="q", verdict="correct")
    # a migration run regenerates every claim_id; the annotation is found by
    # content next time the reviewer opens the claim
    key = annotation_key("p1", "c", "q")
    assert store.latest()[key].verdict == "correct"


def test_verdict_validated(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    with pytest.raises(ValueError, match="verdict"):
        store.add(claim_id="c", paper_id="p", claim="c", quote=None, verdict="maybe")


def test_empty_store_reads_empty(tmp_path):
    store = AnnotationStore(tmp_path / "nothing.parquet")
    assert store.read() == []
    assert store.latest() == {}
    assert store.counts()["total"] == 0


def test_counts(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    store.add(claim_id="c1", paper_id="p1", claim="a", quote=None, verdict="correct")
    store.add(claim_id="c2", paper_id="p1", claim="b", quote=None, verdict="correct")
    store.add(claim_id="c3", paper_id="p1", claim="c", quote=None, verdict="wrong")
    counts = store.counts()
    assert counts["correct"] == 2
    assert counts["wrong"] == 1
    assert counts["unsure"] == 0
    assert counts["total"] == 3


def test_write_is_atomic(tmp_path):
    path = tmp_path / "annotations.parquet"
    store = AnnotationStore(path)
    store.add(claim_id="c1", paper_id="p1", claim="a", quote=None, verdict="correct")
    # no stray temp file left behind, and the file parses
    assert not list(tmp_path.glob("*.tmp"))
    assert pq.read_table(path).num_rows == 1


def test_schema_matches_written_file(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.parquet")
    store.add(claim_id="c1", paper_id="p1", claim="a", quote="q", verdict="unsure")
    table = pq.read_table(tmp_path / "annotations.parquet")
    assert set(table.column_names) == {
        "annotation_key",
        "claim_id",
        "paper_id",
        "verdict",
        "note",
        "annotator",
        "created_at",
    }
