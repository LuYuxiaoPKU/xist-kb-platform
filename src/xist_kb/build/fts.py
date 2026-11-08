"""Build the query database: every Gold table materialised, plus the chunk FTS index.

Why materialise instead of view: DuckDB cannot create views on a read-only
connection, and the FTS index forces the database to be opened read-only if a
second process is to share it. So the database carries its own copy of every
table and is opened read-only by every reader.

Cost measured on the full corpus:
  load        2.5 s
  FTS index  16.2 s
  file       1.33 GB (chunks dominate; the seven metadata tables add ~40 MB)

The file is derived data: `scripts/rebuild_index.py` regenerates it after any
migration, and deleting it makes the API fall back to views over Parquet (no
BM25 ranking).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import duckdb

from xist_kb.query.engine import GOLD_TABLES

log = logging.getLogger("index")

FTS_TABLE = "chunks"
FTS_KEY = "chunk_id"
FTS_COLUMNS = ["text"]


def build(gold_dir: Path, db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".duckdb.tmp")
    for stale in (tmp, tmp.with_name(tmp.name + ".wal")):
        if stale.exists():
            stale.unlink()

    conn = duckdb.connect(str(tmp))
    started = time.time()
    loaded: dict[str, int] = {}
    for name in GOLD_TABLES:
        parquet = gold_dir / f"{name}.parquet"
        if not parquet.exists():
            log.warning("skipping %s: no parquet", name)
            continue
        conn.execute(
            f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{parquet.as_posix()}')"
        )
        count_row = conn.execute(f"SELECT count(*) FROM {name}").fetchone()
        loaded[name] = int(count_row[0]) if count_row else 0
    load_seconds = time.time() - started

    started = time.time()
    conn.execute(
        f"PRAGMA create_fts_index('{FTS_TABLE}', '{FTS_KEY}', "
        f"'{', '.join(FTS_COLUMNS)}', overwrite=1)"
    )
    index_seconds = time.time() - started

    conn.execute("CHECKPOINT")
    conn.close()
    os.replace(tmp, db_path)

    return {
        "tables": loaded,
        "load_seconds": round(load_seconds, 1),
        "index_seconds": round(index_seconds, 1),
        "db_bytes": db_path.stat().st_size,
    }


if __name__ == "__main__":
    import json

    data = Path(os.environ["XIST_KB_DATA"])
    gold = data / "gold" if (data / "gold").is_dir() else data
    report = build(gold, data / "index" / "xist.duckdb")
    print(json.dumps(report, indent=1, ensure_ascii=False))
