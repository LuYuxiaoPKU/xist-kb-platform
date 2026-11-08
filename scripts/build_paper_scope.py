"""Build gold/paper_scope.parquet: which papers belong in this knowledge base.

The corpus was assembled by keyword search, so it contains papers about MALAT1,
TERRA, DDX39B in mRNA export, and radiotherapy dosimetry -- anything whose
abstract or full text brushed the query. Annotation then extracted claims from
those papers faithfully, and 16% of the corpus is statements about something
other than XIST or X inactivation. That is not a classification error: the
misclassification story would say "ROS production" belongs in a different topic,
but no topic in the vocabulary is about ROS production, and the claim genuinely
is what its paper says.

So scope is recorded per paper, not per claim, and the evidence is the paper's
own full text:

``xist``
    The text names Xist. Whatever the claims are phrased as -- "Repeat A RNA",
    "the A-repeat" -- they are about this knowledge base's subject.

``phenomenon_only``
    No mention of Xist, but the text discusses X inactivation, the inactive X,
    Tsix, the Xic, dosage compensation or lyonization. Drosophila MSL work and
    older X-inactivation papers live here; their claims are in scope even though
    the transcript is never named.

``out_of_scope``
    Neither. The paper's text contains no XIST/XCI vocabulary at all, so no claim
    from it can be about the subject.

``unknown``
    The paper has no extracted text. Absence of evidence is not evidence of
    absence: these 283k registered-but-unparsed papers are left unjudged rather
    than declared out of scope.

Measured on the current corpus:

    xist              8,932 papers   84,295 claims
    phenomenon_only   1,585 papers   11,983 claims
    out_of_scope      2,982 papers   18,964 claims  (16.4% of all claims)
    unknown         283,407 papers      432 claims

The `unknown` majority is the registration-only layer: papers.csv lists far more
papers than the PDF archive covers. Only 13,499 papers have text, and those hold
99.6% of the claims, so the scope judgement covers essentially the whole
annotated corpus.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

from xist_kb.query.paper_scope import (  # noqa: E402
    PAPER_SCOPE_SCHEMA,
    PHENOMENON_PATTERN,
    SCOPE_REASONS,
    XIST_PATTERN,
    classify,
)


def build(conn: duckdb.DuckDBPyConnection, out_path: Path) -> dict:
    """Compute per-paper scope from the chunks table and write the parquet."""
    # strftime-free formatting: the pattern strings contain backslashes that
    # DuckDB's regex engine needs verbatim, so they are passed as parameters
    # rather than interpolated into the SQL text.
    # The ids come from papers UNION chunks: 71 text files have no papers.csv
    # entry (their stems are raw DOIs), and leaving them out would report them as
    # unjudged when their text is right there. None of the 71 carries a claim, so
    # the omission was not distorting the counts -- but a scope table that cannot
    # answer "is this paper in scope?" for a paper whose text it holds is wrong
    # on its own terms.
    rows = conn.execute(
        """
        WITH ids AS (
            SELECT paper_id FROM papers
            UNION
            SELECT DISTINCT paper_id FROM chunks
        ),
        dens AS (
            SELECT paper_id,
                   sum(length(text)) AS text_chars,
                   sum(len(regexp_extract_all(text, ?))) AS xist,
                   sum(len(regexp_extract_all(text, ?))) AS phen
            FROM chunks
            GROUP BY 1
        )
        SELECT i.paper_id,
               coalesce(d.text_chars, 0),
               coalesce(d.xist, 0),
               coalesce(d.phen, 0)
        FROM ids i LEFT JOIN dens d USING (paper_id)
        """,
        [XIST_PATTERN, PHENOMENON_PATTERN],
    ).fetchall()

    records: list[dict] = []
    tally: dict[str, int] = {}
    for paper_id, chars, xist, phen in rows:
        scope = classify(int(xist), int(phen), int(chars))
        tally[scope] = tally.get(scope, 0) + 1
        records.append(
            {
                "paper_id": paper_id,
                "scope": scope,
                "xist_mentions": int(xist),
                "phenomenon_mentions": int(phen),
                "text_chars": int(chars),
                "xist_per_10k": (10000.0 * xist / chars) if chars else 0.0,
                "reason": SCOPE_REASONS[scope],
            }
        )

    table = pa.Table.from_pylist(records, PAPER_SCOPE_SCHEMA)
    tmp = out_path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out_path)

    return {"papers": len(records), "by_scope": tally, "bytes": out_path.stat().st_size}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data_dir = Path(os.environ.get("XIST_KB_DATA") or "data_local_lowercase")
    gold = data_dir / "gold" if (data_dir / "gold").is_dir() else data_dir
    index = data_dir / "index" / "xist.duckdb"
    if not index.exists():
        raise SystemExit(f"index database not found at {index}; build chunks and the index first")

    conn = duckdb.connect(str(index), read_only=True)
    report = build(conn, gold / "paper_scope.parquet")
    conn.close()

    import json

    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
