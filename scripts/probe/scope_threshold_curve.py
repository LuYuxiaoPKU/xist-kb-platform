"""Where to draw the scope line: how many claims survive each density cut.

The measurement is XIST mentions per 10,000 characters of a paper's full text.
Zero means the paper never says the word; a paper about Xist says it hundreds of
times. The question this answers is what each candidate threshold costs in claims
and papers, so the threshold can be chosen from the curve instead of guessed.

Also reports, for the papers each cut would drop, whether they carry any
XIST-adjacent signal at all (Tsix, Xic, inactive X, dosage compensation) -- a
paper that never says "Xist" but does say "inactive X" is about the phenomenon
and must not be dropped.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")

# The wider phenomenon vocabulary. A paper can discuss X inactivation at length
# without naming the transcript -- Drosophila work, or old papers that call it
# "the X-inactivation centre".
PHENOMENON = r"(?i)(tsix|xic\b|x[\s\-]?chromosome inactivation|x[\s\-]?inactivation|inactive x|dosage compensation|lyoniz|barr body)"


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)

    # Count XIST and the wider phenomenon vocabulary in one pass over chunks.
    conn.execute(
        f"""
        CREATE TEMP TABLE dens AS
        SELECT paper_id,
               sum(length(text)) AS chars,
               sum(length(text) - length(regexp_replace(text, '(?i)xist', '', 'g'))) / 4 AS xist,
               sum(length(text) - length(regexp_replace(text, '{PHENOMENON}', '', 'g'))) AS phen_raw
        FROM chunks GROUP BY 1
        """
    )
    # regexp_replace with alternation collapses the whole match to '', so the
    # length loss is the total length of matched text, not a hit count. Counting
    # separately is the honest approach: count occurrences per chunk instead.
    conn.execute("DROP TABLE dens")
    conn.execute(
        """
        CREATE TEMP TABLE dens AS
        SELECT paper_id,
               sum(length(text)) AS chars,
               sum(len(regexp_extract_all(text, '(?i)xist'))) AS xist,
               sum(len(regexp_extract_all(text,
                   '(?i)(tsix|xic|x[\\s-]?chromosome inactivation|x[\\s-]?inactivation|inactive x|dosage compensation|lyoniz|barr body)'
               ))) AS phen
        FROM chunks GROUP BY 1
        """
    )

    total_claims = conn.execute("SELECT count(*) FROM claims").fetchone()[0]
    rows = conn.execute("SELECT count(*) FROM dens").fetchone()[0]

    thresholds = [0, 1, 2, 5, 10, 20]
    curve = []
    for minimum in thresholds:
        stats = conn.execute(
            """
            WITH kept AS (SELECT paper_id FROM dens WHERE xist >= ?),
                 dropped AS (SELECT paper_id FROM dens WHERE xist < ?)
            SELECT
              (SELECT count(*) FROM kept) AS kept_papers,
              (SELECT count(*) FROM claims c JOIN kept k USING (paper_id)) AS kept_claims,
              (SELECT count(*) FROM dropped) AS dropped_papers,
              (SELECT count(*) FROM claims c JOIN dropped d USING (paper_id)) AS dropped_claims,
              (SELECT count(*) FROM claims c JOIN dropped d USING (paper_id)
                 JOIN dens dd USING (paper_id) WHERE dd.phen > 0) AS dropped_but_phenomenon
            """,
            [minimum, minimum],
        ).fetchone()
        curve.append(
            {
                "min_xist_mentions": minimum,
                "kept_papers": stats[0],
                "kept_claims": stats[1],
                "kept_claim_pct": round(100 * stats[1] / total_claims, 2),
                "dropped_papers": stats[2],
                "dropped_claims": stats[3],
                "dropped_claim_pct": round(100 * stats[3] / total_claims, 2),
                "dropped_claims_with_phenomenon_words": stats[4],
            }
        )

    # Papers with no text at all cannot be judged; list them separately.
    no_text = conn.execute(
        """
        SELECT count(*), (SELECT count(*) FROM claims c
                          WHERE c.paper_id NOT IN (SELECT paper_id FROM dens))
        FROM papers WHERE paper_id NOT IN (SELECT paper_id FROM dens)
        """
    ).fetchone()

    print(
        json.dumps(
            {
                "papers_with_text": rows,
                "papers_without_text": no_text[0],
                "claims_in_papers_without_text": no_text[1],
                "total_claims": total_claims,
                "curve": curve,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
