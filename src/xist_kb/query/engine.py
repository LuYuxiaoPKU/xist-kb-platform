"""DuckDB access to the Gold layer.

One connection per process, views over the Parquet files rather than copies,
so a re-run of the migration is visible to the next query with no reload step.
"""

from __future__ import annotations

import duckdb

from xist_kb.paths import GOLD_DIR

GOLD_TABLES = (
    "papers",
    "claims",
    "provenance",
    "interactors",
    "regulations",
    "xci_status",
    "species_xist",
    "paper_id_map",
)

# Tables the query layer can run without. A missing one is not fatal, so a
# Gold directory built before the table existed still opens.
OPTIONAL_TABLES = frozenset({"paper_id_map"})


def connect(gold_dir=None, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with a view per Gold table.

    In-memory because there is nothing to persist: the views point at Parquet,
    and a file-backed database would need invalidating after every migration.
    """
    gold = gold_dir or GOLD_DIR
    if not gold.exists():
        raise FileNotFoundError(f"gold layer not built yet: {gold}")

    conn = duckdb.connect(":memory:", read_only=False)
    for name in GOLD_TABLES:
        path = gold / f"{name}.parquet"
        if not path.exists():
            if name in OPTIONAL_TABLES:
                continue
            raise FileNotFoundError(f"missing {path}; run the migration first")
        conn.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')"
        )
    return conn


def describe(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row count per Gold table."""
    counts: dict[str, int] = {}
    for name in GOLD_TABLES:
        try:
            row = conn.execute(f"SELECT count(*) FROM {name}").fetchone()
        except duckdb.CatalogException:
            continue  # optional table absent
        counts[name] = int(row[0]) if row else 0
    return counts
