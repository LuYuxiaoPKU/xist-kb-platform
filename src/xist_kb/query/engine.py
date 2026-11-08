"""DuckDB access to the Gold layer.

Views over the Parquet files rather than copies, so a re-run of the migration is
visible to the next query with no reload step.

Two modes:

* **In-memory** (default): every Gold table is a view over its Parquet file.
  Fast to open (milliseconds), used by the CLI and tests.
* **Index-backed**: when `index/xist.duckdb` exists, it is opened read-only and
  its materialised `chunks` table brings the BM25 index with it. The rest of
  the tables are still views over Parquet, attached into the same database, so
  a re-migration is picked up without rebuilding the index.

The index database is ~1.3 GB. It is derived data, rebuildable in 20 seconds --
which is why it lives under `index/` rather than `gold/`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from xist_kb.paths import GOLD_DIR, INDEX_DIR

log = logging.getLogger(__name__)

GOLD_TABLES = (
    "papers",
    "claims",
    "provenance",
    "interactors",
    "regulations",
    "xci_status",
    "species_xist",
    "paper_id_map",
    "claim_provenance",
    "paper_scope",
    "species_fill",
    "chunks",
)

# Tables the query layer can run without. A missing one is not fatal, so a
# Gold directory built before the table existed still opens; search features
# degrade (tier filter, scope filter, species fill, full-text) rather than the
# whole API failing.
OPTIONAL_TABLES = frozenset(
    {"paper_id_map", "claim_provenance", "paper_scope", "species_fill", "chunks"}
)

# Materialised into the index database because DuckDB can only build an FTS
# index on a table; every other table stays a view.
MATERIALISED = frozenset({"chunks"})


def index_path() -> Path:
    return INDEX_DIR / "xist.duckdb"


def connect(gold_dir=None, index_file: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open the query database: index-backed when available, else in-memory.

    When `index/xist.duckdb` exists it already contains every Gold table (built
    by `build/fts.py`), so it is opened read-only and used as-is -- many
    processes can share it, and no views are needed. DuckDB cannot create views
    on a read-only connection, which is why the index builder materialises
    everything rather than leaving views over Parquet.

    Without the index, views over the Parquet files are created in memory.
    Full-text search then falls back to LIKE (no BM25 ranking).
    """
    gold = Path(gold_dir) if gold_dir else GOLD_DIR
    if not gold.exists():
        raise FileNotFoundError(f"gold layer not built yet: {gold}")

    index = index_file if index_file is not None else index_path()
    if index.exists():
        conn = duckdb.connect(str(index), read_only=True)
        if has_table(conn, "claims"):
            return conn
        conn.close()  # an older index without the tables; fall through

    conn = duckdb.connect(":memory:")
    for name in GOLD_TABLES:
        parquet = gold / f"{name}.parquet"
        if not parquet.exists():
            if name in OPTIONAL_TABLES:
                continue
            raise FileNotFoundError(f"missing {parquet}; run the migration first")
        conn.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{parquet.as_posix()}')"
        )
    return conn


def has_table(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Whether a table is queryable on this connection.

    Public because callers other than `connect` need it: an optional table like
    `paper_scope` can be missing on an older Gold layer, and the query that
    would use it has to choose a different SQL rather than raise.
    """
    try:
        conn.execute(f"SELECT 1 FROM {name} LIMIT 0")
        return True
    except duckdb.Error:
        return False


def describe(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row count per Gold table."""
    counts: dict[str, int] = {}
    for name in GOLD_TABLES:
        try:
            row = conn.execute(f"SELECT count(*) FROM {name}").fetchone()
        except duckdb.Error:
            continue  # optional table absent
        counts[name] = int(row[0]) if row else 0
    return counts
