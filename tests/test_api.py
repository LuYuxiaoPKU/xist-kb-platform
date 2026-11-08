"""API tests against a synthetic Gold directory.

Every test builds its own data tree and points the app at it through the
environment, so nothing here depends on the 34 MB real Gold layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

PAPER_TEXT = """\
Abstract
XIST coats the inactive X chromosome.

Results
We found that XIST recruits the silencing complex, and that this requires the
A-repeat. The A-repeat is conserved across mammals.

Discussion
Our data suggest a model in which coating precedes silencing.
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    gold = tmp_path / "gold"
    gold.mkdir()
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "p1.txt").write_text(PAPER_TEXT, encoding="utf-8")
    (tmp_path / "silver").mkdir()

    now = datetime.now(UTC)
    papers = [
        {
            "paper_id": "p1",
            "doi": "10.1/x",
            "pmid": None,
            "pmcid": None,
            "openalex_id": None,
            "title": "Xist coats the inactive X",
            "abstract": None,
            "year": 2020,
            "journal": "Nature",
            "first_author": "Smith",
            "authors": [],
            "species": ["Mus musculus"],
            "taxonomic_group": "Mammalia",
            "status": "annotated",
            "has_text": True,
            "has_pdf": False,
            "has_annotation": True,
            "source": "test",
            "retrieved_at": now,
        }
    ]
    claims = [
        {
            "claim_id": "c_p1",
            "paper_id": "p1",
            "claim": "XIST coats the inactive X",
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
            "quote": "XIST recruits the silencing complex, and that this requires the A-repeat",
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov1",
        },
        {
            "claim_id": "c_s",
            "paper_id": "p1",
            "claim": "Coating precedes silencing",
            "topic": "xci",
            "evidence": None,
            "evidence_type": "inferred",
            "directness": "indirect",
            "section": "discussion",
            "figure_or_table": None,
            "species": [],
            "cell_type": None,
            "confidence": "medium",
            "caveat": None,
            "quote": None,
            "quote_offset_start": None,
            "quote_offset_end": None,
            "chunk_id": None,
            "provenance_id": "prov1",
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
        }
    ]
    tier_schema = pa.schema(
        [
            ("claim_id", pa.string()),
            ("paper_id", pa.string()),
            ("tier", pa.string()),
            ("span_start", pa.int32()),
            ("span_end", pa.int32()),
            ("span_count", pa.int32()),
            ("fuzzy_score", pa.int32()),
            ("section_renderable", pa.bool_()),
            ("chunk_index", pa.int32()),
        ]
    )
    tiers = [
        {
            "claim_id": "c_p1", "paper_id": "p1", "tier": "P1",
            "span_start": 74, "span_end": 140, "span_count": 1,
            "fuzzy_score": None, "section_renderable": None, "chunk_index": 1,
        },
        {
            "claim_id": "c_s", "paper_id": "p1", "tier": "S",
            "span_start": None, "span_end": None, "span_count": None,
            "fuzzy_score": None, "section_renderable": True, "chunk_index": None,
        },
    ]
    chunks = [
        {
            "chunk_id": "ch0",
            "paper_id": "p1",
            "chunk_index": 0,
            "start": 0,
            "end": 40,
            "text": "XIST coats the inactive X chromosome.",
            "char_count": 38,
        },
        {
            "chunk_id": "ch1",
            "paper_id": "p1",
            "chunk_index": 1,
            "start": 41,
            "end": 140,
            "text": "XIST recruits the silencing complex, and that this requires the A-repeat.",
            "char_count": 77,
        },
    ]

    from xist_kb.ingest.migrate_v2 import (
        CLAIMS_SCHEMA,
        INTERACTORS_SCHEMA,
        PAPERS_SCHEMA,
        PROVENANCE_SCHEMA,
        REGULATIONS_SCHEMA,
        SPECIES_XIST_SCHEMA,
        XCI_STATUS_SCHEMA,
    )

    pq.write_table(pa.Table.from_pylist(papers, PAPERS_SCHEMA), gold / "papers.parquet")
    pq.write_table(pa.Table.from_pylist(claims, CLAIMS_SCHEMA), gold / "claims.parquet")
    pq.write_table(
        pa.Table.from_pylist(provenance, PROVENANCE_SCHEMA), gold / "provenance.parquet"
    )
    for name, schema in (
        ("interactors", INTERACTORS_SCHEMA),
        ("regulations", REGULATIONS_SCHEMA),
        ("xci_status", XCI_STATUS_SCHEMA),
        ("species_xist", SPECIES_XIST_SCHEMA),
    ):
        pq.write_table(schema.empty_table(), gold / f"{name}.parquet")
    pq.write_table(
        pa.Table.from_pylist(tiers, tier_schema), gold / "claim_provenance.parquet"
    )
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

    monkeypatch.setenv("XIST_KB_DATA", str(tmp_path))
    monkeypatch.setenv("XIST_KB_TEXT_DIR", str(text_dir))
    monkeypatch.delenv("XIST_KB_API_KEY", raising=False)
    monkeypatch.delenv("XIST_KB_ALLOWED_NETS", raising=False)

    import importlib

    from xist_kb import paths
    from xist_kb.api import deps
    from xist_kb.query import engine

    importlib.reload(paths)
    importlib.reload(engine)
    importlib.reload(deps)

    from xist_kb.api.main import create_app

    return TestClient(create_app())


def test_health_needs_no_auth(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_claims_list(client):
    r = client.get("/api/claims")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {c["claim_id"] for c in body["items"]} == {"c_p1", "c_s"}


def test_claims_carry_tier(client):
    body = client.get("/api/claims").json()
    tiers = {c["claim_id"]: c["tier"] for c in body["items"]}
    assert tiers == {"c_p1": "P1", "c_s": "S"}


def test_claim_filter_by_tier(client):
    body = client.get("/api/claims?tier=P1").json()
    assert body["total"] == 1
    assert body["items"][0]["claim_id"] == "c_p1"


def test_claim_detail_includes_tier_and_annotation(client):
    body = client.get("/api/claims/c_p1").json()
    assert body["claim_id"] == "c_p1"
    assert body["tier"] == "P1"
    assert body["annotation"] is None


def test_claim_detail_unknown(client):
    body = client.get("/api/claims/nope").json()
    assert "error" in body


def test_context_returns_quote_span(client):
    body = client.get("/api/claims/c_p1/context").json()
    assert body["kind"] == "quote"
    assert body["spans"]
    span = body["spans"][0]
    assert PAPER_TEXT[span["start"] : span["end"]] == span["text"]


def test_context_falls_back_to_section(client):
    body = client.get("/api/claims/c_s/context").json()
    assert body["kind"] == "section"
    assert body["section"]["name"] == "discussion"
    assert "coating precedes silencing" in body["section"]["text"]
    assert 0 < body["section"]["fraction_of_paper"] < 1


def test_chunks_search(client):
    body = client.get("/api/chunks?text=A-repeat").json()
    assert body["items"]
    assert "A-repeat" in body["items"][0]["text"]


def test_papers_list(client):
    body = client.get("/api/papers").json()
    assert body["total"] == 1
    assert body["items"][0]["paper_id"] == "p1"


def test_paper_detail_and_claims(client):
    body = client.get("/api/papers/p1").json()
    assert body["paper_id"] == "p1"
    assert len(body["claims"]) == 2


def test_paper_detail_unknown(client):
    body = client.get("/api/papers/nope").json()
    assert "error" in body


def test_stats(client):
    body = client.get("/api/stats").json()
    assert body["tables"]["claims"] == 2
    assert any(t["tier"] == "P1" for t in body["tiers"])


def test_export_csv(client):
    r = client.get("/api/export?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "c_p1" in r.text


def test_export_json(client):
    r = client.get("/api/export?format=json")
    assert r.status_code == 200
    assert "c_p1" in r.text


def test_annotation_roundtrip(client):
    r = client.post(
        "/api/claims/c_p1/annotations",
        json={"verdict": "correct", "note": "matches Fig 1", "annotator": "luyx"},
    )
    assert r.status_code == 200
    assert r.json()["verdict"] == "correct"

    listing = client.get("/api/annotations").json()
    assert listing["total"] == 1
    assert listing["counts"]["correct"] == 1

    detail = client.get("/api/claims/c_p1").json()
    assert detail["annotation"]["verdict"] == "correct"
    assert detail["annotation"]["note"] == "matches Fig 1"


def test_annotation_bad_verdict_is_rejected(client):
    r = client.post("/api/claims/c_p1/annotations", json={"verdict": "maybe"})
    assert r.status_code >= 400


def test_annotation_unknown_claim(client):
    body = client.post("/api/claims/nope/annotations", json={"verdict": "correct"}).json()
    assert "error" in body


def test_api_key_required_when_set(client, monkeypatch):
    monkeypatch.setenv("XIST_KB_API_KEY", "s3cret")
    assert client.get("/api/claims").status_code == 401
    assert client.get("/api/claims", headers={"x-api-key": "s3cret"}).status_code == 200


def test_health_stays_public_with_key_set(client, monkeypatch):
    monkeypatch.setenv("XIST_KB_API_KEY", "s3cret")
    assert client.get("/api/health").status_code == 200


def test_ip_allowlist_denies_outside(client, monkeypatch):
    # TestClient connects from "testclient", which is not an IP -> 403
    monkeypatch.setenv("XIST_KB_ALLOWED_NETS", "10.0.0.0/8")
    assert client.get("/api/claims").status_code == 403


def test_malformed_network_entry_is_a_hard_error(client, monkeypatch):
    monkeypatch.setenv("XIST_KB_ALLOWED_NETS", "not-a-network")
    with pytest.raises(RuntimeError, match="invalid network"):
        client.get("/api/claims")


class TestAsk:
    """The ask endpoint must return evidence even with no model configured."""

    def test_returns_evidence_without_api_key(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        body = client.get("/api/ask?q=XIST").json()
        assert body["answer"] is None
        assert "ANTHROPIC_API_KEY" in body["error"]
        assert body["chunks"]

    def test_budget_endpoint(self, client):
        body = client.get("/api/ask/budget").json()
        assert body["limit_usd"] > 0
        assert body["remaining_usd"] <= body["limit_usd"]

    def test_no_model_call_when_budget_exhausted(self, client, monkeypatch):
        monkeypatch.setenv("XIST_KB_DAILY_TOKEN_BUDGET", "0")
        body = client.get("/api/ask?q=XIST").json()
        assert "预算" in (body["error"] or "")
