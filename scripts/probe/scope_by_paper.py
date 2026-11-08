"""How many papers in the KB are actually about XIST/XCI?

The claim-level measurement found only 18.6% of claims name XIST or XCI. Some of
that is legitimate background inside a XIST paper, but the `chromatin` topic has
17,263 claims of which 1.0% mention XIST -- and the misses are about ce-lncRNAs
in oesophageal cancer, which is a different field.

This measures the contamination at the paper level, where it can still be fixed:
a paper whose title and abstract never mention XIST, XCI, the inactive X or
dosage compensation is not in this knowledge base's scope.

Papers with no abstract and a non-matching title are counted separately as
unknown rather than out of scope: absence of text is not evidence of absence of
the subject.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")

# Spelling variants matter here: publishers write "X chromosome", "X-chromosome"
# and "Xchromosome" interchangeably, and a first version of this pattern matched
# only the hyphenated form -- which put a paper titled "X chromosome inactivation
# in mammals" out of scope and reported the whole corpus as 99.6% contamination.
SCOPE_TERMS = re.compile(
    r"("
    r"\bxist\b|"
    r"\btsix\b|\bxic\b|"
    r"\bx[\s\-]?chromosome inactivation|"
    r"\bx[\s\-]?inactivation\b|"
    r"\binactive x\b|\bx[\s\-]?inactive\b|"
    r"\bdosage compensation\b|\blyoniz(?:ation|ed|es)\b|"
    r"\bbarr body\b|"
    r"\bx[\s\-]?inactive[\s\-]specific transcript"
    r")",
    re.IGNORECASE,
)


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)
    rows = conn.execute(
        """
        SELECT p.paper_id, p.title, p.abstract, p.status, p.has_text, p.has_annotation,
               count(c.claim_id) AS claims
        FROM papers p LEFT JOIN claims c USING (paper_id)
        GROUP BY 1, 2, 3, 4, 5, 6
        """
    ).fetchall()

    total = len(rows)
    buckets = {"in_scope": [0, 0], "out_of_scope": [0, 0], "unknown": [0, 0]}
    by_claims: list[tuple[int, str, str]] = []

    for paper_id, title, abstract, status, has_text, has_annotation, claims in rows:
        claims = claims or 0
        blob = f"{title or ''} {abstract or ''}"
        if SCOPE_TERMS.search(blob):
            key = "in_scope"
        elif not (abstract or "").strip():
            key = "unknown"
        else:
            key = "out_of_scope"
        buckets[key][0] += 1
        buckets[key][1] += claims
        if key == "out_of_scope" and claims > 0:
            by_claims.append((claims, paper_id, (title or "")[:110]))

    by_claims.sort(reverse=True)
    claim_total = sum(v[1] for v in buckets.values())

    print(
        json.dumps(
            {
                "papers_total": total,
                "papers": {k: {"count": v[0], "claims": v[1]} for k, v in buckets.items()},
                "papers_pct": {
                    k: round(100 * v[0] / max(total, 1), 2) for k, v in buckets.items()
                },
                "claims_total": claim_total,
                "claims_pct": {
                    k: round(100 * v[1] / max(claim_total, 1), 2) for k, v in buckets.items()
                },
                "top_out_of_scope_papers_by_claim_count": [
                    {"claims": n, "paper_id": pid, "title": t} for n, pid, t in by_claims[:20]
                ],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
