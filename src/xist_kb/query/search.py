"""Structured search over claims, papers and side tables.

Filters are applied before text matching, so a query that names a topic and a
species reads only those rows. Every filter is optional; passing none returns
the most recent annotated claims rather than the whole 115k table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb


@dataclass
class ClaimFilter:
    topics: list[str] = field(default_factory=list)
    species: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    confidence: list[str] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)
    text: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class PaperFilter:
    status: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    text: str | None = None
    limit: int = 50
    offset: int = 0


def _in_clause(values: list[str], column: str, params: list) -> str | None:
    if not values:
        return None
    placeholders = ", ".join("?" for _ in values)
    params.extend(values)
    return f"{column} IN ({placeholders})"


def _like_clause(text: str | None, columns: list[str], params: list) -> str | None:
    if not text or not text.strip():
        return None
    pattern = f"%{text.strip()}%"
    parts = []
    for column in columns:
        parts.append(f"{column} ILIKE ?")
        params.append(pattern)
    return "(" + " OR ".join(parts) + ")"


def search_claims(conn: duckdb.DuckDBPyConnection, f: ClaimFilter) -> tuple[list[dict], int]:
    """Return matching claims and the total count before pagination.

    The count is a separate query because DuckDB has no window-free way to
    report both in one pass without materialising every row.
    """
    where: list[str] = []
    params: list = []

    if clause := _in_clause(f.topics, "c.topic", params):
        where.append(clause)
    if clause := _in_clause(f.confidence, "c.confidence", params):
        where.append(clause)
    if clause := _in_clause(f.evidence_types, "c.evidence_type", params):
        where.append(clause)
    if f.species:
        # species is a list column; exact membership avoids LIKE over-splitting.
        for sp in f.species:
            where.append("list_contains(c.species, ?)")
            params.append(sp)
    if f.year_from is not None:
        where.append("p.year >= ?")
        params.append(f.year_from)
    if f.year_to is not None:
        where.append("p.year <= ?")
        params.append(f.year_to)
    if clause := _like_clause(f.text, ["c.claim", "c.quote"], params):
        where.append(clause)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM claims c LEFT JOIN papers p USING (paper_id){where_sql}"

    count_row = conn.execute(f"SELECT count(*) {base}", params).fetchone()
    total = int(count_row[0]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT c.claim_id, c.paper_id, c.claim, c.topic, c.evidence_type,
               c.directness, c.section, c.confidence, c.species, c.quote,
               c.quote_offset_start, c.quote_offset_end, c.chunk_id,
               p.title, p.year, p.journal, p.doi
        {base}
        ORDER BY p.year DESC NULLS LAST, c.claim_id
        LIMIT ? OFFSET ?
        """,
        [*params, f.limit, f.offset],
    ).fetchdf()
    return rows.to_dict("records"), total


def search_papers(conn: duckdb.DuckDBPyConnection, f: PaperFilter) -> tuple[list[dict], int]:
    where: list[str] = []
    params: list = []

    if clause := _in_clause(f.status, "status", params):
        where.append(clause)
    if f.year_from is not None:
        where.append("year >= ?")
        params.append(f.year_from)
    if f.year_to is not None:
        where.append("year <= ?")
        params.append(f.year_to)
    if clause := _like_clause(f.text, ["title", "journal", "first_author"], params):
        where.append(clause)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    count_row = conn.execute(f"SELECT count(*) FROM papers{where_sql}", params).fetchone()
    total = int(count_row[0]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT paper_id, title, year, journal, first_author, doi, pmid,
               species, status, has_text, has_pdf, has_annotation
        FROM papers{where_sql}
        ORDER BY year DESC NULLS LAST, paper_id
        LIMIT ? OFFSET ?
        """,
        [*params, f.limit, f.offset],
    ).fetchdf()
    return rows.to_dict("records"), total


def stats(conn: duckdb.DuckDBPyConnection) -> dict:
    """Aggregate counts the web UI's overview page needs."""
    topic_rows = conn.execute(
        "SELECT topic, count(*) AS n FROM claims GROUP BY topic ORDER BY n DESC"
    ).fetchall()
    status_rows = conn.execute(
        "SELECT status, count(*) AS n FROM papers GROUP BY status ORDER BY n DESC"
    ).fetchall()
    confidence_rows = conn.execute(
        "SELECT confidence, count(*) AS n FROM claims GROUP BY confidence ORDER BY n DESC"
    ).fetchall()
    year_rows = conn.execute(
        "SELECT year, count(*) AS n FROM papers WHERE year IS NOT NULL "
        "AND year BETWEEN 1900 AND 2100 GROUP BY year ORDER BY year"
    ).fetchall()
    species_rows = conn.execute(
        """
        SELECT s AS species, count(*) AS n
        FROM (SELECT unnest(species) AS s FROM claims)
        GROUP BY s ORDER BY n DESC LIMIT 25
        """
    ).fetchall()
    return {
        "topics": [{"topic": t, "count": n} for t, n in topic_rows],
        "statuses": [{"status": s, "count": n} for s, n in status_rows],
        "confidence": [{"confidence": c, "count": n} for c, n in confidence_rows],
        "years": [{"year": y, "count": n} for y, n in year_rows],
        "species": [{"species": s, "count": n} for s, n in species_rows],
    }


def get_paper(conn: duckdb.DuckDBPyConnection, paper_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", [paper_id]).fetchdf()
    return None if row.empty else row.to_dict("records")[0]


def get_claims_for_paper(conn: duckdb.DuckDBPyConnection, paper_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.claim_id, c.claim, c.topic, c.evidence_type, c.directness,
               c.section, c.confidence, c.species, c.quote,
               c.quote_offset_start, c.quote_offset_end, c.chunk_id,
               c.provenance_id, pv.method AS annotation_method
        FROM claims c
        LEFT JOIN provenance pv USING (provenance_id)
        WHERE c.paper_id = ?
        ORDER BY c.section, c.claim_id
        """,
        [paper_id],
    ).fetchdf()
    return rows.to_dict("records")


def get_interactors(conn: duckdb.DuckDBPyConnection, protein: str | None = None) -> list[dict]:
    if protein:
        rows = conn.execute(
            "SELECT * FROM interactors WHERE protein ILIKE ? ORDER BY protein",
            [f"%{protein}%"],
        ).fetchdf()
    else:
        rows = conn.execute("SELECT * FROM interactors ORDER BY protein").fetchdf()
    return rows.to_dict("records")
