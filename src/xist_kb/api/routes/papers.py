"""Paper, chunk, side-table, stats and export endpoints."""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from xist_kb import ask as asker
from xist_kb.api.deps import resources
from xist_kb.api.serialize import clean_rows
from xist_kb.query import search as q
from xist_kb.query.aggregate import visualizing_payload

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers")
def list_papers(
    status: Annotated[list[str] | None, Query()] = None,
    year_from: int | None = None,
    year_to: int | None = None,
    text: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    res = resources()
    f = q.PaperFilter(
        status=status or [],
        year_from=year_from,
        year_to=year_to,
        text=text,
        limit=limit,
        offset=offset,
    )
    with res.lock:
        rows, total = q.search_papers(res.conn, f)
    return {"total": total, "limit": limit, "offset": offset, "items": clean_rows(rows)}


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str) -> dict:
    res = resources()
    with res.lock:
        paper = q.get_paper(res.conn, paper_id.lower())
        if paper is None:
            return {"error": "no such paper", "paper_id": paper_id}
        paper["claims"] = q.get_claims_for_paper(res.conn, paper_id.lower())
    return paper


@router.get("/papers/{paper_id}/claims")
def paper_claims(paper_id: str) -> dict:
    res = resources()
    with res.lock:
        rows = q.get_claims_for_paper(res.conn, paper_id.lower())
    return {"paper_id": paper_id, "total": len(rows), "items": clean_rows(rows)}


@router.get("/chunks")
def search_chunks(
    text: Annotated[str, Query(min_length=2)],
    paper_id: Annotated[list[str] | None, Query()] = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Full-text search over sentence windows, ranked by BM25 when indexed."""
    res = resources()
    f = q.ChunkFilter(
        text=text,
        paper_ids=paper_id or [],
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        offset=offset,
    )
    with res.lock:
        rows, total = q.search_chunks(res.conn, f)
    return {"total": total, "limit": limit, "offset": offset, "items": clean_rows(rows)}


@router.get("/interactors")
def interactors(protein: str | None = None) -> dict:
    res = resources()
    with res.lock:
        rows = q.get_interactors(res.conn, protein)
    return {"total": len(rows), "items": clean_rows(rows)}


@router.get("/regulations")
def regulations(
    regulator: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    res = resources()
    where, params = "", []
    if regulator:
        where = "WHERE regulator ILIKE ?"
        params = [f"%{regulator}%"]
    with res.lock:
        rows = res.conn.execute(
            f"SELECT * FROM regulations {where} ORDER BY regulator LIMIT ?",
            [*params, limit],
        ).fetchdf()
    return {"total": len(rows), "items": clean_rows(rows.to_dict("records"))}


@router.get("/xci_status")
def xci_status(
    species: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    res = resources()
    where, params = "", []
    if species:
        where = "WHERE species ILIKE ?"
        params = [f"%{species}%"]
    with res.lock:
        rows = res.conn.execute(
            f"SELECT * FROM xci_status {where} ORDER BY species LIMIT ?",
            [*params, limit],
        ).fetchdf()
    return {"total": len(rows), "items": clean_rows(rows.to_dict("records"))}


@router.get("/visualize")
def visualize() -> dict:
    """Aggregations for the charts page: interactors, species, years, marks."""
    res = resources()
    with res.lock:
        return visualizing_payload(res.conn)


@router.get("/ask")
def ask(
    q_: Annotated[str, Query(alias="q", min_length=3)],
) -> dict:
    """Answer a question from retrieved claims and paper text.

    Returns the retrieved evidence even when no answer is generated -- an
    unavailable model must leave the reader with something to inspect, not an
    empty page.
    """
    res = resources()
    with res.lock:
        result = asker.answer(res.conn, q_)
    return {
        **result,
        "claims": clean_rows(result["claims"]),
        "chunks": clean_rows(result["chunks"]),
    }


@router.get("/ask/budget")
def ask_budget() -> dict:
    return asker.budget_remaining()


@router.get("/stats")
def stats() -> dict:
    res = resources()
    with res.lock:
        payload = q.stats(res.conn)
        counts = {}
        for table in ("papers", "claims", "chunks", "claim_provenance"):
            try:
                row = res.conn.execute(f"SELECT count(*) FROM {table}").fetchone()
                counts[table] = int(row[0]) if row else 0
            except Exception:
                counts[table] = 0
        try:
            tier_rows = res.conn.execute(
                "SELECT tier, count(*) FROM claim_provenance GROUP BY tier ORDER BY 2 DESC"
            ).fetchall()
            payload["tiers"] = [{"tier": t, "count": n} for t, n in tier_rows]
        except Exception:
            payload["tiers"] = []
    payload["tables"] = counts
    return payload


@router.get("/export")
def export(
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv",
    topic: Annotated[list[str] | None, Query()] = None,
    species: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    text: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 5_000,
) -> StreamingResponse:
    """Export matching claims. Capped at 50k rows by default."""
    res = resources()
    f = q.ClaimFilter(
        topics=topic or [],
        species=species or [],
        tiers=tier or [],
        text=text,
        limit=limit,
        offset=0,
    )
    with res.lock:
        rows, _ = q.search_claims(res.conn, f)
        if rows:
            _attach_tiers(res.conn, rows)

    if format == "json":
        import json as jsonlib

        body = jsonlib.dumps(rows, ensure_ascii=False, default=str)
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="claims.json"'},
        )

    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(v) for k, v in row.items()})
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="claims.csv"'},
    )


def _csv_value(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return value


def _attach_tiers(conn, rows: list[dict]) -> None:
    ids = [r["claim_id"] for r in rows]
    try:
        pairs = conn.execute(
            "SELECT claim_id, tier FROM claim_provenance WHERE claim_id IN ("
            + ", ".join("?" for _ in ids)
            + ")",
            ids,
        ).fetchall()
    except Exception:
        return
    tiers = dict(pairs)
    for row in rows:
        row["tier"] = tiers.get(row["claim_id"])
