"""Filesystem layout for the knowledge base.

Every module resolves paths through here so a single environment variable
(XIST_KB_DATA) can relocate the data tree — the server deployment keeps data
outside the checkout, since Parquet and PDFs must never enter git.

The .env beside the checkout is loaded once at import so command-line runs
pick up XIST_KB_DATA without the caller having to export it first.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DOTENV = PROJECT_ROOT / ".env"
if _DOTENV.exists():
    load_dotenv(_DOTENV, override=False)

DATA_DIR = Path(os.environ.get("XIST_KB_DATA") or PROJECT_ROOT / "data")

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
