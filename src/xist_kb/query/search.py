"""Structured search over claims, papers and side tables.

Filters are applied before text matching, so a query that names a topic and a
species reads only those rows. Every filter is optional; passing none returns
the most recent annotated claims rather than the whole 115k table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb

from xist_kb.query.engine import has_table
from xist_kb.query.paper_scope import SCOPE_LABELS


@dataclass
class ClaimFilter:
    topics: list[str] = field(default_factory=list)
    species: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    confidence: list[str] = field(default_factory=list)
    evidence_types: list[str] = field(default_factory=list)
    tiers: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    text: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class ChunkFilter:
    """Full-text search over sentence windows.

    Separate from ClaimFilter because it searches the papers, not the
    annotations: a query for "A-repeat" should surface the sentence even when
    no claim was ever extracted from it. Measured on 800k windows: LIKE 280ms,
    FTS with BM25 ranking 300ms -- the ranking is why FTS is preferred, not the
    speed.

    `exact_total` is off by default because counting matches costs as much as
    the search itself (a second BM25 pass over the whole table). With it off,
    `total` is the number of rows on this page, and the UI says "showing 50"
    instead of blocking a second to learn the true count.
    """

    text: str
    paper_ids: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 50
    offset: int = 0
    exact_total: bool = False


@dataclass
class PaperFilter:
    status: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    text: str | None = None
    limit: int = 50
    offset: int = 0


def _to_dicts(rows: list[tuple], columns: list[str]) -> list[dict]:
    """Rows as dicts, without pandas.

    `fetchdf()` cost 718 ms for a 50-row join over these tables against 30 ms
    for `fetchall()`: pandas' type inference over the nested list columns
    dominates. Rows are serialized field by field downstream anyway.

    `rows` must already be fetched. DuckDB's `execute` returns the connection
    itself, so holding a pending result across a second `execute` on the same
    connection silently yields the newer query's rows -- and `fetchall()`
    returns a bare list, discarding the column names with it.
    """
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _fetch(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list
) -> tuple[list[tuple], list[str]]:
    """Execute and return (rows, column names) in one shot."""
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return cursor.fetchall(), columns


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
    if f.tiers:
        # tiers live in the derived claim_provenance table
        where.append(
            "c.claim_id IN (SELECT claim_id FROM claim_provenance WHERE tier IN ("
            + ", ".join("?" for _ in f.tiers)
            + "))"
        )
        params.extend(f.tiers)
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
    if f.scopes:
        # Scope is a property of the paper, not the claim: a claim from a paper
        # whose full text never mentions Xist is about something else, however
        # it is labelled. When paper_scope has not been built the filter cannot
        # be satisfied, and the honest answer is no rows -- but returning an
        # error would take down every scope-defaulted query on an older Gold
        # layer, so the absence is checked here rather than raised.
        if has_table(conn, "paper_scope"):
            where.append(
                "c.paper_id IN (SELECT paper_id FROM paper_scope WHERE scope IN ("
                + ", ".join("?" for _ in f.scopes)
                + "))"
            )
            params.extend(f.scopes)
        else:
            where.append("FALSE")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM claims c LEFT JOIN papers p USING (paper_id){where_sql}"

    count_row = conn.execute(f"SELECT count(*) {base}", params).fetchone()
    total = int(count_row[0]) if count_row else 0

    rows, cols = _fetch(conn,
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
    )
    return _to_dicts(rows, cols), total


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

    rows, cols = _fetch(conn,
        f"""
        SELECT paper_id, title, year, journal, first_author, doi, pmid,
               species, status, has_text, has_pdf, has_annotation
        FROM papers{where_sql}
        ORDER BY year DESC NULLS LAST, paper_id
        LIMIT ? OFFSET ?
        """,
        [*params, f.limit, f.offset],
    )
    return _to_dicts(rows, cols), total


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
    scope_rows, scope_claims = _scope_stats(conn)
    return {
        "topics": [{"topic": t, "count": n} for t, n in topic_rows],
        "statuses": [{"status": s, "count": n} for s, n in status_rows],
        "confidence": [{"confidence": c, "count": n} for c, n in confidence_rows],
        "years": [{"year": y, "count": n} for y, n in year_rows],
        "species": [{"species": s, "count": n} for s, n in species_rows],
        "scopes": scope_rows,
        "scope_claims": scope_claims,
    }


def _scope_stats(conn: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict]]:
    """Paper counts and claim counts per scope.

    Claim counts are attributed through the claim's paper, so a paper-level
    judgement becomes a claim-level one without duplicating the decision into
    every claim row. Returns empty lists when paper_scope has not been built --
    the overview page then shows no scope panel rather than zeros.
    """
    try:
        paper_rows = conn.execute(
            "SELECT scope, count(*) FROM paper_scope GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        claim_rows = conn.execute(
            """
            SELECT s.scope, count(*) AS n
            FROM claims c JOIN paper_scope s USING (paper_id)
            GROUP BY 1 ORDER BY 2 DESC
            """
        ).fetchall()
    except duckdb.CatalogException:
        return [], []
    claim_map = {scope: n for scope, n in claim_rows}
    papers = [
        {"scope": s, "label": SCOPE_LABELS.get(s, s), "count": n} for s, n in paper_rows
    ]
    claims = [
        {"scope": s, "label": SCOPE_LABELS.get(s, s), "count": claim_map.get(s, 0)}
        for s, _ in paper_rows
    ]
    return papers, claims


def get_paper(conn: duckdb.DuckDBPyConnection, paper_id: str) -> dict | None:
    rows, cols = _fetch(conn, "SELECT * FROM papers WHERE paper_id = ?", [paper_id])
    records = _to_dicts(rows, cols)
    return records[0] if records else None


_CLAIM_PAPER_COLUMNS = [
    "claim_id", "claim", "topic", "evidence_type", "directness", "section",
    "confidence", "species", "quote", "quote_offset_start", "quote_offset_end",
    "chunk_id", "provenance_id", "annotation_method",
]


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
    ).fetchall()
    return _to_dicts(rows, _CLAIM_PAPER_COLUMNS)


def get_interactors(conn: duckdb.DuckDBPyConnection, protein: str | None = None) -> list[dict]:
    if protein:
        rows, cols = _fetch(
            conn,
            "SELECT * FROM interactors WHERE protein ILIKE ? ORDER BY protein",
            [f"%{protein}%"],
        )
    else:
        rows, cols = _fetch(conn, "SELECT * FROM interactors ORDER BY protein", [])
    return _to_dicts(rows, cols)


def search_chunks(conn: duckdb.DuckDBPyConnection, f: ChunkFilter) -> tuple[list[dict], int]:
    """Search sentence windows, ranked by BM25 when the FTS index is present.

    Two paths, same result shape:

    * FTS (preferred): `fts_main_chunks` is built by `build/fts.py`. It ranks
      by BM25, so "A-repeat" surfaces the sentences that are *about* the
      A-repeat, not the first 50 by paper id.
    * LIKE (fallback): works on a fresh checkout before the index is built.

    The index cannot be queried through an alias in the SELECT list -- DuckDB
    rejects that as "expression has side effects" -- hence the subquery form.
    """
    params: list = []
    extra: list[str] = []
    if f.paper_ids:
        extra.append("paper_id IN (" + ", ".join("?" for _ in f.paper_ids) + ")")
        params.extend(f.paper_ids)
    if f.year_from is not None:
        extra.append("paper_id IN (SELECT paper_id FROM papers WHERE year >= ?)")
        params.append(f.year_from)
    if f.year_to is not None:
        extra.append("paper_id IN (SELECT paper_id FROM papers WHERE year <= ?)")
        params.append(f.year_to)
    filter_sql = (" AND " + " AND ".join(extra)) if extra else ""

    match_fn = _fts_match_function(conn)
    if match_fn:
        try:
            return _fts_search(conn, f, match_fn, filter_sql, params)
        except duckdb.Error:
            pass  # index present but unusable for this query; fall through

    pattern = f"%{f.text.strip()}%"
    where = f"WHERE text ILIKE ?{filter_sql}"
    cursor = conn.execute(
        f"""
        SELECT chunk_id, paper_id, chunk_index, start, "end", text, NULL::DOUBLE AS score
        FROM chunks {where}
        ORDER BY paper_id, chunk_index
        LIMIT ? OFFSET ?
        """,
        [pattern, *params, f.limit, f.offset],
    )
    columns = [d[0] for d in cursor.description]
    page = cursor.fetchall()
    if not f.exact_total:
        return _to_dicts(page, columns), len(page)
    total_row = conn.execute(
        f"SELECT count(*) FROM chunks {where}", [pattern, *params]
    ).fetchone()
    return _to_dicts(page, columns), int(total_row[0]) if total_row else 0


def _chunk_total(
    page_rows: list, conn, f: ChunkFilter, match_fn: str, filter_sql: str, params: list
) -> int:
    if not f.exact_total:
        return len(page_rows)  # the page size, not the true match count
    row = conn.execute(
        f"SELECT count(*) FROM chunks WHERE {match_fn}(chunk_id, ?) IS NOT NULL{filter_sql}",
        [f.text, *params],
    ).fetchone()
    return int(row[0]) if row else 0


# FTS returns a lexeme bag: quotes, AND/OR and hyphens are all stripped before
# matching, so "A-repeat" retrieves every chunk containing "repeat" anywhere --
# 37,013 of them, ranked by an unrelated G-repeat sentence first. The fix is to
# re-rank the BM25 candidates by what the user actually typed: exact substring
# first, then all words present, then the rest.
_FTS_CANDIDATES = 400


def _fts_search(
    conn: duckdb.DuckDBPyConnection,
    f: ChunkFilter,
    match_fn: str,
    filter_sql: str,
    params: list,
) -> tuple[list[dict], int]:
    needle = f.text.strip().strip('"')

    # A literal hit is always a better answer than a lexeme match, and there are
    # usually few enough of them to rank exactly. Measured: "A-repeat" has 1,394
    # literal occurrences, but BM25's top 400 candidates contain none of them --
    # the index matched "repeat" alone (37,013 chunks) and buried the phrase.
    literal_total = conn.execute(
        f"SELECT count(*) FROM chunks WHERE text ILIKE ?{filter_sql}",
        [f"%{needle}%", *params],
    ).fetchone()
    if literal_total and int(literal_total[0]) > 0:
        cursor = conn.execute(
            f"""
            SELECT chunk_id, paper_id, chunk_index, start, "end", text,
                   {match_fn}(chunk_id, ?) AS score
            FROM chunks
            WHERE text ILIKE ?{filter_sql}
            ORDER BY score DESC NULLS LAST, paper_id, chunk_index
            LIMIT ? OFFSET ?
            """,
            [f.text, f"%{needle}%", *params, f.limit, f.offset],
        )
        columns = [d[0] for d in cursor.description]
        return _to_dicts(cursor.fetchall(), columns), int(literal_total[0])

    # No literal occurrence: the query is a genuine keyword search, and BM25
    # ranking is exactly what is wanted.
    cursor = conn.execute(
        f"""
        SELECT chunk_id, paper_id, chunk_index, start, "end", text,
               {match_fn}(chunk_id, ?) AS score
        FROM chunks
        WHERE {match_fn}(chunk_id, ?) IS NOT NULL{filter_sql}
        ORDER BY score DESC
        LIMIT ? OFFSET ?
        """,
        [f.text, f.text, *params, f.limit, f.offset],
    )
    columns = [d[0] for d in cursor.description]
    page = _to_dicts(cursor.fetchall(), columns)

    total_row = conn.execute(
        f"SELECT count(*) FROM chunks WHERE {match_fn}(chunk_id, ?) IS NOT NULL{filter_sql}",
        [f.text, *params],
    ).fetchone()
    total = int(total_row[0]) if total_row else 0
    return _rerank(page, f.text)[f.offset : f.offset + f.limit], total


def _rerank(rows: list[dict], query: str) -> list[dict]:
    """Order BM25 candidates by how literally they contain the query.

    Tiers, in order:
      0  the query appears verbatim (case-insensitive)
      1  every whitespace/AND-separated term appears
      2  anything else BM25 returned

    Within a tier the BM25 score orders the rows, so relevance ranking survives
    for queries that are genuinely keyword searches.
    """
    needle = query.strip().strip('"').lower()
    terms = [t.lower() for t in _QUERY_TERM.findall(needle) if len(t) > 1]

    def key(row: dict) -> tuple[int, float]:
        haystack = row["text"].lower()
        if needle and needle in haystack:
            return 0, -(row.get("score") or 0)
        if terms and all(term in haystack for term in terms):
            return 1, -(row.get("score") or 0)
        return 2, -(row.get("score") or 0)

    return sorted(rows, key=key)


_QUERY_TERM = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")


_FTS_FN_CACHE: dict[int, str | None] = {}


def _fts_match_function(conn: duckdb.DuckDBPyConnection) -> str | None:
    """Fully-qualified BM25 function name, or None when there is no index.

    DuckDB registers the FTS scalar as `fts_main_<table>.match_bm25`, and an
    index built in an attached database keeps that database's namespace:
    `idx.fts_main_chunks.match_bm25`. Both spellings are probed because which
    one exists depends on whether the index file was attached or opened
    directly.
    """
    key = id(conn)
    if key in _FTS_FN_CACHE:
        return _FTS_FN_CACHE[key]
    result: str | None = None
    for candidate in ("fts_main_chunks", "idx.fts_main_chunks"):
        try:
            # LIMIT 0 keeps the probe from scoring any row: the probe is
            # checking whether the function resolves, not what it returns.
            conn.execute(f"SELECT {candidate}.match_bm25(chunk_id, 'probe') FROM chunks LIMIT 0")
        except duckdb.Error:
            continue
        result = f"{candidate}.match_bm25"
        break
    _FTS_FN_CACHE[key] = result
    return result
