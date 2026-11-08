"""Papers that never mention XIST anywhere in their full text.

Claim-level keyword scope fails in both directions. "ATRX, PRC2, and Repeat A RNA
form a stable ternary complex" is unambiguously a XIST claim but never says
"XIST" -- Repeat A is Xist's own motif. Meanwhile "CYTOR associates with FOSL1"
is not a XIST claim and also never says "XIST". A text scan cannot separate them.

At the paper level it can. A paper that mentions XIST once in 40,000 characters is
a passing-mention paper; its introduction's background sentences (ROS, Toll-like
receptors, radiotherapy dosimetry) were never about this knowledge base. A paper
that mentions XIST fifty times is a XIST paper, and its claims belong here even
when phrased as "Repeat A RNA".

So the unit of scope is the paper, measured from full text: occurrences of the
XIST/XCI vocabulary per 10,000 characters. Chunks already hold every paper's text
(799k windows over 13,499 papers), so this needs no PDF re-reading.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)
    rows = conn.execute(
        """
        SELECT c.paper_id,
               count(*) AS chunks,
               sum(length(c.text)) AS chars,
               sum(
                   length(c.text)
                   - length(regexp_replace(c.text, '(?i)xist', '', 'g'))
               ) / 4 AS xist_hits
        FROM chunks c
        GROUP BY 1
        """
    ).fetchall()

    densities = []
    for paper_id, chunks, chars, hits in rows:
        if not chars:
            continue
        hits = max(hits or 0, 0)
        densities.append((paper_id, chars, hits, 10000.0 * hits / chars))

    densities.sort(key=lambda r: -r[3])

    def bucket(rate: float) -> str:
        if rate >= 10:
            return "core"  # mentions XIST every 1,000 chars
        if rate >= 2:
            return "substantive"
        if rate >= 0.5:
            return "mention"
        if rate > 0:
            return "passing"
        return "never"

    counts: dict[str, int] = {}
    for _, _, _, rate in densities:
        counts[bucket(rate)] = counts.get(bucket(rate), 0) + 1

    # How many claims sit in papers that never mention XIST?
    claim_rows = conn.execute(
        "SELECT paper_id, count(*) FROM claims GROUP BY 1"
    ).fetchall()
    rate_by_paper = {pid: rate for pid, _, _, rate in densities}
    claim_bucket: dict[str, int] = {}
    papers_missing_text = 0
    for paper_id, n in claim_rows:
        rate = rate_by_paper.get(paper_id)
        if rate is None:
            papers_missing_text += 1
            key = "no_text"
        else:
            key = bucket(rate)
        claim_bucket[key] = claim_bucket.get(key, 0) + n

    total_claims = sum(claim_bucket.values())
    print(
        json.dumps(
            {
                "papers_with_text": len(densities),
                "papers_by_density": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "claims_by_paper_density": {
                    k: {"claims": v, "pct": round(100 * v / max(total_claims, 1), 2)}
                    for k, v in sorted(claim_bucket.items(), key=lambda kv: -kv[1])
                },
                "claims_total": total_claims,
                "claim_papers_with_no_text": papers_missing_text,
                "highest_density": [
                    {"paper_id": p, "chars": c, "hits": h, "per_10k": round(r, 1)}
                    for p, c, h, r in densities[:5]
                ],
                "zero_density_sample": [p for p, _, _, _ in densities[-8:]],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
