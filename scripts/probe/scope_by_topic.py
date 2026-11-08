"""Do claims across every topic mention XIST/XCI, or only `other` claims fail to?

The `other` bucket turned out to be 99.6% background statements that never name
the topic. If the same is true elsewhere, the fix belongs at the claim level for
the whole corpus; if it is confined to `other`, the fix is narrower.

Reports, per topic: how many claims mention any XIST/XCI term. Also dumps
non-mentioning examples from the largest topics so the misses can be eyeballed
-- a claim about "the inactive X" that fails to match would mean the term list
is too narrow, not that the claim is background.
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import duckdb  # noqa: E402

DB = Path(r"C:\00_Data\实验室\实验室\MetaAnalysis\XIST_Project_V3_Plan\data_local_lowercase\index\xist.duckdb")

# Terms that mark a claim as being about this knowledge base's subject. Kept
# deliberately broad: "inactive X", "Xi", "dosage compensation" and "lyonization"
# all name the phenomenon without naming the transcript.
SCOPE_TERMS = re.compile(
    r"\b("
    r"xist|xist\b|"
    r"x-?chromosome inactivation|x-?inactivation|xci\b|"
    r"inactive x\b|\bxi\b|x\s?i\b|"
    r"dosage compensation|lyonization|lyonisation|"
    r"barr body|heterochromat\w+ x|"
    r"x inactive specific transcript"
    r")",
    re.IGNORECASE,
)


def main() -> None:
    conn = duckdb.connect(str(DB), read_only=True)
    rows = conn.execute(
        """
        SELECT c.topic, c.claim, pv.method
        FROM claims c LEFT JOIN provenance pv USING (provenance_id)
        """
    ).fetchall()

    by_topic_total: Counter = Counter()
    by_topic_mention: Counter = Counter()
    by_method_total: Counter = Counter()
    by_method_mention: Counter = Counter()
    misses: dict[str, list[str]] = defaultdict(list)

    for topic, claim, method in rows:
        topic = topic or "(null)"
        method = method or "(null)"
        text = claim or ""
        hit = bool(SCOPE_TERMS.search(text))
        by_topic_total[topic] += 1
        by_method_total[method] += 1
        if hit:
            by_topic_mention[topic] += 1
            by_method_mention[method] += 1
        elif len(misses[topic]) < 2:
            misses[topic].append(text[:120])

    total = sum(by_topic_total.values())
    mentioned = sum(by_topic_mention.values())

    per_topic = {
        topic: {
            "total": n,
            "mentions": by_topic_mention[topic],
            "pct": round(100 * by_topic_mention[topic] / n, 1),
            "no_mention_examples": misses[topic],
        }
        for topic, n in by_topic_total.most_common()
    }

    per_method = {
        m: {
            "total": n,
            "mentions": by_method_mention[m],
            "pct": round(100 * by_method_mention[m] / n, 1),
        }
        for m, n in by_method_total.most_common()
    }

    print(
        json.dumps(
            {
                "claim_total": total,
                "mentions_any_scope_term": mentioned,
                "mentions_pct": round(100 * mentioned / max(total, 1), 1),
                "no_mention_total": total - mentioned,
                "no_mention_pct": round(100 * (total - mentioned) / max(total, 1), 1),
                "per_method": per_method,
                "per_topic": per_topic,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
