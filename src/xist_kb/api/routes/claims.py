"""Claim search, detail, context and annotation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from xist_kb.annotate.store import AnnotationStore
from xist_kb.api.deps import resources
from xist_kb.api.serialize import clean_row, clean_rows
from xist_kb.extract.context import build_context
from xist_kb.paths import SILVER_DIR
from xist_kb.query import search as q
from xist_kb.query.paper_scope import IN_SCOPE

router = APIRouter(prefix="/api", tags=["claims"])


def _annotations() -> AnnotationStore:
    return AnnotationStore(SILVER_DIR / "annotations.parquet")


@router.get("/claims")
def list_claims(
    topic: Annotated[list[str] | None, Query()] = None,
    species: Annotated[list[str] | None, Query()] = None,
    confidence: Annotated[list[str] | None, Query()] = None,
    evidence_type: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    scope: Annotated[list[str] | None, Query()] = None,
    year_from: int | None = None,
    year_to: int | None = None,
    text: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Search claims.

    Scope defaults to the papers that are about XIST/XCI. Omitting the parameter
    means "the knowledge base as it should be read", not "every row in the
    table": 16% of claims come from papers whose full text never mentions the
    subject, and a default that mixes them in would misrepresent the corpus on
    every unfiltered search. Passing `scope=out_of_scope` (or all four values)
    brings them back, so nothing is hidden from a reader who asks.
    """
    res = resources()
    f = q.ClaimFilter(
        topics=topic or [],
        species=species or [],
        confidence=confidence or [],
        evidence_types=evidence_type or [],
        tiers=tier or [],
        scopes=scope if scope else list(IN_SCOPE),
        year_from=year_from,
        year_to=year_to,
        text=text,
        limit=limit,
        offset=offset,
    )
    with res.lock:
        rows, total = q.search_claims(res.conn, f)
        _attach_tiers(res.conn, rows)
        _attach_scope(res.conn, rows)
    return {"total": total, "limit": limit, "offset": offset, "items": clean_rows(rows)}


def _attach_scope(conn, rows: list[dict]) -> None:
    """Join the paper's scope onto each row; absent without paper_scope."""
    if not rows:
        return
    paper_ids = list({r["paper_id"] for r in rows})
    try:
        pairs = conn.execute(
            "SELECT paper_id, scope FROM paper_scope WHERE paper_id IN ("
            + ", ".join("?" for _ in paper_ids)
            + ")",
            paper_ids,
        ).fetchall()
    except Exception:
        return
    scopes = dict(pairs)
    for row in rows:
        row["scope"] = scopes.get(row["paper_id"])


def _attach_tiers(conn, rows: list[dict]) -> None:
    """Join the tier onto each row; absent for a Gold layer without tiers."""
    if not rows:
        return
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


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str) -> dict:
    res = resources()
    with res.lock:
        row = res.conn.execute(
            """
            SELECT c.*, p.title, p.year, p.journal, p.doi,
                   pv.method AS annotation_method,
                   cp.tier, cp.span_start, cp.span_end, cp.span_count,
                   cp.fuzzy_score, cp.section_renderable
            FROM claims c
            LEFT JOIN papers p USING (paper_id)
            LEFT JOIN provenance pv USING (provenance_id)
            LEFT JOIN claim_provenance cp USING (claim_id)
            WHERE c.claim_id = ?
            """,
            [claim_id],
        ).fetchdf()
        if row.empty:
            return {"error": "no such claim", "claim_id": claim_id}
        record = clean_row(row.to_dict("records")[0])
        ann = _annotation_for(res.conn, record)
    record["annotation"] = ann
    return record


def _annotation_for(conn, claim: dict) -> dict | None:
    store = _annotations()
    from xist_kb.annotate.store import annotation_key

    key = annotation_key(claim["paper_id"], claim["claim"], claim.get("quote"))
    ann = store.latest().get(key)
    if ann is None:
        return None
    return {
        "verdict": ann.verdict,
        "note": ann.note,
        "annotator": ann.annotator,
        "created_at": ann.created_at.isoformat(),
    }


@router.get("/claims/{claim_id}/context")
def claim_context(claim_id: str) -> dict:
    """The paper's own words for this claim: a quote span or a section body.

    Returns `kind = quote` with character intervals, `kind = section` with the
    full section text and its size, or `kind = none` with the reason. There is
    no approximate-paragraph kind -- locating a claim to a 700-char window was
    measured at 11.6% accuracy, and offering it would misrepresent the data.
    """
    res = resources()
    with res.lock:
        row = res.conn.execute(
            "SELECT claim_id, paper_id, quote, section FROM claims WHERE claim_id = ?",
            [claim_id],
        ).fetchone()
        if row is None:
            return {"kind": "none", "reason": "no such claim", "claim_id": claim_id}
        text = res.texts.get(row[1])
    result = build_context(row[0], row[1], row[2], row[3], text)
    return result.model_dump(mode="json")


@router.post("/claims/{claim_id}/annotations")
async def annotate(claim_id: str, request: Request) -> dict:
    """Record a reviewer's verdict. Idempotent per (claim, content)."""
    body = await request.json()
    verdict = str(body.get("verdict", "")).strip()
    res = resources()
    with res.lock:
        row = res.conn.execute(
            "SELECT paper_id, claim, quote FROM claims WHERE claim_id = ?", [claim_id]
        ).fetchone()
    if row is None:
        return {"error": "no such claim", "claim_id": claim_id}

    try:
        ann = _annotations().add(
            claim_id=claim_id,
            paper_id=row[0],
            claim=row[1],
            quote=row[2],
            verdict=verdict,
            note=str(body.get("note", "")),
            annotator=str(body.get("annotator", "")),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {
        "annotation_key": ann.annotation_key,
        "claim_id": ann.claim_id,
        "verdict": ann.verdict,
        "created_at": ann.created_at.isoformat(),
    }


@router.get("/annotations")
def list_annotations(paper_id: str | None = None) -> dict:
    store = _annotations()
    latest = store.latest()
    items = [
        {
            "annotation_key": a.annotation_key,
            "claim_id": a.claim_id,
            "paper_id": a.paper_id,
            "verdict": a.verdict,
            "note": a.note,
            "annotator": a.annotator,
            "created_at": a.created_at.isoformat(),
        }
        for a in latest.values()
        if paper_id is None or a.paper_id == paper_id
    ]
    return {"total": len(items), "items": items, "counts": store.counts()}
