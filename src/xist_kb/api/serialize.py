"""Row serialization for the API.

DuckDB -> pandas -> dict gives numpy scalars and arrays, which FastAPI's default
encoder rejects (`Unable to serialize unknown type: numpy.ndarray`). Every row
that leaves a route goes through `clean_row` so the JSON encoder only ever sees
Python built-ins.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def clean_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [clean_value(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [clean_value(v) for v in value]
    if isinstance(value, dict):
        return {k: clean_value(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def clean_row(row: dict) -> dict:
    return {k: clean_value(v) for k, v in row.items()}


def clean_rows(rows: list[dict]) -> list[dict]:
    return [clean_row(row) for row in rows]
