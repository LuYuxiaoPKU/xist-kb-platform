"""Filesystem layout for the knowledge base.

Every module resolves paths through here so a single environment variable
(XIST_KB_DATA) can relocate the data tree — the server deployment keeps data
outside the checkout, since Parquet and PDFs must never enter git.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("XIST_KB_DATA", PROJECT_ROOT / "data"))

BRONZE_DIR = DATA_DIR / "bronze"  # raw API responses, gzipped JSONL
SILVER_DIR = DATA_DIR / "silver"  # normalized entity tables
GOLD_DIR = DATA_DIR / "gold"  # query-ready claims/papers/chunks
INDEX_DIR = DATA_DIR / "index"  # DuckDB views and FTS indexes


def layer_dir(layer: str) -> Path:
    """Return the directory for a data layer, raising on unknown names."""
    dirs = {
        "bronze": BRONZE_DIR,
        "silver": SILVER_DIR,
        "gold": GOLD_DIR,
        "index": INDEX_DIR,
    }
    try:
        return dirs[layer]
    except KeyError:
        raise ValueError(f"unknown data layer {layer!r}; expected one of {sorted(dirs)}") from None


def ensure_layer(layer: str) -> Path:
    """Create and return a layer directory."""
    path = layer_dir(layer)
    path.mkdir(parents=True, exist_ok=True)
    return path
