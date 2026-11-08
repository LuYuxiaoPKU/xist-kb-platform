"""Process-wide resources the API shares: one DuckDB connection, one text store.

DuckDB connections are not thread-safe, and FastAPI runs sync endpoints in a
thread pool, so every request goes through a lock. Throughput is bounded by
DuckDB's single-writer model anyway; at 115k claims a query is milliseconds, so
the lock costs nothing measurable.

The connection is opened lazily so importing the app (for tests, or for
generating the OpenAPI schema) does not require a built data layer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache

import duckdb

from xist_kb.extract.context import TextStore
from xist_kb.paths import TEXT_DIR
from xist_kb.query.engine import connect


@dataclass
class Resources:
    conn: duckdb.DuckDBPyConnection
    lock: threading.Lock
    texts: TextStore


@lru_cache(maxsize=1)
def resources() -> Resources:
    conn = connect()
    return Resources(conn=conn, lock=threading.Lock(), texts=TextStore.from_map(TEXT_DIR, conn))


def reset() -> None:
    """Drop the cached resources; used by tests after changing env vars."""
    resources.cache_clear()
