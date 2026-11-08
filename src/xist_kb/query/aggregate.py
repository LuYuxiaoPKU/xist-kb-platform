"""Aggregations for the visualization page.

Everything here is a GROUP BY over the side tables; the frontend draws bars and
nothing more. One call returns all panels so the page loads in one round trip
instead of four.

`xci_status.chromatin_marks` holds a stringified Python dict per paper
(`"{'h3k27me3': 'not reported', ...}"`) rather than a mark list -- that is how
V2 stored it and the migration preserved the value verbatim. Parsing it here
keeps the stored form intact while still letting the chart count actual marks.
"""

from __future__ import annotations

import ast
from collections import Counter

import duckdb

# The four marks V2's annotation template asks about. Counted separately from
# whatever free text came back, because "not reported" is not a mark.
TRACKED_MARKS = ("h3k27me3", "h2ak119ub", "macroh2a", "dna_methylation")

_NOT_REPORTED = frozenset(
    {"", "not reported", "not_reported", "none", "n/a", "na", "unknown", "null"}
)


def _mark_value(raw: str) -> dict[str, str]:
    """Parse one stored dict, tolerating V2's non-JSON formatting."""
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in parsed.items() if v is not None}


def _is_reported(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in _NOT_REPORTED


def visualizing_payload(conn: duckdb.DuckDBPyConnection, top: int = 15) -> dict:
    interactors = conn.execute(
        """
        SELECT protein, count(*) AS papers, count(DISTINCT paper_id) AS distinct_papers
        FROM interactors
        WHERE protein IS NOT NULL AND protein <> ''
        GROUP BY protein
        ORDER BY papers DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()

    species = conn.execute(
        """
        SELECT species, count(*) AS n
        FROM species_xist
        WHERE species IS NOT NULL AND species <> ''
        GROUP BY species
        ORDER BY n DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()

    years = conn.execute(
        """
        SELECT year, count(*) AS n
        FROM papers
        WHERE year IS NOT NULL AND year BETWEEN 1970 AND 2100
        GROUP BY year
        ORDER BY year
        """
    ).fetchall()

    xci_types = conn.execute(
        """
        SELECT xci_type, count(*) AS n
        FROM xci_status
        WHERE xci_type IS NOT NULL AND xci_type <> ''
        GROUP BY xci_type ORDER BY n DESC LIMIT ?
        """,
        [top],
    ).fetchall()

    # Chromatin marks: parse the stored dicts and count how many papers report
    # each tracked mark, separately from how many report an uninterpretable one.
    mark_counts: Counter[str] = Counter()
    total_papers = 0
    for (entry,) in conn.execute(
        "SELECT chromatin_marks FROM xci_status WHERE chromatin_marks IS NOT NULL"
    ).fetchall():
        # the column is a list: V2 stored one stringified dict per row
        for raw in entry or []:
            values = _mark_value(raw)
            if not values:
                continue
            total_papers += 1
            for mark in TRACKED_MARKS:
                if _is_reported(values.get(mark)):
                    mark_counts[mark] += 1

    return {
        "interactors": [{"protein": p, "claims": n, "papers": d} for p, n, d in interactors],
        "species": [{"species": s, "count": n} for s, n in species],
        "years": [{"year": y, "count": n} for y, n in years],
        "xci_types": [{"xci_type": t, "count": n} for t, n in xci_types],
        "chromatin_marks": [
            {"mark": mark, "papers": mark_counts.get(mark, 0)}
            for mark in TRACKED_MARKS
        ],
        "chromatin_mark_papers": total_papers,
    }
