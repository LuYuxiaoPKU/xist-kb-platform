"""Profile the papers whose full text never mentions XIST.

If a paper's text never contains "Xist", any claims extracted from it are about
something else -- the extractor was asked for the paper's findings, and the paper
has none about this subject. Those claims are the wrong corpus, not a
misclassification, and no topic assignment can fix them.

This checks the hypothesis from the other side: if the never-mention papers' claims
are dominated by `other` and by a handful of off-topic subjects, the corpus
contains papers that were never in scope. Then B10 becomes a scope filter with a
documented rule, not a 35k-row relabelling exercise.
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)

    # XIST occurrences per paper, counted as length loss from stripping the term.
    conn.execute(
        """
        CREATE TEMP TABLE dens AS
        SELECT paper_id,
               sum(length(text)) AS chars,
               sum(length(text) - length(regexp_replace(text, '(?i)xist', '', 'g'))) / 4 AS hits
        FROM chunks GROUP BY 1
        """
    )

    profile = conn.execute(
        """
        WITH never AS (
            SELECT paper_id, chars FROM dens WHERE hits = 0
        )
        SELECT c.topic, count(*) AS claims, count(DISTINCT c.paper_id) AS papers
        FROM claims c JOIN never n USING (paper_id)
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()

    totals = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM dens WHERE hits = 0) AS never_papers,
          (SELECT count(*) FROM claims c JOIN dens d USING (paper_id) WHERE d.hits = 0) AS never_claims,
          (SELECT count(*) FROM claims) AS all_claims
        """
    ).fetchone()

    # Which journals do the never-mention papers come from? A single-source batch
    # would say the ingestion filter let a feed through.
    journals = conn.execute(
        """
        SELECT coalesce(p.journal, '(none)') AS journal, count(*) AS papers
        FROM papers p JOIN dens d USING (paper_id)
        WHERE d.hits = 0
        GROUP BY 1 ORDER BY 2 DESC LIMIT 12
        """
    ).fetchall()

    sample = conn.execute(
        """
        SELECT c.paper_id, p.title, count(*) AS n
        FROM claims c
        JOIN dens d USING (paper_id)
        JOIN papers p USING (paper_id)
        WHERE d.hits = 0
        GROUP BY 1, 2 ORDER BY n DESC LIMIT 12
        """
    ).fetchall()

    # A no-text control: rule extraction runs on text, so never-mention papers
    # with claims must be text-based. Confirm the claims are not all rule-tagged.
    methods = conn.execute(
        """
        SELECT pv.method, count(*) AS claims
        FROM claims c JOIN dens d USING (paper_id)
        LEFT JOIN provenance pv USING (provenance_id)
        WHERE d.hits = 0 GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()

    print(
        json.dumps(
            {
                "never_mention_papers": totals[0],
                "never_mention_claims": totals[1],
                "all_claims": totals[2],
                "never_mention_claim_pct": round(100 * totals[1] / max(totals[2], 1), 2),
                "topics_in_never_mention_papers": [
                    {"topic": t, "claims": n, "papers": p} for t, n, p in profile[:15]
                ],
                "annotation_method_of_never_mention_claims": dict(methods),
                "journals_of_never_mention_papers": [
                    {"journal": j, "papers": n} for j, n in journals
                ],
                "largest_never_mention_papers": [
                    {"paper_id": pid, "title": (t or "")[:100], "claims": n} for pid, t, n in sample
                ],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
